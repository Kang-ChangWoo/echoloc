#!/usr/bin/env python3
"""Per-floor floor-plan stand-ins for Matterport3D scenes (mp3d twin of build_floorplan.py).

One MP3D scene is a whole building. F3Loc wants one map per FLOOR (spec 3.3 / 5.2), so
this writes one output folder per storey, named  <scene>_f<k>  (k = 0 from the lowest),
each with exactly the files the Replica builder writes:

    <out>/<scene>_f<k>/occupancy.png     wall mask of that storey (0.05 m cells, flipped for viewing)
    <out>/<scene>_f<k>/interior.png      sealed free space of that storey (rooms reachable from
                                         that storey's SoundSpaces graph nodes inside the envelope)
    <out>/<scene>_f<k>/floorplan.glb     that storey's walls extruded floor->ceiling + floor/ceiling slabs
    <out>/<scene>_f<k>/floorplan.json    origin_xy, grid, z_floor, z_ceiling, floor index, node height ...
    <out>/<scene>_f<k>/floorplan_map.png, leak_diagnostic.png   sanity images

Storeys: SoundSpaces graph nodes clustered by height (gap > FLOOR_GAP m = new storey), the
same rule the merged builder (build_floorplan_mp3d_legacy_merged.py) used. A storey's
z-band is [node_min - 0.1, min(node_lo + 2.7, next storey - 0.1)]. All storeys of a scene
share one (x0, y0, W, H) frame.

Fixes carried over from the Replica builder (2026-09-08): grid padded by MARGIN_M so the
navmesh sealing ring always fits; envelope = navmesh (within this storey's height band)
∩ scan footprint of the band, filled; flood-fill seeds only from nodes inside the envelope.

Axis convention as everywhere: mesh/trimesh z is up; habitat = (tx, tz, -ty); export the
glb untouched (habitat's importer applies the -90 deg X rotation).

Usage (ss_v2 env):  python build_floorplan_mp3d.py --scenes 17DRP5sb8fy 1LXtFkjw3qL --out ./mp3d_floors
"""
import argparse
import json
import os
import pickle

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage

MP3D = os.environ.get("MP3D_MESH_DIR", "/mnt/sdb/mp3d_raw")
if not os.path.isdir(MP3D):
    MP3D = "/file1/rvi/dataset/matterport/sound-spaces/data/scene_datasets/matterport/mp3d"
DATA_ROOT = os.environ.get("SS_DATA_ROOT", "/file2/changwoo/soundspaces")
CONFIG = os.path.join(MP3D, "mp3d.scene_dataset_config.json")

CELL = 0.05
MARGIN_M = 1.0
CLOSE_RADIUS = 3
MAX_WALL_NZ = 0.35
BAND_BOTTOM = 0.35
BAND_TOP = 0.20
BAND_STEP = 0.20
BAND_FRACTION = 0.60
FOOTPRINT_CLOSE = 5
FLOOR_GAP = 1.0          # node height gap that starts a new storey
FLOOR_HEIGHT = 2.7       # storey height when the next storey is further away
NAV_Y_TOL = 0.8          # is_navigable height tolerance: stay inside one storey (gap ~2.5-3 m)
MIN_NODES = 4            # storeys with fewer graph nodes are skipped (stair landings)
MIN_AREA_M2 = 8.0
CAM_HEIGHT = 1.25        # must match common.CAM_HEIGHT
MIN_CEIL_MARGIN = 0.15   # storey ceiling must clear the camera; FLOOR_GAP 1 m splits split-levels into
                         # bands only 1.0-1.9 m tall, where the camera would sit above the proxy ceiling


def load_mesh(scene):
    mesh = trimesh.load(os.path.join(MP3D, scene, f"{scene}.glb"), process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    return mesh


def graph_points(scene):
    with open(os.path.join(DATA_ROOT, "mp3d", "metadata", scene, "graph.pkl"), "rb") as f:
        g = pickle.load(f)
    return {n: np.asarray(g.nodes[n]["point"], dtype=float) for n in g.nodes()}


def cluster_floors(pts):
    ys = sorted((p[1], n) for n, p in pts.items())
    floors, cur = [], [ys[0]]
    for y, n in ys[1:]:
        if y - cur[-1][0] > FLOOR_GAP:
            floors.append(cur)
            cur = []
        cur.append((y, n))
    floors.append(cur)
    return [(min(y for y, _ in f), max(y for y, _ in f), float(np.median([y for y, _ in f])), [n for _, n in f]) for f in floors]


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
    # footprint: ANY geometry inside this storey's band (walls, floor, furniture, ceiling)
    in_band = (zmax_all >= z_floor - 0.3) & (zmin_all <= z_ceil + 0.3)
    footprint = ndimage.binary_closing(_stamp(tri_all[in_band], x0, y0, H, W),
                                       structure=np.ones((FOOTPRINT_CLOSE, FOOTPRINT_CLOSE)))
    footprint = ndimage.binary_fill_holes(footprint)
    # walls: near-vertical faces, voted across the storey's height bands
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


def node_cells(ids, pts, x0, y0, H, W):
    out = []
    for n in ids:
        hx, _, hz = pts[n]
        r, c = int((-hz - y0) / CELL), int((hx - x0) / CELL)
        if 0 <= r < H and 0 <= c < W:
            out.append((r, c))
    return out


_SIM = {}


def get_sim(scene):
    """One headless simulator per scene (navmesh only), reused across storeys."""
    import habitat_sim
    if scene in _SIM:
        return _SIM[scene]
    for s in list(_SIM.values()):
        s.close()
    _SIM.clear()
    backend = habitat_sim.SimulatorConfiguration()
    backend.scene_id = os.path.join(MP3D, scene, f"{scene}.glb")
    backend.scene_dataset_config_file = CONFIG
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
    navmesh = os.path.join(MP3D, scene, f"{scene}.navmesh")
    if not sim.pathfinder.is_loaded:
        sim.pathfinder.load_nav_mesh(navmesh)
    _SIM[scene] = sim
    return sim


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
    pts = graph_points(scene)
    v = mesh.vertices
    x0, y0 = v[:, 0].min() - MARGIN_M, v[:, 1].min() - MARGIN_M
    W = int(np.ceil((v[:, 0].max() + MARGIN_M - x0) / CELL)) + 1
    H = int(np.ceil((v[:, 1].max() + MARGIN_M - y0) / CELL)) + 1
    floors = cluster_floors(pts)
    written = []
    for fi, (y_lo, y_hi, y_med, ids) in enumerate(floors):
        if len(ids) < MIN_NODES:
            print(f"[{scene}] floor {fi}: only {len(ids)} nodes, skipped", flush=True)
            continue
        z_floor = y_lo - 0.1
        z_ceil = min(y_lo + FLOOR_HEIGHT, floors[fi + 1][0] - 0.1) if fi + 1 < len(floors) else y_lo + FLOOR_HEIGHT
        if z_ceil - (y_med + CAM_HEIGHT) < MIN_CEIL_MARGIN:
            print(f"[{scene}] floor {fi}: band [{z_floor:.2f},{z_ceil:.2f}] too thin for a {CAM_HEIGHT} m camera, skipped", flush=True)
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
        seeds = [(r, c) for r, c in node_cells(ids, pts, x0, y0, H, W) if env[r, c]]
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
        for r, c in seeds:
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
                "node_y_habitat": {"min": float(y_lo), "median": y_med, "max": float(y_hi)}, "n_nodes": len(ids),
                "height_bands": n_bands, "wall_cells": int(grid.sum()), "interior_area_m2": round(area, 1),
                "footprint_cells": int(footprint.sum()), "faces": int(len(fp.faces))}
        with open(os.path.join(out_dir, "floorplan.json"), "w") as f:
            json.dump(info, f, indent=2)
        written.append(sid)
        print(f"[{sid}] nodes={len(ids)} z=[{z_floor:.2f},{z_ceil:.2f}] walls={info['wall_cells']} interior={area:.1f} m2 faces={info['faces']}", flush=True)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="+", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mp3d_floors"))
    a = ap.parse_args()
    for s in a.scenes:
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
