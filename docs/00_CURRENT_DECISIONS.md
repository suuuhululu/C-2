# 최신 결정과 남은 확인

갱신: 2026-10-04. [Notion TBD 결정 목록](https://app.notion.com/p/TBD-3efffcadfd2680ea9119c1fdf22e566a)의 작성 내용을 최신 합의로 적용합니다. 기존 2026-10-03 역할·일정 및 페이지 앞부분의 이전 기준보다 우선합니다. 아래 ID는 Notion 표의 근거입니다.

## 환경과 자료 상태

| 항목 | 확인 |
|---|---|
| Python | 사용자 제공·로컬 확인: 3.12.3 |
| ROS2 / Robot | 사용자 제공: Jazzy / Doosan M0609, 실제 실행 미검증 |
| Camera / Gripper | 사용자 재확인: RealSense D435i / OnRobot RG2 |
| OS / Docker / GPU | 2026-10-04 사용자 재확인: Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060. 실제 설치·GPU driver / VRAM·호환성 미검증 |
| 코드 | 레포는 문서만 있음. 앱·adapter·Schema·테스트·CI 미구현 |
| 문서 | 레포 내 Markdown, 원본 참고자료 보존 |

## 책임과 전달 경계

아래 역할 분담은 2026-10-04 사용자가 재확인했습니다.

| 객체 / 기능 | Owner | 의미 |
|---|---|---|
| Initial / Revised Design | 시율 | 키워드 최초 생성·변경 의도 반영 |
| Assembly Plan / Step | 세은 | 사람 조립 순서·검증·Remaining·Replan |
| Observed | 홍동 | 촬영 당시 블록 종류·색상·위치·층·방향·시각·신뢰·오류 |
| Current | 수현 Backend | 유효 Observed를 채택한 실제 상태·채택 관측 식별 |
| Expected | 수현 Backend 단일 Owner | 현재 비교 Step까지 조립돼 있어야 할 목표 배치 |
| Difference·채택·System State | 수현 Backend | 목표 / 실제 비교·진행·보류·버전 관리 |
| Robot Result·source·슬롯 | 수현 Robot Controller | 필요한 종류·색상으로 source 선택·집기·전달 |
| HRI | 시율 의미·음성, 수현 HMI·연결 | 질문·현재 응답 연결·유지 / 수정 / 불명확 |
| 통합 | 수현·각 담당 지원 | 모듈별 adapter·Fixture·진단 제공 |

Initial 경로는 시율 → 세은 → Design과 검증된 Plan을 Backend(H01·F08). 모든 데이터 전달이 Backend를 반드시 경유한다는 과거 규칙은 적용하지 않습니다.

## Day 4 범위

- 키워드 기반 최초 Design 생성 포함(F08·G01). Chair는 첫 예시·Fixture이며 임의 LEGO 전체의 창작을 요구하지 않습니다.
- 4점·6점 × 노랑·파랑, 최대 4층, 24×24점 plate(A03). 정확한 기하·허용 방향·축·layer 표현은 확인 필요입니다.
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
- 불명확은 재질문, 사용자 응답 대기·횟수 제한 없음(F04). Robot / 통신 timeout과 구분합니다.
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
|---|---|---|
| A01 전달 | 반복된 D03·D05·E01·E02에 따라 Robot 전달로 정렬. 원문 문구 확인 | 수현·전원 |
| A02 완료 | D07·E02·G01의 전달 / 조립 분리·전체 배치 확인 적용 | 수현·홍동·세은 |
| C01 실패 미처리 | C02·C03·H10에 따라 실패 감지·보류 지원, 자동 복구 제외 | 홍동·수현 |
| B01·D02 공급 | 보충 주체·신호·pick 실패 후 번호 갱신 | 수현 |
| B01·B02·B07 | 공통 필드·기하·ID·필수값·Schema·Fixture | 연결 담당 전원 |
| B04·B05 | 좌표·시간·최신성. 과거 GT 규약 자동 채택 금지 | 홍동·세은·수현·시율 |
| C01·C05·H07 | 판별 항목·confidence·안정 관측·4층 가림·정상 대기 / 차이 | 홍동·수현·세은 |
| A05·D02·D05 | 제거 / 재배치·Step 목표·효과·전달 필요 여부 | 세은·수현 |
| F05 | 모델·구조화 출력·비정상 / 실패 / 미지원 처리 | 시율·수현 |
| G02·G04 | 버전·관측·질문·실행 식별·늦은 결과 | 수현·각 담당 |
| H02·H03 | Vision callback / Topic 관계·API / Action 이름 | 연결 담당 |
| E03~E07 | 보정·TCP·pose·motion·STOP / 재개 실제 시험 | 수현·홍동 |

새 필드·정책은 [계약 초안](06_CONTRACT_DRAFT.md)에 제안으로 표시합니다. 과거 포트·모델·좌표를 임의 확정하지 않습니다.
