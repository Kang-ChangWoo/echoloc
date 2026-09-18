#!/usr/bin/env python3
"""Floor-plan stand-in for a Matterport3D (mp3d) scene — the mp3d twin of
build_floorplan.py.

Same idea as the Replica builder: keep the walls, drop the furniture, extrude floor to
ceiling, so we can ask whether an IR in the bare box resembles the IR in the real mesh.
Three things differ from Replica and each one broke a naive port:

1. MULTI-FLOOR. 54 of the 83 mp3d scenes are buildings with 2-4 storeys; Replica scenes
   were all single-storey. A single floor/ceiling percentile over ALL vertices spans
   every storey at once, and the band-vote — "a wall is solid at EVERY height" — then
   finds nothing solid across the whole stack (the slab between storeys breaks it). So we
   CLUSTER the graph nodes by height into floors, and extract walls WITHIN each floor's
   own z-band, stacking the per-floor boxes into one mesh. The acoustic sim only ever
   places a listener on a graph node, so per-floor bands centred on the node heights are
   exactly the volumes that matter.

2. MESH IS A .glb, not mesh.ply. trimesh loads it as a Scene; concatenate. It comes in
   z-up (mesh z = height, verified against the graph nodes), same frame the Replica
   builder authored in, so the habitat=(tx,tz,-ty) mapping and the "do not rotate on
   export" rule carry over unchanged.

3. mp3d PATHS + CONFIG. Meshes under sound-spaces/data/scene_datasets/..., navmesh is a
   sibling .glb.navmesh, and the dataset config is mp3d.scene_dataset_config.json.

Outputs mirror the Replica builder: floorplan.glb + configs + occupancy/map PNGs + json.
Validation images are always written — the one bug that hid in every numeric check was
orientation, and it was obvious the instant someone looked at a frame.
"""
import argparse
import json
import os
import pickle

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage

MP3D = os.environ.get(
    "MP3D_MESH_DIR",
    "/file1/rvi/dataset/matterport/sound-spaces/data/scene_datasets/matterport/mp3d")
DATA_ROOT = os.environ.get("SS_DATA_ROOT", "/file2/changwoo/soundspaces")
CONFIG = os.path.join(MP3D, "mp3d.scene_dataset_config.json")

CELL = 0.05
CLOSE_RADIUS = 3
MAX_WALL_NZ = 0.35
WALL_PCTL = (2.0, 98.0)

BAND_BOTTOM = 0.35
BAND_TOP = 0.20
BAND_STEP = 0.20
BAND_FRACTION = 0.60

# Floor clustering: nodes whose heights sit within this gap are one storey. Storeys in
# mp3d are separated by ~2.5-3 m, and nodes on a storey vary by <0.3 m, so 1.0 m cleanly
# splits them without merging a tall stairwell landing into the storey above.
FLOOR_GAP = 1.0
FLOOR_HEIGHT = 2.7      # assumed storey height when the mesh gives no clear ceiling


def load_mesh(scene):
    path = os.path.join(MP3D, scene, f"{scene}.glb")
    mesh = trimesh.load(path, process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    return mesh


def graph_points(scene):
    """Graph nodes in habitat coords, plus their (row,col) helper — habitat (hx,hy,hz)."""
    with open(os.path.join(DATA_ROOT, "mp3d", "metadata", scene, "graph.pkl"), "rb") as f:
        g = pickle.load(f)
    return {n: np.asarray(g.nodes[n]["point"], dtype=float) for n in g.nodes()}


def cluster_floors(pts):
    """Split node heights (habitat y) into storeys. Returns list of (y_lo, y_hi, [ids])."""
    ys = sorted((p[1], n) for n, p in pts.items())
    floors, cur = [], [ys[0]]
    for y, n in ys[1:]:
        if y - cur[-1][0] > FLOOR_GAP:
            floors.append(cur)
            cur = []
        cur.append((y, n))
    floors.append(cur)
    out = []
    for f in floors:
        yy = [y for y, _ in f]
        ids = [n for _, n in f]
        out.append((min(yy), max(yy), ids))
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
    """Wall mask for ONE storey: cells solid across that storey's height bands only."""
    tri_all = mesh.vertices[mesh.faces]
    nz = np.abs(mesh.face_normals[:, 2])
    keep = nz < MAX_WALL_NZ
    tri = tri_all[keep]
    zmin = tri[:, :, 2].min(axis=1)
    zmax = tri[:, :, 2].max(axis=1)
    # only triangles whose vertical extent overlaps this storey
    band_lo, band_hi = z_floor + BAND_BOTTOM, z_ceil - BAND_TOP
    in_floor = (zmax >= band_lo) & (zmin <= band_hi)
    tri = tri[in_floor]
    zmin, zmax = zmin[in_floor], zmax[in_floor]

    edges = np.arange(band_lo, band_hi, BAND_STEP)
    if len(edges) == 0:
        edges = np.array([band_lo])
    votes = np.zeros((H, W), dtype=np.int32)
    for b in edges:
        sel = (zmax >= b) & (zmin <= b + BAND_STEP)
        band = _stamp(tri[sel], x0, y0, H, W)
        band = ndimage.binary_closing(band, structure=np.ones((CLOSE_RADIUS, CLOSE_RADIUS)))
        votes += band
    grid = votes >= max(1, int(round(BAND_FRACTION * len(edges))))
    grid = ndimage.binary_closing(grid, structure=np.ones((CLOSE_RADIUS, CLOSE_RADIUS)))
    return grid, len(edges)


def node_cells(ids, pts, x0, y0, H, W):
    """habitat -> grid (trimesh) frame: tx = hx, ty = -hz."""
    cells = []
    for n in ids:
        hx, _, hz = pts[n]
        c = int((hx - x0) / CELL)
        r = int((-hz - y0) / CELL)
        if 0 <= r < H and 0 <= c < W:
            cells.append((r, c))
    return cells


def navmesh_env(scene, x0, y0, H, W, agent_y):
    """Outer envelope for one storey from the scene navmesh, at height agent_y."""
    import habitat_sim
    glb = os.path.join(MP3D, scene, f"{scene}.glb")
    backend = habitat_sim.SimulatorConfiguration()
    backend.scene_id = glb
    if os.path.exists(CONFIG):
        backend.scene_dataset_config_file = CONFIG
    backend.enable_physics = False
    backend.load_semantic_mesh = False
    backend.create_renderer = False
    ac = habitat_sim.agent.AgentConfiguration()
    ac.sensor_specifications = []
    sim = habitat_sim.Simulator(habitat_sim.Configuration(backend, [ac]))
    navmesh = os.path.join(MP3D, scene, f"{scene}.navmesh")
    if not sim.pathfinder.is_loaded and os.path.exists(navmesh):
        sim.pathfinder.load_nav_mesh(navmesh)
    nav = np.zeros((H, W), dtype=bool)
    if sim.pathfinder.is_loaded:
        for r in range(H):
            ty = y0 + (r + 0.5) * CELL
            for c in range(W):
                tx = x0 + (c + 0.5) * CELL
                nav[r, c] = sim.pathfinder.is_navigable([tx, agent_y, -ty], 2.0)
    sim.close()
    if not nav.any():
        return None
    env = ndimage.binary_fill_holes(nav)
    env = ndimage.binary_dilation(env, iterations=int(round(0.6 / CELL)))
    return env


def boxes_from_grid(grid, x0, y0, z_floor, z_ceil, parts):
    h = z_ceil - z_floor
    ys, xs = np.where(grid)
    for row in np.unique(ys):
        cols = np.sort(xs[ys == row])
        for run in np.split(cols, np.where(np.diff(cols) != 1)[0] + 1):
            if run.size == 0:
                continue
            wx = run.size * CELL
            cxm = x0 + (run[0] + run.size / 2) * CELL
            cym = y0 + (row + 0.5) * CELL
            box = trimesh.creation.box(extents=(wx, CELL, h))
            box.apply_translation((cxm, cym, z_floor + h / 2))
            parts.append(box)


def write_configs(out_dir, glb_name):
    stage = {"render_asset": glb_name, "collision_asset": glb_name,
             "requires_lighting": False, "up": [0, 0, 1], "front": [0, 1, 0],
             "origin": [0, 0, 0]}
    with open(os.path.join(out_dir, "floorplan.stage_config.json"), "w") as f:
        json.dump(stage, f, indent=2)
    dataset = {"stages": {"paths": {".json": ["*.stage_config.json"]}},
               "objects": {}, "light_setups": {},
               "scene_instances": {"default_attributes": {"default_lighting": "no_lights"}}}
    with open(os.path.join(out_dir, "floorplan.scene_dataset_config.json"), "w") as f:
        json.dump(dataset, f, indent=2)


def build(scene, out_root, with_navmesh=True):
    out_dir = os.path.join(out_root, scene)
    os.makedirs(out_dir, exist_ok=True)

    mesh = load_mesh(scene)
    pts = graph_points(scene)
    v = mesh.vertices
    x0, y0 = v[:, 0].min(), v[:, 1].min()
    x1, y1 = v[:, 0].max(), v[:, 1].max()
    W = int(np.ceil((x1 - x0) / CELL)) + 1
    H = int(np.ceil((y1 - y0) / CELL)) + 1

    floors = cluster_floors(pts)
    parts = []
    interior_total = np.zeros((H, W), dtype=bool)
    grid_total = np.zeros((H, W), dtype=bool)
    n_bands_all = []

    for fi, (y_lo, y_hi, ids) in enumerate(floors):
        # storey vertical band in the mesh's z (= habitat y): floor at the node height,
        # ceiling a storey up (or the next floor, whichever is closer).
        z_floor = y_lo - 0.1
        z_ceil = y_hi + FLOOR_HEIGHT if len(floors) == 1 else \
            min(y_lo + FLOOR_HEIGHT, floors[fi + 1][0] - 0.1) if fi + 1 < len(floors) \
            else y_lo + FLOOR_HEIGHT

        grid, n_bands = occupancy_for_floor(mesh, x0, y0, H, W, z_floor, z_ceil)
        n_bands_all.append(n_bands)

        if with_navmesh:
            env = navmesh_env(scene, x0, y0, H, W, agent_y=(y_lo + y_hi) / 2 + 0.1)
            if env is not None:
                seal = ndimage.binary_dilation(env) & ~env
                grid = grid | seal
                grid[~ndimage.binary_dilation(env, iterations=2)] = False

        # interior = free space reachable from this floor's nodes
        free = ~grid
        labels, _ = ndimage.label(free)
        seeds = node_cells(ids, pts, x0, y0, H, W)
        keep = {labels[r, c] for r, c in seeds if labels[r, c] > 0}
        interior = np.isin(labels, list(keep)) if keep else np.zeros_like(grid)

        boxes_from_grid(grid, x0, y0, z_floor, z_ceil, parts)
        # per-floor slabs
        fx, fy = W * CELL, H * CELL
        cx, cy = x0 + fx / 2, y0 + fy / 2
        for zc in (z_floor - 0.025, z_ceil + 0.025):
            slab = trimesh.creation.box(extents=(fx, fy, 0.05))
            slab.apply_translation((cx, cy, zc))
            parts.append(slab)

        interior_total |= interior
        grid_total |= grid

    fp = trimesh.util.concatenate(parts)
    glb = os.path.join(out_dir, "floorplan.glb")
    fp.export(glb)                       # do NOT rotate: habitat's importer applies -90 X
    write_configs(out_dir, "floorplan.glb")

    # top-down map: rooms white, walls+exterior black, nodes red
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[interior_total] = (245, 245, 245)
    allcells = []
    for _, _, ids in floors:
        allcells += node_cells(ids, pts, x0, y0, H, W)
    for r, c in allcells:
        rgb[max(0, r - 1):r + 2, max(0, c - 1):c + 2] = (220, 40, 40)
    Image.fromarray(np.flipud(rgb)).resize((W * 3, H * 3), Image.NEAREST).save(
        os.path.join(out_dir, "floorplan_map.png"))
    Image.fromarray((np.flipud(grid_total) * 255).astype(np.uint8)).save(
        os.path.join(out_dir, "occupancy.png"))

    info = {"scene": scene, "floors": len(floors),
            "floor_heights": [round(float(f[0]), 2) for f in floors],
            "nodes": len(pts), "cell_m": CELL, "grid": [H, W],
            "wall_cells": int(grid_total.sum()),
            "interior_area_m2": round(float(interior_total.sum()) * CELL ** 2, 1),
            "faces": int(len(fp.faces)), "height_bands": n_bands_all}
    with open(os.path.join(out_dir, "floorplan.json"), "w") as f:
        json.dump(info, f, indent=2)
    print(f"[{scene}] floors={len(floors)} nodes={len(pts)} walls={info['wall_cells']} "
          f"interior={info['interior_area_m2']}m2 faces={info['faces']}", flush=True)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="+", required=True)
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "out_mp3d"))
    ap.add_argument("--no-navmesh", action="store_true")
    args = ap.parse_args()
    for s in args.scenes:
        try:
            build(s, args.out, with_navmesh=not args.no_navmesh)
        except Exception as e:
            print(f"[{s}] FAILED: {e}", flush=True)


if __name__ == "__main__":
    main()
