# echoloc_simulator — `../echoloc_dataset` 생성·검증 파이프라인 (Replica / MP3D / Gibson / Structured3D)

`../echoloc_dataset/dataset_generation_spec.md`(F3Loc 호환 + AV-FPLoc 음향 확장)를 네 소스에 적용해 데이터셋을 만드는 코드.
데이터는 `../echoloc_dataset/<dataset>/`에만 쓰고, 이 폴더에는 코드·서드파티·로그·검증 부산물만 둔다.
데이터셋 형식은 `../echoloc_dataset/README.md`와 각 데이터셋의 `README.md`에 있다.

## 프로파일

`ECHOLOC_DATASET` 환경변수 하나로 세 데이터셋을 전환한다(기본 `replica`). `common.py`가 프로파일별 경로·카메라·split을 정한다.

| | replica | mp3d | gibson | s3d |
|---|---|---|---|---|
| 원본 | `/mnt/sdb/replica_raw` (`REPLICA_RAW_DIR`) | `/mnt/sdb/mp3d_raw` (`MP3D_MESH_DIR`) | `/mnt/sdb/gibson_raw/gibson` (`GIBSON_MESH_DIR`) | `/mnt/sdb/s3d_raw/Structured3D` (`S3D_RAW_DIR`) |
| 벽 마스크 | `floorplan_extraction/replica/` | `floorplan_extraction/mp3d_floors/` (층별) | `floorplan_extraction/gibson_floors/` (층별) | 없음 (주석에서 직접 생성) |
| collection | replica_f, replica_g | mp3d_f, mp3d_g | gibson_f, gibson_g | s3d |
| 씬 | 17 | 159 층씬 | 945 층씬 (489 건물) | 700 |
| 카메라 | 480×640, F_W 3/8 | 동일 | 동일 | 640×360, **F_W 0.596** |
| 청크 | 4-view (L=3) | 4-view (L=3) | 4-view (L=3) | 단일 뷰 (L=0) |
| 음향 조건 | raw_scan_open, floorplan_closed | 동일 | 동일 | floorplan_closed (메시 없음) |
| 시멘틱 지도 | O (per-face object id) | O (`.house` → mpcat40) | **X** (habitat 릴리스에 주석 없음) | O (annotation JSON) |
| 출력 루트 | `$ECHOLOC_DATA/replica` | `.../mp3d` | `.../gibson` | `.../s3d` |

## 구성

```
echoloc_simulator/
├── env.sh                 ss_v2 env + LD_PRELOAD + 경로·프로파일 환경변수 (실행 전 source)
├── run_all.sh             스테이지 오케스트레이션 (resume-safe, 프로파일에서 collection·조건을 읽음)
├── common.py              프로파일·상수·좌표 변환·habitat 시뮬레이터 (모든 규약의 단일 출처)
├── raycast.py             정확한 grid ray cast (Amanatides–Woo) + F3Loc 원본과의 self-test
├── build_maps.py          1  map.png / scene_meta.json / floorplan_proxy / split.yaml   (replica, mp3d)
├── build_s3d.py           1' Structured3D 전용 임포터: 지도·프록시·rgb·radial depth·포즈를 한 번에 (s3d)
├── sample_poses.py        2  4-view 청크 포즈 샘플링 → poses.txt, chunks.json          (replica, mp3d)
├── render_rgb.py          3  rgb/*.png (+ 검증용 depth 샘플)                            (replica, mp3d)
├── render_depth.py        3b depth_radial_scan/ · depth_radial_floorplan/ (16-bit PNG mm, radial)
├── make_depth_gt.py       4  depth40.txt / depth160.txt
├── make_desdf.py          5  desdf/<test scene>/desdf.npy
├── render_rir.py          6  rir/<collection>/<condition>/<scene>/pose_*/ (--layout ring|binaural)
├── validate.py            7  스펙 §6 체크리스트 + 수치 축 검증 + depth 맵 전수 조사
├── write_dataset_meta.py  8  <dataset>/dataset_meta.json
├── resample_and_wipe.py   (보조) 포즈 재샘플 후 바뀐 씬의 산출물만 삭제
├── patch_maps.py          (보조) 이미 만든 map.png에 사후 수정 적용
├── floorplan_extraction/  벽 마스크 추출기 + 결과
│   ├── build_floorplan.py          Replica용 (높이밴드 투표)
│   ├── build_floorplan_mp3d.py     MP3D용 (층 클러스터링 + 층별 밴드)
│   ├── build_floorplan_gibson.py   Gibson용 (navmesh 샘플 히스토그램 모드로 층 분리)
│   ├── replica/<scene>/            18씬 산출물
│   ├── mp3d_floors/<scene>_f<k>/   층별 산출물
│   └── gibson_floors/<scene>_f<k>/ 층별 산출물 (945)
├── third_party/f3loc/     felix-ch/f3loc clone — 원본 참조용, 수정 안 함
├── logs/                  스테이지별 로그 + 실행 스크립트(run_*.sh, fix_*.sh, sync_*.sh) + diag/
└── validation/            검증 부산물 (프록시/실제 depth 샘플, figs)   17 GB — 데이터셋 아님, 지워도 무방
```

## 실행

```bash
cd /mnt/sdb/soundspaces/echoloc/echoloc_simulator
source env.sh                              # $PY = ss_v2 python (LD_PRELOAD 포함)
export ECHOLOC_DATASET=replica             # 또는 mp3d / s3d

# replica, mp3d
./run_all.sh maps                          # 1
./run_all.sh poses 300                     # 2  (mp3d는 0 = 층 면적 비례 자동)
JOBS=4 ./run_all.sh rgb                    # 3  GPU
JOBS=4 ./run_all.sh depthmaps              # 3b GPU
WORKERS=12 ./run_all.sh depth              # 4
WORKERS=12 ./run_all.sh desdf              # 5
JOBS=6 THREADS=5 ./run_all.sh rir          # 6  링
LAYOUT=binaural JOBS=6 THREADS=5 ./run_all.sh rir   # 6b binaural
$PY write_dataset_meta.py                  # 8
./run_all.sh validate                      # 7

# s3d: 1~3b를 build_s3d.py 하나가 대신한다
ECHOLOC_DATASET=s3d $PY build_s3d.py
# 이후 depth / desdf / rir / validate 는 위와 동일
```

모든 스테이지는 이미 있는 산출물을 건너뛴다(재개 가능). `python raycast.py <scene>`은 ray caster self-test를 출력한다.

## RIR 설정

`common.py`: **48 kHz**, direct + indirect(**20,000 rays, 반사 50회**) + **edge diffraction on**(order 10), transmission off,
materials off(RLR Default: 흡음 0.10, 산란 0.5). 링은 마이크당 Mono 렌더(rel 0만), binaural은 RLR Binaural로 rel 0/90/180/270.
guard/usable은 스펙의 16/1024@8 kHz를 같은 시간으로 환산(96/6144).

스펙(8 kHz·4096 rays·깊이 6·회절 off·헤딩 1)과 다른 이유: NLOS에는 회절이 필요하고, 4096 rays는 같은 설정 재렌더 파형 상관이 0.74뿐이며,
샘플레이트·헤딩은 기존 replica_0422 렌더와 맞췄다. 반사 50회는 기본값 200과 에너지 분포가 같고 비용이 1/3이다.

## 검증 (validate.py)

스펙 §6의 1–7, 9, 10을 자동 체크하고, 8(포즈 재투영 육안 확인)은 두 가지로 대체한다.

- **수치 축 검증**: 프록시 glb를 실제 카메라로 렌더한 수평선 z-depth vs 지도 ray cast. 부호·축·F_W·z-depth 실수는 수십 cm로 드러난다.
- **depth 맵 전수 조사**: 프록시 depth에 무충돌 픽셀이 하나라도 있으면 실패(지도가 안 막힌 것). 스캔 무충돌은 보고만 하고
  `chunks.json`의 `scan_nohit_lower`와 일치하는지 확인한다.

## 스펙에서 의도적으로 벗어난 것

**F3Loc `ray_cast`를 쓰지 않는다.** 원본 DDA는 왼쪽/아래 스텝에서 `int()`가 나가는 픽셀을 가리켜 벽 블록의 꼭짓점 픽셀을 검사하지 않는다.
회전된 벽의 계단식 가장자리를 스치는 광선이 지도 밖까지 나가 dist_max로 기록됐다(광선의 0.27~0.43%). desdf도 같은 누수를 물려받으므로
`raycast.py`의 정확한 DDA를 GT·desdf·검증·포즈 샘플링에 일관되게 쓴다. 원본은 `third_party/f3loc`에 그대로 둔다.

## 함정 (다시 만들 때)

- habitat-sim 0.2.2는 `ss_v2` env에서 conda의 libstdc++·libz를 `LD_PRELOAD`해야 import된다(env.sh).
- Replica PTex 스테이지는 **시각 센서가 하나도 없으면** 죽는다. `common.make_sim`이 8×8 더미 depth 센서를 붙인다.
- 카메라 near plane은 **0.001 m**여야 한다. 기본 0.01은 벽에 1 cm 이내로 붙은 카메라(S3D에 흔함)에서 벽을 클리핑해 무충돌 픽셀을 만든다.
- `pathfinder.get_random_navigable_point()`는 habitat 내부 RNG라 `pathfinder.seed()`를 씬마다 줘야 한다.
- MP3D 층 클러스터링(간격 1 m)은 반층 구조를 별도 층으로 나눈다. 천장이 카메라보다 낮은 층은 빌더가 건너뛴다(`MIN_CEIL_MARGIN`).
- Gibson은 **간격 기반 층 클러스터링이 통하지 않는다**. 계단이 navigable이라 층들이 하나로 이어진다. 대신 navmesh 샘플 y 히스토그램의
  모드로 층을 잡는다(`PEAK_BIN`/`PEAK_MERGE`). 빌더는 씬을 나눠 실행할 것 — 한 프로세스에서 수백 씬을 돌리면 드물게
  `TypeError: 'float' object is not callable`로 한 씬이 죽는다(단독 재실행하면 정상).
- RLR에 다중 모노 배열 레이아웃이 없다. 마이크당 Mono 렌더로 6채널을 만든다.
- 긴 작업은 세션 메모리 감시에 죽을 수 있다. `logs/run_*.sh`처럼 `setsid nohup`으로 분리 실행할 것.
- NAS 동기화 스크립트를 겹쳐 띄우지 말 것(`--delete`가 다른 쪽이 쓰는 파일을 지운다).

## 확장

- **Gibson 시멘틱**: habitat trainval 릴리스는 `.glb` + `.navmesh`뿐이라 벽/문/창을 뽑을 근거가 없다. 3DSceneGraph(별도 배포)를 받으면
  객체 단위 주석이 생기지만 habitat 메시와 면 단위로 정렬돼 있지 않아 `make_semantic_map.py`를 그대로 쓸 수 없다.
- **S3D 가구 음향**: 메시가 없어 raw_scan은 불가능하지만, `bbox_3d.json`의 가구 바운딩 박스를 상자로 넣어 별도 조건을 만들 수는 있다.
- **RIR 전 프레임**: `render_rir.py --all-views` (기본은 reference frame만).
