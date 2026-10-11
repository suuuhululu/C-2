"""MVP HMI 가짜 사례를 선택하는 화면. Backend·장치·LLM·DB 연결 없음."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from PyQt5.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QWidget

from app.hmi_contracts import validate_hmi_snapshot
from app.hmi_mvp_contracts import USER_REQUESTS, validate_user_request
from app.qt_hmi import HmiWindow


def load_snapshots():
    directory = Path(__file__).resolve().parents[1] / "interfaces/fixtures"
    snapshots = json.loads((directory / "hmi_mvp.json").read_text())["snapshots"]
    variants = json.loads((directory / "hmi_execution_cases.json").read_text())["variants"]
    for name, variant in variants.items():
        snapshot = deepcopy(snapshots[variant["base"]])
        snapshot["execution"].update(method=variant["method"], phase=variant["phase"])
        snapshot["workflow_status"] = "HOLD" if variant["phase"] == "HOLD" else "DELIVERING"
        snapshot["notice"].update(reason=None, required_action="가짜 실행 단계 표시 시험입니다. 조립 완료 근거가 아닙니다.")
        snapshots[name] = snapshot
    for name, case in json.loads((directory / "hmi_remaining_cases.json").read_text())["cases"].items():
        snapshot = deepcopy(snapshots[case["base"]])
        snapshot.update(deepcopy(case["overrides"]))
        snapshots[name] = snapshot
    return snapshots


class MvpFixtureDemo:
    def __init__(self, window, snapshots, selected, *, interactive=False):
        self.window = window
        self.interactive = interactive
        self.requests = []
        # FAKE 표기가 없는 자료는 화면 시험에 로드하지 않는다.
        self.snapshots = {name: validate_hmi_snapshot(value) for name, value in snapshots.items()}
        if any(value["monitor"]["robot"]["mode"] != "FAKE" for value in self.snapshots.values()):
            raise ValueError("MVP 화면 시험에는 FAKE 입력만 사용할 수 있습니다.")
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("FAKE · 요청 접수 시험 (장치 미연결)" if interactive else "가짜 화면 시험 · 사례 선택 (공정 조작은 비활성)"))
        self.selector = QComboBox()
        self.selector.setAccessibleName("가짜 HMI 사례 선택")
        self.selector.addItems(list(self.snapshots))
        layout.addWidget(self.selector, 1)
        window.layout().insertWidget(1, toolbar)
        self.selector.setCurrentText(selected)
        self.selector.currentTextChanged.connect(self.show_case)
        if interactive:
            window.mvp_request_requested.connect(self.receive_request)
        self.show_case(selected)

    def show_case(self, name):
        snapshot = self.snapshots[name]
        self.window.render_snapshot(snapshot)
        for button in (*self.window.buttons.values(), *self.window.refill_buttons.values()):
            button.setEnabled(False)
        if not self.interactive:
            for button in self.window.user_request_controls.buttons.values():
                button.setEnabled(False)
        self.window.footer.setText(f"FAKE · {name} · 표시 전용 · 로봇/Camera/LLM/DB 호출 없음")

    def receive_request(self, request):
        # D 접수 결과의 Fixture만 반환한다. 접수를 실행/도움 준비 완료로 변환하지 않는다.
        request = validate_user_request(request)
        self.requests.append(deepcopy(request))
        settings = json.loads((Path(__file__).resolve().parents[1] / "interfaces/fixtures/hmi_remaining_cases.json").read_text())
        reason = settings["request_rejections"].get(self.selector.currentText())
        name = next(key for key, command in USER_REQUESTS.items() if command == request["command"])
        active = self.window._snapshot
        control = active.get("user_requests", {}).get(name)
        if (request["job_id"] != active["actions"]["job_id"] or not control or not control["enabled"] or
                not control["visible"] or request["request_id"] != control["request_id"]):
            reason = "가짜 D 거절: 현재 활성 요청이 아닙니다."
        self.window.mvp_reply_received.emit(dict(**request, accepted=reason is None,
            reason=reason or "FAKE 접수입니다. 실제 동작은 수행하지 않습니다."))


def main(argv=None):
    snapshots = load_snapshots()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=snapshots, default="draft_updated")
    parser.add_argument("--interactive", action="store_true", help="FAKE 신규 요청 버튼과 접수/거절 응답만 시험")
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = HmiWindow()
    demo = MvpFixtureDemo(window, snapshots, args.case, interactive=args.interactive)
    window.show()
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
