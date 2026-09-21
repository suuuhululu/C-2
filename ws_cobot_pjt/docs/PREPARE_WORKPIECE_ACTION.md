# 준비 Action 권장안 · 두 담당자의 공통 구현 기준

2026-09-21. 기준: 원격 main `829db40`, 작업 브랜치 `codex/hmi-preparation-flow`.
사용자 요청으로 작성한 **검토용 권장 계약**이다. 타입 생성은 구현하되 HMI/제어 연결·팀 승인·실기 완료를 의미하지 않는다. 기존 5개 ROS 통신과 3개 노드는 그대로 유지한다.

> **2026-09-21 준비된 REAL 실행 정책 확정:** BIND가 성공한 작업의
> `ExecuteProcess`는 측정 유효성·기본 로봇 상태·제어권·TCP/하중을 다시
> 조회하지 않는다. 동일 준비 성공 기록과 profile binding, 경로·설정 원본
> 무결성, 깊이·접촉 보정을 반영한 실제 실행 계획의 최종 IK·관절 검사를
> 확인한다. 취소·정지 요청과 실제 정지 확인은 계속 유지한다. 새 측정·설정
> 변경·취소/정지·연결 상실·제어 재시작으로 준비가 무효화되면 실행을
> 거절한다. 이 정책은 준비되지 않은 직접 실행의 PRECHECK를 완화하지 않는다.

## 1. 이번에 정할 답

| 질문 | 권장 계약 |
| --- | --- |
| 준비 요청 | `/c2/prepare_workpiece`, `c2_interfaces/action/PrepareWorkpiece` |
| 요청 ID 발급 | 브라우저가 MEASURE `request_id` UUID v4 발급. 백엔드가 접수 시 `preparation_id`, `measurement_id` UUID v4를 한 번 발급·저장. BIND에는 백엔드가 별도 `request_id` 발급 |
| 측정 전 설정 | 백엔드가 불변 설정 파일을 먼저 저장. `input_profile_snapshot_id`, `input_profile_sha256`으로 전달. 제어가 원본 파일 해시와 내용 확인 후 시작 |
| 상세 측정 결과 | MEASURE Action Result의 타입 필드로 기하·접촉 자세/힘/시각·부분 결과를 직접 수신. 임의 JSON 문자열 Topic을 추가하지 않음 |
| 결과 보관 | 백엔드가 수신 Result 전체를 불변 `measurement_record` 자산으로 저장하고, 별도로 실측 profile snapshot 생성 |
| 제어에 등록 | 같은 Action의 `BIND_SNAPSHOT`으로 원본 기록과 최종 snapshot ID/해시 전달. 제어가 자기 측정 결과와 대조·등록한 후 `snapshot_bound=true` 반환. 이 호출은 이동하지 않음 |
| 경로/실행 연결 | BIND 성공 뒤 GeneratePath에 그 snapshot ID/해시 전달. ExecuteProcess는 기존 path ID/version/hash 유지. 제어가 경로 메타데이터 → 등록 snapshot → 자기 측정 결과를 검증 |

Action 파일: [PrepareWorkpiece.action](../ws_cobot1/src/c2_interfaces/action/PrepareWorkpiece.action).
두 단계로 나누는 이유는 **제어가 측정을 마친 뒤 HMI가 최종 스냅샷을 저장**하기 때문이다. MEASURE 성공을 스냅샷 등록 완료로 오해하지 않는다. 별도 등록 Service나 노드를 추가하지 않는다.

## 2. Goal 채우기

모든 ID는 UUID v4 문자열, 해시는 저장 원본 바이트의 SHA-256 소문자 64자리다. 누락/형식 오류를 서버가 검사한다. `schema_version=2`는 데이터 계약 버전이며 main_v3/main_v4와 무관하다. 새 Action 추가이며 기존 v2 타입의 필드를 바꾸지 않는다.

| 필드 | MEASURE | BIND_SNAPSHOT |
| --- | --- | --- |
| `operation` | `MEASURE` | `BIND_SNAPSHOT` |
| `request_id` | 준비 버튼 요청의 ID | 등록 전용 새 ID, 통신 재시도 시 재사용 |
| `preparation_id`, `measurement_id` | 백엔드 발급 값 | 성공한 측정의 같은 값 |
| `source_mode` | `SIMULATION` 또는 `REAL` 명시 | 측정과 같은 모드 |
| `input_profile_snapshot_id`, `input_profile_sha256` | 측정 전 설정 참조 | 측정 당시와 동일 |
| `measurement_record_id`, `measurement_record_sha256` | 빈 문자열 | 저장한 MEASURE Result 참조 |
| `profile_snapshot_id`, `profile_sha256` | 빈 문자열 | 저장한 최종 실측 profile 참조 |

`operator_confirmed_drill_fixed`, `operator_confirmed_gripper_closed`, `operator_confirmed_drill_off`, `confirmed_at`, 드릴 ON은 넣지 않는다. 높이 역시 Goal과 설정에 중복 전달하지 않는다. 사람이 잰 전체 높이는 설정의 `workcell.height_m`, `height_source=OPERATOR_RULER`에 저장한다. 윗면 접촉만으로 전체 높이를 독립 실측했다고 표시하지 않는다.

## 3. 설정·파일 전달과 검증

저장 주체는 HMI 백엔드다. 제어의 읽기 어댑터는 배포 설정에 고정한 백엔드 주소에서 기존 `GET /api/operator/assets/{id}/content`로 원본 바이트를 읽는다. Goal에 임의 URL/로컬 경로/인증 토큰을 받지 않는다. 이 endpoint는 현재 저장소에 있으나 **제어 측 resolver 연결은 구현할 작업**이다. HTTP 조회는 읽기 전용 파일 전달이며 새로운 로봇 제어 API가 아니다.

- 백엔드 `storage.encoded()` 규칙(UTF-8, 키 정렬, 공백 없는 JSON, NaN 금지)으로 한 번 저장하고 그 바이트의 해시를 발급한다. 소비자가 재직렬화해서 해시를 계산하지 않는다.
- 입력 설정 payload는 `contract=prepare-workpiece-config/1`, `source_mode`, `tool_id`, `tcp_id`, `load_id`, `workcell`, `profiles`를 필수로 한다. `workcell`/`profiles`는 시율 측정 모듈의 기존 설정 구조를 사용한다. TCP는 `GripperDA_v1`, 도구는 `engraving_drill`; REAL 하중 ID·오프셋·홈·허용오차·속도·힘은 확인한 현장 설정만 허용한다.
- 기존 `hmi-preparation-sim/1` MOCK 설정은 새 계약의 REAL 입력으로 사용하지 않는다. 모드·설정 스키마·ID·해시·필수 키·유한 수·양수 높이·작업 범위·TCP/하중 일치 모두 검사한다. 실행 상수의 별도 사본을 HMI에 만들지 않는다.
- 두 파일 입력을 한꺼번에 검증하고, 불일치면 모션 전에 거절한다. 설정을 덮어쓰지 않고 변경마다 새 ID/해시와 새 측정·경로를 만든다.
- 입력 파일 조회는 호출당 5초, 최대 2회(총 10초)로 제한한다. 불가하면 `NOT_READY`/`HASH_MISMATCH`로 실패한다. 이 시간은 소프트웨어 대기 상한이지 로봇 정지 성능 보장이 아니다.

## 4. MEASURE 동작과 결과

진행 `stage`는 `VALIDATING → ROBOT_CHECK → HOME_CHECK → HOME_MOVE(필요 시) → HOME_RECHECK → TOP_TOUCH → SIDE_TOUCH → RETRACT → FIT → COMPLETE`다. 시작·완료 경계에서 즉시 Feedback을 보내고 동작 중 표시 갱신은 최대 5 Hz로 제한한다. 이미 홈이면 HOME_MOVE를 생략하고 최신 상태 재검사는 수행한다.

세은 상태 기계가 제어권·단일 모션 소유권을 확보하고 실제 연결·운전·정지·관절/TCP·도구/하중·하드웨어 관측을 검사한다. 시율의 내부 홈 함수로 검사된 홈 이동을 한 번 수행하고 도착·정지를 확인한다. 이후 최신 상태 재검사와 측정 접근/터치/후퇴 검사를 통과해야 측정한다. 실패·취소 뒤 자동 홈 복귀는 하지 않는다. 그리퍼 개폐/드릴 전원 명령은 어떤 분기에도 추가하지 않는다.

성공 필수 조건은 `outcome=SUCCEEDED`, `error_code=NONE`, `stop_confirmed=true`, `partial=false`, `geometry_ready=true` 모두 충족이다. MEASURE의 `snapshot_bound=false`, 최종 record/profile 참조는 빈 문자열이다. 최종 등록은 아직 하지 않았기 때문이다.

- `frame_id=c2_base`, 길이/좌표 m, 힘 N, 접촉 자세는 도구 끝 quaternion `(x,y,z,w)`다. 기존 내부 회전 표현 변환은 검증된 어댑터에서 수행하며 HMI는 좌표 변환하지 않는다.
- 접촉 배열은 동일 길이, 최대 9개다. 성공 시 인덱스 `[0,1,2,3,4,5,6,7,8]`가 필요하다. 0은 윗면, 1..8은 기존 시율 탐색 순서다. 부분 실패는 검증된 접촉만 순서대로 보존한다. 실패한 접촉과 계획·내부 이벤트는 제어 진단 기록 `log_id`에 남기며 Action의 승인된 접촉으로 섞지 않는다.
- `contact_received_at`은 원본 측정의 `received_at` UTC Unix 시각이다. `contact_monotonic_s`는 원본 `measured_at_monotonic_s`; 다른 PC/프로세스 시각과 비교하지 않는다. `started_at`/`measured_at`은 측정 시작/완료 UTC다. 미확인 Time=0을 현재 시각으로 꾸미지 않는다.
- SIM 성공의 `validity=SIMULATED`, REAL은 유효한 절대 기하를 확인한 경우에만 `FORCE_CONTACT_ESTIMATE`. `REFERENCE_ONLY`/`INCOMPLETE`는 경로 생성 불가다. `independent_accuracy_verified=false`를 임의로 true로 만들지 않는다.
- `height_m`은 설정의 수동 높이, `axis_xy_m`/`radius_m`/`top_z_m`은 유효한 접촉에서 계산한다. `bottom_z_m=top_z_m-height_m`. `work_v_range_m=[상단 여유, 높이-하단 여유]`는 윗면에서 아래 방향 거리, `work_z_range_m=[top_z-v_max, top_z-v_min]`는 절대 z다.
- 현 단계는 수직축 가정(`vertical_axis_assumed=true`, `tilt_measured=false`), 정밀 기울기/테이퍼 측정 완료가 아니다. 잔차는 원본 fit의 RMS/max 값을 반환한다.
- 실패 시 숫자 기본 0은 실측 0이 아니다. `geometry_ready=false`이면 접촉 배열만 부분 데이터로 사용하고 기하 필드는 사용하지 않는다. 성공 결과의 모든 수치·배열·범위·quat 정규화·최신성은 송수신 양쪽에서 검사한다.

## 5. HMI 저장 → BIND → 기존 경로/실행

1. HMI는 MEASURE Result 모든 필드를 `contract=prepare-workpiece-result/1`, `result={필드명: 값}`으로 저장한다. Time은 `{sec,nanosec}`, Pose는 ROS 필드명 그대로 중첩 객체, 배열은 JSON 배열이다. 실패/부분 결과도 저장한다. 로그 ID는 원격 파일을 자동 다운로드하는 URL이 아니다.
2. 성공한 기하만 기존 profile 형식으로 변환한다. `surface.radius_mm=radius_m*1000`, `height_mm=height_m*1000`, `axis_origin_m=[cx,cy,bottom_z_m]`, `axis_direction=[0,0,1]`, `height_reference=bottom`, `v_direction=up`, `valid_v_range_mm=[(H-v_max)*1000,(H-v_min)*1000]`. 기존 경로 profile의 나머지 필수 필드는 검증된 설정에서 보존한다.
3. profile 루트에 `preparation_id`, `measurement_id`, `source_mode`, `input_profile_snapshot_id`, `input_profile_sha256`, `measurement_record_id`, `measurement_record_sha256`를 보존한다. profile 자체 ID/해시는 외부 참조이며 자기 파일에 자기 해시를 넣지 않는다.
4. HMI가 BIND Goal을 보낸다. 제어는 자기 성공 기록의 ID·모드·설정과 일치하는지, 파일 해시·기록 내용이 자기 반환 Result와 일치하는지, profile 기하·메타데이터가 위 변환과 일치하는지 검사한다. ID/해시만 echo하지 않는다. 실수 변환 비교 오차는 1e-9 m(단위 변환 필드는 이에 상응)이며 현장 동작 허용오차가 아니다.
5. 일치하고 최신 준비가 취소/무효화되지 않았으며 현재 정지·설정이 유효할 때 원자적으로 등록한다. BIND 성공은 `snapshot_bound=true`, `geometry_ready=true`, `partial=false`, `stop_confirmed=true`와 동일 ID/해시를 반환한다. 기하/접촉 필드는 기본값이며 MEASURE Result에서 읽는다. BIND Feedback stage는 `BINDING → COMPLETE`다. BIND 자체는 모션/홈/측정을 호출하지 않는다.
6. HMI는 이 ack 후에만 GeneratePath를 요청한다. 제어는 ExecuteProcess에서 경로 메타데이터의 profile ID/해시를 자기 등록표와 대조한다. 누락/불일치/무효화면 `NOT_READY`/`PROFILE_MISMATCH`로 실행 차단한다. 최종 관절 검사도 동일 경로를 사용한다. 준비된 실행에서는 측정 유효성·기본 로봇 상태·제어권·TCP/하중을 다시 조회하지 않는다. ExecuteProcess Goal을 늘리지 않는다.

현재 c2_path의 고정 SIM/test_only profile 검사와 동적 실측 profile 지원은 별개다. 위 변환 계약에 맞는 profile 소비·검증은 경로 담당자 연결 작업이며 이 파일 추가로 해결됐다고 보지 않는다.

## 6. 중복·취소·오류·재시작

- 같은 `request_id`+같은 Goal은 같은 진행/결과로 합류하고 새 측정을 시작하지 않는다. 같은 request ID에 다른 내용은 `REQUEST_CONFLICT`. 같은 preparation/measurement를 새 request ID로 재측정하려 해도 거절한다. 실제 재측정은 새 3개 ID를 사용한다. ROS goal UUID와 업무 request_id는 별개다.
- 제어는 실행 중 다른 측정·조각을 `BUSY`로 거절한다. 새 측정을 실제 접수하는 순간 이전 준비/등록 경로를 무효화한다. 입력 설정 변경, 취소/정지, 연결 상실, 제어 재시작도 무효화한다. UI만 비활성화하지 않고 제어에서도 실행 거절한다.
- 준비 취소는 이 Action의 표준 CancelGoal을 사용한다. 기존 StopProcess의 run_id에 preparation_id를 끼워 넣지 않는다. 공통 모션 정지 처리를 내부에서 공유한다. 취소 접수와 실제 정지를 구별하고, 정지 미확인은 `UNKNOWN/STOP_UNCONFIRMED`, `stop_confirmed=false`다. 새 이동/후퇴/자동 홈을 보내지 않는다.
- BIND의 취소와 등록은 동일 잠금에서 결정한다. 취소가 먼저 수락되면 등록하지 않는다. 등록이 이미 끝났으면 늦은 취소를 거절한다. HMI에서 새 작업으로 폐기한 뒤 늦은 성공을 받아도 UI/경로를 복구하지 않는다. 실행 시 최신 준비 검증은 항상 필요하다.
- ROS terminal status는 SUCCEEDED→succeed, FAILED/UNKNOWN→abort, 수락한 취소의 STOPPED→canceled다. 취소 외 정지의 STOPPED는 abort다. 잘못된 Goal은 accept 후 검증 실패 결과를 보내 오류 코드를 전달하되, 검증 전에는 모션 권한을 주지 않는다.
- 전체 MEASURE 상한은 입력 설정 `workcell.runtime_timeout_s`(현재 SIM 300초)를 홈/재검사 포함 전체에 적용한다. BIND 상한 30초. 초과하면 TIMEOUT 및 제어 정지 절차를 적용하고 실제 정지를 별도 확인한다. 하드웨어 정지 확인 기한은 검증된 장치 설정을 사용하며 없으면 REAL 요청을 받지 않는다.
- 서버 결과 캐시는 600초로 설정한다. HMI/제어 모두 요청 원장을 보존하고 결과 캐시 만료/재시작 후 이전 모션을 재실행하지 않는다. 제어 재시작 시 성공 이력도 실행 권한으로 자동 복구하지 않는다. 새 측정이 필요하다. 통신 상실 시 새 ID로 자동 재시도하지 않는다.
- 오류 코드는 `NONE`, `INVALID_INPUT`, `UNSUPPORTED_SCHEMA`, `NOT_READY`, `BUSY`, `REQUEST_CONFLICT`, `HASH_MISMATCH`, `PROFILE_MISMATCH`, `STALE_DATA`, `TIMEOUT`, `CANCELLED`, `STOP_UNCONFIRMED`, `COMMUNICATION_LOST`, `INTERNAL_ERROR`와 기존 측정 코드(`UNSUPPORTED_ADAPTER`, `MOTION_INCOMPLETE`, `CONTACT_UNCONFIRMED`, `CONTACT_OUT_OF_RANGE`, `INVALID_MEASUREMENT`)를 사용한다. 알 수 없는 코드는 실패로 표시하고 원문 보존한다.

## 7. 담당자별 구현·완료 조건

| 담당 | 구현할 내용 |
| --- | --- |
| 수현(HMI/백엔드) | ID 발급/원장, 설정 저장, ROS ActionClient 두 operation 연결, Feedback/Result 변환·보관, 최종 profile 생성·BIND ack 확인, 취소와 늦은 결과 차단, 수동 ON UI와 초기화. 기존 준비 수동 bool 3개 제거 |
| 세은(공정 제어) | ActionServer, 입력 resolver/해시 검사, 모션 소유권·홈/재검사·측정 호출, typed Result 변환, 중복/취소/시간초과, BIND 검증/등록/무효화, ExecuteProcess의 경로→등록 측정 검증 |
| 시율(측정) | 기존 함수·홈 호출에 실제 최신 관측 연결, SI/quat 변환 확인, 전체 접촉/후퇴/부분 실패 결과 제공. 그리퍼/드릴 명령 및 수동 bool 의존 제거 |
| 경로 담당 | 등록한 실측 profile의 기존 GeneratePath 입력 소비, 동일 snapshot 참조를 경로 메타데이터에 보존. 고정 test_only 제한과 REAL 승인을 별도로 검증 |

먼저 동일 커밋의 c2_interfaces를 빌드하여 SIM으로 연결한다. Action 기본 서비스/결과는 reliable, Feedback은 reliable/volatile depth 10으로 송수신을 맞춘다. 상태 표시는 기존 ProcessState 관측 출처·품질·시각을 유지한다.

완료 시험: 홈/비홈, 재검사 실패, 전체 9접촉, 부분 결과, 잘못된 설정/해시, BIND 이전 생성 차단, 다른 측정의 snapshot 거절, 중복/취소/시간초과/정지 미확인, 늦은 BIND/결과, 재시작 후 실행 차단, 같은 경로의 미리보기·최종 검사·실행. 그리퍼/드릴 제어 호출 0건도 검사한다.

이 권장안은 타입·명세를 먼저 전달하는 단계다. 송수신자 구현 PR을 이 계약에 맞춰 검토하고 같은 설치본으로 배포하기 전에는 연결 완료로 표시하지 않는다. REAL/test_only 제한을 해제하지 않는다.
