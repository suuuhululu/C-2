# 블록의자 1 Ground Truth 작성 메모

- design_id: `chair_low_v1`
- 원본 스크린샷 13장은 보존하고, 촬영 시각이 포함된 원래 파일명 순으로 복사했습니다.
- step_000은 빈 Assembly Board입니다. step_001~012는 직전 사진에 블록 하나를 추가한 상태로 확인했습니다.
- RealSense Viewer UI가 포함된 RGB 스크린샷입니다. 원본 RGB 스트림/Depth 데이터는 아닙니다.

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

B001/B002는 사용자 확인에 따라 각각 grid=(10,12)/(13,12), layer=0을 반영했습니다. 모든 2×2×1의 orientation_deg=0은 회전 대칭에 따른 기록 규칙입니다. 그 밖의 미확정 좌표·layer와 2×3×1 회전각은 TBD를 유지합니다. 화면의 가로/세로만으로 Board 기준 회전각을 확정하지 않습니다. 기존 색상·geometry·관찰 메모를 유지하며 이번 수정에서 사진 기반 추정값을 추가하지 않았습니다.

색상과 geometry는 이미지에서 보이는 stud 수로 판별했습니다. 높이 1은 요청한 블록 규격을 적용한 것이며 사진만으로 높이를 계측한 값은 아닙니다. 남아 있는 TBD 필드는 실제 조립 기록을 확인하여 채워 주세요. 블록 ID는 추가 순서입니다. 가려진 이전 블록은 누적 상태에 유지합니다.

| step | image filename | block_id | color | geometry | grid_x | grid_y | layer | orientation_deg | 관찰 / 사용자 메모 |
|---|---|---|---|---|---|---|---|---|---|
| 000 | chair_low_step_000_rgb.png | — | — | — | — | — | — | — | 빈 판 |
| 001 | chair_low_step_001_rgb.png | B001 | YELLOW | 2x2x1 | 10 | 12 | 0 | 0 | 첫 노란 블록 |
| 002 | chair_low_step_002_rgb.png | B002 | YELLOW | 2x2x1 | 13 | 12 | 0 | 0 | 화면 오른쪽 노란 블록 |
| 003 | chair_low_step_003_rgb.png | B003 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 화면 왼쪽 아래 노란 블록 |
| 004 | chair_low_step_004_rgb.png | B004 | YELLOW | 2x2x1 | TBD | TBD | TBD | 0 | 화면 오른쪽 아래 노란 블록 |
| 005 | chair_low_step_005_rgb.png | B005 | YELLOW | 2x3x1 | TBD | TBD | TBD | TBD | 화면 왼쪽 위에 세로 2×3 추가 |
| 006 | chair_low_step_006_rgb.png | B006 | YELLOW | 2x3x1 | TBD | TBD | TBD | TBD | 화면 오른쪽 위에 가로 2×3 추가 |
| 007 | chair_low_step_007_rgb.png | B007 | YELLOW | 2x3x1 | TBD | TBD | TBD | TBD | 화면 오른쪽 아래에 세로 2×3 추가 |
| 008 | chair_low_step_008_rgb.png | B008 | YELLOW | 2x3x1 | TBD | TBD | TBD | TBD | 화면 왼쪽 아래에 가로 2×3 추가 |
| 009 | chair_low_step_009_rgb.png | B009 | BLUE | 2x3x1 | TBD | TBD | TBD | TBD | 화면 아래 오른쪽 파란 2×3 추가 |
| 010 | chair_low_step_010_rgb.png | B010 | BLUE | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 왼쪽 파란 2×2 추가 |
| 011 | chair_low_step_011_rgb.png | B011 | BLUE | 2x3x1 | TBD | TBD | TBD | TBD | 화면 아래 왼쪽에 파란 2×3 추가; 이전 블록 일부 가림 |
| 012 | chair_low_step_012_rgb.png | B012 | BLUE | 2x2x1 | TBD | TBD | TBD | 0 | 화면 아래 오른쪽에 파란 2×2 추가; 이전 블록 일부 가림 |

## 원래 파일명 → 새 파일명

파일명 속 촬영 시각(초 단위)을 우선했습니다. 파일 수정 시각도 같은 분으로 일치했으며, 이미지 내용에서도 단계 역전이나 빈 단계는 발견되지 않았습니다. 아래 새 파일들은 원본과 바이트가 동일한 복사본입니다.

| 원래 파일명 | 새 파일명 |
|---|---|
| Screenshot from 2026-10-03 14-50-57.png | chair_low_step_000_rgb.png |
| Screenshot from 2026-10-03 15-02-40.png | chair_low_step_001_rgb.png |
| Screenshot from 2026-10-03 15-02-51.png | chair_low_step_002_rgb.png |
| Screenshot from 2026-10-03 15-02-54.png | chair_low_step_003_rgb.png |
| Screenshot from 2026-10-03 15-02-57.png | chair_low_step_004_rgb.png |
| Screenshot from 2026-10-03 15-03-01.png | chair_low_step_005_rgb.png |
| Screenshot from 2026-10-03 15-03-05.png | chair_low_step_006_rgb.png |
| Screenshot from 2026-10-03 15-03-08.png | chair_low_step_007_rgb.png |
| Screenshot from 2026-10-03 15-03-12.png | chair_low_step_008_rgb.png |
| Screenshot from 2026-10-03 15-03-20.png | chair_low_step_009_rgb.png |
| Screenshot from 2026-10-03 15-03-23.png | chair_low_step_010_rgb.png |
| Screenshot from 2026-10-03 15-03-26.png | chair_low_step_011_rgb.png |
| Screenshot from 2026-10-03 15-03-30.png | chair_low_step_012_rgb.png |

## 지금 직접 채워야 할 값 체크

- [ ] Board 사진에서 실제 `+X`, `+Y` 방향을 확인하고 Board 정의의 `TBD`를 채우기.
- [ ] B003~B012 각각의 `grid_x`, `grid_y`, `layer`를 실물 또는 조립 기록으로 확인하여 채우기. 좌표는 점유 stud의 X/Y 최소값, Board 직접 결합은 layer=0.
- [ ] 2×3×1 블록 B005, B006, B007, B008, B009, B011의 `orientation_deg`를 실제 +X/+Y 기준으로 확인하여 0 또는 90으로 채우기. 확실하지 않으면 `TBD` 유지.

B001/B002의 좌표·layer와 모든 2×2×1의 orientation_deg는 반영되어 있습니다. 가려진 이전 블록은 누적 상태에 유지합니다.
