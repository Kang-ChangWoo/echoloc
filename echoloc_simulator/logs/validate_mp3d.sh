#!/bin/bash
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh && export ECHOLOC_DATASET=mp3d
echo "[val_mp3d] start $(date)"
$PY validate.py --figs 0 2>&1 | grep -v "^\[.*\]:\[" > logs/validate_mp3d.out
echo "[val_mp3d] exit=$? $(date)"
grep -E "RESULT" logs/validate_mp3d.out | sed 's/^/[val_mp3d] /'
grep "FAIL" logs/validate_mp3d.out | head -20 | sed 's/^/[val_mp3d] /'
echo "[val_mp3d] ALL DONE $(date)"
