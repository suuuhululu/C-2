# Adaptive Co-Assembly 개발 설계 원칙

> **성격:** 사람과 코딩 AI가 함께 지켜야 하는 개발 헌법(System
> Contract). 이 문서는 "전체 시스템을 새로 구현하라"는 설계서가 아니다.

## 1. 최상위 원칙

**AI는 Architect가 아니라 Contract-bound Implementer로 사용한다.**\
"이 설계서 보고 전체 시스템 만들어줘"라고 요청하지 않는다. 확정된
architecture/interface를 읽힌 뒤, 작은 작업 단위와 Acceptance Criteria만
준다.

AI가 임의로 바꾸면 안 되는 것: - framework / DB / communication
protocol - repository 구조 - REST endpoint / ROS2 topic·service·action -
JSON schema / DB schema - 단위와 좌표계 - M0609 hardware API와 safety
parameter - dependency/version

LLM은 joint angle, TCP pose, 속도, acceleration, force limit을 즉석
생성해 실제 로봇으로 보내지 않는다.

------------------------------------------------------------------------

## 2. 권장 Architecture

``` text
                CONTROL PLANE (Docker)
        ┌───────────────────────────────┐
        │ HMI ←→ Backend ←→ Reasoner   │
        │          ↕         ↕         │
        │      PostgreSQL  Perception   │
        └──────────────┬────────────────┘
                       │ validated command
                       ▼
                PHYSICAL PLANE
        ┌───────────────────────────────┐
        │ Robot Bridge ←→ ROS2 Jazzy    │
        │                    ↕          │
        │                  M0609        │
        │                  Gripper      │
        └───────────────────────────────┘
```

역할: - Vision: 현실 상태 관찰 - LLM/VLM: deviation 의미/의도
reasoning - Planner: 실행 가능한 새 sequence - Backend: workflow와
runtime state의 authority - PostgreSQL: 이력, 실험 데이터, 감사 로그 -
HMI: 사용자 확인과 상태 표시 - ROS2: 실제 robot 통신 - M0609: 검증된
physical skill 실행 - Docker: 재현 가능한 software runtime - Isaac/3D:
preview 및 선택적 validation

### AI → Robot 경계

``` text
LLM / Planner
      ↓
{"action":"DELIVER_PART","slot":3}
      ↓
Robot Bridge
      ↓
Schema + Safety Validation
      ↓
Validated Skill
      ↓
ROS2 → M0609
```

허용 skill 예: `pick(slot)`, `deliver()`, `release()`, `return_home()`,
`stop()`.

정의되지 않은 action은 `REJECTED` 처리한다.

------------------------------------------------------------------------

## 3. 프로젝트 내부 Co-Adaptive AI 원칙

AI는 모든 것을 결정하는 중앙 두뇌가 아니라 **사람·설계·현실 상태 사이의
차이를 해석하고 적응안을 제안하는 bounded decision layer**다.

1.  **Reality over Model** --- 실제 Vision/robot feedback이
    LLM·simulation 예측보다 우선한다.
2.  **Intent is not assumed** --- 사람의 의도가 불확실하면 추측하지 않고
    `ASK`.
3.  **Preserve valid work** --- deviation이 있어도 가능한 경우 이미
    완성된 유효 조립을 보존한다.
4.  **Minimum intervention** --- 목표 달성에 필요한 최소 수정부터
    제안한다.
5.  **Act or Ask** --- confidence와 deterministic validation 결과에 따라
    ACT/ASK를 분리한다.
6.  **No silent adaptation** --- 계획이 변경되면 plan version과 이유를
    기록하고 HMI에 표시한다.
7.  **Deterministic safety boundary** --- AI 판단과 실제 robot execution
    사이에 검증 계층을 둔다.
8.  **Fail closed** --- schema 오류, mode 불명, safety validation 실패
    시 실행하지 않는다.
9.  **Traceability** --- 어떤 state를 보고 어떤 decision을 내렸는지 DB에
    남긴다.
10. **Human override** --- 사용자는 AI 판단을 KEEP/CORRECT/STOP할 수
    있다.

권장 decision vocabulary: `ACT`, `ASK`, `CORRECT`, `REPLAN`, `WAIT`,
`STOP`.

------------------------------------------------------------------------

## 4. Docker 사용 원칙

Docker 목적은 **동일 software stack 재현**이다. 모든 hardware를
container에 넣는 것이 목표가 아니다.

``` text
docker compose
├── postgres
├── backend
├── reasoning
├── perception
├── hmi
└── optional-simulation

HOST
└── ROS2 Jazzy
    ├── Robot Bridge
    └── M0609 Driver
```

실제 M0609 driver는 네트워크/device permission/ROS2 discovery를 먼저
검증한다. MVP에서 억지로 container화하지 않는다.

규칙: - image tag 명시, `latest` 지양 - `.env.example`만 commit, 실제
secret은 금지 - healthcheck 사용 - service 간 hostname은 Compose service
name - host absolute path 하드코딩 금지 - dependency 추가/버전 변경은
owner 승인 - `docker compose up`으로 Control Plane 재현 가능 - Compose는
Integration Owner가 관리

------------------------------------------------------------------------

## 5. PostgreSQL / DB 원칙

DB는 **시스템의 기억과 연구 증거**다.

저장: - assembly session - target/current/adapted state history -
deviation - AI decision/confidence - human decision - plan version -
robot action/result - experiment run - timestamp/latency

최소 table: `assembly_sessions`, `assembly_states`, `deviations`,
`decisions`, `plans`, `robot_actions`, `experiment_runs`.

### DB를 Message Broker로 쓰지 않는다

금지:

``` text
Vision → DB → AI → DB → Robot → DB → HMI
```

실시간 전달은 REST/API 또는 ROS2. DB는 기록/복구/분석용이다.

``` text
Backend
├── runtime current state
└── PostgreSQL
    └── history / persistence / experiment evidence
```

DB schema는 migration으로만 변경한다. 모든 팀원이 clean volume에서 같은
schema를 재생성할 수 있어야 한다.

------------------------------------------------------------------------

## 6. Day 1에 사람이 확정할 Contract

-   OS / Python / ROS2 distribution
-   M0609 interface
-   Backend framework
-   PostgreSQL version
-   Container runtime
-   AI API/model interface
-   mm/m, degree/radian
-   camera/base/TCP frame
-   JSON schema
-   REST endpoint
-   ROS2 interface names
-   error codes
-   repository structure
-   LEGO ID / slot numbering
-   robot speed/gripper policy

**AI가 위 항목을 추측하지 않는다.**

------------------------------------------------------------------------

## 7. 권장 문서 구조

``` text
docs/
├── 00_PROJECT_VISION.md
├── 01_SYSTEM_ARCHITECTURE.md
├── 02_SYSTEM_CONTRACT.md
├── 03_INTERFACES.md
├── 04_DB_SCHEMA.md
├── 05_DEMO_SCENARIO.md
└── 06_TEST_PLAN.md
```

각 subsystem에도 README를 둔다.

Repository root `AGENTS.md` 핵심 문구:

``` text
시스템 문서는 전체 시스템을 새로 구현하라는 요청이 아니다.
이미 확정된 System Contract다.

작업 전 Architecture, Contract, Interfaces, DB Schema,
현재 subsystem README를 확인한다.

허용 수정 범위 밖 파일을 임의 수정하지 않는다.

금지:
- interface/DB/ROS 이름 임의 변경
- dependency/version 임의 변경
- 단위/좌표계/hardware API 추정
- 안전 검증 제거
- 테스트 약화

계약으로 구현 불가능하면 우회하지 말고:
BLOCKER:
REQUIRED CHANGE:
AFFECTED INTERFACE:
REASON:
형식으로 보고한다.
```

------------------------------------------------------------------------

## 8. AI에게 작업 요청하는 형식

나쁜 요청: **"Perception 시스템 만들어줘."**

좋은 요청:

``` text
목표:
camera_frame → block_detection[] 구현

수정 가능:
perception/**

수정 금지:
interfaces/**
robot/**
db/**

입력/출력:
docs/03_INTERFACES.md 계약 준수

완료 조건:
- fixture에서 지정 블록 검출
- schema validation PASS
- confidence 존재
- 검출 실패 시 빈 배열
- 예외로 process 전체 종료 금지

구현 후:
1. 기존 test 실행
2. 신규 unit test 추가
3. 변경 파일 목록 보고
4. interface 변경 필요 여부 보고
```

**작은 계약 + Acceptance Criteria**가 기본이다.

------------------------------------------------------------------------

## 9. Ownership / Change Request

``` text
/perception → A
/reasoning, /planning → B
/robot → C
/hmi, /simulation → D
```

공동 계약 영역: `/interfaces`, `/db/schema`, `docker-compose.yml`,
`SYSTEM_CONTRACT`, `INTERFACES`.

개인/개인 AI가 공동 영역을 임의 수정하지 않는다.

변경 요청:

``` text
CHANGE ID:
REQUESTER:
CURRENT CONTRACT:
PROPOSED CHANGE:
WHY:
AFFECTED MODULES:
BREAKING: YES/NO
MIGRATION:
TEST IMPACT:
```

Breaking change는 Integration Owner 승인 후 적용한다.

------------------------------------------------------------------------

## 10. 팀원이 하지 말아야 할 일

1.  자기 편의를 위해 interface 몰래 변경
2.  AI 추천만으로 새 framework 도입
3.  dependency 문제를 전체 upgrade로 해결
4.  migration 없이 DB 직접 수정
5.  unit/mock test 없이 실제 robot부터 테스트
6.  타 팀원 코드를 대규모 refactor
7.  Critical Path blocker를 오래 숨김
8.  마지막 이틀까지 integration 미룸
9.  secret commit
10. "내 PC에서는 된다"를 완료 조건으로 사용
11. AI 코드를 이해하지 않고 merge
12. 테스트 실패 상태에서 기능 추가
13. Hero Scenario가 불안정한데 Stretch Goal 착수

------------------------------------------------------------------------

## 11. 팀원의 AI가 하지 말아야 할 일

1.  repository 전체 재설계
2.  폴더 구조 임의 변경
3.  DB 추가/교체
4.  REST/ROS2 protocol 임의 교체
5.  ROS2 interface 이름 변경
6.  단위/좌표계 추측
7.  hardware API 추측
8.  robot safety limit 임의 수정
9.  DB를 message broker로 사용
10. LLM 출력을 실제 robot command에 직접 연결
11. `except: pass` 등으로 오류 숨기기
12. 테스트 삭제/assertion 약화
13. secret 출력/commit
14. unrelated file 대규모 정리
15. dependency 일괄 최신화
16. MOCK/SIM/REAL 경계 무시
17. "작동할 것"을 테스트 결과처럼 보고
18. fallback 결과를 실제 성공처럼 보고

------------------------------------------------------------------------

## 12. MOCK / SIM / REAL 모드

``` text
APP_MODE=MOCK
APP_MODE=SIM
APP_MODE=REAL
```

-   **MOCK:** 개발/CI. 가짜 camera/robot. 실제 robot command 금지.
-   **SIM:** Isaac/3D. simulation command만 허용.
-   **REAL:** 실제 M0609. safety validation + allowlist skill 필수.

환경변수 누락을 REAL로 해석하지 않는다. 기본값은 MOCK 또는 안전한
실패다. 현재 mode는 HMI와 로그에 항상 표시한다.

------------------------------------------------------------------------

## 13. Backend State Machine

Backend가 workflow authority를 가진다.

``` text
IDLE → OBSERVING → COMPARING
                  ├─ no deviation → REQUEST_NEXT_PART
                  └─ deviation → REASONING
                                  ├─ ACT → VALIDATING
                                  ├─ ASK → WAITING_HUMAN
                                  ├─ CORRECT → CORRECTION_REQUIRED
                                  └─ REPLAN → PLANNING
PLANNING → VALIDATING → ROBOT_READY → EXECUTING
→ VERIFYING → COMPLETE / RETRY / FAILED
```

AI가 새로운 workflow state를 즉석 생성하지 않는다.

------------------------------------------------------------------------

## 14. Git / Docker Governance

권장 branch: `main`, `dev`, `feature/perception-*`,
`feature/reasoning-*`, `feature/robot-*`, `feature/hmi-*`.

-   main: 항상 demo 가능
-   dev: integration
-   main 직접 commit 금지
-   merge 전 unit/contract test
-   interface 변경은 별도 PR
-   Day 7 이후 Hero Scenario를 깨는 refactor 금지

Integration Owner는 Compose의
service/network/port/volume/healthcheck/env contract를 관리한다. 각
subsystem owner는 자기 Dockerfile/dependency/health endpoint를 관리한다.

------------------------------------------------------------------------

## 15. 테스트 계층

1.  **Unit** --- subsystem 내부
2.  **Contract** --- JSON/REST/ROS2 계약
3.  **Mock Integration** --- Camera Mock → Perception → Reasoner → HMI →
    Robot Mock
4.  **Real Integration** --- 실제 M0609
5.  **Hero Scenario** --- Human deviation 포함

**Level 1\~3 실패 상태에서 REAL 테스트로 가지 않는다.**

Day 4부터 매일:

``` text
docker compose up
→ PostgreSQL healthy
→ Backend healthy
→ Perception
→ Reasoner
→ HMI
→ Robot Bridge
→ ROS2/M0609
→ DB experiment log
```

------------------------------------------------------------------------

## 16. Error / Logging

최소 공통 필드: `request_id`, `session_id`, `component`, `status`,
`error_code`, `message`, `timestamp`, `latency_ms`.

status 예: `READY`, `RUNNING`, `WAITING`, `DEGRADED`, `FAILED`,
`STOPPED`.

AI decision에는 최소: - input state version - model/interface version -
structured decision - confidence - validation result - human override

를 기록한다.

------------------------------------------------------------------------

## 17. Security / Reproducibility

-   secret은 `.env`, Git 제외
-   `.env.example`에는 key 이름만
-   DB/API credential 로그 금지
-   robot IP 등 환경값은 config/env
-   모델/API 변경 시 experiment metadata 기록
-   dependency version 고정 또는 제한
-   clean setup 절차 README 유지

------------------------------------------------------------------------

## 18. Definition of Done

Subsystem: - 계약된 I/O 준수 - mock 실행 가능 - unit/contract test
PASS - error state 정의 - README 존재 - Docker/host 경계 명확 - 다른
subsystem 몰래 수정하지 않음

Integration: - `docker compose up` Control Plane 기동 -
migration/healthcheck PASS - Mock E2E PASS - REAL 전 safety checklist
PASS

Hero Scenario: - **Deviation → Reason → Human Confirmation → Replan →
Robot Behavior Change → Continue** - 실제 M0609 포함 반복 성공 - 실패 시
안전 STOP/HOME - DB에 trial evidence 저장

------------------------------------------------------------------------

## 19. 팀 운영

매일 15분:

``` text
1. 어제 완료
2. 오늘 완료 예정
3. BLOCKER
4. 오늘 integration 가능한 interface
```

Critical Path blocker가 2시간 이상 지속되면 공유한다.

새 기능은: 1. Hero Scenario 성공률을 높이는가? 2. 연구 질문을
증명하는가? 3. Critical Path를 해결하는가? 4. 일정 내 안정화 가능한가?

아니면 Backlog/Future Work로 보낸다.

------------------------------------------------------------------------

# 20. 최종 팀 합의

> **사람이 Architecture를 결정하고, AI는 그 Architecture 안의 작은
> 계약을 구현한다.**
>
> **DB는 기억이지 메시지 버스가 아니다.**
>
> **Docker는 재현성 도구이지 로봇 안전계층이 아니다.**
>
> **LLM은 행동을 제안하지만 실제 로봇의 저수준 제어를 생성하지 않는다.**
>
> **Simulation과 AI의 예측보다 실제 세계의 관찰과 실행 결과가
> 우선한다.**
>
> **모르면 추측하지 않고 ASK, 검증되지 않으면 실행하지 않는다.**
