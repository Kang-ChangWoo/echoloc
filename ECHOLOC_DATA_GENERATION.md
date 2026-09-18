# echoloc 데이터셋 생성 전과정 기록

F3Loc 호환 floorplan-localization 데이터셋 4종(Replica, Matterport3D, Gibson, Structured3D)에
AV-FPLoc 음향 확장(co-located 6-mic ring RIR)을 붙여 만든 전 과정의 기록이다.
코드는 `echoloc/echoloc_simulator/`, 데이터는 `echoloc/echoloc_dataset/`, 요구 스펙은
`echoloc/echoloc_dataset/dataset_generation_spec.md`.
이 문서는 "누가 처음부터 다시 만들어도 같은 결과가 나오도록" 쓰였다. 상수 하나까지 코드의 값을 그대로 옮겼고,
값이 코드에 있는 것은 어느 파일의 어느 상수인지 같이 적었다.

작업 기간: 2026-09-08 ~ 2026-09-19. 워크스테이션 `rvi-lab-w27` (RTX A6000 48 GB, 32 코어, 125 GB RAM, Ubuntu 22.04).

---

## 0. 한눈에 보기

| | replica | mp3d | gibson | s3d |
|---|---|---|---|---|
| 원본 | Replica v1 (`mesh_semantic.ply`) | MP3D habitat (`<id>.glb` + `.house` + `_semantic.ply`) | Gibson habitat trainval (`<id>.glb` + `.navmesh`) | Structured3D (`annotation_3d.json` + perspective/full 렌더) |
| 씬 단위 | 씬 | **층** (`<id>_f<k>`) | **층** (`<id>_f<k>`) | 씬 |
| 씬 수 | 17 | 159 층 / 83 건물 | 945 층 / 489 건물 | 700 |
| split (train/val/test) | 11 / 3 / 3 | 131 / 16 / 12 | 795 / 81 / 69 | 400 / 50 / 250 |
| collection | replica_f, replica_g | mp3d_f, mp3d_g | gibson_f, gibson_g | s3d |
| 청크 구조 | 4-view (L=3) | 4-view (L=3) | 4-view (L=3) | 단일 뷰 (L=0) |
| 청크/씬 | 300 고정 | 면적 비례 40–160 | 면적 비례 40–160 | 카메라 위치 그대로 |
| 프레임 (collection당) | 20,400 | 65,780 | 246,212 | 15,872 |
| 카메라 | 480×640, F_W 3/8 | 동일 | 동일 | 640×360, **F_W 0.596** |
| RGB 출처 | habitat 렌더 | habitat 렌더 | habitat 렌더 | S3D 제공 렌더 (가구 포함) |
| 음향 조건 | raw_scan_open + floorplan_closed | 동일 | 동일 | floorplan_closed만 |
| RIR 레이아웃 | ring + binaural×4 | ring + binaural×4 | **ring만** | ring + binaural×4 |
| 시멘틱 지도 | O | O | **X** (주석 없음) | O |
| 용량 / 파일 수 | 46 GB / 265,519 | 173 GB / 858,336 | 372 GB / 1,984,889 | 30 GB / 166,673 |
| 생성 완료 | 2026-09-11 | 2026-09-11 | 2026-09-18 | 2026-09-11 |
| validate | OK | OK | OK | OK |

추가로 **ZInD(Zillow Indoor)** 원본을 내려받아 두었다 (1,575집 / 2,737층 / 파노라마 67,448장 / 28 GB, `/mnt/sdb/zind_raw`). 데이터셋으로는 아직 만들지 않았다 (§12).

### 위치

| | 경로 |
|---|---|
| 저장소 | https://github.com/Kang-ChangWoo/echoloc (코드·문서·샘플) |
| 코드 | `/mnt/sdb/soundspaces/echoloc/echoloc_simulator/` |
| 데이터 | `/mnt/sdb/soundspaces/echoloc/echoloc_dataset/<dataset>/` |
| NAS 사본 1 | `/file1/changwoo/echoloc_dataset/`, `/file1/changwoo/echoloc_simulator/` (10.20.22.39, NFS) |
| NAS 사본 2 | `/file2/changwoo/echoloc_dataset/`, `/file2/changwoo/echoloc_simulator/` (10.20.22.41, NFS) |
| 원본 스캔 (로컬만) | `/mnt/sdb/replica_raw`, `/mnt/sdb/mp3d_raw`, `/mnt/sdb/gibson_raw/gibson`, `/mnt/sdb/s3d_raw/Structured3D`, `/mnt/sdb/zind_raw` |

NAS 두 곳의 `echoloc_dataset/` 파일 수는 2026-09-19 04:41 기준 로컬과 **정확히 일치** (누락 0). 원본 스캔은 다른 데이터셋과 동일하게 NAS에 올리지 않았다.

---

## 1. 실행 환경

| 항목 | 값 |
|---|---|
| conda env | `ss_v2` (`~/miniconda3/envs/ss_v2`), Python 3.9.25 |
| habitat-sim | **0.2.2** (SoundSpaces 2.0 빌드, `libRLRAudioPropagation.so` 포함), 소스 `~/workspace/habitat-sim` |
| sound-spaces | `~/workspace/sound-spaces` (참조만) |
| 음향 백엔드 | RLRAudioPropagation (habitat_sim AudioSensor) |
| numpy / scipy / trimesh / pillow / opencv | 1.26.4 / 1.13.1 / 4.11.5 / 11.3.0 / 4.11.0 |
| GPU | RTX A6000, driver 580.173.02. rgb·depth 렌더는 GPU, RIR·ray cast·desdf는 CPU |
| F3Loc 참조 구현 | `echoloc_simulator/third_party/f3loc` (felix-ch/f3loc clone, 수정 없음, 규약 참조 + S3D 유틸 import 용) |

**`env.sh`를 반드시 source한 뒤 `$PY`로 실행한다.** habitat-sim 0.2.2는 conda의 `libstdc++.so.6`과 `libz.so.1`을 `LD_PRELOAD`하지 않으면 import 시 세그폴트가 난다. `env.sh`가 이것과 `ECHOLOC_DATASET`, `ECHOLOC_DATA`, `REPLICA_RAW_DIR`를 잡아준다.

```bash
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator
source env.sh                      # $PY = ss_v2 python -u (LD_PRELOAD 포함)
export ECHOLOC_DATASET=gibson      # replica | mp3d | gibson | s3d
```

프로파일 전환은 환경변수 `ECHOLOC_DATASET` 하나다. `common.py`가 프로파일별 원본 경로, 벽 마스크 경로, collection 이름, 카메라, split을 결정하고 **모든 스테이지가 `common.py`의 값만 읽는다** (규약이 한 곳에만 있어야 스테이지끼리 어긋나지 않는다).

---

## 2. 폴더 구조

```
/mnt/sdb/soundspaces/echoloc/       ← git repo 루트 (코드·문서·샘플만 추적, 데이터는 .gitignore)
    ├── README.md                       짧은 안내
    ├── ECHOLOC_DATA_GENERATION.md      ← 이 문서
    ├── samples/<dataset>/{raw,generated}/   씬 하나씩의 실제 파일 (라이선스 허용 범위, samples/README.md)
    ├── echoloc_dataset/
    │   ├── README.md                       4종 비교·공통 규약·사용 예
    │   ├── dataset_generation_spec.md      요구 스펙 (원문)
    │   ├── supplementary_datasets.tex      논문 supplementary 초안 (3종; Gibson 열 미반영)
    │   └── <dataset>/                      replica | mp3d | gibson | s3d
    │       ├── README.md                   데이터셋 고유 사항
    │       ├── dataset_meta.json           기계 판독용 전역 메타 (규약·카메라·음향·시뮬레이터·개수·스펙 이탈 목록)
    │       ├── <collection>/               F3Loc이 읽는 단위 (data.root = <dataset>)
    │       │   ├── split.yaml
    │       │   └── <scene>/  rgb/  poses.txt  depth40.txt  depth160.txt  map.png  chunks.json
    │       │                 depth_radial_scan/  depth_radial_floorplan/
    │       ├── maps/<scene>/               map.png (0.01 m/px) + scene_meta.json (+ semantic_map.png, semantic_legend.json)
    │       ├── floorplan_proxy/<scene>/    floorplan.glb (+ stage/scene_dataset config) = map.png을 압출한 watertight 상자
    │       ├── desdf/<scene>/desdf.npy     test 씬만
    │       └── rir/<collection>/<condition>/<scene>/pose_{index:05d}/
    │               rir.npy  rir_metadata.json  [rir_binaural.npy  rir_binaural_rel{090,180,270}.npy  rir_binaural_metadata.json]
    └── echoloc_simulator/
        ├── env.sh  run_all.sh  common.py  raycast.py
        ├── build_maps.py  sample_poses.py  render_rgb.py  render_depth.py  make_depth_gt.py
        ├── make_desdf.py  render_rir.py  validate.py  write_dataset_meta.py
        ├── build_s3d.py  make_semantic_map.py  qc_render.py  zind_download.py
        ├── resample_and_wipe.py  patch_maps.py                     (보조)
        ├── floorplan_extraction/
        │   ├── build_floorplan.py  build_floorplan_mp3d.py  build_floorplan_gibson.py
        │   ├── mp3d_scene_split.json  gibson_scene_split.json
        │   └── replica/  mp3d_floors/  gibson_floors/               벽 마스크 산출물 (git 제외)
        ├── logs/    *.sh 오케스트레이션 스크립트 (추적) + *.log (git 제외)
        ├── validation/   검증 부산물 67 GB (git 제외, 지워도 됨)
        └── third_party/f3loc/   (git 제외; clone해서 넣을 것)
```

---

## 3. 공통 규약 (모든 데이터셋 동일)

### 3.1 좌표계

- **월드 프레임**: 2D, 원점 = `map.png` 중심, x 오른쪽, y 위, 단위 m. yaw는 +x축 기준 반시계(CCW) 라디안, `[-π, π]`.
- **map 픽셀**: `row = y/0.01 + H/2`, `col = x/0.01 + W/2` (`common.world_to_map`). `occ[row, col]`. F3Loc 규약 그대로(row = y). 그리므로 `origin='lower'`.
- **habitat ↔ 월드**: habitat는 y-up, 전방 −z.
  `x = habitat_x − world_cx_habitat`, `y = −habitat_z − world_cy_habitat_neg_z`,
  `habitat_theta (about +y) = yaw − π/2`. 씬별 오프셋 `world_cx_habitat`, `world_cy_habitat_neg_z`는 `maps/<scene>/scene_meta.json`.
- **trimesh(z-up) ↔ habitat**: glb를 z-up으로 authoring해서 그대로 export하면 habitat importer가 X축 −90° 회전을 적용해 `habitat = (tx, tz, −ty)`. 프록시·S3D·Gibson 모두 이 규약으로 검증됐다.
- **포즈**: `poses.txt` 한 줄 = 한 프레임 `x y yaw`, 전체 정밀도, 순서 = rgb 파일명 순서. **글로벌 SE(2), 상대 포즈 아님, 쿼터니언 없음.** roll = pitch = 0 (S3D만 예외, §8.4).
- **높이**: 카메라 = 음원 = 마이크 링 중심 = navmesh 바닥 + **1.25 m** (`common.CAM_HEIGHT`). 프레임별 habitat xyz는 `chunks.json → chunks[i].frames[v].hab`.

### 3.2 카메라

| | replica / mp3d / gibson | s3d |
|---|---|---|
| 해상도 | 480×640 | 360×640 (1280×720 축소) |
| K | `[[240,0,320],[0,240,240],[0,0,1]]` | `[[381.4,0,320],[0,408.2,180],[0,0,1]]` |
| HFOV | 106.26° | 80.0° |
| **F_W = fx/W** | **3/8** | **0.596** |
| 렌더 | habitat 핀홀, near **0.001 m** | S3D 제공, gravity-align |

F3Loc config의 `F_W`는 데이터셋에 맞게 바꿔야 한다. near plane 0.001은 기본 0.01이 벽에 1 cm 이내로 붙은 카메라(S3D에 흔함)에서 벽을 클리핑해 무충돌 픽셀을 만들기 때문이다.

### 3.3 map.png

- 0.01 m/px. 8-bit RGB 3채널 동일 (`[:, :, 0]`으로 읽음). **자유공간 = 255, 벽·건물 외부 = 0.** 이진.
- 0.05 m 벽 마스크를 nearest로 ×5 업샘플 (`common.UPSAMPLE`). 벽 두께 = 1 셀 = 5 cm.
- 벽만 있고 가구 없음. **한 장 = 한 층**. 문은 열려 있음(§5.1의 이유). 창은 벽.
- `close_diagonal_leaks()`: 대각선으로만 맞닿은 벽 픽셀 코너를 채워 4-연결로 만든다 (F3Loc DDA 누수 방지, §5.3). 채운 픽셀 수는 `scene_meta.json → diagonal_corner_px_filled`.
- `floorplan_proxy/<scene>/floorplan.glb`는 **같은 마스크를 바닥→천장으로 압출**한 watertight 상자 메시(바닥·천장 슬랩 포함). 시각 GT와 `floorplan_closed` 음향이 정확히 같은 지오메트리를 본다.

### 3.4 depth40.txt / depth160.txt (F3Loc GT)

스펙 3.4 그대로, 단 ray caster만 교체:
```
center_angs = flip(arctan2(u − u.mean(), ray_n · F_W)),  u = 0..ray_n−1
depth_i = ray_cast(occ, [row, col], center_angs[i] + yaw, dist_max = 20/0.01) · 0.01 · cos(center_angs[i])
```
**카메라 전방 z-depth**(radial × cos). dist_max 20 m에서 포화(유한값 유지). `make_depth_gt.py`.

### 3.5 depth_radial_scan / depth_radial_floorplan (픽셀 depth 맵)

- 16-bit PNG, **mm**, 0 = 무충돌. rgb와 같은 이름·카메라.
- habitat DEPTH 센서는 z-depth를 주므로 **radial**로 변환:
  `radial = z · sqrt(1 + ((u+0.5−cx)/fx)² + ((v+0.5−cy)/fy)²)` (`render_depth.radial_factor`).
  정면 3 m 벽과 이미지 모서리의 3 m 벽이 둘 다 3000으로 읽힌다.
- `_scan` = 실제 스캔 메시(가구 포함), `_floorplan` = 프록시. S3D는 `_scan`이 S3D 제공 depth.png(planar, mm)를 radial로 바꾼 것.
- 요청 사항: "둘 다 만들어서 넣어, radial로, cubemap z value로 넣지 말고" (2026-09-08).

### 3.6 desdf

`{"l": int, "t": int, "desdf": float32 (H, W, 36)}` m 단위. 0.1 m/cell, 36 yaw bin (o·10°, CCW), 10 m까지 캐스트. `map.png`의 자유공간 bbox(+20 px)를 crop해서 계산: `x_map = x_desdf·10 + l`, `y_map = y_desdf·10 + t`. **test 씬만** 생성. `make_desdf.py`, 36 방향을 워커 풀에 분배.

### 3.7 청크

- L = 3: 청크 = 4 프레임 `{chunk:05d}-{view}.png`, view 3이 reference frame. `len(poses) % 4 == 0`.
- `chunks.json`: `collection, scene, L, seed, cam_height_m, n_chunks, kinds, scan_hole_filter, chunks[]`.
  `chunks[i] = {idx, kind, frames[4]}`, `frames[v] = {x, y, yaw, hab[3], theta, scan_nohit_lower}`.
- S3D는 L = 0: 프레임 하나가 청크 하나, `{step:05d}.png`.

### 3.8 split

train / val / test 셋 다 둔다 (val 필요, 2026-09-15 결정). F3Loc 원저자 배포본은 test만 있어 참고만 했다.

| | 근거 |
|---|---|
| replica | OAA 실험의 off3 split. val/test 서로소 3씬씩. `apartment_0` 제외(2층 스캔, 단일 도면 불가) |
| mp3d | `matterport3d_0303renew/scene_split.json` (건물 72/9/9) → 층으로 확장. 한 건물의 층은 전부 같은 split |
| gibson | 공식 fullplus split. trainval 릴리스에 test 씬이 없어 **공식 val을 반으로 갈라 val/test**. 층으로 확장 |
| s3d | 표준: id 0–2999 train, 3000–3249 val, 3250–3499 test (추출된 700씬으로 제한) |

`split.yaml`은 각 collection 폴더에, `SPLIT`은 `common.py`. `validate.py`가 서로소를 확인한다.

---

## 4. 원본 데이터 확보

| 데이터셋 | 어떻게 | 로컬 |
|---|---|---|
| Replica | 연구실 NAS `/file1/rvi/dataset/replica/raw` 복사 (43 GB). `replica.scene_dataset_config.json`이 z-up→y-up 변환 | `/mnt/sdb/replica_raw` |
| MP3D | NAS `/file1/rvi/dataset/matterport/sound-spaces/data/scene_datasets/matterport/mp3d` 복사. `.glb`, `.navmesh`, `.house`, `_semantic.ply` | `/mnt/sdb/mp3d_raw` |
| Gibson | 스탠퍼드 라이선스 폼 제출 후 받은 URL로 `gibson_habitat_trainval.zip` + `gibson_habitat.zip` 다운로드 (492 씬 `.glb` + `.navmesh`). **폼 제출은 사용자가 직접** (에이전트가 법적 동의를 대신할 수 없다고 판단) | `/mnt/sdb/gibson_raw/gibson` |
| Structured3D | NAS `/file1/rvi/dataset/Structured3D`의 `perspective_full` zip + `annotation_3d.json` 추출 (700씬) | `/mnt/sdb/s3d_raw/Structured3D` |
| ZInD | Bridge Data Output API (§12.2) | `/mnt/sdb/zind_raw` |

---

## 5. 벽 마스크 추출 (stage 0)

세 스캔 데이터셋(Replica, MP3D, Gibson)은 메시에서 벽 마스크를 뽑아야 한다. `floorplan_extraction/build_floorplan*.py`. 출력은 씬(층)마다:
`occupancy.png`(벽), `interior.png`(봉합된 자유공간), `floorplan.glb`(압출 프록시) + stage/scene_dataset config, `floorplan.json`(origin, grid, z 밴드), `floorplan_map.png`, `leak_diagnostic.png`.

### 5.1 높이 밴드 투표 (세 빌더 공통)

머리 높이에서 자르면 소파·테이블이 벽으로 들어온다. 천장 바로 밑에서 자르면 가구는 빠지지만 **문 상인방(lintel)**이 들어와 모든 문이 막힌다 → 방끼리 음향적으로 완전히 격리된 상자가 되어 버린다. 그래서:

- **벽 = 모든 높이에서 solid한 셀.** 바닥+0.35 m부터 천장−0.20 m까지 0.20 m 간격 밴드(`BAND_BOTTOM/TOP/STEP`)마다 `|normal_z| < 0.35`(`MAX_WALL_NZ`)인 삼각형을 0.05 m 격자에 top-down 래스터화. 밴드별 점유를 평균 내어 **0.60 이상**(`BAND_FRACTION`)만 벽. 벽은 ~1.0, 가구·상인방은 ~0.3.
- 바닥/천장 높이는 z 분포의 2/98 백분위(`WALL_PCTL`).
- `CLOSE_RADIUS = 3` 셀 morphological closing으로 스캔 구멍 봉합.
- **외곽 봉합**: 스캔에는 창·미스캔 코너로 구멍이 있어 소리가 새어 나간다. navmesh를 채우고 팽창한 것(=건물 외피)과 스캔 footprint(어떤 높이든 지오메트리가 있는 셀, `FOOTPRINT_CLOSE = 5`)의 교집합 경계에 벽 링을 두른다. 격자는 `MARGIN_M = 1.0` 패딩(링이 격자 밖으로 나가던 room_0/room_2 버그의 수정).
- **자유공간 = 외피 안의 시드(SoundSpaces 그래프 노드 또는 navmesh 샘플)에서 flood-fill한 영역**. 외피 밖 시드(apartment_1/2의 실외 노드)는 무시.
- 벽 셀을 바닥→천장 상자로 압출 + 바닥/천장 슬랩 → `floorplan.glb` (trimesh z-up authoring).

### 5.2 층 분리

MP3D와 Gibson은 한 씬이 건물 전체라 "한 지도 = 한 층" 요구를 만족하지 못한다. 층마다 `<id>_f<k>`(k=0 최하층)로 나눈다. **한 건물의 모든 층은 같은 지도 프레임(원점·크기)**을 공유하고 z 밴드만 다르다.

| | mp3d (`build_floorplan_mp3d.py`) | gibson (`build_floorplan_gibson.py`) |
|---|---|---|
| 시드 | SoundSpaces 그래프 노드 | navmesh 무작위 샘플 4,000개 (`N_SAMPLES`) |
| 층 클러스터링 | 노드 높이 **간격 > 1.0 m** (`FLOOR_GAP`)면 새 층 | **높이 히스토그램 모드** (`PEAK_BIN` 0.10 m, `PEAK_FRAC` 0.02, 모드 간 `PEAK_MERGE` 0.60 m 이내 병합, 샘플은 모드 ±`FLOOR_BAND` 0.50 m 소속) |
| 왜 다른가 | 그래프 노드는 계단에 없어 간격이 생김 | **Gibson은 계단이 navigable**이라 높이가 연속 → 간격 클러스터링이 건물 전체를 한 덩어리로 묶음 |
| z 밴드 | `[floor − 0.1, min(floor + 2.7, next − 0.1)]` | 동일 (`FLOOR_HEIGHT` 2.7) |
| 스킵 | 노드 < 4, 실내 < 8 m², 천장이 카메라(1.25)+0.15 m 미만 (`MIN_CEIL_MARGIN`) | 샘플 < 40 (`MIN_SAMPLES`), 실내 < 8 m², 천장 여유 동일 |
| 결과 | 83 건물 → 165 층 → **159** (천장 낮은 6층 제외) | 492 씬 → 945 층 / 489 건물 (천장 낮아 101층, 8 m² 미만 10층 스킵; 3씬은 층 0개) |

Gibson 층 분포: 1층 173, 2층 188, 3층 115, 4층+ 12 건물. 층 높이 1.50–2.80 m (중앙값 2.80).

### 5.3 정확한 ray cast (`raycast.py`) — F3Loc 원본을 쓰지 않는 이유

F3Loc `utils.ray_cast`의 DDA는 경계 이벤트마다 `occ[int(row), int(col)]`를 검사하는데, 왼쪽/아래로 이동하는 스텝에서는 도착 좌표가 정수 경계라 `int()`가 **떠나는** 픽셀을 가리킨다. 벽 블록의 꼭짓점 픽셀을 스치는 광선은 그 픽셀을 검사하지 않고 통과한다. 회전된 벽의 계단식 가장자리에서 스치는 광선은 블록마다 이 짓을 반복해 지도 밖까지 나간다. 실측: frl_apartment_0의 depth160 광선 **0.27%**(씬에 따라 0.43%)가 3 m 앞 벽을 뚫고 dist_max(20 m)를 보고. desdf도 같은 누수를 물려받는다.

`raycast.py`는 Amanatides–Woo 순회로 광선이 지나는 **모든** 픽셀을 순서대로 검사한다. 시그니처는 F3Loc과 동일. F3Loc이 새지 않는 곳에서는 ≤1 px 이내로 일치 (`selftest()`). 원본은 `third_party/f3loc`에 그대로 두고, **depth GT·desdf·검증·포즈 샘플링 전부 이 구현을 쓴다.** F3Loc 원본과 비교하면 `python raycast.py <scene>`.

---

## 6. 스테이지별 파이프라인 (`run_all.sh`)

모든 스테이지는 **이미 있는 산출물을 건너뛴다**(재개 가능). 긴 작업은 세션 메모리 감시에 죽을 수 있어 `setsid nohup ... &`로 분리 실행 (`logs/run_*.sh` 참고).

```bash
./run_all.sh maps                          # 1
./run_all.sh poses 300                     # 2  (mp3d/gibson은 0 = 면적 비례 자동)
JOBS=4 ./run_all.sh rgb                    # 3  GPU
JOBS=4 ./run_all.sh depthmaps              # 3b GPU
WORKERS=12 ./run_all.sh depth              # 4  (gibson_g는 12워커에서 세그폴트 → 6으로 재개)
WORKERS=12 ./run_all.sh desdf              # 5
JOBS=6 THREADS=5 ./run_all.sh rir          # 6  ring
LAYOUT=binaural JOBS=6 THREADS=5 ./run_all.sh rir   # 6b binaural
$PY write_dataset_meta.py                  # 8
./run_all.sh validate [--ring-only]        # 7
# s3d: 1~3b를 build_s3d.py 하나가 대신함:  ECHOLOC_DATASET=s3d $PY build_s3d.py
```

### 6.1 stage 1 `build_maps.py` — map.png + scene_meta.json + 프록시 복사

`interior.png`(봉합된 자유공간)를 읽어 ×5 업샘플 → `map.png`. **다시 flood-fill하지 않는다**(빌더가 한 봉합을 그대로 믿음). `close_diagonal_leaks` 적용. `floorplan.glb`와 config를 `floorplan_proxy/<scene>/`로 복사. `split.yaml` 기록.
`scene_meta.json` 키: `map_res_m, map_w, map_h, src_cell_m, origin_xy_trimesh, world_cx_habitat, world_cy_habitat_neg_z, z_floor_mesh, z_ceiling_mesh, room_height_m, cam_height_m, free_area_m2, wall_cells_src, diagonal_corner_px_filled, axis_convention, base_scene, floor_index, n_floors_in_scene, node_y_habitat{min,median,max}, floor_y_habitat, navmesh_on_free_fraction, navmesh_bounds_habitat`.
`navmesh_on_free_fraction` = 봉합된 자유공간 중 navmesh가 실제 덮는 비율. Gibson 평균 0.994, 0.90 미만 16층, 0.50 미만 2층(Gratz_f0 0.38, Fedora_f0 0.45). 포즈는 navmesh에서만 뽑으므로 지도 오류가 아니라 포즈가 몰리는 것뿐.

### 6.2 stage 2 `sample_poses.py` — 4-view 청크

포즈는 **habitat navmesh에서 뽑고**(`pathfinder.get_random_navigable_point`, 씬마다 `pathfinder.seed()` 필수 — habitat 내부 RNG) **동시에 map.png로 검사**한다. 프레임 하나가 통과하려면:

1. map 픽셀이 자유공간(255)
2. 가장 가까운 벽 픽셀까지 **≥ 0.25 m** (`MIN_CLEARANCE`, distance transform)
3. `snap_point`가 수평 3 cm(`SNAP_XY_TOL`), 수직 0.30 m(`MAX_Y_DELTA`) 이내 — 다른 층으로 튀지 않음
4. `is_navigable(p, 0.5)`
5. **층 천장 규칙** (mp3d·gibson): `navmesh_y + 1.25 > z_ceiling − 0.15`면 거부. 반층 계단참에 카메라가 놓이면 천장 위로 올라간다. 처음엔 mp3d에만 걸려 있었고 gibson/Pinesdale_f2에서 터져서(§10) 2026-09-17에 gibson으로 확대.
6. 연속 프레임 사이 직선이 벽을 지나지 않음 (`segment_free`, ray cast)
7. 실제 스캔을 그 포즈에서 렌더해 **120행 아래 무충돌 비율**을 `scan_nohit_lower`로 기록. `HOLE_MAX = None` → **거부하지 않고 기록만** (2026-09-08 결정: 모든 포즈 유지, 하류에서 필터).

동작 regime (`step()`):

| kind | collection | 이동 |
|---|---|---|
| `forward` | *_f | step U(0.15, 0.40) m 헤딩 방향, yaw 드리프트 N(0, 4°) clip ±10° |
| `forward_g` | *_g 40% | yaw U(−20°, 20°), step U(0.10, 0.40) m |
| `rotate` | *_g 35% | 제자리 회전 단조 U(10°, 35°)/step, 위치 N(0, 0.02) m |
| `mixed` | *_g 25% | step U(0, 0.30) m 헤딩 ±60° 내 임의 방향, yaw U(−35°, 35°) |

청크 수: replica 300 고정. mp3d/gibson `--n-chunks 0` → `clip(round(free_area_m2 × 0.6), 40, 160)` (`AUTO_DENSITY/MIN/MAX`). 시드 = 씬 인덱스 기반(재현 가능). Gibson 결과: collection당 61,553청크, 씬당 최소 40·중앙값 50·최대 160, 하한 걸린 365씬·상한 51씬, 1,890 씬-collection에서 거부된 청크 합계 23.

### 6.3 stage 3 `render_rgb.py` — rgb + 검증용 depth 샘플

habitat 핀홀 COLOR 센서, `CAM_HEIGHT` 오프셋, `chunks.json`의 `hab`/`theta`로 에이전트 배치. 부수적으로 `--val-every`(기본 25) 프레임마다 실제 메시와 프록시의 z-depth를 `validation/<col>/<scene>/depth_{real,plan}/{frame:05d}.npy`에 남긴다 → `validate.py`의 축 검사 입력. **이미 있으면 건너뛰므로 씬을 재샘플링했으면 `validation/<col>/<scene>/`도 지워야 한다** (§10 Pinesdale_f2 두 번째 실패의 원인).
Replica PTex: 시각 센서가 하나도 없으면 "submesh ID 0 out of range"로 죽는다 → `make_sim`이 8×8 더미 depth 센서를 붙인다.
Gibson 처리량: 초당 51프레임(JOBS=4, GPU 2%… 씬 로딩이 병목), 492,424프레임 2시간 37분.

### 6.4 stage 3b `render_depth.py` — radial depth 맵 ×2 지오메트리

§3.5. `geom='real'`(스캔)과 `'plan'`(프록시) 각각 렌더. 무충돌 = 0. Gibson 984,848파일 1시간 51분.

### 6.5 stage 4 `make_depth_gt.py` — depth40/160

§3.4. 씬당 프로세스 하나, 프레임을 워커 풀에. 포화 광선: replica 0%, mp3d <0.01%, gibson 0.0000%(1/20 표본), s3d 0%.

### 6.6 stage 5 `make_desdf.py`

§3.6. test 씬만: replica 3, mp3d 12, gibson 69, s3d 250.

### 6.7 stage 6 `render_rir.py` — 음향 확장

**한 RIR = 한 평가 포즈 = 청크의 reference frame(view 3)** 기본 (`--all-views`로 전 프레임 가능). `pose_<index>`는 `poses.txt`의 행 번호 → 시각·음향이 행 인덱스로 결합. `rir_metadata.json`의 `f3loc_pose_m_rad`가 그 행과 일치하는지 validate가 확인.

**배열**: 6 mic, 반경 0.05 m, 각도 `[π, 4π/3, 5π/3, 2π, π/3, 2π/3] + yaw` (채널 3 = 각도 2π + yaw = 카메라 전방). habitat 오프셋 `[r cos a, 0, −r sin a]` (−sin은 `y_f3loc = −z_habitat`). 음원 = 링 중심, 높이 1.25 m (co-located, active sensing). **RLR에 다중 모노 배열 레이아웃이 없어** 채널마다 Mono 렌더를 따로 한다: 수신기를 마이크 위치로 옮기고 음원 고정 → `rir.npy (6, n)`. binaural은 RLR 내장 HRTF Binaural 렌더 한 번 → `(2, n)`, 머리 yaw = 카메라 yaw + rel.

**조건**:
- `raw_scan_open` — 실제 스캔 메시 그대로 (구멍·열린 경계 포함)
- `floorplan_closed` — `floorplan_proxy/<scene>/floorplan.glb` (시각 GT와 같은 지오메트리)
둘의 쌍이 "음향-시각 이득이 진짜 지오메트리에서 오는지, 메시 아티팩트인지"를 가른다. S3D는 메시가 없어 후자만.

**파라미터** (`common.py`, 최종 2026-09-09):

| | 값 | 스펙 | 이유 |
|---|---|---|---|
| sample rate | **48,000 Hz** | 8,000 | 기존 replica_0422 / house_traj 렌더와 맞춤 |
| indirect rays | **20,000** | 4,096 | 4,096에서는 같은 설정 재렌더 파형 상관이 0.74뿐 (16k 0.83, 65k 0.91) |
| ray depth (최대 반사) | **50** | 6 | depth 6은 ~36 ms 이후 반사를 전부 버림. 50은 RLR 기본 200과 에너지 분포 동일(99%가 ~53 ms 내, 128 ms 창 밖 0.3%)에 비용 1/3 |
| diffraction | **ON**, order 10 | off | 이 데이터셋은 NLOS가 핵심. 사용자: "diffraction 왜 없앴냐" (2026-09-09). RLR에서 비용 중립 |
| transmission / materials | off / off (RLR Default: 흡음 0.10, 산란 0.5) | 동일 | Replica에 재질 정의가 없고, 한 데이터셋만 재질을 쓰면 비교 불가 |
| binaural headings | rel 0/90/180/270 | 1 | 기존 렌더와 동일. ring은 rel 0만(모노 마이크는 지향성이 없어 회전한 링이 같은 원을 다시 샘플링할 뿐) |
| guard / usable | 96 / 6,144 samples | 16 / 1,024 @8 kHz | 같은 시간(2 ms / 128 ms)을 48 kHz로 환산 |

RIR 길이 n은 포즈마다 다르다(RLR이 에너지가 빠지면 잘라냄). Gibson 실측 17,463–48,202 샘플(0.36–1.0 s), 중앙값 26,621. `rir_metadata.json`에 `direct_peak_index`(채널별도), `channel_offsets_habitat_m`, `acoustics{...}`, `channel_order` 기록. 스펙 4.4의 경고("링 회전 = 방 회전, 나중에 못 잡는다")대로 채널 순서와 yaw-zero를 메타에 고정.

**버전 이력** (`dataset_meta.json → rir_version_history`): v1 스펙 그대로(8 kHz, 4096, depth 6, 회절 off) → 폐기·삭제. v2 8 kHz 65,536 rays → 중단. v3 48 kHz depth 200 → 36시간/300 GB 예상, 정보 이득 없어 중단. **final** 위 표.

Gibson ring: 246,212개(= 61,553 × 2 collection × 2 조건), 15시간 10분 (JOBS=6 THREADS=5 = 30 스레드, 시간당 ~15,400개). binaural은 **사용자 결정으로 제외**(2026-09-16, "binaural은 하지마 일단"); 나중에 `LAYOUT=binaural ./run_all.sh rir`만 돌리면 ring 결과는 건너뛰고 binaural만 추가된다.

### 6.8 stage 7 `validate.py`

스펙 §6 체크리스트 1–7, 9, 10을 자동화하고 8(육안 재투영)은 두 수치 검사로 대체. `RESULT: OK`가 아니면 실패 목록 출력, exit 1.

**장부 검사**: map 3채널 동일·이진·255 존재 / poses 3열, `len % (L+1) == 0`, yaw ∈ [−π, π] / rgb 개수·이름 순서 = poses / 모든 포즈가 자유 픽셀 / depth40·160 형상 (n, 40)·(n, 160), 유한·양수·≤ dist_max / split 서로소, 씬 폴더 존재 / desdf: test 씬마다, `l/t` int, `(H, W, 36)` float32 / rir: pose_<index> 메타의 포즈 = poses.txt 행, ring 완비, binaural 완비 (`--ring-only`면 binaural 전무는 보고만, **일부만 있으면 여전히 실패**).

**check 9 — 독립 재유도**: depth160을 ray caster와 코드를 공유하지 않는 0.05 px 스텝 march와 비교. p99 < 0.016 m이고 march가 GT보다 짧은 광선 0.

**축 검사 (axis check)**: 프록시를 실제 핀홀 카메라로 렌더한 **수평선 행(239/240)의 z-depth** vs 같은 포즈·컬럼 각도에서의 map ray cast. 부호·축 교환·F_W·z/radial 혼동이 있으면 수십 cm로 드러난다. 기준 median < 5 cm, mean < 15 cm.

**depth 맵 검사**: 12프레임에서 `depth_radial_floorplan` vs map range |diff| median < 1 cm(planar를 radial로 잘못 저장했는지), 16-bit 크기, **프록시 depth 무충돌 픽셀 == 0**.

**전수 zero survey**: **모든** 프레임의 floorplan depth에 0 픽셀이 하나라도 있으면 실패 ("map not sealed"). 프록시가 watertight이고 지도가 봉합됐으면 있을 수 없다. 이 검사가 잡아낸 것: 봉합 링이 격자 밖으로 나간 지도(room_0/2), near plane 클리핑(S3D), 계단참 위 카메라(Gibson Pinesdale_f2). 스캔 무충돌은 **보고만** 하고 `chunks.json`의 `scan_nohit_lower`와 0.02 이내 일치하는지 확인.

**결과 요약** (모두 `RESULT: OK`, 실패 0):

| | replica | mp3d | gibson | s3d |
|---|---|---|---|---|
| 축 검사 median | 0.0 cm | 0.0 cm | 0.0 cm (1,890 씬-collection 평균) | 0.0 cm |
| check 9 p99 | 0.05 cm | 0.05 cm | ≤ 0.05 cm | — |
| 프록시 무충돌 프레임 | 0 | 0 | 0 / 492,424 | 0 |
| 스캔 void >15% 프레임 비율 | apartment_2 ~47%, apartment_1 ~35% | 씬 중앙값 3.8%, 318 중 5 씬-col >90% | 평균 6.9%, 최대 100% | 평균 13% 무충돌(제공 depth의 빈 곳) |

### 6.9 stage 8 `write_dataset_meta.py`

`dataset_meta.json`: 이름·설명·생성일·규약(좌표·카메라·map·depth·desdf)·동작 파라미터·음향 설정 전체·시뮬레이터 버전·F3Loc commit·**실측 개수**·RIR 버전 이력·**스펙 이탈 목록과 이유**. 프로파일별 분기(mp3d/gibson/s3d). 2026-09-19에 gibson 분기가 없어 Replica 설명이 들어가 있던 결함을 발견·수정·NAS 반영.

### 6.10 `qc_render.py` — 완결성 검사 (2026-09-16 추가)

`validate.py`보다 가볍고 전수: 씬마다 rgb / depth_radial_scan / depth_radial_floorplan 파일 수 = poses 행 수 (**한 프레임만 빠져도 행 정렬이 깨짐**), 표본 씬에서 rgb 크기·검은 프레임, 프록시 무충돌 픽셀, 스캔 무충돌 비율. 945씬 규모에서 조용히 지나가는 산발 실패(§10 Portal_f1)를 잡으려고 만들었고, 기존 세 데이터셋에도 돌려 미완 씬 0을 확인했다.

### 6.11 `make_semantic_map.py` — 시멘틱 도면 (SemRayLoc 형식)

SemRayLoc(Grader & Averbuch-Elor, ICCV 2025, arXiv:2507.09291)의 `F ∈ {0,…,C}^(H×W)` 형식. `maps/<scene>/semantic_map.png` (uint8 3채널 동일, **0 empty / 1 wall / 2 window / 3 door**) + `semantic_legend.json`(라벨표·출처·클래스별 픽셀 수).

- **map.png은 절대 수정하지 않는다.** `semantic_map != 0`인 집합 == `map.png != 255`인 집합. 어느 쪽으로 ray cast해도 같은 픽셀에서 멈추므로 기존 depth GT 유효. "기존 floorplan에 덮어 씌우지 않도록" (2026-09-15).
- 모든 장애물 픽셀은 `wall`로 시작, 주석이 창/문을 두는 곳만 덮어씀(문을 나중에 → 문 옆 창은 문이 이김).
- **"시멘틱은 벽에만 있으면 된다"**: 창/문 라벨은 자유공간을 마주보는 **표면 3 px**(`SHELL_PX`)에만 둔다. 처음엔 라벨이 외부 덩어리 안으로 번졌다.
- 출처: replica `mesh_semantic.ply` 면별 object id → `info_semantic.json` 101클래스 / mp3d `<id>_semantic.ply` 면별 object id → `.house`의 C/O 레코드 → mpcat40 (semantic ply와 glb가 같은 좌표계임을 검증) / s3d `annotation_3d.json` 문·창 폴리곤. 근수직 면(`MAX_WALL_NZ` 0.35)만, 층 밴드 안만, 0.05 m 격자에 투영 후 `DILATE_CELLS` 2.
- `CATEGORIES = {window, blinds, curtain → WINDOW; door → DOOR}`, `EXCLUDE = (shower,)`. frl_apartment의 창이 `blinds`/`curtain`으로 주석돼 있어 alias 추가(`--strict`로 끔).
- 문은 지도에서 **열린 상태**이므로 `door` 라벨은 장애물 집합에 속한 문 표면(외부 문, 닫힌 문짝, 개구부 옆 문설주)에만 붙는다.
- 검증(2026-09-17, 876씬 전수): 크기 불일치 0, 자유공간 라벨 0, 미라벨 장애물 0, 표면 밖 창/문 픽셀 0. 장애물 픽셀 중 창/문 비율: replica 0.30/0.35%, mp3d 0.14/0.18%, s3d 0.47/0.27%. 창 없는 씬 mp3d 9·s3d 23, 문 없는 씬 mp3d 3·s3d 1 (원본 주석 그대로).
- **Gibson은 불가**: habitat 릴리스에 `.glb`+`.navmesh`뿐, 면별 주석이 없다. 3DSceneGraph는 habitat 메시와 면 단위로 정렬돼 있지 않아 그대로 못 쓴다.
- 같은 투영으로 다른 레이어(가구 footprint, 방 종류)도 만들 수 있다 — `CATEGORIES`만 바꾸면 된다.

---

## 7. Structured3D 임포터 (`build_s3d.py`)

S3D는 메시가 없다. 씬마다 `annotation_3d.json`(벽/바닥/천장 평면, 정션 mm z-up)과 고정 카메라 위치의 perspective 렌더(`rgb_rawlight.png` 1280×720, `depth.png` uint16 mm, `camera_pose.txt`). 한 스크립트가 stage 1~3b를 대신한다.

- **지도**: 방 바닥 폴리곤(F3Loc이 LASER에서 빌린 `s3d_utils.read_s3d_floorplan`)을 0.05 m 격자에 래스터화 → 자유공간, 벽 1셀(5 cm), 방 밖 전부 0. `LINE_4` 벽 그리기.
- **문**: **방과 방 사이 문만 연다.** 외부 여부는 닫힘+채움 footprint로 판정(닫힌 방 마스크). 외부 문과 창은 벽으로 둔다. 문을 열지 않으면 방끼리 음향 결합이 사라진다.
- **프록시**: 벽 선만이 아니라 **모든 장애물 경계 셀**을 0..천장으로 압출 + 슬랩. 벽 선만 쓰면 3–4 cm 어긋났다.
- **카메라**: `camera_pose.txt`의 xfov/yfov(반각 0.698/0.441 rad) → `K640 = [[320/tan xfov, 0, 320],[0, 180/tan yfov, 180],[0,0,1]]` → **F_W 0.596**. yaw/pitch/roll은 view·up 벡터에서 F3Loc `viewmap_s3d.py`와 같은 식으로. rgb와 depth를 F3Loc `utils.gravity_align`으로 정렬(roll·pitch 제거, `chunks.json`에 원값 보존).
- **depth_radial_scan**: 제공 depth.png(planar z, 검증됨)를 1280×720 내부 파라미터로 radial 변환 후 정렬·축소.
- **좌표**: 월드 `x = X/1000 − cx`, `y = Y/1000 − cy`. 프록시 z-up authoring → `habitat = (X, Z, −Y)`. `hab.y = camera_z − CAM_HEIGHT`(1.5)로 저장해 렌더러의 고정 오프셋이 센서를 정확히 S3D 카메라 높이에 놓는다.
- **near plane 문제**: S3D 카메라가 벽에 1 cm 이내로 붙은 경우가 많아 기본 near 0.01에서 벽이 클리핑돼 무충돌 픽셀 발생 → `near = 0.001`로 내리고, 그래도 **2 cm 미만(`MIN_CLEARANCE`) 프레임 243개는 스킵** (193씬 재빌드).
- 결과 700씬 / 15,872프레임 / test 250 desdf. `raw_scan_open` 없음, 단일 뷰(L=0).

---

## 8. 데이터셋별 특이사항

### 8.1 Replica
- 17씬. `apartment_0` 제외(5.2 m 높이 2층 스캔).
- frl_apartment_*는 천장 스캔이 없다 → `scan_hole` 검사가 120행 아래만 본다(`HOLE_ROW0`). apartment_1/2는 문 뒤에 미스캔 공간 → `scan_nohit_lower`로 기록.
- 초기 봉합 버그: room_0/room_2는 링이 bbox 밖(→ `MARGIN_M`), apartment_1/2는 실외 노드에서 flood-fill이 외부로 샘(→ 외피 ∩ footprint, 외피 안 시드만).

### 8.2 Matterport3D
- 83건물(그래프 메타데이터 있는 것) → 159층. 층 클러스터링·스킵 규칙 §5.2. 6층은 천장이 카메라보다 낮아 제외했는데 그 결과 `poses.txt`가 빈 4개 씬이 validate를 죽여서 validate를 방어적으로 고치고 해당 층을 뺐다.
- 스캔 void >90%인 3층이 있다(보고만, 결정 보류).
- 2026-09-16 README 수치가 옛 값(165 / 133·17·15 / 16,763 / 67,052)이었던 것을 실측(159 / 131·16·12 / 16,445 / 65,780)으로 정정.

### 8.3 Gibson
- 타임라인(2026-09-16 → 09-18): 층 빌드 00:37–00:41(누적) → maps 02:19–02:22 → poses 02:23–02:35 → rgb 02:35–05:12 → depthmaps 05:12–07:03 → depth 07:03–07:41 세그폴트, 12:49–13:17 재개 → desdf 13:18–13:29 → ring RIR 13:29 → 09-17 04:39 → validate 04:39–07:06 (3,781 실패: binaural 3,780 + Pinesdale_f2) → 복구 13:48 → 재검증 15:20–17:29 (stale 부산물 1건) → 최종 validate 09-18 14:37–17:01 **OK**.
- 통계: 실내 면적 min/median/max 9.7 / 83.9 / 1,762.6 m², 합계 108,907 m². 지도 폭 555 / 1,555 / 7,895 px. 씬당 프레임 160 / 200 / 640. 층 높이 1.50–2.80 m.
- 층 9개가 높이 < 1.75 m (Pinesdale_f2 1.50이 최소). 카메라 여유 규칙에 걸리지 않을 만큼만 남긴 것이라 마진이 작다.
- **시멘틱 없음, binaural 없음** (위).
- 규모 추정이 맞았다: 사전 계산 61,553청크 → 실제 61,553.

### 8.4 Structured3D
§7. roll/pitch가 0이 아니므로 이미지·depth는 정렬본, 원값은 `chunks.json`. 카메라 높이 프레임별(~1.2–1.7 m).

---

## 9. 스펙(`dataset_generation_spec.md`) 대비 의도적 이탈

1. ray cast: F3Loc `utils.ray_cast` 대신 정확한 DDA (§5.3).
2. RIR: 48 kHz / 20,000 rays / depth 50 / **회절 on** / binaural 4헤딩 (스펙 8 kHz / 4,096 / 6 / off / 1). 이유 §6.7.
3. RIR은 reference frame만 (`--all-views`로 전체 가능).
4. 카메라 높이 1.25 m = 음원 높이 (co-location).
5. Replica 17씬 (스펙 ≥ 60). mp3d 159·gibson 945·s3d 700으로 보완.
6. mp3d/gibson: 씬 = 층, 청크 수 면적 비례(고정 300 아님).
7. s3d: F_W 0.596, 단일 뷰, floorplan_closed만.
8. gibson: binaural 없음.
9. 스캔 void 프레임을 버리지 않고 `scan_nohit_lower`로 표시.

---

## 10. 발생한 문제와 해결 (시간순)

| 날짜 | 문제 | 원인 | 조치 |
|---|---|---|---|
| 09-08 | Replica PTex "submesh ID 0 out of range" | 시각 센서 없이 로드 | `make_sim`이 8×8 더미 depth 센서 추가 |
| 09-08 | depth160 광선 0.27–0.43%가 벽 통과 | F3Loc DDA 꼭짓점 누수 | `raycast.py` 정확한 DDA, 전 스테이지 교체 |
| 09-08 | room_0/2 봉합 안 됨, apartment_1/2 외부로 샘 | 링이 격자 밖 / 실외 시드 | `MARGIN_M`, 외피∩footprint, 외피 안 시드, `interior.png`를 build_maps가 소비 |
| 09-09 | RIR 스펙값이 NLOS에 부적합 | 회절 off, 4096 rays | 회절 on, 20k rays, depth 50, 48 kHz, 헤딩 통일 (측정: 상관 0.74→0.83→0.91) |
| 09-10 | S3D 프록시 무충돌 픽셀 | near 0.01 클리핑 + 벽 1 cm 이내 카메라 | `near=0.001`, <2 cm 프레임 243개 스킵 |
| 09-10 | S3D 문/외부 판정, 프록시 3–4 cm 어긋남 | 벽 선만 압출 | 닫힘+채움 footprint, 모든 장애물 경계 셀 압출 |
| 09-11 | MP3D 천장 낮은 층 | 클러스터링 밴드 얇음 | `MIN_CEIL_MARGIN`, 6층 제외, 빈 poses 씬 방어 |
| 09-11 | fix_mp3d가 ALL DONE 찍고 validate 출력 없음 | 체인 오류 | 완료를 성급히 보고한 것을 사용자 질문으로 발견, 재검증 |
| 09-12 | file2/mp3d에 rsync 두 개 경합(`--delete`) | 스크립트 중복 실행 | 하나 kill. **동시 rsync 금지** 규칙 |
| 09-13 | 데이터셋 간 maps/desdf가 최상위에 섞임 | 초기 구조 | 데이터셋별 폴더로 재구성(로컬·NAS) |
| 09-15 | 시멘틱 라벨이 외부 덩어리로 번짐 | 팽창 무제한 | `SHELL_PX` 3 표면만 |
| 09-15 | Replica 창 0 | `blinds`/`curtain` 주석 | alias + `--strict` |
| 09-15 | Gibson 층이 하나로 뭉침 | 계단 navigable → 간격 없음 | 히스토그램 모드 클러스터링 |
| 09-15 | Gibson 층 빌드가 매번 조기 종료 | 래퍼가 로그 덮어쓰고 오류 필터 | 25씬 청크 + append 로그. 218씬 4분에 완료 |
| 09-16 | Timberon `TypeError: 'float' object is not callable` | 한 프로세스에 수백 씬, 상태 오염(미특정) | 단독 재실행 정상 |
| 09-16 | gibson_g depth 세그폴트 217/945 | 워커 12 산발 | 워커 6 재개, 재현 안 됨 |
| 09-16 | Portal_f1 depth 렌더 실패 | habitat import 중 torch meta-registration 경쟁 | 단독 재실행. `qc_render.py` 도입 |
| 09-17 | validate 3,781 실패 | binaural 미렌더(의도) 3,780 + **Pinesdale_f2 4프레임 상반부 무충돌** | `--ring-only` 추가; 천장 규칙을 gibson으로 확대, 재샘플링(112 거부) |
| 09-17 | 복구 후 축 검사 32.8 cm | `validation/` 부산물이 옛 포즈 | 부산물 삭제·재생성 → 0.0 cm. 복구 절차에 명시 |
| 09-17 | NAS 전송 37시간 예상 | **유선 down, Wi-Fi(16–27 MB/s)**, NFS 파일당 왕복 | 씬 단위 병렬 rsync 8워커: 626 → 4,541 파일/분 |
| 09-17 | ZInD 이미지 HTTP 202 | CloudFront WAF 챌린지(워커 16) | 워커 4, 요청 간격, 202 시 풀 전체 120 s 후퇴. 35분 뒤 해제 |
| 09-19 | gibson `dataset_meta.json`이 "Replica…" | `write_dataset_meta.py`에 gibson 분기 없음 | 분기 추가, 재생성, NAS 반영 |

---

## 11. 스토리지 운용

- 스크립트: `logs/sync_gibson_par.sh` (병렬, `TARGET=/file2/changwoo WORKERS=8`), `logs/sync_code.sh`(코드; validation/logs/third_party .git 제외), `logs/sync_semantic.sh`, `logs/verify_final.sh`(로컬 vs NAS 파일 목록 comm 대조).
- **원칙**: 같은 트리에 rsync를 겹쳐 띄우지 않는다. 병렬 스크립트는 워커가 자기 씬만 보므로 `--delete`를 쓰지 않는다(트리 전체 삭제를 걸면 서로 지운다). 부분 렌더 중인 폴더는 올리지 않는다(어디까지 온전한지 구분 불가).
- 전송 완료 후 `verify_final.sh`로 누락 0 확인 (2026-09-19). 발견한 것: `/file1`의 replica/mp3d/s3d에 `semantic40.txt` 1,052개(`root` 소유, 09-17 01:51)가 있다. **다른 세션(av_localization)의 작업물**(포즈별 40방향 광선 시멘틱 라벨, `(N, 40)` ∈ {0,1,2})이라 지우지 않았고 `/file2`·로컬에는 없다.
- 상대 세션이 "Gibson이 509 MB뿐, 복사 중단"이라 판단한 적이 있는데(09-16), 전송 실패가 아니라 **아직 생성되지 않은 것**을 안 올린 상태였다. 상대 세션은 원본 메시가 없는 것도 지적했으나 `raw_scan_open`은 이 서버에서 렌더하므로 필요 없다.

---

## 12. 남은 일

### 12.1 미완
- `supplementary_datasets.tex`에 Gibson 열 추가 (표 4개, §Limitations의 thin storey 문장 갱신).
- Gibson binaural (원하면 `LAYOUT=binaural ./run_all.sh rir`, ~1.5일, ~318 GB).
- MP3D 스캔 void >90% 3층 처리 결정, sdb 휴지통 1,012 GB.

### 12.2 ZInD (원본만 확보)
- 규모: 1,575집, 2,737층, 22,485방, 파노라마 67,448장(0.46 MB 평균), 층 도면 이미지 2,737장, 메타 JSON ~280 MB. 총 28 GB. 층 수 분포 1/2/3/4/5층 = 632/736/196/10/1 집.
- 접근: Bridge Data Output API `https://api.bridgedataoutput.com/api/v2/OData/zgindoor/Indoor/replication`, `Authorization: Bearer <Server Token>`. **전체를 한 요청으로 받으면 30 s에 408** → `$top=50` + `@odata.nextLink`로 32페이지 (공식 `zillow/zind download_data.py`는 이 처리가 없어 실패). 이미지는 CloudFront+AWS WAF 뒤 → `zind_download.py`(워커 4, `PACE` 0.15 s, 202 감지 시 `WAF_BACKOFF` 120 s 풀 정지, md5 검증, 페이지 캐시, 재개 가능). 토큰은 `ZIND_SERVER_TOKEN` 환경변수로만(파일에 없음; 이 폴더는 NAS로 미러됨). 9시간 23분, 실패 0.
- 레이아웃은 공식 배포본과 동일: `<home_id>/zind_data.json`, `panos/<floor>_<partial_room>_<pano>.jpg`, `floor_plans/<floor>.png`.
- 데이터셋화 시 성격: **S3D형**(메시 없음 → `floorplan_closed`만, 파노라마 크롭으로 RGB, 카메라 파라미터 별도 정의). 대신 벽 폴리곤에 `doors`/`windows` 리스트가 있어 **시멘틱은 바로 가능**. `scale_meters_per_coordinate`가 집(층)마다 달라 미터 스케일 검증 단계 필요. 2,737층은 4종 중 최대.

---

## 13. 파일 인덱스 (echoloc_simulator)

| 파일 | 역할 |
|---|---|
| `env.sh` | ss_v2 + LD_PRELOAD + 경로 환경변수. 실행 전 source |
| `run_all.sh` | 스테이지 오케스트레이션, 프로파일에서 collection·조건 읽음, resume-safe |
| `common.py` | **규약의 단일 출처**: 프로파일, 상수, 좌표 변환, `make_sim`, split |
| `raycast.py` | 정확한 grid ray cast + F3Loc 원본과 self-test |
| `build_maps.py` | 1: map.png / scene_meta.json / 프록시 복사 / split.yaml |
| `build_s3d.py` | 1′: S3D 임포터 (지도·프록시·rgb·radial depth·포즈 한 번에) |
| `sample_poses.py` | 2: 4-view 청크 포즈 샘플링 |
| `render_rgb.py` | 3: rgb + 검증용 depth 샘플 |
| `render_depth.py` | 3b: radial depth 맵 (scan / floorplan) |
| `make_depth_gt.py` | 4: depth40/160 |
| `make_desdf.py` | 5: desdf (test) |
| `render_rir.py` | 6: RIR ring / binaural, 두 조건 |
| `validate.py` | 7: 검사 스위트 (`--ring-only`) |
| `write_dataset_meta.py` | 8: dataset_meta.json |
| `make_semantic_map.py` | 시멘틱 도면 (replica/mp3d/s3d) |
| `qc_render.py` | 렌더 완결성 전수 검사 |
| `zind_download.py` | ZInD 다운로더 (페이징·WAF·md5·재개) |
| `resample_and_wipe.py`, `patch_maps.py` | 보조: 재샘플 후 산출물 삭제, 지도 사후 수정 |
| `floorplan_extraction/build_floorplan.py` | Replica 벽 마스크 |
| `floorplan_extraction/build_floorplan_mp3d.py` | MP3D 층별 벽 마스크 |
| `floorplan_extraction/build_floorplan_gibson.py` | Gibson 층별 벽 마스크 (navmesh 샘플) |
| `floorplan_extraction/{mp3d,gibson}_scene_split.json` | 건물 split |
| `logs/run_*.sh, fix_*.sh, sync_*.sh, verify_final.sh` | 실제로 실행한 오케스트레이션·복구·전송 스크립트 (재현용) |

---

## 14. 다시 만들 때 함정 (요약)

1. `env.sh` 없이 habitat import → 세그폴트.
2. Replica: 시각 센서 없으면 PTex 로드 실패.
3. `near = 0.001`. 기본값이면 벽에 붙은 카메라에서 무충돌 픽셀.
4. `pathfinder.seed()` 씬마다. 안 하면 재현 불가.
5. F3Loc `ray_cast`를 쓰지 말 것 (누수).
6. 층 데이터셋은 천장 규칙(`navmesh_y + 1.25 ≤ z_ceil − 0.15`) 필수.
7. 씬을 재샘플링하면 `validation/<col>/<scene>/`도 지울 것 (`render_rgb.py`가 있으면 건너뜀).
8. 수백 씬을 한 프로세스에서 돌리지 말 것(Gibson 빌더 산발 TypeError). 청크로 나누고 append 로그.
9. 워커 수: `make_depth_gt` 12에서 산발 세그폴트, 6은 정상.
10. rsync 겹쳐 띄우지 말 것. 병렬 스크립트에 `--delete` 넣지 말 것.
11. 이 워크스테이션은 Wi-Fi(유선 down). 대용량 전송은 병렬로, 다운로드와 동시에 하지 말 것.
12. `pkill -f <script>`는 자기 셸까지 죽인다. PID로 kill.
13. 크리덴셜은 환경변수로만. 이 코드 폴더는 NAS로 미러된다.
