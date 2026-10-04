# 프로젝트 에이전트 안내

## 작업 전 읽기

README.md → docs/00_CURRENT_DECISIONS.md → docs/STATUS.md → docs/01_DAY_PLAN.md 순서로 읽습니다. 관련 작업에는 docs/02_TEAM_GUIDE.md, docs/06_CONTRACT_DRAFT.md, docs/03_MEASUREMENT_GUIDE.md를 확인합니다. docs/reference/AI_CODE_POLICY.md와 UNIT_TEST_POLICY.md의 작은 작업·사람 리뷰·검증 원칙을 따릅니다.

사용자의 최신 명시적 지시와 최신 TBD 작성 내용이 이전 역할·구조·일정보다 우선합니다. docs/reference는 역사적 출처이며 과거 PostgreSQL·다중 서비스·역할표를 자동 적용하지 않습니다. 확정된 방향·제안·실제 검증을 구분합니다.

## 최신 목표와 책임

- Day 4: 키워드 Initial → Plan 검증 → Robot 전달 → 사람 조립 → 지속 관측 → 실제 차이의 의도 확인 → 유지 / Revised → 재계획 → 진행.
- 시율: Design·질문·STT·의도 해석. 세은: 사람 조립 Plan·Remaining·Replan·검증. 홍동: Observed·품질·오류. 수현: Current·Expected·비교·상태·버전·Robot·HMI·통합.
- Robot은 supply board에서 place board로 전달하며 place board는 조립판이 아닙니다. 배치·체결·물리 수정은 사람 담당입니다.
- 4점·6점 × 노랑·파랑, 24×24점, 최대 4층. 기하·좌표·관측 능력은 계약과 시험으로 확인합니다.
- 환경: Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 / Python 3.12.3 / ROS2 Jazzy / M0609 / D435i / RG2 gripper. 환경·역할은 사용자 재확인, driver·펌웨어·보정값·실제 호환성은 미확인입니다.

## 구현 경계

- 승인된 현재 작업만 진행합니다. 설계문서가 전체 시스템 구현 요청은 아닙니다.
- Day 4 1PC. LLM / Planner / Backend 함수, Vision callback, 웹 HMI API, Robot 전달 Action 방향. Vision Topic 관계·이름·필드는 확인 필요입니다.
- Design 최초 경로는 시율 → 세은 → Design과 검증된 Plan을 Backend. Backend가 전체 상태·대화·진행·goal 발행을 중재합니다.
- Observed는 Vision 출력, Current는 Backend 채택 상태, Expected는 Backend 단일 Owner입니다. Expected와 다르다고 유효 관측을 거절하지 않습니다.
- 가림·부분 관측·실패 시 Current 유지·완료 판단과 다음 전달 보류. 정상 조립 대기와 실제 차이의 세부 구분은 계약 초안입니다.
- 재계획 Expected는 고정 기준 Current와 새 Plan 효과로 계산합니다. Robot 전달 완료를 조립 효과로 반영하지 않습니다.
- Planner는 선행 관계 규칙 기반, 수량 재고 검사는 제외합니다. 공급 슬롯 종류별 1~6 선택·순서는 Robot 책임입니다.
- Day 4는 고정 검증 좌표로 전달합니다. 조립 grid → Robot 변환·실행 중 별도 reachability / 경로 검증을 필수로 추가하지 않습니다.
- LLM이 joint / TCP / 속도 / 힘 / 저수준 궤적을 생성하도록 만들지 않습니다. pose·motion parameter를 임의 추정하지 않습니다.
- STOP·Robot / 통신 오류는 보류·사유 표시·수동 확인 후 재개. 자동 Robot 복구·재시도·종료 후 복구는 제외합니다.
- Intervention의 응답·유효 Plan 후 자동 진행과 STOP / Robot 오류의 수동 재개를 구분합니다.
- Step·질문 하나씩 처리해도 ID·최신성 계약은 필요합니다. 늦은 결과·중복 전달 규칙을 임의 확정하지 않습니다.
- PostgreSQL 제외·파일 로그. JSONL·경로·HMI framework·Schema·ID는 제안과 확정을 구분합니다.
- 이전 GT의 anchor·layer=0·orientation은 원자료 규약입니다. 축 확인·공통 계약 채택 전 전체 모듈에 강제하지 않습니다.
- Mock / Real 입출력 의미를 유지합니다. 모드 누락을 Real로 해석하지 않습니다. Isaac은 후속 검토이며 Day 4 필수 설치가 아닙니다.

## 작은 작업과 검증

작업 목표·수정 범위·입출력·완료 기준을 먼저 확인합니다. 공통 계약이 없으면 초안·Fixture를 준비해 연결 담당자가 확인합니다. contract draft는 구현된 Schema가 아닙니다.

main 직접 개발 대신 feature branch와 사람 리뷰를 사용합니다. 빈 원격은 최소 기반 커밋과 리뷰 변경을 분리하고 게시 전에 사용자에게 수정 내용을 설명합니다. 기존 이력 덮어쓰기·force push는 하지 않습니다.

dependency·framework·무관한 대규모 변경을 피합니다. 문서 작업은 링크·표·정합성으로 확인하며 빈 pytest를 PASS로 표시하지 않습니다. 코드 작업은 관련 L1~L3 후 장치 시험을 별도 기록합니다. 시행하지 않은 시험은 PASS가 아닙니다.

완료 후 STATUS.md에 변경·실제 검증·미검증·다음 작업을 기록합니다. 보고가 필요하면 BLOCKER / REQUIRED CHANGE / AFFECTED INTERFACE / REASON을 남깁니다.
