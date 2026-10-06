"""가짜 C + 실제 A + 실제 3회 전달 + 시험용 현장 수동 관측. Camera 연결 없음."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Thread

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.contracts import _object, validate_block, validate_design
from app.current import _placements
from app.hmi_board import dimensions
from app.jsonl_log import JsonlLog
from app.planning_connection import run_planning_request
from app.qt_hmi import HmiWindow
from app.real_trial_hmi import RealTrialController
from app.snapshot import make_snapshot
from app.step_input_hmi import InputBridge


class WorkflowTrial:
    def __init__(self, window, controller, fixture_path, log_directory):
        self.window, self.controller = window, controller
        self.fixture_path = Path(fixture_path)
        self.response = None
        self.backend = Backend(self.emit, mode="REAL", manual_trial=True, record=JsonlLog(log_directory))
        self.backend.connect_robot(controller)
        controller.on_result, controller.on_event = self.backend.on_robot_result, self.backend.on_robot_event
        controller.changed.connect(self.publish)
        window.command_requested.connect(self.command)
        window.installEventFilter(controller)
        self.publish()

    def publish(self, message=None):
        if self.backend.state["job_id"] is None:
            ready = self.controller.state["ready_at_observe"]
            self.backend.controller_ready(ready=ready, at_observe_point=ready)
        snapshot = make_snapshot(self.backend.state)
        if message:
            snapshot["notice"]["required_action"] = message
        self.window.snapshot_received.emit(snapshot)

    def command(self, command):
        if command["command"] == "START" and self.backend.state["job_id"] is None:
            try:
                response = json.loads(self.fixture_path.read_text(encoding="utf-8"))
                design = validate_design(response["design"])
                if len(design["blocks"]) != 3 or any(
                    block[field] != self.controller.target[field]
                    for block in design["blocks"] for field in ("brick_type", "color")
                ):
                    raise ValueError("시험 Design은 지정 공급열과 일치하는 블록 3개여야 합니다.")
                self.response = response
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.publish(f"C Fixture 입력 보류: {error}")
                return dict(accepted=False, reason=str(error))
        reply = self.backend.command(command)
        self.publish()
        print(json.dumps(reply, ensure_ascii=False), flush=True)
        return reply

    def emit(self, port, payload):
        print(json.dumps(dict(request=port, payload=payload), ensure_ascii=False), flush=True)
        if port == "planner":
            if "design" in payload:
                run_planning_request(self.backend, payload)
            else:
                self.backend.on_initial_design(payload["request_id"], deepcopy(self.response))
        elif port == "hri":
            self.backend.on_failure(port, payload["request_id"], "MANUAL_TRIAL_HRI_NOT_CONNECTED")
        elif port == "vision":
            event = "place_empty" if payload["after"] is None else "assembly"
            instruction = ("전달판이 비었고 손·장애물이 경로에서 벗어났으면" if event == "place_empty" else
                           f"기존 조립을 유지한 채 현재 목표 {payload['after']}대로 조립했고 전달판이 비었으며 손을 뺐으면")
            print(instruction + " 아래 JSON을 같은 터미널에 입력하세요:", flush=True)
            print(json.dumps(dict(event=event, check_id=payload["check_id"], confirmed=True)), flush=True)
            if event == "assembly":
                print("잘못 놓았으면 아래 신고를 입력하세요. 로그/화면에 보류하며 다음 전달은 없습니다:", flush=True)
                print(json.dumps(dict(event=event, check_id=payload["check_id"], confirmed=False)), flush=True)
                print("잘못 놓인 좌표도 표시하려면 신고 JSON에 actual 블록 여섯 필드를 추가하세요. 기존 조립은 유지 확인한 것으로 받습니다.", flush=True)
                print("좌표를 알면 위 신고 대신 아래 actual 양식의 값을 실제 배치로 바꿔 입력하세요. 현재 값은 목표를 복사한 양식입니다:", flush=True)
                print(json.dumps(dict(event=event, check_id=payload["check_id"], confirmed=False, actual=payload["after"])), flush=True)

    def receive(self, value):
        extra = ("actual",) if isinstance(value, dict) and "actual" in value else ()
        value = _object(value, ("event", "check_id", "confirmed") + extra, "manual.input")
        if (value["event"] not in ("place_empty", "assembly") or type(value["confirmed"]) is not bool or
                value["event"] == "place_empty" and not value["confirmed"]):
            raise ValueError("place_empty는 confirmed=true, assembly는 confirmed=true/false여야 합니다.")
        state = self.backend.state
        check = state["place_check"] if value["event"] == "place_empty" else state["active_check"]
        if (check is None or check["check_id"] != value["check_id"] or state["fault"] or
                (value["event"] == "assembly" and state["workflow_status"] != "WAIT_ASSEMBLY") or
                state["execution_id"] is not None or not self.controller.state["ready_at_observe"]):
            raise ValueError("닫힌/오래된 check 또는 Robot 실행/오류 중 확인은 채택하지 않습니다.")
        misplaced = value["event"] == "assembly" and not value["confirmed"]
        if extra and not misplaced:
            raise ValueError("actual 배치는 assembly/confirmed=false 신고에만 입력합니다.")
        target = self.backend._next_step()["after"] if value["event"] == "assembly" else None
        actual = validate_block(value["actual"]) if extra else None
        if actual == target and actual is not None:
            raise ValueError("actual이 현재 목표와 같습니다. 잘못 놓았다는 신고 좌표를 확인하세요.")
        blocks = None
        if value["event"] == "assembly" and (not misplaced or actual is not None):
            blocks = _placements(deepcopy(state["current"]["blocks"]) + [actual or deepcopy(target)],
                                 "manual.blocks", allow_duplicates=False)
        event = "MANUAL_ASSEMBLY_MISMATCH" if misplaced else "MANUAL_FIELD_CONFIRMATION"
        if not self.backend._event(event, request_id=value["check_id"], result=value):
            self.publish()
            return False
        observed = None
        if blocks is not None:
            regions = []
            # 좌표 신고에는 현재 목표 영역도 확인한 빈/다른 영역으로 포함한다.
            for block in blocks + ([target] if misplaced else []):
                width, height = dimensions(block)
                regions.append(dict(x=block["x"], y=block["y"], layer=block["layer"], width=width, height=height))
            # 운영자가 기존 조립 유지와 현재 블록 배치를 확인한 시험 입력이다.
            # 같은 색 아래층/기존 블록의 이동 여부를 Camera 없이 추정하지 않는다.
            observed = dict(check_id=value["check_id"], observation_seq=0, status="OK",
                visible_blocks=blocks, verified_regions=regions, reason=None)
        if misplaced:
            return self._report_misplaced(observed, actual, target)
        accepted = self.backend.on_place(value["check_id"], 0, "EMPTY")
        if observed is not None:
            accepted = self.backend.on_observation(observed) and accepted
        self.publish()
        return accepted

    def _report_misplaced(self, observed, actual, target):
        if observed is not None:
            self.backend.on_observation(observed)
            state = self.backend.state
            accepted = not state["fault"] and state["comparison"] == "MISMATCH"
        else:
            # 좌표가 없는 신고는 Observed를 만들거나 Current를 지울 근거가 아니다.
            accepted = True
        if accepted:
            if actual is not None:
                self.backend._state["manual_reported_placement"] = actual
            self.backend._hold("MANUAL_ASSEMBLY_MISMATCH")
        state = self.backend.state
        self.publish()
        print(json.dumps(dict(accepted=accepted, result="MISPLACED_REPORTED", source="MANUAL_REPORT",
            actual=actual, target=target, current_revision=state["current"]["current_revision"],
            completed_steps=len(state["context"]["confirmed_steps"]), next_delivery=False), ensure_ascii=False), flush=True)
        return accepted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-workflow", action="store_true", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--c-fixture", default="interfaces/fixtures/c_three_blue4.json")
    parser.add_argument("--color", default="blue", choices=("blue", "yellow"))
    parser.add_argument("--first-slot", type=int, default=1, choices=range(1, 5))
    parser.add_argument("--log-dir", default="logs/real_workflow")
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = HmiWindow()
    controller = RealTrialController(args.config, args.log_dir, brick_type="2x2x1", color=args.color,
                                     slot=args.first_slot, delivery_limit=3)
    trial = WorkflowTrial(window, controller, args.c_fixture, Path(args.log_dir) / "backend")
    bridge = InputBridge()

    def receive(value):
        try:
            trial.receive(value)
        except (OSError, ValueError, KeyError, TypeError) as error:
            trial.publish(f"현장 입력 보류: {error}")
            print(f"입력 보류: {error}", flush=True)

    bridge.received.connect(receive, Qt.QueuedConnection)
    bridge.ended.connect(window.close, Qt.QueuedConnection)
    window.show()
    print("REAL 3회 시험 · 가짜 C/실제 A/현장 수동 확인. 창 열기는 조회만 합니다.", flush=True)
    print("시작 전에 조립판·전달판 비움과 지정 공급 슬롯 3개 준비를 확인하세요.", flush=True)
    Thread(target=bridge.read, daemon=True).start()
    QTimer.singleShot(0, controller.check)
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
