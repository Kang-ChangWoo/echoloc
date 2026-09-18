#!/bin/bash
# Final cross-check: every local Gibson file present on both NAS, and nothing stale left over.
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset
cd $S/gibson && find . -type f | sort > /tmp/gib_local.txt
echo "[vfy] local $(wc -l < /tmp/gib_local.txt) files"
for T in /file1/changwoo /file2/changwoo; do
  cd $T/echoloc_dataset/gibson && find . -type f | sort > /tmp/gib_$(basename $(dirname $T)).txt
  f=/tmp/gib_$(basename $(dirname $T)).txt
  echo "[vfy] $T $(wc -l < $f) files  missing $(comm -23 /tmp/gib_local.txt $f | wc -l)  extra $(comm -13 /tmp/gib_local.txt $f | wc -l)"
  comm -13 /tmp/gib_local.txt $f | head -5
done
for d in replica mp3d s3d; do
  cd $S/$d && find . -type f | sort > /tmp/d_local.txt
  for T in /file1/changwoo /file2/changwoo; do
    cd $T/echoloc_dataset/$d && find . -type f | sort > /tmp/d_nas.txt
    echo "[vfy] $d $T: missing $(comm -23 /tmp/d_local.txt /tmp/d_nas.txt | wc -l)  extra $(comm -13 /tmp/d_local.txt /tmp/d_nas.txt | wc -l)"
    comm -13 /tmp/d_local.txt /tmp/d_nas.txt | head -3
  done
done
echo "[vfy] ALL DONE $(date)"
