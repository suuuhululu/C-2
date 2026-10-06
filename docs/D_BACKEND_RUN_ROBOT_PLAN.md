# 수현 Backend·HMI 실행과 Robot 개발 계획

> 이 문서는 최초 게시 단계의 실행 안내·계획 기록이다. 최신 A 연결은 [A–D 연결 안내](D_A_PLANNER_HANDOFF.md)를 따른다. 현재 FakeDemo는 Fake Robot Controller/driver를 사용하며 실제 A 연결 검사는 별도 통합 테스트로 실행한다.

갱신: 2026-10-06. 현재 Backend는 Python 객체이고 HMI와 **같은 프로세스**에서 실행한다. 독립 서버/웹 API/ROS 실행 명령은 아직 없다. 현재 실행 예제는 FAKE 전용이다.

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

시나리오를 바꾸려면 예제를 종료하고 `--scenario` 값만 바꿔 다시 실행한다. `--fake-demo`는 필수다. 이 예제는 ROS/Robot driver/실제 Vision/HRI/Planner를 호출하지 않는다. 공급 슬롯은 Controller 미연결로 미확인이다.

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

## 오늘 Robot 개발을 시작할 단계

아래는 **설계/개발 계획**이며 Robot 신규 구현 승인이나 장치 실행 지시가 아니다. 단계마다 결과·실제 검사·미검증을 보고한 뒤 다음 단계 승인을 받는다. 0~4는 원격 Fake 작업, 5는 실제 연결 준비, 6~7은 별도 장치 실행 지시 이후다.

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

다음 구현 승인은 Robot **0단계**부터다. 오늘은 원격이면 0단계 검토 → 1단계 경계 승인 → 2~4단계 Fake 검증 순서로 진행할 수 있다. 현장 확인값 없이 5단계를 완료하거나 6~7단계 장치 통과를 선언하지 않는다.
