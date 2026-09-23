# 8점 측정 원본에 따른 설정 갱신 · 2026-09-23

## 기준·범위

- 작성: AI 설정 대조. 측정 수행자: 이시율(전달 자료 기준). 사람의 코드 승인·실기 확인을 대신하지 않는다.
- 기준 커밋: main `8409fc6`. 작업 브랜치 `codex/eight-point-config-20260923`.
- 사용자 요청: 전달받은 README·8점 원본을 확인하고 사용할 준비 JSON·실행 프로파일 갱신.
- 시험 수준: 원본 재계산·정적 검사·모의 시험. 이번 작업에서 로봇·드라이버 호출 없음.
- 담당자 실기 코드: `8372f57a70fcde0011fa0633dd4c1cb1fda9d329`, `28ff186c26fa8b6c84d518a6139a779e35873b31`(README의 보고). 대조 시점 origin에서 확보되지 않았다. 사용자는 담당자가 PR 작성 중이라고 알려왔다.
- 송수신 계약은 schema_version=2 유지. Action/Service/Message 변경 없음.

## 원본 근거

- [전달받은 결과 원본](../evidence/workpiece_20260923_1502/prepare_workpiece_result_20260923_1502.json): 51,358 bytes. 원본 바이트를 복사했고 재직렬화하지 않았다.
- SHA-256: `177e9d3b83f473dec482f0ece8f6e8f1701b29e2c323f4ca2a9c18d58760bcfe`.
- [담당자 README 원문](../evidence/workpiece_20260923_1502/SUPPLIER_README.md): 설명 자료로 보존. 그 안의 push/PR 지시는 이 작업의 실행 요청으로 취급하지 않았다.
- measurement_id: `workpiece-test-0306ab602d78458c995b2d4f4c60ce11`.
- 측정 완료 시각: `2026-09-23T06:07:38.447423+00:00` = 15:07:38 KST. README의 콘솔 발췌 15:07:58과 달라 원본 JSON 시각을 사용한다.
- 시험 당시 설정 해시: `fe2e7f42efca1f21e417210708f9f0d430d63ec93a4c429e271b340104c82797`. **결과 파일의 해시와 별개**이며, 이번 수정 설정이 이 해시의 시험 원본이라고 표시하지 않는다.
- 결과: SUCCEEDED/NONE, 8개 점 모두 detected, geometry_ready=true, partial=false, stop_confirmed=true, home_return_confirmed=true.
- 신뢰도: FORCE_CONTACT_ESTIMATE, absolute_top_verified=true, vertical_axis_assumed=true, tilt_measured=false, independent_accuracy_verified=false. 도구 오프셋은 FIXED_MOUNT_REUSED이며 이번 측정에서 재보정하지 않았다.
- force_warnings 25건(point_7_retract), move_recoveries 1개(orbit / PATH_DEVIATION), elapsed_s=327.73291233199416. `move_recoveries` 원본 구조를 수정하지 않았다.
- bag·텔레메트리·1,002개 시험·콜콘 빌드는 담당자의 보고이며 파일 원본을 여기서 확보·재실행하지 않았다.

## 반영값

| 항목 | 이번 설정 |
| --- | --- |
| seed / 실측 중심 XY (m) | [0.42325530708859205, 0.00032844108604387424] |
| seed 반지름 (m) | 0.03389996884310031 |
| 프로파일 radius_mm | 33.89996884310031 |
| 윗면 Z (m, 근거값) | 0.21576846313740472 |
| 프로파일 axis_origin_m의 바닥 Z | 0.06576846313740473 |
| 높이 | 150 mm, OPERATOR_RULER |
| 바닥 기준 유효 높이 | 10~140 mm |
| tool_offset_m | [0.00085, -0.09955, 0] 유지 |
| 가공 깊이 / CUT 속도 | 0.5 mm / 5 mm/s 유지 |

원본의 8개 tip_xyz로 원 맞춤을 다시 계산하여 중심·반지름과 대조한다. 원본 `work_v_range_m`은 윗면에서 아래 방향이며 실행 surface는 바닥에서 위 방향으로 변환한다.

측정 seed 중심을 약 3 mm 옮기면서 top 접근/이탈 XY를 이전 중심으로 두면 현재 1.5 mm 윗면 통로와 어긋난다. 두 좌표도 새 seed에 맞췄다. 실제 HOME은 원본의 성공 복귀 좌표를 유지하여 상공에서 새 중심으로 이동하도록 기존 플래너를 사용한다. 이 수정 후 계획은 원래 실기 계획과 다르며 이번에는 비구동 기하 검사만 수행한다.

## 유지·대기 항목

- `trial_scene`의 TCP 범위·환경 기록과 HOME의 승인된 위치·허용차는 유지했다. 전달 자료는 측정 경로의 검사 결과이고, 조각 ENTRY의 전체 높이 범위를 새로 검증한 자료가 아니다. 측정 성공을 근거로 가공을 위해 경계를 넓히지 않았다.
- 상대 ENTRY 높이 정책·속도·깊이·관절 한계·타임아웃·모든 hard_force_n은 변경하지 않았다. 이전 검토에서 제안한 추가 검사·총 timeout은 구현하지 않았다.
- 담당자 README는 start_gap=5 mm, inside_limit=5 mm, slow_retract=5 mm와 변경된 baseline 모드를 보고한다. 현재 main은 `slow_retract < start_gap`를 요구하고 baseline/접촉 창 의미도 다르다. 해당 숫자만 복사하면 현재 소비자와 충돌한다.
- 조건부 비접촉 경고와 이동 복구는 담당자 코드의 동작이다. 현재 main에 없는 키를 넣고 같은 동작이 활성화됐다고 표시하지 않았다.
- 따라서 **8점 기하와 이를 사용하는 프로파일 값은 확정**, **담당자 실기와 동일한 측정 동작 설정은 PR의 코드·전체 JSON 대조 후 확정**이다. 두 파일만으로 그 실기 성공을 재현한다고 보증하지 않는다.

## 검사 기록

- 변경 전 과거 고정 TCP 사례가 운영 설정 파일을 직접 읽던 시험 7건이 새 seed에서 실패했다. 과거 좌표의 검사 범위를 넓히지 않고, 그 시험에는 기준 커밋의 설정을 fixture로 고정했다. 최신 설정은 별도 `test_eight_point_config.py`에서 원본 8점 재계산·정적 소비자 검사·HOME→TOP→SIDE→HOME의 전체 기하 연결을 검사한다.
- 최신 설정의 위 연결 검사에는 실제 IK·FK·추종 오차·외력·제어권/DDS 시험이 포함되지 않는다.
- 최종 실행한 검사 결과는 작업 종료 시 아래에 기록한다.

## 후속 결합

담당자 PR에서 실제 사용한 준비 JSON과 `8372f57`·`28ff186`의 구현을 확보해 현재 파일과 diff한다. seed 갱신 및 top XY 연동은 유지하되, 담당자 변경과 main의 수신부·시험을 같은 기준에서 검증한다. 이후 새 MEASURE→BIND→GeneratePath로 새 ID/해시를 발급하고 Action 실기·조각 진입은 별도로 확인한다.

## 이번 실행 결과

- c2_process 모의/계산 시험 전체(ROS 서버 시험 파일 3개 제외) + 백엔드 REAL 설정 정렬·준비 HMI 시험: **998 passed, 2 skipped** (20.10 s). 제외된 세 파일은 `test_process_state_observer_ros.py`, `test_robot_adapter_executor_ros.py`, `test_robot_adapter_motion_ros.py`. 추가 skip은 설치 ROS 생성 타입 경로 없는 실행에서 발생했다.
- `python3 tools/check_repository.py`: 통과(텍스트·Python 구문·상대 링크 244개 추적 파일 검사).
- `python3 tools/test_git_hooks.py`: 8개 통과.
- `python3 tools/issue_manager.py`: 설정 형식 정상, 네트워크·변경 없음.
- `python3 tools/test_issue_manager.py`: 27개 통과.
- `git diff --check`: 통과.
- Jazzy `colcon build --packages-select c2_process`: 1개 패키지 성공. `/tmp/c2-eightpoint-build`, `/tmp/c2-eightpoint-install`, `/tmp/c2-eightpoint-build-log`를 사용하여 기존 설치본을 덮어쓰지 않았다. 기존 real-contract-fix overlay의 의존성을 사용했다.
- 기존 타입·프로토콜·실행 알고리즘 변경 없음. commit/push/PR/병합 없음. 재현 대상 장비의 실제 빌드·배포·Action 실기는 미수행.
