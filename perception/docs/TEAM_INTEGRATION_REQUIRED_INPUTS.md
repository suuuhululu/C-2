# B 팀 통합 연결에 필요한 실제 인터페이스

2026-10-11 현재 저장소를 확인한 결과다. 확정 Schema나 연결 완료 선언이 아니다.

## BLOCKER

팀장 메시지의 `connect(bridge) → bridge.bind(handler)` 및
`submit_observation / submit_place / submit_failure` 구현 파일이 현재 저장소에 없다.
`app/backend.py`의 `_open_vision`은 `check_id, after`만 전송하므로
`after=null`인 PLACE/CURRENT를 구분할 수 없다. Controller와 표시부의 신규
입출력 메시지도 확인되지 않았다. 미게시 D 로컬 코드를 먼저 전달받아야 한다.

## REQUIRED CHANGE / AFFECTED INTERFACE / REASON

| 필요한 자료 | 확인할 내용 | 필요한 이유 |
|---|---|---|
| D bridge 실제 Python 파일 | handler 인자, 요청 목적·모드·순번·취소/닫힘, 세 submit 함수 signature | 요청과 결과를 실제 호출 방식에 맞춰 연결 |
| D 요청별 입력/출력 예시 | PLACE/ASSEMBLY/CURRENT, 정상·실패·늦은 결과 | after=null 혼동 및 이전 결과의 재사용 방지 |
| Controller 관측 인터페이스 | 토픽/서비스 또는 Python 함수, View·실제 정지·안전·STOP·오류, 관측 종료 응답 | 로봇 이동과 촬영 순서를 실제 신호로 연결 |
| Current/Expected 제공 인터페이스 | 봉투 구조, 버전·요청 ID, 유효성·업데이트/취소 방식 | 묶음 중 고정 기준과 재관측 갱신·투영 연결 |
| CURRENT 확인 범위 | 확인할 영역·층을 어떤 필드로 지정하는지 | 임의 전체 보드 비움이나 목표 생성 없이 판단 가능성 검사 |
| 전달판 측정 설정 | 실제 ROI·View·촬영 조건·비움 검증 방법과 설정 | 검출 없음이나 촬영 실패를 EMPTY로 오인하지 않음 |
| 층/손 설정 | Board 기준 층별 실측 높이·허용차, 손 ROI·품질·안정화 설정 | 미확정 측정값을 확정 layer나 안전 조건으로 사용하지 않음 |

## 현재 재사용 가능한 B 함수

- `backend_adapter.build_observed`: ASSEMBLY 결과 생성.
- `backend_adapter.build_current_observed`: 명시적 내부 확인 범위로 CURRENT 결과 생성.
  `required_regions`는 내부 함수 인자이며 D 공통 필드로 추가한 것이 아니다.
- `backend_adapter.deliver_observed`: 공통 여섯 필드 검증·callback 전달.
- `main.observe_cycle`: 관측점별 정지 확인→실제 촬영→검증→통합 처리.
  현재 target_after를 요구하므로 CURRENT 촬영 경로로 바로 호출할 수 없다.
- `live_view.ViewSelection.update`: 관측점·정지 상태 입력 경계. Robot 명령이 아니다.
- `visualization.freeze_overlay_states / render_state_overlay`: 표시 기준 고정·투영.

위 함수 존재는 실제 D/Controller 송수신 연결을 뜻하지 않는다. 기존 네 클래스
공통 배치 계약과 라이브 다섯 클래스(빨강 2x1 포함)의 차이도 D 확인이 필요하다.
공통 계약·로봇 이동·완료 판정을 임의 변경하지 않는다.
