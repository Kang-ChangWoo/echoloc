#!/usr/bin/env python3
"""Zillow Indoor Dataset -> echoloc (F3Loc-compatible) importer.  Profile: ECHOLOC_DATASET=zind

ZInD ships no mesh and no depth: per home a zind_data.json (per-panorama room layouts with
doors/windows/openings, and the 2D transform that merges them into a floor plan) plus the
panoramas themselves (2048x1024 equirectangular photographs of furnished homes). So, per FLOOR:

  maps/<home>_f<k>/map.png          0.01 m/px = 0.05 m wall grid x5, free = 255, walls 1 cell,
                                    doors between rooms opened, windows stay wall, outside = 0
  maps/<home>_f<k>/scene_meta.json  same keys as the Replica/MP3D/Gibson builders
  maps/<home>_f<k>/semantic_map.png SemRayLoc labels (wall/window/door) -- ZInD annotates both
  floorplan_proxy/<...>/floorplan.glb   map's obstacle cells extruded 0..ceiling + slabs
  zind/<home>_f<k>/rgb/{i:05d}.png      480x640 pinhole CROPPED FROM THE PANORAMA at its own
                                    heading, K = [[240,0,320],[0,240,240],[0,0,1]], F_W = 3/8
                                    (same pinhole as replica/mp3d/gibson; 2048-wide panos give
                                    605x512 source pixels for this crop, so it is ~1:1)
  zind/<home>_f<k>/poses.txt        x y yaw, one line per panorama
  zind/<home>_f<k>/chunks.json      L = 0: every frame is its own chunk; per frame the real
                                    camera height, room label, pano id, habitat pose

Coordinates (verified against zillow/zind's own transformations.py, 2026-09-20):
  * layout_raw vertices are in the panorama's room frame, NORMALISED BY CAMERA HEIGHT
    (camera_height == 1.0 for every pano).
  * room -> floor plan:  v.dot(R) * t.scale + t.translation,  R = [[cos a, sin a], [-sin a, cos a]]
  * floor plan -> metres: x scale_meters_per_coordinate  (per floor)
  * hence the real camera height in metres = t.scale * scale_meters_per_coordinate
    (median 1.44 m over the corpus; ceiling = ceiling_height * that, median 2.49 m)
  * panorama azimuth: theta = atan2(-x_room, y_room), theta = 0 at the image's horizontal centre;
    elevation phi = asin(z / rho), phi = 0 at the vertical centre, y flipped so it goes up.
  * world (ours) = floor-plan metres, origin at the map centre; habitat = (x, z, -y) as elsewhere.

Floors WITHOUT scale_meters_per_coordinate are skipped: 284 of 2737 (10.4%). Borrowing another
floor's scale would make the metric depth GT an estimate, so those floors are dropped, not imputed.

Usage:  ECHOLOC_DATASET=zind python build_zind.py [--homes 0000 0001 ...] [--workers 8]
"""
import argparse
import json
import os
import shutil
import sys
from multiprocessing import Pool

import cv2
import numpy as np
import trimesh
import yaml
from PIL import Image
from scipy import ndimage

import common as C

assert C.DATASET == "zind", "run with ECHOLOC_DATASET=zind"

CELL = 0.05              # m per wall-grid cell (as every other profile)
MARGIN_M = 1.0           # grid padding so the map never clips the footprint
CLOSE_CELLS = 9          # room polygons are separated by wall-thickness gaps: close wider than a wall
MIN_CLEARANCE = 0.05     # m; a pano closer than this to an obstacle cell is dropped (proxy near-plane)
MIN_AREA_M2 = 8.0        # floors with less sealed interior than this are not a floor plan
MIN_PANOS = 2
PART = os.path.join(C.HERE, "floorplan_extraction", "zind_partition.json")


# ---- ZInD geometry (mirrors zillow/zind transformations.py) -----------------
def to_global(v, t):
    """room-frame coordinates -> floor-plan coordinates (ZInD Transformation2D.to_global)."""
    a = np.radians(t["rotation"])
    R = np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])
    return np.asarray(v, float).reshape(-1, 2).dot(R) * t["scale"] + np.asarray(t["translation"])


def room_dir_to_global(a_deg):
    """The panorama's theta=0 direction (room +y) as a unit vector in floor-plan coordinates."""
    a = np.radians(a_deg)
    return np.array([-np.sin(a), np.cos(a)])


def floors_of(home, raw):
    """-> [(scene_id, floor_name, scale_m_per_coord)] for floors that have a metric scale."""
    d = json.load(open(os.path.join(raw, home, "zind_data.json")))
    S = d.get("scale_meters_per_coordinate") or {}
    out = []
    for fl in sorted(d["merger"]):
        s = S.get(fl)
        if s is None:
            continue
        k = fl.rsplit("_", 1)[-1].lstrip("0") or "0"        # floor_01 -> 1
        out.append((f"{home}_f{k}", fl, float(s)))
    return d, out


def panos_of(d, fl):
    """-> [(pano_name, pano_dict, room_label)] in a stable order."""
    out = []
    for cr in sorted(d["merger"][fl]):
        for pr in sorted(d["merger"][fl][cr]):
            for pn in sorted(d["merger"][fl][cr][pr]):
                out.append((pn, d["merger"][fl][cr][pr][pn], cr))
    return out


# ---- map -------------------------------------------------------------------
def build_map(d, fl, s):
    """-> occ, (x_min, y_min), z_ceil, grid, stats. Free space is the union of the room polygons;
    walls are their outlines; a door whose cells touch only free space is opened."""
    P = panos_of(d, fl)
    polys, doors, wins, opens, ceil, cam_hs = [], [], [], [], [], []
    for pn, p, cr in P:
        t = p["floor_plan_transformation"]
        polys.append(to_global(p["layout_raw"]["vertices"], t) * s)
        cam_h = t["scale"] * s
        cam_hs.append(cam_h)
        ceil.append(p["ceiling_height"] * cam_h)
        # Wall openings are TRIPLETS, not pairs: [end_a(x,y), end_b(x,y), (z_bottom, z_top)],
        # with z camera-normalised (floor = -1). Verified over 16,154 lists: every length is a
        # multiple of 3, z_top > z_bottom always, segment length median 0.88 m (a door).
        # Reading them in pairs mixes an endpoint with a z range and fabricates segments.
        for key, acc in (("doors", doors), ("windows", wins), ("openings", opens)):
            v = p["layout_raw"].get(key) or []
            for i in range(0, len(v) - 2, 3):
                seg = to_global([v[i], v[i + 1]], t) * s
                zb, zt = float(v[i + 2][0]), float(v[i + 2][1])
                acc.append((seg, zb * cam_h, zt * cam_h))
    if not polys:
        return None
    z_ceil = float(np.median(ceil)) if ceil else 2.5
    z_ceil = float(np.clip(z_ceil, 2.0, 4.0))

    pts = np.vstack(polys)
    x_min, y_min = pts.min(0) - MARGIN_M
    x_max, y_max = pts.max(0) + MARGIN_M
    Wc = int(np.ceil((x_max - x_min) / CELL)) + 1
    Hc = int(np.ceil((y_max - y_min) / CELL)) + 1
    if Wc * Hc > 40_000_000:
        return None
    to_c = lambda p: np.floor((np.asarray(p) - [x_min, y_min]) / CELL).astype(np.int32)

    # Free space is the UNION of the filled room polygons -- their outlines are NOT drawn as wall.
    # Each panorama estimates its own room independently, so neighbouring estimates overlap; drawing
    # every outline would stamp walls through the inside of adjacent rooms (measured: the map ray was
    # shorter than the room's own polygon on 50-60% of rays). The wall between two rooms is the gap
    # their polygons leave, and the building's outer wall is the complement of the union.
    free = np.zeros((Hc, Wc), np.uint8)
    for poly in polys:
        if len(poly) >= 3:
            cv2.fillPoly(free, [to_c(poly)], 1)
    grid = np.zeros((Hc, Wc), bool)

    # exterior: rooms are separated by wall-thickness gaps belonging to no polygon, so
    # "not in any room" is not exterior -- close wider than a wall, then fill holes.
    foot = ndimage.binary_fill_holes(
        ndimage.binary_closing(free.astype(bool), structure=np.ones((CLOSE_CELLS,) * 2)))
    exterior = ~foot

    # z is measured from the camera, so the floor sits at -cam_h (about -1.4 m). An opening is
    # walkable only if it reaches the floor; a window starts well above it and stays wall.
    def reaches_floor(e):
        return e[1] <= -0.75 * np.median([abs(c) for c in cam_hs])

    def carve(entries):
        """Open each opening unless it borders the exterior (entrance doors stay solid, and the
        map's exterior is obstacle, so carving there would leak rays out of the building)."""
        opened = solid = 0
        for seg, zb, zt in entries:
            m = np.zeros((Hc, Wc), np.uint8)
            cv2.line(m, tuple(to_c(seg[0])), tuple(to_c(seg[1])), 1, 3, lineType=cv2.LINE_4)
            mb = m.astype(bool)
            if (ndimage.binary_dilation(mb, structure=np.ones((3, 3))) & exterior).any():
                solid += 1
                continue
            grid[mb] = False
            free[mb] = 1
            opened += 1
        return opened, solid

    walk_doors = [e for e in doors if reaches_floor(e)]
    walk_opens = [e for e in opens if reaches_floor(e)]
    n_open, n_solid = carve(walk_doors)
    n_op2, n_sol2 = carve(walk_opens)
    n_open += n_op2
    n_solid += n_sol2

    free_cells = free.astype(bool) & ~grid
    free_cells = ndimage.binary_opening(free_cells, structure=np.ones((3, 3)))
    if free_cells.sum() * CELL * CELL < MIN_AREA_M2:
        return None
    # obstacle geometry = every cell bordering free space, so map and proxy agree exactly
    grid = ~free_cells & ndimage.binary_dilation(free_cells, structure=np.ones((3, 3)))
    occ = np.kron(np.where(free_cells, 255, 0).astype(np.uint8), np.ones((C.UPSAMPLE,) * 2, np.uint8))
    return occ, (float(x_min), float(y_min)), z_ceil, grid, {
        "doors_opened": n_open, "doors_solid": n_solid,
        "doors_above_floor": len(doors) - len(walk_doors),
        "openings_above_floor": len(opens) - len(walk_opens),
        "n_doors": len(doors), "n_windows": len(wins), "n_openings": len(opens),
        "free_area_m2": round(float(free_cells.sum()) * CELL * CELL, 1)}, (wins, doors)


def proxy_from_grid(grid, origin, z_ceil):
    """Obstacle cells -> boxes 0..z_ceil, plus floor/ceiling slabs (same as build_s3d)."""
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
            box.apply_translation((x0 + (run[0] + run.size / 2) * CELL,
                                   y0 + (row + 0.5) * CELL, z_ceil / 2))
            parts.append(box)
    fx, fy = Wc * CELL, Hc * CELL
    for zc in (-0.025, z_ceil + 0.025):
        slab = trimesh.creation.box(extents=(fx, fy, 0.05))
        slab.apply_translation((x0 + fx / 2, y0 + fy / 2, zc))
        parts.append(slab)
    return trimesh.util.concatenate(parts)


# ---- panorama -> pinhole ---------------------------------------------------
def crop_maps():
    """Pixel -> (map_x, map_y) lookup into a 2048x1024 pano for a camera looking at theta = 0.
    Built once; a different yaw only shifts the azimuth, so the maps are reused."""
    u = (np.arange(C.IMG_W) + 0.5 - C.IMG_W / 2) / C.FX
    v = (np.arange(C.IMG_H) + 0.5 - C.IMG_H / 2) / C.FY
    uu, vv = np.meshgrid(u, v)
    # camera frame: forward = room +y, right = room +x, up = +z
    fwd, right, up = np.ones_like(uu), uu, -vv
    rho = np.sqrt(fwd ** 2 + right ** 2 + up ** 2)
    theta = np.arctan2(-right, fwd)               # ZInD: theta = atan2(-x, y)
    phi = np.arcsin(up / rho)
    return theta.astype(np.float32), phi.astype(np.float32)


_THETA, _PHI = crop_maps()


def crop_pano(img, yaw_room):
    """480x640 pinhole crop of an equirectangular pano, looking at room-frame azimuth yaw_room."""
    H, W = img.shape[:2]
    th = _THETA + yaw_room
    th = (th + np.pi) % (2 * np.pi) - np.pi
    x = (th + np.pi) / (2 * np.pi) * (W - 1)
    y = (1.0 - (_PHI + np.pi / 2) / np.pi) * (H - 1)
    return cv2.remap(img, x.astype(np.float32), y.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


# ---- per-floor build -------------------------------------------------------
def build_floor(args):
    home, scene, fl, s, d = args
    raw = os.path.join(C.RAW_DIR, home)
    try:
        got = build_map(d, fl, s)
    except Exception as e:
        return scene, f"map failed: {type(e).__name__}: {e}", 0
    if got is None:
        return scene, "no usable floor plan", 0
    occ, (x0, y0), z_ceil, grid, stats, (wins, doors) = got
    H, W = occ.shape
    cx, cy = x0 + W / 2 * C.MAP_RES, y0 + H / 2 * C.MAP_RES

    mdir = os.path.join(C.ROOT, "maps", scene)
    os.makedirs(mdir, exist_ok=True)
    Image.fromarray(np.repeat(occ[:, :, None], 3, axis=2)).save(os.path.join(mdir, "map.png"))
    pdir = os.path.join(C.PROXY_DIR, scene)
    os.makedirs(pdir, exist_ok=True)
    proxy_from_grid(grid, (x0, y0), z_ceil).export(os.path.join(pdir, "floorplan.glb"))

    clearance = ndimage.distance_transform_edt(occ == 255) * C.MAP_RES
    sd = C.scene_dir(C.COLLECTIONS[0], scene)
    os.makedirs(os.path.join(sd, "rgb"), exist_ok=True)
    frames, skipped = [], {"outside": 0, "clearance": 0, "no_pano": 0, "not_inside": 0}
    for pn, p, cr in panos_of(d, fl):
        if not p.get("is_inside", True):
            skipped["not_inside"] += 1
            continue
        t = p["floor_plan_transformation"]
        cam_h = t["scale"] * s
        gx, gy = np.asarray(t["translation"], float) * s
        x, y = float(gx - cx), float(gy - cy)
        r, c = C.world_to_map(x, y, occ.shape)
        ri, ci = int(np.floor(r)), int(np.floor(c))
        if not (0 <= ri < H and 0 <= ci < W) or occ[ri, ci] != 255:
            skipped["outside"] += 1
            continue
        if clearance[ri, ci] < MIN_CLEARANCE:
            skipped["clearance"] += 1
            continue
        src = os.path.join(raw, p["image_path"])
        if not os.path.exists(src):
            skipped["no_pano"] += 1
            continue
        f = room_dir_to_global(t["rotation"])
        yaw = float(C.wrap(np.arctan2(f[1], f[0])))
        frames.append({"x": x, "y": y, "yaw": yaw, "cam_z": float(cam_h),
                       "ceiling_z": float(p["ceiling_height"] * cam_h),
                       "room": cr, "pano": pn, "label": p.get("label"),
                       "is_primary": bool(p.get("is_primary")),
                       # habitat pose in the PROXY frame = floor-plan metres (gx, gy), NOT the map-centred
                       # world (x, y): the glb is authored at origin_xy_trimesh, as build_s3d does. Storing
                       # world x here shifted every proxy render and RIR by (cx, cy) -- caught by validate
                       # 2026-09-22 (floorplan depth vs map range median 1.75 m; 0.04 cm once fixed).
                       "hab": [float(gx), float(cam_h - C.CAM_HEIGHT), float(-gy)],
                       "theta": float(C.yaw_to_habitat_theta(yaw)), "src": src})
    if len(frames) < MIN_PANOS:
        # map.png and the proxy are already on disk: remove them, or the floor looks built to
        # anything that enumerates maps/ (scene_meta.json is written last, so it is the marker).
        for p in (mdir, pdir, sd):
            shutil.rmtree(p, ignore_errors=True)
        return scene, f"only {len(frames)} usable panoramas", 0
    for i, fr in enumerate(frames):
        img = cv2.imread(fr.pop("src"), cv2.IMREAD_COLOR)
        if img is None:
            return scene, f"unreadable panorama {fr['pano']}", 0
        cv2.imwrite(os.path.join(sd, "rgb", f"{i:05d}.png"), crop_pano(img, 0.0))
    np.savetxt(os.path.join(sd, "poses.txt"),
               np.array([[f["x"], f["y"], f["yaw"]] for f in frames]), fmt="%.17g")
    json.dump({"collection": C.COLLECTIONS[0], "scene": scene, "L": 0,
               "cam_height_m": "per frame (frames[].cam_z)", "n_chunks": len(frames),
               "kinds": {"panorama_crop": len(frames)},
               "chunks": [{"idx": i, "kind": "panorama_crop", "frames": [f]}
                          for i, f in enumerate(frames)]},
              open(os.path.join(sd, "chunks.json"), "w"), indent=1)
    Image.fromarray(np.repeat(occ[:, :, None], 3, axis=2)).save(os.path.join(sd, "map.png"))

    meta = {"scene": scene, "map_res_m": C.MAP_RES, "map_w": W, "map_h": H, "src_cell_m": CELL,
            "origin_xy_trimesh": [x0, y0], "world_cx_habitat": float(cx),
            "world_cy_habitat_neg_z": float(cy),
            "z_floor_mesh": 0.0, "z_ceiling_mesh": z_ceil, "room_height_m": z_ceil,
            "cam_height_m": "per frame", "free_area_m2": stats["free_area_m2"],
            "axis_convention": "x_world = X_floorplan_m - cx; y_world = Y_floorplan_m - cy; "
                               "yaw CCW from +x_world; habitat theta = yaw - pi/2; row = y, col = x",
            "base_scene": home, "floor_name": fl, "scale_meters_per_coordinate": s,
            "n_panos_used": len(frames), "skipped": skipped, **stats}
    json.dump(meta, open(os.path.join(mdir, "scene_meta.json"), "w"), indent=1)
    return scene, None, len(frames)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--homes", nargs="+", default=None)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    homes = a.homes or sorted(h for h in os.listdir(C.RAW_DIR) if h != "_pages")

    jobs = []
    for h in homes:
        try:
            d, fls = floors_of(h, C.RAW_DIR)
        except Exception as e:
            print(f"[{h}] unreadable: {e}", flush=True)
            continue
        for scene, fl, s in fls:
            if os.path.exists(os.path.join(C.ROOT, "maps", scene, "scene_meta.json")):
                continue
            jobs.append((h, scene, fl, s, d))
    print(f"[zind] {len(homes)} homes -> {len(jobs)} floors to build", flush=True)

    ok = frames = 0
    reasons = {}
    with Pool(a.workers) as pool:
        for n, (scene, err, nf) in enumerate(pool.imap_unordered(build_floor, jobs, chunksize=1)):
            if err:
                reasons[err.split(":")[0]] = reasons.get(err.split(":")[0], 0) + 1
            else:
                ok += 1
                frames += nf
            if (n + 1) % 100 == 0:
                print(f"[zind] {n+1}/{len(jobs)}  built {ok}  frames {frames}", flush=True)
    print(f"[zind] built {ok} floors, {frames} frames; skipped {len(jobs)-ok} {reasons}", flush=True)

    # split: ZInD's own home-level partition, expanded to the floors that were built
    # scene_meta.json is written last, so it marks a FINISHED floor; a directory alone may be
    # a floor that bailed after writing map.png (its poses.txt would not exist, and every later
    # stage reads split.yaml -> FileNotFoundError).
    mroot = os.path.join(C.ROOT, "maps")
    built = sorted(d for d in os.listdir(mroot)
                   if os.path.exists(os.path.join(mroot, d, "scene_meta.json")))
    part = json.load(open(PART))
    split = {k: [s for s in built if C.base_scene(s) in set(v)] for k, v in part.items()}
    sdir = os.path.join(C.ROOT, C.COLLECTIONS[0])
    os.makedirs(sdir, exist_ok=True)
    yaml.safe_dump(split, open(os.path.join(sdir, "split.yaml"), "w"))
    print("[zind] split:", {k: len(v) for k, v in split.items()},
          "unassigned:", len(built) - sum(len(v) for v in split.values()), flush=True)


if __name__ == "__main__":
    sys.exit(main())
