# Round2 로봇 제어 연결과 하드코딩 점검 — 2026-10-14

이 변경은 기존 Round1 제어·원본 A plan·B 완료 판정을 보존하고 Round2용 후보와 실행 함수를 추가한다. 실물 조립 완료나 전체 HMI 연결 완료를 뜻하지 않는다.

## 세 분기

| 입력 step | Round2 후보 | 동작 |
|---|---|---|
| ROBOT_GRIP / NONE | ROBOT_RELEASE_PRESS | 공급 중심 관측 → 이송 → 각도 보정 → 놓기 → 빈 패드 중심 수직 가압 |
| 구조 지지 HOLD / PRESS_AND_HOLD / MANUAL_ASSEMBLY_AND_HOLD | HUMAN_ASSEMBLY / MANUAL_ASSEMBLY_AND_HOLD | place board 전달, 지지·사람 조립 정책 유지 |
| HUMAN_ASSEMBLY / 접근·간섭 문제 | 실측 조건 충족 시 ROBOT_RELEASE_PRESS | 최초 공급 파지부터 높은 파지 관계를 적용, 같은 중심에서 놓고 누름 |

높은 파지의 간섭·안착·접촉 자료가 부족하면 원래 사람 결착 분기를 유지한다. ROBOT_GRIP의 닫힌 패드 자료가 없으면 새 경로는 그 사실을 반환한다. 이 보류는 임의의 블록 좌표를 다른 step에 재사용하지 않기 위한 입력 상태다.

`app/round2_step_controller.py`의 `prepare_round2_step` / `run_round2_step`이 일반 step의 연결점이다. Live 실행은 기존 ControlledDriver/session 검사를 사용한다. 기존 `integration_runtime.StepRuntime`의 상태·signals·B 완료 소유를 자동 변경하지 않았다. 따라서 기존 HMI가 이 새 진입점을 호출하도록 연결하는 작업은 별도이며, 현재 일반 runtime에 단순히 ROBOT_RELEASE_PRESS 문자열을 넣어 실행하면 안 된다.

## 각도 보정: 중심 위치와 구분

- 조립판 보정·현재 카메라 pose·CameraInfo로 가상의 평행 방향을 계산한다. 기존 layer_records의 층간 Z 차이로 층별 평면을 선택한다.
- 비교 지점은 실제 블록 모서리의 화면 중점이다. stud 중심과 격자선이 겹칠 필요가 없다. 원근 투영 때문에 화면의 모든 평행선이 같은 픽셀 기울기는 아니므로 블록 위치에서 방향을 계산한다.
- 기존 격자 방향 provider는 yaw만 보정한다. XY·roll·pitch 측정으로 표시하지 않는다. 일반 step은 `virtual_grid_direction_provider(capture, config, near_contact_offset_mm=profile['near_contact_offset_mm'])`를 연결할 수 있다.
- RGB-D/접촉으로 등록된 실제 윗면·목표 평면 데이터가 있을 때 `registered_surface_provider`를 연결하면 roll/pitch/yaw를 비교한다. H/J/K 기준 자세 복귀는 실제 윗면 평행 측정과 다르다.
- 자동 반복은 새 측정마다 진행하며 횟수 상한이 없다. 각 오차가 포함 경계 −0.50°~+0.50°에 들어오면 종료한다. 가상의 격자 yaw 경로는 매회 최대0.5°씩 움직이고 실제 영상 반응으로 방향/이득을 확인한다. 인식 소실이나 불분명한 반응으로는 맹목적으로 회전을 반복하지 않는다.

held 팝업의 `--integrated-cycle`은 자동 yaw를 기본 사용한다. E로 윗면의 같은 모서리 두 끝점을 한 번 지정하면 새 영상에서 추적한다. 기존 G/R 반복 입력은 필요 없다. B는 블록 ROI, A는 기준 축 변경, X/I/O/P/U는 기존 XY/안착/해제/가압/상승 절차다. 위 입력이 자동 체결 성공 판정을 뜻하지 않는다.

## 높은 파지와 가압

실측15mm 어댑터는 원래5mm grasp를 들어 올려 대신하지 않는다. 최초 pickup TCP와 해당 landing TCP를 함께 바꾼다. profile.pending.json의 null pose는 실측이 아니다.

사용자가 별도로 지정한 +10mm base-Z 시험은 `--raised-grasp-z-offset-mm 10`으로 새 공급 파지부터 시작한다. 초기 pickup/landing을 함께 +10mm하고 원본값을 저장한다. 닫힌 빈 패드 접촉 Z에는 +10mm를 더하지 않는다. `measured_15mm_relation_verified=false`로 기록하며 기존 측정 어댑터와 혼합하지 않는다.

가압은 **측정 합력45N에서 멈추는 위치 하강**이다. 일정45N 유지 force control이 아니다. 놓기 직전 실제 XY/자세를 저장하고 개방 → 같은 XY/자세 수직 상승 → 빈 패드 닫기 → 수직 하강한다. 빈 패드가 폭12mm 이하에서 status2를 반환해도, 그 전에 개방이 확인된 이 순서에 한해 실제 status를 이후 모션에 유지한다.

## 점검 결과

| 부분 | 발견·조치 |
|---|---|
| held 관측/복귀 메시지 | 목표를 바꿔도 11,11로 기록하던 부분 수정 |
| held 복귀 속도·힘 | 별도의 24/120/35 상수 대신 현재 config를 사용하도록 수정; 합력45N과 축 힘35N의 불일치도 제거 |
| Round2 이동 속도 | 기본 사용자 지정120/12는 유지, profile.round2_motion으로 변경 가능; 중복 대입 제거 |
| OpenCV 크기/면적 기준 | 슬롯별 설정을 코드 기본값으로 덮어쓰던 부분 수정; 지정된 기준 우선 |
| 경로 높이 | 실제 상승에만 clearance_z를 넘기도록 opt-in Round2 수정; 정상 하강을 이송 높이로 판정하지 않음 |
| 층별 교시 | 4층의 옛 값/채택 값 중복을 해결; 명시적으로 채택된 실측을 우선하고 원자료는 보존 |
| 반복 측정 | 이전 반복의 AFTER보다 오래된 BEFORE를 재사용하지 않음 |
| MOCK 파지 | 35/40mm만 파지로 처리하던 replay에 grasp_width_mm 입력 추가; 실물 어댑터와 구분 |
| 경로 파일 위치 | 런타임 경로의 checkout 상대경로 지원; PR에 필요한 static-TF snapshot 포함 |
| 기존 integration_runtime | 2×2/90°와 ROBOT_RELEASE_PRESS 지원 제한이 남아 있음. Round1 보존 때문에 이 상태 머신을 이 PR에서 확대하지 않음. 새 Round2 API와 구분 |
| 기존 held 시험 | 슬롯1/노랑2×2와 가압1층은 시험 데이터 범위다. 일반 지원5종×0/90°와 구분; 다른 블록의 실측값으로 가장하지 않음 |
| 기본 calibration | 11,11은 실제 교시 anchor다. 임의 좌표 제한과 구분. 다른 좌표는 기존 affine delta이며 새 직접 교시로 표시하지 않음 |

24×24, layer1~5, 지원5종, RG2 측정 범위110mm는 현재 장치/계약 기준이며 임의의 작업 좌표 하드코딩과 다르다. 합력45N·높이15mm·허용각±0.50°는 사용자 결정값이다. 원본 force/TCP/tool/STOP 검사와 상태 소유는 보존했다.

## Preview와 실물 시험

일반 step Preview는 장치 연결 없이 실행 후보를 저장한다:

```bash
python3 robot_control_integration/scripts/round2_step_preview.py \
  --step-dir <기존-step-폴더> --profile <기존-profile.json> \
  --measured <해당-step-측정.json> --output /tmp/round2-step-preview.json
```

기존 held 실물 시험은 사용자가 터미널에서 시작한다. 아래는 홈/빈 그리퍼/슬롯1/빈(17,17)1층 전제의 사용자 +10mm 시험이다:

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py \
  --execute --integrated-cycle --start-zone home \
  --target-x 17 --target-y 17 --raised-grasp-z-offset-mm 10 \
  --same-xy-press --confirm-target-empty --confirm-hand-clear
```

입력 자료의 `automatic_geometry_verified=false`를 목표11,11과 같다는 이유로 true로 승격하지 않는다. 기본 패드 reference는 과거 사용자의 읽기 전용 캡처 snapshot이며 현장의 현재 접촉 상태가 아니다.

일반 step의 실제 OpenCV 중심→robot XY mapping, RGB-D 윗면 측정 producer, 모든 블록의 높은 파지 간섭/안착/누름은 실물 검증 대상이다. 이번 변경 과정에서는 로봇/그리퍼 명령을 실행하지 않았다.
