#!/bin/bash
# Generation + validation code to both NAS (excludes the 17 GB of validation by-products,
# the raw logs and the caches). Small enough to re-run after any change.
S=/mnt/sdb/soundspaces/echoloc/echoloc_simulator
for T in /file1/changwoo /file2/changwoo; do
  mkdir -p $T/echoloc_simulator
  rsync -a --delete \
    --exclude 'validation/' --exclude '__pycache__/' --exclude 'logs/poses_prev/' \
    --exclude 'logs/*.out' --exclude 'third_party/f3loc/.git/' \
    $S/ $T/echoloc_simulator/ && echo "[sync_code] -> $T done ($(du -sh $T/echoloc_simulator | cut -f1)) $(date)"
done
echo "[sync_code] ALL DONE $(date)"
