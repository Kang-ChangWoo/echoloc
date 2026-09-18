# echoloc_dataset — F3Loc 호환 floorplan localization 데이터셋 4종 (+ RIR)

`dataset_generation_spec.md`(F3Loc + AV-FPLoc 음향 확장)를 네 소스에 적용한 결과물.
**데이터셋마다 폴더 하나**이고, 폴더 안 구조는 셋 다 동일하다. 생성 코드와 검증은 옆 폴더 `../echoloc_simulator/`.

```
echoloc_dataset/
├── dataset_generation_spec.md       요구 스펙 (원문, 공통)
├── replica/    Replica 17씬                       46 GB
├── mp3d/       Matterport3D 159 층씬 (83 건물)    173 GB
├── gibson/     Gibson 945 층씬 (489 건물)         372 GB
└── s3d/        Structured3D 700씬                 30 GB
```

데이터셋 폴더 하나의 내부 구조 (셋 다 동일):

```
<dataset>/
├── README.md                     그 데이터셋의 상세 문서
├── dataset_meta.json             기계 판독용 전역 메타데이터 (규약·카메라·지도·음향·시뮬레이터 버전·개수)
├── <collection>/                 F3Loc이 읽는 단위. data.root = 이 <dataset> 폴더
│   ├── split.yaml
│   └── <scene>/  rgb/ poses.txt depth40.txt depth160.txt map.png chunks.json
│                 depth_radial_scan/ depth_radial_floorplan/
├── maps/<scene>/                 map.png (0.01 m/px, 자유공간 255) + scene_meta.json
├── floorplan_proxy/<scene>/      map.png을 바닥→천장으로 압출한 watertight glb (floorplan_closed 음향 지오메트리)
├── desdf/<scene>/desdf.npy       test 씬만
└── rir/<collection>/<condition>/<scene>/pose_{index:05d}/
        rir.npy (6ch 링) · rir_binaural.npy + _rel{090,180,270} (2ch HRTF) · 각 metadata.json
```

## 네 데이터셋 비교

| | replica | mp3d | gibson | s3d |
|---|---|---|---|---|
| 씬 | 17 | 159 층씬 (83 건물) | 945 층씬 (489 건물) | 700 |
| split (train/val/test) | 11 / 3 / 3 | 131 / 16 / 12 | 795 / 81 / 69 | 400 / 50 / 250 |
| collection | replica_f, replica_g | mp3d_f, mp3d_g | gibson_f, gibson_g | s3d |
| 청크 | 4-view (L=3) | 4-view (L=3) | 4-view (L=3) | 단일 뷰 (L=0) |
| 프레임 | 20,400 ×2 | 65,780 ×2 | 246,212 ×2 | 15,872 |
| 카메라 | 480×640, HFOV 106.3°, F_W 3/8 | 동일 | 동일 | 640×360, HFOV 80°, **F_W 0.596** |
| 포즈 | navmesh 샘플링 | navmesh 샘플링 (층별) | navmesh 샘플링 (층별) | S3D 고정 카메라 위치 그대로 |
| 음향 조건 | raw_scan_open + floorplan_closed | 동일 | 동일 | **floorplan_closed만** (메시 없음) |
| RGB 출처 | habitat 렌더 (Replica 메시) | habitat 렌더 (MP3D 메시) | habitat 렌더 (Gibson 메시) | S3D 제공 렌더 (가구 포함) |
| 시멘틱 지도 | O | O | **X** (원본에 주석 없음) | O |

**F_W 주의**: s3d는 카메라 화각이 달라 `F_W = 0.596`이다. F3Loc config의 `F_W`를 데이터셋에 맞게 바꿔야 한다.

## 공통 규약

- **포즈**: 지도 좌표계의 글로벌 SE(2) `(x, y, yaw)`. 원점 = map.png 중심, yaw는 +x축 기준 반시계 라디안. 회전은 스칼라 하나(쿼터니언 아님).
- **map.png**: 0.01 m/px, 8-bit RGB 3채널 동일, 자유공간 = 255, 벽·외부 = 0. 벽만(가구 없음), 한 장이 한 층.
- **depth40 / depth160**: 지도에서 ray cast한 **카메라 전방 z-depth**(radial × cos), dist_max 20 m.
- **depth_radial_\***: 480×640(s3d는 640×360) **픽셀 radial depth**, 16-bit PNG mm, 0 = 미충돌. `_scan`은 실제 메시(또는 S3D 렌더), `_floorplan`은 프록시.
- **desdf**: `{"l","t","desdf"}`, 0.1 m/cell, 36 yaw bin, 10 m, float32.
- **RIR**: 48 kHz, indirect 20,000 rays·반사 50회·회절 on, 6ch 링(반경 5 cm, rel 0) + binaural(rel 0/90/180/270). 음원은 수신기와 같은 위치.
- **floorplan_closed**: 2D 벽 지도만 압출한 상자 메시. 가구·실제 메시 없음. 시각 GT와 정확히 같은 지오메트리.

자세한 내용·검증 결과·스펙과 다른 점은 각 데이터셋의 `README.md`와 `dataset_meta.json` 참조.

## 사용

```python
# F3Loc: configs 의 data.root 를 <dataset> 폴더로 (예: .../echoloc_dataset/replica)
import numpy as np, cv2
from PIL import Image
root = "replica"          # or "mp3d", "s3d"
col, scene = "replica_f", "office_4"
occ   = cv2.imread(f"{root}/{col}/{scene}/map.png")[:, :, 0]          # 255 = free
poses = np.loadtxt(f"{root}/{col}/{scene}/poses.txt")                  # (N, 3): x y yaw
d160  = np.loadtxt(f"{root}/{col}/{scene}/depth160.txt")               # (N, 160)
rir   = np.load(f"{root}/rir/{col}/raw_scan_open/{scene}/pose_00003/rir.npy")   # (6, n) 48 kHz
desdf = np.load(f"{root}/desdf/{scene}/desdf.npy", allow_pickle=True).item()
```
