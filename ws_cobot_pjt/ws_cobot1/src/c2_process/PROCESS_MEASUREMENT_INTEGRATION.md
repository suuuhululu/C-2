# 공정 노드 내부의 실물 측정 연결

`workpiece_calibration.measure_workpiece()`가 실제 모듈 진입점이다. 단독 시험 노드는 같은 함수를 호출하는 시험 껍데기다.
`workpiece_real_trial.create_adapter()`는 TrialLease와 공정 노드 동시 실행 거절이 있는 **단독 시험용**이다.
공정에서는 새 `workpiece_process_adapter.create_process_measurement_adapter()`를 사용한다.
새 ROS 노드/Action을 만들지 않으며 세은님의 수신부·상태 기계는 변경하지 않는다.

## 공정의 작업 스레드 호출 예시

```python
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece
from c2_process.workpiece_process_adapter import create_process_measurement_adapter

# 아래 객체/설정/ID는 실제 공정의 현재 준비 요청에서 전달한다.
ctx = MeasurementContext(
    measurement_id, preparation_id, "REAL",
    motion_lock=coordinator.motion_lock,
    cancel=preparation_cancel_event,
    profile_snapshot_id=settings_snapshot_id,
    profile_sha256=settings_file_sha256,
)
adapter = create_process_measurement_adapter(
    node, measurement_config, ctx,
    motion_lock=coordinator.motion_lock,
    cancel=preparation_cancel_event,
    evidence_provider=read_preparation_evidence,
    evidence_max_age_s=measurement_evidence_max_age_s,
    scene_check=approved_measurement_scene_check,
)
try:
    result = measure_workpiece(adapter, measurement_config["workcell"],
                               measurement_config["profiles"], ctx, on_progress=publish_progress)
finally:
    adapter.close()  # 준비 adapter만 종료; 공정 노드는 계속 실행
```

공정 executor는 다른 스레드에서 spin해야 한다. ROS 콜백 안에서 동기 대기하지 않는다.
`measure_workpiece`가 잠금을 직접 획득하므로 호출 전에 같은 비재진입 Lock을 먼저 잡지 않는다.
조각도 동일한 coordinator.motion_lock을 사용해야 측정과의 중복 실행을 차단할 수 있다.
취소는 `preparation_cancel_event.set()`으로 전달하며, 측정 함수가 정지 요청/확인을 처리한다.
공정은 실패·취소·UNKNOWN 이후 별도 이동/홈/측정 재시작을 추가하지 않는다.

## evidence_provider(context)의 반환 계약

각 항목은 실제 근거를 캐시에서 복사해 반환한다. 함수가 호출됐다는 이유로 원래 관측 시각을 현재 시각으로 갱신하지 않는다.

```python
{
    "measurement_id": context.measurement_id,
    "control_authority": {
        "value": True, "valid": True,
        "source": "CONTROLLER_ACCESS_CONTROL",
        "observed_at_monotonic_s": authority_observation_time,
    },
    "mount_fixed": {
        "value": True, "valid": True,
        "source": "OPERATOR_CONFIRMATION",
        "observed_at_monotonic_s": mount_confirmation_received_time,
    },
    "drill_off_confirmed": {
        "value": True, "valid": True,
        "source": "OPERATOR_CONFIRMATION",
        "observed_at_monotonic_s": drill_off_confirmation_received_time,
    },
}
```

위 True는 형식 예시이며 실제 값은 다음 출처에서 공급해야 한다.

| 항목 | 공급 방법 |
|---|---|
| 소유권 | 동일 요청 context, 공정 공유 Lock과 취소 Event의 객체 동일성 및 잠금 상태로 검사 |
| 제어권 | 실제 드라이버 access-control 관측/검증된 공급 경로. AUTO·STANDBY·TCP 일치만으로 True로 만들지 않음 |
| 장착 고정 | 현재 준비 요청에 연결된 운영자 고정 확인 또는 실제 센서 근거. 그리퍼 닫힘만으로 철사 고정 추정 금지 |
| 드릴 OFF | HMI 운영자 OFF 확인을 준비 요청에 연결. 전원 센서 측정으로 표시하지 않음 |
| 현재 상태·관절·TCP·힘 | RosMeasurementIO가 실제 제어기 조회 |
| AUTO/REAL·TCP 이름·하중 | io.metadata() 실제 조회; 실행 중 재확인 |
| 간섭 검사 | 현장 기하에 맞는 scene_check. 기존 고정 현장에서는 `workpiece_real_trial.check_trial_scene` 계산기만 재사용 가능; TrialLease와 별개 |

`evidence_max_age_s`는 위 세 항목별 유효기간(초)을 공정 설정에서 명시한다. 코드가 임의로 유효기간을 넣지 않는다.
운영자 확인 취소·장착 변경·드릴 ON·제어권 상실 시 해당 근거를 무효화한다. 누락/거짓/만료 근거는 NOT_READY이며 움직이지 않는다.

설치된 드라이버 소스에서는 `OnMonitoringAccessControlCB`의 GRANT=2, LOSS 등과 내부 상태 갱신을 확인했다.
`dsr_msgs2/RobotState.msg`에 `access_control` 필드도 있으나 **현재 실행 환경에서 어떤 Topic으로 실제 발행되는지는 이 작업에서 검증하지 않았다**.
필드 존재만 보고 토픽 이름을 가정하거나 고정 True를 공급하지 않는다. 세은님의 실제 관측 공급 경로 확인이 남아 있다.

## 정지 확인 보강 · 2026-09-21

`GuardedMeasurementAdapter.stop_measurement(profile)`의 함수 인자와 StepResult 형식은 유지한다.
정지 명령은 한 번만 보내고, 다음 조건을 모두 만족해야 `SUCCEEDED`, `stop_confirmed=true`를 반환한다.

- `motion_status=0(IDLE)`이며 `robot_state`가 STANDBY(1), SAFE_OFF(3), SAFE_STOP(5), EMERGENCY_STOP(6), SAFE_STOP2(9), SAFE_OFF2(10) 중 하나다.
- 정지 요청 응답 이후의 새 관측으로 `guards.stop_stable_s` 동안 위치·자세·관절이 안정돼 있다.
- 안정 구간 첫 관측을 기준으로 도구 끝 위치 차이는 `movement_start_m`, 자세 회전각과 각 관절 차이는 `movement_start_deg` 이하다. 인접 두 점만 비교하지 않으므로 누적 이동도 검출한다.
- 기존 가드 값을 재사용하며 속도·힘·정지 모드를 변경하지 않는다. 현재 예제의 안정 구간은 0.2초, 위치 0.03mm, 자세·관절 0.03도다. 이번 보강의 실기 검증 완료값을 뜻하지 않는다.

명령 거부·조회 실패·만료·제한 시간 초과·안정 미확인은 기존대로 `UNKNOWN / STOP_UNCONFIRMED`, `stop_confirmed=false`다.
같은 관측 시각의 캐시를 반복 읽어 안정 시간을 채우지 않는다. 초기화·교시·복구·미지원 상태를 정지 확인으로 받아들이지 않는다.
보호정지 중 정지 확인 성공은 **공정 latch 해제·정상 준비·재시작 허용이 아니다**. 이 함수는 자동 해제·후퇴·홈 복귀를 명령하지 않는다.

### 조회·명령 근거

현재 실기 설정의 접두사는 `/dsr01/dsr_controller2`이며 다음 기존 서비스를 사용한다.

| 접두사 뒤 경로 | 타입 | 필드 |
| --- | --- | --- |
| `system/get_robot_state` | `dsr_msgs2/srv/GetRobotState` | `robot_state`, `success` |
| `motion/check_motion` | `dsr_msgs2/srv/CheckMotion` | `status`, `success` |
| `aux_control/get_current_posx` | `dsr_msgs2/srv/GetCurrentPosx` | `task_pos_info`, `success` |
| `aux_control/get_current_posj` | `dsr_msgs2/srv/GetCurrentPosj` | `pos`, `success` |
| `motion/move_stop` | `dsr_msgs2/srv/MoveStop` | 요청 `stop_mode`, 응답 `success` |

드라이버 기본 서비스 QoS는 Reliable / Volatile / KeepLast(10)이다.
응답에 원본 제어기 시각·sequence는 없다. `RosMeasurementIO.read()`의 `measured_at_monotonic_s`는 **조회 응답 완료 시각**이며 원본 센서 측정 시각이 아니다.
기존 `max_state_age_s` 검사는 어댑터 관측 캐시의 나이를 검사한다. 응답 성공이나 위치 불변만으로 연결 신선도를 증명하지 않으므로 공정의 연결·제어권 관측과 함께 사용해야 한다.
공정의 `stop_latched_provider` 및 latch 해제 정책은 세은님 담당이며 이번 변경에서 구현하거나 만료 시간을 새로 확정하지 않는다.

설치된 `DRFC.h`와 `DSR_ROBOT2.py` 기준 `1=DR_QSTOP`, `2=DR_SSTOP(Soft Stop)`이다.
`robot_adapter.py`의 기존 `_qstop()`는 이름과 달리 모드 2를 보내므로 주석만 바로잡았다. 실제 모드 선택은 기존 설정을 유지한다.

검증: 측정 어댑터·공정 어댑터 모의검사 82개 통과. 실제 드라이버/ROS 왕복·실기 정지 검증은 미실시.

## 세은님 브랜치 연결 시 확인할 두 제한

조회한 `origin/feat/process-integration-clean`의 `node.py`는 현재 SIM 전용 분기다.
`prepare_workpiece`는 runtime_mode/context/adapter가 SIM인 경우만 허용하고, 결과의 validity도 SIMULATED만 허용한다.
REAL adapter를 주입하는 것만으로 이 제한이 해제되지는 않는다. 이 두 연결 변경은 세은님 담당이다.
이번 결과 `ESTIMATED`, `absolute_top_verified=false`는 사용자 합의의 통합용 추정값이며, 정확한 실측으로 승격하면 안 된다.
기존 측정별 진행·StepResult 계약은 유지하고 `tool_projection_check`, `tool_reference`, 추정 출처를 추가했다.
