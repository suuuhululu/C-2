# 시스템 모니터·좌표 생성·공정 제어 디렉토리 구조

2026-09-18 사용자 수정사항을 반영한 현재 설계다. 고객 웹앱 없이 운영자가 시스템 모니터에서 이미지와 설정을 입력하고 경로를 확인한 뒤 실행을 요청한다. 그리퍼는 한 장치로 고정하고, 그리퍼가 잡는 도구가 바뀌는 조건이다. 작업대와 작업대상의 기준 좌표는 고정되어 있으며, 매 작업마다 위치를 탐색·추정하는 공정은 두지 않는다.

팀에서 개발할 노드는 `monitor_gateway_node`, `path_planner_node`, `process_controller_node`의 3개다. ROS 패키지는 공통 인터페이스 `c2_interfaces`와 기능 패키지 `c2_path`, `c2_process`의 3개다. 모니터 노드는 백엔드에 개발할 ROS 연결 모듈에 둔다. 두산 및 필요한 장치 공급자 드라이버는 팀 노드 수와 별개다.

아래는 **구현 목표 디렉토리와 파일**이다. 세 패키지의 [개발 폴더](../ws_cobot1/src/README.md)는 README·`.gitkeep`으로 준비했으며, 아래의 빌드 설정·Python 모듈·메시지·설정 파일은 아직 구현 대상이다. 폴더가 있다는 이유로 빌드·실행 가능한 ROS 패키지로 취급하지 않는다. 2026-09-18 후속 작업에서 `robot_adapter.py`와 시험 소스가 추가됐고, 기존 Clay 코드·실행 안내는 사용자 요청으로 로컬 보관 후 제거했다. [현재 draw.io 아키텍처](architecture/README.md)와 [보관·복구 기록](LEGACY_CLAY_ARCHIVE.md)을 참고한다. 9/17 [시스템 아키텍처](SYSTEM_ARCHITECTURE.md)의 고객 웹앱을 포함한 기능 배치는 이번 축소 설계로 갱신한다.

## 디렉토리

```text
ws_cobot_pjt/
├── frontend/
│   └── src/
│       ├── main.tsx                      # 모니터 화면 진입
│       ├── Operator.tsx                  # 이미지·설정 입력, 미리보기, 실행 요청, 상태·검사
│       └── api.ts                        # HTTP 요청·WebSocket 수신
│
├── backend/
│   └── app/
│       ├── main.py                       # 서버 실행·업로드·설정 입력
│       ├── gateway.py                    # 경로 생성·실행·정지 API
│       ├── ros_bridge.py                 # monitor_gateway_node
│       └── storage.py                    # 원본·경로·실행·알람·검사 기록
│
├── ws_cobot1/
│   ├── doc/
│   │   └── README.md                     # ROS 실행·설정·검증 기록
│   └── src/
│       ├── c2_interfaces/                # 통신 형식, 실행 노드 없음
│       │   ├── package.xml
│       │   ├── CMakeLists.txt
│       │   ├── action/
│       │   │   ├── GeneratePath.action
│       │   │   └── ExecuteProcess.action
│       │   ├── srv/
│       │   │   └── StopProcess.srv
│       │   └── msg/
│       │       ├── ProcessState.msg
│       │       └── ProcessEvent.msg
│       │
│       ├── c2_path/
│       │   ├── package.xml
│       │   ├── setup.py
│       │   ├── setup.cfg
│       │   ├── resource/
│       │   │   └── c2_path
│       │   └── c2_path/
│       │       ├── __init__.py
│       │       ├── node.py               # path_planner_node
│       │       ├── image_to_svg.py       # 이미지 정규화·SVG 변환
│       │       ├── extract_2d.py         # SVG → 2D 좌표
│       │       ├── optimize_2d.py        # 좌표·작업선 순서 최적화
│       │       ├── map_3d.py             # 표면·로봇 좌표계 변환
│       │       ├── generate_path.py      # 공구 자세·접근·가공·이탈 경로
│       │       └── validate_path.py      # 경로 검증
│       │
│       └── c2_process/
│           ├── package.xml
│           ├── setup.py
│           ├── setup.cfg
│           ├── resource/
│           │   └── c2_process
│           ├── c2_process/
│           │   ├── __init__.py
│           │   ├── node.py               # process_controller_node
│           │   ├── state_machine.py      # 공정 순서·상태 전이
│           │   ├── preconditions.py      # 준비 조건·경로·도구 설정 검사
│           │   ├── robot_adapter.py      # 두산 드라이버 호출·결과 확인
│           │   ├── gripper_adapter.py    # 고정 그리퍼 제어·파지·해제 확인
│           │   ├── tool_sequence.py      # 도구별 집기·반납 순서
│           │   ├── engraving.py          # 생성된 경로에 따른 조각 실행
│           │   └── cleaning.py           # 뭉침 제거 순서
│           ├── config/
│           │   ├── workcell.yaml         # 작업대·작업대상 고정 좌표·형상·연결 설정
│           │   └── tools.yaml            # 도구별 파지·TCP·하중·가공·청소 설정
│           └── launch/
│               └── process.launch.py     # 좌표·공정 노드 실행
│
├── ws_dsr/
│   └── src/                             # 외부 cobot_rg2 원본, 로컬 전용·Git 제외
│                                        # 두산·그리퍼 드라이버는 확인된 원본 구조 유지
│
└── docs/
    ├── INTERFACE_GUIDE.md                # 팀 협업용 전체 흐름·통신 개념
    ├── SYSTEM_STRUCTURE.md               # 목표 디렉토리·역할 정의
    └── INTERFACE_RECOMMENDATION.md        # 통신 필드·완료 조건 권장안
```

`c2_process`의 `setup.py`에서 launch·config도 설치 대상으로 포함한다. 백엔드가 자신의 실행 과정에서 모니터 ROS 노드를 구동하며, `process.launch.py`는 좌표·공정 노드를 구동한다. 공급자 드라이버는 `ws_dsr`의 확인된 실행 절차를 따른다. 각 워크스페이스의 build/install/log는 분리한다.

이미지 변환 구현은 `c2_path/image_to_svg.py`에 모으는 설계다. 기존 알고리즘을 재사용할 때는 입력·출력과 단위를 이 계약에 맞춰 검증한다. 백엔드는 파일 수신·보관과 요청 전달을 담당하며 좌표 계산을 중복 구현하지 않는다. 외부 드라이버 배치는 [의존성 기록](../../docs/DEPENDENCIES.md)을 따른다.

## 노드별 역할

| 노드 | 위치 | 담당 기능 | 주요 결과 |
| --- | --- | --- | --- |
| `monitor_gateway_node` | `backend/app/ros_bridge.py` | 화면 요청을 ROS 호출로 연결, 경로 결과·공정·장비 상태 수집, 서버의 저장·화면 전달 기능에 연결 | 경로 미리보기, 진행·알람·결과 |
| `path_planner_node` | `c2_path/node.py` | 이미지 → SVG → 2D 추출·최적화 → 표면 3D 변환 → 선택 도구에 맞는 실행 경로 생성·검증 | SVG, 미리보기 데이터, 경로 ID·버전·해시·검증 결과 |
| `process_controller_node` | `c2_process/node.py` | 준비·버전·도구 조건 검사, 로봇·그리퍼 제어, 집기·가공·청소·반납, 완료·실패·정지 처리 | 공정 상태, 파지 상태, 실행 결과·로그 |

모니터 화면은 입력·표시·요청을, 공정 제어는 실행 여부와 작업 순서를 책임진다. 공정 제어의 내부 모듈은 별도 ROS 노드가 아니다. 긴 이동이나 그리퍼 피드백을 기다리는 중에도 상태 발행·통신 감시·정지 처리가 계속 가능하도록 구성한다.

## 공정 제어 내부의 기능 분리

| 모듈 | 담당 범위 |
| --- | --- |
| `state_machine.py` | 준비 → 도구 집기 → 조각 → 필요한 청소 → 반납 → 완료의 전체 순서를 관리하고 단계 결과에 따라 진행·중단한다. |
| `gripper_adapter.py` | 그리퍼 자체의 열기·닫기 명령과 피드백 확인을 담당한다. 로봇팔의 보관대 접근·이탈 이동은 담당하지 않는다. 실제 피드백·신선도·제한 시간·실패를 확인한다. |
| `tool_sequence.py` | 도구를 집고 놓는 복합 작업을 담당한다. `robot_adapter.py`로 접근·정렬·이탈하고 `gripper_adapter.py`로 열기·닫기·파지·해제를 확인한다. 장착 전후 TCP·하중 전환도 이 순서에서 처리한다. |
| `engraving.py` | 확정된 실행 경로의 접근·가공·이탈 구간을 순서대로 실행한다. `robot_adapter.py`로 이동을 요청하고 구간 완료·오류·중단을 확인해 조각 진행을 보고한다. 좌표를 새로 생성하지 않는다. |
| `robot_adapter.py` | 로봇 이동·정지·상태·TCP·하중 관련 요청을 확인된 두산 드라이버 인터페이스로 전달하고 결과를 반환한다. 도구 집기나 조각의 작업 순서는 호출 모듈이 결정한다. |
| `cleaning.py` | 해당 도구의 정해진 조건에 따라 청소 위치 접근·뭉침 제거·작업 복귀 순서를 관리한다. |
| `preconditions.py` | 경로에 지정된 도구·설정 버전과 준비·장착 상태를 검사한다. |

도구 집기 호출 예시는 `state_machine.py → tool_sequence.py → robot_adapter.py(접근) → gripper_adapter.py(닫기·파지 확인) → robot_adapter.py(이탈)`이다. 놓기도 `tool_sequence.py`가 반납 위치 이동·지지 조건 확인·열기·해제 확인·이탈을 순서대로 담당한다. 단순 그리퍼 열기·닫기와 도구 집기·놓기는 같은 기능이 아니다.

조각 호출은 `state_machine.py → engraving.py → robot_adapter.py → 두산 드라이버 → M0609`다. `engraving.py`는 원래 공정에 있던 조각 실행을 명시적으로 분리한 내부 파일이며 별도 노드나 새 공정이 아니다. 전체 모션 명령의 소유자는 여전히 `process_controller_node` 하나다.

팀의 별도 `c2_gripper` 패키지와 `gripper_controller_node`, `OperateGripper.action`은 이 구조에 두지 않는다. 공정 내부 모듈 호출로 연결한다. 실제 그리퍼 통신에 공급자 ROS 드라이버가 필요하면 `gripper_adapter.py`가 그 드라이버를 호출한다.

`tools.yaml`은 도구 ID별로 다음 항목을 관리하는 설정 원본이다.

- 설정 버전, 도구 형상·가공에 필요한 치수
- 보관·집기·반납 위치와 접근·이탈 조건
- 파지 명령 조건과 실제 파지·해제 확인 기준
- 장착 전후 TCP와 하중 프로파일, 전환 단계
- 가공 조건과 뭉침 제거 조건

장치가 고정되었다는 사실로 모델·배선·통신·피드백의 미확정 값이 확정되는 것은 아니다. 위치·힘·TCP·하중·I/O 번호는 현장에서 확인한 값으로 채운다. 그리퍼 명령 접수와 실제 파지·해제 성공을 구분하며 실패 후 다음 단계로 진행하지 않는다.

모니터가 선택한 `tool_id`와 해당 설정 버전의 스냅샷을 경로 생성 입력에 포함하고, 경로 결과에도 기록한다. 공정 제어는 같은 도구·설정으로 집기와 실행을 수행한다. 도구·TCP·공작물 보정 변경 시 기존 실행 경로를 재검증한다.

## 작업대·작업대상의 고정 좌표

`workcell.yaml`에 작업대 기준 프레임과 로봇 base에서 작업대·작업대상 기준 프레임으로의 고정 변환, 작업대상 표면 형상·유효 작업 영역, 좌표 설정 버전을 보관한다. 변환에 필요한 위치·방향·단위를 명시하되 실제 수치는 사용자 제공 또는 현장 확인값으로 채운다. 도구의 보관·집기·반납 위치는 해당 기준 프레임을 명시하여 `tools.yaml`에 둔다.

`map_3d.py`는 도안 좌표를 작업대상 표면의 좌표·자세로 변환한 뒤 이 고정 변환으로 로봇 base 기준에 배치한다. 작업대상의 위치가 고정이라는 것은 도안에 따라 움직일 모든 가공점이 동일하거나 표면이 평면이라는 뜻은 아니다. 2D 도안의 표면 매핑과 도구 자세 계산은 그대로 필요하다.

설정은 경로 생성 시 스냅샷·버전으로 전달하고 공정 시작 시 같은 버전인지 확인한다. 작업 준비에서는 대상이 정해진 위치에 놓여 고정되었는지 확인하며 좌표를 매번 새로 추정하지 않는다. 지그·설치 위치가 변경되면 고정 좌표 설정을 갱신하고 경로를 재검증한다.

## 통신과 공정 흐름

노드별 요청·응답 필드, 경로 파일 형식, 성공·실패·정지 조건, 제한 시간·QoS와 내부 함수 계약은 [인터페이스 권장안 v1](INTERFACE_RECOMMENDATION.md)을 따른다.

```text
시스템 모니터 화면
    ↕ HTTP / WebSocket
monitor_gateway_node
    ├─ GeneratePath Action ─→ path_planner_node
    │                           └─ 경로·미리보기 반환
    ├─ ExecuteProcess Action → process_controller_node
    └─ StopProcess Service ─→ process_controller_node
                                ├─ robot_adapter.py → 두산 드라이버 → M0609
                                └─ gripper_adapter.py → 확인된 장치 통신

공정 상태·이벤트 ── Topic ──→ monitor_gateway_node → 화면·저장
```

| 인터페이스 | 내용 |
| --- | --- |
| `GeneratePath.action` | 이미지·크기·배치·작업대상 형상·등록된 고정 좌표·도구 설정 입력, 생성 단계 피드백, 경로·검증 결과 반환 |
| `ExecuteProcess.action` | 확인한 경로 ID·버전으로 실행 요청, 진행 피드백, 완료·실패·취소 결과 |
| `StopProcess.srv` | 정지 요청을 신속히 접수하고 실제 정지 완료는 상태로 별도 통지 |
| `ProcessState.msg` | 실행 ID·단계·진행·정지 상태와 도구 ID·파지 상태·신선도 |
| `ProcessEvent.msg` | 실행·단계 전환·알람·오류의 식별자·시각·기록 내용 |

실행 파일은 서버가 관리하는 파일 ID·버전·해시로 연결한다. 같은 PC의 로컬 파일 구성을 기준으로 하며, 미리보기와 실행이 같은 경로를 참조해야 한다. 그리퍼 상태는 공정 상태에 포함해 전달한다.

`이미지·설정 입력 → 경로 생성 → 미리보기 확인 → 시작 요청 → 공정 준비 검사 → 선택 도구 집기·파지 확인 → 가공·필요한 청소 → 정상 종료·반납 → 실행 결과 표시·검사 기록`

중단·실패 시에는 정상 종료용 반납·복귀 순서를 무조건 실행하지 않는다. 모니터의 소프트웨어 정지 요청과 물리 비상정지는 구분하며, 정지 요청 접수·Action 취소 수락만으로 실제 정지 완료를 기록하지 않는다.
