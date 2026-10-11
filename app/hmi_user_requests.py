"""HMI 요청 발행과 D 접수 응답 표시. 실제 실행은 D 수신부의 책임이다."""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QTextBrowser, QWidget

from app.hmi_mvp_contracts import USER_REQUESTS, validate_user_reply, validate_user_request


CAPTIONS = dict(change_design="설계 변경 요청", home="홈 복귀 요청", assistance_ready="도움 준비됨")


class UserRequestControls(QWidget):
    requested = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._snapshot = None
        self._pending, self._sent = {}, set()
        self._last = None
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        row = QHBoxLayout()
        self.buttons = {}
        for name, caption in CAPTIONS.items():
            button = QPushButton(caption)
            button.clicked.connect(lambda checked=False, name=name: self._request(name))
            row.addWidget(button)
            self.buttons[name] = button
        root.addLayout(row, 1)
        self.feedback = QTextBrowser()
        self.feedback.setOpenExternalLinks(False)
        self.feedback.setFixedHeight(34)
        self.feedback.hide()
        root.addWidget(self.feedback, 2)
        self.hide()

    def _identities(self):
        requests = self._snapshot.get("user_requests", {}) if self._snapshot else {}
        job = self._snapshot["actions"]["job_id"] if self._snapshot else None
        return {name: (USER_REQUESTS[name], job, control["request_id"]) for name, control in requests.items() if control["visible"]}

    def render_snapshot(self, snapshot):
        if self._snapshot and self._snapshot["actions"]["job_id"] != snapshot["actions"]["job_id"]:
            self._sent.clear()
        self._snapshot = snapshot
        active = set(self._identities().values())
        self._pending = {identity: name for identity, name in self._pending.items() if identity in active}
        if self._last not in active:
            self.feedback.clear()
            self.feedback.hide()
            self._last = None
        self.setVisible(bool(active))
        self._refresh_buttons()

    def _refresh_buttons(self):
        requests = self._snapshot.get("user_requests", {}) if self._snapshot else {}
        identities = self._identities()
        for name, button in self.buttons.items():
            control = requests.get(name)
            button.setVisible(bool(control and control["visible"]))
            button.setEnabled(bool(control and control["enabled"] and identities.get(name) not in self._sent))

    def _request(self, name):
        if not self.buttons[name].isEnabled():
            return
        identity = self._identities()[name]
        request = validate_user_request(dict(zip(("command", "job_id", "request_id"), identity)))
        self._sent.add(identity)
        self._pending[identity] = name
        self._last = identity
        self.feedback.setPlainText(CAPTIONS[name] + " · 전송됨, 접수 결과 대기")
        self.feedback.show()
        self._refresh_buttons()
        self.requested.emit(request)

    def receive_reply(self, value):
        reply = validate_user_reply(value)
        identity = tuple(reply[key] for key in ("command", "job_id", "request_id"))
        if identity not in self._pending or identity not in self._identities().values():
            return False
        name = self._pending.pop(identity)
        self._last = identity
        message = "요청 접수 · 실행 완료 아님" if reply["accepted"] else "요청 거절: " + reply["reason"]
        self.feedback.setPlainText(CAPTIONS[name] + " · " + message + ("\n" + reply["reason"] if reply["accepted"] and reply["reason"] else ""))
        self.feedback.show()
        return True
