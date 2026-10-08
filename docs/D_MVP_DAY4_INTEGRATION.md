# MVP_Day4 통합 실행과 검증

2026-10-08 사용자 채택 사항을 반영하고 로컬 검증 후 사용자 요청으로 원격 `MVP_Day4`에 게시한 변경이다. 수정 전 기준 커밋 `95259bd03f3cef32ce2807c25851316655cbd7a0`은 원격 `MVP_day4_2`에 보존했다. 작업 위치는 자료 폴더 아래 `work/c2-mvp-day4-integration`의 `MVP_Day4`이며, 기존 `/home/ms-02/C_2` checkout과 작업 브랜치를 전환하거나 수정하지 않았다. GitHub 직접 커밋으로 반영했으며 PR 생성과 main 병합은 수행하지 않았다. 원격 게시를 실제 장치 통합 성공으로 간주하지 않는다.

## 적용한 동작

- 운영 진입점 [real_workflow_hmi.py](../app/real_workflow_hmi.py)는 초기 STT → C 함수 → 실제 A Plan 검증 → D Backend를 사용한다. `--c-fixture`, `--c-mode offline`, 수동 Camera 확인 JSON 입력을 운영에서 받지 않는다. 저장된 예시와 수동 확인 harness는 회귀 검사를 위해 [tests](../tests/integration/workflow_support.py)에만 남겼다. 다른 FAKE/단일 장치 시험 진입점은 기존 독립 시험용이다.
- 새 START는 사용자가 **조립판을 비웠음을 확인**한 입력이다. IDLE/COMPLETE이고 Robot이 준비된 경우 새 Job·빈 Current를 생성한다. 실행 중 새 START는 거절한다. 이전 Job의 완료 기록/로그는 유지하고, 공급 슬롯 소모는 새 Job에도 유지한다. 시작으로 공급판 보충까지 간주하지 않는다.
- Plan은 필요한 블록 개수와 남은 공급 슬롯 개수를 비교해 거절하지 않는다. Robot은 검증된 열의 1~6번 슬롯을 사용한다. 6번 소비 뒤 해당 열이 필요하면 `NEEDS_REFILL`로 대기하고, 사람이 그 열을 채운 뒤 보충 완료를 입력한다. 해당 열만 1번으로 복귀한다. **보충 입력 자체로 이동하지 않고 새 전달판 EMPTY를 받아야 진행**한다. 자동 재충전·수량 재고 검사는 없다.
- B의 요청 목적을 `PLACE`(전달판), `ASSEMBLY`(이번 Step 조립), `CURRENT`(재계획/의도/정리용 실제 상태 재관측)로 구분했다. 이는 D 연결부의 호출 문맥이며 공통 Observed 여섯 필드를 바꾸지 않는다. 실제 B 생산자 연결은 홍동 담당의 남은 작업이다.
- 음성/API 호출 중 STOP 이후에는 기존 호출이 끝나야 RESUME/새 START가 가능하다. 이전 호출을 강제 종료하거나 녹음/재생을 겹치지 않는다. `AMBIGUOUS_RELOCATION`의 보수적 판단과 Current 보존 정책은 유지한다.
- 전달/사전 이동의 최대 대기 시간을 현장 측정값으로 설정한다. 초과 시 정지를 한 번 요청하고, 실제 정지·이전 실행 종료·블록 상태 증거를 기다린다. 늦은 성공으로 다음 전달하지 않으며 오류 이후 자동 재시도·재개가 없다. STOP/probe 자식의 종료 시간 감시나 하드웨어 비상정지를 대신하는 기능은 아니다. 자동 감지는 코드 추가가 필요하고, 코드 없이 할 수 있는 대응은 사람의 감시·정지 조작이다.

## B 연결 요청: D 쪽 API 구현, 실제 B 연결 미검증

`--vision-module`은 `connect(bridge)`를 제공하는 Python 모듈명이다. 이 모듈에서 `bridge.bind(handler)`를 한 번 호출한다. handler는 아래 요청을 받아 촬영을 비동기로 예약하고 빨리 반환해야 한다. B 내부 알고리즘/Camera 시작 방식은 이번에 대신 구현하지 않았다. 이 Python 연결 API는 D에서 구현한 연결안이며, 홍동 코드에 실제로 반영됐다는 뜻은 아니다.

| 요청 필드 | 의미 |
|---|---|
| check_id | D가 발급. B는 촬영 시작 시 고정하며 완료 시점의 새 요청으로 바꾸지 않음 |
| after | ASSEMBLY의 목표 블록 여섯 필드. PLACE/CURRENT는 null |
| purpose | PLACE / ASSEMBLY / CURRENT. after=null만으로 전달판 요청이라고 추정하지 않음 |

B worker에서 다음 함수를 호출하면 Qt 대기열을 통해 D 상태를 변경한다. D 함수를 B worker에서 직접 호출하지 않는다.

- `bridge.submit_observation(observed)`: `check_id, observation_seq, status, visible_blocks, verified_regions, reason`의 공통 Observed. OK는 목표 일치가 아니라 관측 가능이라는 뜻이다. 확인한 빈 영역도 verified_regions에 포함하고, 가려진 아래층을 임의로 빈 상태로 만들지 않는다.
- `bridge.submit_place(value)`: `check_id, observation_seq, status, reason`. status는 EMPTY/OCCUPIED/UNOBSERVABLE, 정상 reason은 null, UNOBSERVABLE에는 사유를 준다. B의 기존 전달판 진단 결과를 이 callback에 연결해야 한다.
- `bridge.submit_failure(check_id, reason)`: 해당 요청의 실제 실패. 미수신/실패를 EMPTY나 정상 빈 Observed로 바꾸지 않는다.

ASSEMBLY 요청에서는 조립 Observed와 전달판 결과를 모두 같은 check_id로 반환한다. 각각의 순번은 해당 결과 채널에서 증가시킨다. 중복/역순/닫힌 check는 D가 진행 근거로 사용하지 않는다. CURRENT에는 조립판의 실제 관측을 반환하며 전달판 EMPTY로 대신하지 않는다. 확인 범위가 부족하면 Current를 유지하고 완료/다음 전달을 보류한다.

## 경로와 실행 환경

[Robot 설정](../interfaces/robot_trial_blue5.json)과 [네 공급열 manifest](../interfaces/robot_voice_workflow.json)의 파일 참조는 **그 JSON 파일의 위치**를 기준으로 해석한다. 로그와 자식 프로세스용 채택 설정에는 해석된 절대 경로를 기록한다. 사용자별 원본 폴더를 요구하지 않는다.

검증된 [Robot 원본](../robot_cycles/yellow4_row_to_place.py)과 [공급열 측정 파일](../supply_board_map/supply_pick_lines_provisional.json)을 내용 그대로 저장소 안에 복사했다. SHA-256은 각각 `01d874432e4ed7d635c8728b73e22b47f06964f69a83872976fd855d1df2fe99`, `b8606bae5e0fe897beea097c653906f4d6d1b4b915fe98a6da4a7ec64d73a11c`다. pose/TCP/속도/힘/측정값은 변경하지 않았다. 저장소 위치를 옮긴 파일 복사본에서 경로·hash와 무이동 계획 생성을 검증한다.

저장소만으로 **소스 파일을 찾을 수 있게** 한 변경이다. 다른 PC에서 하드웨어 환경까지 자동 구성되는 것은 아니다. Python/PyQt5, 음성용 numpy·sounddevice/PortAudio, 기존 Robot 원본의 scipy·pymodbus, ROS2/rclpy·dsr_msgs2·장치 드라이버, 마이크/스피커·Camera 보정·Robot TCP/tool/IP가 필요하다. 이 작업에서 설치·장치 재보정·저수준 값 변경을 수행하지 않았다. API key는 환경으로 주입하고 저장소에 넣지 않는다. 상대 경로를 쓴 설정 파일 하나만 다른 폴더로 복사하면 참조 기준도 바뀌므로 폴더 구조를 유지하거나 경로를 명시적으로 바꿔야 한다.

## 실행

아래는 실제 장치 연결용 명령이다. B 모듈과 현장에서 측정한 시간 한도를 먼저 준비한다. 고정 임의 시간값은 제공하지 않는다. 시작 직후 Robot 무이동 준비 조회를 수행한다. PREPARE_OBSERVE/START 이후에는 실제 장치를 움직일 수 있다.

```bash
# 저장소 루트, 기존 ROS/Robot 실행 환경을 준비한 데스크톱 터미널
export C_DESIGN_USE_LLM=1
# OPENAI_API_KEY와 OPENAI_TTS_API_KEY를 이 터미널에 주입
# B_DAY4_MODULE: 실제 connect(bridge)를 제공하는 B 모듈명
# DAY4_ROBOT_TIMEOUT_SECONDS: 현장 측정으로 정한 양의 초 단위 한도
python3 -m app.real_workflow_hmi --real-workflow \
  --supply-manifest interfaces/robot_voice_workflow.json \
  --vision-module "$B_DAY4_MODULE" \
  --robot-timeout-seconds "$DAY4_ROBOT_TIMEOUT_SECONDS" \
  --log-dir logs/day4_integration
```

B 모듈 미제공/미연결 또는 API 환경 누락이면 운영을 시작하지 않는다. 저장 Fixture나 수동 확인으로 자동 대체하지 않는다. 실행 중 실제 장치가 오류를 내면 현장 상태를 확인하고 정리한다. 자동 복구는 Day4 범위 밖이다.

## DB 없는 Day4

확인한 이 브랜치의 [C 함수](../app/c_design/main.py), [C 연결부](../app/c_text_connection.py), [계획 연결](../app/planning_connection.py)에는 DB 연결/조회/저장이 공정 선행 조건으로 들어 있지 않다. C는 전달된 text/Design/Current/Difference를 사용한다. PostgreSQL 이력은 [별도 적재 app](D_DB_HISTORY.md)이 JSONL을 읽는 기능이다. Day4에는 DB를 새로 연결하지 않는다. DB를 실행하지 않으면 PostgreSQL 적재만 수행하지 않으며 Job별 JSONL 기록은 유지된다. 확인하지 않은 담당자의 새 코드에는 이 결론을 자동 적용하지 않는다.

DB 의존 코드가 나중에 들어오면 구분한다. 저장만 선택적으로 수행하고 실패를 분리하면 공정은 진행할 수 있다. DB 조회 결과로 Design을 만들거나 초기화/저장 성공을 함수 반환 조건으로 삼으면 공정도 막히므로 Day4에서는 그 의존을 제거해야 한다.

## 검증과 남은 확인

실제 결과는 [STATUS](STATUS.md)의 2026-10-08 항목을 따른다. [운영 연결 검사](../tests/integration/test_day4_connected_workflow.py)는 실제 C/A/D 로직을 사용하되 HTTP·녹음/재생·B 결과 생산·Robot 자식은 Mock/Fixture다. 15 Step 조립 확인, 같은 열 두 차례 보충, 새 Job, 1 Step Job의 연속 슬롯 사용, 오래된 결과 무시, Current 재관측 구분, 잘못된 결과 보류, 실행 시간 초과 정지 요청, 저장소 위치 이동을 확인한다.

실제 Camera 생산, STT/LLM/TTS 서비스, Robot 이동/STOP/probe/시간 한도 적정성, 전체 장치 통합과 사람 리뷰는 미검증이다. 모든 센서 결과가 제대로 들어오는지부터 현장에서 확인하고 한 블록→종류별 전달→작은 전체 목표 순으로 범위를 늘린다.
