# hmi_ros2.py — HMI 의 ROS 2 쪽 (수업 qt_hmi/hmi_ros2.py 구조). GUI 는 hmi_gui.py, 진입점은 hmi_main.py.
# 노드들과의 연결: /clay/stage·/clay/data·/clay/prompt·/clay/preview 구독, /clay/answer·/clay/confirm·/clay/start 발행,
# 제어기 서비스로 TCP 위치·로봇 상태 조회와 긴급정지. 브링업은 전원 버튼으로 이 노드가 띄운다.
import json
import math
import os
import signal
import subprocess
import time

from rclpy.node import Node
from rclpy.qos import QoSProfile
from rcl_interfaces.msg import Log
from sensor_msgs.msg import JointState
from std_msgs.msg import String, Empty
from dsr_msgs2.srv import MoveStop, GetCurrentPosx, GetRobotState

from clay_carving.clay_common import (STAGE_TOPIC, DATA_TOPIC, START_TOPIC, PROMPT_TOPIC, ANSWER_TOPIC,
                                      PREVIEW_TOPIC, CONFIRM_TOPIC, LATCHED, _load_state, _save_state)

BRINGUP_CMD = ["ros2", "launch", "m0609_rg2_bringup", "bringup.launch.py",
               "mode:=real", "host:=192.168.1.100", "port:=12345", "model:=m0609"]   # .bashrc 의 sodreal 과 동일
ROBOT_STATES = {0: "초기화", 1: "대기(STANDBY)", 2: "이동 중", 3: "서보 오프", 4: "티칭", 5: "안전 정지",
                6: "비상 정지", 7: "호밍", 8: "복구", 9: "안전 정지 2", 10: "서보 오프 2", 15: "준비 안 됨"}
NODE_FILTER = ("clay_", "gripper_ui", "force_probe")     # /rosout 에서 화면에 보여줄 노드 이름


class RobotNode(Node):
    def __init__(self):
        super().__init__("clay_hmi_node")
        self.gui = None
        qos = QoSProfile(depth=10)
        self.create_subscription(JointState, "/dsr01/joint_states", self.joint_callback, qos)
        self.create_subscription(String, STAGE_TOPIC, self.stage_callback, LATCHED)
        self.create_subscription(String, DATA_TOPIC, self.data_callback, LATCHED)
        self.create_subscription(String, PROMPT_TOPIC, self.prompt_callback, LATCHED)
        self.create_subscription(String, PREVIEW_TOPIC, self.preview_callback, LATCHED)
        self.create_subscription(Log, "/rosout", self.rosout_callback, qos)
        self.answer_pub = self.create_publisher(String, ANSWER_TOPIC, qos)
        self.confirm_pub = self.create_publisher(String, CONFIRM_TOPIC, qos)
        self.start_pub = self.create_publisher(Empty, START_TOPIC, qos)
        self.stop_client = self.create_client(MoveStop, "/dsr01/dsr_controller2/motion/move_stop")
        self.posx_client = self.create_client(GetCurrentPosx, "/dsr01/dsr_controller2/aux_control/get_current_posx")
        self.state_client = self.create_client(GetRobotState, "/dsr01/dsr_controller2/system/get_robot_state")

        self.current_joint = [0.0] * 6
        self.connected = False
        self.bringup = None                      # 전원 버튼으로 띄운 브링업 프로세스
        self.tcp = None                          # 최근 TCP [x, y, z, A, B, C]
        self._posx_pending = False
        self.data = {}                           # /clay/data 최신 (clay, awl, job ...)
        self.stage = ""
        self.create_timer(1.0, self.check_services)
        self.create_timer(0.2, self.poll_posx)   # 5 Hz 로 손끝 위치 (2D 화면 동기화)
        self.create_timer(1.0, self.poll_state)
        self.get_logger().info("clay_hmi node started")
        st = _load_state()                       # 상태 파일에 남은 마지막 결과를 미리 보여준다
        if st.get("data"):
            self.data = st["data"]
            self.stage = st.get("stage", "")

    def set_gui(self, gui):
        self.gui = gui
        if self.data:
            self.gui.update_data(self.data)
            self.gui.update_stage(self.stage or "대기")

    # ---- 연결·상태 ----
    def check_services(self):
        ready = self.stop_client.service_is_ready() and self.posx_client.service_is_ready()
        if ready != self.connected:
            self.connected = ready
            self.log("브링업 연결됨 (제어기 서비스 확인)" if ready else "브링업 없음")
            if self.gui is not None:
                self.gui.update_connection(ready)
        if self.bringup is not None and self.bringup.poll() is not None:
            self.log(f"브링업 프로세스 종료됨 (코드 {self.bringup.returncode})")
            self.bringup = None
            if self.gui is not None:
                self.gui.update_power(False)

    def poll_posx(self):
        if not self.connected or self._posx_pending or not self.posx_client.service_is_ready():
            return
        self._posx_pending = True
        fut = self.posx_client.call_async(GetCurrentPosx.Request(ref=0))
        fut.add_done_callback(self._posx_done)

    def _posx_done(self, fut):
        self._posx_pending = False
        try:
            r = fut.result()
            if r and r.success and r.task_pos_info:
                self.tcp = list(r.task_pos_info[0].data[:6])
                if self.gui is not None:
                    self.gui.update_tcp(self.tcp)
        except Exception as e:
            self.get_logger().debug(f"posx: {e}")

    def poll_state(self):
        if not self.connected or not self.state_client.service_is_ready():
            return
        fut = self.state_client.call_async(GetRobotState.Request())

        def done(f):
            try:
                st = f.result().robot_state
                if self.gui is not None:
                    self.gui.update_robot_state(ROBOT_STATES.get(st, str(st)), st)
            except Exception:
                pass
        fut.add_done_callback(done)

    # ---- 구독 콜백 ----
    def joint_callback(self, msg):
        if len(msg.position) < 6:
            return
        self.current_joint = list(msg.position[:6])
        if self.gui is not None:
            self.gui.update_joint_position([math.degrees(p) for p in self.current_joint])

    def stage_callback(self, msg):
        self.stage = msg.data
        self.log(f"단계 → {msg.data}")
        if self.gui is not None:
            self.gui.update_stage(msg.data)

    def data_callback(self, msg):
        try:
            self.data = json.loads(msg.data)
        except Exception:
            return
        if self.gui is not None:
            self.gui.update_data(self.data)

    def prompt_callback(self, msg):
        try:
            d = json.loads(msg.data)
        except Exception:
            return
        if self.gui is not None:
            self.gui.show_prompt(d.get("id", ""), d.get("text", ""))

    def preview_callback(self, msg):
        try:
            d = json.loads(msg.data)
        except Exception:
            return
        self.log(f"실측 도안 미리보기 수신: {d.get('name')} ({len(d.get('strokes', []))} 획) → 확인/취소 대기")
        if self.gui is not None:
            self.gui.show_final_preview(d)

    def rosout_callback(self, msg):
        if not any(k in msg.name for k in NODE_FILTER):
            return
        if "travelled=" in msg.msg:            # 프로빙 샘플은 너무 많아 화면에서 뺀다
            return
        lvl = {10: "D", 20: "I", 30: "W", 40: "E", 50: "F"}.get(msg.level, "?")
        short = msg.name.split(".")[-1]
        if self.gui is not None:
            self.gui.write_node_log(f"[{lvl}] {short}: {msg.msg}", msg.level)

    # ---- 발행·명령 ----
    def answer(self, qid, yes):
        self.answer_pub.publish(String(data=json.dumps({"id": qid, "answer": "y" if yes else "n"})))
        self.log(f"응답 {qid}: {'예' if yes else '아니오'}")

    def confirm(self, ok):
        self.confirm_pub.publish(String(data="ok" if ok else "cancel"))
        self.log("그리기 확인" if ok else "그리기 취소")

    def start_job(self, job):
        """가이드라인을 상태 파일에 적고 시작 신호를 보낸다 (clay_start 와 같은 동작)."""
        _save_state(stage="", data={"job": job})
        self.log(f"작업 설정 저장: {job}")
        if self.start_pub.get_subscription_count() == 0:
            self.log("시작 실패: /clay/start 를 듣는 노드(clay_scan)가 없습니다. 노드 1 을 먼저 실행하세요")
            return False
        for _ in range(3):
            self.start_pub.publish(Empty())
            time.sleep(0.2)
        self.log(f"시작 신호 전송 ({self.start_pub.get_subscription_count()} 구독자)")
        return True

    def emergency_stop(self):
        """제어기에 즉시 정지(QSTOP=2). 물리 비상정지 버튼을 대체하지는 않는다."""
        if not self.stop_client.service_is_ready():
            self.log("긴급정지 실패: move_stop 서비스 없음 (브링업 확인)")
            return
        req = MoveStop.Request()
        req.stop_mode = 2
        fut = self.stop_client.call_async(req)
        fut.add_done_callback(lambda f: self.log("긴급정지 전송됨" if f.result() and f.result().success else "긴급정지 거부됨"))

    def toggle_power(self):
        """전원 버튼: 브링업을 띄우거나(이미 있으면) 내린다. 다른 곳에서 띄운 브링업이 있으면 새로 띄우지 않는다."""
        if self.bringup is not None:
            self.log("브링업 종료 중 ...")
            self.bringup.send_signal(signal.SIGINT)
            return False
        if self.connected:
            self.log("이미 다른 터미널의 브링업에 연결돼 있어 새로 띄우지 않습니다")
            return True
        self.bringup = subprocess.Popen(BRINGUP_CMD, env=dict(os.environ),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.log("브링업 실행: " + " ".join(BRINGUP_CMD[2:]))
        return True

    def bringup_cmd(self):
        return BRINGUP_CMD

    def log(self, text):
        self.get_logger().info(str(text))
        if self.gui is not None:
            self.gui.write_log(str(text))

    def shutdown(self):
        if self.bringup is not None:
            self.bringup.send_signal(signal.SIGINT)
        self.get_logger().info("ROS shutdown")
