#!/usr/bin/env python3
"""Stage 5 — desdf/<scene>/desdf.npy for the test scenes (spec 3.6).

{"l": int, "t": int, "desdf": float32 (H, W, 36) metres}, 0.1 m/cell, 36 CCW yaw
bins at o*10 deg, cast to 10 m with F3Loc's ray_cast (through its own
raycast_desdf, which we call on a crop of map.png so the array stays small:
x_map = x_desdf*10 + l, y_map = y_desdf*10 + t). The 36 orientations are spread
over a worker pool.

Usage:  python make_desdf.py [--scenes apartment_2 frl_apartment_5 office_4] [--workers 12]
"""
import argparse
import os
import sys
from multiprocessing import Pool

import numpy as np

import common as C

ORN = 36
MAX_DIST_M = 10.0
CELL_M = 0.1
PAD_PX = 20

_occ = None


def _init(occ):
    global _occ
    _occ = occ
    C.f3loc_import()


def _orientation(o):
    from raycast import ray_cast   # exact DDA; see raycast.py (F3Loc original leaks at wall corners)
    ratio = int(round(CELL_M / C.MAP_RES))
    Hc, Wc = _occ.shape[0] // ratio, _occ.shape[1] // ratio
    theta = o / ORN * 2 * np.pi
    out = np.zeros((Hc, Wc), dtype=np.float32)
    for row in range(Hc):
        for col in range(Wc):
            pos = np.array([row, col], dtype=np.float64) * ratio
            out[row, col] = ray_cast(_occ, pos, theta, MAX_DIST_M / C.MAP_RES)
    return o, out * C.MAP_RES


def run(scene, workers):
    out = os.path.join(C.ROOT, "desdf", scene, "desdf.npy")
    if os.path.exists(out):
        print(f"[desdf/{scene}] cached", flush=True)
        return
    occ = C.load_map(scene)
    rows, cols = np.where(occ == 255)
    ratio = int(round(CELL_M / C.MAP_RES))
    # crop to the free-space bounding box (+pad), offsets snapped to whole desdf cells
    t = max(0, (rows.min() - PAD_PX) // ratio * ratio)
    l = max(0, (cols.min() - PAD_PX) // ratio * ratio)
    b = min(occ.shape[0], rows.max() + PAD_PX)
    r = min(occ.shape[1], cols.max() + PAD_PX)
    crop = np.ascontiguousarray(occ[t:b, l:r])
    ratio_f = CELL_M / C.MAP_RES
    Hc, Wc = int(crop.shape[0] // ratio_f), int(crop.shape[1] // ratio_f)
    desdf = np.zeros((Hc, Wc, ORN), dtype=np.float32)
    with Pool(workers, initializer=_init, initargs=(crop,)) as pool:
        for o, plane in pool.imap_unordered(_orientation, range(ORN)):
            desdf[:, :, o] = plane
    assert np.isfinite(desdf).all() and desdf.max() <= MAX_DIST_M + 1e-4
    os.makedirs(os.path.dirname(out), exist_ok=True)
    np.save(out, {"l": int(l), "t": int(t), "desdf": desdf})
    print(f"[desdf/{scene}] {desdf.shape} float32  l={l} t={t}  (map {occ.shape[1]}x{occ.shape[0]})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="+", default=C.SPLIT["test"])
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    for s in a.scenes:
        run(s, a.workers)


if __name__ == "__main__":
    sys.exit(main())
