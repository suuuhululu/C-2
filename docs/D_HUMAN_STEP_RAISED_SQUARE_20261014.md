# 사람 결착 step의 높은 파지·윗면 가압 후보

## 대상

기존 HUMAN_ASSEMBLY 중 그리퍼 충돌/접근 제한 때문에 사람이 결착하던 step이다.
노랑/파랑 2x2x1, 2x3x1 및 빨강 1x2x1, orientation 0/90을 처리한다.
새 app/human_step_raised_press.py는 임의의 step key/목표 위치/기존 파지 slot을 받는다.
기존 yellow slot1 (11,11) 팝업의 제한과 독립적인 일반 step 경로다.
모든 블록 종류를 코드로 처리한다는 뜻이며 모든 배치가 물리적으로 가능하다는 뜻은 아니다.

## 예제

fixtures/raised_square_last_20261014에 5종 x 2방향=10개 fixture를 제공했다.
서로 겹치지 않는 4개 블록으로 사각형 외곽을 만들며 Current에는 3개,
target에는 마지막 블록이 들어간다. 블록 폭/길이에 따라 중앙 빈 공간 크기는 다르며
2x2 네 개는 중앙 빈 공간 없이 사각형을 이룬다. 실제 간섭/파지 시뮬레이터가 아닌 stud 격자 예제다.

## 연결

```python
from app.human_step_raised_press import adapt_human_step
from app.assembly_step_runner import run_step

# plan은 기존 HUMAN_ASSEMBLY plan, profile은 기존 실행 profile이다.
# measured는 해당 step/블록/파지축에서 실측·확인한 값이다.
candidate, raised_profile = adapt_human_step(plan, profile, measured)
# 기존 review/physical validation/confirm 경로를 거친 뒤 같은 runner에 전달한다.
result = run_step(driver, connection, candidate, raised_profile, confirm, record)
```

원본 plan/profile을 수정하지 않고 별도 ROBOT_RELEASE_PRESS 실행 후보를 만든다.
source_mode/source_assistance_kind와 original A/B plan을 보존하며 Current나 완료를 변경하지 않는다.
아래 입력을 확인해야 후보 생성이 가능하다:

- 정확한 key와 block, GRIPPER_COLLISION/GRIPPER_ACCESS 이유, measurement_ref
- pad_bottom_from_block_bottom_mm > 5이며 body_height_mm 미만
- 높은 파지 pickup_pose, 같은 파지 관계의 landing_pose, 빈 그리퍼 pad_contact_pose
- pickup/release/press 폭, 파지 안정성/삽입 sweep/개방 및 후퇴 sweep/누름 sweep/안착 지지 확인
- human_support_required는 기존 MANUAL_ASSEMBLY_AND_HOLD 등 지원 여부를 그대로 유지

미확인 항목은 ValueError로 후보 생성 거절; 호출자가 원본 HUMAN_ASSEMBLY를 유지한다.
force limit/속도/물리 리뷰 플래그를 임의 승격하지 않는다. 높은 파지/press 위치에 기존
bbox/stud 중심 mapping을 재사용하지 않는다. 실측은 fixture 수치와 구분한다.

runner의 ROBOT_RELEASE_PRESS 분기에 raised_human_step 전용 수직 후퇴를 추가했다:
목표 안착 → RELEASE_FOR_TOP_PRESS 확인 → 개방 → 현재 XY에서 빈 그리퍼 수직 후퇴
→ 누름 도구 접근 → 닫기 → 윗면 가압 → 기존 후퇴/Backend 관측.
사람 지원이 필요하면 assistance_kind=HOLD와 기존 준비/gesture 확인을 유지한다.
기존 human gesture commissioning은 새 지지 동작에 맞게 리뷰해야 하며 자동 승인하지 않는다.
X/Y 기울기 보정이나 가압 정답 판단은 이 어댑터와 별도다.

파일 기반 preview (장치 연결 없음):

```bash
python3 robot_control_integration/scripts/raised_human_step_preview.py \
  --step-dir /기존/step자료폴더 --profile /기존/profile.json \
  --measured /해당step/실측.json --output /결과/raised-candidate.json
```

## 테스트

repo 루트에서:

```bash
cd robot_control_integration
PYTHONPATH=../perception:. python3 -m pytest -q tests/unit/test_human_step_raised_press.py
```

5종×2방향×지지 필요/불필요, 사각형 마지막 step의 비겹침, 원본 보존,
미확인 sweep이면 사람 경로 유지, 지지 제거 금지, 5mm 이하 거절,
실제 기존 runner의 안착→개방→수직 후퇴→접근→가압 순서를 MOCK으로 검증한다.
기존 raised adapter와 합계 40개 통과. 기존 경로 회귀도 별도로 실행했다.
실물 그리퍼 간섭/안착 지지/높은 파지 안정성/가압은 미검증이다.

최종 신규+기존 raised/bridge/gesture/pickup 검사: 186 passed (2026-10-14).

## 2026-10-14 중심 수직 가압 변경

사용자 확인: 블록 중심을 잡아 운반하므로 놓은 위치에서 상승→닫기→수직 하강하면 중심이다.
raised 경로는 해제 후 실제 pose의 XY/ABC를 고정하며 가압 전 수평 이동/회전을 없앴다.
press_start/approach 설정의 XY/ABC도 landing 기준으로 통일한다. pad_contact_pose는
닫힌 패드의 접촉 Z 기준만 사용한다. 블록 파지 높이와 닫힌 패드 접촉 높이는 같다고 가정하지 않는다.
가압 어댑터의 force_stop_n은 45N으로 통일한다. 이 값은 현재 위치 하강 방식에서
측정 합력 45N 도달 시 중단 기준이다. 45N을 일정하게 유지하는 힘 제어는 아니다.
기존 ROBOT_GRIP native_press 정책은 새 release/closed-tool 방식으로 재사용하지 않는다.
개방/상승/닫기/수직 하강 및 actual XY/ABC 유지와 45N을 테스트했다.

## 파지 높이 확정: 15mm

사용자 결정으로 pad_bottom_from_block_bottom_mm=15.0을 모든 블록에 적용한다.
기준은 그리퍼 패드 하단과 블록 바닥 사이 거리다. 기존5mm보다10mm 높은 파지이며
공급판에서 처음부터 해당 높이로 잡는다. 정확한 TCP pose는 파지 관계/자세에 맞는
실측 pose를 입력하며 단순 base-Z +10mm를 자동 가정하지 않는다.
목표 안착 pose도15mm 파지 기준으로 함께 지정한다. 기존 파지 상태로 재개하지 않는다.
15mm와 다른 profile은 새 경로에서 거절한다. 관련 테스트41개 통과.
