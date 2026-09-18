#!/bin/bash
# HEAR360 sequence data (supple_trajectories, ~530 GB, 618k files) -> file2. Detached, resumable.
SRC=/mnt/sdb/soundspaces/supple_trajectories/; DST=/file2/changwoo/supple_trajectories/
mkdir -p "$DST"
echo "[sync_supple] start $(date)"
rsync -a --info=progress2 "$SRC" "$DST" 2>&1 | tr '\r' '\n' | grep --line-buffered -E "^\s*[0-9]" | awk 'NR%2000==0' 
echo "[sync_supple] rsync exit=${PIPESTATUS[0]} $(date)"
echo "[sync_supple] files src $(find $SRC -type f | wc -l) dst $(find $DST -type f | wc -l)"
du -sh "$DST" | sed 's/^/[sync_supple] size /'
echo "[sync_supple] ALL DONE $(date)"
