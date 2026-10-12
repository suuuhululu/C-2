"""Camera-loop workflow fixtures; no real ROS, image model or devices."""
import builtins
import json
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace as NS

import pytest

from app import handover_gesture_camera as camera
from app import handover_gesture_gripper as gripper_module


@pytest.mark.parametrize("transport", ["raw", "theora"])
@pytest.mark.parametrize("stream,seconds,key,expected,enable_output", [
    (True, 2, None, "CAPTURED", False), (False, 8, None, "FAIL", False),
    (True, 2, ord("r"), "CAPTURED", False), (True, 8, 27, "CAPTURED", False),
    (True, 5, ord("r"), "CAPTURED", False),
    (True, 5, ord("r"), "CAPTURED", True), (True, 2, -1, "CAPTURED", True),
    (True, 5, ord("q"), "CAPTURED", True), (False, 8, -1, "FAIL", True),
    (True, 2, ord("r"), "FAIL", True),
])
def test_slow_initialization_and_exit_paths(monkeypatch, tmp_path, stream, seconds, key, expected, enable_output, transport):
    if transport == "theora" and not stream:
        seconds = 65  # The camera owner has time to send the initial codec headers.
    clock = NS(t=0.0)
    show_hand = enable_output or (seconds == 5 and key == ord("r"))
    state = NS(callback=None, sequence=0, model_closed=False, node_destroyed=False, ok=False,
               calls=[], relay_commands=[], relay_stopped=False)
    monkeypatch.setattr(camera, "time", NS(monotonic=lambda: clock.t,
                                           monotonic_ns=lambda: int(clock.t*1_000_000_000)))
    monkeypatch.setattr(gripper_module, "time", camera.time)

    def create_model(options):
        clock.t += 20.0  # Longer than both the capture and first-frame time budgets.
        hands = [[NS(x=.5, y=.5, z=0)]*21] if show_hand else []
        return NS(detect=lambda image: NS(hand_landmarks=hands),
                  close=lambda: setattr(state, "model_closed", True))

    def subscribe(message_type, topic, callback, qos):
        state.callback = callback
        state.topic = topic

    relay = NS(poll=lambda: None)

    def spawn(command, **kwargs):
        assert kwargs["start_new_session"] is True
        state.relay_commands.append(command)
        return relay

    monkeypatch.setattr(camera, "subprocess", NS(Popen=spawn, STDOUT=-2))
    monkeypatch.setattr(camera, "stop_relay", lambda process:
                        setattr(state, "relay_stopped", process is relay))

    def spin_once(node, timeout_sec):
        clock.t += .25
        state.sequence += 1
        if stream:
            state.callback(NS(header=NS(stamp=NS(sec=state.sequence, nanosec=0))))

    def write_image(path, image):
        Path(path).write_bytes(b"synthetic image workflow fixture")
        return True

    def send(path, request):
        state.calls.append((path, vars(request).copy()))
        return NS(done=lambda: True, result=lambda: NS(success=True, robot_system=0, robot_state=1, value=1),
                  cancel=lambda: None)

    node = NS(create_subscription=subscribe, destroy_node=lambda: setattr(state, "node_destroyed", True),
              create_client=lambda srv, path: NS(service_is_ready=lambda: True,
                                                call_async=lambda request: send(path, request)))
    fake_ros = NS(init=lambda args: setattr(state, "ok", True), create_node=lambda name: node,
                  spin_once=spin_once, ok=lambda: state.ok,
                  shutdown=lambda: setattr(state, "ok", False))
    fake_cv = NS(cvtColor=lambda image, code: image, COLOR_RGB2BGR=1, imwrite=write_image,
                 waitKey=lambda delay: key if (key == 27 and state.sequence >= 3) or (key in (ord("r"), ord("q")) and state.sequence == 2) else -1,
                 putText=lambda *args: None, FONT_HERSHEY_SIMPLEX=1,
                 imshow=lambda *args: None, circle=lambda *args: None, destroyAllWindows=lambda: None)
    fake_mp = NS(tasks=NS(BaseOptions=lambda **kwargs: kwargs),
                 Image=lambda **kwargs: kwargs, ImageFormat=NS(SRGB=1))
    vision = NS(HandLandmarker=NS(create_from_options=create_model),
                HandLandmarkerOptions=lambda **kwargs: kwargs)
    modules = {"cv2": fake_cv, "numpy": NS(ascontiguousarray=lambda image: image),
               "mediapipe": fake_mp, "mediapipe.tasks.python": NS(vision=vision),
               "rclpy": fake_ros, "rclpy.qos": NS(qos_profile_sensor_data=object()),
               "sensor_msgs.msg": NS(Image=object()),
               "dsr_msgs2.srv": NS(**{name: NS(Request=lambda: NS()) for name in
                                     ("GetRobotSystem", "GetRobotState", "SetCtrlBoxDigitalOutput", "GetCtrlBoxDigitalInput")})}
    original_import = builtins.__import__

    def importing(name, *args, **kwargs):
        return modules[name] if name in modules else original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    monkeypatch.setattr(camera, "image_array", lambda message: NS(shape=(10, 10, 3)))
    if show_hand:
        monkeypatch.setattr(camera, "shape_preview", lambda *args: dict(pose="OPEN_HAND", center=[50, 50], palm_size=50))
    monkeypatch.setattr(camera, "frame_metadata", lambda message, received:
                        dict(source_ns=message.header.stamp.sec*1_000_000_000, frame="synthetic-camera"))
    model = tmp_path/"fixture-model"; model.write_bytes(b"synthetic model workflow fixture")
    output = tmp_path/"capture"
    args = ["--output", str(output), "--model", str(model), "--seconds", str(seconds),
            "--rgb-transport", transport]
    if transport == "theora" and stream and key is None:
        args.extend(["--rgb-topic", "/camera/color/image_raw/theora"])
    if key is None:
        args.append("--no-window")
    if enable_output:
        args.append("--enable-gripper-output")
    exit_code = camera.main(args)
    result = json.loads((output/"result.json").read_text())
    assert result["status"] == expected
    assert exit_code == (0 if expected == "CAPTURED" else 1)
    assert result["real_output_enabled"] == enable_output
    assert result["open_hold_seconds"] == 1.0
    should_send = enable_output and key == ord("r")
    assert result["motion_commands_sent"] == should_send
    assert state.model_closed and state.node_destroyed and not state.ok
    if transport == "theora":
        assert state.relay_stopped and len(state.relay_commands) == 1
        command = state.relay_commands[0]
        assert "in/theora:=/camera/color/image_raw/theora" in command
        assert "in_transport:=theora" in command and "out_transport:=raw" in command
        assert state.topic == result["decoded_rgb_topic"]
        assert f"out:={state.topic}" in command
    else:
        assert state.relay_commands == [] and not state.relay_stopped
    if stream:
        assert result["frames"] >= 2
        rows = [json.loads(line) for line in (output/"frames.jsonl").read_text().splitlines()]
        assert all(row["event"] is None and row["real_output_enabled"] == enable_output for row in rows)
        assert all(row["open_hold_seconds"] == 1.0 for row in rows)
        assert result["reason"] == ("OPERATOR_ENDED" if key == 27 else "DURATION_ENDED")
        if key == ord("r"):
            assert rows[0]["mode"] == "INACTIVE"
            assert all(row["mode"] == "OPEN_GRIPPER" for row in rows[1:])
            assert clock.t-20 >= seconds
            if show_hand:
                assert result["candidate_events"] == 1
        if should_send:
            output_calls = [request for path, request in state.calls if "set_ctrl_box" in path]
            assert output_calls[0] == {"index": 1, "value": 0}
            if expected == "CAPTURED":
                assert output_calls == [{"index": 1, "value": 0}, {"index": 2, "value": 1}]
                assert result["gripper_state"] == "OPEN_FEEDBACK_CONFIRMED"
            else:
                assert result["gripper_state"] == "FAIL"
            journal = [json.loads(line) for line in (output/"gripper.jsonl").read_text().splitlines()]
            assert any(row.get("step") == "CLOSE_OFF" for row in journal)
        else:
            assert state.calls == []
    else:
        assert result["reason"] == "NO_RGB_RECEIVED" and result["frames"] == 0
        timeout = 60 if transport == "theora" else 5
        assert timeout < clock.t-20 < timeout+1


@pytest.mark.parametrize("timeouts,expected_signals", [
    (0, [signal.SIGINT]), (1, [signal.SIGINT, signal.SIGTERM]),
    (2, [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]),
])
def test_shutdown_stops_only_owned_relay_group(monkeypatch, timeouts, expected_signals):
    state = NS(signals=[], waits=0)
    process = NS(pid=12345, poll=lambda: None)

    def wait(timeout):
        assert timeout == 2
        state.waits += 1
        if state.waits <= timeouts:
            raise subprocess.TimeoutExpired("synthetic relay", timeout)
        return 0

    process.wait = wait
    monkeypatch.setattr(camera.os, "killpg", lambda pid, sig: state.signals.append((pid, sig)))
    camera.stop_relay(process)
    assert state.signals == [(12345, sig) for sig in expected_signals]


def test_shutdown_ignores_absent_or_finished_relay(monkeypatch):
    def forbidden(*args):
        pytest.fail("must not signal any other process")
    monkeypatch.setattr(camera.os, "killpg", forbidden)
    camera.stop_relay(None)
    camera.stop_relay(NS(poll=lambda: 0))
