"""C STT/TTS/의도 및 실제 A/D/REAL 소비 경로. HTTP·음향·ROS 실행은 Mock."""

from copy import deepcopy
import json
from pathlib import Path
from threading import Event
from urllib.parse import urljoin

import pytest
from jsonschema import Draft202012Validator, RefResolver
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.c_design import llm, voice
from app.hmi_contracts import validate_hmi_snapshot
from test_c_function_hmi import INITIAL, settled
from test_c_voice_hmi import audio
from test_real_voice_workflow import create, records, finish_confirmed_delivery
from test_real_stop_resume import probe

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "logs/real-stop-resume"


@pytest.fixture
def live(create, audio, monkeypatch):
    calls, change = [], {}

    def http(payload, key):
        calls.append(deepcopy(payload))
        design = deepcopy(INITIAL["design"])
        if len(calls) > 1:
            design["design_version"] = 2
            first = next(b for b in design["blocks"] if (b["x"], b["y"], b["layer"]) == (9, 12, 1))
            first.update(change)
        return dict(choices=[dict(message=dict(content=json.dumps(design)))])

    monkeypatch.setattr(llm, "_post_json", http)
    window, workflow, processes = create(voice_mode=True)
    window.buttons["START"].click()
    settled(workflow)
    assert workflow.receive(dict(event="place_empty"))
    finish_confirmed_delivery(workflow, processes)
    assert workflow.backend.state["workflow_status"] == "WAIT_ASSEMBLY"
    return window, workflow, processes, calls, change


def misplaced(live, audio, answer="2번", *, moved=False):
    window, workflow, processes, calls, change = live
    target = deepcopy(workflow.backend._next_step()["after"])
    change.update(x=10) if moved else change.update(color="yellow")
    actual = dict(target, **change)
    audio[0].append(answer)
    assert workflow.receive(dict(event="assembly", actual=actual))
    return target, actual


def snapshot(window):
    QApplication.instance().processEvents()
    validate_hmi_snapshot(window._snapshot)
    schema = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    common = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    Draft202012Validator(schema, resolver=RefResolver.from_schema(schema,
        store={common["$id"]: common, urljoin(schema["$id"], "day4.schema.json"): common})).validate(window._snapshot)


@pytest.mark.parametrize("answer,expected", [("1번", "WAIT_CORRECTION"), ("2번", "HOLD"), ("취소", "HOLD")])
def test_real_question_speaks_before_answer_and_only_revise_adopts_remaining(live, audio, answer, expected):
    window, workflow, processes, calls, change = live
    target, actual = misplaced(live, audio, answer)
    settled(workflow)
    state = workflow.backend.state
    assert state["workflow_status"] == expected
    assert state["current"] == dict(current_revision=1, blocks=[actual])
    assert len(processes) == 2 and workflow.controller._attempts == 1
    assert audio[1][2][0] == "tts" and audio[1][3:] == ["play", "play_finished", "record", "stt"]
    snapshot(window)
    assert "STT/TTS LIVE" in window.notice.toPlainText()
    assert window.buttons["STOP"].isEnabled()
    log = records(workflow)
    assert any(r["event"] == "C_VOICE_RESULT" and r["result"]["phase"] == "TTS_QUESTION" for r in log)
    assert not any(r["event"] == "STEP_CONFIRMED" for r in log)
    assert "mock-stt-secret" not in json.dumps(log) and "mock-tts-secret" not in json.dumps(log)
    if answer == "2번":
        assert len(calls) == 2 and state["context"]["design"]["design_version"] == 2
        assert state["context"]["base_current"] == state["current"]
        assert len(state["context"]["plan"]["steps"]) == 14
        assert all(step["after"] != actual for step in state["context"]["plan"]["steps"])
        assert len(workflow.controller.plan_columns) == 15  # 기존 1회 시도와 남은 14회 전달을 유지.
        assert workflow.controller.state["supply"][-1]["next_slot"] == 2
        assert state["reason"] == "WAIT_PLACE_EMPTY"
        assert workflow.receive(dict(event="place_empty"))
        assert len(processes) == 3 and workflow.controller.target["slot"] == 2
    else:
        assert len(calls) == 1 and state["context"]["design"]["design_version"] == 1


def test_form_change_preserved_in_real_revised_design_and_hmi(live, audio):
    window, workflow, processes, calls, change = live
    target, actual = misplaced(live, audio, moved=True)
    settled(workflow)
    state = workflow.backend.state
    assert state["current"]["blocks"] == [actual]
    assert actual in state["context"]["design"]["blocks"] and target not in state["context"]["design"]["blocks"]
    assert len(state["context"]["plan"]["steps"]) == 14
    assert len(processes) == 2 and state["place_check"] and state["place_status"] is None
    snapshot(window)
    assert actual in window.target_board.current["blocks"]
    assert window.design_board.blocks == state["context"]["design"]["blocks"]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(EVIDENCE / "real-revised-awaiting-empty.png"))
    (EVIDENCE / "mock-real-tts-revise.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records(workflow)) + "\n")
    (EVIDENCE / "real-revised.snapshot.json").write_text(json.dumps(window._snapshot, ensure_ascii=False, indent=2))


def test_keep_requires_physical_correction_report_before_actual_a_replan(live, audio):
    window, workflow, processes, calls, change = live
    target, actual = misplaced(live, audio, "1번")
    settled(workflow)
    backend = workflow.backend
    assert backend.state["workflow_status"] == "WAIT_CORRECTION"
    snapshot(window)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(EVIDENCE / "real-keep-correction.png"))
    command = dict(command="CONTINUE_AFTER_CORRECTION", job_id=backend.state["job_id"],
                   request_id=backend.state["correction_request"]["request_id"])
    assert workflow.command(command)["accepted"]
    check = backend.state["current_check"]["check_id"]
    assert backend.state["current"]["blocks"] == [actual] and len(processes) == 2
    assert workflow.receive(dict(event="current", check_id=check, confirmed=True, blocks=[actual]))
    assert backend.state["workflow_status"] == "WAIT_CORRECTION"  # 버튼·같은 배치만으로 정리 성공 아님.
    command["request_id"] = backend.state["correction_request"]["request_id"]
    workflow.command(command)
    check = backend.state["current_check"]["check_id"]
    corrected = dict(event="current", check_id=check, confirmed=True, blocks=[target])
    assert workflow.receive(corrected)
    assert backend.state["current"] == dict(current_revision=2, blocks=[target])
    assert backend.state["context"]["design"]["design_version"] == 1
    assert len(backend.state["context"]["plan"]["steps"]) == 14
    assert backend.state["place_check"] and len(processes) == 2
    with pytest.raises(ValueError, match="현재 열린"):
        workflow.receive(corrected)
    snapshot(window)


def test_tts_provider_failure_blocks_answer_and_next_delivery(live, audio, monkeypatch):
    window, workflow, processes, calls, change = live
    original = voice._request
    def request(url, *args):
        if url == voice.TTS_URL:
            voice._set_error("auth", "HTTP 403")
            return None
        return original(url, *args)
    monkeypatch.setattr(voice, "_request", request)
    target, actual = misplaced(live, audio)
    settled(workflow)
    assert workflow.backend.state["workflow_status"] == "HOLD"
    assert "VOICE_IO_FAILED" in workflow.backend.state["reason"]
    assert workflow.backend.state["current"]["blocks"] == [actual]
    assert audio[1] == ["record", "stt"] and len(processes) == 2 and len(calls) == 1
    snapshot(window)


def test_two_unclear_answers_require_existing_real_hmi_choice(live, audio):
    window, workflow, processes, calls, change = live
    audio[0].append("모르겠어요")
    misplaced(live, audio, "모르겠어요")
    settled(workflow)
    state = workflow.backend.state
    assert state["workflow_status"] == "WAIT_INTENT" and state["choice_required"]
    assert audio[1].count("record") == 3 and len(processes) == 2
    before = deepcopy(audio[1])
    QTest.qWait(30)
    assert audio[1] == before
    snapshot(window)
    assert workflow.command(dict(command="CHOOSE_INTENT", job_id=state["job_id"],
        request_id=state["question_request"]["request_id"], choice="REVISE"))["accepted"]
    settled(workflow)
    assert workflow.backend.state["context"]["design"]["design_version"] == 2
    assert len(calls) == 2 and len(processes) == 2 and audio[1] == before


def test_real_stop_during_tts_ignores_answer_then_resume_reasks_same_difference(live, audio, monkeypatch):
    window, workflow, processes, calls, change = live
    entered, release = Event(), Event()
    original = voice._sounddevice
    class BlockingOutput(original):
        def wait(self):
            entered.set()
            assert release.wait(3)
            super().wait()
    monkeypatch.setattr(voice, "_sounddevice", BlockingOutput)
    target, actual = misplaced(live, audio)
    try:
        assert entered.wait(1)
        for _ in range(20):
            QTest.qWait(5)
            if workflow.backend.state["question"]:
                break
        snapshot(window)
        assert workflow.backend.state["question"] in window.notice.toPlainText()
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(EVIDENCE / "real-tts-question.png"))
        before = workflow.backend.state
        assert workflow.command(dict(command="STOP", job_id=before["job_id"]))["accepted"]
        probe(workflow.controller)
        assert workflow.backend.state["workflow_status"] == "STOPPED"
        assert not workflow.command(dict(command="RESUME", job_id=before["job_id"]))["accepted"]
    finally:
        release.set()
    settled(workflow)
    assert audio[1].count("record") == 1 and len(calls) == 1
    assert workflow.backend.state["current"] == before["current"]
    assert workflow.command(dict(command="RESUME", job_id=before["job_id"]))["accepted"]
    settled(workflow)
    assert audio[1].count("record") == 2 and len(calls) == 2
    assert workflow.backend.state["context"]["design"]["design_version"] == 2
    assert workflow.backend.state["job_id"] == before["job_id"]
    assert len(processes) == 3 and workflow.backend.state["place_check"]  # 정지 probe 외 새 이동 없음.


def test_replan_preserves_consumed_slot_and_accepts_later_human_refill(live):
    _, workflow, processes, _, _ = live
    controller = workflow.controller
    before = deepcopy(controller.plan_columns)
    controller.prepare_design_plan(dict(steps=[dict(after=dict(brick_type="2x3x1", color="blue"))] * 6))
    assert controller.plan_columns == before[:1] + [("2x3x1", "blue")] * 6
    assert controller._attempts == 1 and controller._limit == 7
    assert controller.state["supply"][-1]["next_slot"] == 2 and len(processes) == 2


def test_current_changes_during_answer_recording_cannot_adopt_old_revised_plan(live, audio, monkeypatch):
    _, workflow, processes, calls, _ = live
    entered, release = Event(), Event()
    original = voice.record
    def record():
        entered.set()
        assert release.wait(3)
        return original()
    monkeypatch.setattr(voice, "record", record)
    target, actual = misplaced(live, audio)
    try:
        assert entered.wait(1)
        before = workflow.backend.state
        replacement = dict(actual, x=10)
        check = before["current_check"]["check_id"]
        assert workflow.receive(dict(event="current", check_id=check, confirmed=True, blocks=[replacement]))
    finally:
        release.set()
    settled(workflow)
    state = workflow.backend.state
    assert state["current"] == dict(current_revision=2, blocks=[replacement])
    assert state["context"] == before["context"] and len(processes) == 2
    assert state["workflow_status"] == "HOLD" and "C_CALL_BUSY" in state["reason"]
    assert any(r["event"] == "LATE_RESULT_IGNORED" for r in records(workflow))


def test_closed_planner_request_cannot_change_remaining_robot_plan(live):
    _, workflow, processes, _, _ = live
    before = deepcopy(workflow.controller.plan_columns)
    assert not workflow.check_design_plan(dict(request_id="closed"))
    assert workflow.controller.plan_columns == before and len(processes) == 2


def test_real_voice_cli_requires_tts_key_before_qt_or_robot(monkeypatch):
    from app.real_workflow_hmi import main
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "mock")
    monkeypatch.delenv("OPENAI_TTS_API_KEY", raising=False)
    with pytest.raises(SystemExit) as error:
        main(["--real-workflow", "--supply-manifest", "unused", "--vision-module", "unused", "--robot-timeout-seconds", "120"])
    assert error.value.code == 2
