#!/bin/bash
# Full Structured3D import, detached. Waits for the extraction (session task) to finish first.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh && export ECHOLOC_DATASET=s3d
EXT=/tmp/claude-1000/-home-rvi-lab/060ce9f5-cdf0-48b3-8fc2-ca764951b5dd/tasks/bcpou7nxu.output
until grep -q "s3d-extract\] scenes:" "$EXT" 2>/dev/null; do sleep 60; done
echo "[run_s3d] extraction finished, start $(date)"
$PY build_s3d.py 2>&1 | grep -E "^\[" | grep -vc "cached" | sed 's/^/[build_s3d] scenes: /'
$PY build_s3d.py 2>&1 | grep "^\[split\]"
JOBS=12 ./run_all.sh depth 2>&1 | grep -c "^\[" | sed 's/^/[depth] files: /'
JOBS=4 ./run_all.sh depthmaps 2>&1 | grep "^\[depthmaps\]"
WORKERS=12 ./run_all.sh desdf 2>&1 | grep -c "^\[" | sed 's/^/[desdf] scenes: /'
./run_all.sh validate --figs 1 2>&1 | grep -E "RESULT|FAIL" | grep -v "scene dir missing" | sed 's/^/[validate-visual] /'
JOBS=6 THREADS=5 ./run_all.sh rir 2>&1 | grep "^\[rir\]"
LAYOUT=binaural JOBS=6 THREADS=5 ./run_all.sh rir 2>&1 | grep "^\[rir\]"
$PY write_dataset_meta.py 2>&1 | grep -v Warning | head -1
./run_all.sh validate --figs 0 2>&1 | grep -E "RESULT|FAIL" | sed 's/^/[validate-final] /'
echo "[run_s3d] ALL DONE $(date)"
