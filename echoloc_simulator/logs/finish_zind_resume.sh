#!/bin/bash
# Resume of finish_zind.sh after the 2026-09-22 21:13 workstation hard crash (RIR stage, 12 floors left).
# Everything before rir is done; the 314 zero-byte RIR files were removed so render_rir re-renders those poses.
# LOW LOAD on purpose (13900KS suspected unstable under sustained all-core load): JOBS=2 x THREADS=4.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=zind
D=$ECHOLOC_DATA/zind
run () { echo "[stage] $1 start $(date)"; shift 1; "$@" || { echo "[stage] FAILED $(date)"; exit 1; }; echo "[stage] done $(date)"; }

run rir env JOBS=2 THREADS=4 ./run_all.sh rir
echo "[fin] rir files: $(find $D/rir -type f | wc -l) (expect 111852), zero-byte: $(find $D/rir -type f -size 0 | wc -l)"
$PY write_dataset_meta.py && echo "[stage] meta done $(date)"

echo "[stage] validate start $(date)"
./run_all.sh validate --ring-only > logs/zind_validate.log 2>&1
echo "[stage] validate $(grep '^RESULT:' logs/zind_validate.log) $(date)"
grep -q "^RESULT: OK" logs/zind_validate.log || {
  echo "[fin] ABORT: validation failed, nothing uploaded"; grep '  FAIL ' logs/zind_validate.log | head -20; exit 1; }

# per-scene rsync, 4 at a time. No --delete.
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
