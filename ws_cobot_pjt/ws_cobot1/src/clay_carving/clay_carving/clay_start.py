# 시작 신호: /clay/start 를 한 번 보낸다 (터미널 7). 1번 노드 clay_scan 이 이를 받아 시작한다.
import time
import rclpy
from std_msgs.msg import Empty
from clay_carving.clay_common import START_TOPIC, _save_state, _load_state


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("clay_start", namespace="dsr01")
    job = _load_state().get("data", {}).get("job")
    _save_state(stage="", data=({"job": job} if job else {}))     # 새 사이클: 이전 단계·데이터 초기화 (대시보드 가이드라인은 유지)
    pub = node.create_publisher(Empty, START_TOPIC, 10)
    # 구독자(clay_scan)가 매칭될 때까지 기다린 뒤 보낸다. 디스커버리 전에 보내면 유실된다 (9/17 가상 검증).
    t0 = time.time()
    while pub.get_subscription_count() == 0 and time.time() - t0 < 10.0:
        time.sleep(0.1)
    if pub.get_subscription_count() == 0:
        node.get_logger().error("No subscriber on /clay/start: is clay_scan running?")
    else:
        for _ in range(3):
            pub.publish(Empty()); time.sleep(0.3)
        node.get_logger().info(f"start signal sent to {pub.get_subscription_count()} subscriber(s)")
    node.destroy_node(); rclpy.shutdown()


if __name__ == "__main__":
    main()
