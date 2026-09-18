#!/bin/bash
# After the S3D chain: drop wall-touching frames (clearance < 2 cm) by rebuilding the affected scenes.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh && export ECHOLOC_DATASET=s3d
L=logs; R=/mnt/sdb/soundspaces/echoloc/echoloc_dataset
until grep -q "ALL DONE" $L/run_s3d.log 2>/dev/null; do sleep 120; done
SC=$(cat /tmp/claude-1000/-home-rvi-lab/060ce9f5-cdf0-48b3-8fc2-ca764951b5dd/scratchpad/s3d_fix_scenes.txt)
echo "[fix_s3d] start $(date): $(echo $SC | wc -w) scenes"
for s in $SC; do rm -rf $R/s3d/$s $R/rir/s3d/floorplan_closed/$s $R/maps/$s $R/floorplan_proxy/$s $R/desdf/$s; done
$PY build_s3d.py --scenes $SC 2>&1 | grep -c "^\[scene" | sed 's/^/[fix_s3d] rebuilt: /'
$PY build_s3d.py --scenes scene_00000 2>&1 | grep "^\[split\]"
$PY make_depth_gt.py --collection s3d --scenes $SC --workers 12 2>&1 | grep -c "^\[" | sed 's/^/[fix_s3d] depth files: /'
printf '%s\n' $SC | xargs -P 4 -I{} bash -c "$PY render_depth.py --collection s3d --scenes {} 2>&1 | grep -v '^\[.*\]:\[' >> $L/depthmaps_s3d_fix.log"; echo "[fix_s3d] proxy depth done"
TEST=$($PY -c "import common as C; sc=set('$SC'.split()); print(' '.join(s for s in C.SPLIT['test'] if s in sc))")
[ -n "$TEST" ] && $PY make_desdf.py --scenes $TEST --workers 12 2>&1 | grep -c "^\[" | sed 's/^/[fix_s3d] desdf: /'
for layout in ring binaural; do printf '%s\n' $SC | xargs -P 6 -I{} bash -c "$PY render_rir.py --collection s3d --condition floorplan_closed --scenes {} --threads 5 --layout $layout 2>&1 | grep -v '^\[.*\]:\[' >> $L/rir_s3d_fix.log"; echo "[fix_s3d] rir $layout done"; done
$PY write_dataset_meta.py 2>&1 | grep -v Warning | head -1
./run_all.sh validate --figs 0 2>&1 | grep -E "RESULT|FAIL" | sed 's/^/[fix_s3d validate] /'
touch $L/s3d_fixed.done; echo "[fix_s3d] ALL DONE $(date)"
