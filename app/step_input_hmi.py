"""터미널의 keyword/design/plan JSON을 순서대로 넣는 FAKE HMI. 장치 연결 없음."""

import argparse
import json
from pathlib import Path
import sys
from threading import Thread

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.contracts import _object, _text, validate_design, validate_plan
from app.jsonl_log import JsonlLog
from app.qt_hmi import HmiWindow
from app.snapshot import make_snapshot


class StepInputDemo:
    def __init__(self, window, log_directory):
        self.window = window
        self.keyword = self.design = self.request_id = None
        self.requests = []
        self.backend = Backend(self.emit, mode="FAKE", record=JsonlLog(log_directory))
        self.backend.controller_ready(ready=True, at_observe_point=True)  # FAKE 시작 조건만 주입한다.
        window.command_requested.connect(self.command)
        self.publish()

    def emit(self, port, payload):
        self.requests.append((port, payload))
        print(json.dumps(dict(request=port, payload=payload), ensure_ascii=False), flush=True)
        if port == "planner":
            self.request_id = payload["request_id"]
        elif port in ("robot.stop", "robot.resume"):
            QTimer.singleShot(0, lambda: self.robot_reply(port, payload))

    def robot_reply(self, port, payload):
        # 이 입력 창에는 장치 실행이 없다. 확인 응답만 FAKE로 공급한다.
        if port == "robot.stop":
            self.backend.on_stopped(payload["request_id"], stopped=True,
                                    execution_ended=True, block_state_known=True)
        else:
            self.backend.on_robot_result(dict(execution_id=payload["execution_id"], success=True, reason=None))
        self.publish()

    def publish(self, message=None):
        snapshot = make_snapshot(self.backend.state)
        if message is not None:
            snapshot["notice"]["required_action"] = message
        self.window.snapshot_received.emit(snapshot)

    def command(self, value):
        reply = self.backend.command(value)
        if value["command"] == "START" and reply["accepted"]:
            self.keyword = self.design = None
        self.publish()
        print(json.dumps(reply, ensure_ascii=False), flush=True)

    def receive(self, value):
        if not isinstance(value, dict) or value.get("event") not in ("keyword", "design", "plan"):
            raise ValueError("event must be keyword, design or plan")
        active = self.backend.state["planning_request"]
        if active is None or active["request_id"] != self.request_id:
            raise ValueError("먼저 HMI 시작을 누르세요. 닫힌 요청에는 입력을 채택하지 않습니다.")
        if value["event"] == "keyword":
            _object(value, ("event", "text"), "fake.keyword")
            _text(value["text"], "fake.keyword.text")
            if self.design is not None:
                raise ValueError("Design 입력 후 keyword를 덮어쓸 수 없습니다.")
            self.keyword = value["text"]
            self.backend._event("FAKE_KEYWORD_RECEIVED", request_id=self.request_id, result=dict(text=self.keyword))
            message = f"FAKE 키워드 입력: {self.keyword} · 다음은 Design Fixture입니다."
        else:
            _object(value, ("event", "file", "key"), "fake.fixture")
            _text(value["file"], "fake.fixture.file")
            _text(value["key"], "fake.fixture.key")
            fixture = json.loads(Path(value["file"]).read_text(encoding="utf-8"))[value["key"]]
            if self.keyword is None:
                raise ValueError("keyword부터 입력하세요.")
            if value["event"] == "design":
                if self.design is not None:
                    raise ValueError("Design Fixture는 한 번만 입력합니다.")
                self.design = validate_design(fixture)
                self.backend._event("FAKE_DESIGN_RECEIVED", request_id=self.request_id, result=self.design)
                message = "FAKE Design 후보 저장 · 아직 미채택. 다음은 Plan Fixture입니다."
            else:
                if self.design is None:
                    raise ValueError("Design부터 입력하세요.")
                plan = validate_plan(fixture)
                self.backend.on_plan_result(self.request_id, dict(status="READY", plan=plan, errors=[]), design=self.design)
                message = "FAKE Design/Plan 입력 처리 · 채택 상태를 화면에서 확인하세요."
        self.publish(message)
        print(message, flush=True)


class InputBridge(QObject):
    received = pyqtSignal(dict)
    ended = pyqtSignal()

    def read(self):
        for line in sys.stdin:
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("JSON object required")
                self.received.emit(value)
            except (ValueError, TypeError) as error:
                print(f"입력 오류: {error}", flush=True)
        self.ended.emit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake-inputs", action="store_true", required=True)
    parser.add_argument("--log-dir", default="logs/step_inputs")
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = HmiWindow()
    demo = StepInputDemo(window, args.log_dir)
    bridge = InputBridge()

    def receive(value):
        try:
            demo.receive(value)
        except (OSError, ValueError, KeyError, TypeError) as error:
            window.footer.setText(f"FAKE · 입력 보류: {error}")
            print(f"입력 보류: {error}", flush=True)

    bridge.received.connect(receive, Qt.QueuedConnection)
    bridge.ended.connect(window.close, Qt.QueuedConnection)
    window.show()
    print('HMI 시작 후 keyword → design → plan JSON을 한 줄씩 입력하세요. Ctrl+D로 종료.', flush=True)
    Thread(target=bridge.read, daemon=True).start()
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
