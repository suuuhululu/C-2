# 블록의자 2 Ground Truth 작성 메모

- design_id: `chair_2_v1`
- 원본 24장은 보존하고 촬영 시각이 포함된 파일명 순으로 복사했습니다. 수정 시각도 해당 촬영 분과 일치합니다.
- **빈 Assembly Board 사진이 없습니다.** 첫 사진에 노란 블록 1개가 있어 step_001부터 시작합니다. step_000은 미촬영/누락이며 다른 의자의 빈 판으로 대체하지 않았습니다.
- 각 사진을 한 블록 추가 단계로 간주한 임시 step입니다. 특히 step_005~012는 같은 footprint에서 높이가 변하는 구간으로, Top View 가림 때문에 실제 추가 여부와 개수는 사용자 확인이 필요합니다. 확인 전 확정 Ground Truth로 사용하지 마세요.
- RealSense Viewer UI를 포함한 RGB 스크린샷입니다.

## Board 정의

| 항목 | 정의 / 작성할 값 |
|---|---|
| grid_size | 24 × 24 (사용자 지정, 사진으로 별도 계수하지 않음) |
| origin | red-marked stud = (0, 0) |
| +X | robot base 좌표계의 +X 방향과 맞춤. 사진에서 해당 방향: TBD |
| +Y | robot base 좌표계의 +Y 방향과 맞춤. 사진에서 해당 방향: TBD |
| z / layer | LEGO brick 층 번호(0-based). Board 직접 결합 brick은 layer=0, 그 위는 1, 이후 2…; Board 자체는 brick 층으로 세지 않음 |
| anchor | Board 좌표계에서 블록 footprint가 차지하는 stud 중 X와 Y가 모두 최소인 모서리 stud. grid_x=min(X), grid_y=min(Y)이며 회전 후에도 이 기준을 적용. 블록 중심이나 회전하는 local 원점이 아님 |
| orientation_deg | +X/+Y 기준으로 정의. geometry=a×b×1의 0°는 X 방향 a stud, Y 방향 b stud. +Z 쪽에서 Board를 내려다볼 때 반시계 방향으로 90° 증가. 2×2×1은 회전 대칭이므로 0으로 기록. 2×3×1은 0°일 때 X 2/Y 3, 90°일 때 X 3/Y 2 stud; 대칭인 180°/270°는 각각 0°/90°로 기록. 실제 +X/+Y 기준을 확인하지 못하면 TBD 유지 |


## Step별 추가 블록

B001/B002는 사용자 확인에 따라 각각 grid=(10,12)/(13,12), layer=0을 반영했습니다. 블록의자1과 시작 위치가 같다는 사용자 확인을 적용했습니다. 모든 2×2×1의 orientation_deg=0은 회전 대칭에 따른 기록 규칙입니다. 그 밖의 미확정 좌표·layer와 2×3×1 회전각은 TBD를 유지합니다. 화면의 가로/세로만으로 Board 기준 회전각을 확정하지 않습니다. 기존 색상·geometry·관찰 메모를 유지하며 이번 수정에서 사진 기반 추정값을 추가하지 않았습니다.

block_id는 촬영 순서 기준 임시 ID입니다. 색상과 geometry는 보이는 윗면을 기준으로 채웠습니다. 같은 footprint의 적층 구간에서는 신규 블록의 규격인지 확인해 주세요. 높이 1은 지정된 블록 규격이며 이미지 계측값은 아닙니다. 남아 있는 TBD 필드는 직접 확인하여 채워 주세요. 화면 방향은 robot base 방향과 구별됩니다.

| step | image filename | block_id | color | geometry | grid_x | grid_y | layer | orientation_deg | 관찰 / 확인할 내용 |
|---|---|---|---|---|---|---|---|---|---|
| 001 | chair_2_step_001_rgb.png | B001 | YELLOW | 2x2x1 | 10 | 12 | 0 | 0 | 첫 노란 블록; 빈 판 사진 없음 |
| 002 | chair_2_step_002_rgb.png | B002 | YELLOW | 2x2x1 | 13 | 12 | 0 | 0 | 화면 오른쪽 위 노란 블록 |
| 003 | chair_2_step_003_rgb.png | B003 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 화면 왼쪽 아래 노란 블록 |
| 004 | chair_2_step_004_rgb.png | B004 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 화면 오른쪽 아래 노란 블록 |
| 005 | chair_2_step_005_rgb.png | B005 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 006 | chair_2_step_006_rgb.png | B006 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 007 | chair_2_step_007_rgb.png | B007 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 008 | chair_2_step_008_rgb.png | B008 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 009 | chair_2_step_009_rgb.png | B009 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 010 | chair_2_step_010_rgb.png | B010 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 011 | chair_2_step_011_rgb.png | B011 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 012 | chair_2_step_012_rgb.png | B012 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 노란 2×2 footprint 적층 구간; 신규 블록/위치/개수 확인 필요 |
| 013 | chair_2_step_013_rgb.png | B013 | BLUE | 2x3x1 | TBD | TBD | TBD | TBD | 화면 왼쪽 위 파란 가로 2×3 |
| 014 | chair_2_step_014_rgb.png | B014 | BLUE | 2x3x1 | TBD | TBD | TBD | TBD | 화면 오른쪽 위 파란 세로 2×3 |
| 015 | chair_2_step_015_rgb.png | B015 | BLUE | 2x3x1 | TBD | TBD | TBD | TBD | 화면 오른쪽 아래 파란 가로 2×3 |
| 016 | chair_2_step_016_rgb.png | B016 | BLUE | 2x3x1 | TBD | TBD | TBD | TBD | 화면 왼쪽 아래 파란 세로 2×3 |
| 017 | chair_2_step_017_rgb.png | B017 | BLUE | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 왼쪽 파란 2×2 |
| 018 | chair_2_step_018_rgb.png | B018 | BLUE | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 오른쪽 파란 2×2 |
| 019 | chair_2_step_019_rgb.png | B019 | BLUE | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 왼쪽 파란 2×2 적층; 신규 블록 확인 |
| 020 | chair_2_step_020_rgb.png | B020 | BLUE | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 오른쪽 파란 2×2 적층; 신규 블록 확인 |
| 021 | chair_2_step_021_rgb.png | B021 | RED | 2x3x1 | TBD | TBD | TBD | TBD | 화면 아래 오른쪽 빨간 가로 2×3 |
| 022 | chair_2_step_022_rgb.png | B022 | RED | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 왼쪽 빨간 2×2 |
| 023 | chair_2_step_023_rgb.png | B023 | RED | 2x3x1 | TBD | TBD | TBD | TBD | 화면 아래 왼쪽 빨간 가로 2×3 적층 |
| 024 | chair_2_step_024_rgb.png | B024 | RED | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 오른쪽 빨간 2×2 적층 |

## 원래 파일명 → 새 파일명

새 파일은 원본과 바이트가 동일한 복사본입니다. 촬영 시간순을 유지했습니다. 빈 판이 없어 step_000 파일은 생성하지 않았습니다.

| 원래 파일명 | 새 파일명 |
|---|---|
| Screenshot from 2026-10-03 15-10-04.png | chair_2_step_001_rgb.png |
| Screenshot from 2026-10-03 15-10-07.png | chair_2_step_002_rgb.png |
| Screenshot from 2026-10-03 15-10-10.png | chair_2_step_003_rgb.png |
| Screenshot from 2026-10-03 15-10-13.png | chair_2_step_004_rgb.png |
| Screenshot from 2026-10-03 15-10-19.png | chair_2_step_005_rgb.png |
| Screenshot from 2026-10-03 15-10-21.png | chair_2_step_006_rgb.png |
| Screenshot from 2026-10-03 15-10-23.png | chair_2_step_007_rgb.png |
| Screenshot from 2026-10-03 15-10-25.png | chair_2_step_008_rgb.png |
| Screenshot from 2026-10-03 15-10-28.png | chair_2_step_009_rgb.png |
| Screenshot from 2026-10-03 15-10-31.png | chair_2_step_010_rgb.png |
| Screenshot from 2026-10-03 15-10-34.png | chair_2_step_011_rgb.png |
| Screenshot from 2026-10-03 15-10-37.png | chair_2_step_012_rgb.png |
| Screenshot from 2026-10-03 15-10-41.png | chair_2_step_013_rgb.png |
| Screenshot from 2026-10-03 15-10-44.png | chair_2_step_014_rgb.png |
| Screenshot from 2026-10-03 15-10-47.png | chair_2_step_015_rgb.png |
| Screenshot from 2026-10-03 15-10-52.png | chair_2_step_016_rgb.png |
| Screenshot from 2026-10-03 15-10-58.png | chair_2_step_017_rgb.png |
| Screenshot from 2026-10-03 15-11-01.png | chair_2_step_018_rgb.png |
| Screenshot from 2026-10-03 15-11-04.png | chair_2_step_019_rgb.png |
| Screenshot from 2026-10-03 15-11-07.png | chair_2_step_020_rgb.png |
| Screenshot from 2026-10-03 15-11-12.png | chair_2_step_021_rgb.png |
| Screenshot from 2026-10-03 15-11-15.png | chair_2_step_022_rgb.png |
| Screenshot from 2026-10-03 15-11-20.png | chair_2_step_023_rgb.png |
| Screenshot from 2026-10-03 15-11-23.png | chair_2_step_024_rgb.png |

## 지금 직접 채워야 할 값 체크

- [ ] Board 사진에서 실제 `+X`, `+Y` 방향을 확인하고 Board 정의의 `TBD`를 채우기.
- [ ] B003~B024 각각의 `grid_x`, `grid_y`, `layer`를 실물 또는 조립 기록으로 확인하여 채우기. 좌표는 점유 stud의 X/Y 최소값, Board 직접 결합은 layer=0.
- [ ] 2×3×1 블록 B013, B014, B015, B016, B021, B023의 `orientation_deg`를 실제 +X/+Y 기준으로 확인하여 0 또는 90으로 채우기. 확실하지 않으면 `TBD` 유지.
- [ ] step_005~012 및 적층 관찰 단계의 실제 신규 블록 여부·개수·규격을 확인하고 임시 step/block_id 기록을 검증하기. step_000은 미촬영/누락 상태 유지.

B001/B002의 좌표·layer와 모든 2×2×1의 orientation_deg는 반영되어 있습니다. 가려진 이전 블록은 누적 상태에 유지합니다.
