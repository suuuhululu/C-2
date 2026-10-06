"""A/B 합성 시험 창의 실제 Qt 입력·callback·Fake 진행·로그를 검증한다."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.abd_input_hmi import AbdInputDemo
from app.qt_hmi import HmiWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def create(qapp, tmp_path):
    windows = []

    def build(scenario="normal"):
        window = HmiWindow(screen_size=QSize(1920, 1080))
        demo = AbdInputDemo(window, tmp_path, scenario=scenario, delay_ms=1)
        windows.append(window)
        window.show()
        qapp.processEvents()
        return window, demo

    yield build
    for window in windows:
        window.close()


def wait_for(demo, status):
    for _ in range(100):
        QTest.qWait(2)
        if demo.backend.state["workflow_status"] == status:
            return
    pytest.fail(f"Did not reach {status}: {demo.backend.state['workflow_status']}")


def records(demo):
    path = demo.directory / (demo.backend.state["job_id"] + ".jsonl")
    return [json.loads(line) for line in path.read_text().splitlines()]


def start(window, demo, qapp):
    window.buttons["START"].click()
    qapp.processEvents()
    assert demo.backend.state["reason"] == "WAIT_PLACE_EMPTY"
    assert window.design_board.blocks == demo.design["blocks"]
    assert not demo.driver.calls
    assert next(row for row in records(demo) if row["event"] == "PLAN_RESULT")["result"]["status"] == "READY"


def transfer(demo):
    demo.receive(dict(event="place_empty"))
    wait_for(demo, "WAIT_ASSEMBLY")


def test_normal_qt_start_actual_a_b_callback_three_steps_before_final_confirmation(create, qapp, tmp_path, monkeypatch):
    window, demo = create()
    captured = []
    original = demo.b.deliver_example

    def deliver(case, callback):
        captured.append(deepcopy(case["vision_result"]))
        return original(case, callback)

    monkeypatch.setattr(demo.b, "deliver_example", deliver)
    start(window, demo, qapp)
    for index in range(3):
        transfer(demo)
        qapp.processEvents()
        assert f"조립 확인 {index} / 3" in window.progress.text()
        assert window.status.text() != "전체 조립 완료"
        assert demo.backend.state["current"]["current_revision"] == index
        if index == 2:
            assert window.grab().save(str(tmp_path / "before-final.png"))
        demo.receive(dict(event="observe"))
        qapp.processEvents()
        assert demo.backend.state["current"]["current_revision"] == index + 1
        assert len(demo.driver.calls) == (index + 1) * 3
    assert window.status.text() == "전체 조립 완료"
    assert "조립 확인 3 / 3" in window.progress.text()
    assert "B 합성 callback" in window.notice.toPlainText()
    assert len(captured) == 3 and len({p["check_id"] for p in captured}) == 3
    assert all(p["observation_seq"] == 0 for p in captured)
    assert sum(row["event"] == "JOB_COMPLETED" for row in records(demo)) == 1
    inputs = [row["result"] for row in records(demo) if row["event"] == "SYNTHETIC_OBSERVATION_INPUT"]
    assert "D 추가 합성" in inputs[1]["source"]
    final = json.loads(next(tmp_path.glob("*.snapshot.json")).read_text())
    assert final["snapshot"]["progress"] == dict(completed=3, total=3)
    assert final["current"] == demo.backend.state["current"]
    assert window.grab().save(str(tmp_path / "complete.png"))


@pytest.mark.parametrize("scenario,workflow,completed,revision", [
    ("mismatch", "WAIT_INTENT", 0, 1),
    ("verified-empty", "WAIT_INTENT", 0, 0),
    ("occluded", "HOLD", 0, 1),
    ("lower-occluded", "HOLD", 1, 2),
    ("place-unobservable", "HOLD", 1, 1),
])
def test_independent_b_scenarios_show_result_without_auto_next_pick(create, qapp, tmp_path, scenario, workflow, completed, revision):
    window, demo = create(scenario)
    start(window, demo, qapp)
    transfer(demo)
    demo.receive(dict(event="observe"))
    qapp.processEvents()
    assert demo.backend.state["workflow_status"] == workflow
    assert len(demo.driver.calls) == 3
    assert demo.backend.state["current"]["current_revision"] == revision
    assert f"조립 확인 {completed} / 2" in window.progress.text()
    if scenario == "mismatch":
        assert window.table.item(1, 1).text() == "노랑"
        assert window.table.item(1, 2).text() == "파랑"
        assert demo.backend.state["context"]["design"]["blocks"][0]["color"] == "yellow"
    elif scenario == "verified-empty":
        assert demo.backend.state["comparison"] == "MISMATCH"
        assert demo.backend.state["current"]["blocks"] == []
    elif scenario == "occluded":
        before = demo.backend.state["current"]
        assert before == demo.seed
        identity = demo.backend.state["active_check"]["check_id"]
        demo.receive(dict(event="observe"))
        assert demo.sequences[identity] == 1
        assert demo.backend.state["current"] == before and len(demo.driver.calls) == 3
    elif scenario == "lower-occluded":
        assert demo.b.block() in demo.backend.state["current"]["blocks"]
        assert demo.b.block("blue", 2) in demo.backend.state["current"]["blocks"]
    else:
        fresh = demo.backend.state["place_check"]["check_id"]
        assert demo.requests[-1] == ("vision", dict(check_id=fresh, after=None))
        demo.receive(dict(event="place_unobservable"))
        qapp.processEvents()
        assert "camera_view_occluded" in window.notice.toPlainText()
        assert demo.backend.state["place_status"] == "UNOBSERVABLE"
        assert len(demo.driver.calls) == 3
        assert window.grab().save(str(tmp_path / "place-unobservable.png"))
        demo.receive(dict(event="place_empty"))
        assert len(demo.driver.calls) == 4
        wait_for(demo, "WAIT_ASSEMBLY")
    filename = "after-fresh-empty.png" if scenario == "place-unobservable" else f"{scenario}.png"
    assert window.grab().save(str(tmp_path / filename))


@pytest.mark.parametrize("value", [dict(event="unknown"), dict(event="observe", check_id="made-up"),
                                    dict(event="place_empty", confirmed=False), {}, None])
def test_invalid_or_unavailable_terminal_input_never_starts_fake_driver(create, value):
    _, demo = create()
    with pytest.raises(ValueError):
        demo.receive(value)
    assert demo.backend.state["job_id"] is None and not demo.driver.calls


@pytest.mark.parametrize("stage", ["place", "assembly"])
def test_stop_resume_qt_buttons_and_late_b_result_keep_original_check(create, qapp, stage):
    window, demo = create()
    start(window, demo, qapp)
    if stage == "assembly":
        transfer(demo)
        identity = demo.backend.state["active_check"]["check_id"]
        old, _ = demo.assembly_case(identity, 0)
    before = demo.backend.state["current"]
    window.buttons["STOP"].click()
    wait_for(demo, "STOPPED")
    qapp.processEvents()
    assert window.buttons["RESUME"].isEnabled()
    with pytest.raises(ValueError):
        demo.receive(dict(event="observe" if stage == "assembly" else "place_empty"))
    window.buttons["RESUME"].click()
    wait_for(demo, "WAIT_ASSEMBLY" if stage == "assembly" else "HOLD")
    qapp.processEvents()
    assert demo.backend.state["current"] == before
    if stage == "assembly":
        assert demo.backend.state["active_check"]["check_id"] != identity
        assert not demo.b.deliver_example(old, demo.backend.on_observation)
        assert demo.backend.state["current"] == before
        demo.receive(dict(event="observe"))
        assert demo.backend.state["current"]["current_revision"] == 1
    else:
        assert demo.backend.state["reason"] == "WAIT_PLACE_EMPTY"
        assert not any(op == "pick" for op, _ in demo.driver.calls)


def test_input_before_fake_return_is_rejected(create, qapp):
    window, demo = create()
    start(window, demo, qapp)
    demo.receive(dict(event="place_empty"))
    before = demo.backend.state["current"]
    with pytest.raises(ValueError):
        demo.receive(dict(event="observe"))
    wait_for(demo, "WAIT_ASSEMBLY")
    assert demo.backend.state["current"] == before


@pytest.mark.parametrize("scenario,revision", [("lower-occluded", 3), ("place-unobservable", 2)])
def test_additional_d_synthetic_frame_completes_remaining_step(create, qapp, scenario, revision):
    window, demo = create(scenario)
    start(window, demo, qapp)
    transfer(demo)
    demo.receive(dict(event="observe"))
    assert len(demo.backend.state["context"]["confirmed_steps"]) == 1
    transfer(demo)
    assert demo.backend.state["workflow_status"] == "WAIT_ASSEMBLY"
    demo.receive(dict(event="observe"))
    qapp.processEvents()
    assert window.status.text() == "전체 조립 완료"
    assert demo.backend.state["current"]["current_revision"] == revision
    assert len(demo.driver.calls) == 6
    final_input = [row for row in records(demo) if row["event"] == "SYNTHETIC_OBSERVATION_INPUT"][-1]
    assert "D 추가 합성" in final_input["result"]["source"]


def test_cli_requires_explicit_synthetic_flag_and_exits_on_eof(tmp_path):
    root = Path(__file__).resolve().parents[2]
    bad = subprocess.run([sys.executable, "-m", "app.abd_input_hmi"], cwd=root,
                         capture_output=True, text=True, timeout=10)
    assert bad.returncode == 2 and "--synthetic-b" in bad.stderr
    good = subprocess.run([sys.executable, "-m", "app.abd_input_hmi", "--synthetic-b", "--log-dir", str(tmp_path)],
                          cwd=root, input='not-json\n{"event":"observe"}\n', capture_output=True, text=True, timeout=10)
    assert good.returncode == 0 and "Robot FAKE" in good.stdout
    assert "입력 오류:" in good.stdout and "입력 보류:" in good.stdout
    assert not list(tmp_path.glob("*.jsonl"))  # 창을 여는 것만으로 Job/전달을 시작하지 않는다.
