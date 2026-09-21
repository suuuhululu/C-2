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

## 상시 관측 연결 · 2026-09-21 팀장 합의 반영

기준 main `2e94e5d`. 새 `process_state_observer.py`는 **공정 내부 공유 캐시 공급자**다.
별도 노드·publisher·Topic·Action·필드를 추가하지 않는다. 측정 함수와 어댑터의 반환·취소 계약은 변경하지 않는다.

- 최종 측정 결과: `measure_workpiece()`의 `StepResult` → 공정 검증 → 기존 `PrepareWorkpiece` Result.
- 실시간 상태: 기존 드라이버 조회 → `node.observations` (`ObservationCache`) → 공정의 기존 `/c2/process_state` 발행.
- 공정 상태·진행·Action 응답·관측 시작/종료는 세은님 노드 담당이다. 측정 완료 후에도 공정 노드와 관측은 유지한다.

### 세은님 연결 지점

```python
from c2_process.process_state_observer import (
    start_process_state_observer, stop_process_state_observer,
)

# REAL 공정 노드 초기화: node.observations와 node.coordinator 생성 이후,
# 첫 준비 요청을 받기 전에 공정 소유자가 한 번 호출한다.
observer = start_process_state_observer(node, measurement_config)

# 기존 executor가 node를 spin하는 동안 대기·측정·완료 후에도 조회된다.
# 측정 함수 호출부나 측정 adapter.close()에서는 시작/종료하지 않는다.

# 공정 자체 종료 시, node.destroy_node() 전에 호출한다.
stop_process_state_observer(node)
```

### 관측기 시작 시점 확정

- 노드 기동 직후부터 첫 `PrepareWorkpiece` Goal 전까지 `joints`와 `tcp` 품질은 `UNKNOWN`이다.
- 첫 유효한 REAL `MEASURE` 요청에서 설정 스냅샷을 검증한 다음, 로봇 모션과 측정 adapter 생성 전에 관측기를 시작한다.
- 관측기는 해당 요청의 성공·실패·취소와 관계없이 유지하며 다음 대기와 후속 요청에서도 같은 설정으로 재사용한다.
- 관측 설정이 바뀐 후속 요청은 실행하지 않고 설정 불일치로 실패한다. 공정 노드를 종료한 뒤 새 설정으로 다시 기동한다.
- 관측기는 공정 노드 `destroy_node()`에서만 종료한다. 측정 함수 반환이나 측정 adapter `close()`는 관측기를 종료하지 않는다.
- 따라서 HMI는 첫 Goal 전 관절/TCP의 `UNKNOWN`을 통신 오류나 측정 실패로 바꾸지 않고, 아직 요청별 관측 설정이 연결되지 않은 상태로 표시한다.

`measurement_config`의 기존 `controller_prefix`, `service_timeout_s`, `guards.max_state_age_s`를 사용한다.
같은 노드·설정의 중복 시작은 기존 관측기를 반환한다. 설정이 다르면 오류이며, 명시적으로 종료 후 재구성한다.
SIMULATION 노드에 실제 조회를 붙이는 시작 호출은 거절한다. 모의시험은 별도 모의 서비스만 사용한다.
이 변경에는 **세은님 `node.py`의 시작/종료 호출 추가가 포함되지 않는다**. 위 연결 후 전체 공정 검증이 필요하다.

### 공급하는 값과 품질

| 기존 서비스 / 응답 | 캐시에 공급하는 값 | 기존 ProcessState 표현 |
| --- | --- | --- |
| `aux_control/get_current_posj` / `pos`, `success` | deg → rad의 J1~J6 | `joints`, 품질·관측 시각 |
| `aux_control/get_current_posx` / `task_pos_info`, `success`, 요청 `ref=0` | mm·ZYZ → m·quaternion, `c2_base` 제어기 TCP | `tcp`, 품질·관측 시각 |
| `system/get_robot_state` / `robot_state`, `success` | 기존 상태 코드 유효 여부 | 기존 캐시의 연결 관측, 품질·관측 시각 |

접두사는 설정에서 받는다. 제어기 TCP에 드릴 오프셋을 더하지 않으며, 캐시에도 `offset=None`을 전달한다.
제어권은 기존 전용 관측 경로를 유지한다. 모드·온도·그리퍼 등 조회하지 않은 항목은 정상값으로 채우지 않는다.
`robot_mode=UNKNOWN`, 온도는 기존 `UNSUPPORTED`다. 상태 코드 조회 성공은 로봇 준비·실행 허가를 뜻하지 않는다.

세 응답에는 **원본 제어기 측정 시각/sequence가 없다**. 관측 시각은 조회 묶음 시작 시각이며 원본 센서 시각이 아니다.
캐시가 이를 UTC 시각으로 변환하며, 발행 주기마다 새 측정처럼 시간을 바꾸지 않는다.
서비스 미수신·거부·비정상 수치·미지원 상태·시간 초과는 `UNKNOWN`, 캐시 유효기간 경과는 기존 규칙대로 `STALE`이다.
실패 사유별 새 ROS 필드는 만들지 않고 기존 품질 규약을 따른다. 조회 응답만으로 제어기 내부 데이터 신선도를 증명하지 않는다.

### 동시 조회와 종료

0.2초 주기의 비동기 조회이며, 응답 대기로 executor 콜백을 막지 않는다. 동시에 한 조회 묶음만 유지하고,
제한 시간은 기존 `service_timeout_s`와 `max_state_age_s` 중 작은 값이다. 만료 후 도착한 이전 응답은 캐시를 덮어쓰지 않는다.
클라이언트 취소는 서버에서 이미 처리 중인 조회를 취소한다는 뜻이 아니다.

관측기는 모션 잠금·취소 이벤트를 소유하거나 이동/정지 명령을 보내지 않는다. 측정은 기존 공유 잠금·취소 처리를 유지한다.
노드는 기존 MultiThreadedExecutor로 실행하고, 동기 측정 작업은 콜백 밖 작업 스레드에서 수행한다.
드라이버에 읽기 요청이 추가되므로 실기 통합에서 측정 조회와 함께 실행할 때 지연을 확인해야 한다.
드라이버 API 전체의 동시 접근 안전성이나 5Hz 실기 달성은 이번 모의시험만으로 보장하지 않는다.

### 검증 범위

- 실제 `ObservationCache`를 사용하는 단위검사: 정상 단위 변환, 조회 실패·만료·늦은 응답, 복구, 중복 시작, 종료.
- 격리 ROS 모의검사: 모의 드라이버 서비스 → 캐시 → 기존 ProcessState publisher → 구독자. 대기/진행/완료/대기의 상태 표시, 실패·복구·관측 종료 후에도 발행 유지.
- 모의검사의 공정 상태는 시험에서 설정한다. 실제 측정 함수·Action 취소 왕복·HMI·실기 연결 완료를 의미하지 않는다.
- 세은님 코드의 시작/종료 연결과 실제 하드웨어 동시 조회는 미검증이다.

## 준비 상태 조회의 executor 보존 · 2026-09-21 수정

통합 실기 요청은 상태 검사 뒤 `측정 I/O에는 별도 스레드에서 spinning 중인 executor 필요`로 실패했다.
`DoosanRobotAdapter.observe()`의 DSR_ROBOT2 조회 래퍼와 `_call()`이 기본 executor로 중첩 spin하여
공정 노드를 원래 executor에서 빼는 경로를 확인했다.

우리 어댑터의 관절·TCP·힘·로봇 상태 조회를 기존 ROS 서비스의 직접 호출로 변경했다.
공정 executor가 실행 중이면 별도 callback group의 응답을 Event로 기다리고 executor 등록은 변경하지 않는다.
처음부터 executor가 없는 단독 호출만 임시 spin을 허용한다. 등록됐지만 실행되지 않는 executor는 거절한다.
조회 실패는 UNKNOWN으로 유지하며, 시간 초과 시 해당 future를 취소하고 단발 client를 정리한다.
세은님 공정 코드, 측정 경로·속도·힘 기준, ROS 계약은 변경하지 않는다.

격리 ROS 모의 서비스에서 상태 조회 → TCP/하중 조회 → RosMeasurementIO.read 연결,
조회 거부·시간 초과·늦은 응답 후에도 공정 executor와 타이머 유지 검사를 통과했다.
이번 수정은 준비 측정 연결 범위다. 기존 조각·IK의 다른 DSR 래퍼 호출까지 통합 검증한 것은 아니다.
실행 중인 공정은 이전 코드를 사용하므로 재빌드 후 공정 노드를 다시 시작해야 한다.

### 접촉 결과의 기본 수치형 반환

19:30 통합 실기 요청은 8점 측정과 상공 홈 정지를 끝냈지만 Action 변환에서
`INVALID_MEASUREMENT: 접촉 힘/시각 오류`로 종료됐다. ROS 힘 배열의 numpy.float64가
측정 내부의 isinstance 검사는 통과하고 반환값에 그대로 남아, 공정의 기본 int/float
타입 검사에서 거절되는 경로를 로봇 없이 재현했다.
`measure_workpiece()`가 이미 유효성·접촉 범위를 검사한 기본 float의 힘·시각·자세를
접촉 기록에 저장하도록 수정했다. 공정 Action 검사와 ROS 필드는 바꾸지 않는다.
실패 재현 후 정상 9접촉 결과 변환 및 NaN/Infinity/bool 거절 4개 검사 통과.
수정 후 실기 재시험은 아직이며 이전 실패 결과를 성공으로 변경하지 않는다.

### 윗면 접촉 탐색 속도 변경

사용자 요청으로 실기 설정의 `profiles.top_touch.speed_m_s`만 0.0003 → 0.0006으로 변경했다.
가속도·힘 상한·기준 힘 측정·최대 탐색 거리·옆면 속도·IK/FK 검사 간격은 유지한다.
9/21 19:30 bag에서는 윗면 완료 약 32.4초, 옆면 준비 약 37.4초, 첫 점 접촉 준비 약 76.9초였다.
약 38~66초 동안 상공 TCP가 유지되며, 코드상 옆면 전체 경로 사전 IK/FK 검사가 이 구간에 해당한다.
0.6 mm/s 설정으로 실기 재시험은 아직 하지 않았다. 다음 준비 요청에는 변경된 파일의 새 ID·해시를 사용한다.

## 측정 경로 사전 검사 계측·중복 계산 재사용 (2026-09-21)

기준 main `08956e5`(PR #54 병합). 변경은 측정 내부 어댑터이며 준비 Action,
ProcessState, 공정 호출·반환 계약은 유지한다. 로봇 속도·힘·IK 표본 간격을 변경하지 않는다.

- `GuardedMeasurementAdapter.preflight_measurement()`는 성공/실패 시 기존 공정 로그에
  `measurement_preflight`와 JSON 진단 한 줄을 남긴다. 측정 ID, 구간/검사점 수,
  단계별 호출 횟수·초 단위 소요 시간(`readiness`, `metadata`, `observation`, `scene`,
  `ik`, `fk`), IK/FK 재사용 횟수, 전체 초·종료 상태를 포함한다.
  이는 로컬 진단이며 새 ROS 필드·토픽이 아니다. 원래 bag 명령에는 rosout이 없으므로
  다음 시험에서는 공정 터미널 로그를 보관해야 한다.
- 한 번의 사전 검사 안에서만 좌표·자세·해 공간이 정확히 같은 IK 입력을 재사용한다.
  FK는 목표와 회전수를 반영한 관절 입력이 모두 같을 때 재사용한다. 반올림한 좌표나
  이전 측정의 결과는 재사용하지 않는다. 모든 표본의 취소/제어권·시간 제한·관절 범위·
  직전 관절과의 연속성·FK 대조는 유지한다. 현재 상태와 힘 데이터는 캐시하지 않는다.
- `RosMeasurementIO`는 기존부터 서비스별 client를 재사용한다. 이번에 다시 구현하지
  않았으며 격리 ROS 검사에서 연속 조회 시 client 객체가 유지되는 것을 확인했다.

기존 로컬 bag `prepare_20260921_193029`의 Action Feedback을 다시 읽은 결과,
옆면 준비는 37.351초, 첫 접촉 시작은 76.884초다. 차이 39.533초에는 사전 검사와
첫 점까지 이동이 함께 들어 있다. 이 bag에는 IK/FK 서비스별 시간 기록이 없어
39.533초 전체를 IK 계산 시간으로 해석할 수 없다.

현재 설정·기준 윗면 Z=0.23470465087890625 m로 **오프라인 경로만** 재구성하면
48구간·765검사점·759고유점(정확한 중복 6점)이다. 이는 당시 실제 IK 결과나 이번
실물 측정값의 복원이 아니다. 중복 제거만으로 대기 시간이 크게 단축된다고 주장하지
않으며, 추가한 계측으로 실제 서비스 대기 비용을 확인한 뒤 다음 최적화를 결정한다.

검증: 측정 어댑터 모의시험 84개, 공정 측정 어댑터 모의시험 11개, 로봇과 분리된
ROS 서비스 연결 재사용 시험 1개 통과. 실물 이동·실기 시간 단축 검증은 미실시다.
# REAL 준비·실행 통합 진입점

`real_process_controller_node`는 기존 `/c2/prepare_workpiece`, `/c2/execute_process`,
`/c2/stop_process`, `/c2/process_state`를 한 공정 노드에서 제공한다. 준비 성공과
`BIND_SNAPSHOT`으로 연결된 스냅샷이 없는 실행 요청은 거절한다. 준비된 경로는
생성 후 전체 경로를 다시 평행 이동하거나 자동 홈 복귀하지 않는다.

```bash
ros2 run c2_process real_process_controller_node \
  --backend-url http://127.0.0.1:8000 \
  --preparation-journal-path "$PWD/runtime/prepare.sqlite3" \
  --execution-journal-path "$PWD/runtime/execute.sqlite3" \
  --controller-prefix /dsr01/dsr_controller2
```

두 원장 파일의 상위 디렉터리는 미리 존재해야 한다. 관리 경로 조회 결과와
원본 `path.json`, profile snapshot은 HMI backend에서 다시 읽고 ID·버전·SHA-256을
대조한다. 다음 조건 중 하나라도 빠지면 모션 전에 `NOT_READY` 또는 구체적인
불일치 오류로 종료한다.

- 경로·config·snapshot의 `source_mode=REAL`, `test_only=false`
- 관리 경로의 `real_execution_allowed=true`
- `workcell.measurement_scope=ABSOLUTE_GEOMETRY`
- `top.contact_offset_tool_m`, `top.offset_status=VERIFIED`, `top.offset_record_id`
- snapshot/workcell의 동일한 `tcp_id`, `load_id`
- `surface`의 실측 중심·반지름·높이
- `tip_calibration`, `calibration_profiles`
- `execution_context`의 REAL motion/tool/stop profile
- `joint_check_arguments`의 승인된 6축 범위와 J6 여유
- `verify_tool_tip_arguments.tol_m`

이 진입점 추가만으로 HMI와 c2_path가 실행 가능한 REAL 경로를 생산하는 것은
아니다. 두 소비자는 같은 snapshot을 보존한 `test_only=false` 경로를 등록하고,
HMI가 준비 BIND 성공 뒤 ExecuteProcess를 보내야 한다. 기존 REAL 추정 미리보기
경로(`test_only=true`, `real_execution_allowed=false`)는 계속 거절한다.
