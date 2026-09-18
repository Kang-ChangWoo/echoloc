# echoloc_dataset / mp3d — Matterport3D floorplan-localization dataset (F3Loc 호환, + RIR)

Matterport3D 건물을 **층 단위 씬**으로 나눠 F3Loc 형식으로 렌더한 데이터셋.
구조·규약은 `../README.md`와 `../replica/README.md`가 설명하는 것과 같고, 여기서는 MP3D 고유 사항만 적는다.
요구 스펙은 `../dataset_generation_spec.md`, 생성 코드는 `../../echoloc_simulator/`.

## 씬 id = 층

MP3D 씬 하나는 건물 전체라 F3Loc의 "한 지도 = 한 층"(스펙 3.3 / 5.2) 요구를 만족하지 못한다.
그래서 SoundSpaces 그래프 노드를 높이로 클러스터링(간격 1 m 초과 = 새 층)해 **`<건물>_f<k>`** (k = 0이 최하층)로 나눴다.

| | 값 |
|---|---|
| 건물 | 83 (그래프 메타데이터가 있는 것) |
| 층 씬 | 159 |
| split | train 131 / val 16 / test 12 (0303renew `scene_split.json`의 건물 split을 층에 그대로 상속) |
| 청크 | 층 면적 비례 (m²당 0.6개, 40–160), collection당 16,445 |
| 프레임 | collection당 65,780 (청크 × 4뷰) |

- 한 건물의 모든 층은 **같은 지도 좌표계**(같은 원점·크기)를 쓴다. 층별 z 밴드는 `maps/<id>/scene_meta.json`.
- 층 판정에 쓴 z 밴드는 `[노드 최저 − 0.1, min(노드 최저 + 2.7, 다음 층 − 0.1)]`.
- 그래프 노드 4개 미만이거나 봉합된 실내 면적 8 m² 미만인 층은 제외했다.
- 천장이 카메라(1.25 m) 위로 `MIN_CEIL_MARGIN` 0.15 m를 못 남기는 층도 제외했다. 반층·다락으로 잡힌 6개 층이
  여기서 빠져 165 → 159가 됐다.
- 포즈는 해당 층 높이에서만 샘플링하고, 카메라가 그 층의 프록시 천장 위로 올라가는 지점은 거부한다(계단참 대응).

## 벽 지도

`../../echoloc_simulator/floorplan_extraction/build_floorplan_mp3d.py`가 층마다 만든다.
메시를 높이 밴드로 나눠 "모든 높이에서 solid한 셀"만 벽으로 투표(가구·문 상인방 제거, 문은 열림),
navmesh ∩ 스캔 footprint로 외곽을 봉합, 그 안의 그래프 노드에서 flood-fill한 방만 자유공간.
같은 마스크를 압출한 `floorplan_proxy/<id>/floorplan.glb`가 `floorplan_closed` 음향 지오메트리다.

## 스캔의 빈 영역

MP3D 스캔에도 스캔되지 않은 공간이 있어 일부 프레임은 RGB·`depth_radial_scan`이 검게 나온다.
지도와 `depth_radial_floorplan`은 봉합된 지도 기준이라 그 자리에 벽을 보고한다.
**포즈는 거르지 않았고**, 프레임마다 `chunks.json`의 `scan_nohit_lower`(이미지 120행 아래 무충돌 비율)로 기록했다.
필요하면 그 값으로 하류에서 제외하면 된다.

```python
import json, numpy as np
ch = json.load(open("mp3d_f/1LXtFkjw3qL_f1/chunks.json"))
nohit = np.array([fr["scan_nohit_lower"] for c in ch["chunks"] for fr in c["frames"]])  # poses.txt 행 순서
keep = [c["idx"] for c in ch["chunks"] if max(f["scan_nohit_lower"] for f in c["frames"]) <= 0.15]
```

## 검증

`../../echoloc_simulator/validate.py` 기준. 축 검증(프록시 렌더 vs 지도 ray cast) 중앙값 0.0 cm,
check 9(depth160 vs 독립 ray march) p99 0.05 cm, 프록시 depth 무충돌 픽셀 0, RIR 포즈 인덱스·링·binaural 완비 OK.

## 스펙과 다른 점

1. 씬 = 층 (`<건물>_f<k>`), 지도는 층마다 하나.
2. 청크 수가 층 면적 비례(고정 300 아님).
3. ray cast는 `../../echoloc_simulator/raycast.py`의 정확한 DDA (F3Loc 원본은 벽 꼭짓점 픽셀을 건너뜀).
4. RIR: 48 kHz, 20,000 rays, 반사 50회, 회절 on, 링 rel 0 + binaural 4헤딩 (스펙은 8 kHz·4096 rays·깊이 6·회절 off·헤딩 1).
