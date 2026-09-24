"""Shared constants, paths and coordinate conventions for the echoloc F3Loc datasets (Replica / MP3D).

Everything that the spec (<dataset>/dataset_generation_spec.md) pins down lives here so
that no stage can drift from another:

  * camera        480x640, K = [[240,0,320],[0,240,240],[0,0,1]]  (F_W = 3/8)
  * map           0.01 m/pixel, free space == 255, world origin = map centre
  * habitat->f3loc: x = hx, y = -hz, yaw measured CCW in the (x, y) plane,
                    habitat agent yaw theta (about +y, forward = -z) <-> yaw = theta + pi/2
  * acoustics     48 kHz, 6-mic ring r=0.05 m + binaural, 4 relative headings, source co-located, height 1.25 m,
                  direct + indirect (20000 rays, depth 50) + edge diffraction (order 10), no transmission/materials

Sources of the geometry:
  * wall masks / floor-plan proxies: floorplan_extraction/replica/<scene>/
    (floorplan_extraction/build_floorplan.py — 0.05 m cells, walls voted across height bands,
    envelope sealed from the navmesh; furniture removed)
  * real meshes + navmeshes: /file1/rvi/dataset/replica/raw/<scene>/
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))                     # echoloc_simulator/
DATASET = os.environ.get("ECHOLOC_DATASET", "replica")                 # replica | mp3d | gibson | s3d (selects the profile below)
BASE = os.environ.get("ECHOLOC_DATA", "/mnt/sdb/soundspaces/echoloc/echoloc_dataset")   # holds one folder per dataset
ROOT = os.path.join(BASE, DATASET)   # this dataset's root: <collection>/, maps/, floorplan_proxy/, desdf/, rir/, dataset_meta.json
F3LOC = os.path.join(HERE, "third_party", "f3loc")
SS_META = os.environ.get("SS_META_DIR", "/file2/changwoo/soundspaces/replica/metadata")
PROXY_DIR = os.path.join(ROOT, "floorplan_proxy")          # copied floorplan.glb per scene (part of the dataset)
VAL_DIR = os.path.join(HERE, "validation")                 # generation by-products, not part of the dataset
LOG_DIR = os.path.join(HERE, "logs")

if DATASET == "replica":
    RAW_DIR = os.environ.get("REPLICA_RAW_DIR", "/mnt/sdb/replica_raw")   # local copy of /file1/rvi/dataset/replica/raw
    SCENE_CONFIG = os.path.join(RAW_DIR, "replica.scene_dataset_config.json")
    TEST_OUT = os.environ.get("FLOORPLAN_OUT", os.path.join(HERE, "floorplan_extraction", "replica"))
    COLLECTIONS = ("replica_f", "replica_g")
elif DATASET == "mp3d":
    RAW_DIR = os.environ.get("MP3D_MESH_DIR", "/mnt/sdb/mp3d_raw")        # local copy of sound-spaces/.../scene_datasets/matterport/mp3d
    SCENE_CONFIG = os.path.join(RAW_DIR, "mp3d.scene_dataset_config.json")
    TEST_OUT = os.environ.get("FLOORPLAN_OUT", os.path.join(HERE, "floorplan_extraction", "mp3d_floors"))
    COLLECTIONS = ("mp3d_f", "mp3d_g")
elif DATASET == "gibson":
    RAW_DIR = os.environ.get("GIBSON_MESH_DIR", "/mnt/sdb/gibson_raw/gibson")   # habitat release: <scene>.glb + .navmesh
    SCENE_CONFIG = None                                                   # no dataset config: the glb is loaded directly
    TEST_OUT = os.environ.get("FLOORPLAN_OUT", os.path.join(HERE, "floorplan_extraction", "gibson_floors"))
    COLLECTIONS = ("gibson_f", "gibson_g")
elif DATASET == "s3d":
    RAW_DIR = os.environ.get("S3D_RAW_DIR", "/mnt/sdb/s3d_raw/Structured3D")   # extracted perspective/full + annotation_3d.json
    SCENE_CONFIG = None                                                   # no mesh: only the floor-plan proxy exists
    TEST_OUT = None
    COLLECTIONS = ("s3d",)                                                # single-view (F3Loc S3D style), L = 0
elif DATASET == "zind":
    RAW_DIR = os.environ.get("ZIND_RAW_DIR", "/mnt/sdb/zind_raw")         # <home>/zind_data.json + panos/ + floor_plans/
    SCENE_CONFIG = None                                                   # no mesh: only the floor-plan proxy exists
    TEST_OUT = None
    COLLECTIONS = ("zind",)                                               # single-view (L = 0): one crop per panorama
else:
    raise ValueError(f"ECHOLOC_DATASET={DATASET!r}")


CONDITIONS = ("floorplan_closed",) if DATASET in ("s3d", "zind") else ("raw_scan_open", "floorplan_closed")
GEOMS = ("plan",) if DATASET in ("s3d", "zind") else ("real", "plan")   # depth-map geometries available


def base_scene(scene):
    """mp3d/gibson/zind scene ids are '<scene>_f<k>' (one map per storey); the simulator loads '<scene>'."""
    if DATASET in ("mp3d", "gibson", "zind") and "_f" in scene:
        return scene.rsplit("_f", 1)[0]
    return scene


# ---- visual ---------------------------------------------------------------
MAP_RES = 0.01            # m / pixel of map.png (fixed by F3Loc)
SRC_CELL = 0.05           # m / cell of the source wall mask
UPSAMPLE = int(round(SRC_CELL / MAP_RES))   # 5
if DATASET == "s3d":
    IMG_H, IMG_W = 360, 640                                     # F3Loc's S3D convention (1280x720 downsized)
    FX = (IMG_W / 2) / np.tan(0.698132)                         # S3D xfov (half) = 0.698132 rad -> HFOV 80 deg
    FY = (IMG_H / 2) / np.tan(0.440992)
    L = 0                                                       # single view: every frame is its own chunk
    CAM_HEIGHT = 1.5                                            # nominal; real per-frame camera z is stored (hab y = cam_z - 1.5)
elif DATASET == "zind":
    IMG_H, IMG_W = 480, 640                                     # same pinhole as replica/mp3d/gibson: F_W = 3/8.
    FX = FY = 240.0                                             # 2048x1024 panoramas give 605x512 source px for this
    L = 0                                                       # crop -> essentially 1:1, no meaningful upsampling
    CAM_HEIGHT = 1.5                                            # nominal; the real per-pano height (median 1.44 m) is
                                                                # stored per frame (hab y = cam_z - 1.5), as for s3d
else:
    IMG_H, IMG_W = 480, 640
    FX = 240.0
    FY = 240.0
    L = 3                                                       # views 0..L per chunk, view L is the reference frame
    CAM_HEIGHT = 1.25                                           # m above the navmesh floor; == acoustic source height (co-located)
HFOV_DEG = float(np.degrees(2 * np.arctan((IMG_W / 2) / FX)))   # 106.26 (replica/mp3d/gibson/zind) / 80.0 (s3d)
F_W = FX / IMG_W                                                # 3/8 (replica/mp3d/gibson/zind) / 0.596 (s3d)
DIST_MAX_M = 20.0         # ray-cast saturation, metres
MIN_CLEARANCE = 0.25      # m from the nearest wall pixel for every sampled pose

# ---- acoustic -------------------------------------------------------------
SR = 48000                # spec: 8000. 48 kHz to match the earlier replica_0422 / house_traj renders (user, 2026-09-09)
N_MIC = 6
RING_R = 0.05
RING_ANGLES = np.array([np.pi, 4 * np.pi / 3, 5 * np.pi / 3, 2 * np.pi, np.pi / 3, 2 * np.pi / 3])
DIRECT_GUARD_8K, USABLE_LEN_8K = 16, 1024          # spec values, defined at 8 kHz
DIRECT_GUARD = DIRECT_GUARD_8K * SR // 8000          # same durations at SR: 96 / 6144 samples at 48 kHz
USABLE_LEN = USABLE_LEN_8K * SR // 8000
REL_HEADINGS_DEG = (0, 90, 180, 270)                 # binaural: per pose, relative to the camera yaw (HRTF makes headings distinct)
RING_HEADINGS_DEG = (0,)                             # 6-mic mono ring: no directivity, a rotated ring resamples the same 5 cm circle -> rel 0 only
INDIRECT_RAYS = 20000     # = the earlier replica_0422/house_traj renders (spec: 4096; RLR default 5000). Ray-sampling noise: run-to-run corr ~0.74 at 4096, ~0.83 at 16k, ~0.91 at 65k
RAY_DEPTH = 50            # indirectRayDepth (max reflections per ray). 50 == 200 in energy terms (99% by ~53 ms, 0.3% beyond the 128 ms window) at 1/3 the cost; RLR default 200, spec 6
DIFFRACTION = True        # NLOS matters for this dataset: edge diffraction ON (spec 4.3 said false; deliberate deviation, 2026-09-09)
MAX_DIFFRACTION_ORDER = 10  # RLR default
TRANSMISSION = False

# ---- scenes / split -------------------------------------------------------
if DATASET == "replica":
    # off3 split (same as the OAA Replica experiments): val/test disjoint, 3 scenes each.
    # apartment_0 is a two-storey scan (5.2 m floor-to-ceiling); its single wall mask is
    # not a one-floor plan (spec 3.3), so it is left out until per-floor maps exist.
    SPLIT = {
        "train": ["frl_apartment_0", "frl_apartment_1", "frl_apartment_2", "frl_apartment_3",
                  "hotel_0", "office_0", "office_1", "office_2", "room_0", "room_1", "room_2"],
        "val": ["apartment_1", "frl_apartment_4", "office_3"],
        "test": ["apartment_2", "frl_apartment_5", "office_4"],
    }
elif DATASET == "gibson":
    # official Gibson fullplus split; the habitat trainval release ships no test scenes, so the
    # official val set is halved into our val/test. Expanded to the per-storey scene ids.
    _sp = json.load(open(os.path.join(HERE, "floorplan_extraction", "gibson_scene_split.json")))
    _have = sorted(d for d in os.listdir(TEST_OUT) if os.path.isdir(os.path.join(TEST_OUT, d))) if os.path.isdir(TEST_OUT) else []
    SPLIT = {k: [d for d in _have if base_scene(d) in set(v)] for k, v in _sp.items()}
elif DATASET == "zind":
    # ZInD ships its own partition (zind_partition.json: home ids -> train/val/test). Expanded to
    # the per-floor scene ids that build_zind.py produced, so every floor of a home stays in that
    # home's split. Floors without scale_meters_per_coordinate are never built (no metric GT).
    _sy = os.path.join(ROOT, "zind", "split.yaml")
    if os.path.exists(_sy):
        import yaml as _yaml
        SPLIT = {k: list(v) for k, v in _yaml.safe_load(open(_sy)).items()}
    else:
        SPLIT = {"train": [], "val": [], "test": []}
elif DATASET == "s3d":
    # Structured3D standard split by scene id: 0-2999 train, 3000-3249 val, 3250-3499 test,
    # restricted to the scenes extracted under RAW_DIR.
    _sy = os.path.join(ROOT, "s3d", "split.yaml")
    if os.path.exists(_sy):                      # written by build_s3d.py: only scenes that were built
        import yaml as _yaml
        SPLIT = {k: list(v) for k, v in _yaml.safe_load(open(_sy)).items()}
    else:
        _have = sorted(d for d in os.listdir(RAW_DIR) if d.startswith("scene_")) if os.path.isdir(RAW_DIR) else []
        _id = lambda d: int(d.split("_")[1])
        SPLIT = {"train": [d for d in _have if _id(d) < 3000], "val": [d for d in _have if 3000 <= _id(d) < 3250],
                 "test": [d for d in _have if _id(d) >= 3250]}
else:
    # matterport3d_0303renew scene_split.json (72/9/9 buildings, disjoint), expanded to the
    # per-storey scene ids that build_floorplan_mp3d.py produced; every storey of a
    # building stays in that building's split.
    _sp = json.load(open(os.path.join(HERE, "floorplan_extraction", "mp3d_scene_split.json")))
    _have = sorted(d for d in os.listdir(TEST_OUT) if os.path.isdir(os.path.join(TEST_OUT, d))) if os.path.isdir(TEST_OUT) else []
    SPLIT = {k: [d for d in _have if base_scene(d) in set(v)] for k, v in _sp.items()}
SCENES = SPLIT["train"] + SPLIT["val"] + SPLIT["test"]
assert len(set(SCENES)) == len(SCENES)
if DATASET == "replica":
    assert len(SCENES) == 17


def f3loc_import():
    if F3LOC not in sys.path:
        sys.path.insert(0, F3LOC)


def scene_dir(collection, scene):
    return os.path.join(ROOT, collection, scene)


def load_meta(scene):
    """scene_meta.json written by build_maps.py (shared by both collections)."""
    with open(os.path.join(ROOT, "maps", scene, "scene_meta.json")) as f:
        return json.load(f)


def load_map(scene):
    from PIL import Image
    occ = np.array(Image.open(os.path.join(ROOT, "maps", scene, "map.png")))
    if occ.ndim == 3:
        occ = occ[:, :, 0]
    return occ


def close_diagonal_leaks(occ, max_pass=8):
    """Fill 1-px corners where wall pixels touch only diagonally.

    F3Loc's ray_cast (a DDA that tests the pixel it is *leaving* on left/down
    steps) slides through such corner contacts, and on the staircase edge of a
    rotated wall a grazing ray can slide corner to corner all the way to the map
    border (observed: 0.27% of rays returning dist_max through a wall at 3 m).
    Making the wall mask 4-connected costs one map pixel (1 cm) per corner and
    fixes depth GT, desdf and the evaluation ray casts consistently.
    Returns (occ_fixed, n_pixels_added)."""
    wall = occ != 255
    added = 0
    for _ in range(max_pass):
        a, b, c, d = wall[:-1, :-1], wall[1:, 1:], wall[:-1, 1:], wall[1:, :-1]
        d1 = a & b & ~c & ~d          # \ contact -> fill upper-right
        d2 = c & d & ~a & ~b          # / contact -> fill upper-left
        n = int(d1.sum() + d2.sum())
        if n == 0:
            break
        wall[:-1, 1:] |= d1
        wall[:-1, :-1] |= d2
        added += n
    out = np.where(wall, 0, 255).astype(np.uint8)
    return out, added


# ---- coordinates -----------------------------------------------------------
def habitat_to_world(hx, hz, meta):
    """habitat (x, z) on the floor -> f3loc world metres (origin = map centre)."""
    return hx - meta["world_cx_habitat"], -hz - meta["world_cy_habitat_neg_z"]


def world_to_habitat(x, y, meta):
    return x + meta["world_cx_habitat"], -(y + meta["world_cy_habitat_neg_z"])


def yaw_to_habitat_theta(yaw):
    """f3loc yaw (CCW from +x in the x,-z plane) -> habitat rotation about +y."""
    return yaw - np.pi / 2


def habitat_theta_to_yaw(theta):
    return wrap(theta + np.pi / 2)


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def world_to_map(x, y, occ_shape):
    """-> (row, col) float pixels, F3Loc convention (row = y, col = x)."""
    H, W = occ_shape[:2]
    return y / MAP_RES + H / 2, x / MAP_RES + W / 2


def habitat_quat(theta):
    from habitat_sim.utils.common import quat_from_angle_axis
    return quat_from_angle_axis(float(theta), np.array([0.0, 1.0, 0.0]))


# ---- habitat ---------------------------------------------------------------
def make_sim(scene, geom="real", rgb=False, depth=False, audio=None):
    """geom: 'real' (Replica mesh, resolved through the dataset config so the z-up
    transform runs) or 'plan' (floor-plan proxy glb from build_floorplan.py).
    audio: None or dict(channel='mono'|'binaural') -> adds an RLR audio sensor."""
    import habitat_sim
    from habitat_sim import SensorSubType, SensorType

    backend = habitat_sim.SimulatorConfiguration()
    if geom == "plan":
        backend.scene_id = os.path.join(PROXY_DIR, scene, "floorplan.glb")
    elif DATASET == "s3d":
        raise ValueError("Structured3D has no scan mesh: only geom='plan' can be simulated")
    elif DATASET == "replica":
        backend.scene_id = scene
        backend.scene_dataset_config_file = SCENE_CONFIG
    elif DATASET == "gibson":
        backend.scene_id = os.path.join(RAW_DIR, f"{base_scene(scene)}.glb")
    else:
        b = base_scene(scene)
        backend.scene_id = os.path.join(RAW_DIR, b, f"{b}.glb")
        backend.scene_dataset_config_file = SCENE_CONFIG
    backend.enable_physics = False
    backend.load_semantic_mesh = False
    # Replica's PTex mesh fails to load without a renderer ("submesh ID 0 is out of
    # range"), even for audio/navmesh-only use — keep the renderer on always.
    backend.create_renderer = True
    backend.requires_textures = bool(rgb) and geom == "real"

    specs = []
    for uuid, st, want in (("rgb", SensorType.COLOR, rgb), ("depth", SensorType.DEPTH, depth)):
        if not want:
            continue
        s = habitat_sim.CameraSensorSpec()
        s.uuid = uuid
        s.sensor_type = st
        s.sensor_subtype = SensorSubType.PINHOLE
        s.resolution = [IMG_H, IMG_W]
        s.hfov = HFOV_DEG
        s.position = [0.0, CAM_HEIGHT, 0.0]
        s.orientation = [0.0, 0.0, 0.0]
        s.near = 0.001      # default 0.01 clips a wall the camera nearly touches (S3D cameras sit < 1 cm from walls) -> no-hit pixels
        specs.append(s)
    if not specs:
        # Replica's PTex stage only loads when the renderer owns >= 1 visual sensor;
        # navmesh-/audio-only users get a throwaway 8x8 depth sensor.
        s = habitat_sim.CameraSensorSpec()
        s.uuid = "_dummy_depth"
        s.sensor_type = SensorType.DEPTH
        s.resolution = [8, 8]
        specs.append(s)
    agent_cfg = habitat_sim.agent.AgentConfiguration()
    agent_cfg.sensor_specifications = specs
    sim = habitat_sim.Simulator(habitat_sim.Configuration(backend, [agent_cfg]))

    if DATASET != "s3d":
        b = base_scene(scene)
        navmesh = (os.path.join(RAW_DIR, b, "habitat", "mesh_semantic.navmesh") if DATASET == "replica"
                   else os.path.join(RAW_DIR, f"{b}.navmesh") if DATASET == "gibson"
                   else os.path.join(RAW_DIR, b, f"{b}.navmesh"))
        if not sim.pathfinder.is_loaded:
            sim.pathfinder.load_nav_mesh(navmesh)

    if audio:
        a = habitat_sim.AudioSensorSpec()
        a.uuid = "audio"
        a.enableMaterials = False
        lt = habitat_sim.sensor.RLRAudioPropagationChannelLayoutType
        if audio.get("channel", "mono") == "mono":
            a.channelLayout.type = lt.Mono
            a.channelLayout.channelCount = 1
        else:
            a.channelLayout.type = lt.Binaural
            a.channelLayout.channelCount = 2
        a.position = [0.0, CAM_HEIGHT, 0.0]
        a.acousticsConfig.sampleRate = SR
        a.acousticsConfig.direct = True
        a.acousticsConfig.indirect = True
        a.acousticsConfig.indirectRayCount = INDIRECT_RAYS
        a.acousticsConfig.indirectRayDepth = RAY_DEPTH
        a.acousticsConfig.diffraction = DIFFRACTION
        a.acousticsConfig.maxDiffractionOrder = MAX_DIFFRACTION_ORDER
        a.acousticsConfig.transmission = TRANSMISSION
        a.acousticsConfig.threadCount = int(audio.get("threads", 4))
        sim.add_sensor(a)
    return sim


def set_agent(sim, hx, hy, hz, theta):
    agent = sim.get_agent(0)
    st = agent.get_state()
    st.position = np.array([hx, hy, hz], dtype=np.float32)
    st.rotation = habitat_quat(theta)
    st.sensor_states = {}
    agent.set_state(st, True)


def frame_png(idx):
    """rgb / depth-map file name of global frame index idx (spec 3.1)."""
    if L == 0:
        return f"{idx:05d}.png"                     # trajectory / single-view naming
    return f"{idx // (L + 1):05d}-{idx % (L + 1)}.png"


def read_poses(collection, scene):
    p = os.path.join(scene_dir(collection, scene), "poses.txt")
    return np.loadtxt(p, ndmin=2, dtype=np.float64)


def read_chunks(collection, scene):
    with open(os.path.join(scene_dir(collection, scene), "chunks.json")) as f:
        return json.load(f)
