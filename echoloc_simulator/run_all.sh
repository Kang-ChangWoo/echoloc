#!/bin/bash
# End-to-end generation, resume-safe (every stage skips what already exists).
#
#   ./run_all.sh maps                      stage 1  map.png + meta + proxies (all scenes)
#   ./run_all.sh poses  [N_CHUNKS]         stage 2  both collections, all scenes (0 = auto from free area)
#   ECHOLOC_DATASET=mp3d ./run_all.sh ...  runs the MP3D profile (collections mp3d_f/mp3d_g, per-storey scenes)
#   ./run_all.sh rgb                       stage 3  parallel over scenes (JOBS workers)
#   ./run_all.sh depthmaps                 stage 3b per-pixel radial depth (scan + floorplan), JOBS workers
#   ./run_all.sh depth                     stage 4  depth40/160 (CPU pool per scene)
#   ./run_all.sh desdf                     stage 5  test scenes
#   ./run_all.sh rir [condition]           stage 6  reference frames; default both conditions; LAYOUT=binaural for the 2ch HRTF render
#   ./run_all.sh validate                  stage 7
#   ./run_all.sh visual                    stages 1-5 + validate
#
# JOBS=4 ./run_all.sh rgb   -> 4 habitat workers at once (one A6000 handles ~4-6).
# ECHOLOC_DATA=<dir> selects the dataset root (default /mnt/sdb/soundspaces/echoloc/echoloc_dataset).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
source ./env.sh
LOG="$HERE/logs"; mkdir -p "$LOG"
JOBS="${JOBS:-4}"
SCENES=$($PY -c "import common as C; print(' '.join(C.SCENES))")
COLS=$($PY -c "import common as C; print(' '.join(C.COLLECTIONS))")

stage_maps()  { $PY build_maps.py 2>&1 | grep -v '^\[.*\]:\[' | tee "$LOG/maps.log"; }
stage_poses() {
  local n="${1:-300}"
  for c in $COLS; do $PY sample_poses.py --collection "$c" --n-chunks "$n" 2>&1 | grep -v '^\[.*\]:\[' | tee -a "$LOG/poses_$c.log"; done
}
stage_rgb() {
  for c in $COLS; do
    printf '%s\n' $SCENES | xargs -P "$JOBS" -I{} bash -c \
      "$PY render_rgb.py --collection $c --scenes {} 2>&1 | grep -v '^\[.*\]:\[' >> '$LOG/rgb_${c}_{}.log'"
    echo "[rgb] $c done"; grep -h "^\[" "$LOG"/rgb_${c}_*.log | tail -n 40
  done
}
stage_depthmaps() {
  for c in $COLS; do
    printf '%s\n' $SCENES | xargs -P "$JOBS" -I{} bash -c \
      "$PY render_depth.py --collection $c --scenes {} 2>&1 | grep -v '^\[.*\]:\[' >> '$LOG/depthmaps_${c}_{}.log'"
    echo "[depthmaps] $c done"
  done
}
stage_depth() {
  for c in $COLS; do $PY make_depth_gt.py --collection "$c" --workers "${WORKERS:-12}" 2>&1 | tee -a "$LOG/depth_$c.log"; done
}
stage_desdf() { $PY make_desdf.py --workers "${WORKERS:-12}" 2>&1 | tee -a "$LOG/desdf.log"; }
stage_rir() {
  local conds="${1:-$($PY -c "import common as C; print(' '.join(C.CONDITIONS))")}"
  for c in $COLS; do for cond in $conds; do
    printf '%s\n' $SCENES | xargs -P "$JOBS" -I{} bash -c \
      "$PY render_rir.py --collection $c --condition $cond --scenes {} --threads ${THREADS:-2} --layout ${LAYOUT:-ring} 2>&1 | grep -v '^\[.*\]:\[' >> '$LOG/rir_${c}_${cond}_{}.log'"
    echo "[rir] $c $cond done"
  done; done
}
stage_validate() { $PY validate.py "$@" 2>&1 | grep -v '^\[.*\]:\[' | tee "$LOG/validate.log"; }

case "${1:-}" in
  maps) stage_maps ;;
  poses) stage_poses "${2:-300}" ;;
  rgb) stage_rgb ;;
  depthmaps) stage_depthmaps ;;
  depth) stage_depth ;;
  desdf) stage_desdf ;;
  rir) stage_rir "${2:-}" ;;
  validate) shift; stage_validate "$@" ;;
  visual) stage_maps; stage_poses "${2:-300}"; stage_rgb; stage_depthmaps; stage_depth; stage_desdf; stage_validate ;;
  *) sed -n 2,14p "$0"; exit 1 ;;
esac
