# A파트 최초 계획·재계획 계산

기존 실습 코드를 [Day4 공통 계약](https://github.com/suuuhululu/C-2/blob/main/docs/06_CONTRACT_DRAFT.md)의
Design·블록·Plan·Step 형식으로 수정했다. 샘플과 실제 연결에서 같은 계산 함수를 사용한다.
현재 구현 범위는 **최초 Plan**과 **현재 배치 보존＋남은 PLACE Plan** 생성·검증이다.

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

## 출력: Plan과 Step

Plan에는 plan_id, design_version, base_current_revision, steps만 담는다.
Step에는 step_id, operation, before, after, prerequisites, requires_delivery를 담는다.

- operation은 PLACE, before는 null, after는 위의 여섯 필드를 갖는 목표 배치다.
- requires_delivery는 true다. 필요한 부품 종류와 색상은 after에서 읽는다.
- prerequisites는 같은 Plan 안의 선행 step_id 목록이다.
- 매번 새 Plan ID를 생성하고, Step ID는 해당 Plan 안에서 S01부터 부여한다.
- 기존 assembly_steps·delivery_order·expected_assembled_block_ids는 출력하지 않는다.

공통 계산 함수는 build_plan(design, current_blocks, current_revision)이다.
입력은 전체 목표 Design, Backend가 채택한 실제 블록 목록, 그 목록의 revision이다.
base_current_revision에는 입력 revision을 그대로 복사하며 A가 발급하거나 추측하지 않는다.
이 인자 구성은 내부 계산용이고 Backend Current의 전체 구조를 확정한 것은 아니다.

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
이 수치는 사용자가 A에 적용하기로 한 기준이며 A/C 공통 계약의 최종 반영은 확인 중이다.
추가로 위에서 수직으로 끼운다는 단순 가정에서 목표 footprint 위의 기존 블록을 검사한다.
기존 위층 블록이 삽입을 막으면 사람이 정리해야 한다는 이유로 계산을 중단한다.
이 검사는 물리 안정성·재고 수량·손이나 그리퍼의 실제 접근 경로 검증은 아니다.

## 실패 처리

현재 Python 함수는 잘못된 입력이나 계획에 ValueError를 발생시키며 위치와 이유를 메시지에 담는다.
입력값을 임의로 보정하지 않는다. CLI는 INVALID_INPUT과 이유를 출력하고 종료 코드 2를 반환한다.
출력 파일 저장에 실패하면 OUTPUT_ERROR와 종료 코드 2를 반환한다.

수현님께 제안한 status / plan / errors 반환 객체는 아직 합의 대기다.
그 구조를 확정 API로 적용하지 않았으며, Backend의 반환 계약을 받은 뒤 연결한다.

## 재계획 샘플과 함수 사용

- sample_modified_design.json: 전체 Revised Design v2. 초기 목표에서 (4,6,1)에 있던
  노란 2×2 블록을 실제 위치인 (5,6,1)에 보존하는 가상 목표다.
- sample_current_state.json: 같은 블록을 포함해 1층 블록 3개를 조립했다고 가정한 비교 자료다.
  블록 여섯 필드만 공통 계약에 맞췄다. 바깥의 trial_only·current_id·is_complete는
  과거 실습용 임시 필드이며 Backend Current 계약이 아니다.
- is_complete=true는 가상 자료에 미확인 영역이 없다는 가정이며, 의자 조립 완료를 뜻하지 않는다.

calculate_remaining_blocks(design, current_blocks)를 추가했다. 입력은 전체 Revised Design과
Backend가 채택한 실제 블록 목록이다. Current 바깥 구조나 revision 필드의 전달 방식을
새로 확정하지 않고, 공통 여섯 필드만 사용한다. 직접 카메라 검출 목록을 넣는 함수가 아니다.

- 목표와 실제 배치의 규격·색상·좌표·층·방향 및 수량을 비교한다. 내부 ID에 의존하지 않는다.
- 이미 목표에 맞는 블록은 제외하고 남은 블록을 층 → y 내림차순 → x 오름차순으로 반환한다.
- 샘플은 유지 3개, 남은 블록 9개로 계산된다. 빈 Current는 12개, 모두 일치하면 0개다.
- 실제 블록이 목표에 보존되지 않거나 수량이 맞지 않으면 ValueError로 문제 배치를 알린다.
  블록을 제거하거나 이동하는 순서는 만들지 않는다. 최종 status 반환은 연결 계약에 맞춘다.
- 입력을 변경하지 않고 결과 블록은 복사본으로 반환한다.

calculate_remaining_blocks는 블록 목록만 반환한다. Step이 포함된 Plan이 필요하면
build_plan을 사용한다. 이미 조립된 블록의 지지와 남은 Step의 지지를 함께 계산한다.
가림·미확인 관측을 빈 블록 목록으로 바꾸면 안 되며 유효한 Current 채택은 Backend 책임이다.
남은 블록이 0개라는 사실만으로 실제 작업 완료를 선언하지 않는다.

Revised Design만 최초 계획 함수에 넣으면 전체 12개를 계획하므로 재계획으로 사용하면 안 된다.
남은 블록 목록만 최초 계획 함수에 넣는 것도 현재의 지지 블록을 잃으므로 올바른 연결이 아니다.
다음은 프로젝트 폴더에서 실행 가능한 샘플이다. 블록 목록을 꺼내는 부분은 임시 샘플용이며
실제 Backend 연결에서는 받은 Current 구조에 맞춘다. revision=7은 시험용 값으로,
A가 발급한 실제 Current revision이 아니다.

```bash
python3 - <<'PY'
import json
from pathlib import Path
from planning_trial.planner import build_plan

design = json.loads(Path("planning_trial/sample_modified_design.json").read_text())
current = json.loads(Path("planning_trial/sample_current_state.json").read_text())
plan = build_plan(design, current["blocks"], current_revision=7)
Path("planning_trial/sample_replan.json").write_text(json.dumps(plan, indent=2) + "\n")
print("남은 Step:", len(plan["steps"]))
print("첫 Step:", plan["steps"][0])
PY
```

결과는 9개 PLACE Step이며 첫 Step은 노란 2×2, (8,4), 1층이다.
2층의 첫 Step은 이번 Plan의 1층 작업 S01을 참조한다. 이미 조립된 1층 3개를
선행 Step이나 공급 요청으로 다시 만들지 않는다. sample_replan.json에 예시 결과를 저장했다.

현재 지원하는 오류 예시는 목표에 보존되지 않은 실제 배치, 지지가 부족한 Current,
기존 위층 블록이 삽입을 막는 경우, 잘못된 revision·선행 참조·목표 수량 등이다.
오류가 있으면 ValueError로 사유를 반환하며 검증된 Plan으로 반환하지 않는다.
status / plan / errors를 포함한 최종 반환 객체는 수현님 답변 후 연결한다.

Backend는 같은 시점의 채택 Current 목록과 revision을 전달해야 한다.
계산 중 Current나 목표 버전이 바뀌면 그 이전 입력으로 만든 결과는 Backend가 채택하지 않는다.
실제 Backend 구조·호출 연결·전달 중인 부품 처리는 아직 연결 검증이 필요하다.
자동 제거·이동·교체 계획은 구현 범위에 넣지 않는다.

## 검증 기록

2026-10-06 기준:

- 독립 테스트 89개 PASS. 정상 입력, 필드 누락, 잘못된 값, 회전한 판 경계, 겹침,
  바로 아래층 0/1/2 stud 지지, 복수 아래 블록의 합산, Plan 참조·선행 조건·누락 등을 확인했다.
- 남은 블록 비교는 빈 Current·부분 조립·전체 일치·목표와 다른 배치·수량 중복·잘못된 입력·
  내부 ID 차이·입력 보존을 확인했다. 가상 Current 3개와 Revised Design 12개로 남은 9개를 계산했다.
- 공통 build_plan으로 최초 12개·재계획 9개·전체 일치 0개 Step을 확인했다.
  Current만으로 지지하는 경우와 Current＋새 Step을 합산하는 경우, 중복 공급·잘못된 revision·
  기존 위층 블록에 막히는 경우도 확인했다. 최초 계획과 재계획의 계산 구현을 나누지 않았다.
- CLI로 12개 블록 Plan을 계산하고 sample_plan.json을 새 형식으로 저장했다.
- 계산·검사 함수는 Python 표준 라이브러리만 사용하며 새 dependency·class를 추가하지 않았다.
- C/D 실제 모듈 연결 및 실물 조립 검증은 수행하지 않았다.

프로젝트의 고정 A 브랜치는 work/seeun-planning을 사용한다.
