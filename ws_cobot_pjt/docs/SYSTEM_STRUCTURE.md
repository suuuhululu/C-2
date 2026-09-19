# 시스템 모니터·좌표 생성·고정 드릴 공정 구조

2026-09-19, 기준 main `301ea6e`. [고정 드릴 운영 결정](C2_FIXED_DRILL_20260919.md)을 반영한다. 고객 웹앱 없이 HMI에서 이미지·배치를 입력하고 생성 경로를 확인한 뒤 실행한다. 고정 좌표 매핑은 유지하며, 드릴은 철사로 고정해 자동 집기·청소·반납을 하지 않는다. **그리퍼 열기는 초기화·종료·오류 복구·보정에도 금지한다.**

팀 노드는 `monitor_gateway_node`, `path_planner_node`, `process_controller_node` 3개다. 로봇의 모든 공정·보정 모션은 공정 제어의 단일 소유권 아래에 둔다. 내부 파일이 늘어나도 별도 노드·Topic·Service를 만들지 않는다.

## 현재 구현과 목표 구조

공통 타입·HMI·서버·MOCK·ROS 클라이언트가 존재한다. `c2_process`의 실제 모듈은 `robot_adapter.py`와 `__init__.py`뿐이며 공정 노드·패키지 빌드 설정은 아직 없다. `engraving.py` 이관은 [PR #25](https://github.com/suuuhululu/C-2/pull/25), `tool_calibration.py` 추가는 [PR #27](https://github.com/suuuhululu/C-2/pull/27)에서 진행 중이며 아직 미병합이다. 어댑터의 c2_base 기본값은 [PR #23](https://github.com/suuuhululu/C-2/pull/23)에서 변경한다. 이번 변경은 이 세 PR의 코드를 중복 반영하지 않으며 cleaning은 feat/12-robot-adapter의 4b6416d에 보존한다. 아래에서 “목표”라고 한 파일은 구현해야 할 위치다.

```text
ws_cobot_pjt/
├── frontend/src/monitor/          # 구현: 운영자 HMI, 직접 모션 명령 없음
│   ├── Monitor.tsx
│   ├── Previews.tsx
│   ├── LivePathPreview.tsx
│   └── api.ts
├── backend/app/                  # 구현: HTTP·DB·모의 상대·ROS 클라이언트
│   ├── monitor.py
│   ├── monitor_service.py
│   ├── monitor_contract.py
│   ├── ros_bridge.py             # monitor_gateway_node
│   ├── mock_peer.py
│   └── storage.py
├── ws_cobot1/src/
│   ├── c2_interfaces/            # 구현: v2 공통 타입, 실행 노드 없음
│   │   ├── package.xml
│   │   ├── CMakeLists.txt
│   │   ├── action/               # GeneratePath, ExecuteProcess
│   │   ├── srv/                  # StopProcess
│   │   └── msg/                  # ProcessState, ProcessEvent
│   ├── c2_path/                  # 아래 계산·노드·빌드 설정은 목표
│   │   └── c2_path/
│   │       ├── node.py
│   │       ├── image_to_svg.py
│   │       ├── extract_2d.py
│   │       ├── optimize_2d.py
│   │       ├── map_3d.py
│   │       ├── generate_path.py
│   │       └── validate_path.py
│   └── c2_process/
│       ├── package.xml           # 목표
│       ├── setup.py              # 목표: launch/config 설치 포함
│       ├── setup.cfg             # 목표
│       ├── resource/c2_process   # 목표
│       ├── c2_process/
│       │   ├── __init__.py        # 구현
│       │   ├── node.py            # 목표: process_controller_node
│       │   ├── state_machine.py   # 목표: 공정 순서·정지·실패 처리
│       │   ├── preconditions.py   # 목표: 경로·장착·닫힘·보정·J6 검사
│       │   ├── robot_adapter.py   # 구현: 두산 호출; c2_base 기본값은 PR #23
│       │   ├── engraving.py       # 목표: 담당 브랜치에서 검토 후 이관
│       │   └── tool_calibration.py # 목표: 전체 보정·실행 전 확인
│       ├── test/                 # 기존 어댑터 모의 시험·별도 실기 확인 소스
│       ├── config/
│       │   ├── README.md          # 확정/미확정 설정 안내
│       │   ├── workcell.yaml      # 목표: 실측 후 작성, 청소면 없음
│       │   └── tools.yaml         # 목표: 고정 드릴·TCP·하중·가공·보정
│       └── launch/process.launch.py # 목표: 좌표·공정 노드
└── ws_dsr/src/                   # 공급자 원본, 로컬 전용·Git 제외
```

6개 공정 모듈은 node/state_machine/preconditions/robot_adapter/engraving/tool_calibration을 센 것이다. `__init__.py`, 패키지 설정, 시험 파일은 모듈 수와 별개다. 없던 Python 파일을 빈 구현으로 만들어 완료처럼 표시하지 않는다.

## 노드·모듈 책임

| 영역 | 책임 | 담당 제안·현황 |
| --- | --- | --- |
| monitor_gateway_node | HTTP 요청을 기존 ROS 5개 통신에 연결, 상태·파일 결과를 서버/HMI에 전달 | 모니터 영역 |
| path_planner_node | 이미지→가공 중심선 SVG→2D 최적화→표면 매핑→도구 끝 경로·검증 | 좌표 영역 |
| process_controller_node (`node.py`) | ExecuteProcess·StopProcess 수신, ProcessState·ProcessEvent 발행 | 세은 제안, 최종 배정 대기 |
| state_machine.py | PRECHECK→TOOL_CHECK→경로 실행→FINISH; 실패·정지 시 후속 진입 차단 | 세은 제안 |
| preconditions.py | 버전·경로/설정 해시·모드·STANDBY·제어권·드릴 고정/닫힘 근거·보정·J6 범위 검사 | 세은 제안 |
| robot_adapter.py | 두산 이동·접촉 접근·정지·관측·TCP/하중·도구 오프셋 변환 | 이시율 제안, 소스 존재 |
| engraving.py | 확정 경로의 획별 접근·힘 터치·가공·이탈과 진행·취소·실패 보고 | 이시율 제안, main 이관 대기 |
| tool_calibration.py | 장착 시 3점 전체 측정, 실행 전 기존 보정의 1점 확인 | 이시율 제안, PR #27 미병합 |

담당 제안을 확정 배정으로 기록하거나 Issue를 자동 재배정하지 않는다. `gripper_adapter.py`·`tool_sequence.py`는 현재 만들지 않으며 `cleaning.py`는 담당 브랜치에 예비 보관한다. 그리퍼 닫힘·장착을 확인하는 책임은 남아 있고, 실제 관측은 확인된 장치 입력을 사용한다. 닫혔다는 이유만으로 고정 장착이나 접촉·가공 성공을 판단하지 않는다.

## 보정·조각 호출과 설정

장착 전체 보정은 승인된 준비 절차에서 수행해 **새 불변 설정 스냅샷을 만든 뒤** 경로를 생성한다. 실행 전 TOOL_CHECK는 같은 저장 보정이 유효한지 확인한다. 실패하면 중단하고 필요 시 전체 보정→새 스냅샷→경로 재생성→미리보기 확인으로 돌아간다. 실행 요청 뒤 설정을 덮어쓰고 같은 경로 ID로 조각하지 않는다.

```text
state_machine → preconditions
              → tool_calibration(저장값 확인) → robot_adapter
              → engraving(접근·가공·이탈)      → robot_adapter → 두산 드라이버
```

APPROACH/ENGRAVE/RETRACT는 engraving이 실제 경로 구간을 보고한 단계다. state_machine이 접근·이탈을 중복 실행하지 않는다. robot_adapter의 현재 동기 함수를 작업 스레드 등에서 호출해도 정지·상태 처리는 계속 가능해야 한다. 정지 접수·정지 명령·실제 정지 확인은 별도이며 실패 뒤 자동 열기·손목 풀기·홈 이동을 넣지 않는다.

- workcell.yaml: `c2_base`가 실제 로봇 base와 일치하는 등록, 고정 변환, 대상 형상·유효 영역·이음매·버전. 이름 변경만으로 TF나 좌표 변환이 생기지 않는다.
- tools.yaml: `engraving_drill`, 철사 고정·열기 금지 정책, 장착/닫힘 확인 근거, `GripperDA_v1`·하중, 가공·보정 프로파일과 측정 근거. 집기·반납·청소는 미사용이다.
- `clearance_m`·도구 끝 오프셋은 m, 자세는 quaternion xyzw. 어댑터 프로파일은 vel_mm_s·acc_mm_s2·pos_tol_mm으로 단위를 구분한다.
- 자세: 툴 −Y가 표면 안쪽 법선, 툴 +Z가 원통 축 아래. 좌표 담당자가 정규화 quaternion과 실제 프레임을 생성하며 어댑터만 제어기 TCP로 변환한다.
- 획은 180° 이내·이음매 금지·J6 왕복 원칙. IK·현재 관절·전체 이동 구간 검사는 별도 필수다. 상세 순서/한계값은 담당자가 합의 후 명세·설정으로 제출한다.

받침대 50 mm 변경 보고와 z≈234.4 mm 예상치는 [설정 대기 목록](../ws_cobot1/src/c2_process/config/README.md)에 구분한다. 9/18 evidence를 새 실측값으로 덮어쓰지 않는다. 전체 실행 환경은 Jazzy·M0609이고 ws_dsr와 ws_cobot1의 build/install/log를 분리한다.

## 외부 통신

[인터페이스 권장안 v2](INTERFACE_RECOMMENDATION.md)의 기존 5개 이름·형식을 유지한다. 내부 보정 모듈을 이유로 새 보정 노드·Action을 추가하지 않는다.

`이미지·설정 → GeneratePath → 미리보기 확인 → ExecuteProcess → PRECHECK → TOOL_CHECK → APPROACH/ENGRAVE/RETRACT → FINISH → 별도 검사`

StopProcess는 모든 단계에서 우선 처리한다. ProcessState의 파지·도구 필드는 계속 필요하며 열기 계열 관측값은 이상 진단용으로 남긴다. 그 필드가 존재한다고 열기 동작이 허용되는 것은 아니다. 과거 draw.io 도면은 9/18 보관본이며 이 문서와 [운영 결정](C2_FIXED_DRILL_20260919.md)이 현재 기준이다.
