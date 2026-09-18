#!/usr/bin/env python3
"""Structured3D -> echoloc (F3Loc-compatible) importer.  Profile: ECHOLOC_DATASET=s3d

Structured3D ships no mesh: per scene an annotation_3d.json (wall/floor/ceiling planes,
junctions in mm, z-up) and perspective renders at fixed camera positions
(rgb_rawlight.png 1280x720, depth.png uint16 mm, camera_pose.txt). So, per scene:

  maps/<scene>/map.png            0.01 m/px = 0.05 m wall grid x5 (walls 1 cell = 5 cm), free = 255
                                  (room floor polygons), doors re-opened, windows stay wall,
                                  everything outside the rooms = 0.  Origin = map centre.
  maps/<scene>/scene_meta.json    same keys as the Replica/MP3D builders
  floorplan_proxy/<scene>/floorplan.glb   the map's wall cells (0.05 m) extruded 0..ceiling +
                                  floor/ceiling slabs -> the only acoustic geometry (floorplan_closed)
  <collection>/<scene>/rgb/{i:05d}.png    640x360, gravity-aligned (F3Loc utils.gravity_align)
  <collection>/<scene>/depth_radial_scan/{i:05d}.png   S3D depth.png (planar z, mm) -> RADIAL range, 640x360,
                                  gravity-aligned like the rgb, uint16 mm (the furnished render = the 'scan')
  <collection>/<scene>/poses.txt  x y yaw (metres / rad, CCW from +x)  one line per image
  <collection>/<scene>/chunks.json   L = 0: every frame is its own chunk (single view); per frame
                                  roll, pitch, camera height, room id, S3D position id, habitat pose

Camera: xfov/yfov from camera_pose.txt (half angles; 0.698 rad -> HFOV 80 deg),
K640 = [[320/tan(xfov),0,320],[0,180/tan(yfov),180],[0,0,1]]  ->  F_W = 0.596 (NOT 3/8).
Yaw/pitch/roll from the view and up vectors exactly as F3Loc's viewmap_s3d.py does.

Coordinates: S3D (X, Y, Z) mm z-up.  world x = X/1000 - cx, y = Y/1000 - cy (cx, cy = map
centre).  The proxy is authored z-up in metres and exported untouched, so habitat =
(X, Z, -Y) and the usual world<->habitat formulas hold (world_cx_habitat = cx, ...).
Habitat 'hab' y is stored as camera_z - CAM_HEIGHT so the renderers' fixed sensor offset
puts the sensor/source exactly at the S3D camera height.

Usage:  ECHOLOC_DATASET=s3d python build_s3d.py [--scenes scene_00000 ...] [--collection s3d]
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage
from scipy.spatial.transform import Rotation

import common as C

assert C.DATASET == "s3d", "run with ECHOLOC_DATASET=s3d"
C.f3loc_import()
sys.path.insert(0, os.path.join(C.F3LOC, "s3d", "process"))
from s3d_utils import read_s3d_floorplan          # noqa: E402  (F3Loc, borrowed from LASER)
from utils.utils import gravity_align             # noqa: E402

MARGIN_M = 1.0
CELL = 0.05
MIN_CLEARANCE = 0.02     # m; S3D cameras can sit inside a wall's 5 cm cell edge -> proxy near-plane leaks; skip those frames


def parse_pose(line):
    v = [float(x) for x in line.split()]
    pos = np.array(v[0:3]) / 1000.0
    t = np.array(v[3:6]); t /= np.linalg.norm(t)
    u = np.array(v[6:9]); u /= np.linalg.norm(u)
    w = np.cross(u, t)
    u2 = np.cross(t, w)
    R = np.stack([t, w, u2], axis=1)
    yaw, pitch, roll = Rotation.from_matrix(R).as_euler("ZYX")
    return pos, float(yaw), float(pitch), float(roll), float(v[9]), float(v[10])


def build_map(annos):
    """-> occ (H, W) uint8 at MAP_RES (kron of a CELL grid), (x_min_m, y_min_m), z_ceil_m, n_rooms, grid.
    Walls are rasterised on the 0.05 m grid (1 cell thick) and upsampled x5 like the Replica/MP3D
    maps, so the acoustic proxy (boxes of the same cells) and the map agree exactly."""
    n_rooms, room_lines, door_lines, window_lines = read_s3d_floorplan(annos)
    junctions = np.array([j["coordinate"] for j in annos["junctions"]]) / 1000.0
    z_ceil = float(np.percentile(junctions[:, 2], 98)) if len(junctions) else 2.8
    if z_ceil < 2.0:
        z_ceil = 2.8
    pts = room_lines.reshape(-1, 2)
    x_min, y_min = pts.min(0) - MARGIN_M
    x_max, y_max = pts.max(0) + MARGIN_M
    Wc = int(np.ceil((x_max - x_min) / CELL)) + 1
    Hc = int(np.ceil((y_max - y_min) / CELL)) + 1
    to_c = lambda p: np.floor((p - [x_min, y_min]) / CELL).astype(np.int32)
    free = np.zeros((Hc, Wc), np.uint8)
    polys, cur = [], [room_lines[0][0]]
    for a, b in room_lines:
        if not np.allclose(a, cur[-1]):
            polys.append(np.array(cur)); cur = [a]
        cur.append(b)
    polys.append(np.array(cur))
    for poly in polys:
        if len(poly) >= 3:
            cv2.fillPoly(free, [to_c(poly)], 1)
    wall = np.zeros((Hc, Wc), np.uint8)
    for a, b in room_lines:                      # LINE_4: 4-connected cells, otherwise diagonally touching
        cv2.line(wall, tuple(to_c(a)), tuple(to_c(b)), 1, 1, lineType=cv2.LINE_4)   # boxes leave edge gaps for 3D rays
    grid = wall.astype(bool)
    # exterior = outside the building footprint. Rooms are separated by wall-thickness gaps that
    # belong to no room polygon, so "not in any room" is NOT exterior: close the room mask with a
    # kernel wider than a wall (9 cells = 45 cm) and fill holes to get the footprint.
    footprint = ndimage.binary_fill_holes(ndimage.binary_closing(free.astype(bool), structure=np.ones((9, 9))))
    exterior = ~footprint
    # doors: one polygon each (consecutive door lines share vertices). A door between two rooms
    # is opened (its cells become free); a door bordering the exterior (entrance / unannotated
    # space) stays wall, because the map treats the exterior as obstacle and the proxy has no
    # exterior walls -> rays would leak there.
    dpolys, cur = [], [door_lines[0][0]] if len(door_lines) else []
    for a, b in door_lines:
        if not np.allclose(a, cur[-1]):
            dpolys.append(np.array(cur)); cur = [a]
        cur.append(b)
    if cur:
        dpolys.append(np.array(cur))
    n_open = n_solid = 0
    for poly in dpolys:
        if len(poly) < 3:
            continue
        m = np.zeros((Hc, Wc), np.uint8)
        cv2.fillPoly(m, [to_c(poly)], 1)
        for a, b in zip(poly[:-1], poly[1:]):
            cv2.line(m, tuple(to_c(a)), tuple(to_c(b)), 1, 1, lineType=cv2.LINE_4)
        m = m.astype(bool)
        if (ndimage.binary_dilation(m, structure=np.ones((3, 3))) & exterior).any():
            n_solid += 1
            continue
        grid &= ~m
        free[m] = 1
        n_open += 1
    free_cells = free.astype(bool) & ~grid
    # proxy geometry = every map obstacle cell that borders free space (wall lines AND the
    # wall-thickness gap edges), so the acoustic proxy and the map ray cast agree exactly
    grid = ~free_cells & ndimage.binary_dilation(free_cells, structure=np.ones((3, 3)))
    occ = np.kron(np.where(free_cells, 255, 0).astype(np.uint8), np.ones((int(round(CELL / C.MAP_RES)),) * 2, np.uint8))
    return occ, (float(x_min), float(y_min)), z_ceil, len(polys), grid, (n_open, n_solid)


def proxy_from_grid(grid, origin, z_ceil):
    """Wall cells (0.05 m) -> boxes 0..z_ceil, plus floor/ceiling slabs over the grid extent."""
    x0, y0 = origin
    Hc, Wc = grid.shape
    parts = []
    ys, xs = np.where(grid)
    for row in np.unique(ys):
        cols = np.sort(xs[ys == row])
        for run in np.split(cols, np.where(np.diff(cols) != 1)[0] + 1):
            if run.size == 0:
                continue
            box = trimesh.creation.box(extents=(run.size * CELL, CELL, z_ceil))
            box.apply_translation((x0 + (run[0] + run.size / 2) * CELL, y0 + (row + 0.5) * CELL, z_ceil / 2))
            parts.append(box)
    fx, fy = Wc * CELL, Hc * CELL
    for zc in (-0.025, z_ceil + 0.025):
        slab = trimesh.creation.box(extents=(fx, fy, 0.05))
        slab.apply_translation((x0 + fx / 2, y0 + fy / 2, zc))
        parts.append(slab)
    return trimesh.util.concatenate(parts), int(grid.sum())


def build(scene, collection):
    raw = os.path.join(C.RAW_DIR, scene)
    annos = json.load(open(os.path.join(raw, "annotation_3d.json")))
    occ, (x0, y0), z_ceil, n_rooms, grid, (n_open, n_solid) = build_map(annos)
    H, W = occ.shape
    cx, cy = x0 + W / 2 * C.MAP_RES, y0 + H / 2 * C.MAP_RES
    mdir = os.path.join(C.ROOT, "maps", scene); os.makedirs(mdir, exist_ok=True)
    Image.fromarray(np.repeat(occ[:, :, None], 3, axis=2)).save(os.path.join(mdir, "map.png"))
    pdir = os.path.join(C.PROXY_DIR, scene); os.makedirs(pdir, exist_ok=True)
    proxy, n_cells = proxy_from_grid(grid, (x0, y0), z_ceil)
    proxy.export(os.path.join(pdir, "floorplan.glb"))

    # frames: every perspective position, sorted by (room, position)
    clearance = ndimage.distance_transform_edt(occ == 255) * C.MAP_RES
    frames, skipped, skipped_wall = [], 0, 0
    rooms = sorted(d for d in os.listdir(os.path.join(raw, "2D_rendering")))
    for room in rooms:
        pdir_r = os.path.join(raw, "2D_rendering", room, "perspective", "full")
        if not os.path.isdir(pdir_r):
            continue
        for pos_id in sorted(os.listdir(pdir_r), key=int):
            d = os.path.join(pdir_r, pos_id)
            if not all(os.path.exists(os.path.join(d, f)) for f in ("camera_pose.txt", "rgb_rawlight.png", "depth.png")):
                continue
            pos, yaw, pitch, roll, xfov, yfov = parse_pose(open(os.path.join(d, "camera_pose.txt")).readline())
            x, y = pos[0] - cx, pos[1] - cy
            r, c = C.world_to_map(x, y, occ.shape)
            ri, ci = int(np.floor(r)), int(np.floor(c))
            if not (0 <= ri < H and 0 <= ci < W) or occ[ri, ci] != 255:
                skipped += 1
                continue
            if clearance[ri, ci] < MIN_CLEARANCE:
                skipped_wall += 1
                continue
            frames.append({"x": float(x), "y": float(y), "yaw": float(C.wrap(yaw)), "pitch": pitch, "roll": roll,
                           "cam_z": float(pos[2]), "xfov": xfov, "yfov": yfov, "room": room, "pos_id": int(pos_id),
                           "hab": [float(pos[0]), float(pos[2] - C.CAM_HEIGHT), float(-pos[1])],
                           "theta": float(C.yaw_to_habitat_theta(C.wrap(yaw))), "src": d})
    if not frames:
        print(f"[{scene}] no usable frames, skipped", flush=True)
        return None

    sd = C.scene_dir(collection, scene)
    os.makedirs(os.path.join(sd, "rgb"), exist_ok=True)
    os.makedirs(os.path.join(sd, "depth_radial_scan"), exist_ok=True)
    K = np.array([[C.FX, 0, C.IMG_W / 2], [0, C.FY, C.IMG_H / 2], [0, 0, 1]], np.float32)
    for i, fr in enumerate(frames):
        out = os.path.join(sd, "rgb", f"{i:05d}.png")
        if not os.path.exists(out):
            img = cv2.imread(os.path.join(fr["src"], "rgb_rawlight.png"), cv2.IMREAD_COLOR)
            img = cv2.resize(img, (C.IMG_W, C.IMG_H), interpolation=cv2.INTER_AREA)
            img = gravity_align(img, r=fr["roll"], p=fr["pitch"], K=K)
            cv2.imwrite(out, img)
        outd = os.path.join(sd, "depth_radial_scan", f"{i:05d}.png")
        if not os.path.exists(outd):
            # S3D depth.png = planar z in mm (verified: horizon pixels match z, not range). Convert to
            # radial with the ORIGINAL 1280x720 intrinsics, then warp with the same gravity homography as
            # the rgb: radial range is invariant to a rotation about the camera centre, planar z is not.
            dep = np.array(Image.open(os.path.join(fr["src"], "depth.png"))).astype(np.float32)
            h0, w0 = dep.shape
            fx0, fy0 = (w0 / 2) / np.tan(fr["xfov"]), (h0 / 2) / np.tan(fr["yfov"])
            u = (np.arange(w0) + 0.5 - w0 / 2) / fx0
            v = (np.arange(h0) + 0.5 - h0 / 2) / fy0
            rad = dep * np.sqrt(1.0 + u[None, :] ** 2 + v[:, None] ** 2)
            rad = cv2.resize(rad, (C.IMG_W, C.IMG_H), interpolation=cv2.INTER_NEAREST)
            rad = gravity_align(rad, r=fr["roll"], p=fr["pitch"], K=K, mode=1)
            Image.fromarray(np.clip(np.round(rad), 0, 65535).astype(np.uint16), mode="I;16").save(outd)
    with open(os.path.join(sd, "poses.txt"), "w") as f:
        for fr in frames:
            f.write(f"{fr['x']!r} {fr['y']!r} {fr['yaw']!r}\n")
    chunks = [{"idx": i, "kind": "s3d_static", "frames": [{k: v for k, v in fr.items() if k != "src"}]} for i, fr in enumerate(frames)]
    with open(os.path.join(sd, "chunks.json"), "w") as f:
        json.dump({"collection": collection, "scene": scene, "L": C.L, "seed": None, "cam_height_m": "per frame (cam_z)",
                   "n_chunks": len(chunks), "kinds": {"s3d_static": len(chunks)}, "chunks": chunks}, f)
    Image.fromarray(np.repeat(occ[:, :, None], 3, axis=2)).save(os.path.join(sd, "map.png"))
    meta = {"scene": scene, "map_res_m": C.MAP_RES, "map_w": int(W), "map_h": int(H),
            "origin_xy_trimesh": [x0, y0], "world_cx_habitat": cx, "world_cy_habitat_neg_z": cy,
            "z_floor_mesh": 0.0, "z_ceiling_mesh": z_ceil, "room_height_m": round(z_ceil, 3),
            "cam_height_m": "per frame: chunks.json frames[].cam_z (S3D camera z); hab y = cam_z - %.2f" % C.CAM_HEIGHT,
            "floor_y_habitat": 0.0, "free_area_m2": round(float((occ == 255).sum()) * C.MAP_RES ** 2, 1),
            "wall_cells_src": n_cells, "n_rooms": n_rooms, "src_cell_m": CELL, "doors_opened": n_open, "doors_kept_solid_exterior": n_solid, "n_frames": len(frames), "frames_skipped_off_map": skipped, "frames_skipped_wall_touch": skipped_wall, "min_clearance_m": MIN_CLEARANCE,
            "axis_convention": "x_world = S3D_X/1000 - cx; y_world = S3D_Y/1000 - cy; yaw CCW from +x; habitat = (X, Z, -Y); "
                               "habitat theta = yaw - pi/2; row = y, col = x",
            "source": "Structured3D annotation_3d.json (walls from room floor polygons, doors opened, windows solid) + perspective/full renders"}
    with open(os.path.join(mdir, "scene_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[{scene}] map {W}x{H}px rooms {n_rooms} doors open/solid {n_open}/{n_solid} free {meta['free_area_m2']} m2 ceil {z_ceil:.2f} m  frames {len(frames)} (skipped off-map {skipped}, wall-touch {skipped_wall})", flush=True)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="+", default=None)
    ap.add_argument("--collection", default=C.COLLECTIONS[0])
    a = ap.parse_args()
    scenes = a.scenes or sorted(d for d in os.listdir(C.RAW_DIR) if d.startswith("scene_"))
    os.makedirs(os.path.join(C.ROOT, a.collection), exist_ok=True)
    for s in scenes:
        if os.path.exists(os.path.join(C.scene_dir(a.collection, s), "chunks.json")):
            print(f"[{s}] cached", flush=True)
            continue
        try:
            build(s, a.collection)
        except Exception as e:
            print(f"[{s}] FAILED: {type(e).__name__}: {e}", flush=True)
    # split.yaml = standard S3D split (by scene id) restricted to the scenes that were built
    built = sorted(d for d in os.listdir(os.path.join(C.ROOT, a.collection))
                   if os.path.exists(os.path.join(C.ROOT, a.collection, d, "chunks.json")))
    sid = lambda d: int(d.split("_")[1])
    split = {"train": [d for d in built if sid(d) < 3000], "val": [d for d in built if 3000 <= sid(d) < 3250],
             "test": [d for d in built if sid(d) >= 3250]}
    with open(os.path.join(C.ROOT, a.collection, "split.yaml"), "w") as f:
        for k in ("train", "val", "test"):
            f.write(f"{k}: {json.dumps(split[k])}\n")
    print(f"[split] train {len(split['train'])} val {len(split['val'])} test {len(split['test'])}", flush=True)


if __name__ == "__main__":
    main()
