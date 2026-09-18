#!/bin/bash
# Resume the Gibson pipeline after the depth stage: desdf -> rir(ring) -> rir(binaural)
# -> dataset_meta -> validate. Waits for the depth retry loop to finish first.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
echo "[chain2] waiting for fix_gibson_depth.sh $(date)"
while kill -0 "${DEPTH_PID:-0}" 2>/dev/null; do sleep 60; done
F=$(ls $ECHOLOC_DATA/gibson/gibson_f/*/depth160.txt 2>/dev/null | wc -l)
G=$(ls $ECHOLOC_DATA/gibson/gibson_g/*/depth160.txt 2>/dev/null | wc -l)
echo "[chain2] depth: gibson_f $F/945  gibson_g $G/945  $(date)"
if [ "$F" -lt 945 ] || [ "$G" -lt 945 ]; then echo "[chain2] ABORT: depth incomplete"; exit 1; fi

echo "[stage] desdf start $(date)"
WORKERS=12 ./run_all.sh desdf || { echo "[stage] desdf FAILED $(date)"; exit 1; }
echo "[stage] desdf done $(date)"
echo "[stage] rir ring start $(date)"
JOBS=6 THREADS=5 ./run_all.sh rir || { echo "[stage] rir ring FAILED $(date)"; exit 1; }
echo "[stage] rir ring done $(date)"
echo "[stage] rir binaural start $(date)"
LAYOUT=binaural JOBS=6 THREADS=5 ./run_all.sh rir || { echo "[stage] rir binaural FAILED $(date)"; exit 1; }
echo "[stage] rir binaural done $(date)"
$PY write_dataset_meta.py && echo "[stage] meta done $(date)"
echo "[stage] validate start $(date)"
./run_all.sh validate || { echo "[stage] validate FAILED $(date)"; exit 1; }
echo "[stage] validate done $(date)"
echo "[chain2] ALL DONE $(date)"
