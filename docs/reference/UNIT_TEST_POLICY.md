# Unit & Component Test Policy

> **Purpose:** upstream 기능의 완성을 기다리지 않고 각 담당자가 자신의
> 기능을 독립적으로 검증한다.

## 1. Core Rules

**MUST --- Unit tests consume contracts, not upstream implementations.**

앞 단계의 실제 산출물이 없어도 계약이 정의되어 있으면 fixture/mock으로
테스트한다.

**MUST --- Mock the workflow, never mock physical safety.**

업스트림 JSON, AI 응답, camera input은 mock할 수 있다. REAL M0609의
E-stop, 작업공간, TCP/tool, gripper, 속도 제한 등 안전조건은 실제로
확인한다.

**MUST --- TEST와 REAL은 동일한 I/O contract를 사용한다.**

REAL 전환 때문에 Reasoner/Planner/Backend의 계약을 변경하지 않는다.

## 2. Test Levels

### L1 --- Unit

한 함수/모듈만 검증한다. 실제 M0609와 upstream node는 사용하지 않는다.
입력은 fixture를 사용한다.

### L2 --- Component

하나의 subsystem을 실제 dependency 일부와 검증한다. 예:
Camera→Perception, Backend→PostgreSQL, Robot Adapter→M0609.

### L3 --- Contract / Integration

인접 subsystem 사이의 실제 계약을 검증한다. 예:
`Perception → AssemblyState → Reasoner`.

### L4 --- REAL

실제 M0609 + 2점 그리퍼를 포함한다.

**MUST:** 관련 L1\~L3 통과 전 L4로 가지 않는다.

## 3. TEST / REAL

초기 프로젝트는 MOCK/SIM/REAL 3개를 강제하지 않는다.

``` text
TEST
├── Fixture / Mock
├── FakeRobotAdapter
└── RViz2: 필요 시 visualization/debugging

REAL
└── M0609Adapter → ROS2 Jazzy → M0609
```

RViz2 성공을 REAL 성공으로 간주하지 않는다. 향후 Isaac Sim이 필요하면
동일 계약의 `IsaacRobotAdapter`를 추가한다.

## 4. Fixture First

새 interface 순서:

1.  Schema
2.  Valid Fixture
3.  Invalid Fixture
4.  Consumer Test
5.  Producer 구현
6.  Contract Test

``` text
interfaces/
├── schemas/
│   └── robot_command.json
└── fixtures/
    └── robot_command/
        ├── valid.json
        └── invalid.json
```

**MUST:** Consumer는 Producer 구현 완료를 기다리지 않는다.

## 5. "테스트를 못 한다" 보고

팀장은 먼저 묻는다.

> 지금 L1/L2/L3/L4 중 어떤 테스트인가?

L1에서 upstream artifact가 없으면: - Contract 정의됨 → fixture 생성 후
테스트 - Contract 없음 → 코딩 중지, interface부터 정의

`Bind`, `prevalidation.json`, `current_state.json`, `decision.json`,
`robot_command.json` 등이 실제로 아직 생성되지 않아도 schema/fixture가
있으면 L1은 진행한다.

## 6. Subsystem별 L1

  Subsystem    L1 입력                    검증
  ------------ -------------------------- -----------------------------
  Perception   fixture image/frame        Image → Assembly State
  Reasoning    fixture Assembly State     State → Decision
  Planning     fixture State + Decision   → Adapted Plan
  Robot        fixture RobotCommand       validation / execution flow
  HMI          fixture State/Decision     UI state / user event
  DB           fixture record             migration / CRUD

## 7. REAL Test Gate

-   [ ] 관련 L1\~L3 PASS
-   [ ] REAL adapter 명시
-   [ ] M0609 연결
-   [ ] E-stop 접근
-   [ ] 작업공간 안전
-   [ ] TCP/tool 확인
-   [ ] gripper 확인
-   [ ] 허용 slot/skill 확인
-   [ ] 속도/가속도 제한
-   [ ] HOME/STOP recovery
-   [ ] 사람 위험영역 이탈

환경변수 누락을 REAL로 해석하지 않는다.

## 8. pytest

Python 테스트는 `pytest`를 기본으로 사용한다.

``` bash
pytest
```

``` text
tests/
├── unit/
│   ├── test_perception.py
│   ├── test_reasoning.py
│   └── test_robot.py
└── integration/
    └── test_mock_e2e.py
```

정상 입력뿐 아니라 invalid/malformed/boundary/timeout을 포함한다.

## 9. CI

GitHub Actions에서 PR마다 다음을 자동 검증하는 것을 권장한다.

-   Unit tests
-   JSON Schema / Contract tests
-   Mock integration

REAL M0609 테스트는 CI에서 수행하지 않는다.

``` text
AI-assisted coding → local pytest → PR → CI PASS → Human Review → Merge
```

## 10. Test Progress

  기능         L1   L2   L3   L4 REAL   Blocker
  ------------ ---- ---- ---- --------- ---------
  Perception   ⬜   ⬜   ⬜   \-        
  Reasoning    ⬜   ⬜   ⬜   \-        
  Planning     ⬜   ⬜   ⬜   \-        
  Robot        ⬜   ⬜   ⬜   ⬜        
  HMI          ⬜   ⬜   ⬜   \-        

L1이 실패한 기능이 L4부터 시도하고 있다면 중단한다.

## 11. Definition of Test Done

-   [ ] I/O 계약 명확
-   [ ] Valid Fixture
-   [ ] Invalid Fixture
-   [ ] L1 pytest PASS
-   [ ] 실패 동작 정의
-   [ ] 필요 시 L2 PASS
-   [ ] 인접 subsystem과 L3 PASS
-   [ ] REAL 기능이면 안전 Gate 후 L4
-   [ ] 결과/실패 원인 기록

> **Unit tests consume contracts, not upstream implementations.**
