#!/bin/bash
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
echo "[poses] start $(date)"
./run_all.sh poses 0
echo "[poses] done $(date)"
