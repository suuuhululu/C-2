# 양초 측정 · 세 터미널 실행

2026-09-21, 이시율 현장 PC의 `/home/skywalker/collaborative` 기준.
이전 HOME·외곽 종료 버전의 단독 실물에서 **윗면 → 옆면 8점 → 계산 → 마지막 후퇴를 연속 2회 완료**했다(270.394초 / 299.295초).
두 번째는 8점 종료 자세에서 HOME 회전 경유까지 포함한다. CONTACT_REFERENCE 결과이며 절대 윗면/바닥 Z는 아직 null이다.
공중 이동·완전히 분리된 외곽 후퇴는 60 mm/s, 15 N 즉시 정지만 적용한다. 표면 접근/접촉/초기 후퇴는 10 N을 유지한다.
전체 시간 제한은 시험 후 300→360초로 여유만 늘렸다. **2분 목표 달성은 아니다.**

조건: 기존 sodreal 연결, 드릴 OFF, 양초·받침·철사 고정 유지, 주변 비움,
운영자가 비상정지를 사용할 수 있는 상태. 기존 측정/조각 수신부는 종료한다.
이 문서의 절대경로는 해당 PC 실행 예시이며 공통 JSON/모듈에는 넣지 않는다.

## 터미널 1 · 수신부

실행 후 대기한다. 이것만으로 이동하지 않는다.

```bash
cd /home/skywalker/collaborative
source /opt/ros/jazzy/setup.bash
source ws_cobot_pjt/ws_dsr/install/setup.bash
export ROS_DOMAIN_ID=20 ROS_LOG_DIR=/tmp/workpiece-user-ros-logs
python3 ws_cobot_pjt/ws_cobot1/src/c2_process/test/workpiece_test_node.py --mode REAL --operator-ready --output-dir /tmp/workpiece-user-test
```

## 터미널 2 · bag 기록

`Recording...` 및 측정 토픽 구독 메시지 이후 터미널 3을 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/skywalker/collaborative/ws_cobot_pjt/ws_dsr/install/setup.bash
export ROS_DOMAIN_ID=20 ROS_LOG_DIR=/tmp/workpiece-user-ros-logs
ros2 bag record --qos-profile-overrides-path /home/skywalker/collaborative/ws_cobot_pjt/ws_cobot1/src/c2_process/config/workpiece_bag_qos.yaml -o "/tmp/workpiece_bag_$(date +%Y%m%d_%H%M%S)" --topics /workpiece_test/feedback /workpiece_test/result /workpiece_test/telemetry /dsr01/joint_states /dsr01/error /rosout
```

## 터미널 3 · 시작 요청

요청 수락 후 2초 예고 → 현재 관절/TCP 확인 → 필요할 때만 새 상공 HOME으로 이동 → 바로 수직 윗면 접근 → 옆면 8점·외곽 후퇴 → 좌표 계산 → 새 HOME 복귀·정지 확인 → 완료 순서다.

새 HOME: GripperDA_v1 TCP `(426.243743, 0.046709, 330.000) mm`, 기존 수직 자세. 이미 홈이면 재상승·옆 이동을 생략한다. 사용자 실물 재시험은 8점 완료 후 홈 X 복귀에서 선분 편차로 정지했다. 상공 자세 유지 이동만 1 mm 허용폭으로 분리한 후 모의 156건을 통과했으며 수정본 실기 재시험은 남아 있다. 기존 수신부를 종료한 뒤 터미널 1을 다시 실행해야 수정본이 적용된다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/skywalker/collaborative/ws_cobot_pjt/ws_dsr/install/setup.bash
export ROS_DOMAIN_ID=20 ROS_LOG_DIR=/tmp/workpiece-user-ros-logs
ros2 service call /workpiece_test/start std_srvs/srv/Trigger '{}'
```

`success=True, accepted=True`는 **접수**이며 측정 성공이 아니다.
최종 결과는 터미널 1의 `result: SUCCEEDED / FAILED / STOPPED / UNKNOWN`과 bag에 남는다.
실패하면 다음 점/자동 홈 이동을 하지 않는다. 기준을 바꾸거나 시작 요청을 반복하지 말고 기록을 확인한다.
완료·정지 결과를 받은 후 터미널 2를 Ctrl+C로 종료하면 bag 저장이 마무리된다.

센서·명령·진행·결과 JSONL은 `/tmp/workpiece-user-test/`에 함께 저장된다.
최신 코드에는 `desired_posx`와 실제 `posx`, 횡오차 상세 기록이 추가돼 있다.
2분 완료는 아직 달성하지 못했으며, 설정된 전체 실행 제한 360초는 성공 시간이 아니다.

추가 취소가 필요하면 터미널 1에서 Ctrl+C 또는 터미널 3에서 아래 명령을 사용한다.
취소 접수와 실제 정지 확인은 구분한다. 통신 정지는 현장 비상정지를 대신하지 않는다.

```bash
ros2 service call /workpiece_test/cancel std_srvs/srv/Trigger '{}'
```
