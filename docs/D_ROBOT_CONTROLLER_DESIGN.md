# 수현 Robot 0~5단계 — Fake 연결·실제 한 블록 시험 준비

2026-10-06 최신 추가: 사용자가 노랑 4점 2번의 실제 전달/observe 복귀를 확인했고 HMI 연결 뒤 파랑 4점 5번을 바로 시험하며 검증하도록 지시했다. [단일 시험 HMI](../app/real_trial_hmi.py)는 기존 Backend/Qt와 실제 CLI를 QProcess로 연결한다. 창 열기는 조회만, 사람의 준비 확인/START가 실제 단일 전달이다. 파랑 측정 끝점을 원본 보간/경유 코드에 주입했고 40점 IK/FK·15개 메시지 변환·실제 QProcess 무이동 연결을 검사했다. 아래 이전 단계 기록과 구분하며 파랑 실기/STOP·재개/Camera/전체 Day4 REAL 완료로 확대하지 않는다. 구체 파일/범위/실제 로그와 검사는 [STATUS](STATUS.md), 실행법은 [안내](D_BACKEND_RUN_ROBOT_PLAN.md)다.

새 REAL snapshot은 단일 전달 전용이며 기존 Fake 전체 조립 상태의 mode만 REAL로 바꿀 수 없다. 아직 실제 Plan/Observed를 연결하지 않아 Current/조립 진행을 변경하지 않는다. Controller가 공급 슬롯을 소유하며 Backend가 Job/실행과 로그를 연결한다. QObject Controller 1개와 기존 QProcess만 추가했다. 활성 이동 프로세스를 UI 종료로 취소하거나 STOP ACK/프로세스 종료를 실제 정지로 해석하지 않는다. 실제 STOP/재개는 미검증으로 UI에서 차단하고 현장 비상정지 장치를 사용한다.

갱신: 2026-10-06. 사용자가 Robot **6단계까지** 승인했다. 5단계 조회 뒤 사용자의 6단계 첫 실행은 HOME 요청의 float64 변환에서 abort됐다. 타입 정규화와 실제 메시지 직렬화 검사를 보완하고 무이동 검증했다. 실제 전달/복귀 재실행은 미수행이다. 기존 실기 원본은 수정하지 않았다. 아래 이전 기록과 최신 실패/수정 결과를 구분한다.

추가 수정: JSON의 정수 수치도 입력으로 허용하지만 원본 ROS 호출에는 실수로 전달한다. 값/속도/경로는 같다. `check_motion_messages`는 원본 이동 메서드의 실제 ROS 메시지 직렬화를 송신 없이 검증한다. 최신 `--check`는 37점 IK/FK와 **15개 이동 메시지 변환**을 통과했다. 6단계 첫 실패는 source CLI의 argparse float와 새 JSON int의 차이를 놓친 연결 결함이다. 상세 실패 원자료·511개 회귀 결과는 [STATUS](STATUS.md)에 남겼다.

## 5단계: 실제 한 블록 시험 연결과 조회 결과

[robot_trial.py](../app/robot_trial.py)는 기존 `yellow4_row_to_place.py`를 해시로 확인한 뒤 `plan`·`RowRobot`·`Gripper`를 재사용한다. 원본 main/연속 전달은 호출하지 않는다. [외부 설정](../interfaces/robot_trial.json)에서 노랑 4점 2번 슬롯·기존 속도/높이/장치 이름과 사용자 제공 observe posj/posx를 채택한다. pose/경로를 새로 보간하거나 기존 보간 규칙을 수정하지 않는다. 원본은 start_block=2만으로 6번까지 실행하므로, 선택 슬롯 명령과 기존 HOME 복귀만 남기고 사용자가 검증했다고 확인한 HOME→observe posj 복귀를 연결했다. 정상 매 Step의 사람 확인 버튼은 추가하지 않는다.

기본 실행은 계획만 출력하고 장치에 연결하지 않는다. `--check`는 조회/IK/FK/그리퍼 레지스터 읽기만 수행한다. `--execute`만 실제 이동과 개폐를 보낸다. REAL 모드·현장 확인 누락, 원본 해시 변경, TCP/tool 불일치, 대기/이동 상태 오류, 집기 유지 실패, 기록 실패는 보류이며 자동 재시도가 없다. 이 실행부는 **현장 단일 전달 시험용**이며 현재 FAKE 전용 Controller/Backend/HMI와 연결하지 않았다. Fake Vision으로 실제 Robot을 연속 실행하지 않는다.

집기 감지 응답만으로 소모하지 않고 첫 상승 후 기존 RG2 상태 레지스터의 grip 유지도 확인한 뒤 해당 슬롯의 다음 번호를 한 번 기록한다. 놓기/복귀 실패가 나도 기록된 집기 사실을 지우지 않는다. 기존 Job 공급 상태를 변경하는 API는 아직 연결하지 않았다. 모든 명령 전/집기/놓기/복귀/최종 결과는 기존 JSONL writer로 독립 시험 UUID 파일에 기록한다. 실제 조립 Current·Step/Job 완료 이벤트는 발행하지 않는다.

- 실제 조회: `dsr01`, Jazzy, ROS_DOMAIN_ID=20, M0609 real bringup·RG2 서버 확인. robot_state=1, check_motion=0, robot_mode=1, TCP=`GripperDA_v4`, tool=`ToolWeight0`, RG2 status=0·폭 62.1mm. TCP 이름 일치는 오프셋 측정 증거가 아니며 오프셋/tool 변경 없음은 현장 사용자 확인이다.
- 실제 무이동 검사: 원본 경로 **37개 표본점 IK/FK** 통과. observe FK 좌표도 사용자 posx와 기존 FK 기준(2mm/1도) 이내다. 종료 코드 0, 로그 `/tmp/c2-robot-stage5-check-logs/8a29e914-22ca-4d22-befa-b62dfb586db3.jsonl`. 충돌·카메라 시야·블록 전달 성공 시험은 아니다.
- 초기 조회에서 ROS 인터페이스 타입을 찾지 못한 원인은 shell에 기존 workspace overlay가 적용되지 않은 것이다. `/home/ms-02/cobot2_ws/install/setup.bash`를 읽어 해결했다. 설치/build/driver 변경은 없다.
- STOP API는 설치 C++에서 ACK이고 실제 정지 증거가 아니다. MoveStop은 이동 호출과 별도 callback group이지만 실제 처리 시간·진행 중 호출 종료/블록 상태·HMI STOP 연동은 미검증이다. 단일 현장 CLI 실패 시 기존 stop 요청을 사용하되 정지 완료/재개 허용을 반환하지 않는다. 실제 STOP/재개 시험은 7단계다.

사용자가 현장 확인 flag를 저장한 뒤 6단계를 시도했고, 위 타입 수정 후 단일 전달 재실행이 남아 있다. 재실행 시 해당 현장 상태를 확인한다. observe 끝점과 HOME→observe 경로 검증, 현장 감시/비상정지 가능 사람, 기존 TCP/tool·배치 유지는 사용자가 확인했다. 카메라가 실제 놓기/시야를 자동 확인한 것은 아니다.

추가 요구: observe point·동작 설정·팀 모듈 연결·Day4 이후 확장에 필요한 값은 변경 가능한 설정으로 분리한다. Fake 공급/전달/관측 위치 이름·슬롯 수는 외부 JSON으로 주입한다. 4단계 실행 예제는 `--robot-config`, `--fixture`, `--delay-ms`를 제공한다. 실제 동작 값·팀 연결 설정은 후속 연결에서 검증하며 기존 Python 전체를 일괄 수정하지 않는다.

## 0단계: 재사용 근거와 확인 범위

자료 위치는 `/home/ms-02/C-2_협동2자료/robot_cycles/`다. 이 자료와 Git 개발 저장소 `/home/ms-02/C_2`의 게시/검증 상태는 별개다.

| 근거 | 코드/기록에서 확인한 내용 | 새 Controller에서 남은 확인 |
|---|---|---|
| `yellow4_to_place.py` | 노랑 4점 1번의 집기·고정 전달·HOME 복귀 순서. Robot/Gripper 구체 호출 코드 | 1번의 별도 스크립트 전체 실행 성공을 2~6번 기록으로 대신하지 않음 |
| `yellow4_row_to_place.py` | 노랑 4점 1~6번 계획, 종류가 고정된 연속 실행, 중간 전달판 Enter 확인, 마지막 HOME 복귀 | 한 블록 실행으로 분리·각 전달 뒤 observe point 복귀·Backend 자동 비움 관측 연결 |
| `yellow4_row_success_2026-10-04.json` / `.txt` | 사용자가 2~6번 자동 전달과 마지막 HOME 복귀를 확인. 1번은 이전 수동 전달. 실제 입력 명령은 별도 캡처하지 않음 | 네 종류/색상·전체 1~6번 자동 전달·조립 장애물 여유·실제 STOP/재개·Action은 미검증 |
| Robot 서비스 호출 | 코드상 `/{robot_id}/dsr_controller2/` 아래 TCP/tool 조회, 대기 상태 조회, IK/FK 검사, 이동, `motion/move_stop` 호출 | 현재 설치 driver의 반환 의미·실제 정지 확인·진행 중 호출 취소/종료 확인은 현장 검증 필요 |
| `Gripper.move` | 코드상 Modbus 상태/폭 읽기, 닫기 시 `require_grip=True` 감지 대기, timeout/오류 발생 | 감지 후 집어 올린 실제 블록의 유지·STOP 이후 블록 상태·놓기 성공 증거 확인 |

기록의 TCP `GripperDA_v4`, tool `ToolWeight0`, HOME `[0,0,90,0,90,0]`, 관절 속도 20도/s, 접근 40mm/s, 이송 80mm/s, 접근 높이 30mm, 이송 Z=200mm, 경유 Y=400mm, 공급 staging X=-450mm, 그리퍼 60/2mm·40N을 **과거 시험 설정**으로 보존한다. 이번 새 실행 설정으로 채택하거나 변경하지 않는다. 실제 pick/place pose는 원본을 참조하고 새 좌표를 작성하지 않는다. HOME이 observe point라는 근거는 없다.

주의할 연결 차이:

- `Robot.call`은 응답을 동기 대기한다. Qt의 버튼 처리에서 그대로 호출하지 않는다. 긴 이동/그리퍼 대기 중에도 STOP 입력과 처리 경로가 유지돼야 하며 실제 연결 방법은 5단계에서 driver와 확인한다.
- `Robot.stop`은 정지 서비스를 호출하고 실패를 출력한다. 실제 정지·이전 실행 종료·블록 상태 확인을 반환하지 않는다. 정지 응답/timeout/노드 종료를 실제 정지 완료로 바꾸지 않는다.
- 집기 감지는 닫기 호출 안에 있고, 이후 상승/이송은 별도 이동이다. 감지 반환만으로 새 Controller의 실제 pick 성공·슬롯 소모 근거가 완성됐다고 표시하지 않는다.
- 기존 연속 실행은 각 블록 뒤 HOME/observe point로 돌아오는 구조가 아니다. 매 Step Enter를 HMI 버튼으로 옮기는 방식도 최신 계약과 맞지 않는다. 기존 스크립트는 보존하고, 후속 adapter에서 한 블록 전달 경계를 연결한다.
- `--check`는 조회/IK와 그리퍼 통신까지 연결하므로 원격 독립 검사로 실행하지 않는다. `--execute`는 장치를 움직인다. 이번에는 둘 다 실행하지 않았다.
- 장애물 높이 기본값 92mm는 코드의 가정이다. 실제 장애물 높이/여유의 확인값이나 새 실행 승인으로 사용하지 않는다.

## 1단계: 책임과 기존 연결 형식

Backend가 Job/Plan/Step·실행 ID·진행·Current/Expected·관측 확인을 소유한다. Controller는 공급열/슬롯·한 블록 전달·정지 증거·재개 동작을 소유한다. driver는 검증된 장치 호출과 실제 결과를 제공한다. Qt는 Backend snapshot 표시/명령 신호만 담당한다.

아래는 [현재 Backend](../app/backend.py)에 이미 있는 **Python/Fake 연결 경계**다. ROS Action/topic/service 이름·실제 transport envelope를 확정한 것이 아니다. 2~3단계의 Fake Controller가 이 의미를 먼저 소비하고 4단계에서 Backend에 연결한다. 새 공통 필드나 Schema를 이번 단계에서 추가하지 않는다.

| 방향 | 기존 포트/호출 | 값과 의미 |
|---|---|---|
| Backend → Controller | `robot.deliver` | `execution_id, brick_type, color`. 조립판 좌표·slot·pose는 전달하지 않음 |
| Backend → Controller | `robot.stop` | `request_id, execution_id`. 실행이 없으면 execution_id는 null. request_id는 정지 확인 연결에 사용 |
| Backend → Controller | `robot.resume` | 새 `execution_id`, `previous_execution_id`, `goal`. goal은 전달 3필드 또는 null |
| Controller → Backend | `on_robot_result(value)` | `execution_id, success, reason`. 실패 reason은 비어 있지 않음. 정상 결과는 reason=null 사용 |
| Controller → Backend | `on_stopped(request_id, stopped=..., execution_ended=..., block_state_known=...)` | 세 확인이 모두 true여야 정상 STOPPED. 기존 Fake 함수의 인자이며 실제 장치 증거 수집/반환은 미구현 |
| Controller → Backend | `controller_ready(ready=..., at_observe_point=...)` | 새 시작 전 준비/관측 위치 확인. 실제 확인 없이 true를 넣지 않음 |

정상 전달 요청/결과 예시:

```json
{"execution_id":"delivery-example","brick_type":"2x2x1","color":"yellow"}
```

```json
{"execution_id":"delivery-example","success":true,"reason":null}
```

정지/재개는 현재 내부 연결 형식을 그대로 사용한다:

```json
{"request_id":"stop-example","execution_id":"delivery-example"}
```

```json
{"execution_id":"resume-example","previous_execution_id":"delivery-example","goal":{"execution_id":"resume-example","brick_type":"2x2x1","color":"yellow"}}
```

`goal=null` 재개는 observe point 복귀 확인만 필요할 때의 기존 경계다. 새 집기를 요청하지 않는다. 이때 success는 **복귀 요청 완료**이며 새 블록 전달/조립 완료가 아니다. Backend가 요청 문맥을 구분한다. Controller가 조립 상태를 추정하거나 결과에 delivery_state를 추가하지 않는다.

## 변경 가능한 설정의 경계

새 Controller는 **명시적으로 전달받은 설정 값**을 사용한다. pose·observe point·속도·슬롯 위치·팀 연결 주소를 Python 상수로 넣지 않는다. 표준 JSON 파일을 읽은 dict를 시작 연결부에서 검사해 Controller/adapter에 전달하는 최소 방식이다. 설정 전용 framework·동적 plugin·Factory·실행 중 자동 재보정은 추가하지 않는다. 2단계의 Fake 설정 구조/필수값/지원값 검사는 `validate_robot_config`와 아래 Fixture로 구현했다. 실제 pose/driver 설정 형식은 후속 검증 대상이다.

| 변경할 설정 | 소유/사용처 | 변경 시 확인 |
|---|---|---|
| 실행 모드·설정 식별 | 시작 연결부 → Backend/Controller/로그 | FAKE/REAL 명시. 누락을 REAL로 해석하지 않음. 현재 실행은 FAKE만 구현 |
| observe point·복귀 경로·좌표계/단위 | 수현의 검증 설정 → Controller/driver | 실제 pose/경로가 확인된 값인지 검사. HOME이나 빈 값으로 대신하지 않음 |
| 공급열 종류/색상·슬롯 위치/개수·고정 전달 위치 | Controller | 종류/색상은 공통 계약과 일치. 각 위치가 검증됐는지 확인. 현재 Day4 슬롯은 1~6 |
| TCP/tool·속도/가속·높이·그리퍼 폭/힘·장치 주소 | 수현의 검증 설정 → driver | 범위/단위·현장 TCP/tool·실제 경로 확인. 기존 시험값을 무조건 기본값으로 실행하지 않음 |
| ROS namespace/Action·Vision 연결 이름/주소 | 인접 연결부 | 메시지 의미·식별·지연/실패 반환 검증. 이름 변경이 완료 의미를 바꾸지 않음 |
| 촬영 가능 신호·전달판 영역·촬영/View 구성 | 홍동과 수현의 연결 설정 | 홍동이 촬영 시점/판별 조건을 정하고 수현은 검증된 이동/정지를 연결. Controller가 새 카메라 이동 경로를 생성하지 않음 |
| 판 크기·최대 층·지원 블록/색상/작업 | 팀 공통 지원 설정 | Day4 기본은 24×24·4층·4/6점·노랑/파랑·PLACE. 이후 변경은 A/B/C/D의 Schema·지원값 검사·기하/화면/Controller 검사와 함께 반영 |

설정 파일이 바뀌었다고 실행 중인 Job에 즉시 반영하지 않는다. Job 시작 시 검증한 설정의 복사본/식별을 고정하고 그 Job의 로그에 연결한다. 설정을 바꾸려면 실행을 멈춘 상태에서 검사하고 다음 Job에 적용한다. 실제 pose/TCP/경로 변경은 현장 재검증 뒤 사용할 수 있다. 이 설정 고정은 실행 중 보정 변경/Camera 재시작을 Day4에 넣지 않는 기존 범위와 맞는다.

검증 실패/지원 범위 불일치/Real 필수 위치 미설정은 시작 보류와 사유로 처리한다. 임의 좌표 생성·기존 HOME으로 fallback·값 누락을 정상값으로 채우지 않는다. 구조/필수값/지원값 검사는 수현 경계, 전체 기하/지지는 세은, 관측 성능은 홍동의 검사로 나눈다.

Day4 이후 확장은 값 교체와 기능 변경을 구분한다. 검증된 observe point/주소/지원 규격의 변경은 설정을 통해 반영한다. MOVE/REMOVE 같은 새 동작은 설정에서 허용 목록만 바꿔 구현된 것으로 처리하지 않고 담당 알고리즘/효과/관측/Controller 계약과 검사를 추가한다. 현재 코드의 고정 Day4 Schema·Backend 지원 범위·24×24 표시도 변경 대상이 될 수 있으며, 이번 Robot 1단계에서 이미 가변 구현됐다고 표시하지 않는다.

2단계 설정 주입에 이어 4단계에서 같은 공급 상태를 Backend/HMI에 연결하고 Job의 검증 설정 전체/식별을 JSONL에 기록했다. 설정은 START 때 읽어 복사하고 RESUME에서 다시 읽지 않는다. 5단계는 실제 검증 pose/driver 설정의 외부 연결 대상이다. 기존 실기 원본의 상수/실측값은 근거 자료로 보존한다.

## 단일 실행과 결과 설계

Controller 한 개와 구체 Fake driver 한 개로 정상/중복/실패/STOP/재개를 구현했다. Factory/Manager/추상 driver 계층·DB·자동 복구는 없다. 세 증거와 집기 상태는 Fake가 명시적으로 제공하며 실제 장치 증거 수집 API는 아직 없다.

- 한 번에 활성 실행 하나. Controller 내부에는 활성 execution_id·요청 종류/색상·선택 슬롯·이번 전달의 확인된 진행 사실·종료/STOP 확인을 보관한다. 확인된 집기/놓기 사실은 내부 재개 판단용이며 공통 enum이나 HMI 필드를 늘리지 않는다.
- 정상 순서는 준비/현재 비움 확인 → 집기 → 고정 전달 위치 놓기 → 검증된 observe point 복귀/정지 → 최종 성공 결과다. 요청 수락·move/gripper 한 명령 성공을 전달 최종 성공으로 반환하지 않는다. 전달판 비움 관측과 그 유효성은 Backend/홍동 경계에 둔다.
- 활성/종료 execution_id의 동일 요청 중복은 새 driver 호출·집기·슬롯 소모·최종 결과 발행을 만들지 않는다. 같은 ID에 다른 종류/색상은 식별 충돌로 거절하고 기존 실행 사실을 보존한다. 잘못된 중복의 실패를 원래 활성 실행의 최종 결과로 붙이지 않는다.
- 다른 새 ID가 활성 실행 중 도착하면 새 전달을 거절한다. adapter는 그 새 요청의 실패/수락 거절을 Backend의 해당 요청에만 연결하며 진행 중인 실행을 바꾸지 않는다. 구체 ROS 수락 거절 mapping은 5단계에서 확인한다.
- 시작한 각 실행의 최종 결과는 한 번만 발행한다. STOP된 이전 실행은 종료/관측 사실을 보관하고, 뒤늦은 성공 callback이 새 실행을 완료하거나 추가 소모시키지 못하게 한다.
- 실패/timeout·놓기 후 복귀 실패·상태 불명확은 사유와 보류다. 자동 집기 재시도·번호 보정·오류를 성공/빈 정상값으로 바꾸는 경로는 없다. 실제 이전 동작 종료/정지가 확인되기 전 새 실행을 시작하지 않는다.

## 공급 슬롯 설계

네 공급열은 `(2x2x1, yellow/blue)`, `(2x3x1, yellow/blue)`다. Controller가 각 열의 다음 슬롯 1~6과 보충 필요를 관리한다. 재계획/STOP/재개는 공급열을 초기화하지 않는다.

1. 준비된 다음 슬롯을 선택해 해당 실행과 연결한다. 단순 선택/집기 명령 발행은 소모가 아니다.
2. driver가 **실제 집어 올림 확인**을 제공할 때 그 실행의 슬롯을 한 번 소모한다. Fake에서는 이를 명시 이벤트로 제공한다. Real의 감지/상승/유지 증거 조합은 5단계 확인 대상이다.
3. 집기 뒤 놓기/복귀 실패가 나도 확인된 소모를 되돌리지 않는다. 미집기 확인이면 같은 다음 슬롯을 유지하고, 집기 여부가 불명확하면 번호를 임의 결정하지 않고 보류한다.
4. 6번이 실제 소모되면 해당 열만 보충 대기다. 기존 HMI 필드 next_slot=null, needs_refill=true로 연결했다. 7번을 표시하거나 선택하지 않는다.
5. 해당 열을 사람이 채우고 보충 완료를 확인했을 때만 그 열을 1번으로 초기화한다. 소모 여부 불명확·활성 실행의 슬롯을 보충 입력으로 자동 정리하지 않는다.
6. 새 Job은 준비 확인 뒤 START에서 Controller의 공급 순서를 초기화한다. START는 조립판/전달판 비움·공급판 채움의 명시 확인 의미다. 오류 후에는 STOP 세 증거와 별도 준비/빈 그리퍼 확인을 먼저 받아야 START 상태로 돌아간다. STOP/재개/정리 확인만으로 Current나 공급을 초기화하지 않는다.

## STOP/재개 설계

STOP은 신규 집기/진행을 막고 활성 요청/관측을 닫는다. Job·채택 Design·Current·완료 기록·확인된 공급 소모는 유지한다. Controller/driver가 실제 정지, 이전 실행 종료, 블록 상태를 각각 확인해야 한다. 요청 ACK·cancel 응답·스레드 종료만으로 세 조건을 충족했다고 표시하지 않는다. 확인되지 않으면 보류하고 재개시키지 않는다.

| Controller가 확인한 실제 상황 | 새 실행 ID 재개 동작 | 공급 소모 |
|---|---|---|
| 집기 전 | 같은 Step·같은 다음 슬롯의 Goal 재전송 | 집어 올림 확인 전 증가 없음 |
| 들고 있음 | 새 집기 없이 현재 블록 전달·observe point 복귀 | 이미 확인한 슬롯 유지, 추가 소모 없음 |
| 놓았음 | 집기/놓기 없이 observe point 복귀 | 이미 확인한 슬롯 유지, 추가 소모 없음 |
| 불명확 또는 이전 실행 미종료 | 실행 보류·이유 표시 | 추정 증가/되돌림 없음 |
| 조립/계획 대기에서 정지, goal=null | 확인된 빈 그리퍼 상태 등 검증 조건하에 관측 위치 복귀 요청만 처리 | 공급 슬롯 변화 없음 |

새 실행은 이전 실행과 같은 Job/Step 연결을 Backend가 유지한다. Controller가 확인 사실을 새 실행 ID에 연결하며, 이전 ID의 늦은 callback을 재개 동작 증거로 덮어쓰지 않는다. 복귀/정지 확인 뒤 Backend가 새 check를 열고 홍동이 실제 프레임을 선택한다. 정상 매 Step 완료/전달판 비움 버튼을 추가하지 않는다.

## 4단계에서 연결한 Backend 경계

| 연결 경계 | 현재 동작/남은 확인 |
|---|---|
| `connect_robot`와 snapshot | Controller를 첫 Job 전에 연결하고 준비/공급 값을 읽어 기존 HMI 필드에 표시. 미연결 Backend 검사는 기존 null 표시 유지. Qt가 슬롯 계산하지 않음 |
| `SUPPLY_REFILLED` | 현재 Job·해당 열·준비/보충 필요를 확인해 Controller를 호출하고 기록. 보충 후 새 EMPTY 확인 전에는 다음 집기 없음 |
| 오류 후 새 시작 | STOP 증거 뒤 driver의 준비/빈 그리퍼 증거를 `on_robot_cleanup(job_id)`로 연결해 IDLE로 전환. 기존 Current/공급/오류는 유지하고 START에서 새 Job·설정·초기 배치를 채택. 자동 정리/재시작 없음 |
| Backend는 명시적 FAKE 모드만 허용 | Real 준비가 끝나기 전 실행 모드/driver를 바꾸지 않음. 실제 adapter로 교체했다고 표시하지 않음 |

`FakeDemo.confirm_robot_cleanup()`는 독립/Qt 시험에서 별도 정리 증거를 제공하는 입력이다. 일반 STOP/START 버튼이 자동 호출하지 않는다. 실제 준비/빈 그리퍼 확인의 생산자 연결은 5단계에서 정한다. 오류 시 GUI만으로 자동 정리할 수는 없다.

## 단계별 검사 기준

아래 2~4단계 검사 기준을 Fake/독립/Qt offscreen에서 실행했다. 실제 정지·촬영·사람 조립 시험으로 표시하지 않는다. KEEP/REVISE/UNCLEAR는 기존 Fake 시나리오와 새 Controller의 연결로 확인했다.

| 단계 | 입력/경로 | 외부에서 확인할 결과 |
|---|---|---|
| 2 | 정상 1회·명령 발행만·집기 확인·놓기·복귀 | 슬롯은 집기 확인 한 번에만 증가, 복귀 전 success 없음, driver 호출 순서·최종 결과 한 번 |
| 2 | 같은 활성/종료 ID 중복·같은 ID 다른 요청·동시 새 ID | 새 집기/이중 소모 없음, 잘못된 요청이 기존 실행을 완료/취소하지 않음 |
| 2 | 네 열·6번 소모·해당 열 보충·설정 복사본 | 독립 순서 유지, 7번 없음, 재계획으로 초기화 없음, 확인된 열만 1번. 주입한 지원 설정을 사용하고 진행 중 외부 dict 변경으로 동작이 바뀌지 않음 |
| 3 | 집기 전/들고 있음/놓았음 STOP·재개 | 새 실행 ID, 세 가지 동작 차이, 추가 소모/중복 집기 없음 |
| 3 | 정지 미확인·이전 실행 미종료·블록 상태 불명확 | 새 실행/다음 집기 없음, 사유 유지 |
| 3 | 집기/놓기/복귀 실패·timeout·옛 callback·중복 결과 | 실패 보류, 확인된 실제 소모 유지, 자동 재시도/새 실행 완료 없음 |
| 4 | 정상 3 Step·전달판 미확인/점유·조립 관측 불가 | 전달과 조립 완료 분리, 최신 EMPTY/실제 Step 확인 전 다음 전달 없음 |
| 4 | 공급 보충·Robot 오류 후 정리/새 시작·로그 실패·설정 변경 | Controller 사실이 화면/로그에 일치, 초기화 조건/설정 식별 확인, 기록 실패 시 신규 실행 보류/STOP 경로 유지. 새 설정은 검사 후 다음 Job에 적용 |

## 4단계 현재 구현·검증과 남은 제공물

[robot_controller.py](../app/robot_controller.py)는 기존 3필드 goal을 받아 수락 여부/사유를 반환하고, 집기 → 놓기 → observe point 도착/정지 확인 뒤 기존 3필드 최종 결과를 한 번 반환한다. [fake_robot_driver.py](../app/fake_robot_driver.py)는 요청을 기록하고 `confirm/fail/confirm_stop`으로 모의 결과를 제공한다. Qt 예제의 타이머가 이 driver 결과만 지연 공급한다. Controller나 Qt가 Current/조립 완료를 대신 확정하지 않는다.

[robot.json](../interfaces/fixtures/robot.json)의 필수 설정은 `config_id, mode, slot_count, supply_rows, place_point, observe_point`다. 각 공급열은 `brick_type, color, supply_point`다. 네 Day4 열을 모두 지정하며 모드는 FAKE만 허용한다. 기본 슬롯 수는 6이고 독립 Fake 검사의 축소 설정은 1~6을 허용한다. 6 초과·다른 종류/색상은 현재 계약에서 거절한다. 위치는 Fake 식별명이며 실제 좌표가 아니다. Job 시작 때 검사한 복사본을 고정하고 `ROBOT_CONFIG_ADOPTED`로 기록한다.

최종 검사 결과는 [STATUS](STATUS.md)에 기록한다. [Controller 독립 검사](../tests/unit/test_robot_controller.py), [Backend/Controller 연결 검사](../tests/unit/test_robot_backend.py), [Qt offscreen 검사](../tests/unit/test_qt_hmi.py)와 기존 검사/팀 연결 소비 검사 17개를 실행한다. 실행 거절/모순된 증거/driver 실패/timeout·늦은 결과는 보류하고 자동 재시도하지 않는다. 집기/놓기/복귀 로그 실패는 다음 이동을 막으며 STOP은 가능하다. lint/type check는 미구성이다. 누락/지원 외 설정·goal은 ValueError, 파일 누락/JSON 오류는 원래 예외를 유지한다.

다음 승인 단위는 5단계 실제 driver adapter 준비이며 장치 움직임은 포함하지 않는다. 수현의 검증된 observe point/복귀 경로·네 공급열 설정·pick/놓기 증거·실제 정지/이전 실행 종료·준비/빈 그리퍼 확인 API가 필요하다. 홍동의 촬영 시점/전달판 callback은 연결 의미를 확인할 실제 반환이 필요하다. 공통 계약 필드를 팀원에게 다시 작성해 달라는 요청이 아니다. 실제 모듈/Camera/Robot 연결·안전·장치 시연과 추가 GitHub 게시 없음.
