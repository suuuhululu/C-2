# 새김 ROS·파일 인터페이스 기준 · 고정 드릴 v2

기준: `main` `b9eb003` (2026-09-23, PR #80 병합). 이 문서는 현재 코드의 통신·단위·실행 게이트를 읽기 위한 안내다. **필드·자료형의 원본은 같은 커밋의 [`c2_interfaces`](../ws_cobot1/src/c2_interfaces/README.md) `.action`·`.srv`·`.msg` 파일**이며, 이 표로 별도 타입을 만들지 않는다. ROS 2 Jazzy와 M0609를 기준으로 한다. 이력은 날짜별 [일지](daily/)와 [9/19 운영 결정](C2_FIXED_DRILL_20260919.md)에 보존한다.

## 1. 통신 경계

| 이름 | ROS 타입 | 호출/발행 → 처리/구독 |
| --- | --- | --- |
| `/c2/prepare_workpiece` | `c2_interfaces/action/PrepareWorkpiece` | 모니터 게이트웨이 → 공정 제어. `MEASURE`·`BIND_SNAPSHOT` |
| `/c2/generate_path` | `c2_interfaces/action/GeneratePath` | 모니터 게이트웨이 → 경로 생성 |
| `/c2/execute_process` | `c2_interfaces/action/ExecuteProcess` | 모니터 게이트웨이 → 공정 제어 |
| `/c2/stop_process` | `c2_interfaces/srv/StopProcess` | 모니터 게이트웨이 → 공정 제어, 정지 접수 |
| `/c2/process_state` | `c2_interfaces/msg/ProcessState` | 공정 제어 → 모니터 게이트웨이, 최신 상태 |
| `/c2/process_events` | `c2_interfaces/msg/ProcessEvent` | 공정 제어 → 모니터 게이트웨이, 사건 기록 |

`monitor_gateway_node`는 `backend/app/ros_bridge.py`의 rclpy 클라이언트다. 화면은 HTTP·WebSocket으로만 서버와 통신한다. `path_planner_node`는 파일과 기하 계산만 수행하고 모션을 내리지 않는다. `process_controller_node`가 공정 모션의 단일 소유자다. 측정·보정·조각의 Python 내부 함수에는 중간 ROS 통신을 추가하지 않는다.

## 2. 공통 데이터·단위

| 항목 | 현재 계약 |
| --- | --- |
| `schema_version` | 고정 드릴 팀 계약 `2` (`uint16`). ROS Jazzy 버전·패키지 버전·경로 버전과 별개. 타입 정의가 다르면 숫자만 같아도 호환되지 않음. |
| `request_id`, `run_id` | 문자열 식별자. 서버는 같은 논리 요청의 재전송을 기존 기록과 연결하며 공정은 같은 요청의 중복 모션을 막음. 새 실행 시도에는 새 `run_id`. |
| `path_id/version/sha256` | 불변 경로의 관리 ID, `uint32` 버전, **파일 원본 바이트** SHA-256. 설정·측정 원본도 관리 ID/해시로 연결. |
| `source_mode` | `SIMULATION` 또는 `REAL`. Goal, 스냅샷, 경로, 실행 노드의 모드가 일치해야 함. 요청 문자열만 바꿔 실기 활성화 불가. |
| `frame_id`·3D | 경로는 `c2_base` 기준 **드릴 끝** pose. 위치 m, 정규화 quaternion `(x,y,z,w)`. 관절 rad. `ProcessState.tcp`는 제어기 TCP 관측이므로 경로 waypoint와 구별. |
| 2D·화면 | 도안 크기·배치 mm, 회전 deg. 양초 준비 Result의 길이 m. `work_v_range_m`은 **윗면에서 아래로**이고 경로의 `surface.valid_v_range_mm`은 **바닥에서 위로**이므로 높이 H에 대해 `[H-v_max, H-v_min]`을 mm로 변환. |
| 두산 경계 | 도구 끝→제어기 TCP·서비스 단위/자세 변환은 `c2_process/robot_adapter.py` 한 곳에서 처리. 두산 서비스의 관절 각도 규약을 팀 경로의 rad와 혼용하지 않음. |
| 시각·품질 | ROS 절대 시각은 `builtin_interfaces/Time`, HMI/DB는 UTC RFC3339. 미확인 시각은 0/0 또는 JSON null. 상태 heartbeat와 실제 측정 시각을 분리하고 `VALID/STALE/UNKNOWN/UNSUPPORTED`를 보존. |
| 결과·정지 | `error_code=NONE`은 정상 결과. Goal 접수, 모션 완료, 실물 가공 성공은 다름. StopProcess 응답의 `accepted`는 실제 정지 완료가 아님. 정지 미확인은 `UNKNOWN`으로 남김. |

그리퍼에 철사로 고정한 도구는 `engraving_drill`이다. 고정 중 그리퍼 열기·자동 집기·청소·반납을 호출하지 않는다. `GripperDA_v1`은 제어기 TCP로, 도구 끝 waypoint와 같은 점이 아니다. REAL 측정 설정의 load는 `ToolWeight_1`과 일치해야 한다. 실제 장비·배선·그리퍼 모델은 확인된 현장 설정에 따른다.

## 3. 준비·측정과 BIND

`PrepareWorkpiece.Goal`은 `operation`, 요청/준비/측정 ID, 모드, 입력 설정 ID/해시를 갖는다. `BIND_SNAPSHOT`에는 추가로 측정 원본 ID/해시와 최종 스냅샷 ID/해시가 필요하다. `MEASURE`에서는 이 네 결과 참조를 비워 둔다.

- `MEASURE`: 공정은 최신 상태·제어권·정지 래치·모션 소유권과 설정을 확인한다. 필요 시 검사된 홈 이동·정지/도착 재관측을 거쳐 윗면과 옆면 8점을 접촉 측정하고 정상 후퇴·홈을 확인한다. #75의 REAL 옆면 접촉 구간 검사는 baseline과 접촉 후보를 분리하며, `side_point_max_attempts`는 최초 포함 1~3회다. 복구 가능한 한 점 오류만 정지 확인·검사된 후퇴 후 재시도하고 힘 한계·통신/정지 미확인은 재시도하지 않는다. 결과는 `outcome`, `stop_confirmed`, `partial`, `geometry_ready`, `validity`, 측정 위치/반지름/작업 범위/접촉 원본을 담는다. 높이는 운영자 자 측정, 수직 축은 가정이며 `ESTIMATED`를 독립 정밀도 검증으로 읽지 않는다. `absolute_top_verification_known`과 `absolute_top_verified`를 원본 그대로 전달한다.
- 서버는 성공 결과를 원본 파일에 저장하고 측정값·출처·가정·도구/가공 설정을 새 불변 스냅샷에 조립한다. 유효한 REAL 실행 설정이 없거나 잘못되면 측정은 진행할 수 있지만 **미리보기 전용** 스냅샷만 만들고 BIND·조각은 진행하지 않는다. 측정 설정과 실행 설정은 작업자 JSON 업로드가 아닌 배포 설정이다.
- `BIND_SNAPSHOT`: 공정은 저장 원본이 자신의 직전 성공 측정 Result와 같은지, 준비/측정 ID·설정 ID/해시·기하·신뢰도·도구/TCP/load가 맞는지 검사한다. 이 작업은 로봇을 움직이지 않는다. 성공한 `snapshot_bound=true`는 **연결 확인**이며 경로 실행 승인이나 측정 정확도 증명이 아니다. 다른 내용으로 기존 BIND를 덮어쓰지 않는다.
- REAL HMI는 기동 및 준비 직전에 제어기를 **읽기 전용** 조회해 `c2-hardware-observation/1`을 파일로 저장한다. 현재 TCP/load, AUTO/REAL·STANDBY/정지, 관절·TCP 등을 확인한다. 고정 설비, 그리퍼/드릴 체결, 드릴 OFF, 이동 경로, 지속 감시는 자동 조회 불가 항목으로 준비 화면에서 사람이 한 번 확인한다. 이 수동 확인은 PrepareWorkpiece ROS Goal의 센서 bool이 아니며, 드릴 ON 화면 체크와도 다르다. REAL 실행 전에는 준비 시 확인과 저장된 관측 파일의 무결성을 다시 대조한다.

## 4. GeneratePath와 경로 파일

`GeneratePath.Goal`은 이미지 `asset_id/sha256`, 도안 크기·배치·회전, 변환 preset, 도구 ID, 프로파일 스냅샷 ID/해시를 받는다. 결과는 경로 ID/버전/해시, SVG·미리보기·검증 보고서 ID와 검증 통과 여부를 준다. 피드백은 단계·진행률이다. 실패·취소 시 실행 가능한 새 경로를 공개하지 않는다.

경로 파일에는 `schema_version`, 모드, 이미지·프로파일 ID/해시, 도구·좌표계, 순서가 고정된 `APPROACH`/`CUT`/`TRAVEL`/`RETRACT` 구간과 도구 끝 waypoint가 있다. 접근·이탈도 실제 경로 구간이다. 경로의 `validation_passed`는 기하·형식 검사 결과이며 로봇 IK·충돌이나 실물 홈 깊이의 합격을 뜻하지 않는다. 미리보기·검사·실행에는 같은 경로 식별자와 파일 바이트를 사용한다.

| 설정 경로 | 생성 결과와 제한 |
| --- | --- |
| SIMULATION `/1`·`/2` | 모의/시험용 `test_only` 경로. `/2`는 요청별 원통 기하를 사용. |
| REAL 추정값 미리보기 `/3` | `allow_real_preview:=true`가 필요. 결과는 `test_only`; 실행 불가. |
| REAL 실행 후보 계약 | `allow_real_execution:=true`와 이번 준비 BIND, 절대 기하·접촉 오프셋 출처, 실행/관절/도구 설정, 작업 범위 검사를 요구. 통과 시 `test_only=false`, `real_execution_allowed=true`. `executability=NOT_JUDGED`는 유지. |

REAL 경로 서버도 로봇을 움직이지 않는다. `ESTIMATED`·`absolute_top_verified=false` 자체는 경로 후보 생성의 일괄 거절 근거가 아니지만, 원본 신뢰도와 출처는 변경하지 않는다. 작업 범위 밖·실행 금지 설정·미리보기 전용 결과는 공정 요청으로 승격하지 않는다. 관련 구현 조건은 [경로 README](../ws_cobot1/src/c2_path/README.md)를 따른다.

## 5. ExecuteProcess와 공정 검사

`ExecuteProcess.Goal`은 `request_id`, `run_id`, `source_mode`, `path_id/version/sha256`, `operator_confirmed_fixture`, 서버가 기록한 `operator_id/confirmed_at`을 받는다. **드릴 ON bool은 없다.** 드릴 ON은 운영자의 수동 전원 절차에 대한 HMI 화면 확인이며 공정 제어의 센서 신호·전원 인터록이 아니다. `operator_confirmed_fixture`도 공작물 고정에 관한 별도 운영자 확인이다.

HMI는 최신 상태, 준비 성공과 BIND, 동일 스냅샷·경로·미리보기, 파일 해시, REAL 후보 표시를 대조한다. 공정 노드는 모드·경로/설정 원본 바이트, 도구·프레임·상태·제어권, 정지 래치, 실행 설정을 다시 검사한다. 깊이·접근·이탈을 적용한 실행계획의 **모든 명시 waypoint**에 IK·관절 한계·J6 여유 검사를 수행하고, 검사한 계획과 실행 계획을 연결한다. 점 사이 연속 충돌·특이점 전체 보증이나 힘 유지 중 실제 위치의 IK 연속 증명은 아직 아니다.

준비 후 실행 경로의 상태 기계는 `PRECHECK → ENTRY → ENGRAVE → FINISH`다. `PRECHECK`는 배포 실행 프로파일의 `execution_context.entry_planning`과 이번 측정 스냅샷의 기하를 결합해 현재/HOME에서 첫 APPROACH까지의 후보를 읽기 전용 IK와 관절·간격 검사로 확정하고 해시로 고정한다. `ENTRY`는 검사된 동일 계획만 실행한다. 정책의 높이는 실측 `top_z_m`에 대한 상대 여유이므로 양초의 절대 표면 좌표를 고정하지 않는다. 기존 직접 실행 경로에는 `TOOL_CHECK`, 시작 이동·홈 복귀 콜백도 남아 있으므로 두 호출 경로를 혼동하지 않는다. #74의 `normal_force_hold`·`chunk_adaptive` CUT, 힘 관측·검사형 `return_home()` 코드는 설정이 있을 때만 사용되며 실제 힘 유지 중 MoveSX 수락, 연속 도달성, 전체 홈 복귀 실기는 미검증이다. `return_home()`을 준비 후 실행에 자동 연결했다고 기록하지 않는다. 세부 범위는 [공정 README](../ws_cobot1/src/c2_process/README.md)를 따른다.

결과 `outcome`은 `SUCCEEDED/FAILED/STOPPED/UNKNOWN`; 진행률·마지막 구간·로그 ID는 실물 가공 품질이 아니다. 동일 `request_id`의 같은 내용은 재실행하지 않고 다른 내용은 충돌로 거절한다. 통신·모션 결과가 미확인되면 성공으로 바꾸거나 새 경로/작업을 자동 시작하지 않는다.

## 6. 정지·상태·QoS

`StopProcess`는 `request_id/run_id/reason`을 받고 `accepted/stop_state/error_code/message`로 **접수 결과**를 돌려준다. Action 취소도 공정의 정지 경로를 사용한다. 실제 정지 확인은 ProcessState와 Action 결과를 본다. 실패·미확인 뒤 자동 보호정지 해제, 그리퍼 열기, 경로 재개·자동 홈을 하지 않는다.

`ProcessState`는 발행자 epoch/seq, 공정 상태·단계, 실행/경로 식별자, 정지·오류, 도구/그리퍼 관측, 관절·TCP·온도·로봇 상태의 품질/측정 시각을 담는다. `ProcessEvent`는 event ID/seq와 발생 시각·단계·오류·경로/설정 참조를 담는다. `state`는 reliable/volatile/keep-last 1, `events`는 reliable/volatile/keep-last 100으로 생성한다. Topic heartbeat가 오래된 센서값을 새 측정으로 바꾸지 않는다. 서버는 event ID로 중복을 제거한다.

## 7. HMI API와 배포

주요 API는 `/api/operator/preparations`, `/api/operator/assets`, `/api/operator/path-generations`, `/api/operator/runs`, `/api/operator/inspections`, `/api/operator/snapshot`, `/api/operator/stream`이다. HTTP 202 접수, ROS Goal 수락, 실제 공정 완료를 다른 상태로 다룬다. HMI는 좌표 생성·로봇 모션을 직접 하지 않는다. 관리 파일은 브라우저 임의 절대 경로가 아닌 서버 UUID로 조회하고 원본 바이트 해시를 재확인한다.

기본 `run_monitor.py`는 SIMULATION/MOCK이다. ROS SIM 연결에는 같은 checkout의 타입·경로·공정 빌드가 필요하다. REAL HMI는 `--transport ros --mode REAL --preparation-config`를 사용한다. 측정·미리보기만 할 때 실행 프로파일은 생략할 수 있지만, BIND와 실제 실행 후보 생성에는 `--execution-profile`이 필수이며 `execution_context.entry_planning`까지 사전 검사를 통과해야 한다. 검사는 파일을 수정하지 않는다. 양초 중심·반지름·윗면 등 작업별 기하는 측정 결과로 새 스냅샷에 기록되고, 실행 프로파일은 속도·깊이·관절 한계·상대 entry 정책처럼 사전에 승인한 값만 제공한다. `run_monitor.py`는 HMI·서버·경로 노드를 시작하지만 공정 노드·두산 드라이버는 별도다. REAL 공정 노드의 `--controller-prefix`가 측정/실행 서비스와 `<prefix>/control_authority`를 함께 정한다. 공정 노드 namespace remap을 임의로 더하지 않는다. 현재 실행 옵션은 [백엔드](../backend/README.md)와 [ROS 실행](../ws_cobot1/doc/README.md) 안내를 따른다.

현장 속도·깊이·힘·관절 한계·TCP·하중·정지 기한은 배포 설정과 장치에서 확인한다. 저장소의 단위 시험용 숫자는 실행 승인값이 아니다. 이 커밋의 가상 장치/대역 시험과 REAL 연결 소스는 **실제 M0609 전체 측정→조각의 실기 성공 증거가 아니다.** [가상 장치 기록](VIRTUAL_CELL_20260922.md), [실기 시행착오](LESSONS_ROBOT.md)에 시험한 범위를 구분한다.
