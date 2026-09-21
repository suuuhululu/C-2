# c2_path 스냅샷·파일 묶음 명세 (1차 SIM 통합 시험용 초안)

작성: 노홍동 (path_planner_node / c2_path) · 기준: 2026-09-21 · 상태: **초안 — 담당자 확인 전**

이 문서는 팀장님이 정리하신 "1차 SIM 통합 방식"에서 c2_path 쪽이 맡은 사항을 코드 기준으로 적은 것이다.
**코드에서 확인한 사실**과 **아직 확정되지 않은 제안**을 구분해 적고, 미정 항목은 기본값으로 채우지 않고
담당자와 미정 이유를 표시한다(10절). 이 문서의 필드 표는 `test/test_snapshot.py` 가 스냅샷 필드와 대조한다.

| 표시 | 뜻 |
| --- | --- |
| **확인** | 현재 코드(`pipeline.py`, `generate_path.py`, `engraving.py` 등)에서 확인한 사실 |
| **제안** | HMI 가져오기·통합을 위해 c2_path 가 제안하는 규격. 공통 규격으로 확정되지 않았다 |
| **미정** | 담당자 확정 전. 코드는 값을 임의로 채우지 않는다 |

## 1. 1차 SIM 흐름과 c2_path 의 자리

```
① 공통 스냅샷 형식 확정 ─ ② HMI: 스냅샷·입력 이미지 등록(ID·해시 발급)
      ─ ③ HMI → 입력 묶음(input/) ─ ④ c2_path: 경로·산출물 생성 → 출력 묶음(output/)
      ─ ⑤ HMI: 묶음 해시·참조 확인 후 등록, 미리보기 ─ ⑥ 공정 로더: 같은 스냅샷·경로로 모의 실행
```

- ④ 를 실행하는 명령: `python -m c2_path.bundle run --input <입력 묶음> --output <출력 묶음>` (ROS 불필요).
  기존 ROS 액션(`node.py`)과 **같은 `GeneratePipeline`** 을 쓴다. 계산·검증 로직은 하나다.
- 출력 묶음 확인: `python -m c2_path.bundle verify <묶음>`
- **시험 기록 구분**: "파일 묶음 시험"(이 방식)과 "ROS 통신 시험"(`/c2/generate_path` 액션)은 따로 적는다.
  파일 묶음이 통과해도 ROS 통신이 검증된 것이 아니다.
- **PC 한 대 · 절대 경로 금지** (팀장님 확정: 통합 시험·최종 모두 PC 한 대). 코드에 고정 경로를 쓰지 않고, 폴더는 명령 인자·
  ROS 파라미터·환경 변수로 받는다. 파일 안에는 절대 경로를 넣지 않고 묶음 내부 상대 파일명만 쓴다.
  `test/test_no_absolute_paths.py` 가 소스와 샘플 묶음을 검사한다.

## 2. 스냅샷 본문 규칙 (**확인** 후 **제안**)

- 스냅샷 본문에는 자기 자신의 ID·해시를 넣지 않는다. ID·해시는 HMI 등록 응답과 요청(`profile_snapshot_id`,
  `profile_sha256`), manifest 에 기록한다. **확인**: 현재 `matching_test_profile()` 도 본문에 ID·해시가 없다.
- **해시는 HMI 에 최종 저장된 파일 바이트 기준**이다. c2_path 는 받은 바이트를 다시 직렬화하지 않고 그대로 해시를 확인한다.
  **확인**: 직렬화가 구현마다 다르다. HMI(`backend/app/storage.py` `encoded`)는 정렬·compact JSON, c2_path
  `artifacts.json_bytes` 는 정렬·들여쓰기 2칸·끝 줄바꿈이다. 같은 내용이어도 바이트가 달라 해시가 다르므로,
  **등록 이후에는 파일을 다시 저장하지 않고 수정이 필요하면 새 스냅샷으로 등록**한다.
- 시험: `test_bundle.py::test_input_bytes_are_used_as_received_not_reserialized`.

## 3. `tools_config_id` · `tools_config_version` (홍동님 요청 1)

| 항목 | 내용 (**확인**: `pipeline.validate_profile`, `generate_path.build`) |
| --- | --- |
| 위치 | 스냅샷 **최상위** 필드 (`surface` 안이 아님) |
| 필수 | **필수.** 없으면 `PROFILE_MISMATCH` |
| 자료형 | `tools_config_id` 문자열, `tools_config_version` **정수** (`true`, `"1"`, `1.0` 은 거절 — 9/21 강화) |
| 현재 허용값 | `"c2_tools"` / `1` (`workcell.TOOLS_CONFIG_ID/VERSION` 과 정확히 일치해야 함) |
| 검증 조건 | test_only 단계: 위 값과 **정확 일치**. 불일치 시 경로를 만들지 않고 `PROFILE_MISMATCH` |
| 전파 | 생성된 `path.json` 의 `config.tools_config_id/version` 에 그대로 기록 (경로가 어느 도구 설정 기준인지 추적) |
| 미검사 | HMI `PathArtifactLoader` 는 아직 `config.tools_config_*` 를 스냅샷과 대조하지 않는다 → **제안**: 대조 추가 |
| 미정 | 실제 `tools.yaml`(세은님) 의 버전 체계와 이 값의 대응 — 담당: 세은님, 이유: tools.yaml 변경 이력 규칙 미확정 |

## 4. 스냅샷 필드 표 (`c2-path-test-profile/1`, `/2` 는 4.1)

검증 열은 현재 `validate_profile` 동작이다. "정확 일치"는 `workcell.py` 상수와 같아야 통과한다는 뜻이다.

| 필드 | 값(현재) | 검증 (**확인**) | 비고 |
| --- | --- | --- | --- |
| `contract` | `c2-path-test-profile/1` | 9/21부터 검사: 없음(→`/1` 규칙)·`/1`·`/2` 만 받고 다른 값은 `PROFILE_MISMATCH` | 형식 버전. `/1`·`/2` 의 차이는 4.1. 실측 프로필의 최종 계약 이름은 **미정** |
| `schema_version` | `2` | 정확 일치 | 경로 파일 schema 와 같은 값 |
| `source_mode` | `SIMULATION` | 정확 일치 | `REAL` 은 test_only 동안 `NOT_READY` |
| `workcell_id` | `candle_test_0919` | 정확 일치 | |
| `workcell_version` | `1` | 정확 일치 | |
| `tools_config_id` | `c2_tools` | 정확 일치 | 3절 |
| `tools_config_version` | `1` | 정확 일치 | 3절 |
| `tool_id` | `engraving_drill` | 정확 일치 | 경로·요청의 `tool_id` 와도 같아야 함 |
| `tool_version` | `1` | 정확 일치 | |
| `tcp_id` | `GripperDA_v1` | 정확 일치 | 제어기 TCP. c2_path 는 계산에 쓰지 않고 `path.json config` 에 기록 |
| `tcp_version` | `1` | 정확 일치 | |
| `load_id` | `ToolWeight_1` | 정확 일치 | |
| `load_version` | `1` | 정확 일치 | |
| `frame_id` | `c2_base` | 정확 일치 | 팀장님 확정 |
| `gripper_open_allowed` | `false` | 정확 일치 | 그리퍼 열기 금지 |
| `calibration_status` | `SIMULATION_ONLY` | **미검사** | 실측 프로필에서 값 체계 **미정** (측정 결과 형식 확정 후, 시율님) |
| `surface.kind` | `cylinder` | 정확 일치 | |
| `surface.radius_mm` | `34.25` | 정확 일치(±1e-6 mm) | 9/20 캘리퍼스 실측 지름 68.5±0.3 의 절반 |
| `surface.height_mm` | `150.0` | 정확 일치(±1e-6 mm) | |
| `surface.axis_origin_m` | `[0.4218, 0.0001, 0.0834]` | 정확 일치 | `[x, y, 바닥 z]` (m). 윗면 z = 바닥 z + 높이 = 0.2334 |
| `surface.axis_direction` | `[0, 0, 1]` | 정확 일치 | 계산·미리보기가 +Z 축만 지원 |
| `surface.valid_v_range_mm` | `[10, 140]` | 정확 일치 | **바닥(0) 기준** 로봇 작업 가능 높이(잠정) — 바닥 여백 10mm, 윗면 여백 10mm(양초 높이 150mm 기준). 시율님 표현 "윗면 아래 10~140mm"와 150mm에서는 같은 구간이지만, 코드·스냅샷은 윗면 깊이가 아니라 바닥 기준 높이만 쓴다. 9/21 시율님 지시로 이전 값 `[85, 130]`(윗면 아래 20~65mm)에서 변경. 경로 생성 조건이 아니라 실행 사전 점검 기준이다 (13절) |
| `surface.u_origin_angle_deg` | `0` | 정확 일치 | u=0 이 놓이는 각도 (0° = +X, 로봇 반대편) |
| `surface.seam_angle_deg` | `180` | 정확 일치 | 이음매 = −X, 로봇 쪽 (J5 위험) |
| `surface.reachable_angle_deg` | `[-135, 135]` | 정확 일치 | J5 안전 범위 — **잠정**, 5° 간격 실측표 대기 (시율님). 9/21부터 경로 생성 조건이 아니라 실행 사전 점검 기준이다 (13절) |

### 4.1 스냅샷 계약 `/1` 과 `/2` (9/21, 팀장님 회신 반영 — **제안**)

`contract`(`c2-path-test-profile/1` 또는 `c2-path-test-profile/2`) 끝의 번호는 스냅샷 양식 버전이다. c2_path 는 이 값을 보고 검사 규칙을 고른다. 새 필수 필드를 `/1` 에
추가하면 그 필드가 없는 기존 스냅샷이 모두 거절되므로, 새 규칙은 `/2` 에만 적용하고 `/1` 은 그대로 둔다.

| 항목 | `/1` (기존) | `/2` (새) |
| --- | --- | --- |
| 값 검사 | 코드 상수와 **정확히 같을 때만** 받음 | 식별은 상수와 같아야 하고, **원통 치수·작업 범위·도달각은 요청별 값**을 받음 |
| `surface.valid_v_range_mm` | `[10,140]` (바닥 기준, 상수와 같아야 함) | 요청별 `[하한, 상한]` (mm, 바닥 기준). `0 <= 하한 < 상한 <= height_mm` |
| `surface.reachable_angle_deg` | `[-135,135]` (상수와 같아야 함) | 요청별. `-180 <= 하한 < 상한 <= 180`, 이음매가 범위 안에 들어가지 않음 |
| `surface.height_reference` | 없음 | **필수** `"bottom"` — 높이 0 = 양초 바닥(축 원점 z) |
| `surface.v_direction` | 없음 | **필수** `"up"` — 바닥에서 위로 갈수록 v 가 커짐 |
| `calibration_status` | 값 검사 없음 | **필수** `"SIMULATION_ONLY"` (지금은 이 값만). 실측 유효 값은 제어팀 확인 후 추가 — **미정** |
| `measurement_id`, `measured_at` | 없음 | 선택. 있으면 형식만 검사(1~128자 문자열 / 시간대가 있는 ISO 8601) |
| 원통 치수(`radius_mm`, `height_mm`, `axis_origin_m`) | 상수와 같아야 함 | **요청별 값** — 경로 좌표·검증·미리보기가 이 값으로 계산됨. `radius_mm`·`height_mm` > 0, `axis_origin_m` 은 [x, y, 바닥 z] (m) |
| 원통 종류·축 방향·`u_origin_angle_deg`·`seam_angle_deg` | 상수와 같아야 함 | **아직 상수와 같아야 함** (`cylinder`, `[0,0,1]`, 0°, 180°). 이음매는 J5 위험 구역, 축은 +Z 만 계산·미리보기가 지원 |
| 작업 영역 | `[10, 140]` 고정 | 팀장님 확정 규칙 `[10, H−10]`(상하 각 10mm 제외)을 HMI 가 계산해서 `valid_v_range_mm` 으로 보냄 |

변환은 **HMI 백엔드 한 곳**에서만 한다(팀장님 확정): 바닥 기준 `V = H − v`, 윗면 기준 값을 받았다면 범위를
`[H − v_max, H − v_min]` 로 뒤집고, `axis_origin_m.z = top_z_m − H_mm/1000`. c2_path 는 받은 값을 다시 변환하지 않는다.
HMI 의 `hmi-work-area-policy/1`(상하 제외 mm)은 화면·모의 스냅샷용 설정이고 c2_path 는 읽지 않는다 — 스냅샷의
`valid_v_range_mm` 만 쓴다. 예시: `samples/profile_snapshot_v2.json`(기본), `samples/bundles/heart_request_range_out_of_limits/input/simulation-profile.json`
(범위를 `[110,140]` 으로 바꾼 것). `pipeline.matching_test_profile()` 은 여전히 `/1` 을 만든다(HMI ROS 모드가 그대로 등록하는 값).

## 5. 실측값을 받는 새 프로필에 필요한 기하 필드와 허용 조건 (홍동님 요청 2)

**현재 상태 (9/21 반영)**: `/1` 스냅샷은 코드 상수와 **정확히 같은지**만 본다(기존 시험용). `/2` 는 **스냅샷의 원통 치수(반지름·높이·축 원점)와 작업 범위·도달각으로 경로를 계산한다.**
경로 좌표·검증(표면 위·관통·높이)·미리보기·실행 사전 점검이 모두 이 값을 쓴다. 상수(`workcell.py`)는 `/1` 의 기준값이자 기본 형상일 뿐이다.
구현: 요청마다 스냅샷에서 `workcell.Surface` 를 만들어 그 요청 안에서만 쓴다(`workcell.current_surface()`, 요청이 끝나면 기본 형상으로 복귀 — 다른 요청에 새지 않는다).
사용한 스냅샷은 경로 `config.profile_snapshot_id`·`config.profile_sha256`, 검증 보고서 `profile_snapshot_id`·`profile_sha256`·`profile_contract`·`measurement_id`·`measured_at`·`surface_used`(실제로 계산에 쓴 반지름·높이·축 원점),
미리보기의 `profile_snapshot_id`·`profile_sha256` 로 연결된다. 아직 상수로 남은 것: 종류(cylinder)·축 방향(+Z)·u 원점(0°)·이음매(180°).

**필요한 기하 필드 (제안)** — 4절의 `surface.*` 와 같은 이름·단위를 유지하고, 실측값을 담는다.

| 필드 | 실측/고정 | 구조 조건 (**확인**: `snapshot.surface_geometry_errors`) | 수치 허용 범위 |
| --- | --- | --- | --- |
| `surface.radius_mm` | 실측 (캘리퍼스) | 유한, > 0 | **미정** — 시율님 (양초 규격·측정 오차 ±0.3mm 기준 상·하한) |
| `surface.height_mm` | 실측 | 유한, > 0 | **미정** — 시율님 |
| `surface.axis_origin_m` | 실측 (`workpiece_calibration`) | 유한한 수 3개 `[x, y, 바닥 z]` | 명목값 대비 허용 이동량 **미정** — 시율님 (9/20 재장착 시 3~5mm 어긋남 관측 → 5mm 이상 필요) |
| `surface.axis_direction` | 고정 | `[0, 0, 1]` | 없음 |
| `surface.valid_v_range_mm` | 고정(작업 정의) | `0 <= 하한 < 상한 <= height_mm` | 윗면 아래 10~140mm(9/21 시율님 지시, 이전 20~65mm)는 로봇 작업 범위. 실측 프로필에서 유지할지, 측정 결과가 주는 값을 쓸지 **미정**. 경로가 놓일 수 있는 범위는 `0 ~ height_mm` 전체다 (13절) |
| `surface.u_origin_angle_deg` | 고정(배치 정의) | −180~180 | 없음 |
| `surface.seam_angle_deg` | 고정 | −180 초과 180 이하 | 없음 |
| `surface.reachable_angle_deg` | 실측(J5) | `−180 <= 하한 < 상한 <= 180`, **이음매가 범위 안에 들어가지 않음** | 5° 간격 실측표 후 확정 — 시율님 |
| `tool_id`, `tools_config_*`, `tcp_*`, `load_*`, `frame_id` | 고정 | 3·4절 | 실측 프로필에서도 정확 일치 유지 제안 |
| 측정 시각·측정 ID | 실측 메타 | `/2` 에서 선택 필드 `measured_at`, `measurement_id` (형식만 검사) | 필수로 할지 **미정** |
| 유효 상태(`calibration_status`) | 실측 메타 | `/2` 에서 `SIMULATION_ONLY` 만 통과 | 실측 유효 값 체계 **미정** — 제어팀 확인 후 팀장님이 공유 예정 |

구조 조건은 `c2_path/snapshot.py` 에 구현돼 있고 `test_snapshot.py` 가 확인한다. `/2` 스냅샷에서는 `pipeline.validate_profile` 이 이 검사를 호출한다(`test_profile_contract.py`). `/1` 은 호출하지 않는다.

## 6. `workcell` 측정 결과 ↔ 경로 생성용 `surface` 연결 (홍동님 요청 3)

**제안: 원본은 스냅샷의 `surface` 하나로 두고, 공정 쪽 `workcell` 입력은 그 값에서 파생한다.**
`tool_calibration.measure_tool_tip/verify_tool_tip` 이 읽는 키는 `axis_xy_m`, `radius_m`, `top_z_m` 뿐이다(**확인**).

| 스냅샷 `surface` (원본) | 공정 `workcell` (파생) | 변환·규칙 |
| --- | --- | --- |
| `axis_origin_m[0:2]` (m) | `axis_xy_m` (m) | 변환 없음. 같은 `c2_base` 좌표 |
| `radius_mm` (mm) | `radius_m` (m) | ÷ 1000. **단위 이름을 값에 붙여** mm/m 혼동 방지 |
| `axis_origin_m[2]` + `height_mm`/1000 | `top_z_m` (m) | 바닥 z + 높이 = 윗면 z |

- 파생: `snapshot.workcell_view(profile)` → `{axis_xy_m, radius_m, top_z_m}`.
- 두 표현을 **함께 저장**한다면: `snapshot.check_workcell_view(profile, workcell)` 로 일치 검사. 허용 오차 `1e-6 m`(1 µm)은
  mm↔m 변환의 부동소수 오차만 허용한다. 측정 오차를 흡수하는 값이 아니다.
- 시험이 잡는 실수: 반지름을 mm 로 넣고 이름만 `radius_m`(34.25 대 0.03425), 0918 구버전 축 좌표(0.4224, −0.0026),
  윗면 z 불일치.
- **미정**: 시율님 쪽에서 측정 결과를 `surface` 형태로 직접 낼지 `workcell` 형태로 낼지 — 담당: 시율님·홍동님,
  이유: `workpiece_calibration.py` 결과 형식이 별도 합의 대상.

## 7. 입력·출력 묶음과 `manifest.json` (**제안**)

### 7.1 폴더 구성

```
input/    manifest.json  request.json  <이미지 파일>  <스냅샷 JSON>     ← HMI 가 내보냄
output/   manifest.json  request.json  result.json
          c2-path.json  c2-path-centerline.svg  c2-path-preview.json  c2-path-validation.json   (성공)
          c2-path-validation-failed.json  c2-path-centerline-diagnostic.svg                      (실패 진단)
```

샘플 6종 (`samples/bundles/<이름>/{input,output}`). 입력 스냅샷은 모두 `/2`(4.1)다. 앞의 다섯은 생성·검증에 모두 성공하고, 실행 사전 점검(13절) 결과만 다르다.

| 이름 | 생성 | 실행 사전 점검 |
| --- | --- | --- |
| `heart_ok` | 성공 | `WITHIN_LIMITS` (높이 45mm 아래, θ=−90°) |
| `heart_seam_out_of_limits` | 성공 | `OUT_OF_LIMITS` (θ=180° 이음매, 각도 범위 밖) |
| `heart_low_out_of_limits` | 성공 | `OUT_OF_LIMITS` (높이 15mm, 작업 높이 10~140mm 밖) |
| `heart_request_range_out_of_limits` | 성공 | `OUT_OF_LIMITS` (`heart_ok` 와 같은 하트, **스냅샷 범위만 `[110,140]`mm** — 요청별 범위가 쓰이는 것을 보여 줌) |
| `heart_custom_cylinder` | 성공 | `WITHIN_LIMITS` (**스냅샷의 원통 치수를 바꿈**: 반지름 30mm·높이 120mm·축 원점 [0.45, 0.01, 0.09]·범위 [10,110]mm — 좌표가 이 원통 위에 놓임) |
| `heart_off_surface` | **실패** (`HEIGHT_OUT_OF_SURFACE`, 원기둥 높이 150mm 밖) | 없음 (경로 없음) |

**이 샘플의 ID·해시는 HMI 가 발급한 값이 아니다** (입력 manifest 의 `origin` = `local_test_sample`). 재생성:
`python3 build_bundle_samples.py`.

### 7.2 manifest 필드

`contract` = `c2-path-bundle/1`, `schema_version` = 1.

| 위치 | 필드 | 내용 |
| --- | --- | --- |
| 최상위 | `bundle_role` | `input` 또는 `output` |
| 최상위 | `origin` | (입력 묶음) 출처. HMI 발급이면 HMI 가 정한 값, 시험 샘플은 `local_test_sample` |
| 최상위 | `source_mode`, `request_id` | `SIMULATION`, 요청 UUID |
| 최상위 | `inputs` | (출력 묶음) 이 결과가 참조한 입력: `asset_id`, `asset_sha256`, `profile_snapshot_id`, `profile_sha256` |
| 최상위 | `path` | (성공 출력) 논리 경로 ↔ 경로 파일 연결: `path_id`, `path_version`, `path_sha256`, `asset_id`. 실패는 `null` |
| 최상위 | `files` | 자산 파일 목록 (아래) |
| 최상위 | `documents` | 자산이 아닌 문서: `request`, `result` 의 `kind`, `file`, `mime`, `sha256`, `size_bytes` |
| `files[]` | `asset_id` | 파일 UUID |
| `files[]` | `kind` | 입력: `image`/`profile`. 출력: `path`/`svg`/`preview`/`validation` |
| `files[]` | `file` | 묶음 내부 **상대 파일명** (폴더 구분자·`..`·숨김 파일 금지) |
| `files[]` | `name` | 자산 이름 (HMI `assets.name`) |
| `files[]` | `mime` | `image/png`·`image/jpeg`·`application/json`·`image/svg+xml` |
| `files[]` | `sha256` | **실제 파일 바이트**의 SHA-256 (소문자 hex) |
| `files[]` | `size_bytes` | 실제 크기 |
| `files[]` | `path_id` | 관련 논리 경로 ID. 진단·입력 파일은 `null` |
| `files[]` | `path_version` | 경로 파일(`kind=path`)만 값이 있고 나머지는 `null` |
| `files[]` | `executable` | 실패 진단 파일에만 `false`. 성공 산출물에는 없음 |

**`manifest.json` 은 자기 자신의 해시를 담지 않는다.** 묶음 폴더의 다른 모든 파일이 `files` 또는 `documents` 에 있어야 한다
(목록에 없는 파일은 `UNLISTED_FILE` 오류). `result.json` 은 manifest 의 해시를 담지 않아 순환이 없다.

### 7.3 `path_id` 와 경로 파일 `asset_id` 는 다르다

`path_id` 는 논리 경로 식별자이고 `path.json` 파일의 자산 ID 는 별도 UUID 다. **확인**: `GeneratePath.Result` 에는 경로 파일의
asset ID 가 없다. 그래서 manifest 의 `path` 와 `files[kind=path]` 가 둘을 잇는다. `result.json` 과 각 파일 안에 적힌
`path_id`/`path_version`/`path_sha256` 은 manifest 와 일치해야 하며 `verify` 가 확인한다.

### 7.4 팀장님 4절 산출물 대응

| 요청 산출물 | 파일 | `kind` |
| --- | --- | --- |
| 경로 JSON | `c2-path.json` | `path` |
| SVG (변환된 2D 도안) | `c2-path-centerline.svg` | `svg` |
| 미리보기 JSON | `c2-path-preview.json` | `preview` |
| 검증 보고서 JSON | `c2-path-validation.json` | `validation` |
| 결과 JSON (Result 12개 필드 전체) | `result.json` | `documents.result` |
| 파일 연결 목록 | `manifest.json` | — |

`result.json` 은 `GeneratePath.Result` 의 `success`, `error_code`, `message`, `path_id`, `path_version`, `path_sha256`,
`svg_asset_id`, `preview_asset_id`, `segment_count`, `cut_length_m`, `validation_passed`, `validation_report_id` **전체**이며
`test_bundle.py` 가 액션 파일의 필드명과 대조한다. 실패 결과 규칙은 액션 파일과 같다 (`success=false`,
`validation_passed=false`, 경로 ID/해시 비움, 버전 0).

### 7.5 HMI 가져오기와의 대응 (**제안**)

manifest 의 한 줄이 HMI `assets` 한 행에 대응한다: `id`=`asset_id`, `sha256`, `kind`, `mime`, `name`, `size_bytes`, 그리고
`metadata`= `{"path_id": ..., "path_version": ...}` (실패 진단은 `{"executable": false}`). 기존 `PathArtifactLoader` 가
`kind='path'` 이면서 `metadata.path_id/path_version` 이 일치하는 자산을 찾으므로, 이 규칙대로 등록하면 기존 미리보기
검증을 그대로 쓸 수 있다.

가져오기 전에 HMI 가 확인하기를 제안하는 것: ① 파일 바이트 해시가 manifest 와 같음, ② `documents.result` 의 `success`,
`validation_passed` 가 참일 때만 경로 등록(`path_versions`) — 등록하면 실행 요청이 가능해지므로 실패·진단 묶음은
**등록하지 않거나 실행 불가로 표시**, ③ `manifest.inputs` 의 스냅샷·이미지 ID·해시가 HMI 에 등록된 값과 같음,
④ (9/21 추가) `success` 여도 검증 보고서·미리보기의 `execution_readiness.precheck` 가 `OUT_OF_LIMITS` 이면 실행 가능으로
표시하지 않음, `WITHIN_LIMITS` 여도 "실행 가능"이 아니라 "잠정 범위 안(판정 전)"으로만 표시 (13절).

## 8. 공정 함수 입력 구조 대조 (홍동님 6절 확인 사항)

`tool_calibration.py` / `engraving.py` / `joint_check.py` 를 읽고, c2_path 가 만드는 경로·설정이 입력 구조에 맞는지 확인했다.
`test/test_loader_compat.py` 가 실제 함수(모의 어댑터)로 확인한다. **이 함수들을 공정에서 연결해 호출하는 것은 세은님 담당**이다.

| 공정 입력 | c2_path 쪽 사실 (**확인**) | 실행 시점 값 / 확정 필요 |
| --- | --- | --- |
| `tool_calibration` 의 `workcell` = `{axis_xy_m, radius_m, top_z_m}` | 6절 `workcell_view` 로 스냅샷에서 파생 가능 | 측정 결과(`TipCalibration`)는 시율님 측정 산출물이며 스냅샷에 포함할지 **미정** (시율님) |
| `TipCalibration.tool_id` | 스냅샷 `tool_id` 와 같아야 함 (`engraving_drill`) | 세은님: 불일치 시 거절 지점 확정 |
| `engraving.validate_path(path, context)` 의 `path` | `schema_version` 2, `position_unit` m, `orientation` quaternion_xyzw, `frame_id`, `tool_id`, `source_mode`, waypoint 7개 값, CUT ≥ 2점·≤ 80점 → **통과 확인** (`force_touch`, `fixed_depth` 모두) | — |
| `ExecutionContext.motion_profiles` | 경로가 쓰는 `motion_profile_id` 는 **`candle_approach`, `candle_cut`, `candle_travel`, `candle_retract` 4개**. 하나라도 없으면 `PROFILE_MISMATCH` | 세은님: 4개 프로파일의 속도·가속·`completion_timeout_s`(REAL 필수) 값 |
| `ExecutionContext.tool_profile` | `tool_id` 는 경로·스냅샷과 같아야 함. `contact_mode` 는 `force_touch`/`fixed_depth` | 세은님·시율님: 접촉 방식·`depth`·`clearance`·`touch_force_n`·`touch_speed_mm_s` 값 |
| `ExecutionContext.source_mode` | 경로의 `source_mode`(SIMULATION) 와 같아야 함 | 실행 시점 |
| `ExecutionContext.run_id`, `cancel` | 스냅샷에 넣지 않는다 | **실행 시점에 생성** (저장 설정과 구분) |
| `check_path_joints(path, adapter, tool_offset_m, ref_joints_rad, …)` | `path` 는 위와 같은 `path.json`. 모의 어댑터로 전 waypoint 를 끝까지 검사함을 확인 | `adapter`, `ref_joints_rad`(현재 관절)는 **실행 시점 조회**. `tool_offset_m` 은 `TipCalibration.offset_tool_m`. `limits_deg`(현장 안전 설정)·`j6_margin_deg` 는 설정으로 둘지 **미정** (세은님·시율님) |

c2_path 는 J6/IK 를 계산하지 않는다. 검증 보고서의 `not_checked` 에 `J6_RANGE` 가 남는 이유다.

## 9. 가공 깊이 적용 위치 (**확인** + **제안**)

- **확인**: c2_path 는 깊이를 적용하지 않는다. CUT waypoint 는 반지름 `surface.radius_mm` 원통 **표면 위의 점**이다
  (`test_loader_compat.py` 가 반지름 오차 10 µm 이내로 확인). 스냅샷 `surface` 에도 깊이 필드가 없다.
- **확인**: 깊이는 `engraving.py` 가 실행 시점에 적용한다. `fixed_depth` 는 표면점에서 법선 안쪽으로 `depth_m`,
  `force_touch` 는 힘 감시로 찾은 접촉점 기준 보정량을 쓴다 (둘 다 `tool_profile` 입력).
- **제안**: **적용 위치는 실행 쪽(`engraving.py` + `tool_profile`)만**으로 확정. c2_path·스냅샷 `surface` 에는 깊이를 넣지 않는다.
  그러면 이중 적용이 구조적으로 생기지 않는다. 만약 나중에 경로 쪽에 깊이를 넣기로 하면 `path.json` 에 적용 여부
  필드를 두어 실행 쪽이 `depth=0` 으로 바꾸게 해야 한다.
- **미정**: 세은님·시율님 확정 필요 — 이유: 실기에서 `force_touch` 를 쓸지 `fixed_depth` 를 쓸지, 깊이 값이 미확정.

## 10. 미정 항목 (기본값으로 채우지 않음)

| 항목 | 담당 | 미정 이유 |
| --- | --- | --- |
| 실측 프로필 계약 이름·`calibration_status` 실측 유효 값 체계 | 시율님·제어팀 | `workpiece_calibration.py` 결과 형식이 별도 합의 대상. `/2` 는 지금 `SIMULATION_ONLY` 만 받는다 |
| `surface.radius_mm`·`height_mm` 허용 범위, 명목 축 대비 허용 이동량 | 시율님 | 재장착 이동량(3~5mm) 관측만 있고 허용 기준 미확정 |
| `surface.reachable_angle_deg` 확정값 | 시율님 | 5° 간격 J5 실측표 대기 (현재 ±135° 잠정). 이 값은 이제 실행 사전 점검에만 쓰인다 |
| 측정 결과를 `surface` 로 낼지 `workcell` 로 낼지 | 시율님·홍동님 | 결과 형식 합의 전 |
| `TipCalibration` 을 스냅샷에 포함할지 | 시율님·세은님 | (a)안 범위와 측정 결과 형식이 아직 정해지지 않음 |
| `tools_config_*` 와 실제 `tools.yaml` 버전 체계 | 세은님 | tools.yaml 변경 이력 규칙 미확정 |
| 4개 motion profile 값, `tool_profile`(접촉 방식·depth·clearance·touch), stop_profile, `limits_deg` | 세은님·시율님 | 실기 값 미확정 |
| 가공 깊이 적용 위치 | 세은님·시율님·홍동님 | 9절 제안 확정 필요 |
| 스냅샷 계약(스키마) 버전 부여 방식 | 팀 전체 | 공통 형식이 PR 로 확정되기 전 |
| manifest 규격 (7절) | 팀장님·홍동님 | HMI 가져오기 대조 후 확정 (현재 제안) |
| 실제 `workcell.py` 상수 → 요청별 값으로 전환 | 홍동님 | `/2` 에서 원통 치수·작업 범위·도달각 모두 요청별로 전환됨(4.1, 5절). 남은 것: 축 방향·u 원점·이음매(고정), `calibration_status` 실측 유효 값(제어팀) |
| `/2` 의 필수 필드 이름·위치(`surface.height_reference`, `surface.v_direction`) | 팀장님·홍동님 | 9/21 회신에서 이름은 확정됐고 위치(`surface` 안)는 제안 |

## 11. 분할된 획의 관계 필드 (9/21, **확인**: 코드에 이미 구현됨 — 제안)

`map_3d.map_strokes()`는 이음매·각도 한계로 획을 쪼갤 때 이미 조각 사이 관계를 `mapped` 항목에 넣고 있다
(이번에 새로 만든 게 아니라 기존 코드 확인). 아직 공통 규격으로 제안하지 않았던 부분이라 여기 명시한다.

| 필드 | 값 | 의미 |
| --- | --- | --- |
| `stroke_id` | `strokeNNN` 또는 `strokeNNN_partK` | 조각이 하나뿐이면 원본 ID, 쪼개졌으면 조각별 ID |
| `split_from_stroke_id` | 원본 `stroke_id` | 쪼개지지 않았으면 이 필드 자체가 없음 |
| `split_index` | 0-base 순번 | 같은 원본에서 나온 조각들의 순서 |
| `split_count` | 총 조각 수 | |
| `join_forbidden` | `true` (쪼개진 경우 항상) | 쪼개진 조각들을 하나의 연속 CUT으로 다시 이으면 안 됨(이음매를 넘거나 각도 한계를 넘기 때문) |

**미정(변경 없음)**: 구간별 완료 검증 조건(목표·허용오차·확인 방식)은 10절과 같이 실행 측(세은님·시율님) 입력이
있어야 채울 수 있다. 이 절은 "조각들이 서로 어떤 관계인지"만 formalize한 것이고, "각 조각이 언제 완료로
판단되는지"는 별개로 남아 있다.

## 12. 정량 평가 지표 (9/21, **확인**: `c2_path/metrics.py` + `report_metrics.py` 구현)

`samples/bundles/*/output/c2-path-validation(.json)`를 입력으로 아래를 집계한다 (`samples/metrics_report.json`).

- 래스터→벡터 실측 형상 오차(최대/평균, px) — `image_to_svg.convert()`가 이제 각 획의 최종 베지어와 원본 점
  사이 거리를 사후 측정해 `measured_max_error_px`/`measured_mean_error_px`로 낸다. 손으로 만든 SVG를 직접 쓰는
  샘플(`heart`/`heart_pair`/`heart_seam`)은 raster 입력이 없어 해당 없음으로 표시한다.
- 획 보존율(추출 단계 대비 최적화 단계), 2-opt 전후 TRAVEL 감소율(%), CUT/TRAVEL 길이, 분할 관계 개수.
- 검증 실패 사유별 건수(오류 코드 집계), 이음매/원통관통 위반 건수. 각도범위·작업 높이 범위는 9/21부터 생성 실패 사유가 아니라
  실행 사전 점검이므로 샘플별 `execution_precheck` 와 `execution_precheck_out_of_limits_sample_count` 로 따로 센다.
- **다루지 않음** (김세은/`joint_check.py` 담당): 실제 두산 IK 도달 가능성, 경로별 J5/J6 최소 여유, IK 성공
  waypoint 비율.

## 13. 전체 옆면 변환과 실행 사전 점검 (9/21, 팀장님 1차 시험 결과 반영)

**배경**: HMI 는 도안을 원기둥 옆면 전체에 배치하는데, `c2_path` 는 높이 85~130mm 와 각도 ±135° 를 **생성 실패 조건**(당시 값. 높이는 이후 아래처럼 바뀜)으로
써서 그 밖의 도안은 만들지 못했다. 두 값은 오류가 아니라 시율님 9/20 실측(J5, 작업 가능 높이)이지만, 로봇이 닿는 범위이지
도안이 놓일 수 있는 범위가 아니다. 생성 조건과 실행 조건이 한데 묶여 있던 것이 문제였다.

### 13.1 무엇이 바뀌었나 (**확인**: 코드·시험 반영)

| 구분 | 이전 | 지금 |
| --- | --- | --- |
| 도안이 놓일 수 있는 범위 | 높이 85~130mm, θ ±135° (이전 값) | 높이 `0 ~ surface.height_mm`(150mm), 둘레 360° 전체 (`workcell.SURFACE_HEIGHT_RANGE_M`) |
| 범위를 벗어나면 | 생성 실패 (`HEIGHT_OUT_OF_RANGE`, `ANGLE_OUT_OF_RANGE`) | 옆면 **밖**(0 미만·150mm 초과)만 생성 실패 (`HEIGHT_OUT_OF_SURFACE`). 옆면 안이면 생성 성공 |
| 로봇 작업 범위(높이 10~140mm, ±135° — 9/21 시율님 지시로 높이를 85~130mm 에서 변경) | 생성·검증 조건 | **실행 사전 점검**(`execution_readiness`). 범위 밖이어도 경로·미리보기는 만들어진다 |
| 검증 `checks` | `HEIGHT_IN_RANGE`, `ANGLE_IN_REACHABLE_RANGE` | `HEIGHT_ON_SURFACE` (각도 항목 삭제). 모두 통과해야 하는 기하 검사만 남김 |
| 이음매(±180°) | 그대로 — 이음매에서 획을 나누고 이음매를 넘는 이동을 만들지 않음 | 그대로. (이음매를 따라 곧게 놓인 조각을 "이음매를 넘음"으로 잘못 판정하던 오류를 고침 — 전체 옆면에서 θ=180° 도안이 실패하던 원인) |

### 13.2 `execution_readiness` (계약 `c2-path-execution-readiness/1`, **제안**)

검증 보고서(`c2-path-validation.json`)와 미리보기(`c2-path-preview.json`)의 최상위 필드다. **`c2-path.json` 의
`validation` 블록에는 넣지 않았다** — HMI `PathArtifactLoader` 가 그 블록을 `{report_id, passed, checks, not_checked}`
와 정확히 비교하기 때문이다. 보고서·미리보기의 추가 필드는 HMI 가 읽지 않으므로 기존 등록 검증은 그대로 통과한다
(`test_hmi_loader_compat.py` 가 실제 `PathArtifactLoader` 로 확인).

| 필드 | 값·뜻 |
| --- | --- |
| `precheck` | `WITHIN_LIMITS`(모든 CUT 구간이 잠정 범위 안) / `OUT_OF_LIMITS`(하나라도 밖) |
| `executability` | 항상 `NOT_JUDGED`. c2_path 는 실행 가능 여부를 판정하지 않는다 (IK·J5/J6·충돌은 실행 전 검사 몫) |
| `authoritative` | 항상 `false` |
| `limits` | 사용한 범위(`work_height_range_m` — 바닥 기준, `reachable_angle_deg`), `provisional: true`, `source`(출처), `angle_meaning`. 요청 스냅샷의 `surface.valid_v_range_mm`·`reachable_angle_deg` 를 쓰고 없으면 `workcell` 상수. `/2` 면 `source` 가 "요청 스냅샷(/2)" 이다 |
| `checks` | `WORK_HEIGHT_IN_RANGE`, `ANGLE_IN_REACHABLE_RANGE` 각각 통과 여부 |
| `summary` | CUT 구간 수, 범위 밖 CUT 구간 수·획 수·waypoint 수 |
| `out_of_limit_segment_ids`, `violations` | 범위 밖 구간 ID, 위반 목록(최대 100개, `violations_truncated`). 코드: `HEIGHT_OUT_OF_RANGE`, `ANGLE_OUT_OF_RANGE` |
| `not_checked` | c2_path 가 계산하지 않는 항목: `["J5_JOINT_LIMIT","J6_RANGE","IK_REACHABILITY","COLLISION"]` |

**각도 범위(±135°)의 뜻**: 9/20 J5 실측에서 나온 **원통 도달각 참고 범위**(잠정)다. 실제 J5 관절 한계 판정이 아니며, 그래서 `not_checked` 에 `J5_JOINT_LIMIT` 가 남고 `limits.angle_meaning` 에도 그렇게 적는다. 높이 범위는 바닥 기준 로봇 작업 범위다.

미리보기의 각 CUT 구간에는 `execution_precheck`(`WITHIN_LIMITS`/`OUT_OF_LIMITS`)와 `execution_precheck_reasons` 가 붙는다.
점검 대상은 CUT 구간이다. APPROACH/TRAVEL/RETRACT 는 CUT 끝점 사이를 보간하거나 반경만 바꾸므로 모든 CUT 이 범위 안이면
벗어나지 않는다.

### 13.3 `GeneratePath v2` 유지 여부와 HMI 가 바꿔야 할 것

**`GeneratePath` Action 은 v2 그대로 유지한다.** goal 14개·result 12개 필드와 단계 이름은 바뀌지 않았다.

| 항목 | 변경 |
| --- | --- |
| HMI → c2_path (goal, 프로필 스냅샷) | **필드·값 변경 없음.** `surface.valid_v_range_mm=[10,140]`(이전 `[85,130]` — **HMI 가 이 값을 직접 만든다면 바꿔야 한다**), `reachable_angle_deg=[-135,135]` 도 그대로 보내며 뜻만 "로봇 작업 범위(잠정)"로 바뀐다. 도안 배치(`offset_u_mm`, `offset_v_mm`, 크기)는 옆면 전체 안에서 자유롭게 보내도 된다 |
| c2_path → HMI (result) | 필드 변경 없음. `success=true` 여도 실행 가능하다는 뜻이 아니다. `message` 끝에 사전 점검 요약 한 문장이 붙는다 |
| 실패 코드 | 3D 매핑 실패 사유 `HEIGHT_OUT_OF_RANGE` → `HEIGHT_OUT_OF_SURFACE` (이름·의미 변경). 생성 실패에서 `ANGLE_OUT_OF_RANGE` 는 사라졌다 |
| HMI 등록·미리보기 로더 | 코드 변경 없이 통과한다 (실제 로더로 확인) |
| HMI 가 **새로 해야 할 것** | ① 보고서·미리보기의 `execution_readiness` 를 읽어 화면에 표시, ② "생성 성공 ≠ 실행 가능" 문구, ③ `precheck=OUT_OF_LIMITS` 면 실행 요청을 막거나 경고, ④ `WITHIN_LIMITS` 도 `executability=NOT_JUDGED` 이므로 실행 전 검사 결과를 따로 받기 전에는 "실행 가능"으로 표시하지 않기, ⑤ 배치 UI 의 범위 제한을 옆면 전체(높이 0~150mm)로 |
| 미리보기 | `points_uv_mm` 등 기존 필드 그대로. 구간별 `execution_precheck` 로 범위 밖 구간을 다른 색으로 표시 가능 |

`execution_readiness.limits` 는 요청 스냅샷 값을 그대로 쓴다. `/2` 스냅샷은 범위가 상수와 달라도 통과하므로, 시율님이
5° 간격 실측표로 범위를 바꾸면 스냅샷 값만 바꾸면 된다(`/1` 은 상수와 정확히 같아야 한다 — 4.1).

### 13.4 정렬 성능과 진행률 (**확인**)

글자가 많은 이미지에서 `OPTIMIZING_2D` 가 120초를 넘긴 원인은 2-opt 가 후보마다 전체 비용을 처음부터 다시 더하는 것
(패스당 O(n³))이었다. 획 544개(글자 이미지)에서 이전 구현은 (획 60/120/200개 실측에서 추정) 100초 이상, 지금은 0.13초다. `BUILDING_PATH` 의 안전비용
정렬도 같은 구조라 같은 방식으로 고쳤다 (획 200개: 35.6초 → 0.02초). 전체 파이프라인(변환 포함)은 544획 이미지에서 약 2초다.

- 획은 하나도 빼거나 바꾸지 않는다. 방문 순서만 다루며, 같은 입력이면 이전 구현과 같은 순서가 나온다
  (`test_ordering.py` 가 무작위 입력으로 이전 구현과 대조).
- 단계 안 진행률: `OPTIMIZING_2D` 0.38→0.55, `MAPPING_3D` 0.55→0.64, `BUILDING_PATH` 0.72→0.87 구간을 0.2초마다 갱신한다.
  진행률은 줄어들지 않는다.
- 취소·시간 초과는 단계 도중에도 확인한다. 제한 시간의 60% 가 지나면 개선(2-opt)만 멈추고 그 시점의 완전한 순서를 쓴다.
  통계에 `two_opt_stopped_early` 로 남는다. 120초를 넘으면 이전과 같이 `TIMEOUT` 이다.

## 14. REAL 추정값 미리보기 전용 스냅샷 `/3` (9/21, 팀장님 요청 — **이름·필드는 제안**)

REAL 실측(`validity=ESTIMATED` 또는 `FORCE_CONTACT_ESTIMATE`)으로 경로를 **생성·미리보기만** 한다. 실제 가공 승인이 아니다.
`/1`·`/2`·SIMULATION 동작은 바꾸지 않았고, REAL 은 새 계약 `c2-path-test-profile/3` 으로만 받는다.

### 14.1 동작 (**확인**: 코드·시험 `test_real_preview.py`)

| 항목 | 동작 |
| --- | --- |
| 노드 스위치 | ROS 파라미터 `allow_real_preview`(기본 `false`). 꺼져 있으면 REAL Goal 은 `NOT_READY`. 켜도 SIMULATION Goal 은 그대로 받는다 |
| 모드 일치 | Goal `source_mode` 와 스냅샷 `source_mode` 가 같아야 한다. REAL Goal 은 `/3` 과, SIMULATION Goal 은 `/1`·`/2` 와만 계산한다. 어긋나면 `PROFILE_MISMATCH`. REAL 을 SIMULATION 으로 바꿔 통과시키지 않고 그 반대도 없다 |
| 기하·범위 | `/2` 와 같다: 스냅샷의 반지름·높이·축 원점·`valid_v_range_mm`(바닥 기준, 위로 +)·`reachable_angle_deg` 로 계산하고 고정값으로 대체하지 않는다. 변환(윗면 기준 `work_v_range_m` → 바닥 기준)은 HMI 한 곳에서 한다: `valid_v_range_mm = [(H−v_max)·1000, (H−v_min)·1000]` |
| 산출물 | 경로·미리보기·보고서의 `source_mode="REAL"`, 경로 `test_only=true`. 출처·상태는 경로 `config.real_preview`, 미리보기 `real_preview`, 보고서 `real_preview` 에 같은 내용으로 남는다 |
| 실행 금지 표시 | `execution_readiness.execution_blocked = {code: "REAL_ESTIMATE_PREVIEW_ONLY", message}` 를 보고서·미리보기에 추가. `precheck`(WITHIN/OUT_OF_LIMITS) 값은 바꾸지 않는다. `executability` 는 `NOT_JUDGED` 유지. `Result.message` 에도 문장이 붙는다 |
| ID·버전·해시 | `Result.path_id/path_version/path_sha256` = 경로 파일 = 미리보기(`path_id`, `path_version`, `path_sha256`) = 보고서(`path_id`, `path_version`). 경로 `config` 와 미리보기에 스냅샷 ID·해시가 그대로 남는다(보고서는 경로 해시를 넣을 수 없다 — 경로가 보고서 ID 를 담는다) |

### 14.2 `/3` 스냅샷 필수 조건 (**제안**: 이름·값은 합의 전)

`/2` 의 기하 구조 조건(`surface.height_reference="bottom"`, `v_direction="up"`, 범위·치수 구조, 고정 축·이음매)에 더해:

| 필드 | 조건 |
| --- | --- |
| `contract` | `"c2-path-test-profile/3"` |
| `source_mode` | `"REAL"` |
| `calibration_status` | `"REAL_ESTIMATE_PREVIEW_ONLY"` (새 값 — **미정**) |
| `measurement_status` | `"ESTIMATED"` 또는 `"FORCE_CONTACT_ESTIMATE"` = 준비 Result `validity` 값 그대로. 그 밖의 값(SIMULATED, REFERENCE_ONLY, INCOMPLETE 등)은 거절. HMI 백엔드가 이미 쓰는 필드 이름(`measurement_status`)을 따랐다 |
| `measurement_assumptions.independent_accuracy_verified` | 반드시 `false` (정확도 검증 완료로 바꾸지 않는다) |
| 측정 출처 | `preparation_id`, `measurement_id`, `input_profile_snapshot_id`, `measurement_record_id`: 정규화된 UUID. `input_profile_sha256`, `measurement_record_sha256`: 소문자 SHA-256. `measured_at`: 시간대가 있는 ISO 8601. **하나라도 없거나 형식이 틀리면 `PROFILE_MISMATCH`** (보충·추정 없음) |
| 설정 식별자 | `/1`·`/2` 와 같다: `workcell_*`, `tools_config_*`, `tool_*`, `tcp_*`, `load_*`, `frame_id`, `gripper_open_allowed=false`, `schema_version=2`. 다르거나 없으면 거절 |

준비 Action 5.2절이 이미 정한 루트 필드(`preparation_id`, `measurement_id`, `input_profile_*`, `measurement_record_*`)는 그대로 쓰고,
새로 제안하는 것은 계약 이름 `/3`, `calibration_status` 값, HMI 가 이미 쓰는 `measurement_status`·`measurement_assumptions` 를 REAL 에서도 쓰는 것뿐이다.

### 14.3 다른 담당이 바꿔야 하는 것 (c2_path 만으로는 끝나지 않는다)

- **세은님**: `_bind` 가 `ESTIMATED` 를 "경로용 스냅샷 승인은 별도 계약 필요"로 거절한다. 미리보기 전용 스냅샷 등록 방식을 정해야 한다. ExecuteProcess 는 이 경로를 계속 거절해야 한다.
- **팀장님(HMI)**: REAL 모드에서 BIND·GeneratePath 를 허용하지 않고, `artifact_loader` 가 경로·미리보기 `source_mode` 를 `SIMULATION` 으로만 받는다. `/3` 프로파일 조립(등록 설정과 결합), REAL 미리보기 표시, 실행 요청 차단(`execution_blocked`, `OUT_OF_LIMITS`, `test_only`)이 필요하다.
- **실행 방법**: 경로 노드를 `-p allow_real_preview:=true` 로 띄운 경우에만 REAL Goal 을 받는다. HMI REAL 모드는 경로 노드를 자동 기동하지 않으므로 따로 띄워야 한다.
- 이번 시험은 c2_path 단독이다. 파일 묶음(`bundle`)은 SIMULATION 만 지원하고 REAL 은 지원하지 않는다.
