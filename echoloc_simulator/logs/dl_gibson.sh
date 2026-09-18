#!/bin/bash
cd /mnt/sdb/gibson_raw
echo "[gibson] start $(date)"
for u in https://dl.fbaipublicfiles.com/habitat/data/scene_datasets/gibson_habitat_trainval.zip \
         https://dl.fbaipublicfiles.com/habitat/data/scene_datasets/gibson_habitat.zip; do
  f=$(basename $u)
  curl -sL --retry 5 -C - -o $f "$u" && echo "[gibson] downloaded $f ($(du -h $f | cut -f1))"
done
for f in *.zip; do unzip -q -o $f -d . && echo "[gibson] extracted $f"; done
echo "[gibson] scenes: $(find . -name '*.glb' | wc -l) glb, $(find . -name '*.navmesh' | wc -l) navmesh"
du -sh /mnt/sdb/gibson_raw | sed 's/^/[gibson] size /'
echo "[gibson] ALL DONE $(date)"
