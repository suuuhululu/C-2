# B → D 단일 PC 연결

## 현재 통합 기준 안내

2026-10-11 팀장님 요청의 INITIAL/STEP/FINAL·B 상태 소유 계약은
[ROUND1_INSPECTION.md](ROUND1_INSPECTION.md)의 `connect_inspection`을 사용합니다.
아래 `connect(bridge)`는 기존 전달판/Observed 계약의 호환 경로이며 새 검사 형식으로 자동 전환되지 않습니다.

실제 D `app.vision_connection.VisionConnection`의 bind와 세 submit 함수에
맞춘 B 진입점은 `perception_mvp.team_connection.connect(bridge)`다.
별도 서버/네트워크 API가 아니라 한 프로세스의 Python 함수와 Qt callback이다.

## 입력과 반환

요청은 D의 `check_id, after, purpose` 그대로 받는다. ASSEMBLY는 조립 Observed와
전달판 결과를 모두 반환하며, CURRENT는 Observed만, PLACE는 전달판만 반환한다.
Observed 여섯 필드 및 전달판 네 필드는 바꾸지 않는다. EMPTY는 실제 전달판
확인 근거가 있을 때만 실제 처리 함수가 생성해야 하며, 연결부가 추정하지 않는다.

Qt handler는 요청을 고정 복사하여 worker에 예약하고 즉시 반환한다. 새 check가
오면 이전 작업 결과를 전송하지 않는다. 같은 요청의 중복은 재촬영하지 않는다.
실패는 submit_failure로 보내며 자동 재시도하지 않는다. 한 check에서 채널별
한 결과만 보내므로 observation_seq는 내부에서 0으로 고정한다. 재관측은 새 check다.
`cancel(check_id)`와 `close()`는 결과 전송을 막으며 실제 Robot STOP을 대신하지 않는다.

## 실제 처리 함수 연결 — 아직 필요한 부분

D가 한 인자로 connect를 호출하는 경우 환경 `B_PERCEPTION_RUNTIME_MODULE`에
실제 처리 모듈을 지정한다. 그 모듈의 `process_request(request, is_active)`가
실제 손/촬영/검증/전달판 처리를 수행한다. 내부 request에는 observation_seq=0이
추가되며 결과는 다음 키를 가진 dict다. 이 봉투는 내부 함수 계약이지 D 공통 DTO가 아니다.

| purpose | 반환 키 |
|---|---|
| ASSEMBLY | observation, place |
| CURRENT | observation |
| PLACE | place |

장치 처리 함수는 손 대기·Controller 대기 중 is_active를 검사하고, 실제 STOP 및
안전 상태도 별도로 확인해야 한다. 활성 상태 검사는 요청 교체/cancel/close만 검사하며
Controller 안전이나 D의 모든 요청 닫힘을 자동 감지하지 않는다. 그 이벤트 연결도 필요하다.
내부 processor 호출 중에도 기존 요청 식별자를 유지해야 한다.

실제 processor가 없으면 connect는 bind 전에 명시적으로 실패한다. 가짜 결과나
예시 데이터로 시작시키지 않는다. 모듈 환경을 임의의 예시 이름으로 설정해 실행하면 안 된다.
현재 live_view는 이 processor를 구현하지 않는다. Controller의 V0/D1/D3 이동·정지,
실제 hand-config·층/보정값·전달판 비움 증거·CURRENT 확인 범위를 연결해야 실제 시연이 가능하다.

D 실행 옵션에서 B 모듈은 `--vision-module perception_mvp.team_connection`이며,
패키지 탐색 경로에 `/home/roh/C-2/perception`이 필요하다. 이것만으로 실제 processor가
생기는 것은 아니다. 기존 D 실행의 나머지 장치/음성 설정을 생략하지 않는다.

## 검증 범위

tests/test_team_connection.py는 정상 목적 분기·미수신 실패·잘못된 ID·중복·늦은
결과·취소·미설정 시작 차단과 실제 D Qt bridge의 one-argument connect 경로를 검사한다.
처리 함수 대역을 사용한 L1/L3 연결 검사이며 Camera/Robot 또는 인식 정확도 검증이 아니다.
