#!/bin/bash
# Sync the MP3D and Structured3D collections to both NAS once their chains (and the MP3D fix) are done.
R=/mnt/sdb/soundspaces/echoloc/echoloc_dataset; L=/mnt/sdb/soundspaces/echoloc/echoloc_simulator/logs
sync_parts() {   # $1 = label, rest = relative paths under $R
  local label=$1; shift
  for T in /file1/changwoo/echoloc_dataset /file2/changwoo/echoloc_dataset; do
    for p in "$@"; do
      [ -e "$R/$p" ] || continue
      if [ -d "$R/$p" ]; then mkdir -p "$T/$p" && rsync -a "$R/$p/" "$T/$p/"; else rsync -a "$R/$p" "$T/$p"; fi
    done
    echo "[sync_new] $label -> $T done $(date)"
  done
}
until grep -q "ALL DONE" $L/run_s3d.log 2>/dev/null && [ -f $L/s3d_fixed.done ]; do sleep 120; done
echo "[sync_new] s3d chain finished; syncing $(date)"
sync_parts s3d s3d rir/s3d maps floorplan_proxy desdf dataset_meta_s3d.json README.md dataset_generation_spec.md
until grep -q "ALL DONE" $L/run_mp3d.log 2>/dev/null && [ -f $L/mp3d_fixed.done ]; do sleep 300; done
echo "[sync_new] mp3d chain + fix finished; syncing $(date)"
sync_parts mp3d mp3d_f mp3d_g rir/mp3d_f rir/mp3d_g maps floorplan_proxy desdf dataset_meta_mp3d.json README.md
echo "[sync_new] ALL DONE $(date)"
