# 현재 진행 상황

## A파트 — C Mock·공유 fixture 재현 실행 파일 게시 (2026-10-06)

- 기존 고정 브랜치 `work/seeun-planning`에 [실행 안내](../planning_trial/README.md)와 재현용 실행 파일 4개를 추가했습니다. A 계산 코드 `planner.py`와 공통 입출력은 변경하지 않았습니다.
- `check_c_initial.py`: C 공개 Initial 성공 응답의 Design → A, `check_c_revised.py`: C 공개 Revised 성공 응답의 Design + 같은 Current → A, `check_c_fixtures.py`: C가 공유한 JSON fixture → A, `run_fake_cases.py`: 저장된 Initial 응답으로 네 가지 A 반환 사례를 실행합니다.
- 최초 Initial 기록은 C `3e18f04`, Revised·fixture 기록은 C `9de685b`였습니다. 게시 준비 checkout에서는 **네 실행 모두 `9de685b6b135d3a46968fabc9031befb02f91301`로 다시 실행**했습니다. C source checkout 경로를 인자로 받으며 README에 별도 checkout과 해당 커밋 고정 방법을 적었습니다. 특정 PC의 임시 경로를 팀 재현 지침으로 사용하지 않습니다.
- C Initial/Revised 실행에서 기존 Mock provider를 명시적으로 선택합니다. shell의 LLM 설정과 관계없이 이 재현은 외부 LLM을 호출하지 않습니다. A는 샘플/실제 연결에 같은 `plan_from_current()`를 사용하며 시뮬레이션/REAL 구현을 분리하지 않습니다.
- 게시 준비 실제 실행: Initial **READY·15 PLACE**, 부분 Current 4개를 제외한 **READY·11 PLACE**, 목표와 다른 색상 **NEEDS_CORRECTION**, 5층 입력 **INVALID**, C REVISE·Design v2 후 **READY·11 PLACE**. 각 실행 종료 코드 0과 검증 JSON의 통과 결과를 확인했습니다.
- C 공유 fixture 12개 사례 PASS: 최초 8 PLACE·부분 2개 보존 후 6 PLACE·전체 조립 0 PLACE·수정 Current 4개 보존 후 4 PLACE·목표와 다른 배치 보류·중복 점유 INVALID. `support_violation` fixture는 보존 불일치가 먼저 반환되므로 이 사례로 지지 오류 사유 반환을 증명하지 않습니다. Difference fixture는 참고·원본 해시 기록만 하며 A 계산 입력으로 사용하지 않습니다.
- `python3 -m pytest planning_trial/test_planner.py -q` → **112 passed**, 종료 코드 0. 변경 후 네 실행 파일도 모두 실제로 실행했습니다. A 소스 SHA256은 `0f96d24b8fad195185b68c9c520976b3c97d91aa179fcd91382426772f2e7835`로 이전 공유 계산 코드와 같습니다.
- 사용자 직접 실행 기록(Initial·네 가지 A 사례·Revised)과 이번 게시 준비 실행을 구분합니다. 원래 로그·산출물·첨부 압축 파일은 사용자 로컬에 보존했습니다. 소스에는 결과 생성 경로·기대값·로그 수집·압축 방법을 포함하며, 결과 JSON/로그는 실행 시 생성해 별도 공유합니다. fixture runner에 대한 사용자 직접 실행은 이번 기록에서 완료로 주장하지 않습니다.
- 이번 게시 범위는 실행 파일 4개·README·이 기록 **6개 파일**입니다. 변경량 300줄 초과는 기존에 준비한 독립 실행 4종을 팀이 재현하도록 공유하는 규모이며, 신규 계산 구현·class·dependency·추상 계층은 없습니다. 실행 파일마다 실제 입력·출력·검사·실패 경로를 표시했습니다.
- 미검증/다음 작업: D Consumer의 최신 A 출력 수용·최초/재계획 채택·화면/JSONL 반영·실제 LLM/음성·Camera/Robot/실물 조립. Current는 명시한 revision을 붙인 샘플이며 D의 실제 관측 채택이 아닙니다. 소스 게시를 공동 연결 체크박스 완료로 보고하지 않습니다. main 병합·PR 생성은 이번 작업 범위가 아닙니다.

## A파트 — Current 연결·결과 반환 형식 적용 (2026-10-06)

- 수현의 답변에 맞춰 `plan_from_current(design, current)`를 추가했습니다. Current는 `current_revision / blocks`, 반환은 `status / plan / errors`입니다. 실제 배치 채택과 결과 최신성 확인은 Backend 책임입니다.
- 기존 단일 `build_plan`을 호출하며 최초와 재계획 구현을 분리하지 않았습니다. revision을 그대로 Plan에 복사하고 이미 조립된 목표 배치는 PLACE에서 제외합니다.
- READY는 검증된 Plan·빈 errors, NEEDS_CORRECTION과 INVALID는 plan=null·사유·문제 배치이며 특정할 수 없는 배치는 block=null입니다. 처음 발견한 오류 하나를 반환합니다. 예외 문구를 분석하지 않도록 ValueError 하위 PlanningError 하나에 분기·배치 정보를 담았습니다.
- Current 누락을 빈 보드로 추측하지 않습니다. 목표에 보존되지 않은 실제 배치·삽입 방해·현재 지지 부족은 사람 정리가 필요하다고 반환하고 자동 MOVE/REMOVE는 생성하지 않습니다. malformed 입력·겹치는 Current·목표 또는 Plan 검증 실패는 INVALID입니다.
- 바로 아래층과 중복을 제외한 총 2 stud 이상 지지는 수현의 2026-10-06 회신에서 A/C 통일에 동의한 기준입니다. 공통 문서의 후보 표기 갱신은 별도입니다.
- [Current 샘플](../planning_trial/sample_current_state.json)을 합의된 바깥 구조로 바꿨습니다. revision=7과 블록 배치는 가상 시험 자료이며 실제 관측 증거가 아닙니다. [연결 예시](../planning_trial/handoff_examples.json)는 정상·부분 조립·전체 일치·사람 정리 필요·invalid 입력과 테스트 기대값입니다.
- 실제 게시 준비 checkout 검증: `python3 -m pytest planning_trial/test_planner.py -q` → **112 passed**, 종료 코드 0. 기존 최초 12 Step·재계획 9 Step의 내용과 입력 revision 유지도 확인했습니다.
- 수정 범위는 planning 파일 5개와 이 기록입니다. 신규 dependency·framework·모드 분리는 없습니다. 기존 테스트 파일 400줄 초과는 정상/invalid/경계/반환 검증의 길이이며 테스트를 약화하거나 분할용 구조를 추가하지 않았습니다.
- 미검증/다음 작업: D의 기존 reason/conflicts 수신부 조정 후 실제 C/D 함수 호출 연결, Camera·HMI·Robot·실물 조립·통합 CI. 독립 샘플 검증을 실제 모듈 통합 성공으로 표시하지 않습니다. 기존 최초 계획 CLI는 호환성을 위해 Plan만 저장하며 Backend는 새 연결 함수 반환을 사용합니다.

## A파트 — 최초 Plan·보존＋추가 Replan 공유 (2026-10-06)

- 세은의 고정 작업 브랜치 `work/seeun-planning`에서 기존 main(7dffb50) 이력을 보존하며 [계획 코드와 실행 안내](../planning_trial/README.md)를 공유합니다. main 병합·다른 파트 구현 변경은 이번 작업 범위가 아닙니다.
- 기존 로컬에서 개발·검증한 단일 계산 구현을 `planning_trial/`에 게시합니다. 최초·재계획 모두 `build_plan(design, current_blocks, current_revision)`을 사용하며 `base_current_revision`은 입력 revision을 복사합니다. 이 인자 구성은 내부 계산 API이며 실제 Backend Current 전체 구조와 실패 envelope를 확정한 것은 아닙니다.
- 규격·색상·좌표·층·방향 및 수량으로 실제 배치를 대조하고, 보존되지 않는 배치를 오류로 처리합니다. 남은 PLACE만 생성하며 자동 MOVE/REMOVE·재고 수량 검사·물리 안정성 시뮬레이션·Robot 실행을 추가하지 않았습니다.
- 현재 블록을 시작 배치로 두고 단계별 선행 관계·겹침·지지·목표 일치를 검사합니다. 위에서 수직 삽입한다는 단순 footprint 가정의 가림 검사이며 실제 손/그리퍼 경로 검증은 아닙니다. 2 stud 이상 지지는 세은이 적용하기로 선택한 기준이고 A/C 공통 계약 반영은 확인 중입니다.
- 게시 전 실제 독립 검증: `python3 -m pytest planning_trial/test_planner.py -q` → **89 passed**, 종료 코드 0. 저장된 최초 Plan 12 Step과 보존 3개＋남은 Plan 9 Step을 공통 validator로 재검사했습니다.
- [Current 샘플](../planning_trial/sample_current_state.json)은 가상 자료입니다. 바깥 필드는 Backend 확정 Schema가 아니고, [재계획 예시](../planning_trial/sample_replan.json)의 revision=7도 시험용 값입니다. 의자 사진을 복원한 GT·실제 관측·실물 검증 결과로 사용하지 않습니다.
- 규모 설명: 기존 작성 자료 8개(계산 코드 268줄, 테스트 437줄, README 1개, JSON 샘플 5개)를 같은 경로로 공유하고 이 진행 기록을 추가합니다. 테스트와 JSON의 길이는 독립 검증·재현용입니다. 신규 class·dependency·framework·계산 모드 분리는 없습니다. 공통 app 패키지로의 이동·API 확정은 연결 시 별도 확인합니다.
- 미검증/다음 작업: C/D 실제 모듈·Current 구조·최종 status/plan/errors·진행 중 부품 처리·HMI·Robot·실물 조립·통합 CI는 미검증입니다. 수현의 실제 Current 및 실패 반환 규약과 생산자/소비자 예시로 연결 검증해야 합니다. 새 lint/type-check/CI 도구는 도입하지 않았습니다.

## 최신 작업 — Day4 결정 계약과 팀원 준수 사항 (2026-10-05)

- 사용자 요청으로 현재 대화의 결정을 공통 docs에 반영. PLACE·좌표 / 각도·before / after·관측 check·verified_regions·가림 이력·최소 ID / 버전·HRI·Replan·슬롯·STOP 3방향 재개·Qt·JSONL을 정리했습니다.
- 채택 Design의 전체 미리보기를 Qt 한 화면에 포함하고 기존 여섯 snapshot 묶음에 전체 Design 표시 데이터를 추가하도록 명시했습니다. 홍동의 observe point / 전달판 판별은 수정 가능한 제안으로 분리했습니다.
- 기존 C 필드 / 의도명 차이를 이행 표로 남겼습니다. C production skeleton·기존 진행률·실제 장치 설정·reference 원본은 변경하지 않았습니다.
- GitHub 최신 main(4b4f193) 기준 별도 docs/day4-confirmed-interfaces 브랜치에서 문서 10개만 변경합니다. 다른 로컬 브랜치의 미커밋 문서·final_docs·발표 자료는 포함하지 않습니다.
- 현재 계약은 문서상 결정입니다. 공통 실행 Schema·callback / Action / Qt 연결·실제 Robot 정지 / 재개·Camera 인식·전체 Day4 시연은 이번 작업에서 구현하거나 검증하지 않았습니다. 별도 자료 폴더의 과거 독립 시험을 이 저장소의 시험 통과로 표시하지 않습니다.
- 실제 문서 정적 검증: 변경 Markdown 10개, 상대 링크 25개 존재, JSON 예시 5개 파싱, 정상 3 Step 예시의 footprint / 범위 / 지지 / 선행 관계·Design / Plan 연결 확인, 문서만 변경한 범위·git diff --check 통과. README의 존재하지 않는 AGENT.md 안내 링크 제거. 로컬 상세 결과: /tmp/day4_docs_validation.json.
- 실행 앱·Camera·Robot 시험은 수행하지 않았습니다. 다음 작업은 담당별 Fixture와 공통 형식 이행·Mock 연결이며 실제 장치 시험은 별도로 기록합니다.

아래는 이전 작업 당시 기록입니다. 오래된 웹 HMI·미정 좌표 / 식별·원격 게시 전 설명은 현재 결정으로 적용하지 않습니다.


## 최신 작업 — AI 개입 범위와 검증 보고 규칙 (2026-10-05)

- 사용자 제공 노마드 코더 영상의 설명·영어 자동 생성 자막을 확인하고 AGENTS.md에 간결한 답변, 가정 확인, 최소 수정, 기존 자동 검사 활용, 검증 증거 후 완료 보고를 반영.
- 질문/검토와 파일 변경 요청을 구분하고 요청 밖 정리·리팩터링·추상계층·dependency 추가, 실패 은폐, 테스트 약화, 사용자 변경의 혼입을 제한. 승인된 범위는 반복 확인 없이 끝까지 진행.
- 맥락에 필요한 문서만 읽도록 안내를 조정. 기존 역할·목표·구현 경계 보존. 별도 자료 폴더의 최신 계약 결정을 이 저장소의 공통 계약으로 임의 승격하지 않음.
- 별도 로컬 `협동2_프로젝트` 자료 폴더에도 AGENTS.md를 작성해 해당 작업 위치의 새 대화에 지침을 제공. 이미 열린 다른 대화의 자동 재로딩은 미검증.
- 실제 확인: 자료 폴더 53줄/9,168 bytes, 저장소 72줄/10,747 bytes. 상대 링크 4개 존재·외부 출처 링크 3개 표기, 코드 블록·후행 공백·기존 구현 경계 보존 확인 통과. 외부 출처는 영상·공식 문서 조회로 확인. 로컬 상세 결과: `/tmp/c2_agents_validation.json`.
- 실행 코드·Schema·Robot 설정 변경 없음. 앱 테스트·장치 시험·새 lint/CI 설치 없음. 문서 확인을 시스템 통과로 보고하지 않음. 다음 작업은 이번 변경만 담은 새 PR 생성과 사람 리뷰.

아래는 이전 작업 당시 기록이며 현재 원격 상태·구현 완료 여부의 신규 확인 결과가 아닙니다.

갱신: 2026-10-04. **최신 결정 반영·협업 문서·로컬 PR 준비 단계입니다. 앱 구현·장치 시험은 미완료입니다.**

| 항목 | 상태 | 다음 작업 |
|---|---|---|
| 역할·Day 4 범위 | 역할 사용자 재확인·최신 TBD 범위 반영 | 담당별 계약·Fixture 확인 |
| 환경 | Python 3.12.3 로컬 확인, Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060 / Jazzy / M0609 / D435i / RG2 사용자 확인 | 실제 OS·Docker·GPU driver·ROS·펌웨어·장치 확인 |
| Design / Plan / Observed | Owner·의미 정리, 정확한 Schema 미정 | 생산자·소비자가 정상 / invalid 예시 확인 |
| Current / Expected·완료 | Backend Owner·전달 / 조립 완료 분리 | 정상 대기 / 실제 차이·최신성 규칙 합의 |
| HMI / 저장 | 웹 HMI API·파일 로그 방향 | framework·API·파일 형식 확인 |
| 공급·Robot | 종류 / 색상별 1~6 순서·고정 전달 | 보충 신호·실패 시 번호·STOP / 취소 시험 |
| 좌표·GT | 과거 기록·원본 pose 보존 | 공통 grid·layer·방향·판별 범위·실측 확인 |
| 일정 | H12의 Day 1~4 개발 단계 | 실제 날짜·가용 시간·시험 횟수 합의 |
| Day 4 / 최종 버전 | 공통 코드 + 검증 태그 운영 제안 | 팀 합의·시연 검증 후 태그 생성 |
| Git / PR | 빈 원격 확인·최소 기반과 문서 변경 준비 | 사용자 변경 검토 후 게시·Draft PR |
| 실행 코드·테스트·CI | 이 저장소에 없음 | 계약 합의 후 작은 기능별 구현·검증 |
| C Design (시율) | `app/c_design/` docstring skeleton·문서, 진행률 0% — [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md) | C Contract |
| Isaac Sim | 후속 검토 후보 | Day 4 결과·목적·PC 사양 확인 |

## 이번 문서 작업

- README·현재 결정·역할·일정·측정·Sim·Git·에이전트 안내·PR 템플릿을 최신 결정으로 정렬.
- `06_CONTRACT_DRAFT.md`와 팀원 작업 Issue 템플릿 추가. 필드·정책 초안은 확정된 계약과 구분.
- `docs/reference/` 8개 원본과 기존 pose 배열 보존. 사진·Depth·실행 코드 추가 없음.
- 기존 파일 대비 10개 수정·2개 추가. 문서 간 과거 역할·일정의 충돌을 함께 수정하기 위한 범위이며 runtime 구조·dependency 변경 없음.
- 로컬 기반 브랜치 `bootstrap/pr-base`, 변경 브랜치 `docs/latest-decisions-collaboration`로 최초 PR 비교를 준비. 원격 게시·PR 생성·태그 생성은 후속 단계.

## 사용자 검토 반영

2026-10-04: Ubuntu 24.04 / Docker 29.8.2 / NVIDIA 4060과 역할 분담 확인을 반영했습니다. 실제 문서 폴더와 향후 코드 구조 제안을 Git 가이드에서 구분합니다. 앱 폴더·공통 Schema·Docker 실행 구성은 아직 생성·확정하지 않았습니다.

## 실제 확인과 미검증

- `python3 --version`: Python 3.12.3.
- 원격 조회: GitHub size=0·브랜치 없음, 로컬 커밋 없음 확인 후 기반 준비.
- 문서 정적 확인 통과: 현재 Markdown 13개·상대 링크 16개·표 15개·코드 블록 7개. 참고 원본 8개 해시 일치·pose 기록 일치. 외부 링크의 접근성과 앱 동작은 이 검사 범위 밖.
- Git 공백 검사: 현재 문서 통과. 전체 최초 추가에는 참고 원본 2개 파일의 기존 후행 공백 17줄이 경고로 남으며 원본 보존을 위해 수정하지 않음.
- 미검증: 앱·Schema·pytest / CI·D435i 인식·ROS Action·Robot 전달 / STOP / 취소·HMI·전체 시연. 문서 검토를 시스템 성공으로 표시하지 않음.

## 다음 구현 전에 확인할 사항

1. 시율·세은·홍동·수현: 동일 Design / 상태의 필드·기하·grid·layer·방향·정상 / invalid Fixture.
2. 세은·수현: Step 목표 / 효과·제거 / 재배치·Robot 전달 필요 여부.
3. 홍동·수현: 관측 품질·가림·정상 조립 대기 / 차이·callback / Topic 관계.
4. 시율·수현: 모델·구조화 출력·질문 / STT·비정상 응답·식별 / 버전.
5. 수현: 공급 보충 / 실패 처리·실제 driver·고정 좌표·STOP / 재개·HMI API / 로그.

내부 문서·PR 준비는 진행할 수 있습니다. 공유 필드·물리 판별·실측 값은 담당자 확인이 필요하며 이번 작업에서 임의 확정하지 않습니다.

## 작업·trial 기록 양식

작업: 날짜 / 담당 / 작은 목표 / 변경 파일 / 입력·출력 계약 / 실행한 검증 / 실제 결과 / 미검증 / blocker / 다음 작업.

trial 항목 제안: trial_id, scenario_id, mode, 입력 관측·촬영 시각, Design / Plan / Calibration 버전, 비교 Step·Difference, 질문·응답, 채택 결과, Robot 실행·전달 결과, 검증 범위·성공 / 실패 사유·소요 시간·증거 파일. 정확한 영문 필드명은 계약 확인 후 정하며 실패 trial도 기록합니다.
