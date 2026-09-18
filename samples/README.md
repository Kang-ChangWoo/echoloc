# samples/ — 데이터셋마다 씬 하나씩, 파이프라인이 만드는 모든 파일의 실물

전체 데이터(~620 GB)는 저장소에 없다. 이 폴더는 "각 파일이 실제로 어떻게 생겼는지"를 보여주기 위한 것으로,
`echoloc_simulator/make_samples.py`가 실제 데이터셋에서 그대로 복사해 만든다 (93 파일, 10.5 MB).
행 단위 파일(`poses.txt`, `depth40.txt`, `depth160.txt`)은 첫 8행(= 2청크), `chunks.json`은 첫 2청크로 잘랐고 머리글에 표시했다.

| 데이터셋 | 씬 | split | 넣은 것 | 뺀 것과 이유 |
|---|---|---|---|---|
| replica | `office_4` | test | **전부**: rgb 4뷰, depth_radial_scan/floorplan, map, semantic_map, 프록시 glb, poses/depth 행, chunks, ring+binaural RIR 두 조건, desdf, raw의 `info_semantic.json`·scene config | 메시 `.ply`(크기) |
| mp3d | `pLe4wQe7qrG_f0` | test | map, semantic_map, 프록시, poses/depth 행, chunks, depth_radial_**floorplan**, 프록시 조건 ring RIR, desdf | rgb·scan depth·raw·binaural — **Matterport 약관이 데이터와 그 렌더의 재배포를 금지** |
| gibson | `Crookston_f1` | test | 위와 같음 (시멘틱 없음) | 위와 같음 — **Stanford Gibson 라이선스** |
| s3d | `scene_03260` | test | map, semantic_map, 프록시, poses/depth 행, chunks, depth_radial_floorplan, ring RIR, desdf | rgb·depth_radial_scan(S3D가 제공한 렌더 그 자체)·`annotation_3d.json` — **Structured3D 비재배포 조건** |
| zind | `0000` | — | 파일 목록만 | 전부 — Zillow 약관 |

즉 mp3d / gibson / s3d에서 넣은 것은 **우리가 계산한 추상물**(벽 도면, 압출 프록시, 포즈, 도면에 ray cast한 깊이, 프록시 위에서 렌더한 RIR)뿐이고 원본 스캔의 픽셀·기하가 그대로 담긴 파일은 없다.
같은 파일 종류의 실물이 필요하면 replica 샘플을 보면 된다(형식·이름·카메라는 네 데이터셋이 동일하고, s3d만 640×360·단일 뷰).

`<dataset>/raw/LISTING.txt`는 원본 폴더의 `find` 결과(크기, 경로)라 어떤 파일이 입력인지는 알 수 있다.

## 읽는 법

```python
import numpy as np, json, cv2
root = "samples/replica/generated"
occ   = cv2.imread(f"{root}/maps/office_4/map.png")[:, :, 0]                       # 255 = free
sem   = cv2.imread(f"{root}/maps/office_4/semantic_map.png")[:, :, 0]              # 0 empty 1 wall 2 window 3 door
poses = np.loadtxt(f"{root}/replica_f/office_4/poses.txt")                          # (8, 3) x y yaw  (샘플: 첫 8행)
d160  = np.loadtxt(f"{root}/replica_f/office_4/depth160.txt")                       # (8, 160) forward z-depth, m
dr    = cv2.imread(f"{root}/replica_f/office_4/depth_radial_scan/00000-3.png", -1)  # uint16 mm, radial
rir   = np.load(f"{root}/rir/replica_f/raw_scan_open/office_4/pose_00003/rir.npy")  # (6, n) 48 kHz
meta  = json.load(open(f"{root}/rir/replica_f/raw_scan_open/office_4/pose_00003/rir_metadata.json"))
desdf = np.load(f"{root}/desdf/office_4/desdf.npy", allow_pickle=True).item()      # {'l','t','desdf'(H,W,36)}
```

규약(좌표, 카메라, 단위, 채널 순서)은 `../ECHOLOC_DATA_GENERATION.md` §3과 각 `generated/dataset_meta.json`.
