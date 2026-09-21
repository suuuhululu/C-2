# HMI 준비·양초 측정 흐름

> **최신 기준:** [main 8a68790 반영·ROS SIM 연결](HMI_INTEGRATION_20260921.md). 아래는 이전 구현 기록이다.

> **최신 반영은 [HMI 선행 수정](HMI_PREWORK_20260921.md)을 우선한다.** 아래는 최초 MOCK 구현 이력이다. 현재 준비 수동 bool 3개와 confirmed_at은 제거됐고 드릴 ON UI·관측 패널·준비 raw 클라이언트를 추가했다. 준비 Action 타입/서버는 main에 병합됐지만 HMI HTTP의 ROS 활성화·BIND·동적 profile 통합은 아직 미완료다.

2026-09-21. 기준 main `829db40`, 구현 브랜치 `codex/hmi-preparation-flow`.
제어팀 [준비 Action 검토 초안 `6a020c9`](https://github.com/suuuhululu/C-2/blob/6a020c9/ws_cobot_pjt/docs/PREPARE_WORKPIECE_ACTION_DRAFT.md)과
`feat/process-integration-clean`의 내부 SIM 연결을 읽고 HMI 부분을 구현했다.

**이번 구현은 HMI의 MOCK 통합이다.** 제어팀 ProcessCoordinator나 실제 측정 함수를 HMI에서 호출하지 않는다.
공정팀 SIM 설정의 합성값을 응답하는 모의 상대를 사용한다. 준비 ROS Action·상세 원본 전송·제어의 스냅샷 연결은 아직 미확정이다.
c2_interfaces, GeneratePath v2, ExecuteProcess v2, 제어팀 소스는 변경하지 않았다.
ROS 모드의 준비 요청은 NOT_READY로 거절하며 경로 생성·미리보기 시험은 유지한다. REAL은 계속 차단한다.

## 2026-09-21 사용자 결정 · 다음 구현 기준

드릴 ON은 운영자가 수동으로 전원을 켠 뒤 HMI에서 체크하는 UI로 한정한다. HTTP 실행 입력·ExecuteProcess에 ON 필드를 추가하거나 제어 코드에서 ON을 판정하지 않는다.
그리퍼/드릴 제어 명령은 제외하고 장착 상태는 실제 하드웨어 Topic의 관측·출처·품질·시각으로 확인한다.
준비 요청은 상태 검사 → 필요 시 검사된 홈 이동 → 홈 도착·정지 및 상태 재검사 → 윗면·사방 측정까지 포함한다.
홈 밖이라는 이유만으로 실패시키지 않는다. 이동 불가·보호정지·취소·정지 미확인 시에는 후속 동작을 차단한다.

현재 아래의 **세 운영자 bool을 필수로 받는 MOCK 코드는 이 결정 이전 구현**이며 수정 대상이다.
드릴 OFF는 측정 전 수동 운영 안내로 남기고 세 bool의 전송·서버 필수 검증을 정리한다. 이번 수정에서는 실행 코드를 변경하지 않았다.
[수현 작업 목록](HMI_ACTION_ITEMS_20260921.md)과 [세은님 전달 문서](PROCESS_HANDOFF_20260921.md)를 다음 구현 기준으로 사용한다.

## 현재 MOCK 사용 방법 · 결정 반영 전

1. 저장소 루트에서 `python3 ws_cobot_pjt/run_monitor.py --transport mock`을 실행한다.
2. **작업 준비 → 양초 준비·측정**에서 높이 150mm와 드릴 고정·그리퍼 닫힘·드릴 OFF 확인 세 항목을 확인한다.
   MOCK에서는 확인 UI 시험이며 실제 장치 상태를 판정하지 않는다. 높이는 등록된 SIM 설정과 일치해야 한다.
3. **사전 검사·양초 측정 요청**을 누른다. 상태 검사·윗면·옆면 1~8점·최종 결과를 표시한다.
   단계 진입은 완료가 아니다. 초록색 점은 해당 점의 성공 응답만 반영하며, 8점 완료만으로 다음 단계에 진입하지 않는다.
4. 최종 준비 성공·완전한 기하·정상 후퇴 근거를 확인하면 서버가 측정 원본과 새 설정을 자동 보관한다.
   사용자가 ZIP을 옮기거나 별도로 스냅샷을 등록할 필요는 없다.
5. 이미지 첨부 또는 **샘플로 둘러보기 → 경로 생성 → 미리보기 확인·공작물 고정 확인 → 시작 요청** 순서로 모의 공정을 확인한다.
   MOCK 경로는 첨부 이미지를 변환하지 않고 기존 고정 중심선 샘플을 사용한다.
6. 다시 측정하면 이전 경로·운영자 확인은 사용할 수 없다. 새 설정으로 경로를 다시 생성한다.
   **이전 준비 이력**과 **준비 기록·원본 보기**에서 실패·부분 결과도 확인할 수 있다.

진행 중 **준비·측정 취소**는 접수 뒤 최종 결과를 기다린다. 새로고침해도 같은 요청과 점별 진행을 복원한다.
접수 응답을 못 받은 경우 **같은 요청으로 접수 확인**을 사용한다. 재전송은 같은 request_id와 원래 입력을 유지한다.
취소 이후 늦은 성공, 최종 응답 없음, 정지 미확인, 결과 저장 실패는 UNKNOWN으로 새 작업을 차단한다.
서버 재시작 시 진행 중 요청은 UNKNOWN, 이전 성공은 재준비 필요로 표시하고 자동으로 다시 실행하지 않는다.
MOCK 시험의 미확인 상태는 **설정 정보 → 모의 상태 초기화**로 해제할 수 있다. 기록은 보존하며 실제 정지 확인이 아니다.

## 현재 MOCK 연결 · 결정 반영 전

| 항목 | 현재 구현 | ROS 통합 전에 합의할 내용 |
| --- | --- | --- |
| 요청·준비·측정 ID | 브라우저가 request_id, 서버가 preparation_id·measurement_id를 발급. 재전송 시 동일 값 | 같은 ID·같은 입력 재조회와 공정 수신부 중복 처리 |
| 측정 전 설정 | workpiece_simulation.json의 workcell·profiles·오프셋 및 MOCK 도구/TCP/하중 참조를 관리 자산으로 자동 등록 | REAL 설정 원본·등록 책임·유효성. SIM 자산을 실기 설정으로 사용 금지 |
| 작업자 확인 | 세 bool 개별 필수. 브라우저의 마지막 확인 UTC 시각과 서버 접수 시각을 분리 보존 | OFF 근거의 실제 측정 어댑터 전달, 확인 유효기간·운영자 인증 |
| 상세 측정 결과 | 모의 상대의 전체 결과를 성공·실패 모두 measurement_record 자산으로 저장. 진행 이벤트도 보존 | typed 핵심 Result + 공정이 저장한 원본의 ID/해시 참조를 제안. 저장 주체·공유 저장소·실패 처리는 제어팀과 확정 필요 |
| 측정 후 스냅샷 | 정상 결과를 바닥 기준으로 변환하고 불변 ID/해시 발급. 측정 ID·시각·수직 가정·미측정 기울기·설정 참조 보존 | 홍동님 요청별 프로파일 지원 및 실제 유효 상태 매핑 |
| 제어 연결 | 모의 상대의 준비 성공 기록과 최종 스냅샷 ID/해시 일치 응답 확인 후 활성화 | 실제 bind_preparation_snapshot은 내부 함수만 존재. HMI→제어 전달 방법·확인 응답 미확정 |

현재 상세 결과 사전은 **프로세스 내부 MOCK 응답과 HMI HTTP 데이터**다. ROS Action의 JSON 문자열 우회 규격이 아니다.
준비 Action 이름·schema_version·.action 파일을 임의로 확정하지 않는다. StopProcess.run_id에 준비 ID를 넣지 않는다.
기존 GeneratePath는 최종 profile_snapshot_id/profile_sha256로 요청하며, 준비 ID는 HMI 경로·실행 기록에 추가 보관한다.
기존 ExecuteProcess의 ROS 필드를 확장한 것은 아니다.

## 높이·단위와 결과 조건

- 측정 원본은 m, c2_base, 윗면 기준 아래 방향 v다. 높이는 OPERATOR_RULER 입력이며 독립 로봇 높이 실측이 아니다.
- HMI에서 한 번만 `bottom_z_m = top_z_m − height_m`, 바닥 범위 mm는 `[(H−v_max)×1000, (H−v_min)×1000]`으로 변환한다.
- 원본 bottom_z·base Z 작업 범위가 위 계산과 다르면 거절한다. 0이나 고정값으로 누락값을 채우지 않는다.
- 준비 최종 SUCCEEDED, geometry_ready=true, validity=SIMULATED, partial=false, stop_confirmed=true,
  같은 ID/해시·단위·좌표계·입력 높이·완료 시각·8점 원본을 확인해야 MOCK 스냅샷을 만든다.
- REFERENCE_ONLY/부분 결과/실패는 원본만 보존한다. 준비 성공이나 기하 생성 가능으로 바꾸지 않는다.
- 원본 stop_confirmed=null은 **확인 근거 없음**이며 true로 채우지 않는다. false는 미확인으로 작업을 차단한다.
- 생성 파일과 미리보기는 새 원점의 같은 base 좌표를 사용한다. HMI에서 생성 후 경로 전체를 다시 옮기지 않는다.
- 경로 미리보기 성공은 IK·J5/J6·충돌·드릴 ON 확인 완료가 아니다. 실제 제어 통합·실행 승인은 별도다.

## HTTP·저장 변경

| API | 기능 |
| --- | --- |
| POST /api/operator/preparations | 작업자 확인과 측정 전 설정 ID/해시로 MOCK 요청 접수 |
| GET /api/operator/preparations | 최근 준비 기록 100개 |
| GET /api/operator/preparations/{request_id} | 요청·진행·최종 결과·관리 자산 참조 |
| POST /api/operator/preparations/{request_id}/cancel | 해당 준비 취소 접수. 종료 확인과 구분 |
| GET /api/operator/snapshot / 기존 WebSocket | preparation 지원 여부·현재 요청·준비 사용 가능 여부 추가 |

POST 입력은 request_id, input_profile_snapshot_id, input_profile_sha256, height_m, confirmed_at 및 세 운영자 확인 필드다.
confirmed_at은 시간대를 포함한다. 실기 확인 유효기간은 미확정이며 이번 구현에서는 SIM 기록으로만 사용한다.
준비·생성·조각·미확인 작업은 서로 중복 접수되지 않는다. 같은 요청 재조회는 허용하고 다른 입력은 REQUEST_CONFLICT다.
기존 API의 경로 단독 생성 시험은 유지하지만, MOCK 화면의 생성과 모든 새 MOCK 실행은 준비 완료를 요구한다.
준비 실패·재측정 후에는 이전 설정 경로의 실행을 서버에서도 차단한다.

DB는 기존 버전 1에 preparations 테이블을 추가하며 기존 데이터를 삭제하지 않는다. 원본은 기존 관리 assets 저장소를 사용한다.
반영할 때 프런트를 빌드하고 백엔드를 재시작한다. 되돌릴 때 진행 중 모의 작업을 종료한 뒤 이전 코드로 복원하며
추가 테이블·자산은 보존한다. 되돌린 코드를 새 준비 검사가 적용된 상태로 취급하지 않는다.

## 담당자 연결 순서

1. 준비 세 bool 필수 검증을 제거하고 ON 수동 UI·하드웨어 관측·홈 복귀 재검사를 반영한다. 제어팀과 준비 Action 필드·버전, 상세 원본 전달, 스냅샷 연결을 확정한다. ON/OFF 확인 필드를 공정 입력으로 추가하지 않는다.
2. 공통 타입·제어 수신부·HMI RosBridge를 함께 연결한다. 이번 MOCK 함수는 실제 통신 규격으로 재사용하지 않는다.
3. 좌표팀 요청별 프로파일 변경과 함께 준비→측정→생성→미리보기→최종 검사→실행을 ROS SIM으로 확인한다.
4. REAL 제한은 해제하지 않는다. 현장 오프셋·측정·정지·관절 검증은 별도 기록한다.

[시험 결과와 재현 명령](VALIDATION_HMI_PREPARATION_20260921.md)
