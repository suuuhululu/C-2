# A파트 최초 계획·재계획 계산

기존 실습 코드를 [Day4 공통 계약](https://github.com/suuuhululu/C-2/blob/main/docs/06_CONTRACT_DRAFT.md)의
Design·블록·Plan·Step 형식으로 수정했다. 샘플과 실제 연결에서 같은 계산 함수를 사용한다.
현재 구현 범위는 **최초 Plan**과 **현재 배치 보존＋남은 PLACE Plan** 생성·검증이다.
2026-10-06 수현님 답변에 맞춰 Current 입력과 `status / plan / errors` 반환을 연결했다.

## 실행

이 폴더의 상위 프로젝트 폴더에서 실행한다.

```bash
python3 planning_trial/planner.py planning_trial/sample_design.json --output planning_trial/sample_plan.json
python3 -m pytest planning_trial/test_planner.py -q
```

샘플은 사진의 의자1·의자2를 정확히 복원한 설계가 아닌 임의의 12개 블록이다.
계산 결과는 1층 4개 → 2층 4개 → 3층 2개 → 4층 2개다.
매번 새 plan_id를 발급하므로 다시 실행하면 ID가 달라지지만 Step 순서는 같다.

## 입력: Design

전체 목표의 design_version과 blocks를 받는다. 각 블록은 아래 여섯 필드를 사용한다.

| 필드 | 의미 |
| --- | --- |
| brick_type | 2x2x1 또는 2x3x1 |
| color | yellow 또는 blue |
| x, y | 0~23 정수, stud 단위. 차지하는 영역의 최소 x/y 모서리 |
| layer | 1~4 정수. 조립판 위 첫 층은 1 |
| orientation_deg | 2×2는 0, 2×3은 0 또는 90 |

공통 좌표는 사진 기준 +X 오른쪽, +Y 위다. 2×3의 0도는 X폭 2/Y길이 3,
90도는 X폭 3/Y길이 2다. 회전해도 기준점은 차지하는 영역의 최소 모서리다.
x/y 값뿐 아니라 블록 전체가 24×24 판 안에 있어야 한다.

공통 block_id·design_id·session_id·trial_rules는 요구하지 않는다.
C의 선택적 내부 block_id는 입력에 있어도 계산 기준과 공통 출력에서 제외한다.
구형 z와 orientation을 자동으로 추측해서 변환하지 않는다.

## Backend 연결: Design + Current → 결과

Backend에서 호출할 함수는 `plan_from_current(design, current)`다. 두 입력은
JSON 문자열이나 파일 경로가 아닌 Python dict로 받는다. 파일을 사용할 때는
`json.loads()`로 읽은 결과를 전달한다. Current의 구조는 다음과 같다.

```json
{"current_revision":0,"blocks":[]}
```

`blocks`는 Backend가 채택한 실제 배치이며 `current_revision`은 그 배치의 revision이다.
함수는 이를 기존 `build_plan()`에 전달하고 결과를 아래 구조로 반환한다.

| status | plan | errors |
| --- | --- | --- |
| READY | 검증된 Plan | 빈 배열 |
| NEEDS_CORRECTION | null | 사람이 정리해야 하는 배치·삽입 방해·Current 지지 부족의 사유 |
| INVALID | null | 잘못된 입력·겹치는 Current·목표 또는 Plan 검증 실패의 사유 |

오류 배열의 각 항목은 `reason / block`이다. 현재는 처음 발견한 오류 하나를 반환한다.
배치를 특정할 수 있으면 여섯 공통 필드를 넣고, revision 오류·필드 누락 등
전체 배치를 지목할 수 없으면 `block=null`로 반환한다. 잘못된 필드 값은 오류의
문제 배치에 그대로 표시할 수 있으며, 이를 실행 가능한 블록으로 취급하지 않는다.

```json
{"status":"INVALID","plan":null,"errors":[{"reason":"Current.current_revision must be a nonnegative integer","block":null}]}
```

최초 계획도 빈 Current를 **명시적으로** 전달해 같은 함수를 호출한다.
Current가 없거나 blocks가 null이면 빈 보드로 추측하지 않는다.
READY의 steps가 비어 있어도 Backend가 작업 완료를 별도로 판단한다.

```python
from planning_trial.planner import plan_from_current

result = plan_from_current(design, current)
if result["status"] == "READY":
    plan = result["plan"]  # Backend가 최신성 확인 후 채택
else:
    errors = result["errors"]  # Backend/HMI에서 사유 표시·후속 처리
```

`handoff_examples.json`에는 빈 보드·부분 조립·전체 일치·사람 정리 필요·invalid
입력이 있다. expected_status와 expected_step_count는 테스트 기대값이며 함수 입력이나
반환 필드가 아니다. 이 파일은 실제 카메라 결과가 아닌 합의된 형식의 가상 자료다.

## 출력: Plan과 Step

Plan에는 plan_id, design_version, base_current_revision, steps만 담는다.
Step에는 step_id, operation, before, after, prerequisites, requires_delivery를 담는다.

- operation은 PLACE, before는 null, after는 위의 여섯 필드를 갖는 목표 배치다.
- requires_delivery는 true다. 필요한 부품 종류와 색상은 after에서 읽는다.
- prerequisites는 같은 Plan 안의 선행 step_id 목록이다.
- 매번 새 Plan ID를 생성하고, Step ID는 해당 Plan 안에서 S01부터 부여한다.
- 기존 assembly_steps·delivery_order·expected_assembled_block_ids는 출력하지 않는다.

내부 계산 함수는 build_plan(design, current_blocks, current_revision)이다.
입력은 전체 목표 Design, Backend가 채택한 실제 블록 목록, 그 목록의 revision이다.
base_current_revision에는 입력 revision을 그대로 복사하며 A가 발급하거나 추측하지 않는다.
Backend 연결 함수가 Current에서 이 두 값을 꺼내 전달한다.

build_initial_plan(design)은 build_plan(design, [], 0)을 호출하는 기존 실행용 진입점이다.
Backend가 새 작업의 빈 조립판과 revision=0을 확인했다는 전제다. 이미 진행된 Current는
build_plan에 실제 목록과 revision을 전달한다. 함수가 카메라 관측을 읽어 Current를 채택하지 않는다.

Expected·Current 채택·Step 완료·전달 중복 방지·실행 시점은 D Backend가 관리한다.
로봇 전달 성공을 사람 조립 완료로 기록하지 않는다. 공급 슬롯·로봇 실제 좌표도
A의 출력에 추가하지 않는다.

## 계산과 검사

1. validate_design(): 필수 필드·규격·색상·방향·층·판 범위·겹침을 재검사한다.
2. calculate_remaining_blocks(): 실제 배치가 목표에 보존됐는지 확인하고 남은 블록을 정렬한다.
3. 남은 블록의 낮은 층부터, 같은 층에서는 y 내림차순 → x 오름차순으로 PLACE Step을 만든다.
4. 아래층의 남은 Step만 선행 조건으로 연결한다. 이미 조립된 블록은 중복 Step으로 만들지 않는다.
5. validate_plan(): Current를 시작 배치로 사용해 Step 참조·층 순서·각 시점의 지지와 겹침을 검사한다.
   마지막에는 Current＋모든 PLACE 결과가 목표 블록 및 수량과 일치하는지 확인한다.
6. 검사를 통과하면 Plan을 반환한다. CLI는 화면 출력과 JSON 저장만 담당한다.

한 층을 모두 끝낸 뒤 다음 층으로 가는 순서와 같은 층의 정렬은 A 담당자의 선택이다.
공통 좌표의 +Y와 사람이 보는 먼 쪽이 어떻게 대응하는지는 실물 배치에서 확인해야 한다.

지지 검사는 **바로 아래층과 겹치는 서로 다른 stud가 총 2개 이상**인지 확인한다.
하나의 아래 블록에서 2개가 겹쳐도 통과하며, 여러 아래 블록의 겹침을 합산한다.
1층은 조립판 위이므로 이 검사에서 제외한다. 중복 블록은 겹침 오류로 거부한다.
이 수치는 2026-10-06 수현님 답변에서 A/C 통일에 동의한 기준이다.
GitHub 문서에 남아 있는 후보 표기는 후속 문서 반영이 필요하다.
추가로 위에서 수직으로 끼운다는 단순 가정에서 목표 footprint 위의 기존 블록을 검사한다.
기존 위층 블록이 삽입을 막으면 사람이 정리해야 한다는 이유로 계산을 중단한다.
이 검사는 물리 안정성·재고 수량·손이나 그리퍼의 실제 접근 경로 검증은 아니다.

## 실패 처리

내부 계산 함수는 잘못된 입력이나 계획에 ValueError를 발생시키며 위치와 이유를 메시지에 담는다.
문제 배치·분기 정보를 전달하는 PlanningError는 ValueError의 하위 예외이며 기존 호출도 유지한다.
입력값을 임의로 보정하지 않는다. CLI는 INVALID_INPUT과 이유를 출력하고 종료 코드 2를 반환한다.
출력 파일 저장에 실패하면 OUTPUT_ERROR와 종료 코드 2를 반환한다.

Backend 연결 함수는 예상되는 계산·입력 오류를 status / plan / errors로 반환한다.
실패 시 부분 Plan이나 성공 + 빈 steps로 바꾸지 않는다. 오류 문구를 분석해 분기를
추측하지 않고 예외에 담긴 분기·문제 배치를 사용한다.
기존 최초 계획 CLI의 --output은 호환성을 위해 Plan만 저장한다.
Backend에서 이 CLI 출력 대신 plan_from_current의 반환 객체를 사용한다.

## 재계획 샘플과 함수 사용

- sample_modified_design.json: 전체 Revised Design v2. 초기 목표에서 (4,6,1)에 있던
  노란 2×2 블록을 실제 위치인 (5,6,1)에 보존하는 가상 목표다.
- sample_current_state.json: 같은 블록을 포함해 1층 블록 3개를 조립했다고 가정한 비교 자료다.
  current_revision / blocks 구조로 바꿨다. revision=7은 시험용 입력값이며 실제 관측 기록이 아니다.

calculate_remaining_blocks(design, current_blocks)를 추가했다. 입력은 전체 Revised Design과
Backend가 채택한 실제 블록 목록이다. 바깥 Current는 plan_from_current에서 읽는다.
직접 카메라 검출 목록을 넣는 함수가 아니다.

- 목표와 실제 배치의 규격·색상·좌표·층·방향 및 수량을 비교한다. 내부 ID에 의존하지 않는다.
- 이미 목표에 맞는 블록은 제외하고 남은 블록을 층 → y 내림차순 → x 오름차순으로 반환한다.
- 샘플은 유지 3개, 남은 블록 9개로 계산된다. 빈 Current는 12개, 모두 일치하면 0개다.
- 실제 블록이 목표에 보존되지 않거나 수량이 맞지 않으면 ValueError로 문제 배치를 알린다.
  블록을 제거하거나 이동하는 순서는 만들지 않는다. 연결 함수에서는 NEEDS_CORRECTION으로 반환한다.
- 입력을 변경하지 않고 결과 블록은 복사본으로 반환한다.

calculate_remaining_blocks는 블록 목록만 반환한다. Step이 포함된 Plan이 필요하면
build_plan을 사용한다. 이미 조립된 블록의 지지와 남은 Step의 지지를 함께 계산한다.
가림·미확인 관측을 빈 블록 목록으로 바꾸면 안 되며 유효한 Current 채택은 Backend 책임이다.
남은 블록이 0개라는 사실만으로 실제 작업 완료를 선언하지 않는다.

Revised Design만 최초 계획 함수에 넣으면 전체 12개를 계획하므로 재계획으로 사용하면 안 된다.
남은 블록 목록만 최초 계획 함수에 넣는 것도 현재의 지지 블록을 잃으므로 올바른 연결이 아니다.
다음은 프로젝트 폴더에서 실행 가능한 연결 샘플이다. 샘플과 실제 Backend가
같은 함수를 사용하며 revision은 Current 파일에서 읽는다.

```bash
python3 - <<'PY'
import json
from pathlib import Path
from planning_trial.planner import plan_from_current

design = json.loads(Path("planning_trial/sample_modified_design.json").read_text())
current = json.loads(Path("planning_trial/sample_current_state.json").read_text())
result = plan_from_current(design, current)
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
```

결과는 9개 PLACE Step이며 첫 Step은 노란 2×2, (8,4), 1층이다.
2층의 첫 Step은 이번 Plan의 1층 작업 S01을 참조한다. 이미 조립된 1층 3개를
선행 Step이나 공급 요청으로 다시 만들지 않는다. sample_replan.json에 예시 결과를 저장했다.

현재 지원하는 오류 예시는 목표에 보존되지 않은 실제 배치, 지지가 부족한 Current,
기존 위층 블록이 삽입을 막는 경우, 잘못된 revision·선행 참조·목표 수량 등이다.
연결 함수에서는 오류를 status / plan / errors로 반환하며 검증된 Plan으로 반환하지 않는다.

Backend는 같은 시점의 채택 Current 목록과 revision을 전달해야 한다.
계산 중 Current나 목표 버전이 바뀌면 그 이전 입력으로 만든 결과는 Backend가 채택하지 않는다.
Backend 입출력 구조는 수현님 답변에 맞췄다. D 수신부 조정 후 실제 호출 연결·
전달 중인 부품 처리는 여전히 연결 검증이 필요하다.
자동 제거·이동·교체 계획은 구현 범위에 넣지 않는다.

## 검증 기록

2026-10-06 기준:

- 독립 테스트 112개 PASS. 정상 입력, 필드 누락, 잘못된 값, 회전한 판 경계, 겹침,
  바로 아래층 0/1/2 stud 지지, 복수 아래 블록의 합산, Plan 참조·선행 조건·누락 등을 확인했다.
- 남은 블록 비교는 빈 Current·부분 조립·전체 일치·목표와 다른 배치·수량 중복·잘못된 입력·
  내부 ID 차이·입력 보존을 확인했다. 가상 Current 3개와 Revised Design 12개로 남은 9개를 계산했다.
- 공통 build_plan으로 최초 12개·재계획 9개·전체 일치 0개 Step을 확인했다.
  Current만으로 지지하는 경우와 Current＋새 Step을 합산하는 경우, 중복 공급·잘못된 revision·
  기존 위층 블록에 막히는 경우도 확인했다. 최초 계획과 재계획의 계산 구현을 나누지 않았다.
- CLI로 12개 블록 Plan을 계산하고 sample_plan.json을 새 형식으로 저장했다.
- Current 입력·세 가지 반환 분기·오류 배치/null·입력 보존·수정 후 최신 revision·
  기존 위층 삽입 방해·목표 전체 일치의 빈 Plan을 연결 함수로 확인했다.
- 계산·검사 함수는 Python 표준 라이브러리만 사용한다. 신규 dependency는 없고,
  실패 분기와 문제 배치를 전달하기 위한 PlanningError 하나를 추가했다.
- D 실제 호출 연결·채택 및 실물 조립 검증은 수행하지 않았다.

## 다른 PC에서 C → A 재현하기

A 브랜치 `work/seeun-planning`의 이 파일이 있는 커밋과 아래 C 커밋을 사용한다.
환경은 Git·Python 3.12(시험 환경 3.12.3)이며 네 실행 파일은 표준 라이브러리만 쓴다.
독립 테스트를 실행할 때는 기존 pytest가 추가로 필요하다. Mock 재현에는 API 키·ROS·Qt·장치가 필요 없다.
C Initial/Revised 실행 파일은 `C_DESIGN_USE_LLM=0`을 명시해 C의 기존 Mock 생성기를 선택한다.
A 계산은 실제 연결과 같은 `plan_from_current()`를 사용한다.

최초 기록의 C Initial은 `3e18f04a840db69d30aaa149920f4857e2adf258`, Revised와 fixture는
`9de685b6b135d3a46968fabc9031befb02f91301`이었다. 게시 준비에서는 **네 실행 모두 C의
`9de685b6b135d3a46968fabc9031befb02f91301` 하나로 재검증**했다.
C 브랜치의 이후 변경과 시험 결과를 혼동하지 않도록 이 커밋을 재현 기준으로 고정한다.

현재 터미널 위치를 A checkout의 루트로 둔다. 다음 예시는 기존 C 작업 폴더를 건드리지 않고
옆에 별도 C 소스 checkout을 만드는 방법이다. 이미 이 커밋의 C checkout이 있다면 clone과
checkout을 생략하고 `c_reproduction_root`만 해당 경로로 지정한다.

```bash
git clone --single-branch --branch work/siyul-design-hri https://github.com/suuuhululu/C-2.git ../C-2-c-reproduction
c_reproduction_root="../C-2-c-reproduction"
git -C "$c_reproduction_root" checkout --detach 9de685b6b135d3a46968fabc9031befb02f91301
git -C "$c_reproduction_root" rev-parse HEAD
git rev-parse HEAD
python3 --version
```

C 버전·A 버전·Python 버전을 실행 기록에 함께 남긴다. 이는 C **소스**를 지정하는 것이며
A 계산 코드 복사본이나 시뮬레이션/REAL 분기를 만드는 방식이 아니다.
아래 명령은 하나씩 실행하고 매번 종료 코드가 0인지 확인한다. 오류가 나면 이후 실행 전에
원인을 확인한다. `set -o pipefail`은 `tee` 저장 성공으로 계산 실패를 가리지 않게 한다.

```bash
mkdir -p planning_trial/manual_run_logs
set -o pipefail
python3 planning_trial/check_c_initial.py "$c_reproduction_root" 2>&1 | tee planning_trial/manual_run_logs/initial.log
echo "실행 종료 코드: $?"
python3 planning_trial/run_fake_cases.py 2>&1 | tee planning_trial/manual_run_logs/fake_cases.log
echo "실행 종료 코드: $?"
python3 planning_trial/check_c_revised.py "$c_reproduction_root" 2>&1 | tee planning_trial/manual_run_logs/revised.log
echo "실행 종료 코드: $?"
python3 planning_trial/check_c_fixtures.py "$c_reproduction_root" 2>&1 | tee planning_trial/manual_run_logs/c_fixtures.log
echo "실행 종료 코드: $?"
```

기대 결과는 Initial 15 PLACE, 부분 Current 4개를 제외한 11 PLACE,
NEEDS_CORRECTION·INVALID의 plan=null, Revised v2에서 Current 4개 보존 후 11 PLACE,
공유 fixture 12개 사례 PASS다. 각 실행의 검증 JSON과 로그를 직접 확인한다.
`run_fake_cases.py`는 앞서 생성한 `c_initial/c_response.json`을 읽으므로 최초 실행이 먼저다.
`--initial-response`로 다른 저장 응답을 지정할 수 있고, 네 실행 파일 모두
`--output-dir`로 저장 위치를 변경할 수 있다. 파일이 없으면 가짜 성공 데이터를 만들지 않고 실패한다.

결과는 `planning_trial/integration_results/{c_initial,fake_cases,c_revised,c_fixtures}/`와
`planning_trial/manual_run_logs/`에 **실행 시 생성**한다. 같은 경로로 재실행하면 결과가 갱신되므로
기존 기록을 보존하려면 다른 output-dir·로그 파일명을 사용한다. 생성 JSON·수동 로그·압축 파일은
이번 소스 커밋에 포함하지 않는다. 필요한 JSON과 로그는 실행 후 별도로 첨부한다.

```bash
tar -czf planning_trial/a_manual_execution.tar.gz planning_trial/manual_run_logs planning_trial/integration_results
```

C 공개 성공 응답은 `design`을 꺼내 A에 전달한다. C `run_intervention()`에는
`current["blocks"]` 목록을, A에는 같은 시점의 revision이 포함된 Current 전체 객체를 전달한다.
모든 Current는 이 재현에서 샘플이다. D의 실제 Current 채택·Plan Consumer 수용·HMI·장치
검증을 완료한 것으로 보고하지 않는다. 해당 연결은 D에서 별도로 실행·기록해야 한다.

## C Mock Initial → A 최초 계획 연결 확인

2026-10-06, 시율의 `work/siyul-design-hri` 커밋 `3e18f04`에서 공개 함수
`create_initial_design(text="의자")`를 실제 호출하고, 성공 응답의 design을
기존 `plan_from_current()`에 전달했다. Current는 빈 보드 revision=0의 시험 자료다.
C 응답 OK → A 응답 READY, Design 15개 블록 → PLACE 15 Step을 확인했다.
층별 순서는 **1층 4개 → 2층 6개 → 3층 2개 → 4층 3개**다.
필드·입력 보존·설계/Current 버전·순서·지지/겹침/선행 관계·최종 배치 일치를 검증했다.

C 브랜치의 코드가 있는 checkout 경로를 인자로 전달해 재현한다.
경로·시험 버전 준비는 위의 다른 PC 재현 절차를 따른다.

```bash
python3 planning_trial/check_c_initial.py "$c_reproduction_root"
```

결과는 `integration_results/c_initial/`에 저장된다.
`c_response.json`의 design이 A 입력이고, `current.json`, `a_result.json`,
`verification.json`을 함께 저장한다.
plan_id는 실행마다 새로 발급된다. 검증 결과에는 C 커밋과 A 소스 해시를 기록한다.

이는 C의 **Mock 생성 구현과 A 계산 구현** 사이의 실제 함수 연결 확인이다.
사진 의자 GT 복원·실제 LLM/음성·Revised 경로·D 채택·HMI·장치 시험은 아니다.
신규 자료는 재현용 실행 파일 1개와 입력/출력/검증 JSON 4개이며 계산 구현이나
dependency·class·시뮬레이션/REAL 분기를 추가하지 않았다.

## 가짜 입력 네 가지 직접 실행

2026-10-06 C 공개 Mock Initial을 다시 실행한 뒤, 그 Design으로 A 함수를
직접 호출했다. pytest 결과만 기록한 것이 아니라 실제 반환과 Step 순서를 저장했다.
Current는 직접 만든 시험 자료이며 D의 실제 관측·채택 결과가 아니다.

```bash
python3 planning_trial/run_fake_cases.py
```

| 입력 사례 | 실제 반환 |
| --- | --- |
| 빈 Current | READY, PLACE 15개, 기준 revision 0 |
| 1층 4개가 조립된 Current | READY, 남은 PLACE 11개, 기준 revision 1. 기존 4개 재요청 없음 |
| 파랑 목표 자리에 노랑이 있는 Current | NEEDS_CORRECTION, plan=null, 문제 배치·사유 |
| 목표 블록 layer=5 | INVALID, plan=null, 문제 배치·허용 층 범위 사유 |

`integration_results/fake_cases/execution.txt`와 사례별 실제 입력·반환인
`integration_results/fake_cases/runs.json`을 실행 시 저장한다.
정상 Plan은 공통 validator로 지지·겹침·선행·최종 목표 일치를 검사했다.
이 실행은 A 계산까지이며 C Revised 생성·D 채택·HMI·장치 연결은 확인하지 않았다.
재실행에는 앞 단계의 c_initial/c_response.json이 필요하다. 새 C 응답으로 시험하려면
check_c_initial.py를 먼저 실행한다. 재실행 시 해당 실행 자료를 갱신하며 Plan ID는 달라진다.

## C Mock Revised → A 재계획 직접 실행

2026-10-06, 시험 C 커밋 `9de685b`의 `run_intervention()`과 같은 A 계산 함수를
연결했다. C는 기존 Mock 생성기를 명시적으로 선택했다. 실제 LLM·음성 호출은 없다.
가짜 Current에는 1층 블록 4개를 넣고, 하나를 원래 (9,9)에서 (8,9)로 옮겼다.
원래 Design v1로는 NEEDS_CORRECTION이었다. 가짜 텍스트 응답 "2번"으로 REVISE를
선택하니 C가 실제 (8,9)를 보존한 전체 Design v2를 반환했다.
A는 같은 Current revision=1로 READY·남은 PLACE 11개를 생성했다.
순서는 2층 6개 → 3층 2개 → 4층 3개이며, Current 4개는 다시 요청하지 않는다.
현재 배치 보존·버전·수량·각 PLACE 시점 지지/선행·최종 목표 일치를 검증했다.

```bash
python3 planning_trial/check_c_revised.py "$c_reproduction_root"
```

인자는 C checkout 경로다. 위 재현 절차에서 시험 소스 커밋을 지정한다.
C 공개 함수의 current 인자는 블록 목록이므로 `current["blocks"]`를 전달하고,
A에는 revision을 포함한 같은 Current 전체를 전달한다.

`integration_results/c_revised/`에 입력·Current·Difference인 `inputs.json`,
C 응답 `c_response.json`, A 결과 `a_result.json`, 검증 기록 `verification.json`을 저장한다.
신규 자료는 재현용 실행 파일 1개·JSON 4개다. A/C 계산 코드는 수정하지 않았다.
이 검증은 C Mock → A 함수 사이이며 D 채택·HMI·장치 연결은 미검증이다.

프로젝트의 고정 A 브랜치는 work/seeun-planning을 사용한다.

## C 공유 fixture → A 직접 실행

시율님이 안내한 `tests/unit/c_design/fixtures/`의 JSON을 읽는 실행 파일이다.
확보한 C snapshot `9de685b`에서 12개 사례를 실제 A 함수로 실행해 모두 통과했다.
준비 검증과 사용자 직접 실행 기록을 구분한다.

```bash
python3 planning_trial/check_c_fixtures.py "$c_reproduction_root"
```

인자는 해당 fixture가 들어 있는 C checkout 경로다. 다른 PC에서는 경로를 바꾼다.
`--output-dir`로 결과 저장 위치를 지정할 수 있으며, 기본은
`planning_trial/integration_results/c_fixtures`다. `runs.json`에 사용한 전체 Design·Current와
A 결과를, `verification.json`에 C 커밋·원본 fixture 해시·A 소스 해시·각 검사 결과를,
`execution.txt`에 실제 출력을 저장한다. 재실행 시 지정한 출력 위치의 결과를 갱신한다.

- 최초 8개 PLACE, 부분 조립 2개를 제외한 6개 PLACE, 전체 조립 후 0개 PLACE.
- 수정 전 NEEDS_CORRECTION, 수정 목표 v2와 Current 4개로 남은 4개 PLACE.
- 위치·방향·색상·Board 위치·층 변경은 NEEDS_CORRECTION, 중복 점유는 INVALID.
- `support_violation` fixture는 기존 목표와 다른 배치를 포함하므로 보존 불일치가 먼저
  반환된다. 이 사례만으로 지지 오류 사유가 반환됐다고 주장하지 않는다.

fixture 설명인 `_note`는 계산 입력에 포함하지 않는다. C의 Current 블록 목록은
테스트용 revision을 붙인 공통 Current 객체로 감싼다. 이 revision은 D의 관측값이 아니다.
`difference_cases.json`은 읽어 원본 해시만 기록한다. A는 Difference를 직접 입력받지 않는다.
C fixture의 `expected_input_rules`는 C 검사의 기대값이며 A의 반환 상태와 혼용하지 않는다.
이 실행은 저장된 fixture → 기존 A 함수 확인이다. C 공개 함수·LLM·D Consumer·HMI·장치
연결을 새로 시험하는 것이 아니며, 계산 코드·공통 계약은 변경하지 않았다.

## C 공개 수정 함수 + D Current → A → D 채택

`check_c_a_d_revised.py`는 저장된 C 응답 대신 C의 공개 Initial/Revised 함수를 호출한다.
시험 소스는 main `101d9d85efe8bdf7cf82bef2a199f4919e1e6c84`다. 이 커밋의 C는 Mock 생성기를
사용하며 음성·LLM은 호출하지 않는다. D/A/C 운영 코드와 일반 Difference 변환을 수정하지 않는다.

```bash
python3 planning_trial/check_c_a_d_revised.py /path/to/team-checkout
```

다른 PC에서는 A checkout 루트에서 아래처럼 **C·D를 포함한 main 시험 커밋**을 준비한다.
이 경로는 앞의 C 전용 `9de685b` checkout과 구분한다. 이미 해당 팀 checkout이 있으면
clone·checkout을 생략하고 `team_reproduction_root`만 그 경로로 지정한다.

```bash
git clone --single-branch --branch main https://github.com/suuuhululu/C-2.git ../C-2-team-reproduction
team_reproduction_root="../C-2-team-reproduction"
git -C "$team_reproduction_root" checkout --detach 101d9d85efe8bdf7cf82bef2a199f4919e1e6c84
git -C "$team_reproduction_root" rev-parse HEAD
git rev-parse HEAD
mkdir -p planning_trial/manual_run_logs
set -o pipefail
python3 planning_trial/check_c_a_d_revised.py "$team_reproduction_root" 2>&1 | tee planning_trial/manual_run_logs/c_a_d_revised.log
echo "실행 종료 코드: $?"
```

기대 결과는 아래 Initial/Revised 채택 기록과 `Checks: PASS (17 checks)`, 종료 코드 0이다.

인자는 C·D가 함께 있는 팀 checkout 경로이며 `--output-dir`로 별도 결과 위치를 지정할 수 있다.
실행 파일에는 backend 요청을 실제 A 함수에 전달하고 호출 입력/출력을 기록하는 역할만 추가한다.
관측 fixture와 Fake Robot을 사용하므로 실제 장치를 움직이지 않는다.

- C Initial 공개 함수 → 실제 A 15 PLACE → D 채택.
- 네 블록을 관측 fixture로 확인해 D가 Current revision=4를 만든다.
- 다리 하나를 (9,9,1)에서 (8,9,1)로 옮긴 관측으로 D가 revision=5를 만든다.
- D가 보낸 차이에는 이동 전 다리와 아직 조립되지 않은 다음 Step의 누락이 함께 있다.
  시험에서 알고 있는 이동 쌍과 실제 확인된 빈 다음 Step(actual=null)을 명시적으로 C에 전달한다.
  목록 순서로 짝짓는 일반 변환 기능을 구현한 것이 아니며 가림을 빈 영역으로 취급하지 않는다.
- C `run_intervention(..., text_answers=["2번"])` → REVISE v2 → 같은 D Current로 A 11 PLACE → D 채택.

수정 목표·Current·A 입력/출력·채택 Plan·HMI 표시 데이터는 `integration_results/c_a_d_revised/runs.json`,
검사 결과는 `verification.json`, 실제 출력은 `execution.txt`, D 이벤트는 `jobs/<job_id>.jsonl`에 저장한다.
한 Job 안에서 생성/요청/관측/질문/재계획/채택 기록을 연결한다. 재실행하면 요약 파일은 갱신되고
Job 로그는 새 ID로 추가된다. HMI snapshot 계약은 확인하지만 Qt 창을 표시한 시험은 아니다.
남은 11개 전달·조립 전체 사이클, 실제 LLM·음성·카메라·로봇, 여러 차이의 자동 대응은 미검증이다.
