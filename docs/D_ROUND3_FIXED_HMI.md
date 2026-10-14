# Round3 첫 연결: full-real HMI에서 T1 고정 시험

기준 브랜치는 `codex/integration-round2`의 `5652b694`이며 작업 브랜치는
`codex/integration-round3`다. 기존 full-real의 실행 경로는 유지하고,
`--round3-fixed-step`을 지정했을 때만 별도의 고정 시험을 실행한다.

## 이번 연결의 범위

HMI 준비 확인 및 (DB 설정 시) 로그인 → 시작 버튼 → 기존 round2 현장 시험의
T1만 실행 → 종료/실패 결과와 기록 경로를 HMI에 표시한다.

T1은 노랑 2×2 슬롯4에서 집어 `(9,9,L2,0°)`에 조립하는 기존 시험이다.
사전 8블록 배치, 교시, 빈 그리퍼 HOME 출발 조건은
[기존 세 단계 안내](D_ROUND2_THREE_STEP_TRIAL_20261014.md)를 그대로 따른다.
첫 Step 이후 상태가 필요한 T2/T3는 단독 선택할 수 없다.

고정 시험은 C 음성 설계·A가 생성한 임의 계획을 실행하지 않는다.
음성 버튼과 가짜 B 선택은 이 모드에서 숨긴다. 일반 full-real은 영향을 받지 않는다.
로그인 사용자는 작업 로그와 연결하지만 최종 결과 저장은 활성화하지 않는다.

## 호출 흐름과 변경 이유

```text
app.mvp_integration.main (--round3-fixed-step)
  → FullFeatureRealTrial.fixed_command('START')
  → FixedStepProcess
  → scripts.round2_three_step_trial run --only-step T1
  → 기존 LiveVision / supply.execute / held.transfer / held.observe
  → result.json과 프로세스 종료 상태 확인
  → HMI HOLD + 기록 경로 표시
```

`app/round3_fixed_trial.py`는 별도 현장 프로세스를 시작·조회·중단한다.
별도 프로세스로 두어 기존 팝업과 ROS 실행을 HMI 화면 처리와 분리하고,
기존 main-thread SIGINT 정리 경로를 재사용한다. 기존 RobotProcess에는
READ_STATE/EXECUTE를 보내지 않아 두 실행 경로가 장치를 동시에 초기화하지 않는다.

STOP과 창 종료는 자식에 SIGINT를 보내고 기존 driver.stop/자원 정리를 기다린다.
강제 kill·자동 재시작·RESUME를 제공하지 않는다. 종료를 기다리지 못하면 오류를
표시하며 프로세스 종료만으로 실제 정지가 검증됐다고 기록하지 않는다.

## 세 기능의 실제 의미

- 공급 OpenCV: 기존 stud 검출과 center_target을 사용한다. 검증된 center_mapping이
  없거나 보정 범위를 벗어나면 기존 교시 좌표를 유지할 수 있다. 검출 성공은
  중앙 보정 적용과 다르다. `VISION_DECISION`의 `center_assist_applied`,
  `fallback_reason`, `commanded_pickup_pose`를 확인한다.
- yaw: 기존 `auto_yaw=True` 경로를 사용한다. 실제 윗면 모서리 지정과 영상·기준
  선택이 필요하다. roll/pitch 자동 보정이나 무조작 전체 자동화가 아니다.
- 윗면 누르기: 기존 팝업의 삽입·놓기·패드 준비·누르기 절차와 45N 설정을
  재사용한다. 위치 도달·접촉·정지 조건은 바꾸지 않았다. 기존 X/I/O/P/U 등의
  조작은 원래 팝업 안내를 따른다. 45N은 목표 유지 힘이 아니라 반력 정지 기준이다.

## 실행

기존 ms-02 full-real 환경과 ROS/드라이버가 준비된 현장에서 사용하는 명령이다.
아래 명령은 HMI를 열고, 준비 확인 후 시작을 누르면 실제 로봇이 움직인다.

```bash
bash scripts/cad_trial_ms02.sh full-real --round3-fixed-step
```

다른 PC에서는 기존 로컬 환경을 설정한 뒤 동일 checkout의
`python3 -m app.mvp_real_trial --robot-root <robot_control_integration 절대경로>
--execute --c-mode live --round3-fixed-step`을 사용한다.
로그인은 기존 `HISTORY_DATABASE_DSN` 설정을 따른다. 키·DB 접속값은 문서에 넣지 않는다.

## 결과와 미연결 범위

성공은 `FIXED_STEP_EXECUTED`이며 `completed_steps=['T1']`인 경우만 채택한다.
`assembly_completion=False`, `current_update=False`를 유지하며 HMI는 HOLD에 머문다.
정지 후 늦게 도착한 성공은 성공으로 채택하지 않는다.
기록은 `logs/full-feature-real/<job_id>/fixed-trial/` 아래 console.log와
타임스탬프 하위 events.jsonl/result.json에 남는다.

다음 단계는 이 고정 시험에서 확인된 실행 결과를 일반 Step 계약에 연결하고,
실제 B/사람 상태 확인·C 변경 설계·A 재계획·최종 저장을 연결하는 작업이다.
현재 코드는 그 연결 완료나 실물 조립 성공을 뜻하지 않는다.

## 이번 변경의 오프라인 검증

- HMI 버튼 신호·로그인/준비 gate·중복 시작·STOP·종료 대기·잘못된 결과·T1 단독
  합성 재생과 관련 공급 좌표/기존 HMI 회귀: 선택 검사 43 passed, 16 deselected.
- 기존 native round2/정렬/공급 관련 검사: 120 passed, 1389 deselected.
- 전체 full-real adapter/프로세스 선택 파일: 33 passed, 5 failed. 실패5건은 수정 전
  round2 HMI 모듈로도 동일 재현됐다. 원인은 테스트 설계의 최소 지지 조건 위반이며
  이번 변경에서 수정하지 않았다. 자세한 범위는 STATUS.md에 기록했다.
- 구문 검사와 diff 공백 검사 통과. 실제 장치·음성 API·DB는 실행하지 않았다.
