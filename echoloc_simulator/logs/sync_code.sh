#!/bin/bash
# Generation + validation code to both NAS (excludes the 67 GB of validation by-products,
# the raw logs, the wall-mask outputs and the caches). Small enough to re-run after any change.
# Paths moved 2026-09-19: /mnt/sdb/soundspaces/echoloc/{echoloc_simulator,echoloc_dataset}.
S=/mnt/sdb/soundspaces/echoloc/echoloc_simulator
for T in /file1/changwoo /file2/changwoo; do
  mkdir -p $T/echoloc_simulator
  rsync -a --delete \
    --exclude 'validation/' --exclude '__pycache__/' --exclude 'logs/poses_prev/' \
    --exclude 'logs/*.out' --exclude 'third_party/f3loc/.git/' --exclude '.git/' \
    $S/ $T/echoloc_simulator/ && echo "[sync_code] -> $T done ($(du -sh $T/echoloc_simulator | cut -f1)) $(date)"
  rsync -a /mnt/sdb/soundspaces/echoloc/ECHOLOC_DATA_GENERATION.md $T/echoloc_dataset/ \
    && rsync -a /mnt/sdb/soundspaces/echoloc/echoloc_dataset/README.md /mnt/sdb/soundspaces/echoloc/echoloc_dataset/gibson/README.md $T/echoloc_dataset/gibson/../ 2>/dev/null
  rsync -a /mnt/sdb/soundspaces/echoloc/echoloc_dataset/gibson/README.md $T/echoloc_dataset/gibson/
done
echo "[sync_code] ALL DONE $(date)"
