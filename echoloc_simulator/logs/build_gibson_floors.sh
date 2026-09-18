#!/bin/bash
# Build Gibson storey masks in chunks so a crash or leak costs at most one chunk, and keep
# the full output (a previous wrapper grepped away tracebacks).
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator/floorplan_extraction && source ../env.sh
L=../logs; OUT=$PWD/gibson_floors
echo "[gib] start $(date)"
python3 - > $L/gibson_todo.txt <<'PY'
import os
have={d.rsplit('_f',1)[0] for d in os.listdir('gibson_floors')} if os.path.isdir('gibson_floors') else set()
done=set()
if os.path.exists('../logs/gibson_attempted.txt'): done={l.strip() for l in open('../logs/gibson_attempted.txt') if l.strip()}
allsc=sorted(f[:-4] for f in os.listdir('/mnt/sdb/gibson_raw/gibson') if f.endswith('.glb'))
print('\n'.join(s for s in allsc if s not in have and s not in done))
PY
N=$(wc -l < $L/gibson_todo.txt)
echo "[gib] todo $N scenes"
while read -r -d '' chunk || [ -n "$chunk" ]; do :; done < /dev/null
i=0
while [ $i -lt $N ]; do
  SC=$(tail -n +$((i+1)) $L/gibson_todo.txt | head -25 | tr '\n' ' ')
  [ -z "$SC" ] && break
  $PY build_floorplan_gibson.py --scenes $SC --out $OUT >> $L/gibson_floors.log 2>&1
  for s in $SC; do echo "$s" >> $L/gibson_attempted.txt; done
  i=$((i+25))
  echo "[gib] $i/$N attempted, storeys $(ls $OUT | wc -l) $(date +%H:%M)"
done
echo "[gib] storeys: $(ls $OUT | wc -l) from $(ls $OUT | sed 's/_f[0-9]*$//' | sort -u | wc -l) scenes"
echo "[gib] ALL DONE $(date)"
