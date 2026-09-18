# echoloc_dataset / replica — Replica floorplan-localization dataset (F3Loc-compatible, + 6ch RIR)

Replica 17씬을 F3Loc(Gibson Floorplan Localization Dataset) 형식으로 렌더한 데이터셋과,
같은 포즈에서 렌더한 6채널 링 마이크 RIR(AV-FPLoc용 음향 확장).
요구 스펙은 `../dataset_generation_spec.md`, 생성 코드와 검증은 옆 폴더 `../echoloc_simulator/`.

이 폴더에는 **데이터만** 있다. F3Loc 학습/평가 코드는 `data.root`를 이 폴더로 잡으면 수정 없이 읽는다.

```
echoloc_dataset/replica/             ~46 GB
├── dataset_meta.json                전역 메타데이터 (규약·카메라·지도·음향 설정·시뮬레이터 버전·개수), 기계 판독용
├── replica_f/                       collection 1 — forward motion            ~9.5 GB
│   ├── split.yaml
│   └── <scene>/
│       ├── rgb/{chunk:05d}-{view}.png   480×640 RGB, view 0..3 (3 = reference frame)
│       ├── poses.txt                    프레임당 "x y yaw"  (rgb 파일명 순서 = 행 순서)
│       ├── depth40.txt                  프레임당 40개 z-depth (m)
│       ├── depth160.txt                 프레임당 160개 z-depth (m)
│       ├── depth_radial_scan/{chunk:05d}-{view}.png       픽셀 radial depth, Replica 스캔 메시(가구 포함), 16-bit mm
│       ├── depth_radial_floorplan/{chunk:05d}-{view}.png  픽셀 radial depth, 벽만(floorplan_proxy), 16-bit mm
│       ├── map.png                      벽 지도 0.01 m/px (maps/<scene>/map.png과 동일)
│       └── chunks.json                  청크 종류·habitat 포즈·프레임별 scan_nohit_lower (추가 정보, F3Loc은 안 읽음)
├── replica_g/                       collection 2 — general motion (제자리 회전 포함)  ~9.5 GB
├── desdf/<scene>/desdf.npy          test 3씬                                   3 MB
├── rir/<collection>/<condition>/<scene>/pose_{index:05d}/
│   ├── rir.npy                                                    (6, n) float32, 48 kHz — 6-mic 링 (rel 0; mono 마이크라 방향성 없음)
│   ├── rir_metadata.json
│   ├── rir_binaural.npy  rir_binaural_rel{090,180,270}.npy         (2, n) float32, 48 kHz — RLR HRTF binaural, 머리 yaw = 카메라 yaw + rel
│   └── rir_binaural_metadata.json
├── maps/<scene>/
│   ├── map.png                      씬당 1개 (두 collection이 공유)
│   └── scene_meta.json              지도 크기·원점·habitat 변환·바닥 높이
└── floorplan_proxy/<scene>/floorplan.glb   map.png을 바닥→천장으로 압출한 watertight 메시
                                            (rir의 floorplan_closed 조건 지오메트리)
```

## 규모

| | replica_f | replica_g |
|---|---|---|
| 씬 | 17 | 17 |
| 청크 (4프레임) | 5,100 | 5,100 |
| 프레임 | 20,400 | 20,400 |
| RIR 포즈 (reference frame, 조건당; 포즈마다 링 6ch×1 + binaural 2ch×4헤딩) | 5,100 | 5,100 |

split (두 collection 동일, 서로소):

| split | 씬 |
|---|---|
| train (11) | frl_apartment_0 frl_apartment_1 frl_apartment_2 frl_apartment_3 hotel_0 office_0 office_1 office_2 room_0 room_1 room_2 |
| val (3) | apartment_1 frl_apartment_4 office_3 |
| test (3) | apartment_2 frl_apartment_5 office_4 |

apartment_0은 2층 스캔(바닥→천장 5.2 m)이라 단일 층 지도를 만들 수 없어 제외.

## 좌표와 포즈

- **포즈 = 지도 좌표계의 글로벌 SE(2) 포즈 (x, y, yaw)**. 상대 포즈 아님.
- x, y: 미터. 원점은 map.png의 중심. `x_map = x/0.01 + W/2`, `y_map = y/0.01 + H/2`, ray cast는 `occ[y_map, x_map]`.
- yaw: +x축 기준 반시계(CCW) 각도, 라디안, [−π, π]. roll = pitch = 0. 회전은 이 스칼라 하나이며 쿼터니언·행렬은 저장하지 않는다.
- 카메라 높이: navmesh 바닥 + 1.25 m (음원·마이크 링과 동일 위치). 높이는 `maps/<scene>/scene_meta.json`의 `floor_y_habitat`, 프레임별 habitat 좌표는 `chunks.json`의 `hab`(x, y, z)에 있다.
- habitat 좌표와의 관계: `x = habitat_x − cx`, `y = −habitat_z − cy`, `θ_habitat(+y축) = yaw − π/2`. cx, cy는 scene_meta.json.

## 카메라·지도·깊이

| 항목 | 값 |
|---|---|
| 카메라 | 480×640, K = [[240,0,320],[0,240,240],[0,0,1]], HFOV 106.26°, F_W = 3/8 |
| map.png | 8-bit RGB 3채널 동일, 0.01 m/px, **자유공간 = 255**, 벽·건물 외부 = 0. 5 cm 벽 마스크를 nearest로 5배 업샘플한 이진 지도 |
| depth40 / depth160 | 스펙 §3.4 각도 그리드, **카메라 전방 z-depth**(radial × cos), dist_max 20 m에서 포화(유한값 유지). F3Loc 학습용 1-D 구조 깊이 |
| depth_radial_scan / depth_radial_floorplan | 480×640 **픽셀 단위 radial depth**(각 픽셀 광선을 따른 유클리드 거리, cubemap/planar z 아님), 16-bit PNG, mm, 0 = 미충돌. scan = 실제 메시(가구 포함), floorplan = 벽만(map.png 압출 프록시). radial = z·√(1+((u+½−cx)/fx)²+((v+½−cy)/fy)²) |
| desdf | `{"l": int, "t": int, "desdf": float32 (H, W, 36)}`, 0.1 m/cell, 36 yaw bin(10°, CCW), 10 m 캐스트. `x_map = x_desdf·10 + l` |

벽 지도는 Replica 메시를 높이 밴드로 나눠 "모든 높이에서 solid한 셀"만 벽으로 투표한 것(가구·문 상인방 제거, 문은 열림), navmesh 외곽으로 스캔 구멍을 봉합했고, SoundSpaces 그래프 노드에서 flood-fill한 방만 자유공간이다. 같은 마스크를 압출한 `floorplan_proxy`가 음향 프록시라 시각 GT와 음향 프록시가 정확히 같은 방을 기술한다.

## 모션 (청크 구성)

| collection | 프레임 0→3 |
|---|---|
| replica_f | 전진: heading 방향으로 0.15–0.40 m/step, yaw 드리프트 N(0, 4°) ≤ 10° |
| replica_g | 40% 전진(yaw ±20°, 0.10–0.40 m) · 35% 제자리 회전(단조 10–35°/step, 이동 ~N(0, 2 cm)) · 25% 혼합(임의 방향 0–0.30 m, yaw ±35°) |

청크 종류는 `chunks.json`의 `kind`(forward / forward_g / rotate / mixed). 모든 포즈는 navmesh 위, 지도 자유 픽셀, 벽에서 ≥ 0.25 m, 연속 프레임 사이 직선이 벽을 지나지 않는다.

## Replica 스캔의 빈 영역 (알고 쓰기)

Replica 스캔 메시에는 스캔되지 않은 공간이 있다. frl_apartment_*는 천장이 없어 이미지 상단 ~20%가 항상 비고,
apartment_1/apartment_2는 문 너머 미스캔 공간이 커서 일부 포즈에서 화면 절반 이상이 검게 나온다(rgb 검정, depth_radial_scan = 0).
벽 지도와 depth40/160, depth_radial_floorplan은 봉합된 지도 기준이라 그 자리에 벽을 보고한다.
**포즈는 거르지 않고 전부 남겼다.** 대신 `chunks.json`의 프레임마다 `scan_nohit_lower`(이미지 120행 아래에서 스캔 무충돌 픽셀 비율)를
기록했으니 학습·평가 코드에서 원하는 임계값으로 제외하면 된다. 씬별 비율:

| 씬 | 프레임 절반 이상 무충돌 | 하단 75% 영역 15% 초과 무충돌 |
|---|---|---|
| apartment_2 (test) | 22% | 47% |
| apartment_1 (val) | 14% | 35% |
| office_2 | 1–2% | ~19% |
| office_3 | 0.2% | ~6% |
| frl_apartment_* | 0% | ~5–8% (천장 제외해도 창 등) |
| 나머지 | 0% | 0% |

```python
import json, numpy as np
ch = json.load(open("replica_f/apartment_2/chunks.json"))
nohit = np.array([fr["scan_nohit_lower"] for c in ch["chunks"] for fr in c["frames"]])   # (N,), 행 순서 = poses.txt
keep_chunks = [c["idx"] for c in ch["chunks"] if max(fr["scan_nohit_lower"] for fr in c["frames"]) <= 0.15]
```

## 음향 (rir/)

- 포즈: 각 청크의 **reference frame(view 3)**. `pose_<index>`는 해당 collection `poses.txt`의 행 번호(0-base). binaural은 포즈마다 **상대 헤딩 4개**(rel 0/90/180/270°, yaw_h = 카메라 yaw + rel, CCW), 링은 mono 마이크라 방향성이 없어 rel 0만. rel 0이 스펙 파일명(`rir.npy`, `rir_binaural.npy`), 나머지는 `rir_binaural_rel090` 등.
- 조건: `raw_scan_open`(Replica 스캔 메시 원본) / `floorplan_closed`(floorplan_proxy glb).
- 배열: 6 mic, 링 반경 0.05 m, 각도 [π, 4π/3, 5π/3, 2π, π/3, 2π/3] + yaw_h (채널 3 = 해당 헤딩 전방). 음원은 링 중심, 높이 1.25 m.
- 신호: **48 kHz**(스펙 8 kHz → 기존 replica_0422/house_traj 렌더와 맞춤), float32. `direct_peak_index` 뒤 guard 96샘플(2 ms), usable 6,144샘플(128 ms) — 스펙의 16/1024@8 kHz와 같은 시간 창. RLR indirect **20,000 rays·depth 50**(rays는 기존 replica_0422 렌더와 동일; depth 50은 기본값 200과 에너지 분포가 같고 비용 1/3), **모서리 회절 on**(order 10), transmission·materials off(RLR Default 재질: 흡음 0.10, 산란 0.5). 스펙의 4096 rays·depth 6·diffraction false를 의도적으로 바꿈: 4096에서는 같은 설정을 두 번 렌더해도 파형 상관이 ~0.74(광선 샘플링 잡음)이고, depth 6은 36 ms 이후 고차 반사(NLOS 경로)를 버린다. IR 길이는 ~0.4 s.
- `rir_metadata.json`에 포즈·채널 오프셋(habitat 좌표)·조건·시뮬레이터 설정을 전부 기록.
- **binaural**: 같은 포즈·같은 음원·같은 acoustics로 RLR 내장 HRTF binaural을 헤딩마다 렌더(채널 [left, right], 머리 yaw = yaw_h). direct 피크가 조금 늦게 오는 건 HRTF 지연. 메타는 `rir_binaural_metadata.json`.

## RIR 버전 이력

| 버전 | 설정 | 상태 |
|---|---|---|
| v1 (2026-09-08) | 8 kHz, 4096 rays, depth 6, **회절 off**, transmission off, 링 6ch만, 헤딩 1개, (6, 2049) | 스펙 §4.3 그대로. NLOS에 회절이 필요하다는 지적으로 폐기·**삭제됨** (NAS 사본도 최종본으로 덮어씀) |
| v2 (2026-09-09, 미완) | 8 kHz, 65,536 rays, depth 6, 회절 on | 샘플레이트·헤딩을 기존 렌더와 맞추기로 하면서 중단·삭제 |
| v3 (2026-09-09, 미완) | 48 kHz, 20,000 rays, depth 200, 링·binaural 각 헤딩 4개 | 비용(~36 h, ~300 GB) 대비 정보 이득 없어 중단·삭제 |
| **최종** (2026-09-09) | 48 kHz, 20,000 rays, depth 50, 회절 on(order 10), 링 6ch rel 0 + binaural 2ch rel 0/90/180/270 | 현재 `rir/` |

구버전과 최종본의 차이: 회절 유무(v1), 샘플레이트(v1·v2), 반사 횟수(v1·v2는 6, 최종 50), binaural·헤딩 유무. v1로 만든 결과와 비교할 때는 이 차이를 감안해야 한다.

## 검증 결과 (2026-09-08, 지도 봉합 수정 후 재생성본)

`../echoloc_simulator/validate.py` 기준, 34개 씬·collection 조합 전부 통과.

| 검사 | 결과 |
|---|---|
| 파일 수·정렬·청크 배수·split 서로소·map 이진성·깊이 유한/양수 | OK |
| 축 검증: 프록시 glb를 실제 카메라로 렌더한 수평선 z-depth vs map ray cast | 중앙값·평균 0.0 cm |
| depth160 vs 독립 ray march | p99 0.05 cm |
| depth_radial_floorplan 수평선 vs map ray 거리 (office_4) | 중앙값 0.03 cm |
| depth_radial_floorplan 무충돌 픽셀 (17씬 전 프레임) | 0 |
| desdf shape/dtype, RIR pose_index ↔ poses.txt | OK |

## 스펙과 다른 점

1. **ray cast 함수**: 스펙은 F3Loc `utils.ray_cast`를 그대로 쓰라고 하지만 그 DDA는 벽 블록 꼭짓점 픽셀을 건너뛰어 광선의 0.3~0.4%가 벽을 뚫고 20 m로 기록된다. 깊이 GT·desdf 모두 픽셀을 건너뛰지 않는 정확한 DDA(`../echoloc_simulator/raycast.py`)로 만들었다. 누수가 없는 광선에서는 원본과 ≤ 1.4 px 일치.
2. **씬 수**: 17 (스펙 목표 ≥ 60은 Replica 규모상 불가).
3. **RIR은 reference frame만** (스펙의 "evaluated pose" 해석). 전 프레임이 필요하면 simulator의 `render_rir.py --all-views`.
4. **RIR 회절 on, 20,000 rays, depth 50, 48 kHz, binaural 헤딩 4개**: 스펙 acoustics 블록은 `diffraction: false`, 4096 rays, depth 6, 8 kHz, 포즈당 1개지만 NLOS 데이터셋이라 회절을 켰고, rays·depth·샘플레이트·상대 헤딩 4개는 기존 Replica/MP3D 렌더(RLR 기본 depth)와 맞췄다.

## 사용

```python
# F3Loc: configs/visual_*.yaml 의 data.root 를 이 폴더로
# 직접 읽기
import numpy as np, cv2
from PIL import Image
occ   = cv2.imread("replica_f/office_4/map.png")[:, :, 0]        # 255 = free
poses = np.loadtxt("replica_f/office_4/poses.txt")               # (N, 3): x y yaw
d160  = np.loadtxt("replica_f/office_4/depth160.txt")            # (N, 160)
radial = np.array(Image.open("replica_f/office_4/depth_radial_scan/00000-3.png")).astype(np.float32) / 1000  # (480, 640) m
rir   = np.load("rir/replica_f/raw_scan_open/office_4/pose_00003/rir.npy")   # (6, n) 48 kHz; binaural: rir_binaural.npy, rir_binaural_rel090.npy ...
desdf = np.load("desdf/office_4/desdf.npy", allow_pickle=True).item()        # l, t, desdf
```
