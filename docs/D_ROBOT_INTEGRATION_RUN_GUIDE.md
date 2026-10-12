# 통합용 로봇 실행 안내 — 2026-10-11

사용자 결정에 따라 전체 Plan의 실측 프로필을 모두 채워야 시작하는 규칙은 넣지 않았다. D가 요청한 **현재 Step의 필수 입력**을 확인해 실행한다. 가상 수치는 모의 프로필에만 넣었다. 원본 ZIP과 측정 파일은 보존했다. GitHub 게시/병합과 기존 HMI의 실행 경로 변경은 하지 않았다.

현재 A/B/C/D·HMI·DB 모의 연결과 확정 결정은 [최종 MVP 실행 안내](D_MVP_INTEGRATION_20261011.md)를 우선한다. 아래 개별 Robot 실행·실측 입력 양식은 함께 사용한다.

## 코드 위치와 실행 범위

Backend 호출부는 `/home/ms-02/C_2/app/robot_process.py`, 모의 실행 명령은 `/home/ms-02/C_2/scripts/robot_integration_smoke.py`다.

Robot 소스 루트는 아래 위치다. 압축 원본에서 분리한 개발 사본이며, 기존 실기 시험 프로그램을 덮어쓴 것이 아니다.

```text
/home/ms-02/C-2_협동2자료/work/c2-virtual-inputs-20261011/D_robot_control_integration_20261011/robot_control_integration_20261010
```

그 안의 `scripts/robot_integration_runtime.py`가 새 실행 진입점이다. `app/integration_runtime.py`는 Step 진행/STOP/재개를 담당하며 기존 이동, 정지 검증, 파지, 위치 누름/Native35 함수를 호출한다. `app/integration_motion_binding.py`는 A의 픽업·파지 이송 후보와 D 프로필이 일치하는지 확인한다. 기존 `robot_control_trial.py`는 시험용으로 유지했다.

최종 MVP의 색/종류/방향과 1~5층을 소프트웨어에서 처리한다. `ROBOT_GRIP`의 도움 없음/잡기 도움/사람 누르기＋잡기(`PRESS_AND_HOLD`)와 `HUMAN_ASSEMBLY`를 지원한다. PRESS_AND_HOLD는 pre-contact 엄지척 후 near-contact에서 놓고 후퇴해 사람이 누르도록 하며 Robot force press를 추가하지 않는다. 미구현 `ROBOT_RELEASE_PRESS`는 다른 동작으로 대체하지 않고 거절한다. Native35의 기존 검증 범위는 **4점·회전 0°**이며, 다른 블록의 실기 체결 검증을 대신하지 않는다.

## 오늘: 장치 없이 실행

프로젝트 환경의 Python을 사용한다. 기존 Robot 환경의 numpy/scipy/pytest가 필요하며 새 의존성은 추가하지 않았다. 아래 실행은 MOCK이며 Camera/Robot/LLM/DB에 연결하지 않는다.

```bash
cd /home/ms-02/C_2
python3 -m scripts.robot_integration_smoke --robot-root '/home/ms-02/C-2_협동2자료/work/c2-virtual-inputs-20261011/D_robot_control_integration_20261011/robot_control_integration_20261010' --scenario robot --output /tmp/c2-robot-runtime-robot.json
```

`--scenario`를 아래 값으로 바꾸어 각각 실행한다.

| 값 | 확인하는 흐름 |
|---|---|
| `robot` | 공급 집기→조립판 pre-contact→체결→개방/후퇴→B 결과 대기→FAKE B KEEP |
| `tray` | 전달판 상공 3초 동안 새 손 없음 입력→하강→도달/정지 확인→개방/후퇴→10초 완료 신호 대기→FAKE B 검사 |
| `direct` | 전달판 하강 전 편 손 준비 입력→정지 상태 재확인→직접 인계→10초 후 FAKE B 검사 |
| `hand-hold` | 손은 있지만 준비 신호 없음→3초가 지나도 하강/개방하지 않음→STOP·파지 유지 |

보고서의 `mode=MOCK`, `device_connections=0`, `physical_simulation=false`, `b_result_kind=FAKE`를 확인한다. 이는 Isaac/실물 성공 결과가 아니다.

## 내일: 현재 Step의 값을 채우기

Robot 루트의 `settings/integration_runtime/real-step.template.json`이 빈 실기 입력 양식이다. 원본을 보관하고 작업용 파일로 복사한다. `fake.example.json`의 숫자나 FAKE session을 실기 입력으로 승격하지 않는다. 새 가상 실행용 입력은 Robot 루트에서 `python3 -m scripts.robot_integration_fixture fake`로 생성한다. 가상 session의 유효 시간이 지나면 다시 생성한다.

| 위치 | 채울 값 / 단위 / 기준 |
|---|---|
| `step` | A 재평가가 선택한 Plan/Step·블록·작업 방식, B의 최신 Current revision, D의 실제 예약 |
| `step.case_id`, `d_profile.steps`의 키 | 같은 D 프로필 키 사용: `case_id/step_id` |
| `pickup_pose` | 실제 슬롯의 TCP `[X,Y,Z,A,B,C]`, mm·deg·Base/ZYZ. **패드 하단=블록 밑면+5mm**의 교시 TCP |
| `reference_pose` | 같은 파지/TCP로 완전 체결된 목표의 TCP. 기존 측정 기준을 재사용하고 중심 0.5 stud·228mm·5mm 파지 오프셋을 다시 더하지 않음 |
| `turn_base_z_deg` | 해당 파지에서의 실제 Base Z 회전. 설계 90°를 무조건 복사하지 않음. 회전 파지 XY 보정 실측 여부도 함께 입력 |
| `pickup_width_mm`, `release_width_mm` | 해당 블록의 실제 닫기/최소 개방 폭과 피드백 범위. 측정된 35/48mm는 해당 시험 대상에만 적용 |
| `place_pose` | 전달판의 실제 내려놓기 TCP. 사람 직접 인계에서도 전달판 상공 경유 기준으로 사용 |
| `clearance_z_mm`, `supply_transit_xy_mm`, `body_bypass_xy_mm` | 기존에 검증한 상승/공급판 상공/몸통 회피 경로의 mm 값 |
| `approach_offset_mm` | 완전 체결 TCP에서 pre-contact TCP까지의 실제 차이. **새 블록 밑면이 아래 stud 끝보다 20mm 위**라는 기준과 A 반환을 대조. 기존 20.1mm가 같은 의미인지 확인 없이 바꾸거나 그대로 승인하지 않음 |
| 속도·가속도·힘·이동 한도 | 검증된 설정의 mm/s, mm/s², N, mm. 블록별 시험 근거를 사용 |
| `profile_id`와 기존 확인 필드 | 실제 D 프로필과 확인 근거. 미확인 값을 확인 완료로 바꾸지 않음 |
| `session` | 현재 실행의 새 execution_id/source_epoch, profile/frame 참조, 만료 시각(Unix 초), Plan/Step/revision, 기존 정지 검증 파라미터 |
| `session.d_runtime` | 기존 LIVE 수신 근거: 아래 예시의 필드. B Current를 D가 새 revision으로 발급하지 않음 |
| 연결 config | `interfaces/assembly_contact_trial.json`을 작업용으로 복사해 robot_id/domain/TCP/tool/gripper 주소를 실제 환경과 대조 |

`session.d_runtime`은 기존 실행 검사에 필요한 수신 근거이며 전체 Plan을 사전 검사하는 새 규약이 아니다.

```json
{
  "sample_kind": "LIVE_D_RUNTIME",
  "source_epoch": "실제 D 실행 세대",
  "execution_id": "session과 같은 실행 ID",
  "plan_id": "A Plan ID",
  "step_id": "현재 Step ID",
  "current_revision": 0,
  "profile_id": "D 실제 profile ID",
  "valid_until_unix_s": 0,
  "reassessment_ref": "최신 A 재평가 참조",
  "reassessed_block": {},
  "reassessed_mode": "ROBOT_GRIP",
  "reassessed_assistance_kind": "NONE",
  "current_ref": "B 확정 Current 참조",
  "reservation_ref": "D 예약 참조",
  "start_pose_ref": "현재 RobotState 참조",
  "reservation_confirmed": false,
  "slot_id": "실제 예약 슬롯"
}
```

위 0/빈 객체/false는 작성 위치를 보이기 위한 자리표시자이며 실행값이 아니다. 슬롯 ID/generation/소속 workflow는 기존 예약 계약 그대로 넣는다. `reservation_generation`과 `workflow_generation`을 숫자로 같게 맞추지 않는다.

## Backend에서 호출하는 방법

기존 Backend/HMI는 현재 연결을 유지한다. 새 `RobotProcess`는 명시적으로 생성하는 호출부이며 production 자동 연결은 별도 배선이 필요하다. 같은 컴퓨터의 ROS2/기존 드라이버 환경에서 Robot 프로세스를 시작한다. REAL 생성 자체는 첫 EXECUTE 입력을 받기 전 장치에 연결하지 않는다.

```python
from app.robot_process import RobotProcess
robot = RobotProcess(robot_root, mode="MOCK")
robot.send("EXECUTE", document=current_step_document)
event = robot.receive()
robot.send("STOP")
robot.close()
```

실기 호출은 `mode="REAL", config=실제_config_경로`를 명시한다. Robot 환경의 Python이 다르면 `python=실제_Python_경로`를 전달한다. 이 가이드를 작성하면서 REAL 호출은 실행하지 않았다.

`document`는 `d_profile`, `session`, `start_zone`과 `step`을 받는다. A의 실제 세 메시지를 넘길 경우 `step` 대신 `assessment`, `request`, `motion`, `case_id`를 넣는다. A의 후보 값 `execution_allowed=false`는 유지하고 D가 별도 EXECUTE 요청을 발급한다. 후보가 수신됐다는 이유만으로 EXECUTE를 발급하지 않는다.

A의 현재 generic 이송 경로와 D의 공급→몸통 회피→전달판 경유 경로가 다르면 `A_D_ROUTE_LABELS_DIFFER`로 거절한다. D 프로필에 맞춘 동일 경유점으로 A가 계산하도록 연결한다. 특히 generic 사람 전달판 후보를 검증 없이 D 경로로 바꿔 실행하지 않는다. A 세 메시지를 받는 실행은 픽업 TCP·빈 그리퍼 접근·파지 이송 구간의 경유점/pose를 대조한다. 기존 D 상승→전달판→몸통 회피→공급 경로와 A 후보를 맞춘다. 이 검사는 전체 팔 IK/충돌 검증이 아니다.

| 보내는 명령 | 의미 |
|---|---|
| `EXECUTE` + document | 현재 Step 실행. 이미 실행 중이거나 B 검사 대기이면 다음 Step 거절 |
| `STOP` | 작업 중 즉시 취소 요청 수신. `STOP_ACCEPTED`는 정지 요청 접수이며 `STOP_VERIFIED`가 실제 정지 확인 |
| `STATE` | 현재 진행 상태와 활성 사람 요청 조회 |
| `SIGNAL` + signal | 활성 요청에 연결된 손/도움/완료 신호. 이전 요청·실행·Step·revision·sequence의 신호 거절 |
| `INSPECTION` + result | Backend가 B의 판단을 전달. UNOBSERVABLE이면 Current 변경/다음 집기 없음 |
| `REINSPECT` | UNOBSERVABLE 후 HMI 재검사 요청 |
| `RESUME` + document | 새 실행 session, 동일 Step/프로필, `resume_current_revision`에 최신 B revision 전달. 완료 동작을 반복하지 않고 남은 동작부터 진행 |
| `CLOSE` | 실행 중이면 STOP 후 종료. 정지/force cleanup이 끝나지 않으면 강제로 성공 종료하지 않음 |

`SIGNAL_REQUEST`의 request_id/execution_id/plan_id/step_id/current_revision을 그대로 신호에 붙인다. `sequence`는 새 관측마다 증가시킨다. RECEIVE는 `hand_present`, `receiving_ready`, 다른 요청은 `ready`를 사용한다. 준비 신호에는 실제 확인 근거에 따라 `verified=true`를 제공한다. REAL에서는 `source=SENSOR/HMI`, `observed_monotonic_s`에 같은 PC의 실제 관측 시각을 전달한다. RECEIVE의 손 없음/받을 준비는 SENSOR만 받고 HMI의 단순 입력으로 손이 없다고 처리하지 않는다. FAKE 신호는 REAL에서 거절한다. **기존 Camera의 미검증 candidate를 verified로 바꿔 보내지 않는다.** 실제 제스처 producer/Backend 신호 배선은 연결 시험 대상이다.

HOLD 도움은 pre-contact 도달/정지 후 새 HELP_READY 요청을 받는다. 개방/후퇴 뒤에도 B 확인 전까지 유지 안내를 남기며 B KEEP 이후 해제 안내를 보낸다. 사람 직접 인계는 최신 받을 준비 신호를 다시 받아 개방한다. 개방 명령 직전까지 요청을 유지해 최신 받을 준비 신호를 확인한다. 하강 명령 직전 손이 나타나거나 새 관측이 없으면 파지를 유지하고 보류한다. 실제 손 영역 검사·인계 준비 producer는 별도 장치 검증이 필요하다.

`INSPECTION.result`는 현재 plan_id/step_id/execution_id와 B의 `decision=KEEP/CALL_C/UNOBSERVABLE`을 전달한다. KEEP/CALL_C에는 B `current`를 그대로 포함한다. 이는 Robot 프로세스의 로컬 응답 봉투이며 팀 공통 B schema를 교체한 것이 아니다. Backend가 공통 B 결과를 이 봉투에 연결한다. `conditions_ready=true`인 UNOBSERVABLE에는 1회 자동 재검사를 요청하고, 이후에는 HMI 재검사를 기다린다. CALL_C이면 승인된 수정 설계의 새 Plan을 기다린다. FINAL 판단과 DB/웹 저장은 Backend 책임이다.

## STOP 후 재개 기준

완료된 이동/집기는 checkpoint로 남긴다. 새 session으로 실제 pose/파지/최신 B revision을 확인해 남은 이동 또는 요청부터 계속한다. 이미 전달이 끝난 경우 이동/집기를 반복하지 않고 B 검사를 다시 요청한다. STOP으로 옛 신호와 옛 B 결과를 거절한다.

그리퍼 명령이나 Contact 도중 STOP/응답 손실이 발생한 경우는 명령 결과를 단정할 수 없어 자동 재개하지 않는다. `RECOVERY_REQUIRED` 또는 재개 거절 원인과 실제 상태를 확인한다. 다음 집기나 자동 재시도를 하지 않는다. 새 프로세스로 재시작하면 메모리 checkpoint 복원은 지원하지 않는다.

## 검증 기록

이 문서 하단의 결과는 실제 실행한 검사만 기록한다. MOCK 통과는 실제 Camera/Robot/Isaac/전체 HMI/DB 통합 완료를 뜻하지 않는다. 기존 환경에 별도 lint/type check는 미구성이다.

### 이전 실행 결과 — 추가 통합 변경 전

- Robot 단위/기존 시험: **893 passed**, 실패/오류/skip 0, 종료 코드 0. 기존 831개와 새 62개 포함.
- 별도 프로세스 연결 + 기존 Robot Backend/HMI 관련 회귀: **131 passed**, 실패/오류/skip 0, 종료 코드 0. 연결 검사 3개는 이 수치에 포함한다.
- 최종 수정 후 server 연결 검사 별도 재실행: **3 passed**, 종료 코드 0. 위 131개와 중복이며 합산하지 않는다.
- 별도 프로세스 모의 시나리오 `robot/tray/direct/hand-hold`: **4개 PASS**, 각 종료 코드 0.
- 새 코드와 변경한 runner의 Python 구문 검사: 종료 코드 0.
- 원본 manifest 3,295개 확인: 기존 파일 변경은 `app/assembly_step_runner.py`의 MOCK 재생 파지/개방 폭 보존 수정 1개뿐이다. 원자료/측정 파일 누락 없음.
- 원본 ZIP 보존. commit/push/PR/merge 없음. 기존 Backend/HMI 자동 실행 경로는 변경하지 않음.

미검증/미연결: 실제 로봇·카메라 제스처 producer·A 새 경로→D 실수신·공통 B 응답 매핑·기존 HMI 새 실행 경로 배선·Isaac/IK/전체 팔 충돌·새 블록별 물리 파지/체결. 실측 파일을 채우는 작업과 위 실제 연결 검증을 구분한다.


### 2026-10-11 추가 통합 변경

PRESS_AND_HOLD와 전달판 하강 중 STOP 후 새 수신 관측 요청을 추가했다. A/D 빈 접근 경로 대조와 GRIP_STARTED 표시 이벤트를 연결했고 가짜 최초 RobotState와 MOCK 시작 pose를 일치시켰다. Current/revision은 B 결과에서만 받는다. 최신 검사·한계는 [최종 MVP 실행 안내](D_MVP_INTEGRATION_20261011.md)와 logs/mvp-integration-verification/verification.json을 따른다. 원본 ZIP·실측값과 이전 시험 기록은 보존했다. 새 모의 HMI 연결은 명시적 app.mvp_integration 진입점이며 REAL 자동 연결 완료를 뜻하지 않는다.
