#!/bin/bash
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
echo "[maps] start $(date)"
./run_all.sh maps
echo "[maps] done $(date) -> $(ls $ECHOLOC_DATA/gibson/maps 2>/dev/null | wc -l) maps"
