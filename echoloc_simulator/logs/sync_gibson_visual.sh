#!/bin/bash
# Gibson through the desdf stage: frames, depth GT, desdf. RIR is excluded -- it is still
# rendering and is the bulk of the release, so it gets its own pass afterwards.
# Sequential on purpose: two rsyncs against the same tree fight each other.
S=/mnt/sdb/soundspaces/echoloc/echoloc_dataset/gibson
for T in /file1/changwoo /file2/changwoo; do
  D=$T/echoloc_dataset/gibson
  mkdir -p $D
  rsync -a --exclude 'rir/' $S/ $D/ \
    && echo "[visual] $T done  $(du -sh $D | cut -f1)  files $(find $D -type f | wc -l)  $(date)" \
    || echo "[visual] $T FAILED $(date)"
done
echo "[visual] ALL DONE $(date)"
