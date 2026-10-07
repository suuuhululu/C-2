# 수현 Backend·HMI 실행과 Robot 개발 계획

> 2026-10-07 적용: 현재 제품 목표는 [최종 MVP](10_FINAL_MVP.md)입니다. 아래 명령과 REAL 버튼은 **기존 공급판→place board 전달 공정**용입니다. 문서 변경으로 assembly board 직접 결착·지지·접촉 실행 명령이 되지 않습니다. 최종 실행에는 새로운 좌표/경로·제어 인계·지원/최종 Vision 계약과 실측이 필요합니다. 기존 현장 준비·정지 조건을 임의로 바꾸지 않습니다.

갱신: 2026-10-06. 최신 REAL 실행·단축 입력·STOP/재개·질문 TTS는 문서 마지막의 「REAL 정지·재개와 오배치 질문 TTS」를 우선한다. 앞 절은 단계별 개발 기록이다. 현재 Backend는 Python 객체이고 HMI와 **같은 프로세스**에서 실행한다. 독립 서버/웹 API는 아직 없다. FAKE 전체 시나리오·수동 입력 창과 REAL 한 블록 시험 창을 구분한다.

## 실행 전 확인

저장소 작업 위치는 `/home/ms-02/C_2`, 지정 로컬 브랜치는 `work/suhyun-hmi-backend-robot-db`다. 다른 브랜치로 전환하지 않는다. Python 3를 사용한다. 현재 확인 환경은 Python 3.12.3, PyQt5 5.15.10, Qt 5.15.13이다. 검사는 pytest/jsonschema/referencing을 사용한다. 자동 설치 스크립트·dependency 고정 파일은 이번 개발에서 추가하지 않았다.

```bash
cd /home/ms-02/C_2
git branch --show-current
python3 -c "import sys; from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR; print(sys.version); print('PyQt', PYQT_VERSION_STR, 'Qt', QT_VERSION_STR)"
```

## HMI와 Backend 함께 실행

화면을 볼 수 있는 Ubuntu 데스크톱 터미널에서 실행한다.

```bash
cd /home/ms-02/C_2
python3 -m app.fake_demo --fake-demo --scenario normal --log-dir /tmp/c2-day4-fake-logs
```

창 오른쪽 위 **시작**을 누르면 고정 3 Step 목표·Fake 전달·Fake 조립 관측이 진행된다. 실제 사람이 블록을 놓지 않아도 모의 관측이 반환된다. 정상 매 Step에 확인 버튼은 없다. 정지는 작업 문맥을 유지하며, 모의 정지 확인 뒤 재개할 수 있다. 창 닫기는 예제 종료다. 종료 후 이어하기는 지원하지 않는다.

| `--scenario` | 확인할 내용 | 화면에서 필요한 입력 |
|---|---|---|
| `normal` | 정상 3 Step·아래층 가림 기록 유지·전체 목표 완료 | 시작 |
| `keep` | 색상 차이 → 원래 목표 유지 → 사람 정리 → 재계획 | 시작, 정리 안내 후 **정리 완료**. 예제에서는 이 입력 뒤 정리된 모의 관측을 반환 |
| `revise` | 색상 차이 → 전체 목표 수정 후보와 Plan 함께 채택 | 시작 |
| `unclear` | 두 모의 불명확 응답 뒤 명시 선택 대기 | 시작, **목표 유지** 또는 **목표 수정**. 유지를 선택하면 정리 안내 뒤 정리 완료 |
| `hri-failure` | 의도 해석 호출 실패·사유 표시·다음 전달 보류 | 시작. 실패를 정상 완료로 표시하지 않음 |

시나리오를 바꾸려면 예제를 종료하고 `--scenario` 값만 바꿔 다시 실행한다. `--fake-demo`는 필수다. 이 예제는 Fake Controller/driver를 사용하고 ROS/실제 Robot driver/Vision/HRI/Planner는 호출하지 않는다. 공급 슬롯과 보충 버튼은 Controller 상태를 표시하며 Qt가 계산하지 않는다.

지정 파일의 데이터를 쓰거나 모의 속도를 조절하려면 다음 옵션을 사용한다.

```bash
cd /home/ms-02/C_2
python3 -m app.fake_demo --fake-demo --scenario normal \
  --robot-config /home/ms-02/C_2/interfaces/fixtures/robot.json \
  --fixture /home/ms-02/C_2/interfaces/fixtures/day4.json \
  --delay-ms 350 --log-dir /tmp/c2-day4-fake-logs
```

Robot 설정은 START마다 검사해 복사하고 활성 Job/STOP·재개에서 고정한다. 변경 파일은 다음 Job에서 사용한다. `--fixture`도 START마다 읽지만 예제는 순서가 맞는 3 Step Fixture 전용이며 범용 Planner/인식기가 아니다. 정상 경로는 파일의 목표/Plan과 그 위치로 만든 모의 관측을 사용한다. HRI 분기는 해당 파일의 색상 불일치 예시를 사용한다. 판 크기/층/지원 작업은 현재 공통 Day4 계약을 유지한다.

Robot 오류 경로는 `--scenario robot-pick-failure`, `robot-return-failure`, `robot-timeout`으로 실행한다. 오류는 HOLD·사유 표시·다음 전달 보류다. STOP 뒤에도 자동 정리/재개하지 않는다. 원격 독립/Qt 검사에서 `driver.confirm_cleanup(ready_at_observe=True, gripper_empty=True)`와 `backend.on_robot_cleanup(job_id)`로 별도 준비 증거를 공급하고, 이후 시작 입력으로 새 Job을 만든다. Qt 예제의 시험용 `demo.confirm_robot_cleanup()`가 이 두 입력을 연결한다. GUI START/STOP이 자동 호출하지 않으며 실제 확인 생산자는 5단계에서 연결한다. 새 START는 초기 조립판/전달판 비움·공급판 채움 확인을 뜻한다.

## 시작 후 터미널에서 가짜 키워드·Design·Plan 입력

이 창은 **FAKE 입력 확인 전용**이며 ROS/Robot/LLM/Planner를 호출하지 않는다. 실제 파랑 5번 시험 창과 별도로 실행한다.

```bash
cd /home/ms-02/C_2
python3 -m app.step_input_hmi --fake-inputs
```

HMI **시작**을 누른 뒤, 프로그램이 실행 중인 **동일 터미널**에 아래 JSON을 한 줄씩 붙여넣고 Enter를 누른다. 셸 명령 프롬프트에 붙여넣는 것이 아니다.

```json
{"event":"keyword","text":"탑"}
```

질문/사유 영역에 가짜 키워드 수신이 표시된다. 아직 설계도는 없다. 이어서:

```json
{"event":"design","file":"interfaces/fixtures/day4.json","key":"design"}
```

Design 후보를 검사·저장하며 아직 채택하지 않는다. 키워드로 설계도를 실제 생성하는 것이 아니라 기존 Fixture를 직접 지정한다. 이어서:

```json
{"event":"plan","file":"interfaces/fixtures/day4.json","key":"initial_plan"}
```

유효한 Design/Plan을 함께 채택하고 전체 목표 3개·현재 S01 목표·진행 0/3을 표시한다. 이 Plan은 **사람 조립 순서**이며 Robot 관절/TCP 궤적이 아니다. 첫 전달판 확인 요청까지 출력하고 관측 입력을 기다린다. 자동 가짜 관측·전달·완료는 실행하지 않으며 Current는 revision 0/빈 배치다. 입력 순서 오류·지원하지 않는 데이터·없는 파일·닫힌 요청은 오류를 표시하고 채택하지 않는다. 후보 저장 후 키워드/Design 덮어쓰기도 허용하지 않는다.

Fixture를 수정하려면 `file`에 별도 JSON 경로와 `key`를 지정한다. 공통 계약과 Design/Plan 버전·Current revision·배치 정합성을 그대로 검사한다. 기록은 기본 `logs/step_inputs/<Job UUID>.jsonl`에 남고 `--log-dir`로 바꿀 수 있다. Ctrl+D 또는 창 닫기로 종료한다. 이후 관측/전달까지 자동 Fake 시연하려면 위 `app.fake_demo`를 사용한다.

이 입력 창에서 **정지**를 누르면 장치 없는 모의 정지 확인을 받고 **재개**가 활성화된다. 재개 후 같은 Job과 기존 키워드·Design 후보를 유지하며 빠진 입력부터 계속 넣는다. Plan 채택 전 정지했다면 새로운 Planner 요청 ID에 연결하며 이전 요청은 채택하지 않는다. Plan 채택 후 재개는 새 전달판 관측 대기로 돌아가고 자동 집기/조립 완료를 만들지 않는다. 이 응답은 FAKE 창에만 있으며 실제 정지 증거가 아니다. 수정 전에 실행한 창은 종료하고 같은 명령으로 다시 열어야 적용된다.

## 원격에서 화면 없이 Backend 검증

Qt 없는 Fake Backend/로그/Replan 검사:

```bash
cd /home/ms-02/C_2
python3 -m pytest -q tests/unit/test_backend.py tests/unit/test_snapshot_log.py tests/unit/test_replan.py
```

이번 게시 파일의 전체 검사(화면이 없는 원격 환경):

```bash
cd /home/ms-02/C_2
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/unit/test_contracts.py tests/unit/test_hmi_contracts.py tests/unit/test_current.py tests/unit/test_completion.py tests/unit/test_backend.py tests/unit/test_snapshot_log.py tests/unit/test_replan.py tests/unit/test_qt_hmi.py
```

`offscreen`은 화면 렌더링 검사에 사용한다. 사용자에게 창을 보여주지 않는다. 원격 터미널에서 HMI를 눈으로 확인하려면 Ubuntu 그래픽 세션/원격 데스크톱이 필요하다. `python3 -m app.backend`는 실행 진입점이 아니다. 별도 Backend 서버가 필요하면 후속 연결 단계에서 범위를 정한다.

## JSONL 확인

예제 기본 위치는 `/tmp/c2-day4-fake-logs`이며 `--log-dir`로 지정할 수 있다. Job UUID마다 JSONL 하나가 생성되고 주요 요청·관측 채택·확인·질문·STOP·완료·사유를 한 줄씩 기록한다. 반복 실행의 이전 로그도 보존된다.

```bash
cd /home/ms-02/C_2
python3 - <<'PY'
import json
from pathlib import Path
for path in sorted(Path('/tmp/c2-day4-fake-logs').glob('*.jsonl')):
    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    print(path.name, len(events), 'events')
    for event in events[-5:]:
        print(event['event'], event.get('reason'))
PY
```

`/tmp`는 임시 보관 위치다. 시험 기록을 보존할 때는 `--log-dir`에 별도 기록 폴더를 지정한다. 로그를 Current 복원이나 실제 장치 성공 증거로 사용하지 않는다.

## 잘못 놓음 수동 신고·좌표 비교와 마지막 확인 검수 (2026-10-06)

REAL 3-Step 시험의 `assembly`에서 `confirmed:false`를 받도록 확장했다. C 연결 없이도 현장 신고와 기존 Step 목표를 비교할 수 있다. **실제 배치는 B 관측 또는 현장 입력, 원하는 배치는 채택 Design/Step**의 책임이다. C는 목표 자체를 수정할 때 필요하며 이번에 실제 C/HRI를 연결하지 않았다. Robot은 전달만 담당하고 사람이 조립판을 정리한다.

- `confirmed:false`만 보내면 `MANUAL_ASSEMBLY_MISMATCH`에 신고를 남기고 HOLD로 닫는다. 좌표가 없으므로 관측을 만들거나 Current/Step을 변경하지 않는다.
- 같은 신고에 `actual` 여섯 필드를 넣으면 기존 조립이 유지됐고 현재 목표 영역과 입력한 실제 블록을 확인했다는 **수동 시험 관측**으로 받는다. 유효 배치는 기존 Current/Expected/Difference 계산으로 채택한다. 원래 목표를 유지하고 다음 전달을 보류한다. 이전 블록을 이동/교체한 경우나 겹친 배치는 이 간단한 입력으로 표현하지 않으며 실제 Observed 경로가 필요하다.
- HMI에서 **현재 목표 vs 현장 입력** 표, 목표의 채움 vs 현장 입력의 빨간 테두리를 보여준다. reported_placement는 REAL 수동 차이 표시용 선택 필드이며 실제 B 반환에 포함하지 않는다. 화면이 블록의 대응/완료를 추정하지 않는다. 표시한 현재 Step 목표는 수정 참고 위치이며 Robot MOVE 명령이 아니다.

이번 사용자 시험 입력은 `(9,5)`이고 **S03 목표는 파랑 4점 `(7,5)·1층·0°`**다. 새 코드로 실행한 창에서 세 번째 전달·복귀가 끝나면 출력된 **그 시점의 check_id**를 써야 한다. 프로그램은 actual을 포함한 완성된 한 줄 양식도 출력한다. 기본 actual은 목표 복사본이므로 이번에는 x를 7에서 9로 바꿔 **그 신고 한 줄만** 입력한다. 좌표 없는 false를 먼저 보내면 check가 닫히므로 그 뒤 같은 ID로 좌표를 추가할 수 없다. 예시 ID를 그대로 입력하지 않는다.

```json
{"event":"assembly","check_id":"새 창에서 출력된 S03 확인 ID","confirmed":false,"actual":{"brick_type":"2x2x1","color":"blue","x":9,"y":5,"layer":1,"orientation_deg":0}}
```

프로그램은 `MISPLACED_REPORTED`, `source=MANUAL_REPORT`, actual/target, Current revision, confirmed Step 수, `next_delivery=false`를 터미널로 반환한다. 이것은 수동 시험 결과이며 Camera 인식 성공이 아니다. `confirmed:true`는 정상 조립 확인이므로 오류 시험에 사용하지 않는다. 잘못된 Boolean·이전/중복 check·실행 중 입력·범위/겹침/목표와 같은 actual·정상 확인에 actual을 붙이는 입력은 거절한다. 로그 기록 실패에서도 다음 집기를 막는다.

**이미 실행 중인 Python/Qt 창에는 파일 변경이 자동 반영되지 않는다.** 이번 변경은 새 실행부터 적용한다. 에이전트는 사용자의 활성 Robot/창/Job을 종료하거나 재시작하지 않았다. 기존 Job 종료 후 이어하기는 미지원이며, 기존 check_id나 소모 슬롯을 새 Job에 그대로 재사용하지 않는다. 새 실제 시험에는 준비된 연속 3개 공급 슬롯·빈 조립판/전달판·현장 조건을 다시 확인해야 한다. 현재 창에서 새 오류 입력을 받아 같은 Job을 이어가는 기능은 없다.

신고 후 정리 확인/새 관측/재개, 목표 수정 의도/새 Design·Plan 채택은 이번 단위에서 연결하지 않았다. 신고 check를 닫고 진행을 막으므로 정리한 뒤 같은 ID에 true를 보내도 재개하지 않는다. 자동 KEEP·자동 Robot 복구·재배치는 없다.

검수: 신규 오류/표시/최종 확인 검사 20개, 관련 파일 38개 및 최종 전체 **745 passed**, 종료 코드 0. 세 번째 전달만 성공했을 때 **WAIT_ASSEMBLY·2/3·Current 유지·JOB_COMPLETED 없음**, 오류 입력 뒤 **HOLD·2/3·actual (9,5)/target (7,5)·완료 없음**, 정상 마지막 확인 뒤에만 **COMPLETE·3/3**을 확인했다. 실제 A와 모의 QProcess/Qt·수동 데이터 검사이며 Robot/ROS/Camera 동작 없음. [확인 전 화면](/tmp/c2-s03-before-confirmation.png), [오류 비교 화면](/tmp/c2-s03-misplaced-preview.png), 실행 기록 `/tmp/c2-s03-misplaced-65t4o8vb/result.json` 및 같은 폴더의 Job/모의 driver 로그를 보존했다.

## REAL 3 Step: 가짜 C → 실제 A → Backend/HMI → 현장 수동 확인 (2026-10-06)

사용자 선택은 **3개 블록을 한 번 조립, 총 3회 전달**이며 공급 슬롯을 모두 채웠다고 확인했다. 색상/슬롯은 임의 선택을 허용했지만 재현을 위해 이번 Fixture는 **파랑 4점 1→2→3번**으로 고정했다. 목표는 24×24 조립판의 `(3,5)`, `(5,5)`, `(7,5)`, 모두 1층·0°다. C는 [3개 블록 Fixture](../interfaces/fixtures/c_three_blue4.json), 사람 조립 Plan은 세은의 실제 A 함수가 계산한다. Robot은 기존 경로로 고정 전달판에 놓는다. A의 Plan은 사람 조립 순서이며 Robot TCP 궤적이 아니다.

홍동 Camera는 미연결이므로 **운영자가 현장에서 확인하고 같은 실행 터미널에 JSON을 입력하는 시험**이다. 로봇 전달 성공만으로 조립 완료/Current를 갱신하지 않는다. 수동 확인으로 만든 시험 Observed와 Camera 관측을 구분하며, 화면/JSONL에 수동 확인 출처를 남긴다. 기존 조립 유지·현재 목표 일치·빈 전달판·손/장애물 여유를 모두 확인한 경우만 정상 확인한다. 실제 차이/불확실이 있으면 `confirmed=true`를 보내지 않는다. 잘못 놓음 수동 신고/좌표 비교는 위 절을 따른다. 정리 후 재개/자동 복구 경로는 제공하지 않는다.

기존 단일 전달 창의 전달/복귀가 끝난 뒤 닫고 아래 명령을 새 터미널에서 실행한다. 조립판·전달판은 비우고 **파랑 4점 1·2·3번**을 준비한다. TCP/tool·배치·observe 복귀 조건 및 현장 감시/비상정지 대응을 확인한다. 파랑 5번 성공을 1·2·3번 경로 충돌/집기 검증으로 확대하지 않는다.

```bash
source /home/ms-02/cobot2_ws/install/setup.bash
cd /home/ms-02/C_2
python3 -m app.real_workflow_hmi --real-workflow \
  --config interfaces/robot_trial_blue5.json \
  --c-fixture interfaces/fixtures/c_three_blue4.json \
  --color blue --first-slot 1
```

설정 파일 이름의 `blue5`는 기존 파랑 공급열 설정의 이름이다. 이번 실행 슬롯은 `--first-slot 1`과 Controller의 연속 슬롯 선택으로 **1·2·3번**을 사용한다. 원본 JSON·측정값·제어 파일·observe/TCP/tool/속도/궤적은 변경하지 않았다. 변경 설정은 시작 조회와 대조해 고정하며, 도중 변경은 다음 전달을 막는다. 다른 색상/설계를 시험하려면 지정 공급열과 일치하는 3개 블록 C Fixture와 해당 실제 경로 설정이 함께 필요하다.

| 순서 | 사용자가 하는 일 | 화면/Robot 결과 |
|---|---|---|
| 1 | 창 열기 | 현재 observe 상태/경로/ROS 메시지 조회. 이동·그리퍼 개폐 없음 |
| 2 | 조회 성공 뒤 `준비 확인 · Job 시작` 클릭 | 가짜 C와 실제 A 채택. 전체 Design·현재 S01·0/3 표시. 아직 전달 없음 |
| 3 | 터미널이 출력한 최신 `place_empty` JSON을 같은 터미널에 입력 | **첫 실제 집기·전달·observe 복귀** 시작 |
| 4 | 복귀 뒤 전달 블록을 S01 목표에 조립. 기존 조립 유지·현재 목표 일치·전달판 비움·손을 뺀 상태 확인 후 최신 `assembly` JSON 입력 | Current revision 1·조립 1/3. **두 번째 실제 전달** 시작 |
| 5 | 같은 방법으로 S02를 조립하고 새 `assembly` 입력 | Current revision 2·조립 2/3. **세 번째 실제 전달** 시작 |
| 6 | S03를 조립하고 마지막 새 `assembly` 입력 | 누적 Current와 채택 Design 대조, 수동 조립 확인 3/3·COMPLETE. 추가 전달 없음 |

다음 형태의 **완성된 JSON 한 줄이 프로그램 터미널에 매번 출력**된다. 해당 줄을 복사해 붙여넣는다. 아래 `현재 출력된 ID`는 예시 자리표시자이므로 그대로 쓰지 않는다. 별도 쉘에서 JSON을 실행하는 명령이 아니다.

```json
{"event":"place_empty","check_id":"현재 출력된 ID","confirmed":true}
{"event":"assembly","check_id":"현재 출력된 새 ID","confirmed":true}
```

**첫/두 번째 `assembly` 입력은 다음 실제 이동을 시작한다.** Robot이 observe point에 돌아와 멈춘 후에만 조립·확인하며 움직임 중 손을 넣지 않는다. 닫힌/이전 check, 중복 입력, 실행 중 입력은 거절한다. 마지막 입력은 조립 확인만 기록한다. 수동 확인은 누적 기존 조립도 그대로 유지했다는 뜻이며 카메라가 목표를 읽었다는 뜻이 아니다. 정상 매 Step 확인 버튼은 HMI에 추가하지 않았다.

이 절의 초기 시험 이후 STOP/재개 연결을 추가했다. 현재 동작은 아래 「REAL 정지·재개와 오배치 질문 TTS」를 따른다. 긴급 정지는 현장 비상정지를 사용한다. 실패·증거 누락·프로세스 비정상 종료·설정/로그 오류는 HOLD와 추가 집기 차단이다. 해당 창에서 자동 재시도·복구·재개·두 번째 Job·슬롯 보충을 하지 않는다. 동작 중 창 닫기는 차단한다. 정상 종료는 최종 확인 후 창을 닫거나 Ctrl+D다. 종료 후 이어하기는 없다.

Backend 주요 이벤트는 `logs/real_workflow/backend/<Job UUID>.jsonl`, 실제 실행 기록은 `logs/real_workflow/<세션 UUID>/driver/<실행 UUID>.jsonl`이다. `MANUAL_FIELD_CONFIRMATION`을 Camera 결과와 구분해 읽는다. 시험마다 슬롯을 자동으로 재충전하지 않으므로 새 실행은 현장에서 준비된 슬롯을 다시 확인해야 한다.

최종 검사: 신규 실제 A/D/Qt + **모의 QProcess** 통합 18개, 현재 전체 725개 통과. 실제 `main`/stdin/Qt 입력으로 1→2→3·revision 3·3/3도 모의 확인했다. `/tmp/c2-real-three-main-smoke/result.json`, [S01 화면](/tmp/c2-real-three-step-preview.png). Robot/ROS/Camera를 호출하지 않은 검사이며 이번 3회 실제 장치 성공은 아직 미검증이다. 다음은 위 명령으로 현장 정상 시험을 기록하고, 이후 홍동의 실제 촬영/Observed/전달판 판별을 수동 입력 대신 한 모듈씩 연결하는 것이다.

## 오늘 Robot 개발을 시작할 단계

아래는 **설계/개발 계획**이다. 2026-10-06 사용자 승인으로 Robot 0~4단계를 진행했다. 상세 결과는 [Robot 설계와 현재 구현](D_ROBOT_CONTROLLER_DESIGN.md)에 있다. 5단계 이후 구현과 실제 장치 실행 지시로 확대하지 않는다. 단계마다 결과·실제 검사·미검증을 보고한 뒤 다음 단계 승인을 받는다. 0~4는 원격 작업, 5는 실제 연결 준비, 6~7은 별도 장치 실행 지시 이후다.

| 단계 | 목표·최소 수정 범위 | 입력 → 출력 | 검증/승인 기준 |
|---|---|---|---|
| 0. 기존 제어·계약 점검 | 기존 노랑 4점 코드/실행 기록과 최신 계약을 읽고 재사용 가능·미검증 목록 작성. 제어 코드 수정/실행 없음 | 검증 기록·driver API → 실제/미확인 설정표·확인 과제 | 정상 전달/실제 집기 증거/STOP 증거/observe point/나머지 세 조합을 구분. 1단계 전 설계 검토 |
| 1. Controller 최소 경계 설계 | 기존 Backend goal/result를 유지하고 단일 실행·정지/재개 연결·상태 보고 의미를 문서화. ROS 이름/메서드는 driver 확인 후 고정 | goal 3필드·stop/resume 요청 → 결과 3필드·준비/정지 확인 | 중복·실패·블록 상태 불명확의 반환/보류 의미 합의. Backend/Qt에 슬롯 계산을 넘기지 않음 |
| 2. Fake driver 정상 전달·슬롯 | 승인된 작은 Controller와 Fake driver 검사만 구현. 실제 pose 없음 | 종류/색상·실행 ID·집기/놓기/복귀 이벤트 → 슬롯·단일 최종 결과 | 한 실행만 허용, 중복 요청 집기 없음, 실제 집기 성공 확인에만 1회 슬롯 소모, observe point 복귀/정지까지 성공, 6번 이후 해당 공급열 보충 대기 |
| 3. Fake 실패·STOP/재개 | 실패/지연/중복 및 세 상황의 재개를 같은 Controller에서 구현·검사 | 정지·이전 실행 종료·블록 상태 증거 → 새 ID 재개/보류 | 미집기면 같은 슬롯 새 Goal, 들고 있으면 추가 집기 없이 전달/복귀, 놓았으면 복귀만. 소모/Current/완료 초기화 없음, 불명확 상태와 timeout은 자동 재시도 없음 |
| 4. Backend·로그·HMI Fake 연결 | 기존 robot.deliver/stop/resume을 Fake Controller에 연결. 필요한 snapshot 운영 상태만 Controller에서 제공 | Backend 명령·Controller callback → 화면/로그·다음 전달 유무 | 정상 3 Step·보충·실패·STOP 시점별 재개·옛 결과 검사. 전달 성공은 조립 완료 아님. 현재 실행 이후의 EMPTY와 새 관측 없이 다음 전달 없음 |
| 5. 실제 driver adapter 준비 | 기존 검증 제어를 한 블록 단위로 연결할 최소 adapter와 설정 표를 검토. 장치를 움직이는 시험 없음 | 확인된 ROS/그리퍼 API·검증 설정 → Real 연결 후보·시험 절차 | TCP/tool/pose/속도/궤적/observe point/집기 감지/정지 확인을 임의 생성하지 않음. 긴 이동 중 STOP 처리 확인 방법·미검증 조합을 명시 |
| 6. 실제 한 블록 전달 | 관련 독립/인접 검사 후 현장에서 별도 승인된 한 블록 시험 | 현장 안전/설정 확인·명시 실행 지시 → 실제 전달/집기/복귀 기록 | Robot Owner와 다른 사람 리뷰, 실제 정지와 observe point 확인. 노랑 4점부터 승인된 슬롯만 시험. 나머지 조합은 각각 별도 확인 |
| 7. 실제 STOP/재개·촬영 연결 | 승인된 안전 절차로 세 상황의 정지/재개와 홍동 촬영을 연결 | 실제 Robot 상태·홍동 촬영/전달판 결과 → 재개·조립 확인 | 실제 정지/이전 실행 종료/블록 상태 확인, 중복 집기·이중 슬롯 소모 없음. 사람 조립 후 실제 Observed로만 완료. 실제 결과·설정·로그·미검증 기록 |

## 0단계에서 이미 확인한 근거와 필요한 현장 확인

자료 폴더의 `robot_cycles/yellow4_row_to_place.py`와 `yellow4_row_success_2026-10-04.json`은 노랑 4점의 기존 제어/실행 근거다. 기록은 2~6번 자동 전달과 사용자의 최종 HOME 복귀 확인이며 1번은 이전 수동 전달이다. 전체 1~6번 자동 시험, 나머지 세 조합, 조립 장애물 여유, Action/실제 STOP·재개 성공으로 확대하지 않는다. HOME과 계약의 observe point가 같은 위치라고 가정하지 않는다.

기존 코드는 동기 대기와 전달판 정리 후 Enter 입력을 사용한다. 이것을 그대로 Qt 호출에 붙이면 응답/STOP 처리가 막힐 수 있고, 정상 매 Step 확인 버튼을 없앤 새 계약과도 연결 검토가 필요하다. 기존 경로/설정은 보존한다. 스크립트의 장애물 높이 기본 가정도 새로운 실제 안전 확인값으로 사용하지 않는다.

Controller에 필요한 제공물은 기존 driver의 실제 반환/집기 감지/정지 확인 방법과 검증된 네 공급열 설정이다. 확정 계약의 필드를 다시 작성하라는 요청이 아니다. 홍동에게는 observe point 시야·실제 촬영 시점·전달판 EMPTY 판별의 연결 가능 여부를 확인한다. 관측 제안은 홍동이 수정할 수 있게 유지한다.

0·1단계 점검/설계와 2~4단계 Fake 연결에 이어 **5단계 한 블록 시험 실행부/조회**를 검사했다. 사용자 6단계 첫 실행은 HOME 요청의 ROS float64 변환에서 abort됐다. 타입 정규화와 메시지 검사 보완 후 재실행 대기다. 7단계 실제 STOP/재개·촬영 연결은 아직 승인/수행하지 않았다.

사용자 추가 요구에 따라 observe point·공급/전달 위치·동작 값·팀 연결 이름/주소·이후 지원 범위는 [Controller 설계의 변경 가능한 설정](D_ROBOT_CONTROLLER_DESIGN.md#변경-가능한-설정의-경계)으로 분리한다. `load_robot_config(path)`와 Qt의 `--robot-config`가 지정 JSON을 검사해 읽는다. 활성 Job에는 시작 때 검증한 설정을 유지하고 변경 값은 검사 후 다음 Job에 적용한다. Day4 이후 새 동작은 설정 변경과 함께 실제 기능/공통 계약/검사를 구현해야 한다.

## Robot 2~4단계: 원격 독립 검사와 사용 예

```bash
cd /home/ms-02/C_2
python3 -m pytest -q tests/unit/test_robot_controller.py tests/unit/test_robot_backend.py
```

위 검사는 Qt/ROS/장치 없이 Controller와 Backend/로그 연결을 확인한다. 실제 수치는 [STATUS](STATUS.md)에 기록한다. 아래 예는 지정한 [Robot Fixture](../interfaces/fixtures/robot.json)를 읽어 한 블록의 집기/놓기/복귀 성공을 명시적으로 모의 확인한다. 실제 좌표·장치 통신은 없다. 다른 검증된 Fake 설정 파일을 쓰려면 `config_path`를 변경한다.

```bash
cd /home/ms-02/C_2
python3 - <<'PY'
from app.fake_robot_driver import FakeRobotDriver
from app.robot_controller import RobotController, load_robot_config

config_path = '/home/ms-02/C_2/interfaces/fixtures/robot.json'
driver = FakeRobotDriver(ready_at_observe=True)  # 모의 준비 확인
results = []
controller = RobotController(load_robot_config(config_path), driver, results.append)
print(controller.deliver(dict(execution_id='example-1', brick_type='2x2x1', color='yellow')))
for operation in ('pick', 'place', 'observe'):
    driver.confirm('example-1', operation)
print(results)
print(controller.state['supply'])
PY
```

수락 결과는 `accepted=True, reason=None`, 최종 결과는 `execution_id=example-1, success=True, reason=None`이다. 노랑 4점의 다음 슬롯만 2가 되며 나머지는 1이다. 전달 성공은 사람 조립 완료가 아니다. 전체 로컬 회귀 검사는 `QT_QPA_PLATFORM=offscreen python3 -m pytest -q`로 실행하며 최종 수치는 STATUS에 기록한다. 실제 모듈/안전/전달은 아래 조회와 구분한다.

## Robot 5·6단계: 한 블록 현장 시험

현재 추가한 **HMI 실제 단일 시험**은 파랑 4점 5번이다. 사용자가 바로 실기로 시험하며 검증하겠다고 요청해 자료의 파랑 공급열 측정 끝점과 기존 보간/경유 코드를 연결했다. 무이동 40점 IK/FK·15개 메시지 검사는 통과했으며 실제 파랑 전달은 아직 수행하지 않았다. 노랑 2번은 사용자가 실제 전달/observe 복귀 성공을 확인했다. 상세 [STATUS](STATUS.md).

```bash
source /home/ms-02/cobot2_ws/install/setup.bash
cd /home/ms-02/C_2
python3 -m app.real_trial_hmi --real-trial \
  --config interfaces/robot_trial_blue5.json \
  --brick-type 2x2x1 --color blue --slot 5
```

창을 열면 **조회만** 실행하며 성공 뒤 `준비 확인 · 1회 시작`이 활성화된다. 전달판 비움·파랑 4점 5번 준비·작업 경로의 사람/장애물 여유·현장 비상정지 대응을 확인하고 버튼을 누르면 **실제 한 블록 이동/그리퍼 개폐**를 수행한다. 이 버튼은 해당 준비의 사람 확인 의미다. JSON flag를 별도로 바꿀 필요는 없고 START 때 실행 복사본에 기록한다. 첫 파랑 실기 시험이며 IK/FK 성공은 경로 충돌/집기 성공을 대신하지 않는다.

현재 전달 대상의 블록 그림·종류·색상·공급 슬롯·고정 전달판 목적지를 표시한다. 전체 조립 Design/Plan은 미채택이다. 다른 FAKE 창에 넣은 키워드/Design/Plan은 이 창으로 전달되지 않는다. 조립 좌표·층·방향을 그림용으로 만들어 넣지 않는다. 수정 전부터 실행 중인 창에는 자동 반영되지 않으므로 해당 전달/복귀가 끝난 뒤 종료하고 다시 연다. 새 표시 확인은 창 열기의 조회만으로 가능하며 START를 다시 누를 필요가 없다. 이미 사용한 슬롯을 다음 새 시험 대상으로 자동 재사용하지 않는다.

전달 뒤 `HOLD · 실제 전달/복귀 완료, 조립 미확인`으로 남고 시작을 다시 허용하지 않는다. 슬롯 소모는 실제 상승 후 grip 확인 때만 Controller가 한 번 반영한다. 실제 관측/Design/Plan을 연결하지 않아 미리보기·현재 Step은 미채택/없음, 조립 진행은 0/0이다. 화면을 조립 완료로 바꾸거나 다음 블록을 자동 전달하지 않는다. 종료 후 다음 대상은 별도 시험으로 설정/준비를 확인해야 하며 앱 종료 후 이어하기는 없다.

현재 STOP/재개 연결은 아래 「REAL 정지·재개와 오배치 질문 TTS」를 따른다. 실제 장치 정지·재개 시험은 아직 별도로 필요하다. 현재 시험 중 실제 긴급 정지는 현장 장치를 사용한다. 동작 중 창 닫기로 프로세스를 끊지 않으며 조회 전용 자식은 창을 닫을 때 종료할 수 있다. 일반 Fake HMI 명령은 앞 절의 `app.fake_demo --fake-demo` 그대로다.

로그는 `logs/robot_hmi/backend/<Job UUID>.jsonl`과 `logs/robot_hmi/<세션 UUID>/driver/<실행 UUID>.jsonl`이다. Backend 로그가 해당 실행 ID를 연결한다. 공급열/설정 불일치·조회 실패·기존 요청 중복·프로세스 비정상 종료/유효 결과 없음·집기/복귀 증거 누락은 보류이고 자동 재실행하지 않는다.

[시험 실행부](../app/robot_trial.py)와 [설정](../interfaces/robot_trial.json)은 기존 검증 경로의 노랑 4점 **2번 하나**만 사용한다. 제공한 observe posj/posx·기존 속도/장치 이름은 설정 파일에서 바꿀 수 있다. 변경 뒤 현장 경로/TCP/tool 검증과 무이동 검사를 다시 해야 한다. JSON의 확인 flag는 해당 시험의 사용자 확인 기록이며 이후 현장 조건을 자동 보증하지 않는다. 입력 없이 HOME/새 좌표로 대신하지 않는다.

```bash
cd /home/ms-02/C_2
python3 -m app.robot_trial --config interfaces/robot_trial.json
```

위 명령은 계획 출력만 하며 장치에 연결하지 않는다. 다음은 **실제 장치 조회만** 수행하고 이동/개폐를 보내지 않는다. 이미 설치된 ROS workspace 환경을 먼저 읽는다.

```bash
source /home/ms-02/cobot2_ws/install/setup.bash
cd /home/ms-02/C_2
python3 -m app.robot_trial --config interfaces/robot_trial.json --check
```

조회 성공 시 `이동 요청 15개 ROS 메시지 변환 검사 완료. 송신 없음.`과 `조회 완료`를 확인한다. 기존 조회는 이동 메시지를 직렬화하지 않아 JSON int의 C 변환 오류를 놓쳤으며 현재는 이 검사를 포함한다. 설정의 정수/실수 표기 때문에 속도/pose를 수동 수정할 필요가 없다.

실제 한 블록 실행은 같은 명령의 `--check`를 `--execute`로 바꾼다. 이 옵션은 **Robot 이동과 RG2 개폐를 실행**한다. 현장 감시/비상정지·동일 배치/TCP/tool·빈 전달판/2번 블록·검증된 복귀 경로 확인이 모두 필요하다. 사용자가 `empty_place_and_slot=true`로 현장 확인을 저장했다. flag는 이후 시험의 실제 상태를 자동 보증하지 않으므로 재실행 직전 다시 확인한다. 자동 다음 전달/자동 재시도/오류 후 재개는 없다.

독립 시험 로그는 기본 `logs/robot_trials/<시험 UUID>.jsonl`, 경로 변경은 `--log-dir`다. 집기 후 상승/유지, 놓기, HOME→observe 복귀/대기, 최종 3필드 result를 기록한다. 이 결과는 조립 완료가 아니다. 실제 블록이 전달판에 정상 놓였는지는 현장 결과로 추가 확인한다. 초기 37점 IK/FK 조회 로그는 `/tmp/c2-robot-stage5-check-logs/`이며 전달 성공 로그로 사용하지 않는다.

Fake HMI의 `app.fake_demo --fake-demo`는 여전히 장치를 움직이지 않는다. 위의 `app.real_trial_hmi --real-trial`은 별도 실제 단일 전달 연결이며 준비 확인/START가 한 블록을 움직인다. 전체 Day4 REAL Controller, 진행 중 HMI STOP과 STOP 세 증거/재개, 홍동 촬영/EMPTY 연결은 후속 작업이다. 단일 CLI의 기존 실패 시 stop 요청을 실제 정지 검증으로 표시하지 않는다.

## 2026-10-06 — 음성 C 의자 Design과 네 공급열 REAL 시험 준비

사용자가 노랑/파랑 6점열도 기존 전달·HOME·observe 경로로 실기 검증했다고 확인했다. 원자료의 provisional 표시를 변경하거나 에이전트의 장치 통과로 기록하지 않는다. 기존 공급열 측정 끝점과 제어 파일을 재사용한다. 기존 단일 전달/한 열 3회 명령은 유지한다.

- `app/real_design_controller.py`: 네 열의 설정·시작 슬롯을 읽고 기존 RealTrialController의 프로세스/집기·놓기·복귀 증거 처리를 재사용한다. 종류·색상별 슬롯은 실제 집기 증거에만 한 번 소모된다. 실행 ID 중복·진행 중 새 요청·다른 Plan 대상·설정 변경은 거절한다.
- `app/real_workflow_hmi.py`: 기존 CTextConnection의 초기 STT/설계 함수와 실제 A `plan_from_current(design, current)`를 연결한다. 전체 Plan을 첫 이동 전에 검사하고 C Design/A 결과/Robot 수락 여부를 `REAL_PLAN_PREFLIGHT`로 기록한다. 저장 Plan 주입·합성 관측·가짜 전달판 EMPTY는 사용하지 않는다.
- `app/robot_trial.py`: 기존 설정 검증을 재사용하며 기록된 6점 공급열 끝점도 선택한다. pose·TCP/tool·속도·이송/복귀 경로와 원본 제어 파일은 변경하지 않는다. 각 실제 실행은 기존 무이동 상태·IK/FK·메시지 검사를 먼저 수행한다.
- `app/hmi_contracts.py`, `interfaces/schemas/hmi.schema.json`: 명시적 수동 REAL 시험의 진행 표시를 0~24 Step(4열×6슬롯)로 맞춘다. 필드·Current/Expected·완료 판단·버튼 정책은 유지한다. `app/snapshot.py`의 완료 안내는 고정 3회 대신 실제 완료 횟수를 표시한다.
- `interfaces/robot_voice_workflow.json`: 기존 기준 설정과 측정 파일/hash·네 열의 시작 슬롯을 지정한다. 현재 시작 슬롯은 모두 **1**이다. 이미 사용한 슬롯을 채우거나 실행 전에 `first_slot`을 실제 준비 상태에 맞춰 설정한다. 실행 중 설정 변경·자동 보충·앱 종료 후 복원은 없다. Plan이 남은 슬롯 범위를 넘으면 첫 전달 전 `REAL_PLAN_NEEDS_REFILL`로 보류한다. 실제 재고 수량 검사는 아니다.

이 절은 초기 음성 연결 기록이다. 현재는 아래 「REAL 정지·재개와 오배치 질문 TTS」까지 확장해 오배치 의도·재계획과 STOP/재개를 연결했다. `--c-voice`는 이제 `OPENAI_TTS_API_KEY`도 요구한다. Camera/B 생산 연결과 실제 장치·음성 시험은 별도로 확인한다.

기존과 같은 배치·TCP/tool·경로 및 현장 감시/비상정지 조건을 확인한다. 로봇은 검증된 observe 위치에서 시작해야 하며 창 열기의 조회는 그 위치를 대신 만들어 주지 않는다. 네 공급열의 지정 슬롯부터 블록을 준비하고 조립판·전달판을 비운다. START는 준비 상태의 사람 확인 입력이다.

키가 설정된 사용자 터미널에서 실행한다. 키 값은 명령 기록/채팅/JSONL에 넣지 않는다. `OPENAI_API_KEY`가 없으면 먼저 `read -rsp "OpenAI API key: " OPENAI_API_KEY`로 입력하고 줄바꿈 후 `export OPENAI_API_KEY`를 실행한다.

```bash
source /home/ms-02/cobot2_ws/install/setup.bash
cd /home/ms-02/C_2
export OPENAI_API_KEY
export C_DESIGN_USE_LLM=1
export OPENAI_MODEL=gpt-4o
export OPENAI_STT_MODEL=whisper-1
export OPENAI_TTS_API_KEY
export OPENAI_TTS_MODEL=tts-1
export OPENAI_TTS_VOICE=alloy

env -u QT_QPA_PLATFORM python3 -m app.real_workflow_hmi \
  --real-workflow \
  --config interfaces/robot_trial_blue5.json \
  --supply-manifest interfaces/robot_voice_workflow.json \
  --c-mode live --c-voice \
  --log-dir logs/c_voice_real
```

창 열기는 장치 조회만 수행하고 이동/그리퍼 개폐를 보내지 않는다. 조회 성공 후 **준비 확인 · Job 시작**을 누르고 “의자 만들어줘”라고 말한다. C의 전체 Design과 실제 A Plan을 먼저 채택/표시한다. 이때도 Robot은 이동하지 않는다. 마이크 인식 문장과 Design을 확인한 뒤에만 첫 현장 입력을 한다. 부적합 입력/음성 실패/슬롯 범위 초과는 보류한다. 초기 음성이 잘못됐다면 정지→정지 확인→재개로 같은 Job에서 다시 말한다. 이전 음성/API가 종료되기 전에는 재개를 보류한다. 창 재실행은 슬롯 복원이나 Robot 재개가 아니다.

1. 첫 전달은 터미널에 출력된 **현재 check_id가 포함된** `place_empty`, `confirmed:true` JSON 전체 한 줄을 같은 HMI 실행 터미널에 입력하면 시작된다. **실제 Robot 이동과 그리퍼 개폐가 발생한다.**
2. 전달·observe 복귀 뒤 사람은 HMI의 목표대로 조립한다. 기존 구조 유지·목표 일치·전달판 비움·손 이탈을 확인한 뒤 출력된 현재 `assembly`, `confirmed:true` JSON 전체를 입력한다. **마지막 Step 이전 입력은 다음 실제 전달을 바로 시작한다.**
3. 마지막 확인 후에만 최종 Current/채택 Design을 대조해 완료한다. Robot 성공만으로 Current/Step 완료를 바꾸지 않는다.
4. 잘못 놓임은 출력된 `confirmed:false`로 신고한다. 실제 좌표/색상 등을 알고 있으면 `actual` 여섯 필드를 함께 넣는다. 실제 Current·목표를 구분해서 보여주고 다음 전달을 보류한다. C 연결 모드이면 실제 배치를 채택한 뒤 C 질문·KEEP/REVISE·실제 A 재계획을 진행한다. 아래 최신 절의 입력 방법을 따른다.

Fake의 `{"event":"observe"}`·`{"event":"observe_wrong_color"}`는 REAL 확인으로 채택하지 않는다. 현재 REAL 단축 입력은 아래 최신 절을 따른다. 확인하지 않은 블록을 정상 조립했다고 입력하지 않는다. HMI STOP은 요청·상태 확인을 수행하며 긴급 정지는 현장 장치를 사용한다. 동작 중 창/자식 프로세스를 끊어 정지됐다고 판단하지 않는다.

저장된 C Design부터 시험하려면 위 명령의 `--c-mode live --c-voice` 대신 `--c-fixture interfaces/fixtures/c_design_initial_result.json`을 사용한다. 이때 C API/마이크는 호출하지 않으며 실제 A/Robot/현장 입력은 동일하다. `--color/--first-slot`은 기존 한 열 3회 시험용이므로 다중 열 manifest와 혼용하지 않는다.

장치 없는 검증: 관련 검사 **514 passed**, 종료 **0**(신규 18개 포함). 수정한 Python 컴파일·`git diff --check` 종료 0. 네 열×6슬롯의 계획 출력 24개, 저장 C와 실제 C 음성 함수 경로 각각 15 Step, 전달 전/조립 확인 전 미완료, 색상 불일치 보류, 무음/Provider 실패, 복귀 증거 누락, 설정 변경, 슬롯 경계, 잘못된 목표·중복 실행/집기 및 오래된 확인 거절을 확인했다. C 음성 녹음/HTTP·LLM HTTP와 Robot QProcess는 Mock이다. 원본 C/A/Backend 알고리즘과 측정/제어 파일은 수정하지 않았다.

Qt 1200×900에서 첫 조립 대기/최종 Current·Design과 축·목표 강조·표·안내·버튼을 렌더링해 확인했다. 증거는 검사 요약 (`logs/real-voice-preparation/summary.json`, 로컬 산출물), [첫 조립 대기 화면](../logs/real-voice-preparation/chair-awaiting-first-assembly.png), [완료 화면](../logs/real-voice-preparation/chair-complete.png), `logs/real-voice-preparation/mock-voice-fifteen-step.jsonl`이다. Mock 화면의 REAL 표시는 REAL Controller 소비 경로를 뜻하며 실제 장치 실행 성공이 아니다.

현장 로그는 `logs/c_voice_real/backend/<Job UUID>.jsonl`과 세션 디렉터리의 `driver/<실행 UUID>.jsonl`이다. 이번 에이전트 실행에서는 실제 API·마이크·Robot/Camera 조회 또는 이동을 하지 않았다. 사용자 보고와 이번 연결부 장치 시험은 별도다. 브랜치를 유지했고 커밋/게시/PR/merge는 하지 않았다. 기존 lint/type 검사 설정은 미구성이다.

## 2026-10-06 — 시작 전 오류 표시와 명시적 사전 이동

현장 시작 실패 로그의 원인은 `OBSERVE_POSE_MISMATCH`다. Robot 연결·대기 상태·TCP/tool 조회는 통과했으나 실제 시작 위치가 설정된 observe 위치와 달랐다. 조회 실패 결과를 Controller가 읽지 않아 HMI에 사유가 빠지던 부분을 수정했다. 현재/기대 pose와 거리(mm)·자세 차이(도)는 `ROBOT_OBSERVE_COMPARISON`으로 터미널과 driver JSONL에 기록하며, HMI 하단에는 오류 사유를 표시한다.

사용자는 HOME이 아닌 현재 위치에서 기존 HOME을 거쳐 observe로 이동하는 시험을 요청했다. 이를 **새 사전 이동 시험**으로 구현했으며 이 경로의 실기·충돌 검증 완료를 주장하지 않는다. 관절 목표의 FK 일치는 경로 충돌 검증이 아니다. 기존 HOME `[0, 0, 90, 0, 90, 0]`과 observe `[0.712, 7.268, 63.143, -0.006, 109.185, 0.785]`, 원본 joint 속도/가속도·TCP/tool을 재사용한다. 새로운 pose나 자동 원점 복구는 추가하지 않았다.

현재 HMI에서 실제 이동이 진행 중이 아니라면 창을 닫고 위의 REAL 음성 실행 명령으로 다시 연다. 창 열기는 여전히 **무이동 조회**다. observe 위치가 달라 시작이 비활성화되면 다음 순서로 사용한다.

1. 현장 감시·비상정지 대응 및 이동 공간을 확인하고 **사전 이동 · HOME→관측**을 누른다. 이 버튼은 **현재 위치→HOME→observe 실제 관절 이동**을 보내며 마이크·Job·집기·그리퍼 개폐는 시작하지 않는다.
2. 이동 전 대기/자율 상태·TCP/tool·그리퍼 상태와 현재 위치, HOME/observe FK 및 두 이동 메시지 직렬화를 검사한다. 이동 중 시작과 사전 이동 버튼은 비활성화되며 창 닫기도 차단한다.
3. 이동 후 실제 observe pose와 대기/그리퍼 상태 확인 및 정상 종료 증거를 모두 받은 뒤에만 **준비 확인 · Job 시작**이 활성화된다. 이후 STT/C/A 채택과 현장 확인 입력은 앞 절과 같다. 사전 이동만으로 공급 슬롯·Current·Step 완료는 바뀌지 않는다.

사전 이동은 창당 한 번만 요청할 수 있다. 실패·프로세스 오류·도착 증거 누락은 오류 보류이며 자동 재시도하지 않는다. 이동 중 실패의 stop 요청은 실제 정지 완료 증거가 아니다. 실패 후에는 현장 정지·위치·블록 상태를 확인하고 사람이 복구해야 하며, 창 재실행 자체를 정지나 복구로 해석하지 않는다. 현재 HMI STOP/재개 연결은 아래 최신 절을 따른다. 실제 장치 시험은 여전히 별도다.

화면 연결은 Qt 명령 `{"command":"PREPARE_OBSERVE"}` → Backend → 기존 Controller다. snapshot의 선택 항목 `actions.prepare_observe={visible, enabled}`는 REAL의 Job 시작 전만 사용한다. Fake·진행 중 Job에서는 요청을 거절한다. 기존 START/STOP/재개·완료 정책은 유지한다. Job 생성 전 기록은 세션 `driver/<실행 UUID>.jsonl`에 남으며 `ROBOT_PREPARE_PREFLIGHT / STARTED / COMMAND / COMPLETE`와 실패 result를 구분한다. STARTED의 `collision_verified=false`는 이번 구현이 충돌 검증을 포함하지 않는다는 뜻이다.

장치 없는 실제 검사 결과와 수정 파일은 사전 이동 검사 기록 (`logs/real-voice-preparation/prepare-button-summary.json`, 로컬 산출물)에 있다. [시작 오류 화면](../logs/real-voice-preparation/observe-start-failed.png)과 [사전 이동 도착 후 화면](../logs/real-voice-preparation/prepare-observe-ready.png)은 Qt 1200×900 Mock 렌더링이다. 실제 이동/API/Camera는 에이전트가 실행하지 않았다. 실제 경로 시험·현장 정지/복귀·운영 모니터 확인은 남아 있으며 커밋/게시/PR/merge는 하지 않았다.


## 2026-10-06 — REAL 정지·재개와 오배치 질문 TTS

사용자의 명시 요청으로 기존 REAL 버튼과 C 음성 연결을 확장했다. 기존 공통 Design/Observed/Current/Expected·A/B/C 알고리즘·측정값·HOME/observe·TCP/tool·속도는 유지한다. 이번 에이전트 실행은 장치 없는 Mock 검증이다. 실제 정지·재개나 음성 API 시험 통과를 뜻하지 않는다.

### 실행

이미 열린 창에는 코드가 자동 적용되지 않는다. 현재 Job의 실제 정지/종료와 블록 정리를 현장에서 확인한 뒤 새 프로그램을 실행한다. 앱 종료 후 Job/Current/공급 슬롯 복원은 지원하지 않는다. 기존에 소모한 공급 슬롯은 채우거나 manifest의 각 first_slot을 실제 준비 상태에 맞춘다. 실행 중 manifest 변경은 거절한다.

현재 사용자 터미널에서 `OPENAI_API_KEY`는 설계 LLM/STT, `OPENAI_TTS_API_KEY`는 질문 TTS에 사용한다. 키가 없다면 `read -rsp "TTS API key: " OPENAI_TTS_API_KEY`로 숨김 입력하고 다음 줄에서 `export OPENAI_TTS_API_KEY`를 실행한다. `export`만으로 없는 키가 생기지는 않는다. 키 값은 채팅/명령 문자열/로그에 넣지 않는다.

```bash
source /home/ms-02/cobot2_ws/install/setup.bash
cd /home/ms-02/C_2
export OPENAI_API_KEY
export OPENAI_TTS_API_KEY
export C_DESIGN_USE_LLM=1
export OPENAI_MODEL=gpt-4o
export OPENAI_STT_MODEL=whisper-1
export OPENAI_TTS_MODEL=tts-1
export OPENAI_TTS_VOICE=alloy

env -u QT_QPA_PLATFORM python3 -m app.real_workflow_hmi \
  --real-workflow \
  --config interfaces/robot_trial_blue5.json \
  --supply-manifest interfaces/robot_voice_workflow.json \
  --c-mode live --c-voice \
  --log-dir logs/c_voice_real
```

창 열기의 준비 검사는 실제 조회만 한다. 사전 이동 버튼은 **실제 현재 위치→기존 HOME→observe 이동**이며 집기/슬롯 효과는 없다. 준비 성공 뒤 시작→마이크 목표→실제 C 설계/실제 A Plan을 확인한다. STT/설계 오류는 성공 Design으로 대신하지 않는다.

### 정상 현장 입력과 오배치

현재 열린 요청에만 연결하는 다음 단축 입력을 같은 터미널에 한 번씩 입력한다. 외부 관측 결과의 오래된 check_id를 새 것으로 바꾸는 기능이 아니다. 명시적 check_id가 있으면 원래 ID로 검증한다. 대기 요청 없이, 이동/STOP/오류 중에는 거절한다. 단축 JSON도 사람이 현장을 확인했다는 실행 명령이다.

```json
{"event":"place_empty"}
```

첫 전달판이 비고 손/장애물과 공급 준비를 확인했을 때만 입력한다. **실제 전달과 그리퍼 개폐가 시작된다.**

```json
{"event":"assembly"}
```

observe 복귀 뒤 기존 구조 유지·목표 블록의 여섯 필드 일치·전달판 비움·손 이탈을 확인했을 때만 입력한다. 마지막 전 Step에서는 **다음 실제 전달이 시작된다.** 마지막 확인 후 누적 Current와 전체 Design을 대조한다. Robot 성공/버튼/빈 Remaining만으로 완료하지 않는다.

잘못 놓았으면 다음 양식의 실제 블록 여섯 필드를 고쳐 입력한다. 아래 값은 사용 예시이며 현재 Step의 실제 결과가 아니다. 기존 조립을 유지했다는 현장 확인도 포함한다.

```json
{"event":"assembly","actual":{"brick_type":"2x3x1","color":"blue","x":17,"y":9,"layer":1,"orientation_deg":0}}
```

실제 배치를 Current에 반영하고 이번 목표와 구분해서 표시한다. Step 미완료/다음 전달 보류→실제 C 질문 생성→TTS 재생 완료→마이크 답변 순서다. 음성 질문은 AI 생성 음성이다. 음성 입력을 terminal event로 가장하지 않는다.

- **1번/KEEP:** 기존 Design 유지. 실제 A가 충돌/보존 위반을 반환하면 사람 정리 대기다. 사람이 고친 뒤 기존 `정리 완료` 버튼을 누르고 출력된 `event=current` JSON의 blocks를 **현장에서 확인한 조립판 전체 실제 배치**로 수정해 입력한다. 현재 열린 check_id와 confirmed=true가 필요하다. 이 시험 입력은 24×24·1~4층 전체를 사람이 확인한 근거이며 Camera 관측이 아니다. 버튼만 누르거나 동일한 배치를 보고하면 정리 성공으로 처리하지 않는다. 실제 배치 변화 채택→실제 A 재계산→새 전달판 EMPTY 확인을 기다린다.
- **2번/REVISE:** C가 현재 실제 배치를 그대로 포함한 전체 수정 Design을 반환하고 실제 A가 최신 Current로 Remaining을 계산한다. Design·Plan을 함께 채택한 뒤 새 전달판 비움 요청을 연다. 채택 자체로 이동하지 않는다. 기존 Current와 실제 집기 후 공급 순서를 초기화하지 않는다.
- **불명확:** 안내 질문 한 번 뒤 계속 불명확하면 기존 KEEP/REVISE 버튼 선택을 기다린다. 자동 KEEP/무한 음성 반복은 없다.
- **TTS/STT/API 실패:** 실제 Current와 공급 순서를 유지하고 보류한다. 못 들려준 질문에 대한 마이크 응답이나 다음 전달을 시작하지 않는다. 재시도하려면 정지 확인→재개로 새 요청을 사용한다.
- **실제 배치 좌표 없음:** `{"event":"assembly","confirmed":false}`는 신고/보류만 한다. Current나 Difference를 추정하지 않아 TTS 의도 질문을 만들 근거가 없다. 목표대로 정리한 뒤 정지 확인→재개의 새 check에서 다시 확인한다.

C 연결이 없는 `--c-fixture` 전용 시험은 HRI/TTS를 호출하지 않는다. `--c-mode offline`은 실제 C 텍스트 함수 경로이며 터미널에 출력된 answer JSON으로 응답한다. Fake의 observe/observe_wrong_color 명령을 REAL에 사용하지 않는다.

### 정지와 재개

진행 중 정지 버튼을 사용할 수 있다. 이동 중에는 별도 `app.robot_pause --stop` 프로세스가 기존 move_stop(mode=1)을 요청하고 정지 표식으로 다음 이동/개폐를 차단한다. 이미 실행 중인 gripper/음성/HTTP 호출의 즉시 취소는 보장하지 않는다. 취소된 음성 결과는 채택하지 않는다.

정지 ACK·자식 프로세스 종료만으로 재개를 허용하지 않는다. 이전 실행 종료 뒤 무이동 probe가 실제 motion=0·idle/autonomous·기존 TCP/tool·그리퍼 상태를 확인해야 한다. 기존 Job·Design·Current·완료 기록·공급 순서는 유지하며 예전 관측·음성 결과는 진행을 바꾸지 않는다.

| 확인된 정지 상태 | 수동 재개 결과 |
|---|---|
| 미집기 | 새 execution_id, 같은 Step/공급 슬롯으로 기존 전달 명령 재전송 |
| 들고 있음 | 기존 명령 기록 이후 전달/복귀만 수행. 추가 집기 없음 |
| 놓음 | 기존 명령 기록 이후 observe 복귀만 수행. 다시 열기/집기 없음 |
| 조립/질문/초기 음성 대기 | observe 위치·빈 그리퍼 확인 후 새 check 또는 새 C 호출. 추가 이동 없음 |
| 사전 이동 중 정지 | 별도 확인 뒤 기존 HOME→observe 사전 이동 재개. Job/집기 효과 없음 |

그리퍼·로그·설정이 충돌하거나 실제 정지가 확인되지 않으면 재개를 차단하고 사유를 표시한다. STOP 뒤 servo 상태가 달라졌다면 자동 servo/reset/recovery를 추가하지 않는다. 현장에서 상태를 확인한다. 긴급 정지는 현장 비상정지를 사용한다. 앱 재실행을 STOP/복원/재개로 해석하지 않는다.

정지/확인 로그는 세션 `pause/<요청 UUID>.jsonl`, 전달/재개는 `driver/<실행 UUID>.jsonl`, Job별 Current/질문/음성/재계획/진행 기록은 `backend/<Job UUID>.jsonl`이다. 정상 현장 확인과 합성 B 입력을 구분해 기록한다. 검증 결과·수정 파일·Mock 화면은 이번 검사 색인 (`logs/real-stop-resume/summary.json`, 로컬 산출물)을 따른다.

### 규모와 남은 검증

정지 요청을 이동 호출과 분리해야 하므로 새 실행부 robot_pause.py 하나와 기존 Controller/driver/Backend/HMI 계약·Schema를 수정했다. TTS는 기존 CTextConnection/voice를 그대로 호출한다. 새 framework/dependency/추상 계층·A/B/C 알고리즘 변경은 없다. 기존 real_trial_hmi.py가 400행을 넘는 복잡성 검토 대상이며 STOP/재개 상태·증거/중복 처리와 테스트가 증가한 이유를 사람이 리뷰해야 한다.

실제 STOP의 정지 모드·ROS 상태 반환·들고/놓은 상태의 재개 궤적·마이크/TTS 재생/API 모델 권한·실제 Camera/B 생산자·운영 모니터 검증은 남았다. 원본 제어/측정 hash는 보존했다. 자동 Robot 복구·실행 중 보충·앱 종료 후 이어하기를 추가하지 않았다. 커밋/게시/PR/merge는 하지 않았다.

이번 수정 후 관련 검사 **634 passed**, 실패/오류/skip **0**, 종료 **0**. 신규 STOP/재개·TTS/재계획 사례 53개를 포함한다. Python 컴파일과 git diff --check 종료 0. HMI·JSONL·Schema/키 미기록·원본 hash를 확인했다. 검사 명령은 아래와 같다(실제 장치/API를 실행하지 않는다).

```bash
cd /home/ms-02/C_2
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/unit/test_robot_pause.py tests/integration/test_real_stop_resume.py \
  tests/integration/test_real_voice_replan.py \
  tests/unit/test_robot_trial.py tests/unit/test_real_trial_hmi.py \
  tests/unit/test_robot_backend.py tests/unit/test_backend.py \
  tests/unit/test_hmi_contracts.py tests/unit/test_qt_hmi.py \
  tests/unit/test_hmi_current.py tests/unit/test_snapshot_log.py tests/unit/test_replan.py \
  tests/integration/test_real_workflow_hmi.py tests/integration/test_real_voice_workflow.py \
  tests/integration/test_c_voice_hmi.py tests/integration/test_c_function_hmi.py \
  tests/integration/test_c_saved_results_hmi.py tests/integration/test_a_backend.py \
  tests/integration/test_abd_input_hmi.py tests/integration/test_abd_callback.py \
  planning_trial/test_planner.py -q
```
