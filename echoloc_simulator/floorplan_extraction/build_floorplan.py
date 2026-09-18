#!/usr/bin/env python3
"""
[echoloc_simulator] moved here from ~/workspace/test/floorplan_vs_mesh (2026-09-08); outputs for
Replica are in ./replica/<scene>/ and for MP3D in ./mp3d/<scene>/. Runs in the ss_v2 env (env.sh).
2026-09-08 fix: grid padded by MARGIN_M so the navmesh sealing ring cannot fall outside the grid
(room_0/room_2 were open at the bbox border), and the envelope is intersected with the scan
footprint so navmesh areas without scanned geometry (apartment_1/2) are exterior.

Build a "floor plan" stand-in for a Replica scene: walls only, extruded floor to
ceiling, no furniture.

The question this serves: does an IR rendered in a floor-plan box resemble the IR
rendered in the real, cluttered mesh at the same spot?

How the plan is extracted
-------------------------
Slicing the mesh at head height would catch sofas, tables and shelves — exactly
the clutter a floor plan is supposed to omit. So we take a slab just BELOW the
ceiling, where (almost) the only geometry left is wall:

    slab = [ceiling - SLAB_TOP, ceiling - SLAB_BOTTOM]

Triangles intersecting that slab are rasterized top-down into an occupancy grid,
morphologically closed to seal scanner gaps, and every occupied cell becomes a
box spanning floor->ceiling. Floor and ceiling slabs are added as two more boxes.
The result is watertight enough for acoustic ray tracing and carries no furniture.

Axis convention (from build_square_rooms.py — habitat's glTF importer rotates -90
about X relative to trimesh's frame):

    (habitat_x, habitat_y, habitat_z) = (trimesh_x, trimesh_z, -trimesh_y)

so we author in trimesh coords and the exported glb lands upright in habitat.

Outputs (per scene):
    <out>/<scene>/floorplan.glb
    <out>/<scene>/floorplan.stage_config.json
    <out>/<scene>/floorplan.scene_dataset_config.json
    <out>/<scene>/occupancy.png        top-down wall mask (sanity check)
    <out>/<scene>/interior.png         sealed free space (rooms), same layout
    <out>/<scene>/floorplan.json       bounds, heights, cell size, wall cell count
"""
import argparse
import json
import os

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage

from materials import mixed_default_config

RAW_DIR = os.environ.get("REPLICA_RAW_DIR", "/file1/rvi/dataset/replica/raw")
DATA_ROOT = os.environ.get("SS_DATA_ROOT", "/file2/changwoo/soundspaces")

CELL = 0.05          # metres per occupancy cell
MARGIN_M = 1.0       # grid padding around the mesh bbox so the sealing ring always fits inside the grid
FOOTPRINT_CLOSE = 5  # cells; mesh footprint (any height) closing — rooms without scanned geometry are outdoors
CLOSE_RADIUS = 3     # cells; seals scan holes in walls
MAX_WALL_NZ = 0.35   # |normal_z| below this counts as a wall, not floor/ceiling
WALL_PCTL = (2.0, 98.0)   # robust floor/ceiling percentiles (ignore stray verts)

# A wall is what is solid at EVERY height. Furniture only occupies low bands; the
# lintel above a door only occupies high ones. Requiring a cell to be occupied in
# nearly all bands therefore keeps the walls, drops the furniture, and — the part
# that matters acoustically — leaves doorways OPEN.
BAND_BOTTOM = 0.35   # first band starts this far above the floor
BAND_TOP = 0.20      # last band ends this far below the ceiling
BAND_STEP = 0.20     # band thickness / spacing, metres
# Threshold on the band vote. A true wall scores near 1.0 (minus sampling gaps);
# furniture and door lintels each only reach ~0.3, since each lives in one end of
# the height range. 0.6 sits in the empty gap between those two populations.
BAND_FRACTION = 0.60


def load_mesh(scene):
    """The plain mesh.ply — mesh_semantic.ply uses Replica's custom face format
    that trimesh does not parse."""
    path = os.path.join(RAW_DIR, scene, "mesh.ply")
    mesh = trimesh.load(path, process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    return mesh


def _stamp(tri, x0, y0, H, W):
    """Top-down mask of a triangle set: stamp vertices, edge midpoints, centroid.
    At 5 cm cells and Replica's dense triangulation that covers surfaces without
    a full rasterizer."""
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


def occupancy_from_slab(mesh):
    """Top-down wall mask: cells that are solid across (nearly) all heights.

    Replica meshes are authored z-up, matching trimesh's frame here: vertical is
    the mesh's z, the floor plan lives in (x, y).

    Two filters, and both are load-bearing:

    1. Near-horizontal normals only (|n_z| < MAX_WALL_NZ). Ceilings of lower
       rooms otherwise slice into the mask and fill it solid.
    2. Occupied in >= BAND_FRACTION of the height bands. A single slab cannot
       tell a wall from clutter: slice low and the sofas come along, slice high
       and you pick up the lintel above every door — which, once extruded floor
       to ceiling, SEALS the doorway and turns the flat into a set of airtight
       boxes. That is acoustically wrong: it deletes the room-to-room coupling.
       A wall is solid at every height; furniture only low; a lintel only high.
       Intersecting the bands keeps walls, drops furniture, and leaves doorways
       open.
    """
    v = mesh.vertices
    z_floor, z_ceil = np.percentile(v[:, 2], WALL_PCTL)

    tri_all = v[mesh.faces]                          # (F, 3, 3)
    nz = np.abs(mesh.face_normals[:, 2])
    tri_all = tri_all[nz < MAX_WALL_NZ]              # walls only
    zmin = tri_all[:, :, 2].min(axis=1)
    zmax = tri_all[:, :, 2].max(axis=1)

    x0, y0 = v[:, 0].min() - MARGIN_M, v[:, 1].min() - MARGIN_M
    x1, y1 = v[:, 0].max() + MARGIN_M, v[:, 1].max() + MARGIN_M
    W = int(np.ceil((x1 - x0) / CELL)) + 1
    H = int(np.ceil((y1 - y0) / CELL)) + 1
    # Footprint of the whole scan (walls, floor, ceiling, anything): cells with no
    # geometry at any height are outside the scanned volume. The navmesh can extend
    # there (Replica navmeshes sometimes do), and a camera placed there sees nothing.
    footprint = ndimage.binary_closing(_stamp(v[mesh.faces], x0, y0, H, W),
                                       structure=np.ones((FOOTPRINT_CLOSE, FOOTPRINT_CLOSE)))
    footprint = ndimage.binary_fill_holes(footprint)

    lo = z_floor + BAND_BOTTOM
    hi = z_ceil - BAND_TOP
    edges = np.arange(lo, hi, BAND_STEP)
    votes = np.zeros((H, W), dtype=np.int32)
    for b in edges:
        sel = (zmax >= b) & (zmin <= b + BAND_STEP)
        band = _stamp(tri_all[sel], x0, y0, H, W)
        band = ndimage.binary_closing(band, structure=np.ones((CLOSE_RADIUS, CLOSE_RADIUS)))
        votes += band

    grid = votes >= max(1, int(round(BAND_FRACTION * len(edges))))
    grid = ndimage.binary_closing(grid, structure=np.ones((CLOSE_RADIUS, CLOSE_RADIUS)))
    return grid, (x0, y0, float(z_floor), float(z_ceil)), len(edges), footprint


def node_cells(scene, origin, grid_shape):
    """SoundSpaces graph nodes as (row, col) grid cells.

    The nodes are in habitat coords; the grid is in the mesh's own (trimesh) frame.
    build_square_rooms.py records the mapping habitat = (tx, tz, -ty), so going the
    other way: tx = hx, ty = -hz.
    """
    path = os.path.join(DATA_ROOT, "replica", "metadata", scene, "graph.pkl")
    if not os.path.exists(path):
        return []
    import pickle
    with open(path, "rb") as f:
        g = pickle.load(f)

    x0, y0 = origin
    H, W = grid_shape
    cells = []
    for n in g.nodes():
        hx, _, hz = g.nodes()[n]["point"]
        c = int((hx - x0) / CELL)
        r = int((-hz - y0) / CELL)
        if 0 <= r < H and 0 <= c < W:
            cells.append((r, c))
    return cells


def navmesh_envelope(scene, origin, grid_shape, agent_y):
    """The building's outer envelope, from the scene's navmesh.

    The wall mask alone does not enclose anything: Replica's scans have gaps
    (windows, unscanned corners), so free space leaks straight out of the flat and
    the "room" would be an open field — acoustically far too dry. The navmesh is
    the walkable floor, so filling its holes (furniture) and dilating gives the
    envelope the walls must sit inside. Everything outside it is solid.
    """
    import habitat_sim

    mesh = os.path.join(RAW_DIR, scene, "habitat", "mesh_semantic.ply")
    backend = habitat_sim.SimulatorConfiguration()
    backend.scene_id = mesh
    backend.scene_dataset_config_file = os.path.join(RAW_DIR, "replica.scene_dataset_config.json")
    backend.enable_physics = False
    backend.load_semantic_mesh = False
    agent_cfg = habitat_sim.agent.AgentConfiguration()
    agent_cfg.sensor_specifications = []
    sim = habitat_sim.Simulator(habitat_sim.Configuration(backend, [agent_cfg]))

    navmesh = os.path.join(RAW_DIR, scene, "habitat", "mesh_semantic.navmesh")
    if not sim.pathfinder.is_loaded:
        sim.pathfinder.load_nav_mesh(navmesh)

    x0, y0 = origin
    H, W = grid_shape
    nav = np.zeros((H, W), dtype=bool)
    for r in range(H):
        ty = y0 + (r + 0.5) * CELL
        for c in range(W):
            tx = x0 + (c + 0.5) * CELL
            # grid (trimesh) -> habitat: hx = tx, hz = -ty
            nav[r, c] = sim.pathfinder.is_navigable([tx, agent_y, -ty], 2.0)
    sim.close()

    env = ndimage.binary_fill_holes(nav)                       # furniture holes -> floor
    env = ndimage.binary_dilation(env, iterations=int(round(0.6 / CELL)))  # out to the walls
    return env


def interior_from_nodes(grid, origin, scene, env=None):
    """Free space connected to a graph node: the rooms, excluding the outdoors.
    Seeds outside the sealed envelope (nodes on unscanned outdoor navmesh) would
    flood the exterior, so they are dropped when `env` is given."""
    free = ~grid
    labels, _ = ndimage.label(free)
    seeds = node_cells(scene, origin, grid.shape)
    if env is not None:
        seeds = [(r, c) for r, c in seeds if env[r, c]]
    keep = {labels[r, c] for r, c in seeds if labels[r, c] > 0}
    if not keep:
        return np.zeros_like(grid)
    return np.isin(labels, list(keep))


def boxes_from_grid(grid, origin, z_floor, z_ceil):
    """One floor->ceiling box per occupied cell, plus floor and ceiling slabs.

    Neighbouring boxes are merged by run-length along x so the mesh stays small.
    """
    x0, y0 = origin
    h = z_ceil - z_floor
    parts = []

    ys, xs = np.where(grid)
    runs = 0
    for row in np.unique(ys):
        cols = np.sort(xs[ys == row])
        # split the row's occupied cells into contiguous runs
        splits = np.split(cols, np.where(np.diff(cols) != 1)[0] + 1)
        for run in splits:
            if run.size == 0:
                continue
            runs += 1
            wx = run.size * CELL
            cxm = x0 + (run[0] + run.size / 2) * CELL
            cym = y0 + (row + 0.5) * CELL
            box = trimesh.creation.box(extents=(wx, CELL, h))
            box.apply_translation((cxm, cym, z_floor + h / 2))
            parts.append(box)

    H, W = grid.shape
    fx, fy = W * CELL, H * CELL
    cx, cy = x0 + fx / 2, y0 + fy / 2
    floor = trimesh.creation.box(extents=(fx, fy, 0.05))
    floor.apply_translation((cx, cy, z_floor - 0.025))
    ceil = trimesh.creation.box(extents=(fx, fy, 0.05))
    ceil.apply_translation((cx, cy, z_ceil + 0.025))
    parts += [floor, ceil]

    return trimesh.util.concatenate(parts), runs


def write_configs(out_dir, glb_name):
    stage = {
        "render_asset": glb_name,
        "collision_asset": glb_name,
        "requires_lighting": False,
        "up": [0, 0, 1],
        "front": [0, 1, 0],
        "origin": [0, 0, 0],
    }
    with open(os.path.join(out_dir, "floorplan.stage_config.json"), "w") as f:
        json.dump(stage, f, indent=2)

    dataset = {
        "stages": {"paths": {".json": ["*.stage_config.json"]}},
        "objects": {}, "light_setups": {},
        "scene_instances": {"default_attributes": {"default_lighting": "no_lights"}},
    }
    with open(os.path.join(out_dir, "floorplan.scene_dataset_config.json"), "w") as f:
        json.dump(dataset, f, indent=2)


def build(scene, out_root):
    out_dir = os.path.join(out_root, scene)
    os.makedirs(out_dir, exist_ok=True)

    mesh = load_mesh(scene)
    grid, (x0, y0, z_floor, z_ceil), n_bands, footprint = occupancy_from_slab(mesh)

    # Where the mesh-derived walls fail to enclose the flat, sound would pour out
    # of the model. Seal the outer envelope (from the navmesh) with a ring of wall.
    env = navmesh_envelope(scene, (x0, y0), grid.shape, agent_y=z_ceil - 1.2)
    env &= footprint                                            # never outside the scanned volume
    env = ndimage.binary_fill_holes(env)
    leak = interior_from_nodes(grid, (x0, y0), scene, env) & ~env   # free space that escaped
    seal = ndimage.binary_dilation(env) & ~env                 # one-cell ring around it
    grid = grid | seal
    grid[~ndimage.binary_dilation(env, iterations=2)] = False  # drop stray far-out cells

    fp, n_runs = boxes_from_grid(grid, (x0, y0), z_floor, z_ceil)

    # Do NOT rotate here. habitat-sim's glTF importer already applies -90 deg about
    # X, i.e. habitat = (tx, tz, -ty); build_square_rooms.py exports its z-up boxes
    # untouched for exactly this reason. Rotating first double-applies it and the
    # room comes out lying on its side — the listener then sits outside the box and
    # the IR collapses to the direct path alone.
    glb = os.path.join(out_dir, "floorplan.glb")
    fp.export(glb)

    # The plan carries no semantics, so RLR gives every surface the Default material.
    # Make that Default the area-weighted mix of the surfaces the plan actually has.
    nz = np.abs(fp.face_normals[:, 2])
    area = fp.area_faces
    wall_area = float(area[nz < MAX_WALL_NZ].sum())
    horiz = area[nz > 0.9]
    # floor and ceiling slabs are boxes, so each contributes its top and bottom face
    flat_area = float(horiz.sum()) / 2.0
    mat_info = mixed_default_config(
        {"wall": wall_area, "floor": flat_area / 2, "ceiling": flat_area / 2},
        os.path.join(out_dir, "floorplan_material_config.json"))

    # "Inside" cannot be found by hole-filling: Replica scans have open boundaries
    # (a doorway leading out of the scanned volume), so the rooms leak to the image
    # border and nothing reads as enclosed. Flood-fill from the SoundSpaces graph
    # nodes instead — those are, by construction, points a person stands on.
    interior = interior_from_nodes(grid, (x0, y0), scene, env)

    # Read it as a floor plan: rooms white, walls and everything outside black.
    # `leak` (the free space the raw wall mask failed to enclose) is all outdoors,
    # so painting it would just turn the exterior orange — it goes in the separate
    # leak_diagnostic.png instead.
    rgb = np.zeros(grid.shape + (3,), dtype=np.uint8)   # black: walls + exterior
    rgb[interior] = (245, 245, 245)                     # enclosed rooms

    # Graph nodes: the poses the RIRs and the images were rendered at.
    for r, c in node_cells(scene, (x0, y0), grid.shape):
        rr = slice(max(0, r - 1), r + 2)
        cc = slice(max(0, c - 1), c + 2)
        rgb[rr, cc] = (220, 40, 40)

    Image.fromarray(np.flipud(rgb)).resize(
        (grid.shape[1] * 3, grid.shape[0] * 3), Image.NEAREST
    ).save(os.path.join(out_dir, "floorplan_map.png"))
    Image.fromarray((np.flipud(grid) * 255).astype(np.uint8)).save(
        os.path.join(out_dir, "occupancy.png"))
    # The sealed interior (rooms reachable from in-envelope graph nodes), same layout
    # as occupancy.png. Downstream map builders must use THIS as free space rather
    # than re-flooding from the graph nodes (nodes on unscanned outdoor navmesh exist).
    Image.fromarray((np.flipud(interior) * 255).astype(np.uint8)).save(
        os.path.join(out_dir, "interior.png"))

    # Diagnostic: where the mesh-derived walls leaked, and what the navmesh ring sealed.
    diag = np.zeros(grid.shape + (3,), dtype=np.uint8)
    diag[env] = (60, 70, 85)          # navmesh envelope
    diag[leak] = (232, 140, 60)       # free space that escaped it (now sealed)
    diag[interior] = (245, 245, 245)
    diag[grid] = (15, 15, 15)
    Image.fromarray(np.flipud(diag)).resize(
        (grid.shape[1] * 3, grid.shape[0] * 3), Image.NEAREST
    ).save(os.path.join(out_dir, "leak_diagnostic.png"))

    area = float(interior.sum()) * CELL ** 2
    info = {
        "scene": scene,
        "cell_m": CELL,
        "grid": list(grid.shape),
        "origin_xy": [float(x0), float(y0)],
        "z_floor": z_floor,
        "z_ceiling": z_ceil,
        "room_height_m": round(z_ceil - z_floor, 3),
        "height_bands": n_bands,
        "wall_cells": int(grid.sum()),
        "leak_cells": int(leak.sum()),
        "margin_m": MARGIN_M,
        "footprint_cells": int(footprint.sum()),
        "interior_area_m2": round(area, 1),
        "interior_volume_m3": round(area * (z_ceil - z_floor), 1),
        "wall_runs": n_runs,
        "faces": int(len(fp.faces)),
        "material_mix": mat_info,
    }
    with open(os.path.join(out_dir, "floorplan.json"), "w") as f:
        json.dump(info, f, indent=2)

    print(f"[{scene}] height={info['room_height_m']}m  bands={n_bands}  "
          f"walls={info['wall_cells']} cells  interior={info['interior_area_m2']} m2 "
          f"({info['interior_volume_m3']} m3)  faces={info['faces']}")
    return info


def main():
    ap = argparse.ArgumentParser(description="Extract a furniture-free floor-plan mesh.")
    ap.add_argument("--scenes", nargs="+", default=["room_1", "office_3", "frl_apartment_2"])
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    args = ap.parse_args()
    for s in args.scenes:
        build(s, args.out)


if __name__ == "__main__":
    main()
