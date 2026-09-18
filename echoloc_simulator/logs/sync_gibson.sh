#!/bin/bash
# Gibson dataset to both NAS, same per-dataset layout as replica/mp3d/s3d.
# Run one at a time: a second rsync with --delete would eat what this one is still writing.
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset/gibson
for T in /file1/changwoo /file2/changwoo; do
  mkdir -p $T/echoloc_dataset/gibson
  rsync -a --delete --info=progress2 $S/ $T/echoloc_dataset/gibson/ \
    && echo "[sync_gibson] -> $T done ($(du -sh $T/echoloc_dataset/gibson | cut -f1)) $(date)" \
    || echo "[sync_gibson] -> $T FAILED $(date)"
done
echo "[sync_gibson] ALL DONE $(date)"
