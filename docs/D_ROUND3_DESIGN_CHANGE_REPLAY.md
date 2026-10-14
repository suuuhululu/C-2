# 저장 관측 기반 설계 변경·차이 대응 재계획

기존 T1/full-real/한 Step replay/ABCD 저장 관측 모드는 유지한다.
`design_change_replay=true`인 SYNTHETIC·MOCK·offline 입력에만 새 흐름을 적용한다.

## 두 경로

1. 사용자 변경: v1 첫 Step 실행 → B MATCH → 안전한 단계 경계에서 변경 요청
   대기 → 사용자 변경 버튼 → C 대화(REVISE) → v2 후보 표시 → 별도 승인
   → 확인된 Current를 출발점으로 A 재계획 → 남은 한 Step만 새 EXECUTE → B FINAL.
2. 차이 대응: D 첫 Step → B가 예상과 다른 배치를 확인해 Current 채택 →
   C가 실제 차이와 Current로 의도 질문 → 새 설계를 원한다고 답변 → 후보·승인
   → A 재계획 → 남은 한 Step → 최종 비교.

진행 중의 변경 요청은 현재 Step과 B 검사가 끝난 뒤 처리한다. 실제 이동의 RESUME가
아니라 새 계획/실행 ID를 사용한다. 기존 조립 블록의 재집기·재실행은 하지 않는다.

## 합성 입력과 실제 코드의 경계

- 최초 설계는 기존 두 블록 fixture이며, 새 후보는 `revised_candidates`에서 공급한다.
- C의 실제 대화 해석, Current 보존/지지/배치 검증, 버전 증가, 미리보기 후 승인
  코드를 호출한다. LLM/음성 호출은 하지 않는다. 자유로운 설계 생성 검증이 아니다.
- 후보는 이전 설계 버전·변경 사유·Current가 일치해야 공급된다. 다른 입력에 대해
  기본 후보나 T1 좌표로 대체하지 않는다.
- C에 optional `revised_generator`를 추가했다. offline 텍스트 재현에서만 허용하고
  후보를 기존 designer 검증에 통과시킨다. 일반 C 호출의 기본 동작은 유지한다.
- 새 설계에서 B Current의 여섯 배치 필드를 모두 보존해야 한다. 이미 조립된 실제
  색상이 목표와 달라도 실제 Current를 목표 색으로 덮어쓰지 않는다.
- 새 Step/FINAL 관측은 승인된 design_version과 맞아야 한다. 이전 설계의 저장
  관측은 ERROR로 보류한다. 새 블록의 패드 자료 누락도 실행 전에 보류한다.
- 불명확한 관측은 여전히 HOLD다. 실물 정지/인식/접촉/저장 검증을 뜻하지 않는다.

## HMI에서 사용자 변경 흐름 확인

저장소 루트에서 실행한다. 실제 장치나 ROS를 켤 필요가 없다.

```bash
env -u HISTORY_DATABASE_DSN -u HISTORY_WEB_URL \
  C_DESIGN_USE_LLM=0 PYTHONPATH="$PWD:$PWD/perception" \
  python3 -m app.mvp_integration \
  --robot-root "$PWD/robot_control_integration" \
  --design interfaces/fixtures/round3_abcd_design.json \
  --round3-step-replay interfaces/fixtures/round3_design_change_replay.json \
  --log-directory logs/round3-design-change
```

시작 → 첫 후보에 텍스트 `좋아 이걸로 하자` → 첫 Step과 B MATCH 후
`DESIGN_CHANGE_REPLAY_AWAITING_USER_REQUEST` 대기 → 설계 변경 요청 버튼 →
텍스트 `바꿔줘` → 새 후보 확인 후 `좋아 이걸로 하자`.
예제는 아래 파랑 블록을 보존하고 미조립 위 블록을 노랑으로 바꾼다.
실행 도중 변경 버튼을 눌러도 첫 Step 검사 뒤 대화로 넘어간다.

## 자동 검사와 로그

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD:$PWD/perception" \
python3 -m pytest tests/integration/test_round3_design_change_replay.py -q
```

`-k mismatch`는 B 차이 발견 후 재계획, `-k deferred`는 첫 MATCH 경계에서 기다렸다
변경하는 경우를 선택한다. 각 시험의 scenario.json에 저장 관측/후보가 남는다.

승인 전 PLAN_ADOPTED/ROBOT_EXECUTION_STARTED가 각 1회인지, 승인 후 새 계획의
base_current가 B Current인지, 남은 Step이 1개인지 검사한다. 승인 전 STOP과
늦은 승인, Current 삭제 후보, 후보/측정 누락, 구버전 관측도 검사한다.
로그는 `<log-directory>/<job_id>.jsonl`의 MODULE_RESULT(c.intent/c.review),
PLAN_ADOPTED, CHECK_RESULT, ROBOT_EXECUTION_STARTED로 연결을 추적한다.

다음 실물 연결에는 실제 관측/교시 provider와 새 계획의 경로·정지 검증이 필요하다.
이번 수정에서 force/pose/보정값·실물 실행 허용 조건은 변경하지 않았다.

## 이번 변경의 확인 결과

- 새 변경/차이 대응·승인/정지/자료 오류·provider 격리: 11 passed.
- 기존 C 단위 선택 검사: 118 passed.
- 기존 T1/한 Step/통신: 25 passed, ABCD 저장 관측: 12 passed.
- 기존 full-real UI/문서 선택 검사: 5 passed, 27 deselected.
- 구문/diff 공백 검사 통과. 실제 장치·음성 API·DB 미실행.

## HMI에서 조립 차이 대응 보기

위 HMI 명령의 `--round3-step-replay` 파일을
`interfaces/fixtures/round3_difference_replay.json`으로 바꾸고 로그 폴더를
`logs/round3-difference`로 지정한다. 앱을 닫고 새로 실행한다.

시작 → 첫 후보 승인 → 첫 D 가상 실행 후 B가 아래층 노랑 블록을 관측해
불일치 판정 → C 질문에 `바꿔줘` → 아래층 노랑을 보존한 새 후보 확인/승인
→ A가 위층 파랑 한 블록만 재계획 → D 가상 실행 → 최종 비교.
이 경우 별도로 설계 변경 버튼을 누를 필요가 없다.

## 로봇 PC의 검증 순서

1. round3 코드와 기존 현장 교시/드라이버 환경을 확인한다.
2. 기존 T1 고정 시험을 preview/replay로 확인한 뒤, 8블록 사전 배치·슬롯4·빈
   그리퍼 HOME 조건에서 T1 실물 집기/yaw/삽입/놓기/누르기/정지를 확인한다.
   실행과 키 조작은 D_ROUND3_FIXED_HMI.md와 세 단계 현장 안내를 따른다.
3. 실제 장치를 움직이지 않고 통합 2단계 A 한 Step replay를 실행한다.
4. ABCD 저장 관측 검사로 MATCH 진행/MISMATCH·UNOBSERVABLE 보류를 확인한다.
5. 이 문서의 사용자 변경과 조립 차이 대응 두 시나리오를 MOCK으로 확인한다.
6. 이후 실제 A의 임의 Step을 실제 관측/교시 provider에 연결하는 현장 통합이
   필요하다. 현재 replay 옵션은 REAL에서 거부되며, 3~5를 통과했다고 실물 전체
   통합이 완료되는 것은 아니다. 정상 실물 다단계/변경/최종 저장 시험은 그 연결 후다.

2번이 막혀 있어도 3~5의 소프트웨어 검사는 병행할 수 있다. T1 재시험 때는 실제
정지·블록 보유 상태를 확인하고 T1을 제거해 원래 사전 배치/출발 조건으로 복원한다.
