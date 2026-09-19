# GitHub 문서 정합성 점검 · 2026-09-19

기준 main `301ea6e`. 사용자 요청으로 루트 docs와 ws_cobot_pjt/docs의 Markdown을 대상으로 현재/과거 범위, 그리퍼 열기·집기·반납·청소, 도구·프레임·계약 버전·구현 상태를 검색하고 변경 관련 내용을 대조했다. 링크·UTF-8·충돌 표시는 저장소 검사로 확인한다. 외부 링크의 모든 본문이나 과거 실기를 다시 검증했다는 뜻은 아니다.

## 점검 결과

기존 관리 Markdown 31개를 점검했다. 아래 표는 이번 작업의 변경 여부와 이유다. 공통 타입·패키지·서버 README, AGENTS·루트 README도 별도로 맞췄다.

| 기존 파일 | 처리 | 이유 |
| --- | --- | --- |
| [docs/DEPENDENCIES.md](../../docs/DEPENDENCIES.md) | 갱신 | 현재 앱/공통 타입 의존성과 과거 환경 기록 구분 |
| [docs/GIT_GUIDE.md](../../docs/GIT_GUIDE.md) | 갱신 | 공통 ROS 패키지는 있으나 CI는 ROS 빌드를 안 함 |
| [docs/ISSUE_AUTOMATION.md](../../docs/ISSUE_AUTOMATION.md) | 유지 | 공정 변경이 Issue 자동화 규칙을 바꾸지 않음 |
| [docs/PROJECT_GUIDE.md](../../docs/PROJECT_GUIDE.md) | 갱신 | 현재 축소 범위와 담당 제안 링크; 일정·배정 자동화 유지 |
| [docs/REFERENCES.md](../../docs/REFERENCES.md) | 유지 | 외부 원문·조회 시점 출처 기록 유지 |
| [docs/REVIEW_STATUS.md](../../docs/REVIEW_STATUS.md) | 갱신 | PR #21까지의 최신 main, 미병합 #23/#25/#27과 이번 작업 브랜치 구분 |
| [docs/TEAM_LEAD_GUIDE.md](../../docs/TEAM_LEAD_GUIDE.md) | 유지 | 팀장이 담당자와 최종 배정하는 기존 절차 유지 |
| [docs/TEAM_ONBOARDING.md](../../docs/TEAM_ONBOARDING.md) | 갱신 | 현재 필수 읽기·열기 금지·동일 타입 버전 안내 |
| [docs/WORKSPACES.md](../../docs/WORKSPACES.md) | 갱신 | 현재 팀 패키지·HMI 존재와 과거 미구현 기록 구분 |
| [ws_cobot_pjt/docs/ALGORITHM_VALIDATION.md](ALGORITHM_VALIDATION.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/CLAY_0918_MIGRATION.md](CLAY_0918_MIGRATION.md) | 갱신 | 현 구조로의 이관 대상에서 tool_sequence/열기 제외 |
| [ws_cobot_pjt/docs/EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) | 갱신 | 집기·세척 시험을 장착 확인·3점/1점 보정·정지 시험으로 갱신 |
| [ws_cobot_pjt/docs/HARDWARE_STATUS.md](HARDWARE_STATUS.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/HMI_MONITOR_IMPLEMENTATION.md](HMI_MONITOR_IMPLEMENTATION.md) | 갱신 | 고정 드릴 MOCK·v2·이전 검증과 이번 검증 구분 |
| [ws_cobot_pjt/docs/HMI_PATH_QUALITY_PROPOSAL.md](HMI_PATH_QUALITY_PROPOSAL.md) | 갱신 | 압력/부분 경로 계약은 여전히 별도 합의임을 명시 |
| [ws_cobot_pjt/docs/INTERFACE_GUIDE.md](INTERFACE_GUIDE.md) | 갱신 | 고정 드릴 흐름·책임·v2와 미구현 범위 |
| [ws_cobot_pjt/docs/INTERFACE_RECOMMENDATION.md](INTERFACE_RECOMMENDATION.md) | 갱신 | schema v2, TOOL_CHECK, 자세/획/J6, 보정·배포 규칙 |
| [ws_cobot_pjt/docs/LEGACY_CLAY_ARCHIVE.md](LEGACY_CLAY_ARCHIVE.md) | 유지 | 백업·원본 해시·복구 기록 유지 |
| [ws_cobot_pjt/docs/LESSONS_ROBOT.md](LESSONS_ROBOT.md) | 갱신 | 현재 열기 금지가 과거 L9·자동 복귀 사례보다 우선함을 명시 |
| [ws_cobot_pjt/docs/PROJECT_PLAN.md](PROJECT_PLAN.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/SERVICE_FLOW.md](SERVICE_FLOW.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/SVG_VECTORIZATION_VALIDATION.md](SVG_VECTORIZATION_VALIDATION.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/SYSTEM_STRUCTURE.md](SYSTEM_STRUCTURE.md) | 갱신 | 목표 공정 8→6개 모듈, 실제 파일과 목표 파일 구분 |
| [ws_cobot_pjt/docs/VALIDATION_TEMPLATE.md](VALIDATION_TEMPLATE.md) | 유지 | 공통 검증 양식 유지; 이번 시험은 별도 기록 작성 |
| [ws_cobot_pjt/docs/architecture/README.md](architecture/README.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/daily/2026-09-17.md](daily/2026-09-17.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/daily/2026-09-18-candle.md](daily/2026-09-18-candle.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/daily/2026-09-18.md](daily/2026-09-18.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |
| [ws_cobot_pjt/docs/evidence/CANDLE_0918_EVIDENCE.md](evidence/CANDLE_0918_EVIDENCE.md) | 유지 | 9/18 evidence의 당시 의미/미확정 항목 기록 유지 |
| [ws_cobot_pjt/docs/validation/2026-09-19-c2-interfaces.md](validation/2026-09-19-c2-interfaces.md) | 갱신 | 과거 설계·실측·시험 기록으로 표시하고 최신 고정 드릴 기준에 연결 |

## 도면·측정 증거

- 9/18 `architecture/C2_SYSTEM_ARCHITECTURE.drawio`와 `overview.png`는 보관본으로 유지하며 README에 현재 사용 금지를 표시했다. 최신 6개 모듈 트리와 흐름은 SYSTEM_STRUCTURE/INTERFACE_GUIDE가 원본이다. 그림 자체를 최신이라고 보고하지 않는다.
- evidence 디렉토리의 JSON·YAML·PNG·해시 manifest는 수정하지 않았다. 받침대 20 mm의 과거 수치를 50 mm로 바꾸면 당시 증거가 훼손되므로 새 실측 파일과 설정 버전을 기다린다.
- 새 `workcell.yaml`·`tools.yaml`은 main에 아직 없다. 예상 z≈234.4 mm나 보정 허용차를 채운 실행 파일을 만들지 않고 config README에 확인 대기 항목을 기록했다.
- 담당 배정은 제안이며 team.json·Issue·일정·리뷰 승인자를 변경하지 않았다.

## 새 인계 문서

- [운영·인터페이스 변경 결정](C2_FIXED_DRILL_20260919.md)
- [이번 검증 기록](validation/2026-09-19-fixed-drill.md)
- [Slack 공유용 문안](SLACK_FIXED_DRILL_20260919.md)
