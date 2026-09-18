# Dataset Generation Spec — F3Loc-compatible floorplan localization data

Requirements for producing a new dataset that the F3Loc training and evaluation
code in this repository consumes without modification, plus the acoustic
extension AV-FPLoc needs on top of it.

Every convention below was read out of the pinned upstream source
(`third_party/f3loc`, revision in `third_party/f3loc/PINNED_REVISION`) and
verified against the released Gibson Floorplan Localization Dataset. Where the
spec says "must", the code will silently produce wrong numbers otherwise.

Target simulator: Habitat-sim + SoundSpaces over Matterport3D (MP3D). Nothing
below is Gibson-specific except where stated.

---

## 1. Directory layout

```text
<dataset_root>/
├── <collection>/                     e.g. mp3d_f, mp3d_g
│   ├── split.yaml
│   ├── <scene_id>/
│   │   ├── rgb/
│   │   │   ├── 00000-0.png  00000-1.png  00000-2.png  00000-3.png
│   │   │   ├── 00001-0.png  ...
│   │   ├── poses.txt
│   │   ├── depth40.txt
│   │   ├── depth160.txt
│   │   └── map.png
│   └── ...
└── desdf/
    └── <scene_id>/desdf.npy           test scenes only
```

One collection = one motion regime. The released data ships two four-view
collections (`gibson_f` forward-only motion, `gibson_g` general motion including
in-place rotation) plus a long-trajectory collection. Reproduce at least the two
four-view collections; the complementary network exists specifically to arbitrate
between well-conditioned and degenerate baselines, so a dataset with only one
motion regime cannot exercise it.

---

## 2. Coordinate conventions

This section is the part that goes wrong. Everything else is bookkeeping.

### 2.1 World frame

* SE(2) pose is `(x, y, yaw)`: metres, metres, radians in `[-π, π]`.
* Yaw is measured **counter-clockwise from the +x axis**.
* The world origin is the **centre of `map.png`**.

### 2.2 World → map pixel

```
x_map = x_world / 0.01 + W / 2
y_map = y_world / 0.01 + H / 2
```

`0.01 m/pixel` is fixed for `map.png`. `W`, `H` are the map width and height in
pixels. Ray casting indexes the map as `occ[row, col] = occ[y_map, x_map]`, and
the yaw convention is the one you get by displaying the map with
`origin="lower"` — that is, `y_map` increases in the same direction the sine of
the yaw does.

### 2.3 Habitat → F3Loc

Habitat is y-up; the floorplan frame is z-up. The mapping already used by this
project's RIR renderer is:

```
x_f3loc =  x_habitat
y_f3loc = -z_habitat
yaw_f3loc: measured CCW in the (x_f3loc, y_f3loc) plane
height  =  y_habitat   (not part of the SE(2) pose)
```

Verify this on your own scenes before generating in bulk: render one image,
ray-cast the GT depth from your floorplan at the same pose, and confirm the two
agree. A sign error here produces data that trains to a low loss and localizes at
chance.

---

## 3. File specifications

### 3.1 `rgb/`

| Property | Requirement |
| --- | --- |
| Format | PNG, 8-bit RGB, 3 channels |
| Resolution | `480 × 640` (H × W) for the released camera |
| Naming, four-view | `{chunk:05d}-{view}.png`, `view ∈ 0..L`, with `L = 3` |
| Naming, trajectory | `{step:05d}.png` |
| Ordering | Ascending filename order **is** the row order of `poses.txt` and the depth files |

For a four-view collection the last view (`view == L == 3`) is the **reference
frame**; views `0..L-1` are the source frames the multi-view cost volume warps
onto it. Every scene must contain a whole number of chunks: `len(poses) % (L+1) == 0`.

Camera intrinsics are constant across the entire dataset:

```
K = [[240,   0, 320],
     [  0, 240, 240],
     [  0,   0,   1]]
```

which is a horizontal FOV of `2·atan(320/240) ≈ 106.3°` and gives the code
constant `F_W = f/W = 240/640 = 3/8`. **If you change the camera, `F_W` changes
and must be updated in every config and in the GT ray generation** — it is not
inferred from the images. A different resolution with the same FOV is fine; a
different FOV is a different dataset.

Images must be gravity-aligned (zero roll and pitch) unless you deliberately want
the non-upright case. If roll/pitch is non-zero you must also ship it per frame,
because the network needs it to build the gravity-alignment mask.

### 3.2 `poses.txt`

One line per frame, ascending in rgb filename order, space-separated:

```
<x_world_m> <y_world_m> <yaw_rad>
```

Full float precision. Example from the released data:

```
-14.971680773613322 -2.660856517507788 2.9005750617203567
```

### 3.3 `map.png`

| Property | Requirement |
| --- | --- |
| Format | PNG, 8-bit, 3 identical channels (the code reads `[:, :, 0]`) |
| Resolution | `0.01 m/pixel`, fixed |
| Free space | **exactly 255** |
| Obstacle | **anything other than 255** |
| Content | Wall-only floorplan occupancy for one floor |

The polarity requirement is strict. `ray_cast` computes `255 - occ` and stops at
the first pixel `> 0`, so an anti-aliased wall edge at value 254 is an obstacle
and a JPEG-compressed "white" region at 254 is a wall everywhere. **Rasterize the
floorplan with nearest-neighbour/binary output and never save it through a lossy
codec.**

Wall-only means structural surfaces: walls, and the door/window openings that
break them. Furniture must not be rasterized — the ground-truth depth is the
distance to the *floorplan*, and the network is trained to see through clutter to
structure. This is the single most important semantic decision in the whole
dataset.

One map per scene, one floor per scene. A multi-floor MP3D scene must be split
into separate scene ids.

### 3.4 `depth40.txt` and `depth160.txt`

One line per frame, ascending in rgb filename order, space-separated floats,
`40` and `160` values respectively.

**These are camera-forward depths (z-depth), not radial ranges.** The generation
code casts a radial ray and multiplies by `cos` of the ray angle; the evaluation
code divides by the same `cos` to recover radial range. Getting this backwards is
a silent ~10% error at the edges of the field of view.

Generation, for `ray_n ∈ {40, 160}`:

```python
# angles across the image, left to right
F_W = 3/8                                    # focal / width, must match the camera
u   = np.arange(ray_n)
center_angs = np.flip(np.arctan2(u - u.mean(), ray_n * F_W))

for (x, y, yaw) in poses:                    # world metres / radians
    pos = np.array([y / 0.01 + H/2, x / 0.01 + W/2])   # map pixels, [row, col]
    row = []
    for i, ang in enumerate(center_angs + yaw):
        d_pixels = ray_cast(occ, pos, ang, dist_max=20 / 0.01)
        row.append(d_pixels * 0.01 * np.cos(center_angs[i]))   # -> forward depth, metres
```

`ray_cast` is `third_party/f3loc/utils/utils.py`; use it directly rather than
reimplementing, so the discretization matches. `depth40` supervises the monocular
network, `depth160` the multi-view and complementary networks. Both are required
if you want to train all three stages.

Values must be finite and positive. Rays that escape the map return `dist_max`;
keep them, the training loss handles the saturation, but do not emit `inf`/`nan`.

### 3.5 `split.yaml`

```yaml
train: ["scene_a", "scene_b", ...]
val:   [...]
test:  [...]
```

Scene-level split, **disjoint** — verify it. The released data uses 100/9/9
scenes and, importantly, `val` and `test` share no scene, so selecting a
checkpoint on `val` does not leak into `test`. All collections in the dataset
should use the same split so a single checkpoint is evaluable on all of them.

### 3.6 `desdf/<scene>/desdf.npy`

Required for **test scenes only**; it is the matching target at evaluation time
and is not used in training.

A pickled dict saved with `np.save`:

```python
desdf = {
    "l":     int,          # left offset into map.png, in map pixels
    "t":     int,          # top offset into map.png, in map pixels
    "desdf": np.ndarray,   # (H, W, 36) float32, metres
}
```

* `36` equiangular yaw bins, counter-clockwise, bin `o` at `o · 2π/36` (10°/bin).
* Output resolution `0.1 m/cell`, i.e. a 10× downsample of `map.png`.
* Transform back to map pixels: `x_map = x_desdf * 10 + l`, `y_map = y_desdf * 10 + t`.
* Crop `l`/`t` to the occupied bounding box so the array stays small; the
  released Springhill cache is `(90, 112, 36)` with `l=90, t=1600` over a
  `3800×3800` map.
* Cast to at least `10 m` — evaluation truncates everything above `10 m`.
* Store `float32`. This project's decision log fixes `float32` for geometry
  caches; the shipped Structured3D caches are `float64` and are twice the size
  for no accuracy at `0.1 m/cell`.

Generate with `raycast_desdf` from `third_party/f3loc/utils/generate_desdf.py`.
It is a brute-force `O(cells × 36)` ray cast and takes a long time — that is why
only test scenes need it.

---

## 4. Acoustic extension (AV-FPLoc)

The visual spec above is enough to reproduce F3Loc. AV-FPLoc additionally needs an
active acoustic observation at the same poses. Nothing upstream defines this;
these are this project's requirements.

### 4.1 What to render

One room impulse response per **evaluated pose**, co-located with the camera,
with a compact microphone array and a co-located source (active sensing: the
agent emits and listens).

```text
<dataset_root>/rir/<scene_id>/pose_<index:05d>/
├── rir.npy               (n_mic, n_samples) float32
└── rir_metadata.json
```

`pose_<index>` indexes `poses.txt` of the corresponding collection, so the
acoustic and visual observations are joined by row index. Do not invent a
separate pose file.

### 4.2 Array and signal parameters

These match `configs/gibson_soundspaces.yaml`, already used by this project's
Gibson renderer. Keep them unless you have a reason to change, and record any
change in the metadata.

| Parameter | Value |
| --- | --- |
| Sample rate | `8000 Hz` |
| Microphones | `6`, uniform ring |
| Ring radius | `0.05 m` |
| Ring angles | `π/3 · k`, rotated by the pose yaw |
| Source height | `1.25 m` |
| Source | co-located with the array centre |
| Direct-sound guard | `16` samples after the direct peak |
| Usable length | `1024` samples after the guard |

The ring offsets in Habitat coordinates, for yaw `θ` and radius `r`:

```python
angles = np.array([π, 4π/3, 5π/3, 2π, π/3, 2π/3]) + θ
offsets = np.stack([r*np.cos(angles), np.zeros_like(angles), -r*np.sin(angles)], axis=1)
```

The `-sin` on the third component is the `y_f3loc = -z_habitat` mapping from §2.3.

### 4.3 Metadata

`rir_metadata.json` must carry enough to reproduce and to audit:

```json
{
  "pose_index": 141,
  "f3loc_pose_m_rad": [x, y, yaw],
  "array_center_habitat": [x, y, z],
  "channel_offsets_habitat_m": [[...], ...],
  "sample_rate_hz": 8000,
  "direct_peak_index": 1,
  "direct_sound_guard_samples": 16,
  "condition": "raw_scan_open",
  "simulator": {"name": "soundspaces", "version": "...", "scene": "..."},
  "acoustics": {"indirect_rays": 4096, "ray_depth": 6,
                "diffraction": false, "transmission": false,
                "materials_enabled": false}
}
```

`condition` names the geometry the RIR was rendered against. This project uses at
least two, and they answer different questions:

* `raw_scan_open` — the real scene mesh, with the holes and open boundaries a
  scan actually has.
* `floorplan_closed` — a watertight proxy extruded from the same `map.png` used
  for the visual ground truth.

The second exists because an acoustic likelihood matched against a floorplan is
only meaningful if the acoustics and the floorplan describe the same room. Render
both if you can; the pair is what tells you whether an acoustic-visual gain is
real geometry or a mesh artifact.

### 4.4 Ordering caveat

Whatever channel ordering and yaw-zero convention you choose, **write it down in
the metadata and keep it fixed**. A rotated ring is indistinguishable from a
rotated room to any downstream model, and this is the failure mode that is
hardest to detect after the fact.

---

## 5. MP3D-specific notes

Points where MP3D differs from the released Gibson data and a decision is needed.

1. **Floorplan extraction.** Gibson ships `floor_trav_*.png` occupancy maps.
   MP3D does not give you a wall-only floorplan directly. Options: slice the mesh
   at a fixed height above the floor and rasterize the intersection, or use the
   MP3D region/category annotations to keep only structural surfaces. Whichever
   you pick, the result must satisfy §3.3 — wall-only, binary, `0.01 m/pixel`,
   and *consistent with what the camera sees*.

2. **Multi-floor scenes.** MP3D scenes are frequently multi-storey. One
   `map.png` describes one floor. Split by floor and treat each as its own scene
   id, with poses filtered to that floor's height band.

3. **Pose sampling.** Sample from the Habitat navmesh so poses are reachable and
   not inside geometry. For a four-view chunk, generate one trajectory segment of
   `L+1 = 4` frames:
   * forward-motion collection: monotonic translation, small yaw change;
   * general-motion collection: include in-place rotation chunks (near-zero
     translation variance). These are the degenerate cases for the multi-view
     network and the reason the complementary selector exists — the released
     `gibson_g` deliberately contains them.

4. **Scale.** The released collections are 119 scenes with roughly 20k and 42k
   four-frame chunks. As a floor for training the monocular and multi-view
   networks, target **≥ 15k chunks over ≥ 60 scenes**, with at least 9 scenes each
   held out for `val` and `test`. Fewer scenes hurts more than fewer chunks;
   generalization here is across floorplans.

5. **Storage.** At 480×640 PNG the released data is ~320 KB per image, so a
   collection of 20k chunks is roughly 25–30 GB. Plan for the disk, and plan for
   where it lives — this project has already been bitten by training against a
   shared NFS export that could not sustain the read rate.

---

## 6. Validation checklist

Run all of these before handing the dataset over. Each corresponds to a failure
that is expensive to find later.

| # | Check | Why |
| --- | --- | --- |
| 1 | `len(rgb) == len(poses) == len(depth40) == len(depth160)` per scene | Row alignment is positional and unchecked at runtime |
| 2 | `len(poses) % (L+1) == 0` for four-view collections | Trailing frames are silently dropped |
| 3 | Filename sort order equals pose row order | The whole GT correspondence rests on this |
| 4 | `train ∩ val == train ∩ test == val ∩ test == ∅` | Checkpoint selection would leak |
| 5 | `map.png` values: free space is exactly 255 | 254 is an obstacle |
| 6 | Depth values finite, positive, `≤ dist_max` | `nan` propagates into the loss |
| 7 | DESDF exists for every `test` scene, shape `(H, W, 36)`, `float32` | Evaluation crashes or silently mismatches |
| 8 | Re-project a sampled pose: overlay the cast rays on `map.png` and the RGB frame | Catches every sign and axis error at once |
| 9 | A held-out pose's `depth160` matches an independent ray cast to `< 1 cm` | Catches the forward-depth vs radial-range mistake |
| 10 | Acoustic `pose_<index>` resolves to the same row as the visual frame | Silent modality misalignment |

Check 8 is worth doing manually on ten poses across three scenes before
generating anything in bulk.

Once the dataset exists, point `data.root` in `configs/visual_*.yaml` at it and
run the repository's own contract tests:

```bash
AVFPLOC_F3LOC_DATA=<dataset_root> python -m pytest tests/test_visual_training.py -q
```

Those assert the batch keys, the frame-to-depth-row alignment, and that a
checkpoint trained on the data still loads into the upstream Lightning wrappers.

---

## 7. Minimum viable subset

If the full generation is too expensive up front, this is the order that unblocks
the most work per unit of effort:

1. `rgb/`, `poses.txt`, `depth40.txt`, `map.png`, `split.yaml` for one collection
   → trains the monocular network end to end.
2. `depth160.txt` → adds the multi-view and complementary networks.
3. `desdf/` for the 9 test scenes → enables the localization metrics. Without
   this you can measure depth loss but not recall.
4. A second collection with general motion → makes the complementary stage
   meaningful.
5. `rir/` → the acoustic branch.

Steps 1–3 are the point at which numbers become comparable to the published
F3Loc results.
