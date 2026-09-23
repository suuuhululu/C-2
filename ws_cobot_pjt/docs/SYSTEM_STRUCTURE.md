# 새김 시스템 구조와 코드 책임

기준: `main` `b9eb003` (2026-09-23, PR #80 병합). 현재 코드의 구조를 설명한다. 장치·실기 검증의 범위는 [인터페이스 안내](INTERFACE_GUIDE.md)와 관련 시험 기록을 따른다.

```text
운영자 React HMI
  └─ HTTP·WebSocket ─ FastAPI 서버/SQLite·관리 파일
                         └─ monitor_gateway_node (rclpy 클라이언트)
                              ├─ /c2/prepare_workpiece ─ process_controller_node
                              ├─ /c2/generate_path ──── path_planner_node
                              └─ /c2/execute_process ─ process_controller_node
                                    └─ robot_adapter ─ 외부 두산 드라이버 ─ M0609
```

`/c2/stop_process` Service와 `/c2/process_state`·`/c2/process_events` Topic도 게이트웨이와 공정 노드 사이에 있다. 세 팀 노드는 `monitor_gateway_node`, `path_planner_node`, `process_controller_node`이며, 내부 Python 파일 수가 ROS 노드 수를 늘리지 않는다. **모든 로봇 모션의 공정 소유권은 `c2_process`에 있다.**

## 위치·담당·실제 역할

| 위치 | 주 담당 | 코드와 역할 |
| --- | --- | --- |
| `frontend/src/monitor/` | 이수현 | `Monitor.tsx`의 입력·미리보기·실행·상태 화면, `PreparationPanel.tsx`의 준비·측정·REAL 제어기 관측/수동 확인, `api.ts`의 HTTP·WS 계약. 드릴 ON은 화면 수동 확인만 한다. |
| `backend/app/` | 이수현 | `monitor.py` HTTP/WS, `monitor_service.py` 요청 순서·실행 게이트, `preparation.py` 측정 원본·스냅샷·BIND, `hardware_snapshot.py` REAL 읽기 관측, `real_execution_config.py` 배포 설정 정적 검사, `storage.py` SQLite/파일, `ros_bridge.py` ROS 변환·클라이언트, `artifact_loader.py` 산출물 검사. |
| `ws_cobot1/src/c2_interfaces/` | 팀 공통 계약 | `GeneratePath`, `ExecuteProcess`, `PrepareWorkpiece` Action 3개, `StopProcess` Service 1개, `ProcessState`, `ProcessEvent` Message 2개. 정확한 필드는 실제 `.action`·`.srv`·`.msg`가 원본. |
| `ws_cobot1/src/c2_path/` | 노홍동 | 관리 이미지·스냅샷을 읽어 중심선/해칭→2D→원통 3D 드릴 끝 경로·미리보기·기하 검증. Action 서버는 `node.py`; 로봇은 구동하지 않음. |
| `ws_cobot1/src/c2_process/` | 김세은·이시율 | Action/Service/Topic 공정 노드, 상태·준비·사전 검사·관절 검사, 측정·조각·로봇 어댑터. `setup.py`의 SIM/REAL 실행 엔트리 존재. 실기 전체 공정 검증과는 별개. |
| `ws_dsr/src/` | 실행 PC의 공급자 환경 | 외부 두산·그리퍼 드라이버 원본은 별도 설치. 이 저장소에는 제어권 관측 패치 4개 파일만 추적하며 실행 PC의 원본·설치본·버전을 따로 확인. |

## 경로 생성 내부

| 파일 | 기능 |
| --- | --- |
| `node.py` | `/c2/generate_path` Action, 진행·취소·동시 요청·모드 파라미터 |
| `pipeline.py`, `artifacts.py` | 계산 단계·설정 계약 검사, UUID→관리 파일 조회·해시 확인, 결과 원자적 등록 |
| `image_to_svg.py`, `image_to_hatch.py`, `extract_2d.py`, `optimize_2d.py` | 중심선/해칭 SVG, 2D 획 추출·배치·방문 순서 |
| `map_3d.py`, `generate_path.py`, `validate_path.py`, `readiness.py` | 원통 매핑, 접근/CUT/이동/이탈 pose7 경로, 기하·잠정 작업 범위 검사 |
| `snapshot.py`, `workcell.py` | 요청별 표면 설정 연결과 시험 상수. `workcell.py`는 승인된 REAL 설정 원본이 아님. |

기본 경로 노드는 `SIMULATION/test_only`다. `allow_real_preview:=true`는 REAL 추정값 `/3` 미리보기 전용이며 여전히 `test_only`다. `allow_real_execution:=true`는 별도 REAL 실행 계약·BIND·설정/범위가 맞을 때 `test_only=false`, `real_execution_allowed=true` **실행 후보**를 만든다. 실제 실행 가능 판정은 공정 노드의 최종 검사다. 상세 조건은 [c2_path README](../ws_cobot1/src/c2_path/README.md)를 따른다.

## 공정 내부

| 파일 | 기능 |
| --- | --- |
| `node.py` | `/c2/prepare_workpiece`, `/c2/execute_process` Action, `/c2/stop_process` Service, 상태·이벤트 Topic. 요청 중복 방지·모션 소유권·실행 파일 로딩·최종 검사 연결. |
| `preparation_action.py` | `MEASURE`와 이동 없는 `BIND_SNAPSHOT`, 측정 원본·스냅샷의 ID/해시·기하·신뢰도 대조. |
| `state_machine.py`, `preconditions.py` | 준비 단계/준비 후 실행 순서, 현재 모드·상태·제어권·경로/스냅샷 무결성 검사. 이전 직접 실행 경로도 별도 존재. |
| `joint_check.py` | 실행계획의 **모든 명시 waypoint** IK, 관절 범위·J6 여유 검사. 점 사이 연속 충돌 검증은 아님. |
| `entry_planner.py` | 현재/HOME에서 첫 APPROACH까지의 상공 entry 후보 생성, 실제 IK·관절/J3/J5·보간 변화·단순 원통 간격 검사, 선택 계획 해시 고정·실행. 전체 메시 충돌 검사는 아님. |
| `workpiece_calibration.py` | 필요 시 검사된 홈 이동과 재관측, 윗면·옆면 8점 접촉, 중심·반지름 계산, 정상 후퇴/홈 결과. #75는 옆면 접촉 구간 분리와 복구 가능한 점 오류의 제한 재측정을 추가. 높이는 운영자 자 측정, 수직 축은 가정. |
| `measurement_robot_adapter.py` | 측정 단계의 실제 로봇 관측·접촉 실행, baseline/접촉 구간 감시와 사전 검사. 공중 이동 일부의 IK 표본 간격 조절은 실기 간섭 검사 완료가 아님. |
| `tool_calibration.py` | 장착된 드릴 끝 보정·기존 기준 확인. 양초 위치 측정과 별개. |
| `engraving.py` | 검사된 계획의 접근·CUT·이탈/이동 실행, 취소·진행·결과. `cut_contact` 설정에 따라 법선 힘 유지 또는 묶음별 offset 조정 코드와 검사형 `return_home()`이 있으나, 그 동작의 실기 검증과 준비 후 자동 복귀 연결은 별도다. |
| `robot_adapter.py` | 실제 장치 관측·이동·접촉·IK·정지, 도구 끝↔제어기 TCP 및 두산 단위 변환. `controller-prefix`로 서비스와 `<prefix>/control_authority` Topic을 정한다. |

`c2_process/setup.py`에는 `process_controller_node`(SIM), `real_preparation_node`(REAL 측정 전용), `real_process_node`(REAL 준비·조각), `virtual_cell_node` 엔트리가 있다. `run_monitor.py`는 공정 노드·두산 드라이버를 기동하지 않는다. `c2_process/launch/process.launch.py`, 실행용 `config/workcell.yaml`·`config/tools.yaml`은 이 커밋에 **없다**. 설정은 현재의 관리 JSON·배포 설정·공정 CLI 경로로 확인한다. [공정 README](../ws_cobot1/src/c2_process/README.md)와 [ROS 실행 안내](../ws_cobot1/doc/README.md)에 현재 진입점을 정리한다.

## 순서와 검증 경계

1. REAL의 HMI는 기동 시와 준비 직전 제어기를 읽기 전용 조회해 hardware snapshot을 저장하고, 자동 조회 불가 항목은 준비 화면에서 사람이 확인한다. 이 값은 드릴 ON 센서나 실물 고정 검증을 대신하지 않는다.
2. `MEASURE`가 상태/필요 시 홈·재검사 뒤 양초를 측정한다. 서버는 원본을 저장하고 별도 불변 스냅샷에 실측 기하·가정·신뢰도를 묶는다. 유효한 REAL 실행 설정이 없으면 미리보기 전용 스냅샷으로 남긴다.
3. 유효한 실행 설정이 있을 때 `BIND_SNAPSHOT`이 같은 측정과 설정의 일치를 확인한다. 이후 `GeneratePath`가 경로·미리보기를 생성하고 운영자가 확인한다.
4. `ExecuteProcess`는 별도 요청이다. HMI와 공정이 모드·현재 준비·경로/설정 ID·버전·해시·상태를 검사한다. prepared 공정은 `PRECHECK → ENTRY → ENGRAVE → FINISH`로 진행하며, 승인된 entry 정책과 실측 기하로 현재/HOME에서 첫 APPROACH까지의 계획을 먼저 확정한다. 이어 깊이·접근·이탈이 반영된 본 실행계획의 명시 waypoint IK/관절 검사를 통과한 경우에만 같은 계획으로 조각한다.
5. 취소·StopProcess의 접수와 실제 정지는 구별한다. 정지 미확인 `UNKNOWN`은 새 작업을 차단한다. 실기 전체 왕복·품질 검증을 완료로 표시하지 않는다.

경로는 `c2_base`의 **드릴 끝** pose, 위치 m·quaternion xyzw다. 2D 입력·표시는 mm/deg, 관절은 rad다. 두산 서비스의 단위 변환은 어댑터에만 둔다. 철사로 고정한 드릴을 위한 그리퍼 열기·집기·반납·청소 명령은 현재 공정에서 제외한다. 이력·미검증 범위는 [21일 일지](daily/2026-09-21.md), [22일 일지](daily/2026-09-22.md), [가상 장치 시험](VIRTUAL_CELL_20260922.md)에 날짜와 함께 남긴다.
