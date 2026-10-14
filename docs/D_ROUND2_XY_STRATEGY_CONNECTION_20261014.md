# Round2 XY 보정과 A 놓기·가압 연결

A PR50의 `f7a7655549fc273cf33393901bf4d91b9dc56e0a`와 계산 계약 `assembly-ad-calculation-draft/0.5.2`를 기준으로 D의 작업 전달과 실행 분기를 연결했다. 기존 로봇 조립은 A motion을 사용하고, `ROBOT_GRIP`에 `assembly_strategy=RELEASE_PRESS`가 있는 작업은 D의 명시된 놓기·가압 프로필을 사용한다.

## A 결과와 D 실행

A는 전체 밑면 지지가 있고 그리퍼 접근이 막힌 배치를 `RELEASE_PRESS`로 분류한다. 부분 지지·접근 불가 배치는 사람 조립을 유지한다. D는 원본 mode, strategy, gripper, assistance_kind와 도움 대상 전체를 보존한다. A의 `execution_allowed=false`도 유지한다.

이 방식의 A StepMotion은 `BLOCKED/UNSUPPORTED_METHOD`를 반환한다. D는 이를 성공으로 바꾸지 않고 `DReleasePressMotionResult`라는 별도 결과를 만든다. 결과에는 D 프로필 ID·SHA256, 작업 키와 원래 요청·assessment 연결이 있다. 요청·Current revision이 오래됐거나 프로필이 바뀌면 기존 작업 진행 규칙에 따라 채택하지 않는다.

| A의 도움 방식 | D 동작 |
|---|---|
| NONE | 공급 파지 → 이송 → 명시된 상공 해제 위치 → 개방 → 수직 후퇴 → 빈 패드 닫기 → 패드 목표로 접근 → 가압 → 상승 |
| HOLD | 계획에 지정된 아래 구조 지지 준비를 받은 뒤 위 로봇 동작 수행 |
| PRESS / PRESS_AND_HOLD | 계획의 사람 누름·지지 정보를 유지하며 놓기·후퇴 후 사람 응답 대기. 로봇의 두 번째 가압을 추가하지 않음 |

로봇 동작 종료 후에는 B 검사를 요청한다. 반력 도달, 사람 확인 응답, 로봇 명령 종료만으로 Current·revision·조립 완료를 갱신하지 않는다. 해제 이후 STOP·재개는 수행한 개방을 반복하지 않고, 패드 닫기 결과를 알 수 없는 경우에는 같은 명령을 자동 재전송하지 않는다. 빈 패드가 닫힌 상태는 다음 준비 조회에 전달하여 다음 Step의 `PREPARE_OPEN`으로 연결한다.

## 실물 프로필의 남은 입력

2026-10-14 사용자 결정으로 **상공 해제 높이는 미정**이다. 현재 T2 교시의 landing은 작업자가 파지를 유지해 완전히 결착한 위치다. 이 값을 `release_pose`로 자동 채우지 않는다. 실물 파일은 블록의 여섯 배치 필드와 공급 슬롯이 일치하는 측정값만 선택하며, 상공 해제 pose가 없으면 `INPUTS_REQUIRED`를 반환한다.

다음 항목을 명시해야 새 놓기·가압 작업을 준비할 수 있다. 좌표는 Base XYZ mm와 로봇 ZYZ 자세 deg를 사용한다.

- 파지 `pickup_pose`, 결착 기준 `reference_pose`, 상공 해제 `release_pose`.
- 로봇 가압을 사용할 경우 빈 패드 `press_approach_pose`, `press_start_pose`, `press_width_mm`.
- 파지·개방 폭과 해당 측정 기록 참조. 사람 PRESS 작업에는 로봇 패드 pose가 필요하지 않다.

FullFeatureRealTrial의 `--release-press-profile`은 다음 구조의 JSON 파일을 읽는다. `settings`에는 위의 실측 pose·폭을 넣는다. transient Step ID가 달라져도 블록 전체 배치와 슬롯이 같으면 선택할 수 있으며, 다른 블록·방향·층·슬롯의 값을 재사용하지 않는다.

```json
{
  "profile_id": "D_RELEASE_PRESS_MEASURED",
  "calibration_refs": {"tcp": "교시 기준 참조", "tool": "도구 참조"},
  "entries": [
    {
      "block": {"brick_type": "2x3x1", "color": "blue", "x": 13, "y": 11, "layer": 2, "orientation_deg": 0},
      "supply_slot": {"color": "blue", "brick_type": "2x3x1", "slot_index": 3},
      "settings": {},
      "measurement_refs": {}
    }
  ]
}
```

이 빈 예시로 로봇 실행 후보를 만들 수 없다. 입력값이 마련되면 기존 full-real 명령에 `--release-press-profile <실측파일.json>`을 추가한다. 이 full-real 시험의 B 입력은 기존과 같이 합성이며 실제 B 카메라 통합 완료 근거가 아니다.

기존 3Step 시나리오의 T2는 양옆 장애물을 제거한 `(13,11,L2)`이며 A에서 일반 로봇 조립이다. 이 시험을 새 `RELEASE_PRESS` 실물 검증으로 집계하지 않는다. 현재 세 단계 명령과 실제 A 전략 예제 시험은 각각 [세 사이클 안내](D_ROUND2_THREE_STEP_TRIAL_20261014.md)와 `tests/unit/test_release_press_connection.py`에서 확인한다.

## 영상 XY 보정

3Step 조립 팝업에서 **같은 몸체 윗면 모서리의 양 끝점**과 목표 outline의 해당 변 1~4를 선택한다. 두 끝점을 CameraInfo·카메라 변환으로 Base에 역투영해 목표 변과의 `dX/dY`를 계산한다. 원근 왜곡 때문에 픽셀 중점만 계산하지 않는다. 작업자가 X를 누르면 현재 TCP에 이 보정량을 적용하고 I의 착좌 XY에도 반영한다.

치우친 파지를 보상해 TCP를 옮겨도 최종 블록 목표는 같으므로 목표 outline과 빈 패드 접촉 목표는 원래 위치를 유지한다. 목표 변을 변경하면 이전 실제 모서리 선택과 yaw 이력을 지워 새 변으로 재선택한다. X 적용 뒤에도 각도 이력을 새 영상으로 다시 쌓는다.

등록된 깊이·영상 시각·크기가 맞고 양 끝점의 깊이를 사용할 수 있으면 깊이를 사용한다. 그렇지 않으면 기존 가상 격자의 예상 윗면 평면을 사용하며 화면에 높이 근거를 표시한다. 현재 카메라·보드 투영은 독립 실측 검증되지 않았으므로 XY 값은 작업자 적용 후보다. 두 점의 깊이만으로 배경 혼입이나 roll/pitch를 판정하지 않는다. 방출 후 블록 이동의 재관측은 미연결이다.

## T2 실측 교시

`T2.operator_teaching.json`에 공급판 중앙 파지, 동일 파지로 옮긴 완전 결착 TCP, 닫힌 빈 패드의 윗면 접촉 TCP를 보존했다. 이 세 pose가 이전 Base-Z +10mm 시험값을 대체한다. +10mm를 다시 더하지 않는다. 사용자가 추정한 파지 높이 약 8mm는 독립 측정값과 구분한다.

| 교시 | Base XYZ mm |
|---|---|
| 파랑 2×3 슬롯3 중앙 파지 | -459.1123, 11.1125, 50.5543 |
| `(13,11,L2)` 완전 결착 기준 | 503.7803, 91.6303, 37.0088 |
| 닫힌 빈 패드 윗면 접촉 | 504.0961, 91.2379, 55.5591 |

세 좌표의 Z 차이는 TCP 교시 차이다. 블록 파지 높이·스터드 삽입 깊이·해제 여유를 직접 측정한 수치로 해석하지 않는다. 사용자 제안 개방 46mm·상승 25mm는 현재 동작에 채택하지 않았다.

## 검증과 게시 범위

로봇 게시 사본에서 native 1,509개·영상 XY/가상 격자 49개 검사가 통과했다. A–D 사본에서는 실제 A 예제 6개·전체 메시지 36개를 포함한 A·Workflow·HMI·D 검사 652개가 통과했다. 명시 프로필 파일 → 실제 준비 코드 → D 서비스 → native MOCK → B 검사 대기 흐름과 HMI snapshot 계약도 확인했다. 범위가 겹치는 수치는 합산하지 않는다.

합성 3Step replay는 T1→T2→T3를 완료했다. 접촉 반력과 이동 종점을 부여하는 대역이며 실물 접촉·충돌·영상 yaw의 물리 시뮬레이션은 아니다. XML·원본 실패·source SHA는 로컬 `reports/round2_xy_strategy_link_20261014/`에 보존한다. 실제 로봇에 실행 명령은 보내지 않았다.

확장 모의 통합은 28 PASS / 8 FAIL이다. 8개 실패 node ID와 C의 지지 3<4 또는 2<4 거절 사유는 `reports/round2_pr46_review_20261014/baseline_failed_cases.xml`의 기존 결과와 같다. C 검사나 기대 결과를 약화하지 않았다.

로봇 제어·XY·교시 수정과 서비스 A–D 연결 수정은 별도 PR로 게시한다. A PR50은 통합 브랜치에 병합됐으며, A–D 연결 PR은 로봇 제어 PR 위에 쌓아 수정 범위를 분리한다. 게시·오프라인 연결 검증과 실물 시험·통합 완료 판정은 구분한다.
