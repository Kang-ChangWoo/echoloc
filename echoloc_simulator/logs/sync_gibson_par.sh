#!/bin/bash
# Parallel Gibson mirror. This machine reaches both NAS over Wi-Fi (both wired ports are
# down), so a single rsync spends most of its time waiting on NFS round trips: 626 files/min
# against a 16-27 MB/s link. Splitting by scene lets several transfers overlap that latency.
#
#   TARGET=/file2/changwoo WORKERS=12 logs/sync_gibson_par.sh
#
# Resume-safe (rsync skips files that already match) and safe to re-run. No --delete: the
# workers each see only their own slice, so a tree-wide delete would remove the others' work.
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset/gibson
T=${TARGET:?set TARGET, e.g. /file2/changwoo}/echoloc_dataset/gibson
W=${WORKERS:-12}
mkdir -p $T
echo "[par] $T with $W workers $(date)"

# top-level small trees first: cheap, and they make the target usable early
for d in maps floorplan_proxy desdf; do
  rsync -a $S/$d/ $T/$d/ && echo "[par] $d done $(date +%H:%M)"
done
rsync -a --include='*.json' --include='*.md' --exclude='*/' $S/ $T/ 2>/dev/null

# per-scene work, one rsync per scene, W at a time
for col in gibson_f gibson_g; do
  mkdir -p $T/$col
  rsync -a --include='split.yaml' --exclude='*/' --exclude='*' $S/$col/ $T/$col/
  ls $S/$col | grep '_f[0-9]*$' | xargs -P $W -I{} \
    rsync -a $S/$col/{}/ $T/$col/{}/
  echo "[par] $col done  $(find $T/$col -type f | wc -l) files  $(date +%H:%M)"
done
for col in gibson_f gibson_g; do
  for cond in raw_scan_open floorplan_closed; do
    mkdir -p $T/rir/$col/$cond
    ls $S/rir/$col/$cond | xargs -P $W -I{} \
      rsync -a $S/rir/$col/$cond/{}/ $T/rir/$col/$cond/{}/
    echo "[par] rir/$col/$cond done  $(date +%H:%M)"
  done
done
echo "[par] ALL DONE  $(du -sh $T | cut -f1)  $(find $T -type f | wc -l) files  $(date)"
