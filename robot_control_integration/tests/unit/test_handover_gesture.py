import json
from pathlib import Path
import pytest
from app.handover_gesture import GestureGate, main

SECOND = 1_000_000_000


def gate():
    # Fixture limits, not measured camera safety parameters.
    return GestureGate(max_age_ns=100_000_000, max_gap_ns=500_000_000,
                       max_latency_ns=50_000_000)


def sample(t, pose="THUMBS_UP", **hand_changes):
    hand = dict(track_id="hand-1", track_confirmed=True, pose=pose,
                pose_confirmed=True, surface="unknown", orientation_confirmed=False)
    hand.update(hand_changes)
    return dict(request_id="question-1", source_ns=t, inference_ns=t,
                clock_verified=True, frame="camera", hands=[hand])


def feed(g, t, pose="THUMBS_UP", mode="QUESTION", **changes):
    return g.evaluate(sample(t, pose, **changes), t, mode=mode, request_id="question-1")


@pytest.mark.parametrize("pose,evidence,event", [
    ("THUMBS_UP", {}, "YES"),
    ("L", dict(surface="back", orientation_confirmed=True), "NO"),
])
def test_answer_two_seconds_boundary_and_one_shot(pose, evidence, event):
    g = gate()
    for t in range(0, 2*SECOND, SECOND//4):
        assert feed(g, t, pose, **evidence)["event"] is None
    assert feed(g, 2*SECOND-1, pose, **evidence)["event"] is None
    result = feed(g, 2*SECOND, pose, **evidence)
    assert result["event"] == event and result["held_ns"] == 2*SECOND
    assert result["request_id"] == "question-1" and not result["real_output_enabled"]
    assert feed(g, 3*SECOND, pose, **evidence)["reason"] == "ALREADY_EMITTED"


@pytest.mark.parametrize("surface,confirmed", [("palm", True), ("side", True), ("unknown", False), ("back", False)])
def test_l_requires_confirmed_back(surface, confirmed):
    g = gate()
    for t in range(0, 3*SECOND, SECOND//4):
        assert feed(g, t, "L", surface=surface, orientation_confirmed=confirmed)["event"] is None


@pytest.mark.parametrize("failure", ["absent", "multiple", "track", "pose", "clock", "stale", "late", "future", "duplicate", "old", "request", "invalid_time"])
def test_interruption_cancels_old_hold(failure):
    g = gate()
    for t in range(0, 2*SECOND, SECOND//4):
        feed(g, t)
    s, now = sample(2*SECOND), 2*SECOND
    if failure == "absent": s["hands"] = []
    if failure == "multiple": s["hands"] *= 2
    if failure == "track": s["hands"][0]["track_confirmed"] = False
    if failure == "pose": s["hands"][0]["pose_confirmed"] = False
    if failure == "clock": s["clock_verified"] = False
    if failure == "stale": now += 100_000_001
    if failure == "late": s["inference_ns"] += 50_000_001; now = s["inference_ns"]
    if failure == "future": now -= 1
    if failure == "duplicate": s["source_ns"] = 7*SECOND//4
    if failure == "old": s["source_ns"] = SECOND
    if failure == "request": s["request_id"] = "closed-question"
    if failure == "invalid_time": s["source_ns"] = True
    assert g.evaluate(s, now, mode="QUESTION", request_id="question-1")["event"] is None
    result = feed(g, 9*SECOND//4)
    assert result["event"] is None and result["held_ns"] == 0


@pytest.mark.parametrize("change", ["track", "frame", "gap", "pose"])
def test_continuity_changes_start_new_hold(change):
    g = gate()
    for t in range(0, 2*SECOND, SECOND//4): feed(g, t)
    s = sample(2*SECOND)
    if change == "track": s["hands"][0]["track_id"] = "hand-2"
    if change == "frame": s["frame"] = "other-camera"
    if change == "gap": s["source_ns"] = s["inference_ns"] = 3*SECOND
    if change == "pose": s["hands"][0].update(pose="L", surface="back", orientation_confirmed=True)
    result = g.evaluate(s, s["inference_ns"], mode="QUESTION", request_id="question-1")
    assert result["event"] is None and result["held_ns"] == 0


def test_inactive_and_new_question_never_inherit_hold():
    g = gate()
    for t in range(0, 2*SECOND, SECOND//4): feed(g, t)
    assert g.evaluate(sample(2*SECOND), 2*SECOND)["reason"] == "INACTIVE"
    s = sample(3*SECOND); s["request_id"] = "question-2"
    result = g.evaluate(s, 3*SECOND, mode="QUESTION", request_id="question-2")
    assert result["held_ns"] == 0 and result["event"] is None
    assert g.evaluate(sample(4*SECOND), 4*SECOND, mode="QUESTION", request_id="question-2")["reason"] == "REQUEST_MISMATCH"


def test_receive_fist_then_palm_once_and_no_close_event():
    g = gate()
    palm = dict(surface="palm", orientation_confirmed=True)
    assert feed(g, 0, "OPEN_PALM", mode="RECEIVE", **palm)["event"] is None
    assert feed(g, SECOND//4, "FIST", mode="RECEIVE")["reason"] == "FIST_ARMED"
    result = feed(g, SECOND//2, "OPEN_PALM", mode="RECEIVE", **palm)
    assert result["event"] == "RECEIVE_REQUEST" and not result["real_output_enabled"]
    assert feed(g, 3*SECOND//4, "FIST", mode="RECEIVE")["event"] is None


@pytest.mark.parametrize("failure", ["track", "gap", "missing", "unknown_palm", "back", "mode"])
def test_receive_requires_unbroken_same_hand_transition(failure):
    g = gate()
    feed(g, 0, "FIST", mode="RECEIVE")
    if failure == "missing":
        s = sample(SECOND//8); s["hands"] = []
        g.evaluate(s, SECOND//8, mode="RECEIVE", request_id="question-1")
    changes = dict(surface="palm", orientation_confirmed=True)
    if failure == "track": changes["track_id"] = "hand-2"
    if failure == "unknown_palm": changes["orientation_confirmed"] = False
    if failure == "back": changes["surface"] = "back"
    t = SECOND if failure == "gap" else SECOND//4
    result = feed(g, t, "OPEN_PALM", mode="QUESTION" if failure == "mode" else "RECEIVE", **changes)
    assert result["event"] is None


def test_modes_do_not_share_gesture_meaning():
    for pose in ("THUMBS_UP", "L"):
        g = gate()
        for t in range(0, 3*SECOND, SECOND//4):
            assert feed(g, t, pose, mode="RECEIVE", surface="back", orientation_confirmed=True)["event"] is None
    assert feed(gate(), 0, "FIST")["event"] is None


def test_runner_is_synthetic_only(tmp_path, capsys):
    fixture = tmp_path/"unit.json"
    data = dict(provenance="SYNTHETIC", limits=dict(max_age_ns=0, max_gap_ns=SECOND, max_latency_ns=0),
                steps=[dict(sample=sample(t), now_ns=t, mode="QUESTION", request_id="question-1") for t in (0, SECOND, 2*SECOND)])
    fixture.write_text(json.dumps(data))
    assert main([str(fixture)]) == 0
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["event"] for r in results] == [None, None, "YES"]
    data["provenance"] = "SENSOR"; fixture.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="synthetic"): main([str(fixture)])


def test_invalid_configuration_and_mode():
    with pytest.raises(ValueError): GestureGate(max_age_ns=0, max_gap_ns=0, max_latency_ns=0)
    with pytest.raises(ValueError): gate().evaluate({}, 0, mode="REAL")
    with pytest.raises(ValueError): gate().evaluate({}, 0, mode="QUESTION")


def test_checked_in_scenarios():
    path = Path(__file__).resolve().parents[2]/"interfaces/fixtures/handover_gestures_synthetic.json"
    data = json.loads(path.read_text())
    g = GestureGate(**data["limits"])
    for step in data["steps"]:
        result = g.evaluate(step["sample"], step["now_ns"], mode=step["mode"], request_id=step["request_id"])
        assert result["event"] == step["expected_event"], step["case"]
