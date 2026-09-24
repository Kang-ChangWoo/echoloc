#!/bin/bash
# 2nd resume (2026-09-24 00:10): rir stage is complete (111,852 files, 0 zero-byte); the 09-23 18:55 FAILED was a
# transient python corruption (yaml AttributeError) on the faulty P-core 16 -> CPUs 8-11 (cores 16/20) taken offline.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=zind
D=$ECHOLOC_DATA/zind
[ "$(find $D/rir -type f | wc -l)" = 111852 ] || { echo "[fin] ABORT: rir file count $(find $D/rir -type f | wc -l) != 111852"; exit 1; }
$PY write_dataset_meta.py || { echo "[stage] meta FAILED $(date)"; exit 1; }
echo "[stage] meta done $(date)"
echo "[stage] validate start $(date)"
./run_all.sh validate --ring-only > logs/zind_validate.log 2>&1
echo "[stage] validate $(grep '^RESULT:' logs/zind_validate.log) $(date)"
grep -q "^RESULT: OK" logs/zind_validate.log || {
  echo "[fin] ABORT: validation failed, nothing uploaded"; grep '  FAIL ' logs/zind_validate.log | head -20; exit 1; }
for T in /file2/changwoo /file1/changwoo; do
  DD=$T/echoloc_dataset/zind
  mkdir -p $DD
  rsync -a --include='*.json' --include='*.md' --exclude='*/' $D/ $DD/ 2>/dev/null
  for sub in maps floorplan_proxy desdf zind; do
    mkdir -p $DD/$sub
    ls $D/$sub | xargs -P 4 -I{} rsync -a $D/$sub/{}/ $DD/$sub/{}/ 2>/dev/null
    echo "[fin] $T $sub done $(date +%H:%M)"
  done
  ls $D/rir/zind 2>/dev/null | while read c; do
    mkdir -p $DD/rir/zind/$c
    ls $D/rir/zind/$c | xargs -P 4 -I{} rsync -a $D/rir/zind/$c/{}/ $DD/rir/zind/$c/{}/ 2>/dev/null
  done
  echo "[fin] $T done  $(du -sh $DD | cut -f1)  $(find $DD -type f | wc -l) files  $(date)"
done
echo "[fin] ALL DONE $(date)"
