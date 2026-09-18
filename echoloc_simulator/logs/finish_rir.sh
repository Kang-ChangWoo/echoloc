#!/bin/bash
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
JOBS=4 THREADS=6 ./run_all.sh rir 2>&1 | grep "^\[rir\]"
LAYOUT=binaural JOBS=4 THREADS=6 ./run_all.sh rir 2>&1 | grep "^\[rir\]"
$PY write_dataset_meta.py 2>&1 | grep -v Warning | head -1
./run_all.sh validate --figs 0 2>&1 | grep -E "RESULT|FAIL"
for t in /file1/changwoo/echoloc_dataset /file2/changwoo/echoloc_dataset; do
  rsync -a --delete /mnt/sdb/soundspaces/echoloc/echoloc_dataset/rir/ $t/rir/ && rsync -a /mnt/sdb/soundspaces/echoloc/echoloc_dataset/dataset_meta.json /mnt/sdb/soundspaces/echoloc/echoloc_dataset/README.md $t/ && echo "[sync] $t done"
done
echo "[finish_rir] ALL DONE $(date)"
