# Adaptive Co Assembly — C-2 팀 개발 안내

LLM과 사용자가 대화로 **커스텀 의자**를 설계·확정하면 조립 순서와 경로를 생성하고 Backend·HMI에 반영합니다. 로봇은 supply board에서 블록을 집어 assembly board에 직접 결착하며, 지지가 필요한 부분은 사람에게 고정 도움을 요청합니다. 계획에 필요한 블록 사용 종료 → Vision 확인과 Backend 최종 조립 판정 → 사용자별 DB 저장·웹앱 반영의 세 단계로 마칩니다.

**2026-10-07 최종 MVP 목표이며 개발 과정에서 수정될 수 있습니다.** 문서 목표와 현재 구현·실제 장치 검증은 구분합니다.

## 처음 읽는 순서

1. [최종 MVP 흐름·세 단계 종료·현재 구현과의 차이](docs/10_FINAL_MVP.md)
2. [최신 결정·남은 합의](docs/00_CURRENT_DECISIONS.md)
3. [진행 상황과 검증 기록](docs/STATUS.md)
4. [개발·통합 단계](docs/01_DAY_PLAN.md) · [팀원 협업 안내](docs/02_TEAM_GUIDE.md)
5. [기존 Day4 계약과 최종 MVP 이행](docs/06_CONTRACT_DRAFT.md) · [C/B 기존 연결 합의](docs/09_C_B_BACKEND_HANDOFF.md)
6. [수현 접촉 실행·사람 지원 연구 설계](docs/suhyun_individual_research_topic.md)
7. [환경·측정 확인](docs/03_MEASUREMENT_GUIDE.md) · [Git·PR·문서 관리](docs/05_REPOSITORY_GUIDE.md)
8. [Isaac Sim 후속 검토](docs/04_ISAAC_SIM.md)

협업 문서는 레포 안 Markdown으로 관리합니다. 새 AI 채팅은 [AGENTS.md](AGENTS.md)를 먼저 읽습니다.

## 현재 구현과 최종 목표

GitHub main `95259bd`에는 C Design·A Planner·Backend·Qt·기존 Board 전달 연결 및 독립 PostgreSQL 이력 코드가 있습니다. 아래는 소스와 기존 기록을 확인한 결과이며 이번 문서 작업에서 앱·장치 시험을 다시 실행한 결과가 아닙니다.

| 구분 | 현재 게시 구현 | 최종 MVP 목표 / 남은 작업 |
|---|---|---|
| 설계 | Initial/Revised·텍스트·음성 입력 | 커스텀 의자 설계 대화·명시적 확정 |
| 계획 | PLACE 순서·기하·Remaining/Replan | 조립 순서와 경로 생성·Backend 채택·HMI 반영 |
| 물리 조립 | Robot 공급판→고정 place board 전달, 사람 조립 | Robot 공급판→assembly board 직접 결착 |
| 사람 지원 | 기존 의도 질문·물리 정리 안내 | 지지 필요 판단·고정 도움 요청·준비 응답·실행 알림 |
| 완료 | 기존 관측 기반 Step·Design 비교 | 블록 사용 종료와 최종 Vision/Backend 판정·저장/반영 구분 |
| HMI / 웹 | Qt 단일 화면; 사용자별 웹 화면 없음 | 지지·진행·종료 표시 및 웹앱 개인 설계·조립 기록; Qt/웹 분담 미확정 |
| 저장 | Job별 JSONL→별도 PostgreSQL 적재·조회, users 표 | 사용자–Job 소유자 연결·현재 설계/조립 기록 저장·웹앱 조회 |

실제 Camera 생산자, Robot STOP/재개·직접 결착·지원 제스처, 최종 완성상태 판정과 사용자별 DB/웹 전체 연결은 별도 검증이 필요합니다. 기존 시험 기록은 [STATUS](docs/STATUS.md), 기본 실행은 [실행 버전 기록](docs/D_RUNTIME_BASELINE.md)과 [Robot/HMI 안내](docs/D_BACKEND_RUN_ROBOT_PLAN.md), DB는 [이력 안내](docs/D_DB_HISTORY.md)를 확인합니다. 기존 명령은 전달 공정용이며 직접 결착 실행 명령이 아닙니다.

## 전체 흐름

```text
서비스 시작 → LLM/사용자 커스텀 의자 대화 → 설계 확정
→ 조립 순서·경로 생성 → Backend 채택·HMI 반영
→ [필요하면 고정 도움 요청·준비 확인] → 공급판 집기·조립판 결착
→ Step 증거 확인 → 다음 Step
→ 1. 필요한 블록 모두 사용
→ 2. Vision 완성상태 확인·Backend 최종 조립 판정과 종료
→ 3. 사용자별 현재 설계·조립 기록 DB 저장·웹앱 반영
```

계획·경로와 실행 전제가 준비되면 첫 Step을 바로 실행합니다. HIGH 지지는 준비 응답과 알림 후 실행합니다. 정상 Step마다 수동 승인을 요구하지 않으며, 명령 완료·블록 사용 종료만으로 조립 완료를 선언하지 않습니다. 불확실·실패·저장/반영 실패는 각각 기록·표시합니다.

## 환경·지원 범위와 근거

기존 환경은 사용자 제공 Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 / Python 3.12.3 / ROS2 Jazzy / M0609 / D435i / RG2입니다. 기존 구현 범위는 4점·6점 × 노랑·파랑, 24×24 stud, 최대 4층입니다. 최종 의자 구조·직접 결착 가능 범위와 보정은 확인이 필요하며 블록·층 범위를 임의 확대하지 않습니다.

- 최신 목표는 [최종 MVP](docs/10_FINAL_MVP.md), 상세 연구 근거는 [첨부 연구 설계](docs/suhyun_individual_research_topic.md)를 봅니다.
- [참고자료 적용 안내](docs/reference/README.md)의 원본 정책·과거 계획·GT는 보존합니다. 과거 TBD·Day4 흐름보다 최신 사용자 결정이 우선합니다.
- 원본 사진·Depth·영상은 레포에 포함되지 않습니다. GT 이미지 파일명은 원자료 기록입니다.
