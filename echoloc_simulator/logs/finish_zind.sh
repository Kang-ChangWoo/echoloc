#!/bin/bash
# Wait for the ZInD import, then finish the dataset the way the other four are finished:
# proxy depth maps -> depth40/160 -> desdf (test) -> semantic maps -> dataset_meta -> validate,
# and upload to both NAS only if validation passes.
#
# ZInD has no scan mesh and no depth of its own, so there is no depth_radial_scan and only the
# floorplan_closed acoustic condition -- same situation as s3d, one step more extreme.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=zind
D=$ECHOLOC_DATA/zind

# split.yaml must list only finished floors: every later stage reads it and dies on a missing
# poses.txt (hit once: floors that bailed after writing map.png were still in the split).
echo "[fin] refreshing split.yaml from finished floors $(date)"
$PY - <<'EOS'
import json, os, yaml, common as C
mroot = os.path.join(C.ROOT, "maps")
built = sorted(d for d in os.listdir(mroot) if os.path.exists(os.path.join(mroot, d, "scene_meta.json")))
part = json.load(open(os.path.join(C.HERE, "floorplan_extraction", "zind_partition.json")))
split = {k: [s for s in built if C.base_scene(s) in set(v)] for k, v in part.items()}
yaml.safe_dump(split, open(os.path.join(C.ROOT, C.COLLECTIONS[0], "split.yaml"), "w"))
print("[fin] split", {k: len(v) for k, v in split.items()}, "of", len(built), "floors")
EOS

echo "[fin] verifying the import $(date)"
$PY verify_zind.py --scenes 60 > logs/zind_verify.log 2>&1
grep -E '^floors|^frames|^camera|^ceiling|^free |^yaw/map|^crop|^split' logs/zind_verify.log
grep -q "^RESULT: OK" logs/zind_verify.log || {
  echo "[fin] ABORT: import verification not OK"; grep -E '^RESULT|^ -' logs/zind_verify.log; exit 1; }
echo "[fin] import verified $(date)"

run () {
  echo "[stage] $1 start $(date)"
  shift 1
  "$@" || { echo "[stage] FAILED $(date)"; exit 1; }
  echo "[stage] done $(date)"
}
run depthmaps env JOBS=4 ./run_all.sh depthmaps
run depth     env WORKERS=12 ./run_all.sh depth
run desdf     env WORKERS=12 ./run_all.sh desdf
run semantic  $PY make_semantic_map.py
run rir       env JOBS=6 THREADS=5 ./run_all.sh rir
$PY write_dataset_meta.py && echo "[stage] meta done $(date)"

echo "[stage] validate start $(date)"
./run_all.sh validate --ring-only > logs/zind_validate.log 2>&1
echo "[stage] validate $(grep '^RESULT:' logs/zind_validate.log) $(date)"
grep -q "^RESULT: OK" logs/zind_validate.log || {
  echo "[fin] ABORT: validation failed, nothing uploaded"; grep '  FAIL ' logs/zind_validate.log | head -20; exit 1; }

# per-scene rsync, 6 at a time (Wi-Fi: a single stream is latency-bound). No --delete.
for T in /file2/changwoo /file1/changwoo; do
  DD=$T/echoloc_dataset/zind
  mkdir -p $DD
  rsync -a --include='*.json' --include='*.md' --exclude='*/' $D/ $DD/ 2>/dev/null
  for sub in maps floorplan_proxy desdf zind; do
    mkdir -p $DD/$sub
    ls $D/$sub | xargs -P 6 -I{} rsync -a $D/$sub/{}/ $DD/$sub/{}/ 2>/dev/null
    echo "[fin] $T $sub done $(date +%H:%M)"
  done
  ls $D/rir/zind 2>/dev/null | while read c; do
    mkdir -p $DD/rir/zind/$c
    ls $D/rir/zind/$c | xargs -P 6 -I{} rsync -a $D/rir/zind/$c/{}/ $DD/rir/zind/$c/{}/ 2>/dev/null
  done
  echo "[fin] $T done  $(du -sh $DD | cut -f1)  $(find $DD -type f | wc -l) files  $(date)"
done
echo "[fin] ALL DONE $(date)"
