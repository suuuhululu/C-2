# Adaptive Co Assembly — C-2 팀 개발 안내

지원 범위의 LEGO Design을 생성하고, M0609가 블록을 전달하면 사람이 조립합니다. Vision이 실제 상태를 관측하고 Backend가 목표와 비교합니다. 실제 차이가 있으면 사용자 의도를 확인하고 설계를 유지하거나 수정하여 조립을 이어갑니다.

## 처음 읽는 순서

1. [최신 결정·역할·남은 확인](docs/00_CURRENT_DECISIONS.md)
2. [진행 상황과 다음 작업](docs/STATUS.md)
3. [Day 1~4 일정](docs/01_DAY_PLAN.md)
4. [팀원 협업 안내](docs/02_TEAM_GUIDE.md)
5. [입출력 계약 초안](docs/06_CONTRACT_DRAFT.md)
6. [환경·측정 확인](docs/03_MEASUREMENT_GUIDE.md)
7. [Git·PR·문서 관리](docs/05_REPOSITORY_GUIDE.md)
8. [Isaac Sim 후속 검토](docs/04_ISAAC_SIM.md)

협업 문서는 레포 안 Markdown으로 관리합니다. 새 AI 채팅은 [AGENTS.md](AGENTS.md)를 먼저 읽습니다. [AGENT.md](AGENT.md)는 같은 안내로 연결합니다.

## 현재 상태

**문서 준비 단계입니다. 실행 가능한 앱·ROS adapter·확정 Schema·테스트·CI는 아직 없습니다.** 아래 기능은 최신 목표이며 구현 완료 목록이 아닙니다.

| 구분 | 기준 |
|---|---|
| OS / Docker / GPU | 사용자 확인: Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 |
| 개발 / 장치 | Python 3.12.3 / ROS2 Jazzy / Doosan M0609 / RealSense D435i / OnRobot RG2 gripper |
| Day 4 Design | 키워드 최초 생성 + 변경 의도에 따른 유지 / Revised |
| 지원 범위 | 4점·6점 × 노랑·파랑, 24×24점 Baseplate, 최대 4층 |
| 책임 | 시율 Design·HRI, 세은 Plan·검증, 홍동 Observed, 수현 Backend·Robot·HMI·통합 |
| 물리 작업 | Robot 공급판 → 고정 전달 위치, 사람 조립판 배치·체결·수정 |
| 상태 | Vision Observed → Backend Current 채택, Backend Expected 생성·비교 |
| 배치 | Day 4 1PC, 함수 / callback·웹 HMI API·Robot 전달 Action 방향 |
| 저장 | PostgreSQL 제외·파일 로그. JSONL은 제안 |

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

전달 완료와 조립 완료를 분리합니다. 아직 놓지 않은 현재 블록의 정상 대기와 실제 변경을 구분하는 세부 규칙은 계약 초안에서 확인합니다.

## 근거와 참고자료

- 최신 근거: [TBD 결정 목록](https://app.notion.com/p/TBD-3efffcadfd2680ea9119c1fdf22e566a). 작성된 최신 결정이 이전 문서보다 우선합니다.
- `docs/reference/`는 과거 합의·정책·GT 원본입니다. 역할·최초 생성·DB·상태 계약은 현재 문서를 먼저 읽습니다.
- 원본 사진·Depth·영상은 레포에 포함되지 않습니다. GT의 이미지 파일명은 원자료 기록입니다.
