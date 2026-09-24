#!/bin/bash
# ZInD -> echoloc: maps, proxies, panorama crops, poses for every floor with a metric scale,
# then verify (yaw/map consistency, crop orientation, metric plausibility, split disjointness).
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=zind
echo "[zind] build start $(date)"
$PY build_zind.py --workers 10
echo "[zind] build exit $? $(date)"
echo "[zind] verify start $(date)"
$PY verify_zind.py --scenes 60 > logs/zind_verify.log 2>&1
echo "[zind] verify exit $? -- $(grep '^RESULT' logs/zind_verify.log) $(date)"
grep -E '^floors|^frames|^camera|^ceiling|^free|^yaw/map|^crop|^split|^ -' logs/zind_verify.log
echo "[zind] ALL DONE $(date)"
