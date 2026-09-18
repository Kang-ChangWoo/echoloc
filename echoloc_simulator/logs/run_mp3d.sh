#!/bin/bash
# Full MP3D generation, detached from the session (memory watchdog). Resume-safe stages.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh && export ECHOLOC_DATASET=mp3d
echo "[run_mp3d] start $(date)"
./run_all.sh maps 2>&1 | grep -c "^\[" | sed 's/^/[maps] scenes: /'
./run_all.sh poses 0 2>&1 | grep "^\[" | grep -vc cached | sed 's/^/[poses] new: /'
JOBS=4 ./run_all.sh rgb 2>&1 | grep "^\[rgb\]"
JOBS=4 ./run_all.sh depthmaps 2>&1 | grep "^\[depthmaps\]"
WORKERS=12 ./run_all.sh depth 2>&1 | grep -c "^\[" | sed 's/^/[depth] files: /'
WORKERS=12 ./run_all.sh desdf 2>&1 | grep -c "^\[" | sed 's/^/[desdf] scenes: /'
./run_all.sh validate --figs 1 2>&1 | grep -E "RESULT|FAIL" | sed 's/^/[validate-visual] /'
JOBS=6 THREADS=5 ./run_all.sh rir 2>&1 | grep "^\[rir\]"
LAYOUT=binaural JOBS=6 THREADS=5 ./run_all.sh rir 2>&1 | grep "^\[rir\]"
$PY write_dataset_meta.py 2>&1 | grep -v Warning | head -1
./run_all.sh validate --figs 0 2>&1 | grep -E "RESULT|FAIL" | sed 's/^/[validate-final] /'
echo "[run_mp3d] ALL DONE $(date)"
