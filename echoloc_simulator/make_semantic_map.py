#!/usr/bin/env python3
"""Semantic floor plans: label every wall pixel of map.png as wall / window / door.

Format follows SemRayLoc (Grader & Averbuch-Elor, ICCV 2025, arXiv:2507.09291), which
represents a floor plan as F in {0,1,...,C}^(H x W) with zero for empty space and the
semantic categories *wall*, *window*, *door*.

    maps/<scene>/semantic_map.png      uint8, 3 identical channels (read as [:, :, 0])
                                       0 = empty space, 1 = wall, 2 = window, 3 = door
    maps/<scene>/semantic_legend.json  label table, source, per-class pixel counts

map.png is NEVER modified. The non-zero set of semantic_map.png is exactly the obstacle
set of map.png, so a ray cast on either stops at the same pixel: the existing depth
ground truth stays valid and the semantic map only adds a label at the hit point.
Every obstacle starts as `wall` and is overwritten where the dataset's own annotation
places a window or a door (doors last, so a door beside a window wins).

Sources of the labels, per dataset:
  replica  mesh_semantic.ply carries a per-face object id; habitat/info_semantic.json maps
           it to one of 101 classes. We keep near-vertical faces of the window/door classes.
  mp3d     <scene>_semantic.ply carries a per-face object id; the .house file maps object ->
           category -> mpcat40 name. Same filtering, restricted to the storey's height band.
           (Verified: the semantic ply and the .glb share one coordinate frame.)
  s3d      annotation_3d.json gives door and window polygons directly.

Doorways are openings in these maps (a deliberate choice: sealing them would delete the
room-to-room coupling the acoustic simulation needs), so the `door` label marks door
surfaces that are part of the obstacle set — exterior doors, closed door leaves in a scan,
and the jambs bordering an opening — not the free pixels of the opening itself.

Projection note: the same face-to-grid projection produces any other per-category layer
(furniture footprint, floor/ceiling extent, room type where annotated). `CATEGORIES`
below is the only thing that decides which classes are drawn.

Usage:  ECHOLOC_DATASET=replica python make_semantic_map.py [--scenes ...] [--workers 4]
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

import common as C

EMPTY, WALL, WINDOW, DOOR = 0, 1, 2, 3
LABELS = {"empty": EMPTY, "wall": WALL, "window": WINDOW, "door": DOOR}

# class name (lower-case, substring match) -> label.  Extending this is all that is needed
# to add a category; the projection machinery does not change.
# Several Replica and MP3D scenes annotate the opening itself only as its covering
# (a window behind blinds or a curtain is labelled `blinds` / `curtain`, never `window`),
# so those count as window evidence; `shower curtain` is excluded because it is not an
# opening. --strict drops the aliases and keeps only the exact `window` / `door` classes.
CATEGORIES = {
    "window": WINDOW,
    "blinds": WINDOW,
    "curtain": WINDOW,
    "door": DOOR,
}
STRICT_CATEGORIES = {"window": WINDOW, "door": DOOR}
EXCLUDE = ("shower",)
CELL = 0.05                 # the wall-mask grid; map.png is this upsampled by UP
UP = int(round(CELL / C.MAP_RES))
DILATE_CELLS = 2            # openings sit in the wall plane; reach the neighbouring wall cells
MAX_WALL_NZ = 0.35          # near-vertical faces only (same threshold as the wall extractor)
SHELL_PX = 3                # a ray only ever hits the obstacle surface facing free space;
                            # labels are confined to that shell so the exterior blob stays `wall`


# ---------------------------------------------------------------- semantic PLY
def read_semantic_ply(path):
    """Replica / MP3D semantic PLY -> (vertices (V,3), faces (F,k) int64, object_id (F,) int64).

    Both use a binary little-endian PLY whose face element carries an extra scalar
    property after the vertex-index list; trimesh refuses that, so we parse it directly.
    Face lists are uniform in these files (Replica quads, MP3D triangles)."""
    with open(path, "rb") as f:
        header = []
        while True:
            line = f.readline().decode("ascii", "replace").strip()
            header.append(line)
            if line == "end_header":
                break
        data = f.read()
    np_t = {"float": "f4", "double": "f8", "uchar": "u1", "uint8": "u1", "char": "i1",
            "ushort": "u2", "uint16": "u2", "short": "i2", "int": "i4", "int32": "i4",
            "uint": "u4", "uint32": "u4"}
    n_vert = n_face = 0
    vprops, el = [], None
    fcount_t = fidx_t = oid_t = None
    for line in header:
        p = line.split()
        if not p:
            continue
        if p[0] == "element":
            el = p[1]
            if el == "vertex":
                n_vert = int(p[2])
            elif el == "face":
                n_face = int(p[2])
        elif p[0] == "property" and el == "vertex" and p[1] != "list":
            vprops.append(p[1])
        elif p[0] == "property" and el == "face":
            if p[1] == "list":
                fcount_t, fidx_t = p[2], p[3]
            else:
                oid_t = p[1]
    vdt = np.dtype([(f"v{i}", np_t[t]) for i, t in enumerate(vprops)])
    V = np.frombuffer(data, dtype=vdt, count=n_vert)
    xyz = np.stack([V["v0"], V["v1"], V["v2"]], 1).astype(np.float64)
    rest = data[vdt.itemsize * n_vert:]
    if oid_t is None:
        raise ValueError(f"{path}: face element has no object id")
    ct = np.dtype(np_t[fcount_t]).itemsize
    it = np.dtype(np_t[fidx_t]).itemsize
    ot = np.dtype(np_t[oid_t]).itemsize
    k = int(np.frombuffer(rest[:ct], dtype=np_t[fcount_t])[0])
    if ct + it * k + ot != len(rest) // n_face:
        raise ValueError(f"{path}: non-uniform face lists are not supported")
    fdt = np.dtype([("c", np_t[fcount_t]), ("i", np_t[fidx_t], (k,)), ("o", np_t[oid_t])])
    F = np.frombuffer(rest, dtype=fdt, count=n_face)
    return xyz, F["i"].astype(np.int64), F["o"].astype(np.int64)


def replica_object_class(scene):
    """object id -> class name, from habitat/info_semantic.json."""
    info = json.load(open(os.path.join(C.RAW_DIR, scene, "habitat", "info_semantic.json")))
    names = {c["id"]: c["name"] for c in info["classes"]}
    id_to_label = info["id_to_label"]           # index = object id, value = class id (<0: none)
    out = {}
    for oid, cls in enumerate(id_to_label):
        if cls is not None and cls >= 0:
            out[oid] = names.get(cls, "?")
    return out


def mp3d_object_class(scene):
    """object id -> mpcat40 name, from the .house file (O -> category index -> C record)."""
    path = os.path.join(C.RAW_DIR, scene, f"{scene}.house")
    cats, objs = {}, {}
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == "C":                          # C idx mapping_idx name mpcat40_idx mpcat40_name
            cats[int(p[1])] = p[5] if len(p) > 5 else p[3]
        elif p[0] == "O":                        # O idx region_idx category_idx ...
            objs[int(p[1])] = int(p[3])
    return {o: cats.get(c, "?") for o, c in objs.items()}


def label_of(name, table=None):
    n = name.lower()
    if any(x in n for x in EXCLUDE):
        return None
    for key, lab in (table or CATEGORIES).items():
        if key in n:
            return lab
    return None


# ---------------------------------------------------------------- projection
def stamp(tri, x0, y0, H, W):
    """Top-down footprint of a set of triangles/quads on the CELL grid."""
    g = np.zeros((H, W), bool)
    if len(tri) == 0:
        return g
    k = tri.shape[1]
    pts = [tri[:, i, :2] for i in range(k)]
    pts += [(tri[:, i, :2] + tri[:, (i + 1) % k, :2]) / 2 for i in range(k)]
    pts += [tri[:, :, :2].mean(axis=1)]
    P = np.concatenate(pts, axis=0)
    c = np.clip(((P[:, 0] - x0) / CELL).astype(int), 0, W - 1)
    r = np.clip(((P[:, 1] - y0) / CELL).astype(int), 0, H - 1)
    g[r, c] = True
    return g


def evidence_from_mesh(scene, meta, shape_cells, table=None):
    """-> {label: bool grid} on the CELL grid, from the scene's semantic mesh."""
    base = C.base_scene(scene)
    if C.DATASET == "replica":
        ply = os.path.join(C.RAW_DIR, base, "habitat", "mesh_semantic.ply")
        obj_class = replica_object_class(base)
    else:
        ply = os.path.join(C.RAW_DIR, base, f"{base}_semantic.ply")
        obj_class = mp3d_object_class(base)
    xyz, faces, oid = read_semantic_ply(ply)
    tri = xyz[faces]                                   # (F, k, 3)
    e0 = tri[:, 1] - tri[:, 0]
    e1 = tri[:, 2] - tri[:, 0]
    nz = np.abs(np.cross(e0, e1)[:, 2])
    norm = np.linalg.norm(np.cross(e0, e1), axis=1) + 1e-12
    vertical = (nz / norm) < MAX_WALL_NZ
    zlo, zhi = float(meta["z_floor_mesh"]), float(meta["z_ceiling_mesh"])
    in_band = (tri[:, :, 2].max(1) >= zlo) & (tri[:, :, 2].min(1) <= zhi)
    x0, y0 = meta["origin_xy_trimesh"]
    Hc, Wc = shape_cells
    lab_of_face = np.zeros(len(oid), np.int16)
    for o, name in obj_class.items():
        lab = label_of(name, table)
        if lab is not None:
            lab_of_face[oid == o] = lab
    out = {}
    for lab in (WINDOW, DOOR):
        sel = vertical & in_band & (lab_of_face == lab)
        if sel.any():
            out[lab] = stamp(tri[sel], x0, y0, Hc, Wc)
    return out


def evidence_from_s3d(scene, meta, shape_cells):
    """-> {label: bool grid} from the Structured3D door / window polygons."""
    C.f3loc_import()
    sys.path.insert(0, os.path.join(C.F3LOC, "s3d", "process"))
    from s3d_utils import read_s3d_floorplan
    annos = json.load(open(os.path.join(C.RAW_DIR, scene, "annotation_3d.json")))
    _, _, door_lines, window_lines = read_s3d_floorplan(annos)
    x0, y0 = meta["origin_xy_trimesh"]
    Hc, Wc = shape_cells
    import cv2
    out = {}
    for lab, lines in ((DOOR, door_lines), (WINDOW, window_lines)):
        g = np.zeros((Hc, Wc), np.uint8)
        for a, b in lines:
            pa = (int(np.floor((a[0] - x0) / CELL)), int(np.floor((a[1] - y0) / CELL)))
            pb = (int(np.floor((b[0] - x0) / CELL)), int(np.floor((b[1] - y0) / CELL)))
            cv2.line(g, pa, pb, 1, 1)
        if g.any():
            out[lab] = g.astype(bool)
    return out


# ---------------------------------------------------------------- driver
def build(scene, overwrite=False, strict=False):
    mdir = os.path.join(C.ROOT, "maps", scene)
    out_png = os.path.join(mdir, "semantic_map.png")
    if os.path.exists(out_png) and not overwrite:
        print(f"[{scene}] cached", flush=True)
        return
    meta = C.load_meta(scene)
    occ = C.load_map(scene)
    obstacle = occ != 255
    H, W = occ.shape
    Hc, Wc = int(np.ceil(H / UP)), int(np.ceil(W / UP))
    table = STRICT_CATEGORIES if strict else CATEGORIES
    ev = evidence_from_s3d(scene, meta, (Hc, Wc)) if C.DATASET == "s3d" \
        else evidence_from_mesh(scene, meta, (Hc, Wc), table)

    sem = np.where(obstacle, WALL, EMPTY).astype(np.uint8)
    shell = obstacle & ndimage.binary_dilation(~obstacle, iterations=SHELL_PX)
    for lab in (WINDOW, DOOR):                       # door last: it wins over a window
        g = ev.get(lab)
        if g is None:
            continue
        g = ndimage.binary_dilation(g, iterations=DILATE_CELLS)
        full = np.kron(g, np.ones((UP, UP), bool))[:H, :W]
        sem[shell & full] = lab

    Image.fromarray(np.repeat(sem[:, :, None], 3, axis=2)).save(out_png)
    counts = {n: int((sem == v).sum()) for n, v in LABELS.items()}
    n_obs = int(obstacle.sum())
    legend = {
        "scene": scene, "dataset": C.DATASET,
        "format": "SemRayLoc-style label matrix: F in {0,...,C}, 0 = empty space",
        "reference": "Grader & Averbuch-Elor, Supercharging Floorplan Localization with "
                     "Semantic Rays, ICCV 2025 (arXiv:2507.09291)",
        "labels": LABELS,
        "file": "semantic_map.png (uint8, 3 identical channels; read as [:, :, 0])",
        "nonzero_set": "identical to the obstacle set of map.png, so ray casting is unchanged",
        "source": {"replica": "mesh_semantic.ply per-face object id + habitat/info_semantic.json",
                   "mp3d": "<scene>_semantic.ply per-face object id + .house category records",
                   "s3d": "annotation_3d.json door and window polygons"}[C.DATASET],
        "cell_m": CELL, "dilate_cells": DILATE_CELLS, "max_wall_nz": MAX_WALL_NZ, "shell_px": SHELL_PX,
        "category_map": {k: v for k, v in table.items()}, "excluded_substrings": list(EXCLUDE),
        "pixel_counts": counts,
        "obstacle_pixels": n_obs,
        "shell_pixels": int(shell.sum()),
        "labelled_fraction_of_shell": round((counts["window"] + counts["door"]) / max(int(shell.sum()), 1), 4),
        "note": "doorways are openings in these maps, so `door` marks door surfaces inside the "
                "obstacle set (exterior doors, closed leaves, jambs), not the free opening",
    }
    with open(os.path.join(mdir, "semantic_legend.json"), "w") as f:
        json.dump(legend, f, indent=2)
    print(f"[{scene}] obstacles {n_obs}  wall {counts['wall']}  window {counts['window']}  "
          f"door {counts['door']}  ({legend['labelled_fraction_of_shell']:.1%} of surface)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", nargs="+", default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--strict", action="store_true", help="only the exact window/door classes (no blinds/curtain)")
    a = ap.parse_args()
    for s in (a.scenes or C.SCENES):
        try:
            build(s, a.overwrite, a.strict)
        except Exception as e:
            print(f"[{s}] FAILED: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
