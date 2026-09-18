# Floor plan vs real mesh — do the IRs look alike?

Question: at one spot in one Replica scene, does an impulse response synthesised in
the **real, furnished mesh** resemble one synthesised in a **floor-plan box** — the
same walls, extruded floor to ceiling, furniture deleted?

Short answer: **no, and not just in the fine detail.** The waveforms barely
correlate (0.24 early, 0.29 late), and the floor plan is roughly **twice as
reverberant** as the real room (RT30 0.69 s vs 0.41 s). Removing the furniture does
not only smooth the early reflections — it removes most of the absorbing and
scattering surface, and the whole decay changes.

## Run it

```bash
./run.sh                       # build plans -> render IRs -> figures
# or step by step:
python build_floorplan.py --scenes room_1 office_3 frl_apartment_2
python render_irs.py     --scenes room_1 office_3 frl_apartment_2 --pairs 6
python analyze.py
```

habitat-sim 0.2.2 lives in the `ss_v2` env and segfaults on import unless conda's
libstdc++ is preloaded — `run.sh` handles that.

## What is compared

Three IRs at the **same receiver/source node pair**, so nothing but the geometry
(or the renderer) differs:

| trace | geometry | renderer |
|---|---|---|
| `real` | the Replica mesh, furniture and all | RLR (habitat-sim 0.2.2) |
| `floorplan` | walls only, extruded floor→ceiling | RLR, identical sensor config |
| `ss1.0` | the Replica mesh | the downloaded SoundSpaces 1.0 RIR |

`ss1.0` is the control: it is a *different renderer at the same spot*, so it shows
how big a difference "the same room, rendered differently" produces. Anything
larger than that gap is a real geometry effect.

Receiver and source both sit 1.5 m above the node, the SoundSpaces convention, so
these poses line up with the RIRs and the images in `dataset-replica/`.

## Extracting the plan (the part that needed care)

A floor plan is walls without furniture. Two traps:

1. **Slice at head height and the sofas come along.** Slice just below the ceiling
   and you avoid the furniture — but you pick up the *lintel above every door*.
   Extrude that and every doorway is sealed: the flat becomes a set of airtight
   boxes with no room-to-room coupling, which is acoustically nonsense.
   Fix: a wall is what is solid at *every* height. Occupancy is voted across ~12
   height bands; walls score ~1.0, furniture and lintels only ~0.3 each (one lives
   at the bottom of the range, the other at the top). Threshold at 0.6.
2. **The wall mask does not enclose anything.** Replica scans have gaps (windows,
   unscanned corners), so sound pours straight out of the model and the room comes
   out far too dry. Fix: take the navmesh, fill its holes, dilate — that is the
   building envelope — and seal its boundary with a ring of wall.

`floorplan_map.png` shows the result (rooms white, walls and outside black, graph
nodes red); `leak_diagnostic.png` shows what the sealing ring had to close.

**Watch the axes.** habitat-sim's glTF importer already rotates -90° about X
(`habitat = (tx, tz, -ty)`), so the mesh is exported z-up and *untouched*. Rotating
it first double-applies the transform, the room ends up on its side, the listener
lands outside the box, and every IR collapses to the direct path (DRR +40 dB, RT30
≈ 0). That bug produced the first, nonsense, version of these numbers.

## Results (18 pairs, 3 scenes, 0.5–12.8 m)

| | real | floor plan | ss1.0 |
|---|---|---|---|
| RT30, mean | 0.41 s | **0.69 s** | 0.44 s |
| waveform correlation (real vs plan), early <50 ms | | **0.24** | |
| waveform correlation (real vs plan), late | | **0.29** | |

- **The plan is much more reverberant.** In `frl_apartment_2` the floor plan sits at
  a flat RT30 ≈ 0.72–0.80 s regardless of distance (a diffuse field in a bare box),
  while the real flat is 0.14–0.31 s. The furniture was doing most of the absorbing.
- **The 1.0 control lands near the real mesh** (0.39–0.50 s), not near the plan. So
  the gap above is geometry, not a renderer artefact — that is the point of having
  the control.
- **Waveforms only agree when the direct path dominates.** At 0.5 m the early
  correlation is 0.67; by 6 m it is ~0.0. Past the direct sound and the first
  floor/ceiling bounce, the two rooms have nothing in common.
- **DRR splits the same way**: in the real flat the direct path is +17 dB over the
  reverb at 0.5 m; in the plan it is already −1 dB, because the bare box throws far
  more energy back.

The prediction going in was that the *late* tail would match (RT60 is set by volume
and absorption, and the plan preserves the volume) and only the early reflections
would diverge. That was wrong: the plan preserves the volume but not the absorbing
area, so the late field is where the two diverge most.

## Caveats

- `enableMaterials = False` for both geometries — Replica ships no acoustic material
  JSON, so every surface gets RLR's default. With real materials the furniture would
  absorb *more*, widening the gap.
- RLR truncates the IR once the energy falls off, so a few `real` pairs return short
  IRs and their RT30 fit (the −5…−35 dB slope) is unreliable — the 0.01–0.05 s
  outliers in `office_3` are that, not physics. The `frl_apartment_2` numbers, where
  the IRs are long, are the trustworthy ones.
- Three scenes, six pairs each. Enough to answer "are they alike" (they are not),
  not enough to calibrate a correction.

## Files

```
build_floorplan.py     mesh -> wall mask -> extruded glb (+ maps)
render_irs.py          IRs at identical poses in both geometries
analyze.py             metrics + figures
out/<scene>/
  floorplan.glb          the plan, as habitat loads it
  floorplan_map.png      rooms white / walls+outside black / nodes red
  leak_diagnostic.png    what the navmesh ring had to seal
  irs/                   raw IRs, (2, T) float32
  figs/waveforms.png     full IR + first 50 ms, three traces
  figs/decay_spectrum.png  Schroeder decay + octave bands
  figs/metrics.png       RT30 / DRR / correlation vs distance
out/summary.md         the table above, per pair
```
