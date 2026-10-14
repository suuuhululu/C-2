# Round2 D 실행 정합성과 A 연결 요청

2026-10-14 · 기준 `codex/integration-round2 @ b0d22e5` · 후속 브랜치 `codex/round2-d-consistency-20261014`

이 문서는 A PR50 이전의 연결 제안과 당시 기준 시험 기록이다. 최신 RELEASE_PRESS는 A의 기존 StepMotion 대신 D의 별도 프로필로 실행하며, 현재 로봇 분기는 [현장 수정 기록](D_ROUND2_ROBOT_FIELD_FIXES_20261014.md)을 따른다.

PR #46의 Round2 후보를 기존 A 계획·D 실행·B 검사 흐름에 연결하려면 실제 실행할 파지와 경로가 A의 계산 결과에 포함되어야 한다. D는 속도와 실행 연결을 보완한다. 기존 HMI의 Round2 자동 전환은 A/D 경로·작업 방식 계약을 확인한 뒤 진행한다.

2026-10-14 사용자 지시에 따라 이번 후속 수정에서 추가했던 실물 실행 검사·차단 조건을 제거했다. 기준 커밋의 기존 검사와 영상 신선도·촬영 시점·모서리 대응 검증은 유지한다.

## D에서 보완하는 실행 연결

- `run_round2_step`은 세션이 있는 경우 기존 `execute_step`의 실행 claim, 제어 소유권, 요청별 확인, STOP과 정리 절차를 재사용한다. 공개 확인 콜백은 기존 `confirm(kind, plan, sample)` 형태를 유지한다.
- Round2 수직 이동은 수직 속도로 명령한다. 프로파일에 각속도·각가속도가 있으면 별도로 전달하고, 누락 시 기존 이동 함수의 동작을 유지한다. 각속도 누락으로 추가 차단하지 않는다.
- 마지막 작업의 빈 패드 상태를 프로세스 내부 컨텍스트로 연결해 다음 Step의 개방과 분리된 `contact → release`의 상승에 사용한다. 새 증거·실행 세대·만료·보정 바인딩 검사는 요구하지 않는다.
- Round2 `ROBOT_RELEASE_PRESS`의 `assemble-held`를 기존 NONE 도움 조건 안에서 처리한다. 새 파지 완료 증거 요구나 분리 단계 차단은 추가하지 않는다.
- 사람 전달 분기에서는 로봇 결착용 `native_press`를 제거하고 원본 A 결과를 보존한다.
- 새 잔류 하중 보류 조건은 제거했다. 기존 힘·TCP/Tool·그리퍼·정지 검사는 기준 커밋의 동작을 유지한다. replay의 `stop_force_z_n=None`은 하중 유지를 재현하는 선택 입력이다.

## A에 필요한 확인

기존 세 API `handle_whole_plan`, `handle_step_reassessment`, `handle_step_motion`과 공통 배치 여섯 필드는 유지하는 방향을 우선한다. 아래는 A와 D가 확인할 연결안이다.

| 항목 | 현재 계약 | Round2 연결안 |
|---|---|---|
| 작업 방식 | A는 `ROBOT_GRIP` 또는 `HUMAN_ASSEMBLY` 후보를 반환한다. | A의 두 분류를 보존하고 D의 놓기·빈 패드 누르기 전략을 별도 실행 조건으로 표현할 수 있는지 확인한다. |
| 높은 파지 | 기존 공급 파지 관계로 접근·간섭을 계산한다. | D가 제공하는 해당 블록·방향·슬롯의 실측 pickup/landing 및 파지 관계를 A 재평가 전에 전달한다. |
| 로봇 이송 | `SUPPLY_20_0 → BODY_BYPASS → PLACE_BOARD`를 D 검증기가 요구한다. | `SUPPLY_20_0 → BODY_BYPASS → ROUND2_ASSEMBLY_OBSERVATION`을 A가 계산하고 D가 동일한 좌표·자세로 검증할 수 있는 프로파일 표현을 확인한다. |
| 사람 전달 | 전달판 경유와 사람 도움 정책을 사용한다. | 검토된 전달판 경로와 구조 지지 요구를 보존한다. |
| 방향 보정 | A 경로의 목표 자세와 D 실행을 비교한다. | D가 실행 중 허용할 보정 범위와 그 범위를 벗어났을 때의 재평가 조건을 함께 정한다. |
| 승인 연결 | 원본 A 재평가·경로와 Current·예약에 실행을 묶는다. | 원본 A 결과와 실제 실행 후보의 변경 항목을 모두 추적한다. 기존 `reassessed_mode`를 덮어써서 일치시키지 않는다. |

실측15mm 파지와 사용자 +10mm base-Z 시험은 다른 입력이다. +10mm 시험을 실측15mm 프로파일이나 검증된 간섭 근거로 사용할 수 없다. 닫힌 빈 패드 접촉 기준에도 동일한 Z 오프셋을 자동 추가하지 않는다.

예제는 [A/D 연결 제안 JSON](../robot_control_integration/interfaces/round2_a_handoff.proposed.json)에 있다. `existing_a_d_document`는 실제 A/D fixture 함수로 만든 SYNTHETIC 후보이며, `requested_changes`는 검토할 변경이다. 최상위 `execution_allowed=false`와 `A_D_REVIEW_PENDING`을 유지한다. 이 JSON은 현재 A API에 그대로 보내는 새 요청 형식이 아니다.

관련 구현은 [A 이동 후보](../planning_trial/assembly_motion.py), [A 지원 방식](../planning_trial/assembly_profiles.py), [D 경로 검증](../robot_control_integration/app/integration_motion_binding.py), [D StepRuntime](../robot_control_integration/app/integration_runtime.py)이다.

## 영상 캡처의 D 내부 계약

새 Current·예약·보정 식별자, 측정 출처, REAL/TEST 프로파일을 강제하는 실물 실행 검사와 정렬 누적 이동·시간 예산 검사는 제거했다. 아래 필드는 영상 신선도와 영상·로봇 관측의 시점 대응을 위한 입력이다. 수치는 현장의 시각 동기화 자료로 정한다.

```text
round2_capture_limits:
  max_frame_age_ns
  max_pose_skew_ns
  max_clock_mapping_error_ns

capture_timing:
  clock_domain, clock_now_ns
  pose_clock_domain, pose_stamp_ns, pose_posx
  exposure_monotonic_ns, exposure_mapping_error_ns, clock_mapping_ref
```

영상의 `frame_stamp_ns`와 로봇 pose 시각은 같은 선언된 소스 clock domain에서 비교한다. 소스 시각을 프로세스 monotonic 시각으로 변환한 근거와 오차를 별도로 제공한다. 이동 후 관측은 매핑 오차를 고려해도 `round2_capture_not_before_monotonic_ns` 이후에 촬영된 영상이어야 한다. ROS timestamp를 monotonic timestamp와 직접 비교하지 않는다.

방향 provider의 `edge_id`는 추적하는 물리 모서리를 식별한다. Step·예약·물리 모서리가 바뀌면 이전 축과 보정 이득을 폐기한다. 캡처 시각이나 모서리 식별자가 없으면 영상 관측을 보류한다. 영상 yaw 정렬은 XY·윗면 기울기·체결 완료의 증거가 아니다.

## HMI와 B 및 저장 연결의 완료 기준

1. 검증된 파지의 `GRIP_SUCCEEDED(label=PICKUP_CLOSE)`는 실행 ID별로 공급 슬롯을 한 번 소모한다.
2. 로봇 또는 사람 작업 뒤 관측 가능한 정지 조건에서 `INSPECTION_REQUIRED`로 B의 STEP 검사를 요청한다.
3. B의 Current·revision·비교 결과를 전달한다. MATCH 뒤에 다음 Step을 진행하고, 관측 불가·오류·불일치는 기존 보류·재검사·C 호출 절차를 따른다.
4. 모든 Step 확인 후 FINAL 검사와 조립 종료 근거가 있어야 저장한다. 저장·웹 실패는 물리 실행을 반복하는 이유가 아니다.
5. STOP 이후 늦은 신호·검사·실행 결과로 다시 진행하지 않는다.

이 후속 작업은 D의 실행 조건과 A 연결 예제를 검증한다. 기존 HMI의 Round2 자동 전환, 실제 RGB-D producer, 모든 블록의 실측 파지·간섭·가압, 충돌·접촉 물리 시뮬레이션은 별도 연결·시험 대상이다.

## 검증과 후속 작업

로봇 검사는 `python3 scripts/test_robot_trial_offline.py`로 장치·외부 연결을 차단한 상태에서 실행한다. A/D 계약 검사는 원본 후보의 경로 검증 통과와 제안 경로의 거부를 모두 확인한다. 새 제안이 원본 승인 ID를 재사용하는 것만으로 실행권을 얻지 않아야 한다.

추가 실물 검사 제거 후 최종 native 검사는 **1,384 passed / 0 failed / 0 errors / 0 skipped**, 종료0(37.01초)다. 명령은 `python3 scripts/test_robot_trial_offline.py -p no:cacheprovider --junitxml=/tmp/round2-d-consistency-no-extra-gates-20261014.xml`이다. 기하/비전190개는 변경 없는 모듈을 앞서 검사한 결과이며, A/D 시스템550 passed/8 failed는 마지막 검사 제거 전 결과다. 이 두 결과를 마지막 수정 뒤의 전체 재실행 결과로 표시하지 않는다.

검토 기준에서 통합 시나리오 8개는 최신 C의 지지 규칙과 이전 입력이 충돌해 실행 전에 실패했다. 동일한 실패가 기준 브랜치에서도 재현됐다. 이 정상·과거 입력 시나리오는 현재 C 계약에 맞춰 별도 정렬하며, 검사를 삭제하거나 지지 규칙을 완화해 통과시키지 않는다.

A가 프로파일 표현과 경로·방법 반환 계약을 확인하면 D의 Round2 dispatch, 기존 진행 이벤트, B 검사·최종 종료·저장 연결을 같은 예제로 검증한다. 이 과정에서 기존 실행 계약을 유지하며 새로운 실물 실행 차단 조건을 추가하지 않는다.
