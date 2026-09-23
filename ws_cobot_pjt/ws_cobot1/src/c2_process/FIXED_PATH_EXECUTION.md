# 조각 실행기 선택

기준: `4d5034e` (최신 main 반영 후 수정). 공정 호출은 그대로 `engraving.execute_path(path, context, on_progress, adapter)`이며 반환은 `StepResult`다. 공정 노드·Action·Topic 정의는 바꾸지 않는다.

| 기존 설정 `context.tool_profile.contact_mode` | 호출할 구현 | 동작 |
| --- | --- | --- |
| `force_touch` | `engraving.py`의 기존 실행 | 획 시작 접촉 탐색과 실제 접촉 보정 |
| `fixed_depth` | `c2_process/run_fixed_path_trial.py:execute_path` | 표면 경로에 설정 깊이를 한 번 적용한 최종 경로를 실행. 접촉 탐색·획별 재보정 없음 |

설정은 **스냅샷 등록·경로/최종 계획 검사 전에** 선택한다. 기존 스냅샷을 실행 직전에 수정하거나, 실패한 실행 중 자동으로 다른 실행기로 넘기지 않는다. 모드 변경도 기존 설정 서명 검사 대상이므로 설정을 갱신한 뒤 다시 검사한다. 둘 다 같은 `robot_adapter.py`를 사용하며 어댑터·드라이버 장애를 우회하는 기능은 아니다.

## 동일한 호출

기존 공정에서는 import나 인자를 바꿀 필요가 없다. 기존 `fixed_depth` 설정이면 새 고정 경로 모듈로 분기한다.

```python
from c2_process.engraving import execute_path
result = execute_path(path, context, on_progress, adapter)
```

직접 주입하는 단위시험 또는 기존 `ProcessCoordinator(engrave_fn=...)` 구성에서도 동일하게 호출할 수 있다.

```python
from c2_process.engraving import execute_fixed_depth_path
result = execute_fixed_depth_path(path, context, on_progress, adapter)
```

9/23 정리로 본문은 `engraving.py`가 소유한다. 기존 `from c2_process.run_fixed_path_trial import execute_path`
경로는 같은 함수를 가리키는 얇은 wrapper로 유지하므로 기존 호출부는 고치지 않아도 된다.

직접 호출도 `fixed_depth` 설정을 요구한다. 함수가 `force_touch` 설정을 몰래 바꾸지 않는다. 깊이가 반영된 내부 검사 계획을 원본 표면 경로인 것처럼 다시 넣으면 거절한다.

## 보장과 범위

- 원본 경로·단위·좌표계·구간 순서를 보존한다. 깊이는 계획 생성 시 한 번 반영하고, 명시 waypoint의 IK·관절·J6 검사에 전달한 점을 실행한다.
- APPROACH/TRAVEL/RETRACT는 직선, CUT은 첫 점 직선 진입 뒤 기존 한도 내 spline으로 보낸다. 한 점 남으면 직선을 사용한다.
- 경로/설정/도구 오프셋 서명, 취소, 이동 실패와 정지 미확인을 유지한다. 접수 불명 명령을 자동 재전송하지 않는다.
- 공정 노드의 제어권·최신 관측·정지·TCP/하중·해시·독점 실행 검사는 그대로 유지한다. 이 모듈만 호출해서 공정 사전검사를 대신할 수는 없다.
- `SUCCEEDED`는 경로 이동 완료다. 내부 결과에는 `touches=[]`, `contact_verified=false`, `engraving_quality_verified=false`, `execution_mode=FIXED_PATH_REPLAY`를 기록한다. 기존 진행 콜백 형식은 그대로다.
- 현재 공통 IK 검사는 명시 waypoint 검사다. 실제 spline 보간 궤적이나 로봇 전체 형상의 충돌 검사까지 완료한 것으로 해석하지 않는다.

## 로컬 단독 시험기와 차이

기존 `/tmp/c2-direct-character-20260922/run_fixed_path_trial.py`는 별도의 현장 단독 실행기로 남겨둔다. 패키지 안의 `engraving.execute_fixed_depth_path`(구 `run_fixed_path_trial.execute_path`)는 그 단순 경로 실행 방식을 공정 함수 계약에 맞춘 버전이다. 개인 PC 경로·현장 고정값·별도 ROS 노드·통신 자동 복구는 이관하지 않는다. 배포에는 패키지 안의 파일을 사용한다.

## 검증

`test_fixed_path_module.py`에서 동일 함수 형식, 설정별 분기, 접촉 호출 없음, 깊이 1회 적용, 검사/실행 점 일치, 실패 시 후속 이동 차단, 취소·설정 변경·접수 불명을 검사한다. 기존 조각·실행계획·공정 시험도 함께 대조한다. 실물 조각 및 HMI 전체 통합 검증은 별도로 남아 있다.


## 공정 어댑터 연결과 기한

- `DoosanRobotAdapter(node, ..., initialization_timeout_s=5.0)`는 기존 드라이버의 특이점 회피 설정 `mode=0`만 기한 내 확인한다. `DSR_ROBOT2` 전역 노드 초기화·무제한 서비스 대기·고정 1초 대기는 사용하지 않는다. 초기화 실패는 예외로 반환해 노드 기동 측이 처리한다.
- 공정 executor가 실행 중이면 별도 작업 스레드에서 호출한다. 서비스 응답은 기존 executor가 처리한다. 이미 다른 executor에 등록돼 있으나 spin하지 않는 노드는 즉시 오류다. executor에 미등록된 단독 초기화만 임시 spin을 사용한다.
- 이동·spline은 비동기 서비스 접수와 실제 완료 관측을 구분한다. 시작 관측, 목표 위치/자세, `STANDBY`·motion=0, 정착을 확인한다. 폐곡선은 시작점과 종점이 같다는 이유로 완료 처리하지 않는다.
- 접촉 전 TCP·힘 기준선과 접촉 중 조회는 하나의 `deadline_s`를 나눠 쓴다. 각 모션/접촉 서비스 응답 대기는 최대 2초이면서 남은 기한 이하이다. 기한 만료·취소 후 들어온 접촉값으로 성공 처리하지 않는다.
- 이동 중 취소·통신/응답 불명확 시 다음 명령을 보내지 않고 기존 QSTOP(mode=1) 후 실제 정지를 별도 최대 2초 동안 확인한다. 따라서 오류 반환 시 전체 경과시간은 동작 기한에 정지 확인 시간을 더한 범위까지 걸릴 수 있다. 정지 접수만으로 `STOPPED`를 확정하지 않는다. 자동 재전송·자동 재개는 없다.
- 공정의 기존 `stop()` → 공유 cancel → 어댑터 정지 → `_finalize_stop()` 흐름을 유지한다. 공정 런타임 코드는 이번 PR에서 수정하지 않는다.

## 측정·실행 설정 연결 확인

최신 main의 HMI `real_bound_profile()`은 측정 설정 `workcell.tool_offset_m`과 실행 설정 `tip_calibration.offset_tool_m`을 비교해 불일치를 스냅샷 생성 전에 거절한다. 이번에는 이를 중복 구현하지 않고 실제 HMI 조립 → `resolve_real_execution_settings()` 연결 시험을 추가했다. 동일 값은 `tool_offset_m`으로 실행 설정에 전달된다. 그리퍼 밑면용 `contact_offset_tool_m`은 별개이며 드릴 오프셋으로 대체하지 않는다.

`absolute_top_verified`·`validity` 계산 코드는 변경하지 않았다. 연결 시험에서도 원본 `ESTIMATED`·`false`가 보존되는지 확인한다. 이 검증은 기존 HMI 경유 입력 범위이며, 임의로 만든 스냅샷의 출처/기하 일치 검사를 대신하지 않는다.

## 재현 가능한 대역 시험

패키지 루트에서 다음 관련 시험만 실행한다. 로봇에 연결하거나 모션 명령을 보내지 않는다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  test/test_robot_adapter_motion.py test/test_fixed_path_module.py \
  test/test_engraving_mock.py test/test_execution_plan.py test/test_node.py \
  test/test_measurement_execution_offset.py
```

오프셋 연결 시험은 저장소의 backend와 c2_path를 함께 import하며 해당 Python 의존성이 필요하다. ROS 대역 시험은 Jazzy와 dsr_msgs2 환경을 source한 뒤 실행한다. UUID namespace의 서비스 대역을 사용한다.

```bash
ROS_DOMAIN_ID=173 ROS_LOCALHOST_ONLY=1 C2_RUN_ADAPTER_ROS_TEST=1 \
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  test/test_robot_adapter_motion_ros.py test/test_robot_adapter_executor_ros.py
```

ROS 시험은 초기화, 이동·폐곡선 spline·IK·접촉, 공정 정지 요청과 동시 실행, 응답 지연, 정지 미확인, executor/상태 타이머 유지 범위다. 실제 드라이버 응답 지연·실제 절삭 깊이·spline 보간 간섭·HMI 전체 왕복은 실기 시험에서 별도 확인한다.
