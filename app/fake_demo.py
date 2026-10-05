"""명시적 FAKE 전용 Qt 실행 예제. 실제 모듈·ROS·장치 코드를 import하지 않는다."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.jsonl_log import JsonlLog
from app.qt_hmi import HmiWindow
from app.snapshot import make_snapshot


FIXTURES = json.loads((Path(__file__).resolve().parents[1]/"interfaces/fixtures/day4.json").read_text())
REGIONS = [dict(x=3,y=5,width=2,height=2,layer=1), dict(x=5,y=5,width=2,height=2,layer=1),
           dict(x=3,y=5,width=3,height=2,layer=2)]


class FakeDemo:
    def __init__(self, window, log_directory, *, delay_ms=350, scenario="normal"):
        if scenario not in ("normal","keep","revise","unclear","hri-failure"):
            raise ValueError("Unsupported Fake scenario")
        self.window, self.delay_ms = window, delay_ms
        self.scenario = scenario
        self._actual, self._mismatched, self._correction_ready = [], False, False
        self.backend = Backend(self.emit, mode="FAKE", record=JsonlLog(log_directory))
        self.backend.controller_ready(ready=True, at_observe_point=True)
        window.command_requested.connect(self.command)
        self.publish()

    def publish(self):
        self.window.snapshot_received.emit(make_snapshot(self.backend.state))

    def command(self, command):
        result = self.backend.command(command)
        if result["accepted"] and command["command"] == "START":
            self._actual, self._mismatched, self._correction_ready = [], False, False
        if result["accepted"] and command["command"] == "CONTINUE_AFTER_CORRECTION":
            self._correction_ready = True
        self.publish()
        if not result["accepted"]:
            self.window.footer.setText(f"FAKE · 요청 보류: {result['reason']}")

    def emit(self, port, payload):
        # 지연 콜백도 원래 요청 식별을 돌려준다. 수신 시점의 새 실행에 붙이지 않는다.
        payload = deepcopy(payload)
        QTimer.singleShot(self.delay_ms, lambda: self.receive(port,payload))

    def receive(self, port, payload):
        if port == "planner":
            if "design" not in payload:
                self.backend.on_plan(payload["request_id"], FIXTURES["design"], FIXTURES["initial_plan"])
            else:
                self._replan_fixture(payload)
        elif port in ("robot.deliver","robot.resume"):
            self.backend.on_robot_result(dict(execution_id=payload["execution_id"], success=True, reason=None))
        elif port == "robot.stop":
            self.backend.on_stopped(payload["request_id"], stopped=True, execution_ended=True, block_state_known=True)
        elif port == "vision":
            check = self.backend.state["current_check"]
            if check and check["check_id"] == payload["check_id"]:
                if self._correction_ready and self.backend.state["current_check_purpose"] == "CORRECTION":
                    self._actual = deepcopy(FIXTURES["design"]["blocks"][:2])
                    self._correction_ready = False
                self.backend.on_observation(dict(check_id=payload["check_id"],observation_seq=0,status="OK",
                    visible_blocks=deepcopy(self._actual),verified_regions=REGIONS,reason=None))
            elif payload["after"] is not None:
                self.backend.on_place(payload["check_id"], 0, "EMPTY")
                # 고정 3-Step Fixture만 제공한다. Planner/인식 알고리즘을 대체 구현하지 않는다.
                index = FIXTURES["design"]["blocks"].index(payload["after"])
                blocks = FIXTURES["design"]["blocks"][:index+1] if index<2 else [payload["after"]]
                regions = REGIONS[:index+1] if index<2 else [REGIONS[2]]
                if index == 2 and self.scenario != "normal" and not self._mismatched:
                    blocks = deepcopy(FIXTURES["observed_mismatch"]["visible_blocks"])
                    self._mismatched = True
                self._actual = deepcopy(FIXTURES["design"]["blocks"][:index]+blocks[-1:])
                self.backend.on_observation(dict(check_id=payload["check_id"], observation_seq=0, status="OK",
                                                 visible_blocks=blocks, verified_regions=regions, reason=None))
            else:
                self.backend.on_place(payload["check_id"], 0, "EMPTY")
        elif port == "hri":
            self._hri_fixture(payload)
        else:
            raise ValueError(f"Unsupported Fake port: {port}")
        self.publish()

    def _replan_fixture(self, payload):
        if payload["design"]["design_version"] == 1 and len(payload["current"]["blocks"]) == 3:
            self.backend.on_plan_result(payload["request_id"],dict(status="NEEDS_CORRECTION",
                reason="원래 파랑 목표를 유지하려면 2층 노랑 6점을 정리해야 합니다. PLACE 추가로 해결할 수 없습니다.",
                conflicts=FIXTURES["observed_mismatch"]["visible_blocks"]))
            return
        plan = deepcopy(FIXTURES["completed_plan"])
        plan.update(plan_id="fake-replan-"+payload["request_id"],design_version=payload["design_version"],
                    base_current_revision=payload["base_current_revision"])
        if len(payload["current"]["blocks"]) == 2:
            plan["steps"] = [deepcopy(FIXTURES["initial_plan"]["steps"][2])]
            plan["steps"][0]["prerequisites"] = []
        self.backend.on_plan_result(payload["request_id"],dict(status="READY",plan=plan))

    def _hri_fixture(self, payload):
        request_id = payload["request_id"]
        question = "파랑 대신 노랑이 관측됐습니다. 원래 목표 유지에는 노랑 블록 정리가 필요하고, " \
                   "목표 수정에는 전체 목표 검증이 필요합니다. 원래 목표 유지를 권장합니다. 어느 쪽으로 할까요?"
        if self.scenario == "hri-failure":
            self.backend.on_failure("hri",request_id,"모의 HRI 호출 실패")
        elif payload.get("choice") == "REVISE" or self.scenario == "revise":
            design = deepcopy(FIXTURES["design"])
            design.update(design_version=2)
            design["blocks"][2] = deepcopy(FIXTURES["observed_mismatch"]["visible_blocks"][0])
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
    parser.add_argument("--scenario",choices=("normal","keep","revise","unclear","hri-failure"),default="normal")
    args = parser.parse_args()
    application = QApplication(sys.argv[:1])
    window = HmiWindow()
    demo = FakeDemo(window,args.log_dir,scenario=args.scenario)
    window.show()
    application.exec_()
    return demo


if __name__ == "__main__":
    main()
