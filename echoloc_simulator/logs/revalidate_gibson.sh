#!/bin/bash
# Re-validate Gibson after the Pinesdale_f2 repair, with --ring-only (this release ships
# ring RIRs only). On a clean result, mirror the whole dataset -- rir included -- to both
# NAS and re-confirm the semantic maps of the other three datasets.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset

echo "[reval] waiting for the Pinesdale_f2 repair $(date)"
until grep -q "\[fix\] ALL DONE" logs/fix_pinesdale.log 2>/dev/null; do sleep 60; done
echo "[reval] repair done $(date)"

echo "[reval] waiting for the visual rsync $(date)"
until grep -q "\[visual\] ALL DONE" logs/sync_gibson_visual.log 2>/dev/null; do sleep 120; done

echo "[reval] validate start $(date)"
$PY validate.py --ring-only 2>&1 | grep -v '^\[.*\]:\[' > logs/validate_gibson2.log
RES=$(grep "^RESULT:" logs/validate_gibson2.log)
echo "[reval] $RES $(date)"
if ! grep -q "^RESULT: OK" logs/validate_gibson2.log; then
  echo "[reval] ABORT: validation still failing"
  grep "  FAIL " logs/validate_gibson2.log | head -20
  exit 1
fi

for T in /file1/changwoo /file2/changwoo; do
  D=$T/echoloc_dataset/gibson
  mkdir -p $D
  rsync -a --delete $S/gibson/ $D/ \
    && echo "[reval] $T gibson done  $(du -sh $D | cut -f1)  files $(find $D -type f | wc -l)  $(date)" \
    || { echo "[reval] $T gibson FAILED $(date)"; continue; }
  for d in replica mp3d s3d; do
    rsync -a --include='*/' --include='semantic_map.png' --include='semantic_legend.json' \
      --exclude='*' $S/$d/maps/ $T/echoloc_dataset/$d/maps/
    echo "[reval] $T $d semantic: $(find $T/echoloc_dataset/$d/maps -name 'semantic_map.png' | wc -l) maps"
  done
  rsync -a $S/README.md $T/echoloc_dataset/
done
echo "[reval] ALL DONE $(date)"
