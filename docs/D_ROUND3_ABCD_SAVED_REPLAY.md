# ABCD 연결 검사: D 가상 실행 → 저장 관측 → B 비교 → 다음 Step

실제 장치 없이 저장된 합성 관측 JSON을 사용하는 round3 선택 모드다.
기존 T1 실물 시험, 일반 full-real, 통합 2단계 한 Step replay는 유지한다.

## 연결한 흐름

```text
고정 설계 후보 → 실제 C 검토/승인 → 실제 A whole/assess/motion
→ 실제 round2 runner의 MOCK 파지/정렬/누르기
→ D 결과 수신 → B STEP 검사 요청
→ 파일에서 해당 관측을 읽음 → 실제 B Current/Expected 비교
  ├ MATCH → 완료 Step 기록 → A 다음 단계 재평가 → D 실행
  ├ MISMATCH → 관측된 Current 채택, HOLD (자동 C 변경 대화 없음)
  └ UNOBSERVABLE/ERROR → HOLD, 다음 Step 실행 안 함
→ 모든 Step MATCH → 별도 FINAL 저장 관측 검사 → MATCH인 경우 COMPLETE
```

C 최초 후보는 fixture이며 생성 LLM/음성은 호출하지 않는다. C의 기존 검토/승인,
A 계산, B 비교 코드와 D runner를 호출한다. 카메라 인식·실제 yaw·접촉 물리·DB
저장 검증이 아니다. COMPLETE도 이 합성 시나리오의 최종 비교 통과를 뜻한다.

## 입력과 규칙

- `round3_abcd_design.json`: (11,11)에 파랑2×2를 1층/2층으로 쌓는 고정 설계.
- `round3_abcd_replay.json`: Step별 합성 패드 자료와 INITIAL→STEP→STEP→FINAL
  순서의 저장 관측이다. 보정/검증 참 값들은 합성 가정이며 현장 교시 증거가 아니다.
- 각 STEP 레코드의 target_block은 A의 현재 Step 블록과 정확히 일치해야 한다.
- 관측의 check_id/observation_seq만 현재 요청에 연결한다. visible_blocks,
  verified_regions, status는 파일의 값을 사용하며 Expected로 덮어쓰지 않는다.
- 자료 누락·순서 오류·Step 불일치는 ERROR로 보류한다. 자동 생성된 scene이나
  성공 관측으로 대체하지 않는다.
- MISMATCH에서도 B가 확인한 실제 입력 상태를 목표 상태로 바꾸지 않는다.
- 이 모드에서는 재검사·설계 변경·재개를 막는다. 파일은 고정된 관측 순서이므로
  다른 장면이 필요한 동작은 앱을 재시작해 새로운 시험으로 수행한다.

## 장치 없는 실행

저장소 루트에서 실행한다. ROS/로봇/카메라 드라이버는 필요 없다.

```bash
env -u HISTORY_DATABASE_DSN -u HISTORY_WEB_URL \
  C_DESIGN_USE_LLM=0 PYTHONPATH="$PWD:$PWD/perception" \
  python3 -m app.mvp_integration \
  --robot-root "$PWD/robot_control_integration" \
  --design interfaces/fixtures/round3_abcd_design.json \
  --round3-step-replay interfaces/fixtures/round3_abcd_replay.json \
  --log-directory logs/round3-abcd-replay
```

시작 → 미리보기 확인 → 텍스트 승인 후 두 Step이 진행된다. 일치 예제는 FINAL
MATCH 후 COMPLETE가 된다. 최종 저장은 자동 실행하지 않는다.

## 자동 검증

```bash
env -u HISTORY_DATABASE_DSN -u HISTORY_WEB_URL \
  QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD:$PWD/perception" \
  python3 -m pytest tests/integration/test_round3_abcd_saved_observations.py -q
```

검사에서는 정상 두 Step, 첫째/둘째/FINAL의 MISMATCH·UNOBSERVABLE,
관측 누락·순서·대상 오류, B 대기 중 STOP을 확인한다. 첫 B MATCH 기록이 두 번째
D 실행보다 앞서는지 확인하고, 실패 후 다음 실행이나 C 자동 재계획이 없는지 검사한다.

## 기록과 코드

`logs/round3-abcd-replay/<job_id>.jsonl`의 CHECK_RESULT에서 B 결과와 채택 여부를,
ROBOT_EXECUTION_STARTED에서 실행 횟수를, ROBOT_ROUND3_STEP_REPLAY_RESULT에서
D 가상 결과를 확인한다. STEP 완료와 FINAL 비교는 별도 기록이다.

- `mvp_integration.py`: 저장 관측 읽기, Step별 측정 선택, 기존 가상 scene fallback 제외.
- `mvp_workflow.py`: D 종료 후 STEP 검사, MATCH 다음 진행, 불일치/관측 불가 HOLD.
- native runtime: 이 모드에만 연속된 새 실행 허용, execution_id 재사용 거부.
- `round3_step_replay.py`: 최종 가상 로봇 표본 전달, B 대기 중 STOP 처리.

다음 현장 단계는 실제 관측 provider 또는 사람이 확인한 상태 입력을 같은 검사
경계에 연결하는 것이다. 이번 결과만으로 실물 조립 성공을 주장하지 않는다.
