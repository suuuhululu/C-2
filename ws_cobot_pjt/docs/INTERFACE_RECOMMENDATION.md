> 9/22 HMI 작업 변경: [REAL 실행 연결 계약](HMI_REAL_EXECUTION_20260922.md). 아래의 REAL 측정 전용 설명은 이전 기준이며, 현재 작업 브랜치는 BIND·생성·실행 요청을 연결한다. 상대 PR과 실기 검증은 별도다.

# 3개 노드의 인터페이스 권장안 v2 · 고정 드릴

> **준비 Action 권장안 추가:** `/c2/prepare_workpiece`의 MEASURE/BIND_SNAPSHOT과 담당자별 구현은 [준비 Action 공통 구현 기준](PREPARE_WORKPIECE_ACTION.md)을 따른다. 기존 v2 타입은 유지하며, 새 타입 생성과 서버/클라이언트 연결 완료를 구별한다.

> **2026-09-21 사용자 운영 결정:** 드릴 ON은 HMI 수동 확인으로 한정하며 HTTP 실행 요청·ExecuteProcess 필드와 공정 검사/대기 대상으로 추가하지 않는다. 그리퍼/드릴 제어 명령은 제외하고 장착 상태는 실제 하드웨어 Topic의 관측으로 확인한다. 사전 검사에는 필요 시 검사된 홈 이동과 도착·정지 후 상태 재검사를 포함한다. [수현 작업 목록](HMI_ACTION_ITEMS_20260921.md)·[세은님 전달 문서](PROCESS_HANDOFF_20260921.md)에 구현 차이·전환 범위를 기록했다. 아래 배포 v2의 기존 필드와 역사적 준비 순서는 보존하며, 준비 Action·관측 연결 구현 완료나 REAL 승인으로 해석하지 않는다. 아래 9/20 안내의 운영자 드릴 확인 통신 대기는 이 결정으로 대체한다.

> **9/20 설계 변경 검토:** 이 문서의 v2는 현재 공통 타입 기준이다. 사용자 요청에 따른 준비 확인→양초 실측→c2_path의 3D 경로 생성→미리보기→최종 관절 검사 흐름은 [변경안과 계약 대기 항목](INTERFACE_GUIDE.md)에 구분했다. 경로 생성 전 준비/측정 요청·측정 스냅샷 전달·운영자 드릴 확인은 아직 통신 계약에 반영되지 않았다. 아래 기존 PRECHECK/TOOL_CHECK 순서를 새 흐름의 구현 완료로 해석하지 않는다. 이번 문서화에서는 타입·schema_version을 변경하지 않는다. 역할은 **이시율 측정 → 실측 좌표 전달 → 노홍동 경로 생성 → 김세은 관절 검사 → 이시율 조각**으로 정리한다. 생성 후 prepared_path.py의 중심 재이동은 제외하며, 고정 장착 기준 재사용·정밀 보정 후순위 등 첫 통합 범위는 [공정 README](../ws_cobot1/src/c2_process/README.md#1차-통합-범위)를 따른다.

2026-09-18 작성, 2026-09-19 공통 타입 구현 반영. [목표 디렉토리 구조](SYSTEM_STRUCTURE.md)의 `monitor_gateway_node`, `path_planner_node`, `process_controller_node`를 연결하기 위한 팀 계약 초안이다. 먼저 [팀 인터페이스 안내](INTERFACE_GUIDE.md)에서 전체 흐름과 노드·파일의 차이를 확인한다. 아래 이름·필드·함수는 팀 계약이며 두산 제조사 API가 아니다. 공통 타입 5개의 Jazzy 빌드·직렬화와 서버 변환을 확인했다. 전체 노드 통합·로봇 시험은 완료하지 않았다. 자료형은 12절, 9/19 고정 드릴 전환은 13절과 [운영 결정](C2_FIXED_DRILL_20260919.md)을 따른다. 현재 schema_version=2다.

드릴 `engraving_drill`은 그리퍼에 철사로 고정하며 그리퍼 열기·자동 집기·청소·반납을 금지한다. 초기화·종료·오류 복구·정지·보정에도 열기 금지를 적용한다. 작업대·작업대상은 등록된 고정 좌표를 사용한다. 고객 주문·대기열·별도 그리퍼 노드를 추가하지 않는다. 같은 PC에서 서버와 ROS가 관리되는 파일 저장소를 사용하는 구성을 기준으로 한다.

## 1. 통신 목록

| 이름 | 형식 | 요청/발행 측 | 처리/구독 측 | 책임 |
| --- | --- | --- | --- | --- |
| `/c2/generate_path` | `c2_interfaces/action/GeneratePath` | 모니터 게이트웨이 | 좌표 노드 | 이미지부터 실행 경로·미리보기까지 생성 |
| `/c2/execute_process` | `c2_interfaces/action/ExecuteProcess` | 모니터 게이트웨이 | 공정 제어 | 준비·드릴 고정·보정 확인 후 조각·이탈·완료 |
| `/c2/stop_process` | `c2_interfaces/srv/StopProcess` | 모니터 게이트웨이 | 공정 제어 | 정지 요청을 우선 접수 |
| `/c2/process_state` | `c2_interfaces/msg/ProcessState` | 공정 제어 | 모니터 게이트웨이 | 공정·장비·도구·파지 상태 스냅샷 |
| `/c2/process_events` | `c2_interfaces/msg/ProcessEvent` | 공정 제어 | 모니터 게이트웨이 | 명령·단계 전환·알람·오류·종료 이력 |

좌표 노드는 Action의 feedback/result로 진행·결과를 반환한다. 별도 경로 완료 Topic을 만들지 않는다. 생성 완료만으로 실행하지 않으며, 운영자가 미리보기를 확인한 뒤 게이트웨이가 실행 Action을 요청한다. 이미지·경로 본문은 파일로, ROS에는 식별자·해시·설정과 결과를 전달한다.

## 2. 공통 데이터 규칙

| 항목 | 권장 계약 |
| --- | --- |
| `schema_version` | `uint16`, 고정 드릴 계약은 2. 지원하지 않는 버전은 거절 |
| `request_id` | 문자열 UUID. 동일 논리 요청의 재조회·재전송에는 같은 ID 사용 |
| `run_id` | 문자열 UUID. 실행 시도마다 새 ID이며 게이트웨이가 실행 요청 전에 발급 |
| `path_id`, `path_version`, `path_sha256` | 경로 식별자, `uint32` 버전, 파일 바이트 SHA-256. 해당 버전은 덮어쓰지 않음 |
| `source_mode` | `SIMULATION` 또는 `REAL`. 게이트웨이·경로·실행기 설정이 일치해야 함. 요청 값만으로 실기 모드를 활성화하지 않음 |
| 오류 | `error_code`는 기계 판정용 고정 문자열, `message`는 한국어 설명. 정상은 `error_code=NONE` |
| 시간 | 이벤트에는 발생 시각, 서버에는 수신 시각. 로컬 제한 시간·경과 시간은 monotonic 시계로 계산 |
| 2D 입력·표시 | 도안 크기·배치 mm, 화면 회전 입력 deg. 필드에 `_mm`, `_deg` 명시 |
| 3D 경로·내부 Pose | 위치 m, 회전 quaternion `(x,y,z,w)`, 관절 rad. quaternion은 정규화된 값 |
| 로봇 API 경계 | `robot_adapter.py`에서만 확인된 두산 API 단위·회전 규약으로 변환. 6개 자세 값을 임의의 RPY로 해석하지 않음 |
| `frame_id` | 현재 이름은 `c2_base`. `workcell.yaml`에 등록한 실제 로봇 base와 일치하며 이름 변경만으로 좌표 변환을 추가하지 않음. 경로 좌표는 그 프레임 기준이며 실행 중 고정 변환을 다시 더하지 않음 |
| 설정 원본 | `workcell.yaml`, `tools.yaml`. 서버가 선택 설정을 불변 스냅샷으로 보관하고 ID·버전·해시로 연결 |

### `schema_version`의 의미

`schema_version`은 **팀이 정한 데이터 계약의 버전 번호**다. `uint16`은 0~65535의 음이 아닌 정수를 담는 자료형이고, 현재 계약에서는 값 `2`을 사용한다. ROS 2 버전이나 도안·경로 번호가 아니다. 같은 계약으로 만든 경로 내용이 바뀌면 `path_version`을 바꾸고, 필드의 의미·필수 항목·단위 등 계약이 바뀌면 호환성 검토 후 `schema_version`을 바꾼다.

예를 들어 수신 코드가 버전 2만 지원하는데 `schema_version=1`인 파일·요청을 받으면, 값을 임의 해석하지 않고 `UNSUPPORTED_SCHEMA_VERSION`으로 처리한다. **개발자가 검사 코드를 작성해야 하며 ROS가 이 필드를 보고 자동으로 거절하는 것은 아니다.** 상태·이벤트에서 지원하지 않는 버전을 받으면 해석하지 않고 모니터에 호환성 오류를 표시한다. 이 숫자만으로 서로 다른 ROS 메시지 타입 정의가 호환되지는 않으므로, 송수신자는 같은 `c2_interfaces` 정의를 사용해야 한다.

ROS의 필수 필드는 아니며 팀 전체를 동일 버전으로만 배포한다면 처음에는 생략하는 선택도 가능하다. 다만 이 문서의 v2 계약은 필드를 유지하는 안이다. 생략으로 합의하면 송수신 측·경로 파일·명세를 함께 수정한다.

### 설정·파일 전달

`profile_snapshot_id`는 선택한 작업대상·고정 변환·고정 드릴·TCP·하중·가공·보정·열기 금지 조건을 묶은 스냅샷이다. `profile_sha256`은 스냅샷 파일 바이트의 해시다. 스냅샷에는 `workcell_id/version`, `tool_id/version`을 포함한다. 실행기는 스냅샷과 현재 승인된 설정을 대조한다. 파일을 덮어써서 과거 경로의 설정이 바뀌지 않게 한다.

서버가 관리하는 asset/profile/path ID를 저장소의 파일로 해석한다. 브라우저가 전달한 임의 절대 경로를 열지 않는다. 파일 생성 완료·검증 후 임시 파일을 최종 위치로 원자적으로 바꾸고 결과를 공개한다. 처음 구현에서는 JSON과 별도 SVG/미리보기 파일을 사용한다.

## 3. GeneratePath: 이미지 → 좌표·경로

호출자: `monitor_gateway_node`. 처리자: `path_planner_node`.

| 방향 | 필드 | 형식·의미 |
| --- | --- | --- |
| Goal | `schema_version`, `request_id`, `source_mode` | 공통 규칙 |
| Goal | `asset_id`, `asset_sha256` | 서버가 저장한 입력 파일과 무결성 확인값 |
| Goal | `width_mm`, `height_mm` | 양수 `float64`. 비율 유지 선택은 화면에서 계산하여 두 실제 출력 크기를 전달 |
| Goal | `offset_u_mm`, `offset_v_mm`, `rotation_deg` | 작업대상의 표면 도안 좌표계에서 배치·회전 |
| Goal | `conversion_preset` | 서버가 지원한다고 표시한 이미지 전처리 방식 또는 SVG 입력 처리 방식. 미지원 값은 거절 |
| Goal | `tool_id`, `profile_snapshot_id`, `profile_sha256` | 선택 도구와 작업대상·고정 좌표·가공 조건 스냅샷 |
| Feedback | `request_id`, `stage`, `progress` | `CONVERTING`, `EXTRACTING_2D`, `OPTIMIZING_2D`, `MAPPING_3D`, `BUILDING_PATH`, `VALIDATING`; 진행률은 0~1의 처리 진행 추정치 |
| Result | `success`, `error_code`, `message` | 결과. 실패·취소 때는 실행 가능한 새 경로를 공개하지 않음 |
| Result | `path_id`, `path_version`, `path_sha256` | 확정한 경로 |
| Result | `svg_asset_id`, `preview_asset_id` | 변환 SVG와 2D/3D 미리보기에 필요한 데이터의 조회 ID |
| Result | `segment_count`, `cut_length_m` | 실행 구간 수, 조각 구간의 총 길이 |
| Result | `validation_passed`, `validation_report_id` | 검사 결과와 근거 파일 ID. 실물 가공 검증 완료를 뜻하지 않음 |

**배치 규약:** `u/v` 원점과 축 방향은 작업대상 표면 설정에 정의한다. `offset_u/v`는 도안 중심의 위치, 회전은 그 중심을 기준으로 한다. 2D 좌표는 u 오른쪽·v 위쪽의 오른손 좌표계로 정규화하고 SVG의 아래 방향 y축은 추출 단계에서 변환한다. 회전 양의 방향은 u에서 v로 향하는 반시계 방향이다. 임의의 원통 축·반경·이음매 위치는 넣지 않고 표면 설정을 사용한다.

성공 조건은 입력·설정 해시 확인, SVG와 경로 생성, 지정 범위·좌표·자세·실행 가능성 검증 통과, 최종 파일 저장 완료다. 필수 검증 기능이 준비되지 않았으면 `VALIDATION_UNAVAILABLE`로 실패시키고 미검사 경로에 통과 표시를 하지 않는다. 선택한 가공 방식이 미지원이면 `UNSUPPORTED_RECIPE`다. SVG 윤곽을 중심선 가공으로 임의 해석하지 않는다.

동시 생성은 초기 1건으로 제한하고 추가 요청은 `BUSY`로 거절한다. 취소 시 생성 작업을 중단하고 미완료 파일을 결과로 등록하지 않는다. 생성 결과를 기다리던 화면이 종료되어도 로봇은 움직이지 않는다.

## 4. 실행 경로 파일

`path.json`은 각 버전의 실행 입력이다. 실제 로봇 좌표나 가공 조건의 예시 숫자는 이 문서에 넣지 않는다.

| 영역 | 필수 내용 |
| --- | --- |
| 식별 | `schema_version`, `path_id`, `path_version`, 입력 `asset_id/sha256`, `source_mode` |
| 설정 | `profile_snapshot_id/sha256`, `workcell_id/version`, `tool_id/version`, 사용 TCP·하중 프로파일 ID·버전 |
| 좌표 | `frame_id`, `position_unit=m`, `orientation=quaternion_xyzw` |
| 구간 | 순서가 고정된 `segments` 배열: `segment_id`, `stroke_id`, `kind`, `waypoints`, `motion_profile_id` |
| 구간 종류 | `APPROACH`, `CUT`, `TRAVEL`, `RETRACT`. 서로 떨어진 작업선을 암묵적으로 연결하지 않음 |
| waypoint | base 기준 도구 끝(칼끝)의 위치·자세. 제어기 TCP 좌표가 아니며 driver별 명령 형식은 포함하지 않음 |
| 이동 조건 | `motion_profile_id`가 스냅샷의 속도·가속도·가공 조건을 참조. 작업 시 임의 기본값을 주입하지 않음 |
| 완료 검증 | 구간별 목표·허용 오차·확인 방식, 실행기 지원 여부 |
| 미리보기·검증 | 미리보기 데이터의 경로 ID·버전 연결, 검사 항목·결과·범위 |

제어기 TCP `GripperDA_v1`은 그리퍼 끝점이다. 경로의 도구 끝 자세를 제어기 TCP로 변환하는 책임은 `robot_adapter.py`에 있으며 좌표 노드·모니터가 중복 변환하지 않는다.

경로 해시는 파일 바이트로 계산해 결과·저장 메타데이터에 둔다. 해시 계산 대상 파일 안에 그 파일 자신의 해시를 넣지 않는다. 모든 실행 의존 파일은 해시로 묶이고 시작 전에 고정된 사본을 로딩한다.

경로의 `CUT` 구간과 실제 공구 접촉 조건을 구분한다. 접촉·깊이·자세가 어느 제어 방식으로 실행되는지는 도구·가공 프로파일에 명시하고, 지원·검증하지 않은 조건은 실행을 거절한다. `engraving.py`가 검증된 구간을 실행하고 `robot_adapter.py`가 실제 API 호출 형식으로 변환한다.

## 5. ExecuteProcess: 전체 공정 실행

호출자: `monitor_gateway_node`. 처리자: `process_controller_node`.

| 방향 | 필드 | 형식·의미 |
| --- | --- | --- |
| Goal | `schema_version`, `request_id`, `run_id`, `source_mode` | 공통 규칙 |
| Goal | `path_id`, `path_version`, `path_sha256` | 미리보기에서 확인한 경로. 좌표 본문을 화면에서 다시 보내지 않음 |
| Goal | `operator_confirmed_fixture` | 운영자가 대상이 지정 위치에 고정되었음을 확인한 bool. 센서 확인으로 취급하지 않음 |
| Goal | `operator_id`, `confirmed_at` | 서버가 기록한 확인 주체와 시각. 화면이 보낸 임의 사용자 이름을 신뢰하지 않음 |
| Feedback | `run_id`, `phase`, `engraving_progress`, `completed_segment_id`, `elapsed_s` | 공정 단계, 확인된 조각 진행률, 마지막 완료 구간, 전체 경과 시간 |
| Result | `run_id`, `outcome`, `error_code`, `message` | `SUCCEEDED`, `FAILED`, `STOPPED`, `UNKNOWN` |
| Result | `last_completed_segment_id`, `log_id` | 재현·확인 가능한 마지막 완료 지점과 실행 기록 |

Goal의 수락은 실행 성공을 뜻하지 않는다. 스키마·ID·현재 실행 소유권 등 기본 조건을 검사한 뒤 수락하고, 자세한 준비 검사는 `PRECHECK`에서 수행한다. 경로/설정 해시·버전, 고정 확인, 실기/모의 모드, 고정 드릴·열기 금지 정책, 장비 연결·상태·제어권·정지 latch·필수 프로파일을 검사한다. 필요한 값이나 실제 확인 수단이 없으면 모션을 시작하지 않는다.

공정 단계는 `PRECHECK → TOOL_CHECK → APPROACH → ENGRAVE → RETRACT → FINISH`다. PRECHECK는 경로/스냅샷·모드·제어권·STANDBY·고정 장착/닫힘 근거·보정·전체 경로 J6 조건을 검사한다. TOOL_CHECK는 이미 저장된 보정의 1점 확인이며 새 보정값을 실행 중 덮어쓰지 않는다. 실패 시 중단하고 전체 보정·스냅샷·경로 재생성·미리보기 확인을 다시 수행한다. PICK_TOOL/CLEAN_TOOL/PLACE_TOOL은 현재 공정에서 사용하지 않는다.

`APPROACH`·`ENGRAVE`·`RETRACT`는 `engraving.execute_path()`가 수행하는 경로 구간에 따라 갱신하는 공정 단계다. 상태 기계가 같은 접근·이탈 이동을 별도로 중복 실행하는 뜻은 아니다.

`engraving_progress`는 확인된 완료 CUT 구간의 길이 / 전체 CUT 길이로 계산한다. 조각 100%와 전체 공정 성공은 다르다. 모든 경로 구간과 이탈 완료를 확인한 뒤에만 `SUCCEEDED`다. 이 결과는 실물 검사 합격을 뜻하지 않는다. 검사는 모니터에서 별도로 기록한다.

한 로봇에 한 활성 실행만 허용한다. 같은 `request_id`의 같은 내용은 기존 실행 상태로 연결하고 새 모션을 보내지 않는다. 같은 ID에 다른 내용은 `REQUEST_CONFLICT`, 같은 `run_id`를 새 요청으로 다시 시작하려는 경우도 거절한다. 게이트웨이는 HTTP 재전송을 기존 요청에 연결하고 ROS Goal을 다시 만들지 않는다. 실행기도 저장된 요청·실행 ID로 중복 진입을 차단한다.

시작 예약은 모션 전 기록한다. 기록 실패 시 시작을 거절한다. 응답을 잃거나 프로세스가 재시작하면 기록과 장비 상태를 대조하고 미확정 실행을 자동 재전송·재개하지 않는다. 중복 방지 ID만으로 장애 중 물리 동작의 정확히 한 번 실행이 보장되는 것은 아니다.

## 6. StopProcess와 Action 취소

| 방향 | 필드 | 의미 |
| --- | --- | --- |
| Request | `schema_version`, `request_id`, `run_id`, `reason` | 현재 실행에 대한 정지 요청 |
| Response | `accepted`, `run_id`, `stop_state`, `error_code`, `message` | 정지 처리 접수 결과. 응답에 실제 정지 완료 의미를 부여하지 않음 |

정지 상태는 `NONE → REQUESTED → ACCEPTED → STOPPING → CONFIRMED`이며 `FAILED`, `UNKNOWN`을 별도로 둔다. 실제 정지 확인은 `/c2/process_state`와 실행 Action 결과로 전달한다.

정지 요청이 들어오면 새 모션 발행을 차단하고 사용 중인 실행 방식에 맞는 하위 정지를 요청한다. DB 저장·이미지 변환·긴 모션 대기 뒤에서 정지 처리가 밀리지 않게 한다. 정지 처리는 감사 저장의 완료를 기다리지 않는다. 진행 중 명령 응답이 늦게 와도 그 응답으로 공정을 다음 단계로 진행시키지 않는다.

같은 정지 요청은 기존 처리 상태를 반환하며 확인 기한을 다시 늘리지 않는다. `run_id`가 다른 요청은 `RUN_MISMATCH`로 거절해 지연된 이전 요청이 새 실행을 조작하지 않도록 한다. 시작 예약 직후부터 정지 요청을 처리하고 모션 전에도 latch를 재확인한다.

Action 취소도 동일한 정지 절차를 호출한다. 취소 수락만으로 `CANCELED` 완료를 보고하지 않는다. 정지가 확인된 취소는 ROS Action `CANCELED`와 도메인 결과 `STOPPED`로 종료한다. 별도 StopProcess에 의한 중단은 ROS Action `ABORTED`와 `STOPPED`로 종료한다. 정지 확인이 불가능하면 `ABORTED`와 `UNKNOWN`으로 종료하고 새 실행을 차단한다. 보호정지 자동 해제·오류 시 무조건 열기·자동 홈 복귀는 이 계약에 포함하지 않는다.

## 7. 상태·이벤트와 기록

### ProcessState

| 필드 묶음 | 내용 |
| --- | --- |
| 메시지 식별 | `schema_version`, `source_mode`, `source_epoch`(프로세스 시작 UUID), `seq`(uint64), 발행 시각 |
| 실행 | 활성 또는 마지막 `run_id`, `path_id/version`, `status`, `phase`, `engraving_progress`, `elapsed_s` |
| 상태 | `IDLE`, `RUNNING`, `STOPPING`, `STOPPED`, `SUCCEEDED`, `FAILED`, `UNKNOWN`. 단계는 별도 `phase` |
| 정지·오류 | `stop_state`, `error_code`, `message` |
| 도구·파지 | `requested_tool_id`, 확인된 `mounted_tool_id`, `tool_confirmation_source`, `grip_state` |
| 파지 상태 | `UNKNOWN`, `OPENING`, `OPEN`, `CLOSING`, `GRIPPED`, `EMPTY`, `ERROR`. 닫혔다는 이유만으로 GRIPPED로 만들지 않음 |
| 로봇 표시 | 확인된 관절 rad, TCP Pose·frame, 실제 운전·연결 상태. 모터 온도는 유효한 입력이 확인된 경우에만 제공 |
| 신호 품질 | TCP·관절·그리퍼·온도 각각 `quality`와 측정 시각. `VALID`, `STALE`, `UNKNOWN`, `UNSUPPORTED` 구분 |

희망 도구 ID와 실제 장착 확인은 다르다. 센서로 도구를 식별하지 못하면 실제 수행한 운영자 확인의 출처·시각·근거를 기록하거나 `UNKNOWN`으로 남긴다. 닫힘 관측만으로 철사 고정·드릴 장착 확인을 대신하지 않는다. OPEN/OPENING 등은 관측 이상 진단용이며 열기 동작 허용이 아니다. TCP 프로파일을 선택했다는 사실만으로 실제 도구 장착을 확인하지 않는다.

발행 heartbeat와 센서 측정 시각을 분리한다. 같은 오래된 센서 값을 새 메시지에 넣어도 신선도가 갱신되지 않는다. 무효한 ROS 값은 quality로 구분하고 브라우저 JSON에서는 해당 값을 null로 보내 0 측정값으로 표시하지 않는다. `source_epoch/seq`로 중복·역순 상태를 거른다.

### ProcessEvent

`schema_version`, `source_mode`, `event_id`, `source_epoch`, `event_seq`, `run_id`, `request_id`, `occurred_at`, `event_type`, `phase`, `severity`, `code`, `message`, `segment_id`, 필요한 설정/경로 식별자를 기록한다.

종류는 `COMMAND`, `PHASE_CHANGED`, `ALARM_RAISED`, `ALARM_CLEARED`, `RUN_FINISHED`다. 알람 읽음 기록과 원인 해소를 구분한다. 중요 이벤트는 공정 제어가 로컬 실행 저널에 기록하고 서버가 DB에 반영한다. 서버는 `event_id`로 중복을 제거한다. 정지 우선 처리와 기록 실패는 별도로 다루며 저장 실패를 숨기지 않는다.

Topic은 실시간 전달 경로이고 저장소 자체가 아니다. 모니터 재연결 시 서버의 `storage.py`가 동일 PC의 관리된 실행 저널에서 누락 이벤트를 읽어 DB에 보완한다. 모션·정지 콜백에서 DB 쓰기를 기다리지 않는다. 새 기록 노드를 추가하지 않는다.

## 8. 제한 시간·QoS 권장값

아래의 숫자는 **초기 소프트웨어·모의 통합 시험을 위한 제안값**이며 장비 정지 시간이나 실기 동작 조건을 보장하는 값이 아니다.

| 항목 | 권장 초기 계약 | 초과 시 |
| --- | --- | --- |
| 일반 Action Goal 응답 | 3초 | 접수 상태 미확인으로 표시하고 같은 요청을 조회. 새 ID로 자동 재실행하지 않음 |
| 경로 생성 | 전체 120초 | 작업 취소·실패 처리, 미완료 경로 공개 금지 |
| 정지 Service 응답 | 1초 | 즉시 정지 요청한 뒤 접수 응답이 없으면 `UNKNOWN`. 로봇이 멈췄다고 표시하지 않음 |
| 상태 발행 | 5 Hz 및 상태 변경 시 즉시 | 모니터용 주기이며 로봇 제어 주기와 별개 |
| 모니터 상태 신선도 | 새 상태 2초 미수신 | 화면 통신 미확인, 시작 요청 비활성. 실제 로컬 감시의 대체 아님 |
| 모션·그리퍼 완료 | 검증된 단계/도구 프로파일의 `completion_timeout_s` 필수 | 새 명령 차단, 오류·정지 처리. 값 미설정 시 REAL 실행 거절 |
| 실제 정지 확인 | 검증된 정지 프로파일의 `confirmation_timeout_s` 필수 | `UNKNOWN`, 새 실행 차단·현장 상태 확인 |

실제 명령 도중 timeout이 나더라도 장치가 계속 움직일 수 있다. Python 대기를 취소하는 것만으로 장치를 멈췄다고 취급하지 않는다. 명령과 피드백을 대응시켜 오래된 완료 상태가 새 명령의 성공으로 오인되지 않게 한다.

`process_state`는 reliable, volatile, keep-last 1을 초기 권장값으로 하고 다음 스냅샷에서 최신 상태를 받는다. `process_events`는 reliable, volatile, keep-last 100으로 두되 유실 복구는 실행 저널과 DB가 담당한다. 명령 Service와 Action의 Goal·Result·Cancel Service는 Jazzy 기본 Service QoS를 사용하며 명령을 transient-local로 보관·재생하지 않는다. Action 내부 상태 Topic은 명령과 구분하고 Jazzy의 기본 Action 상태 QoS를 유지한다. [Jazzy ActionServer의 QoS 구분](https://raw.githubusercontent.com/ros2/rclpy/jazzy/rclpy/rclpy/action/server.py).

공급자 Topic은 실제 게시 QoS에 맞춰 구독한다. ROS의 reliable 설정만으로 디스크 기록·재시작 복구가 보장되는 것은 아니다. [ROS 2 Jazzy QoS 원문](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/Concepts/Intermediate/About-Quality-of-Service-Settings.rst).

## 9. 공정 내부 함수 계약

별도 ROS 통신을 추가하지 않는다. 아래는 담당자 구현을 연결할 목표다. 현재 robot_adapter 함수는 호출자 입장에서 동기 반환이다. 노드는 작업 스레드 등으로 긴 호출을 격리하고 정지·상태 콜백이 계속 처리되도록 검증한다. 결과는 outcome/error_code/message/completed_step/observed_state에 성공·실패·확인 근거를 담고, 제한 시간·취소를 같은 공정 소유권으로 연결한다.

| 호출자 → 모듈·함수 | 입력 | 성공 조건 | 실패·중단 |
| --- | --- | --- | --- |
| 상태 기계 → preconditions | 경로·불변 스냅샷·현재 상태·운영자/센서 근거 | v2·모드·ID/해시·STANDBY·제어권·장착·닫힘·보정·J6·열기 금지 정책 일치 | 모션 시작 차단; 미확인 값을 정상 추정하지 않음 |
| 준비 절차 → tool_calibration 전체 보정 | 장착 ID·기준면·TCP/하중·검증된 접촉 프로파일·취소 | 3점 측정과 적합/잔차 확인, 도구 좌표계 오프셋과 근거 제공 | 새 스냅샷/경로 공개 금지, 자동 열기·복귀 없음 |
| 상태 기계 → tool_calibration 저장값 확인 | 같은 스냅샷의 보정과 확인 프로파일 | 1점 확인이 검증된 허용차 내, 저장값 변경 없음 | PROFILE_MISMATCH/NOT_READY, 후속 조각 차단 |
| 상태 기계 → engraving.execute_path() | 검증·고정 경로, context, 진행 callback | 획별 접근·접촉·가공·이탈과 필요한 TRAVEL 완료 확인 | 마지막 확인 구간 기록, 자동 다음 점/재개 금지 |
| 조각/보정 → robot_adapter.move()/probe_touch() | Pose·frame, 프로파일, 제한 시간, 취소 | 실제 완료·접촉·목표/자세 조건 확인 | 실패·정지 미확인 시 다음 단계 차단 |
| 공정 → robot_adapter.stop() | 확인된 정지 프로파일·기한 | 실제 로봇 정지 확인 | 접수와 정지 확인을 구분 |
| 준비/보정 → robot_adapter.select_tool_profile()/set_tool_offset() | 스냅샷의 TCP/하중·도구 오프셋(m) | 선택 결과 확인 및 동일 보정 적용 | 오래된 경로/스냅샷으로 진행하지 않음 |

기존 어댑터 API를 바꾸는 PR에서는 실제 인자·동기/비동기·반환 의미와 소비자 시험을 함께 갱신한다. clearance_m·오프셋은 m이며 vel_mm_s·acc_mm_s2·pos_tol_mm는 mm/s·mm/s²·mm다. 3점/1점 보정 함수명·산출물 상세는 담당 구현 PR에서 확정한다. 그리퍼 close/open·tool_sequence·cleaning 호출은 현재 계약에서 제외한다.

## 10. 화면↔서버 연결

다음은 축소된 운영 화면의 제안 API다. 기존 데모 API가 이미 이 계약으로 동작한다는 뜻은 아니다.

| 화면 요청 | 권장 API | 처리 |
| --- | --- | --- |
| 이미지 업로드 | POST `/api/operator/assets` | 파일 검증·저장 후 asset ID·해시 반환. 미지원 형식은 415 |
| 크기·배치·도구 선택 후 경로 생성 | POST `/api/operator/path-generations` | 위 GeneratePath Goal로 연결. HTTP 202와 request ID 반환 |
| 생성 결과·미리보기 | GET `/api/operator/path-generations/{request_id}`, GET `/api/operator/paths/{path_id}/versions/{version}` | 진행·결과·해시·관리된 미리보기 URL |
| 작업 시작 | POST `/api/operator/runs` | ExecuteProcess로 연결. HTTP 202와 request/run ID 반환 |
| 실행 상태·결과 조회 | GET `/api/operator/runs/{run_id}` | 접수/실행/완료를 구분하고 결과·로그 제공 |
| 정지 | POST `/api/operator/runs/{run_id}/stop` | StopProcess로 연결. 최종 정지는 상태로 별도 확인 |
| 현재 상태·이력 | GET `/api/operator/snapshot`, GET `/api/operator/runs`, GET `/api/operator/alarms` | 서버의 최신 상태·저장 기록 |
| 실시간 갱신 | WS `/api/operator/stream` | 생성 진행·공정 상태·이벤트. 초기 및 재연결 시 snapshot/이력과 대조 |
| 검사 기록 | POST `/api/operator/inspections` | `run_id`, `PASS/HOLD/REJECT`, 근거를 저장하고 검사자·시각은 서버가 기록 |

HTTP 접수 응답과 ROS Goal 수락, 공정 성공은 서로 다른 상태로 보여 준다. WebSocket 연결이 끊겼다고 결과를 완료로 추정하지 않는다. 고객 API와 별도 주문·대기열을 추가하지 않는다.

## 11. 공통 오류와 남은 현장 확정값

공통 오류 코드는 `BUSY`, `REQUEST_CONFLICT`, `INVALID_INPUT`, `UNSUPPORTED_SCHEMA_VERSION`, `UNSUPPORTED_FORMAT`, `UNSUPPORTED_RECIPE`, `ASSET_NOT_FOUND`, `HASH_MISMATCH`, `PROFILE_MISMATCH`, `VALIDATION_FAILED`, `VALIDATION_UNAVAILABLE`, `NOT_READY`, `COMMUNICATION_LOST`, `GRIP_NOT_CONFIRMED`, `RELEASE_NOT_CONFIRMED`, `TIMEOUT`, `RUN_MISMATCH`, `STOP_UNCONFIRMED`, `STORAGE_ERROR`로 시작한다. 미확인 상태를 성공으로 치환하지 않는다.

이름·데이터 흐름·ID·파일 형식·기본 상태와 소프트웨어 통신 계약은 이 초안으로 개발을 시작할 수 있다. 실제 좌표·그리퍼 피드백 기준·TCP·하중·가공 조건·모션 완료 오차·실제 동작 제한 시간·정지 확인 조건은 현장에서 확정해야 한다. 값이 없으면 테스트용 모의 데이터와 구분하고 REAL 동작을 시작하지 않는다.

Action의 장시간 처리·피드백·취소 성격은 [ROS 2 Jazzy Action 원문](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/Concepts/Basic/About-Actions.rst)을, ROS 표준 좌표·단위는 [REP-103 원문](https://raw.githubusercontent.com/ros-infrastructure/rep/master/rep-0103.rst)을 확인했다. 이 문서의 구체적인 이름·필드·기한은 팀 설계 제안이다.

## 12. 공통 타입 구현과 배포 · 2026-09-19

사용자 요청에 따라 문서의 5개 통신 정의를 [c2_interfaces](../ws_cobot1/src/c2_interfaces/README.md)에 구현했다. 통신 이름·방향·단계·성공/실패 의미·QoS·제한 시간은 유지한다. 이전 문서에서 시각과 장비 표시를 개념으로만 적어 담당자별로 다른 타입을 만들 수 있었던 부분을 아래처럼 구체화했다. 이 절의 최초 배포는 `schema_version=1`, ROS 패키지 `0.1.0`이었다. 9/19 고정 드릴 운영 변경으로 현재는 `schema_version=2`, 패키지 `0.2.0`이며 13절이 이전 공정 단계를 대체한다. 검토 후 수정할 때도 아래 전환 절차를 따른다.

### 이전/이후 계약과 영향 범위

| 항목 | 이전 | 이번 구현 | 영향받는 곳 |
| --- | --- | --- | --- |
| ROS 파일 | 개발 폴더와 필드 표 | Action 2개·Service 1개·Message 2개 및 생성 설정 | 세 노드의 공통 의존 패키지 |
| 발생·확인·측정 시각 | ROS 자료형 미정, HMI는 RFC3339 문자열 | `builtin_interfaces/Time` ↔ UTC RFC3339 변환 | 공정 발행자, ExecuteProcess 수신자, `backend/app/ros_bridge.py` |
| 발행 시각 | 이름 없이 '발행 시각' | `published_at` | ProcessState 발행자·게이트웨이 |
| 장비 표시·품질 | 관절·TCP·온도·운전/연결 상태 개념 | 아래 필드와 신호별 품질·시각 | 공정 발행자·게이트웨이·HMI 후속 표시 |
| 이벤트 관련 식별자 | '필요한 설정/경로 식별자' | `path_id/version/sha256`, `profile_snapshot_id/sha256`, `tool_id` | 이벤트 발행자·서버 저장 |

`c2_path`의 ActionServer와 `c2_process`의 ActionServer·ServiceServer·Publisher는 아직 구현 대상이다. 이 변경에서 해당 노드나 별도 통신 채널을 만들지 않는다. 모니터의 가짜 상대는 유지하고 실제 ROS 타입 경계만 맞춘다. 미리보기 파일 상세, 관리 ID→파일 해석, 구간별 압력/가공 판정은 별도 합의·구현 대상이며 이번 `.msg`에 임의로 포함하지 않는다.

### 공통 자료형·초기값

정확한 필드 순서·선언은 패키지의 `.action`·`.srv`·`.msg`가 원본이다. 식별자·해시·상태·단계·오류·설명은 `string`, `schema_version`은 `uint16`, 경로 버전과 `segment_count`는 `uint32`, `seq/event_seq`는 `uint64`다. 크기·배치·회전·진행률·경과 시간·CUT 길이는 `float64`, 성공·검증·고정 확인·접수는 `bool`이다. SHA-256은 소문자 16진수 64자다. 진행률은 유한한 0~1, 길이·경과 시간은 유한한 0 이상이어야 한다.

시각은 UTC Unix epoch 기준 `builtin_interfaces/Time(sec, nanosec)`이다. `nanosec`은 0 이상 1,000,000,000 미만이다. `{0,0}`은 미확인을 나타내며 실행 요청의 `confirmed_at`으로 사용할 수 없다. 이 계약의 절대 시각을 ROS `/clock`의 시뮬레이터 경과 시간으로 대체하지 않는다. 제한 시간 계산은 기존대로 monotonic 시계를 사용한다.

실패·취소한 GeneratePath는 `success=false`, `validation_passed=false`, 빈 `path_id/path_sha256`, `path_version=0`으로 실행 경로를 공개하지 않는다. 진단 자산·검증 보고서는 제공할 수 있으나 실행 경로로 등록하지 않는다. 관련 없는 선택 식별자는 빈 문자열, 관련 경로 버전은 0이다. 정상 결과는 `error_code=NONE`을 명시한다. 기본 생성자의 UNKNOWN·false·빈 문자열·0을 정상 응답으로 그대로 보내지 않는다.

ROS 선언의 상수는 참고 값이며 허용 문자열·UUID·해시·길이·버전·상호 필드 조건을 강제하는 enum이나 검증기가 아니다. 송수신 구현에서 2~8절의 검사·실패·중복 방지·정지 처리를 수행한다.

### ProcessState의 측정 필드

| 신호 | 값 | 품질 | 측정 시각·해석 |
| --- | --- | --- | --- |
| 파지 | `string grip_state` | `grip_quality` | `grip_measured_at` |
| 관절 | `float64[] joints` | `joints_quality` | `joints_measured_at`; VALID이면 M0609 1~6 순서, 유한한 rad 6개 |
| 제어기 TCP | `geometry_msgs/PoseStamped tcp`, `string tcp_profile_id` | `tcp_quality` | `tcp.header.stamp`, `header.frame_id`; m·정규화 quaternion xyzw. 프로파일 미확인 시 ID는 빈 문자열 |
| 모터 온도 | `float64[] temperature` | `temperature_quality` | `temperature_measured_at`; VALID이면 모터 1~6 순서의 유한한 섭씨 6개 |
| 로봇 상태 | `string robot_connection_state`, `string robot_mode` | `robot_quality` | `robot_measured_at`; 모드는 확인된 공급자 운전 모드 이름을 전달하며 임의 숫자 해석을 하지 않음 |

품질 필드는 모두 `string`이고 `VALID/STALE/UNKNOWN/UNSUPPORTED`를 사용한다. 연결 상태는 `CONNECTED/DISCONNECTED/UNKNOWN`, 도구 확인 출처는 `SENSOR/OPERATOR/UNKNOWN`이다. 그 밖의 공정·정지·파지 상태는 6~7절을 따른다. 로봇 운전 모드의 공급자별 이름 매핑은 장치 어댑터 연결 시 문서화해야 하며, 단순 표시값만으로 실행 준비 완료를 판단하지 않는다.

발행 heartbeat는 `published_at`이고 센서별 측정 시각을 덮어쓰지 않는다. TCP 시각만 `PoseStamped.header.stamp`를 사용하며 별도의 중복 시각 필드를 만들지 않는다. 아직 측정하지 못한 배열은 비우고, 고정 구조인 Pose는 품질 `UNKNOWN`으로 구별한다. 미지원 온도를 0°C로 채우지 않는다.

게이트웨이는 `VALID`가 아닌 관절·TCP·온도 값을 JSON `null`로 바꾸고 품질·원래 측정 시각을 유지한다. 무효한 파지/로봇 상태는 UNKNOWN으로 전달한다. 시각 미확인은 JSON `null`, 알려진 시각은 나노초를 보존한 UTC RFC3339 문자열이며 비유한 숫자는 `null`이다. 발행자는 측정 신선도·프레임·배열 길이·유한값·quaternion을 검사해야 한다. 이 변환만으로 장비 상태 검증을 대신하지 않는다.

### 팀 적용·향후 수정 절차

1. 모든 담당자가 동일 커밋의 `c2_interfaces`를 받고 Jazzy에서 빌드·source한다. `c2_path`와 `c2_process`는 이 패키지를 의존성으로 선언한다.
2. 모니터는 기존 HTTP/SQLite 시각 형식을 유지한다. `ros_bridge.py`가 ExecuteProcess의 확인 시각을 ROS Time으로, 상태·이벤트를 JSON으로 변환한다. DB 스키마 변경은 없다.
3. 경로·공정 담당자는 제공한 타입으로 요청·Feedback·Result·상태·이벤트를 연결한다. 지원 버전·입력·설정 해시·모드·정지 조건을 수신 코드에서 검사한다. 모의 상대 통합 후 실기 시험을 별도로 진행한다.
4. 타입·의미 변경은 이유, 이전/이후, 영향받는 파일, 버전, 전환 순서를 PR에 기록하고 송수신 담당자가 검토한다. 호환되지 않는 변경은 schema_version 처리와 모든 소비자의 배포 순서를 함께 정한다. 다른 타입 정의에 같은 schema_version 숫자만 넣어 호환된다고 주장하지 않는다.
5. 변경된 타입을 사용하는 모든 노드를 정지·재빌드·재시작하여 같은 설치본을 사용한다. 문제가 있으면 실행을 중지하고 호환되는 소비자·타입 묶음으로 함께 복구한다. 철사 고정 중에는 집기/열기가 포함된 v1 실행으로 되돌려 가동하지 않는다. 자동 main 병합이나 실기 기동은 하지 않는다.

빌드 설정은 [ROS 2 Jazzy 공통 인터페이스 작성 안내](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/Tutorials/Beginner-Client-Libraries/Custom-ROS2-Interfaces.rst)와 설치된 `rosidl_cmake`를 기준으로 했다. 실제 검사 결과와 한계는 [검증 기록](validation/2026-09-19-c2-interfaces.md)에 남긴다.

## 13. 고정 드릴 v2의 추가 규칙·배포

[9/19 운영·구조 변경](C2_FIXED_DRILL_20260919.md)을 적용한다. ROS 5개 이름·필드 배치는 유지하되 실행 의미가 바뀌므로 schema_version 상수·기본값을 2로, 패키지는 0.2.0으로 변경한다. 기존 v1 요청을 v2로 묵시적으로 바꾸지 않으며 새 데이터의 송수신·버전 검사를 함께 배포한다. 같은 숫자만으로 서로 다른 설치 타입이 호환되지는 않는다.

- GeneratePath의 tool_id는 engraving_drill, 경로·미리보기·TCP 관측 프레임은 c2_base를 사용한다. 현재 제어기 TCP GripperDA_v1과 도구 끝 waypoint의 차이는 유지한다.
- 툴 −Y가 표면 안쪽 법선, 툴 +Z가 원통 축 아래를 향한다. +X는 오른손 좌표계의 나머지 축으로 정해지며 정규화 quaternion으로 제공한다. 같은 축 정의를 좌표·실행자가 사용한다.
- 한 획의 연속 둘레 각도 범위는 180° 이내, 이음매 통과 금지다. 각도 범위·분할 획의 재연결 금지는 좌표 검증에서, 현재 관절·IK·전체 경로 J6 한계/여유는 공정 준비에서 확인한다. 획 순서로 J6 누적 회전을 줄이는 왕복을 계획한다. 부호·시작각·IK 해 선택·세부 정렬 규칙과 현장 한계 수치는 담당자 합의 후 추가한다.
- 보정은 장착 시 전체 측정 결과를 스냅샷에 묶고 경로를 생성한 다음, TOOL_CHECK에서 저장값을 확인한다. 보정 식별·오프셋·근거를 JSON 스냅샷에 어떤 필드로 담을지는 담당자 PR에서 문서화한다. 미확정 보정을 기본 0으로 실행하지 않는다.
- 패키지·화면·게이트웨이·좌표/공정 소비자를 같은 커밋으로 빌드·source·재시작한다. 게이트웨이는 v1 생성 타입 설치본 기동과 v1 새 요청을 거절한다. 이전 DB·파일은 보존하되 새 실행은 v2 프로파일로 경로를 다시 생성·확인한다.
- 현재 DB user_version=1은 저장 테이블 버전이며 통신 schema_version=2와 별개다. 그리퍼 열기 금지를 위반하는 이전 실행 코드는 철사 고정 상태에서 되돌려 가동하지 않는다.

재측정 전 윗면 z≈234.4 mm, 보정 ±1 mm 제안, 과거 ±350° J6 여유값을 승인된 REAL 기본값으로 넣지 않는다. 이번 변경은 보정·J6 검증·실제 공정 구현 완료가 아니다.
## 2026-09-21 준비 Action 추가 권장안

기존 v2 통신 정의는 유지한다. 새 `/c2/prepare_workpiece`와 `PrepareWorkpiece.action`의 MEASURE/BIND_SNAPSHOT 계약은 [준비 Action 공통 구현 기준](PREPARE_WORKPIECE_ACTION.md)을 따른다. 타입·빌드 등록 단계이며 송수신 연결 및 실기 검증 완료가 아니다.
