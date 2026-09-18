#!/bin/bash
# Upload the parts of the Gibson dataset that are final while rgb/depth are still
# rendering: maps, floorplan proxies, poses/chunks/split, READMEs.
# No --delete here -- the target will legitimately lack the frame dirs for now.
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset
for T in /file1/changwoo /file2/changwoo; do
  mkdir -p $T/echoloc_dataset/gibson
  rsync -a $S/README.md $T/echoloc_dataset/
  rsync -a $S/mp3d/README.md $T/echoloc_dataset/mp3d/
  rsync -a $S/gibson/README.md $T/echoloc_dataset/gibson/
  rsync -a $S/gibson/maps/ $T/echoloc_dataset/gibson/maps/ \
    && echo "[stable] $T maps done $(date +%H:%M)"
  rsync -a $S/gibson/floorplan_proxy/ $T/echoloc_dataset/gibson/floorplan_proxy/ \
    && echo "[stable] $T floorplan_proxy done $(date +%H:%M)"
  for c in gibson_f gibson_g; do
    rsync -a --include '*/' --include 'poses.txt' --include 'chunks.json' \
      --include 'map.png' --include 'split.yaml' --exclude '*' \
      $S/gibson/$c/ $T/echoloc_dataset/gibson/$c/ \
      && echo "[stable] $T $c poses/chunks done $(date +%H:%M)"
  done
  echo "[stable] $T subtotal $(du -sh $T/echoloc_dataset/gibson | cut -f1) $(date)"
done
echo "[stable] ALL DONE $(date)"
