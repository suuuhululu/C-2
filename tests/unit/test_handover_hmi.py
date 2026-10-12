import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import jsonschema
import pytest
from PyQt5.QtWidgets import QApplication

from app.handover_demo import CONFIG, create_demo, create_window


@pytest.mark.parametrize("action", ["cancel", "receipt"])
def test_buttons_wait_for_separate_stop_evidence_and_never_open(action):
    application = QApplication.instance() or QApplication([])
    controller, driver = create_demo()
    window = create_window(controller, driver)
    window.show()
    application.processEvents()
    try:
        assert not window.buttons["request"].isEnabled()
        window.buttons["start"].click()
        window.buttons["request"].click()
        assert controller.handover["status"] == "STOP_PENDING"
        assert not window.buttons["receipt"].isEnabled()
        assert "미확인" in window.status_label.text()
        window.buttons["stop"].click()
        assert controller.handover["status"] == "WAIT_RECEIVER"
        assert window.buttons["receipt"].isEnabled()
        window.buttons[action].click()
        assert controller.handover["status"] == "CHECK_REQUIRED"
        assert not window.buttons["receipt"].isEnabled()
        assert not window.buttons["start"].isEnabled()
        assert [call[0] for call in driver.calls] == ["pick", "place", "stop"]
    finally:
        window.close()


def test_schema_fixture_and_controller_consumer_agree():
    root = CONFIG.parents[1]
    schema = json.loads((root / "schemas/handover_request.json").read_text())
    fixture = json.loads((root / "fixtures/handover.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(fixture["valid_request"], schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(fixture["invalid_request"], schema)
    controller, driver = create_demo()
    controller.deliver(dict(execution_id="transport-1", brick_type="2x2x1", color="yellow"))
    driver.confirm("transport-1", "pick")
    with pytest.raises(ValueError):
        controller.request_handover(fixture["invalid_request"])
    assert controller.request_handover(fixture["valid_request"])["accepted"]
    assert driver.confirm_stop(**fixture["stop_evidence"])
    assert controller.handover["status"] == "WAIT_RECEIVER"
