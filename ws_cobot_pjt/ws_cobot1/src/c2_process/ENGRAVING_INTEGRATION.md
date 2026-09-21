# 조각 공통 코드 연결 변경 — 2026-09-21

이시율 담당 `engraving.py`, `robot_adapter.py`의 로컬 수정이다. 김세은 담당 node/state_machine/preconditions/joint_check는 수정하지 않았다. PR 제출 전 사용자 검토가 필요하다.

## 실기 근거와 이번 변경

9/20 `cut_heart_20260920_151004.jsonl`/`cut_heart_result.json`은 125/125 명령, 178.617초, 사용자 하트 연결 확인 기록이다. **명령 모델 깊이는 0.3 mm**이며 홈의 실제 깊이 측정값은 아니다. 별도 실행기의 고정 깊이·직선 실행·이동 시작/완료 확인 방식을 공통 코드에 이관했다. 별도 실행기의 모든 현장 검사와 전체 실행기를 그대로 복제한 것은 아니다.

- CUT 점에 목표 깊이를 **검사 전 한 번** 적용한다. 중심/높이를 재이동하지 않는다.
- 원본 경로를 보존하고 파생 실행 계획을 만든다. HMI의 원본 ID·버전·파일 해시는 유지한다.
- 실행 도중 점 축소·힘 기반 깊이 누적·기울기 보정을 하지 않는다. 입력받은 최종 점을 직선 이동한다.
- 시작을 관측하기 전에는 끝점에 가까워도 완료하지 않는다. STANDBY + CheckMotion IDLE + 위치/회전 오차 + 안정 시간을 확인한다.
- 공통 move/move_spline/IK/관측은 직접 ROS 서비스로 호출하고 공유 executor를 중첩 spin하지 않는다. 생성자의 무기한 서비스 대기/동작 설정 변경을 제거했다.
- 실패 시 임의 후퇴나 무동작 추정 재전송을 하지 않는다. 정지 확인 결과를 보존하고, 확인이 없으면 UNKNOWN을 반환한다.
- 기존 force_touch 실험 분기는 SIM 호환으로 남는다. REAL에서는 준비·검사를 거친 fixed_depth 계획이 필요하다. 옛 probe_touch와 도구 전체 보정 절차는 이번 이관 범위가 아니다.

## 세은님 호출 순서

```python
from c2_process.engraving import prepare_execution_path, execution_path_digest, execute_path

# 1. 원본 파일/스냅샷 무결성 및 현재 로봇 상태 검사: 공정 담당
final_path = prepare_execution_path(source_path, ctx)
checked_digest = execution_path_digest(final_path)
# 2. check_path_joints에 source_path 대신 final_path 전달
#    현재 자세 → 첫 점, 구간 연결/이탈, 보간/간섭의 확인도 필요
# 3. 필요한 최종 검사를 통과한 경우에만 다음 값을 기록
ctx.prechecked_execution_sha256 = checked_digest
result = execute_path(final_path, ctx, on_progress=on_progress, adapter=adapter)
```

위 주석 2~3은 통합 위치 설명이며 검사 생략을 허용하는 실행 스크립트가 아니다. 현재 joint_check는 CUT을 4점 간격으로 검사한다. **모든 점·보간·충돌을 검사했다고 주장할 수 없으며**, 그 검사 범위와 진입 경로 보강은 김세은 담당과 연결해야 한다. 관절 검사 결과 자체가 아닌, 검사한 경로/설정의 일치 여부를 이번 해시가 보장한다.

### 입력

기존 `ExecutionContext`에 `prechecked_execution_sha256: Optional[str]`만 추가했다. 기본값 None은 REAL 실행 승인 아님.

- `tool_profile`: `contact_mode="fixed_depth"`, `depth_m`, `clearance_m`, `tool_axis`, `tool_offset_m` 필요. 선택 `max_depth_m`. `adaptive_max_m`, `surface_z_gradient`, `cut_monitor` 등 실행 중 좌표 변경 실험 설정은 제거한다. 힘 상한은 아래 이동 프로파일에 둔다.
- `motion_profiles`: 각 사용 프로파일의 `vel_mm_s`, `acc_mm_s2`, `completion_timeout_s`. REAL 추가 필수: `angular_vel_deg_s`, `angular_acc_deg_s2`, `pos_tol_mm`, `angle_tol_deg`, `force_limit_n`, `start_timeout_s`, `completion_settle_s`.
- `stop_profile`: `mode`, `confirmation_timeout_s`. 이동 중 중단에도 같은 정지 프로파일이 전달된다.
- `adapter.tool_offset_m`은 검사 설정의 `tool_offset_m`과 같아야 한다. 단위 m, 도구 좌표계 오프셋.
- 준비/조각 간 공유 motion_lock, 실행 취소 Event, 도구/TCP/하중/제어권·실측 유효성 확인은 공정의 기존 책임이다. 함수는 executor 응답을 처리할 수 있는 작업 스레드에서 호출한다.

9/20 확인된 예시: 깊이 0.0003 m, 고정 장착 오프셋 `[0.00085,-0.09955,0]` m, 직선 속도 상한 5 mm/s·가속도 10 mm/s², 완료 위치/자세 허용차 0.15 mm/deg·안정 시간 0.2 s·시작 제한 3 s. raw 힘 상한은 당시 10 N이었다. 이는 **해당 실험 조건의 근거**이며 전체 작업 공간·새 양초·모든 이동에서 검증된 공통 승인값이 아니다. 이번 수정은 기존 설정 파일의 값을 자동 교체하지 않는다.

### 해시/반환 의미

`execution_path_digest()`는 정렬·압축 JSON 객체 SHA-256이다. HMI가 저장한 **파일 바이트 해시와 별개**다. 깊이 적용 후 path의 validation은 passed=false로 무효화한다. execution_plan에 원본 객체 해시·깊이·직선 방식·실행 설정을 넣는다. 외부 원본 파일 검증 → 실행 계획 생성 → 최종 검사 → 동일 계획 실행의 순서다.

`StepResult.observed_state`는 마지막 완료 구간, 진행률, execution_sha256 및 어댑터의 정지/오류 관측을 보존한다. SUCCEEDED는 경로 실행 완료이며 실제 홈 깊이 합격이나 공정 홈 복귀 완료를 의미하지 않는다. STOPPED는 실제 정지 확인이 있는 취소, UNKNOWN은 이동/정지 결과 미확인이다. 시간 초과 후 실제 정지 확인이 되면 FAILED/TIMEOUT, 정지까지 미확인이면 UNKNOWN/STOP_UNCONFIRMED다.

## 검증과 남은 연결

- 핵심 회귀 14개: 깊이 1회·원본 보존·점 누락 없음·경로/설정/오프셋 변경 차단·콜백에 의한 입력 변경 차단·취소/정지 미확인·폐곡선/자세만 이동·명령 응답 소실 시 중복 전송 없음.
- 설치된 ROS srv 요청 필드 확인 및 별도 domain의 프로세스 내부 가짜 서비스로 공유 executor 응답 확인. 실제 제어기 왕복 시험 아님.
- 새 공통 코드로 실기 조각은 아직 하지 않았다. 구형 run_engrave_real.py는 동적 재보정 경로로, 그대로 실행하면 새 REAL 조건에서 거절된다. 검사/프로파일 연결을 바꾼 뒤 사용해야 한다.
- 세은님 최종 검사와 본 실행 계획 연결, 최종 경로 전 점/구간 연결 및 보간/간섭 확인, 현재 장착 상태의 실제 ROS 실행 검증이 남았다. 이 문서만으로 전체 통합 완료라고 하지 않는다.
