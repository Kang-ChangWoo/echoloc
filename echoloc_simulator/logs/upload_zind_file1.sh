#!/bin/bash
# Parallel /file1 uploader started 03:32 while finish_zind_after_validate.sh is still on /file2.
# Upload is NFS-latency bound (~1k files/min at 2-4 MB/s), not bandwidth bound, so a second
# stream to the other NAS roughly doubles throughput. No --delete; the main script's later
# /file1 pass just skips files already present.
D=/mnt/sdb/soundspaces/echoloc/echoloc_dataset/zind
T=/file1/changwoo; DD=$T/echoloc_dataset/zind
mkdir -p $DD
rsync -a --include='*.json' --include='*.md' --exclude='*/' $D/ $DD/ 2>/dev/null
for sub in maps floorplan_proxy desdf zind; do
  mkdir -p $DD/$sub
  ls $D/$sub | xargs -P 6 -I{} rsync -a $D/$sub/{}/ $DD/$sub/{}/ 2>/dev/null
  echo "[f1] $sub done $(date +%H:%M)"
done
ls $D/rir/zind | while read c; do
  mkdir -p $DD/rir/zind/$c
  ls $D/rir/zind/$c | xargs -P 6 -I{} rsync -a $D/rir/zind/$c/{}/ $DD/rir/zind/$c/{}/ 2>/dev/null
done
echo "[f1] done  $(find $DD -type f | wc -l) files  $(date)"
