#!/usr/bin/env python3
"""Per-floor floor-plan stand-ins for Gibson scenes (the habitat release).

Same construction as build_floorplan_mp3d.py — a wall is what is solid at every height,
the envelope comes from the navigation mesh, and one output folder is written per storey
as <scene>_f<k> — with one difference: the habitat Gibson release ships only <scene>.glb
and <scene>.navmesh, with no SoundSpaces graph and no semantic mesh. Storeys and flood-fill
seeds therefore come from points sampled on the navigation mesh itself, clustered by height.

    <out>/<scene>_f<k>/occupancy.png     wall mask of that storey (0.05 m cells, flipped for viewing)
    <out>/<scene>_f<k>/interior.png      sealed free space of that storey
    <out>/<scene>_f<k>/floorplan.glb     walls extruded floor->ceiling + floor/ceiling slabs
    <out>/<scene>_f<k>/floorplan.json    origin, grid, z band, storey index, sample count
    <out>/<scene>_f<k>/floorplan_map.png, leak_diagnostic.png

Axis convention (verified against the navmesh bounds): the glb is authored z-up in trimesh
coordinates and habitat = (tx, tz, -ty), exactly as for Replica and MP3D, so the glb is
exported untouched.

Usage (ss_v2 env):  python build_floorplan_gibson.py --scenes Alfred Herricks --out ./gibson_floors
"""
import argparse
import json
import os

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage

GIBSON = os.environ.get("GIBSON_MESH_DIR", "/mnt/sdb/gibson_raw/gibson")

CELL = 0.05
MARGIN_M = 1.0
CLOSE_RADIUS = 3
MAX_WALL_NZ = 0.35
BAND_BOTTOM = 0.35
BAND_TOP = 0.20
BAND_STEP = 0.20
BAND_FRACTION = 0.60
FOOTPRINT_CLOSE = 5
PEAK_BIN = 0.10          # histogram bin for finding storey heights
PEAK_FRAC = 0.02         # a bin holding this fraction of the samples is a storey mode
PEAK_MERGE = 0.60        # modes closer than this are the same storey (split levels, thresholds)
FLOOR_BAND = 0.50        # a sample belongs to a mode if it is within this of it
FLOOR_HEIGHT = 2.7
NAV_Y_TOL = 0.8
N_SAMPLES = 4000         # navmesh samples used to find storeys and seed the flood fill
MIN_SAMPLES = 40         # a storey needs this many samples (drops stair landings)
MIN_AREA_M2 = 8.0
CAM_HEIGHT = 1.25        # must match common.CAM_HEIGHT
MIN_CEIL_MARGIN = 0.15   # the storey ceiling must clear the camera

_SIM = {}


def load_mesh(scene):
    mesh = trimesh.load(os.path.join(GIBSON, f"{scene}.glb"), process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    return mesh


def get_sim(scene):
    """One headless simulator per scene, reused across storeys."""
    import habitat_sim
    if scene in _SIM:
        return _SIM[scene]
    for s in list(_SIM.values()):
        s.close()
    _SIM.clear()
    backend = habitat_sim.SimulatorConfiguration()
    backend.scene_id = os.path.join(GIBSON, f"{scene}.glb")
    backend.enable_physics = False
    backend.load_semantic_mesh = False
    backend.create_renderer = True
    backend.requires_textures = False
    spec = habitat_sim.CameraSensorSpec()
    spec.uuid = "_d"
    spec.sensor_type = habitat_sim.SensorType.DEPTH
    spec.resolution = [8, 8]
    ac = habitat_sim.agent.AgentConfiguration()
    ac.sensor_specifications = [spec]
    sim = habitat_sim.Simulator(habitat_sim.Configuration(backend, [ac]))
    navmesh = os.path.join(GIBSON, f"{scene}.navmesh")
    if not sim.pathfinder.is_loaded:
        sim.pathfinder.load_nav_mesh(navmesh)
    _SIM[scene] = sim
    return sim


def navmesh_samples(scene, n=N_SAMPLES, seed=0):
    """Points on the navigation mesh, in habitat coordinates."""
    pf = get_sim(scene).pathfinder
    if not pf.is_loaded:
        return np.zeros((0, 3))
    pf.seed(seed)
    return np.array([pf.get_random_navigable_point() for _ in range(n)], dtype=float)


def cluster_floors(pts):
    """Storeys from the modes of the sample-height histogram -> [(y_lo, y_hi, y_med, points)].

    Gap clustering fails here: stairs are navigable, so samples form a continuous ramp between
    storeys and a single gap threshold merges them. A storey is instead a *mode*: floors are
    flat, so their samples pile into a few narrow height bands while stairs contribute a thin
    uniform spread. We take histogram bins holding at least PEAK_FRAC of the samples, merge
    bins closer than PEAK_MERGE, and assign each sample to the nearest mode within FLOOR_BAND."""
    y = pts[:, 1]
    lo, hi = y.min(), y.max()
    nb = max(4, int(np.ceil((hi - lo) / PEAK_BIN)) + 1)
    hist, edges = np.histogram(y, bins=nb, range=(lo, lo + nb * PEAK_BIN))
    centres = (edges[:-1] + edges[1:]) / 2
    peaks = [c for c, h in zip(centres, hist) if h >= PEAK_FRAC * len(y)]
    if not peaks:
        peaks = [float(np.median(y))]
    merged = [peaks[0]]
    for c in peaks[1:]:
        if c - merged[-1] <= PEAK_MERGE:
            merged[-1] = (merged[-1] + c) / 2          # same storey, keep one mode
        else:
            merged.append(c)
    out = []
    for m in merged:
        sel = np.abs(y - m) <= FLOOR_BAND
        if not sel.any():
            continue
        yy = y[sel]
        out.append((float(yy.min()), float(yy.max()), float(m), pts[sel]))
    return out


def _stamp(tri, x0, y0, H, W):
    grid = np.zeros((H, W), dtype=bool)
    if len(tri) == 0:
        return grid
    pts = [tri[:, i, :2] for i in range(3)]
    pts += [(tri[:, i, :2] + tri[:, (i + 1) % 3, :2]) / 2 for i in range(3)]
    pts += [tri[:, :, :2].mean(axis=1)]
    P = np.concatenate(pts, axis=0)
    cx = np.clip(((P[:, 0] - x0) / CELL).astype(int), 0, W - 1)
    cy = np.clip(((P[:, 1] - y0) / CELL).astype(int), 0, H - 1)
    grid[cy, cx] = True
    return grid


def occupancy_for_floor(mesh, x0, y0, H, W, z_floor, z_ceil):
    tri_all = mesh.vertices[mesh.faces]
    nz = np.abs(mesh.face_normals[:, 2])
    zmin_all = tri_all[:, :, 2].min(axis=1)
    zmax_all = tri_all[:, :, 2].max(axis=1)
    in_band = (zmax_all >= z_floor - 0.3) & (zmin_all <= z_ceil + 0.3)
    footprint = ndimage.binary_closing(_stamp(tri_all[in_band], x0, y0, H, W),
                                       structure=np.ones((FOOTPRINT_CLOSE, FOOTPRINT_CLOSE)))
    footprint = ndimage.binary_fill_holes(footprint)
    keep = nz < MAX_WALL_NZ
    tri, zmin, zmax = tri_all[keep], zmin_all[keep], zmax_all[keep]
    band_lo, band_hi = z_floor + BAND_BOTTOM, z_ceil - BAND_TOP
    sel = (zmax >= band_lo) & (zmin <= band_hi)
    tri, zmin, zmax = tri[sel], zmin[sel], zmax[sel]
    edges = np.arange(band_lo, band_hi, BAND_STEP)
    if len(edges) == 0:
        edges = np.array([band_lo])
    votes = np.zeros((H, W), dtype=np.int32)
    for b in edges:
        s = (zmax >= b) & (zmin <= b + BAND_STEP)
        band = ndimage.binary_closing(_stamp(tri[s], x0, y0, H, W), structure=np.ones((CLOSE_RADIUS, CLOSE_RADIUS)))
        votes += band
    grid = votes >= max(1, int(round(BAND_FRACTION * len(edges))))
    grid = ndimage.binary_closing(grid, structure=np.ones((CLOSE_RADIUS, CLOSE_RADIUS)))
    return grid, len(edges), footprint


def sample_cells(pts, x0, y0, H, W):
    """habitat (hx, hy, hz) -> grid (row, col) in the trimesh frame: tx = hx, ty = -hz."""
    out = []
    for hx, _, hz in pts:
        r, c = int((-hz - y0) / CELL), int((hx - x0) / CELL)
        if 0 <= r < H and 0 <= c < W:
            out.append((r, c))
    return out


def navmesh_env(scene, x0, y0, H, W, agent_y):
    pf = get_sim(scene).pathfinder
    nav = np.zeros((H, W), dtype=bool)
    ty = y0 + (np.arange(H) + 0.5) * CELL
    tx = x0 + (np.arange(W) + 0.5) * CELL
    for r in range(H):
        for c in range(W):
            nav[r, c] = pf.is_navigable([float(tx[c]), agent_y, float(-ty[r])], NAV_Y_TOL)
    if not nav.any():
        return None
    env = ndimage.binary_fill_holes(nav)
    return ndimage.binary_dilation(env, iterations=int(round(0.6 / CELL)))


def boxes_from_grid(grid, x0, y0, z_floor, z_ceil):
    h = z_ceil - z_floor
    parts = []
    ys, xs = np.where(grid)
    for row in np.unique(ys):
        cols = np.sort(xs[ys == row])
        for run in np.split(cols, np.where(np.diff(cols) != 1)[0] + 1):
            if run.size == 0:
                continue
            box = trimesh.creation.box(extents=(run.size * CELL, CELL, h))
            box.apply_translation((x0 + (run[0] + run.size / 2) * CELL, y0 + (row + 0.5) * CELL, z_floor + h / 2))
            parts.append(box)
    H, W = grid.shape
    fx, fy = W * CELL, H * CELL
    cx, cy = x0 + fx / 2, y0 + fy / 2
    for zc in (z_floor - 0.025, z_ceil + 0.025):
        slab = trimesh.creation.box(extents=(fx, fy, 0.05))
        slab.apply_translation((cx, cy, zc))
        parts.append(slab)
    return trimesh.util.concatenate(parts)


def write_configs(out_dir):
    with open(os.path.join(out_dir, "floorplan.stage_config.json"), "w") as f:
        json.dump({"render_asset": "floorplan.glb", "collision_asset": "floorplan.glb", "requires_lighting": False,
                   "up": [0, 0, 1], "front": [0, 1, 0], "origin": [0, 0, 0]}, f, indent=2)
    with open(os.path.join(out_dir, "floorplan.scene_dataset_config.json"), "w") as f:
        json.dump({"stages": {"paths": {".json": ["*.stage_config.json"]}}, "objects": {}, "light_setups": {},
                   "scene_instances": {"default_attributes": {"default_lighting": "no_lights"}}}, f, indent=2)


def build(scene, out_root):
    mesh = load_mesh(scene)
    pts = navmesh_samples(scene)
    if len(pts) == 0:
        print(f"[{scene}] no navmesh, skipped", flush=True)
        return []
    v = mesh.vertices
    x0, y0 = v[:, 0].min() - MARGIN_M, v[:, 1].min() - MARGIN_M
    W = int(np.ceil((v[:, 0].max() + MARGIN_M - x0) / CELL)) + 1
    H = int(np.ceil((v[:, 1].max() + MARGIN_M - y0) / CELL)) + 1
    floors = cluster_floors(pts)
    written = []
    for fi, (y_lo, y_hi, y_med, fpts) in enumerate(floors):
        if len(fpts) < MIN_SAMPLES:
            print(f"[{scene}] floor {fi}: only {len(fpts)} navmesh samples, skipped", flush=True)
            continue
        z_floor = y_med - 0.1
        z_ceil = min(y_med + FLOOR_HEIGHT, floors[fi + 1][2] - 0.1) if fi + 1 < len(floors) else y_med + FLOOR_HEIGHT
        if z_ceil - (y_med + CAM_HEIGHT) < MIN_CEIL_MARGIN:
            print(f"[{scene}] floor {fi}: band [{z_floor:.2f},{z_ceil:.2f}] too thin for the camera, skipped", flush=True)
            continue
        grid, n_bands, footprint = occupancy_for_floor(mesh, x0, y0, H, W, z_floor, z_ceil)
        env = navmesh_env(scene, x0, y0, H, W, agent_y=y_med + 0.1)
        if env is None:
            print(f"[{scene}] floor {fi}: no navmesh at y={y_med:.2f}, skipped", flush=True)
            continue
        env &= footprint
        env = ndimage.binary_fill_holes(env)
        seal = ndimage.binary_dilation(env) & ~env
        grid = grid | seal
        grid[~ndimage.binary_dilation(env, iterations=2)] = False
        labels, _ = ndimage.label(~grid)
        seeds = [(r, c) for r, c in sample_cells(fpts, x0, y0, H, W) if env[r, c]]
        keep = {labels[r, c] for r, c in seeds if labels[r, c] > 0}
        interior = np.isin(labels, list(keep)) if keep else np.zeros_like(grid)
        area = float(interior.sum()) * CELL ** 2
        if area < MIN_AREA_M2:
            print(f"[{scene}] floor {fi}: interior {area:.1f} m2, skipped", flush=True)
            continue
        sid = f"{scene}_f{fi}"
        out_dir = os.path.join(out_root, sid)
        os.makedirs(out_dir, exist_ok=True)
        fp = boxes_from_grid(grid, x0, y0, z_floor, z_ceil)
        fp.export(os.path.join(out_dir, "floorplan.glb"))
        write_configs(out_dir)
        Image.fromarray((np.flipud(grid) * 255).astype(np.uint8)).save(os.path.join(out_dir, "occupancy.png"))
        Image.fromarray((np.flipud(interior) * 255).astype(np.uint8)).save(os.path.join(out_dir, "interior.png"))
        rgb = np.zeros((H, W, 3), dtype=np.uint8)
        rgb[interior] = (245, 245, 245)
        for r, c in seeds[::20]:
            rgb[max(0, r - 1):r + 2, max(0, c - 1):c + 2] = (220, 40, 40)
        Image.fromarray(np.flipud(rgb)).resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(out_dir, "floorplan_map.png"))
        diag = np.zeros((H, W, 3), dtype=np.uint8)
        diag[env] = (60, 70, 85)
        diag[interior] = (245, 245, 245)
        diag[grid] = (15, 15, 15)
        Image.fromarray(np.flipud(diag)).resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(out_dir, "leak_diagnostic.png"))
        info = {"scene": sid, "base_scene": scene, "floor_index": fi, "n_floors_in_scene": len(floors),
                "cell_m": CELL, "grid": [H, W], "origin_xy": [float(x0), float(y0)], "margin_m": MARGIN_M,
                "z_floor": float(z_floor), "z_ceiling": float(z_ceil), "room_height_m": round(float(z_ceil - z_floor), 3),
                "node_y_habitat": {"min": y_lo, "median": y_med, "max": y_hi}, "n_nodes": int(len(fpts)),
                "seeds": "navmesh samples (no SoundSpaces graph in the Gibson release)",
                "height_bands": n_bands, "wall_cells": int(grid.sum()), "interior_area_m2": round(area, 1),
                "footprint_cells": int(footprint.sum()), "faces": int(len(fp.faces))}
        with open(os.path.join(out_dir, "floorplan.json"), "w") as f:
            json.dump(info, f, indent=2)
        written.append(sid)
        print(f"[{sid}] samples={len(fpts)} z=[{z_floor:.2f},{z_ceil:.2f}] walls={info['wall_cells']} "
              f"interior={area:.1f} m2 faces={info['faces']}", flush=True)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="+", default=None)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gibson_floors"))
    a = ap.parse_args()
    scenes = a.scenes or sorted(f[:-4] for f in os.listdir(GIBSON) if f.endswith(".glb"))
    for s in scenes:
        if os.path.isdir(os.path.join(a.out, f"{s}_f0")):
            print(f"[{s}] cached", flush=True)
            continue
        try:
            build(s, a.out)
        except Exception as e:
            print(f"[{s}] FAILED: {type(e).__name__}: {e}", flush=True)
    for s in list(_SIM.values()):
        s.close()


if __name__ == "__main__":
    main()
