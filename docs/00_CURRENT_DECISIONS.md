# 현재 결정과 적용 범위

> 2026-10-06 보완: C/B DM 이후 확정 내용과 연결 책임은 [C·B Backend 연결 합의](09_C_B_BACKEND_HANDOFF.md)를 함께 확인합니다. block_id 필수 제외·5분 자동 취소 제외·유한 후보 재생성·촬영 순서·확인 영역·전달판 미확인을 명확히 했습니다. 지지 2 stud 및 관측 묶음 순번 범위는 확인 전 후보/제안입니다.


갱신: 2026-10-05. 사용자가 현재 대화의 결정 사항을 GitHub docs에 반영하도록 요청했습니다. 이 문서와 [공통 계약](06_CONTRACT_DRAFT.md)이 과거 TBD·reference·C 구조 문서의 상충하는 설명보다 우선합니다. **설계 계약의 확정과 실제 구현·장치 검증은 구분합니다.**

## Day4 목표

키워드 → 시율의 전체 Design → 세은의 검증된 Plan → Robot 전달 → 사람 조립 → 홍동의 완료 확인 관측 → 수현의 비교 → 다음 Step. 목표와 실제가 다르면 사람의 의도를 확인하고 KEEP / REVISE 후 재계획합니다.

- 블록: 4점·6점 × 노랑·파랑. 조립판 24×24 stud, 최대 4층.
- Robot은 supply board에서 고정 place board로 전달합니다. 사람이 별도 assembly board에 배치·체결합니다. Plan의 PLACE 좌표는 사람의 조립 목표입니다.
- 정상 Plan은 PLACE만 포함합니다. MOVE / REMOVE는 Day4 MVP에 넣지 않습니다.
- 재고 수량·예약·부족 검사는 제외합니다. 종류·색상별 공급 슬롯 순서만 관리합니다.
- 1PC, LLM / Planner / Backend 함수, Vision callback, Robot ROS2 Action, Qt 단일 화면입니다. 웹 앱·새 HTTP 서버·DB는 필요하지 않습니다.
- 주요 이벤트를 Job별 JSONL 파일 하나에 누적합니다. 실행 상태는 메모리이며 앱 종료 후 이어하기는 제외합니다.
- 카메라 자동 재시작·실행 중 보정 변경·Robot 자동 복구·실패 자동 재시도·체결 강도 판정은 제외합니다.
- LLM의 능동적 목표 변경·확장 판단은 Day4 이후 발전 과제입니다. 현재는 의도 확인과 검증된 Design / Plan 채택 경로를 완성합니다.

## 책임

| 담당 | 소유하는 결과 | 지켜야 할 경계 |
|---|---|---|
| 시율 C | Initial / Revised 전체 Design, 질문·STT·의도 | layer 초과 목표 재설계. 조립 순서·Current·Robot 경로를 결정하지 않음 |
| 세은 A | Plan·Remaining·Replan·기하 검증 | footprint / overlap / support / dependency / 범위 검사. x=23의 6점 0도 목표 등 범위 오류 재검사 |
| 홍동 B | 실제 Observed·관측 가능한 영역·촬영 시점 | 완료 확인 시점 선택. Expected를 관측값으로 반환하지 않음 |
| 수현 D | Current·Expected·Difference·진행·식별·Robot·Qt·로그·통합 | 실제 상태 채택, 오래된 결과 차단, 전달 / 조립 완료 분리 |

최초 전달은 시율 → 세은 → 검증된 Design + Plan을 Backend로 보냅니다. 모든 계산 함수에 Job이나 ROS를 강제하지 않습니다.

## 결정 타임라인

| 순서 | 결정 | 연결 문서 |
|---|---|---|
| 1 | 1층이 최하층, +X 오른쪽 / +Y 위, 각도 표현. 6점 0도 X2 / Y3 | 공통 계약 §1 |
| 2 | 정상 PLACE Plan, before=null / after=목표, 선행 Step은 관측으로 완료 | §2 |
| 3 | 완료 확인 시점은 홍동. OK는 판별 가능, 목표 일치와 별개 | §3 |
| 4 | Current 누적·가림 유지·verified_regions, 최소 ID / 버전, 오래된 결과 무시 | §3~4 |
| 5 | 차이는 사람의 의도 확인 대상. KEEP / REVISE / UNCLEAR | §5 |
| 6 | 최신 Current 기준 Remaining / Replan, 필요할 때만 사람 정리 | §6 |
| 7 | 종류·색상별 공급 순서, observe point, STOP 시 3상황별 재개 | §7 |
| 8 | Qt 반폭 고정 창, 전체 상태 일괄 갱신, 단순 시작 / 정지 / 재개, 전체 Design 미리보기 포함 | §8 |
| 9 | Backend가 실패 처리·보류 사유 관리, Job별 주요 이벤트 JSONL | §9 |
| 10 | 담당별 Fixture → Mock 연결 → 실제 장치 확인. 문서 결정을 연결 완료로 표시하지 않음 | 팀 가이드 |

## 홍동 검토 가능 제안과 실제 연결 확인

카메라는 로봇팔에 장착되어 있고 observe point가 있으며 전달판도 보입니다. observe point의 시야·촬영 타이밍·전달판 판별 방식과 `place_status` 형식은 **홍동이 추후 수정할 수 있는 제안**입니다. 조립판의 verified_regions와 전달판 영역을 섞지 않습니다.

실제 ROS2 Action 이름·msg / cancel / 정지 API, Controller의 중단 후 동작 연결, Qt 바인딩·신호 연결, Vision의 판별 임계값·성능은 구현과 장치 시험에서 확인합니다. 기존 pose / TCP / 속도·보정값을 이 문서에서 추정하지 않습니다.

기존 C 문서의 geometry / grid_x / grid_y / 대문자 색상·KEEP_TARGET / KEEP_CURRENT는 현재 공통 계약과 명칭이 다릅니다. [팀 가이드의 이행 표](02_TEAM_GUIDE.md)를 따릅니다. 이 문서 갱신은 기존 코드의 자동 변경이나 연결 검증 완료를 의미하지 않습니다.

환경은 사용자 제공 Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 / Python 3.12.3 / ROS2 Jazzy / M0609 / D435i / RG2입니다. 설치·driver·장치 호환성은 이 문서 작업에서 시험하지 않았습니다. 과거 원자료는 docs/reference에 보존합니다.
