# c2_interfaces · 공통 ROS 2 통신 정의 v2

2026-09-25 확인: 준비용 `PrepareWorkpiece.action`은 HMI 서버·ROS 게이트웨이·공정 노드의 `MEASURE/BIND_SNAPSHOT` 흐름에 연결되어 있다. ID 발급·설정 해시·타입 결과·스냅샷 등록·취소는 [준비 Action 계약](../../../docs/PREPARE_WORKPIECE_ACTION.md)을 따른다. 코드 연결과 실제 M0609 반복 측정·가공 검증 완료는 구별한다.

현재 v2는 고정 드릴 전용이다. 통신 이름·필드 배치는 v1과 같지만 집기·반납·청소를 없애고 TOOL_CHECK를 추가했다. [v1→v2 전환](../../../docs/C2_FIXED_DRILL_20260919.md)을 따라 모든 소비자를 함께 갱신한다. 아래 최초 타입 시험 기록은 v1 시점이며 이번 검증은 [고정 드릴 검증 기록](../../../docs/validation/2026-09-19-fixed-drill.md)을 따른다.

2026-09-19. [인터페이스 권장안 v2](../../../docs/INTERFACE_RECOMMENDATION.md)의 공통 타입을 구현했다. 실행 노드 없이 세 노드가 공유하는 Python·C/C++ 타입을 생성하는 `ament_cmake` 패키지다. Jazzy 빌드·직렬화 시험을 완료했으며, 실제 상대 노드 통합·로봇 동작은 별도 구현·검증 대상이다. [검증 기록](../../../docs/validation/2026-09-19-c2-interfaces.md).

| 디렉토리 | 파일 | 연결 |
| --- | --- | --- |
| `action/` | `GeneratePath.action` | 모니터 → 좌표·경로 생성 |
| `action/` | `ExecuteProcess.action` | 모니터 → 전체 공정 실행 |
| `action/` | `PrepareWorkpiece.action` | 모니터 → 사전 검사·홈 복귀·측정 / 결과 등록 |
| `srv/` | `StopProcess.srv` | 모니터 → 정지 접수 |
| `msg/` | `ProcessState.msg` | 공정 → 최신 상태 |
| `msg/` | `ProcessEvent.msg` | 공정 → 기록할 이벤트 |

```text
c2_interfaces/
├── package.xml
├── CMakeLists.txt
├── LICENSE
├── README.md
├── action/
│   ├── GeneratePath.action
│   ├── ExecuteProcess.action
│   └── PrepareWorkpiece.action
├── srv/StopProcess.srv
├── msg/
│   ├── ProcessState.msg
│   └── ProcessEvent.msg
└── test/test_generated_contract.py
```

## 받기·빌드·타입 확인

main 병합 전에는 `codex/fixed-drill-contract` 브랜치를 받고, 병합 후에는 최신 main을 사용한다. 자신의 미커밋 작업을 보존한 상태에서 팀 Git 절차에 따라 가져온다. 다른 ROS 패키지에 타입 파일을 복사하지 않는다.

ROS 2 Jazzy 개발 환경에서 저장소 루트 기준:

```bash
source /opt/ros/jazzy/setup.bash
cd ws_cobot_pjt/ws_cobot1
rosdep install --from-paths src/c2_interfaces --ignore-src -r -y --rosdistro jazzy
colcon build --packages-select c2_interfaces --symlink-install
```

새 터미널에서 저장소 루트 기준:

```bash
source /opt/ros/jazzy/setup.bash
source ws_cobot_pjt/ws_cobot1/install/local_setup.bash
ros2 interface show c2_interfaces/action/GeneratePath
ros2 interface show c2_interfaces/action/ExecuteProcess
ros2 interface show c2_interfaces/action/PrepareWorkpiece
ros2 interface show c2_interfaces/srv/StopProcess
ros2 interface show c2_interfaces/msg/ProcessState
ros2 interface show c2_interfaces/msg/ProcessEvent
```

이 패키지에는 실행 노드가 없으므로 `ros2 run c2_interfaces ...`로 기동하지 않는다. `ws_dsr`의 build/install/log와 섞지 않는다.

## 담당자 코드에서 사용

```python
from c2_interfaces.action import GeneratePath, ExecuteProcess
from c2_interfaces.srv import StopProcess
from c2_interfaces.msg import ProcessState, ProcessEvent

# 전송·모션 없이 타입만 생성하는 예시
goal = GeneratePath.Goal()
goal.schema_version = 2
goal.source_mode = 'SIMULATION'
# 실제 전송 전 ID·해시·크기·도구·프로파일 등 필수 필드를 채운다.
```

`c2_path`·`c2_process`의 패키지를 구현할 때 각 `package.xml`에 `<depend>c2_interfaces</depend>`를 선언한다. 모니터 서버는 이 워크스페이스를 source한 환경에서 실행한다. C++에서는 `#include "c2_interfaces/action/generate_path.hpp"` 형태로 사용하고, 소비 패키지의 CMake에서 `find_package(c2_interfaces REQUIRED)`와 대상 의존성을 등록한다.

## 이번에 구체화한 규칙

- `schema_version=2`, 패키지 버전은 `0.2.0`이다. 서로 다른 용도다. ROS는 schema_version·UUID·해시·진행률 범위를 자동 검사하지 않으므로 송수신 노드가 명세대로 검사해야 한다.
- `.action`의 세 구역은 **Goal / Result / Feedback**, `.srv`는 **Request / Response** 순서다.
- 시각은 `builtin_interfaces/Time`, UTC Unix epoch 기준이다. `{sec: 0, nanosec: 0}`은 미확인이며 실행 고정 확인 시각으로 허용하지 않는다. HMI JSON·DB는 시간대가 포함된 RFC3339 문자열을 쓰고 `ros_bridge.py`에서 변환한다. 경과 시간은 별도의 `float64` 초다.
- 도안 값은 mm·deg, 길이는 m, 관절은 rad다. `ProcessState.tcp`는 `geometry_msgs/PoseStamped`로 제어기 TCP의 측정값·프레임·실제 측정 시각을 담는다. 경로 waypoint는 도구 끝 기준이며, `GripperDA_v1` 그리퍼 끝점으로의 변환은 공정의 `robot_adapter.py` 책임이다.
- 관절·모터 온도는 M0609의 1~6 순서다. 신호마다 `*_quality`와 측정 시각을 둔다. 미확인 배열은 비우고 품질은 `UNKNOWN`, 미지원 온도는 `UNSUPPORTED`로 보낸다. TCP 측정 시각은 `tcp.header.stamp`다.
- 기본 생성값은 성공·정지 완료·유효한 측정으로 취급하지 않는다. `success`, `validation_passed`, 고정 확인, 정지 접수는 기본 false이고 상태·품질은 `UNKNOWN`이다. 송신자는 모드를 명시해야 한다.
- 정지 서비스는 접수만 응답한다. 실제 정지 확인은 ProcessState 및 ExecuteProcess 결과를 사용한다. `engraving_progress`·완료 segment만으로 압력이나 실물 품질 합격을 판단하지 않는다. 구간별 가공 판정은 [별도 제안](../../../docs/HMI_PATH_QUALITY_PROPOSAL.md)이며 이번 타입에 추가하지 않았다.

전체 필드 자료형·누락 값·상태 해석·배포 규칙은 [명세 12절](../../../docs/INTERFACE_RECOMMENDATION.md#12-공통-타입-구현과-배포--2026-09-19)을 따른다.

## 시험

빌드 후 Jazzy와 워크스페이스를 source한 터미널에서:

```bash
cd ws_cobot_pjt/ws_cobot1
colcon test --packages-select c2_interfaces --event-handlers console_direct+
colcon test-result --verbose
```

생성 타입 직렬화·역직렬화, 기본값, 측정 시각·프레임 보존을 시험한다. 노드·네트워크·로봇은 실행하지 않는다. 서버 변환 시험은 [서버 README](../../../backend/README.md#ros-게이트웨이-연결-상태)를 따른다.

타입을 수정할 때는 명세와 송수신 코드·시험을 같은 변경으로 검토한다. 모든 담당자가 같은 커밋의 `c2_interfaces`를 다시 빌드하고 노드를 재시작한 뒤 연결한다. `schema_version=2`이 같아도 다른 ROS 타입 정의를 혼용할 수 없다.
