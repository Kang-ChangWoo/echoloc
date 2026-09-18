#!/bin/bash
# Finish Gibson after the ring RIR stage: dataset_meta -> validate.
# Binaural RIR is deliberately NOT rendered (user decision, 2026-09-16); it can be added
# later with LAYOUT=binaural ./run_all.sh rir -- render_rir.py skips what already exists.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
echo "[chain3] waiting for the ring RIR stage $(date)"
while kill -0 "${RIR_PID:-0}" 2>/dev/null; do sleep 120; done
echo "[chain3] ring RIR finished: $(find $ECHOLOC_DATA/gibson/rir -name 'rir.npy' | wc -l) impulse responses $(date)"
$PY write_dataset_meta.py && echo "[stage] meta done $(date)"
echo "[stage] validate start $(date)"
./run_all.sh validate || { echo "[stage] validate FAILED $(date)"; exit 1; }
echo "[stage] validate done $(date)"
echo "[chain3] ALL DONE $(date)"
