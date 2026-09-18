# echoloc_dataset / s3d — Structured3D floorplan-localization dataset (F3Loc 호환, + RIR)

Structured3D 주택 700채를 F3Loc 형식으로 가져온 데이터셋.
구조·공통 규약은 `../README.md` 참조. 여기서는 S3D 고유 사항만 적는다.
요구 스펙은 `../dataset_generation_spec.md`, 생성 코드는 `../../echoloc_simulator/build_s3d.py`.

## Replica·MP3D와 다른 점 세 가지

1. **메시가 없다.** S3D는 합성 데이터라 3D 메시를 배포하지 않고, 렌더 결과와 구조 주석(`annotation_3d.json`)만 준다.
   따라서 새 포즈에서 렌더할 수 없고, 음향도 `floorplan_closed` 조건만 존재한다(`raw_scan_open` 없음).
2. **단일 뷰(L = 0).** 포즈를 샘플링하지 않고 S3D가 제공하는 고정 카메라 위치를 그대로 쓴다.
   청크 하나 = 프레임 하나이고 파일명은 `{step:05d}.png`.
3. **카메라가 다르다.** 640×360, HFOV 80°, **F_W = 0.596** (Replica/MP3D의 3/8이 아님).
   F3Loc config의 `F_W`를 반드시 바꿔야 한다. roll·pitch가 0이 아니라서 RGB와 depth를 F3Loc `gravity_align`으로 워핑해 두었고,
   원래 roll·pitch·카메라 높이는 `chunks.json`에 남겼다.

| | 값 |
|---|---|
| 씬 | 700 (perspective/full zip 00·01·16·17에서 추출) |
| split | train 400 (id < 3000) / val 50 (3000–3249) / test 250 (3250+) — S3D 표준 split |
| 프레임 | 15,872 |
| RIR | 15,872 포즈 × floorplan_closed (링 6ch + binaural 4헤딩) |

## 지도

`annotation_3d.json`의 방 바닥 폴리곤을 0.05 m 격자에 그려(벽 1셀, 4-연결) 5배 업샘플한다.

- **방 사이 문은 열고**, 건물 바깥으로 나가는 문(현관 등)과 창은 벽으로 둔다. 지도는 외부를 장애물로 보기 때문에,
  바깥 문을 열면 프록시(외벽 없음)와 지도가 어긋난다.
- 프록시는 지도의 **장애물 경계 셀 전부**를 상자로 세운다. 벽 선만 세우면 방 사이 벽 두께 틈으로 광선이 새서 3~4 cm 어긋난다.
- 천장 높이는 주석 junction z의 98% 분위(대개 2.8 m).

## depth

- `depth_radial_scan/`: S3D가 제공하는 **가구 포함** 렌더. 원본은 planar z(mm)라 1280×720 내부 파라미터로 **radial로 변환**한 뒤
  RGB와 같은 gravity 워핑을 적용했다(광선 거리는 회전 불변, planar z는 아니다).
- `depth_radial_floorplan/`: 프록시를 habitat으로 같은 포즈에서 렌더한 것.
- `depth40/160.txt`: 지도 ray cast (공통 규약과 동일).

## 제외한 프레임

- 카메라가 지도상 자유 픽셀이 아닌 프레임.
- 벽에서 **2 cm 미만**인 프레임 243개(1.5%). S3D 카메라는 벽에 바짝 붙는 경우가 있고, 그러면 habitat near plane이 벽을 잘라
  프록시 렌더에 무충돌 픽셀이 생긴다. 개수는 `maps/<scene>/scene_meta.json`의 `frames_skipped_wall_touch`.

## 검증

`../../echoloc_simulator/validate.py` 700씬 전항목 OK. depth160 vs 독립 ray march p99 0.05 cm,
프록시 radial vs 지도 ray 거리 중앙값 0.03 cm, 프록시 depth 무충돌 픽셀 0, RIR 포즈 인덱스·링·binaural 완비 OK.
