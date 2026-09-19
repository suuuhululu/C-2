# /c2/process_state: reliable / volatile / keep-last 1, 초기 5 Hz.
# 모션 완료·파지·정지 확인·검사 합격을 서로 대체하지 않는다.
uint16 SCHEMA_VERSION=1
string QUALITY_VALID=VALID
string QUALITY_STALE=STALE
string QUALITY_UNKNOWN=UNKNOWN
string QUALITY_UNSUPPORTED=UNSUPPORTED
uint16 schema_version 1
string source_mode
string source_epoch
uint64 seq
# UTC Unix epoch 시각. heartbeat 시각은 개별 신호 측정 시각과 별개다.
builtin_interfaces/Time published_at
string run_id
string path_id
uint32 path_version
# IDLE, RUNNING, STOPPING, STOPPED, SUCCEEDED, FAILED, UNKNOWN
string status "UNKNOWN"
string phase
float64 engraving_progress
float64 elapsed_s
# NONE, REQUESTED, ACCEPTED, STOPPING, CONFIRMED, FAILED, UNKNOWN
string stop_state "UNKNOWN"
string error_code "UNKNOWN"
string message
string requested_tool_id
string mounted_tool_id
# SENSOR, OPERATOR, UNKNOWN. 모의값도 source_mode로 명확히 구분한다.
string tool_confirmation_source "UNKNOWN"
# UNKNOWN, OPENING, OPEN, CLOSING, GRIPPED, EMPTY, ERROR
string grip_state "UNKNOWN"
string grip_quality "UNKNOWN"
builtin_interfaces/Time grip_measured_at

# M0609 관절 1..6 순서, rad. VALID일 때 유한 값 6개. 미확인은 빈 배열.
float64[] joints
string joints_quality "UNKNOWN"
builtin_interfaces/Time joints_measured_at
# 제어기에서 확인한 TCP Pose. 경로 waypoint의 도구 끝 Pose와 구분한다.
# 위치 m, 정규화 quaternion xyzw, header.frame_id는 등록된 프레임.
# header.stamp는 TCP 측정 시각이며 published_at으로 덮어쓰지 않는다.
geometry_msgs/PoseStamped tcp
string tcp_quality "UNKNOWN"
# TCP 프로파일 ID. 현재 개발 기준은 그리퍼 끝점 GripperDA_v1.
# 선택 결과를 실제로 확인하지 못했으면 비워 둔다.
string tcp_profile_id
# M0609 모터 1..6 순서, Celsius. 미지원이면 빈 배열 + UNSUPPORTED.
float64[] temperature
string temperature_quality "UNKNOWN"
builtin_interfaces/Time temperature_measured_at
# 로봇 연결 상태는 HMI↔서버 WebSocket 연결과 별개.
# CONNECTED, DISCONNECTED, UNKNOWN. robot_mode는 확인한 공급자 모드 이름.
string robot_connection_state "UNKNOWN"
string robot_mode "UNKNOWN"
string robot_quality "UNKNOWN"
builtin_interfaces/Time robot_measured_at
