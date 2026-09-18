#!/bin/bash
# Full re-validation after the Pinesdale_f2 repair, then mirror the remaining pieces to
# /file1 (it already holds rgb/depth/desdf from the 12:05 run; rir and the repaired scene
# are what is left). /file2 is already complete.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
echo "[final2] validate start $(date)"
$PY validate.py --ring-only 2>&1 | grep -v '^\[.*\]:\[' > logs/validate_gibson3.log
echo "[final2] $(grep '^RESULT:' logs/validate_gibson3.log) $(date)"
if ! grep -q "^RESULT: OK" logs/validate_gibson3.log; then
  echo "[final2] ABORT: still failing"; grep '  FAIL ' logs/validate_gibson3.log | head -20; exit 1
fi
TARGET=/file1/changwoo WORKERS=8 ./logs/sync_gibson_par.sh
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset
for T in /file1/changwoo /file2/changwoo; do
  for d in replica mp3d s3d; do
    rsync -a --include='*/' --include='semantic_map.png' --include='semantic_legend.json' \
      --exclude='*' $S/$d/maps/ $T/echoloc_dataset/$d/maps/
    echo "[final2] $T $d semantic: $(find $T/echoloc_dataset/$d/maps -name 'semantic_map.png' | wc -l) maps"
  done
  rsync -a $S/README.md $T/echoloc_dataset/
done
echo "[final2] ALL DONE $(date)"
