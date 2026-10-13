# 현재 모듈 연결·계약

소스 기준은 README의 ebeeef2다. 명목 계산·모의 진행·실제 장치·실제 관측을 구분한다.

## 역할과 호출 흐름

```text
C 설계 후보 → HMI 미리보기 → 사용자 검토/승인
→ A 전체 계획 → 동일 Plan 자료를 B/D에 공유
→ Step 직전 A 재평가 → A 이동 후보
→ D 슬롯/상태/도움 준비 확인·실행
→ 지정 B 검사 → 확정 Current/revision → D 진행/보류
→ FINAL 결과 → 명시 DB 저장 → 웹 조회·선택 공개
```

| 부분 | 책임 |
|---|---|
| C | 형상·블록 규격/색/배치 생성·수정, 사용자 응답 해석. Candidate와 Approved를 구분 |
| A | Design/Current 기반 순서·기대 상태·작업 방식·사람 도움·이동 후보 계산 |
| B | Expected·관측 가능한 전체 판 비교·Current/revision 확정 |
| D | B 결과 중계·대응 확인, 실행/도움/검사 요청·진행·HMI·통합 |
| HMI | 표시·사용자 입력. 독립 Current/조립 완료/계획 생성자가 아님 |
| DB·웹 | JSONL 기록·제작자/Job 소유권·저장/조회/공개. 공정 상태 자동 복원·로봇 재실행 없음 |

현재 `app.mvp_integration`과 `app.mvp_real_trial`은 B 상태 처리 함수에 **합성 observe**를 공급한다. REAL 로봇 실행도 실제 Camera→B 전체 판 관측 증거는 아니다. B의 다른 실제 Camera runtime/모델·촬영 코드는 이번 실행용 구성에서 분리되어 있다.

## A와 C의 공개 연결

A 세 함수는 `planning_trial/assembly_adapter.py`에 있다.

| 함수 | 시점·입력·결과 |
|---|---|
| `handle_whole_plan(request)` | 승인 Design + 기준 Current + context/profile → 전체 Plan·방식·도움·공통 계획 자료 |
| `handle_step_reassessment(request)` | 같은 Plan + 최신 Current/선택 방식 → 실행 직전 평가 |
| `handle_step_motion(request)` | 평가 참조 + 예약 슬롯 + 로봇 상태 + profile → 이동 후보 |

A 계약은 `assembly-ad-calculation-draft/0.5.1`, 공통 bundle은 `a-b-d-planning-bundle-draft/0.1.1`이다. 같은 plan_id·design_version·base_current_revision·Step·평가/예약 참조를 연결한다. A 반환의 `execution_allowed=false`를 유지하며 실행 여부·장치 명령은 D 책임이다. A 결과는 TCP waypoint/motion proposal이고 MoveIt IK·전체 궤적/충돌 검사 결과가 아니다.

C 공개 함수는 `create_initial_design`, `review_design_candidate`, `run_intervention`, `run_design_change`다. D가 동기 호출해 response envelope을 받는다. 미리보기 표시 완료 후 검토하고 APPROVE 뒤 A에 전달한다. 수정 후보도 같은 검토/승인을 거친다. `design_metadata`는 설명·표시·기록용이다.

계획 실패 KEEP은 승인 목표·Current·실패 근거를 보존하고 보류한다. 같은 실패 입력을 자동 반복하지 않는다. 수정 후 재승인을 받아 같은 유효 Current로 남은 계획을 계산한다. 자동 분해·제거·교체 계획은 만들지 않는다.

## 계획·도움 정책

- 낮은 층부터 진행한다. 최초 완성 탐색/도움 최적화의 max_states 중단은 제거되었고, 구형 필드가 들어와도 탐색 중단에 사용하지 않는다.
- 30초는 최적화 반환 정책의 기준이며 모든 설계의 완성 계획이 30초에 나온다는 보장이 아니다. 완성 후보 확보 여부를 구분한다.
- 사람 손 접근 공간 검사와 최대 2손 상한은 제거됐다. 필요한 HOLD/PRESS/MANUAL_PLACE·손 수·도움 비용은 계속 계산·반환한다.
- 지지·겹침·삽입·로봇 국소 접근 검사는 유지된다. 방식은 현재 D에서 ROBOT_GRIP/HUMAN_ASSEMBLY를 요청한다. 계산상 후보가 있다는 사실은 실제 인원·공간·도움 준비 확인과 별개다.
- NO_FEASIBLE_ORDER는 검사한 조건에서 완성 순서를 확보하지 못한 결과다. blocked_candidates·원시 optimization 및 공개 블록/사유를 확인하고, 확인된 제약을 실물 절대 불가로 확대하지 않는다. INVALID·Current 보존 불일치와 구분한다.

## 실행·검사 경계

픽업 성공·이송 도달·실제 정지·파지 유지·Contact·체결·그리퍼 해제·B 확인은 서로 다른 상태다. A의 `HOLD_NO_AUTOMATIC_OPEN`, D_CONTACT 인계, `assembly_completed=false`가 물리 실행/관측 완료를 대신하지 않는다. 사람 직접 조립에는 인계와 사람 준비 응답이 필요하다.

B INITIAL/STEP/FINAL 요청과 결과의 Plan/Step/검사 대응을 확인한다. Expected는 Plan 시작 시 고정 Current에 목표 효과를 적용하며, 불일치 뒤 같은 Plan의 baseline을 새 Current로 바꾸지 않는다. 가림·UNKNOWN·관측 불가는 미조립으로 단정하지 않는다. 취소·중복·오래된 결과로 Current/진행을 갱신하지 않는다.

PR #36의 현장 시험은 공급 접근 MoveL, 파지 후 이송 MoveB, XYZ 반력40N 정지 확인 후 개방, 요청별 HMI 확인 버튼을 포함한다. 40N은 desired-force 명령이 아니다. 조립 grid x>11에는 기존 회전 보정과 별도로 Base X −1mm를 실행 사본에 적용한다. 원본 native35·교시 JSON은 보존한다. 상세 사용 조건은 RUN을 본다.

## 좌표·자료

| 기준 | 의미 |
|---|---|
| body 19mm / stud 4.5mm / pitch 16mm | 공통 블록·stud 계산 기준 |
| 공급 파지 5mm | 블록 밑면 기준 파지 정책 |
| GripperDA_v4 flange offset 228mm | 제공된 TCP 기준. 현재 장치 설정 변경 명령이 아님 |
| pre-contact bottom 간격 20mm | A 명목 계산 기준. D 현장 접근값/실측과 구분 |
| 공급판 모서리 Z | 접촉 TCP 원본. 물리 표면 Z로 간주하지 않음 |

`assembly_api_fixtures.py`, 기본 seed/sample JSON, measurements, assembly handoff JSON은 현재 profile 생성에 쓰인다. D의 teaching_sources는 현장 로그가 없을 때 사용하는 교시 원자료다. 이름이 fixture/isaac이라고 삭제하지 않는다. 두 `app` 패키지(루트와 D)는 별도 프로세스/cwd에서 사용하므로 합치지 않는다.

## 저장·공개

DB가 설정된 HMI는 시작 전 제작자 로그인 후 Job 소유자를 고정한다. 완료 후 저장은 같은 제작자로 확인하며 웹도 같은 DB를 사용한다. 새 도안은 기본 비공개, 사용자의 PUBLISH/UNPUBLISH로 공개를 선택한다. 개인 Job·대화·관측 이력은 공개 도안 조회와 구분된다.

로그인·DB 저장·웹 조회·공개 실패를 공정 완료 실패나 성공으로 덮어쓰지 않는다. 저장 재시도 때문에 물리 조립을 반복하지 않는다. DB는 상태 기록이며 B 관측/체결 확인의 대체 입력이 아니다.
