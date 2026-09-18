#!/bin/bash
# gibson_g/Pinesdale_f2 had one chunk on a raised landing, putting the camera on the storey
# ceiling (4 frames, top half of the image empty). sample_poses.py now applies the
# split-level ceiling rule to gibson too; resample this scene and rebuild only its outputs.
set -e
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
S=Pinesdale_f2; D=$ECHOLOC_DATA/gibson
for col in gibson_g; do
  echo "[fix] wiping $col/$S outputs $(date)"
  rm -rf $D/$col/$S/rgb $D/$col/$S/depth_radial_scan $D/$col/$S/depth_radial_floorplan
  rm -f  $D/$col/$S/poses.txt $D/$col/$S/chunks.json $D/$col/$S/depth40.txt $D/$col/$S/depth160.txt
  rm -rf $D/rir/$col/raw_scan_open/$S $D/rir/$col/floorplan_closed/$S
  echo "[fix] resampling poses"
  $PY sample_poses.py --collection $col --scenes $S --n-chunks 0 2>&1 | grep -v '^\[.*\]:\[' | tail -2
  echo "[fix] rgb";        $PY render_rgb.py   --collection $col --scenes $S 2>&1 | grep -v '^\[.*\]:\[' | tail -1
  echo "[fix] depthmaps";  $PY render_depth.py --collection $col --scenes $S 2>&1 | grep -v '^\[.*\]:\[' | tail -2
  echo "[fix] depth gt";   $PY make_depth_gt.py --collection $col --scenes $S --workers 4 2>&1 | tail -2
  for cond in raw_scan_open floorplan_closed; do
    echo "[fix] rir $cond"
    $PY render_rir.py --collection $col --condition $cond --scenes $S --threads 8 --layout ring 2>&1 | grep -v '^\[.*\]:\[' | tail -1
  done
done
echo "[fix] ALL DONE $(date)"
