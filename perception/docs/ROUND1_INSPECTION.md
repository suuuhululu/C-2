# B 1차 통합 연결 — 10/8 계약

2026-10-11 팀장 요청/PR #22와 최신 integration `02137d8` 기준.
B가 Current·revision·Expected·비교를 확정한다.
D는 요청 식별과 진행/보류·HMI/DB 전달을 맡는다. 기존 PLACE/ASSEMBLY/CURRENT bridge는
과거 전달판 계약이며 이 검사 계약으로 자동 재해석하지 않는다.

## 실제 호출

기존 `perception_mvp.team_connection`에 추가한 `connect_inspection`을 사용한다.
새 ROS 타입·DB·모델 준비 ACK는 추가하지 않았다.

```python
from perception_mvp.team_connection import connect_inspection

# 두 함수는 통합 실행부의 실제 함수다. 테스트/가짜 생산자로 대신 bind하지 않는다.
b = connect_inspection(
    d_enqueue_inspection_result,  # D 소유 스레드에 결과를 enqueue하는 실제 callable
    observe=capture_and_validate_bundle,  # (context, is_active) -> (Observed, diagnostics)
    geometry_reference=actual_geometry_reference,
    initial_current=previous_confirmed_b_current,  # 첫 실행은 None, 실제 INITIAL로 확보
)
b.load_plan(design, plan, plan_base_current, geometry_reference=actual_geometry_reference)
b.request({"check_id": check_id, "check_kind": "STEP", "plan_id": plan_id, "step_id": step_id})
b.cancel(check_id)  # 동기 반환: 해당 검사 확정 권한 닫힘. Robot 정지 확인은 아님.
b.close()
```

`initial_current=None`이면 Plan 로드 전에 INITIAL 요청이 필요하다. 빈 Current를 임의 주입하지 않는다.
`capture_and_validate_bundle`은 실제 정지/안전/영상 안정·V0 손 조건 및 V0→D1→D3 관측을 수행하는
기존 실제 촬영 흐름에 연결할 함수다. 이번 구현은 이 외부 함수 없이 Camera/Robot을 실행하지 않는다.
오버레이에는 context.current의 blocks와 context.expected를 사용한다. INITIAL의 Expected는 None이다.

## 요청/계획/결과

- 계획 공유: `load_plan(Design, Plan, plan_base_current, geometry_reference=...)`.
  동일 자료를 A가 B/D에 공유한다. Current/revision이 B 현재 상태와 다르면 거부한다.
  5층·빨강 `1x2x1` 전용, 노랑/파랑 `2x2x1`·`2x3x1`, 목표 최대 40블록.
- 요청은 정확히 `check_id, check_kind, plan_id, step_id`다. INITIAL은 Plan/Step null,
  STEP은 둘 다 필수, FINAL은 Plan 필수/Step null. 새 검사마다 새 check_id.
- 촬영 문맥은 시작 시 고정하고 한 요청 한 묶음으로 `observation_seq=0`을 사용한다.
  관측 함수는 동일 check_id/seq를 반환한다. D가 다른 순번 정책을 요구하면 합의 후 변경한다.
- 결과는 PR #22의 `history.final_mvp.validate_response` 봉투:
  `check_id, check_kind, plan_id, step_id, status, comparison, current, expected,
  difference, observation, reason`.
- `current={current_revision,blocks}`, `expected={plan_id,step_id,blocks}`.
  `difference={missing,unexpected,unobservable}`. observation에는 기존 근거 네 필드가 들어간다.
  내부의 공통 Observed 여섯 필드는 그대로 유지한다.
- 정상 STEP/FINAL comparison은 MATCH/MISMATCH/UNOBSERVABLE. INITIAL은 comparison/expected null.
  ERROR/CANCELED는 current/expected/difference/observation/comparison 모두 null이며 원인을 보존한다.
  미수신/실패는 빈 Current/MATCH로 대체하지 않는다.

## 상태와 취소

- 관측 가능 영역 전체를 비교한다. 새 목표 하나가 맞아도 확인된 다른 차이는 MISMATCH다.
  순수 UNOBSERVABLE은 기존 Current를 유지한다. 확인된 실제 차이와 가림이 함께 있으면
  MISMATCH와 unobservable을 함께 반환하며 D는 다음 진행을 보류한다.
- 가려진 기존 아래층은 이력으로 유지하고 이번 visible_blocks에 넣지 않는다.
  실제 확인 변경이 있을 때만 revision이 증가한다. 사진/check만 바뀌면 유지한다.
- FINAL은 모든 Plan Step의 B MATCH 기록 뒤 허용하며 전체 승인 Design을 비교한다.
  Plan 누적 효과와 Design 불일치는 Plan 공유 때 거부한다. B가 다음 Step을 선택하지 않는다.
- 공유만으로 취소하지 않는다. D는 STOP/교체/재계획 전에 같은 check_id를 cancel하고 반환을 확인한다.
  취소와 확정은 같은 잠금으로 순서화한다. 취소 이후 계산은 상태/이력을 갱신하지 않는다.
  확정이 먼저 끝난 경우 되돌리지 않고 D는 새 검사로 최신 B Current를 확보한다.
- 같은 요청 재수신은 재촬영/재확정하지 않는다. 다른 내용의 동일 ID는 충돌 오류다.
  활성 검사 교체에는 명시 cancel이 필요하다. 자동 이동·재시도 없음.
- 결과 전달 callback이 실패해도 확정 상태를 되돌리거나 ERROR로 위장하지 않는다.
  `last_delivery_error`에 원인과 미전달 원문을 남긴다. D는 진행 보류하고 연결 복구/새 검사로 처리한다.

## 실제 검증 범위 / 남은 연결

2026-10-11 이전 로컬 시험에서는 D Qt 수신 경계를 사용해 실제 B 코어와 PR #22
소비자/로그 파서를 대조했다. 이후 원격 `02137d8`을 가져와 별도
`codex/b-round1-realign` 작업 공간에 B만 옮겼다. 최신 사용자 지시에 따라
D 수신부·호환 bridge·D 연결 시험은 이번 제출 범위에 포함하지 않는다.
[D 담당자 인계 사항](D_INSPECTION_CONNECTION.md)을 따른다.
현재 B 작업은 기존 D 공정/HMI 및 실제 Camera/Controller bind 완료를 뜻하지 않는다.

단위 검사는 Camera/Robot 대신 명시된 테스트 Observed를 사용한다. 실제 장치 검증이 아니다.
PR #22 commit `7bf15ee4571169e98a15e725ce2365767eea46ac`의 DB 결과 validator와 HMI inspection
validator 원문을 별도 읽기 전용 시험 사본으로 가져와, B가 생성한 STEP/FINAL·5층·가림·차이·미확인·오류
결과를 검사한다. DB 접속/저장, Qt 실시간 이벤트 연결, 실제 D 진행 판단은 이 검사에 포함하지 않는다.

```bash
# 최신 integration 기반 B 작업 공간의 저장소 루트에서 실행
QT_QPA_PLATFORM=offscreen \
PYTHONPATH=.:perception:perception/legacy \
B_ROUND1_CONSUMER_PATH="$PWD/history/final_mvp.py" \
B_ROUND1_HMI_CONSUMER_PATH="$PWD/app/hmi_mvp_contracts.py" \
python3 -m pytest perception/perception_mvp/tests perception/legacy/tests -q
```

위 명령은 최신 checkout의 실제 DB/HMI 검증 함수를 대조한다. HMI 검증 함수
`_inspection`은 `app/hmi_mvp_contracts.py`에 있다. B-only checkout에서는 두 환경변수에
검토한 소비자 원문 경로를 지정해야 한다. 소비자 미제공 시 검사는 skip이며 PASS로 주장하지 않는다.

남은 작업:

1. D가 위 B 함수에 검사/취소/계획 공유를 bind하고 결과를 D 스레드로 enqueue한다.
   PR #22의 문서·표시/저장 validator만으로 이 실시간 수신 연결이 구현된 것은 아니다.
2. 실제 capture_and_validate_bundle 및 Camera/Controller 다중 관측점 연결.
   안전한 관측 자세·정지·손 조건은 실제 근거로 확인한다.
3. 5층 실측 높이·가림/반사·위치/층 정답 및 실제 HMI/DB/Robot 통합 시험.
   빨강 실제 Depth/Grid에는 해당 footprint/중심 lattice/anchor 오프셋 실측 설정도 필요하다.
4. 최초 Current조차 없는 INITIAL 관측 불가는 원인 `INITIAL_STATE_UNAVAILABLE`의 ERROR/null로
   반환한다. PR #22 validator가 UNOBSERVABLE에도 Current 객체를 요구하기 때문에 미관측 빈 상태를
   만들지 않는다. D와 초기 미확인 상태의 표시/재검사 정책을 확인해야 한다.

정렬 단계의 GitHub 게시 보류 이후 사용자가 기존 PR #24 갱신을 명시 승인했다.
최신 integration과 기존 제출 이력을 보존하는 merge·일반 push를 사용한다.
기존 작업 브랜치·원자료·실측 파일은 보존하고 force push·PR 병합은 하지 않는다.
