"""Optional operator-armed RG2 opening through the existing WebLogic I/O rules."""
import time


class WebLogicGripper:
    """No robot movement or closing. Feedback means configured width >=60 mm.

    A cancelled/timed-out ROS request may already have reached the controller.
    Failure therefore latches; it never retries or sends a rollback command.
    """
    def __init__(self, node, prefix, record):
        from dsr_msgs2.srv import (GetRobotSystem, GetRobotState,
                                  SetCtrlBoxDigitalOutput, GetCtrlBoxDigitalInput)
        self.types = dict(SYSTEM=GetRobotSystem, STANDBY=GetRobotState,
                          CLOSE_OFF=SetCtrlBoxDigitalOutput, OPEN_ON=SetCtrlBoxDigitalOutput,
                          FEEDBACK=GetCtrlBoxDigitalInput)
        paths = dict(SYSTEM="system/get_robot_system", STANDBY="system/get_robot_state",
                     CLOSE_OFF="io/set_ctrl_box_digital_output",
                     OPEN_ON="io/set_ctrl_box_digital_output", FEEDBACK="io/get_ctrl_box_digital_input")
        self.clients = {step: node.create_client(self.types[step], f"{prefix.rstrip('/')}/{path}")
                        for step, path in paths.items()}
        self.record = record
        self.state, self.reason, self.request_id = "READY", None, None
        self.future = None
        self.deadline_ns = self.next_poll_ns = 0
        self.output_commands_attempted = 0
        self.used_requests = set()

    @property
    def busy(self):
        return self.state in self.clients

    def abort(self, reason):
        if self.busy:
            if self.future is not None:
                self.future.cancel()
            self.future = None
            self.state, self.reason = "FAIL", reason
            self.record(dict(kind="ABORT", request_id=self.request_id, reason=reason,
                             output_commands_attempted=self.output_commands_attempted))

    def start(self, request_id):
        if self.state == "FAIL" or self.busy or request_id in self.used_requests:
            return
        self.used_requests.add(request_id)
        self.request_id = request_id
        self.state = "SYSTEM"
        self.deadline_ns = time.monotonic_ns()+5_000_000_000

    def advance(self, eligible, received_ns):
        if not self.busy:
            return
        now = time.monotonic_ns()
        if not eligible or not 0 <= now-received_ns <= 300_000_000:
            self.abort("OPEN_HAND_LOST_OR_STALE")
            return
        if now >= self.deadline_ns:
            self.abort("GRIPPER_SEQUENCE_TIMEOUT")
            return
        if self.future is not None:
            if not self.future.done():
                return
            try:
                response = self.future.result()
            except Exception as exc:
                self.abort(f"SERVICE_EXCEPTION: {exc}")
                return
            if response is None or not response.success:
                self.abort("SERVICE_FAILED")
                return
            self.record(dict(kind="RESPONSE", step=self.state, request_id=self.request_id,
                             response=str(response)))
            self.future = None
            if self.state == "SYSTEM" and response.robot_system != 0:
                self.abort("REAL_ROBOT_REQUIRED")
                return
            if self.state == "STANDBY" and response.robot_state != 1:
                self.abort("ROBOT_NOT_STANDBY")
                return
            if self.state == "FEEDBACK":
                if response.value == 1:
                    self.state = "OPEN_FEEDBACK_CONFIRMED"
                    return
                self.next_poll_ns = now+100_000_000
            else:
                self.state = {"SYSTEM": "STANDBY", "STANDBY": "CLOSE_OFF",
                              "CLOSE_OFF": "OPEN_ON", "OPEN_ON": "FEEDBACK"}[self.state]
        if now < self.next_poll_ns:
            return
        if not all(client.service_is_ready() for client in self.clients.values()):
            self.abort("GRIPPER_SERVICES_UNAVAILABLE")
            return
        request = self.types[self.state].Request()
        if self.state in ("CLOSE_OFF", "OPEN_ON"):
            request.index = 1 if self.state == "CLOSE_OFF" else 2
            request.value = 0 if self.state == "CLOSE_OFF" else 1
        elif self.state == "FEEDBACK":
            request.index = 2
        # Persist intent before writing either hardware output; log failure stops us.
        self.record(dict(kind="REQUEST", step=self.state, request_id=self.request_id,
                         request=str(request)))
        if self.state in ("CLOSE_OFF", "OPEN_ON"):
            self.output_commands_attempted += 1
        try:
            self.future = self.clients[self.state].call_async(request)
        except Exception as exc:
            self.abort(f"SERVICE_SEND_EXCEPTION: {exc}")
