#!/usr/bin/env python3
"""Stage 1 — map.png (0.01 m/px, free == 255) + scene_meta.json + floor-plan proxy.

Source: the 0.05 m wall mask from ~/workspace/test/floorplan_vs_mesh (walls voted
across height bands so furniture and door lintels drop out, outer envelope sealed
from the navmesh). Free space = interior.png from build_floorplan.py (rooms reachable from in-envelope
SoundSpaces graph nodes); walls AND the exterior are obstacles (anything != 255), which is what the
floor-plan proxy glb (same mask, extruded floor->ceiling) also encodes — so the
visual GT and the `floorplan_closed` acoustics describe the same geometry.

The mask is upsampled 5x with nearest neighbour (binary in, binary out) and saved
losslessly as an 8-bit RGB PNG with three identical channels.

World frame (spec 2.1/2.2): origin at the map centre, x = habitat x, y = -habitat z.
scene_meta.json records the offsets so every later stage converts the same way.

Usage:  python build_maps.py [--scenes ...]
"""
import argparse
import json
import os
import pickle
import shutil

import numpy as np
from PIL import Image
from scipy import ndimage

import common as C


def wall_grid(scene):
    """(grid[row, col] bool, x0, y0, info): row = +y (trimesh) = -habitat z."""
    info = json.load(open(os.path.join(C.TEST_OUT, scene, "floorplan.json")))
    img = np.array(Image.open(os.path.join(C.TEST_OUT, scene, "occupancy.png")))
    grid = np.flipud(img > 0)                      # occupancy.png was saved flipped for viewing
    assert list(grid.shape) == info["grid"], (scene, grid.shape, info["grid"])
    x0, y0 = info["origin_xy"]
    return grid, float(x0), float(y0), info


def node_cells(scene, x0, y0, shape):
    with open(os.path.join(C.SS_META, scene, "graph.pkl"), "rb") as f:
        g = pickle.load(f)
    H, W = shape
    out = []
    for n in g.nodes():
        hx, _, hz = g.nodes()[n]["point"]
        r, c = int((-hz - y0) / C.SRC_CELL), int((hx - x0) / C.SRC_CELL)
        if 0 <= r < H and 0 <= c < W:
            out.append((r, c))
    return out


def interior(grid, seeds):
    labels, _ = ndimage.label(~grid)
    keep = {labels[r, c] for r, c in seeds if labels[r, c] > 0}
    return np.isin(labels, list(keep)) if keep else np.zeros_like(grid)


def floor_stats(scene, occ, meta, n=2000, seed=0, y_hint=None):
    """Navmesh floor height and how much of the navmesh lands on free map pixels.
    y_hint (mp3d): only navmesh points within +-0.6 m of this storey's node height count."""
    sim = C.make_sim(scene, geom="real")
    pf = sim.pathfinder
    pf.seed(seed)
    ys, hits, tries = [], 0, 0
    while len(ys) < n and tries < 50 * n:
        tries += 1
        p = pf.get_random_navigable_point()
        if y_hint is not None and abs(float(p[1]) - y_hint) > 0.6:
            continue
        ys.append(float(p[1]))
        x, y = C.habitat_to_world(float(p[0]), float(p[2]), meta)
        r, c = C.world_to_map(x, y, occ.shape)
        r, c = int(r), int(c)
        if 0 <= r < occ.shape[0] and 0 <= c < occ.shape[1] and occ[r, c] == 255:
            hits += 1
    lo, hi = pf.get_bounds()
    sim.close()
    if not ys:
        raise RuntimeError(f"{scene}: no navmesh points near y={y_hint}")
    return float(np.median(ys)), hits / len(ys), [list(map(float, lo)), list(map(float, hi))]


def sealed_interior(scene, grid):
    """interior.png from build_floorplan.py: rooms reachable from graph nodes INSIDE the
    sealed envelope. Re-flooding here from all graph nodes is wrong — Replica navmeshes
    put nodes on unscanned outdoor areas (apartment_1/2), and one such seed floods the
    whole exterior (found 2026-09-08: apartment_2 'free' 134 m2 vs 72 m2 interior)."""
    p = os.path.join(C.TEST_OUT, scene, "interior.png")
    if not os.path.exists(p):
        raise FileNotFoundError(f"{p}: rebuild the wall masks with the current build_floorplan.py")
    free = np.flipud(np.array(Image.open(p)) > 0)
    assert free.shape == grid.shape and not (free & grid).any()
    return free


def build(scene):
    grid, x0, y0, info = wall_grid(scene)
    free = sealed_interior(scene, grid)
    occ = np.kron(np.where(free, 255, 0).astype(np.uint8), np.ones((C.UPSAMPLE, C.UPSAMPLE), np.uint8))
    occ, n_corner = C.close_diagonal_leaks(occ)     # see common.close_diagonal_leaks
    H, W = occ.shape
    meta = {
        "scene": scene,
        "map_res_m": C.MAP_RES,
        "map_w": int(W), "map_h": int(H),
        "src_cell_m": C.SRC_CELL,
        "origin_xy_trimesh": [x0, y0],
        # world origin = map centre; x_world = hx - cx, y_world = -hz - cy
        "world_cx_habitat": x0 + W / 2 * C.MAP_RES,
        "world_cy_habitat_neg_z": y0 + H / 2 * C.MAP_RES,
        "z_floor_mesh": info["z_floor"], "z_ceiling_mesh": info["z_ceiling"],
        "room_height_m": info["room_height_m"],
        "cam_height_m": C.CAM_HEIGHT,
        "free_area_m2": round(float(free.sum()) * C.SRC_CELL ** 2, 1),
        "wall_cells_src": int(grid.sum()),
        "diagonal_corner_px_filled": int(n_corner),
        "axis_convention": "x_world = habitat_x - cx; y_world = -habitat_z - cy; "
                           "yaw CCW from +x_world; habitat theta = yaw - pi/2; row = y, col = x",
    }
    y_hint = info["node_y_habitat"]["median"] if "node_y_habitat" in info else None
    floor_y, frac, bounds = floor_stats(scene, occ, meta, y_hint=y_hint)
    if "base_scene" in info:      # mp3d: one map per storey
        meta.update({"base_scene": info["base_scene"], "floor_index": info["floor_index"],
                     "n_floors_in_scene": info["n_floors_in_scene"], "node_y_habitat": info["node_y_habitat"]})
    meta.update({"floor_y_habitat": floor_y, "navmesh_on_free_fraction": round(frac, 3),
                 "navmesh_bounds_habitat": bounds})

    mdir = os.path.join(C.ROOT, "maps", scene)
    os.makedirs(mdir, exist_ok=True)
    Image.fromarray(np.repeat(occ[:, :, None], 3, axis=2)).save(os.path.join(mdir, "map.png"))
    with open(os.path.join(mdir, "scene_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    # sanity: what was written reads back binary
    back = np.array(Image.open(os.path.join(mdir, "map.png")))
    assert back.shape == (H, W, 3) and set(np.unique(back)) <= {0, 255}

    pdir = os.path.join(C.PROXY_DIR, scene)
    os.makedirs(pdir, exist_ok=True)
    for fn in ("floorplan.glb", "floorplan.json",                      # required
               "floorplan.stage_config.json", "floorplan.scene_dataset_config.json"):
        src = os.path.join(C.TEST_OUT, scene, fn)
        if os.path.exists(src):
            shutil.copy2(src, pdir)
        elif fn in ("floorplan.glb", "floorplan.json"):
            raise FileNotFoundError(src)
    for col in C.COLLECTIONS:
        sd = C.scene_dir(col, scene)
        os.makedirs(sd, exist_ok=True)
        shutil.copy2(os.path.join(mdir, "map.png"), sd)

    print(f"[{scene}] map {W}x{H}px  free {meta['free_area_m2']} m2  "
          f"floor_y {floor_y:.3f}  navmesh-on-free {frac:.1%}", flush=True)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="+", default=C.SCENES)
    a = ap.parse_args()
    for s in a.scenes:
        build(s)
    for col in C.COLLECTIONS:
        os.makedirs(os.path.join(C.ROOT, col), exist_ok=True)
        with open(os.path.join(C.ROOT, col, "split.yaml"), "w") as f:
            for k in ("train", "val", "test"):
                f.write(f"{k}: {json.dumps(C.SPLIT[k])}\n")


if __name__ == "__main__":
    main()
