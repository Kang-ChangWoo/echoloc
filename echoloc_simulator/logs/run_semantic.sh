#!/bin/bash
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
for d in replica s3d mp3d; do
  echo "[sem] $d start $(date)"
  ECHOLOC_DATASET=$d $PY make_semantic_map.py --overwrite 2>&1 | grep -v Warning | grep "^\[" > logs/semantic_$d.log
  echo "[sem] $d done: $(grep -c '^\[' logs/semantic_$d.log) scenes, FAILED $(grep -c FAILED logs/semantic_$d.log)"
  # place a copy next to map.png inside each collection scene dir, as loaders expect
  ECHOLOC_DATASET=$d $PY - <<'PY'
import os, shutil, common as C
n=0
for s in C.SCENES:
    src=os.path.join(C.ROOT,"maps",s,"semantic_map.png")
    if not os.path.exists(src): continue
    for col in C.COLLECTIONS:
        d=os.path.join(C.ROOT,col,s)
        if os.path.isdir(d): shutil.copy2(src, os.path.join(d,"semantic_map.png")); n+=1
print(f"[sem] copied {n} semantic maps into collection scene dirs", flush=True)
PY
done
echo "[sem] ALL DONE $(date)"
