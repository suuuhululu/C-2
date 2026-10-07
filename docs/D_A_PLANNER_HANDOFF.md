# D → A Planner 연결 — 2026-10-06

> 2026-10-07 적용: 현재 제품 목표는 [최종 MVP](10_FINAL_MVP.md)입니다. 아래는 기존 A PLACE 순서/Remaining/Replan과 D 연결 기록입니다. 최종 요구의 경로 생성·조립판 직접 결착은 이 Plan 출력만으로 구현되지 않습니다. 경로 생산자·인계·유효성 계약은 별도 합의 대상입니다. 기존 원본 코드·시험 수치는 보존합니다.

2026-10-07 공통 5층 지원: A의 층 상한과 오류 문구만 갱신하고 계산 순서·지지·재계획 의미는 유지했습니다. 아래 원본 커밋·해시는 당시 자료의 기록입니다. 현재 시험은 승인된 두 변경을 제외한 원본 해시 일치와 1~5층·30블록·6층 거절을 확인합니다([STATUS](STATUS.md)).

세은의 `a_manual_execution.tar.gz` 로그·입출력·검증 기록을 확인하고, 원격 `work/seeun-planning`의 **f9b841c8f090b0b25c30ab27459781ad2017fd9e**에서 planning_trial 폴더를 가져왔다. Planner 소스 SHA-256은 첨부 기록의 `0f96d24b8fad195185b68c9c520976b3c97d91aa179fcd91382426772f2e7835`와 일치한다. A 코드는 수정하지 않았다. 수현 브랜치 `work/suhyun-hmi-backend-robot-db`와 기존 미커밋 변경을 보존했다. 이 기록 작성 당시에는 게시하지 않았으며, 이번 PR에서 A–D 연결을 게시한다. main 병합은 수행하지 않는다.

## 구현과 범위

| 연결 | 구현·검증 | 한계 |
|---|---|---|
| C Initial → A | C의 status=OK 응답에서 design을 받아 D 요청에 저장하고 실제 plan_from_current 호출 | C 응답은 첨부 Mock JSON. 실제 C 함수·LLM·음성 호출 아님 |
| D → A Replan | 채택 Design 또는 C Revised와 최신 Current 전체 객체 전달 | Current는 관측 Fixture 또는 이미 채택한 상태 Fixture |
| C Revised → D → A | C hri_result=REVISE를 기존 on_intent에 연결하고 버전 2·Current 보존·11 PLACE 채택 | 실제 run_intervention 실행 아님 |
| 사람 정리 | NEEDS_CORRECTION 보류·안내 → 명령 → 새 관측 → revision 변경 확인 → 실제 A 재계산 | 물리 정리·Camera 판별은 Fake |
| HMI/로그 | 실제 A 오류·문제 배치·범위 밖 값 보존, Qt 안내 표시, PLAN_RESULT에 전체 envelope 기록 | Qt offscreen 검증 |
| 전달·조립 | 실제 A Plan으로 FakeRobot 전달 후 관측 확인까지 수행 | 실제 Robot·경로·정지 검증 아님 |

[연결부](../app/planning_connection.py), [A 원본 코드](../planning_trial/planner.py), [첨부 기반 Fixture](../interfaces/fixtures/a_backend_cases.json), [통합 검사](../tests/integration/test_a_backend.py)를 사용한다. 기존 [FakeDemo](../app/fake_demo.py)는 3-Step 고정 Fixture 시험용으로 유지하며 새 실제 A 경로로 자동 전환하지 않았다.

## 호출 방법

기존 emit의 planner 요청 중 design이 있는 요청을 아래 함수로 전달한다.

```python
from app.planning_connection import run_planning_request

# port == "planner"이고 payload에 design이 있을 때
run_planning_request(backend, payload)
```

START의 첫 planner 요청에는 아직 design이 없다. 이 요청 식별을 C Initial 호출 문맥에 보관하고, 성공 응답을 받았을 때 다음 수신 함수로 연결한다. sample Design을 자동으로 대신 넣지 않는다.

```python
backend.on_initial_design(original_request_id, c_response)
```

이 함수는 같은 request_id에 Design을 고정하고 최신 Current 전체 객체와 함께 planner 요청을 보낸다. 최초 버전은 1이다. 실패·취소·비정상 C 응답은 다음 전달을 보류하며 성공 Design으로 바꾸지 않는다. 취소 이후 Workflow 정리와 실제 C의 모든 비성공 반환 의미는 별도 실제 연결 검증 대상이다.

C의 실제 run_intervention을 연결할 때에는 같은 호출 문맥의 Current에서 목록을 꺼내 전달한다.

```python
from app.planning_connection import current_blocks_for_c, on_c_intervention

blocks_for_c = current_blocks_for_c(hri_payload)
# C에는 blocks_for_c, A에는 hri_payload["current"] 전체 객체를 사용한다.
# C 함수의 다른 인자와 Difference 변환은 C 실제 계약을 확인해 연결한다.
on_c_intervention(backend, original_question_request_id, c_response)
```

C의 성공 KEEP/REVISE/UNCLEAR를 기존 D 의도 경로로 연결한다. questions와 원래 응답은 C_INTERVENTION_RESULT 로그에 보존한다. 실제 C 함수 호출·질문 표시 시점·음성 입출력·취소 정리는 아직 연결하지 않았다. 최신 질문·Current revision·목표 버전 검사는 기존 D가 유지한다.

## 반환 계약

| status | plan / errors | D 처리 |
|---|---|---|
| READY | 검증된 Plan / [] | 활성 요청·Design 버전·Current revision 확인 후 채택. 새 전달판 EMPTY 전 전달 금지 |
| NEEDS_CORRECTION | null / reason·block 목록 | Current 유지, 사람 정리 안내, 다음 전달 보류 |
| INVALID | null / reason·block 목록 | 채택 Design·Current 유지, 진단 표시·기록, 자동 재시도 없음 |

오류 block은 object 또는 null이며 범위 밖 좌표·5층 등 잘못된 값도 원본대로 남긴다. 정상 실행 Plan 검사는 별도로 수행한다. A가 새 request_id를 발급하지 않고 연결부가 원래 호출 식별을 돌려준다. READY의 base_current_revision을 결과 수신 시점 값으로 덮어쓰지 않는다.

## 최초 Plan 없는 사람 정리 관측

이전의 INITIAL_CURRENT_OBSERVATION_NOT_CONNECTED 제한을 해소했다. 첫 NEEDS_CORRECTION 뒤 정리 확인 관측은 D 내부 check 문맥의 plan_id와 step_id를 모두 null로 보관한다. Job/check 식별과 순번 검사는 유지하며 가짜 Plan·Step을 생성하지 않는다. Vision 요청·Observed의 외부 필드에는 변화가 없다.

이 문맥은 Current를 채택할 수 있지만 조립 Step을 완료시키는 증거로 사용하지 못한다. 사람 정리 버튼만으로 Current·revision·완료를 바꾸지 않고 실제 관측 변화 뒤 다시 A를 호출한다. 한쪽 ID만 null인 문맥은 거부한다. startup의 실제 빈 보드 촬영 자동 연결은 이번 시험 범위가 아니다.

## 재실행

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/integration/test_a_backend.py -q
python3 -m pytest planning_trial/test_planner.py -q
QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q
```

첫 명령은 실제 A와 첨부 C Mock 응답을 D·FakeRobot·Qt·JSONL에 연결하는 검사다. 실제 Camera/Robot을 움직이지 않는다. A 독립 검사는 112개이며 전체 결과는 STATUS에 기록한다. 새 dependency·lint/type 도구를 설치하지 않았다.

## 실행 결과와 남은 작업

- 첨부의 빈 Current → READY 15 Step, 부분 Current → READY 11 Step, 색상 차이 → NEEDS_CORRECTION, 5층 → INVALID를 실제 A로 재현했다.
- 실제 D 관측 Fixture로 네 Step을 확인한 Current는 revision=4다. 이 기준으로 재계획하면 11 Step이며 base_current_revision=4다. 첨부의 묶음 Current revision=1을 임의로 바꾸지 않고 별도 사례로 구분한다.
- 네 Step 확인 뒤 이동된 실제 배치를 관측하고 C Mock Revised v2를 수신하면 Current를 기준으로 11 Step을 채택했다. 남은 Step도 FakeRobot·관측으로 COMPLETE까지 확인했다.
- 전체 최초 15 Step도 별도로 COMPLETE를 확인했다. Robot 성공만으로 confirmed_steps/Current를 변경하지 않았다.
- Revised 경로에서 이전 전달과 합쳐 공급 슬롯 6개를 넘으면 기존 보충 대기를 유지한다. 시험에서 모의 운영자의 SUPPLY_REFILLED와 새 EMPTY를 입력한 뒤 이어갔다. Replan으로 슬롯을 초기화하지 않았다.
- 실제 A 결과의 버전/revision 불일치·중복·STOP 후 늦은 C 응답은 채택하지 않았다. 불일치·관측 불가 시 다음 FakeRobot 집기도 시작하지 않았다.
- 실행 증거: [결과 JSON](../logs/a-backend-connection-guy8gbim/results.json). 같은 폴더의 시나리오별 Job JSONL을 참조한다. logs는 로컬 실행 산출물로 Git에서 제외되어 원격 clone에는 없다.

실제 C 함수·음성, B callback·촬영, 실제 Robot driver/pose/STOP·재개 연결은 남아 있다. 현재 데스크톱 FakeDemo 실행만으로 실제 A/C/Vision/Robot 연결이 수행됐다고 보지 않는다.

최종 전체 검사: **707 passed**, 종료 코드 0. A 독립 검사 112개·새 A/D 통합 검사 24개 포함. 이 기록은 이전 550개 Fixture 준비 단계 검사와 구분한다.


PR 게시 대상과 최신 main을 합친 독립 파일 트리에서 `QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q` 실행: **884 passed**, 종료 코드 0. main의 C 검사도 포함하며, 별도 REAL 장치 시험·수동 입력 HMI 검사는 이번 게시 범위에서 제외한다. 실제 Camera/Robot 시험은 수행하지 않았다.

## 사용자가 제공한 C 저장 응답으로 A–D·Qt 시험 (2026-10-06)

Downloads의 `c_design_initial_result.json`과 `c_design_revised_result.json`을 원본 바이트 그대로 [Initial Fixture](../interfaces/fixtures/c_design_initial_result.json), [Revised Fixture](../interfaces/fixtures/c_design_revised_result.json)에 보관했다. C가 산출한 저장 응답이며 C 실행 코드·생성 커밋은 제공되지 않았다. 이번 시험에서 C 함수/LLM/음성은 호출하지 않았다.

| 파일 | SHA-256 | Design |
|---|---|---|
| Initial | `5213f1d01b5bdc3abfeed1c330e3dc975ceb3bc45465fdac5d50f90c8334432b` | v1, 15블록 |
| Revised | `5c60d6d514ec08852f02f4713c1b4ba2491b0254a33ab64205efe6bcefd6588f` | v2, 19블록 |

Revised는 (9,9) 2층의 노랑 6점/90°를 파랑으로 바꾸고 노랑 4점 네 개를 추가한다. 모든 불일치에 적용할 범용 응답은 아니다. 저장된 질문도 그대로 표시·기록하며 실제 의도 해석 결과를 새로 생성하지 않는다.

연결은 `Backend.on_initial_design` → `run_planning_request` → 실제 A `plan_from_current(design,current)` → D 채택이다. Revised는 활성 질문에서 `on_c_intervention` → 실제 A 재계획 → D의 Design/Plan 동시 채택을 사용한다. A는 위 고정 커밋 원본, D는 HEAD `7af9daeb3812f9e87fb36f172293434fd827e42f` 기반 미커밋 구현이다. B PR #10 `c75c80374b848a395fded62ad901020d06b92913`의 원본 `deliver_example`을 거치지만 관측 내용은 D 시험용 합성 프레임이다. 이번 입력은 모든 기존 배치와 현재 입력 배치가 판별 가능하다고 가정한 사례이며 가림 성능 증거가 아니다. 전달판 입력은 기존 `on_place`로 직접 전달하며 B 생산 callback으로 표시하지 않는다. RobotController/FakeRobotDriver, 실제 snapshot/Qt/JSONL을 연결했다.

| 사례 | 결과 |
|---|---|
| Initial + 빈 Current | 실제 A READY 15 Step. Fake 전달 뒤 조립 확인 대기, 관측 후에만 Step 확인. 최종 Current 15개/revision 15, 15/15 COMPLETE |
| 부분 Current 0/4/8개 | 실제 A Remaining 15/11/7. 이미 조립한 목표 배치는 Plan에서 제외 |
| S09 색상 불일치 | 앞선 8 Step 유지, 파랑 실제 배치를 Current에 채택해 9개/revision 9. 기존 목표는 노랑 유지, WAIT_INTENT·8/15·추가 전달 없음 |
| 저장 Revised + 위 Current | 실제 A READY 10 Step. Current/revision 9 보존, Design v2와 새 Plan 채택, 진행 0/10. 새 EMPTY와 관측으로 끝까지 확인 후 Current 19개/revision 19·10/10 COMPLETE |
| 위 실제 배치의 x=7 | Revised가 그 Current를 보존하지 못하므로 실제 A NEEDS_CORRECTION. WAIT_CORRECTION·Design v1 유지·Current 9개 보존·추가 집기 없음 |
| 조기/중복 Revised·STOP 후 늦은 C 응답 | 채택/진행하지 않음 |
| 지원 밖 색상·Boolean 좌표 | 입력 거절, Current/관측 순번 변화 없음 |

Revised를 빈 Current로 A에 넣는 독립 계산은 READY 19 Step이지만 D의 최초 응답으로 v2를 채택하는 시험은 아니다. 재계획 진행 수치는 현재 Plan의 10 Step이며 전체 Design의 19블록 달성률과 구분한다. 위 재계획 사례는 총 19회 Fake 전달·18회 STEP_CONFIRMED다. 불일치 전달 한 번은 이전 Plan의 Step 완료로 기록되지 않는다.

### HMI 실행과 단계 입력

실제 Robot/ROS 연결 없이 다음을 실행한다. 창을 연 뒤 **시작**을 누르면 Initial Design 전체 그림·S01·0/15가 표시된다. 별도 Design/Plan JSON 입력은 필요 없다. 시작 전에는 미채택으로 표시한다.

```bash
cd /home/ms-02/C_2
env -u QT_QPA_PLATFORM python3 -m app.abd_input_hmi --synthetic-b \
  --initial-result interfaces/fixtures/c_design_initial_result.json \
  --revised-result interfaces/fixtures/c_design_revised_result.json
```

같은 터미널에서 출력되는 다음 입력을 한 줄씩 사용한다. 정상 시험에서는 다음 두 입력을 각 Step마다 반복한다. `place_empty` 뒤 Fake 복귀와 다음 관측 안내를 기다린다. 마지막 전달만으로 완료되지 않는다.

```json
{"event":"place_empty"}
```

```json
{"event":"observe"}
```

Revised 시험은 **앞선 8개 Step을 정상 확인한 뒤 S09**에서 수행한다. S09 목표가 **노랑 6점 (9,9), 2층, 90°**인지 HMI로 확인하고 `place_empty`/복귀 뒤 정상 observe 대신 다음 한 줄을 입력한다. 기존 조립을 보존한 채 이번 블록만 파랑으로 놓은 합성 관측이다.

```json
{"event":"observe","actual":{"brick_type":"2x3x1","color":"blue","x":9,"y":9,"layer":2,"orientation_deg":90}}
```

의도 확인 대기에서 아래 입력으로 제공된 Revised 응답을 적용한다. 자동 REVISE/KEEP은 없다. Current를 임의로 변경해 Revised와 맞추지 않는다.

```json
{"event":"revise"}
```

이후 새 Plan의 10개 Step도 `place_empty` → Fake 복귀 → `observe`로 진행한다. 다른 실제 배치나 다른 실행 시점에서는 같은 저장 Revised가 NEEDS_CORRECTION으로 보류될 수 있다. 실제 카메라/로봇 시험 명령으로 사용하지 않는다.

### 이번 검증과 산출물

[새 검사](../tests/integration/test_c_saved_results_hmi.py) **13개**, 관련 **182 passed**, 전체 **805 passed**, 각각 종료 코드 0. 기존 화면 실행부의 입력 옵션만 확장하고 공통 계약·Backend 핵심·A/B 원본·장치 설정은 변경하지 않았다. 새 class/dependency/framework/DB 없음. 변경량 검토 신호는 원본 JSON 두 파일의 보관과 정상 15 Step/재계획 10 Step/보류/지연 응답의 외부 결과 검증에 따른 것이며 새 시스템을 생성하지 않았다.

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/integration/test_c_saved_results_hmi.py -q
QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q
```

[산출물 색인](../logs/c-saved-results-final/summary.json)에 소스 해시·검사 수·사례별 snapshot/JSONL/화면 PNG 위치를 기록했다. native Qt는 파일 로드·창 열기·EOF 종료만 확인했으며 START 이후 상태·그림은 offscreen Qt 검사와 PNG로 확인했다. logs는 Git 제외다. lint/type check는 미구성이다.

남은 연결: 최신 Current/Difference에서 실제 C Revised를 생성하는 함수·응답, B의 실제 관측/전달판 생산 callback·촬영/가림 판별, 실제 Robot 전달/STOP·재개 및 모듈 간 실패/지연 시험. 저장 C 결과·합성 callback·Fake 통과를 실제 Camera/Robot 통합이나 인식 성능 통과로 표시하지 않는다. GitHub 게시/PR/merge/장치 실행 없음.
