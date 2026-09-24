#!/bin/bash
# Waits for finish_zind_resume2.sh (its validate runs the OLD check 9 and will ABORT on corner-clip
# false FAILs), re-validates only the failed scenes with the patched validate.py (corner clips excluded),
# and uploads to both NAS only if that recheck is OK.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=zind
D=$ECHOLOC_DATA/zind
while pgrep -f finish_zind_resume2.sh >/dev/null; do sleep 60; done
echo "[after] chain exited $(date): $(tail -1 logs/zind_finish_resume2.log)"
if grep -q "^RESULT: OK" logs/zind_validate.log; then
  echo "[after] chain validate OK; chain did the upload itself -> nothing to do"; exit 0
fi
FAILED=$(tr '\r' '\n' < logs/zind_validate.log | grep -oE '^  FAIL [0-9]+_f[0-9]+' | awk '{print $2}' | sort -u)
echo "[after] failed scenes: $(echo $FAILED | wc -w): $FAILED"
[ -n "$FAILED" ] || { echo "[after] ABORT: no RESULT OK but no FAIL lines either"; exit 1; }
$PY validate.py --ring-only --figs 0 --scenes $FAILED 2>&1 | grep -v '^\[.*\]:\[' > logs/zind_validate_recheck.log
echo "[after] recheck $(grep '^RESULT:' logs/zind_validate_recheck.log) $(date)"
grep -E "check 9|FAIL" logs/zind_validate_recheck.log
grep -q "^RESULT: OK" logs/zind_validate_recheck.log || { echo "[after] ABORT: recheck failed, nothing uploaded"; exit 1; }
echo "[stage] upload start $(date)"
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
