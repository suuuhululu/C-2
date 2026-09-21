# 양초 측정 · 세 터미널 실행

2026-09-21, 이시율 현장 PC의 `/home/skywalker/collaborative` 기준.
코드·ROS 모의 연결은 통과했지만 **수정본의 실물 8점 완료는 아직 미검증**이다.
마지막 실물 시험은 두 번째 옆점 접근의 0.304 mm 이탈로 정지했다.
아래 명령은 사람이 복귀한 뒤 수행할 진단 시험용이다. 자리를 비운 상태에서 시작하지 않는다.

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
ros2 bag record -o "/tmp/workpiece_bag_$(date +%Y%m%d_%H%M%S)" --topics /workpiece_test/feedback /workpiece_test/result /workpiece_test/telemetry /dsr01/joint_states /dsr01/error /rosout
```

## 터미널 3 · 시작 요청

요청 수락 후 2초 예고 → 현재 관절/TCP 확인 → 필요할 때만 검사한 통로로 홈 이동 → 윗면 → 옆면 8점 → 좌표 계산·외곽 후퇴 순서다.

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
2분 완료는 아직 달성하지 못했으며, 설정된 전체 실행 제한 300초는 성공 시간이 아니다.

추가 취소가 필요하면 터미널 1에서 Ctrl+C 또는 터미널 3에서 아래 명령을 사용한다.
취소 접수와 실제 정지 확인은 구분한다. 통신 정지는 현장 비상정지를 대신하지 않는다.

```bash
ros2 service call /workpiece_test/cancel std_srvs/srv/Trigger '{}'
```
