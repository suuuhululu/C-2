"""전달 0단계 개발용 Qt/비출력 데모. 운영 HMI/Backend 연결은 후속 단계다."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from app.fake_robot_driver import FakeRobotDriver
from app.robot_controller import RobotController, load_robot_config


CONFIG = Path(__file__).resolve().parents[1] / "interfaces/fixtures/robot.json"


def create_demo():
    driver = FakeRobotDriver(ready_at_observe=True)
    controller = RobotController(load_robot_config(CONFIG), driver, lambda result: None,
                                 handover_enabled=True)
    return controller, driver


def start_transport(controller, driver):
    identity = str(uuid4())
    reply = controller.deliver(dict(execution_id=identity, brick_type="2x2x1", color="yellow"))
    if reply["accepted"]:
        driver.confirm(identity, "pick")
    return reply


def request(controller):
    active = controller.state["active_execution"]
    if active is None:
        return dict(accepted=False, reason="NO_ACTIVE_EXECUTION")
    return controller.request_handover(dict(request_id=str(uuid4()), execution_id=active["execution_id"]))


def confirm_stop(controller, driver):
    return driver.confirm_stop(controller.handover["request_id"], stopped=True,
        execution_ended=True, block_state_known=True, block_state="HOLDING")


def create_window(controller, driver):
    from PyQt5.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout

    window = QWidget()
    window.setWindowTitle("로봇 전달 개발 · 0단계 · FAKE")
    layout = QVBoxLayout(window)
    caption = QLabel("실제 장치 미연결 · 접근/그리퍼 개방 기능 없음\n"
                     "운반 시작 → 전달 요청 → 별도 정지 증거 → 수신 대기\n"
                     "취소/수신 신고 이후에는 정지를 유지합니다.")
    layout.addWidget(caption)
    status = QLabel()
    status.setWordWrap(True)
    layout.addWidget(status)
    buttons = {}

    def render(reply=None):
        handover = controller.handover
        captions = dict(IDLE="전달 요청 전", STOP_PENDING="취소/정지 요청됨 · 실제 정지 미확인",
            WAIT_RECEIVER="정지 확인 · 수신 대기", CHECK_REQUIRED="정지 유지 · 확인 필요",
            SAFETY_HOLD="안전 정지 · 별도 복구 필요")
        reasons = dict(STOP_UNCONFIRMED="정지·실행 종료·블록 보유 증거를 기다립니다.",
            CANCELLED_MANUAL_CHECK_REQUIRED="전달을 취소했습니다. 접촉 해제와 블록 상태를 확인하세요.",
            RELEASE_CONFIRMATION_UNAVAILABLE="수신 신고를 받았습니다. 개방/수신 증거가 없어 완료 처리하지 않습니다.",
            BLOCK_NOT_HELD="블록 보유를 확인할 수 없습니다.",
            PROTECTIVE_STOP="보호정지 복구 절차를 따르세요.",
            EMERGENCY_STOP="비상정지 복구 절차를 따르세요.", ROBOT_FAULT="장치 오류를 확인하세요.")
        message = reasons.get(handover["reason"], "정지 요청 결과를 확인하세요." if handover["reason"] else "")
        if isinstance(reply, dict) and not reply["accepted"]:
            message += "\n현재 상태에서는 요청을 처리할 수 없습니다."
        status.setText(captions[handover["status"]] + "\n" + message)
        buttons["start"].setEnabled(controller.state["ready_at_observe"])
        buttons["request"].setEnabled(controller.state["active_execution"] is not None and handover["status"] == "IDLE")
        buttons["stop"].setEnabled(handover["status"] == "STOP_PENDING")
        buttons["cancel"].setEnabled(handover["status"] in ("STOP_PENDING", "WAIT_RECEIVER"))
        buttons["receipt"].setEnabled(handover["status"] == "WAIT_RECEIVER")

    actions = (("start", "모의 운반 시작", lambda: start_transport(controller, driver)),
        ("request", "전달 요청", lambda: request(controller)),
        ("stop", "정지 증거 주입 · FAKE", lambda: confirm_stop(controller, driver)),
        ("cancel", "전달 취소", lambda: controller.cancel_handover(controller.handover["request_id"])),
        ("receipt", "수신 완료 신고 · 증거 미확인", lambda: controller.report_handover_receipt(controller.handover["request_id"])))
    for name, text, action in actions:
        button = QPushButton(text)
        button.clicked.connect(lambda checked=False, action=action: render(action()))
        layout.addWidget(button)
        buttons[name] = button
    window.buttons, window.status_label = buttons, status
    render()
    window.resize(520, 360)
    return window


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true", help="Qt 없이 FAKE 정상 흐름 출력")
    args = parser.parse_args(argv)
    controller, driver = create_demo()
    if args.headless:
        start_transport(controller, driver)
        request(controller)
        pending = controller.handover
        confirm_stop(controller, driver)
        print(json.dumps(dict(before_stop_evidence=pending, after_stop_evidence=controller.handover,
                              fake_calls=driver.calls), ensure_ascii=False, indent=2))
        return 0
    from PyQt5.QtWidgets import QApplication
    application = QApplication([])
    window = create_window(controller, driver)
    window.show()
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
