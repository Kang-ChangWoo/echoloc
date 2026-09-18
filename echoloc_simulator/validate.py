#!/usr/bin/env python3
"""Stage 7 — the spec's validation checklist (section 6) + coordinate-axis proof.

Per (collection, scene):
  1  len(rgb) == len(poses) == len(depth40) == len(depth160)
  2  len(poses) % (L+1) == 0
  3  rgb filename sort order == pose row order (chunk/view numbering is dense)
  5  map.png free space is exactly 255, 3 identical channels, binary
  6  depth values finite, positive, <= dist_max
  9  depth160 vs an independent fine-step ray march on the map: p99 < 1.6 cm, never shorter
  A  AXIS CHECK (the spec's check 8, made numeric): the floor-plan proxy rendered
     with the real pinhole camera at the pose, horizon row z-depth per column, vs the
     exact ray cast (raycast.py) on map.png at the same pose and column angles. The proxy is the
     extruded map, so any sign/axis/F_W/forward-vs-radial error shows up here as
     tens of cm; agreement is expected within ~1 map pixel + edge effects.
  8  figure: rays overlaid on map.png + the rgb frame, for a few frames per scene
  D  depth maps: depth_radial_scan/ and depth_radial_floorplan/ complete (one 16-bit 480x640
     PNG per frame, names == rgb/), floorplan horizon RADIAL value == map ray range
     (no cos factor; a planar/z map would fail at the image edges by ~30%), scan <= floorplan
     except where the scan wall sits beyond the 5 cm mask (reported, not failed).
     Full-scene survey (every frame): floorplan maps must have NO zero pixels (the proxy
     is watertight and the map sealed). Scan no-hit (Replica voids / missing ceilings)
     is reported only and must match chunks.json 'scan_nohit_lower'.
Per collection:
  4  split disjoint, all scenes present
  7  desdf for every test scene, (H, W, 36) float32, l/t ints
 10  rir/pose_<index> resolves to a row of poses.txt (if rir/ exists)

Usage:  python validate.py [--collections replica_f replica_g] [--scenes ...] [--figs 3]
Exit code 1 if any hard check fails.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

import common as C

FAIL = []
RING_ONLY = False    # set by --ring-only: a release that ships no binaural RIRs at all


def check(cond, msg):
    if not cond:
        FAIL.append(msg)
        print("  FAIL", msg, flush=True)
    return cond


def center_angs(ray_n):
    u = np.arange(ray_n)
    return np.flip(np.arctan2(u - u.mean(), ray_n * C.F_W))


def march(occ, pos_rc, ang, dist_max_px, step=0.05):
    """Independent fine-step ray march (pixels) — NOT F3Loc's DDA."""
    H, W = occ.shape
    r0, c0 = pos_rc
    s, c = np.sin(ang), np.cos(ang)
    t = 0.0
    while t < dist_max_px:
        t += step
        r, cc = r0 + t * s, c0 + t * c
        if r < 0 or cc < 0 or r >= H or cc >= W:
            return dist_max_px
        if occ[int(r), int(cc)] != 255:
            return t
    return dist_max_px


def axis_check(collection, scene, occ, poses, n_max=40):
    """Proxy render horizon z-depth vs map ray cast at the pinhole column angles."""
    C.f3loc_import()
    from raycast import ray_cast   # exact DDA; see raycast.py (F3Loc original leaks at wall corners)
    vd = os.path.join(C.VAL_DIR, collection, scene, "depth_plan")
    files = sorted(glob.glob(os.path.join(vd, "*.npy")))[:n_max]
    if not files:
        print("  (no proxy depth frames -> axis check skipped)")
        return None
    H, W = occ.shape
    cols = np.arange(0, C.IMG_W, 8) + 0.5                       # sampled image columns
    angs = np.arctan2((C.IMG_W / 2) - cols, C.FX)               # +left = CCW
    errs = []
    for f in files:
        i = int(os.path.basename(f)[:5])
        x, y, yaw = poses[i]
        d = np.load(f)
        horizon = 0.5 * (d[C.IMG_H // 2 - 1] + d[C.IMG_H // 2])   # rows 239/240 -> cy = 240
        pos = np.array(C.world_to_map(x, y, occ.shape))
        for cidx, a in zip(cols.astype(int), angs):
            hit = ray_cast(occ, pos.copy(), float(C.wrap(yaw + a)), dist_max=C.DIST_MAX_M / C.MAP_RES)
            zmap = hit * C.MAP_RES * np.cos(a)
            zr = float(horizon[cidx])
            if zmap >= C.DIST_MAX_M * 0.99 or zr <= 0 or zr > 19:   # escaped / invalid
                continue
            errs.append(zr - zmap)
    errs = np.array(errs)
    med, mae, p90 = np.median(np.abs(errs)), np.abs(errs).mean(), np.percentile(np.abs(errs), 90)
    print(f"  axis check: {len(files)} frames, {len(errs)} rays  |render - raycast|  "
          f"median {med*100:.1f} cm  mean {mae*100:.1f} cm  p90 {p90*100:.1f} cm  bias {errs.mean()*100:+.1f} cm")
    check(med < 0.05 and mae < 0.15, f"{collection}/{scene}: axis check median {med:.3f} m mean {mae:.3f} m")
    return errs


def figure(collection, scene, occ, poses, idx, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    C.f3loc_import()
    from raycast import ray_cast   # exact DDA; see raycast.py (F3Loc original leaks at wall corners)
    sd = C.scene_dir(collection, scene)
    k, v = idx // (C.L + 1), idx % (C.L + 1)
    x, y, yaw = poses[idx]
    pos = np.array(C.world_to_map(x, y, occ.shape))
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.5))
    ax[0].imshow(occ, cmap="gray", origin="lower")
    for a in center_angs(40):
        d = ray_cast(occ, pos.copy(), float(C.wrap(yaw + a)), dist_max=C.DIST_MAX_M / C.MAP_RES)
        ax[0].plot([pos[1], pos[1] + d * np.cos(yaw + a)], [pos[0], pos[0] + d * np.sin(yaw + a)],
                   color="tab:red", lw=0.6, alpha=0.8)
    ax[0].plot(pos[1], pos[0], "o", color="tab:blue", ms=5)
    ax[0].arrow(pos[1], pos[0], 40 * np.cos(yaw), 40 * np.sin(yaw), color="tab:blue", width=3)
    ax[0].set_title(f"{scene} frame {idx} (chunk {k}, view {v})  yaw {np.degrees(yaw):.0f} deg")
    ax[0].set_xlim(max(0, pos[1] - 500), min(occ.shape[1], pos[1] + 500))
    ax[0].set_ylim(max(0, pos[0] - 500), min(occ.shape[0], pos[0] + 500))
    ax[1].imshow(Image.open(os.path.join(sd, "rgb", C.frame_png(idx))))
    ax[1].set_title("rgb (left of image = CCW = +angle)")
    ax[1].axis("off")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def _zero_frac(f):
    from PIL import Image
    return float((np.array(Image.open(f)) == 0).mean())


def _zero_frac_lower(f):
    from PIL import Image
    return float((np.array(Image.open(f))[120:] == 0).mean())


def zero_survey(collection, scene):
    """Every frame of both depth-map dirs: no-hit pixel fraction.
    Floorplan maps must have none (watertight proxy, sealed map). Scan no-hit is a
    property of the Replica scans (unscanned voids, missing ceilings) and is REPORTED
    only: every pose is kept and chunks.json carries 'scan_nohit_lower' per frame
    (no-hit fraction below row 120) for downstream filtering; it must agree with the
    stored depth_radial_scan maps."""
    from multiprocessing import Pool
    sd = C.scene_dir(collection, scene)
    out = {}
    with Pool(12) as pool:
        for d in ("depth_radial_scan", "depth_radial_floorplan"):
            files = sorted(glob.glob(os.path.join(sd, d, "*.png")))
            out[d] = np.array(pool.map(_zero_frac, files, chunksize=64)) if files else np.zeros(0)
        files = sorted(glob.glob(os.path.join(sd, "depth_radial_scan", "*.png")))
        low = np.array(pool.map(_zero_frac_lower, files, chunksize=64)) if files else np.zeros(0)
    sc, pl = out["depth_radial_scan"], out["depth_radial_floorplan"]
    if not len(sc):
        sc = pl
    if len(sc) and len(pl):
        print(f"  zero survey ({len(sc)} frames): floorplan no-hit mean {pl.mean():.2%}, frames with any {(pl > 0).sum()}; "
              f"scan no-hit mean {sc.mean():.1%}, frames >50% {(sc > 0.5).sum()} (report only)")
        check((pl > 0).sum() == 0, f"{scene}: {(pl > 0).sum()} frames with no-hit floorplan pixels (map not sealed)")
    if len(low) and "real" in C.GEOMS:
        print(f"  scan voids (report): frames with >15% no-hit below row 120: {(low > 0.15).sum()} ({(low > 0.15).mean():.1%}), max {low.max():.1%}")
        ch = C.read_chunks(collection, scene)
        rec = [fr.get("scan_nohit_lower") for c in ch["chunks"] for fr in c["frames"]]
        if check(all(r is not None for r in rec) and len(rec) == len(low), f"{scene}: chunks.json lacks per-frame scan_nohit_lower"):
            check(np.abs(np.array(rec, dtype=float) - low).max() < 0.02,
                  f"{scene}: chunks.json scan_nohit_lower disagrees with depth_radial_scan (max diff {np.abs(np.array(rec, dtype=float) - low).max():.3f})")


def depthmap_check(collection, scene, occ, poses, n_frames=12):
    from PIL import Image
    from raycast import ray_cast
    sd = C.scene_dir(collection, scene)
    n = len(poses)
    expected = [C.frame_png(i) for i in range(n)]
    have = {}
    dirs = ("depth_radial_floorplan",) if "real" not in C.GEOMS else ("depth_radial_scan", "depth_radial_floorplan")
    for d in dirs:
        files = sorted(os.listdir(os.path.join(sd, d))) if os.path.isdir(os.path.join(sd, d)) else []
        have[d] = files == expected
        check(have[d], f"{scene}: {d} has {len(files)} files, expected {n} named like rgb/")
    if not all(have.values()):
        return
    rng = np.random.RandomState(2)
    cols = np.arange(0, C.IMG_W, 8) + 0.5
    angs = np.arctan2((C.IMG_W / 2) - cols, C.FX)
    errs, over, zeros_s, zeros_p, fmt_ok = [], [], 0, 0, True
    for i in rng.choice(n, size=min(n_frames, n), replace=False):
        ims = {}
        for d in dirs:
            im = Image.open(os.path.join(sd, d, C.frame_png(int(i))))
            a = np.array(im)
            fmt_ok &= (im.mode in ("I;16", "I") and a.shape == (C.IMG_H, C.IMG_W) and a.dtype in (np.uint16, np.int32))
            ims[d] = a.astype(np.float32) / 1000.0
        pl = ims["depth_radial_floorplan"]; sc = ims.get("depth_radial_scan", pl)
        zeros_s += int((sc == 0).sum()); zeros_p += int((pl == 0).sum())
        x, y, yaw = poses[i]
        pos = np.array(C.world_to_map(x, y, occ.shape))
        hp = 0.5 * (pl[C.IMG_H // 2 - 1] + pl[C.IMG_H // 2])
        for cidx, a in zip(cols.astype(int), angs):
            rr = ray_cast(occ, pos.copy(), float(C.wrap(yaw + a)), dist_max=C.DIST_MAX_M / C.MAP_RES) * C.MAP_RES
            if rr < C.DIST_MAX_M * 0.99 and hp[cidx] > 0:
                errs.append(hp[cidx] - rr)          # radial png vs radial map range: no cos
        m = (sc > 0) & (pl > 0)
        over.append(float(((sc - pl) > 0.10)[m].mean()))
    errs = np.array(errs)
    med, mae = np.median(np.abs(errs)), np.abs(errs).mean()
    print(f"  depth maps: {min(n_frames, n)} frames  floorplan-radial vs map range |diff| median {med*100:.2f} cm mean {mae*100:.2f} cm; "
          f"scan > floorplan+10cm on {np.mean(over):.1%} px; zero px scan {zeros_s} / floorplan {zeros_p}; 16-bit 480x640: {fmt_ok}")
    check(fmt_ok, f"{scene}: depth map format not 16-bit 480x640")
    check(med < 0.01 and mae < 0.03, f"{scene}: depth_radial_floorplan vs map range median {med:.3f} m mean {mae:.3f} m (planar instead of radial?)")
    check(zeros_p == 0, f"{scene}: floorplan depth has {zeros_p} zero pixels (watertight proxy should always hit)")


def validate_scene(collection, scene, n_figs):
    print(f"[{collection}/{scene}]", flush=True)
    sd = C.scene_dir(collection, scene)
    from PIL import Image
    m = np.array(Image.open(os.path.join(sd, "map.png")))
    check(m.ndim == 3 and m.shape[2] == 3 and np.array_equal(m[..., 0], m[..., 1]) and np.array_equal(m[..., 0], m[..., 2]),
          f"{scene}: map.png must have 3 identical channels")
    occ = m[..., 0]
    check(set(np.unique(occ).tolist()) <= {0, 255} and (occ == 255).any(), f"{scene}: map not binary {np.unique(occ)[:5]}")

    poses = np.loadtxt(os.path.join(sd, "poses.txt"), ndmin=2)
    if poses.size == 0 or poses.shape[1] != 3:
        check(False, f"{scene}: poses.txt is empty or not 3 columns (shape {poses.shape})")
        return
    n = len(poses)
    check(n % (C.L + 1) == 0, f"{scene}: len(poses)={n} not a multiple of {C.L + 1}")
    rgbs = sorted(glob.glob(os.path.join(sd, "rgb", "*.png")))
    check(len(rgbs) == n, f"{scene}: {len(rgbs)} rgb vs {n} poses")
    expected = [C.frame_png(i) for i in range(n)]
    check([os.path.basename(p) for p in rgbs] == expected, f"{scene}: rgb filenames not dense/ordered")
    check(np.all(np.abs(poses[:, 2]) <= np.pi), f"{scene}: yaw outside [-pi, pi]")

    # poses on free pixels
    rc = np.array([C.world_to_map(x, y, occ.shape) for x, y, _ in poses]).astype(int)
    onfree = occ[rc[:, 0], rc[:, 1]] == 255
    check(onfree.all(), f"{scene}: {(~onfree).sum()} poses on non-free pixels")

    depths = {}
    for k in (40, 160):
        p = os.path.join(sd, f"depth{k}.txt")
        if not os.path.exists(p):
            print(f"  (depth{k}.txt missing)")
            continue
        d = np.loadtxt(p, ndmin=2)
        depths[k] = d
        check(d.shape == (n, k), f"{scene}: depth{k} shape {d.shape} != ({n}, {k})")
        check(np.isfinite(d).all() and (d > 0).all() and (d <= C.DIST_MAX_M + 1e-6).all(),
              f"{scene}: depth{k} has non-finite / non-positive / > dist_max values")
    if 160 in depths:
        # Independent sampling march vs depth160. The march (0.05 px steps) can skip a
        # pixel the ray only clips at a corner, so it is occasionally LONGER; a
        # forward-vs-radial mix-up would be ~10% at the FOV edge on every ray.
        rng = np.random.RandomState(0)
        angs = center_angs(160)
        diffs = []
        for i in rng.choice(n, size=min(30, n), replace=False):
            x, y, yaw = poses[i]
            pos = C.world_to_map(x, y, occ.shape)
            for j in rng.choice(160, size=10, replace=False):
                ind = march(occ, pos, yaw + angs[j], C.DIST_MAX_M / C.MAP_RES) * C.MAP_RES * np.cos(angs[j])
                if ind < C.DIST_MAX_M * 0.98:
                    diffs.append(ind - depths[160][i, j])
        diffs = np.array(diffs)
        p50, p99, mx = np.percentile(np.abs(diffs), [50, 99, 100])
        print(f"  check 9: |depth160 - independent march| p50 {p50*100:.2f} cm  p99 {p99*100:.2f} cm  max {mx*100:.1f} cm  "
              f"(march shorter than GT: {(diffs < -0.0006).sum()} rays)")
        check(p99 < 0.016 and (diffs < -0.0006).sum() == 0,
              f"{scene}: depth160 vs independent march p99 {p99:.3f} m / march shorter on {(diffs < -0.0006).sum()} rays")

    axis_check(collection, scene, occ, poses)
    depthmap_check(collection, scene, occ, poses)
    zero_survey(collection, scene)

    if n_figs and rgbs:
        fd = os.path.join(C.VAL_DIR, collection, scene, "figs")
        os.makedirs(fd, exist_ok=True)
        for idx in np.linspace(0, n - 1, n_figs).astype(int):
            figure(collection, scene, occ, poses, int(idx), os.path.join(fd, f"frame_{idx:05d}.png"))
        print(f"  figures -> {fd}")


def validate_collection(collection, scenes, n_figs):
    import yaml
    split = yaml.safe_load(open(os.path.join(C.ROOT, collection, "split.yaml")))
    tr, va, te = map(set, (split["train"], split["val"], split["test"]))
    check(not (tr & va) and not (tr & te) and not (va & te), f"{collection}: split not disjoint")
    for s in tr | va | te:
        check(os.path.isdir(C.scene_dir(collection, s)), f"{collection}: scene dir missing {s}")
    for s in scenes:
        if os.path.exists(os.path.join(C.scene_dir(collection, s), "poses.txt")):
            validate_scene(collection, s, n_figs)
        else:
            print(f"[{collection}/{s}] no poses.txt yet")
    for s in te:
        p = os.path.join(C.ROOT, "desdf", s, "desdf.npy")
        if os.path.exists(p):
            d = np.load(p, allow_pickle=True).item()
            check(isinstance(d["l"], (int, np.integer)) and isinstance(d["t"], (int, np.integer)), f"desdf {s}: l/t not int")
            check(d["desdf"].ndim == 3 and d["desdf"].shape[2] == 36 and d["desdf"].dtype == np.float32,
                  f"desdf {s}: shape/dtype {d['desdf'].shape} {d['desdf'].dtype}")
            print(f"[desdf/{s}] {d['desdf'].shape} {d['desdf'].dtype} l={d['l']} t={d['t']}")
        else:
            print(f"[desdf/{s}] missing (needed for test scenes)")
    rir_root = os.path.join(C.ROOT, "rir", collection)
    if os.path.isdir(rir_root):
        for cond in sorted(os.listdir(rir_root)):
            for s in scenes:
                sdir = os.path.join(rir_root, cond, s)
                if not os.path.isdir(sdir):
                    continue
                poses = np.loadtxt(os.path.join(C.scene_dir(collection, s), "poses.txt"), ndmin=2)
                bad = 0
                pdirs = sorted(glob.glob(os.path.join(sdir, "pose_*")))
                for pd in pdirs[:50]:
                    i = int(os.path.basename(pd)[5:])
                    meta = json.load(open(os.path.join(pd, "rir_metadata.json")))
                    if i >= len(poses) or not np.allclose(meta["f3loc_pose_m_rad"], poses[i], atol=1e-9):
                        bad += 1
                check(bad == 0, f"rir {cond}/{s}: {bad} pose_<index> rows disagree with poses.txt")
                names = [("rir.npy" if r == 0 else f"rir_rel{r:03d}.npy") for r in C.RING_HEADINGS_DEG]
                bnames = [("rir_binaural.npy" if r == 0 else f"rir_binaural_rel{r:03d}.npy") for r in C.REL_HEADINGS_DEG]
                nr = sum(all(os.path.exists(os.path.join(pd, f)) for f in names) for pd in pdirs)
                nb = sum(all(os.path.exists(os.path.join(pd, f)) for f in bnames) for pd in pdirs)
                # A release may ship the ring only (gibson, 2026-09-16). Requiring binaural
                # then buries the real failures under one per scene per condition, so a
                # dataset with no binaural at all is reported, not failed. A dataset that has
                # binaural for *some* poses is still a failure -- that is a partial render.
                want_binaural = nb > 0 or not RING_ONLY
                check(nr == len(pdirs) and (nb == len(pdirs) or not want_binaural),
                      f"rir {cond}/{s}: ring {nr} / binaural {nb} of {len(pdirs)} poses complete (all headings)")
                print(f"[rir/{collection}/{cond}/{s}] {len(pdirs)} poses, ring {nr}, binaural {nb} (x{len(C.REL_HEADINGS_DEG)} headings; ring x{len(C.RING_HEADINGS_DEG)}), index check ok")


def main():
    global RING_ONLY
    ap = argparse.ArgumentParser()
    ap.add_argument("--collections", nargs="+", default=list(C.COLLECTIONS))
    ap.add_argument("--scenes", nargs="+", default=C.SCENES)
    ap.add_argument("--figs", type=int, default=3)
    ap.add_argument("--ring-only", action="store_true",
                    help="the release ships ring RIRs only; report missing binaural instead of failing")
    a = ap.parse_args()
    RING_ONLY = a.ring_only
    for col in a.collections:
        validate_collection(col, a.scenes, a.figs)
    print("\nRESULT:", "OK" if not FAIL else f"{len(FAIL)} FAILURES")
    for f in FAIL:
        print(" -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
