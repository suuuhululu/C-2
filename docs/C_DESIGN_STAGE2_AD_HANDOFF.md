# C Design Stage 2 어휘 변경 — A/D/공유 문서 인수 목록

2026-10-07

## 최종 Stage 2 vocabulary (2026-10-08 사용자 결정)

아래가 최종 재고 기준입니다. 이 문서의 1~41번 변경 지점은 그대로 유효하며, 공급열·조합 관련 항목은 이 표의 다섯 조합을 기준으로 반영합니다. **C는 A/D 코드와 공유 문서를 수정하지 않았습니다.**

| 항목 | 값 |
| --- | --- |
| 허용 조합(공급열 최종 5개) | yellow `2x2x1`·`2x3x1` / blue `2x2x1`·`2x3x1` / red `1x2x1`만 |
| 금지 조합 | yellow `1x2x1`, blue `1x2x1`, red `2x2x1`, red `2x3x1` |
| `1x2x1` orientation | 0 = X 1 · Y 2 (1×2), 90 = X 2 · Y 1 (2×1). brick_type 이름은 `1x2x1` 하나 |
| MAX_LAYER / MAX_BLOCKS | 5 / 40 |
| 블록 필드 | 여섯 필드 그대로(`brick_type`, `color`, `x`, `y`, `layer`, `orientation_deg`), 새 필드 없음 |
| 조합 검사 | C validator `validator.ALLOWED_COMBINATIONS`, 탈락 rule `invalid_combination`(Design·Revised 후보·입력 Current·Difference 모두). A/D가 같은 검사를 둘지는 각 소유자 결정 |

A/D 영향 요약: 공급열은 3 brick_type × 3 color = 9열이 아니라 **5열**입니다(아래 11·15·16·22·24·30·34번과 "확인 필요"의 공급열 개수). 색 라벨·footprint·stud 수 lookup(7~10·12~14·20·21번)은 세 brick_type·세 color를 모두 다루되, 실제로 나타나는 조합은 이 다섯 개뿐입니다.

## 목적

Stage 2 Wave 1에서 C(`app/c_design/validator.py`, `app/c_design/llm.py`)는 블록 어휘를 `red` 색상·`1x2x1` 브릭·`MAX_BLOCKS` 40으로 확장했습니다. 이 문서는 그 확장이 A(`planning_trial/`)·D(`app/*` 중 `c_design` 외)·공유 계약 문서(`interfaces/schemas/*`, `docs/06_CONTRACT_DRAFT.md`, `docs/00_CURRENT_DECISIONS.md`)에 남긴 하드코딩된 어휘 가정을 파일:줄 단위로 나열해, 각 소유자가 직접 반영하도록 넘기는 인수 목록입니다. **C는 이 항목들을 수정하지 않았습니다.** A/D의 코드·테스트, 공유 문서의 실제 수정과 재검증은 각 소유자의 몫입니다.

## C 쪽 확정 값 (2026-10-07 `app/c_design/validator.py` 기준)

| 항목 | 값 |
| --- | --- |
| color | `yellow`, `blue`, `red` |
| brick_type · footprint(X stud, Y stud, orientation 0 기준) | `1x2x1` = (1, 2) · `2x2x1` = (2, 2) · `2x3x1` = (2, 3) |
| 허용 orientation_deg | `1x2x1` {0, 90} · `2x2x1` {0} · `2x3x1` {0, 90}. 90도는 X/Y footprint를 교환 |
| MAX_LAYER | 5 |
| MAX_BLOCKS | 40 (기존 30) |
| support 규칙(불변) | 바로 아래 layer와 겹치는 **고유 stud 합계 ≥ 2**(아래 블록 개수 무관, 같은 stud 중복 합산 없음). `1x2x1`은 footprint 전체가 stud 2개뿐이므로, 이 규칙을 만족하려면 두 stud 모두 아래 블록 위에 있어야 함(즉 완전히 아래 블록 위에 올라가야 함) |

## 변경 지점 (번호 | 소유 | 파일:줄 | REQUIRED CHANGE | AFFECTED INTERFACE | REASON)

| # | 소유 | 파일:줄 | REQUIRED CHANGE (현재 → 필요) | AFFECTED INTERFACE | REASON |
| --- | --- | --- | --- | --- | --- |
| 1 | A | `planning_trial/planner.py:18` | `BRICK_SIZES = {"2x2x1": (2,2), "2x3x1": (2,3)}` → `"1x2x1": (1,2)` 추가 | Plan 검증(`occupied_cells`/`_block` 입력) | 추가 전까지 `brick["brick_type"] not in tuple(BRICK_SIZES)`(56행)에서 `1x2x1`이 바로 거부됨. orientation 허용 계산(65행 `(0,) if brick_type=="2x2x1" else (0,90)`)은 `1x2x1`도 그대로 `(0,90)`이 되어 별도 수정 불필요 |
| 2 | A | `planning_trial/planner.py:58` | `color not in ("yellow","blue")` → `("yellow","blue","red")` | Plan 검증 | `red` Design이 Plan 단계에서 전부 거부됨 |
| 3 | A | `planning_trial/planner.py:16,64` | `MAX_LAYER = 4` → `5`(63행 에러 메시지 "layer must be an integer from 1 to 4"도 "1 to 5"로 동반 수정) | Plan 검증 | C는 이미 layer 1~5 허용. A가 4로 막아 layer 5 PLACE가 Plan에서 거부됨 |
| 4 | D | `app/contracts.py:38` | `block["brick_type"] not in ("2x2x1","2x3x1")` → `"1x2x1"` 추가 | Design/Current 등 전체 envelope 검증(`_block`) | `1x2x1` Design이 envelope 검증에서 거부됨 |
| 5 | D | `app/contracts.py:40` | `block["color"] not in ("yellow","blue")` → `"red"` 추가 | envelope 검증 | `red` Design이 거부됨 |
| 6 | D | `app/contracts.py:44,111` | `_integer(layer, 1, 4, ...)`(block·region 두 곳) → `1, 5` | envelope 검증(block 및 `verified_regions`) | layer 5 블록/검증영역이 거부됨 |
| 7 | D | `app/current.py:15` | `width, height = (2,2) if brick_type=="2x2x1" else (2,3)` → brick_type별 lookup(1x2x1=(1,2) 포함) | Current 병합 footprint 계산(`_footprint`) | `1x2x1`이 `2x3x1` footprint(2,3)로 잘못 계산되어 중복/범위 검사가 틀어짐 |
| 8 | D | `app/hmi_board.py:20-22`(`dimensions()`), `83`(`_transfer` 내부 동일 삼항 중복) | 이진 삼항 → brick_type별 lookup | Qt 보드 렌더링(배치·전달 미리보기 크기) | 두 곳 모두 `1x2x1`을 `2x3x1` 크기로 그림 |
| 9 | D | `app/hmi_board.py:87,102,208` | `QColor("#efc94b" if color=="yellow" else "#699bde")`(3곳) → `red` 색상 값 포함 lookup | Qt 보드 렌더링 색상 | `red` 블록이 전부 파랑으로 표시됨. red의 실제 HEX 값 확인 필요(아래 "확인 필요") |
| 10 | D | `app/qt_hmi.py:26-28`(`fields()`) | `"4점 (2×2)" if brick=="2x2x1" else "6점 (2×3)"` / `"노랑" if color=="yellow" else "파랑"` → 3종 라벨(예: `1x2x1`="2점 (1×2)", red="빨강") | Step/관측 비교 표 라벨 | `1x2x1`·`red`가 각각 `2x3x1`·`blue`로 잘못 표시됨 |
| 11 | D | `app/qt_hmi.py:80-86` | `for brick in ("2x2x1","2x3x1") for color in ("yellow","blue")`(보충 버튼 4개 생성) → 최종 공급열 조합 전체로 확장 | 보충 버튼 UI, `SUPPLY_COLUMNS`(hmi_contracts)와 1:1 대응 | 새 조합(`1x2x1`·`red` 포함) 보충 버튼이 생성되지 않음. 몇 개 조합을 실제 지원하는지는 공급판 설계에 달림(아래 "확인 필요") **최종 조합은 5개: yellow 2x2·2x3, blue 2x2·2x3, red 1x2(2026-10-08).** |
| 12 | D | `app/qt_hmi.py:226-227` | `fields()`와 동일한 이진 삼항 중복(전달 대상 미채택 시 fallback 표시) | Step 패널 전달 대상 표시 | 9번·10번과 동일 원인의 별도 사본. 한 곳만 고치면 이 fallback 표시는 틀린 채로 남음 |
| 13 | D | `app/qt_hmi.py:245-248` | `"파랑" if color=="blue" else "노랑"` / `"4점" if brick=="2x2x1" else "6점"`(supply 상태 텍스트) → 3종 라벨 | 공급 상태 텍스트 | 같은 이진 라벨 패턴의 또 다른 사본 |
| 14 | D | `app/snapshot.py:46-48` | `"파랑" if color=="blue" else "노랑"` / `"4점" if brick=="2x2x1" else "6점"`(required_action 안내 문구) → 3종 라벨 | HMI 안내 문구(`required_action`) | WAIT_ASSEMBLY 안내에서 `1x2x1`/`red` 목표가 `2x3x1`/`blue`로 잘못 설명됨 |
| 15 | D | `app/snapshot.py:104-106` | `for brick in ("2x2x1","2x3x1") for color in ("yellow","blue")`(robot 없을 때 기본 supply 4칸) → 최종 공급열 조합 전체 | `monitor.supply` 기본값 | robot 연결 전 기본 supply 목록이 새 조합을 포함하지 못함. hmi.schema.json의 `supply` 배열 길이(30번 항목)와 함께 결정 필요 **최종 조합은 5개: yellow 2x2·2x3, blue 2x2·2x3, red 1x2(2026-10-08).** |
| 16 | D | `app/hmi_contracts.py:26-28`(`SUPPLY_COLUMNS`) | `{(brick,color) for brick in ("2x2x1","2x3x1") for color in ("yellow","blue")}`(4개) → 최종 조합 집합 | 공급열 계약의 단일 진실 소스(`_column`, `_monitor`, `_actions`가 모두 참조) | 이 상수를 바꾸면 `app/real_design_controller.py:46`의 "all four Day4 rows" 같은 고정 개수 가정도 함께 깨지므로 연쇄 확인 필요 **최종 조합은 5개: yellow 2x2·2x3, blue 2x2·2x3, red 1x2(2026-10-08).** |
| 17 | D | `app/hmi_contracts.py:42,44`(`_column`) | brick_type/color 허용 튜플 → 3종 | 공급열 검증 | 16번과 별개 위치의 동일 어휘 하드코딩 |
| 18 | D | `app/backend.py:22-24` | `supported_scope=dict(..., brick_types=["2x2x1","2x3x1"], colors=["yellow","blue"], ..., max_layer=4)` → `brick_types`/`colors` 확장 + `max_layer=5` | Backend가 HMI/C에 발행하는 `supported_scope`(snapshot, question_request) | C/HMI가 이 값을 보고 지원 범위를 판단하면 `1x2x1`·`red`·layer 5가 미지원으로 보임. `max_layer`는 C의 `MAX_LAYER=5`와 이미 불일치 상태 |
| 19 | D | `app/robot_trial.py:63` | `line["brick_type"] not in ("2x2x1","2x3x1") or line["color"] not in ("yellow","blue")` → 3종 | 실기 공급열(pick_line) 설정 검증 | 새 조합의 공급열을 설정할 수 없음 |
| 20 | D | `app/robot_trial.py:88` | `studs = 4 if brick_type=="2x2x1" else 6` → brick_type별 lookup(`1x2x1`=2) | 측정 파일(`measurements["lines"]`) 키 조회(`f"{color}_{studs}"`) | `1x2x1`이 6-stud 측정값을 잘못 조회함(값이 없으면 KeyError) |
| 21 | D | `app/real_design_controller.py:33` | `studs = 4 if brick_type=="2x2x1" else 6` → 동일 lookup | 공급 매니페스트 행(`supply_rows`)의 측정값 조회 | 20번과 동일 원인의 별도 사본 |
| 22 | D | `app/real_design_controller.py:46` | `if set(rows) != SUPPLY_COLUMNS: raise ... "all four Day4 rows"` → 최종 공급열 개수에 맞는 문구/검증 | 공급 매니페스트 완전성 검증 | `SUPPLY_COLUMNS`(16번)가 4개를 넘으면 이 "네 개" 전제와 에러 문구가 같이 깨짐 **최종 조합은 5개: yellow 2x2·2x3, blue 2x2·2x3, red 1x2(2026-10-08).** |
| 23 | D | `app/real_trial_hmi.py:59` | `"파랑" if color=="blue" else "노랑"` / `"4점" if brick=="2x2x1" else "6점"`(caption) → 3종 | 실기 단일열 시험 안내 문구 | 새 조합 시험 시 라벨이 틀리게 표시 |
| 24 | D | `app/real_trial_hmi.py:66-69` | `for brick in ("2x2x1","2x3x1") for color in ("yellow","blue")`(supply 4칸 생성) → 최종 공급열 조합 | 실기 단일열 컨트롤러의 `state["supply"]` | 15번과 같은 패턴의 별도 사본 **최종 조합은 5개: yellow 2x2·2x3, blue 2x2·2x3, red 1x2(2026-10-08).** |
| 25 | D | `app/real_trial_hmi.py:456,458` | `choices=("2x2x1","2x3x1")` / `choices=("yellow","blue")`(argparse) → 3종 | `--real-trial` CLI | 새 조합으로 실기 단일열 시험을 CLI에서 지정할 수 없음 |
| 26 | D | `app/real_workflow_hmi.py:261` | `choices=("blue","yellow")`(argparse `--color`) → `"red"` 추가 | `--real-workflow` CLI(단일열 시험 경로) | red 단일열 시험을 CLI에서 지정할 수 없음 |
| 27 | 공유 문서 | `interfaces/schemas/day4.schema.json:67-76`(`$defs/block`) | `brick_type` enum `["2x2x1","2x3x1"]` / `color` enum `["yellow","blue"]` → 3종씩 | Design/Plan/Current JSON 스키마 검증 | 새 조합 블록이 스키마 검증에서 거부. 같은 파일의 `brick_type=="2x2x1" → orientation_deg const 0` `allOf` 규칙(90-109행)은 `1x2x1`에 적용되지 않으므로 수정 불필요(확인함) |
| 28 | 공유 문서 | `interfaces/schemas/day4.schema.json:44-47`(`$defs/layer`) | `"maximum": 4` → `5` | `$ref`로 재사용되는 모든 layer 필드(block·region 등) | 단일 `$def`라 한 곳만 고치면 전체 반영됨. 지금은 모든 참조처가 layer 5를 거부 |
| 29 | 공유 문서 | `interfaces/schemas/hmi.schema.json:21,25,29,116` | `brick_type`/`color` enum 반복 4곳 → 3종씩 | `supply_refill`/`supply`/`transfer_target`/`SUPPLY_REFILLED` command 스키마 | 새 조합 HMI 메시지가 스키마 검증에서 거부 |
| 30 | 공유 문서 | `interfaces/schemas/hmi.schema.json:54,66` | `supply` 배열 `minItems/maxItems: 4`, `supply_refill` 배열 `maxItems: 4` → 최종 공급열 개수 | `monitor.supply`, `actions.supply_refill` 배열 길이 | `SUPPLY_COLUMNS`(16번) 개수가 바뀌면 이 길이도 같이 바뀌어야 함. 최종 개수는 "확인 필요" 참고 **최종 조합은 5개: yellow 2x2·2x3, blue 2x2·2x3, red 1x2(2026-10-08).** |
| 31 | 공유 문서 | `docs/06_CONTRACT_DRAFT.md:45-46` | `brick_type: 2x2x1 또는 2x3x1` / `color: yellow 또는 blue` → 1x2x1/red 추가 | 공유 계약 §2(Brick 여섯 필드) | 공유 계약 문서가 C의 실제 어휘보다 좁음 |
| 32 | 공유 문서 | `docs/06_CONTRACT_DRAFT.md:48` | 표의 layer 칸 "정수 1~4" → "정수 1~5" | 공유 계약 §2 | 53행의 "목표 layer=5는 재설계를 요청" 문구와도 이미 모순(그 문구 자체도 Stage 2에선 layer 5가 정상 범위이므로 재검토 필요) |
| 33 | 공유 문서 | `docs/06_CONTRACT_DRAFT.md` (블록 수 상한 미기재) | 미기재 → `MAX_BLOCKS=40` 명시 | 공유 계약(Design 블록 수 상한) | A/D가 C의 §9.1 `brick_count` 상한(40)을 어디서도 확인할 수 없음 |
| 34 | 공유 문서 | `docs/06_CONTRACT_DRAFT.md:197` | `공급열은 yellow 4 / blue 4 / yellow 6 / blue 6 각각 슬롯 1~6` → 새 brick_type·color 조합을 반영한 공급열 재정의 | 공급 슬롯 계약 서술 | 현재 문구가 2종×2종(4열) 전제를 명시하고 있어, 새 조합 결정 전까지 계약 문서와 실제 어휘가 불일치 **최종 조합은 5개: yellow 2x2·2x3, blue 2x2·2x3, red 1x2(2026-10-08).** |
| 35 | 공유 문서 | `docs/00_CURRENT_DECISIONS.md:39` | `4점·6점 × 노랑·파랑, 24×24 stud, 최대 4층·여섯 배치 필드는 현재 구현의 기준입니다` → 1x2x1(2점)·red·최대 5층 반영 | 최신 결정 요약 | 이 문구는 "현재 구현의 기준"이라고 명시하는데, C 구현은 이미 Stage 2 어휘로 바뀌어 문구가 사실과 다름 |

## 확인 필요

- `app/hmi_board.py`(9번 항목)에서 `red`에 쓸 실제 HEX 색상 값(예: `#...`)이 아직 정해지지 않았습니다. D가 결정합니다.
- (2026-10-08 확정: 최종 공급열은 5개 — yellow 2x2·2x3, blue 2x2·2x3, red 1x2. 위 "최종 Stage 2 vocabulary" 절. 아래는 확정 전 기록입니다.) 최종 공급열(SUPPLY_COLUMNS, 11·15·16·24·30번 항목) 개수가 몇 개인지 미확정입니다. 단순히 3 brick_type × 3 color = 9열 전체를 지원하는지, 아니면 일부 조합만 물리 공급판에 배치하는지(Day4의 "검증된 공급열"처럼 실측 pick_line이 있는 조합만) 사용자/D 확인이 필요합니다. 이 개수가 `hmi.schema.json`의 배열 길이·`real_design_controller.py`의 "all four rows" 문구·Qt 보충 버튼 개수를 모두 결정합니다.
- D가 `app/c_design/validator.py`의 `MAX_BLOCKS=40`을 어디서 실제로 검사하는지(Plan 단계 A, 혹은 Backend)는 이번 조사에서 별도 강제 지점을 찾지 못했습니다. A의 Plan 검증(`planning_trial/planner.py`)에는 블록 개수 상한 검사가 없습니다(AGENTS.md 지침상 "수량 재고 검사는 제외"와 일치하는지, 혹은 블록 개수 자체도 A가 검사하지 않는 것이 의도인지 D/세은 확인 필요).
- `interfaces/fixtures/*.json`, `planning_trial/sample_*.json`은 특정 예시값만 담고 있어(열거형이 아님) 이번 조사에서 REQUIRED CHANGE로 묶지 않았습니다. 새 조합(`1x2x1`/`red`)의 예시 fixture가 A/D 테스트에 필요해지면 그때 추가하면 됩니다.
- `app/abd_input_hmi.py`(합성 입력 시험 도구)에 `yellow`/`blue`만 쓰는 테스트 블록 빌더 호출(58, 59, 181, 229행)이 있습니다. 목록에 없던 항목이라 표에는 넣지 않았으나, D가 새 조합으로 합성 시험을 넓히려면 참고하십시오.

## 확인한 결과(변경 불필요 확인)

- `planning_trial/planner.py:65`의 orientation 허용 계산과 `app/contracts.py:46`의 동일 패턴은 `brick_type=="2x2x1"`만 특별 취급하고 그 외는 `(0,90)`이라, `BRICK_SIZES`/허용 튜플에 `1x2x1`만 추가하면 별도 로직 수정 없이 올바르게 동작합니다.
- `interfaces/schemas/day4.schema.json`의 `allOf`(2x2x1 → orientation 0 강제) 규칙은 `1x2x1`에는 적용되지 않는 범위라 수정이 필요 없습니다.

## Stage 2 Wave 3 `main` 연결이 D에 주는 영향 (2026-10-08 추가)

C는 아래 D 코드·테스트를 수정하지 않았습니다. 2026-10-08 기준 루트 `pytest` 실패·오류 ID는 Wave 3 전(4b063dc)과 같습니다(`OPENAI_LLM_API_KEY`를 fake로 줘도 D 통합 5파일 결과 동일).

| # | 소유 | 파일:줄 | REQUIRED CHANGE (현재 → 필요) | AFFECTED INTERFACE | REASON |
| --- | --- | --- | --- | --- | --- |
| 36 | D | `app/c_text_connection.py:120,161` (`create_initial_design(text=…, should_stop=…)`) | 선호 질문을 쓰려면 `preference_text`(텍스트) 또는 C 음성 모드(`text=None`)와 `on_question` 전달 | C §4.1 `create_initial_design(text=None, should_stop=None, preference_text=None, on_question=None)` | 지금 D 경로는 목표 문장만 넘겨 LLM 모드에서도 선호 질문 없이 무작위 family로 Initial을 만듭니다(호환 동작, 오류 아님). 선호 질문을 HMI에 띄우려면 D 결정 필요 |
| 37 | D | `app/c_text_connection.py:118` (`voice_call`의 initial 분기) | D가 목표를 직접 STT한 뒤 C를 텍스트 모드로 부름 → 선호 답도 D가 받아 `preference_text`로 넘기거나, C 음성 모드로 위임 | C §4.1 | D가 음성 I/O를 소유하는 현재 구조에서는 C가 선호 질문을 TTS로 낼 수 없습니다 |
| 38 | D | `tests/integration/test_c_voice_hmi.py:66-74` 등 LLM(live) 모드 fake `_post_json` | Revised 응답을 이전 Design과 같은 블록 수로 돌려주는 fake는 LLM 모드에서 `too_few_blocks`로 탈락(§8.13 `min_blocks` = 이전 + 6, 상한 40) | C §8.13 richness 하한 | 현재는 이 테스트들이 다른 원인(기존 기준선 실패)으로 먼저 실패해 드러나지 않지만, 기준선 원인이 고쳐지면 Revised fake가 이전보다 6블록 이상 많은 유효 Design을 돌려줘야 합니다 |
| 39 | D | LLM(live) 모드 fake `_post_json` 전반 | Initial 설명(`describe`)·Intervention 답변 해석(`interpret_intervention_answer`)·선호 해석도 같은 transport로 나감 | C §4.1·§4.2 | Rule이 정하지 못한 자유 답변(예: "실수 아니에요")이 들어오면 C가 LLM 해석을 한 번 더 부릅니다. 숫자·명확한 답("1번"·"2번"·"일부러"·"실수")은 추가 호출 없음 |

## Stage 2 Wave 4b Initial HRI가 D에 주는 영향 (2026-10-08 추가)

| # | 소유 | 파일:줄 | REQUIRED CHANGE (현재 → 필요) | AFFECTED INTERFACE | REASON |
| --- | --- | --- | --- | --- | --- |
| 40 | D | `app/c_text_connection.py:118~120` (`voice_call`의 initial 분기: D가 목표를 STT한 뒤 `create_initial_design(text=…)`) | LLM 모드에서 둘 중 하나를 택해야 함: (a) 첫 듣기를 C에 위임 — `create_initial_design(text=None, on_question=…)`로 부르면 C가 인사 TTS → `listen(mode="free", beep=True)` → 해석·되묻기 1회를 맡음(이 경우 D의 `STT_GOAL` 단계는 필요 없음), 또는 (b) 지금처럼 D가 듣되 사용자 **한 문장 전체**를 `text`로 넘기고(예: "사과 같은 의자를 만들고 싶어요"), 되묻기 답이 있으면 `preference_text`로 넘김 | C §4.1 `create_initial_design(text=None, should_stop=None, preference_text=None, on_question=None)` (시그니처 불변, LLM 모드에서 `text`의 의미가 "목표 문장" → "첫 자유 발화 전체") | LLM 모드에서 C는 더 이상 `parse_goal`("의자" 포함 여부)로 사물을 판정하지 않고 LLM 요청 해석으로 판정합니다(앉는 가구가 아니면 `UNSUPPORTED_OBJECT`). Mock 모드는 그대로 `parse_goal`이라 D 통합 테스트(offline)는 영향이 없습니다. D의 `listen()` 직접 호출은 기본 `mode="short"`(대기 8 s·끝 무음 1 s)라 긴 자유 발화가 중간 쉼에서 끊길 수 있으니, (b)를 택하면 `voice.listen(mode="free", beep=True)` 사용을 권장합니다 |

## Stage 2 Wave 4c 진행 표시가 D에 주는 선택지 (2026-10-08 추가)

| # | 소유 | 파일:줄 | REQUIRED CHANGE (현재 → 필요) | AFFECTED INTERFACE | REASON |
| --- | --- | --- | --- | --- | --- |
| 41 | D | `app/c_text_connection.py`(`create_initial_design`·`run_intervention` 호출부) | 필수 아님(선택, Stage 3 후보): `on_progress=callback`을 넘기면 C의 진행 단계(`{stage, message, at}`, 예: ACK 문장·"디자인을 생성하고 있어요.")를 HMI에 표시할 수 있음 | C §4.1·§4.2 `on_progress` (기본 `None`이면 지금과 동일) | 진행 이벤트는 envelope·Design에 넣지 않으므로 D가 콜백을 넘기지 않으면 아무 영향이 없습니다. 텍스트 모드 호출에서는 C가 음성을 내지 않습니다 |
