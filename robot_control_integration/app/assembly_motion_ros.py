"""비접촉 시험의 REAL ROS/Modbus 연결. 생성자 호출 전에는 장치 라이브러리를 import하지 않는다."""

import time
from numbers import Real
from uuid import uuid4

from app.assembly_motion import vector
from app.contracts import _integer


def response_vector(values, name):
    # ROS 고정 배열은 numpy 실수로 반환된다. JSON 입력 검사는 그대로 유지한다.
    values = list(values)
    if len(values) != 6 or any(isinstance(v, bool) or not isinstance(v, Real) for v in values):
        raise ValueError(f"{name}: expected 6 real numbers")
    return vector([float(v) for v in values], 6, name)


class AssemblyMotionRos:
    mode = "REAL"

    def __init__(self, config, *, node=None):
        import rclpy
        from rclpy.signals import SignalHandlerOptions
        from dsr_msgs2 import srv
        from pymodbus.client import ModbusTcpClient
        self.config, self.ros, self.srv = config, rclpy, srv
        self.clients, self.gripper, self.node = {}, None, None
        self.external_executor = node is not None
        connection = config["connection"]
        self.prefix = f"/{connection['robot_id']}/dsr_controller2/"
        # CLI의 SIGINT/SIGTERM 처리 중 STOP을 요청할 수 있도록 ROS 자동 shutdown을 막는다.
        if not self.external_executor:
            rclpy.init(args=[], signal_handler_options=SignalHandlerOptions.NO)
        try:
            self.node = node if node is not None else rclpy.create_node(f"assembly_noncontact_{uuid4().hex[:8]}")
            self.client("motion/move_stop", "MoveStop")
            self.gripper = ModbusTcpClient(connection["gripper_ip"], port=502,
                                          timeout=config["timing"]["service_timeout_s"])
            if not self.gripper.connect():
                raise ConnectionError("GRIPPER_READ_CONNECTION_FAILED")
        except BaseException:
            self.close()
            raise

    def client(self, path, typename):
        if path not in self.clients:
            self.clients[path] = self.node.create_client(getattr(self.srv, typename), self.prefix+path)
        return self.clients[path]

    def call(self, path, typename, **fields):
        client = self.client(path, typename)
        timeout = self.config["timing"]["service_timeout_s"]
        if path.startswith("force/"):
            # Force-mode ACK may arrive later than a sensor-read ACK. Reuse the
            # configured stop window; do not resend a possibly accepted command.
            timeout=max(timeout,self.config["timing"].get("stop_timeout_s",timeout))
        if not client.wait_for_service(timeout_sec=timeout):
            raise TimeoutError(f"SERVICE_UNAVAILABLE: {path}")
        request = getattr(self.srv, typename).Request()
        for field, value in fields.items():
            setattr(request, field, value)
        future = client.call_async(request)
        if getattr(self, 'external_executor', False):
            deadline = time.monotonic()+timeout
            while not future.done() and time.monotonic() < deadline:
                time.sleep(.01)
        else:
            self.ros.spin_until_future_complete(self.node, future, timeout_sec=timeout)
        if not future.done():
            raise TimeoutError(f"SERVICE_RESPONSE_TIMEOUT: {path}")
        response = future.result()
        if response is None or response.success is not True:
            raise RuntimeError(f"SERVICE_FAILED: {path}")
        return response

    def motion_feedback(self):
        begin = time.monotonic()
        joints = response_vector(self.call("aux_control/get_current_posj", "GetCurrentPosj").pos, "joints")
        posx = response_vector(self.call("motion/fkin", "Fkin", pos=joints, ref=0).conv_posx, "FK pose")
        speed = response_vector(self.call("aux_control/get_current_velx", "GetCurrentVelx", ref=0).vel, "tool velocity")
        status = self.call("motion/check_motion", "CheckMotion").status
        return dict(posj=joints, posx=posx, velx=speed, motion_status=status,
                    query_started_monotonic_s=begin, query_duration_s=time.monotonic()-begin,
                    query_finished_monotonic_s=time.monotonic())

    def _register(self, address):
        result = self.gripper.read_holding_registers(address=address, count=1, slave=65)
        if result.isError() or len(result.registers) != 1:
            raise ConnectionError(f"GRIPPER_READ_FAILED: {address}")
        return result.registers[0]

    def sample(self):
        begin = time.monotonic()
        result = self.motion_feedback()
        result.update(robot_state=self.call("system/get_robot_state", "GetRobotState").robot_state,
                      robot_mode=self.call("system/get_robot_mode", "GetRobotMode").robot_mode,
                      drl_state=self.call("drl/get_drl_state", "GetDrlState").drl_state,
                      tcp=self.call("tcp/get_current_tcp", "GetCurrentTcp").info,
                      tool=self.call("tool/get_current_tool", "GetCurrentTool").info,
                      wrench=response_vector(self.call("aux_control/get_tool_force", "GetToolForce", ref=0).tool_force, "wrench"))
        # One RG2 feedback block replaces four network round trips. Preserve
        # raw/offset-aware width semantics and the signed fingertip offset.
        feedback = self.gripper.read_holding_registers(address=258, count=18, slave=65)
        if feedback.isError() or len(feedback.registers) != 18:
            raise ConnectionError("GRIPPER_READ_FAILED: 258..275")
        registers = feedback.registers
        result.update(gripper_status=registers[10], gripper_width_mm=registers[9]/10)
        offset = registers[0]
        result["gripper_fingertip_offset_mm"] = (offset if offset < 32768 else offset-65536)/10
        result["gripper_width_with_offset_mm"] = registers[17]/10
        result["query_duration_s"] = time.monotonic()-begin
        result["query_started_monotonic_s"] = begin
        result["query_finished_monotonic_s"] = time.monotonic()
        return result

    def check_pose(self, pose, *, max_joint_delta_deg=None):
        joints = response_vector(self.call("aux_control/get_current_posj", "GetCurrentPosj").pos, "joints")
        sol = self.call("aux_control/get_solution_space", "GetSolutionSpace", pos=joints).sol_space
        _integer(sol, 0, 7, "solution space")
        target_joints = response_vector(self.call("motion/ikin", "Ikin", pos=pose, sol_space=sol, ref=0).conv_posj, "IK joints")
        if max_joint_delta_deg is not None:
            if type(max_joint_delta_deg) not in (int,float) or not 0 < max_joint_delta_deg <= 10:
                raise ValueError("INVALID_LOCAL_JOINT_STEP_LIMIT")
            # Do not wrap modulo 360: an equivalent orientation can still demand
            # a large wrist move. Local trials reject it before issuing motion.
            if max(abs(a-b) for a,b in zip(target_joints,joints)) > max_joint_delta_deg:
                raise RuntimeError("LOCAL_IK_JOINT_JUMP")
        return response_vector(self.call("motion/fkin", "Fkin", pos=target_joints, ref=0).conv_posx, "FK pose")

    def move_line_async(self, pose, velocity, acceleration):
        self.call("motion/move_line", "MoveLine", pos=pose, vel=velocity, acc=acceleration,
                  time=0., radius=0., ref=0, mode=0, blend_type=0, sync_type=1)

    def move_blending_async(self, targets, radius, velocity, acceleration):
        import math
        if not isinstance(targets,list) or not 2 <= len(targets) <= 50:
            raise ValueError('DOOSAN_BLEND_POINT_COUNT_REQUIRED')
        radii = radius if isinstance(radius,list) else [radius]*len(targets)
        if (len(radii)!=len(targets) or any(type(v) not in (int,float) or
                not math.isfinite(v) or v < 0 for v in radii)):
            raise ValueError('FINITE_NONNEGATIVE_SEGMENT_RADII_REQUIRED')
        for values in (velocity, acceleration):
            if len(values) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in values):
                raise ValueError('POSITIVE_FINITE_BLEND_RATES_REQUIRED')
        from std_msgs.msg import Float64MultiArray
        segments = []
        for target,segment_radius in zip(targets,radii):
            segment = Float64MultiArray()
            segment.data = [*vector(target, 6, 'blend target'), *([0.]*6), 0., float(segment_radius)]
            segments.append(segment)
        self.call('motion/move_blending', 'MoveBlending', segment=segments, pos_cnt=len(segments),
                  vel=velocity, acc=acceleration, time=0., ref=0, mode=0, sync_type=1)

    def command_gripper(self, width_mm, force_n):
        # Same RG2 register/unit/command as the existing yellow4_row_to_place.Gripper.
        # ACK is not completion: the integration runner polls actual status and width.
        if (type(width_mm) not in (int, float) or not 0 <= width_mm <= 110
                or type(force_n) not in (int, float) or not 0 < force_n <= 40):
            raise ValueError("INVALID_RG2_COMMAND")
        if self._register(268) not in (0, 2):
            raise RuntimeError("GRIPPER_NOT_IDLE_OR_SAFETY_ACTIVE")
        response = self.gripper.write_registers(address=0,
            values=[round(force_n * 10), round(width_mm * 10), 16], slave=65)
        if response.isError():
            raise ConnectionError("GRIPPER_WRITE_FAILED")

    def stop(self):
        self.call("motion/move_stop", "MoveStop", stop_mode=1)

    def enable_compliance(self, stiffness, transition):
        self.call("force/task_compliance_ctrl", "TaskComplianceCtrl", stx=stiffness, ref=0, time=transition)

    def set_downward_force(self, force, transition, *, relative=True):
        self.call("force/set_desired_force", "SetDesiredForce", fd=[0., 0., -force, 0., 0., 0.],
                  dir=[0, 0, 1, 0, 0, 0], ref=0, time=transition, mod=1 if relative else 0)

    def release_force(self, transition):
        self.call("force/release_force", "ReleaseForce", time=transition)

    def release_compliance(self):
        self.call("force/release_compliance_ctrl", "ReleaseComplianceCtrl")

    def robot_system(self):
        return self.call("system/get_robot_system", "GetRobotSystem").robot_system

    def check_contact_services(self, *, native_force=True):
        # Availability check only. Never enable force/compliance as a capability probe.
        services = [("force/task_compliance_ctrl", "TaskComplianceCtrl"),
            ("force/set_desired_force", "SetDesiredForce"), ("force/release_force", "ReleaseForce"),
            ("force/release_compliance_ctrl", "ReleaseComplianceCtrl"),
            ("motion/move_line", "MoveLine"), ("motion/move_stop", "MoveStop")]
        if not native_force:services=services[-2:]
        for path, kind in services:
            if not self.client(path, kind).wait_for_service(timeout_sec=self.config["timing"]["service_timeout_s"]):
                raise TimeoutError(f"SERVICE_UNAVAILABLE: {path}")
        return [self.prefix + path for path, _ in services]

    def close(self):
        if self.gripper is not None:
            self.gripper.close()  # 연결만 닫는다. 그리퍼 개방 명령이 아니다.
        if self.node is not None and not getattr(self, 'external_executor', False):
            self.node.destroy_node()
        if not getattr(self, 'external_executor', False) and self.ros.ok():
            self.ros.shutdown()
