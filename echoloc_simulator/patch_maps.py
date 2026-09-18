#!/usr/bin/env python3
"""Apply common.close_diagonal_leaks to already-built maps (maps/ + both collection
copies) without re-running the simulator. Idempotent. Prints pixels added per scene.
Depth GT / desdf built from the old maps must be regenerated afterwards."""
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image

import common as C


def main(scenes):
    for s in scenes:
        mdir = os.path.join(C.ROOT, "maps", s)
        p = os.path.join(mdir, "map.png")
        if not os.path.exists(p):
            print(f"[{s}] no map yet")
            continue
        occ = np.array(Image.open(p))[:, :, 0]
        fixed, n = C.close_diagonal_leaks(occ)
        if n:
            Image.fromarray(np.repeat(fixed[:, :, None], 3, axis=2)).save(p)
        mp = os.path.join(mdir, "scene_meta.json")
        meta = json.load(open(mp))
        meta["diagonal_corner_px_filled"] = meta.get("diagonal_corner_px_filled", 0) + n
        json.dump(meta, open(mp, "w"), indent=2)
        for col in C.COLLECTIONS:
            sd = C.scene_dir(col, s)
            os.makedirs(sd, exist_ok=True)
            shutil.copy2(p, sd)
        print(f"[{s}] corner pixels filled: {n}  (wall px {(fixed != 255).sum()})")


if __name__ == "__main__":
    main(sys.argv[1:] or C.SCENES)
