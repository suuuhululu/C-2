"""명시적 FAKE 전용 Qt 실행 예제. 실제 모듈·ROS·장치 코드를 import하지 않는다."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.contracts import _integer, validate_design, validate_plan, validate_observed
from app.fake_robot_driver import FakeRobotDriver
from app.hmi_board import dimensions
from app.jsonl_log import JsonlLog
from app.qt_hmi import HmiWindow
from app.robot_controller import RobotController, load_robot_config
from app.snapshot import make_snapshot


FIXTURE_PATH = Path(__file__).resolve().parents[1]/"interfaces/fixtures/day4.json"
ROBOT_CONFIG_PATH = FIXTURE_PATH.parent/"robot.json"
SCENARIOS = ("normal", "keep", "revise", "unclear", "hri-failure",
             "robot-pick-failure", "robot-return-failure", "robot-timeout")


class FakeDemo:
    def __init__(self, window, log_directory, *, delay_ms=350, scenario="normal",
                 robot_config=ROBOT_CONFIG_PATH, fixture_path=FIXTURE_PATH):
        if scenario not in SCENARIOS:
            raise ValueError("Unsupported Fake scenario")
        _integer(delay_ms, 0, None, "Fake delay_ms")
        self.window, self.delay_ms = window, delay_ms
        self.robot_config_path, self.fixture_path = Path(robot_config), Path(fixture_path)
        self._load_fixture()
        self.scenario = scenario
        self._actual, self._mismatched, self._correction_ready = [], False, False
        self._robot_failed = False
        self.backend = Backend(self.emit, mode="FAKE", record=JsonlLog(log_directory))
        self.driver = FakeRobotDriver(ready_at_observe=True, on_request=self.driver_request)
        self.controller = RobotController(load_robot_config(self.robot_config_path), self.driver,
            self.backend.on_robot_result, on_stopped=self.backend.on_stopped, on_event=self.backend.on_robot_event)
        self.backend.connect_robot(self.controller, config_loader=lambda: load_robot_config(self.robot_config_path))
        window.command_requested.connect(self.command)
        self.publish()

    def _load_fixture(self):
        fixtures = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        validate_design(fixtures["design"])
        validate_plan(fixtures["initial_plan"])
        validate_plan(fixtures["completed_plan"])
        validate_observed(fixtures["observed_mismatch"])
        blocks = fixtures["design"]["blocks"]
        if len(blocks) != 3 or [step["after"] for step in fixtures["initial_plan"]["steps"]] != blocks:
            raise ValueError("Fake demo requires an ordered three-Step Fixture")
        self.fixtures = fixtures
        self.regions = [dict(x=block["x"], y=block["y"], layer=block["layer"],
                             width=dimensions(block)[0], height=dimensions(block)[1]) for block in blocks]

    def publish(self):
        self.window.snapshot_received.emit(make_snapshot(self.backend.state))

    def command(self, command):
        if command["command"] == "START" and self.backend.state["workflow_status"] in ("IDLE", "COMPLETE"):
            try:
                self._load_fixture()
            except (OSError, ValueError, KeyError) as error:
                self.window.footer.setText(f"FAKE · Fixture 입력 오류: {error}")
                return
        result = self.backend.command(command)
        if result["accepted"] and command["command"] == "START":
            self._actual, self._mismatched, self._correction_ready = [], False, False
            self._robot_failed = False
        if result["accepted"] and command["command"] == "CONTINUE_AFTER_CORRECTION":
            self._correction_ready = True
        self.publish()
        if not result["accepted"]:
            self.window.footer.setText(f"FAKE · 요청 보류: {result['reason']}")

    def driver_request(self, operation, payload):
        QTimer.singleShot(self.delay_ms, lambda: self.driver_result(operation, payload))
        self.publish()

    def driver_result(self, operation, payload):
        if operation == "stop":
            self.driver.confirm_stop(payload["request_id"], stopped=True, execution_ended=True,
                                     block_state_known=True, block_state=self.driver.block_state)
        else:
            failure_at = {"robot-pick-failure":"pick", "robot-return-failure":"observe", "robot-timeout":"pick"}
            if not self._robot_failed and operation == failure_at.get(self.scenario):
                reason = "TIMEOUT" if self.scenario == "robot-timeout" else "모의 Robot 실행 실패"
                self._robot_failed = self.driver.fail(payload["execution_id"], operation, reason)
            else:
                self.driver.confirm(payload["execution_id"], operation)
        self.publish()

    def confirm_robot_cleanup(self):
        """원격 시험용 별도 정리 증거. STOP/시작 버튼이 자동 호출하지 않는다."""
        self.driver.confirm_cleanup(ready_at_observe=True, gripper_empty=True)
        result = self.backend.on_robot_cleanup(self.backend.state["job_id"])
        self.publish()
        return result

    def emit(self, port, payload):
        # 지연 콜백도 원래 요청 식별을 돌려준다. 수신 시점의 새 실행에 붙이지 않는다.
        payload = deepcopy(payload)
        QTimer.singleShot(self.delay_ms, lambda: self.receive(port,payload))

    def receive(self, port, payload):
        if port == "planner":
            if "design" not in payload:
                self.backend.on_plan_result(payload["request_id"],
                    dict(status="READY",plan=self.fixtures["initial_plan"],errors=[]),design=self.fixtures["design"])
            else:
                self._replan_fixture(payload)
        elif port == "vision":
            state = self.backend.state
            active = state["current_check"] or state["active_check"] or state["place_check"]
            if active is None or active["check_id"] != payload["check_id"]:
                self.backend.on_failure("vision", payload["check_id"], "closed Fake check")
                self.publish()
                return
            check = self.backend.state["current_check"]
            if check and check["check_id"] == payload["check_id"]:
                if self._correction_ready and self.backend.state["current_check_purpose"] == "CORRECTION":
                    self._actual = deepcopy(self.fixtures["design"]["blocks"][:2])
                    self._correction_ready = False
                self.backend.on_observation(dict(check_id=payload["check_id"],observation_seq=0,status="OK",
                    visible_blocks=deepcopy(self._actual),verified_regions=self.regions,reason=None))
            elif payload["after"] is not None:
                self.backend.on_place(payload["check_id"], 0, "EMPTY")
                # 고정 3-Step Fixture만 제공한다. Planner/인식 알고리즘을 대체 구현하지 않는다.
                index = self.fixtures["design"]["blocks"].index(payload["after"])
                blocks = self.fixtures["design"]["blocks"][:index+1] if index<2 else [payload["after"]]
                regions = self.regions[:index+1] if index<2 else [self.regions[2]]
                if index == 2 and self.scenario in ("keep", "revise", "unclear", "hri-failure") and not self._mismatched:
                    blocks = deepcopy(self.fixtures["observed_mismatch"]["visible_blocks"])
                    self._mismatched = True
                self._actual = deepcopy(self.fixtures["design"]["blocks"][:index]+blocks[-1:])
                self.backend.on_observation(dict(check_id=payload["check_id"], observation_seq=0, status="OK",
                                                 visible_blocks=blocks, verified_regions=regions, reason=None))
            else:
                self.backend.on_place(payload["check_id"], 0, "EMPTY")
        elif port == "hri":
            request = self.backend.state["question_request"]
            if request and request["request_id"] == payload["request_id"]:
                self._hri_fixture(payload)
            else:
                self.backend.on_question(payload["request_id"], "closed Fake question")
        else:
            raise ValueError(f"Unsupported Fake port: {port}")
        self.publish()

    def _replan_fixture(self, payload):
        if payload["design"]["design_version"] == 1 and len(payload["current"]["blocks"]) == 3:
            errors = [dict(reason="원래 파랑 목표를 유지하려면 2층 노랑 6점을 정리해야 합니다. PLACE 추가로 해결할 수 없습니다.",
                           block=block) for block in self.fixtures["observed_mismatch"]["visible_blocks"]]
            self.backend.on_plan_result(payload["request_id"],
                                        dict(status="NEEDS_CORRECTION",plan=None,errors=errors))
            return
        plan = deepcopy(self.fixtures["completed_plan"])
        plan.update(plan_id="fake-replan-"+payload["request_id"],design_version=payload["design_version"],
                    base_current_revision=payload["base_current_revision"])
        if len(payload["current"]["blocks"]) == 2:
            plan["steps"] = [deepcopy(self.fixtures["initial_plan"]["steps"][2])]
            plan["steps"][0]["prerequisites"] = []
        self.backend.on_plan_result(payload["request_id"],dict(status="READY",plan=plan,errors=[]))

    def _hri_fixture(self, payload):
        request_id = payload["request_id"]
        question = "파랑 대신 노랑이 관측됐습니다. 원래 목표 유지에는 노랑 블록 정리가 필요하고, " \
                   "목표 수정에는 전체 목표 검증이 필요합니다. 원래 목표 유지를 권장합니다. 어느 쪽으로 할까요?"
        if self.scenario == "hri-failure":
            self.backend.on_failure("hri",request_id,"모의 HRI 호출 실패")
        elif payload.get("choice") == "REVISE" or self.scenario == "revise":
            design = deepcopy(self.fixtures["design"])
            design.update(design_version=2)
            design["blocks"][2] = deepcopy(self.fixtures["observed_mismatch"]["visible_blocks"][0])
            self.backend.on_intent(dict(request_id=request_id,decision="REVISE",design=design))
        elif self.scenario == "keep":
            self.backend.on_intent(dict(request_id=request_id,decision="KEEP"))
        else:
            self.backend.on_question(request_id,question)
            self.backend.on_intent(dict(request_id=request_id,decision="UNCLEAR",question=question))
            # 두 개의 고정 모의 음성 응답이다. Backend의 자동 재질문/LLM 루프가 아니다.
            active = self.backend.state["question_request"]
            if active:
                next_request_id = active["request_id"]
                QTimer.singleShot(self.delay_ms,lambda: self._second_unclear(next_request_id,question))

    def _second_unclear(self, request_id, question):
        self.backend.on_intent(dict(request_id=request_id,decision="UNCLEAR",question=question))
        self.publish()


def main():
    parser = argparse.ArgumentParser(description="실제 장치 미연결 Day4 Qt 예제")
    parser.add_argument("--fake-demo", action="store_true", required=True)
    parser.add_argument("--log-dir", type=Path, default=Path("/tmp/c2-day4-fake-logs"))
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--robot-config", type=Path, default=ROBOT_CONFIG_PATH)
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--delay-ms", type=int, default=350)
    args = parser.parse_args()
    application = QApplication(sys.argv[:1])
    window = HmiWindow()
    demo = FakeDemo(window,args.log_dir,scenario=args.scenario,robot_config=args.robot_config,
                    fixture_path=args.fixture,delay_ms=args.delay_ms)
    window.show()
    application.exec_()
    return demo


if __name__ == "__main__":
    main()
