# [2번 노드] 그리퍼 대화형 제어. stage "scan_done" 을 받으면 터미널과 대시보드(/clay/prompt)에 묻는다.
#   1. 그리퍼를 닫으시겠습니까? (y/n)   → y: 닫기, n: 다시 1
#   2. 이대로 고정하시겠습니까? (y/n)   → y: stage "grip_done" 후 종료, n: 열고 1 로
# 실행: ros2 run clay_carving gripper_ui   (터미널 4)
import rclpy
from clay_carving.clay_common import Robot, Gripper, Bus


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("gripper_ui", namespace="dsr01")
    log = node.get_logger()
    bus = Bus(node)
    bus.wait_stage("scan_done")
    rb = Robot(node, "gripper_ui")      # DO 대체 경로용
    gr = Gripper(node, rb)
    try:
        while True:
            if not bus.ask_yes_no("close", "1. 그리퍼를 닫으시겠습니까?", log):
                continue
            gr.close()
            if bus.ask_yes_no("hold", "2. 이대로 고정하시겠습니까?", log):
                break
            gr.half_open()
        bus.publish_stage("grip_done")
        log.info("gripper_ui finished")
    except KeyboardInterrupt:
        log.info("Program Stopped")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
