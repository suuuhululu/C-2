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
- 경로에는 각자 PC 의 절대 경로를 넣지 않는다. 묶음 안의 상대 파일명만 쓴다.

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

## 4. 스냅샷 필드 표 (현재 `c2-path-test-profile/1`)

검증 열은 현재 `validate_profile` 동작이다. "정확 일치"는 `workcell.py` 상수와 같아야 통과한다는 뜻이다.

| 필드 | 값(현재) | 검증 (**확인**) | 비고 |
| --- | --- | --- | --- |
| `contract` | `c2-path-test-profile/1` | 미검사 | 형식 식별자. 실측 프로필 계약 이름은 **미정** |
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
| `surface.valid_v_range_mm` | `[85, 130]` | 정확 일치 | 바닥 기준 작업 가능 높이 (= 윗면 아래 20~65mm) |
| `surface.u_origin_angle_deg` | `0` | 정확 일치 | u=0 이 놓이는 각도 (0° = +X, 로봇 반대편) |
| `surface.seam_angle_deg` | `180` | 정확 일치 | 이음매 = −X, 로봇 쪽 (J5 위험) |
| `surface.reachable_angle_deg` | `[-135, 135]` | 정확 일치 | J5 안전 범위 — **잠정**, 5° 간격 실측표 대기 (시율님) |

## 5. 실측값을 받는 새 프로필에 필요한 기하 필드와 허용 조건 (홍동님 요청 2)

**현재 한계 (확인)**: `validate_profile` 은 스냅샷이 코드 상수와 **정확히 같은지**만 본다. 즉 c2_path 는 아직
"스냅샷의 실측값으로 경로를 만드는" 상태가 아니라 "스냅샷이 고정 상수와 같음을 확인"하는 상태다.
9/20 확정 방침(작업 시작 전 1회 실측 → 그 좌표로 경로 재생성)을 구현하려면 `workcell.py` 의
`RADIUS_M`, `AXIS_ORIGIN_XY_M`, `TOP_Z_BASE_M`, `SEAM_ANGLE_DEG`, `REACHABLE_ANGLE_DEG` 등을 **스냅샷에서 읽도록**
바꿔야 한다(모듈 상수 → 요청별 값). 이는 계산 전체에 걸친 변경이라 스냅샷 형식이 확정된 뒤에 진행한다.

**필요한 기하 필드 (제안)** — 4절의 `surface.*` 와 같은 이름·단위를 유지하고, 실측값을 담는다.

| 필드 | 실측/고정 | 구조 조건 (**확인**: `snapshot.surface_geometry_errors`) | 수치 허용 범위 |
| --- | --- | --- | --- |
| `surface.radius_mm` | 실측 (캘리퍼스) | 유한, > 0 | **미정** — 시율님 (양초 규격·측정 오차 ±0.3mm 기준 상·하한) |
| `surface.height_mm` | 실측 | 유한, > 0 | **미정** — 시율님 |
| `surface.axis_origin_m` | 실측 (`workpiece_calibration`) | 유한한 수 3개 `[x, y, 바닥 z]` | 명목값 대비 허용 이동량 **미정** — 시율님 (9/20 재장착 시 3~5mm 어긋남 관측 → 5mm 이상 필요) |
| `surface.axis_direction` | 고정 | `[0, 0, 1]` | 없음 |
| `surface.valid_v_range_mm` | 고정(작업 정의) | `0 <= 하한 < 상한 <= height_mm` | 윗면 아래 20~65mm 는 시율님 확정, 실측 프로필에서 유지할지 **미정** |
| `surface.u_origin_angle_deg` | 고정(배치 정의) | −180~180 | 없음 |
| `surface.seam_angle_deg` | 고정 | −180 초과 180 이하 | 없음 |
| `surface.reachable_angle_deg` | 실측(J5) | `−180 <= 하한 < 상한 <= 180`, **이음매가 범위 안에 들어가지 않음** | 5° 간격 실측표 후 확정 — 시율님 |
| `tool_id`, `tools_config_*`, `tcp_*`, `load_*`, `frame_id` | 고정 | 3·4절 | 실측 프로필에서도 정확 일치 유지 제안 |
| 측정 시각·측정 ID·유효 상태 | 실측 메타 | — | **미정** — 시율님, 이유: `workpiece_calibration.py` 결과 형식 별도 합의 필요 |

구조 조건은 `c2_path/snapshot.py` 에 구현돼 있고 `test_snapshot.py` 가 확인한다. 아직 `pipeline` 이 호출하지는 않는다.

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

샘플: `samples/bundles/heart_ok/{input,output}` (검증 통과), `samples/bundles/heart_seam_rejected/{input,output}` (검증 실패).
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
**등록하지 않거나 실행 불가로 표시**, ③ `manifest.inputs` 의 스냅샷·이미지 ID·해시가 HMI 에 등록된 값과 같음.

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
| 실측 프로필 계약 이름·`calibration_status` 값 체계·측정 메타(시각·ID·유효 상태) | 시율님 | `workpiece_calibration.py` 결과 형식이 별도 합의 대상 |
| `surface.radius_mm`·`height_mm` 허용 범위, 명목 축 대비 허용 이동량 | 시율님 | 재장착 이동량(3~5mm) 관측만 있고 허용 기준 미확정 |
| `surface.reachable_angle_deg` 확정값 | 시율님 | 5° 간격 J5 실측표 대기 (현재 ±135° 잠정) |
| 측정 결과를 `surface` 로 낼지 `workcell` 로 낼지 | 시율님·홍동님 | 결과 형식 합의 전 |
| `TipCalibration` 을 스냅샷에 포함할지 | 시율님·세은님 | (a)안 범위와 측정 결과 형식이 아직 정해지지 않음 |
| `tools_config_*` 와 실제 `tools.yaml` 버전 체계 | 세은님 | tools.yaml 변경 이력 규칙 미확정 |
| 4개 motion profile 값, `tool_profile`(접촉 방식·depth·clearance·touch), stop_profile, `limits_deg` | 세은님·시율님 | 실기 값 미확정 |
| 가공 깊이 적용 위치 | 세은님·시율님·홍동님 | 9절 제안 확정 필요 |
| 스냅샷 계약(스키마) 버전 부여 방식 | 팀 전체 | 공통 형식이 PR 로 확정되기 전 |
| manifest 규격 (7절) | 팀장님·홍동님 | HMI 가져오기 대조 후 확정 (현재 제안) |
| 실제 `workcell.py` 상수 → 요청별 값으로 전환 | 홍동님 | 스냅샷 형식 확정 후 진행 (5절) |
