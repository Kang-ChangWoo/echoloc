# echoloc_dataset / gibson — Gibson floorplan-localization dataset (F3Loc 호환, + RIR)

Gibson(habitat trainval 릴리스) 건물을 **층 단위 씬**으로 나눠 F3Loc 형식으로 렌더한 데이터셋.
구조·규약은 `../README.md`와 `../replica/README.md`가 설명하는 것과 같고, 여기서는 Gibson 고유 사항만 적는다.
요구 스펙은 `../dataset_generation_spec.md`, 생성 코드는 `../../echoloc_simulator/`.

F3Loc이 평가에 쓴 "Gibson Floorplan Localization Dataset"과 **같은 원본 환경이지만 다른 데이터셋**이다.
저자 배포본은 테스트용 `gibson_f`/`gibson_g`/`gibson_t`만 담고 있고, 이쪽은 같은 규약으로 전 씬을 다시 렌더해
train/val/test를 모두 만든 것이다.

## 씬 id = 층

| | 값 |
|---|---|
| 원본 씬 | 492 (`.glb` + `.navmesh`) |
| 층씬 | 945 (`<건물>_f<k>`, k = 0이 최하층) |
| 건물 | 489 (3개 씬은 층이 하나도 살아남지 못함) |
| split | train 795 / val 81 / test 69 (official fullplus split의 건물 split을 층에 상속) |
| 청크 | 층 면적 비례 (m²당 0.6개, 40–160), collection당 61,553 |
| 프레임 | collection당 246,212 (청크 × 4뷰) |

건물당 층 수는 1층 173, 2층 188, 3층 115, 4층 이상 12개다.

- 한 건물의 모든 층은 **같은 지도 좌표계**(같은 원점·크기)를 쓴다. 층별 z 밴드는 `maps/<id>/scene_meta.json`.
- 카메라(1.25 m)가 설 수 없는 층 101개와 봉합 실내 면적 8 m² 미만인 층 10개는 제외했다.

## 층 분리가 MP3D와 다른 이유

MP3D는 그래프 노드 높이의 **간격**(1 m 초과 = 새 층)으로 층을 갈랐다. Gibson에서는 이 방법이 통하지 않는다.
계단이 navigable이라 층 사이 높이가 연속적으로 이어져 건물 전체가 한 덩어리로 묶인다.
대신 navmesh 샘플 4,000개의 y 히스토그램에서 **모드**를 찾아 층으로 삼는다
(`build_floorplan_gibson.py`: `PEAK_BIN` 0.10 m, `PEAK_FRAC` 0.02, `PEAK_MERGE` 0.60 m).
층의 z 밴드는 `[모드 − 0.1, min(모드 + 2.7, 다음 모드 − 0.1)]`.

## 벽 지도

`../../echoloc_simulator/floorplan_extraction/build_floorplan_gibson.py`가 층마다 만든다.
메시를 높이 밴드로 나눠 "모든 높이에서 solid한 셀"만 벽으로 투표(가구·문 상인방 제거, 문은 열림),
navmesh 외피로 외곽을 봉합, 그 안의 navmesh 샘플에서 flood-fill한 방만 자유공간.
같은 마스크를 압출한 `floorplan_proxy/<id>/floorplan.glb`가 `floorplan_closed` 음향 지오메트리다.

`maps/<id>/scene_meta.json`의 `navmesh_on_free_fraction`은 봉합된 자유공간 중 실제로 navmesh가 덮는 비율이다.
945층 평균 0.994, 0.90 미만이 16층, 0.50 미만이 2층(`Gratz_f0` 0.38, `Fedora_f0` 0.45)이다.
포즈는 navmesh에서만 뽑으므로 이 층들은 포즈가 특정 영역에 몰릴 뿐 지도가 틀린 것은 아니다.

## 시멘틱 지도가 없는 이유

habitat Gibson trainval 릴리스는 `.glb`와 `.navmesh`뿐이고 면 단위 객체 주석이 없다.
Replica(면별 object id), MP3D(`.house` → mpcat40), S3D(annotation JSON)와 달리 벽/문/창을 가를 근거가 없어
`semantic_maps/`를 만들지 않았다. 3DSceneGraph를 따로 받으면 객체 주석이 생기지만 habitat 메시와
면 단위로 정렬돼 있지 않아 `make_semantic_map.py`를 그대로 적용할 수 없다.

## 스캔의 빈 영역

Gibson 스캔에도 스캔되지 않은 공간이 있어 일부 프레임은 RGB·`depth_radial_scan`이 검게 나온다.
지도와 `depth_radial_floorplan`은 봉합된 지도 기준이라 그 자리에 벽을 보고한다.
**포즈는 거르지 않았고**, 프레임마다 `chunks.json`의 `scan_nohit_lower`(이미지 120행 아래 무충돌 비율)로 기록했다.
필요하면 그 값으로 하류에서 제외하면 된다. 사용법은 `../mp3d/README.md`와 같다.

## 스펙과 다른 점

1. 씬 = 층 (`<건물>_f<k>`), 지도는 층마다 하나.
2. 청크 수가 층 면적 비례(고정 300 아님).
3. ray cast는 `../../echoloc_simulator/raycast.py`의 정확한 DDA (F3Loc 원본은 벽 꼭짓점 픽셀을 건너뜀).
4. RIR: 48 kHz, 20,000 rays, 반사 50회, 회절 on, 링 rel 0 + binaural 4헤딩 (스펙은 8 kHz·4096 rays·깊이 6·회절 off·헤딩 1).
5. 시멘틱 지도 없음 (위 참조).
