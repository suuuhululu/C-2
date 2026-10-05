# C Design 구조

> 2026-10-05 계약 갱신: 아래는 기존 C 구조·작업 기록입니다. 공통 반환은 [06_CONTRACT_DRAFT.md](06_CONTRACT_DRAFT.md)의 brick_type / color / x / y / layer / orientation_deg, Design 버전, KEEP / REVISE / UNCLEAR를 따릅니다. 기존 geometry / grid_x / grid_y / 대문자 색상·KEEP_TARGET / KEEP_CURRENT의 이행은 [02_TEAM_GUIDE.md](02_TEAM_GUIDE.md)에 정리했습니다. 계속 불명확한 응답은 명시 선택 대기로 처리하며 자동 재질문 반복을 강제하지 않습니다. 코드 변경·진행률 갱신·C 계약 시험 통과를 의미하지 않습니다.


C 파트(담당: 시율, **Voice Interaction + LLM Design**)의 예정 구조와 파일 책임입니다. 팀장 승인 구조이며 **실제 기능은 아직 구현되지 않았습니다.** 진행 상황은 [C_DESIGN_PROGRESS.md](C_DESIGN_PROGRESS.md)를 봅니다.

## 1. C 역할

C = Voice Interaction + LLM Design.

**Voice Interaction**

- 최초 사용자 음성 입력: 녹음, STT, 최초 목표 해석
- deviation context 해석, 어떤 질문을 할지 결정, 질문 문장 생성
- TTS로 질문 재생, 사용자 음성 수집(녹음), STT
- Intent Parsing: 응답을 KEEP_TARGET / KEEP_CURRENT / UNCLEAR로 판단
- 불명확한 응답 재질문

**LLM Design**

- Initial Target Design 생성과 Design Validation
- KEEP_CURRENT 시 Modified Target Design 생성과 Modified Design Validation
- 최종 Decision / Design 결과 반환

### 의도값

| 의도값 | 의미 |
|---|---|
| KEEP_TARGET | 최초 v1 복귀가 아니라 **현재 채택된 Target Design**(예: v3)을 계속 따름. 선택했다고 물리 수정 완료를 뜻하지 않음. 이후 사람 수정 → B 관측 → D Current 갱신 → Expected 확인 |
| KEEP_CURRENT | D가 준 Current의 실제 배치를 보존한 Modified Target 생성. 예: Target (5, 5) / Current (6, 5) → Modified Target (6, 5). 보존 대상은 Python이 Current 기준으로 결정하고, LLM이 보존 대상을 바꾸면 validator가 거부 |
| UNCLEAR | 응답을 판단할 수 없음. C가 재질문 |

순차 조립 전제: A가 다음 블록 결정 → D가 M0609로 1개 전달 → 사람 조립 → B / D 확인. C는 동일 블록 간 Data Association을 하지 않습니다.

## 2. C가 하지 않는 것

| 하지 않는 것 | 담당 |
|---|---|
| 카메라 관측, Vision, Observed 생성, 관측 품질·신뢰도·오류 | B (홍동) |
| 사람 조립 순서, 필요한 블록 종류·색상, NextPart, 남은 작업, Replan | A (세은) |
| Observed 검증·Current 채택, Expected / Current 비교, deviation 감지·판단 | D (수현) |
| M0609 블록 전달 정지·재개, 공급 슬롯, Robot mm 좌표, Board→Robot 변환, TCP / Joint / trajectory, Robot Control | D (수현) |
| Backend Workflow 진행, 전체 HMI 화면 구현 | D (수현) |
| 화면 표시 | HMI(D). **질문 문장·재질문·음성은 C** |

D는 Target Design / Current State / deviation context를 C에 전달하고 C 결과를 받아 Workflow를 진행합니다. **D는 질문 문장을 만들지 않고 C에게 읽을 문자열을 주지 않습니다.** 질문 생성부터 음성 대화까지 전부 C 책임입니다.

LLM이 Robot 좌표·joint·TCP·속도·힘·trajectory를 생성하지 않습니다.

## 3. Package tree

```text
app/
└── c_design/
    ├── __init__.py    # 패키지 표시만, 내용 없음
    ├── main.py        # 다른 파트가 호출하는 공개 진입점, 최초 목표·deviation 대화 흐름 연결
    ├── voice.py       # 모든 음성 I/O: 녹음·STT·TTS 재생
    ├── dialogue.py    # 순수 텍스트: 질문·재질문 문장 생성, 응답 의도 해석, 목표 사물 인식
    ├── llm.py         # LLM API 호출과 구조화(JSON) 응답 파싱 전용
    ├── designer.py    # Initial / Modified Target Design 생성
    └── validator.py   # Target Design 규칙 기반 독립 검증
```

production `.py`는 위 6개로 유지합니다. class·state machine·dialogue / conversation manager·service layer·framework를 추가하지 않습니다.

## 4. Test tree (예정)

```text
tests/
├── unit/
│   └── c_design/
│       ├── test_dialogue.py    # 질문 문장·응답 해석 규칙·UNCLEAR
│       ├── test_validator.py   # 규칙별 정상 / invalid
│       ├── test_designer.py    # Mock Initial / Modified, preserved
│       └── test_main.py        # 대화 루프(fake voice)
└── integration/
    └── test_c_contract.py      # A / D 연결 계약
```

테스트 파일은 기능 구현과 함께 하나씩 추가합니다. 지금은 `.gitkeep`만 있습니다. `voice.py`는 unit test 대상이 아니라 후반 L2 장치 시험 대상이며, 다른 테스트에서는 fake로 교체합니다. 실행할 테스트가 없는 상태를 PASS로 표시하지 않습니다.

## 5. 파일 설명

| 파일 | 한 줄 설명 | 앞으로 들어갈 것 | 넣지 않는 것 |
|---|---|---|---|
| `main.py` | 공개 진입점 | 최초 목표 흐름, deviation 대화 흐름과 재질문 루프(기본 횟수 제한 없음, F04), 텍스트 입력 모드 | 음성 I/O·질문 문장·응답 규칙·LLM·검증 로직 직접 구현 |
| `voice.py` | 음성 I/O | 녹음(record), STT, TTS 재생(speak), 재생 종료 후 녹음 시작(F05·F07) | 의미 판단, 질문 문장 생성 |
| `dialogue.py` | 대화 텍스트 처리 | 질문·재질문 문장, 선택지 상수(1번 KEEP_TARGET / 2번 KEEP_CURRENT), 응답 해석(Rule → LLM fallback → UNCLEAR), 목표 사물 인식 | 음성 I/O, 대화 루프 |
| `llm.py` | LLM 호출 전용 | API 호출, JSON 파싱, 실패 예외 | 프롬프트 구성, 검증, 재시도 정책, import 시 secret loading |
| `designer.py` | Target Design 생성 | Initial / Modified 생성, 보존 대상 Python 결정, 검증 실패 재요청, 식별·버전 결정 | 조립 순서, NextPart, Robot 좌표 |
| `validator.py` | Target Design 검증 | color, geometry, grid_x / grid_y, orientation_deg, layer 1~4, Board 범위, overlap, support, connectivity, Current 보존, malformed, Robot field 유입 거부 | LLM 호출, Plan 검증 |

### 공통 LEGO / Board 규약 (Day 4 MVP)

| 항목 | 값 |
|---|---|
| color | YELLOW, BLUE |
| geometry | 2x2x1, 2x3x1 |
| Board | 24 × 24 stud |
| grid_x, grid_y | 0~23, Board의 stud 위치 (Robot mm 좌표 아님) |
| layer | 1~4, **1-based** (layer 1 = Board 위 첫 LEGO 층) |
| orientation_deg | 2x3x1: 0 = X 2 / Y 3 stud, 90 = X 3 / Y 2 stud. 2x2x1: 0 |

`docs/reference/` GT 원본의 0-based layer 표기는 원자료 규약이며 C 구현에는 적용하지 않습니다.

## 6. 모듈 간 예상 호출 관계

```text
외부 / D (deviation 발생 시 호출)
   │  공개 함수만 호출
   ▼
main.py
   ├─▶ dialogue.py  질문 문장 생성
   ├─▶ voice.py     TTS 재생
   ├─▶ voice.py     녹음 + STT
   ├─▶ dialogue.py  응답 해석 ──▶ llm.py (애매한 응답 fallback)
   │
   ├─ UNCLEAR      → dialogue 재질문 문장 → voice 재생·녹음·STT → 다시 해석
   ├─ KEEP_TARGET  → 현재 채택된 Target Design 유지 (LLM 호출 없음)
   └─ KEEP_CURRENT → designer.py ──▶ llm.py
                         └──▶ validator.py
   ▼
최종 Decision / Design 반환
```

- 최초 목표: main → (voice 녹음 + STT) → dialogue 목표 사물 인식 → designer Initial → validator → 반환
- 텍스트 입력 모드에서는 voice를 호출하지 않습니다.

## 7. 외부 호출 원칙

외부 모듈은 `app.c_design.main`의 공개 함수만 호출합니다. `voice`, `dialogue`, `llm`, `designer`, `validator`를 직접 import하지 않습니다. 내부 구조가 바뀌어도 공개 함수의 계약만 유지하면 연결 담당 코드가 바뀌지 않게 하기 위함입니다.

## 8. import side effect 금지

패키지나 모듈을 import하는 것만으로 다음이 일어나면 안 됩니다.

- 녹음 시작, 마이크 접근, 음성 재생
- STT·TTS·LLM 모델 로딩
- API 호출, 네트워크 요청, API key 등 secret loading
- 파일 쓰기, 로그 폴더 생성

무거운 작업은 공개 함수가 호출될 때만 실행합니다. 테스트와 다른 담당의 import가 장치나 네트워크 없이 성공해야 합니다.

## 9. Contract에서 확정할 것

`main.py` 공개 함수 이름, Input / Output, Target / Current 형식, deviation context 형식, 의도값 enum, 실패 반환, 식별·버전 필드는 **다음 단계인 Contract에서 확정**합니다. 이 문서의 설명은 책임 범위이며 실행 가능한 계약이 아닙니다. 공통 계약 초안은 [06_CONTRACT_DRAFT.md](06_CONTRACT_DRAFT.md)를 따릅니다.

## 10. 개발 순서

1. Contract
2. Fixture
3. Text Dialogue
4. Validator
5. Mock Initial Design
6. Mock Modified Design
7. A/D Contract Test + Fake Voice Dialogue
8. 실제 LLM
9. 실제 STT + 녹음
10. 실제 TTS + Voice Dialogue 완성

실제 LLM·STT·TTS는 Mock 경로와 계약 테스트가 끝난 뒤 연결합니다.
