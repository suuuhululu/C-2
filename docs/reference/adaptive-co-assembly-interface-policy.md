# Adaptive Co-Assembly 인터페이스 설계 정책

팀 제안안 v1.0 · 2026-10-03 · 대상: A Planning / B Perception / C Reasoning / D Robot

## 1. 기본 원칙

**계산은 함수, 분리된 애플리케이션 간 전달은 일반 API, 센서·로봇 경계는 ROS2, PostgreSQL은 기록에 사용한다.**

- 1PC MVP에서는 Backend/Workflow가 A·B·C·D의 Python 모듈을 직접 호출한다. 팀원별 담당 영역이라는 이유만으로 프로세스나 ROS node를 나누지 않는다.
- 프로세스·PC를 분리하거나 UI·외부 AI와 연결해야 할 때 REST 등의 일반 API를 사용한다. 함수와 API는 같은 입력·출력 contract를 공유한다.
- ROS2는 D435i 입력 및 M0609 제어·상태 수신에 집중한다. A와 C의 핵심 로직은 ROS에 의존하지 않는다.
- Backend는 현재 단계, 호출 순서, 사람 응답 대기, 실행 상태를 관리한다. 계획·시각 처리·판단·로봇 skill 구현은 각 담당 모듈에 둔다.

## 2. 인터페이스 선택 기준

| 방식 | 선택 기준 | 프로젝트 예 | 정책 |
|---|---|---|---|
| 함수 호출 | 같은 프로세스 안의 계산·모듈 호출 | 블록 검출, 좌표 변환, 비교, 계획 생성 | 기본 선택. DTO를 입력받고 결과를 반환 |
| 일반 API: REST 등 | 별도 프로세스·PC·UI·외부 서비스 | HMI 응답, 분리된 planner, 외부 LLM | 고수준 데이터·명령 전달. timeout·오류 contract 명시 |
| ROS2 Topic | 지속적으로 발행되는 센서·상태 | RGB/Depth, joint state, robot status | 최신성·QoS 설정 명시. 명령 완료 확인은 별도 관리 |
| ROS2 Service | 짧게 끝나는 요청/응답 | 설정 조회, 실행 가능 여부 조회 | 수초 이상 걸리는 부품 전달·HOME 동작에는 사용하지 않음 |
| ROS2 Action | 시간이 걸리고 feedback·cancel·최종 result가 필요한 실행 | 부품 전달, HOME 복귀 | goal 수락과 실행 완료를 구분 |

위 ROS 구분은 [ROS2 공식 인터페이스 설명](https://github.com/ros2/ros2_documentation/blob/rolling/source/ROS-Framework/Interfaces-Topics-Services-Actions.rst)을 따른다. Service도 비동기 호출할 수 있지만, 장시간 실행의 진행률·취소 contract를 대체하지 않는다.

**MVP 구현:** D 내부에서 기존 Doosan 인터페이스를 감싸 사용한다. custom Action을 필수로 만들지 않는다. 기존 드라이버가 Service만 제공하더라도 D가 애플리케이션에 실행 상태·결과를 제공한다. 드라이버의 실제 인터페이스와 취소 지원 여부는 통합 시 확인한다.

## 3. 권장 연결과 데이터 흐름

아래 A↔C 등의 논리적 전달은 기본적으로 Backend/Workflow가 중재한다. API 경로와 Topic 이름은 제안 예시이며, 장치 이름은 실제 드라이버 설정에 맞춘다.

| 출발 → 도착 | 전달 데이터 / 역할 | 1PC MVP | 분리 시 권장 |
|---|---|---|---|
| HMI → Backend → A | 목표 입력 → `TargetDesign`, `AssemblyPlan` 생성 | UI API + A 함수 | `POST /plans` |
| A → C | 목표·계획 버전, 현재 단계 | DTO 함수 인자 | 계획 응답 DTO를 Workflow가 전달 |
| D435i → B adapter | RGB·aligned Depth·camera info | ROS2 Topic | ROS2 Topic 유지 |
| B adapter → B core | 동기화된 이미지·보정 정보 → 검출·grid 변환 | 함수 | 함수 유지 |
| B → Backend → C | `CurrentAssemblyState` → 편차 판단 | DTO 함수 인자 | `GET /assembly-state`로 최신 snapshot 조회 |
| C ↔ HMI | `HumanQuestion` / `HumanResponse` | Backend UI API | REST, 질문 알림은 필요 시 SSE/WebSocket |
| C → A | `PlanChangeRequest` → 재계획 | `replan(...)` | `POST /plans/{id}/replan` |
| A → Backend → D | `NextPart`를 `RobotCommand`로 변환·전달 | robot port 호출 | `POST /robot/commands` → 수락 응답 |
| D core → D adapter → M0609 | skill 순서 → 이동·gripper 제어 | port 호출 → 기존 ROS2/Doosan 인터페이스 | 같은 장치 경계 유지, 필요 시 skill Action 추가 |
| M0609 → D → Backend | 장치 상태 → `RobotStatus`, `RobotResult` | ROS2 Topic + port 상태 조회 | `GET /robot/commands/{command_id}` 또는 상태 이벤트 |
| Backend → PostgreSQL | 설계·계획 버전, 관측, 판단, 사람 응답, 실행 결과 | repository adapter | 같은 기록 경로 유지 |

B는 관측된 상태를 생성하고, C가 목표와 비교한다. D는 검증된 고수준 명령을 실행하며 계획이나 사람의 의도를 판단하지 않는다.

### 한 사이클의 실행 순서

1. A가 목표와 계획을 생성한다. B는 독립적으로 현재 조립 상태를 관측한다.
2. Workflow가 동일 세션의 목표·계획·관측을 C에 전달한다.
3. `CONTINUE_AS_PLANNED`이면 기존 계획의 다음 부품을 요청한다.
4. `ASK_HUMAN`이면 다음 부품 전달을 보류한다. 사람의 `KEEP`은 `ACCEPT_CHANGE`로 해석하여 C가 변경 요청을 만들고 A가 목표·계획 버전을 갱신한다. 재계획 성공 후 다음 부품을 요청한다.
5. `REVERT`/`CORRECT`이면 수정 안내 후 B의 재관측으로 수정 여부를 확인한다. D의 자동 수정 동작은 별도 정의된 skill이 있을 때만 요청한다.
6. Workflow가 D에 전달 명령을 보내고 최종 실행 결과를 확인한다. 로봇 전달 성공과 사람이 실제로 조립한 사실은 구분하며, 조립 진척은 B의 관측으로 확인한다.

## 4. 공통 contract와 오류 처리

공통 DTO는 `contracts/`에서 관리한다. 함수 인자, REST JSON, ROS 변환 결과는 같은 의미·필드·단위를 유지한다. transport 전용 필드는 adapter에서 처리한다.

| DTO | 최소 합의 필드 |
|---|---|
| `TargetDesign`, `AssemblyPlan` | `session_id`, `design_version`, `plan_version`, 블록 목록 / 단계 목록 |
| `CurrentAssemblyState` | `session_id`, `observation_id`, `observed_at`, `frame_id`, 블록 목록, `confidence` |
| `Decision` | `decision_id`, 관측 ID, 기준 계획 버전, `kind`, `reason` |
| `HumanResponse`, `PlanChangeRequest` | 질문/판단 ID, `KEEP` 또는 `REVERT`, 기준 버전, 채택할 변경 |
| `RobotCommand` | `command_id`, `session_id`, `plan_version`, `action`, `slot` |
| `RobotStatus`, `RobotResult` | `command_id`, `status`, `error_code`, `message` |

- 공통 `schema_version`을 둔다. 시각은 UTC ISO 8601, grid는 정수 `(x, y, layer)`, 물리 좌표는 미터·회전은 라디안으로 합의한다. 원점·축·frame 변환은 보정 설정에 명시한다.
- 실행 상태는 `ACCEPTED → RUNNING → SUCCEEDED / FAILED / CANCELED`로 통일한다. 수락 응답은 실행 성공을 뜻하지 않는다. REST는 수락 시 `202`와 `command_id`를 반환하고, 함수도 같은 수락 DTO를 반환한다.
- Workflow는 오래된 관측·계획 버전 불일치·낮은 confidence를 검증하고 재관측/재판단한다. 사람 응답은 질문 ID와 기준 버전이 일치할 때만 반영한다.
- 오류는 `INVALID_INPUT`, `STALE_STATE`, `VERSION_CONFLICT`, `ROBOT_BUSY`, `DEVICE_UNAVAILABLE`, `TIMEOUT` 등 공통 코드로 반환한다. 시간 제한은 설정에서 관리한다.
- 동일 `command_id` 재전송은 기존 실행 상태를 반환한다. 다른 payload로 같은 ID를 보내면 거절한다. timeout 뒤에는 상태를 조회하며 새 ID로 이동 명령을 자동 재실행하지 않는다.
- cancel 요청 수락과 실제 정지 완료를 구분한다. 드라이버가 취소를 지원하지 않으면 명시적 오류를 반환한다.

## 5. PostgreSQL 사용 원칙

**PostgreSQL은 기록·조회·복구를 위한 저장소이며, 이 프로젝트의 message broker가 아니다.**

- 설계·계획 버전, 관측 snapshot, 편차·판단·사람 응답, 로봇 명령·결과·시각을 기록한다. 원본 이미지 저장은 필요할 때 별도 파일 저장소를 사용한다.
- A가 DB에 쓰고 C가 polling하여 판단하거나, D가 명령 테이블을 polling하여 움직이는 구조를 사용하지 않는다. 명령과 결과는 함수/API/ROS 경계로 전달한다.
- 기록 책임은 Backend의 repository adapter에 둔다. DB 장애는 실행 결과와 별도 기록 오류로 보고하고, 저장 실패를 이유로 로봇 명령을 다시 보내지 않는다.
- 재시작 후 미완료 명령은 D의 실제 상태와 대조한다. DB 이력만 보고 자동 재실행하지 않는다.

## 6. TEST/REAL 및 테스트 정책

- TEST는 fixture camera·FakeRobot, REAL은 ROS camera·Doosan adapter를 주입한다. 호출자와 DTO, 검증 규칙, 상태 전이, 오류 의미는 동일하게 유지한다.
- 모드 선택은 진입점/설정에서 한 번 수행한다. core 내부에 `if mode == "REAL"` 분기를 넣지 않는다.
- pure logic에는 ROS·HTTP·DB·환경변수·장치 접근을 넣지 않는다. B의 이미지 계산, C의 비교·판단 규칙, A의 계획 검증/재계획 계산, D의 명령 검증/skill 단계 생성을 분리한다.
- LLM 호출은 외부 adapter에 둔다. C의 core는 주입된 추론 결과를 검증한다. D의 skill 실행 orchestration은 I/O를 수행하므로 pure logic과 구분하고 FakeRobot으로 테스트한다.
- 단위테스트는 ROS 설치·카메라·로봇·DB 없이 실행한다. adapter contract 테스트는 TEST/REAL의 DTO·상태·오류 매핑을 확인하고, 장치 연결·보정·동작은 REAL 통합테스트에서 확인한다.

## 7. 최소 폴더와 코드 예시

```text
app/
  contracts/           # 공통 DTO, enum, schema version
  core/
    planning.py        # A: 계획 계산·검증
    perception.py      # B: 이미지 → 조립 상태
    reasoning.py       # C: 비교·판단·변경 요청
    robot.py           # D: 명령 검증·skill 단계 생성
  ports.py             # Camera / Robot / Inference / Repository 규약
  workflow.py          # 상태 전이·호출 순서·skill 실행 orchestration
  adapters/
    camera_ros.py      # ROS 이미지 변환·동기화
    camera_fixture.py
    robot_doosan.py    # ROS/Doosan 변환·실행 상태 관리
    robot_fake.py
    inference_api.py
    postgres.py
    http_api.py        # UI 및 분리 프로세스용 API
  main.py              # TEST/REAL adapter 주입
tests/
  unit/                # core fixture 및 Fake 기반 orchestration
  contract/            # DTO·port 규약 검증
  integration/         # 실제 ROS·장치·DB 연결
```

```python
# ports.py — ROS 타입을 노출하지 않는 공통 규약
from typing import Protocol
from app.contracts import RobotCommand, RobotStatus

class RobotPort(Protocol):
    def submit(self, cmd: RobotCommand) -> RobotStatus: ...
    def get_status(self, command_id: str) -> RobotStatus: ...
    def cancel(self, command_id: str) -> RobotStatus: ...

# workflow.py — transport와 무관한 호출
def dispatch(cmd: RobotCommand, robot: RobotPort) -> RobotStatus:
    validate_command(cmd)  # core의 입력 검증 함수
    return robot.submit(cmd)  # ACCEPTED 이후 최종 결과는 별도 확인

# main.py — 모드에 따라 구현만 교체
robot = FakeRobot() if mode == "TEST" else DoosanRobotAdapter(config)

# unit test — 실제 장치 없이 같은 contract 사용
def test_delivery_acceptance():
    robot = FakeRobot()
    cmd = delivery_command_fixture(command_id="cmd-001")
    assert dispatch(cmd, robot).status == "ACCEPTED"
    robot.complete(cmd.command_id)  # Fake가 완료 이벤트를 모사
    assert robot.get_status(cmd.command_id).status == "SUCCEEDED"
```

코드는 구조 설명용 축약 예시이며 DTO·factory·adapter 구현은 각 모듈에서 제공한다.

**팀 완료 기준:** A는 fixture로 plan/replan/next part를, B는 fixture 이미지로 현재 상태를, C는 목표·현재 상태·사람 응답으로 decision/change request를, D는 명령 fixture로 수락·실행·결과를 증명한다. 공통 contract가 확인된 뒤 REAL adapter를 연결한다.
