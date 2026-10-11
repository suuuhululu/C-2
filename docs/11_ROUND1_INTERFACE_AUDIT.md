# 1차 통합 인터페이스 점검

점검일: 2026-10-11. 대상 저장소는 `suuuhululu/C-2`이며 제출 대상은 사용자 생성 브랜치 `codex/integration-round1`입니다. 이 문서는 계약 정합과 오프라인 시험 범위이며 실제 Camera·Robot·음성 API·DB·웹 통합 성공을 뜻하지 않습니다.

## 기준과 반영 범위

- 점검 시작 시 main과 통합 브랜치는 모두 `afd75d0b0943d85b44248ea563e89f860921e1dd`였습니다. 이 버전의 C 상한은 5층, A/D/공통 Schema는 4층으로 서로 달랐습니다.
- 기존 `fix/common-five-layer-support`의 `27907c81bfc1f9f2bf9b6ae9ffbaa868b05aa66b` 변경을 재사용합니다. 작업본의 5층 지원을 대상 브랜치에 반영했는지는 PR·원격 커밋으로 확인합니다.
- 제품 목표는 [최종 MVP](10_FINAL_MVP.md), 현재 소프트웨어 경계는 [공통 계약](06_CONTRACT_DRAFT.md), C 상세는 [C 계약](C_DESIGN_CONTRACT.md), 관측 책임은 [C/B/D 연결 합의](09_C_B_BACKEND_HANDOFF.md)를 따릅니다.
- 과거 4층 시험·GT·원본 hash·실측·보관 Fixture는 보존합니다. 현재 5층 입력은 새 연결 시험으로 확인하며 과거 5층 INVALID Fixture를 현재 유효성 기준으로 재사용하지 않습니다.

## 공통 소프트웨어 계약

| 항목 | 1차 통합 기준 | 코드·Schema 근거 |
|---|---|---|
| 블록 필드 | `brick_type, color, x, y, layer, orientation_deg` 여섯 필드 | C validator, D contracts, Day4 Schema의 block |
| 종류·색 | `2x2x1 / 2x3x1`, `yellow / blue` | 세 모듈 검사와 Schema |
| 좌표 | x/y 정수 0~23, stud, footprint의 최소 모서리 | C/A 기하 검사와 D 배치 채택 |
| 층 | 정수 1~5, 1층은 판 위 첫 층. 6층 이상은 거절 | C/A/D MAX_LAYER=5, Day4 Schema의 layer maximum=5 |
| 관측 영역 | `x,y,width,height,layer`, 층 1~5, 판 내부 영역 | D validate_observed와 Schema verified_region |
| 방향 | 6점 0°=X2/Y3, 90°=X3/Y2. 4점은 대표값 0° | C/A/D 및 Schema |
| Design | `{design_version, blocks}`, 전체 목표 | C 공개 계약·D validate_design·Schema |
| 블록 수 | C 생성 1~30. A/D에 새 수량 제한을 추가하지 않음 | C MAX_BLOCKS=30, 30블록 연결 시험 |
| Plan | `{plan_id, design_version, base_current_revision, steps}` | A 순서 계산·D 채택 검사·Schema |
| Current | `{current_revision, blocks}`, D가 유효 관측을 채택하고 변화에 따라 revision 발급 | app/current.py, Backend |
| Observed | `{check_id, observation_seq, status, visible_blocks, verified_regions, reason}` | D validate_observed·B 합성 callback·Schema |
| 관측 상태 | OK는 판별 가능이며 MATCH가 아님. UNOBSERVABLE은 보류 | B/D 합의·Current/완료 검사 |
| 최신성 | 활성 요청·목표 버전·기준 revision·촬영 순서 검사. 닫힘·중복·과거 결과로 진행 금지 | Backend·Current·재계획 검사 |
| HMI | block/design/current는 Day4 Schema를 참조하여 5층을 표시 | HMI Schema·Consumer·Qt |
| 기하 지지 | 바로 아래층 고유 stud 총 2개 이상. layer=1 제외 | A/C 기하 합의. 물리 안정성·접촉 성공의 대체물 아님 |

Schema는 구조 검사입니다. JSON Schema의 integer는 수학적으로 정수인 1.0도 수용할 수 있지만 현재 Python Consumer는 bool·float를 거절합니다. Producer는 JSON 정수로 내보내고 Schema뿐 아니라 실제 Consumer·기하·최신성 검사를 함께 통과해야 합니다. Schema 통과만으로 실행을 허용하지 않습니다.

## 이번에 정리한 문서 충돌

| 위치 | 충돌 | 정리 |
|---|---|---|
| 공통 계약 §1 객체표 | block_id·parent_version을 Design/Current에 요구하는 표현이 C 계약·Schema와 다름 | 여섯 배치 필드·두 Design 필드로 정렬. 공급 slot·진단 정보 분리 |
| 공통 계약 §1 HRI | 무응답 시 CANCELLED라는 표현이 C/B/D 합의와 다름 | 무응답은 대기, 명시 취소·STOP과 구분 |
| 팀 가이드·C 구조 | 이미 합의된 2 stud 기하 지지를 미확정으로 설명 | A/C 합의로 표기. 물리 안정성·관측 순번 증가 범위는 별도 확인 |
| A/D 인계의 오류 설명 | 5층을 현재 잘못된 입력으로 표현 | 현재 범위 초과는 6층, 과거 5층 INVALID 시험은 당시 기록 |

## 별도 작업 브랜치에서 남은 연결 과제

아래는 미병합 브랜치의 문서·코드를 대조한 결과입니다. 담당 브랜치의 책임·동작을 이번 수정에서 바꾸지 않습니다.

| 우선순위·담당 | 차이 / 미연결 | 1차 통합에서 필요한 조치 |
|---|---|---|
| BLOCKER · A/B/D | A `work/seeun-planning`의 API 0.5 문서는 B가 Current/revision을 확정하고 D가 보관·중계한다고 설명. 현행 D/공통 문서는 D가 채택·발급·판정 | 현행 D 단일 상태 Owner를 기준으로 A/B/D 입출력을 확인하고 A 제출 PR의 표현·Fixture·Consumer를 정렬 |
| BLOCKER · A/D | A API 0.5의 전체 계획/직전 재평가/경로·supported_modes·assessment_input_digest·프로필 ID/버전은 현재 통합 기준에 미배포 | D 최종 Schema와 정상·실패 Fixture, A 생산/소비 시험을 담당 PR로 제출. 구형 Plan을 새 경로 계약으로 가장하지 않음 |
| BLOCKER · B/D | 통합 기준의 B 제공물은 합성 callback. 실제 촬영 생산자와 최종 Vision 요청·응답은 미제출 | B 실제 실행 코드·촬영 요청 연결·5층 관측/가림 근거와 D 수신 시험 제출 |
| REQUIRED CHANGE · C/D | 사용자 설계 확정 이벤트와 후보/확정/채택 연결은 최종 MVP 이행 대상 | 실제 승인 이벤트와 STOP·취소·늦은 결과 Fixture 확인. 후보 생성만으로 실행 금지 |
| REQUIRED CHANGE · A/D | A 계획 기하는 m, 실기 adapter의 TCP/위치 입력은 별도 frame·단위를 사용 | 실제 경로 계약에서 단위·좌표계·프로필·Z 원점 변환을 명시. stud·m·mm와 보드 표면/보드 stud 끝/TCP를 혼용하지 않음 |
| REQUIRED CHANGE · D | 연구 `work/suhyun-assembly-evidence` 및 로컬 제스처·접촉 시험본은 전체 live 통합과 다름 | 장치 writer·정지 ACK·접촉 인계·실행/결착 증거를 구분해 제출·검증 |
| REQUIRED CHANGE · D/웹 담당 | 사용자–Job 소유자·웹 세션/권한·저장/조회 연결은 미합의·미연결 | 별도 계약·담당 PR 필요. DB 이력표·계정표 존재를 전체 서비스 완료로 표시하지 않음 |

A 참고 시점은 `1cc01b884446db566e8c3d35ca4da0f9d2b4ab99`의 [API 0.5 문서](https://github.com/suuuhululu/C-2/blob/1cc01b884446db566e8c3d35ca4da0f9d2b4ab99/planning_trial/ASSEMBLY_API_05_20261008.txt), D 연구 참고 시점은 `0ca498da90d444b355ad90d28c2bb0b5e5863aba`의 [인계 문서](https://github.com/suuuhululu/C-2/blob/0ca498da90d444b355ad90d28c2bb0b5e5863aba/docs/D_ASSEMBLY_HANDOVER.md)입니다. 문서에 적힌 과거 PASS 수치를 이번 시험 결과로 사용하지 않습니다.

## 검증과 제출

- `tests/integration/test_five_layer_pipeline.py`: C 검증→A→D→Qt→합성 관측, 30블록, 부분 Current, 6층 거절, 기하 제약, Schema/HMI 참조, 수동 시험의 관측 영역 범위.
- 같은 시험에 C/A/D/Schema 층 상한 일치와 B 합성 callback의 5층 채택·아래층 가림 보존·6층 거절 후 상태 보존·중복 거절을 추가했습니다. 실제 B 인식 성능 시험이 아닙니다.
- 관련 기존 L1/L3와 문서 링크·표·JSON·변경 범위 검사를 실행하고 실제 결과는 [STATUS](STATUS.md)의 2026-10-11 기록에 남깁니다.
- 실제 5층 Camera 인식·직접 결착·30블록 장치 실행·LLM/음향·DB/웹은 이번 시험 범위 밖입니다. REAL 수동 시험의 최대 24 Step과 공급 슬롯 수를 30으로 바꾸지 않습니다.
- 각 담당 PR은 통합 브랜치를 대상으로 하고, 작성자 외 사람 리뷰 뒤 반영합니다. 현재 문서·Schema 정합을 전체 인터페이스 통합 완료로 표시하지 않습니다.
