#!/bin/bash
# Local-only validation (no network), so it can run while the NAS transfer saturates Wi-Fi.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator && source env.sh
export ECHOLOC_DATASET=gibson
echo "[val2] start $(date)"
$PY validate.py --ring-only 2>&1 | grep -v '^\[.*\]:\[' > logs/validate_gibson2.log
echo "[val2] $(grep '^RESULT:' logs/validate_gibson2.log) $(date)"
grep '  FAIL ' logs/validate_gibson2.log | head -20
echo "[val2] ALL DONE $(date)"
