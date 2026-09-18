# hmi_main.py — 진입점 (수업 qt_hmi/hmi_main.py 구조): Qt 이벤트 루프 안에서 10 ms 마다 ROS spin_once.
# 실행: ros2 run clay_hmi hmi_main
import sys

import rclpy
from PyQt5 import QtWidgets
from PyQt5.QtCore import QTimer

from clay_hmi.hmi_gui import RobotGUI
from clay_hmi.hmi_ros2 import RobotNode


def main(args=None):
    rclpy.init(args=args)
    hmi_ros2 = RobotNode()
    app = QtWidgets.QApplication(sys.argv)
    window = RobotGUI(hmi_ros2)
    hmi_ros2.set_gui(window)
    window.show()

    timer = QTimer()
    timer.timeout.connect(lambda: rclpy.spin_once(hmi_ros2, timeout_sec=0.0))
    timer.start(10)

    exit_code = app.exec()
    timer.stop()
    hmi_ros2.shutdown()
    hmi_ros2.destroy_node()
    rclpy.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
