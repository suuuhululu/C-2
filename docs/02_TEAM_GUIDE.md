# 팀원별 계약 준수와 연결 준비

> 2026-10-06 보완: C/B DM 이후 확정 내용과 연결 책임은 [C·B Backend 연결 합의](09_C_B_BACKEND_HANDOFF.md)를 함께 확인합니다. block_id 필수 제외·5분 자동 취소 제외·유한 후보 재생성·촬영 순서·확인 영역·전달판 미확인을 명확히 했습니다. 지지 2 stud 및 관측 묶음 순번 범위는 확인 전 후보/제안입니다.


갱신: 2026-10-05. [현재 결정](00_CURRENT_DECISIONS.md)과 [공통 인터페이스 계약](06_CONTRACT_DRAFT.md)을 기준으로 합니다. 계약 확정은 각 담당의 구현·통합 성공을 뜻하지 않습니다.

## 담당별 필수 제공물

| 담당 | 입력 → 출력 | 반드시 지킬 사항 | 연결 전에 제공할 예시 |
|---|---|---|---|
| 시율 C | 키워드 → 전체 Design; Design / Current / Difference → 질문·KEEP / REVISE / UNCLEAR | 공통 여섯 배치 필드, 전체 blocks, 실제 목표 변경에만 버전 증가, layer 초과 재설계. 질문·음성 생성 Owner | 정상 Initial / Revised, KEEP, 재질문·계속 불명확 선택 대기, 호출 / malformed 실패 |
| 세은 A | Design + Current / revision + 제약 → Plan / Replan | PLACE만, before=null, 범위·overlap·support·선행 관계 검증, 입력 revision 복사, 새 Plan ID, 실패를 빈 성공으로 반환 금지 | 정상 3 Step, 6점 x=23 invalid, 지지 실패, 이미 충족한 Remaining, NEEDS_CORRECTION, 오래된 기준 결과 |
| 홍동 B | 이미지·check 연결·after → Observed | 실제 배치·verified_regions만, 촬영 당시 check / 순번 고정, OK와 MATCH 구분, 가림을 삭제 증거로 반환 금지 | 일치, 다른 색상, 확인한 빈 영역, UNOBSERVABLE, 아래층 가림, 실제 기존 배치 변경, 늦은 프레임 |
| 수현 D | 모듈 결과·Robot result·UI 요청 → Current / Expected / 다음 요청 / snapshot / 로그 | 고정 기준 Expected, 활성 식별 / 버전 검증, 전달과 조립 완료 분리, 중복 실행 금지, 실제 pick만 슬롯 소모, STOP 3방향 재개, Qt 단일 화면 | 닫힌 check, 중복 전달 결과, 재계획 채택 중 Current 변경, STOP / 재개 3상황, 로그·HMI 상태 갱신 |

최초 경로는 C → A → 검증된 Design + Plan을 D입니다. D가 C의 질문 문장을 대신 만들지 않고 A의 Planner 알고리즘·B의 인식을 대행하지 않습니다. 계산 함수는 Job·장치 없는 Fixture로 시험하며 adapter가 실행 문맥을 연결합니다.

## 기존 C 문서와 공통 계약 이행

현재 main의 C 파트는 docstring skeleton이며 기존 구조 설명의 필드·의도명이 아래와 다릅니다. 이번 변경은 문서 계약을 정렬하며 production 코드는 바꾸지 않습니다. Producer / Consumer 연결 시 공통 형식으로 내보내도록 맞추고 계약 시험으로 확인합니다.

| 기존 C 표현 | 현재 모듈 간 공통 표현 / 의미 |
|---|---|
| geometry | brick_type |
| grid_x / grid_y | x / y |
| YELLOW / BLUE | yellow / blue |
| KEEP_TARGET | KEEP: 현재 채택 목표 유지. 최초 v1로 복귀하는 뜻이 아님 |
| KEEP_CURRENT | REVISE: 사람의 변경 의도를 반영한 전체 Design 후보. 실제 배치 보존의 특정 사례는 기존 C validator에서 검증 |
| 무제한 UNCLEAR 재질문 | 설명한 선택지로 재질문하고 계속 불명확하면 명시 선택 대기. 자동 LLM 반복을 강제하지 않음 |

이행 과정에서 내부 별칭은 adapter로 변환할 수 있지만 경계에서 혼합 필드·중복 ID를 반환하지 않습니다. REVISE를 선택했다는 이유만으로 임의 목표·미검증 Plan을 바로 실행하지 않습니다. C package 파일 책임과 import side effect 금지 규칙은 유지합니다.

## 미리 합의한 정책을 다시 늘리지 않기

- HMI는 Qt 한 화면·반폭 고정 창, 기본 버튼은 시작 / 정지 / 재개입니다. 정상 매 Step에 사람 확인을 추가하지 않습니다.
- 전체 목표 미리보기는 채택 Design으로 그립니다. C가 별도 이미지 모델·이미지 파일 API를 제공할 필요가 없습니다.
- 가려진 확인 완료 아래층은 유지합니다. 목록 누락만으로 Current 전체를 교체하지 않습니다.
- 홍동은 observe point 시야·완료 확인 촬영 시점·전달판 판별 제안을 수정할 수 있습니다. 변경 시 D와 callback / 표시를 맞추고 근거를 기록합니다.
- Robot pose·TCP·속도·정지 구현과 실제 성능은 검증된 기존 값·장치 시험을 따릅니다. LLM·문서 예시로 생성하지 않습니다.
- 실패를 성공·빈 정상값으로 감추거나 문서·Mock 성공을 실제 장치 성공으로 표시하지 않습니다.

## Day별 연결 순서와 완료 증거

1. Day1: 공통 입력·출력의 정상 / 실패 Fixture를 인접 담당에게 제공. 의미·필드·좌표·식별 확인.
2. Day2: 각 모듈 독립 구현, Fake Vision / Robot / HRI로 D의 3 Step 흐름과 실패 분기 확인. 실제 장치 준비는 별도 기록.
3. Day3: C–A–D, B–D, D–Robot, D–Qt 연결. 오래된 결과·가림·KEEP / REVISE·정지 후 재개 검증.
4. Day4: 실제 전달 → 사람 조립 → 관측 완료 → 의도 확인 / 재계획 → 최종 전체 Design 확인. 실제 결과와 미검증을 기록.

완료 보고에는 입력·예상 결과·실제 결과·검증 대상·미검증·다음 연결을 남깁니다. 문서에만 정한 Schema·실제 구현·Mock 연결·Camera / Robot 장치 확인을 각각 구분합니다. 다른 자료 폴더의 시험을 이 저장소의 CI / 연결 통과로 옮기지 않습니다.

## Git 협업

feature branch → PR → 작성자 외 사람 리뷰 → merge. 공통 계약은 연결 담당이 확인하고 실제 Robot / STOP 변경은 Robot Owner와 다른 사람이 검토합니다. 이번 문서 갱신도 main에 직접 개발하지 않습니다. 공통 계약 변경 시 생산자·소비자 영향·이행 방법·검증을 PR과 STATUS에 적습니다. 사용자 변경·reference 원자료·기존 장치 설정을 보존합니다.

## 새 AI 채팅 요청 예시

```text
AGENTS.md, docs/00_CURRENT_DECISIONS.md, docs/STATUS.md를 읽어 주세요.
담당: [시율 / 세은 / 홍동 / 수현]
목표: [작은 기능 하나]
범위: [파일 / 모듈]
입출력: docs/06_CONTRACT_DRAFT.md의 해당 계약과 Fixture
완료: 정상·실패 기대값과 실제 검증
기존 변경을 보존하고 문서 결정·구현·장치 검증을 구분하세요.
```
