#!/usr/bin/env python3
"""Stage 3b — per-pixel RADIAL depth maps for every frame, two geometries.

    <collection>/<scene>/depth_radial_scan/{chunk:05d}-{view}.png       Replica scan mesh (furniture and all)
    <collection>/<scene>/depth_radial_floorplan/{chunk:05d}-{view}.png  floor-plan proxy (walls only = map.png extruded)

16-bit PNG, millimetres (0 = no hit / invalid), 480x640, same camera as rgb/.

Habitat's pinhole DEPTH sensor returns the camera-forward z component (planar
depth). It is converted to the Euclidean distance along each pixel's ray:

    radial = z * sqrt(1 + ((u+0.5-cx)/fx)^2 + ((v+0.5-cy)/fy)^2),  K = [[240,0,320],[0,240,240],[0,0,1]]

so that a wall at 3 m straight ahead and a wall at 3 m in the corner of the
image both read 3000. (depth40/depth160 stay camera-forward z as F3Loc requires.)

Usage:  python render_depth.py --collection replica_f --scenes room_1
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

import common as C

DIRS = {"real": "depth_radial_scan", "plan": "depth_radial_floorplan"}
MAX_MM = 65535


def radial_factor():
    u = np.arange(C.IMG_W) + 0.5 - C.IMG_W / 2
    v = np.arange(C.IMG_H) + 0.5 - C.IMG_H / 2
    return np.sqrt(1.0 + (u[None, :] / C.FX) ** 2 + (v[:, None] / C.FY) ** 2).astype(np.float32)


def to_png16(depth_m, factor, path):
    r = depth_m.astype(np.float32) * factor
    mm = np.where(np.isfinite(r) & (r > 0), np.clip(np.round(r * 1000.0), 0, MAX_MM), 0).astype(np.uint16)
    Image.fromarray(mm, mode="I;16").save(path, compress_level=6)


def render(collection, scene, geom):
    sd = C.scene_dir(collection, scene)
    out_dir = os.path.join(sd, DIRS[geom])
    os.makedirs(out_dir, exist_ok=True)
    frames = [(c["idx"], v, fr) for c in C.read_chunks(collection, scene)["chunks"] for v, fr in enumerate(c["frames"])]
    todo = [(k, v, fr) for (k, v, fr) in frames if not os.path.exists(os.path.join(out_dir, C.frame_png(k * (C.L + 1) + v)))]
    if not todo:
        print(f"[{collection}/{scene}/{DIRS[geom]}] cached ({len(frames)})", flush=True)
        return
    fac = radial_factor()
    sim = C.make_sim(scene, geom=geom, depth=True)
    for k, v, fr in todo:
        hx, hy, hz = fr["hab"]
        C.set_agent(sim, hx, hy, hz, fr["theta"])
        to_png16(sim.get_sensor_observations()["depth"], fac, os.path.join(out_dir, C.frame_png(k * (C.L + 1) + v)))
    sim.close()
    print(f"[{collection}/{scene}/{DIRS[geom]}] {len(todo)} new (total {len(frames)})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True, choices=C.COLLECTIONS)
    ap.add_argument("--scenes", nargs="+", default=C.SCENES)
    ap.add_argument("--geoms", nargs="+", default=list(C.GEOMS), choices=list(DIRS))
    a = ap.parse_args()
    for s in a.scenes:
        for g in a.geoms:
            render(a.collection, s, g)


if __name__ == "__main__":
    sys.exit(main())
