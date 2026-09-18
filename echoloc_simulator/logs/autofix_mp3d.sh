#!/bin/bash
# Wait for the MP3D validation, auto-fix any failing scenes (re-sample + regenerate the full
# per-scene product), re-validate, then push the result to both NAS. Idempotent, resume-safe.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh && export ECHOLOC_DATASET=mp3d
L=logs; R=/mnt/sdb/soundspaces/echoloc/echoloc_dataset/mp3d
until grep -q "ALL DONE" $L/validate_mp3d.log 2>/dev/null; do sleep 120; done
round=0
while :; do
  round=$((round+1))
  if grep -q "RESULT: OK" $L/validate_mp3d.out 2>/dev/null; then
    echo "[autofix] validation OK (round $round) $(date)"; break
  fi
  SC=$(grep "FAIL" $L/validate_mp3d.out | sed -n 's/.*FAIL \([A-Za-z0-9_]*_f[0-9][0-9]*\):.*/\1/p' | sort -u | tr '\n' ' ')
  if [ -z "$SC" ]; then
    echo "[autofix] failures that are not per-scene, stopping for review $(date)"
    grep "FAIL" $L/validate_mp3d.out | head -10 | sed 's/^/[autofix] /'; break
  fi
  if [ $round -gt 3 ]; then echo "[autofix] still failing after $round rounds, stopping $(date)"; break; fi
  echo "[autofix] round $round: regenerating $(echo $SC | wc -w) scenes: $SC"
  for s in $SC; do
    for c in mp3d_f mp3d_g; do
      rm -rf $R/$c/$s/rgb $R/$c/$s/depth_radial_scan $R/$c/$s/depth_radial_floorplan \
             $R/$c/$s/poses.txt $R/$c/$s/chunks.json $R/$c/$s/depth40.txt $R/$c/$s/depth160.txt \
             $R/rir/$c/raw_scan_open/$s $R/rir/$c/floorplan_closed/$s validation/$c/$s
    done
    rm -rf $R/desdf/$s
  done
  for c in mp3d_f mp3d_g; do $PY sample_poses.py --collection $c --scenes $SC --n-chunks 0 2>&1 | grep "^\[" | sed 's/^/[autofix] /'; done
  for c in mp3d_f mp3d_g; do
    printf '%s\n' $SC | xargs -P 3 -I{} bash -c "$PY render_rgb.py --collection $c --scenes {} 2>&1 | grep -v '^\[.*\]:\[' >> $L/autofix_render.log"
    printf '%s\n' $SC | xargs -P 3 -I{} bash -c "$PY render_depth.py --collection $c --scenes {} 2>&1 | grep -v '^\[.*\]:\[' >> $L/autofix_render.log"
    $PY make_depth_gt.py --collection $c --scenes $SC --workers 12 2>&1 | grep -c "^\[" | sed "s/^/[autofix] $c depth files: /"
  done
  TEST=$($PY -c "import common as C,sys; sc=set('$SC'.split()); print(' '.join(s for s in C.SPLIT['test'] if s in sc))")
  [ -n "$TEST" ] && $PY make_desdf.py --scenes $TEST --workers 12 2>&1 | grep -c "^\[" | sed 's/^/[autofix] desdf: /'
  for c in mp3d_f mp3d_g; do for cond in raw_scan_open floorplan_closed; do for layout in ring binaural; do
    printf '%s\n' $SC | xargs -P 4 -I{} bash -c "$PY render_rir.py --collection $c --condition $cond --scenes {} --threads 4 --layout $layout 2>&1 | grep -v '^\[.*\]:\[' >> $L/autofix_rir.log"
  done; done; done
  echo "[autofix] round $round rir done $(date)"
  $PY write_dataset_meta.py 2>&1 | grep -v Warning | head -1 | sed 's/^/[autofix] /'
  $PY validate.py --figs 0 2>&1 | grep -v "^\[.*\]:\[" > $L/validate_mp3d.out
  grep "RESULT" $L/validate_mp3d.out | sed "s/^/[autofix] round $round revalidate: /"
done
echo "[autofix] syncing mp3d to NAS $(date)"
for T in /file1/changwoo/echoloc_dataset /file2/changwoo/echoloc_dataset; do
  mkdir -p $T/mp3d && rsync -a --delete $R/ $T/mp3d/ && echo "[autofix] mp3d -> $T done $(date)"
done
echo "[autofix] ALL DONE $(date)"
