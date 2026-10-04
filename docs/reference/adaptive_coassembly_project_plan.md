# Adaptive Co-Assembly Agent

## LEGO 기반 Human--Robot Collaborative Assembly under Uncertainty

> **핵심 문장:** Human changes the plan. The system adapts instead of
> stopping.

## 0. 문서 목적

4인 팀이 약 10일 동안 개발하기 전에 문제 정의, MVP, 역할, 인터페이스,
일정, 마일스톤, Critical Path, 리스크와 평가 기준을 하나의 기준으로
합의한다.

**운영 원칙:** 새 기능보다 end-to-end 한 사이클의 안정적 성공이
우선이다.

------------------------------------------------------------------------

# 1. 문제 정의

초기 아이디어는
`설계도 → 3D 미리보기 → 사용자 조립 → 오조립 검출 → 다음 LEGO를 M0609가 전달`하는
조립 보조 시스템이다.

하지만 고정된 정답 sequence를 따라가는 것만으로는 기존 HRC/assembly
연구와 차별성이 약하다.

### 수정된 연구 질문

> **사람이 원래 계획과 다른 조립을 했을 때, 시스템이 무조건 오류로
> 처리하지 않고 사람의 의도와 현재 물리 상태를 고려하여 새로운 계획으로
> 협업을 계속할 수 있는가?**

연구 초점은 **오류 검출이 아니라 deviation 이후의 적응**이다.

------------------------------------------------------------------------

# 2. 핵심 개념: Adaptive Co-Assembly

  상태                         의미                      기본 대응
  ---------------------------- ------------------------- ------------
  `NO_DEVIATION`               설계와 일치               계속
  `VALID_ALTERNATIVE`          다르지만 목표 달성 가능   KEEP / ASK
  `CORRECTABLE_ERROR`          이후 조립을 방해          CORRECT
  `INTENTIONAL_MODIFICATION`   사용자의 의도적 변경      REPLAN
  `UNKNOWN`                    판단 불확실               ASK / STOP

핵심 정책:

**Observe → Compare → Reason → Act or Ask → Validate → Replan → Execute
→ Verify**

------------------------------------------------------------------------

# 3. Hero Scenario

1.  사용자가 정상 설계에 따라 LEGO를 조립한다.
2.  사용자가 의도적으로 다른 블록을 장착한다.
3.  Vision이 Target과 Current의 차이를 발견한다.
4.  시스템이 변경의 구조적 가능성과 의도를 판단한다.
5.  불확실하면 "이 변경을 유지하시겠습니까?"라고 묻는다.
6.  사용자가 `KEEP`을 선택한다.
7.  현재 상태를 보존하는 Adapted Plan을 생성한다.
8.  변경된 3D Preview를 보여준다.
9.  M0609가 **원래 계획이 아니라 Adapted Plan에서 필요한 다음 블록**을
    전달한다.
10. 사용자가 계속 조립한다.

> **이 한 사이클이 반복 가능하게 동작하면 MVP 성공이다.**

------------------------------------------------------------------------

# 4. 연구·산업적 의미

LEGO는 제품이 아니라 **controlled experimental platform**이다. 저렴하고
반복·분해가 쉽고 ground truth 설계가 있으며 의도적인 오류를 만들기 쉽다.

장기 문제는 **Design-aware collaborative assembly under human
intervention and uncertainty**이며, 다품종 소량생산, customized
assembly, repair, disassembly, remanufacturing, flexible
manufacturing으로 확장할 수 있다.

### 장점

-   Human deviation을 핵심 문제로 다룬다.
-   AI가 불확실하면 `ACT OR ASK`를 사용해 Human-in-the-loop를 구현한다.
-   Vision, LLM/VLM, Planner, Isaac/3D, M0609, HMI 각각의 존재 이유가
    명확하다.
-   팀원별 기술 ownership이 남으면서 하나의 closed-loop Physical AI
    system을 경험한다.

### 단점과 대응

1.  **유사 연구가 많음** → 기술 조합이 아니라
    `ACT / ASK / CORRECT / REPLAN` 정책에 초점을 둔다.
2.  **10일에 비해 시스템이 큼** → Hero Scenario 하나를 MVP로 동결한다.
3.  **LEGO가 장난감처럼 보일 수 있음** → benchmark/testbed로 정의하고
    `LEGO → Customized Assembly → Repair → Remanufacturing` 확장을
    제시한다.
4.  **LLM/VLM의 3D 판단을 그대로 신뢰하기 어려움** →
    `AI proposes → constraint/simulation verifies → Human approves if uncertain → Robot executes → Vision verifies`.
5.  **데모 한 번은 연구 결과가 아님** → Baseline과 Proposed System을
    반복 실험한다.

------------------------------------------------------------------------

# 5. 시스템 아키텍처

``` text
                    HUMAN
                      │
                 HMI / ASK
                      │
CAMERA ───────► PERCEPTION
                      │
                CURRENT STATE
                      │
TARGET DESIGN ────────┼──────► DEVIATION DETECTOR
                                        │
                                   AI REASONER
                                        │
                              ACT / ASK / CORRECT
                                    / REPLAN
                                        │
                                  ADAPTED PLAN
                                   ↙        ↘
                           ISAAC / 3D      ROBOT CMD
                           VALIDATION          │
                                              ▼
                                            M0609
                                              │
                                         PART DELIVERY
                                              │
                                            HUMAN
                                              │
                                      CAMERA → VERIFY
```

### 설계 원칙

1.  LLM이 trajectory를 생성하지 않는다.
2.  모든 subsystem은 mock data로 독립 테스트 가능해야 한다.
3.  공통 interface는 Day 1 이후 임의 변경하지 않는다.
4.  AI 출력은 structured output을 기본으로 한다.
5.  Robot은 allowlist된 skill만 실행한다.
6.  실제 Vision/Robot feedback을 최종 truth로 취급한다.

------------------------------------------------------------------------

# 6. 공통 데이터 모델

``` json
{
  "session_id": "001",
  "target_state": {},
  "current_state": {},
  "deviation": {"detected": true, "type": "PART_SUBSTITUTION"},
  "decision": {"action": "ASK", "confidence": 0.73},
  "human_response": "KEEP",
  "adapted_state": {},
  "next_part": {"type": "2x4", "color": "blue", "slot": 3}
}
```

권장 저장소:

``` text
project/
├── perception/
├── reasoning/
├── planning/
├── robot/
├── simulation/
├── hmi/
├── interfaces/
│   ├── schemas/
│   ├── ros_msgs/
│   └── examples/
├── tests/
├── experiments/
├── docs/
└── README.md
```

`interfaces/`는 시스템 계약 영역이다.

------------------------------------------------------------------------

# 7. 4인 역할 분담

## A. Perception / Digital State Owner

**질문:** 현재 사람이 무엇을 조립했는가?

담당: Camera, LEGO detection, 색/종류 분류, 위치/orientation, Current
Assembly State.

**출력:** `current_state.json`

**완료 조건:** Camera → Current State가 반복적으로 생성된다.

**MVP 제한:** LEGO 3\~5종, 색 2\~3종, 고정 assembly zone, 제한된
orientation.

## B. AI Reasoning / Adaptive Planning Owner

**질문:** 현재 차이를 어떻게 처리해야 하는가?

담당: deviation classification, LLM/VLM reasoning, confidence,
ACT/ASK/CORRECT/REPLAN, Adapted Plan.

``` json
{
  "deviation_type": "VALID_ALTERNATIVE",
  "confidence": 0.72,
  "decision": "ASK",
  "question": "이 변경을 유지하시겠습니까?",
  "structural_validity": true
}
```

**완료 조건:** Mock state 입력 시 일관된 decision과 adapted plan 반환.

**추가 역할:** Research Owner.

## C. M0609 / Robot Skill Owner

**질문:** 요청받은 다음 부품을 안전하고 반복 가능하게 전달할 수 있는가?

담당: M0609/gripper, pick, handover, release, home, execution feedback.

허용 skill:

``` text
pick(slot)
deliver()
release()
return_home()
stop()
```

**완료 조건:** AI 없이 slot 번호만으로 해당 LEGO를 안정적으로 전달한다.

## D. Simulation / HMI / Integration Owner

**질문:** 사람이 현재 상황과 AI 판단을 이해하고 전체 subsystem이
연결되는가?

담당: Target/Current/Adapted preview, ASK/KEEP/CORRECT UI, Isaac Sim
또는 3D preview, integration, subsystem status.

**완료 조건:** Mock state만으로 전체 HMI flow를 재현한다.

**추가 역할:** Integration Owner.

------------------------------------------------------------------------

# 8. 핵심 MVP

### 반드시 구현

1.  Target Assembly
2.  Camera → Current State
3.  정상 조립
4.  사람이 다른 LEGO 장착
5.  Deviation 감지
6.  AI가 deviation 분류
7.  필요 시 ASK
8.  사용자 KEEP
9.  Adapted Plan
10. 변경된 Preview
11. 새로운 `next_part`
12. M0609 부품 전달
13. 작업 계속

### MVP에서 제외

-   모든 LEGO 인식
-   범용 자연어 설계 생성
-   VLA/RL 신규 학습
-   완전한 Sim2Real
-   정밀 Digital Twin physics
-   자동 LEGO 체결
-   대규모 synthetic dataset
-   자유 topology 전체 지원
-   음성 인터페이스
-   모바일 앱

### Stretch Goal

MVP 안정화 후에만: Force-based handover, Isaac collision/reachability
validation, synthetic data, 복수 alternative plan, confidence 기반
ACT/ASK, robot failure recovery.

------------------------------------------------------------------------

# 9. Critical Path

``` text
Target Design
  ↓
Current State
  ↓
Deviation Detection
  ↓
Reasoning
  ↓
Human Decision
  ↓
Replanning
  ↓
Next Part
  ↓
Robot Delivery
```

-   **CP1 Assembly State Schema:** Day 1 확정.
-   **CP2 Perception → State:** 없으면 reasoning 불가.
-   **CP3 Replanning:** 변경 후 `next_part`가 실제로 달라져야 핵심이
    증명된다.
-   **CP4 Robot Delivery:** 실제 M0609 연결이 필요하다.
-   **CP5 Integration:** 개별 성공이 아니라 end-to-end 성공이 필요하다.

------------------------------------------------------------------------

# 10. 10일 개발 일정 / 마일스톤

  -----------------------------------------------------------------------
  Day                     목표                    Gate / Milestone
  ----------------------- ----------------------- -----------------------
  1                       Hero Scenario, LEGO     **M0 Interface Freeze**
                          종류, JSON schema, ROS2 
                          API, 좌표/단위, Git     
                          규칙 확정               

  2                       각 subsystem skeleton + 독립 실행 가능
                          mock test               

  3                       정상 Happy Path         **M1 Subsystems Ready**

  4                       Camera → State →        **M2 E2E v0**
                          Reasoner → HMI → Robot  
                          최초 연결               

  5                       Deviation 감지 + ASK UI Deviation이 UI까지 전달

  6                       KEEP → Adapted Plan →   **M3 Core Loop**
                          next_part 변경 → Robot  

  7                       Hero Scenario 반복, 3회 **M4 Demo Freeze**
                          연속 성공 목표          

  8                       timeout, 재촬영,        **M5 Demo Candidate**
                          invalid JSON, pick      
                          실패, stop/home 등      

  9                       반복 실험, 로그, 영상,  **M6 Evidence Ready**
                          지표                    

  10                      새 기능 금지,           **M7 Final Release**
                          리허설/발표/태그        
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 11. 일정 관리 정책

매일 15분 Stand-up:

``` text
1. 어제 완료
2. 오늘 완료 예정
3. Blocker
4. 오늘 integration 가능한 interface
```

Task 상태:
`BACKLOG → READY → IN PROGRESS → BLOCKED → INTEGRATION READY → DONE`

우선순위: - **P0:** Hero Scenario를 막음 - **P1:** 연구 결과/안정성에
중요 - **P2:** 있으면 좋음

규칙: - Critical Path blocker가 2시간 이상 지속되면 즉시 공유. - 일정이
밀리면 `원인 / 영향 / 우회안 / 새 완료시각` 기록. - Day 4부터 매일 최소
1회 integration test. - Day 7 이후 P2 신규 기능 금지.

------------------------------------------------------------------------

# 12. Definition of Done

### Subsystem DoD

-   입력/출력 schema 준수
-   mock test 가능
-   오류 상태 반환
-   최소 로그 남김
-   실행 방법 README 존재

### MVP DoD

-   Hero Scenario 3회 연속 성공
-   M0609 포함 end-to-end
-   사람이 KEEP/CORRECT 선택 가능
-   Adapted Plan 때문에 실제 `next_part`가 변경됨
-   실패 시 안전하게 STOP/HOME 가능
-   발표용 로그/영상 확보

------------------------------------------------------------------------

# 13. 실험 계획

### Baseline

`Deviation → ERROR → 원상복구 요구`

### Proposed

`Deviation → Reason → ASK/ADAPT → Continue`

테스트 케이스: 1. 정상 2. 색만 변경 3. 동일 geometry 대체 4. 구조적으로
가능한 변경 5. 구조적으로 불가능한 변경 6. 의도 불명 변경

권장 지표: - Deviation detection accuracy - Decision accuracy -
Replanning success rate - End-to-end task completion rate - Human
correction count - Wrong autonomous decision count - Task completion
time - API/Reasoning latency - Robot delivery success rate

각 trial은 `scenario_id`, target/current/adapted state, AI
decision/confidence, human response, next_part, robot result,
timestamps를 저장한다.

------------------------------------------------------------------------

# 14. 리스크 레지스터

  -----------------------------------------------------------------------
  리스크                  영향                    우선 대응
  ----------------------- ----------------------- -----------------------
  Vision 인식 불안정      전체 CP 차단            고정 작업영역·블록 종류
                                                  축소·재촬영

  LLM 출력 변동           통합 실패               JSON schema
                                                  validation +
                                                  retry/fallback

  Replanning 과도한       핵심 기능 지연          제한된 assembly graph와
  복잡성                                          규칙 기반 validator

  M0609 pick 실패         데모 중단               고정 slot/jig, 단순
                                                  pick pose

  Isaac 세팅 지연         일정 손실               3D preview fallback;
                                                  Isaac은 Stretch

  통합 지연               최종 실패               Day 4 첫 Vertical
                                                  Slice, 이후 매일 통합

  기능 욕심               일정 붕괴               MVP Freeze / P2 금지

  AI 오판                 잘못된 행동             ACT/ASK threshold +
                                                  deterministic
                                                  validation
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 15. Isaac Sim 사용 정책

Isaac Sim은 **필수 MVP가 아니다.** 프로젝트의 핵심은 Adaptive
Co-Assembly loop다.

우선순위: 1. Target / Current / Adapted 3D Preview 2. Candidate plan
constraint check 3. Collision / reachability validation 4. Synthetic
data 5. Digital Twin 6. Sim2Real 연구

원칙: \> **LLM proposes. Simulation verifies where useful. Reality
decides.**

Isaac 때문에 Day 4 Vertical Slice가 늦어지면 즉시 fallback 3D preview로
전환한다.

------------------------------------------------------------------------

# 16. Git / 통합 정책

권장 branch: - `main`: 항상 데모 가능한 상태 - `dev`: 통합 -
`feature/perception` - `feature/reasoning` - `feature/robot` -
`feature/hmi-sim`

규칙: 1. `main` 직접 개발 금지. 2. Interface 변경은 PR에
`BREAKING INTERFACE CHANGE` 표기. 3. Merge 전 mock/interface test. 4.
Day 7에 demo tag 생성. 5. 실험 데이터와 결과 로그도 버전 관리 가능한
형태로 보존.

------------------------------------------------------------------------

# 17. 팀 의사결정 기준

새 기능 제안이 나오면 아래 순서로 판단한다.

1.  Hero Scenario 성공률을 높이는가?
2.  연구 질문을 더 명확하게 증명하는가?
3.  Critical Path blocker를 해결하는가?
4.  Day 7 전 안정화 가능한가?

하나도 해당하지 않으면 **Backlog / Future Work**로 이동한다.

------------------------------------------------------------------------

# 18. 2027 확장 로드맵

``` text
2026
LEGO Adaptive Co-Assembly
        ↓
2027
Unknown / Customized Product Assembly
        ↓
Repair + Disassembly
        ↓
Remanufacturing
        ↓
Open-world Human–Robot Collaboration
```

향후 핵심 연구 질문: - AI는 언제 스스로 행동하고 언제 사람에게 물어야
하는가? - 설계와 실제가 다를 때 어떤 부분을 보존해야 하는가? - 여러 대안
중 비용·시간·안전 관점에서 어떤 계획이 좋은가? - Vision/3D/Force 정보를
어떻게 결합할 것인가? - Digital Twin과 현실의 차이를 어떻게 보정할
것인가?

------------------------------------------------------------------------

# 19. 최종 팀 합의 문장

> **우리는 LEGO를 조립하는 로봇을 만드는 것이 아니다.**
>
> LEGO라는 통제 가능한 환경에서, **사람이 계획을 변경하거나 예상 밖
> 행동을 했을 때 멈추지 않고 현재 현실을 다시 이해하고, 필요한 경우
> 사람에게 질문하며, 계획을 수정해 협업을 계속하는 Physical AI
> 시스템**을 검증한다.
>
> 10일 동안의 성공 기준은 기능의 개수가 아니라 **Deviation → Reason →
> Human Confirmation → Replan → Robot Behavior Change → Continue** 한
> 사이클을 실제 M0609까지 포함해 안정적으로 증명하는 것이다.

------------------------------------------------------------------------

## Kickoff 체크리스트

-   [ ] Hero Scenario 확정
-   [ ] 사용할 LEGO와 Target model 확정
-   [ ] 허용 deviation 2\~3종 확정
-   [ ] `assembly_state` JSON schema 확정
-   [ ] ROS2 topic/service/API 확정
-   [ ] M0609 slot/handover pose 전략 확정
-   [ ] HMI 최소 화면 확정
-   [ ] 담당자 A/B/C/D 확정
-   [ ] Git/branch 규칙 확정
-   [ ] Day 4 Integration 시간 예약
-   [ ] Day 7 Demo Freeze 동의
-   [ ] 실험 시나리오와 로그 포맷 확정
