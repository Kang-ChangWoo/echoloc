#!/usr/bin/env python3
"""Stage 2 — four-view chunks: poses.txt + chunks.json per (collection, scene).

Every chunk is L+1 = 4 frames; frame 3 is the reference frame (spec 3.1). Poses are
sampled on the Habitat navmesh (reachable, not inside geometry) AND checked against
map.png (free pixel, >= MIN_CLEARANCE from the nearest wall, straight segment
between consecutive frames does not cross a wall) so the floor-plan GT is always
defined at the pose. The real scan is also rendered at every frame and its no-hit
fraction below row 120 is recorded (chunks.json 'scan_nohit_lower'): Replica scans
have unscanned voids, and the dataset keeps those frames — filter downstream.

Motion regimes (spec 1 / 5.3):
  replica_f  forward motion   step 0.15-0.40 m along the heading, yaw drift N(0, 4 deg) <= 10 deg
  replica_g  general motion   40% forward (yaw +-20 deg, step 0.10-0.40 m)
                              35% in-place rotation (monotonic 10-35 deg/step, translation ~N(0, 2 cm))
                              25% mixed (step 0-0.30 m in any direction within +-60 deg, yaw +-35 deg)

poses.txt: "<x_world_m> <y_world_m> <yaw_rad>" per frame, full precision, ascending
frame order == rgb filename order. chunks.json keeps the regime label and the
habitat-frame pose (incl. navmesh height) of every frame for the renderers.

Usage:  python sample_poses.py --collection replica_f --scenes room_1 [--n-chunks 300]
"""
import argparse
import json
import os
import sys

import numpy as np
from scipy import ndimage

import common as C

DEG = np.pi / 180.0
MAX_Y_DELTA = 0.30        # m; a snapped point further from the scene floor is another level
HOLE_ROW0 = 120           # scan-hole test ignores the top rows (frl apartments have no scanned ceiling)
HOLE_MAX = None           # None = record only (decided 2026-09-08: keep every pose, filter downstream); a float rejects frames above it
SNAP_XY_TOL = 0.03        # m; snap_point must not move the pose horizontally


class Sampler:
    def __init__(self, scene, seed):
        C.f3loc_import()
        from raycast import ray_cast   # exact DDA; see raycast.py (F3Loc original leaks at wall corners)
        self.ray_cast = ray_cast
        self.scene = scene
        self.meta = C.load_meta(scene)
        self.occ = C.load_map(scene)
        self.clear = ndimage.distance_transform_edt(self.occ == 255) * C.MAP_RES
        self.sim = C.make_sim(scene, geom="real", depth=True)   # depth: scan-hole test per frame
        self.pf = self.sim.pathfinder
        self.pf.seed(seed)                      # habitat's own RNG: MUST be seeded per run
        self.rng = np.random.RandomState(seed)
        self.floor_y = self.meta["floor_y_habitat"]

    def close(self):
        self.sim.close()

    # -- validity ---------------------------------------------------------
    def check(self, x, y):
        """-> habitat y of the navmesh at (x, y), or None if the pose is invalid."""
        r, c = C.world_to_map(x, y, self.occ.shape)
        ri, ci = int(np.floor(r)), int(np.floor(c))
        H, W = self.occ.shape
        if not (0 <= ri < H and 0 <= ci < W) or self.occ[ri, ci] != 255:
            return None
        if self.clear[ri, ci] < C.MIN_CLEARANCE:
            return None
        hx, hz = C.world_to_habitat(x, y, self.meta)
        p = self.pf.snap_point(np.array([hx, self.floor_y, hz], dtype=np.float32))
        if not np.all(np.isfinite(p)):
            return None
        if abs(float(p[1]) - self.floor_y) > MAX_Y_DELTA:
            return None
        if np.hypot(float(p[0]) - hx, float(p[2]) - hz) > SNAP_XY_TOL:
            return None
        if not self.pf.is_navigable(p, 0.5):
            return None
        # Split-level storeys: a raised landing inside the storey band can put the camera
        # above the storey's proxy ceiling (z_ceil = next storey - 0.1) -> half-empty proxy
        # renders. Applies to every per-storey dataset, not just mp3d: gibson/Pinesdale_f2
        # (a 1.5 m storey) had one chunk on a landing 0.30 m up, which puts the camera exactly
        # on the ceiling and empties the top half of the image.
        zc = self.meta.get("z_ceiling_mesh")
        if zc is not None and C.DATASET in ("mp3d", "gibson") and float(p[1]) + C.CAM_HEIGHT > zc - 0.15:
            return None
        return float(p[1])

    def scan_hole(self, x, y, yaw, hy):
        """Fraction of no-hit pixels below HOLE_ROW0 when the real scan is rendered at
        this pose. Replica scans have unscanned voids (apartment_1/2: whole spaces
        behind doorways); a camera looking into one gets a black image while the
        sealed map still reports a wall. Recorded per frame in chunks.json as
        'scan_nohit_lower' so consumers can filter; rejection only if HOLE_MAX is set."""
        hx, hz = C.world_to_habitat(x, y, self.meta)
        C.set_agent(self.sim, hx, hy, hz, C.yaw_to_habitat_theta(yaw))
        d = self.sim.get_sensor_observations()["depth"]
        return float((d[HOLE_ROW0:] == 0).mean())

    def segment_free(self, x0, y0, x1, y1):
        d = np.hypot(x1 - x0, y1 - y0)
        if d < 1e-6:
            return True
        ang = float(np.arctan2(y1 - y0, x1 - x0))
        pos = np.array(C.world_to_map(x0, y0, self.occ.shape), dtype=np.float64)
        hit = self.ray_cast(self.occ, pos, ang, dist_max=C.DIST_MAX_M / C.MAP_RES) * C.MAP_RES
        return hit > d + 0.05

    # -- motion models ------------------------------------------------------
    def step(self, kind, x, y, yaw, state):
        r = self.rng
        if kind == "forward":                      # replica_f
            dyaw = float(np.clip(r.normal(0.0, 4 * DEG), -10 * DEG, 10 * DEG))
            yaw2 = C.wrap(yaw + dyaw)
            s = r.uniform(0.15, 0.40)
            return x + s * np.cos(yaw2), y + s * np.sin(yaw2), yaw2
        if kind == "forward_g":
            yaw2 = C.wrap(yaw + r.uniform(-20 * DEG, 20 * DEG))
            s = r.uniform(0.10, 0.40)
            return x + s * np.cos(yaw2), y + s * np.sin(yaw2), yaw2
        if kind == "rotate":
            yaw2 = C.wrap(yaw + state["sign"] * r.uniform(10 * DEG, 35 * DEG))
            return x + r.normal(0, 0.02), y + r.normal(0, 0.02), yaw2
        if kind == "mixed":
            yaw2 = C.wrap(yaw + r.uniform(-35 * DEG, 35 * DEG))
            s = r.uniform(0.0, 0.30)
            d = yaw2 + r.uniform(-60 * DEG, 60 * DEG)
            return x + s * np.cos(d), y + s * np.sin(d), yaw2
        raise ValueError(kind)

    def chunk(self, kind, tries=60):
        for _ in range(tries):
            p = self.pf.get_random_navigable_point()
            for _k in range(200):            # multi-storey buildings (mp3d): stay on this storey
                if abs(float(p[1]) - self.floor_y) <= MAX_Y_DELTA:
                    break
                p = self.pf.get_random_navigable_point()
            x, y = C.habitat_to_world(float(p[0]), float(p[2]), self.meta)
            hy = self.check(x, y)
            if hy is None:
                continue
            yaw = float(self.rng.uniform(-np.pi, np.pi))
            h0 = self.scan_hole(x, y, yaw, hy)
            if HOLE_MAX is not None and h0 > HOLE_MAX:
                continue
            frames = [(x, y, yaw, hy, h0)]
            state = {"sign": float(self.rng.choice([-1.0, 1.0]))}
            ok = True
            for _v in range(C.L):
                x2, y2, yaw2 = self.step(kind, x, y, yaw, state)
                hy2 = self.check(x2, y2)
                if hy2 is None or not self.segment_free(x, y, x2, y2):
                    ok = False
                    break
                h2 = self.scan_hole(x2, y2, yaw2, hy2)
                if HOLE_MAX is not None and h2 > HOLE_MAX:
                    ok = False
                    break
                frames.append((x2, y2, yaw2, hy2, h2))
                x, y, yaw = x2, y2, yaw2
            if ok:
                return frames
        return None


def pick_kind(collection, rng):
    if collection.endswith("_f"):           # replica_f / mp3d_f: forward-motion collection
        return "forward"
    return rng.choice(["forward_g", "rotate", "mixed"], p=[0.40, 0.35, 0.25])


AUTO_DENSITY, AUTO_MIN, AUTO_MAX = 0.6, 40, 160   # mp3d: 165 storeys -> ~17k chunks per collection (spec: >= 15k)


def auto_chunks(scene):
    """n_chunks == 0 -> from the storey's free area: AUTO_DENSITY chunks per m2, clipped."""
    area = C.load_meta(scene)["free_area_m2"]
    return int(np.clip(round(area * AUTO_DENSITY), AUTO_MIN, AUTO_MAX))


def run(collection, scene, n_chunks, seed):
    if n_chunks <= 0:
        n_chunks = auto_chunks(scene)
    sd = C.scene_dir(collection, scene)
    os.makedirs(sd, exist_ok=True)
    out_json = os.path.join(sd, "chunks.json")
    if os.path.exists(out_json):
        j = json.load(open(out_json))
        if len(j["chunks"]) >= n_chunks:
            print(f"[{collection}/{scene}] cached ({len(j['chunks'])} chunks)", flush=True)
            return
    S = Sampler(scene, seed)
    kinds_rng = np.random.RandomState(seed + 1)
    chunks, fails = [], 0
    while len(chunks) < n_chunks:
        kind = pick_kind(collection, kinds_rng)
        fr = S.chunk(kind)
        if fr is None:
            fails += 1
            if fails > 20 * n_chunks:
                print(f"[{collection}/{scene}] giving up at {len(chunks)} chunks", flush=True)
                break
            continue
        frames = []
        for (x, y, yaw, hy, hole) in fr:
            hx, hz = C.world_to_habitat(x, y, S.meta)
            frames.append({"x": x, "y": y, "yaw": yaw,
                           "hab": [hx, hy, hz], "theta": float(C.yaw_to_habitat_theta(yaw)),
                           "scan_nohit_lower": round(hole, 4)})
        chunks.append({"idx": len(chunks), "kind": kind, "frames": frames})
    S.close()

    with open(os.path.join(sd, "poses.txt"), "w") as f:
        for ch in chunks:
            for fr in ch["frames"]:
                f.write(f"{fr['x']!r} {fr['y']!r} {fr['yaw']!r}\n")
    kinds = {k: sum(c["kind"] == k for c in chunks) for k in set(c["kind"] for c in chunks)}
    with open(out_json, "w") as f:
        json.dump({"collection": collection, "scene": scene, "L": C.L, "seed": seed,
                   "cam_height_m": C.CAM_HEIGHT, "n_chunks": len(chunks), "kinds": kinds,
                   "scan_hole_filter": {"rows_from": HOLE_ROW0, "max_nohit": HOLE_MAX},
                   "chunks": chunks}, f)
    print(f"[{collection}/{scene}] {len(chunks)} chunks x {C.L + 1} frames  kinds={kinds}  "
          f"rejected={fails}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True, choices=C.COLLECTIONS)
    ap.add_argument("--scenes", nargs="+", default=C.SCENES)
    ap.add_argument("--n-chunks", type=int, default=300, help="0 = auto from free area (1/m2, 40..200)")
    ap.add_argument("--seed", type=int, default=None, help="default: hash(collection, scene)")
    a = ap.parse_args()
    for i, s in enumerate(a.scenes):
        seed = a.seed if a.seed is not None else (1000 * (1 + C.COLLECTIONS.index(a.collection)) + C.SCENES.index(s))
        run(a.collection, s, a.n_chunks, seed)


if __name__ == "__main__":
    sys.exit(main())
