#!/bin/bash
# Wait for the running pose sampler, then run rgb -> depthmaps -> depth -> desdf -> rir -> validate.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
# Wait on the pose *runner*, not on sample_poses.py: the runner starts one sampler per
# collection, and between the two there is a gap where no sampler process exists.
echo "[chain] waiting for run_gibson_poses.sh $(date)"
while kill -0 "${POSES_PID:-0}" 2>/dev/null; do sleep 60; done
F=$(ls $ECHOLOC_DATA/gibson/gibson_f/*/poses.txt 2>/dev/null | wc -l)
G=$(ls $ECHOLOC_DATA/gibson/gibson_g/*/poses.txt 2>/dev/null | wc -l)
echo "[chain] poses done: gibson_f $F  gibson_g $G  $(date)"
if [ "$F" -lt 900 ] || [ "$G" -lt 900 ]; then echo "[chain] ABORT: pose stage incomplete"; exit 1; fi

run () {  # stage, then env assignments
  local s=$1; shift
  echo "[stage] $s start $(date)"
  env "$@" ./run_all.sh $s || { echo "[stage] $s FAILED $(date)"; exit 1; }
  echo "[stage] $s done $(date)"
}
run rgb       JOBS=4
run depthmaps JOBS=4
run depth     WORKERS=12
run desdf     WORKERS=12
echo "[stage] rir ring start $(date)"
JOBS=6 THREADS=5 ./run_all.sh rir || { echo "[stage] rir ring FAILED"; exit 1; }
echo "[stage] rir ring done $(date)"
echo "[stage] rir binaural start $(date)"
LAYOUT=binaural JOBS=6 THREADS=5 ./run_all.sh rir || { echo "[stage] rir binaural FAILED"; exit 1; }
echo "[stage] rir binaural done $(date)"
$PY write_dataset_meta.py && echo "[stage] meta done $(date)"
run validate
echo "[chain] ALL DONE $(date)"
