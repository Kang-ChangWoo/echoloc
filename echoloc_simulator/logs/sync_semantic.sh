#!/bin/bash
# Wait for the semantic-map run, then push semantic maps (and their legends) to both NAS.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
L=logs; R=/mnt/sdb/soundspaces/echoloc/echoloc_dataset
until grep -q "ALL DONE" $L/run_semantic.log 2>/dev/null; do sleep 60; done
echo "[sync_sem] start $(date)"
for T in /file1/changwoo/echoloc_dataset /file2/changwoo/echoloc_dataset; do
  for d in replica mp3d s3d; do
    rsync -a --include='*/' --include='semantic_map.png' --include='semantic_legend.json' --exclude='*' $R/$d/maps/ $T/$d/maps/
    for col in $(ls -d $R/$d/*/ | xargs -n1 basename | grep -vE '^(maps|floorplan_proxy|desdf|rir)$'); do
      rsync -a --include='*/' --include='semantic_map.png' --exclude='*' $R/$d/$col/ $T/$d/$col/
    done
    echo "[sync_sem] $d -> $T done $(date)"
  done
done
echo "[sync_sem] ALL DONE $(date)"
