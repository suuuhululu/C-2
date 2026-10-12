import builtins
import json
from pathlib import Path
import pytest

from app.handover_pose_preview import PosePreview, shape_preview
from app.handover_gesture_camera import main


def landmarks(extended):
    points = [dict(x=.5, y=.9, z=0) for _ in range(21)]
    for n, x in enumerate((.35, .5, .65, .8), start=1):
        base = 4*n+1
        coords = [(x, .6), (x, .45), (x, .35), (x, .25)] if n in extended else [(x, .6), (x, .45), (x+.04, .58), (x+.04, .65)]
        for i, (px, py) in enumerate(coords):
            points[base+i] = dict(x=px, y=py, z=0)
    coords = [(.4, .8), (.3, .8), (.2, .8), (.1, .8)] if 0 in extended else [(.4, .8), (.3, .8), (.4, .75), (.45, .8)]
    for i, (x, y) in enumerate(coords, start=1):
        points[i] = dict(x=x, y=y, z=0)
    return points


@pytest.mark.parametrize("extended,expected", [({0}, "THUMBS_UP"), ({0, 1}, "L"), (set(), "FIST"), (set(range(5)), "OPEN_HAND"), ({1}, "UNKNOWN")])
def test_shape_geometry_without_orientation_claims(extended, expected):
    result = shape_preview(landmarks(extended), 100, 100)
    assert result["pose"] == expected
    assert not result["pose_verified"] and not result["orientation_verified"]
    assert result["surface"] == "unknown"


@pytest.mark.parametrize("failure", ["short", "nonfinite", "tiny", "degenerate"])
def test_invalid_landmarks_are_unknown(failure):
    points = landmarks({0})
    if failure == "short": points.pop()
    if failure == "nonfinite": points[2]["x"] = float("nan")
    if failure == "tiny": points[17] = dict(points[5])
    if failure == "degenerate": points[7] = dict(points[6])
    assert shape_preview(points, 100, 100)["pose"] == "UNKNOWN"


def hand(pose="THUMBS_UP"):
    return dict(pose=pose, center=[50, 50], palm_size=50)


def feed(preview, t, pose="THUMBS_UP", context=("QUESTION", "q1")):
    return preview.evaluate([hand(pose)], t, t+1, "camera", context)


@pytest.mark.parametrize("pose,expected", [("THUMBS_UP", "THUMBS_UP_HELD"), ("L", "L_HELD_ORIENTATION_UNKNOWN")])
def test_preview_two_seconds_one_candidate_never_control_event(pose, expected):
    p = PosePreview()
    for t in range(0, 2_000_000_000, 100_000_000):
        assert feed(p, t, pose)["candidate_event"] is None
    assert feed(p, 1_999_999_999, pose)["candidate_event"] is None
    result = feed(p, 2_000_000_000, pose)
    assert result["candidate_event"] == expected
    assert result["event"] is None and not result["real_output_enabled"]
    assert feed(p, 2_100_000_000, pose)["candidate_event"] is None


def test_scoped_question_preview_accepts_thumb_after_point_eight_seconds():
    p=PosePreview(question_hold_ns=800_000_000)
    for t in range(0,800_000_000,100_000_000):
        assert feed(p,t)['candidate_event'] is None
    assert feed(p,800_000_000)['candidate_event']=='THUMBS_UP_HELD'


@pytest.mark.parametrize("failure", ["missing", "multiple", "unknown", "gap", "jump", "scale", "frame", "old", "request"])
def test_preview_loss_restarts_duration(failure):
    p = PosePreview()
    for t in range(0, 2_000_000_000, 100_000_000): feed(p, t)
    h, frame, context, t, source = [hand()], "camera", ("QUESTION", "q1"), 2_000_000_000, 2_000_000_001
    if failure == "missing": h = []
    if failure == "multiple": h *= 2
    if failure == "unknown": h[0]["pose"] = "UNKNOWN"
    if failure == "gap": t = 3_000_000_000; source = t+1
    if failure == "jump": h[0]["center"] = [100, 100]
    if failure == "scale": h[0]["palm_size"] = 100
    if failure == "frame": frame = "other"
    if failure == "old": source = 1
    if failure == "request": context = ("QUESTION", "q2")
    result = p.evaluate(h, t, source, frame, context)
    assert result["candidate_event"] is None and result["held_ns"] == 0
    assert feed(p, t+100_000_000)["candidate_event"] is None


def test_inactive_ignores_and_receive_requires_fist_then_open():
    p = PosePreview()
    assert feed(p, 0, context=("INACTIVE", "i1"))["reason"] == "INACTIVE"
    context = ("RECEIVE", "r1")
    assert feed(p, 100_000_000, "OPEN_HAND", context)["candidate_event"] is None
    assert feed(p, 200_000_000, "FIST", context)["candidate_event"] is None
    result = feed(p, 300_000_000, "OPEN_HAND", context)
    assert result["candidate_event"] == "FIST_TO_OPEN_ORIENTATION_UNKNOWN"
    assert result["event"] is None
    assert feed(p, 400_000_000, "FIST", context)["candidate_event"] is None


def test_open_gripper_held_without_fist_once_per_request():
    p = PosePreview(); context = ("OPEN_GRIPPER", "open1")
    for t in range(0, 2_000_000_000, 100_000_000):
        assert feed(p, t, "OPEN_HAND", context)["candidate_event"] is None
    result = feed(p, 2_000_000_000, "OPEN_HAND", context)
    assert result["candidate_event"] == "OPEN_HAND_HELD_ORIENTATION_UNKNOWN"
    assert result["held_ns"] == 2_000_000_000
    assert result["event"] is None and not result["real_output_enabled"]
    assert feed(p, 2_100_000_000, "OPEN_HAND", context)["candidate_event"] is None
    assert feed(p, 2_200_000_000, "OPEN_HAND", ("OPEN_GRIPPER", "open2"))["held_ns"] == 0


@pytest.mark.parametrize("failure", ["missing", "multiple", "unknown", "fist", "jump", "scale", "gap", "old", "frame", "context"])
@pytest.mark.parametrize("hold_ns", [1_000_000_000, 2_000_000_000])
def test_open_gripper_loss_restarts_full_hold(failure, hold_ns):
    p = PosePreview(open_hold_ns=hold_ns); context = ("OPEN_GRIPPER", "loss")
    for t in range(0, hold_ns, 100_000_000):
        feed(p, t, "OPEN_HAND", context)
    hands, frame, source, t = [hand("OPEN_HAND")], "camera", hold_ns+1, hold_ns
    if failure == "missing": hands = []
    if failure == "multiple": hands *= 2
    if failure in ("unknown", "fist"): hands[0]["pose"] = failure.upper()
    if failure == "jump": hands[0]["center"] = [100, 100]
    if failure == "scale": hands[0]["palm_size"] = 100
    if failure == "gap": t = hold_ns+1_000_000_000; source = t+1
    if failure == "old": source = 1
    if failure == "frame": frame = "other"
    if failure == "context": context = ("INACTIVE", "stop")
    assert p.evaluate(hands, t, source, frame, context)["candidate_event"] is None
    next_t = t+100_000_000
    result = feed(p, next_t, "OPEN_HAND", ("OPEN_GRIPPER", "loss"))
    assert result["held_ns"] <= 100_000_000 and result["candidate_event"] is None


def test_fast_open_requires_full_second_and_does_not_speed_up_questions():
    p = PosePreview(open_hold_ns=1_000_000_000)
    context = ("OPEN_GRIPPER", "fast")
    for t in range(0, 1_000_000_000, 100_000_000):
        assert feed(p, t, "OPEN_HAND", context)["candidate_event"] is None
    assert feed(p, 999_999_999, "OPEN_HAND", context)["candidate_event"] is None
    assert feed(p, 1_000_000_000, "OPEN_HAND", context)["candidate_event"] == "OPEN_HAND_HELD_ORIENTATION_UNKNOWN"
    assert feed(p, 1_100_000_000, "OPEN_HAND", context)["candidate_event"] is None
    p = PosePreview(open_hold_ns=1_000_000_000)
    for t in range(0, 2_000_000_000, 100_000_000):
        assert feed(p, t)["candidate_event"] is None
    assert feed(p, 2_000_000_000)["candidate_event"] == "THUMBS_UP_HELD"


@pytest.mark.parametrize("value", [0, -1, 399_999_999, 5_000_000_001, float('nan'), True])
def test_invalid_open_hold_rejected(value):
    with pytest.raises(ValueError): PosePreview(open_hold_ns=value)


def test_point_four_second_open_hand_boundary_and_context_reset():
    p = PosePreview(open_hold_ns=400_000_000)
    context = ('OPEN_GRIPPER', 'short-open')
    for t in (0, 100_000_000, 200_000_000, 399_999_999):
        assert feed(p, t, 'OPEN_HAND', context)['candidate_event'] is None
    assert feed(p, 400_000_000, 'OPEN_HAND', context)['candidate_event'] == 'OPEN_HAND_HELD_ORIENTATION_UNKNOWN'
    assert feed(p, 500_000_000, 'OPEN_HAND', ('OPEN_GRIPPER', 'post-stop'))['held_ns'] == 0


@pytest.mark.parametrize("value", ["0", "-1", "0.39", "5.01", "nan", "inf"])
def test_invalid_cli_open_hold_rejected_before_output(tmp_path, value):
    output = tmp_path/"not-created"
    with pytest.raises(SystemExit):
        main(["--output", str(output), "--open-hold-seconds", value])
    assert not output.exists()


@pytest.mark.parametrize("options", [
    ["--enable-gripper-output", "--no-window"],
    ["--enable-gripper-output", "--mode", "OPEN_GRIPPER"],
    ["--enable-gripper-output", "--mode", "QUESTION"],
    ["--robot-prefix", "relative"],
])
def test_real_output_requires_manual_arming_before_import_or_directory(tmp_path, options):
    output = tmp_path/"not-created"
    with pytest.raises(SystemExit):
        main(["--output", str(output), *options])
    assert not output.exists()


def test_receive_loss_disarms_fist():
    p = PosePreview(); context = ("RECEIVE", "r1")
    feed(p, 0, "FIST", context)
    p.evaluate([], 100_000_000, 100_000_001, "camera", context)
    assert feed(p, 200_000_000, "OPEN_HAND", context)["candidate_event"] is None


@pytest.mark.parametrize("field,value", [
    ("center", None), ("center", [50]), ("center", [50, 50, 50]),
    ("center", "50"), ("center", [float("nan"), 50]),
    ("center", [50, float("inf")]), ("center", [True, 50]),
    ("palm_size", None), ("palm_size", 0), ("palm_size", -50),
    ("palm_size", float("nan")), ("palm_size", float("inf")),
    ("palm_size", "50"), ("palm_size", True),
])
@pytest.mark.parametrize("mode", ["QUESTION", "RECEIVE"])
def test_invalid_geometry_cancels_progress_and_recovers(field, value, mode):
    p = PosePreview(); context = (mode, "invalid-geometry")
    pose = "THUMBS_UP" if mode == "QUESTION" else "FIST"
    for t in range(0, 2_000_000_000, 100_000_000):
        feed(p, t, pose, context)
    bad = hand("THUMBS_UP" if mode == "QUESTION" else "OPEN_HAND")
    bad[field] = value
    result = p.evaluate([bad], 2_000_000_000, 2_000_000_001, "camera", context)
    assert result["reason"] == "INVALID_HAND_GEOMETRY"
    assert result["candidate_event"] is None and result["held_ns"] == 0
    assert not result["continuity_estimate"]
    assert result["event"] is None and not result["real_output_enabled"]
    recovered = feed(p, 2_100_000_000, bad["pose"], context)
    assert recovered["candidate_event"] is None and recovered["held_ns"] == 0
    if mode == "QUESTION":
        for t in range(2_200_000_000, 4_100_000_000, 100_000_000):
            assert feed(p, t, context=context)["candidate_event"] is None
        assert feed(p, 4_100_000_000, context=context)["candidate_event"] == "THUMBS_UP_HELD"
    else:
        feed(p, 2_200_000_000, "FIST", context)
        assert feed(p, 2_300_000_000, "OPEN_HAND", context)["candidate_event"] == "FIST_TO_OPEN_ORIENTATION_UNKNOWN"


@pytest.mark.parametrize("field", ["center", "palm_size"])
def test_missing_geometry_rejects_and_retains_source_watermark(field):
    p = PosePreview(); context = ("RECEIVE", "missing-geometry")
    feed(p, 100_000_000, "FIST", context)
    bad = hand("OPEN_HAND"); del bad[field]
    result = p.evaluate([bad], 200_000_000, 200_000_001, "camera", context)
    assert result["reason"] == "INVALID_HAND_GEOMETRY" and result["candidate_event"] is None
    for source in (100_000_001, 200_000_001):
        result = p.evaluate([hand("FIST")], 250_000_000, source, "camera", context)
        assert result["reason"] == "OLD_OR_INVALID_SOURCE"
    assert feed(p, 300_000_000, "OPEN_HAND", context)["candidate_event"] is None


@pytest.mark.parametrize("hands", [None, {}, [None], [{}]])
def test_malformed_hand_container_disarms_receive(hands):
    p = PosePreview(); context = ("RECEIVE", "malformed-hands")
    feed(p, 100_000_000, "FIST", context)
    result = p.evaluate(hands, 200_000_000, 200_000_001, "camera", context)
    assert result["reason"] == "SINGLE_KNOWN_SHAPE_REQUIRED"
    assert result["candidate_event"] is None and result["event"] is None
    assert feed(p, 300_000_000, "OPEN_HAND", context)["candidate_event"] is None


def test_separate_preview_validation_fixture():
    path = Path(__file__).resolve().parents[2]/"interfaces/fixtures/handover_gestures_preview_validation.json"
    data = json.loads(path.read_text())
    assert data["provenance"] == "SYNTHETIC"
    for scenario in data["scenarios"]:
        p = PosePreview()
        for step in scenario["steps"]:
            result = p.evaluate(step["hands"], step["received_ns"], step["source_ns"],
                                step["frame"], tuple(scenario["context"]))
            assert result["candidate_event"] == step["expected_candidate"], scenario["case"]
            assert result["held_ns"] == step["expected_held_ns"], scenario["case"]
            assert result["reason"] == step["expected_reason"], scenario["case"]
            assert result["event"] is None and not result["real_output_enabled"]


def test_output_directory_is_not_overwritten(tmp_path):
    marker = tmp_path/"kept.txt"; marker.write_text("keep")
    with pytest.raises(FileExistsError): main(["--output", str(tmp_path), "--no-window"])
    assert marker.read_text() == "keep"


def test_duration_rejected_before_import_or_output(tmp_path):
    output = tmp_path/"not-created"
    with pytest.raises(SystemExit): main(["--seconds", "0", "--output", str(output)])
    assert not output.exists()


def test_cli_has_no_execute_option(tmp_path):
    output = tmp_path/"not-created"
    with pytest.raises(SystemExit): main(["--execute", "--output", str(output)])
    assert not output.exists()


def test_import_failure_is_logged_as_failure(tmp_path, monkeypatch):
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("test missing cv2")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    output = tmp_path/"capture"
    assert main(["--output", str(output), "--no-window"]) == 1
    result = json.loads((output/"result.json").read_text())
    assert result["status"] == "FAIL" and result["reason"] == "test missing cv2"
    assert not result["motion_commands_sent"]
