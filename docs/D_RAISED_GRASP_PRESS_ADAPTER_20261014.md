# 높은 파지 → 안착 → 해제 → 윗면 가압 연결

사용자 요청: 사람의 구조 지지는 유지하고, 그리퍼 간섭/접근 어려움 때문에 사람이 체결하던 구간을 보완한다.
참고 채팅: Develop integration2 block motions. 2026-10-14 최신 사용자 확인은 기존 블록 완전 결착,
합력 중단값 45N 변경 요청이다. 본 어댑터는 힘 값을 고정하거나 변경하지 않고 기존 config를 따른다.

## 적용 범위

`robot_control_integration/app/raised_grasp_press.py`에 측정 프로파일 어댑터와 callback 기반
단위/구성 시험 seam을 추가했다. 기존 `held_corner_stud_trial.py`에는
`--raised-grasp-profile`와 `--support-confirmation` 선택 옵션을 연결했다.
옵션 없는 기존 동작은 유지한다. 현재 실물 통합 팝업의 대상은 노랑 2x2 slot1,
(11,11) 1층이다. 다른 설계 전체/다른 층을 자동 채택하는 변경은 하지 않았다.
A/B의 HUMAN_ASSEMBLY 결정과 Current/체결 완료 판정도 임의 변경하지 않는다.
일반 설계 연결 담당자는 run_sequence의 callback으로 기존 지원 응답/명령 경로를 주입할 수 있다.

## 높이 좌표

기존 pickup Z에 임의 수치를 더하지 않는다. 같은 TCP/Tool/파지 방향에서 측정한
높은 공급 파지 pose, 목표 위 안착 pose, 빈 그리퍼 누름 접촉 pose 세 가지가 필요하다.
목표 안착 pose는 높은 파지 관계에 맞춰 측정하며 기존 seated TCP와 같다고 가정하지 않는다.
세 pose, 간섭/파지 안정성/안착 지지/패드 접촉 확인이 없으면 실행 프로파일로 채택하지 않는다.
기존 center_mapping은 높은 파지에 자동 재사용하지 않는다.
현재 XYZ/ZYZ convention과 기존 orientation 유지 제한을 적용했다.

`settings/raised_grasp_press_20261014/profile.pending.json`은 입력 양식이다.
실측 전 pose=null, 확인=false 그대로 두었으며 실물 실행 불가다. 테스트의 수치는
TEST_FIXTURE_ONLY이고 실측값으로 복사하면 안 된다.

## 순서와 지원

높은 파지 → 기존 이송/정렬 → 안착 → 작업자가 안착을 확인 → 해제 → 빈 그리퍼 상승/닫기
→ 기존 윗면 가압/상승 함수. 안착 하강이 force stop이면 새 경로는 놓거나 누르지 않는다.
가압의 reaction-stop은 체결 완료 판정이 아니다. 기존 힘/IK/TCP/gripper guard는 그대로 사용한다.
기울기 보정은 별도 기능이며 이번 adapter가 자동 X/Y tilt를 구현한 것은 아니다.

human_support_required=true인 단계에는 같은 step_id/support_request_id의 준비 응답을
--support-confirmation으로 주입한다. 형식은 request_id, step_id, ready=true,
expires_at_unix_s이다. 이미 끝난/다른 단계/만료된 응답은 거절한다.
신규 모듈은 지원 미준비 시 HUMAN_SUPPORT_REQUEST 이벤트를 반환하며 명령을 시작하지 않는다.
CLI는 잘못된 응답에서 시작을 중단하고 해제 직전에도 유효기간을 검사한다.
지속적인 사람 지지 존재 감지는 구현하지 않았으며 기존 사람 지원 정책과 동일한 한계다.

실측 프로파일 준비 후 기존 repo 루트에서 먼저 preview:

```bash
python3 robot_control_integration/scripts/held_corner_stud_trial.py --integrated-cycle --raised-grasp-profile /실측/프로파일.json
```

지지가 필요하면 유효 준비 응답 파일을 --support-confirmation으로 추가한다.
이번 개발에서는 실물 파지/하강/가압을 실행하지 않았다. 기존 그립 상태에서 새 높은 파지
프로파일로 재개하는 것은 금지한다. 새로운 공급 파지부터 시작해야 한다.

## 단위 테스트

repo 루트에서:

```bash
cd robot_control_integration
PYTHONPATH=../perception:. python3 -m pytest -q tests/unit/test_raised_grasp_press.py
```

실측 입력 누락/원본 보존/공급과 안착 pose 동시 변경/지원 만료와 ID/정상 순서/
힘 중단시 해제·가압 금지/지원 미준비시 이동 없음/기존 경로 유지 검증.
관련 신규+기존 held/supply 검사 44개 통과, py_compile 및 diff 검사 성공.
넓은 회귀 검사 최초 57개 통과/2개 실패: 동시 45N 변경으로 held_xy_seating의 기존 35N
고정 기대값 두 곳이 달라짐. 해당 채팅방 작업과 구분해 기록했으며 본 모듈이 force limit를 변경하지 않았다.
프로파일 실측과 파지 안정성/간섭/실물 가압 검증은 남아 있다.
