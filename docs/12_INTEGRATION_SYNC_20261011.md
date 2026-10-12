# 최종 MVP integration 문서 동기화 — 2026-10-11

> **2026-10-12 최신 문서 기준:** [최종 대화 반영·원격/로컬 상태](16_FINAL_INTEGRATION_CHAT_SYNC_20261012.md)와 [발표·배포 문서 10종](final_mvp/README.md)을 우선합니다. B가 Expected/전체 판 비교/Current·revision, D가 실행·지정 검사·진행/HMI/제스처/기존 이력·웹을 맡습니다. A 3분류 호출과 후보 실행권 분리는 유지합니다. 로컬 D 수정·계획 실패 KEEP 보류와 원격 미반영 상태를 구분하며 아래 본문은 이전 시점 기록으로 보존합니다.

2026-10-12 갱신: 아래 10/11 기록 이후 PR #24가 integration `8914320`에 병합됐습니다. ms-02 현재 시험 코드의 후속 업데이트 범위·검증 상태는 [10/12 안내](13_RUNTIME_UPDATE_20261012.md)를 우선하세요.

비교 기준: 원격 `codex/integration-round1`, **`02137d80ef28bab678e49855d7b6150219028881`**, 2026-10-11 15:01:57 +09:00. [고정 커밋](https://github.com/suuuhululu/C-2/commit/02137d80ef28bab678e49855d7b6150219028881). 이 문서는 해당 소스의 정적 확인 결과다. 로컬 `work/suhyun-hmi-backend-robot-db`가 이 커밋으로 병합·갱신됐다는 뜻이 아니다.

10/8 [확정 인터페이스](handover/final_mvp_interface_20261008/README.md)의 책임·Expected 고정·승인·취소·실행 경계를 유지한다. 아래 지원 범위와 구현 상태는 최신 integration 기준이며, 과거 Day4 계약·시험 수치·원본을 소급 수정하지 않는다. 최종 결정·버전 관리·배포는 **수현**이 담당한다. 이번 변경은 문서만이며 코드·런타임 Schema·DB 구조·Robot 설정·장치 실행·commit/push/GitHub 게시를 포함하지 않는다.

## 1. 책임과 전체 흐름

| 담당 | 확정 책임 | 현재 연결에서 구분할 점 |
|---|---|---|
| C 시율 | 설계 대화·수정 중 설계·대화 승인·실제 차이 의도 확인 | 후보 생성, 사용자 승인, D의 실행 목표 채택은 서로 다른 단계 |
| A 세은 | 계획·작업·도움·경로 계산과 A 어댑터, 동일 자료 B·D 공유 | 후보 계산 구현 존재. D 연결과 B·D 실제 배포 완료는 별도 |
| B 홍동 | Expected·관측 가능한 판 전체 비교·Current 확정·revision 관리 | B 확정 상태 중계 소비 구현과 실제 B 검사 생산자를 구분 |
| D 수현 | Step·Robot·지정 검사·대응/중복/취소·진행/C 호출·HMI·제스처·JSONL→DB/웹 | 목표 역할에는 공간 비교·Current 재확정이 없음. legacy D 비교 경로는 아직 남음 |

```text
사용자↔C → 수정 중 후보 표시 → C 대화 검토·승인 → A
                                                   ├─ 동일 계획/기준/형상 → B
                                                   └─ 동일 자료/작업/도움 → D
D 조건 확인 → A 직전 재평가·경로 후보 → D 자동 승인·실행
→ 공급판 집기·조립판 직접 결착/필요한 사람 도움 → D 지정 B 검사
→ B 전체 관측 영역 비교·Current/revision 확정 → D 판정별 진행/보류/C 호출
→ 모든 필요한 Step 확인 → B FINAL·D 종료 → D JSONL→DB→사용자별 웹
```

위 흐름은 최종 목표다. 현재 FAKE/legacy 전달판 경로 및 REAL 진입 화면 연결을 직접 결착·전체 서비스 통합 성공으로 표시하지 않는다. 수정 중 후보는 실행 승인 설계를 덮어쓰지 않으며 HMI 설계 승인/매 Step 승인 버튼을 추가하지 않는다.

## 2. 최신 소프트웨어 지원 범위

| 항목 | integration 기준 | 장치·기하 제한 |
|---|---|---|
| 블록 | `2x2x1`, `2x3x1`은 yellow/blue; `1x2x1`은 red만 | 다른 종류/색 조합은 유효 입력 아님 |
| Design | `{design_version, blocks}`, 실행 후보 1~40블록 | 빈 HMI 표시 fixture는 실행 후보가 아님. 41개는 거절 |
| 배치 | 기존 여섯 필드, 24×24 stud, x/y 정수 0~23, layer 정수 1~5 | 회전 footprint 전체 판 내부·중첩/지지 검사 필요. 6층은 거절 |
| 방향 | 4점 0°; 6점 0°=X2/Y3·90°=X3/Y2; 2점 0°=X1/Y2·90°=X2/Y1 | stud 배치는 TCP pose가 아님 |
| 공급 | FAKE 다섯 열(빨강 2점 포함)·열별 6슬롯과 보충 경계 | REAL 기존 측정 네 열/기존 실행 범위 유지. 빨강 pose·파지·결착 실기 미검증 |

근거: [D 입력 검사](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/app/contracts.py), [A planner](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/planning_trial/planner.py), [공통 Schema](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/interfaces/schemas/day4.schema.json). 40블록 소프트웨어 수신/계획과 REAL 수동 시험의 24 Step·공급 슬롯 한계는 서로 다른 기준이다. 과거 4층/30블록 fixture는 당시 기록으로 보존한다.

## 3. 핵심 3계약과 실제 반영 상태

| 계약 | 확정 입력·출력/시점·실패 | 구현 확인 / 남은 연결 |
|---|---|---|
| A→B·D | 승인 Design·Plan·고정 `plan_base_current`·좌표/형상. 생성·재계획 때 동일 자료 제공; 오류/한쪽 전달 실패는 실행 보류 | A 공유 bundle 생성은 존재. 기존 D는 `plan_from_current`를 직접 호출하므로 실제 두 소비자 배포와 새 후보 실행 연결은 남음 |
| D→B | INITIAL은 계획 기준 확보, STEP은 지정 Plan/Step 작업 뒤, FINAL은 전체 확인. 기존 check_id·대상 연결; 재검사는 새 ID | 실제 INITIAL/STEP/FINAL 요청 생산·B 수신·취소 확정 연결은 미완료. B가 Step 추정/진행하지 않음 |
| B→D | 확정 Current/revision·판정·해당 Expected·missing/unexpected/unobservable·관측 근거. 대응 검사 후 D 진행 | B Current/revision 보존 중계 소비는 존재. 전체 결과 생산·D 기존 비교 제거·snapshot/CHECK_RESULT 연결은 남음 |

Expected는 Plan 시작 때 고정한 Current와 해당 Step까지의 목표 효과로 계산한다. 불일치 실제 Current로 기존 Plan Expected를 바꾸지 않는다. 새 Plan만 B 최신 확정 Current를 새 기준으로 삼는다. B는 현재 목표뿐 아니라 관측 가능한 판 전체의 위치·색·층·기존 구조 변경을 판단한다. 가려진 아래층은 이전 이력이며 이번 검출이나 숨은 변경 확인으로 표시하지 않는다.

### B 상태 중계의 구현 경계

1. [Python Observed 수신부](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/app/contracts.py#L120)는 기존 Observed에 `current`와 `current_provenance="B_CONFIRMED_D_RELAYED"`를 함께 받는 확장을 지원한다.
2. [Current 처리](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/app/current.py#L121)는 B 블록/revision을 병합하거나 +1 하지 않는다. revision 퇴행·같은 revision의 다른 배치·관측 불가에서 revision 변경은 거절한다. 확장이 없는 legacy 입력은 여전히 D 병합/+1 경로다.
3. [Backend](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/app/backend.py#L393)는 중계 입력에도 [기존 D Expected/비교 함수](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/app/completion.py#L93)를 호출한다. 따라서 중계 구현을 B 전체 검사 책임 이관 완료로 보고하지 않는다.
4. JSON Schema의 Observed는 `additionalProperties=false`이며 중계 두 필드가 없다. **Python 확장과 JSON Schema의 적용 계약이 불일치**한다. 배포 예시는 목표 계약 설명용이고 해당 런타임 Schema 적합성 증거가 아니다. 이번에 실행 Schema를 수정하지 않았다.

카메라 UNOBSERVABLE은 보류·재검사이며 입력 오류·계획 누락·처리 실패와 구분한다. STOP/재계획에서는 D의 옛 결과 차단뿐 아니라 B의 확정/취소 순서화가 필요하다. 취소 뒤 옛 계산이 Current/revision을 갱신하지 못하는 생산자 경계는 **미연결·경쟁 시험 전**이다. 먼저 확정된 사실을 롤백하지 않고 취소 경계 확인 뒤 새 검사로 최신 기준을 확보한다.

## 4. C 후보·승인과 의도 연결

integration에는 `create_initial_design → 후보 표시 → preview_ready → review_design_candidate → APPROVE → A` 연결이 있다. MODIFY는 새 후보 재표시·재검토, UNCLEAR는 보류/명시 답변 대기, CANCEL/실패는 실행 없음이다. 생성과 검토 request_id를 구분하고 Job/revision·STOP·늦은 결과를 검사한다. REAL 진입 화면의 `preview_ready` 연결도 존재하지만 시험의 RealController stub은 실제 로봇이 아니다.

최초 후보는 v1, Revised 후보는 기존 승인 version+1, 동일 후보군 MODIFY는 같은 version을 사용한다. `design_metadata`는 Design/여섯 배치 필드와 분리한다. 검토의 APPROVE/MODIFY/UNCLEAR/CANCEL과 의도의 KEEP/REVISE/UNCLEAR를 혼용하지 않는다.

목표 D→C 입력은 **B Current/revision·단계 Expected·기존 Design·차이/관측 한계**다. 현재 Backend 질문 payload에는 Expected가 없고 C API도 별도 Expected 인자를 받지 않는다. 기존 differences 변환을 우선하며 전체 문맥의 호출 매핑은 남은 과제로 표시한다. C나 D가 B Expected를 다시 계산하는 해결책은 추가하지 않는다.

현재 Stage3 REVISE는 수정 Design 후보를 반환한다. 목표 계약은 수정 의도 먼저 접수하고 이후 수정/대화 승인할 수 있지만 **Design 없는 지연 REVISE 경로가 구현됐다고 보지 않는다**. KEEP도 실제 상태가 계획을 만족하지 않으면 다음 Step 진행 허가가 아니다. 실제 음성·LLM·Camera·Robot을 함께 사용한 최신 통합 시험은 이번 문서 작업에서 수행하지 않았다.

## 5. A 후보 API·Robot·SIM

- A API는 `assembly-ad-calculation-draft/0.5.1`, 공통 자료는 `a-b-d-planning-bundle-draft/0.1.1`이다. bundle은 `DRAFT_NOT_FROZEN`, `execution_allowed=false`이며 Design/Plan/고정 Current/profile/geometry/Expected 자료를 담는다. 구형 0.5 요청은 거절된다. [A 안내](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/planning_trial/README.md).
- 전체 계획·직전 재평가·`plan_step_motion` 후보 구현은 있다. D의 조건 확인·자동 승인·예약·실제 도달/정지/파지·Contact 인계·도움 준비/해제와 연결된 직접 결착 실행은 별도 과제다. A 후보 수신만으로 실행하지 않으며 매번 사용자 승인도 받지 않는다.
- A의 현행 profile/digest는 A 초안 필드다. 이를 모든 메시지의 새 hash/version/generation 또는 B의 robot lease 필수 계약으로 확대하지 않는다.
- 공급 파지는 패드 하단=블록 밑면+5mm. 기존 보정 중복 적용 금지. 새 pose/TCP/속도/힘/보정값을 만들지 않는다. 좌표 정합·실물 파지·결착은 확인 필요다.
- integration에 Isaac 자산·스크립트·MoveIt 기반 검토 자료가 존재한다. [Isaac README](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/isaac_sim/README.txt)의 0.5 설명은 현재 A 0.5.1과 맞지 않는다. 구형 요청/원본 fixture를 보존하고 호환성을 확인해야 한다. 최신 정리 트리의 SIM 재생과 실물 접촉·중력·정지 검증은 완료로 표시하지 않는다.

## 6. HMI·DB·웹과 저장 경계

HMI에는 설계/도움/검사/종료 요청 소비·표시 기능이 있다. 필드 없는 legacy snapshot과 새 UI 요청 수신부 연결은 구분한다. 실제 B 검사 결과와 D snapshot/JSONL 생산은 아직 모두 연결되지 않았다.

integration의 `history/migrations/001_personal_history.sql`, `history/personal.py`, `history/final_mvp.py`에는 Job 소유자와 개인 조회/저장·B 검사 기록 소비가 있다. 따라서 독립 DB를 “계정표만 있고 소유자/개인 저장 미구현”으로 설명하지 않는다. 실제 D의 CHECK_RESULT 생산·로그인 사용자→Job owner 연결·종료 저장/웹 반영은 별도 과제다. B 전용 DB·새 저장 경로는 추가하지 않는다.

원격 integration에는 로컬 `history/web.py`·`history/web_assets`가 포함되지 않았다. 로컬 STATUS/DB 안내의 웹 구현·시험 기록을 보존하되 원격 통합 상태와 합산하지 않는다. 조립 종료·DB 저장·웹 반영은 각각 확인하며 저장 실패로 Robot을 재실행하지 않는다.

## 7. 담당별 다음 단위기능 순서

| 담당 | 개발 순서 | 정상·실패 확인 |
|---|---|---|
| 수현 인터페이스 | 기존 Python 확장/Schema/목표 결과의 매핑 정리 → 배포 기준 관리 | 계약 충돌과 Producer/Consumer 적용 버전 확인 |
| A | 구현된 bundle → B·D 동일 배포 → D 직전 평가/경로 연결 | INVALID_CONTEXT·한쪽 실패·기준 revision 충돌·실행권 없음 |
| B | Plan 수신 → 지정 검사 → 전체 판 비교·확정 → 취소 경계 | 위치/색/층·기존 구조 변경·가림 이력·취소 전후 경쟁 |
| C·D | 현재 Preview/Review 유지 → B Expected/차이 문맥 연결 → 필요 시 지연 REVISE 연결 | 수정/취소/옛 승인·KEEP 불일치·REVISE 재승인 |
| D 실행·HMI | B 결과로 D 비교 대체 → snapshot/CHECK_RESULT → UI 요청 수신 → 실행 경계 | 정상 자동 진행·관측 불가 보류·중복/옛 결과·STOP |
| D DB·웹 | 기존 JSONL 결과 생산 → Job owner 연결 → 개인 저장/웹 통합 | 두 사용자 격리·실패/중복·저장 상태·Robot 재실행 없음 |
| A·D/전원 | 후보/SIM 버전 정렬 → 실제 인접 모듈 연결 → 제한된 장치 시험 | 단위/Fixture/DB/SIM/REAL 증거를 분리 |

## 8. 예시와 검증 상태

[문서용 EXAMPLES.json](handover/final_mvp_interface_20261008/EXAMPLES.json)의 18개 시나리오는 목표 계약을 설명한다. 작은 yellow/blue 두 블록을 썼다는 이유로 최신 red/5층/40블록 범위를 배제하지 않는다. 실제 Producer 반환이나 실행 Schema 입력 fixture로 사용하지 않는다.

| 상황 | 기대 계약 | 구현·시험 판독 |
|---|---|---|
| 정상 | B MATCH·Current/revision·Expected → D 한 번 완료·자동 다음 조건 확인 | legacy 정상 회귀와 최종 B 경로 시험 구분 |
| 불일치 | 판 전체 확인된 차이 반영·Expected 고정 → C 의도 확인 | KEEP 즉시 진행 금지. D Expected 전체 전달은 남음 |
| 관측 불가 | Current 유지·unobservable·보류·새 check_id | 입력/계획/처리 오류를 관측 불가로 바꾸지 않음 |
| 옛/취소 결과 | D 진행 차단·B 취소 뒤 확정 차단 | D 소비자 차단만으로 B 취소 검증 완료 아님 |
| 설계 변경 | 수정 후보 표시·대화 승인 → A 새 Plan/B 최신 Current 기준 | Stage3 후보 승인 연결과 지연 의도-only REVISE를 구분 |

현재 커밋에는 PR #22 관련 D 변경과 A Wave1·D Wave2 변경이 들어 있다. 과거 문서의 Draft/미병합 표현은 해당 작성 시점의 기록이다. 이 소스 확인은 GitHub의 현재 PR 리뷰·CI·main 병합 상태를 조회한 결과가 아니다.

[이전 C/A/D 검증 보고서](https://github.com/suuuhululu/C-2/blob/02137d80ef28bab678e49855d7b6150219028881/reports/c_stage3_ad_alignment_20261011/validation.md)의 관련 504 passed 및 전체 2243 passed/31 failed/11 errors/34 skipped는 당시 트리 결과다. 이후 Wave2 시험 파일이 추가됐다. 해당 수치를 현재 SHA 재실행 결과나 전체 PASS로 옮기지 않는다. [HMI·DB 검토](D_HMI_DB_ROUND1.md)의 독립 PostgreSQL 기록도 실제 B/Robot/음성 전체 통합 증거가 아니다.

이번 문서 검증은 링크·표·코드 블록·문서 예시·변경 범위 확인만 수행한다. 앱 테스트·DB 접속·Isaac 실행·Camera/Robot 통합 시험은 수행하지 않는다. 실제 B 생산자, B 취소 확정, D 비교 이관, A 후보 실행 연결, Expected 의도 문맥, owner/웹 및 실기 좌표/파지/접촉은 남은 확인 사항이다.

## 9. 이번 문서 검증

2026-10-11 로컬 문서 검사 대상은 Markdown 37개와 문서용 EXAMPLES.json 1개다. 링크·표·코드 블록·JSON 및 18개 시나리오의 요청/결과 대응·고정 Expected·revision 변화/유지·가림 이력 분리를 검사했다. 신규 오류와 요청 밖 변경은 없었다. 최종 검사에서 Markdown 링크 527개·표 168개·코드 블록 84개(JSON 표기 24개)를 확인했다. 문서 앵커 27개와 고정 GitHub 파일 링크 28개는 로컬 파일/가져온 Git 객체로 존재를 확인했다. `git diff --check` 종료 코드 0이다. GitHub 링크 확인은 HTTP 상태/CI 조회가 아니다.

기존 문제 8건은 변경 전에도 존재했다. STATUS의 과거 /tmp 화면/로그 링크 7개는 파일이 없어 재열람할 수 없고, D_C_FUNCTION_INTEGRATION의 과거 json 표기 블록 1개는 여러 독립 JSON 값을 이어 놓아 단일 JSON으로 파싱되지 않는다. 과거 원자료/시험 기록이므로 이번에 임의 수정하지 않았다. 외부 일반 웹 링크의 HTTP 상태와 Mermaid 그림 렌더링은 미검증이다.

2135개 기존 파일의 내용 해시를 변경 전후 대조해 문서 수정 31개 외 2104개가 동일함을 확인했다. 실행 코드·런타임 Schema·DB 구조·Robot 설정·원본 예시·원 ZIP은 보존했다. 지정 브랜치 유지·commit/push/게시 없음. 문서 검증은 앱/Camera/Robot/SIM/DB 시험이 아니다.

배포용으로 자료 폴더의 [10/11 문서 ZIP](</home/ms-02/C-2_협동2자료/contract_records/final_mvp_interface_20261011.zip>)을 별도 생성한다. 기존 10/8 ZIP을 덮어쓰지 않는다. 새 ZIP은 갱신 README·원본 EXAMPLES.json·이 동기화 문서를 포함하며 실행 가능한 배포물이 아니다. ZIP의 3파일 목록·CRC·원문 바이트 및 내부 문서 링크/앵커를 검사했다. 원 EXAMPLES.json 바이트와 10/8 ZIP은 그대로다.

### 수정 파일 범위

| 위치/묶음 | 파일 |
|---|---|
| 개발 저장소 진입점 | README.md, AGENTS.md, final_docs/README.md, planning_trial/README.md |
| 책임/기존 계약 | docs/00_CURRENT_DECISIONS.md, 02_TEAM_GUIDE.md, 06_CONTRACT_DRAFT.md, 09_C_B_BACKEND_HANDOFF.md |
| C·A 인계 | docs/D_A_PLANNER_HANDOFF.md, D_C_FUNCTION_INTEGRATION.md, C_DESIGN_CONTRACT.md, C_DESIGN_PROGRESS.md, C_DESIGN_STRUCTURE.md |
| HMI/DB/SIM/진행 | docs/D_HMI_MVP_FINAL.md, D_DB_HISTORY.md, 04_ISAAC_SIM.md, STATUS.md |
| 배포 계약 | docs/handover/final_mvp_interface_20261008/README.md. EXAMPLES.json은 변경 없음 |
| 로컬에 없던 integration 안내 5개 | docs/10_FINAL_MVP.md, 11_ROUND1_INTERFACE_AUDIT.md, C_DESIGN_STAGE3_D_HANDOFF.md, D_C_STAGE3_AD_ALIGNMENT.md, D_HMI_DB_ROUND1.md |
| 신규 상태 색인 | docs/12_INTEGRATION_SYNC_20261011.md (이 문서) |
| 자료 폴더 | AGENTS.md, contract_records/인터페이스 결정 타임라인.md, 최종_MVP_발표문서/README.md와 01~10 주제 문서 |
| 신규 배포물 | contract_records/final_mvp_interface_20261011.zip |

기존 Markdown 31개를 갱신하고 Markdown 6개와 문서 ZIP 1개를 추가했다. 자료 폴더의 보관 work/원본/과거 ZIP과 개발 저장소의 미완료 코드 변경을 대체하거나 삭제하지 않았다.
