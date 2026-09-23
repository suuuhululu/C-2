# 양초 측정 노드 수정 — 최종 자료 회신

담당: 이시율 (3반 09112) · 작성 2026-09-23 · 패키지 `c2_process`

---

## 0. 요약

**8점 측정 실기 성공** (2026-09-23 15:02). 요청 5개 항목 전부 실측 자료로 채웠습니다.

| # | 요청 항목 | 상태 |
|---|---|---|
| 1 | 측정 노드 수정 코드 (브랜치/SHA/파일) | ✅ 커밋 2건 (`8372f57`, `28ff186`) — **미push** |
| 2 | 수정 후 8점 측정 결과 원본 JSON | ✅ 첨부 `prepare_workpiece_result_20260923_1502.json` |
| 3 | 실제 사용한 측정 설정값 | ✅ |
| 4 | 7번 점 후퇴 `FORCE_LIMIT` 처리 결과 | ✅ 원인 확정 · 정책 변경 · 실기 검증 |
| 5 | 검증 결과 | ✅ 단위시험 1002건 · 실기 8/8 · **Action 경로는 미검증** |

**승인값 관련 — 갱신 권고.** 기존 승인값(14:27 7점)과 이번 8점 결과의 차이는 중심 0.54 mm, 반지름 −0.03 mm, top_z −0.16 mm 입니다. 이번 결과는 8점 전부·잔차 절반·FIT 통과·HOME 복귀까지 완료된 **완전한 측정**이므로, 최종 설정에는 이번 값 사용을 권합니다. 어느 쪽을 쓰시든 두 값은 서로 0.5 mm 안에 있습니다.

---

## 1. 측정 노드 수정 코드

### 브랜치 / 커밋 SHA

```
브랜치      fix/workpiece-measurement-baseline-and-move-recovery
분기 기준   54230b6
커밋 1      8372f57a70fcde0011fa0633dd4c1cb1fda9d329   기준힘 게이트 삭제 · 이동 복구 · JSON 수정 · 구조 정리
커밋 2      28ff186c26fa8b6c84d518a6139a779e35873b31   비접촉 구간 자세 의존 외력 정책
상태        로컬 커밋 완료, push 전 (Issue 번호 연결 후 push·PR)
```

### 변경 파일 목록

**커밋 2 (`28ff186`) — 이번 정책**

| 파일 | 증감 | 내용 |
|---|---|---|
| `c2_process/measurement_robot_adapter.py` | +76 −? | `_noncontact_force_verdict()`, `_candle_gap()`, `_check()` 확장, 경고 기록 |
| `c2_process/workpiece_calibration.py` | +7 −1 | 결과에 `force_warnings[]` 수집 |
| `config/workpiece_real_trial_0921.json` | +1 | `guards.noncontact_hard_force_n: 15.0` |
| `test/workpiece_test_node.py` | +5 | 경고 콘솔 로그 |
| `test/test_noncontact_force_policy_mock.py` | +228 신규 | 정책 시험 18건 |
| `test/fixtures/force_limit_20260923.json` | +114 신규 | 실기 12:43·14:27 관측값 고정 |

**커밋 1 (`8372f57`) — 앞선 수정** (19파일, +2725 −400)

| 파일 | 내용 |
|---|---|
| `c2_process/measurement_robot_adapter.py` | 기준힘 게이트 3줄 삭제, `_deviation_error()`, `check_measurement_scene` 흡수 |
| `c2_process/workpiece_calibration.py` | `MoveRecoveryError`, 이동 복구 핸들러, `MOTION_INCOMPLETE` 복구, JSON 키 수정 |
| `c2_process/engraving.py` | `execute_fixed_depth_path()` 흡수 (구조 정리) |
| `c2_process/run_fixed_path_trial.py` | 본문 이관 → 9줄 wrapper |
| `c2_process/workpiece_real_trial.py` | `check_trial_scene` 이관 → 별칭 |
| `c2_process/workpiece_process_adapter.py` | import 경로 |
| `config/workpiece_real_trial_0921.json` | `hard_line_error_mm`, `move_recovery_max_attempts` + 복원값 |
| `test/test_move_recovery_mock.py` 등 시험 8파일 | 신규·교체 |
| `README.md` / `FIXED_PATH_EXECUTION.md` / `WORKPIECE_CALIBRATION.md` | 문서 |

> 커밋 1에는 9/21~9/23 측정 작업의 기존 미커밋 변경(`robot_adapter.py` 힘 유지, 조각 v2 시험)이 함께 들어 있습니다. 파일·시험 단위로 분리가 불가능해 자립하는 최소 집합으로 담았고, 깨끗한 worktree 검증을 3회 거쳤습니다. 측정 외 변경분은 이번 수정이 만든 것이 아닙니다.

### 수정 내용 요약 (4건)

| # | 수정 | 근거 | 실기 검증 |
|---|---|---|---|
| 1 | 이동 기준힘을 정지 기준힘과 비교해 거절하던 조건 삭제 | 이동 시 힘 추정값이 상수 점프(1.65 N). 이동 기준힘이 흡수해야 할 값을 스스로 거부 | 11:54 0/8 → 12:23 1/8 |
| 2 | `PATH_DEVIATION` / `MOTION_INCOMPLETE` 자동 복구 | 0.504 mm 이탈은 서보 추종 오차(지시 TCP는 선분 위 0.08 mm) | 12:43 · 15:02 복구 후 계속 |
| 3 | 결과 JSON 직렬화 버그 (tuple 키) | 12:43 7점 결과 발행 실패 원인 | 14:27 이후 정상 |
| 4 | 비접촉 안전 구간 자세 의존 외력 → 경고 후 계속 | 4절 | **15:02 8/8 완주** |

---

## 2. 8점 측정 결과 원본 JSON

**원본 파일**: `prepare_workpiece_result_20260923_1502.json` (51,358 bytes, 첨부)
**출처**: `/tmp/c2-eight-point-retry-test/results/workpiece_155bed9063674d239e944f24cf32b583.jsonl` 의 `result` 레코드
**measurement_id**: `workpiece-test-0306ab602d78458c995b2d4f4c60ce11`
**measured_at**: `2026-09-23T06:07:38.447423+00:00` (UTC) = 15:07 KST
**profile_sha256**: `fe2e7f42efca1f21…` (원본 참조)

```
outcome             SUCCEEDED
error_code          NONE
message             (빈 문자열)
validity            FORCE_CONTACT_ESTIMATE
geometry_ready      true
partial             false
stop_confirmed      true
home_return_confirmed  true
```

### 기하 결과 (c2_base, m)

```
axis_xy_m           [0.42325530708859205, 0.00032844108604387424]
radius_m            0.03389996884310031          (33.900 mm / 지름 67.800 mm)
top_z_m             0.21576846313740472
bottom_z_m          0.06576846313740473          (top − height 0.15)
top_tcp_contact_z_m 0.23576846313740472
residual_rms_m      0.000046823255894381384      (46.8 um)
residual_max_m      0.00007330182285604503       (73.3 um)
work_z_range_m      [0.07576846313740472, 0.2057684631374047]
work_v_range_m      [0.01, 0.14]
height_m            0.15                          (height_source OPERATOR_RULER)
```

### contact_tip_poses 8개 (드릴 끝, c2_base, m)

| contact_index | 각도 | x | y | z | normal_force_n |
|---|---|---|---|---|---|
| 1 | 90° | 0.426227212 | 0.034160481 | 0.195734721 | 0.958 |
| 2 | 135° | 0.400719059 | 0.025679070 | 0.195863267 | 0.918 |
| 3 | 180° | 0.389427690 | 0.000050481 | 0.195756691 | 1.121 |
| 4 | 225° | 0.401009800 | −0.025247283 | 0.195788634 | 1.087 |
| 5 | 270° | 0.426190950 | −0.033517757 | 0.195690520 | 0.968 |
| 6 | 315° | 0.448536488 | −0.022239045 | 0.195698434 | 1.072 |
| 7 | 0° | 0.457107533 | 0.000045996 | 0.195833999 | 1.236 |
| 8 | 45° | 0.448779437 | 0.022603822 | 0.195711193 | 1.178 |

```
contact_indices     [1, 2, 3, 4, 5, 6, 7, 8]
point_attempts      {1:1, 2:1, 3:1, 4:1, 5:1, 6:1, 7:1, 8:1}   ← 전부 1회 시도
거절·교체된 점      없음
```

각 점의 `tip_pose`(7성분 quaternion 포함)·`measured_at_monotonic_s`·`residuals_m`은 원본 JSON 참조.

### 측정 완료 후 HOME 복귀

```
[15:07:18]  양초 좌표 계산 중
[15:07:18]  측정 완료: 검사한 경로로 상공 홈에 복귀합니다
[15:07:58]  상공 홈 도착·정지 확인 완료
[15:07:58]  좌표 계산·홈 복귀 완료: 양초 측정 완료
[15:07:58]  result: SUCCEEDED
```

```
home_return_confirmed   true
HOME tcp_pose           [0.42624374301578377, 4.6709476999166216e-05, 0.33]  quat (0,1,0,0)
position_tolerance      0.3 mm  /  angle_tolerance 0.3°
```

### 기존 승인값 대비

| 항목 | 승인값 (14:27, 7점) | 이번 (15:02, 8점) | 차이 |
|---|---|---|---|
| axis_xy_m | [0.423646493, −0.000039369] | [0.423255307, 0.000328441] | **0.537 mm** |
| radius_m | 0.033929017 | 0.033899969 | −0.029 mm |
| top_z_m | 0.215929474 | 0.215768463 | −0.161 mm |
| residual_rms_m | 0.000102410 | 0.000046823 | 절반 |
| residual_max_m | 0.000172597 | 0.000073302 | 절반 |
| 점 수 | 7 (45° 누락) | **8** | — |

---

## 3. 실제 사용한 측정 설정값

설정 파일: `config/workpiece_real_trial_0921.json` (커밋 `28ff186` 시점)

### 속도 / 가속도 / 힘 제한

| 프로파일 | 용도 | 속도 (mm/s) | 가속 (mm/s²) | `hard_force_n` | `contact_force_n` | `max_force_delta_n` | `timeout_s` |
|---|---|---|---|---|---|---|---|
| `travel` | 홈·상공·orbit | 60.0 | 60.0 | 15.0 | — | — | 60.0 |
| `escape` | 외곽 이탈 (`*_outer`) | 60.0 | 60.0 | 15.0 | — | — | 60.0 |
| `approach` | 접근 (`*_approach`) | 30.0 | 20.0 | 10.0 | — | — | 60.0 |
| `retract` | 후퇴 (`*_retract`) | 5.0 | 20.0 | 10.0 | — | — | 60.0 |
| `side_touch` | 옆면 접촉 탐색 | 1.0 | 0.3 | 10.0 | 0.8 | 2.0 | 60.0 |
| `top_touch` | 윗면 접촉 탐색 | 0.6 | 0.3 | 10.0 | 0.8 | 2.0 | 60.0 |
| `stop` | 정지 | — | — | — | — | — | 2.0 (mode 1) |

**`hard_force_n` 은 변경하지 않았습니다.** (4절 참조)

### 단계별 힘 판정

```
빈 공간 (lead-in 0 ~ 3.25 mm)     정지 bias 대비 prebaseline_delta_n 5.0 N        → FORCE_LIMIT
이동 기준힘 창 (2.00 ~ 3.25 mm)    moving_mad_n 0.2 / baseline_drift_n 0.2 N     → UNSTABLE_BASELINE (재시도)
정지 기준힘                        stationary_mad_n 0.1 N, baseline_timeout_s 10.0
탐색 구간 (4.05 ~ 14.05 mm)        contact_force_n 0.8 N ↑ = 접촉   max_force_delta_n 2.0 N ↑ = FORCE_LIMIT
전 구간 (PROBE)                    원신호 norm ≥ hard_force_n → FORCE_LIMIT 즉시 중단
비접촉 이동 (MOVE, 바깥 방향)       hard_force_n ~ noncontact_hard_force_n 15.0 N 사이 → 경고 후 계속 (조건부, 4절)
                                   noncontact_hard_force_n 15.0 N ↑ → FORCE_LIMIT 즉시 중단
경로 감시                          line_error_mm 0.5 / overhead 1.0 / hard_line_error_mm 3.0
```

### 재시도 횟수와 재시도 가능 오류

```
side_point_max_attempts    = 3   (최초 포함)
move_recovery_max_attempts = 3   (최초 포함)
```

| 분류 | 코드 | 처리 |
|---|---|---|
| 점 재시도 (`PointMeasurementError`) | `UNSTABLE_BASELINE` · `CONTACT_NOT_FOUND` · `CONTACT_OUT_OF_RANGE`(허용 구간 밖) | 정지 확인 → 시작점 후퇴 → 같은 점 재실행, 3회 |
| 이동 복구 (`MoveRecoveryError`) | `PATH_DEVIATION`(추종 오차형) · `MOTION_INCOMPLETE` | 정지 확인 → 현재 위치 재관측 → 남은 계획 preflight·scene 재검사 → 같은 step 재실행, 3회 |
| 경고 후 계속 | 비접촉 안전 구간 `hard_force_n` 초과 (4절 조건 만족 시) | 기록만 |
| 즉시 중단 | `FORCE_LIMIT`(PROBE·상한·양초 방향) · `STOP_UNCONFIRMED` · `NOT_READY` · `PROFILE_MISMATCH` · `SCENE_REJECTED` · `STALE_DATA` · `TELEMETRY_LOST` · `JOINT_LIMIT` · `SINGULARITY_MARGIN` · `IK_*` · `MOTION_NOT_STARTED` · `TIMEOUT` · `CANCELLED` · 통신 예외 | — |

### 초기 중심·반지름값 (seed)

```
seed_axis_xy_m    [0.42624374301578377, 4.6709476999166216e-05]
seed_radius_m     0.034291659073503865
angles_deg        [90, 135, 180, 225, 270, 315, 360, 405]
orbit_step_deg    22.5
side_depth_m      0.02        (윗면 아래 20 mm 측정)
```

이번 실측 중심은 seed 에서 **3.002 mm** 떨어져 있습니다. 탐색 전 baseline 모드의 허용 한계는 `side_center_limit` = 3.7 mm (`min(start_gap, search−start_gap) − max_radius_error − pose_tolerance`) 라 FIT 통과했습니다. **다음 측정부터는 `seed_axis_xy_m` 을 이번 실측값으로 갱신**하시길 권합니다 — 남은 여유가 0.7 mm 뿐입니다.

```
탐색 구간 (mm)   outer_gap 22.0 · start_gap 5.0 · lead_in 4.05 · search 10.0 · inside_limit 5.0 · slow_retract 5.0
                 → PROBE max_m 14.05, contact_travel_range [4.05, 14.05]
허용 오차        pose_tolerance 0.3 mm · angle_tolerance 0.3° · max_state_age 2.0 s · runtime_timeout 360 s
형상 판정        max_center_shift 2.0 · max_radius_error 1.0 · max_fit_rms 0.3 · max_fit_residual 0.6 mm
```

### TCP / tool / frame_id

```
frame_id            c2_base
tcp_id              GripperDA_v1
load_id             ToolWeight_1       (실기 시점 등록값 weight 1.550 kg, COG [8.400, −7.620, −1.670] mm — 재확인 후 실기)
tool_offset_m       [0.00085, -0.09955, 0]
tool_offset_source  고정 장착 재사용 — 이번 측정에서 도구 길이 재측정 없음
measurement_scope   ABSOLUTE_GEOMETRY   (contact_offset_tool_m 20 mm 확정 적용)
source_mode         REAL
```

---

## 4. 7번 점 후퇴 `FORCE_LIMIT` 처리 결과

### 발생 원인 — 실제 접촉이 아닌 자세 의존 외력 추정 오프셋

12:43·14:27 두 실기 모두 `point_7_retract` (MOVE, `retract`, 한계 10.0 N) 에서 |F| 10.1 N 으로 종료.

```
                      12:43            14:27
|F| 초과값            10.117 N         10.063 N
성분                  Fx 96%           Fx 96%
드릴 끝 공칭 여유     +2.51 mm ↑       +6.18 mm ↑     (양초에서 멀어지는 중)
서보 추종 오차        0.042 mm         0.071 mm       (정상; 막힌 도구는 이 값 불가)
robot_state           1                1              (정상)
정지 후 0.2 s         7.75 N           8.37 N         (감쇠 — 접촉 하중이면 유지됨)
```

**힘이 팔을 뻗은 정도에 단조 비례**합니다 (14:27 전 구간, 베이스 거리별):

| 베이스 거리 | 정지 Fx 중앙 | 이동 Fx 최소 |
|---|---|---|
| 250~300 mm | −1.90 | −4.60 |
| 450~500 mm | −1.82 | −7.96 |
| **550~600 mm** | **−4.13** | **−10.03** |

같은 자세에서 속도만 60배 바꿔도 Fx 는 2배 차이 (1 mm/s −4.80 vs 60 mm/s −9.98). 속도보다 **자세(J2/J3 토크)** 가 지배합니다. 같은 크기(10 N ↑)가 14:27 실기에서 52회 발생했고, 51회는 `travel`/`escape` 구간(한계 15 N)이라 통과했습니다.

### 충돌이 아니라고 판단한 근거 (로그·관찰)

1. **기하**: 초과 시점 드릴 끝이 양초 표면 바깥에서 **멀어지는 중** (공칭 여유 증가)
2. **서보**: 추종 오차 0.04~0.07 mm — 도구가 막혀 있으면 실제↔지시 TCP 가 벌어져야 함
3. **파형**: 이동 시작 0.3 s 내 상승 → 평탄 유지 → **정지 시 감쇠**. 접촉이면 파고들수록 오르고 정지해도 유지
4. **상시 오프셋**: 정지 중에도 |F| 중앙 3.7~4.3 N (아무것도 안 닿은 상태)
5. **재현성**: 두 실기 동일 지점·동일 크기, 다른 점(1~6)은 전부 통과
6. **팀 기록**: `docs/LESSONS_ROBOT.md` L2 "툴 하중·힘센서 기준이 자세마다 달라 이동 중 반력이 2~3 N 씩 올라 평탄해진다" — 조각 쪽에서 이미 겪은 같은 현상
7. **흔들림과 무관**: 7번 자세에서 추종 오차 방향 반전율 56% (진동 실재)이나 진폭은 최소(0.077 mm). 힘이 최대일 때 진동은 최소 → 인과 아님

### 코드·설정 변경 내용

**`hard_force_n` 변경: 없음.** `retract` 10.0 → 10.0, `travel`/`escape` 15.0 → 15.0.

대신 **비접촉 안전 구간 전용 절대 상한**을 하나 두고, 프로파일 한계와 상한 사이는 **아래 8조건을 전부 만족할 때만** 경고로 낮춥니다.

```json
"guards": { "noncontact_hard_force_n": 15.0 }
```

```
① |F| < noncontact_hard_force_n (15.0)     절대 상한 — travel/escape 가 이미 승인받은 값
② step 이 MOVE                             PROBE(접촉 탐색)는 종전대로 즉시 중단
③ 라벨이 orbit / *_retract / *_outer        바깥·접선 이동만. approach 는 양초 쪽이라 제외
④ 드릴 끝이 공칭 원통 바깥 (gap ≥ 0)
⑤ 양초와의 거리가 줄지 않음                 접근 중이면 즉시 중단
⑥ desired_posx 존재                        명령 경로 확인 가능
⑦ 실제↔지시 추종 오차 ≤ line_error_mm 0.5   서보 정상 = 막히지 않음
⑧ robot_state / motion_status 정상
```

만족 시: `force_warning` 텔레메트리 + 결과 `observed_state.force_warnings[]` + 콘솔 로그 기록 후 **계속**.

**승인 근거**: 15 N 은 새 숫자가 아니라 팀이 `travel`/`escape` 프로파일에 이미 적용 중인 값입니다. 실측 자유 이동 최대 11.02 N 대비 4 N 여유. `side_touch`/`top_touch` 의 10 N 과 접촉 판정 0.8 N 은 그대로입니다.

**첫 구현의 버그와 수정**: 조건 ④를 처음엔 "seed 원통 기준 5 mm 여유"로 짰는데 실기 값(2.51 mm)을 차단했습니다. seed 중심이 실측과 2.6~3.0 mm 어긋나므로 seed 기준 넓은 여유대는 무의미 — "공칭 원통 바깥"으로 바꾸고 실기 두 건 관측값을 `test/fixtures/force_limit_20260923.json` 에 고정했습니다.

### 실기 검증 (15:02)

```
경고: point_7_retract 비접촉 구간 외력 10.28 N (한계 10.0 / 상한 15.0, 양초 여유 7.5 mm, 추종 0.034 mm) — 계속 진행
  … (25건, |F| 10.12~10.42 N, 여유 5.5→9.0 mm 증가, 추종 ≤ 0.108 mm, 뻗음 568 mm)
8/8번째 점 측정 중
8/8번째 점 측정 완료
```

경고 25건 전부 `point_7_retract`, 다른 step 에서는 0건. 이번 실기 이동 중 |F| 최대 11.009 N, 10 N 초과 46 sample — 전부 통과.

### 잔존 과제 (별도 안건)

근본 원인은 `ToolWeight_1` 하중/COG 보상 오차입니다. 정지 상태 |F| 가 여전히 4.2 N 이고 뻗으면 커집니다. 이번 정책은 이 오프셋을 **안전하게 우회**하는 것이지 제거하는 게 아닙니다. 하중 프로필을 맞추면 경고 자체가 사라집니다. M0609 에는 ROS 로 접근 가능한 외력 영점 기능이 없음을 확인했습니다 (`set_external_force_reset` 은 DRL 전용, DRL 종료 시 소멸).

---

## 5. 검증 결과

### 실행한 테스트 명령

```bash
cd /home/skywalker/collaborative/ws_cobot_pjt/ws_cobot1/src/c2_process
PYTHONPATH=.:test python3 -m pytest test/ -q \
  --ignore=test/test_measurement_execution_offset.py -p no:cacheprovider
```

```bash
cd /home/skywalker/collaborative/ws_cobot_pjt/ws_cobot1
colcon build --packages-select c2_process
```

### 통과 / 실패 개수

```
pytest        1002 passed, 5 skipped, 0 failed     (24.6 s, 커밋 28ff186 시점)
  신규        test_noncontact_force_policy_mock.py   18건
              test_move_recovery_mock.py             17건
colcon build  Finished <<< c2_process [0.79s]
git diff --check  통과
replay        9/23 11:54 실기 힘 곡선 재생 — 접촉 4케이스 + 장애물 3케이스 전부 기대대로
```

`test_measurement_execution_offset.py` 는 `skimage` 미설치로 수집 불가하여 제외 (환경 문제, 수정과 무관).

### 기존 실패 테스트 2건의 처리 결과 — **교체 완료**

| 테스트 | 처리 |
|---|---|
| `test_measurement_presearch_mock.py::…[preloaded]` | 교체 |
| `test_measurement_reseat_mock.py::test_obstacle_before_window_fails_without_next_point` | 교체 |

두 시험이 주입하던 "이동 시작과 동시에 생겨 일정하게 유지되는 1 N 오프셋"은 실기 정상 파형(1.65 N)과 동일해 **실기에서 재현 불가능한 구분을 요구**했습니다. "크기가 아니라 힘이 오르는 모양으로 장애물을 판정" 계약으로 바꾸고 케이스를 2 → 7건으로 늘렸습니다. 단단한 장애물(6 N) → `FORCE_LIMIT`, 밀리는 장애물(상승) → `UNSTABLE_BASELINE` 재시도, 일정 오프셋 → 정상 완주.

### 읽기 전용 IK 검사

```
옆면 계획   segments 48 · IK/FK 655회 · 표본 773 · SUCCEEDED
윗면 계획   segments 4 · IK/FK 98회 · SUCCEEDED
홈 경유     segments 5 · IK/FK 110회 · SUCCEEDED
validation_level = SAMPLED_CONTROLLER_IK_FK_AND_EXTERNAL_SCENE_CHECK
full_continuous_collision_checked = false
```

### 실제 로봇 옆면 1~8점 완료 결과 (2026-09-23 15:02)

```
홈 확인            ✅  이미 HOME → 이동 없이 정지 확인
윗면 접촉          ✅  top_z_m 0.215768
옆면 1~8/8         ✅  전부 1회 시도, 재측정 0
이동 오차 복구     ✅  orbit 1회 (line_error 0.512 mm, 지시 TCP 는 0.062 mm, 추종 0.606 mm) → 복구 후 계속
힘 경고            ✅  point_7_retract 25건 → 계속
FIT                ✅  rms 46.8 / max 73.3 um
정지 확인          ✅  stop_confirmed true
HOME 복귀          ✅  home_return_confirmed true, 상공 홈 도착·정지 확인
JSON 결과 발행     ✅  result: SUCCEEDED, /workpiece_test/result 1건 (bag 확인)
소요               약 6분 (bag 356.9 s)
```

### 실패·정지 처리 확인

이번 실기에서 중단·정지 사건은 없었습니다. 정지 처리 경로는 앞선 실기에서 확인됨:
- 11:54 `CONTACT_OUT_OF_RANGE` → stop_confirmed true
- 12:23 `PATH_DEVIATION` → stop_confirmed true
- 12:43 · 14:27 `FORCE_LIMIT` → stop_confirmed true, 정지 후 힘 감쇠 기록

### `/c2/prepare_workpiece` MEASURE 전체 성공 여부 — **미검증**

지금까지 실기는 **전부 단독 시험 노드** `test/workpiece_test_node.py` 로 수행했습니다. Action 경로 (`preparation_action` → `workpiece_process_adapter` → `GuardedMeasurementAdapter`) 는 mock 만 검증되어 있습니다. 측정 함수(`measure_workpiece`)와 어댑터는 동일하므로 Action 래퍼 단의 실기 확인이 남았습니다.

### 전체 실기 횟수

| 시각 | 결과 | 막힌 지점 | 조치 |
|---|---|---|---|
| 11:09 / 11:24 | 0/8 | (이전 코드) | — |
| 11:54 | 0/8 | 기준힘 게이트 | 삭제 (커밋 1) |
| 12:23 | 1/8 | `point_2_approach` 0.504 mm | 이동 복구 (커밋 1) |
| 12:43 | 7/8 | `point_7_retract` 10.117 N | 분석 |
| 14:27 | 7/8 | `point_7_retract` 10.063 N | 정책 변경 (커밋 2) |
| **15:02** | **8/8 ✅** | — | — |

**미검증 항목**: `/c2/prepare_workpiece` Action 실기 · `ToolWeight_1` 하중/COG 실측 일치

---

## 6. 첨부 · 참고 파일

```
첨부        prepare_workpiece_result_20260923_1502.json     결과 원본 (51 KB)
설정        c2_process/config/workpiece_real_trial_0921.json  (커밋 28ff186)
실기 기록   /tmp/c2-eight-point-retry-test/results/
              console_20260923_150207.log
              workpiece_155bed9063674d239e944f24cf32b583.jsonl  (텔레메트리 11,848건)
bag         /tmp/c2-bag-20260923_150200/   356.9 s · 239,416 msgs
              /workpiece_test/feedback 30 · /result 1 · /telemetry 11,848
              /dsr01/joint_states 39,026 · /dsr01/error 7 · /dsr01/dynamic_joint_states 35,454
계약 문서   c2_process/WORKPIECE_CALIBRATION.md
팀 기록     docs/LESSONS_ROBOT.md L2 (동일 현상 선례)
```

---

## 7. 다음 단계

| 순서 | 항목 | 담당 |
|---|---|---|
| 1 | Issue 번호 확정 → 커밋 메시지 반영 → push → PR | 팀 / 시율 |
| 2 | 최종 설정에 이번 8점 값 반영 · `seed_axis_xy_m` 갱신 | 설정 작성자 |
| 3 | `/c2/prepare_workpiece` MEASURE Action 실기 검증 | 시율 |
| 4 | `ToolWeight_1` 하중/COG 실측 일치 확인 (경고 근본 원인) | 장비 |
