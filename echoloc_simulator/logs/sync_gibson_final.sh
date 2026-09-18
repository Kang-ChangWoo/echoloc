#!/bin/bash
# Final Gibson upload: waits for validate (chain3) AND for the in-flight 225 GB visual
# rsync, then mirrors the whole dataset including rir. Also re-runs the semantic sync so
# replica/mp3d/s3d semantic maps are confirmed present on both NAS.
# Never run two rsyncs at the same tree concurrently -- hence the waits.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset

echo "[final] waiting for validate $(date)"
until grep -q "\[chain3\] ALL DONE" logs/gibson_chain3.log 2>/dev/null; do
  grep -q "FAILED" logs/gibson_chain3.log 2>/dev/null && { echo "[final] ABORT: chain3 reported FAILED"; exit 1; }
  sleep 120
done
echo "[final] validate done $(date)"

echo "[final] waiting for the visual rsync to finish $(date)"
until grep -q "\[visual\] ALL DONE" logs/sync_gibson_visual.log 2>/dev/null; do sleep 120; done
echo "[final] visual rsync done $(date)"

for T in /file1/changwoo /file2/changwoo; do
  D=$T/echoloc_dataset/gibson
  mkdir -p $D
  rsync -a --delete $S/gibson/ $D/ \
    && echo "[final] $T gibson done  $(du -sh $D | cut -f1)  files $(find $D -type f | wc -l)  $(date)" \
    || { echo "[final] $T gibson FAILED $(date)"; continue; }
  # semantic maps live beside map.png inside maps/<scene>/ and in each collection dir
  for d in replica mp3d s3d; do
    rsync -a --include='*/' --include='semantic_map.png' --include='semantic_legend.json' \
      --exclude='*' $S/$d/maps/ $T/echoloc_dataset/$d/maps/
    echo "[final] $T $d semantic: $(find $T/echoloc_dataset/$d/maps -name 'semantic_map.png' | wc -l) maps $(date)"
  done
  rsync -a $S/README.md $T/echoloc_dataset/
done
echo "[final] ALL DONE $(date)"
