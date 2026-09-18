#!/usr/bin/env python
"""QC for the rgb and depthmaps stages: completeness over every scene, plus a
sampled content check.

Completeness is exhaustive -- one missing frame breaks the poses.txt row
alignment that everything downstream assumes. Content is sampled, because
opening half a million PNGs costs more than it tells us.

  ECHOLOC_DATASET=gibson python qc_render.py --collections gibson_f gibson_g
"""
import argparse
import os
import random

import numpy as np
from PIL import Image

import common as C


def n_poses(col, scene):
    p = os.path.join(C.ROOT, col, scene, "poses.txt")
    return len(np.atleast_2d(np.loadtxt(p))) if os.path.exists(p) else 0


def check(col, sample, rng):
    scenes = sorted(d for d in os.listdir(os.path.join(C.ROOT, col))
                    if os.path.isdir(os.path.join(C.ROOT, col, d)))
    dirs = {"rgb": ".png", "depth_radial_scan": ".png", "depth_radial_floorplan": ".png"}
    missing = {k: [] for k in dirs}
    totals = {k: 0 for k in dirs}
    expected = 0

    for sc in scenes:
        want = n_poses(col, sc)
        expected += want
        for d in dirs:
            p = os.path.join(C.ROOT, col, sc, d)
            got = len(os.listdir(p)) if os.path.isdir(p) else 0
            totals[d] += got
            if got != want:
                missing[d].append((sc, got, want))

    print(f"\n=== {col}: {len(scenes)} scenes, {expected} poses ===")
    for d in dirs:
        bad = missing[d]
        print(f"  {d:24s} {totals[d]:7d} files   incomplete scenes: {len(bad)}"
              + (f"   e.g. {bad[:3]}" if bad else ""))

    # ---- sampled content ----
    # only sample scenes whose rgb is complete; the depth dirs are optional so the
    # script is useful while the depthmaps stage is still running
    ok = [sc for sc in scenes if n_poses(col, sc) > 0
          and os.path.isdir(os.path.join(C.ROOT, col, sc, "rgb"))
          and len(os.listdir(os.path.join(C.ROOT, col, sc, "rgb"))) == n_poses(col, sc)]
    if not ok:
        print("  (no complete scene to sample yet)")
        return
    picked = rng.sample(ok, min(sample, len(ok)))
    shape = (C.IMG_H, C.IMG_W)
    stats = {"rgb_wrong_size": 0, "rgb_black": 0, "n_rgb": 0,
             "fp_wrong_size": 0, "fp_nohit_px": 0, "fp_frames_with_nohit": 0,
             "n_fp": 0, "scan_nohit_frac": [], "fp_range_m": []}

    for sc in picked:
        files = sorted(os.listdir(os.path.join(C.ROOT, col, sc, "rgb")))
        for f in rng.sample(files, min(8, len(files))):
            a = np.array(Image.open(os.path.join(C.ROOT, col, sc, "rgb", f)))
            stats["n_rgb"] += 1
            if a.shape[:2] != shape:
                stats["rgb_wrong_size"] += 1
            if a.mean() < 3:
                stats["rgb_black"] += 1

            stem = os.path.splitext(f)[0] + ".png"
            fp = os.path.join(C.ROOT, col, sc, "depth_radial_floorplan", stem)
            sn = os.path.join(C.ROOT, col, sc, "depth_radial_scan", stem)
            if os.path.exists(fp):
                d = np.array(Image.open(fp))
                stats["n_fp"] += 1
                if d.shape != shape:
                    stats["fp_wrong_size"] += 1
                nz = int((d == 0).sum())
                # the floorplan proxy is watertight: every pixel must hit something
                if nz:
                    stats["fp_frames_with_nohit"] += 1
                    stats["fp_nohit_px"] += nz
                v = d[d > 0]
                if v.size:
                    stats["fp_range_m"].append((v.min() / 1000.0, v.max() / 1000.0))
            if os.path.exists(sn):
                d = np.array(Image.open(sn))
                stats["scan_nohit_frac"].append(float((d == 0).mean()))

    print(f"  sampled {len(picked)} scenes / {stats['n_rgb']} frames")
    print(f"    rgb:       wrong size {stats['rgb_wrong_size']}, near-black {stats['rgb_black']}")
    print(f"    floorplan: wrong size {stats['fp_wrong_size']}, "
          f"frames with no-hit pixels {stats['fp_frames_with_nohit']}/{stats['n_fp']} "
          f"({stats['fp_nohit_px']} px)")
    if stats["fp_range_m"]:
        lo = min(a for a, _ in stats["fp_range_m"])
        hi = max(b for _, b in stats["fp_range_m"])
        print(f"    floorplan depth range: {lo:.2f} - {hi:.2f} m")
    if stats["scan_nohit_frac"]:
        s = np.array(stats["scan_nohit_frac"])
        print(f"    scan no-hit fraction: mean {s.mean():.3f}  p90 {np.percentile(s, 90):.3f}  max {s.max():.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collections", nargs="+", default=list(C.COLLECTIONS))
    ap.add_argument("--sample", type=int, default=40, help="scenes to open per collection")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    print(f"dataset {C.DATASET}  root {C.ROOT}")
    for col in a.collections:
        check(col, a.sample, rng)
