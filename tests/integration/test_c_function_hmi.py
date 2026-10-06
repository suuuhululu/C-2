"""PR #11 원본 C 함수→실제 A→D/Qt. 네트워크는 C HTTP 경계에서 Fake다."""

from copy import deepcopy
from threading import Event
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.abd_input_hmi import AbdInputDemo
from app.c_design import llm, main as c_main
from app.c_text_connection import differences_for_c
from app.qt_hmi import HmiWindow
from test_abd_input_hmi import records, transfer, wait_for

ROOT = Path(__file__).resolve().parents[2]
INITIAL = json.loads((ROOT / "interfaces/fixtures/c_design_initial_result.json").read_text())
REVISED = json.loads((ROOT / "interfaces/fixtures/c_design_revised_result.json").read_text())


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def settled(demo):
    for _ in range(300):
        QTest.qWait(2)
        if not demo.c_connection.active:
            QApplication.instance().processEvents()
            return
    pytest.fail("C call did not settle")


@pytest.fixture
def create(qapp, tmp_path, monkeypatch):
    windows = []

    def build(mode="offline", text="의자 만들어줘", key=True):
        monkeypatch.setenv("C_DESIGN_USE_LLM", "1" if mode == "live" else "0")
        monkeypatch.setenv("OPENAI_API_KEY", "test-secret-not-a-real-key" if key else "")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
        window = HmiWindow(screen_size=QSize(1920, 1080))
        demo = AbdInputDemo(window, tmp_path, c_mode=mode, initial_text=text, delay_ms=1)
        windows.append((window, demo))
        window.show()
        qapp.processEvents()
        window.buttons["START"].click()
        qapp.processEvents()
        return window, demo

    yield build
    for window, demo in windows:
        demo.c_connection.close()
        settled(demo)
        window.close()


def mismatch_after_eight(demo):
    for _ in range(8):
        transfer(demo)
        demo.receive(dict(event="observe"))
    transfer(demo)
    target = demo.backend._next_step()["after"]
    assert target == dict(brick_type="2x3x1", color="yellow", x=9, y=9, layer=2, orientation_deg=90)
    demo.receive(dict(event="observe", actual={**target, "color": "blue"}))
    settled(demo)
    assert demo.backend.state["workflow_status"] == "WAIT_INTENT"
    assert len(demo.backend.state["context"]["confirmed_steps"]) == 8


def reply(demo, text):
    identity = demo.backend.state["question_request"]["request_id"]
    demo.receive(dict(event="answer", request_id=identity, text=text))
    settled(demo)


def test_difference_adapter_color_pair_moved_missing_extra_and_no_mutation():
    expected = INITIAL["design"]["blocks"][0]
    actual = {**expected, "color": "blue" if expected["color"] == "yellow" else "yellow"}
    difference = dict(missing=[expected], unexpected=[actual], unobservable=[])
    before = deepcopy(difference)
    assert differences_for_c(difference) == [dict(expected=expected, actual=actual)]
    moved = {**actual, "x": actual["x"] + 5}
    assert differences_for_c({**difference, "unexpected": [moved]}) == [
        dict(expected=expected, actual=None), dict(expected=None, actual=moved)]
    assert differences_for_c({**difference, "unexpected": []}) == [dict(expected=expected, actual=None)]
    assert difference == before


@pytest.mark.parametrize("difference", [dict(missing=[], unexpected=[], unobservable=[]),
                                        dict(missing=[], unexpected=[], unobservable=["target"]), None])
def test_empty_or_unreadable_difference_is_not_a_c_intent(difference):
    with pytest.raises(ValueError):
        differences_for_c(difference)


def test_actual_c_offline_initial_full_job_only_completes_after_observation(create, qapp, tmp_path):
    window, demo = create()
    settled(demo)
    expected = c_main.create_initial_design(text="의자 만들어줘")["design"]
    assert window.design_board.blocks == expected["blocks"]
    assert not demo.driver.calls
    assert len(demo.backend.state["context"]["plan"]["steps"]) == 15
    for index in range(15):
        transfer(demo)
        assert demo.backend.state["workflow_status"] == "WAIT_ASSEMBLY"
        assert len(demo.backend.state["context"]["confirmed_steps"]) == index
        demo.receive(dict(event="observe"))
        if index < 14:
            assert demo.backend.state["place_check"] is not None
            assert len(demo.driver.calls) == (index + 1) * 3
    qapp.processEvents()
    assert window.status.text() == "전체 조립 완료"
    assert demo.backend.state["current"]["current_revision"] == 15
    assert sum(row["event"] == "JOB_COMPLETED" for row in records(demo)) == 1
    assert window.grab().save(str(tmp_path / "c-function-complete.png"))


def test_live_mode_actual_c_llm_http_fake_revise_actual_a_preserves_current(create, monkeypatch, qapp):
    calls = []

    def http(payload, key):
        calls.append(deepcopy(payload))
        candidate = INITIAL if len(calls) == 1 else REVISED
        return dict(choices=[dict(message=dict(content=json.dumps(candidate["design"])) )])

    monkeypatch.setattr(llm, "_post_json", http)
    window, demo = create("live")
    settled(demo)
    mismatch_after_eight(demo)
    current = demo.backend.state["current"]
    assert demo.backend.state["unclear_count"] == 0  # 질문 미리보기는 UNCLEAR 의도 응답이 아니다.
    assert "색" in window.notice.toPlainText()
    reply(demo, "2번")
    context = demo.backend.state["context"]
    assert len(calls) == 2 and all(p["model"] == "gpt-4o" for p in calls)
    assert context["design"] == REVISED["design"]
    assert context["base_current"] == current and demo.backend.state["current"] == current
    assert len(context["plan"]["steps"]) == 10
    assert len(demo.driver.calls) == 27  # Revised만으로 새 집기를 시작하지 않는다.
    for _ in range(10):
        transfer(demo)
        demo.receive(dict(event="observe"))
    qapp.processEvents()
    assert window.status.text() == "전체 조립 완료"
    assert len(demo.backend.state["current"]["blocks"]) == 19
    assert "test-secret" not in json.dumps(records(demo))


@pytest.mark.parametrize("answer,workflow", [("1번", "WAIT_CORRECTION"), ("취소", "HOLD")])
def test_actual_c_keep_or_explicit_cancel_holds_next_transfer(create, answer, workflow):
    _, demo = create()
    settled(demo)
    mismatch_after_eight(demo)
    current, design = demo.backend.state["current"], demo.backend.state["context"]["design"]
    reply(demo, answer)
    assert demo.backend.state["workflow_status"] == workflow
    assert demo.backend.state["current"] == current and demo.backend.state["context"]["design"] == design
    assert len(demo.driver.calls) == 27
    if answer == "취소":
        assert "CANCELLED" in demo.backend.state["reason"] and "USER_CANCEL" in demo.backend.state["reason"]


def test_unclear_waits_explicit_choice_without_automatic_repetition(create):
    _, demo = create()
    settled(demo)
    mismatch_after_eight(demo)
    old = demo.backend.state["question_request"]["request_id"]
    reply(demo, "모르겠어요")
    assert demo.backend.state["question_request"]["request_id"] != old
    with pytest.raises(ValueError):
        demo.receive(dict(event="answer", request_id=old, text="2번"))
    reply(demo, "모르겠어요")
    assert demo.backend.state["choice_required"] and not demo.c_connection.active
    before = len(records(demo))
    QTest.qWait(20)
    assert len(records(demo)) == before and len(demo.driver.calls) == 27


@pytest.mark.parametrize("failure", ["missing_key", "auth"])
def test_live_c_failure_has_no_mock_fallback_or_robot_pick(create, monkeypatch, failure):
    if failure == "auth":
        import urllib.error
        def http(*args):
            raise urllib.error.HTTPError(llm.API_URL, 401, "unauthorized", {}, None)
        monkeypatch.setattr(llm, "_post_json", http)
    window, demo = create("live", key=failure != "missing_key")
    settled(demo)
    assert demo.backend.state["workflow_status"] == "HOLD"
    assert "LLM_CALL_FAILED" in demo.backend.state["reason"]
    assert not window.design_board.blocks and not demo.driver.calls


def test_stop_during_c_initial_keeps_ui_responsive_and_ignores_late_result(create, monkeypatch):
    entered, release = Event(), Event()
    original = c_main.create_initial_design

    def blocked(**kwargs):
        entered.set()
        assert release.wait(2)
        return original(text=kwargs["text"])

    monkeypatch.setattr(c_main, "create_initial_design", blocked)
    window, demo = create()
    try:
        assert entered.wait(1)
        window.buttons["STOP"].click()
        wait_for(demo, "STOPPED")
        assert demo.c_connection.active[2].is_set()
    finally:
        release.set()
    settled(demo)
    assert demo.backend.state["context"] is None and not demo.driver.calls[1:]
    assert demo.backend.state["workflow_status"] == "STOPPED"
    assert any(r["event"] == "LATE_RESULT_IGNORED" for r in records(demo))


def test_actual_c_unsupported_goal_is_failure_without_fallback(create):
    _, demo = create(text="자동차 만들어줘")
    settled(demo)
    assert demo.backend.state["workflow_status"] == "HOLD"
    assert "UNSUPPORTED_OBJECT" in demo.backend.state["reason"]
    assert demo.backend.state["context"] is None and not demo.driver.calls


def test_current_changes_during_revised_c_call_old_response_does_not_adopt(create, monkeypatch):
    entered, release = Event(), Event()
    calls = []

    def http(payload, key):
        calls.append(payload)
        if len(calls) > 1:
            entered.set()
            assert release.wait(2)
        response = INITIAL if len(calls) == 1 else REVISED
        return dict(choices=[dict(message=dict(content=json.dumps(response["design"])) )])

    monkeypatch.setattr(llm, "_post_json", http)
    _, demo = create("live")
    settled(demo)
    mismatch_after_eight(demo)
    design = demo.backend.state["context"]["design"]
    identity = demo.backend.state["question_request"]["request_id"]
    demo.receive(dict(event="answer", request_id=identity, text="2번"))
    try:
        assert entered.wait(1)
        state = demo.backend.state
        blocks = deepcopy(state["current"]["blocks"])
        blocks[0]["color"] = "yellow"
        observation = dict(check_id=state["current_check"]["check_id"], observation_seq=0, status="OK",
                           visible_blocks=blocks, verified_regions=[demo.b.region(layer=i) for i in range(1, 5)],
                           reason=None)
        assert demo.b.deliver_example(dict(vision_result=observation), demo.backend.on_observation)
        demo.publish()
        assert demo.backend.state["current"]["current_revision"] == 10
        adopted_current = demo.backend.state["current"]
    finally:
        release.set()
    settled(demo)
    assert demo.backend.state["context"]["design"] == design
    assert demo.backend.state["current"] == adopted_current and len(demo.driver.calls) == 27
    assert any(r["event"] == "LATE_RESULT_IGNORED" and r["request_id"] == identity for r in records(demo))


def test_duplicate_c_initial_result_does_not_replan_or_transfer(create):
    _, demo = create()
    settled(demo)
    payload = demo.requests[0][1]
    response = next(r["result"]["response"] for r in records(demo) if r["event"] == "C_CALL_RESULT")
    before = demo.backend.state
    demo.c_connection.finish(("initial", payload, response, False))
    assert demo.backend.state == before and not demo.driver.calls
    assert sum(r["event"] == "PLAN_RESULT" for r in records(demo)) == 1


def test_live_cli_requires_key_and_explicit_llm_mode(tmp_path):
    import os
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", C_DESIGN_USE_LLM="1")
    env.pop("OPENAI_API_KEY", None)
    command = [sys.executable, "-m", "app.abd_input_hmi", "--synthetic-b", "--c-mode", "live"]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "OPENAI_API_KEY is not set" in result.stderr
    env["C_DESIGN_USE_LLM"] = "0"
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "C_DESIGN_USE_LLM must match" in result.stderr
