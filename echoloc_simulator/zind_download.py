#!/usr/bin/env python3
"""Download the Zillow Indoor Dataset (ZInD) via the Bridge Data Output API.

Produces the same on-disk layout as zillow/zind's own download_data.py:

    <out>/<home_id>/zind_data.json
    <out>/<home_id>/panos/<floor>_<partial_room>_<pano>.jpg
    <out>/<home_id>/floor_plans/<floor>.png

with image_path rewritten to those relative paths, so downstream code written
against the official release works unchanged.

Two things the official script does not handle, and the reason this exists:

  * The replication endpoint 408s after ~30 s if you ask for the whole dataset
    in one request (which download_data.py does). Metadata is paged here with
    $top and the @odata.nextLink cursor.
  * Everything resumes. Metadata pages already on disk are reused, and an image
    whose md5 already matches is never refetched, so an interrupted run costs
    only the page it died on.

The server token is read from $ZIND_SERVER_TOKEN -- never pass it on the command
line and never write it into a file; this directory is mirrored to the NAS.

    ZIND_SERVER_TOKEN=... python zind_download.py --out /mnt/sdb/zind_raw
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://api.bridgedataoutput.com/api/v2/OData/zgindoor/Indoor/replication"
PAGE = 50            # 100+ starts hitting the same server-side timeout
RETRIES = 6
WAF_BACKOFF = 120    # seconds to stand down after a CloudFront WAF challenge
PACE = 0.15          # per-worker gap between image requests; 16 workers flat out trips the WAF
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
KEEP_KEYS = ("merger", "redraw", "scale_meters_per_coordinate",
             "floorplan_to_redraw_transformation")


def fetch_json(url, token, timeout=180):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return json.load(f)
        except Exception as e:
            if attempt == RETRIES:
                raise
            wait = 5 * attempt
            print(f"  [meta] {type(e).__name__}: {e} -- retry {attempt} in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)


def metadata_pages(out, token):
    """Yield every home record, caching each page under <out>/_pages/."""
    cache = os.path.join(out, "_pages")
    os.makedirs(cache, exist_ok=True)
    url, page = f"{API}?$top={PAGE}", 0
    while url:
        path = os.path.join(cache, f"page_{page:04d}.json")
        if os.path.exists(path):
            try:
                d = json.load(open(path))
            except json.JSONDecodeError:
                d = None
        else:
            d = None
        if d is None:
            d = fetch_json(url, token)
            with open(path, "w") as f:
                json.dump(d, f)
        yield page, d.get("value", [])
        url = d.get("@odata.nextLink")
        page += 1


def md5(path, block=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def plan_house(rec, out):
    """Write zind_data.json and return [(url, dest, checksum)] for its images."""
    home = rec["home_id"]
    hp = os.path.join(out, home)
    os.makedirs(os.path.join(hp, "panos"), exist_ok=True)
    os.makedirs(os.path.join(hp, "floor_plans"), exist_ok=True)
    local = json.loads(json.dumps(rec))          # rewrite paths on a copy
    todo = []

    for fl, rooms in rec.get("merger", {}).items():
        for cr, parts in rooms.items():
            for pr, panos in parts.items():
                for pn, det in panos.items():
                    name = f"{fl}_{pr}_{pn}.jpg"
                    todo.append((det["image_path"],
                                 os.path.join(hp, "panos", name),
                                 det.get("checksum")))
                    local["merger"][fl][cr][pr][pn]["image_path"] = f"panos/{name}"

    for fl, det in (rec.get("floorplan_to_redraw_transformation") or {}).items():
        rel = os.path.join("floor_plans", f"{fl}.png")
        todo.append((det["image_path"], os.path.join(hp, rel), det.get("checksum")))
        local["floorplan_to_redraw_transformation"][fl]["image_path"] = rel

    with open(os.path.join(hp, "zind_data.json"), "w") as f:
        json.dump({k: v for k, v in local.items() if k in KEEP_KEYS}, f)
    return todo


_lock = threading.Lock()
_waf_until = 0.0


def _waf_pause(seconds):
    """CloudFront fronts the images with AWS WAF. Too many parallel requests and it
    answers 202 with an empty body (x-amzn-waf-action: challenge) for *every* request
    from this IP, for minutes. Back the whole pool off, not just the one worker."""
    global _waf_until
    with _lock:
        _waf_until = max(_waf_until, time.time() + seconds)


def _wait_for_waf():
    while True:
        with _lock:
            delay = _waf_until - time.time()
        if delay <= 0:
            return
        time.sleep(min(delay, 10))


def download(job):
    url, dest, checksum = job
    if os.path.exists(dest) and (checksum is None or md5(dest) == checksum):
        return "skip"
    for attempt in range(1, RETRIES + 1):
        _wait_for_waf()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60 * attempt) as r:
                # a WAF challenge is a 202 with no body, not an error status
                if r.status == 202 or r.headers.get("x-amzn-waf-action"):
                    _waf_pause(WAF_BACKOFF * attempt)
                    continue
                with open(dest + ".part", "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
            if os.path.getsize(dest + ".part") == 0:
                os.remove(dest + ".part")
                _waf_pause(WAF_BACKOFF * attempt)
                continue
            if checksum and md5(dest + ".part") != checksum:
                os.remove(dest + ".part")
                continue
            os.replace(dest + ".part", dest)
            time.sleep(PACE)
            return "ok"
        except Exception:
            if os.path.exists(dest + ".part"):
                os.remove(dest + ".part")
            time.sleep(3 * attempt)
    print(f"  [img] FAILED {url}", file=sys.stderr)
    return "fail"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/mnt/sdb/zind_raw")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    token = os.environ.get("ZIND_SERVER_TOKEN")
    if not token:
        sys.exit("set ZIND_SERVER_TOKEN (Bridge 'Server Token')")
    os.makedirs(a.out, exist_ok=True)

    homes = ok = skip = fail = 0
    t0 = time.time()
    for page, records in metadata_pages(a.out, token):
        jobs = []
        for rec in records:
            homes += 1
            jobs += plan_house(rec, a.out)
        with ThreadPoolExecutor(a.workers) as ex:
            for r in ex.map(download, jobs):
                ok += r == "ok"
                skip += r == "skip"
                fail += r == "fail"
        print(f"[zind] page {page:>3}  homes {homes:>5}  images ok {ok} skip {skip} "
              f"fail {fail}  {(time.time()-t0)/60:.1f} min", flush=True)

    print(f"[zind] DONE homes {homes}  downloaded {ok}  already had {skip}  failed {fail}"
          f"  {(time.time()-t0)/60:.1f} min")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
