"""Day4 STT→C→A→D→실제 Robot·B 연결. 저장 Fixture·수동 관측 입력은 시험 전용이다."""

import argparse
from copy import deepcopy
from importlib import import_module
import json
import math
import os
from pathlib import Path
import sys
from uuid import uuid4

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.c_text_connection import CTextConnection
from app.jsonl_log import JsonlLog
from app.qt_hmi import HmiWindow
from app.real_design_controller import RealDesignController, load_workflow_rows
from app.snapshot import make_snapshot
from app.vision_connection import VisionConnection


class WorkflowTrial:
    def __init__(self, window, controller, log_directory, *, c_connection_factory=CTextConnection):
        self.window, self.controller = window, controller
        self.c_connection = None
        self.backend = Backend(self.emit, mode="REAL", day4_workflow=True, record=JsonlLog(log_directory))
        self.backend.connect_robot(controller)
        self.vision = VisionConnection(self.backend, self.publish)
        controller.on_result, controller.on_event = self.backend.on_robot_result, self.backend.on_robot_event
        controller.on_stopped = self.backend.on_stopped
        controller.on_timeout = self.on_timeout
        self.c_connection = c_connection_factory(self.backend, self.publish, initial_text="음성 목표 입력", voice_mode=True)
        window.destroyed.connect(self.c_connection.close)
        controller.changed.connect(self.publish)
        window.command_requested.connect(self.command)
        window.installEventFilter(controller)
        self.publish()

    def publish(self, message=None):
        if self.c_connection:
            self.c_connection.sync()
        if self.backend.state["workflow_status"] in ("IDLE", "COMPLETE"):
            ready = self.controller.state["ready_at_observe"]
            self.backend.controller_ready(ready=ready, at_observe_point=ready)
        snapshot = make_snapshot(self.backend.state)
        connected = "B 요청 연결됨 · 실제 Camera 검증 별도" if self.vision.connected else "B 미연결 · 시작 보류"
        status = self.c_connection.voice_status if self.c_connection else None
        notice = [snapshot["notice"]["required_action"], message, "STT/TTS LIVE · AI 생성 음성 · " + connected, status]
        snapshot["notice"]["required_action"] = "\n".join(item for item in notice if item)
        self.window.snapshot_received.emit(snapshot)

    def command(self, command):
        name = command["command"]
        if name == "START" and not self.vision.connected:
            self.publish("B의 실제 관측/전달판 callback 연결을 확인하세요.")
            return dict(accepted=False, reason="VISION_NOT_CONNECTED")
        if name in ("START", "RESUME") and self.c_connection.active:
            self.publish("이전 음성/API 호출 종료 후 다시 요청해주세요. 중복 녹음하지 않습니다.")
            return dict(accepted=False, reason="C_CALL_STILL_ENDING")
        reply = self.backend.command(command)
        self.publish()
        return reply

    def emit(self, port, payload):
        if port == "planner":
            if "design" in payload:
                self.check_design_plan(payload)
            else:
                self.c_connection.start("initial", payload)
        elif port == "hri":
            forced = payload.get("choice") == "REVISE"
            self.c_connection.start("intervention", payload, answers=["2번"] if forced else (), preview=not forced)
        elif port == "vision":
            self.vision.request(payload)

    def on_timeout(self, identity, operation):
        if operation == "execute" and self.backend.state["execution_id"] == identity:
            self.backend.on_robot_timeout(identity)
        else:
            self.controller.stop(dict(request_id=str(uuid4()), execution_id=identity))
        self.publish()

    def check_design_plan(self, payload):
        request = self.backend.state["planning_request"]
        if (request is None or any(payload[key] != request[key] for key in
                ("request_id", "job_id", "design_version", "base_current_revision")) or
                payload["base_current_revision"] != self.backend.state["current"]["current_revision"]):
            return self.backend._ignored(payload["request_id"])
        from planning_trial.planner import plan_from_current
        result = plan_from_current(deepcopy(payload["design"]), deepcopy(payload["current"]))
        reason = None
        if result["status"] == "READY":
            try:
                self.controller.prepare_design_plan(result["plan"])
            except (OSError, ValueError) as error:
                reason = str(error)
        report = dict(design=payload["design"], current=payload["current"], a_result=result,
                      robot_plan_accepted=reason is None and result["status"] == "READY", reason=reason)
        if not self.backend._event("REAL_PLAN_PREFLIGHT", request_id=payload["request_id"], result=report):
            return False
        print(json.dumps(dict(event="REAL_PLAN_PREFLIGHT", **report), ensure_ascii=False), flush=True)
        if reason:
            return self.backend.on_failure("planner", payload["request_id"], reason)
        return self.backend.on_plan_result(payload["request_id"], result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-workflow", action="store_true", required=True)
    parser.add_argument("--supply-manifest", required=True)
    parser.add_argument("--vision-module", required=True, help="connect(bridge)를 제공하는 B 연결 모듈")
    parser.add_argument("--robot-timeout-seconds", type=float, required=True,
                        help="현장 측정으로 정한 전달/사전 이동 최대 대기 시간")
    parser.add_argument("--log-dir", default="logs/real_workflow")
    args = parser.parse_args(argv)
    if not math.isfinite(args.robot_timeout_seconds) or args.robot_timeout_seconds <= 0:
        parser.error("--robot-timeout-seconds must be positive and finite")
    if os.environ.get("C_DESIGN_USE_LLM") != "1":
        parser.error("C_DESIGN_USE_LLM=1 is required for STT→C operation")
    for key in ("OPENAI_API_KEY", "OPENAI_TTS_API_KEY"):
        if not os.environ.get(key):
            parser.error(key + " is not set; inject it in this terminal")
    load_workflow_rows(args.supply_manifest)  # 파일·hash 확인만 수행한다.
    try:
        connect = import_module(args.vision_module).connect
        if not callable(connect):
            raise ValueError("connect must be callable")
    except (ImportError, AttributeError, ValueError) as error:
        parser.error("B connector unavailable: " + str(error))
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = HmiWindow()
    controller = RealDesignController(args.supply_manifest, args.log_dir,
                                      execution_timeout_seconds=args.robot_timeout_seconds)
    workflow = WorkflowTrial(window, controller, Path(args.log_dir) / "backend")
    connection = connect(workflow.vision)
    if not workflow.vision.connected:
        parser.error("B connect(bridge) must bind a request handler")
    workflow.publish()
    window.show()
    QTimer.singleShot(0, controller.check)
    result = application.exec_()
    workflow.c_connection.close()
    if connection is not None and hasattr(connection, "close"):
        connection.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
