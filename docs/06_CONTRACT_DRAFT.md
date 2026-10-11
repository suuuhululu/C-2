# Day4 공통 인터페이스 계약

> 2026-10-11 수현 확인: 최신 1차 통합의 상태 소유·검사 결과·C 확정 흐름은 [10/8 계약](handover/final_mvp_interface_20261008/README.md)을 우선합니다. B가 Current·revision·Expected·비교를 확정하고 D가 실행·진행·최종 종료를 담당합니다. 여섯 배치 필드·24×24·정수 layer 1~5는 유지합니다. 아래 §1~9의 Observed→D 채택 경로는 기존 Day4 구현이며 B 소유 경로와 동시에 적용하지 않습니다.

> 2026-10-11 1차 통합 기준: 공통 배치와 관측 영역의 `layer`는 정수 1~5입니다. 현재 코드·Schema·문서와 별도 작업 브랜치의 차이는 [1차 통합 인터페이스 점검](11_ROUND1_INTERFACE_AUDIT.md)에 기록합니다. 아래 JSON 예시는 설명용이며 실제 구조 검사는 `interfaces/schemas/day4.schema.json`과 Consumer를 함께 확인합니다.

## 0. 최종 MVP 이행 범위 (2026-10-07)

현재 제품 목표는 [최종 MVP](10_FINAL_MVP.md)입니다. **이하 §1~9는 기존 전달형 Day4 구현의 계약·예시**로 보존합니다. ‘현재/확정/제외’ 표현도 그 구현 범위에 적용합니다. 제품 목표의 변경이 기존 Schema·함수·ROS Action·실행 명령을 자동 변경하지 않습니다.

| 경계 | 최종 목표의 논리 입력 → 출력 | 기존 계약과의 차이 / 아직 합의할 내용 |
|---|---|---|
| 사용자/LLM → 계획 | 대화 요구·사용자 확정 Design → 조립 순서와 경로 생성 | 최초 키워드 수신과 확정 이벤트 분리; 경로 생산자/필드·실패 반환 미확정 |
| 계획 → Backend/HMI | 채택할 Design·순서·경로·기준 상태 → 실행 준비·미리보기·현재 Step | 현재 Plan은 조립 순서이며 직접 결착 MotionPlan 인계·유효성 검사가 필요 |
| Backend → Robot | 유효 Step·블록·공급/조립 목표와 경로·지원 준비 → 집기·직접 결착과 실행/접촉 결과 | §7의 종류/색상 전달 goal만으로 직접 결착을 명령할 수 없음; grid/robot 변환·제어권 합의 필요 |
| 지원 → 사람 → Backend | LOW/HIGH·대상/영역/방향·활성 요청 → 긍정/부정/미확정 응답 | 엄지척/엄지+검지·HMI 보조 입력, 실행 전 알림과 지지 유지 가정; 응답 품질·ID 대응 초안 |
| Vision → Backend | Step/최종 완성상태 확인 문맥 → 실제 관측·검증 근거 | 기존 OK는 판별 가능이고 MATCH가 아님; 연구 PASS/FAIL/UNKNOWN 매핑과 최종 요청 형식 미확정 |
| Backend → DB → 웹앱 | 사용자와 Job·현재 채택 Design·조립 기록/판정 → 저장 결과·사용자별 조회/반영 | 현재 users와 jobs 소유자 미연결; 소유자·세션·권한·저장/반영 실패와 중복 처리 계약 필요 |

종료는 1) 해당 계획에 필요한 블록 모두 사용, 2) Vision 확인과 Backend 최종 조립 판정·종료, 3) 사용자별 DB 저장·웹앱 반영으로 구분합니다. 마지막 Robot result나 JSONL 쓰기만으로 세 단계 완료를 처리하지 않습니다. 최종 Vision이 불확실하면 조립 종료를 보류하고, 저장/반영 실패는 실제 조립을 재실행시키지 않습니다.

[첨부 연구](suhyun_individual_research_topic.md)의 지지 프로토콜은 반영하되 run_id/brick_id/plan_version·새 상태명·ROS 타입·F/T 임계값은 논리 초안입니다. 기존 여섯 필드·ID에 임의로 강제하지 않습니다. 두 stud 기하 지지 검사는 LOW/HIGH·접촉 결착 판정의 대체물이 아닙니다. Qt/웹 분담도 아직 확정하지 않습니다.

## 기존 Day4 계약·예시

> 2026-10-06 보완: C/B DM 이후 확정 내용과 연결 책임은 [C·B Backend 연결 합의](09_C_B_BACKEND_HANDOFF.md)를 함께 확인합니다. block_id 필수 제외·5분 자동 취소 제외·유한 후보 재생성·촬영 순서·확인 영역·전달판 미확인을 명확히 했습니다. 지지 기준은 2026-10-06 세은의 동의와 수현의 회신에 따라 A/C가 바로 아래층과 겹치는 고유 stud 총 2개 이상으로 통일했습니다. 이는 Day4 기하 검사 기준이며 물리 안정성 검증이 아닙니다. 관측 묶음 순번 범위는 해당 연결 문서의 확인 상태를 따릅니다.


갱신: 2026-10-05. 파일명은 기존 링크를 위해 유지합니다. 아래는 기존 Day4에서 사용자가 채택한 설계 계약입니다. **JSON 예시는 계약 설명용이며 실행 가능한 Schema·ROS msg·실제 Camera 출력은 아닙니다.** 홍동 검토 가능 제안과 구현 시 정할 연결 세부는 별도 표시합니다. 책임·이행은 [팀 가이드](02_TEAM_GUIDE.md), 구현 증거는 [STATUS](STATUS.md)를 봅니다.

## 1 공통 블록과 좌표

| 객체 | 확정된 의미 / Owner | 확인할 필드·표현 |
|---|---|---|
| Block | 블록 종류·색상·위치·층·방향 | 아래 여섯 배치 필드와 개수로 비교. 공급 slot과 구분하며 `block_id`를 공통 필수값으로 넣지 않음. 지지는 바로 아래층과 겹치는 고유 stud 총 2개 이상 |
| Design | 목표 배치·Initial / Revised·시율 | `design_version, blocks` 두 필드. 버전은 C가 발급하고 D가 채택. `parent_version`·출처·진단은 공통 Design 본문에 넣지 않음 |
| Observed | 촬영 당시 실제 관측·홍동 | 관측 ID / 순번·촬영 시각·보정·가림 / 실패 / 완전 관측·항목별 confidence |
| Current | 유효 관측 채택·Backend | 채택 관측·상태 revision·블록 상태·유효성 |
| Plan | 기준 Design / Current·세은 | Plan 버전·기준 상태 revision·Step 목록·검증 / 사유 |
| Step | 사람 조립 작업·세은 | 블록 목표·동작·선행조건·효과·Robot 전달 필요 여부 |
| Expected | 기준 상태 + 해당 Plan 효과·Backend | 기준 Design / Plan·비교 Step·목표 배치 |
| Difference | 일치 / 차이 / 판단 불가·Backend | 대상·항목·기대 / 실제·품질·근거 |
| HRI | 유지 / 수정 / 불명확·시율 | 질문·응답 연결·기준 Design / Current·결과 Design / 재질문. 질문 문장은 C가 생성. 무응답은 입력 대기이며 자동 취소·자동 KEEP 없음. 명시 취소·STOP은 C의 CANCELLED 반환과 구분 |
| Delivery | 종류·색상 요청·Robot | 실행 식별·수락 / 진행 / 최종 결과·슬롯·실패·취소 완료 |
모든 배치는 `brick_type, color, x, y, layer, orientation_deg` 여섯 값으로 표현합니다.

| 필드 | 계약 |
|---|---|
| brick_type | `2x2x1` 또는 `2x3x1` |
| color | `yellow` 또는 `blue` |
| x, y | 정수 0~23, stud 단위. 블록 footprint의 최소 x / y 모서리 |
| layer | 정수 1~5(2026-10-07 공통 지원 확대). 1층이 판 위 첫 층 |
| orientation_deg | 6점: 0 또는 90. 4점 정사각형은 대표값 0 |

사용자 사진의 원점은 (0,0), +X 오른쪽, +Y 위입니다. 6점 0도는 X폭 2 / Y길이 3, 90도는 X폭 3 / Y길이 2입니다. long_axis는 사용하지 않습니다. 조립판 각도와 gripper 자세는 별개입니다.

좌표 필드가 0~23이어도 footprint 전체가 판 안에 있어야 합니다. 예: 6점 0도 x=23은 범위 초과이며 세은이 재검사합니다. 목표 layer=6 이상은 시율에게 재설계를 요청합니다. 임의로 x=22 / layer=5로 고치지 않습니다. Plan 검증은 전체 footprint·중복·지지·선행 관계를 포함합니다.

## 2 Design과 정상 Plan

Design은 `design_version, blocks`이며 최종 목표 **전체** 배치를 담습니다. C 생성 상한은 1~30블록이며 A/D/Qt는 30블록을 동일 계약으로 수신·계획·표시합니다. Consumer에 새 수량 제한은 추가하지 않습니다. REAL 수동 시험의 24개 공급 슬롯 제한은 별도 실행 범위로 유지합니다. 별도 design_id는 필요하지 않습니다. Revised도 동일 형식이며 이미 조립한 목표 블록을 포함합니다.

```json
{
  "design_version": 1,
  "blocks": [
    {"brick_type":"2x2x1","color":"yellow","x":3,"y":5,"layer":1,"orientation_deg":0},
    {"brick_type":"2x2x1","color":"yellow","x":5,"y":5,"layer":1,"orientation_deg":0},
    {"brick_type":"2x3x1","color":"blue","x":3,"y":5,"layer":2,"orientation_deg":90}
  ]
}
```

Plan은 `plan_id, design_version, base_current_revision, steps`입니다. 한 번에 Step 하나를 배열 순서로 처리하며 prerequisites는 같은 Plan의 step_id를 참조합니다.

```json
{
  "plan_id":"P01","design_version":1,"base_current_revision":0,
  "steps":[
    {"step_id":"S01","operation":"PLACE","before":null,
     "after":{"brick_type":"2x2x1","color":"yellow","x":3,"y":5,"layer":1,"orientation_deg":0},
     "prerequisites":[],"requires_delivery":true},
    {"step_id":"S02","operation":"PLACE","before":null,
     "after":{"brick_type":"2x2x1","color":"yellow","x":5,"y":5,"layer":1,"orientation_deg":0},
     "prerequisites":[],"requires_delivery":true},
    {"step_id":"S03","operation":"PLACE","before":null,
     "after":{"brick_type":"2x3x1","color":"blue","x":3,"y":5,"layer":2,"orientation_deg":90},
     "prerequisites":["S01","S02"],"requires_delivery":true}
  ]
}
```

before / after는 한 Step의 전후 효과입니다. 두 개의 블록을 뜻하지 않습니다. PLACE는 before=null, after=조립 목표, requires_delivery=true입니다. MOVE / REMOVE는 생성하지 않습니다. 선행 Step 종료는 관측으로 확인하며 Robot 전달 결과로 대신하지 않습니다.

## 3 관측 요청과 완료 확인

- Plan 실패는 검증 대상·위치·사유를 Backend로 반환하고 Design 수정 / 재질문 동안 전달 보류.
- LLM / STT 호출 실패와 사용자의 불명확한 응답을 구분. malformed / unsupported 출력은 실행 Design으로 채택하지 않는 방향을 확인. malformed LLM 출력·후보 거부는 시율 내부에서 재생성하며 Backend에 실패로 전달하지 않음. C 상세는 [C_DESIGN_CONTRACT.md](C_DESIGN_CONTRACT.md).
- 대화 중 Current가 바뀌면 질문 context와 최종 재계획의 기준 상태를 확인하고, 채택 전 최신 상태를 대조.
- Robot 오류·부분 완료 뒤 재개 시 실제 전달 여부·슬롯 소모·남은 동작을 사람이 확인하는 기록 / UI 결정.
- 공급 보충 신호·확인 주체와 pick 성공 / 실패별 슬롯 증가 조건 결정.
수현은 활성 `check_id`를 Job·Plan·Step·확인 대기에 연결해 보관하고 홍동에게 check_id와 해당 after를 전달합니다. 이는 대상 안내이며 즉시 촬영 명령이 아닙니다. 홍동이 완료 확인 시점을 정합니다.

반환은 `check_id, observation_seq, status, visible_blocks, verified_regions, reason`을 기준으로 합니다. 반복 callback의 순서 구분에는 촬영 순번 observation_seq를 사용하고 별도 observation_id를 추가하지 않습니다. 정확한 순번 제공 방식은 Vision 연결부에서 맞춥니다.

```json
{
  "check_id":"J01:C07","observation_seq":12,"status":"OK",
  "visible_blocks":[
    {"brick_type":"2x3x1","color":"blue","x":3,"y":5,"layer":2,"orientation_deg":90}
  ],
  "verified_regions":[{"x":3,"y":5,"width":3,"height":2,"layer":2}],
  "reason":null
}
```

J01 / C07은 설명용 작업 / 확인 요청 표기입니다. 실제 ID 문자열에는 이 형식을 강제하지 않습니다. S03의 두 지지 블록은 앞서 확인한 1층 Current에 남아 있으며 위 예시의 visible_blocks에 없다고 삭제하지 않습니다.

| 홍동의 완료 확인 결과 | 수현 처리 |
|---|---|
| OK + 실제 목표와 같은 배치 | Current 갱신·Step 한 번 완료 |
| OK + 색상·위치·층·각도 등이 다름 | 실제 Current 채택·Difference·의도 확인, 다음 전달 보류 |
| OK + 읽을 수 있는 목표 영역이 비어 있음 | 완료 확인 시점의 미배치 차이. 계속 정상 대기로 숨기지 않음 |
| UNOBSERVABLE + 사유 | 읽지 못한 영역의 Current 유지·완료 / 다음 전달 보류 |
| 이번 목표는 읽히고 이전 확인한 아래층만 가림 | 아래층 이력 유지·이번 목표 비교 가능 |

OK는 **이번 대상의 필요한 배치를 판단할 수 있음**을 뜻합니다. 일치라는 뜻이 아닙니다. 아직 완료 확인용 관측을 받기 전에는 WAITING입니다. visible_blocks는 실제 읽은 배치만 담고 Expected를 채워 넣지 않습니다.

### verified_regions와 Current 병합

각 영역은 `x, y, width, height, layer`이며 그 층의 점유 상태를 실제 판단한 범위입니다. 단순 카메라 시야가 아닙니다. 영역에 걸친 실제 블록은 경계 밖으로 뻗더라도 visible_blocks에 포함해야 합니다. 필요한 점유 정보를 읽지 못하면 확인한 영역으로 주장하지 않습니다.

- 새로 확인된 실제 배치를 Current에 반영합니다. 목표와 달라도 유효 관측을 거절하지 않습니다.
- 이전 배치가 가렸거나 목록에 없기만 하면 보존합니다. Day4는 가려진 동안 확인된 아래층이 유지된다고 가정합니다.
- 이전 블록의 같은 층 전체 footprint를 확인했고 해당 배치가 더는 존재하지 않는다는 증거가 있을 때 제거·교체합니다. 일부 영역만 확인한 것으로 삭제하지 않습니다.
- 이동인지 추가인지 불명확하면 실제 증거를 보관하고 추가 확인합니다. 해결 전 다음 전달·Replan 채택을 보류합니다. 영구 물리 블록 ID를 억지로 만들지 않습니다.
- 이미 완료한 블록의 실제 변경도 Current revision·Difference에 반영합니다. 과거 완료 이벤트는 남기되 현재 지지·선행 조건의 증거로 계속 사용하지 않습니다.

최종 완료는 누적 Current와 최종 채택 Design 및 확인된 Step을 대조합니다. 모든 층이 한 이미지에 동시에 보여야 하는 조건은 없습니다. 빈 Remaining Plan만으로 완료를 선언하지 않습니다.

## 4 최소 식별·버전·Expected

| 값 | Owner / 변화 조건 |
|---|---|
| job_id | Backend의 작업 경계·로그. 모든 핵심 함수의 필수 인자로 강제하지 않음 |
| design_version | 시율. 최초 1, 전체 목표 배치가 실제 바뀔 때 +1. KEEP / 배열 순서 변경만으로 증가하지 않음 |
| current_revision | Backend. 최초 0, 채택 실제 배치가 바뀔 때 +1. 사진 갱신·가림·전달 결과만으로 증가하지 않음 |
| plan_id | 세은. 새 Plan마다 고유 ID |
| base_current_revision | 계산에 사용한 입력 Current revision의 복사. 별도 카운터가 아님 |
| step_id | Plan 내부 고유 값, 선행·완료 대상 연결 |
| check_id / request_id / execution_id | 확인 / 질문 / 실행별 서로 다른 값. 공통 발급 방식 또는 transport가 제공하는 식별을 재사용 |

Design ID·Expected 버전·Difference ID·DB record ID·블록 영구 ID를 필수로 추가하지 않습니다. Plan 호출은 활성 함수 호출 문맥으로 연결할 수 있으면 별도 planning_request_id가 필요하지 않습니다.

새 Plan 채택은 활성 요청·현재 목표 버전·현재 Current revision과 일치하고 검증을 통과해야 합니다. 계산 중 r7→r8이 되면 r7 기준 결과를 채택하지 않습니다. 검증된 Design + Plan을 함께 채택하고 기준 Current를 고정합니다. **채택 후 정상 Step 진행으로 revision이 증가한 것은 기존 Plan 폐기 사유가 아닙니다.**

Expected는 고정한 기준 Current + 완료 Step + 현재 확인 Step의 효과로 계산합니다. 잘못 놓인 현재 배치를 매번 기준으로 삼아 목표를 덮어쓰지 않습니다. Robot 전달 성공을 조립 효과로 넣지 않습니다.

촬영할 때 check_id와 observation_seq를 고정합니다. 결과 도착 당시 Step을 뒤늦게 붙이지 않습니다. STOP·Plan 교체·Step 이동 시 이전 check를 닫고, 같은 Step 확인을 다시 열어도 새 check를 사용합니다. 닫힌 check·중복 / 역순 관측·옛 질문 / 실행 결과는 현재 진행에 반영하지 않습니다. 실제 부분 실행 사실은 Controller 확인·슬롯·로그에 보존합니다.

## 5 Difference와 사람 의도

차이는 사람이 원한 변경인지 확인할 대상입니다. 무조건 고쳐야 하는 ‘오배치’로 표시하지 않습니다. Backend는 다음 전달을 보류하고 당시 Design·Current·Difference·지원 범위를 시율에게 전달합니다. 질문은 시율이 만들고 같은 문장을 화면·음성으로 제공합니다. 질문 하나만 활성화합니다.

| 결과 | 의미 / 처리 |
|---|---|
| KEEP | 현재 채택 목표·design_version 유지. 최신 Current로 재계획 |
| REVISE | 사람의 변경 의도를 반영한 전체 Design 후보. 검증된 Design + Plan 채택 후 진행 |
| UNCLEAR | 구체적인 선택지·권장 원래 목표를 설명해 재질문. 계속 불명확하면 명시적 선택 대기 |

질문·응답은 request_id와 당시 목표 버전·Current revision에 연결합니다. Current가 달라졌거나 닫힌 질문의 응답이면 그대로 채택하지 않습니다. 후속 질문은 새 요청 식별을 사용합니다. 무한 LLM 재질문·시간 경과에 따른 자동 KEEP·임의 종료는 하지 않습니다.

LLM / STT 호출 오류·malformed 출력은 UNCLEAR와 다릅니다. 유효 의도와 Plan을 받으면 추가 HMI 확인 없이 진행합니다. LLM이 사용자의 의도 없이 목표를 능동 변경하는 기능은 후속 과제입니다.

## 6 Remaining과 Replan

세은 입력은 전체 채택 Design(또는 시율의 Revised 후보), 최신 Current 배치·revision, Day4 제약입니다. 목표에 이미 맞는 실제 배치는 Remaining에서 제외합니다. 결과 분기는 아래 의미를 사용하며 정확한 함수명·실패 envelope 세부는 연결 구현에서 맞춥니다.

| 결과 | 반환 / 처리 |
|---|---|
| READY | 검증된 정상 Plan. Steps는 PLACE만 포함 |
| NEEDS_CORRECTION | 사유·충돌 배치. 실행 Plan 없음. KEEP 목표를 PLACE만으로 달성할 수 없으면 사람 정리 안내 |
| INVALID | 실패 대상·사유. 범위 오류는 세은 재검사, 목표 층 초과 등은 시율 재설계 |

실패를 성공 + steps=[]로 반환하지 않습니다. 사람 정리 후 ‘계속’ 입력은 새 관측 시작 신호이며 Current·Step 완료를 직접 확정하지 않습니다. 최신 실제 배치를 다시 확인해 재계획합니다. 잘못 놓은 블록만 치웠으면 원래 PLACE는 남고, 목표대로 사람이 이미 수정했다면 그 배치는 Remaining에서 제외합니다. REVISE로 실제 배치를 받아들인 경우도 전체 목표의 기하·지지를 검증합니다. 재계획으로 공급 슬롯을 초기화하지 않습니다.

## 7 Robot·공급·관측 위치·STOP

정상 goal 최소값은 execution_id·brick_type·color입니다. Backend가 Job / Plan / Step 문맥을 연결하고 Controller가 실제 공급 슬롯과 사전 검증된 전달 경로를 선택합니다.

```json
{"execution_id":"E01","brick_type":"2x3x1","color":"blue"}
```

```json
{"execution_id":"E01","success":true,"reason":null}
```

Action 수락·feedback·단일 gripper 동작을 전달 완료로 해석하지 않습니다. 정상 완료는 검증한 집기·전달·observe point 복귀 흐름의 완료입니다. 동시에 실행 하나만 유지하고 동일 요청·중복 result로 재집기하지 않습니다. 실제 Action 이름 / 타입 / cancel·중단 후 연결 방식은 Controller adapter와 장치 시험에서 정합니다.

공급열은 yellow 4 / blue 4 / yellow 6 / blue 6 각각 슬롯 1~6입니다. 채워진 공급판으로 새 Job을 시작하면 모두 1부터입니다. **실제 pick 성공 확인 시 한 번 소모**하며 요청 발행·중복 결과·실패만으로 증가시키지 않습니다. 마지막 슬롯을 집으면 해당 열 보충 완료 입력 후 그 열만 1로 초기화합니다. STOP·재개·재계획으로 기존 소모를 초기화하지 않습니다.

### observe point와 전달판 제안

카메라는 로봇팔에 달려 있고 observe point가 있으며 전달판도 보입니다. 이동 중 완료 확인을 닫고, 복귀·정지 후 새 check로 촬영 대상을 연결합니다. 모션 중 프레임·이전 전달 전 EMPTY를 새 완료·비움 증거로 재사용하지 않습니다.

다음 전달에는 현재 Step 확인·새 전달판 비움 확인·활성 실행 없음·정지 / 오류 없음이 필요합니다. 정상 매 Step마다 사람이 비움·완료 버튼을 누르지 않습니다. Step을 확인했지만 전달판이 차 있거나 보이지 않으면 다음 전달만 보류하고 자동 관측을 이어갑니다.

**홍동이 수정 가능한 제안:** 전달판 상태 `place_status=EMPTY / OCCUPIED / UNOBSERVABLE`, observe point 시야·정지 후 촬영 타이밍·판별 방식. 조립 관측 OK / UNOBSERVABLE과 전달판 상태는 별개입니다. 아직 없거나 판별 대기인 값은 null / 대기로 표시하고 EMPTY로 추정하지 않습니다. 프레임 수·대기 시간·보정값을 여기서 임의 확정하지 않습니다.

### 정지 후 재개

STOP은 다음 전달을 보류하고 활성 관측 / 질문을 닫습니다. Job·Design·Current·완료 이력·공급 소모는 유지합니다. UI 재개 요청 이후 실제 Controller가 다음 세 방향으로 처리합니다.

| 실제 중단 시점 | 재개 방향 |
|---|---|
| 아직 집지 않음 | 같은 Step / 공급 슬롯에 새 execution_id로 Action goal 재전송. 이전 실행 종료·실제 정지 확인 후 발행 |
| 블록을 들고 있음 | 다시 집지 않고 전달판에 놓은 뒤 observe point 복귀 |
| 전달판에 이미 놓음 | 다시 집기 / 놓기 없이 observe point 복귀 |

Controller 내부 실행 기록으로 처리하고 새 delivery_state enum·HMI 체크박스를 필수로 만들지 않습니다. 복귀 후 새 관측으로 조립 완료를 판단합니다. 실제 상태가 불명확하면 사유를 표시하고 보류하며 무조건 goal을 재전송하지 않습니다.

Robot 실패·timeout은 정상 STOP 재개와 구분합니다. 자동 재시도 / home / gripper 복구는 제외하며 정리 후 새 Job을 시작하는 최소 처리 방향을 사용합니다. 실패 결과·timeout 자체는 실제 정지 증거가 아닙니다. 새 Job은 조립판·전달판 비움, 공급 보충, Controller 준비를 확인한 뒤 새 ID / Current / 완료 기록 / 슬롯을 초기화합니다. 기존 로그는 보존합니다. 종료 후 상태 복원은 구현하지 않습니다.

## 8 Qt 한 화면 계약

Qt 단일 창에서 운영자가 필수 상태를 모두 봅니다. 탭·페이지 전환·스크롤이 필요하지 않게 배치합니다. 화면 가로폭 절반, 크기 고정·최대화 / 크기 변경 금지, 이동·최소화 허용입니다. 1920×1080 화면의 예시는 960×900이며 창 장식·DPI를 포함해 실제 시작 크기를 조정합니다. 옆 절반에는 터미널을 둘 수 있습니다.

| 화면 구역 | 내용 |
|---|---|
| 상단 | 공정 상태·현재 Plan 완료 / 전체 Step·시작 / 정지 / 재개 |
| 왼쪽 | 전체 채택 Design 미리보기, 현재 Step 목표·실제 관측·비교 |
| 오른쪽 | Robot·관측·전달판 상태·공급열별 다음 슬롯 / 보충 필요 |
| 하단 | 질문·보류 / 오류 사유·필요한 행동과 예외 입력 |

Backend 상태 변경 시 최신 snapshot 전체를 한 묶음으로 보내고 Qt가 함께 갱신합니다. 로봇·카메라 대기 중에도 UI 입력이 반응해야 합니다. Qt는 완료·Current·공급 슬롯을 직접 계산하거나 Robot에 직접 명령하지 않습니다.

| 묶음 | 표시 값 |
|---|---|
| workflow_status | 공정 상태. WAIT_ASSEMBLY는 전달 / observe point 복귀 후 사람 조립 완료 확인 대기 |
| step | 목표 target, 실제 observed, comparison=WAITING / MATCH / MISMATCH / UNOBSERVABLE |
| progress | 현재 채택 Plan의 completed / total. 재계획 후 전체 Design 달성률로 해석하지 않음 |
| monitor | Robot·관측·전달판 상태, next_supply_slot |
| notice | 질문 / 사유 / 필요한 행동 |
| actions | 시작 / 정지 / 재개와 예외 입력 표시·활성 |
| design | 전체 미리보기용 채택 Design의 design_version / blocks |

기존 여섯 묶음은 유지하고 **전체 미리보기에 필요한 최소 추가 표시 데이터 design**을 붙입니다. 새로운 Design ID·이미지 생성 API를 만들지 않고 기존 Design 객체를 재사용합니다. 상세 snapshot Schema·Qt 바인딩은 구현할 때 이 의미로 맞춥니다.

전체 미리보기는 사용자가 포함하도록 결정했습니다. 검증되어 Backend가 채택한 blocks를 층별 도식 또는 간단한 투영도로 그립니다. 수정 후보를 확정 목표처럼 보여주지 않고 Design + Plan 채택 후 갱신합니다. 현재 Step 안내와 함께 같은 화면에 두며 완료 판정 근거로 쓰지 않습니다.

WAIT_ASSEMBLY는 공정 상태이며 프레임이 현재 판별 가능하거나 목표와 일치한다는 뜻이 아닙니다. WAITING은 아직 완료 판정용 관측을 기다리는 비교 상태입니다. 판단 불가를 WAITING으로 숨기지 않습니다. observed=null은 아직 반환 / 판별 대기이며 ‘빈 배치 확인’을 뜻하지 않습니다.

| 화면 상태 | 시작 | 정지 | 재개 |
|---|---|---|---|
| 시작 전 | 활성 | 비활성 | 비활성 |
| 진행 중 | 비활성 | 활성 | 비활성 |
| 정지 후 | 비활성 | 비활성 | 활성 |
| 완료 | 활성 | 비활성 | 비활성 |

버튼 활성 조건에 관측·전달판·상세 Robot 상태 제한을 추가하지 않습니다. Backend와 Controller가 요청을 처리하고 실제 실행 조건·보류 사유를 관리합니다. 정상 Step 완료 / 전달판 비움 수동 버튼은 없습니다. 의도는 음성 입력이 기본이고 계속 불명확할 때만 목표 유지 / 변경 선택을 표시합니다. 사람 정리 후 계속·해당 공급열 보충 완료는 필요할 때만 표시합니다. 입력은 현재 질문 요청 또는 해당 공급열에 연결합니다.

## 9 실패 처리와 파일 로그

Backend가 공정 보류·표시·다음 요청을 관리합니다. UNOBSERVABLE은 읽지 못한 Current 유지·추가 관측, 읽을 수 있는 실제 차이는 Current 채택·HRI, UNCLEAR는 재질문 / 명시 선택 대기, PLACE로 불가능한 KEEP은 사람 정리·재관측입니다. 호출 실패 / Robot 오류는 사유와 보류를 반환하고 정상값·사용자 불명확 응답으로 바꾸지 않습니다. 늦은 결과는 진행에서 제외하고 필요한 실제 사실을 로그에 남깁니다.

Job별 JSONL 파일 하나에 timestamp·job_id·관련 plan_id / step_id / request_id·event·result·reason을 누적합니다. 해당하지 않는 식별은 null로 둡니다. 정확한 경로·영문 이벤트 / 오류 코드명은 구현에서 정합니다.

주요 이벤트는 새 Job, Current 채택, Step 확인, Design / Plan 채택·변경, 전달 요청 / 결과, 질문 / 응답, STOP / 재개 / 작업 중단, 지연 결과 제외입니다. 동일 UNOBSERVABLE 프레임마다 쌓지 않고 의미 있는 상태 진입·변화만 기록합니다. 매 영상 프레임·이미지·비밀 키는 저장하지 않습니다. HMI는 현재 상태·사유를 표시하고 상세 로그는 선택 표시입니다. DB 누적·앱 종료 후 자동 복원은 필요하지 않습니다.
