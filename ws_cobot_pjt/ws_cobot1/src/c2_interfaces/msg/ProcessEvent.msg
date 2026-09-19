# /c2/process_events: reliable / volatile / keep-last 100.
# event_id로 중복 제거. Topic 자체는 영구 저장소가 아니며 저널·DB에 기록한다.
uint16 SCHEMA_VERSION=1
uint16 schema_version 1
string source_mode
string event_id
string source_epoch
uint64 event_seq
# UTC Unix epoch 발생 시각. 수신 시각은 서버가 별도로 기록한다.
builtin_interfaces/Time occurred_at
string run_id
string request_id
# COMMAND, PHASE_CHANGED, ALARM_RAISED, ALARM_CLEARED, RUN_FINISHED
string event_type
string phase
# INFO, WARNING, ERROR. code는 기계 판정용, message는 한국어 설명.
string severity
string code
string message
string segment_id
# 사건에 해당하는 경로·설정. 해당 없으면 빈 문자열/버전 0.
string path_id
uint32 path_version
string path_sha256
string profile_snapshot_id
string profile_sha256
string tool_id
