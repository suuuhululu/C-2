# 양초 측정 모듈 · 제어 노드 내부 호출용

작성 2026-09-21. 기준 main `19ef4c6`, 작업 브랜치 `codex/workpiece-calibration`.
이 문서의 함수 계약은 새 코드에 구현되어 있다. ROS Action 타입/이름과 다른 담당의
로더가 이미 변경됐다는 뜻은 아니다. 9/21 11:34 팀장 제안에 맞춰 별도 측정 서버 대신
제어 노드에서 준비 검사 후 측정 함수를 호출하는 구조로 다시 정리했다.

## 단독 실물 시험 수신부 (추가)

공통 준비 Action을 기다리지 않고 실제 `measure_workpiece()`를 호출하는 **시험 전용**
`test/workpiece_test_node.py`를 추가했다. 별도 운영 노드/공통 통신 계약을 추가한 것이 아니다.
내장 `workpiece_real_trial.create_adapter`가 REAL I/O·상태 재확인·단독 소유권·실험 영역 검사를 연결한다.

현재 그리퍼 밑면 오프셋이 미확인이므로 실물 예제는 `measurement_scope=CONTACT_REFERENCE`다.
윗면을 실제로 접촉하고 8점을 측정하지만, 윗면 결과는 **접촉 시 TCP Z**로만 기록한다.
`top_z_m`, `bottom_z_m`, `work_z_range_m`은 null이고 `geometry_ready=false`, `validity=REFERENCE_ONLY`다.
SUCCEEDED는 이 단독 측정 목표의 완료이며 경로 생성용 기하 스냅샷 완성을 뜻하지 않는다.
밑면 오프셋을 독립 확인한 뒤 ABSOLUTE_GEOMETRY로 시험해야 절대 윗면 Z를 제공한다.

터미널은 기존 sodreal 환경을 사용한다. 패키지 디렉터리 기준 세 명령:

```sh
python3 test/workpiece_test_node.py --mode REAL --operator-ready
```

```sh
ros2 bag record -o /tmp/workpiece_trial_$(date +%Y%m%d_%H%M%S) /workpiece_test/feedback /workpiece_test/result /workpiece_test/telemetry /dsr01/joint_states /dsr01/error /rosout
```

```sh
ros2 service call /workpiece_test/start std_srvs/srv/Trigger '{}'
```

첫 명령은 대기만 한다. `--operator-ready`는 드릴 OFF, 양초/철사 고정 유지,
작업 공간 비움, 단독 제어, 비상정지 대기라는 현장 조건을 운영자가 확인한다는 뜻이다.
드릴 OFF를 센서로 검출하거나 네이티브 제어권을 자동 취득하지 않는다.
시작 서비스는 **접수**만 반환한다. 마지막 결과/정지는 result 토픽 또는 아래 status로 확인한다.
기본 출력 폴더 `/tmp/workpiece-unit-test`에도 센서·명령·진행·결과 JSONL을 저장한다.
telemetry 기록 실패가 정지 명령 송신을 막지 않도록 처리한다.

- 취소: `ros2 service call /workpiece_test/cancel std_srvs/srv/Trigger '{}'`
- 조회: `ros2 service call /workpiece_test/status std_srvs/srv/Trigger '{}'`
- 터미널 1 Ctrl+C: 취소 신호 후 정지 확인 작업이 끝날 때까지 executor를 유지한다.
- UNKNOWN 뒤 재시작은 수신부가 차단한다. 실제 상태/원인을 확인해야 한다.
- 시험 수신부는 기존 공정 노드와 동시에 사용하지 않는다. 공통 소유권 통합을 대체하지 않는다.

현재 REAL 설정은 9/21 현장 실험의 고정 양초와 장착 상태 전용이다. 새 현장의 범용 기본값이 아니다.
현재 관절 확인 → 검사한 통로로 홈 경유 → 홈 도착 확인 → 수직 상승 → 상공 이동 → 윗면 접근·접촉·수직 후퇴 → 상공에서 외곽 이동 →
수직 하강 → 중심을 바라보며 8점 측정 → 마지막 외곽 후퇴로 진행한다.
센서 접촉 판정을 독립 실측 정확도 인증으로 표시하지 않는다.

검증: 모의 시험 **106건**, 별도 ROS 도메인의 Trigger → 함수 → 8점 결과 모의 실행 통과.
실제 제어기 읽기 전용 검사: 윗면 238·옆면 745 표본의 IK/FK 및 제한된 현장 경로 모델 통과.
그리퍼 전체/케이블 메시를 포함한 연속 충돌 검사는 아니다. 첫 실물 시험에서 윗면 조기 접촉 후보가 검출되어 취소했고 STANDBY/정지를 확인했다.
이동 시작 힘 변화를 접촉으로 채택하지 않도록 윗면에도 이동 기준 힘을 적용하고, 기존 현장 접촉 Z 범위를 벗어나면 옆면 측정을 차단한다. 수정 후 실물 재시험은 사용자가 시작하며 아직 미실시다.
힘 한계·속도를 올리지 않았다. 접촉 여부는 사용자가 보지 못해 미확인이다.
기록 요약: `test/fixtures/workpiece_real_trial_0921.json`.

## 홈 경유 및 시간 목표 (9/21 후속 수정)

사용자가 기존 조각 실행기의 HOME을 명시적으로 선택했다. 기준은 **GripperDA_v1 TCP**
`[0.4218, 0.0001, 0.2644] m`, quaternion `[0,1,0,0]`이다. 도구 끝 좌표와 구별한다.
`workcell.home`에 출처와 허용차를 저장하며 현재 관절·TCP 관측은 결과의 `initial_state`에 남긴다.

- 이미 홈(위치 0.3 mm·자세 0.3° 이내): 준비·IK 검사와 홈 도착 상태만 확인하고 **홈 이동 명령을 보내지 않는다**. `home_move_skipped=true`로 기록한 뒤 측정으로 넘어간다.
- 홈이 아님: 양초 옆에서는 동일 자세로 방사선 바깥 이탈 → 수직 상승 → TCP Z 330 mm 상공에서 자세 정렬 → X/Y 분리 이동 → 홈으로 수직 하강.
- 윗면/홈의 확인된 수직 통로에서는 먼저 수직 상승한다. 홈 도착과 정지가 확인되어야 윗면 측정을 시작한다.
- **임의 자세의 일반 경로 탐색기는 아니다.** 양초 내부·방향 불명·확인된 작업 영역 밖·기울어진 시작 자세는 `HOME_PATH_UNAVAILABLE` 또는 `SCENE_REJECTED`로 거절한다. 자동 손목 풀기/관절 홈 직행/그리퍼 열기는 추가하지 않았다.
- 새 요청 시작 때의 홈 경유이며, 실패 후 홈으로 자동 이동하는 기능은 아니다. 실패·취소 처리 원칙은 동일하다.
- 홈 관절 숫자를 임의 생성하지 않는다. 현재 관절부터 같은 IK 가지의 연속성을 검사하고 최종 관절·TCP를 `home_state`에 남긴다.

진행에 `HOME_CHECK`, `HOME_MOVE`, `HOME_READY`가 추가된다. 탐색 중 2초마다
`probe_progress` telemetry와 터미널의 이동 거리/남은 거리/기준 힘 수집 여부를 표시한다.

이동 60 mm/s, 접근 30 mm/s, 이탈 5 mm/s로 시험 프로파일을 조정했다. 윗면 접촉 0.3 mm/s,
옆면 접촉 1 mm/s는 유지한다. 윗면 접근 시작은 기존 확인 범위 위 4 mm인 TCP Z 240.705 mm로
줄이며 탐색 하한은 그대로다. 이동 기준 수집(2~3.25 mm)이 가장 높은 예상 접촉 위치보다
위인지 검사한다. 빈 공간 기준 힘 변화 한계(기존 가드 5 N)와 수집 후 접촉 변화 한계(2 N)를
분리해, 기준 수집 전에 접촉 한계로 중단되던 문제를 수정했다. 원신호 접촉 한계 10 N은 유지한다.

**120초 완료 목표는 아직 달성하지 못했다.** 기록된 시작 위치와 현재 접촉 속도로 계산한
이동·기준 수집·정지 안정화 예상은 약 186초이며 IK·ROS 지연이 더해진다. 따라서
`target_duration_s=120`은 요청 목표, `runtime_timeout_s=300`은 실패 처리 상한이다.
시간초과를 완료로 표시하지 않으며 변경 속도/홈 경유의 실물 검증은 사용자가 실행할 후속 시험이다.
홈 경유 포함 983점의 제어기 IK/FK 조회는 통과했다. 조회 검사만 약 36.6초였고 실제 이동은 없었다.
근거: `test/fixtures/workpiece_home_preflight_0921.json`. 기존 실행 중인 시험 수신부는 종료 후 다시 실행해야 수정본이 적용된다.

## 호출 경계

1. 대쉬보드 → 세은의 제어 노드: 준비·측정 Action 요청(이름/필드는 합의 전).
2. 세은: 로봇 준비 상태 검사 후 `measure_workpiece()` 내부 함수 호출.
3. 우리 모듈 → 세은 제어 노드 → 대쉬보드: 진행 Feedback과 최종 측정 Result.
4. HMI → 홍동: 실측 스냅샷으로 경로 생성 → 미리보기.
5. 조각 실행 요청 → 세은의 최종 경로·관절 검사 → 시율 `execute_path()` 호출.

별도 시율 측정 Action 서버는 만들지 않는다. 세은의 제어 노드가 측정과 조각의
공통 모션 소유권을 관리한다. 측정용 IK/FK 검사는 시율 측정 어댑터에서 수행하며,
세은 `joint_check.py`를 수정하거나 이 모듈에서 호출하지 않는다.

## 현재 구현·확인 수준

| 항목 | 상태 |
| --- | --- |
| 윗면 측정 → 45° 간격 옆면 8점 → 원 맞춤 → 마지막 후퇴 확인 | 코드 + 기하 모의 시험 |
| 시작/윗면/점별 성공/완료 Feedback 콜백 | 코드 + 모의 시험 |
| 취소·실패·시간 초과·통신 단절·정지 미확인 | 코드 + 장애 주입 시험 |
| 중심과 반지름을 동시에 추정 | 기존 8점 실측 자료 재계산 대조 |
| REAL 서비스 I/O/관측/정지/접촉/IK·FK 어댑터 | 코드 + 가짜 I/O + 실제 ROS 이동/취소·정지 확인. 전체 측정 성공 및 수정 후 재시험 미완료 |
| 운영 준비 Action 수신부 및 `.action` 타입 | 미구현. 시험용 Trigger 수신부와 구분. 수현·세은과 계약 필요 |
| 그리퍼 밑면 접촉점 오프셋 | REAL 미확인. SIM 예제의 10 mm는 합성값 |
| 현장 진입·원호·후퇴 검사/모션 소유권 | 제한된 현장 단독 시험용 연결 구현. 공통 제어 노드 소유권 통합은 별도 |

기존 시험의 176초는 옆면 8점 재측정의 기록이다. 이번 윗면 포함 함수의 3분 완료나
실기 정확도를 확인한 기록이 아니다. 새 코드의 REAL 실행은 이 문서만으로 승인되지 않는다.

## 파일

- `c2_process/workpiece_calibration.py`: 측정 순서·설정 검사·이벤트·원 맞춤·StepResult.
- `c2_process/measurement_robot_adapter.py`: 측정 전용 내부 어댑터. 실제 상태/힘/관절 조회,
  표본 IK/FK 검사, 비동기 이동 후 완료 확인, 접촉 후 정지 확인. 새 ROS 노드는 아니다.
- `c2_process/workpiece_simulation.py`: ROS를 전혀 호출하지 않는 원통 기하 모의 백엔드.
- `config/workpiece_simulation.json`: 바로 호출 가능한 SIM 설정. REAL 사용 금지.
- `config/workpiece_trial_guards.json`: 이전 시험을 출처로 한 검토용 가드 설정.
  제조사 관절 사양이나 새 실행 코드의 실기 인증값이 아니다.
- `test/workpiece_simulation_demo.py`: 수신부 내부 호출 예제, 실행 가능한 모의 데모.

기존 `robot_adapter.py`, `engraving.py`, `tool_calibration.py`와 다른 담당의 파일은 수정하지 않았다.

## 바로 호출하기

패키지 디렉터리에서:

```sh
python3 test/workpiece_simulation_demo.py
python3 -m pytest -q test/test_workpiece_calibration_mock.py test/test_measurement_robot_adapter_mock.py
```

```python
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece
from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter

ctx = MeasurementContext(
    measurement_id="measurement-001",
    preparation_id="preparation-001",
    source_mode="SIMULATION",
    motion_lock=shared_motion_lock,
)
adapter = SimulatedWorkpieceAdapter(config["workcell"], clock=ctx.monotonic)
result = measure_workpiece(
    adapter, config["workcell"], config["profiles"], ctx,
    on_progress=publish_feedback,  # 수신부에서 Action Feedback으로 변환
)
```

`config`는 JSON을 읽은 사전, `shared_motion_lock`은 수신부가 보관하는 공통 Lock,
`publish_feedback`은 콜백이다. 모의 데모에는 이 세 가지의 실행 가능한 예가 들어 있다.
측정은 동기 함수이므로 Action 콜백에서 executor를 막지 않도록 작업 스레드에서 실행한다.

취소는 `ctx.cancel.set()`으로 전달한다. 이후 반환이 STOPPED인지 UNKNOWN인지 확인하고
Action의 canceled/aborted 상태로 변환한다. 취소 요청 접수 자체를 정지 완료로 표시하지 않는다.

## 동작과 좌표

- 길이: m, 힘: N, 자세: `[x,y,z,qx,qy,qz,qw]`, 관절: rad, 좌표계: `c2_base`.
- 입력/어댑터 내부 목표 pose는 드릴 끝 기준. native TCP mm/ZYZ 변환은 어댑터가 담당한다.
- 윗면은 **그리퍼 밑면**으로 접촉한다. 드릴 끝 관측 pose에서 도구 오프셋을 빼 TCP를
  복원하고, 그리퍼 밑면 오프셋을 더해 실제 접촉점 Z를 계산한다.
- 옆면은 tool -Y가 중심을 보고 tool +Z가 base -Z를 향하도록 8점 생성한다.
- 기준 중심·반지름은 탐색 경로를 정하는 입력이다. 최종 원 맞춤에서는 둘 다 자유 변수다.
- 150 mm 높이는 `height_source=OPERATOR_RULER`로 재사용한다. 로봇이 높이까지 독립적으로
  재측정했다고 표시하지 않는다. `bottom_z=top_z-height`는 계산값이다.
- 위/아래 10 mm 제외 → 윗면 기준 아래쪽 v=10~140 mm,
  base Z 범위 `[top_z-0.140, top_z-0.010]`.
- 수직 원통 가정. 기울기·테이퍼·가공 깊이 정확도는 이번 측정으로 검증하지 않는다.
- 최초 진입 및 윗면→옆면 이동은 임의로 안전하다고 가정하지 않는다. REAL의 `scene_check`
  콜백이 현재 위치부터 탐색 끝점·접촉 후 후퇴 전체를 검사해야 다음 단계가 시작된다.

## Feedback 사전

| 필드 | 의미 |
| --- | --- |
| `measurement_id` | 요청자가 발급한 측정 ID |
| `sequence` | 해당 호출에서 1부터 증가하는 이벤트 번호 |
| `measured_at` | 이벤트 생성 UTC 시각(센서 취득 시각과 다름) |
| `stage` | START / HOME_CHECK / HOME_MOVE / HOME_READY / TOP_APPROACH / TOP_TOUCH / SIDE_START / SIDE_TOUCH / FIT / COMPLETE / TERMINAL |
| `status` | RUNNING / SUCCEEDED / FAILED / STOPPED / UNKNOWN |
| `point_index`, `total_points` | 윗면은 0, 옆면은 1~8; 전체 옆면 점 수 8 |
| `message` | 화면 표시 문구 |
| `values` | 확보한 윗면 Z 또는 점 좌표, 마지막에는 최종 결과 |

초록색은 `TOP_TOUCH` 또는 `SIDE_TOUCH`의 SUCCEEDED에서 표시한다. 명령 수락만으로 보내지
않으며 접촉 판정·실제 정지·측정값 유효성을 확인한다. 8번째 점 성공과 마지막 외곽 후퇴 완료는
다른 사건이다. 전체 성공은 Action 최종 Result까지 확인해야 한다.
HMI는 이벤트를 ID/sequence 기준으로 저장해야 새로고침 후에도 이력을 볼 수 있다.
콜백에는 복사본을 전달한다. 콜백 예외는 통신 전달 실패로 취급하여 정지를 확인하고 종료한다.

## 최종 StepResult

`result.observed_state`:

- `measurement`: 중심 `axis_xy_m`, `radius_m`, 윗면 `top_z_m`, 높이·출처,
  바닥 Z, 작업 높이 범위, 각 접촉점·법선 힘, 원 맞춤 RMS/최대 잔차, 유효성.
- `measurement.source_mode`: SIMULATION / REAL. SIM 결과의 `validity`는 SIMULATED.
- `measurement.geometry_ready`: 해당 실행 모드에서 기하 계산·수집이 완료됐는지.
  이것만으로 실기 조각/충돌/깊이 정확도 검사가 끝났다는 뜻이 아니다.
- `measurement.measured_at`: 결과 계산 완료 UTC. `started_at`은 시작 UTC.
  접촉점에는 센서 관측 `measured_at_monotonic_s`와 전달 `received_at`을 구분한다.
  monotonic 값은 PC 간 절대시각 비교에 사용하지 않는다.
- `measurement.profile_snapshot_id/profile_sha256`: 호출자가 전달한 등록 스냅샷 참조.
  이 함수가 HMI 최종 파일 바이트의 해시를 발급/검증하지 않는다. 수신부가 파일을 확인한다.
- `plans`: 실제 검사에 넘긴 계획·설정 객체의 내부 SHA-256과 검사 보고.
  이 해시를 HMI 파일의 profile_sha256으로 대신 쓰지 않는다.
- `events`: 이번 호출의 진행 이력, `partial`: 미완료 여부, `stop_confirmed`: 정지 확인,
  `elapsed_s`: 사전 검사와 전체 측정을 포함한 함수 소요 시간.

| outcome | 의미 |
| --- | --- |
| SUCCEEDED | 윗면·8점·형상 검사·마지막 후퇴 완료 |
| FAILED | 입력/준비 불충족 또는 동작 실패. 동작 시도 뒤에는 정지 확인된 실패 |
| STOPPED | 취소됨. 동작 시도 뒤에는 실제 정지 확인 |
| UNKNOWN | 동작/정지 결과 확인 불가. 성공으로 바꾸거나 다음 작업 호출 금지 |

이동을 시도하지 않은 초기 실패/취소에서는 `stop_confirmed=null`이다. 불필요하게 다른
작업의 로봇에 정지 명령을 보내지 않는다. 실패·취소 후 자동 후퇴, 홈 이동, 재전송은 없다.
부분 접촉점은 보존하되 `geometry_ready=false`, `validity=INCOMPLETE`로 반환한다.

## REAL 연결 계약

`GuardedMeasurementAdapter`는 다음 의존성을 받는다.

- `io=RosMeasurementIO(node, controller_prefix, timeout_s)`: 별도 스레드에서 spinning 중인
  기존 executor/node를 사용한다. `controller_prefix`는 ROS namespace이며 파일 절대경로가 아니다.
  설치된 Jazzy dsr_msgs2 소스 대조 및 첫 단독 실물 시험에서 실제 조회·이동·정지 호출을 확인했다.
- `tool_offset_m`: 승인한 고정 장착 기준. workcell 설정과 일치해야 한다.
- `guards`: 위 검토용 JSON과 같은 키의 명시적 설정. 하드웨어 보호 설정을 바꾸지 않는다.
- `readiness(context)`: 최신 로컬 상태를 읽어 `measurement_id`, `checked_at_monotonic_s`,
  `ownership_confirmed`, `drill_off_confirmed`, `mount_fixed`, `control_authority`를 반환한다.
  값을 상수 True로 채우는 실행용 콜백은 허용하지 않는다. 매 감시 주기 호출되므로 비차단 조회여야 한다.
- `scene_check(steps, workcell, initial_observation)`: 전체 진입/전환/원호/탐색/후퇴와 도구 형상의
  간섭 검사를 수행해 `path_checked`, `probe_envelopes_checked`와 검사 기록을 반환한다.
  표본 IK 통과를 충돌 검사 통과로 대신 쓰지 않는다. 단독 시험에는 workpiece_real_trial.check_trial_scene를 연결한다. 범용 현장 검사기를 뜻하지 않는다.

ABSOLUTE_GEOMETRY의 REAL workcell에는 `tcp_id`, `load_id`, `top.offset_status=VERIFIED`, `top.offset_record_id`와
실제로 확인된 `top.contact_offset_tool_m`가 필요하다. ctx에는 등록 스냅샷 ID/해시가 필요하다.
미확인 그리퍼 밑면 오프셋을 0이나 SIM의 10 mm로 채워 실행하면 안 된다.

측정 어댑터는 모든 계획 구간을 설정 간격으로 보간하여 고정 solution space의 IK/FK와
관절 범위·연속성을 확인한다. ZYZ B=180°에서 A/C 표현에 의한 가짜 장회전을 줄여 같은 표현을
명령에도 사용한다. 제어기 내부의 연속 궤적/완전한 충돌 검증은 아니며 실기 대조가 필요하다.

Action 수신부에서 추가로 구현할 것:

1. `.action` 이름·필드와 HMI 변환. 이 모듈의 내부 사전 형식을 기존 ROS 계약으로 오인하지 않는다.
2. 동일 측정 ID의 중복 요청 거절/이전 결과 반환. 함수 자체는 요청 원장을 관리하지 않는다.
3. 측정·조각 공통 소유권/취소·비상정지 연결. `MeasurementContext.motion_lock` 기본값은
   **컨텍스트 하나의 Lock**뿐이므로 여러 요청은 반드시 서버의 공유 Lock을 전달한다.
   별도 프로세스 간 배타 제어는 이 Lock으로 해결되지 않는다.
4. HMI 스냅샷 파일 해시 확인, 최종 결과 저장·스냅샷 등록, 측정 변경 시 경로 재생성.

## 검증

기존 패키지 시험 포함 106건 통과:
정상 윗면/8점, 점별 Feedback, 독립 원 맞춤, 기존 8점 기록 재계산,
잘못된 입력/좌표계/오프셋, 미지원 어댑터, 중복 동시 실행 Lock,
취소 전/중, callback 오류, 실제 정지 미확인, 통신 단절, 시간 초과,
잘못된 접촉 위치, 사전 검사 누락/실패, 마지막 후퇴 실패,
목표 미도달/가짜 조기 완료, ZYZ 단회전, 힘 한계와 윗면/옆면 접촉 모의.
운영 Action 통합 및 절대 윗면 검증은 미실시다. 단독 시험 수신부와 제어기 조회 검증은 상단 추가 기록 참조.
