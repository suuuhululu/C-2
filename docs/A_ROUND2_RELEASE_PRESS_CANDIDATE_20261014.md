# A Round2 놓기·가압 방식 분류 — 2026-10-14

사용자 최종 결정: A는 이 블록에 놓기·가압 방식이 필요하다는 분류를 반환한다. 해제 높이·실측 파지·TCP 변환·열기/후퇴/닫기/가압 경로와 실행 검증은 D 담당이다.

기준은 `codex/integration-round2@b0d22e5`(PR #46), 작업 브랜치는 `codex/round2-release-press-candidate`다. 기존 운반 경유점·교시·힘·D/HMI 코드·B Current/revision/완료 책임을 바꾸지 않는다.

## 판단과 반환

STUD_RULES의 기존 배치/최소 지지/겹침/위쪽 삽입/정적 목표 장애물 검사는 유지한다.

| 조건 | A 분류 |
|---|---|
| 기존 그리퍼 접근 가능 | 기존 ROBOT_GRIP/MINIMAL_OPEN |
| 기존 접근 불가 + 바로 아래층의 밑면 결합점 모두 존재 | ROBOT_GRIP + assembly_strategy=RELEASE_PRESS |
| 기존 접근 불가 + 밑면 결합점 일부만 존재 | HUMAN_ASSEMBLY |
| ROBOT_GRIP 비활성 또는 종류/방향에 맞는 파지 축 없음 | 로봇 분류를 추가하지 않음 |

전체 밑면은 노랑/파랑2×2=4, 2×3=6, 빨강1×2=2점이다. 1층은 보드 지지다. 아래 블록별 두 결착 조건·HOLD/PRESS 정책과 도움 대상/영역은 유지하며 놓기·가압 분류와 함께 반환한다. RELEASE_PRESS의 PRESS는 로봇 작업 전략이고, assistance_kind의 PRESS는 사람 도움이다.

전체 계획의 assembly_actions와 공통 API action_proposals, Step 재평가 action_proposal에 적용했다. 원본 요청·첨부 A 결과는 변경하지 않는다. 새 정책의 재평가에서는 이전 HUMAN_ASSEMBLY 선택이 새 RELEASE_PRESS 분류를 숨기지 않도록 갱신한다. 이전 API에 실행 금지돼 있던 별도 mode=ROBOT_RELEASE_PRESS는 추가로 활성화하지 않는다.

공통 계산 초안은 **0.5.2**다. 새 분류는 다음 필드를 반환한다.

```json
{
  "mode": "ROBOT_GRIP",
  "assembly_strategy": "RELEASE_PRESS",
  "grip_axis": "x",
  "gripper": {
    "pickup_policy": "D_EXISTING_PICKUP",
    "release_strategy": "RELEASE_PRESS",
    "release_owner": "D",
    "policy_at_wait": "HOLD_NO_AUTOMATIC_OPEN",
    "numeric_open_command": null
  },
  "robot_force_model": "NOT_ROBOT_INSERTION",
  "assistance_kind": "NONE"
}
```

위 코드는 실제 Action의 핵심 필드 발췌다. Plan/Step/블록/도움/참조 필드는 기존과 함께 반환한다. 기존 일반 로봇·사람 Action에는 assembly_strategy를 추가하지 않는다. 새 필드와 release_strategy의 조합은 스키마로 검증한다. 모든 API의 execution_allowed=false는 유지한다. 이 분류는 공중 낙하·가압 공간·완전 결착의 실물 검증 결과가 아니다.

## 로컬 호출과 검증 경계

`planning_trial.round2_release_press.assess_release_press(target, current, assembly_context)`는 공통 계획과 같은 방식 정책을 사용한다. 테스트 fixture는 [round2_release_press.synthetic.json](../planning_trial/fixtures/round2_release_press.synthetic.json)이며 해제 높이·도구 형상·실측15mm 입력을 요구하지 않는다.

```python
import json
from pathlib import Path
from planning_trial.round2_release_press import assess_release_press
d = json.loads(Path("planning_trial/fixtures/round2_release_press.synthetic.json").read_text())
r = assess_release_press(d["target"], d["current"], d["assembly_context"])
print(r["status"], r["assembly_strategy"], r["execution_allowed"])
# CANDIDATE RELEASE_PRESS False
```

일반 삽입용 StepMotion API는 RELEASE_PRESS를 UNSUPPORTED_METHOD로 반환하고 경로를 생성하지 않는다. D가 이 새 분류를 받아 전용 실행 프로파일을 적용해야 한다. 기존 D 소비자가 0.5.1 또는 MINIMAL_OPEN만 받는다면 0.5.2 분류 계약의 소비자 수정이 필요하다. 이를 A의 운반 경로 수정이나 D 실기 구현 완료로 표시하지 않는다.

재현: `python3 -m pytest -q planning_trial tests/unit/test_mvp_workflow.py tests/unit/test_mvp_pr30_relay.py --junitxml=reports/round2-release-press-classification-tests.xml`. 실제 결과는 STATUS에 기록한다. 실제 Robot/ROS/Camera/MoveIt/외부 API/DB 실행은 수행하지 않는다.

## D 연결용 전체 반환 예시

[round2_strategy.examples.json](../planning_trial/fixtures/round2_strategy.examples.json)에 실제 A 함수로 생성한 **6개 사례의 전체 메시지**를 저장했다. 각 사례의 `messages`에는 WholePlan·StepReassessment·StepMotion의 request/result 6개가 생략 없이 들어 있다. Plan/Step/Current revision/assessment ID/digest/슬롯 예약 참조도 서로 일치한다.

| case_id | mode / strategy | 사람 도움 | StepMotion |
|---|---|---|---|
| ordinary_robot | ROBOT_GRIP / 기존 조립 | NONE | CANDIDATE |
| release_press | ROBOT_GRIP / RELEASE_PRESS | NONE | BLOCKED / UNSUPPORTED_METHOD |
| partial_support_manual | HUMAN_ASSEMBLY | MANUAL_ASSEMBLY | CANDIDATE; SYNTHETIC 전달판 입력 |
| robot_hold | ROBOT_GRIP / 기존 조립 | HOLD | CANDIDATE |
| robot_press_and_hold | ROBOT_GRIP / 기존 조립 | PRESS_AND_HOLD | CANDIDATE |
| release_press_with_hold | ROBOT_GRIP / RELEASE_PRESS | HOLD | BLOCKED / UNSUPPORTED_METHOD |

사람 PRESS 단독은 이번 정책의 반환 예시가 아니다. 약한 아래 블록을 HOLD해야 하고 중심이 접촉 지지 영역 밖일 때만 사람 PRESS가 추가되므로 PRESS_AND_HOLD로 제시한다. `RELEASE_PRESS` 전략명과 사람 도움 PRESS를 구분한다.

예시는 SYNTHETIC 검토 입력이며 실제 D 교시·실행 프로파일·C가 승인한 실물 Design이 아니다. 전체 API 입력에 포함된 기존 TCP 후보는 기존 A 계산 자료이고, 새 놓기·가압 경로는 생성하지 않는다. A의 부분 지지/도움 API 사례와 C의 현재 최소4점 Design 규칙도 구분한다. 모든 실행 허용 값은 false이고 B Current는 fixture다.

새 예시 재생성(출력 UUID는 매 실행 바뀌며 한 묶음 안의 참조는 일치):

```bash
python3 -m planning_trial.run_round2_strategy_examples --output reports/round2_strategy.examples.json
```

저장된 예시의 스키마·참조 일치·현재 A 재계산 검사는 `planning_trial/test_round2_release_press.py`에 포함했다. 수현님 후속 작업 브랜치는 전달받은 `codex/round2-d-consistency-20261014`, 공통 PR 대상은 `codex/integration-round2`다.
