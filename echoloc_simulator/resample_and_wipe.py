#!/usr/bin/env python3
"""Re-sample poses for every (collection, scene) and wipe the per-scene outputs of
those whose poses.txt changed, so the resume-safe stages regenerate exactly what
is stale (rgb/, depth_radial_*/, depth*.txt, rir/*/*/<scene>). Maps/desdf are
untouched (they do not depend on poses). Previous poses must be in
logs/poses_prev/<collection>_<scene>.txt (or none -> everything regenerates)."""
import os
import shutil
import subprocess
import sys

import numpy as np

import common as C

HERE = os.path.dirname(os.path.abspath(__file__))
PREV = os.path.join(HERE, "logs", "poses_prev")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300

for col in C.COLLECTIONS:
    for s in C.SCENES:
        sd = C.scene_dir(col, s)
        for f in ("chunks.json", "poses.txt"):
            p = os.path.join(sd, f)
            if os.path.exists(p):
                os.remove(p)
    subprocess.run([sys.executable, os.path.join(HERE, "sample_poses.py"), "--collection", col, "--n-chunks", str(N)], check=True)

changed = []
for col in C.COLLECTIONS:
    for s in C.SCENES:
        new = np.loadtxt(os.path.join(C.scene_dir(col, s), "poses.txt"), ndmin=2)
        pp = os.path.join(PREV, f"{col}_{s}.txt")
        same = os.path.exists(pp) and np.array_equal(np.loadtxt(pp, ndmin=2), new)
        if not same:
            changed.append((col, s))
            sd = C.scene_dir(col, s)
            for d in ("rgb", "depth_radial_scan", "depth_radial_floorplan"):
                shutil.rmtree(os.path.join(sd, d), ignore_errors=True)
            for f in ("depth40.txt", "depth160.txt"):
                if os.path.exists(os.path.join(sd, f)):
                    os.remove(os.path.join(sd, f))
            for cond in ("raw_scan_open", "floorplan_closed"):
                shutil.rmtree(os.path.join(C.ROOT, "rir", col, cond, s), ignore_errors=True)
            shutil.rmtree(os.path.join(C.VAL_DIR, col, s), ignore_errors=True)
print(f"[resample] changed {len(changed)}/{len(C.COLLECTIONS) * len(C.SCENES)}: " + " ".join(f"{c}/{s}" for c, s in changed), flush=True)
