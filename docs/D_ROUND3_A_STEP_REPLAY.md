# 통합 2단계: 실제 A 한 Step → round2 제어의 장치 없는 연결 검사

기존 현장 시나리오의 T2(파랑 2×3 슬롯3)와 다르므로 이 작업은 **통합 2단계**라 부른다.
T1 고정 실물 시험과 기존 full-real은 변경 없이 선택할 수 있다.

## 이번 연결

```text
MOCK HMI의 설계 후보·승인
  → 실제 A whole / assess / motion
  → 기존 execution_document + round2_replay 시험 입력
  → 기존 RobotProcess / EXECUTE 채널
  → A/D 기존 motion 일치 검사
  → Round3StepReplay
  → prepare_round2_step / run_round2_step
  → 기존 ControlSession / ControlledDriver / 원래 이동·파지·가압 함수
  → 합성 한 Step 결과 → HMI HOLD
```

고정 현장 스크립트를 호출하는 T1 방식과 달리 실제 A가 반환한 Step을 사용한다.
현재 범위는 필요한 패드 자료가 있고 사람 도움이 없는 로봇 놓기·누르기 분기다.
지지/사람 조립 등 지원하지 않는 방법은 자동 치환하지 않고 실행 전에 보류한다.

## 무엇을 검사하고 무엇을 대신하는가

- A 계산·계획/슬롯/Step 상관관계 검사, round2 후보 변환, 실제 runner의 명령 순서와
  세션/정지 검사는 기존 코드를 호출한다.
- 공급 관측은 교시 좌표를 그대로 반환하는 명시적인 합성 provider다. 실제 OpenCV
  검출이나 중앙점 보정 정확도를 검사하지 않는다.
- 정렬은 오차 0의 합성 패킷이다. 실제 카메라 yaw 추적·회전 응답 검증이 아니다.
- 로봇은 StepReplayDriver다. 반력은 지정한 가상 접촉점에서 주입하는 합성 값이며
  실제 결착·힘 제어 검증이 아니다. 모든 이벤트에 SYNTHETIC/physical_commands=0을 붙인다.
- 측정 입력은 `provenance=SYNTHETIC`이며 블록의 여섯 배치 필드가 A Step과 일치해야 한다.
  고정 T1의 좌표나 교시를 다른 블록에 자동 대입하지 않는다.

## 장치 없는 실행 예시

저장소 루트에서 기존 Python 의존성이 설치된 환경을 사용한다. ROS/로봇/카메라를
실행할 필요가 없다. 예제는 파랑 2×2 (11,11,L1)에 맞는 합성 입력이다.

```bash
export C_DESIGN_USE_LLM=0
python3 -m app.mvp_integration \
  --robot-root "$PWD/robot_control_integration" \
  --design interfaces/fixtures/cad_trial_blue_single.json \
  --round3-step-replay interfaces/fixtures/round3_step_replay.json \
  --log-directory logs/round3-a-step-replay
```

HMI에서 시작한 뒤 후보를 확인하고 텍스트로 승인한다. 기존 DB 환경 설정이 있으면
기존 로그인 gate가 적용된다. 음성/API 없이 시험하려면 위 offline 모드를 유지한다.
JSON의 참 값들은 합성 시험 가정이며 현장 교시·물리 검증 증거가 아니다.

`full-real` 또는 REAL runtime에서는 이 옵션/문서를 거부한다. 기존 일반 MOCK
문서에는 round2_replay가 없으므로 기존 실행 경로가 유지된다.

## 정상·자료 누락·정지

- 정상: A CANDIDATE → round2 분기 → PRESS_RESULT → ROUND3_STEP_REPLAY_RESULT.
  HMI는 `ROUND3_STEP_REPLAY_FINISHED_NOT_ASSEMBLY_CONFIRMED`로 HOLD에 머문다.
- 패드 자료/관측 provider 누락: EXECUTION_STARTED와 이동 전에 HOLD.
- 다른 블록의 자료: 문서 거부, 실행 없음.
- STOP: ControlSession을 취소하고 가상 driver를 정지한다. 이후 이동·그리퍼 명령을
  허용하지 않으며 늦은 성공 결과를 채택하지 않는다. 정지 증거는 합성이다.
- 한 프로세스에서 두 번째 실행이나 RESUME는 지원하지 않는다. 다시 시험하려면
  앱을 재시작한다. 자동 재실행하지 않는다.

결과는 기존 `<log-directory>/<job_id>.jsonl`에 A 결과와 로봇 이벤트로 남는다.
가상 집기 성공 시 공급 슬롯 소비는 기록하지만 B의 Current/완료 단계/최종 저장은
갱신하지 않는다. 실제 상태 확인과 다음 단계 진행은 후속 연결 범위다.

## 변경 파일

- `app/mvp_integration.py`: 명시적 MOCK 옵션과 실행 문서 전달, 시험 화면 표시.
- `robot_control_integration/scripts/robot_integration_runtime.py`: REAL/RESUME 거부 후
  새 replay 경로로 분기. 기존 EXECUTE 경로와 분리.
- `robot_control_integration/app/round3_step_replay.py`: A 자료를 round2 runner에 연결,
  입력 부족 검사·합성 provider·정지·결과 반환.
- `app/mvp_workflow.py`: 한 Step 결과를 HOLD로 표시하고 정지 후 늦은 성공 무시.

## 후속 현장 연결에 필요한 것

실제 관측 provider와 측정 자료를 Step별로 공급하고, 해당 보정이 A/D motion 계약과
일치하는지 확인해야 한다. 그 다음 B/사람 상태 확인·다음 Step·재계획으로 확장한다.
이번 MOCK 검사를 통과했다는 이유로 REAL 차단을 제거해서는 안 된다.

## 이번 작업의 검증 결과

- 새 A Step 연결 + 기존 T1/통신: 25 passed, skip 없음.
- 관련 native round2/정렬/원본 RELEASE_PRESS: 121 passed, 1388 deselected.
- 기존 full-real UI/실행 문서 선택 검사: 5 passed, 27 deselected.
- 정상·패드/provider 누락·블록 불일치·EXECUTE 직후 STOP·첫 이동 직전 STOP·
  정지 후 늦은 성공·REAL 차단·배포 예제 입력을 확인했다. 첫 이동 직전 STOP 이후
  추가 이동/그리퍼 쓰기가 없음을 검사했다.
- 구문/diff 공백 검사 통과. 실제 장치/카메라/음성 API/DB 검증은 하지 않았다.
