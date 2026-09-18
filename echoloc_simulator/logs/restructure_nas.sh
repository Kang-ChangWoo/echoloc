#!/bin/bash
# Reshape both NAS copies into the per-dataset layout (server-side renames), then rsync from
# local to fill anything missing (MP3D never finished transferring).
R=/mnt/sdb/soundspaces/echoloc/echoloc_dataset
reshape() {
  local T=$1
  [ -d "$T" ] || return
  echo "[nas] reshape $T $(date)"
  mkdir -p $T/replica $T/mp3d $T/s3d
  for c in replica_f replica_g; do [ -d "$T/$c" ] && mv "$T/$c" "$T/replica/$c"; done
  for c in mp3d_f mp3d_g;     do [ -d "$T/$c" ] && mv "$T/$c" "$T/mp3d/$c"; done
  if [ -d "$T/s3d" ] && [ ! -d "$T/s3d/s3d" ] && ls "$T/s3d" 2>/dev/null | grep -q '^scene_'; then
    mv "$T/s3d" "$T/_s3d_col" && mkdir -p "$T/s3d" && mv "$T/_s3d_col" "$T/s3d/s3d"
  fi
  python3 - "$T" <<'PY'
import os, shutil, re, sys
T=sys.argv[1]
REPLICA={"frl_apartment_0","frl_apartment_1","frl_apartment_2","frl_apartment_3","hotel_0","office_0","office_1",
         "office_2","room_0","room_1","room_2","apartment_1","frl_apartment_4","office_3","apartment_2",
         "frl_apartment_5","office_4"}
def which(s):
    if s.startswith("scene_"): return "s3d"
    if re.search(r"_f\d+$", s): return "mp3d"
    return "replica" if s in REPLICA else None
for shared in ("maps","floorplan_proxy","desdf"):
    src=os.path.join(T,shared)
    if not os.path.isdir(src): continue
    c={}
    for scene in sorted(os.listdir(src)):
        ds=which(scene)
        if ds is None: continue
        dst=os.path.join(T,ds,shared); os.makedirs(dst,exist_ok=True)
        d=os.path.join(dst,scene)
        if os.path.exists(d): shutil.rmtree(os.path.join(src,scene), ignore_errors=True)
        else: shutil.move(os.path.join(src,scene), d)
        c[ds]=c.get(ds,0)+1
    if os.path.isdir(src) and not os.listdir(src): os.rmdir(src)
    print("  ",shared,c, flush=True)
src=os.path.join(T,"rir")
if os.path.isdir(src):
    for col in sorted(os.listdir(src)):
        ds={"replica_f":"replica","replica_g":"replica","mp3d_f":"mp3d","mp3d_g":"mp3d","s3d":"s3d"}.get(col)
        if ds is None: continue
        dst=os.path.join(T,ds,"rir"); os.makedirs(dst,exist_ok=True)
        d=os.path.join(dst,col)
        if not os.path.exists(d): shutil.move(os.path.join(src,col), d); print("   rir",col,"->",ds, flush=True)
    if not os.listdir(src): os.rmdir(src)
for f,ds in (("dataset_meta.json","replica"),("dataset_meta_mp3d.json","mp3d"),("dataset_meta_s3d.json","s3d")):
    p=os.path.join(T,f)
    if os.path.exists(p): shutil.move(p, os.path.join(T,ds,"dataset_meta.json"))
PY
  echo "[nas] reshape $T done $(date)"
}
for T in /file1/changwoo/echoloc_dataset /file2/changwoo/echoloc_dataset; do reshape $T; done
for T in /file1/changwoo/echoloc_dataset /file2/changwoo/echoloc_dataset; do
  rsync -a $R/README.md $R/dataset_generation_spec.md $T/
  for ds in replica s3d mp3d; do
    mkdir -p $T/$ds && rsync -a $R/$ds/ $T/$ds/ && echo "[nas] $ds -> $T done $(date)"
  done
done
echo "[nas] ALL DONE $(date)"
