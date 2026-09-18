#!/usr/bin/env python3
"""Stage 3 — rgb/{chunk:05d}-{view}.png (480x640, K=[[240,0,320],[0,240,240],[0,0,1]]).

Renders the real Replica mesh with a gravity-aligned pinhole camera at CAM_HEIGHT
above the navmesh, at every pose of poses.txt (via chunks.json, which carries the
habitat-frame pose incl. the navmesh height).

Validation side-products (spec 6, checks 8/9), every --val-every-th frame:
  <echoloc_simulator>/validation/<collection>/<scene>/depth_real/{frame:05d}.npy   z-depth, real mesh
  <echoloc_simulator>/validation/<collection>/<scene>/depth_plan/{frame:05d}.npy   z-depth, floor-plan proxy
The proxy is the very geometry map.png encodes, so its horizon row must agree with
the map ray cast to within a map pixel — validate.py checks that.

Usage:  python render_rgb.py --collection replica_f --scenes room_1 [--val-every 25]
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

import common as C


def frames_of(collection, scene):
    ch = C.read_chunks(collection, scene)
    out = []
    for c in ch["chunks"]:
        for v, fr in enumerate(c["frames"]):
            out.append((c["idx"], v, fr))
    return out


def render(collection, scene, val_every):
    sd = C.scene_dir(collection, scene)
    rgb_dir = os.path.join(sd, "rgb")
    os.makedirs(rgb_dir, exist_ok=True)
    vd = os.path.join(C.VAL_DIR, collection, scene)
    os.makedirs(os.path.join(vd, "depth_real"), exist_ok=True)
    os.makedirs(os.path.join(vd, "depth_plan"), exist_ok=True)

    frames = frames_of(collection, scene)
    if C.DATASET == "s3d":
        print(f"[{collection}/{scene}] s3d: rgb comes from the dataset (build_s3d.py); nothing to render", flush=True)
        return
    todo = [(k, v, fr) for (k, v, fr) in frames
            if not os.path.exists(os.path.join(rgb_dir, C.frame_png(k * (C.L + 1) + v)))]
    val_idx = [i for i in range(len(frames)) if i % val_every == 0]
    val_todo = [i for i in val_idx
                if not os.path.exists(os.path.join(vd, "depth_plan", f"{i:05d}.npy"))]
    if not todo and not val_todo:
        print(f"[{collection}/{scene}] cached ({len(frames)} frames)", flush=True)
        return

    if todo or any(not os.path.exists(os.path.join(vd, "depth_real", f"{i:05d}.npy")) for i in val_idx):
        sim = C.make_sim(scene, geom="real", rgb=True, depth=True)
        n = 0
        for i, (k, v, fr) in enumerate(frames):
            png = os.path.join(rgb_dir, C.frame_png(i))
            dnp = os.path.join(vd, "depth_real", f"{i:05d}.npy")
            want_val = (i % val_every == 0) and not os.path.exists(dnp)
            if os.path.exists(png) and not want_val:
                continue
            hx, hy, hz = fr["hab"]
            C.set_agent(sim, hx, hy, hz, fr["theta"])
            obs = sim.get_sensor_observations()
            if not os.path.exists(png):
                Image.fromarray(np.ascontiguousarray(obs["rgb"][..., :3])).save(png, compress_level=6)
                n += 1
            if want_val:
                np.save(dnp, obs["depth"].astype(np.float32))
        sim.close()
        print(f"[{collection}/{scene}] real: {n} new rgb frames (total {len(frames)})", flush=True)

    if val_todo:
        sim = C.make_sim(scene, geom="plan", depth=True)
        for i in val_todo:
            _, _, fr = frames[i]
            hx, hy, hz = fr["hab"]
            C.set_agent(sim, hx, hy, hz, fr["theta"])
            np.save(os.path.join(vd, "depth_plan", f"{i:05d}.npy"),
                    sim.get_sensor_observations()["depth"].astype(np.float32))
        sim.close()
        print(f"[{collection}/{scene}] plan: {len(val_todo)} validation depth frames", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True, choices=C.COLLECTIONS)
    ap.add_argument("--scenes", nargs="+", default=C.SCENES)
    ap.add_argument("--val-every", type=int, default=25)
    a = ap.parse_args()
    for s in a.scenes:
        render(a.collection, s, a.val_every)


if __name__ == "__main__":
    sys.exit(main())
