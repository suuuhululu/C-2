"""Hook/state unit tests only; no physical camera, robot or safety validation."""
from copy import deepcopy

import pytest

from perception_mvp import main as reobservation
from perception_mvp.hand_cycle import HandCycle
from perception_mvp.hand_cycle import wait_for_hand_ready


def test_normal_entry_point_waits_for_hand_before_observation(monkeypatch):
    gate = HandCycle(.2, 10.)
    calls = []
    context = dict(mode="REAL", check_id="frozen", observation_seq=0,
        view_order=["V0", "D1", "D3"], target_after=dict(brick_type="2x2x1",
        color="yellow", x=0, y=0, layer=1, orientation_deg=0))
    class Detector:
        def reset(self):
            calls.append("reset")
    def wait(stream, detector, g, valid, **kwargs):
        assert g.state == "WAIT_ENTRY" and valid()
        calls.append("hand")
        context["check_id"] = "changed-externally"
        g.state = "READY"
        return True
    def observe(g, capture, frozen, *args, **kwargs):
        assert g.state == "READY" and frozen["check_id"] == "frozen"
        assert kwargs["bundle_valid"]()
        calls.append("observe")
        return {"check_id": frozen["check_id"]}, {}
    monkeypatch.setattr("perception_mvp.hand_cycle.wait_for_hand_ready", wait)
    monkeypatch.setattr(reobservation, "observe_cycle", observe)
    result, _ = reobservation.run_observation_cycle(gate, Detector(), lambda: iter(()),
        None, context, None, {}, {}, .25, callback=None,
        confirm_view=lambda v: calls.append(v) or True,
        workflow_valid=lambda: True, bundle_valid=lambda: True)
    assert calls == ["V0", "reset", "hand", "observe"]
    assert result["check_id"] == "frozen"


@pytest.mark.parametrize("stopped,active", [(False, True), (True, False)])
def test_normal_cycle_blocks_before_hand_stream_without_stop_or_active_context(stopped, active):
    gate = HandCycle(.2, 10.)
    context = dict(mode="REAL", check_id="check", observation_seq=0,
        view_order=["V0", "D1", "D3"], target_after=dict(brick_type="2x2x1",
        color="yellow", x=0, y=0, layer=1, orientation_deg=0))
    def forbidden():
        pytest.fail("must not open camera stream")
    with pytest.raises(RuntimeError, match="stopped V0"):
        reobservation.run_observation_cycle(gate, None, forbidden, None, context,
            None, {}, {}, .25, callback=None, confirm_view=lambda v: stopped,
            workflow_valid=lambda: active, bundle_valid=lambda: True)
    assert gate.state == "HOLD"


@pytest.fixture
def attempt(monkeypatch):
    gate = HandCycle(.2, 10.)
    gate.entry_seen = True
    gate.absent_since = 1.
    calls, notices, delivered = [], [], []
    context = {"mode": "REAL", "check_id": "new-check", "observation_seq": 0,
               "view_order": ["V0", "D1", "D3"],
               "previous_accepted_blocks": [], "target_after": {"version": "new"}}

    def wait(g):
        assert g.state == "WAIT_ENTRY" and not g.entry_seen
        calls.append("hand")
        g.update("PRESENT", False, 0.)
        g.update("ABSENT", True, 1.)
        g.update("ABSENT", True, 4.)
        assert g.state != "READY"  # Three seconds exactly is insufficient.
        g.update("ABSENT", True, 4.1)
        return True

    def request():
        assert gate.state == "READY"
        calls.append("request")
        return deepcopy(context)

    def observe(g, capture, manifest, *args, **kwargs):
        calls.append("observe")
        assert kwargs["bundle_valid"]() is True
        assert manifest == context
        payload = {"check_id": manifest["check_id"],
                   "observation_seq": manifest["observation_seq"], "status": "OK",
                   "visible_blocks": [], "verified_regions": [], "reason": None}
        kwargs["callback"](payload)
        return payload, {"view_ids": manifest["view_order"]}

    monkeypatch.setattr(reobservation, "observe_cycle", observe)
    options = dict(previous_check_id="old-check", current_view="V0",
        hold_kind="ACTUAL_PLACEMENT", reason="Backend position correction required",
        close_check=lambda check: calls.append(("close", check)) or True,
        return_to_v0=lambda: calls.append("return") or True,
        confirm_view=lambda view: calls.append(("confirm", view)) or True,
        workflow_valid=lambda: True, bundle_valid=lambda: True,
        reset_hand_detector=lambda: calls.append("reset-detector"),
        wait_for_hand=wait, request_context=request, callback=delivered.append,
        notice=notices.append)
    return gate, options, calls, notices, delivered


def execute(attempt):
    gate, options, *_ = attempt
    return reobservation.reobserve_once(gate, None, None, {}, {}, .5, **options)


@pytest.mark.parametrize("view", ["V0", "D1", "D3"])
@pytest.mark.parametrize("kind", ["ACTUAL_PLACEMENT", "OBSERVATION_CONDITIONS"])
def test_common_recheck_entry_all_views(attempt, view, kind):
    gate, options, calls, notices, delivered = attempt
    options.update(current_view=view, hold_kind=kind)
    observed, diagnostics = execute(attempt)
    assert calls.count("return") == (0 if view == "V0" else 1)
    assert calls.index(("close", "old-check")) < calls.index(("confirm", "V0"))
    assert calls.index("reset-detector") < calls.index("hand") < calls.index("request")
    assert notices[0]["human_correction_allowed"] is False
    assert notices[1]["human_correction_allowed"] is True
    assert notices[-1]["state"] == "WAIT_BACKEND_REVALIDATION"
    assert diagnostics["view_ids"] == ["V0", "D1", "D3"]
    assert delivered == [observed] and observed["check_id"] == "new-check"
    assert set(observed) == {"check_id", "observation_seq", "status", "visible_blocks",
                             "verified_regions", "reason"}


@pytest.mark.parametrize("kind", ["STOP", "ROBOT_ERROR", "PLACE_OCCUPIED"])
def test_other_holds_do_not_request_human_correction(attempt, kind):
    attempt[1]["hold_kind"] = kind
    with pytest.raises(ValueError, match="not correction"):
        execute(attempt)
    assert attempt[2] == [] and attempt[3] == [] and attempt[4] == []
    assert attempt[0].state == "HOLD"


@pytest.mark.parametrize("hook", ["close_check", "return_to_v0", "confirm_view",
                                  "workflow_valid", "wait_for_hand"])
def test_failed_external_preconditions_hold_without_observation(attempt, hook):
    attempt[1]["current_view"] = "D1"
    attempt[1][hook] = lambda *args: False
    with pytest.raises(RuntimeError):
        execute(attempt)
    assert "observe" not in attempt[2] and attempt[4] == []
    assert attempt[0].state == "HOLD"


def test_reused_check_is_rejected(attempt):
    attempt[1]["request_context"] = lambda: {"check_id": "old-check"}
    with pytest.raises(ValueError, match="new check_id"):
        execute(attempt)
    assert "observe" not in attempt[2] and attempt[4] == []


def test_stop_after_return_blocks_hand_wait(attempt):
    options, calls = attempt[1:3]
    options["current_view"] = "D3"
    options["workflow_valid"] = lambda: "return" not in calls
    with pytest.raises(RuntimeError, match="STOP"):
        execute(attempt)
    assert "hand" not in calls and "request" not in calls
    assert not any(n["human_correction_allowed"] for n in attempt[3])


def test_hand_reentry_unknown_and_gap_reset_exit_wait():
    gate = HandCycle(.2, 1.)
    gate.update("PRESENT", False, 0.)
    gate.update("ABSENT", True, .1)
    gate.update("PRESENT", False, .8)
    assert gate.absent_since is None
    gate.update("ABSENT", True, 1.)
    gate.update("UNKNOWN", False, 1.1)
    assert gate.absent_since is None
    gate.update("ABSENT", True, 1.2)
    gate.update("ABSENT", True, 2.3)
    assert gate.absent_since is None and gate.state != "READY"


def test_stale_bundle_never_delivered(attempt, monkeypatch):
    def observe(*args, **kwargs):
        assert kwargs["bundle_valid"]() is False
        raise RuntimeError("closed or stale Backend check")
    monkeypatch.setattr(reobservation, "observe_cycle", observe)
    attempt[1]["bundle_valid"] = lambda: False
    with pytest.raises(RuntimeError, match="stale"):
        execute(attempt)
    assert attempt[4] == [] and attempt[0].state == "HOLD"


@pytest.mark.parametrize("status", ["OK", "UNOBSERVABLE"])
def test_backend_receives_once_without_automatic_retry_or_completion(attempt, monkeypatch, status):
    def observe(g, capture, manifest, *args, **kwargs):
        attempt[2].append("observe")
        payload = {"check_id": manifest["check_id"], "observation_seq": 0,
                   "status": status, "visible_blocks": [], "verified_regions": [],
                   "reason": "unverified" if status == "UNOBSERVABLE" else None}
        kwargs["callback"](payload)
        return payload, {}
    monkeypatch.setattr(reobservation, "observe_cycle", observe)
    observed, _ = execute(attempt)
    assert observed["status"] == status
    assert attempt[2].count("observe") == 1 and attempt[2].count("request") == 1
    assert attempt[3][-1]["state"] == "WAIT_BACKEND_REVALIDATION"


def test_repeated_failure_requires_a_new_external_call(attempt):
    attempt[1]["current_view"] = "D1"
    attempt[1]["return_to_v0"] = lambda: attempt[2].append("return") or False
    with pytest.raises(RuntimeError, match="return-to-V0"):
        execute(attempt)
    assert attempt[2].count("return") == 1 and attempt[4] == []
    assert attempt[3][-1]["state"] == "HOLD"
    assert attempt[3][-1]["human_correction_allowed"] is False


@pytest.mark.parametrize("stop", [False, True])
def test_live_hand_wait_consumes_gate_and_closes_stream(stop):
    class Stream:
        closed = False

        def __iter__(self):
            for timestamp in (0., 1., 4., 4.1):
                yield None, None, timestamp

        def close(self):
            self.closed = True

    class Detector:
        count = 0

        def detect(self, rgb, depth):
            self.count += 1
            return ("PRESENT" if self.count == 1 else "ABSENT"), True, {}

    stream, detector, gate = Stream(), Detector(), HandCycle(.2, 10.)
    if stop:
        with pytest.raises(RuntimeError, match="STOP"):
            wait_for_hand_ready(stream, detector, gate, lambda: detector.count < 2)
        assert gate.state == "HOLD"
    else:
        assert wait_for_hand_ready(stream, detector, gate, lambda: True) is True
        assert detector.count == 4 and gate.state == "READY"
    assert stream.closed
