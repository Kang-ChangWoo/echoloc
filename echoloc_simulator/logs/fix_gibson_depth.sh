#!/bin/bash
# The depth stage segfaulted partway through gibson_g. make_depth_gt.py is resume-safe,
# so re-run it in a retry loop with fewer workers and record which scene it dies on.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
for try in 1 2 3 4 5 6 7 8; do
  n=$(ls $ECHOLOC_DATA/gibson/gibson_g/*/depth160.txt 2>/dev/null | wc -l)
  echo "[fixdepth] try $try start with $n/945 done $(date)"
  $PY make_depth_gt.py --collection gibson_g --workers 6 >> ../echoloc_simulator/logs/depth_gibson_g.log 2>&1
  rc=$?
  m=$(ls $ECHOLOC_DATA/gibson/gibson_g/*/depth160.txt 2>/dev/null | wc -l)
  echo "[fixdepth] try $try exit $rc, now $m/945 $(date)"
  [ "$m" -ge 945 ] && break
  [ "$m" -le "$n" ] && { echo "[fixdepth] no progress, stopping"; break; }
done
echo "[fixdepth] DONE $(ls $ECHOLOC_DATA/gibson/gibson_g/*/depth160.txt 2>/dev/null | wc -l)/945 $(date)"
