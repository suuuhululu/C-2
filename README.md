# Adaptive Co Assembly — C-2 팀 개발 안내

지원 범위의 LEGO Design을 생성하고, M0609가 블록을 전달하면 사람이 조립합니다. Vision이 실제 상태를 관측하고 Backend가 목표와 비교합니다. 실제 차이가 있으면 사용자 의도를 확인하고 설계를 유지하거나 수정하여 조립을 이어갑니다.

## 처음 읽는 순서

1. [최신 결정·역할·남은 확인](docs/00_CURRENT_DECISIONS.md)
2. [진행 상황과 다음 작업](docs/STATUS.md)
3. [Day 1~4 일정](docs/01_DAY_PLAN.md)
4. [팀원 협업 안내](docs/02_TEAM_GUIDE.md)
5. [Day4 공통 인터페이스 계약](docs/06_CONTRACT_DRAFT.md) — [C/B 연결 합의와 남은 확인](docs/09_C_B_BACKEND_HANDOFF.md)
6. [환경·측정 확인](docs/03_MEASUREMENT_GUIDE.md)
7. [Git·PR·문서 관리](docs/05_REPOSITORY_GUIDE.md)
8. [Isaac Sim 후속 검토](docs/04_ISAAC_SIM.md)

협업 문서는 레포 안 Markdown으로 관리합니다. 새 AI 채팅은 [AGENTS.md](AGENTS.md)를 먼저 읽습니다.

## 현재 상태

`MVP_Day4`의 최신 운영 변경과 실행 조건은 [Day4 통합 안내](docs/D_MVP_DAY4_INTEGRATION.md)를 따른다. STT→C 운영 입력, B callback 연결, 빈 조립판 START·사람 공급 보충·반복 Job을 적용하며 실제 장치 연결은 별도 확인한다.

**C Design·A Planner·Backend·Qt·기본 Board 전달 연결 코드와 모의 통합 검사가 있습니다.** 실제 Camera 생산자 연결, Robot STOP/재개, 음성 API·마이크/스피커와 전체 장치 통합은 별도 현장 검증이 필요합니다. CI는 미구성입니다. 아래 표의 전체 목표를 실기 완료 목록으로 해석하지 않습니다.

현재 로컬 실행부의 게시·검증 범위와 복구 방법은 [기본 실행 버전 기록](docs/D_RUNTIME_BASELINE.md), 실행 절차는 [Robot/HMI 안내](docs/D_BACKEND_RUN_ROBOT_PLAN.md), C 함수·음성 연결은 [C 통합 안내](docs/D_C_FUNCTION_INTEGRATION.md)를 따릅니다. 새 사람 전달 0~12단계는 별도 개발 브랜치에서 진행합니다.

| 구분 | 기준 |
|---|---|
| OS / Docker / GPU | 사용자 확인: Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 |
| 개발 / 장치 | Python 3.12.3 / ROS2 Jazzy / Doosan M0609 / RealSense D435i / OnRobot RG2 gripper |
| Day 4 Design | 키워드 최초 생성 + 변경 의도에 따른 유지 / Revised |
| 지원 범위 | 4점·6점 × 노랑·파랑, 24×24점 Baseplate, 최대 4층 |
| 책임 | 시율 Design·HRI, 세은 Plan·검증, 홍동 Observed, 수현 Backend·Robot·HMI·통합 |
| 물리 작업 | Robot 공급판 → 고정 전달 위치, 사람 조립판 배치·체결·수정 |
| 상태 | Vision Observed → Backend Current 채택, Backend Expected 생성·비교 |
| 배치 | Day 4 1PC, 함수 / callback·Qt 단일 화면·Robot 전달 Action |
| 저장 | 공정은 Job별 주요 이벤트 JSONL, 별도 PostgreSQL 적재·조회는 [DB 이력 안내](docs/D_DB_HISTORY.md) |

환경과 역할 분담은 2026-10-04 사용자 확인입니다. RG2는 gripper입니다. Python은 로컬에서도 3.12.3을 확인했습니다. OS·Docker·GPU는 사용자 제공값이며 실제 설치·driver·장치 호환성은 이번 작업에서 시험하지 않았습니다.

## 전체 흐름

```text
START → 키워드 → 시율 Design → 세은 Plan / 검증 → Backend 채택
→ Robot 전달 → 사람 조립 → Vision Observed → Backend Current / Expected 비교
   ├─ 완료 확인 → 다음 Step
   ├─ 실제 차이 → 시율 의도 확인 → 유지 / 수정 → 세은 재계획 → Backend 채택
   └─ 판단 불가 → Current 유지·다음 전달 보류
→ 최종 채택 Design 전체 배치 확인 → 완료
```

전달 완료와 조립 완료를 분리합니다. PLACE만 수행하며 홍동이 정한 완료 확인 시점의 관측을 Backend가 비교합니다. 가려진 확인 완료 아래층은 보존합니다. Qt는 반폭 고정 단일 창에 채택 Design 미리보기·목표/관측·진행·Robot/전달판/공급·질문/사유·시작/정지/재개를 함께 표시합니다. 상세 규칙은 [공통 계약](docs/06_CONTRACT_DRAFT.md)을 따릅니다.

## 근거와 참고자료

- 최신 근거: [TBD 결정 목록](https://app.notion.com/p/TBD-3efffcadfd2680ea9119c1fdf22e566a). 작성된 최신 결정이 이전 문서보다 우선합니다.
- `docs/reference/`는 과거 합의·정책·GT 원본입니다. 역할·최초 생성·DB·상태 계약은 현재 문서를 먼저 읽습니다.
- 원본 사진·Depth·영상은 레포에 포함되지 않습니다. GT의 이미지 파일명은 원자료 기록입니다.
