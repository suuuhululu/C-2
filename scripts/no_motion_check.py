"""무이동 센서 기록. ROS 조회와 RG2 holding register 읽기만 허용한다."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


SCENES = {
    "reference_only": "기준 블록만 있음",
    "fully_seated": "완전 결착",
    "partially_seated": "부분 결착",
    "occluded": "가림",
    "reference_moved": "기준 블록 이동",
}
# 명령·정지·복구·개폐 서비스는 이 도구에 포함하지 않는다.
READ_SERVICES = (
    ("system/get_robot_state", "GetRobotState", {}),
    ("motion/check_motion", "CheckMotion", {}),
    ("drl/get_drl_state", "GetDrlState", {}),
    ("aux_control/get_current_velj", "GetCurrentVelj", {}),
    ("aux_control/get_tool_force", "GetToolForce", {"ref": 0}),
    ("aux_control/get_tool_force", "GetToolForce", {"ref": 1}),
    ("tcp/get_current_tcp", "GetCurrentTcp", {}),
    ("tool/get_current_tool", "GetCurrentTool", {}),
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def validate_truth(value, scene):
    if value.get("scene") != scene or scene not in SCENES:
        raise ValueError("정답의 scene이 촬영 장면과 같아야 합니다")
    for key in ("operator", "ground_truth", "stop_method", "execution_end_method"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"사람 확인 필요: {key}")
    for key in ("robot_physically_stopped", "execution_ended", "scene_ready"):
        if value.get(key) is not True:
            raise ValueError(f"사람의 명시적 true 확인 필요: {key}")
    return value


def call_readonly(node, typename, path, fields, timeout=3):
    from rosidl_runtime_py.convert import message_to_ordereddict

    client = node.create_client(typename, path)
    result = dict(service=path, request=fields, request_utc=utc_now())
    start = time.monotonic()
    try:
        if not client.wait_for_service(timeout_sec=timeout):
            raise TimeoutError("SERVICE_UNAVAILABLE")
        request = typename.Request()
        for key, val in fields.items():
            setattr(request, key, val)
        future = client.call_async(request)
        import rclpy
        rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
        if not future.done():
            future.cancel()
            raise TimeoutError("SERVICE_RESPONSE_TIMEOUT")
        response = future.result()
        if response is None:
            raise RuntimeError("EMPTY_RESPONSE")
        result["response"] = message_to_ordereddict(response)
        result["status"] = "READ" if getattr(response, "success", True) else "FAILED"
    except Exception as error:
        result.update(status="UNREADABLE", error=str(error))
    finally:
        result.update(response_utc=utc_now(), elapsed_s=time.monotonic() - start)
        node.destroy_client(client)
    return result


def gripper_read(config_path):
    result = dict(request_utc=utc_now(), registers={"width": 267, "status": 268},
                  device_timestamp=None)
    client = None
    try:
        from pymodbus.client import ModbusTcpClient
        settings = json.loads(Path(config_path).read_text())["settings"]
        client = ModbusTcpClient(settings["gripper_ip"], port=502, timeout=2)
        if not client.connect():
            raise ConnectionError("RG2_READ_CONNECTION_FAILED")
        response = client.read_holding_registers(address=267, count=2, slave=65)
        if response.isError() or len(response.registers) != 2:
            raise RuntimeError(f"RG2_REGISTER_READ_FAILED: {response}")
        width, status = response.registers
        result.update(status="READ", raw_width=width, raw_status=status,
                      width_mm=width / 10, busy=bool(status & 1),
                      grip_detected=bool(status & 2), safety_bits=status & 124,
                      release_completed="UNVERIFIED_NO_RELEASE_COMMAND_IN_THIS_TEST")
    except Exception as error:
        result.update(status="UNREADABLE", error=str(error))
    finally:
        if client is not None:
            client.close()
        result["response_utc"] = utc_now()
    return result


def probe(node, config_path):
    from dsr_msgs2 import srv
    from realsense2_camera_msgs.srv import DeviceInfo

    config = json.loads(Path(config_path).read_text())
    prefix = f"/{config['settings']['robot_id']}/dsr_controller2/"
    records = [call_readonly(node, getattr(srv, name), prefix + path, fields)
               for path, name, fields in READ_SERVICES]
    return dict(recorded_utc=utc_now(), motion_commands_sent=0,
                gripper_commands_sent=0, service_reads=records,
                gripper=gripper_read(config_path),
                camera=call_readonly(node, DeviceInfo, "/camera/device_info", {}),
                timestamp_note="서비스 응답에는 계측 시각 없음. request/response UTC는 PC 기록 시각.")


def require_idle(feedback):
    reads = {r["service"].split("/dsr_controller2/")[-1]: r
             for r in feedback["service_reads"]}
    for path, field, expected in (("system/get_robot_state", "robot_state", 1),
                                  ("motion/check_motion", "status", 0)):
        record = reads[path]
        if record["status"] != "READ" or record["response"][field] != expected:
            raise RuntimeError("ROBOT_IDLE_READ_NOT_CONFIRMED")
    drl = reads.get("drl/get_drl_state")
    if drl and drl["status"] == "READ" and drl["response"]["drl_state"] in (0, 2):
        raise RuntimeError("ROBOT_PROGRAM_PLAY_OR_HOLD")


def session(args):
    """각 장면의 준비·정답은 현장 사람이 직접 입력하며 자동 라벨링하지 않는다."""
    args.out.mkdir(parents=True, exist_ok=False)
    print("무이동 5장면 기록. 로봇/그리퍼/카메라 설정을 변경하지 않습니다.", flush=True)
    operator = input("확인자 이름: ").strip()
    stop_method = input("로봇 물리 정지 확인 방법: ").strip()
    end_method = input("실행 프로그램 종료 확인 방법 (DRL=3만으로는 확인 불가): ").strip()
    if not all((operator, stop_method, end_method)):
        raise ValueError("확인자와 정지/종료 확인 방법이 필요합니다")
    for index, (scene, label) in enumerate(SCENES.items(), 1):
        print(f"\n{index}/5 {label}: 사람만 장면을 준비하세요.", flush=True)
        ready = input("현재도 로봇 정지/프로그램 종료이고 장면 준비 완료면 '확인' 입력: ").strip()
        if ready != "확인":
            print("이번 장면은 촬영하지 않았습니다. 재실행 시 새 --out 경로를 사용하세요.")
            return 1
        ground_truth = input("사람 정답 (블록 종류/색/배치/결착·가림 상태, 미확인은 미확인): ").strip()
        truth = dict(scene=scene, operator=operator, ground_truth=ground_truth,
                     stop_method=stop_method, execution_end_method=end_method,
                     robot_physically_stopped=True, execution_ended=True, scene_ready=True,
                     confirmed_utc=utc_now())
        validate_truth(truth, scene)
        truth_path = args.out / f"{index:02d}_{scene}_truth.json"
        write_json(truth_path, truth)
        code = main(["capture", "--out", str(args.out / f"{index:02d}_{scene}"),
                     "--config", str(args.config), "--scene", scene, "--truth", str(truth_path)])
        if code:
            return code
    write_json(args.out / "session_result.json", dict(status="FIVE_SCENES_RECORDED",
                motion_commands_sent=0, gripper_commands_sent=0, operator=operator))
    return 0


def image_array(message):
    import numpy as np

    if message.encoding in ("rgb8", "bgr8"):
        dtype, channels = np.dtype("u1"), 3
    elif message.encoding == "16UC1":
        dtype, channels = np.dtype(">u2" if message.is_bigendian else "<u2"), 1
    else:
        raise ValueError(f"지원하지 않는 image encoding: {message.encoding}")
    row_bytes = message.width * channels * dtype.itemsize
    if message.step < row_bytes or len(message.data) != message.height * message.step:
        raise ValueError("IMAGE_BUFFER_SIZE_INVALID")
    rows = np.frombuffer(bytes(message.data), dtype=np.uint8).reshape(message.height, message.step)
    pixels = rows[:, :row_bytes].copy().view(dtype)
    shape = (message.height, message.width, channels) if channels == 3 else (message.height, message.width)
    return pixels.reshape(shape).astype(dtype.newbyteorder("="), copy=False)


def receive_rgbd(node, timeout=10):
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from realsense2_camera_msgs.msg import RGBD

    frames = []
    subscription = node.create_subscription(RGBD, "/camera/rgbd", frames.append,
                                             qos_profile_sensor_data)
    deadline = time.monotonic() + timeout
    try:
        while not frames and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        if not frames:
            raise TimeoutError("RGBD_TOPIC_TIMEOUT")
        return frames[-1]
    finally:
        node.destroy_subscription(subscription)


def save_rgbd(directory, message):
    import cv2
    import numpy as np
    rgb, depth = image_array(message.rgb), image_array(message.depth)
    if message.depth.encoding != "16UC1":
        raise ValueError("RAW_DEPTH_16UC1_REQUIRED")
    rgb_ns = message.rgb.header.stamp.sec * 10**9 + message.rgb.header.stamp.nanosec
    depth_ns = message.depth.header.stamp.sec * 10**9 + message.depth.header.stamp.nanosec
    if rgb_ns != depth_ns:
        raise ValueError(f"RGB_DEPTH_STAMP_MISMATCH: {rgb_ns} != {depth_ns}")
    from rosidl_runtime_py.convert import message_to_ordereddict

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) if message.rgb.encoding == "rgb8" else rgb
    np.save(directory / "depth_raw.npy", depth, allow_pickle=False)
    preview = cv2.applyColorMap(cv2.convertScaleAbs(depth, alpha=255 / 1500), cv2.COLORMAP_TURBO)
    preview[depth == 0] = 0
    for name, pixels in (("rgb.png", bgr), ("depth_raw.png", depth), ("depth_preview.png", preview)):
        if not cv2.imwrite(str(directory / name), pixels):
            raise OSError(f"IMAGE_WRITE_FAILED: {name}")
    metadata = dict(received_utc=utc_now(), source_topic="/camera/rgbd",
                    rgb_header=message_to_ordereddict(message.rgb.header),
                    depth_header=message_to_ordereddict(message.depth.header),
                    rgb_encoding=message.rgb.encoding, depth_encoding=message.depth.encoding,
                    rgb_camera_info=message_to_ordereddict(message.rgb_camera_info),
                    depth_camera_info=message_to_ordereddict(message.depth_camera_info),
                    depth_unit="mm (ROS RealSense 16UC1 output)",
                    depth_zero="invalid measurement; not empty board",
                    depth_zero_fraction=float(np.mean(depth == 0)),
                    preview_range_mm=[0, 1500],
                    geometry_calibration_verified=False)
    metadata["sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in directory.iterdir() if p.is_file()}
    write_json(directory / "camera.json", metadata)
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("probe", "snapshot", "capture", "session"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=Path("interfaces/robot_trial.json"))
    parser.add_argument("--scene", choices=tuple(SCENES))
    parser.add_argument("--truth", type=Path)
    args = parser.parse_args(argv)
    if args.action == "session":
        return session(args)
    truth = None
    if args.action == "capture":
        if args.truth is None:
            parser.error("capture requires --scene and --truth")
        truth = validate_truth(json.loads(args.truth.read_text()), args.scene)
    args.out.mkdir(parents=True, exist_ok=False)
    import rclpy
    from rclpy.node import Node

    rclpy.init()
    node = Node("c2_no_motion_recorder")
    try:
        before = probe(node, args.config)
        write_json(args.out / "feedback_before.json", before)
        if args.action == "capture":
            require_idle(before)
        if args.action != "probe":
            save_rgbd(args.out, receive_rgbd(node))
            after = probe(node, args.config)
            write_json(args.out / "feedback_after.json", after)
            if args.action == "capture":
                require_idle(after)
            write_json(args.out / "human_truth.json", truth or dict(
                status="DIAGNOSTIC_SNAPSHOT_NOT_A_LABELLED_TEST_SCENE"))
        write_json(args.out / "result.json", dict(status="RECORDED", action=args.action,
                   scene=args.scene, labelled_scene=truth is not None,
                   motion_commands_sent=0, gripper_commands_sent=0))
        print(f"기록: {args.out}")
        return 0
    except Exception as error:
        write_json(args.out / "result.json", dict(status="FAILED", error=str(error),
                   motion_commands_sent=0, gripper_commands_sent=0))
        print(f"기록 보류: {error}")
        return 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
