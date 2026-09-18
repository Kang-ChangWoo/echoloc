#!/usr/bin/env python3
"""Build echoloc/samples/: one small scene per dataset so the repository shows every file
the pipeline produces, without shipping the data.

What goes in is decided by licence, not by size:

  replica   Replica Dataset Research License permits redistribution for non-commercial
            research -> a full sample: rendered rgb, both depth maps, ring + binaural RIRs.
  mp3d      Matterport terms forbid redistribution of the data or renders of it -> only the
            artifacts that are abstractions we computed (wall map, proxy, poses, ray-cast depth
            rows, RIR on the *proxy*, desdf). No rgb, no scan-mesh depth, no raw files.
  gibson    Same terms (Stanford licence form) -> same treatment as mp3d.
  s3d       Structured3D is research-only and non-redistributable; its rgb/depth are the
            dataset's own renders -> map/proxy/poses/depth rows/proxy RIR/desdf only.
  zind      Zillow terms -> nothing but a file listing.

Row-based files are cut to the first N_ROWS rows (2 chunks) and chunks.json to its first two
chunks; the header of every truncated file says so.

    python make_samples.py            (from echoloc_simulator/, any profile)
"""
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "echoloc_dataset")
OUT = os.path.join(REPO, "samples")
N_ROWS = 8                       # 2 chunks x 4 views

PICK = {   # dataset -> (scene, collection, test scene for desdf, rir pose index, full?)
    "replica": ("office_4", "replica_f", 3, True),
    "mp3d":    ("pLe4wQe7qrG_f0", "mp3d_f", 3, False),
    "gibson":  ("Crookston_f1", "gibson_f", 3, False),
    "s3d":     ("scene_03260", "s3d", 0, False),
}
RAW = {
    "replica": "/mnt/sdb/replica_raw/office_4",
    "mp3d": "/mnt/sdb/mp3d_raw/pLe4wQe7qrG",
    "gibson": "/mnt/sdb/gibson_raw/gibson",
    "s3d": "/mnt/sdb/s3d_raw/Structured3D/scene_03260",
    "zind": "/mnt/sdb/zind_raw/0000",
}


def cp(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def head(src, dst, n=N_ROWS):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src) as f, open(dst, "w") as g:
        g.write(f"# sample: first {n} rows of {os.path.relpath(src, DATA)}\n")
        for i, line in enumerate(f):
            if i >= n:
                break
            g.write(line)


def listing(root, dst, depth=2, limit=60):
    """`find`-style listing with sizes: shows the raw layout without shipping the data."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    out = subprocess.run(["find", root, "-maxdepth", str(depth), "-printf", "%10s  %p\n"],
                         capture_output=True, text=True).stdout.splitlines()
    with open(dst, "w") as g:
        g.write(f"# {root}  ({len(out)} entries, first {limit}; bytes  path)\n")
        g.write("\n".join(sorted(out)[:limit]) + "\n")


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for ds, (scene, col, pidx, full) in PICK.items():
        D = os.path.join(DATA, ds)
        O = os.path.join(OUT, ds, "generated")
        L = 0 if ds == "s3d" else 3
        # maps (+ semantic where it exists)
        for f in ("map.png", "scene_meta.json", "semantic_map.png", "semantic_legend.json"):
            p = os.path.join(D, "maps", scene, f)
            if os.path.exists(p):
                cp(p, os.path.join(O, "maps", scene, f))
        # proxy
        for f in os.listdir(os.path.join(D, "floorplan_proxy", scene)):
            cp(os.path.join(D, "floorplan_proxy", scene, f), os.path.join(O, "floorplan_proxy", scene, f))
        # collection: rows, chunks, frames
        S = os.path.join(D, col, scene)
        for f in ("poses.txt", "depth40.txt", "depth160.txt"):
            head(os.path.join(S, f), os.path.join(O, col, scene, f))
        cp(os.path.join(D, col, "split.yaml"), os.path.join(O, col, "split.yaml"))
        ch = json.load(open(os.path.join(S, "chunks.json")))
        ch["_sample"] = f"first 2 of {ch['n_chunks']} chunks"
        ch["chunks"] = ch["chunks"][:2]
        os.makedirs(os.path.join(O, col, scene), exist_ok=True)
        json.dump(ch, open(os.path.join(O, col, scene, "chunks.json"), "w"), indent=1)
        cp(os.path.join(S, "map.png"), os.path.join(O, col, scene, "map.png"))
        frames = [f"00000-{v}.png" for v in range(L + 1)] if L else ["00000.png"]
        ref = frames[-1]
        if full:
            for f in frames:
                cp(os.path.join(S, "rgb", f), os.path.join(O, col, scene, "rgb", f))
            cp(os.path.join(S, "depth_radial_scan", ref), os.path.join(O, col, scene, "depth_radial_scan", ref))
        cp(os.path.join(S, "depth_radial_floorplan", ref), os.path.join(O, col, scene, "depth_radial_floorplan", ref))
        # rir: proxy condition always; scan condition and binaural only where redistributable
        conds = ["floorplan_closed"] + (["raw_scan_open"] if full and ds != "s3d" else [])
        for cond in conds:
            pd = os.path.join(D, "rir", col, cond, scene, f"pose_{pidx:05d}")
            for f in os.listdir(pd):
                if "binaural" in f and not full:
                    continue
                cp(os.path.join(pd, f), os.path.join(O, "rir", col, cond, scene, f"pose_{pidx:05d}", f))
        # desdf (all picked scenes are test scenes)
        cp(os.path.join(D, "desdf", scene, "desdf.npy"), os.path.join(O, "desdf", scene, "desdf.npy"))
        cp(os.path.join(D, "dataset_meta.json"), os.path.join(O, "dataset_meta.json"))
        # raw
        R = os.path.join(OUT, ds, "raw")
        if ds == "replica":
            cp(os.path.join(RAW[ds], "habitat", "info_semantic.json"), os.path.join(R, "office_4", "habitat", "info_semantic.json"))
            cp("/mnt/sdb/replica_raw/replica.scene_dataset_config.json", os.path.join(R, "replica.scene_dataset_config.json"))
            listing(RAW[ds], os.path.join(R, "LISTING.txt"), depth=2)
        elif ds == "gibson":
            listing(RAW[ds], os.path.join(R, "LISTING.txt"), depth=1, limit=12)
        else:
            listing(RAW[ds], os.path.join(R, "LISTING.txt"), depth=2)
    listing(RAW["zind"], os.path.join(OUT, "zind", "raw", "LISTING.txt"), depth=2, limit=40)
    # size report
    tot = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(OUT) for f in fs)
    n = sum(len(fs) for _, _, fs in os.walk(OUT))
    print(f"samples/: {n} files, {tot/1e6:.1f} MB")


if __name__ == "__main__":
    main()
