# echoloc

F3Loc 호환 floorplan-localization 데이터셋 5종(Replica · Matterport3D · Gibson · Structured3D · ZInD)에
co-located 6-mic ring RIR(AV-FPLoc 음향 확장)과 SemRayLoc 형식 시멘틱 도면을 붙여 만든 프로젝트의
**생성 코드, 검증 코드, 전 과정 기록, 샘플**. 데이터 자체(~675 GB)는 여기 없다.

| | replica | mp3d | gibson | s3d | zind |
|---|---|---|---|---|---|
| 씬 | 17 | 159 층 / 83 건물 | 945 층 / 489 건물 | 700 | 2,443 층 / 1,575 집 |
| split | 11 / 3 / 3 | 131 / 16 / 12 | 795 / 81 / 69 | 400 / 50 / 250 | 1,948 / 243 / 252 |
| 프레임 (collection당) | 20,400 | 65,780 | 246,212 | 15,872 | 55,926 |
| RIR | ring + binaural, 2조건 | 동일 | ring, 2조건 | ring + binaural, 도면 조건 | ring, 도면 조건 |
| 시멘틱 도면 | O | O | X | O | O |

- **[ECHOLOC_DATA_GENERATION.md](ECHOLOC_DATA_GENERATION.md)** — 규약·알고리즘·상수·타임라인·문제와 해결까지 전부. 처음 보면 이것부터.
- **[samples/](samples/)** — 데이터셋마다 씬 하나씩, 파이프라인이 만드는 모든 파일의 실물 (10 MB). 라이선스가 허용하는 범위만.
- **[echoloc_dataset/](echoloc_dataset/)** — 데이터셋 루트에 두는 문서: 스펙, 5종 비교 README, 데이터셋별 README와 `dataset_meta.json`.
- **[echoloc_simulator/](echoloc_simulator/)** — 파이프라인. `env.sh` → `ECHOLOC_DATASET=<profile>` → `run_all.sh <stage>`. 자세한 실행법은 그 안의 README.

```bash
git clone https://github.com/felix-ch/f3loc echoloc_simulator/third_party/f3loc   # 참조 구현 (규약·S3D 유틸)
cd echoloc_simulator && source env.sh && export ECHOLOC_DATASET=replica
./run_all.sh maps && ./run_all.sh poses 300 && JOBS=4 ./run_all.sh rgb   # ...
```

환경: habitat-sim 0.2.2 (SoundSpaces 2.0, RLRAudioPropagation), conda `ss_v2`, Python 3.9. 원본 데이터는 각 데이터셋의 라이선스에 따라 직접 받아야 한다.
