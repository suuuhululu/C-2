# 현재 결정과 적용 범위

> 2026-10-06 보완: C/B DM 이후 확정 내용과 연결 책임은 [C·B Backend 연결 합의](09_C_B_BACKEND_HANDOFF.md)를 함께 확인합니다. block_id 필수 제외·5분 자동 취소 제외·유한 후보 재생성·촬영 순서·확인 영역·전달판 미확인을 명확히 했습니다. 지지 기준은 2026-10-06 세은의 동의와 수현의 회신에 따라 A/C가 바로 아래층과 겹치는 고유 stud 총 2개 이상으로 통일했습니다. 이는 Day4 기하 검사 기준이며 물리 안정성 검증이 아닙니다. 관측 묶음 순번 범위는 해당 연결 문서의 확인 상태를 따릅니다.


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
| Initial / Revised Design | 시율 | 키워드 최초 생성·변경 의도 반영 |
| Assembly Plan / Step | 세은 | 사람 조립 순서·검증·Remaining·Replan |
| Observed | 홍동 | 촬영 당시 블록 종류·색상·위치·층·방향·시각·신뢰·오류 |
| Current | 수현 Backend | 유효 Observed를 채택한 실제 상태·채택 관측 식별 |
| Expected | 수현 Backend 단일 Owner | 현재 비교 Step까지 조립돼 있어야 할 목표 배치 |
| Difference·채택·System State | 수현 Backend | 목표 / 실제 비교·진행·보류·채택 Design 버전 기록(Design 버전 발급은 시율) |
| Robot Result·source·슬롯 | 수현 Robot Controller | 필요한 종류·색상으로 source 선택·집기·전달 |
| HRI | 시율 질문 문장·재질문·TTS / STT·응답 해석, 수현 HMI 화면 표시·연결 | 질문·현재 응답 연결·유지 / 수정 / 불명확 |
| 통합 | 수현·각 담당 지원 | 모듈별 adapter·Fixture·진단 제공 |

Initial 경로는 시율 → 세은 → Design과 검증된 Plan을 Backend(H01·F08). 모든 데이터 전달이 Backend를 반드시 경유한다는 과거 규칙은 적용하지 않습니다.

## Day 4 범위

- 키워드 기반 최초 Design 생성 포함(F08·G01). Chair는 첫 예시·Fixture이며 임의 LEGO 전체의 창작을 요구하지 않습니다.
- 4점·6점 × 노랑·파랑, 최대 4층, 24×24점 plate(A03). layer는 1-based 1~4(layer 1 = Board 위 첫 LEGO 층)로 팀 합의했습니다. 정확한 기하·허용 방향·축은 확인 필요입니다.
- Robot은 supply → place 고정 좌표·구간으로 전달, 사람은 조립판 배치·체결·물리 수정(D05·D07·E01). place는 블록 전달 위치입니다.
- 색상·사물의 plate x/y 위치·블록 조립점 변경을 시연(A04). 입력·기대 배치·증거는 준비해야 합니다.
- 재고가 충분하다고 가정하고 수량·예약·소모 관리와 부족 검사 제외(B06·D04·G05). 공급 슬롯 순서는 관리합니다.
- 체결 강도 / 불완전 체결 판정·자동 관측 / Robot 복구·자동 재시도·종료 후 복구 제외(D07·C04·E04·G06).
- PostgreSQL 없이 프로젝트 로그 폴더에 주요 이벤트·시각 파일 기록(H05). JSONL은 제안입니다.

## 관측·비교·완료

1. Vision 지속 관측·Observed 반복 제공, 초기 빈 plate도 확인(C04).
2. 비교 정보가 모두 있는 정상 관측은 Expected와 달라도 Current로 채택(C02).
3. 부분 관측·가림·실패·판단 불가는 Current 유지·완료 판단·다음 전달 보류(C02·C03).
4. Expected / Current의 종류·색상·grid·방향·layer·누락·추가 비교. 정규화 값은 일치 여부를 비교하며 실제 판별 범위·오차 확인(C05).
5. 일치 / 차이 있음 / 판단 불가와 위치·항목·기대값·관측값을 반환(C06).
6. Robot 전달 완료와 조립 Step 완료 분리. 유효 관측으로 목표 배치를 확인한 뒤 Step 진행(D07·E02).
7. 최종 채택 Design의 전체 목표 배치 확인 뒤 완료(G01·G03).

confidence는 블록별 종류·방향·색상·층·좌표의 신뢰 정보이며 0.00~1.00, 소수점 두 자리 표현(C01). 산출·임계값·안정 관측·4층 가림 처리는 미정입니다. **아직 현재 블록을 놓지 않은 정상 대기와 실제 변경을 구분할 세부 규칙은 합의 필요입니다.**

## 계획과 Expected

- 최초: Design + 빈 plate + 제약, 재계획: 채택 Design + 최신 Current + 제약(D01).
- 지지·체결 선행 관계를 만들고 정렬하는 규칙 기반 Planner. 목표에 맞는 블록을 Remaining에서 제외하고 사람의 변경·제거 반영(D05·D06).
- bounds·공간 중복·support / 체결·dependency·지원 종류 / 색상 / 층 / 방향 검증. invalid 대상·실패 항목·사유를 Backend로 반환(D04·D10).
- 제거·재배치는 지원 범위에 따라 사람 작업을 포함하거나 미지원 반환. 정확한 동작 목록 미정(A05·D05).
- 계획 중 실제 블록 상태 변화는 채택 보류·재계산. 시각만 갱신된 것은 상태 변화가 아님(D06).
- Expected는 고정 기준 상태와 완료 Step·현재 확인 Step 효과로 매번 계산. 재계획은 기준 Current와 새 Plan 효과만 적용해 중복 누적 방지(D08).
- 조립 확인 후 다음 Step, 미확인 시 유지, 새 Plan 채택 시 재생성. 전달 완료를 조립 효과로 적용하지 않음(D09).

## 공급·Robot

- Planner는 종류·색상 지정, Controller는 해당 공급 슬롯·실제 좌표 선택(D02·D03).
- 종류별 슬롯 1~6. 새 작업은 채운 판의 1번부터, Step·재계획에도 순서 유지, 6번 후 보충 확인 뒤 1번으로 초기화(D02).
- 사전 검증된 고정 좌표·motion 설정. 실행 중 접근 / 변환 / 경로 검사와 조립 grid → Robot 변환 제외(E01·E05·E07).
- 수락·전달 중·전달 완료·실패 반환, 이동·gripper 결과와 최종 전달 완료 구분(D07·E02).
- 오류·timeout·부분 완료는 자동 재시도·재계획 없이 보류·HMI 표시, 사람이 정리·전달 확인 후 재개(E04).
- STOP은 다음 전달 보류·검증한 진행 motion 정지 방식. 실제 정지·TCP·pose·속도·gripper는 수현 실측 / 시험(E03·E05·E07).

## HRI·상태·버전

- 변경 context는 Design·채택 Current·Difference·지원 제약(F01).
- Original 유지 / Revised 생성 / 불명확과 해당 Design 또는 재질문 제공(F02).
- 질문 하나, 당시 Design·Current 보관, 현재 응답만 연결, 다음 전달 보류(F03).
- 불명확은 재질문. 음성 응답은 의미 있는 발화 없이 5분이 지나면 시율이 최종 안내 후 CANCELLED / NO_RESPONSE를 반환하고 수현이 Workflow를 정리(F04, 2026-10-05 개정). Robot / 통신 timeout과 구분합니다.
- 화면·음성 질문, 마이크 / STT 응답. 질문 음성을 답변으로 재인식하지 않음(F05·F07).
- 응답·유효 Plan 후 Intervention 자동 진행, STOP·Robot 오류는 HMI 재개 버튼(F06).
- 상태: 시작 대기 / 음성 키워드 대기 / 설계·계획 생성 / 블록 전달 / 조립 대기 / 의도 확인 / 정지 / 완료(G01).
- Backend가 요청·결과에 Job 연결, 모듈 핵심 함수는 Job 없는 Fixture로 독립 실행(G02).
- 검증된 Design / Plan 함께 채택, 이전 잔여 요청·질문 종료. 진행 goal 중단 시 취소 완료 뒤 새 발행(G03).
- 한 번에 Step·질문 하나, 현재 작업 결과만 사용·중복 전달 방지(G04). 상세 ID·버전·최신성 규칙 미정입니다.
- 종료 후 이어하기 제외, 조립판 비우기·공급판 채우기 후 새 작업(G06).

## 통신·데이터·일정

Day 4 1PC, LLM / Planner / Backend 함수, Vision callback, 웹 HMI API, Robot 전달 Action(H01·H02). H03의 Vision Topic 표현은 callback 관계 정렬이 필요합니다. Action goal 종류·색상 / feedback 진행 / result 성공·실패·사유이며 실제 이름·필드·driver cancel은 확인합니다(H03·H04).

Design 시율, Config 각 담당, Calibration 홍동·수현, 전체 Runtime Backend, 공급 순서 Robot, Fixture 각 담당. Design 버전과 Config / Calibration / Fixture의 Git 이력 유지(H06). 파일 형식·경로는 미정입니다.

Day 1 범위·입출력 / Day 2 Mock·실기 준비 / Day 3 부분통합 / Day 4 전체 사이클(H12). 기존 달력·5회 목표·Day 5 2PC / Isaac은 과거 운영 계획이며 최신 필수 조건에 자동 추가하지 않습니다.

## 문구 정렬·남은 확인

| 항목 | 적용 / 남은 확인 | 담당 |
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
