# B → D 인계: 검사 연결 요구사항 — 2026-10-11

## 적용 범위

최신 integration `02137d8` 기반의 **B 제출 작업**이다. 사용자의 최신 지시에 따라
D 파트는 수정하거나 추가하지 않는다. `app/`, `tests/`, `interfaces/`,
`planning_trial/`는 최신 integration 원문을 유지한다.

이전 로컬 D 수신부 시제품은 원래 작업 폴더에 보존한다. 이번 제출용 작업 공간에
추가했던 D 수신부·호환 bridge·연결 시험 세 파일도 별도 보관했고 제출 범위에서 제외했다.
이 문서는 D 담당자에게 필요한 연결 사항이며, D 실행기에 연결됐다는 뜻이 아니다.

## B에서 제공하는 실제 함수

```python
from perception_mvp.team_connection import connect_inspection

b = connect_inspection(
    d_enqueue_result,  # D가 제공: 원래 Job 문맥과 결과를 Qt 소유 스레드에 전달
    observe=actual_capture_bundle,  # B/Controller 실기 연결 필요
    geometry_reference=actual_geometry_reference,
)
b.request(dict(check_id=initial_id, check_kind="INITIAL", plan_id=None, step_id=None))
# INITIAL 결과가 도착하고 B Current를 확보한 뒤에만:
b.load_plan(design, plan, b_confirmed_baseline,
            geometry_reference=actual_geometry_reference)
b.request(dict(check_id=step_check_id, check_kind="STEP",
               plan_id=plan["plan_id"], step_id=active_step_id))
# 모든 STEP 확인 뒤 D가 별도 FINAL 요청:
b.request(dict(check_id=final_id, check_kind="FINAL",
               plan_id=plan["plan_id"], step_id=None))
# STOP/교체: D가 진행 권한을 먼저 닫고 취소 반환을 확인:
b.cancel(active_check_id)
b.close()
```

위 코드는 호출 순서 설명이다. 실제 함수·ID·설정을 제공해야 하며 INITIAL 수신 전에
Plan을 로드하면 거부된다. `actual_capture_bundle(context, is_active)`은 실제
정지/안전/영상 안정과 V0 손 조건, V0→D1→D3 촬영·검증을 수행해야 한다.
이 함수의 실기 결선은 문서 예제로 대체하지 않는다.

## D 담당자에게 요청할 최소 연결

1. Job·check_id·검사 종류·Plan·Step을 결과의 원래 문맥과 검사한다.
   닫힘·취소·다른 Job·중복/늦은 결과는 다음 진행 근거로 쓰지 않는다.
2. B callback을 D 소유 Qt 스레드에 enqueue한다. B worker에서 Backend/Qt 상태를 직접 바꾸지 않는다.
3. B Current/revision·Expected·Difference를 원문 그대로 HMI/C/기록에 전달한다.
   D에서 공간 비교·revision 발급을 반복하지 않는다. `B_CONFIRMED_D_RELAYED`를 유지한다.
4. INITIAL/STEP/FINAL 결과는 구형 `Backend.on_observation()`에 자동 변환해 넣지 않는다.
   최신 Backend에 남은 Day4 공간 비교 경로와 중복 실행하지 않는다.
5. STOP·Robot 오류·전달판 상태·활성 실행 등 D 조건도 확인한다.
   B MATCH 또는 손 이탈 >3초만으로 Robot 실행을 허가하지 않는다.
6. 취소·교체 때 D 진행 권한을 먼저 닫고 B cancel 반환을 확인한다.
   취소 전에 B 확정이 끝났으면 되돌리지 않고 새 check로 최신 B 상태를 확보한다.
7. CHECK_RESULT 원문·수신 disposition을 기존 JSONL에 기록하고 HMI/DB에 전달한다.
   실패는 보류·사유로 남기며 빈 정상 상태로 대체하지 않는다.

최신 C Candidate→Preview→Review→APPROVE와 stale/STOP guard, 빨강/5층/40블록,
최신 Robot 설정은 그대로 유지해야 한다. D 수정 필요 여부와 실제 결선은 D 담당자가 확인한다.

## B 범위 검증 재현

최신 integration 기반 B 작업 공간의 저장소 루트에서:

```bash
QT_QPA_PLATFORM=offscreen \
PYTHONPATH=.:perception:perception/legacy \
B_ROUND1_CONSUMER_PATH="$PWD/history/final_mvp.py" \
B_ROUND1_HMI_CONSUMER_PATH="$PWD/app/hmi_mvp_contracts.py" \
python3 -m pytest -p no:cacheprovider \
  perception/perception_mvp/tests perception/legacy/tests \
  perception/calibration/tests perception/supply_vision/tests -q
```

B가 생성한 STEP/FINAL·MATCH/MISMATCH/UNOBSERVABLE·5층·가림·취소 결과를
최신 integration의 실제 DB/HMI 검증 함수와 대조한다. 해당 D 파일은 읽기만 한다.
구형 `connect(bridge)`의 한 인자/Qt queue 검사는 명시된 계약 대역으로 B 전송 경계를
검사하며 최신 D 실연결 시험이라고 주장하지 않는다.

실제 Camera·Robot·전체 Qt 실행기·DB 서버·완료/다음 전달의 공동 시험은 남아 있다.
add/commit/push/PR 변경은 별도 사용자 요청 전 수행하지 않는다.
