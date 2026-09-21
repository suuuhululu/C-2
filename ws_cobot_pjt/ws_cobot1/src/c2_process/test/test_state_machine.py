"""고정 드릴 순서·중단·늦은 성공 응답을 모션 없이 확인한다."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from c2_process.robot_adapter import StepResult
from c2_process.state_machine import run_process


def success(step):
    return StepResult("SUCCEEDED", "NONE", step, step)


def test_successful_sequence_and_progress():
    context = SimpleNamespace(cancel=threading.Event())
    calls = []
    result = run_process(
        context,
        precheck=lambda: (calls.append("precheck"), success("precheck"))[1],
        tool_check=lambda: (calls.append("tool_check"),
                            StepResult("SUCCEEDED", "NONE", "", "tool_check", {"error_m": 0.0002}))[1],
        engrave=lambda report: (calls.append("engrave"), report({"phase": "ENGRAVE"}),
                                StepResult("SUCCEEDED", "NONE", "", "engrave", {"last_completed_segment_id": "cut-1"}))[2],
        on_phase=lambda name: calls.append(name),
        on_progress=lambda value: calls.append(value["phase"]),
    )
    assert result.outcome == "SUCCEEDED"
    assert result.observed_state["last_completed_segment_id"] == "cut-1"
    assert result.observed_state["tool_check"]["error_m"] == 0.0002
    assert calls == ["PRECHECK", "precheck", "TOOL_CHECK", "tool_check", "APPROACH", "engrave", "ENGRAVE", "FINISH"]


def test_precheck_failure_prevents_motion():
    context = SimpleNamespace(cancel=threading.Event())
    result = run_process(context, precheck=lambda: StepResult("FAILED", "PATH_MISMATCH"),
                         tool_check=lambda: (_ for _ in ()).throw(AssertionError("tool check ran")),
                         engrave=lambda _: (_ for _ in ()).throw(AssertionError("engrave ran")))
    assert result.error_code == "PATH_MISMATCH"


def test_tool_check_failure_prevents_engraving():
    context = SimpleNamespace(cancel=threading.Event())
    result = run_process(context, precheck=lambda: success("precheck"),
                         tool_check=lambda: StepResult("FAILED", "VALIDATION_FAILED"),
                         engrave=lambda _: (_ for _ in ()).throw(AssertionError("engrave ran")))
    assert result.error_code == "VALIDATION_FAILED"


def test_stop_during_tool_check_late_success_is_unknown():
    context = SimpleNamespace(cancel=threading.Event())

    def tool_check():
        context.cancel.set()
        return success("tool_check")

    result = run_process(context, precheck=lambda: success("precheck"), tool_check=tool_check,
                         engrave=lambda _: (_ for _ in ()).throw(AssertionError("engrave ran")))
    assert (result.outcome, result.error_code) == ("UNKNOWN", "STOP_UNCONFIRMED")


def test_stop_during_engraving_propagates_stopped():
    context = SimpleNamespace(cancel=threading.Event())

    def engrave(_):
        context.cancel.set()
        return StepResult("STOPPED", "NONE", "정지 확인", "cut-1")

    result = run_process(context, precheck=lambda: success("precheck"),
                         tool_check=lambda: success("tool_check"), engrave=engrave)
    assert result.outcome == "STOPPED"


def test_stop_during_engraving_late_success_is_unknown():
    context = SimpleNamespace(cancel=threading.Event())

    def engrave(_):
        context.cancel.set()
        return success("engrave")

    result = run_process(context, precheck=lambda: success("precheck"),
                         tool_check=lambda: success("tool_check"), engrave=engrave)
    assert (result.outcome, result.error_code) == ("UNKNOWN", "STOP_UNCONFIRMED")


def test_engraving_failure_keeps_tool_check_evidence():
    context = SimpleNamespace(cancel=threading.Event())
    result = run_process(context, precheck=lambda: success("precheck"),
                         tool_check=lambda: StepResult("SUCCEEDED", observed_state={"error_m": 0.0003}),
                         engrave=lambda _: StepResult("FAILED", "VALIDATION_FAILED", "접촉 실패", "cut-1",
                                                      {"last_completed_segment_id": "approach-1"}))
    assert result.error_code == "VALIDATION_FAILED"
    assert result.observed_state["last_completed_segment_id"] == "approach-1"
    assert result.observed_state["tool_check"]["error_m"] == 0.0003


def test_invalid_callbacks_fail_before_motion():
    context = SimpleNamespace(cancel=threading.Event())
    result = run_process(context, precheck=None, tool_check=lambda: success("tool_check"),
                         engrave=lambda _: success("engrave"))
    assert (result.outcome, result.error_code) == ("FAILED", "INVALID_INPUT")


def test_invalid_result_does_not_enter_next_step():
    context = SimpleNamespace(cancel=threading.Event())
    result = run_process(context, precheck=lambda: "done",
                         tool_check=lambda: (_ for _ in ()).throw(AssertionError("tool check ran")),
                         engrave=lambda _: (_ for _ in ()).throw(AssertionError("engrave ran")))
    assert (result.outcome, result.error_code) == ("UNKNOWN", "INVALID_RESULT")


def test_new_motion_steps_fail_or_stop_without_following_motion():
    for failed_step in ("start", "engrave", "home"):
        for outcome, code in (("FAILED", "VALIDATION_FAILED"), ("STOPPED", "NONE"), ("UNKNOWN", "TIMEOUT")):
            calls = []
            context = SimpleNamespace(cancel=threading.Event())
            def operation(name):
                calls.append(name)
                return StepResult(outcome, code, name, name) if name == failed_step else success(name)
            result = run_process(context, precheck=lambda: success("precheck"),
                tool_check=lambda: success("tool_check"), go_to_start=lambda: operation("start"),
                engrave=lambda _: operation("engrave"), return_home=lambda: operation("home"))
            assert (result.outcome, result.error_code) == (outcome, code)
            expected = ["start", "engrave", "home"]
            assert calls == expected[:expected.index(failed_step) + 1]


def test_late_success_in_start_or_home_is_unknown():
    for interrupted in ("start", "home"):
        context = SimpleNamespace(cancel=threading.Event())
        calls = []
        def operation(name):
            calls.append(name)
            if name == interrupted:
                context.cancel.set()
            return success(name)
        result = run_process(context, precheck=lambda: success("precheck"),
            tool_check=lambda: success("tool_check"), go_to_start=lambda: operation("start"),
            engrave=lambda _: operation("engrave"), return_home=lambda: operation("home"))
        assert (result.outcome, result.error_code) == ("UNKNOWN", "STOP_UNCONFIRMED")
        assert calls == (["start"] if interrupted == "start" else ["start", "engrave", "home"])


def test_only_one_transition_callback_is_rejected_before_precheck():
    result = run_process(SimpleNamespace(cancel=threading.Event()),
        precheck=lambda: (_ for _ in ()).throw(AssertionError("precheck ran")),
        tool_check=lambda: success("tool_check"), engrave=lambda _: success("engrave"),
        go_to_start=lambda: success("start"))
    assert result.error_code == "INVALID_INPUT"
