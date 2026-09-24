#!/usr/bin/env python3
"""Stage 4 — depth40.txt / depth160.txt: camera-forward (z) depth from map.png.

Exactly the spec's recipe (3.4), using F3Loc's own `ray_cast` so the
discretisation matches the released data:

    center_angs = flip(arctan2(u - u.mean(), ray_n * F_W)),  F_W = 3/8
    pos = [y/0.01 + H/2, x/0.01 + W/2]                       (row, col)
    depth_i = ray_cast(occ, pos, center_angs[i] + yaw, dist_max=20/0.01) * 0.01 * cos(center_angs[i])

Rays that escape the map saturate at dist_max (kept, finite). One process per
scene, frames split across a worker pool.

Usage:  python make_depth_gt.py --collection replica_f [--scenes ...] [--workers 8]
"""
import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import numpy as np

import common as C

_occ = None
_rc = None


def _init(scene):
    global _occ, _rc
    C.f3loc_import()
    from raycast import ray_cast   # exact DDA; see raycast.py (F3Loc original leaks at wall corners)
    _rc = ray_cast
    _occ = C.load_map(scene)


def center_angs(ray_n):
    u = np.arange(ray_n)
    return np.flip(np.arctan2(u - u.mean(), ray_n * C.F_W))


def _frame(args):
    i, x, y, yaw, ray_n = args
    angs = center_angs(ray_n)
    H, W = _occ.shape
    pos = np.array([y / C.MAP_RES + H / 2, x / C.MAP_RES + W / 2], dtype=np.float64)
    out = np.empty(ray_n)
    for j, a in enumerate(angs):
        d = _rc(_occ, pos.copy(), float(a + yaw), dist_max=C.DIST_MAX_M / C.MAP_RES)
        out[j] = d * C.MAP_RES * np.cos(a)
    return i, out


def run(collection, scene, workers):
    sd = C.scene_dir(collection, scene)
    poses = C.read_poses(collection, scene)
    for ray_n in (40, 160):
        out = os.path.join(sd, f"depth{ray_n}.txt")
        if os.path.exists(out) and sum(1 for _ in open(out)) == len(poses):
            print(f"[{collection}/{scene}] depth{ray_n} cached", flush=True)
            continue
        jobs = [(i, float(x), float(y), float(yaw), ray_n) for i, (x, y, yaw) in enumerate(poses)]
        res = np.zeros((len(poses), ray_n))
        # A worker occasionally dies with a segfault (sporadic, fork-related). multiprocessing.Pool
        # then waits forever for the lost task (hung the ZInD chain for 23 h on 2026-09-21);
        # ProcessPoolExecutor raises BrokenProcessPool instead, and the scene is simply redone.
        for attempt in range(1, 4):
            try:
                with ProcessPoolExecutor(workers, initializer=_init, initargs=(scene,)) as ex:
                    for i, row in ex.map(_frame, jobs, chunksize=16):
                        res[i] = row
                break
            except BrokenProcessPool:
                print(f"[{collection}/{scene}] depth{ray_n}: a worker crashed (attempt {attempt}), retrying", flush=True)
        else:
            raise RuntimeError(f"{collection}/{scene} depth{ray_n}: workers kept crashing")
        assert np.isfinite(res).all() and (res > 0).all()
        with open(out, "w") as f:
            for row in res:
                f.write(" ".join(repr(float(v)) for v in row) + "\n")
        print(f"[{collection}/{scene}] depth{ray_n}: {len(poses)} rows, "
              f"saturated {float((res >= C.DIST_MAX_M * 0.999).mean()):.2%}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True, choices=C.COLLECTIONS)
    ap.add_argument("--scenes", nargs="+", default=C.SCENES)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    for s in a.scenes:
        run(a.collection, s, a.workers)


if __name__ == "__main__":
    sys.exit(main())
