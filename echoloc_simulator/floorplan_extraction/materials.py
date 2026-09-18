"""Acoustic materials for the two geometries.

The Replica pipeline has always run with `enableMaterials = False` on the grounds
that "Replica ships no material JSON". It does not need one: RLR assigns materials
by matching a material's `labels` against the semantic category of each surface, and
Replica's category vocabulary (`wall`, `floor`, `ceiling`, `window`, `blinds`,
`rug`, ...) is the same vocabulary mp3d_material_config.json already keys on. So the
real mesh can just use the mp3d config as-is.

The floor plan cannot: it is a plain glb with no semantics, so every surface falls
through to `Default`. Leaving RLR's Default there (absorption 0.10, uniform) would
compare a furnished room with real materials against a box with invented ones.
Instead we rewrite `Default` as the AREA-WEIGHTED MIX of the three surfaces the
plan actually has — wall (Gypsum Board), floor (Carpet), ceiling (Acoustic Tile) —
so the plan gets the fairest single material it is capable of carrying.
"""
import json
import os

import numpy as np

MP3D_CONFIG = "/home/rvi-lab/workspace/sound-spaces/data/mp3d_material_config.json"

# Which mp3d material stands in for each surface of the plan.
SURFACE_MATERIAL = {"wall": "Gypsum Board", "floor": "Carpet", "ceiling": "Acoustic Tile"}

# The frequency grid the mixed curves are resampled onto (Hz).
FREQS = np.array([20.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 20000.0])


def _curve(pairs, freqs):
    """A [f0, v0, f1, v1, ...] list -> values interpolated onto `freqs`."""
    a = np.asarray(pairs, dtype=float).reshape(-1, 2)
    return np.interp(freqs, a[:, 0], a[:, 1])


def _flatten(freqs, values):
    out = []
    for f, v in zip(freqs, values):
        out += [float(f), float(v)]
    return out


def load_mp3d():
    with open(MP3D_CONFIG) as f:
        return json.load(f)


def mixed_default_config(areas, out_path):
    """Write a material config whose Default is the area-weighted mix of the plan's
    wall / floor / ceiling materials.

    `areas` is {"wall": m2, "floor": m2, "ceiling": m2}.
    """
    cfg = load_mp3d()
    by_name = {m["name"]: m for m in cfg["materials"]}

    total = sum(areas.values())
    weights = {k: v / total for k, v in areas.items()}

    mixed = {}
    for prop in ("absorption", "scattering", "transmission"):
        acc = np.zeros_like(FREQS)
        for surface, w in weights.items():
            mat = by_name[SURFACE_MATERIAL[surface]]
            acc += w * _curve(mat[prop], FREQS)
        mixed[prop] = _flatten(FREQS, acc)

    default = by_name["Default"]
    default.update(mixed)
    default["labels"] = ["default"]

    with open(out_path, "w") as f:
        json.dump(cfg, f)

    return {
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "absorption_1k": round(float(np.interp(1000.0, FREQS, _curve(mixed["absorption"], FREQS))), 3),
    }
