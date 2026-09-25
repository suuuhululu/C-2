# 새김 Interface Specification

> 기준: 2026-09-25 `origin/main` `987a3b7`(PR #90 병합). 이 문서는 발표·교차 검토용 인터페이스 명세다. 설명보다 같은 커밋의 실제 코드와 `c2_interfaces` 타입을 우선한다. 실제 장치 설치본이 다르면 송수신 PC의 타입과 설정을 다시 대조한다.

## 1. 목적과 적용 범위

운영자 HMI, FastAPI 서버, ROS 게이트웨이, 경로 노드, 공정 노드가 주고받는 값을 한 문서에서 확인한다. 브라우저는 로봇과 직접 통신하지 않으며, 서버의 `monitor_gateway_node`가 HTTP·WebSocket과 ROS 2 사이를 변환한다.

```text
운영자 React HMI
  └─ HTTP·WebSocket
      FastAPI·SQLite·관리 파일
        └─ monitor_gateway_node
            ├─ /c2/prepare_workpiece  ─ process_controller_node
            ├─ /c2/generate_path      ─ path_planner_node
            ├─ /c2/execute_process    ─ process_controller_node
            ├─ /c2/stop_process       ─ process_controller_node
            ├─ /c2/process_state      ← process_controller_node
            └─ /c2/process_events     ← process_controller_node
```

REAL 또는 승인된 `entry_planning.enabled=true`의 prepared 정상 흐름은 다음과 같다.

`MEASURE → 측정 원본 저장 → BIND_SNAPSHOT → GeneratePath → 미리보기 → 별도 ExecuteProcess → PRECHECK → ENTRY → ENGRAVE → RETURN_HOME → FINISH`

entry 비활성 호환 흐름에서는 `ENTRY`와 `RETURN_HOME` 콜백이 생략될 수 있다. `RETURN_HOME`은 entry 활성 prepared 성공 경로에 연결되어 있다. 실패·취소·정지 미확인 뒤 무조건 HOME으로 움직인다는 뜻은 아니다. 각 단계가 실패하면 다음 단계에 진입하지 않는다.

## 2. 계약 원본과 책임

| 구분 | 코드 원본 | 책임 |
| --- | --- | --- |
| HTTP 라우트 | `backend/app/monitor.py` | 상태 조회, 요청 접수, 관리 파일 제공 |
| HTTP 요청 모델 | `backend/app/monitor_contract.py` | 자료형, 허용 범위, 필수 필드 |
| 요청 순서·중복·제한 시간 | `backend/app/monitor_service.py`, `backend/app/preparation.py` | 실행 게이트, 결과 상태, 저장 |
| HTTP↔ROS 변환 | `backend/app/ros_bridge.py`, `backend/app/ros_preparation.py` | 타입 변환, Goal/Result/Feedback 전달 |
| 브라우저 소비 계약 | `frontend/src/monitor/api.ts` | 화면 모델, 단계·상태 표시 |
| ROS 필드 | `ws_cobot1/src/c2_interfaces/{action,srv,msg}` | 송수신 타입의 최종 원본 |
| 경로 처리 | `ws_cobot1/src/c2_path/c2_path/node.py` | 경로 생성 Action, 취소, 동시 요청 차단 |
| 공정 처리 | `ws_cobot1/src/c2_process/c2_process/node.py` | 준비·실행·정지, 상태·이벤트 발행 |

문서와 코드가 다르면 위 코드 원본을 우선하고 문서를 갱신한다. `schema_version=2`가 같더라도 생성된 ROS 타입의 필드가 다르면 호환되지 않는다.

## 3. 공통 규칙

| 항목 | 계약 |
| --- | --- |
| 스키마 | 고정 드릴 팀 계약 `schema_version=2`; ROS 배포판·패키지 버전·경로 버전과 별개 |
| 모드 | `SIMULATION` 또는 `REAL`; HMI, Goal, 스냅샷, 경로, 실행 노드가 일치해야 함 |
| ID | HTTP 입력의 ID는 UUID 형식. `request_id`는 논리 요청, `run_id`는 실제 실행 시도 식별자 |
| 해시 | SHA-256 소문자 64자리. JSON 재직렬화 값이 아니라 저장된 원본 바이트 기준 |
| 경로 | `path_id` + `path_version` + `path_sha256`을 미리보기·검사·실행에서 동일하게 사용 |
| 2D 단위 | 도안 크기·배치 `mm`, 화면 회전 `deg` |
| 3D 단위 | `c2_base` 기준 드릴 끝 위치 `m`, 정규화 quaternion `(x,y,z,w)` |
| 관절·시간 | 관절 `rad`, 경과 시간 `s`, 온도 `°C`, 힘 `N` |
| 절대 시각 | ROS는 `builtin_interfaces/Time`, HTTP·DB는 시간대가 포함된 RFC3339 UTC 문자열 |
| 성공 판정 | HTTP 202, ROS Goal 수락, 실제 모션 완료, 실물 품질 합격은 서로 다른 상태 |
| 미확인 값 | 성공으로 보정하지 않고 `UNKNOWN`, `null`, 빈 배열 또는 0/0 시각으로 보존 |

## 4. HMI ↔ FastAPI HTTP·WebSocket

### 4.1 요청 공통 조건

- 변경 요청은 `x-c2-monitor: 1` 헤더가 필요하다. `Origin`이 있으면 로컬 허용 목록과 일치해야 한다.
- JSON 모델은 정의되지 않은 필드를 거절하고 `NaN`·무한대를 허용하지 않는다.
- 프런트 공통 HTTP 대기 시간은 기본 7초다. 시간 초과는 작업 실패 확정이 아니므로 같은 `request_id`로 조회한다.
- 이미지 원본은 PNG/JPEG, 최대 10 MiB, 16 MP, 한 변 6000 px다.
- 오류 본문은 기본적으로 `{ "error_code": "...", "message": "..." }`이다. 입력 모델 오류는 FastAPI 422 형식이다.

### 4.2 운영 API

| Method | 경로 | 입력 | 정상 응답·의미 |
| --- | --- | --- | --- |
| GET | `/api/operator/snapshot` | 없음 | 최신 서버·준비·생성·실행·상태·이벤트 스냅샷 |
| POST | `/api/operator/preparations` | `PreparationInput` | `202`; 준비 요청 접수 기록. 측정/BIND 완료 아님 |
| GET | `/api/operator/preparations` | 없음 | 준비 이력 목록 |
| GET | `/api/operator/preparations/{request_id}` | URL의 `request_id` | 준비 상세·피드백·결과 |
| POST | `/api/operator/preparations/{request_id}/cancel` | 없음 | `202`; CancelGoal 전달 시작. 실제 중단은 최종 상태로 확인 |
| POST | `/api/operator/assets` | multipart `file` | `201`; 원본·썸네일 관리 ID와 SHA-256 |
| GET | `/api/operator/assets/{asset_id}/content` | URL의 `asset_id` | 해시 재검사 후 원본 바이트 |
| POST | `/api/operator/path-generations` | `GenerateInput` | `202`; 생성 요청 접수 상태 |
| GET | `/api/operator/path-generations/{request_id}` | URL의 `request_id` | 생성 상태·단계·진행률·Result |
| POST | `/api/operator/path-generations/{request_id}/cancel` | 없음 | `202`; 취소 요청. 최종 `FAILED`/`UNKNOWN`을 별도 확인 |
| GET | `/api/operator/paths/{path_id}/versions/{version}` | 경로 ID·버전 | 경로 메타데이터와 미리보기, 산출물 URL |
| POST | `/api/operator/runs` | `RunInput` | `202`; 서버가 `run_id`, 운영자·확인 시각을 붙여 실행 접수 |
| GET | `/api/operator/runs` | 없음 | 실행 이력 |
| GET | `/api/operator/runs/{run_id}` | URL의 `run_id` | 실행 상세와 사후 검사 기록 |
| POST | `/api/operator/runs/{run_id}/stop` | `StopInput` | `202`; 정지 접수 응답. 실제 정지 완료 아님 |
| GET | `/api/operator/alarms` | 없음 | 알람 이력 |
| POST | `/api/operator/inspections` | `InspectionInput` | `201`; 종료가 확인된 실행의 운영자 판정 저장 |
| POST | `/api/operator/simulation/scenario` | `ScenarioInput` | MOCK 시나리오 변경. 진행 중 작업이 있으면 거절 |
| POST | `/api/operator/simulation/reset` | 없음 | MOCK 상태만 초기화; 실행 이력·파일·DB는 보존 |
| WS | `/api/operator/stream` | 로컬 허용 Origin | 약 0.4초마다 `{type:"snapshot", data:Snapshot}` 전송 |

### 4.3 파일 교환 보조 API

이 API는 ROS를 대체하지 않는다. 팀 간 입력·결과 ZIP 전달과 미리보기를 위한 보조 경계다.

| Method | 경로 | 의미 |
| --- | --- | --- |
| GET/POST | `/api/operator/integration/profiles` | 프로파일 목록/JSON 파일 등록 |
| POST | `/api/operator/integration/profiles/{profile_id}/select` | 현재 프로파일 선택 |
| POST/GET | `/api/operator/integration/inputs`, `/inputs/{request_id}` | 생성 입력 묶음 작성/ZIP 다운로드 |
| POST | `/api/operator/integration/results` | 결과 ZIP 가져오기 |
| GET | `/api/operator/integration/paths` | 가져온 경로 목록 |
| GET | `/api/operator/integration/paths/{path_id}/versions/{version}/bundle` | 결과 ZIP 다운로드 |

가져온 `FILE_BUNDLE` 경로는 HMI 실행 입력으로 사용할 수 없다.

### 4.4 HTTP 요청 모델

#### `PreparationInput`

| 필드 | 형식·조건 | 설명 |
| --- | --- | --- |
| `request_id` | UUID | 같은 내용 재전송은 기존 기록 반환; 다른 내용은 `REQUEST_CONFLICT` |
| `input_profile_snapshot_id` | UUID | 측정 전 설정 관리 ID |
| `input_profile_sha256` | SHA-256 | 설정 원본 바이트 해시 |
| `height_m` | `> 0` | 운영자가 자로 측정한 높이. 등록 설정과 일치해야 함 |
| `operator_confirmed_fixed_cell` | REAL에서 `true` | 고정 설비·드릴 체결·드릴 OFF·이동 경로·감시 확인. 센서값이 아님 |

HTTP 준비 입력에는 `schema_version`, `source_mode`, `preparation_id`, `measurement_id`가 없다. 서버가 현재 모드와 새 ID를 넣어 ROS Goal을 만든다.

#### `GenerateInput`

| 필드 | 형식·범위 |
| --- | --- |
| `schema_version` | 항상 `2` |
| `request_id`, `asset_id`, `profile_snapshot_id` | UUID |
| `source_mode` | `SIMULATION` 또는 `REAL` |
| `asset_sha256`, `profile_sha256` | SHA-256 |
| `width_mm`, `height_mm` | `0 < 값 ≤ 500` |
| `offset_u_mm`, `offset_v_mm` | `-500..500` |
| `rotation_deg` | `-180..180` |
| `conversion_preset` | `simulation_centerline` 또는 `raster_centerline_bezier` |
| `tool_id` | `engraving_drill` |

#### `RunInput`

| 필드 | 형식·조건 |
| --- | --- |
| `schema_version` | 항상 `2` |
| `request_id`, `path_id` | UUID |
| `source_mode` | `SIMULATION` 또는 `REAL` |
| `path_version` | 1 이상 정수 |
| `path_sha256` | SHA-256 |
| `operator_confirmed_fixture` | 반드시 `true`; 공작물 고정 확인 |

서버가 새 `run_id`, `operator_id=local-operator`, `confirmed_at`을 생성한다. 화면의 드릴 ON 체크는 이 모델이나 ROS Goal의 전원 센서 필드가 아니다.

#### `StopInput`, `InspectionInput`

| 모델 | 필드 |
| --- | --- |
| `StopInput` | `schema_version=2`, UUID `request_id`, 1~300자 `reason`; `run_id`는 URL에서 서버가 결합 |
| `InspectionInput` | UUID `run_id`, `PASS/HOLD/REJECT` verdict, 1~500자 reason |

### 4.5 Snapshot과 상태 해석

`Snapshot`의 주요 필드는 `source_mode`, `transport`, `connection`, `server_time`, `profile`, `preparation`, `active_run`, `execution_pending`, `generation`, `events`, `state`, `storage_error`, `contract_status`, `path_generation`이다.

| 대상 | 상태 |
| --- | --- |
| 준비 | `ACCEPTED`, `RUNNING`, `CANCELING`, `SUCCEEDED`, `FAILED`, `STOPPED`, `UNKNOWN`, `INVALIDATED` |
| 준비 연결 | `PENDING`, `MEASUREMENT_ONLY`, `MEASURED_UNBOUND`, `BOUND_MOCK`, `BOUND_ROS`, `UNCONFIRMED`, `REPREPARATION_REQUIRED` |
| 경로 생성 | `ACCEPTED`, `RUNNING`, `CANCELING`, `SUCCEEDED`, `FAILED`, `UNKNOWN` |
| 실행 | `ACCEPTED`, `RUNNING`, `STOPPING`, `STOPPED`, `SUCCEEDED`, `FAILED`, `UNKNOWN` |
| prepared 단계 | `PRECHECK`, `ENTRY`, `ENGRAVE`, `RETURN_HOME`, `FINISH` |
| 정지 | `NONE`, `REQUESTED`, `ACCEPTED`, `STOPPING`, `CONFIRMED`, `FAILED`, `UNKNOWN` |

`connection=STALE`, 실행/준비/생성 `UNKNOWN`, `stop_state=UNKNOWN`, `storage_error`가 있으면 새 작업을 시작하지 않는다.

## 5. FastAPI ↔ ROS 2 공통 인터페이스

### 5.1 `/c2/prepare_workpiece` · `PrepareWorkpiece` Action

| 구역 | 필드 |
| --- | --- |
| Goal | `schema_version`, `operation`, `request_id`, `preparation_id`, `measurement_id`, `source_mode`, `input_profile_snapshot_id/sha256`, `measurement_record_id/sha256`, `profile_snapshot_id/sha256` |
| Result 식별·상태 | `request_id`, `preparation_id`, `measurement_id`, `operation`, `source_mode`, `outcome`, `error_code`, `message`, `stop_confirmed`, `partial`, `geometry_ready`, `snapshot_bound`, 각 설정/원본 ID·해시, `log_id` |
| Result 측정 | `frame_id`, `validity`, `started_at`, `measured_at`, `height_source`, `height_m`, `axis_xy_m`, `radius_m`, `top_z_m`, `bottom_z_m`, `work_v_range_m`, `work_z_range_m`, 잔차, 가정/검증 bool, 접촉 9점 배열 |
| Feedback | 요청·준비·측정 ID, `operation`, `stage`, `progress`, 완료/전체 옆면 점 수, `elapsed_s`, `message` |

- `MEASURE`는 측정을 수행하며 BIND 관련 네 ID·해시를 빈 문자열로 보낸다.
- `BIND_SNAPSHOT`은 저장된 측정 원본과 새 불변 스냅샷을 대조하며 로봇을 움직이지 않는다.
- 준비 취소는 표준 Action CancelGoal을 사용한다. `/c2/stop_process`에 준비 ID를 넣지 않는다.
- 성공한 BIND는 `outcome=SUCCEEDED`, `snapshot_bound=true`, `geometry_ready=true`, `stop_confirmed=true`, `partial=false`, `error_code=NONE`을 모두 만족해야 한다.

### 5.2 `/c2/generate_path` · `GeneratePath` Action

| 구역 | 필드 |
| --- | --- |
| Goal | HTTP `GenerateInput`과 동일한 14개 필드 |
| Result | `success`, `error_code`, `message`, `path_id/version/sha256`, `svg_asset_id`, `preview_asset_id`, `segment_count`, `cut_length_m`, `validation_passed`, `validation_report_id` |
| Feedback | `request_id`, `stage`, `progress` |

단계는 `CONVERTING → EXTRACTING_2D → OPTIMIZING_2D → MAPPING_3D → BUILDING_PATH → VALIDATING`이다. 생성 성공과 `validation_passed`는 실제 로봇 실행·품질 합격이 아니다.

### 5.3 `/c2/execute_process` · `ExecuteProcess` Action

| 구역 | 필드 |
| --- | --- |
| Goal | `schema_version`, `request_id`, `run_id`, `source_mode`, `path_id/version/sha256`, `operator_confirmed_fixture`, `operator_id`, `confirmed_at` |
| Result | `run_id`, `outcome`, `error_code`, `message`, `last_completed_segment_id`, `log_id` |
| Feedback | `run_id`, `phase`, `engraving_progress`, `completed_segment_id`, `elapsed_s` |

`outcome`은 `SUCCEEDED`, `FAILED`, `STOPPED`, `UNKNOWN` 중 하나다. REAL 또는 승인된 entry 활성 prepared 단계는 `PRECHECK → ENTRY → ENGRAVE → RETURN_HOME → FINISH`다. entry 비활성 prepared 흐름에서는 `ENTRY`와 `RETURN_HOME`이 생략될 수 있고, 직접 실행 호환 경로에서는 `TOOL_CHECK`, `APPROACH`, `RETRACT`가 보일 수 있으므로 HMI는 알려지지 않은 단계도 원문을 보존한다.

### 5.4 `/c2/stop_process` · `StopProcess` Service

| Request | Response |
| --- | --- |
| `schema_version`, `request_id`, `run_id`, `reason` | `accepted`, `run_id`, `stop_state`, `error_code`, `message` |

`accepted=true`는 정지 요청을 받았다는 뜻이다. 실제 정지는 `ProcessState.status=STOPPED`와 `stop_state=CONFIRMED`, 또는 `ExecuteProcess.Result.outcome=STOPPED`로 확인하고 서버의 최종 실행 상태에 반영한다. 정지 요청 후 성공 응답이 늦게 와도 서버는 성공으로 승인하지 않는다.

### 5.5 `/c2/process_state` · `ProcessState` Topic

상태·단계·진행률·정지·오류와 함께 도구, 그리퍼, 관절, TCP, 온도, 로봇 연결의 값·품질·측정 시각을 보낸다.

- QoS: reliable, volatile, keep-last 1. 초기 발행 주기는 5 Hz다.
- `source_epoch + seq`로 재시작과 역순/중복 상태를 판정한다.
- `status`: `IDLE/RUNNING/STOPPING/STOPPED/SUCCEEDED/FAILED/UNKNOWN`.
- 신호 품질이 `VALID`가 아니면 HMI 변환에서 해당 수치를 `null`/빈 값으로 처리한다.
- `ProcessState.tcp`는 제어기 TCP 관측값이며 경로의 드릴 끝 waypoint가 아니다.

### 5.6 `/c2/process_events` · `ProcessEvent` Topic

- QoS: reliable, volatile, keep-last 100.
- `event_id`로 서버가 중복을 제거하고 SQLite에 기록한다.
- `event_type`: `COMMAND`, `PHASE_CHANGED`, `ALARM_RAISED`, `ALARM_CLEARED`, `RUN_FINISHED`.
- `severity`: `INFO`, `WARNING`, `ERROR`.
- Topic 자체는 영구 저장소가 아니다. `occurred_at`과 서버 수신·저장 시각을 구분한다.

## 6. 제한 시간·중복·취소·정지

| 항목 | 코드 기준 | 시간 초과/재전송 처리 |
| --- | --- | --- |
| HMI 일반 HTTP | 7초 | 결과 미확정 문구 후 같은 ID 조회 |
| 상태 freshness | 마지막 상태 수신 후 2초 미만 | 초과 시 `STALE`, 새 실행 차단 |
| 준비 전체 | 준비 설정 `runtime_timeout_s`; 기본 300초 | CancelGoal 후 최대 5초 결과 대기, 미확인은 `UNKNOWN` |
| BIND | 30초 | 미확인 시 준비 `UNKNOWN/UNCONFIRMED` |
| 경로 생성 | 120초 | 취소 전달 후 최대 5초 결과 대기, 미확인은 `UNKNOWN` |
| ROS Goal 수락 | 3초 | 늦은 수락에도 취소 요청, 결과는 미확인 |
| 실행 Result | 최대 3600초 | 시간 초과/통신 오류는 자동 재실행하지 않음 |
| Stop Service 응답 | 1초 | 응답 미확인 시 `STOP_UNCONFIRMED` |
| 실제 정지 확인 | 접수 후 3초 | 미확인 시 실행 `UNKNOWN`, 새 작업 차단 |

- 같은 `request_id`와 같은 입력은 기존 결과를 반환한다.
- 같은 `request_id`에 다른 입력은 `REQUEST_CONFLICT`다.
- 새 실행 요청마다 서버가 새 `run_id`를 만든다.
- `UNKNOWN`은 다른 요청이나 늦게 도착한 성공으로 자동 해제하지 않는다.
- 준비/생성/실행/미확인 작업이 있으면 겹치는 작업은 `BUSY`로 거절한다.

## 7. 주요 오류와 HMI 조치

| 오류 코드·HTTP | 의미 | HMI 처리 |
| --- | --- | --- |
| `FORBIDDEN`·403 | 로컬 모니터 헤더/Origin 불일치 | 요청 중단, 접속 경로 확인 |
| `ASSET_NOT_FOUND`·404 | 기록 또는 파일 없음 | ID를 새로 추측하지 말고 목록/준비부터 재조회 |
| `REQUEST_CONFLICT`·409 | 같은 요청 ID에 다른 입력 | 새 논리 요청이면 새 UUID 발급 |
| `BUSY`·409 | 다른 준비·생성·실행·미확인 작업 존재 | 현재 작업 상태 확인 후 대기 |
| `NOT_READY`·409 | 준비/BIND/상태/서버 조건 미충족 | 메시지의 선행 조건 해결 |
| `RUN_MISMATCH`·409 | 현재 실행과 정지 대상 불일치 | 최신 `active_run.run_id` 재조회 |
| `HASH_MISMATCH`·409 | 관리 파일 원본 바이트 변경 | 실행 금지, 원본 재등록·경로 재생성 |
| `PROFILE_MISMATCH`·409 | 설정·측정·경로 참조 불일치 | 새 스냅샷과 경로 생성 |
| `SOURCE_MODE_MISMATCH`·409 | SIMULATION/REAL 불일치 | 모드 변경으로 우회하지 말고 동일 배포 설정 확인 |
| `VALIDATION_FAILED`·409 | 경로/입력 검증 실패 | 진단 보고서 확인, 실행 금지 |
| `UNSUPPORTED_FORMAT`·415/422 | 이미지·preset 불지원 | 지원 형식으로 다시 입력 |
| `STORAGE_ERROR`·503 | SQLite/관리 파일 저장 실패 | 새 작업 접수 금지, 저장소 복구 |
| `COMMUNICATION_LOST` | Action/Topic 결과 미확인 | `UNKNOWN` 표시, 자동 재시작 금지 |
| `STOP_UNCONFIRMED` | 정지 요청 뒤 실제 정지 미확인 | 현장 상태 확인 전 재실행 금지 |
| `TIMEOUT` | 정해진 시간 안에 결과 미확정 | 취소/정지 결과 확인 후 운영자 판단 |

## 8. 검증·안전 경계

- HMI의 정지 버튼은 소프트웨어 공정 정지 요청이며 물리적 비상정지 장치가 아니다.
- REAL 경로의 `real_execution_allowed=true`는 실행 후보 표시다. 공정 노드의 PRECHECK·IK·관절 검사와 현장 감독을 대체하지 않는다.
- 경로 진행률과 완료 segment는 로봇 명령 진행 정보다. 실제 홈 깊이·선폭·조각 품질 합격이 아니다.
- `RETURN_HOME`은 entry가 활성인 prepared 정상 성공 경로에서 검사된 계획으로 수행한다. 실패·보호정지·정지 미확인 뒤 자동 HOME 복귀를 지시하지 않는다.
- 철사 고정 중에는 그리퍼 열기, 자동 집기·반납·청소를 요청하지 않는다.
- 이 문서는 최신 main 코드 계약을 설명하며 실제 M0609에서 모든 오류·정지·HOME 복귀와 반복 가공 품질이 검증되었다는 뜻은 아니다.

## 9. 코드 대조 결과 · 2026-09-25

| 발견한 불일치 | 코드 근거 | 조치 |
| --- | --- | --- |
| 주요 문서가 entry 활성 prepared 흐름에서 `RETURN_HOME`을 누락 | `state_machine.run_prepared_process`, `ProcessCoordinator._run_active`, 프런트 `preparedPhaseOrder` | 조건부 적용 범위와 함께 현재 구조·인터페이스·실행 안내·공통 메시지 주석 갱신 |
| 공정 README가 HOME 복귀를 “미연결”로 설명 | 최신 coordinator가 검사된 `prepared_return_home`을 전달 | 정상 성공 경로 연결과 실패 후 자동 복귀 금지를 구분해 수정 |
| `PrepareWorkpiece` README/주석이 “권장안·통합 전”으로 표시 | FastAPI PreparationService, RosBridge, process ActionServer가 모두 사용 | 현재 연동 상태와 검증 경계를 반영 |
| HMI Interface 문서가 주요 API 이름만 나열 | `monitor.py`, `monitor_contract.py`, `monitor_service.py`에 실제 계약 존재 | HTTP/WS 요청·상태·오류·제한 시간·중복/취소 규칙을 본 문서에 명시 |
