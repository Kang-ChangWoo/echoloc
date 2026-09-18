#!/bin/bash
# Gibson stages 3-5: rgb -> radial depth maps -> depth40/160 -> desdf (test scenes only).
# Every stage is resume-safe; re-running skips what exists.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
for st in "rgb JOBS=4" "depthmaps JOBS=4" "depth WORKERS=12" "desdf WORKERS=12"; do
  set -- $st; s=$1; shift
  echo "[stage] $s start $(date)"
  env "$@" ./run_all.sh $s || { echo "[stage] $s FAILED $(date)"; exit 1; }
  echo "[stage] $s done $(date)"
done
echo "[stage] ALL DONE $(date)"
