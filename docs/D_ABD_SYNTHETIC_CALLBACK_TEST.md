# A–B–D 합성 JSON callback 통합 검사 (2026-10-06)

**실제 A 계산 + B PR의 합성 JSON 전달 함수 + 현재 D + Fake Robot**을 연결했다.
실제 Camera 인식·인식 성능·Robot/Camera 장치 통합 성공이 아니다. C는 Mock 응답이다.
공통 계약·application 코드·A/B 원본·장치 설정을 수정하지 않았다.

## 기준과 PR 차이

| 구성 | 이번 실행 기준 |
|---|---|
| A | `f9b841c8f090b0b25c30ab27459781ad2017fd9e`, planning_trial/planner.py 원본. SHA-256 `0f96d24b8fad195185b68c9c520976b3c97d91aa179fcd91382426772f2e7835` |
| B | [PR #10](https://github.com/suuuhululu/C-2/pull/10), `c75c80374b848a395fded62ad901020d06b92913`. 변경 파일 18개를 원래 경로에 수정 없이 가져옴 |
| D 비교 기준 | [PR #9](https://github.com/suuuhululu/C-2/pull/9) head `a825e2d6b7440a4ab77fb5c02540484e04dd3acc`, merge `101d9d85efe8bdf7cf82bef2a199f4919e1e6c84` |
| 실제 D 실행 | 로컬 HEAD `7af9daeb3812f9e87fb36f172293434fd827e42f` + 기존 미커밋 소스. 브랜치 `work/suhyun-hmi-backend-robot-db` 유지. PR #9를 이 checkout에 병합한 상태로 표시하지 않음 |

PR #9와 A 원본·planning_connection·Current·completion·replan은 바이트가 같다.
로컬 Backend에는 이후 REAL manual_trial 분기가, snapshot에는 REAL 수동 신고 표시가
추가되어 있다. 이번 검사는 명시적 FAKE mode이며 그 변경을 덮어쓰지 않았다.
정확한 D 소스 해시는 실행 산출물 summary.json에 기록했다.

B는 JSON 저장 형식과 callback 예시만 제공한다. 제공 코드에는 ROS/HTTP 전송,
카메라 촬영·추적·인식·다중 View 융합이나 실제 전달판 판별이 없다.
B README/안내의 `perception_mvp/` 명령 경로는 이번 PR의 저장 경로와 다르므로
아래의 실제 저장 경로로 실행했다. B 문서 원본은 수정하지 않았다.

## 실제 호출과 시험용 연결

1. D START → `Backend.on_initial_design()`에 Mock C 성공 Design 응답.
2. `run_planning_request(..., planner=actual_a)` → 실제
   `planning_trial.planner.plan_from_current(design, current)`.
   actual_a는 입력·반환 기록만 남기며 저장된 Plan을 반환하지 않는다.
3. A의 `status / plan / errors` → `Backend.on_plan_result()`.
   READY는 채택, NEEDS_CORRECTION/INVALID는 보류한다.
4. `RobotController` + `FakeRobotDriver.confirm(pick/place/observe)`.
   성공 후에도 Current·확인 Step 수가 그대로이며 WAIT_ASSEMBLY다.
5. B 저장 observed/diagnostics JSON을 읽고 **묶음 시작 시** D 발급 check_id와
   순번을 연결한다. 지연된 묶음은 도착 시 ID/순번을 다시 붙이지 않는다.
6. **B 원본 `deliver_example(case, callback)`을 실제 호출**한다. 그 함수가 JSON
   직렬화 확인·deepcopy 후 전달한 Observed를 callback에서 `D.on_observation()`에 넣는다.
   Expected·추적·View·quality·시각·진단은 Observed 여섯 필드에 들어가지 않는다.
7. 별도 전달판 진단은 **테스트 함수 deliver 안의 임시 최소 변환**으로
   `delivery_board.state/reason`과 같은 check/seq를 기존 `D.on_place()`에 전달한다.
   **B가 제공한 별도 진단 전달 함수를 통과한 검사는 아니다.** B에는 그 함수가 없다.
   이 위치/전체 diagnostics를 공통 필수 계약이나 production 통신 구현으로 채택하지 않았다.
8. `make_snapshot()` → 기존 `HmiWindow.snapshot_received`로 Qt offscreen 표시.
   `JsonlLog`에 실제 D의 PLAN_RESULT/PLAN_ADOPTED/CURRENT_ADOPTED/STEP_CONFIRMED/
   PLACE_STATUS_CHANGED/관측 보류/의도 요청/최종 완료 기록을 확인한다.
9. 부분 Current는 `begin_replan()`으로, Mock Revised는 `on_c_intervention()`으로
   같은 실제 A를 다시 호출한다. 실제 C 함수·LLM·음성 호출은 없다.

B 원본 자체 14개 검사는 JSON/코드 일치와 로컬 callback 성질을 검사한다.
신규 A–B–D 16개 검사는 위 전달 함수를 통해 D의 외부 결과를 검사한다.
전달판 전용 after=null 요청은 조립 Observed를 임의로 만들지 않고 별도 on_place 변환만
검사한다. 추가 위치를 포함한 3-Step 정상 공정의 두 번째 프레임은 D 작성 합성값이며,
그 프레임도 B의 실제 deliver_example을 거친다. B 인식 출력으로 주장하지 않는다.

## 사례별 입력과 결과

기본 목표는 노랑 4점 (4,6) 1층 0°이며 다음 목표는 파랑 (10,6) 1층이다.
가림 두 사례는 Current에 노랑 (4,6) 1층이 있고 목표는 파랑 (4,6) 2층이다.
실제 A의 층 우선 순서를 따라 이 두 사례의 다음 목표는 같은 위치 3층으로 준비했다.

| 사례 | 실제 시험 결과 |
|---|---|
| 정상 일치 | B 노랑 1층을 채택, revision 0→1, Step 1/2. 처음 전달 전 EMPTY는 재사용하지 않음. 새 EMPTY 없으면 Fake 호출 3개에서 유지 |
| 불일치 | B 파랑 1층을 실제 Current로 채택, revision 0→1. 노랑 Expected 고정, MISMATCH·WAIT_INTENT·0/2·다음 전달 없음 |
| 확인된 빈 영역 | (4,6)의 2×2·1층만 verified, visible 없음. 목표 미배치 MISMATCH·WAIT_INTENT·0/2, 원래 빈 Current revision 0 유지 |
| 빈 영역 범위 보충 | 이미 채택된 세 블록의 Current 재확인에서 같은 영역의 1층만 제거. 같은 위치 2층과 (16,6) 1층 유지, revision 3→4, Robot 호출 없음. 조립 Step 확인 사례와 구분 |
| 이번 목표 가림/Depth 부족 | B UNOBSERVABLE. 노랑 아래층 Current/revision 1 유지, 파랑 2층 완료 보류·0/2, 다음 전달 없음 |
| 아래층만 가림 | B 파랑 2층만 보이고 2층 영역만 verified. 노랑 1층 유지, revision 1→2, MATCH·1/2. 새 전달판 비움 전 추가 집기 없음 |
| 전달판 UNOBSERVABLE | 조립판은 OK/MATCH·1/2. 조립 비교를 실패로 바꾸지 않음. 전달판 사유는 JSONL에 기록. 이후 새 after=null check의 UNOBSERVABLE은 snapshot/Qt에 사유를 표시하고 다음 집기 보류 |
| 부분 Current 재계획 | B 확인 노랑 블록이 있는 revision 1로 실제 A 재호출. 이미 조립된 목표 제외, Remaining 1 Step, Current 보존·새 EMPTY 대기 |
| Mock Revised 재계획 | 불일치로 채택된 파랑 블록을 보존한 Design v2와 revision 1 Current로 실제 A 호출. READY·Remaining 1 Step 채택, 실제 배치 보존·추가 집기 없음 |
| 닫힌/중복/역순 Observed | A/1→B/0→늦은 A/0→B/1→중복 B/1→역순 B/0. 새 check B의 0 허용, 늦은/중복/역순 거절, Step/Current/Fake 호출 변화 없음 |
| 전달판 순번 | 같은 check의 OCCUPIED/1 후 EMPTY/0·중복 EMPTY/1 거절. 새 EMPTY/2만 첫 pick 허용, 실행 중 옛 check/3 거절 |
| A 비성공 | 실제 배치가 Design과 다른 경우 NEEDS_CORRECTION, 5층 Design은 INVALID. 원래 errors 보존, Plan 미채택·Robot 호출 없음 |
| 정상 3 Step·최종 확인 | 실제 A 순서는 노랑 (4,6) 1층 → 파랑 (10,6) 1층 → 파랑 (4,6) 2층. 마지막 Robot 성공 직후 2/3·WAIT_ASSEMBLY, 마지막 B callback 확인 후에만 3/3·COMPLETE·revision 3·JOB_COMPLETED 1회 |

MATCH 뒤 다음 check를 열면 snapshot의 현재 Step/비교는 다음 목표의 WAITING으로
바뀐다. 완료된 이전 Step의 관측 증거는 JSONL 및 검사 assertion에서 확인한다.
미수신 전달판은 null로 남는다. 현재 assembly check의 **새 묶음**에서 EMPTY와
조립 일치를 함께 받으면 기존 gate가 다음 전달을 허용하는 것도 별도로 검사했다.

## 실행 명령·실제 결과

모든 명령은 장치를 움직이지 않는 Python/pytest 합성 검사다. ROS 환경 source는 필요 없다.

```bash
cd /home/ms-02/C_2
python3 tests/integration/perception_backend_callback_examples/callback_examples.py
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/integration/test_abd_callback.py \
  tests/integration/perception_backend_callback_examples/tests/test_callback_examples.py \
  tests/integration/test_a_backend.py planning_trial/test_planner.py \
  -q --basetemp=logs/abd-callback-rerun --junitxml=logs/abd-callback-rerun-results.xml
QT_QPA_PLATFORM=offscreen python3 -m pytest tests planning_trial/test_planner.py -q
```

- B CLI: 합성 JSON 7묶음(기본 5 + 아래층 가림 + 순번 자료) 출력, 종료 코드 0.
- 집중 검사 **166 passed**, 종료 코드 0: 신규 A–B–D 16 + B 원본 14 + 기존 A–D 24 + A 독립 112.
- 최종 전체 **775 passed**, 종료 코드 0. 현재 로컬의 기존 REAL 수동 시험 Mock 검사도 포함하며 실제 Robot을 실행하지 않는다.
- 첫 시도 2 failed/27 passed는 시험 준비 오류였다. 실제 A의 층 정렬에 맞춰
  가림 사례의 현재 목표를 고정했고 Fake 호출 tuple 접근을 수정했다. assertion을
  삭제/완화하지 않았으며 수정 후 집중/전체를 재실행했다.
- lint/type 설정은 미구성. 새 dependency/framework/DB/class 없음.
  새 통합 검사 약 360줄은 정책의 테스트 코드 예외 범위이며 application 계층을 늘리지 않았다.

## 결과 파일과 변경 범위

이번 실행 산출물은 Git 제외 logs에 있다. 원격 clone에는 포함되지 않는다.

- [실행 근거·소스 해시·사례 색인](../logs/abd-callback-final/summary.json)
- [집중 검사 JUnit](../logs/abd-callback-final-results.xml), [전체 검사 JUnit](../logs/abd-callback-full-results.xml)
- [B 원본 CLI 출력](../logs/abd-callback-final/b-example-output.txt)
- [불일치 결과](../logs/abd-callback-final/test_b_stored_json_via_actual_1/result.json), [불일치 HMI](../logs/abd-callback-final/test_b_stored_json_via_actual_1/hmi.png)
- [전달판 독립 보류 결과](../logs/abd-callback-final/test_new_empty_proof_required_0/result.json), [전달판 HMI](../logs/abd-callback-final/test_new_empty_proof_required_0/place-unobservable-hmi.png)
- 각 사례 디렉토리의 result.json: 실제 A 입력·envelope, callback 입력·채택 bool,
  D 요청, Current·고정 Plan 기준·Expected·snapshot·Fake 호출의 시점별 기록.
  같은 디렉토리의 Job UUID.jsonl: 실제 D 이벤트.

이번 작성분은 [통합 검사](../tests/integration/test_abd_callback.py), 이 문서,
[STATUS](STATUS.md) 세 파일이다. 별도로 B 원본 18개를 원래 경로로 가져왔다.
기존 application·Schema·Fixture·A·Robot 설정과 그 밖의 미완료 변경은 그대로 보존했다.
브랜치 전환·commit/push·새 PR·main 병합·실제 장치 실행은 수행하지 않았다.

## 실제 연결 전 blocker

1. **B production callback/진단 전달**: 실제 생산 모듈의 반환 함수와 D 연결부,
   전달판 최소 envelope/수신 경로를 B와 맞춰야 한다. 현재 검증은 로컬 callback까지만이다.
2. **Camera**: 실제 RGB/Depth·단위·보정/pose 대응·안정 프레임·손 이탈·가림과
   verified_regions 생성·묶음 중 상태 변화·실제 촬영 시작 순번을 장치에서 검증해야 한다.
3. **Robot/촬영 시점**: Controller 실제 정지·검증된 observe 복귀·촬영 가능 신호,
   STOP/재개와 지연 촬영의 check 종료를 인접 통합 및 별도 장치 시험으로 확인해야 한다.
   이번 Fake 성공을 이 근거로 사용하지 않는다.
4. **C**: 실제 Initial/Intervention 함수·취소·실패·LLM·음성 연결은 Mock 이후 별도 시험이다.

이 결과는 B 합성 생산자 callback과 실제 A/D의 소프트웨어 소비 의미를 검증한 것이다.
실제 인식 성능, 물리 안정성, Camera/Robot 통합, 전체 사람 조립 시연 통과는 미검증이다.

## 후속 production callback 연결 착수 확인 (2026-10-06)

사용자가 집중 검사 166개 통과를 재현한 뒤 다음 연결 단계 진행을 요청했다.
GitHub PR 목록과 PR #10의 고정 head 전체 파일 트리를 다시 조회했다.
head는 `c75c80374b848a395fded62ad901020d06b92913` 그대로이며,
해당 트리에 있는 B 코드는 위 합성 예시 18개다. 실제 Camera 관측 생산 함수,
callback 등록/호출 구현, 별도 전달판 수신 경로는 제공되지 않았다.
새로운 production 연결 성공으로 보고할 실행 대상이 아직 없다.
사용자도 추가 구현은 아직 없고 현재 커밋이 제공 코드 전부라고 확인했다.

후속 연결에서 사용할 D 경계는 이미 구현되어 있다.

| 연결 지점 | 기존 구현과 다음 확인 |
|---|---|
| D → B | 기존 emit의 vision 요청: D 발급 check_id와 after. after=null은 전달판 확인이며 조립 목표를 임의로 대신 채우지 않음 |
| B → D 조립 관측 | Backend.on_observation(observed). 여섯 필드 계약 유지, B가 묶음 시작 때 보관한 원래 check/seq 반환 |
| B → D 전달판 | Backend.on_place(check_id, observation_seq, status, reason). B의 실제 반환 위치/함수 확인 후 최소 변환; proposed_diagnostics 전체 wrapper는 아직 공통 계약으로 채택하지 않음 |
| 실패·지연 | 실제 B 함수의 예외/호출 실패·닫힌 check·중복/역순·STOP 중 묶음을 기존 D 보류/무시 의미로 연결하고 검사 |
| 장치 실행 | 실제 callback 소프트웨어 연결과 촬영·정지·보정 장치 시험을 분리. 이번 착수 확인에서 장치를 호출하지 않음 |

필요한 제공물은 **실제 B 구현이 있는 PR/커밋 또는 로컬 파일 경로**다.
그 위치에서 촬영 요청을 받는 함수와 Observed/전달판 결과를 전달하는 호출 지점을
확인한 후 기존 합성 시험과 같은 의미로 정상·실패·지연을 검사한다.
B 인식/추적 코드를 D가 대신 구현하거나 ROS/HTTP 경로를 임의로 추가하지 않는다.

이번 착수 확인은 원격 코드 유무 조회와 이 문서/STATUS 갱신만 수행했다.
새 코드·새 테스트·pytest 실행·실제 카메라/Robot 실행·Git 게시/병합은 없다.
앞 절의 166/775 결과는 직전 합성 시험 기록이며 이번 production 연결 통과 수치가 아니다.

## 합성 입력을 넣으며 Qt 화면 확인하기 (2026-10-06)

사용자가 요청한 화면 시험용 [진입점](../app/abd_input_hmi.py)을 추가했다.
기존 Qt·D·Controller/Fake driver와 실제 A 계산을 사용하고, B 원본 callback을
거친 합성 관측을 터미널에서 한 번씩 넣는다. 기존 FakeDemo의 저장 Plan 주입 경로와
구분한다. C 응답은 Mock이며 B production/Camera/실제 Robot 연결은 아니다.

### 실행과 정상 3-Step 확인

일반 터미널에서 다음 명령을 실행한다. ROS setup은 필요 없다.
`QT_QPA_PLATFORM=offscreen`을 붙이면 창이 보이지 않으므로 화면 시험에서는 제외한다.

```bash
cd /home/ms-02/C_2
env -u QT_QPA_PLATFORM python3 -m app.abd_input_hmi --synthetic-b --scenario normal
```

1. HMI **시작** 클릭: 실제 A가 계산한 3-Step Plan·전체 Design·현재 목표·0/3 표시.
   창을 연 것만으로는 Design/Plan 채택·Job 생성·Fake 전달이 시작되지 않는다.
2. 같은 터미널에 아래 첫 줄을 넣는다. Fake pick→place→observe 복귀를 기다린다.
   기본 지연은 동작마다 350ms다. 터미널에 **다음 합성 관측 입력**이 나온 뒤 두 번째 줄을 넣는다.
3. 다음 Step에서도 같은 순서를 반복한다. 총 세 번이며 JSON을 한꺼번에 붙여넣지 않는다.

```json
{"event":"place_empty"}
{"event":"observe"}
```

place_empty는 이번 새 전달판 check에 대한 합성 EMPTY다. observe는 현재 assembly
check의 새 묶음을 만들어 B deliver_example으로 전달한다. 두 event는 별개의 입력이다.
직접 check_id/confirmed를 붙이지 않는다. ID/순번은 합성 묶음 시작에 고정되며 check마다 0부터다.
Robot 복귀 전·시작 전·STOP 중·해당 check가 없는 단계의 입력은 보류된다.
실제 촬영 순번 생성 코드를 구현했다는 뜻은 아니다.

전체 목표는 노랑 (4,6) 1층 → 파랑 (10,6) 1층 → 파랑 (4,6) 2층이다.
첫/마지막은 B 저장 합성 JSON, 추가 위치의 두 번째 프레임은 D가 만든 합성값이며
JSONL의 source로 구분한다. 두 번째도 B 실제 deliver_example을 거친다.
마지막 Fake 전달 성공 직후 **2/3·사람 조립 관측 대기**, 마지막 observe 후에만 **3/3·전체 조립 완료**다.
완료를 위해 Qt가 Current/Expected/슬롯을 계산하지 않는다.

### 독립 사례 선택

창을 닫고 위 실행 명령의 `--scenario normal` 부분을 다음 값으로 바꿔 실행한다.
각 창에서 시작 → place_empty → 복귀 안내 대기 → observe 순서로 확인한다.

| scenario | 화면/진행 확인 |
|---|---|
| mismatch | 목표 노랑/합성 관측 파랑 비교, 0/2·의도 확인 대기. 실제 Current는 파랑, 다음 전달 없음 |
| verified-empty | 목표 영역을 확인했지만 블록 없음, 0/2·실제 차이·의도 확인 대기 |
| occluded | 아래층 Current를 사전 Fixture로 준비. 이번 2층 목표 관측 불가, 0/2·보류. observe를 반복해도 Current 유지 |
| lower-occluded | 아래층 Current는 유지하고 읽힌 파랑 2층을 채택, 1/2. 다음 전달은 새 EMPTY 대기 |
| place-unobservable | 조립 일치 후 1/2. 새 전달판 check에 아래 입력을 넣으면 판단 불가·사유·다음 전달 보류 표시 |

```json
{"event":"place_unobservable"}
```

place_unobservable은 after=null인 새 전달판 확인 단계에서 넣는다. 이후 새 place_empty를
입력하면 다음 Fake 전달을 허용하는지 확인할 수 있다. B의 별도 진단 전송 함수가 아니라
기존 on_place를 호출하는 합성 시험 입력이다. B 저장 조립 사례의 전달판 진단도
기존 검사와 같은 최소 변환으로 소비하며 공통 diagnostics 계약을 확정하지 않는다.

가림 두 사례의 전체 Design은 같은 위치 1·2·3층이며, 1층은 이미 채택된 **사전 Current
Fixture**(revision 1)다. A가 남은 두 Step만 계획하므로 진행은 0/2에서 시작한다.
이 사전 상태는 SYNTHETIC_CURRENT_SEEDED 이벤트로 기록하며 실제 Camera 검증으로 표현하지 않는다.

Fake 정지/재개는 HMI 버튼으로 확인한다. 모의 정지·이전 실행 종료·블록 상태 응답 후에
재개가 활성화된다. 재개 뒤 새 check로 관측하며 옛 check 결과를 완료에 사용하지 않는다.
실제 Robot STOP/재개 검증과 구분한다. 불일치 후 C 의도 해석·정리/수정은 이 화면 시험 범위 밖이다.
창 닫기 또는 Ctrl+D로 종료한다. 입력 오류/보류는 터미널과 footer에 표시한다.

### 기록·검증 범위

Job별 주요 이벤트는 `logs/abd_hmi/<job_id>.jsonl`, 최신 화면/Current는
`logs/abd_hmi/<job_id>.snapshot.json`에 저장한다. snapshot은 시험 산출물이며 종료 후 복원용이 아니다.
`--log-dir <경로>`로 저장 위치, `--delay-ms <밀리초>`로 Fake 동작 지연을 바꿀 수 있다.

신규 [화면 입력 검사](../tests/integration/test_abd_input_hmi.py) 17개:
실제 Qt 시작·3-Step/B callback·확인 전 완료 방지·각 독립 사례·새 EMPTY·입력 오류/부적절한 단계·
Fake STOP/재개·원래 check의 늦은 B 결과·실제 CLI/입력 thread/EOF 종료를 확인했다.
관련 검사 **59 passed**, 최종 전체 **792 passed**, 종료 코드 0.
첫 실행의 한 실패는 테스트에서 기존 Qt table 속성명을 잘못 참조한 것으로 수정 후 재검사했다.
추가 두 사례의 마지막 Step까지 검사하면서 D 작성 3층 합성 프레임이 3층만 verified인데
아래층도 visible로 넣은 오류를 발견했다. 그 프레임에는 3층만 넣고 확인된 아래층은 Current에
유지하도록 수정했다. B/A/D Consumer·assertion은 바꾸지 않았으며 수정 후 재검사했다.
창 표시용 native CLI도 DISPLAY=:0에서 열기/EOF 종료 코드 0으로 확인했으며 Job/전달은 시작하지 않았다.
화면별 관측/상태 검증은 Qt offscreen으로 실행하고 PNG를 시각 확인했다.

- [관련 검사 JUnit](../logs/abd-hmi-final-results.xml), [전체 검사 JUnit](../logs/abd-hmi-full-results.xml)
- [실행 산출물 색인](../logs/abd-hmi-final/summary.json)
- [마지막 확인 전](../logs/abd-hmi-final/test_normal_qt_start_actual_a_0/before-final.png)
- [최종 합성 완료](../logs/abd-hmi-final/test_normal_qt_start_actual_a_0/complete.png)
- [불일치](../logs/abd-hmi-final/test_independent_b_scenarios_s0/mismatch.png)
- [전달판 판단 불가](../logs/abd-hmi-final/test_independent_b_scenarios_s4/place-unobservable.png)

이번 범위는 진입점 198줄/신규 class 1개, 연결 검사와 이 문서/STATUS **4개 파일**다.
약 500줄 변경의 규모 검토 이유는 실제 A/B 연결을 대화형 화면에서 확인하고 외부 결과를
검사하기 위해서이며 실행 모듈은 200줄 안팎이다. 테스트 길이는 정책의 Test Code Exception에 해당한다.
새 framework/dependency/DB/통신 계층과 공통 계약 변경은 없다. 팀원 코드·Backend 핵심·Robot 설정·
기존 변경을 보존했다. GitHub 게시/새 PR/merge·실제 Camera/Robot 실행은 수행하지 않았다.
