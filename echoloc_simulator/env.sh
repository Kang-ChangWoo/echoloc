#!/bin/bash
# habitat-sim 0.2.2 in the ss_v2 env segfaults on import unless conda's libstdc++
# and libz win over the OS ones. Source this, then use $PY.
ENV_DIR="${SS_ENV_DIR:-$HOME/miniconda3/envs/ss_v2}"
export LD_PRELOAD="$ENV_DIR/lib/libstdc++.so.6 $ENV_DIR/lib/libz.so.1"
export MAGNUM_LOG=quiet HABITAT_SIM_LOG=quiet GLOG_minloglevel=2
export REPLICA_RAW_DIR="${REPLICA_RAW_DIR:-/mnt/sdb/replica_raw}"   # local copy of /file1/rvi/dataset/replica/raw (43 GB)
export ECHOLOC_DATASET="${ECHOLOC_DATASET:-replica}"                                 # replica | mp3d
export ECHOLOC_DATA="${ECHOLOC_DATA:-/mnt/sdb/soundspaces/echoloc/echoloc_dataset}"          # dataset root (data only)
PY="$ENV_DIR/bin/python -u"
export PY
