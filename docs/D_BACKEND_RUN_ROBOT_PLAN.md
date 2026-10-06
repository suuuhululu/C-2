# 수현 Backend·HMI 실행과 Robot 개발 계획

갱신: 2026-10-06. 현재 Backend는 Python 객체이고 HMI와 **같은 프로세스**에서 실행한다. 독립 서버/웹 API는 아직 없다. FAKE 전체 시나리오·수동 입력 창과 REAL 한 블록 시험 창을 구분한다.

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

실제 STOP/재개 버튼은 미검증으로 비활성화하며 현장 비상정지를 사용한다. 실패·증거 누락·프로세스 비정상 종료·설정/로그 오류는 HOLD와 추가 집기 차단이다. 해당 창에서 자동 재시도·복구·재개·두 번째 Job·슬롯 보충을 하지 않는다. 동작 중 창 닫기는 차단한다. 정상 종료는 최종 확인 후 창을 닫거나 Ctrl+D다. 종료 후 이어하기는 없다.

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

실제 STOP/재개 버튼은 **미검증으로 비활성화**되어 있다. 현재 시험 중 실제 긴급 정지는 현장 장치를 사용한다. 동작 중 창 닫기로 프로세스를 끊지 않으며 조회 전용 자식은 창을 닫을 때 종료할 수 있다. 일반 Fake HMI 명령은 앞 절의 `app.fake_demo --fake-demo` 그대로다.

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
