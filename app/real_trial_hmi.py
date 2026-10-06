"""기존 HMI/Backend와 한 블록 CLI를 연결하는 단일 실제 전달 시험."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import uuid4

from PyQt5.QtCore import QEvent, QObject, QProcess, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.contracts import _integer, _object, _text
from app.hmi_contracts import _column
from app.jsonl_log import JsonlLog
from app.qt_hmi import HmiWindow
from app.robot_trial import load_trial_config
from app.snapshot import make_snapshot


class RealTrialController(QObject):
    changed = pyqtSignal()

    def __init__(self, config_path, log_directory, *, brick_type, color, slot, process_factory=QProcess, delivery_limit=1):
        super().__init__()
        self.target = dict(brick_type=brick_type, color=color, slot=slot)
        _column(self.target, "trial.target")
        _integer(slot, 1, 6, "trial.target.slot")
        _integer(delivery_limit, 1, 3, "trial.delivery_limit")
        if slot + delivery_limit - 1 > 6:
            raise ValueError("Trial needs consecutive prepared slots within 1..6")
        self._start_slot, self._limit, self._attempts = slot, delivery_limit, 0
        self.config_path, self.directory = Path(config_path), Path(log_directory) / str(uuid4())
        self._factory = process_factory
        self._config = None
        self._checked_config = None
        self._ready = self._used = self._pick_confirmed = False
        self._released = self._returned = False
        self._next_slot = slot
        self._identity = self._operation = self.process = None
        self._seen = set()
        self._events_read = 0
        self._final = self._check_complete = None
        self._fault = self._notice = None
        self.on_result = self.on_event = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)

    @property
    def state(self):
        supported = self._config is not None
        caption = f"{'파랑' if self.target['color'] == 'blue' else '노랑'} {'4점' if self.target['brick_type'] == '2x2x1' else '6점'} {self.target['slot']}번"
        return dict(mode="REAL", config_id=self._config["config_id"] if self._config else None,
                    transfer_target=deepcopy(self.target),
                    ready_at_observe=self._ready, cleanup_ready=False, stop=None, fault=self._fault,
                    active_execution=dict(execution_id=self._identity) if self._operation == "execute" else None,
                    trial_notice=f"전달 대상: {caption} · 고정 전달판\n" + (self._notice or "한 번만 전달"),
                    supply=[dict(brick_type=brick, color=color,
                                 next_slot=self._next_slot if supported and (brick, color) == (self.target["brick_type"], self.target["color"]) else None,
                                 needs_refill=self._next_slot is None if supported and (brick, color) == (self.target["brick_type"], self.target["color"]) else None)
                            for brick in ("2x2x1", "2x3x1") for color in ("yellow", "blue")])

    @property
    def configuration(self):
        return dict(trial=deepcopy(self._config), target=deepcopy(self.target))

    def _read_config(self):
        config = load_trial_config(self.config_path)
        supported = config.get("pick_line", dict(brick_type="2x2x1", color="yellow"))
        if any(supported[field] != self.target[field] for field in ("brick_type", "color")):
            raise ValueError(f"공급열 설정 불일치: {self.target['color']} {self.target['brick_type']} {self.target['slot']}번. 다른 열로 대체하지 않습니다.")
        config["slot"] = self._start_slot
        if not all(flag for name, flag in config["confirmations"].items() if name != "empty_place_and_slot"):
            raise ValueError("현장 감시/장치 설정/복귀 조건 확인이 필요합니다.")
        return config

    def check(self):
        if self._operation is not None or self._used:
            return False
        try:
            self._config = self._read_config()
            self._checked_config = deepcopy(self._config)
            self._fault = None
            self._notice = "실제 무이동 조회 중입니다. 아직 시작할 수 없습니다."
            self._launch("check", str(uuid4()))
            return True
        except (OSError, ValueError) as error:
            self._ready = False
            self._fault = self._notice = str(error)
            self.changed.emit()
            return False

    def new_job(self, config=None):
        if config is not None:
            return dict(accepted=False, reason="REAL_TRIAL_CONFIG_OVERRIDE_UNAVAILABLE")
        if not self._ready or self._used:
            return dict(accepted=False, reason="REAL_TRIAL_NOT_READY")
        try:
            if self._read_config() != self._checked_config:
                return dict(accepted=False, reason="CONFIG_CHANGED_RECHECK_REQUIRED")
        except (OSError, ValueError) as error:
            return dict(accepted=False, reason=str(error))
        # HMI START는 이번 슬롯의 블록·빈 전달판을 사람이 확인한 입력이다.
        # 조회 성공이나 Fake 관측으로 이 확인을 대신하지 않는다.
        self._config = deepcopy(self._checked_config)
        self._config["confirmations"]["empty_place_and_slot"] = True
        return dict(accepted=True, reason=None)

    def deliver(self, value):
        goal = _object(value, ("execution_id", "brick_type", "color"), "robot.goal")
        _text(goal["execution_id"], "robot.goal.execution_id")
        _column(goal, "robot.goal")
        if goal["execution_id"] in self._seen:
            return dict(accepted=False, reason="DUPLICATE")
        if self._operation is not None:
            return dict(accepted=False, reason="BUSY")
        if self._attempts == 0:
            if not self.new_job()["accepted"]:
                return dict(accepted=False, reason="REAL_TRIAL_NOT_READY")
        else:
            if not self._ready or self._fault or self._attempts >= self._limit or self._next_slot is None:
                return dict(accepted=False, reason="REAL_TRIAL_NOT_READY")
            try:
                if self._read_config() != self._checked_config:
                    return dict(accepted=False, reason="CONFIG_CHANGED_RECHECK_REQUIRED")
            except (OSError, ValueError) as error:
                return dict(accepted=False, reason=str(error))
        if any(goal[field] != self.target[field] for field in ("brick_type", "color")):
            return dict(accepted=False, reason="UNVERIFIED_TARGET")
        if self._limit > 1:
            self.target["slot"] = self._next_slot
            self._config["slot"] = self.target["slot"]
        self._attempts += 1
        self._pick_confirmed = self._released = self._returned = False
        self._seen.add(goal["execution_id"])
        self._used, self._ready = True, False
        self._notice = "실제 한 블록 전달 중입니다. 다음 전달은 터미널 현장 확인 뒤 진행합니다." if self._limit > 1 else "실제 한 블록 전달 중입니다. 자동 다음 전달은 없습니다."
        self._launch("execute", goal["execution_id"])
        return dict(accepted=True, reason=None)

    def _launch(self, operation, identity):
        self.directory.mkdir(parents=True, exist_ok=True)
        config_path = self.directory / "adopted_config.json"
        config_path.write_text(json.dumps(self._config, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        self._identity, self._operation = identity, operation
        self._events_read = 0
        self._final = self._check_complete = None
        self.process = self._factory(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.process.finished.connect(lambda code, status: self._finished(identity, code, status))
        self.process.errorOccurred.connect(lambda error: self._process_error(identity, error))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.start(sys.executable, ["-m", "app.robot_trial", "--config", str(config_path),
                            f"--{operation}", "--execution-id", identity, "--require-observe-start",
                            "--log-dir", str(self.directory / "driver")])
        self.timer.start()
        self.changed.emit()

    def _output(self):
        output = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        if output:
            self._notice = output.splitlines()[-1]
            self.changed.emit()

    def _poll(self):
        try:
            self._read_events()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._fault = f"DRIVER_LOG_INVALID: {error}"
            self._ready = False
            self._notice = self._fault + " · 프로세스 종료를 실제 정지로 해석하지 않습니다."
            self.timer.stop()
            self.changed.emit()

    def _read_events(self):
        if self._identity is None:
            return
        path = self.directory / "driver" / f"{self._identity}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except FileNotFoundError:
            return  # 자식 프로세스가 첫 기록을 쓰기 전이다. 성공으로 처리하지 않는다.
        for line in lines[self._events_read:]:
            if not line.endswith("\n"):
                break
            event = json.loads(line)
            self._events_read += 1
            if event.get("execution_id") != self._identity:
                continue
            name, payload = event["event"], event["payload"]
            if name == "ROBOT_CHECK_COMPLETE":
                self._check_complete = payload
            if self._operation != "execute":
                continue
            if name == "ROBOT_TRIAL_RESULT":
                if self._final is None:
                    _object(payload, ("execution_id", "success", "reason"), "driver.result")
                    if payload["execution_id"] != self._identity or type(payload["success"]) is not bool:
                        raise ValueError("Driver result identity/boolean invalid")
                    if payload["success"] and payload["reason"] is not None:
                        raise ValueError("Successful driver result requires null reason")
                    if not payload["success"]:
                        _text(payload["reason"], "driver.result.reason")
                    self._final = payload
                else:
                    continue
            elif name == "ROBOT_PICK_CONFIRMED" and not self._pick_confirmed:
                if payload["slot"] != self.target["slot"]:
                    raise ValueError("Driver pick slot differs from adopted target")
                self._pick_confirmed = True
                if payload["next_slot"] is not None:
                    _integer(payload["next_slot"], 1, 6, "driver.next_slot")
                if payload["next_slot"] != (self.target["slot"] + 1 if self.target["slot"] < 6 else None):
                    raise ValueError("Driver next slot differs from confirmed pick")
                self._next_slot = payload["next_slot"]
            elif name == "ROBOT_PICK_CONFIRMED":
                continue
            elif name == "ROBOT_RELEASE_CONFIRMED":
                self._released = True
            elif name == "ROBOT_RETURN_CONFIRMED":
                self._returned = True
            if self.on_event is not None and not self.on_event(name, self._identity, self.state):
                self._fault = "BACKEND_LOG_FAILED"
            self.changed.emit()

    def _process_error(self, identity, error):
        if error == QProcess.FailedToStart:
            self._finished(identity, -1, QProcess.CrashExit)

    def _finished(self, identity, code, status):
        if identity != self._identity or self._operation is None:
            return
        self._poll()
        operation = self._operation
        self._operation = None
        self.timer.stop()
        if operation == "check":
            self._ready = code == 0 and status == QProcess.NormalExit and self._check_complete is not None and self._check_complete.get("motion_commands_sent") is False and self._fault is None
            self._notice = f"무이동 조회 완료. {'파랑' if self.target['color'] == 'blue' else '노랑'} 4점 {self.target['slot']}번 준비·전달판 비움을 확인하고 시작하세요. 첫 실기 시험이며 한 번만 전달합니다." if self._ready else f"조회 실패: {self._fault or self._notice or code}"
            if self._ready and self._limit > 1:
                self._notice = f"무이동 조회 완료. 공급 슬롯 {self._start_slot}~{self._start_slot+self._limit-1} 준비·조립판/전달판 비움을 확인하고 시작하세요. 현장 확인마다 한 번씩 전달합니다."
        else:
            result = self._final if code == 0 and status == QProcess.NormalExit and self._fault is None else None
            if result is None:
                result = dict(execution_id=identity, success=False, reason=self._fault or f"DRIVER_EXIT_{code}_WITHOUT_VALID_RESULT")
            if result["success"] and not (self._pick_confirmed and self._released and self._returned):
                result = dict(execution_id=identity, success=False, reason="DELIVERY_EVIDENCE_MISSING")
            self._ready = result["success"]
            self._fault = result["reason"]
            self._notice = "한 블록 전달·복귀 완료. 실제 조립 관측은 미연결이며 추가 실행은 차단합니다." if result["success"] else f"오류 보류: {result['reason']}"
            if result["success"] and self._limit > 1:
                self._notice = "전달·observe 복귀 완료. 터미널 현장 확인을 기다립니다."
            if self.on_result:
                self.on_result(result)
        self.changed.emit()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Close and self._operation == "execute":
            self._notice = "실행/조회 중에는 창을 유지합니다. 실제 긴급 정지는 현장 비상정지 장치를 사용하세요."
            self.changed.emit()
            event.ignore()
            return True
        if event.type() == QEvent.Close and self._operation == "check":
            self.process.terminate()  # 조회 전용 자식 종료이며 Robot 정지로 해석하지 않는다.
            self.process.waitForFinished(1000)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-trial", action="store_true", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--brick-type", required=True, choices=("2x2x1", "2x3x1"))
    parser.add_argument("--color", required=True, choices=("yellow", "blue"))
    parser.add_argument("--slot", required=True, type=int, choices=range(1, 7))
    parser.add_argument("--log-dir", default="logs/robot_hmi")
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = HmiWindow()
    controller = RealTrialController(args.config, args.log_dir, brick_type=args.brick_type, color=args.color, slot=args.slot)
    backend = Backend(lambda port, payload: None, mode="REAL", single_trial=True,
                      record=JsonlLog(Path(args.log_dir) / "backend"))
    backend.connect_robot(controller)
    controller.on_result, controller.on_event = backend.on_robot_result, backend.on_robot_event

    def publish():
        if backend.state["job_id"] is None:
            ready = controller.state["ready_at_observe"]
            backend.controller_ready(ready=ready, at_observe_point=ready)
        window.snapshot_received.emit(make_snapshot(backend.state))

    def command(value):
        reply = backend.command(value)
        publish()
        if not reply["accepted"]:
            window.footer.setText(f"REAL · 요청 보류: {reply['reason']}")

    controller.changed.connect(publish)
    window.command_requested.connect(command)
    window.installEventFilter(controller)
    publish()
    window.show()
    QTimer.singleShot(0, controller.check)
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
