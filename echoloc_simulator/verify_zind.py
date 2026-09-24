#!/usr/bin/env python3
"""Verify the ZInD import before anything downstream runs. Exit 1 on failure.

The three things that would silently ruin the dataset, each checked directly:

  1. yaw / map consistency. Free space is the union of the room polygons, so a map ray cast
     from a panorama can never be SHORTER than that panorama's own room polygon along the
     same direction. A wrong yaw breaks this immediately (measured: 0% violations at the
     stored yaw, 11-18% at +-15 deg).
  2. the RGB crop is the panorama, at the pose's heading. Sampled pixels are compared against
     the official ZInD projection (transformations.py) of the same ray; the mirrored and
     flipped variants must be far worse.
  3. metric scale. Camera and ceiling heights must be physically plausible, since every metric
     quantity in the dataset derives from scale_meters_per_coordinate.

Plus bookkeeping: rgb count == poses rows, poses on free pixels, map binary, split disjoint.

    ECHOLOC_DATASET=zind python verify_zind.py [--scenes N]
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

import common as C
import raycast
from build_zind import panos_of

FAIL = []


def check(cond, msg):
    if not cond:
        FAIL.append(msg)
    return cond


def poly_dist(V, th):
    """Distance from the room origin to polygon V along room-frame azimuth th."""
    dr = np.array([-np.sin(th), np.cos(th)])
    best = np.inf
    for a, b in zip(V, np.roll(V, -1, axis=0)):
        e = b - a
        M = np.array([[dr[0], -e[0]], [dr[1], -e[1]]])
        if abs(np.linalg.det(M)) < 1e-12:
            continue
        t, u = np.linalg.solve(M, a)
        if t > 1e-6 and -1e-9 <= u <= 1 + 1e-9:
            best = min(best, t)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", type=int, default=40, help="scenes to open for the deep checks")
    a = ap.parse_args()
    R, Z = C.ROOT, C.RAW_DIR
    # scene_meta.json is written last, so it -- not the directory -- marks a finished floor.
    mroot = os.path.join(R, "maps")
    scenes = sorted(d for d in os.listdir(mroot)
                    if os.path.exists(os.path.join(mroot, d, "scene_meta.json")))
    partial = sorted(d for d in os.listdir(mroot)
                     if os.path.isdir(os.path.join(mroot, d))
                     and not os.path.exists(os.path.join(mroot, d, "scene_meta.json")))
    print(f"floors built: {len(scenes)}")
    check(len(scenes) > 0, "no floors built")
    check(not partial, f"{len(partial)} half-written floors under maps/: {partial[:5]}")

    # ---- exhaustive bookkeeping ----
    tot_frames = 0
    bad_count = bad_free = bad_map = 0
    cam_h, ceil_h, area = [], [], []
    for s in scenes:
        sd = C.scene_dir(C.COLLECTIONS[0], s)
        P = np.atleast_2d(np.loadtxt(os.path.join(sd, "poses.txt")))
        n = len(P)
        tot_frames += n
        if len(os.listdir(os.path.join(sd, "rgb"))) != n:
            bad_count += 1
        occ = C.load_map(s)
        if set(np.unique(occ).tolist()) - {0, 255}:
            bad_map += 1
        H, W = occ.shape
        for x, y, _ in P[:, :3]:
            r, c = C.world_to_map(x, y, occ.shape)
            ri, ci = int(r), int(c)
            if not (0 <= ri < H and 0 <= ci < W) or occ[ri, ci] != 255:
                bad_free += 1
        m = json.load(open(os.path.join(R, "maps", s, "scene_meta.json")))
        ceil_h.append(m["room_height_m"])
        area.append(m["free_area_m2"])
        ch = json.load(open(os.path.join(sd, "chunks.json")))
        cam_h += [f["cam_z"] for c_ in ch["chunks"] for f in c_["frames"]]
    print(f"frames: {tot_frames}")
    check(bad_count == 0, f"{bad_count} scenes where rgb count != poses rows")
    check(bad_free == 0, f"{bad_free} poses not on a free map pixel")
    check(bad_map == 0, f"{bad_map} maps not binary")
    cam_h, ceil_h, area = map(np.array, (cam_h, ceil_h, area))
    print(f"camera height m: p1 {np.percentile(cam_h,1):.2f} med {np.median(cam_h):.2f} p99 {np.percentile(cam_h,99):.2f}")
    print(f"ceiling  m: p1 {np.percentile(ceil_h,1):.2f} med {np.median(ceil_h):.2f} p99 {np.percentile(ceil_h,99):.2f}")
    print(f"free area m2: min {area.min():.1f} med {np.median(area):.1f} max {area.max():.1f} total {area.sum():.0f}")
    check(0.8 < np.percentile(cam_h, 1) and np.percentile(cam_h, 99) < 2.2, "camera heights implausible")
    check(1.9 < np.percentile(ceil_h, 1) and np.percentile(ceil_h, 99) < 5.0, "ceiling heights implausible")

    # ---- deep checks on a sample ----
    rng = np.random.RandomState(0)
    pick = list(rng.choice(scenes, min(a.scenes, len(scenes)), replace=False))
    viol = rays = 0
    d_true, d_mirror, d_flip = [], [], []
    for s in pick:
        m = json.load(open(os.path.join(R, "maps", s, "scene_meta.json")))
        occ = C.load_map(s)
        d = json.load(open(os.path.join(Z, m["base_scene"], "zind_data.json")))
        sc = m["scale_meters_per_coordinate"]
        P = {pn: p for pn, p, _ in panos_of(d, m["floor_name"])}
        ch = json.load(open(os.path.join(C.scene_dir(C.COLLECTIONS[0], s), "chunks.json")))
        for c_ in ch["chunks"][:3]:
            fr = c_["frames"][0]
            p = P.get(fr["pano"])
            if p is None:
                continue
            V = np.asarray(p["layout_raw"]["vertices"], float) * (p["floor_plan_transformation"]["scale"] * sc)
            pos = np.array(C.world_to_map(fr["x"], fr["y"], occ.shape))
            for th in np.linspace(-np.pi, np.pi, 24, endpoint=False):
                pd = poly_dist(V, th)
                if not np.isfinite(pd) or pd > 15:
                    continue
                hit = raycast.ray_cast(occ, pos.copy(), float(C.wrap(fr["yaw"] + th)),
                                       dist_max=int(C.DIST_MAX_M / C.MAP_RES)) * C.MAP_RES
                if hit >= C.DIST_MAX_M * 0.995:
                    continue
                rays += 1
                viol += hit < pd - 0.15          # 0.15 m = 3 wall cells of rasterisation slack
            # crop vs the official ZInD projection
            pano = cv2.imread(os.path.join(Z, m["base_scene"], p["image_path"]), cv2.IMREAD_COLOR)
            crop = cv2.imread(os.path.join(C.scene_dir(C.COLLECTIONS[0], s), "rgb", f"{c_['idx']:05d}.png"),
                              cv2.IMREAD_COLOR)
            if pano is None or crop is None:
                continue
            Hp, Wp = pano.shape[:2]
            for _ in range(20):
                u, v = rng.randint(40, C.IMG_W - 40), rng.randint(40, C.IMG_H - 40)
                rx = (u + 0.5 - C.IMG_W / 2) / C.FX
                ry = (v + 0.5 - C.IMG_H / 2) / C.FY
                pt = np.array([rx, 1.0, -ry])
                rho = np.linalg.norm(pt)
                th_ = np.arctan2(-pt[0], pt[1])
                ph = np.arcsin(pt[2] / rho)
                xp = int(round((th_ + np.pi) / (2 * np.pi) * (Wp - 1))) % Wp
                yp = int(round((1 - (ph + np.pi / 2) / np.pi) * (Hp - 1))) % Hp
                ref = pano[yp, xp].astype(int)
                d_true.append(np.abs(ref - crop[v, u].astype(int)).mean())
                d_mirror.append(np.abs(ref - crop[v, C.IMG_W - 1 - u].astype(int)).mean())
                d_flip.append(np.abs(ref - crop[C.IMG_H - 1 - v, u].astype(int)).mean())
    frac = viol / max(rays, 1)
    print(f"\nyaw/map: {rays} rays, map shorter than the room polygon on {viol} ({100*frac:.2f}%)")
    check(frac < 0.02, f"yaw/map inconsistent: {100*frac:.1f}% of rays shorter than the room polygon")
    t, mi, fl = np.mean(d_true), np.mean(d_mirror), np.mean(d_flip)
    print(f"crop vs ZInD projection (0-255): as built {t:.2f} | mirrored {mi:.2f} | flipped {fl:.2f}")
    check(t < 5 and mi > 3 * t and fl > 3 * t, f"crop orientation suspect (true {t:.2f}, mirror {mi:.2f}, flip {fl:.2f})")

    # ---- split ----
    sy = os.path.join(R, C.COLLECTIONS[0], "split.yaml")
    if os.path.exists(sy):
        import yaml
        sp = yaml.safe_load(open(sy))
        sets = {k: set(v) for k, v in sp.items()}
        print("split:", {k: len(v) for k, v in sp.items()},
              "unassigned:", len(scenes) - sum(len(v) for v in sp.values()))
        check(not (sets["train"] & sets["val"]) and not (sets["train"] & sets["test"])
              and not (sets["val"] & sets["test"]), "split not disjoint")
        homes = {k: {C.base_scene(s) for s in v} for k, v in sets.items()}
        check(not (homes["train"] & homes["val"]) and not (homes["train"] & homes["test"])
              and not (homes["val"] & homes["test"]), "split leaks at the HOME level")

    print("\nRESULT:", "OK" if not FAIL else f"{len(FAIL)} FAILURES")
    for f in FAIL:
        print(" -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
