#!/bin/bash
# Wait for the Gibson pipeline to finish validating, then download ZInD.
# The token comes from the environment ($ZIND_SERVER_TOKEN, set by whoever launches this)
# and is deliberately absent from this file -- this directory is mirrored to the NAS.
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator
echo "[zind] waiting for the Gibson pipeline $(date)"
until grep -q "\[chain3\] ALL DONE" logs/gibson_chain3.log 2>/dev/null; do
  grep -q "FAILED" logs/gibson_chain3.log 2>/dev/null && { echo "[zind] Gibson chain reported FAILED -- starting anyway $(date)"; break; }
  sleep 120
done
echo "[zind] Gibson done, starting download $(date)"
python3 zind_download.py --out /mnt/sdb/zind_raw --workers 4
echo "[zind] exit $? $(date)"
du -sh /mnt/sdb/zind_raw 2>/dev/null
echo "[zind] ALL DONE $(date)"
