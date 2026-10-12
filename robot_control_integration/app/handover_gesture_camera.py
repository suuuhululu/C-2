"""ROS RGB gesture diagnostics; optional operator-armed WebLogic gripper output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

from app.handover_camera_test import image_array, frame_metadata
from app.handover_pose_preview import PosePreview, shape_preview

ROOT = Path(__file__).resolve().parents[1]
LABELS = {ord(k): v for k, v in zip("12345678", (
    "thumbs_up", "L_back", "L_palm", "fist", "open_palm", "withdrawn", "side", "occluded"))}


def stop_relay(process):
    """Stop only the private relay process group, including ros2 run's child."""
    if process is None or process.poll() is not None:
        return
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            continue


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rgb-topic", default="/camera/color/image_raw")
    parser.add_argument("--rgb-transport", choices=("raw", "theora"), default="raw")
    parser.add_argument("--model", type=Path, default=ROOT/"logs/handover/stage02/hand_landmarker.task")
    parser.add_argument("--model-deps", type=Path, default=ROOT/"logs/handover/model-deps")
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--mode", choices=("INACTIVE", "QUESTION", "RECEIVE", "OPEN_GRIPPER"), default="INACTIVE")
    parser.add_argument("--no-window", action="store_true")
    parser.add_argument("--enable-gripper-output", action="store_true")
    parser.add_argument("--open-hold-seconds", type=float, default=1.0)
    parser.add_argument("--robot-prefix", default="/dsr01/dsr_controller2")
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 180:
        parser.error("seconds must be 1..180")
    if not .4 <= args.open_hold_seconds <= 5:
        parser.error("open-hold-seconds must be 0.4..5")
    if args.enable_gripper_output and (args.no_window or args.mode != "INACTIVE"):
        parser.error("gripper output requires a window, INACTIVE startup, and manual R arming")
    if not args.robot_prefix.startswith("/") or args.robot_prefix == "/":
        parser.error("robot-prefix must be an absolute ROS controller namespace")
    output = (args.output or ROOT/"logs/handover/real"/f"gesture-{uuid4()}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    status = dict(status="RUNNING", frames=0, candidate_events=0, real_output_enabled=args.enable_gripper_output,
                  motion_commands_sent=False, recognition_verdict="UNVALIDATED", reason=None,
                  output_commands_attempted=0,
                  gripper_state="READY" if args.enable_gripper_output else "DISABLED",
                  rgb_transport=args.rgb_transport,
                  open_hold_seconds=args.open_hold_seconds,
                  rgb_topic=args.rgb_topic, thresholds="prototype, not measured safety parameters")
    print(f"영상 제스처 진단 로그: {output}\n"
          f"q=새 확인 질문, r=편 손 {args.open_hold_seconds:g}초로 열기 요청, n=비활성, ESC=종료\n"
          "1=엄지척 2=손등L 3=손바닥L 4=주먹 5=손바닥 6=철회 7=옆면 8=가림 (수동 사례 표기)\n"
          + ("실제 출력 활성: 인계 위치에서 로봇을 정지시킨 뒤 R로 한 번씩 무장하세요."
             if args.enable_gripper_output else "PREVIEW ONLY: 후보 표시/기록만 수행하며 실제 승인·개방 없음"), flush=True)
    node = model = gripper = relay = relay_log = None
    cv2 = rclpy = None
    latest = []
    preview = PosePreview(open_hold_ns=round(args.open_hold_seconds*1_000_000_000))
    context, label, last_candidate = (args.mode, str(uuid4())), "unlabeled", None
    started, last_capture, seen, last_print = time.monotonic(), 0, None, 0
    try:
        # Only this diagnostic process receives the existing optional model path.
        sys.path.insert(0, str(args.model_deps.resolve()))
        import cv2
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        import rclpy
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Image
        status["model_sha256"] = hashlib.sha256(args.model.read_bytes()).hexdigest()
        model = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model)), num_hands=2))
        rclpy.init(args=[])
        node = rclpy.create_node("handover_gesture_preview")

        def receive(message):
            latest[:] = [(message, time.monotonic_ns())]

        subscription_topic = args.rgb_topic
        if args.rgb_transport == "theora":
            source_topic = args.rgb_topic.removesuffix("/theora").rstrip("/")
            subscription_topic = f"/gesture_camera/decoded_{uuid4().hex}"
            command = ["ros2", "run", "image_transport", "republish", "--ros-args",
                       "-p", "in_transport:=theora", "-p", "out_transport:=raw",
                       "-r", f"in:={source_topic}", "-r", f"in/theora:={source_topic}/theora",
                       "-r", f"out:={subscription_topic}",
                       "-r", f"__node:=gesture_decoder_{uuid4().hex}",
                       "-p", f"qos_overrides.{source_topic}/theora.subscription.reliability:=best_effort",
                       "-p", f"qos_overrides.{source_topic}/theora.subscription.depth:=5"]
            relay_log = (output/"theora-relay.log").open("x", encoding="utf-8")
            relay = subprocess.Popen(command, stdout=relay_log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            status.update(decoded_rgb_topic=subscription_topic, theora_relay_command=command)
            print("Theora 디코더 시작: 최초 영상은 최대 60초 대기합니다.\n"
                  "초기 헤더가 없는 기존 스트림이면 디코더 구독 후 카메라 노드를 다시 시작해야 합니다.\n"
                  f"디코더 로그: {output/'theora-relay.log'}", flush=True)
        node.create_subscription(Image, subscription_topic, receive, qos_profile_sensor_data)
        # Allow discovery its full timeout after slow model/import initialization.
        started = time.monotonic()
        with (output/"frames.jsonl").open("x", encoding="utf-8") as stream, \
                (output/"gripper.jsonl").open("x", encoding="utf-8") as journal:
            def record_gripper(row):
                journal.write(json.dumps(dict(monotonic_ns=time.monotonic_ns(), **row), ensure_ascii=False)+"\n")
                journal.flush()

            if args.enable_gripper_output:
                from app.handover_gesture_gripper import WebLogicGripper
                gripper = WebLogicGripper(node, args.robot_prefix, record_gripper)
            while time.monotonic()-started < args.seconds:
                rclpy.spin_once(node, timeout_sec=.02)
                if relay is not None and relay.poll() is not None:
                    raise RuntimeError("THEORA_RELAY_EXITED")
                key = -1 if args.no_window else cv2.waitKey(1) & 255
                if key == 27:
                    if gripper is not None:
                        gripper.abort("OPERATOR_ENDED")
                    status["reason"] = "OPERATOR_ENDED"
                    break
                if key in (ord("q"), ord("r"), ord("n")):
                    if gripper is not None:
                        gripper.abort("OPERATOR_CONTEXT_CHANGED")
                    context = ({ord("q"): "QUESTION", ord("r"): "OPEN_GRIPPER", ord("n"): "INACTIVE"}[key], str(uuid4()))
                    last_candidate = None
                    print(f"새 진단 요청: {context[0]} {context[1]}", flush=True)
                if key in LABELS:
                    label = LABELS[key]
                    print(f"수동 사례: {label}", flush=True)
                if not latest:
                    if time.monotonic()-started > (60 if args.rgb_transport == "theora" else 5):
                        raise RuntimeError("NO_RGB_RECEIVED")
                    continue
                message, received = latest[0]
                if time.monotonic_ns()-received > 1_000_000_000:
                    raise RuntimeError("RGB_STREAM_STALLED")
                stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
                if stamp == seen or time.monotonic()-last_capture < .1:
                    continue
                seen, last_capture = stamp, time.monotonic()
                rgb = image_array(message)
                detected = model.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
                landmarks = [[dict(x=p.x, y=p.y, z=p.z) for p in hand] for hand in detected.hand_landmarks]
                hands = [shape_preview(p, rgb.shape[1], rgb.shape[0]) for p in landmarks]
                meta = frame_metadata(message, received)
                result = preview.evaluate(hands, received, meta["source_ns"], meta["frame"], context)
                pose = hands[0]["pose"] if len(hands) == 1 else "NO_HAND" if not hands else "MULTIPLE_HANDS"
                index = status["frames"]
                path = output/f"rgb-{index:04d}.jpg"
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                if not cv2.imwrite(str(path), bgr):
                    raise OSError("RGB screenshot write failed")
                event = dict(provenance="SENSOR", rgb=meta, timing_basis="callback_receipt_monotonic",
                             capture_clock_verified=False, mode=context[0], preview_request_id=context[1],
                             rgb_transport=args.rgb_transport,
                             open_hold_seconds=args.open_hold_seconds,
                             operator_case=label, operator_case_verified=False, hands=hands, landmarks=landmarks,
                             rgb_file=path.name, rgb_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **result)
                event.update(real_output_enabled=args.enable_gripper_output,
                             gripper_state_before=gripper.state if gripper is not None else "DISABLED")
                stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False)+"\n")
                stream.flush()
                status["frames"] += 1
                status["candidate_events"] += int(result["candidate_event"] is not None)
                if result["candidate_event"]:
                    last_candidate = result["candidate_event"]
                if gripper is not None:
                    if result["candidate_event"] == "OPEN_HAND_HELD_ORIENTATION_UNKNOWN":
                        gripper.start(context[1])
                    eligible = (context[0] == "OPEN_GRIPPER" and pose == "OPEN_HAND"
                                and result["reason"] == "PREVIEW_ONLY_UNVERIFIED"
                                and result["continuity_estimate"])
                    gripper.advance(eligible, received)
                    status.update(gripper_state=gripper.state,
                                  output_commands_attempted=gripper.output_commands_attempted,
                                  motion_commands_sent=gripper.output_commands_attempted > 0)
                    if gripper.state == "FAIL":
                        raise RuntimeError(gripper.reason)
                remaining = max(0, args.seconds-(time.monotonic()-started))
                text = f"{context[0]} {pose} {result['held_ns']/1e9:.1f}s last={last_candidate} left={remaining:.0f}s gripper={status['gripper_state']}"
                if result["candidate_event"] or time.monotonic()-last_print >= 1:
                    print(text, flush=True)
                    last_print = time.monotonic()
                if not args.no_window:
                    banner = "GRIPPER OUTPUT ENABLED / R TO ARM" if args.enable_gripper_output else "PREVIEW ONLY / NO ROBOT OUTPUT"
                    for line, caption in enumerate((banner, text, f"case={label} / surface UNKNOWN", f"q question | r open hand {args.open_hold_seconds:g}s | n inactive | ESC exit")):
                        cv2.putText(bgr, caption, (12, 25+line*27), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 255, 255), 1)
                    for hand in landmarks:
                        for p in hand:
                            cv2.circle(bgr, (int(p["x"]*rgb.shape[1]), int(p["y"]*rgb.shape[0])), 2, (0, 255, 0), -1)
                    cv2.imshow("Gesture preview", bgr)
            else:
                status["reason"] = "DURATION_ENDED"
                print("설정한 진단 시간이 끝나 종료합니다.", flush=True)
            if gripper is not None:
                gripper.abort(status["reason"] or "CAPTURE_ENDED")
                status["gripper_state"] = gripper.state
                if gripper.state == "FAIL":
                    raise RuntimeError(gripper.reason)
            status["status"] = "CAPTURED" if status["frames"] >= 2 else "UNKNOWN"
    except (Exception, KeyboardInterrupt) as exc:
        status.update(status="FAIL" if not isinstance(exc, KeyboardInterrupt) else "UNKNOWN", reason=str(exc) or "INTERRUPTED")
        print(f"진단 보류: {status['reason']}", flush=True)
    finally:
        stop_relay(relay)
        if relay_log is not None:
            relay_log.close()
        if gripper is not None:
            # Pending requests must never produce later writes during shutdown.
            if gripper.future is not None:
                gripper.future.cancel()
            status.update(gripper_state="FAIL" if gripper.busy else gripper.state,
                          output_commands_attempted=gripper.output_commands_attempted,
                          motion_commands_sent=gripper.output_commands_attempted > 0)
        if model is not None:
            model.close()
        if node is not None:
            node.destroy_node()
        if rclpy is not None and rclpy.ok():
            rclpy.shutdown()
        if cv2 is not None and not args.no_window:
            cv2.destroyAllWindows()
        (output/"result.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(status, ensure_ascii=False), flush=True)
    return 0 if status["status"] == "CAPTURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
