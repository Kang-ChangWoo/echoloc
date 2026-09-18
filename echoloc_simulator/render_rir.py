#!/usr/bin/env python3
"""Stage 6 — acoustic extension (spec 4): rir/<collection>/<condition>/<scene>/pose_<index:05d>/

    rir.npy                                                        (6, n) float32, 48 kHz — 6-mic ring, rel 0 only
    rir_metadata.json                                              (mono mics have no directivity) (--layout ring)
    rir_binaural.npy, rir_binaural_rel{090,180,270}.npy            (2, n) float32, 48 kHz — RLR HRTF binaural,
    rir_binaural_metadata.json                                     head yaw = camera yaw + rel (--layout binaural)
rir.npy / rir_binaural.npy (rel 0 = camera forward) are the spec-named files.

One RIR per evaluated pose = the reference frame (view L) of every chunk by default
(--all-views renders every frame). pose_<index> is the ROW of poses.txt.

Array: 6 mics, ring r = 0.05 m at angles [pi, 4pi/3, 5pi/3, 2pi, pi/3, 2pi/3] + yaw,
habitat offset = [r cos a, 0, -r sin a] (the -sin is y_f3loc = -z_habitat). Source
co-located with the array centre at CAM_HEIGHT (1.25 m) above the navmesh. RLR has
no multi-mono array layout, so each channel is a separate Mono render with the
receiver moved to the mic position and the source fixed at the centre.

Conditions:
    raw_scan_open      the Replica scan mesh (holes and open boundaries as scanned)
    floorplan_closed   the extruded map.png proxy (floorplan_proxy/<scene>/floorplan.glb)

Usage:  python render_rir.py --collection replica_f --condition raw_scan_open --scenes room_1 [--all-views] [--layout ring|binaural]
"""
import argparse
import json
import os
import sys

import numpy as np

import common as C

COND_GEOM = {"raw_scan_open": "real", "floorplan_closed": "plan"}
COND_NOTE = {
    "raw_scan_open": "Replica scan mesh as shipped (mesh_semantic.ply via replica.scene_dataset_config.json)",
    "floorplan_closed": "watertight proxy extruded floor->ceiling from the same wall mask as map.png "
                        "(floorplan_proxy/<scene>/floorplan.glb, build_floorplan.py)",
}


def ring_offsets(yaw):
    a = C.RING_ANGLES + yaw
    return np.stack([C.RING_R * np.cos(a), np.zeros_like(a), -C.RING_R * np.sin(a)], axis=1)


def render_pose(sim, audio, fr, yaw):
    hx, hy, hz = fr["hab"]
    centre = np.array([hx, hy, hz], dtype=np.float64)
    src = centre + np.array([0.0, C.CAM_HEIGHT, 0.0])
    offs = ring_offsets(yaw)
    chans = []
    for o in offs:
        C.set_agent(sim, *(centre + o), fr["theta"])
        audio.setAudioSourceTransform(src.astype(np.float32))
        ir = np.asarray(sim.get_sensor_observations()["audio"], dtype=np.float32)
        chans.append(ir.reshape(-1))
    n = max(len(c) for c in chans)
    n = max(n, C.DIRECT_GUARD + C.USABLE_LEN + 8)
    rir = np.zeros((C.N_MIC, n), dtype=np.float32)
    for k, c in enumerate(chans):
        rir[k, :len(c)] = c
    return rir, offs, src


def render_pose_binaural(sim, audio, fr):
    """One RLR binaural render: listener at the array centre, head yaw = camera yaw."""
    hx, hy, hz = fr["hab"]
    C.set_agent(sim, hx, hy, hz, fr["theta"])
    src = np.array([hx, hy + C.CAM_HEIGHT, hz], dtype=np.float32)
    audio.setAudioSourceTransform(src)
    ir = np.asarray(sim.get_sensor_observations()["audio"], dtype=np.float32)
    ir = ir.reshape(2, -1) if ir.ndim == 2 else ir.reshape(2, -1)
    n = max(ir.shape[1], C.DIRECT_GUARD + C.USABLE_LEN + 8)
    out = np.zeros((2, n), dtype=np.float32)
    out[:, :ir.shape[1]] = ir
    return out, src


def fname(layout, rel):
    base = "rir" if layout == "ring" else "rir_binaural"
    return f"{base}.npy" if rel == 0 else f"{base}_rel{rel:03d}.npy"


def run(collection, condition, scene, all_views, threads, layout="ring"):
    import habitat_sim
    geom = COND_GEOM[condition]
    chunks = C.read_chunks(collection, scene)
    poses = C.read_poses(collection, scene)
    out_root = os.path.join(C.ROOT, "rir", collection, condition, scene)
    meta_name = "rir_metadata.json" if layout == "ring" else "rir_binaural_metadata.json"
    todo = []
    for c in chunks["chunks"]:
        for v, fr in enumerate(c["frames"]):
            if not all_views and v != C.L:
                continue
            idx = c["idx"] * (C.L + 1) + v
            pd = os.path.join(out_root, f"pose_{idx:05d}")
            headings = C.RING_HEADINGS_DEG if layout == "ring" else C.REL_HEADINGS_DEG
            done = os.path.exists(os.path.join(pd, meta_name)) and all(
                os.path.exists(os.path.join(pd, fname(layout, r))) for r in headings)
            if not done:
                todo.append((idx, fr))
    if not todo:
        print(f"[{collection}/{condition}/{scene}/{layout}] cached", flush=True)
        return
    sim = C.make_sim(scene, geom=geom, audio={"channel": "mono" if layout == "ring" else "binaural", "threads": threads})
    audio = sim.get_agent(0)._sensors["audio"]
    acoustics = {"indirect_rays": C.INDIRECT_RAYS, "ray_depth": C.RAY_DEPTH,
                 "diffraction": C.DIFFRACTION, "max_diffraction_order": C.MAX_DIFFRACTION_ORDER,
                 "transmission": C.TRANSMISSION, "materials_enabled": False}
    for n, (idx, fr) in enumerate(todo):
        x, y, yaw = poses[idx]
        assert abs(x - fr["x"]) < 1e-9 and abs(yaw - fr["yaw"]) < 1e-9
        pd = os.path.join(out_root, f"pose_{idx:05d}")
        os.makedirs(pd, exist_ok=True)
        per_heading = {}
        for rel in headings:
            yaw_h = float(C.wrap(yaw + np.deg2rad(rel)))
            fr_h = dict(fr, theta=float(C.yaw_to_habitat_theta(yaw_h)))
            if layout == "ring":
                rir, offs, src = render_pose(sim, audio, fr_h, yaw_h)
                nch = C.N_MIC
            else:
                rir, src = render_pose_binaural(sim, audio, fr_h)
                offs = None
                nch = 2
            np.save(os.path.join(pd, fname(layout, rel)), rir)
            peaks = [int(np.argmax(np.abs(rir[k, :C.DIRECT_GUARD * 2]))) for k in range(nch)]
            per_heading[f"rel{rel:03d}"] = {
                "file": fname(layout, rel), "rel_heading_deg": rel, "yaw_rad": yaw_h,
                "habitat_theta": fr_h["theta"], "n_samples": int(rir.shape[1]),
                "direct_peak_index": int(min(peaks)), "direct_peak_index_per_channel": peaks,
                **({"channel_offsets_habitat_m": offs.tolist()} if offs is not None else {}),
            }
        meta = {
            "pose_index": int(idx), "collection": collection, "scene": scene,
            "f3loc_pose_m_rad": [float(x), float(y), float(yaw)],
            "array_center_habitat": [float(v) for v in src],
            "layout": ("6-mic ring, Mono x 6 (receiver moved to each mic, source fixed at the centre)" if layout == "ring"
                       else "RLR Binaural (built-in HRTF), channels [left, right], head yaw = camera yaw + rel"),
            "headings": "rel000 = camera forward (rir.npy / rir_binaural.npy, the spec file); binaural also rel090/180/270 = yaw + rel, CCW; "
                        "the mono ring has no directivity so it is rendered at rel000 only",
            "per_heading": per_heading,
            **({"channel_order": "ring angles [pi, 4pi/3, 5pi/3, 2pi, pi/3, 2pi/3] + yaw_h, CCW in the f3loc x,y plane; "
                                 "channel 3 (angle 2pi + yaw_h) points along the heading"} if layout == "ring" else {}),
            "sample_rate_hz": C.SR,
            "direct_sound_guard_samples": C.DIRECT_GUARD, "usable_length_samples": C.USABLE_LEN,
            "guard_usable_at_8khz_spec": [C.DIRECT_GUARD_8K, C.USABLE_LEN_8K],
            "source": "co-located with the array centre, height %.2f m above the navmesh" % C.CAM_HEIGHT,
            "condition": condition, "condition_note": COND_NOTE[condition],
            "simulator": {"name": "soundspaces", "backend": "habitat-sim RLRAudioPropagation",
                          "version": habitat_sim.__version__, "scene": scene},
            "acoustics": acoustics,
        }
        with open(os.path.join(pd, meta_name), "w") as f:
            json.dump(meta, f, indent=1)
        if (n + 1) % 50 == 0:
            print(f"[{collection}/{condition}/{scene}/{layout}] {n + 1}/{len(todo)}", flush=True)
    sim.close()
    print(f"[{collection}/{condition}/{scene}/{layout}] done {len(todo)} poses x {len(headings)} headings", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", required=True, choices=C.COLLECTIONS)
    ap.add_argument("--condition", required=True, choices=list(C.CONDITIONS))
    ap.add_argument("--scenes", nargs="+", default=C.SCENES)
    ap.add_argument("--all-views", action="store_true")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--layout", default="ring", choices=["ring", "binaural"])
    a = ap.parse_args()
    for s in a.scenes:
        run(a.collection, a.condition, s, a.all_views, a.threads, a.layout)


if __name__ == "__main__":
    sys.exit(main())
