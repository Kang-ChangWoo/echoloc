# echoloc_dataset / zind — Zillow Indoor Dataset floorplan-localization dataset (F3Loc 호환, + RIR)

ZInD(Zillow Indoor Dataset) 주택 1,575채를 **층 단위**로 F3Loc 형식으로 가져온 데이터셋.
구조·공통 규약은 `../README.md` 참조. 여기서는 ZInD 고유 사항만 적는다.
생성 코드는 `../../echoloc_simulator/build_zind.py`(임포트) + `verify_zind.py`(임포트 검증), 마무리 체인은 `logs/finish_zind.sh`.

## Replica·MP3D와 다른 점

1. **메시도 깊이도 없다.** ZInD는 집마다 `zind_data.json`(파노라마별 방 레이아웃 + 문·창·개구부 주석 + 층 도면으로 합치는 2D 변환)과
   파노라마 사진(2048×1024 equirectangular, 가구 있는 실제 집)만 준다. 새 포즈에서 렌더할 수 없고,
   음향은 `floorplan_closed` 조건만 존재하며(`raw_scan_open` 없음) `depth_radial_scan/`도 없다.
2. **RGB는 렌더가 아니라 파노라마 크롭이다.** 각 파노라마에서 그 파노라마의 방향(theta = 0)으로 480×640 핀홀 크롭을 잘라낸다
   (K: fx = fy = 240, **F_W = 3/8**, Replica/MP3D와 동일). 2048폭 파노라마에서 605×512 소스 픽셀이 들어오므로 거의 1:1이다.
   파노라마는 배포 상태에서 이미 수직 정렬돼 있어 roll·pitch = 0.
3. **단일 뷰(L = 0).** 포즈는 ZInD 파노라마 위치 그대로(`is_inside`인 것만). 청크 하나 = 프레임 하나, 파일명 `{step:05d}.png`.
4. **씬 = 층.** 씬 id는 `<집 4자리>_f<k>`(k = ZInD floor 번호). 한 집의 모든 층은 같은 split에 있다.
5. **카메라 높이가 프레임마다 다르다.** ZInD 좌표는 카메라 높이로 정규화돼 있어 실제 높이 = `floor_plan_transformation.scale ×
   scale_meters_per_coordinate`(중앙값 1.44 m). `chunks.json`의 `frames[].cam_z`에 있고, 음원/마이크도 같은 높이.
6. **시멘틱 지도가 있다.** ZInD가 문·창을 주석하므로 `maps/<scene>/semantic_map.png`(0 빈공간 / 1 벽 / 2 창 / 3 문, SemRayLoc 형식)를
   지도 장애물 껍질 위에 만들었다. 열어 둔 문은 자유 픽셀이라 문틀만 `door`로 남고, 현관·닫힌 문은 통째로 `door`, `openings`(문 없는 통로)는 라벨 없음.

| | 값 |
|---|---|
| 원본 | 1,575집 / 2,737층 / 파노라마 67,448장 (`/mnt/sdb/zind_raw`, Bridge API) |
| 씬(층) | **2,443** — `scale_meters_per_coordinate`가 없는 284층(미터 GT 불가, 추정치 대입 안 함)과 도면 실패 3·파노 1장 7층 제외 |
| split | train 1,948 / val 243 / test 252 — ZInD 공식 집 단위 partition(1,260/157/158집)을 층으로 확장 |
| 프레임 | **55,926** (is_inside 아님 3,362, 장애물 5 cm 이내 56 제외) |
| 카메라 높이 | p1 1.09 / 중앙값 1.44 / p99 1.70 m |
| 천장 | p1 2.14 / 중앙값 2.47 / p99 3.24 m (2.0–4.0 m로 클립) |
| 자유공간 | 층당 중앙값 100 ㎡, 합계 268,632 ㎡ |
| RIR | 55,926 포즈 × floorplan_closed, **링 6ch만**(binaural 없음), 48 kHz·20k rays·depth 50·회절 on |
| 용량 | ≈54 GB (RIR 34 GB) |

## 지도

`layout_raw`의 방 폴리곤을 ZInD 공식 변환(`v · R · scale + t`, `R = [[cos, sin], [−sin, cos]]`, 그 다음 × `scale_meters_per_coordinate`)으로
층 도면 미터 좌표에 놓고 0.05 m 격자에 그린 뒤 5배 업샘플한다.

- **자유공간 = 방 폴리곤들의 합집합**, 장애물 = 자유공간에 접한 셀 전부. 폴리곤 외곽선을 벽으로 그리지 **않는다**: 파노라마마다 방을
  독립 추정해 이웃 추정이 겹치므로, 외곽선을 그리면 옆방 안으로 벽이 찍힌다(측정: 광선의 50–60%가 자기 방 폴리곤보다 짧아짐).
  방 사이 벽은 폴리곤이 남긴 틈, 외벽은 합집합의 여집합이다.
- **문·개구부는 바닥까지 내려오는 것만 연다**(z_bottom ≤ −0.75 × 카메라 높이). 창은 벽. 바깥(외부)에 접하는 문은 열지 않는다
  (현관을 열면 외부가 장애물인 지도와 프록시가 어긋나고 광선이 밖으로 샌다).
- 문·창·개구부 주석은 **삼중항** `[끝점 a, 끝점 b, (z_bottom, z_top)]`이다. 쌍으로 읽으면 끝점과 z 범위가 섞여 가짜 선분이 생긴다.
- 프록시는 장애물 경계 셀 전부를 상자로 세우고(s3d와 동일) 바닥·천장 슬래브를 덮는다. 천장 = 층 파노라마들의 `ceiling_height` 중앙값.

## 검증 (`verify_zind.py`, 60씬 샘플)

- **yaw/지도 정합**: 자유공간이 방 폴리곤의 합집합이므로 파노라마에서 쏜 지도 광선은 자기 방 폴리곤보다 짧을 수 없다.
  4,296 광선 중 위반 **0**(yaw를 ±15° 틀면 11–18% 위반).
- **크롭 방향**: 크롭 픽셀을 ZInD 공식 `transformations.py` 투영과 비교, 오차 0.85/255 (좌우 반전 25.6, 상하 반전 23.3).
- **스케일**: 카메라·천장 높이가 물리적 범위 안(위 표).
- 이어서 `validate.py --ring-only` 전항목(depth·desdf·프록시 depth 무충돌·RIR 인덱스) — 결과는 `../../echoloc_simulator/logs/zind_validate.log`.

## 좌표 (ZInD 공식 `transformations.py` 기준으로 확인)

- 파노라마 방위각 theta = atan2(−x_room, y_room), 이미지 가로 중앙이 theta = 0; 고도 phi = asin(z/ρ), 세로 중앙이 phi = 0.
- 파노라마의 theta = 0 방향(방 +y)을 도면에 놓으면 `(−sin a, cos a)`(a = rotation) → 이것이 `poses.txt`의 yaw.
- world = 도면 미터, 원점 = 지도 중심; habitat = (x, z, −y)로 다른 데이터셋과 동일.
