# C Design 계약

상태: **확정 (2026-10-05 사용자 승인, WAVE 1).** 시율(C) 파트의 공개 함수·입출력·Design 형식·검증·실패 반환을 정의합니다. 팀 공용 개념과 Owner는 [00_CURRENT_DECISIONS.md](00_CURRENT_DECISIONS.md), 공통 객체 초안은 [06_CONTRACT_DRAFT.md](06_CONTRACT_DRAFT.md)를 따릅니다. 이 문서는 C 쪽 생산·소비 형식을 구체화한 것이며, 연결 담당이 확인할 항목은 [§11](#11-연결-담당-확인-항목)에 분리했습니다. 구조와 파일 책임은 [C_DESIGN_STRUCTURE.md](C_DESIGN_STRUCTURE.md), 진행 상황은 [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md)를 봅니다.

## 1. 용어

C 문서·코드·Fixture·테스트는 아래 팀 공용 용어만 씁니다. 코드 식별자는 공용 용어에서 직접 파생한 이름 하나만 씁니다.

| 공용 용어 | 근거 | 코드 식별자 | 의미 |
|---|---|---|---|
| Design | 06 공통 객체 Design | `design` | 목표 배치. 버전을 가지며 현재 채택된 Design이 조립 기준 |
| Initial Design | 00 Initial / Revised Design | `design_version == 1` | 키워드로 처음 만든 Design |
| Revised Design | 00 F02 Revised 생성 | `parent_version != None` | Current를 보존해 새로 만든 Design |
| Brick | 06 공통 객체 Brick | `brick` | Design·Current 안의 블록 1개 |
| Current | 00 Current | `current` | Backend가 유효 Observed를 채택한 실제 상태 |
| Difference | 00·06 Difference | `differences` | Backend가 판정한 Expected / Current 차이 |
| 변경 context | 00 F01 | (입력 묶음) | Design·채택 Current·Difference·지원 제약 |
| Intervention | 00 F06 | `run_intervention` | 실제 차이 발생 시 사용자 의도 확인 과정 |
| Original 유지 | 00 F02 | `KEEP_ORIGINAL` | **현재 채택된 Design**을 계속 따름. 최초 버전 복귀가 아님 |
| Revised 생성 | 00 F02 | `CREATE_REVISED` | Current를 인정·보존한 Revised Design 생성 |
| 불명확 | 00 F02·F04 | `UNCLEAR` | 응답을 판단할 수 없음, C가 재질문 |
| HRI 결과 | 06 공통 객체 HRI | `hri_result` | 위 세 값 중 하나 |
| 질문 / 재질문 | 00 F03·F04 | `questions` | C가 만든 질문 문장 |

사용하지 않는 용어: Target Design, Modified Design, KEEP_TARGET, KEEP_CURRENT, deviation, Decision, brick_type, local_x, local_y, long_axis, design_local_stud.

## 2. 공통 LEGO / Board 규약

| 필드 | 허용 값 | 정의 |
|---|---|---|
| `color` | `YELLOW`, `BLUE` | 대문자 문자열 |
| `geometry` | `2x2x1`, `2x3x1` | ASCII 소문자 `x` |
| `grid_x` | 정수 0~23 | 24×24 Board stud 좌표. Robot mm·TCP 좌표 아님 |
| `grid_y` | 정수 0~23 | 위와 같음 |
| `orientation_deg` | `2x3x1`: 0 또는 90 / `2x2x1`: 0 | 0 = X 2 stud · Y 3 stud, 90 = X 3 stud · Y 2 stud |
| `layer` | 정수 1~4 | **1-based.** layer 1 = Board 위 첫 LEGO 층 (팀 합의) |

- anchor: `(grid_x, grid_y)`는 Brick footprint가 차지하는 stud 중 X·Y가 모두 최소인 stud입니다(GT 메모의 anchor 정의). 회전 후에도 같은 기준입니다.
- footprint: `2x2x1`은 X 2 · Y 2, `2x3x1`은 위 orientation_deg 정의를 따릅니다. footprint 전체가 0~23 안에 있어야 합니다.
- GT 원본의 0-based layer는 과거 표기이며 C에 적용하지 않습니다.

## 3. Design 형식

### 3.1 Design (top-level)

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `design_version` | int ≥ 1 | 예 | Initial = 1. Revised = 입력 Design의 `design_version` + 1 |
| `parent_version` | int 또는 `null` | 예 | Initial = `null`. Revised = 입력 Design의 `design_version` |
| `object_type` | `"CHAIR"` | 예 | 지원 사물. Day 4는 `CHAIR`만 지원 |
| `source` | `"MOCK"` 또는 `"LLM"` | 예 | 생성 경로. Mock 결과를 Real로 오인하지 않게 함 |
| `bricks` | Brick 배열, 1~20개 | 예 | 순서는 의미 없음. 조립 순서는 A가 결정 |

### 3.2 Brick

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `block_id` | 문자열, 정규식 `^B[0-9]{3}$` (`B001`~`B999`, 대문자) | 예 | Design 안에서 유일한 ID. 이전 Design에 있던 Brick은 Revised Design에서 값이 바뀌어도 같은 ID를 유지하고, 새로 추가한 Brick만 새 ID를 받음 (§8.4). 공급 slot 번호·조립 순서와 무관 |
| `color` | §2 | 예 | |
| `geometry` | §2 | 예 | |
| `grid_x` | §2 | 예 | |
| `grid_y` | §2 | 예 | |
| `orientation_deg` | §2 | 예 | |
| `layer` | §2 | 예 | |

정수 필드(`design_version`, `parent_version`, `grid_x`, `grid_y`, `orientation_deg`, `layer`)는 소수점 없는 JSON 정수만 허용합니다. `true`/`false`와 `1.0`은 정수가 아닙니다. C가 출력하는 Design에는 위 필드 외의 키가 없습니다. 예시(형식 설명용, 실제 Chair Fixture는 WAVE 2에서 작성):

```json
{
  "design_version": 2,
  "parent_version": 1,
  "object_type": "CHAIR",
  "source": "MOCK",
  "bricks": [
    {"block_id": "B001", "color": "YELLOW", "geometry": "2x3x1",
     "grid_x": 6, "grid_y": 5, "orientation_deg": 0, "layer": 1}
  ]
}
```

### 3.3 Initial Design 배치

완성 Chair 전체 footprint(모든 layer 합집합의 bounding box)의 중심을 24×24 Board 중심에 최대한 맞춥니다. bounding box 크기가 W × H stud이면 bounding box의 최소 stud는 `grid_x = (24 − W) // 2`, `grid_y = (24 − H) // 2`입니다. 결과 footprint가 0~23을 벗어나면 §9.1 범위 검사로 거부합니다.

- **금지**: 특정 Brick의 anchor를 `24 // 2 = (12, 12)`에 두는 구현. Board 중심은 stud 11과 12 사이이므로 (12, 12) anchor는 구조를 +X·+Y로 치우치게 합니다.
- 예: bounding box가 2x2 하나(W = H = 2)이면 최소 stud는 (11, 11)이고 footprint는 11~12로 중심에 대칭입니다. (12, 12)에 두면 12~13이 되어 중심에서 벗어납니다. W = 5 → 9, W = 6 → 9, W = 7 → 8.
- 향후 테스트 조건(구현은 WAVE 2 이후): Initial Design의 bounding box 최소 stud가 위 공식과 같아야 하며, Fixture·Designer·Test에서 `24 // 2`를 특정 Brick anchor로 쓰지 않습니다.

| 원칙 | Initial Design | Revised Design |
|---|---|---|
| 우선 기준 | Board 중앙 배치 | 조립된 Current 보존 |
| 중앙 재정렬 | 위 공식으로 정렬 | **하지 않음** |
| 중심 이탈 | 공식 결과 외 불허 | 허용 (Current가 강제하는 위치를 따름) |
| 전체 이동(shift) | 해당 없음 | 조립된 Brick은 움직일 수 없음, 미조립 Brick의 기계적 일괄 이동 금지 (§8.6) |

## 4. 공개 함수 (`app.c_design.main`)

외부 모듈은 이 두 함수만 호출합니다. 두 함수 모두 예외를 밖으로 던지지 않고 §6의 결과 dict를 반환합니다.

**Recovery First**: 실행 중 C는 스스로 실패·정지·포기하지 않습니다. 후보 Design 거부, malformed LLM 출력, 일시적 LLM·STT·TTS 실패, 불명확 응답은 모두 재시도·재생성·재질문으로 복구합니다(§10). C가 스스로 Intervention을 끝내는 유일한 정상 조건은 사용자 무응답(§4.3)입니다.

### 4.1 `create_initial_design(text=None)`

| 입력 | 타입 | 의미 |
|---|---|---|
| `text` | str 또는 `None` | 텍스트 입력 모드면 사용자 목표 문장(예: "오늘은 의자를 만들 거야"). `None`이면 음성 모드: C가 녹음·STT로 목표를 받음. str도 `None`도 아니면 `INVALID_INPUT`, 공백뿐인 문자열은 `UNSUPPORTED_OBJECT` |

출력: §6 결과. 성공 시 `design`은 Initial Design, `hri_result`는 `null`.

### 4.2 `run_intervention(design, current, differences, text_answers=None, on_question=None)`

| 입력 | 타입 | 의미 |
|---|---|---|
| `design` | Design (§3) | 현재 채택된 Design |
| `current` | Brick 배열 | Backend 채택 Current의 Brick 목록 (§5.1) |
| `differences` | Difference 배열, 1개 이상 | 이번 Intervention의 원인 차이 (§5.2). 빈 배열이면 `INVALID_INPUT` |
| `text_answers` | str 배열 또는 `None` | 텍스트 입력 모드: 질문마다 순서대로 쓰일 응답. `None`이면 음성 모드 |
| `on_question` | `callable(str)` 또는 `None` | C가 질문·재질문을 낼 때마다 그 문장으로 호출. D가 HMI 화면에 표시할 때 사용. 콜백이 던진 예외는 C가 잡지 않으며 호출자 책임입니다(§4의 "예외 없음" 약속의 유일한 예외) |

흐름: C가 질문 문장 생성 → `on_question` 통지 → (음성 모드) TTS 재생 → 재생 종료 후 녹음·STT → 응답 해석.

- 불명확 → C가 즉시 전체 질문을 다시 합니다. 음성 모드의 무응답 취소는 §4.3을 따릅니다.
- 텍스트 모드에서 `text_answers`가 소진될 때까지 불명확이면 `hri_result = "UNCLEAR"`로 반환합니다.
- Original 유지 → 입력 `design`을 **변경 없이** 그대로 반환. LLM 호출 없음, 버전 변화 없음.
- Revised 생성 → Revised Design을 생성·검증해 반환.

### 4.3 음성 모드 무응답 종료

> 상태: 사용자 지시로 정한 C 정책입니다. 00 F04 "사용자 응답 대기·횟수 제한 없음"과 다르므로 공용 문서 F04 개정이 필요합니다.

**침묵 시계 하나**만 씁니다. 침묵 시간 = 지금 − (마지막 의미 있는 발화가 끝난 시각, 없으면 최초 질문 재생이 끝난 시각). 아래 시점은 모두 이 시계 기준입니다.

| 침묵 시간 | C 동작 |
|---|---|
| 0초 | 질문 재생 종료 후 듣기 시작 |
| 25초 | 짧은 확인 질문 1회 (예: "1번 또는 2번으로 말씀해 주세요") |
| 60 / 120 / 180 / 240초 | 상태 확인 질문: 응답이 필요하다는 사실과 선택지를 다시 알림 (예: "작업을 계속하려면 1번 원래 설계 유지 또는 2번 새 설계 중 하나를 말씀해 주세요") |
| 300초 | 최종 안내를 TTS로 재생 (예: "5분 동안 답변을 기다렸지만 응답이 없어 이번 요청을 취소 처리하겠습니다"). 재생이 끝나면 다시 듣지 않고 `status: CANCELLED`, `error.code: NO_RESPONSE`로 반환. D가 Workflow를 정리 |

| 규칙 | 내용 |
|---|---|
| 의미 있는 발화 | 정규화 후 비어 있지 않은 STT 텍스트. "잠시만요", "뭐라고요?", "잘 모르겠어요", 불명확 응답 포함 |
| 시계 재시작 | 의미 있는 발화가 끝나면 침묵 시간을 즉시 0으로. 침묵 구간은 서로 독립이며 누적하지 않음 (3분 침묵 + 발화 + 2분 침묵은 5분이 아님) |
| 재시작하지 않음 | 침묵·잡음(STT 결과 빈 문자열), C 자신의 질문 재생 |
| 불명확 응답 | 시계를 0으로 하고 즉시 전체 질문을 다시 함. 새 침묵 구간에도 같은 시점표 적용 |
| 듣기 창 | `voice`의 1회 듣기는 최대 12초, 침묵이면 빈 문자열 반환 |
| 표시 | 확인 질문·상태 확인 질문·최종 안내도 모두 `on_question`으로 통지하고 `questions`에 기록 |
| 장치·엔진 실패 | 무응답이 아님. §10 Recovery First로 재시도하며, 재시도·backoff 대기 시간은 침묵 시간에 넣지 않음 |
| 반환 | `status: CANCELLED`, `hri_result: null`, `design: null`, `error: {code: NO_RESPONSE, details: [총 경과 초, 마지막 침묵 구간 초, 질문 횟수]}` |
| 구현 형태 | 별도 thread·watchdog 없이 `main` 대화 루프가 `voice` 듣기 호출 전후로 시계를 확인 |
| 기본값 | 300 / 25 / 60초 간격 / 12초는 `main` 모듈 상수(설정 가능한 기본값) |
| 텍스트 모드 | 시계 없음. `text_answers` 소진 시 `UNCLEAR` 반환(§4.2) |

계속 말하지만 불명확한 응답만 하는 경우에는 종료하지 않습니다. 사용자가 반응하고 있으면 대화를 이어간다는 요구를 따른 것이며, 이때 중단은 D의 STOP으로 합니다.

질문 문장·재질문 문장·선택지 표현은 C가 만듭니다. D는 질문 문자열을 C에 주지 않습니다. 질문 템플릿·응답 규칙·LLM fallback은 WAVE 2 이후 구현합니다.

## 5. 입력 형식 (D → C)

C는 아래 필드만 읽고 나머지 키는 무시합니다. D는 자기 객체를 그대로 넘겨도 됩니다. 순차 조립 전제(A가 다음 Brick 결정 → D가 1개 전달 → 사람 조립 → B / D 확인)에서 D는 어떤 Design Brick을 전달·조립했는지 알므로, 조립된 Brick의 `block_id`를 함께 줍니다.

### 5.1 Current Brick

`block_id`, `color`, `geometry`, `grid_x`, `grid_y`, `orientation_deg`, `layer` (§2, §3.2).

- `block_id`는 필수이며, 입력 `design`에 있는 ID여야 합니다. 이 Brick을 전달할 때의 Design Brick ID입니다.
- 6개 값은 Design 값이 아니라 **실제로 놓인 값**입니다. 잘못 놓인 Brick도 실제 값 그대로 줍니다.
- 관측 ID·confidence 등은 읽지 않습니다. D가 이미 Board 좌표·1-based layer로 채택한 값이어야 합니다.

### 5.2 Difference

| 필드 | 타입 | 의미 |
|---|---|---|
| `expected` | Brick(§5.1, `block_id` 포함) 또는 `null` | Expected에 있던 배치. `null`이면 Expected에 없던 Brick |
| `actual` | Brick(§5.1, `block_id` 포함) 또는 `null` | Current의 실제 배치. `null`이면 누락된 Brick |

C는 두 Brick의 값을 비교해 어떤 항목(위치·색·방향·층 등)이 다른지 질문 문장에 씁니다. 어떤 Brick끼리 대응하는지는 D가 준 `block_id`를 그대로 사용하며, C는 같은 color·geometry Brick 간 대응(Data Association)을 하지 않습니다.

## 6. 결과 형식 (C → D)

두 공개 함수는 같은 형식을 반환합니다.

| 필드 | 타입 | 의미 |
|---|---|---|
| `status` | `"OK"`, `"CANCELLED"`, `"FAILED"` | `CANCELLED` = 사용자 무응답 취소(§4.3). `FAILED` = 입력 오류 또는 시스템 장애(§10) |
| `hri_result` | `"KEEP_ORIGINAL"`, `"CREATE_REVISED"`, `"UNCLEAR"`, `null` | `create_initial_design`은 항상 `null` |
| `design` | Design 또는 `null` | 성공 시 채택 후보 Design |
| `questions` | str 배열 | 이번 호출에서 C가 낸 질문·재질문 문장(로그·표시용). Initial은 빈 배열 |
| `error` | `null` 또는 `{code, message, details}` | `status`가 `OK`가 아닐 때(`CANCELLED`·`FAILED`)만 값이 있음 |

| 경우 | status | hri_result | design |
|---|---|---|---|
| Initial 성공 | OK | null | Initial Design |
| Original 유지 | OK | KEEP_ORIGINAL | 입력 Design 그대로 |
| Revised 생성 성공 | OK | CREATE_REVISED | Revised Design |
| 텍스트 모드 응답 소진, 불명확 | OK | UNCLEAR | null |
| 무응답 취소 | CANCELLED | null | null |
| 입력 오류·시스템 장애 | FAILED | `CREATE_REVISED`(Revised 생성 중 시스템 장애) 또는 null. KEEP_ORIGINAL·UNCLEAR는 FAILED와 함께 반환되지 않음 | null |

`CANCELLED` 철자는 C 결과 상태 값이며, 참고 정책의 Robot 명령 상태 `CANCELED`와는 다른 도메인입니다. `message`는 사람이 읽는 로그용 문장입니다. 분기는 `status`·`hri_result`·`error.code`로만 합니다.

## 7. C → A 전달

A에게 가는 객체는 §3의 Design 그대로입니다(Initial·Revised 동일 형식, patch 아님). A는 `block_id`와 6개 값으로 Plan Step의 목표 Brick을 가리키고, `design_version`으로 Plan의 기준 Design을 표시합니다. 재계획 입력의 Current는 A가 D에게서 받습니다(00 D01). C는 조립 순서·NextPart·남은 작업·필요 블록 종류를 Design에 넣지 않으며, "다음은 B004" 같은 순서 지시도 하지 않습니다. `block_id` 번호 크기는 조립 순서를 뜻하지 않습니다. A의 재계획은 새 Design과 Current로 매번 다시 계산하므로(00 D01·D05·D06) 미조립 Brick의 버전 간 ID 연속성은 A에 필요하지 않지만, 이전 Design에 있던 Brick은 가독성과 추적을 위해 같은 ID를 유지합니다(§8.4).

## 8. Revised Design 규칙

1. **full object**: Revised Design은 전체 Brick 목록을 담은 새 Design입니다. 이전 Design과의 차이(patch)를 반환하지 않습니다.
2. **버전 (Owner = C, 확정)**: `design_version` = 입력 Design `design_version` + 1, `parent_version` = 입력 Design `design_version`. 버전 값과 lineage는 C(Python)가 발급·관리하고 LLM은 정하지 않습니다. 버전은 후보가 §9.1 검증을 **통과한 뒤에만** 부여합니다. 거부된 후보는 버전을 소비하지 않습니다(후보 A·B 거부, C 통과 → C가 처음으로 v2). Initial Design도 같습니다. D는 C가 반환한 Design과 버전을 채택·기록·최신 상태로 관리하며 버전을 새로 발급하지 않습니다.
3. **조립된 Brick 보존 (hard)**: 입력 `current`의 모든 Brick은 Revised Design에 **같은 `block_id`와 같은 6개 값**(`color`, `geometry`, `grid_x`, `grid_y`, `orientation_deg`, `layer`)으로 정확히 1개 존재해야 합니다. 이동·삭제·교체할 수 없습니다. 잘못 놓인 Brick도 실제 위치·방향 그대로 받아들입니다. 예: B001·B002 조립 완료, B003을 (5, 5) 대신 (5, 6)에 놓고 Revised 생성 → Revised Design에서 B001·B002는 그대로, B003은 같은 ID로 (5, 6). 보존 대상은 LLM이 고르지 않고 Python이 `current`로 정합니다.
4. **block_id (LLM은 새 ID를 발급하지 않음)**:
   - 원칙: 이전 Design에 있던 Brick은 Revised Design에서도 같은 `block_id`를 유지합니다. 미조립 Brick은 위치·방향·layer·색·geometry·구조 역할이 바뀌어도 같은 논리적 Brick이면 같은 ID입니다. 예: v1 B004 (7, 5) → v2 B004 (8, 5). B004가 B021로 바뀌지 않습니다.
   - 대응 방법: LLM은 입력 Design을 `block_id`와 함께 받고, 출력에서 기존 Brick은 같은 `block_id`를 그대로 적습니다(조립된 Brick은 값도 그대로). 삭제한 미조립 Brick은 생략하고, 새로 추가한 Brick은 `block_id`를 `null`로 적습니다. C(Python)는 값 비교로 대응을 추론하지 않으며 `null`에만 새 ID를 부여합니다. Data Association이 아닙니다.
   - 새 ID: 입력 Design에 있는 `block_id` 번호의 최댓값 + 1부터 순서대로. 이번 생성에서 삭제한 ID는 입력 Design에 아직 있으므로 즉시 재사용되지 않습니다. 삭제된 미조립 ID는 그다음 버전부터 다시 쓰일 수 있는데, 조립된 Brick은 삭제되지 않고 A는 버전마다 다시 계산하므로 영향이 없습니다. Brick은 `design_version`과 `block_id`의 쌍으로 기록합니다.
   - Initial Design은 B001부터 순서대로 발급합니다.
   - 이 정책으로 버전이 여러 번 바뀌어도 ID는 실제로 추가된 Brick 수만큼만 늘어납니다.
   - LLM이 두 미조립 Brick의 ID를 서로 바꾸거나 기존 Brick을 `null`로 다시 추가해도 hard constraint 위반은 아니며 A에도 영향이 없으므로 거부하지 않습니다.
5. Revised Design도 §9의 hard constraint를 모두 통과해야 반환합니다.
6. **단순 이동 금지**: 잘못 놓인 Brick 하나에 맞춰 나머지 Brick을 같은 거리만큼 기계적으로 옮긴(translate) 결과를 Revised Design 생성 방식으로 쓰지 않습니다. 미조립 Brick은 위치·방향·layer·역할을 바꿀 수 있고(ID는 유지), Current를 기준으로 전체를 다시 설계합니다. 단, 결과가 hard constraint를 통과하면 validator가 거부할 근거는 없으므로 이 규칙은 Designer·Prompt의 soft goal(§8.9)로 둡니다.
7. **사용자 선택 유지**: C는 사용자 동의 없이 사용자의 선택을 취소하거나 Original 유지로 전환하거나 입력 Design을 대신 반환하지 않습니다. Revised 생성 중 시스템 장애(§10)가 나면 `status: FAILED`, `hri_result: CREATE_REVISED`, `design: null`을 반환하고, 이후 블록 전달 보류와 사용자 재확인은 D Workflow가 담당합니다.

### 8.8 Revised 생성 시 LLM에 주는 context

| 항목 | 출처 |
|---|---|
| 최종 목적물이 Chair라는 것 | 입력 `design.object_type` |
| 기존 Design 전체(`block_id` 포함)와 현재 `design_version` | 입력 `design` |
| 조립 완료 Brick 전체(`block_id`, 실제 위치·방향·색·layer) = 고정 Brick | 입력 `current` |
| 미조립 Brick 목록 | 입력 `design` 중 `current`에 없는 `block_id` |
| Difference | 입력 `differences` |
| 사용자 의도 = Revised 생성 | HRI 결과 |
| 지원 color·geometry·orientation, Board 24 × 24, layer 1~4, Brick 수 상한 | §2, §3 |
| overlap·support·connectivity 규칙 | §9.1 |
| soft design goal | §8.9 |
| 직전 후보의 거부 사유(재생성 시) | §8.10 |

LLM 출력에서 쓰는 값은 Brick의 6개 값과 기존 `block_id`(또는 새 Brick의 `null`)뿐입니다. 새 ID·버전은 Python이 채우고, LLM이 고정 Brick을 바꾸거나 입력 Design에 없는 ID를 쓴 출력은 §9.1에서 거부합니다.

### 8.9 Hard constraint와 Soft design goal

| Hard constraint (validator가 검증, 위반 시 거부) |
|---|
| 조립된 Brick 보존 (§8.3) |
| 필수 필드·형식, 허용되지 않은 키 없음 |
| color·geometry·orientation_deg·layer 허용 값 |
| footprint가 Board 0~23 안 |
| Brick 수 1~20, `block_id` 유일, 입력 Design에 없는 기존 ID 사용 금지 |
| 같은 layer overlap 없음 |
| support (아래 layer와 겹침 합계 2 stud 이상, §9.1) |
| connectivity |

| Soft design goal (Designer·Prompt에 반영, validator 미검증) |
|---|
| Chair다운 기능 형태: 다리·좌석·등받이 |
| 좌우 대칭·시각 균형. 수학적 mirror를 강제하지 않고, Current가 강제하는 비대칭을 기준으로 균형을 최대화 |
| 일관된 배치 |
| 단순 이동보다 전체 재설계 우선 (§8.6). Initial과 상당히 다른 구조도 허용 |

Soft design goal은 테스트로 강제하지 않습니다.

### 8.10 후보 거부와 재생성 (Validator 거부 ≠ Workflow 실패)

Validator가 후보 Design을 거부하는 것은 **후보 하나를 쓸 수 없다는 뜻**이지 Intervention이나 Workflow의 실패가 아닙니다. 고정된 최대 시도 횟수는 없습니다.

1. validator는 거부 사유를 `[{rule, block_ids, message}]` 목록으로 반환합니다. malformed JSON도 `rule: "malformed_output"`인 거부 사유 하나입니다.
2. designer는 그 사유를 LLM에 다시 주고 "현재 후보는 이 이유로 사용할 수 없다. hard constraint와 Current를 유지하면서 다른 Design을 생성하라"고 재요청하며, 통과할 때까지 반복합니다. 거부 사유는 로그와 재요청 입력으로만 쓰고 결과 dict로 반환하지 않습니다.
3. busy loop 금지: 재요청 사이 1초 간격. LLM API 오류는 1, 2, 4, 8초, 이후 10초 간격(상한)으로 재시도. 값은 `designer` 모듈 상수(설정 가능)입니다.
4. 연속 거부 횟수는 포기 기준이 아니라 **전략 전환 기준**입니다.

| 연속 거부 | 전략 |
|---|---|
| 1~3회 | 거부 사유만 붙여 재생성 |
| 4회 이후 | 다른 구조·다른 균형·더 단순한 Chair로 재설계하도록 지시 |
| 6회마다 (Revised만) | §8.11 escalation 질문 |

5. 후보가 통과하면 연속 거부 횟수는 0이 됩니다. Mock 생성은 결정론적이므로 재생성하지 않습니다.

### 8.11 Escalation: 최소 물리 변경 제안 (최후 수단, Revised만)

우선순위: 자동 재설계 → 다른 전략 → 조립된 Brick 최대한 유지 → 거의 불가능할 때만 최소 변경 제안 → 사용자 응답을 받아 계속. "만들 수 없으니 종료"는 하지 않습니다.

| 항목 | 내용 |
|---|---|
| 진입 조건 | Revised 생성에서 후보가 6회 연속 거부됨, 또는 `current` 자체가 support 규칙을 위반해 보존한 채로는 어떤 후보도 통과할 수 없는 경우(즉시. 이때는 LLM 재생성을 시작하지 않음) |
| 제안 내용 | `differences`에서 `actual`이 있는 Brick을 현재 채택 Design 위치(`expected`)로 되돌리기. 임의의 새 위치는 제안하지 않음 |
| 질문 형태 | C(dialogue)가 만든 문장. 예: "지금 놓인 블록으로는 새 설계를 만들기 어렵습니다. B003을 원래 위치로 옮겨 주시겠어요? 1번 옮기기, 2번 계속 새 설계 찾기" |
| 동의 | 사용자의 명시적 동의이므로 `hri_result: KEEP_ORIGINAL`, 입력 Design 그대로 반환. D의 기존 흐름(사람 수정 → B 관측 → D Current 갱신)을 그대로 탐 |
| 거절 | 재설계를 계속하고 연속 거부 횟수를 0으로. 다시 6회 연속 거부되면 같은 질문. 단, `current`가 support를 위반한 경우에는 재설계할 수 없으므로 escalation 질문을 §4.3 규칙(재질문·무응답 취소)에 따라 반복. Revised 후보 생성은 `current`가 support를 만족할 때만 시작 |
| 불명확·무응답 | §4.3과 같음 (재질문, 300초 무응답이면 `CANCELLED`) |

Initial Design에는 고정 Brick이 없으므로 escalation이 없고 §8.10 전략 전환만 적용합니다.

## 9. 검증 책임

### 9.1 C (validator, LLM 없이 A / D / HMI 없이 단독 통과)

| 규칙 | 실패 시 |
|---|---|
| 필수 필드·타입, 허용되지 않은 키 없음(Robot·mm·TCP·joint 등 Robot field 유입 포함) | 거부 |
| `color`, `geometry`, `orientation_deg`(geometry별), `layer` 1~4 허용 값 | 거부 |
| footprint가 Board 0~23 안 | 거부 |
| `bricks` 1~20개, `block_id` Design 안에서 유일. Revised 후보의 기존 `block_id`는 입력 Design에 있는 ID여야 함 | 거부 |
| 같은 layer 안 footprint overlap 없음 | 거부 |
| support: layer ≥ 2인 Brick은 바로 아래 layer에 있는 Brick의 **개수와 무관하게**, 그 Brick들과 겹치는 stud 수를 **모두 더한 값**이 2 이상이면 통과. 합계가 0 또는 1이면 거부 (아래 Case A~D) | 거부 |
| connectivity: 위아래 layer stud 겹침으로 연결했을 때 전체가 하나 | 거부 |
| Revised: §8.3 조립된 Brick 보존 | 거부 |
| malformed LLM 출력(JSON 파싱 불가·형식 불일치) | 거부 |

거부는 후보 하나에 대한 판정이며 `[{rule, block_ids, message}]`로 반환해 재생성에 씁니다(§8.10).

support 예시 (layer ≥ 2인 Brick 하나 기준):

| Case | 바로 아래 layer와의 겹침 | 결과 |
|---|---|---|
| A | 아래 Brick 1개와 2 stud (또는 3·4 stud) | 통과 |
| B | 아래 Brick 2개와 각 1 stud, 합계 2 | 통과 |
| C | 아래 Brick 여러 개, 합계 2 이상 | 통과 |
| D | 합계 0 또는 1 | 거부 |

C validator와 A Plan validator는 이 문장을 그대로 같은 정의로 씁니다.

입력 검사(`INVALID_INPUT`):

- `design`이 §3과 §9.1 Design 규칙을 만족하지 않음
- `current`·`differences`의 Brick 값이 §2 범위·footprint 범위를 벗어남
- `current` Brick의 `block_id`가 없거나, 입력 `design`에 없는 ID이거나, `current` 안에서 중복됨
- `current` 자체가 같은 layer overlap을 위반함(같은 stud에 두 Brick은 물리적으로 불가능한 관측 오류). support 위반은 입력 오류가 아닙니다: 사람이 아래 layer와 1 stud만 겹치게 놓는 것은 실제로 가능한 상태이므로 Intervention을 정상 진행하고, Revised 생성이면 §8.11로 바로 갑니다. connectivity도 검사하지 않습니다. 조립 중인 Current는 다리 두 개처럼 떨어진 덩어리일 수 있고, Revised Design이 Brick을 더해 연결합니다.
- `differences`가 빈 배열

### 9.2 A·D (참고, C가 대신하지 않음)

| 담당 | 검증 |
|---|---|
| A (세은) | Plan / Step의 bounds·공간 중복·support / 체결·dependency·지원 종류 검증과 invalid 사유(00 D04·D10) |
| D (수현) | Observed 검증·Current 채택, Expected / Current 비교·Difference 판정, Design·Plan 채택과 최신성 |

## 10. 오류·실패 계약 (Recovery First)

| 구분 | 상황 | C 동작 | 반환 |
|---|---|---|---|
| 복구 | 후보 거부, malformed LLM 출력, hard constraint 위반 | §8.10 재생성 | 반환하지 않고 계속 |
| 복구 | 일시적 LLM 호출 실패 | backoff 재시도 | 반환하지 않고 계속 |
| 복구 | 일시적 녹음·STT·TTS 실패 | backoff 재시도 | 반환하지 않고 계속 |
| 복구 | 불명확 응답 | 재질문 | 반환하지 않고 계속 (텍스트 모드 소진 시만 `UNCLEAR`) |
| 취소 | 사용자 무응답 300초 (§4.3) | 최종 안내 후 종료 | `CANCELLED` / `NO_RESPONSE` |
| 복구 | `current`의 support 위반 | Intervention 정상 진행, Revised 생성이면 즉시 §8.11 escalation | 반환하지 않고 계속 |
| 실패 | 호출자 입력 오류 (`current` overlap 위반 포함, support 위반은 제외) | 즉시 반환 | `FAILED` / `INVALID_INPUT`, `UNSUPPORTED_OBJECT` |
| 실패 | 시스템 장애: 같은 외부 서비스(LLM 또는 음성 장치·엔진)가 재시도에도 300초 동안 계속 실패 | 반환 | `FAILED` / `LLM_CALL_FAILED`, `VOICE_IO_FAILED` |

| `error.code` | 의미 | 함수 |
|---|---|---|
| `UNSUPPORTED_OBJECT` | 목표 문장에서 지원 사물을 찾지 못함 | create_initial_design |
| `INVALID_INPUT` | `text` 타입 오류, `design` / `current` / `differences` 형식·범위·§9.1 입력 검사 위반 | 둘 다 |
| `NO_RESPONSE` | 음성 모드 사용자 무응답 취소 사유 (`CANCELLED`와 함께) | run_intervention |
| `VOICE_IO_FAILED` | 녹음·STT·TTS 실패. 평소에는 로그·재시도 사유이고, 시스템 장애 기준을 넘을 때만 `FAILED`와 함께 반환 | 둘 다 |
| `LLM_CALL_FAILED` | LLM API 호출 실패. 평소에는 로그·재시도 사유이고, 시스템 장애 기준을 넘을 때만 `FAILED`와 함께 반환 | 둘 다 |

- 시스템 장애 기준: 서비스별로 마지막 성공 이후 연속 실패 시간을 재고, 성공하면 0으로 되돌립니다. 300초는 `main` 모듈 상수입니다. 이 시간은 §4.3 침묵 시간과 별개입니다.
- KPI 정상 시연 경로에서는 `FAILED` 시스템 장애 경로가 발생하지 않는 것이 목표입니다.
- `details`: 사유 문자열 배열(입력 검사 위반 목록, 무응답 시 경과 시간·질문 횟수, 장애 시 마지막 오류 등).
- 불명확 응답은 실패가 아닙니다(§6).
- 00 E04 "자동 재시도 없이 보류"는 Robot 전달 복구 범위이며 C의 LLM·음성 재시도와 무관합니다.
- `INVALID_INPUT`은 참고 인터페이스 정책의 기존 코드 이름을 그대로 씁니다. 참고 정책의 `TIMEOUT`은 Robot·통신용이므로 무응답에 재사용하지 않습니다. 나머지는 공용 문서에 오류 코드 목록이 없어 C가 정의합니다.

## 11. 연결 담당 확인 항목

| 항목 | C 제안 | 확인 |
|---|---|---|
| Difference 입력 필드 `expected` / `actual` | §5.2 | D (수현) |
| Current·Difference Brick에 Design `block_id` 포함 (실제 위치 값과 함께) | §5.1 | D (수현) |
| `on_question` 콜백으로 HMI 화면 표시 | §4.2 | D (수현) |
| `status: CANCELLED`(`NO_RESPONSE`) 수신 후 Workflow 취소·정리, `FAILED` 시스템 장애 수신 후 보류 | §4.3, §10 | D (수현) |
| Escalation 동의 시 `KEEP_ORIGINAL` 반환을 기존 Original 유지 흐름으로 처리 | §8.11 | D (수현) |
| Plan Step이 `block_id` + `design_version`으로 Brick 참조, 미조립 Brick ID 연속성 불필요 (C는 유지하지만 A는 의존하지 않음) | §7, §8.4 | A (세은) |
| support 정의 "아래 Brick 개수와 무관하게 겹침 합계 2 stud 이상"(Case A~D)·overlap 정의를 A Plan 검증에 그대로 사용 (기존 1 stud에서 변경) | §9.1 | A (세은) |

## 12. 이 계약에서 정하지 않는 것

- 진행 중인 Intervention의 취소(STOP 버튼 등): D Workflow 정책이며 이번 계약은 인터페이스를 추가하지 않습니다. 무응답 취소는 §4.3을 따릅니다.
- 임의의 새 위치로 옮기기를 제안하는 escalation: 새 HRI 결과와 D Workflow 변경이 필요하므로 이번 계약에 넣지 않습니다(§8.11은 채택 Design 위치로 되돌리기만 제안).
- 질문 템플릿, 응답 규칙, LLM 프롬프트: WAVE 2 이후.
- Job·질문 ID·최신성 envelope: D가 통합에서 연결(06 식별·최신성 제안).
- C는 Board 좌표 규약(§2)만 사용합니다. Board의 물리 방향과 Board → Robot / world 변환은 D 책임입니다.
