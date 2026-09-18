#!/usr/bin/env python3
"""Write <dataset>/dataset_meta.json — every global convention and generation
setting in one machine-readable place (per-scene: maps/<scene>/scene_meta.json,
per-RIR: rir_metadata.json). Re-run after any regeneration; counts are measured."""
import glob
import json
import os
import subprocess
import sys
from datetime import date

import numpy as np

import common as C


def git_head(path):
    try:
        return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def count(collection):
    frames = 0
    dmaps = {"depth_radial_scan": 0, "depth_radial_floorplan": 0}
    for s in C.SCENES:
        p = os.path.join(C.scene_dir(collection, s), "poses.txt")
        frames += sum(1 for _ in open(p)) if os.path.exists(p) else 0
        for d in dmaps:
            dmaps[d] += len(glob.glob(os.path.join(C.scene_dir(collection, s), d, "*.png")))
    conds = {}
    for cond in ("raw_scan_open", "floorplan_closed"):
        conds[cond] = {"ring6": len(glob.glob(os.path.join(C.ROOT, "rir", collection, cond, "*", "pose_*", "rir.npy"))),
                       "binaural": len(glob.glob(os.path.join(C.ROOT, "rir", collection, cond, "*", "pose_*", "rir_binaural.npy")))}
    return {"scenes": len(C.SCENES), "frames": frames, "chunks": frames // (C.L + 1), "depth_maps": dmaps, "rir_poses": conds}


def main():
    import habitat_sim
    meta = {
        "name": "echoloc_dataset",
        "description": "Replica scenes rendered as an F3Loc-compatible floorplan localization dataset "
                       "(two 4-view collections, wall-only maps, ray-cast depth GT, desdf) with a co-located "
                       "6-mic ring RIR per reference frame (AV-FPLoc acoustic extension).",
        "generated": str(date.today()),
        "spec": "../dataset_generation_spec.md",
        "generator": {"code": "/mnt/sdb/soundspaces/echoloc/echoloc_simulator", "entry": "run_all.sh", "profile": C.DATASET,
                      "conventions_source": "common.py"},
        "collections": {
            "replica_f": {"motion": "forward: step U(0.15,0.40) m along heading, yaw drift N(0,4deg) clipped +-10deg"},
            "replica_g": {"motion": "40% forward (yaw U(-20,20)deg, step U(0.10,0.40) m); 35% in-place rotation "
                                    "(monotonic U(10,35)deg/step, translation N(0,0.02) m); 25% mixed "
                                    "(step U(0,0.30) m within +-60deg of heading, yaw U(-35,35)deg)"},
        },
        "chunk": {"L": C.L, "views_per_chunk": C.L + 1, "reference_view": C.L,
                  "rgb_name": "{chunk:05d}-{view}.png", "rows_per_scene": "len(poses) % 4 == 0"},
        "split": C.SPLIT,
        "excluded_scenes": {"apartment_0": "two-storey scan (5.2 m floor-to-ceiling); no single-floor wall map"},
        "pose": {
            "format": "poses.txt: one line per frame 'x y yaw', ascending in rgb filename order",
            "type": "global SE(2) pose in the floorplan frame (not relative)",
            "position_units": "metres, origin = centre of map.png",
            "rotation": "yaw only (scalar, radians, [-pi, pi]), CCW from +x; roll = pitch = 0; no quaternion/matrix stored",
            "map_pixel": "x_map = x/0.01 + W/2 (col), y_map = y/0.01 + H/2 (row); occ[row, col]; display with origin='lower'",
            "habitat_to_world": "x = habitat_x - world_cx_habitat; y = -habitat_z - world_cy_habitat_neg_z; "
                                "habitat theta (about +y, forward = -z) = yaw - pi/2   (per-scene offsets in maps/<scene>/scene_meta.json)",
            "height": f"camera/array {C.CAM_HEIGHT} m above the navmesh floor (floor_y_habitat in scene_meta.json); "
                      "per-frame habitat xyz in chunks.json['chunks'][i]['frames'][v]['hab']",
        },
        "camera": {"height_px": C.IMG_H, "width_px": C.IMG_W,
                   "K": [[C.FX, 0, C.IMG_W / 2], [0, C.FX, C.IMG_H / 2], [0, 0, 1]],
                   "hfov_deg": round(C.HFOV_DEG, 4), "F_W": C.F_W, "roll_pitch": 0.0,
                   "height_above_floor_m": C.CAM_HEIGHT, "format": "PNG 8-bit RGB"},
        "map": {"resolution_m_per_px": C.MAP_RES, "free": 255, "obstacle": "anything != 255 (walls and building exterior = 0)",
                "channels": "3 identical", "source": "0.05 m wall mask (height-band vote, furniture/lintels removed, "
                "navmesh envelope sealed, rooms = flood fill from SoundSpaces graph nodes) upsampled x5 nearest",
                "same_geometry_as": "floorplan_proxy/<scene>/floorplan.glb (extruded floor->ceiling)"},
        "depth": {"files": ["depth40.txt", "depth160.txt"], "rays": [40, 160],
                  "angles": "center_angs = flip(arctan2(u - u.mean(), ray_n * F_W)) + yaw",
                  "value": "camera-forward z-depth = ray range * cos(center_ang), metres",
                  "dist_max_m": C.DIST_MAX_M, "saturation": "rays leaving the map = dist_max (finite)",
                  "ray_cast": "echoloc_simulator/raycast.py (exact Amanatides-Woo DDA); NOT F3Loc utils.ray_cast, "
                              "which skips wall-corner pixels on left/down steps and leaked 0.3-0.4% of rays"},
        "depth_maps": {
            "dirs": {"depth_radial_scan": "Replica scan mesh (furniture included)",
                     "depth_radial_floorplan": "floor-plan proxy (walls only; the geometry map.png encodes)"},
            "name": "{chunk:05d}-{view}.png (same as rgb/)", "format": "16-bit PNG, millimetres, 0 = no hit",
            "value": "radial (Euclidean along the pixel ray), NOT camera-forward z: "
                     "radial = z * sqrt(1 + ((u+0.5-cx)/fx)^2 + ((v+0.5-cy)/fy)^2)",
            "camera": "same K / pose / height as rgb/"},
        "desdf": {"scenes": C.SPLIT["test"], "cell_m": 0.1, "orientations": 36, "bin_deg": 10, "max_dist_m": 10.0,
                  "dtype": "float32", "layout": "{'l': int, 't': int, 'desdf': (H, W, 36)}; x_map = x_desdf*10 + l"},
        "scan_voids": {"note": "Replica scans have unscanned space (frl_apartment_*: no ceiling; apartment_1/2: voids behind doorways). "
                               "Every pose is kept; chunks.json['chunks'][i]['frames'][v]['scan_nohit_lower'] = fraction of no-hit "
                               "pixels below image row 120 when the scan is rendered at that frame (0 = fully covered). Filter downstream.",
                       "worst_scenes_frames_over_15pct": {"apartment_2": "~47%", "apartment_1": "~35%", "office_2": "~19%"}},
        "pose_sampling": {"source": "habitat navmesh (pathfinder.get_random_navigable_point, seeded per scene)",
                          "constraints": [f"map pixel free", f"clearance >= {C.MIN_CLEARANCE} m from nearest wall pixel",
                                          "snap_point within 3 cm horizontally and 0.3 m vertically of the scene floor",
                                          "segment between consecutive frames does not cross a wall"],
                          "chunks_per_scene": 300},
        "acoustics": {
            "layout": "rir/<collection>/<condition>/<scene>/pose_{index:05d}/{rir.npy, rir_metadata.json, rir_binaural.npy, rir_binaural_metadata.json}",
            "binaural": "rir_binaural*.npy (2, n) float32 = RLR built-in HRTF binaural render at the same pose, head yaw = camera yaw + rel, "
                        "channels [left, right], same source/acoustics as the ring",
            "pose_index": "row of the collection's poses.txt (reference frames only, view 3)",
            "conditions": {"raw_scan_open": "Replica scan mesh as shipped (open boundaries, scan holes)",
                           "floorplan_closed": "floorplan_proxy/<scene>/floorplan.glb"},
            "sample_rate_hz": C.SR, "sample_rate_note": "spec 8000; 48 kHz to match the earlier replica_0422/house_traj renders",
            "headings": {"binaural_rel_deg": list(C.REL_HEADINGS_DEG), "ring_rel_deg": list(C.RING_HEADINGS_DEG),
                         "files": "rel000 -> rir.npy / rir_binaural.npy; binaural others -> rir_binaural_rel{deg:03d}.npy",
                         "note": "yaw_h = camera yaw + rel (CCW); the mono ring has no directivity so only rel 0 is rendered"},
            "n_mics": C.N_MIC, "ring_radius_m": C.RING_R,
            "ring_angles_rad": (C.RING_ANGLES).tolist(), "ring_angles_note": "+ yaw; channel 3 (angle 2pi) = camera forward",
            "channel_offset_habitat": "[r cos a, 0, -r sin a]",
            "source": f"co-located with the array centre, {C.CAM_HEIGHT} m above the navmesh floor",
            "direct": True, "indirect": True, "indirect_rays": C.INDIRECT_RAYS, "indirect_ray_depth": C.RAY_DEPTH,
            "diffraction": C.DIFFRACTION, "max_diffraction_order": C.MAX_DIFFRACTION_ORDER, "transmission": C.TRANSMISSION, "materials": False,
            "diffraction_note": "spec 4.3 lists diffraction=false; enabled deliberately because the dataset targets NLOS "
                                "(cost-neutral in RLR)",
            "channel_render": "RLR Mono x 6: receiver moved to each mic position, source fixed",
            "rir_shape": "(6, n) float32 (n varies; RLR trims when energy is gone, ~0.4 s at ray depth 50)",
            "direct_sound_guard_samples": C.DIRECT_GUARD, "usable_length_samples": C.USABLE_LEN,
            "guard_usable_at_8khz_spec": [C.DIRECT_GUARD_8K, C.USABLE_LEN_8K],
            "usable_window": "rir[:, peak+guard : peak+guard+usable] (same 2 ms / 128 ms as the spec at 8 kHz)",
        },
        "simulator": {
            "habitat_sim": habitat_sim.__version__,
            "habitat_sim_install": os.path.dirname(habitat_sim.__file__),
            "audio_backend": "RLRAudioPropagation (habitat_sim/_ext/libRLRAudioPropagation.so)",
            "habitat_sim_source": {"path": "/home/rvi-lab/workspace/habitat-sim", "git": git_head("/home/rvi-lab/workspace/habitat-sim")},
            "sound_spaces_source": {"path": "/home/rvi-lab/workspace/sound-spaces", "git": git_head("/home/rvi-lab/workspace/sound-spaces")},
            "conda_env": "ss_v2 (LD_PRELOAD libstdc++/libz, see echoloc_simulator/env.sh)",
            "replica_source": {"nas": "/file1/rvi/dataset/replica/raw", "local_copy": C.RAW_DIR,
                               "scene_dataset_config": "replica.scene_dataset_config.json (z-up -> habitat y-up)"},
            "wall_mask_source": {"path": C.TEST_OUT, "script": "echoloc_simulator/floorplan_extraction/build_floorplan.py (ex floorplan_vs_mesh)"},
            "f3loc_reference": {"repo": "https://github.com/felix-ch/f3loc", "git": git_head(C.F3LOC),
                                "used_for": "conventions only; ray_cast replaced (see depth.ray_cast)"},
        },
        "rir_version_history": [
            {"version": "v1", "date": "2026-09-08", "settings": "8 kHz, 4096 rays, depth 6, diffraction OFF, ring 6ch only, 1 heading, (6, 2049)",
             "status": "spec 4.3 verbatim; discarded and DELETED (NLOS needs diffraction)"},
            {"version": "v2", "date": "2026-09-09", "settings": "8 kHz, 65536 rays, depth 6, diffraction on", "status": "aborted, deleted (sample rate/headings changed to match earlier renders)"},
            {"version": "v3", "date": "2026-09-09", "settings": "48 kHz, 20000 rays, depth 200, ring and binaural at 4 headings", "status": "aborted, deleted (~36 h / ~300 GB for no information gain)"},
            {"version": "final", "date": "2026-09-09", "settings": "48 kHz, 20000 rays, depth 50, diffraction on (order 10), ring 6ch rel 0 + binaural 2ch rel 0/90/180/270", "status": "current rir/"},
        ],
        "deviations_from_spec": [
            "ray cast: exact DDA (echoloc_simulator/raycast.py) instead of F3Loc utils.ray_cast (corner-pixel leak)",
            "17 scenes (Replica), not >= 60",
            "RIR rendered for reference frames only (render_rir.py --all-views for every frame)",
            "camera height 1.25 m chosen to co-locate with the acoustic source",
            "RIR rendered WITH edge diffraction (spec acoustics block says false) — NLOS",
            "RIR indirect rays 20000 and ray depth 50 instead of 4096 / 6: at 4096 rays identical re-renders correlate only ~0.74, and depth 6 drops all reflections beyond ~36 ms; depth 50 matches depth 200 (RLR default) in energy terms at 1/3 the cost",
            "RIR sample rate 48 kHz instead of 8 kHz; binaural at 4 relative headings (0/90/180/270) per pose as in the earlier Replica/MP3D renders (ring at rel 0 only: mono mics have no directivity)",
        ],
        "counts": {col: count(col) for col in C.COLLECTIONS},
    }
    if C.DATASET == "mp3d":
        meta["name"] = "echoloc_dataset (MP3D collections)"
        meta["description"] = ("Matterport3D buildings rendered as an F3Loc-compatible floorplan localization dataset: one scene id "
                               "per STOREY ('<scene>_f<k>'), two 4-view collections (mp3d_f forward, mp3d_g general motion), "
                               "wall-only per-storey maps, ray-cast depth GT, desdf, and co-located 6-mic ring + binaural RIRs.")
        meta["collections"] = {"mp3d_f": meta["collections"]["replica_f"], "mp3d_g": meta["collections"]["replica_g"]}
        meta["excluded_scenes"] = {"note": "buildings without SoundSpaces graph metadata or without a usable storey mask are absent; "
                                           "storeys with < 4 graph nodes or < 8 m2 sealed interior are skipped"}
        meta["storeys"] = {"scene_id": "<mp3d scene>_f<k>, k = 0 lowest storey (SoundSpaces graph nodes clustered by height, gap > 1 m)",
                           "frame": "all storeys of a building share one map frame (same origin/size); z band per storey in maps/<id>/scene_meta.json",
                           "n_scene_ids": len(C.SCENES), "n_buildings": len({C.base_scene(s) for s in C.SCENES})}
        meta["simulator"]["replica_source"] = {"nas": "/file1/rvi/dataset/matterport/sound-spaces/data/scene_datasets/matterport/mp3d",
                                               "local_copy": C.RAW_DIR, "scene_dataset_config": "mp3d.scene_dataset_config.json"}
        meta["simulator"]["wall_mask_source"] = {"path": C.TEST_OUT, "script": "echoloc_simulator/floorplan_extraction/build_floorplan_mp3d.py (per storey)"}
        meta["pose_sampling"]["chunks_per_scene"] = "auto: 0.6 per m2 of sealed free area, clipped to [40, 160] (sample_poses.py --n-chunks 0)"
        meta["deviations_from_spec"] = [d for d in meta["deviations_from_spec"] if "17 scenes" not in d]
    if C.DATASET == "gibson":
        meta["name"] = "echoloc_dataset (Gibson collections)"
        meta["description"] = ("Gibson buildings (habitat trainval release) rendered as an F3Loc-compatible floorplan localization "
                               "dataset: one scene id per STOREY ('<scene>_f<k>'), two 4-view collections (gibson_f forward, "
                               "gibson_g general motion), wall-only per-storey maps, ray-cast depth GT, desdf, and co-located "
                               "6-mic ring RIRs (ring only; binaural not rendered for this release).")
        meta["collections"] = {"gibson_f": meta["collections"]["replica_f"], "gibson_g": meta["collections"]["replica_g"]}
        meta["excluded_scenes"] = {"note": "4 of 492 buildings have no usable storey; storeys whose ceiling does not clear the "
                                           "1.25 m camera by 0.15 m (101) or with < 8 m2 sealed interior (10) are skipped"}
        meta["storeys"] = {"scene_id": "<gibson scene>_f<k>, k = 0 lowest storey (navmesh samples clustered by height-histogram modes; "
                                       "gap clustering fails on Gibson because stairs are navigable)",
                           "frame": "all storeys of a building share one map frame (same origin/size); z band per storey in maps/<id>/scene_meta.json",
                           "n_scene_ids": len(C.SCENES), "n_buildings": len({C.base_scene(s) for s in C.SCENES})}
        meta["semantic_maps"] = {"available": False,
                                 "reason": "the habitat Gibson release ships only <scene>.glb + <scene>.navmesh; no per-face object "
                                           "ids or door/window annotation exist, so wall/window/door cannot be labelled"}
        meta["simulator"]["replica_source"] = {"origin": "Stanford Gibson habitat release (gibson_habitat_trainval.zip)",
                                               "local_copy": C.RAW_DIR, "scene_dataset_config": None}
        meta["simulator"]["wall_mask_source"] = {"path": C.TEST_OUT, "script": "echoloc_simulator/floorplan_extraction/build_floorplan_gibson.py (per storey)"}
        meta["pose_sampling"]["chunks_per_scene"] = "auto: 0.6 per m2 of sealed free area, clipped to [40, 160] (sample_poses.py --n-chunks 0)"
        meta["pose_sampling"]["constraints"].append("camera (navmesh y + 1.25 m) stays >= 0.15 m below the storey ceiling (split-level landings rejected)")
        meta["acoustics"]["binaural"] = "NOT rendered for gibson (user decision 2026-09-16); add later with LAYOUT=binaural ./run_all.sh rir"
        meta["acoustics"]["headings"]["binaural_rel_deg"] = []
        meta["deviations_from_spec"] = [d for d in meta["deviations_from_spec"] if "17 scenes" not in d] + [
            "gibson: ring RIRs only, no binaural"]
    if C.DATASET == "s3d":
        meta["name"] = "echoloc_dataset (Structured3D collection)"
        meta["description"] = ("Structured3D houses imported as an F3Loc-compatible floorplan localization collection: single-view "
                               "(L = 0) perspective renders at the dataset's fixed camera positions, wall-only maps from annotation_3d.json, "
                               "ray-cast depth GT, desdf, and floorplan_closed RIRs (ring + binaural) on the extruded map proxy. "
                               "No scan mesh exists, so there is no raw_scan_open condition and no rendering at new poses.")
        meta["collections"] = {"s3d": {"motion": "none: one image per S3D camera position (perspective/full), camera as shipped"}}
        meta["chunk"] = {"L": 0, "views_per_chunk": 1, "reference_view": 0, "rgb_name": "{step:05d}.png"}
        meta["excluded_scenes"] = {"note": "scenes without usable frames are absent; frames whose camera lies on a non-free map pixel are skipped (counted in scene_meta.json)"}
        meta["camera"] = {"height_px": C.IMG_H, "width_px": C.IMG_W, "K": [[C.FX, 0, C.IMG_W / 2], [0, C.FY, C.IMG_H / 2], [0, 0, 1]],
                          "hfov_deg": round(C.HFOV_DEG, 4), "F_W": float(C.F_W), "F_W_note": "S3D camera (xfov 0.698 rad): F_W = 0.596, NOT the Gibson 3/8 — set F_W accordingly in F3Loc configs",
                          "roll_pitch": "non-zero in S3D; images and depth_radial_scan are gravity-aligned with F3Loc utils.gravity_align; per-frame roll/pitch kept in chunks.json",
                          "height_above_floor_m": "per frame (chunks.json frames[].cam_z), ~1.2-1.7 m", "format": "PNG 8-bit RGB, 1280x720 downsized to 640x360"}
        meta["map"]["source"] = "annotation_3d.json room floor polygons rasterised on a 0.05 m grid (walls 1 cell, doors between rooms opened, exterior doors and windows solid), upsampled x5 nearest"
        meta["depth_maps"] = {"dirs": {"depth_radial_scan": "S3D's own furnished depth render (planar z, verified) converted to radial with the 1280x720 intrinsics, gravity-aligned",
                                       "depth_radial_floorplan": "floor-plan proxy rendered in habitat at the same pose"},
                              "name": "{step:05d}.png", "format": "16-bit PNG, millimetres, 0 = no hit / invalid", "value": "radial (Euclidean along the pixel ray)"}
        meta["pose_sampling"] = {"source": "Structured3D perspective camera positions as shipped (no sampling)"}
        meta["acoustics"]["conditions"] = {"floorplan_closed": "floorplan_proxy/<scene>/floorplan.glb (the only geometry available)"}
        meta["acoustics"]["source"] = "co-located with the camera at the S3D camera height (per frame)"
        meta["simulator"]["replica_source"] = {"nas": "/file1/rvi/dataset/Structured3D (perspective_full zips + annotation_3d.json)", "local_copy": C.RAW_DIR}
        meta["simulator"]["wall_mask_source"] = {"path": "annotation_3d.json", "script": "echoloc_simulator/build_s3d.py"}
        meta["deviations_from_spec"] = [d for d in meta["deviations_from_spec"] if "17 scenes" not in d] + [
            "S3D: camera F_W = 0.596 (80 deg HFOV, 640x360) instead of 3/8", "S3D: single view per pose (no 4-view chunks)",
            "S3D: only the floorplan_closed acoustic condition (no scan mesh exists)"]
    out = os.path.join(C.ROOT, "dataset_meta.json")
    with open(out, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print("wrote", out)
    print(json.dumps(meta["counts"], indent=1))


if __name__ == "__main__":
    sys.exit(main())
