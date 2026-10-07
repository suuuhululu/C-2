"""현장 읽기 값의 로컬 projection. 조회·송신·결착 판정은 수행하지 않는다.

metadata/sample_window는 조회 시작 전에 동결한 attempt의 동일 host clock이다.
UTC/ROS/device 시각을 이 clock으로 변환하지 않는다. 원자료는 별도로 보존한다.
"""

from copy import deepcopy
from datetime import datetime
from math import isfinite

from app.assembly_evidence import check_evidence_context
from app.contracts import _integer, _object, _text


FIELDS = ("metadata", "sample_window", "robot", "wrench", "gripper", "camera", "human_confirmation")


def _number(value, path):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{path}: expected finite number")


def _vector(value, path):
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 6:
        raise ValueError(f"{path}: expected six axes or null")
    for number in value:
        _number(number, path)


def _utc(value, path):
    if value is None:
        return None
    _text(value, path)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{path}: expected ISO timestamp with timezone") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{path}: timezone is required")
    return parsed


def _window(value):
    window = _object(value, ("clock_id", "started_at", "finished_at", "request_utc", "response_utc"), "sample_window")
    _text(window["clock_id"], "sample_window.clock_id")
    for key in ("started_at", "finished_at"):
        _number(window[key], f"sample_window.{key}")
        if window[key] < 0:
            raise ValueError("sample_window: negative time")
    start, finish = (_utc(window[key], f"sample_window.{key}") for key in ("request_utc", "response_utc"))
    if (start is None) != (finish is None) or (start is not None and finish < start):
        raise ValueError("sample_window: invalid UTC query pair")
    return window


def _robot(value):
    robot = _object(value, ("success", "robot_state", "motion_status", "joint_speed", "drl_state"), "robot")
    if type(robot["success"]) is not bool:
        raise ValueError("robot.success: expected boolean")
    for key in ("robot_state", "motion_status", "drl_state"):
        if robot[key] is not None:
            _integer(robot[key], 0, None, f"robot.{key}")
    _vector(robot["joint_speed"], "robot.joint_speed")
    if not robot["success"] or any(robot[key] is None for key in ("robot_state", "motion_status", "joint_speed")):
        return None
    return robot["robot_state"] == 1 and robot["motion_status"] == 0 and all(speed == 0 for speed in robot["joint_speed"])


def _wrench(value):
    fields = ("success", "tool_force", "ref", "force_frame", "moment_frame", "frames_verified", "device_stamp", "device_clock_id")
    wrench = _object(value, fields, "wrench")
    for key in ("success", "frames_verified"):
        if type(wrench[key]) is not bool:
            raise ValueError(f"wrench.{key}: expected boolean")
    _vector(wrench["tool_force"], "wrench.tool_force")
    _integer(wrench["ref"], 0, 1, "wrench.ref")
    for key in ("force_frame", "moment_frame"):
        if wrench[key] not in ("BASE", "TOOL", "UNKNOWN"):
            raise ValueError(f"wrench.{key}: unsupported reported frame")
    stamp, clock = wrench["device_stamp"], wrench["device_clock_id"]
    if stamp is not None:
        _number(stamp, "wrench.device_stamp")
        if stamp < 0:
            raise ValueError("wrench.device_stamp: negative time")
    if clock is not None:
        _text(clock, "wrench.device_clock_id")
    if (stamp is None) != (clock is None):
        raise ValueError("wrench: device timestamp and clock must be paired")
    return deepcopy(wrench["tool_force"]) if wrench["success"] else None


def _gripper(value):
    gripper = _object(value, ("success", "status_register", "width_register"), "gripper")
    if type(gripper["success"]) is not bool:
        raise ValueError("gripper.success: expected boolean")
    for key in ("status_register", "width_register"):
        if gripper[key] is not None:
            _integer(gripper[key], 0, 65535, f"gripper.{key}")
    status = gripper["status_register"] if gripper["success"] else None
    width = gripper["width_register"] if gripper["success"] else None
    # 현장 문서가 확인한 두 차단 비트만 해석한다. 폭/파지 없음은 해제 완료가 아니다.
    return [bit for bit in (3, 6) if status is not None and status & (1 << bit)], None if width is None else width / 10


def _camera(value):
    fields = ("success", "rgb_stamp", "depth_stamp", "rgb_frame", "depth_frame", "rgb_encoding", "depth_encoding",
              "width", "height", "aligned_to_rgb", "depth_zero_count", "depth_unit")
    camera = _object(value, fields, "camera")
    for key in ("success", "aligned_to_rgb"):
        if type(camera[key]) is not bool:
            raise ValueError(f"camera.{key}: expected boolean")
    for key in ("rgb_stamp", "depth_stamp"):
        if camera[key] is not None:
            stamp = _object(camera[key], ("sec", "nanosec"), f"camera.{key}")
            _integer(stamp["sec"], 0, None, f"camera.{key}.sec")
            _integer(stamp["nanosec"], 0, 999999999, f"camera.{key}.nanosec")
    for key in ("rgb_frame", "depth_frame", "rgb_encoding", "depth_encoding"):
        if camera[key] is not None:
            _text(camera[key], f"camera.{key}")
    for key in ("width", "height", "depth_zero_count"):
        if camera[key] is not None:
            _integer(camera[key], 0, None, f"camera.{key}")
    if camera["depth_unit"] not in ("mm", "UNKNOWN"):
        raise ValueError("camera.depth_unit: unsupported declared unit")
    width, height, zeros = (camera[key] for key in ("width", "height", "depth_zero_count"))
    if zeros is not None and (not width or not height or zeros > width * height):
        raise ValueError("camera.depth_zero_count: exceeds full-frame pixel count")
    checks = ((camera["success"], "CAMERA_READ_FAILED"),
        (camera["rgb_stamp"] is not None and camera["rgb_stamp"] == camera["depth_stamp"], "RGB_DEPTH_STAMP_MISMATCH"),
        (camera["rgb_frame"] is not None and camera["rgb_frame"] == camera["depth_frame"] and camera["aligned_to_rgb"], "RGB_DEPTH_ALIGNMENT_UNKNOWN"),
        (camera["rgb_encoding"] == "rgb8" and camera["depth_encoding"] == "16UC1", "RGB_DEPTH_ENCODING_UNSUPPORTED"),
        (camera["depth_unit"] == "mm", "DEPTH_UNIT_UNKNOWN"),
        (bool(width and height), "IMAGE_SIZE_UNKNOWN"))
    reasons = [reason for accepted, reason in checks if not accepted]
    return reasons


def _human(value):
    human = _object(value, ("operator", "confirmed_at_utc", "stopped", "execution_ended", "released"), "human_confirmation")
    if human["operator"] is not None:
        _text(human["operator"], "human_confirmation.operator")
    timestamp = _utc(human["confirmed_at_utc"], "human_confirmation.confirmed_at_utc")
    for key in ("stopped", "execution_ended", "released"):
        if human[key] is not None and type(human[key]) is not bool:
            raise ValueError(f"human_confirmation.{key}: expected boolean or null")
    if any(human[key] is not None for key in ("stopped", "execution_ended", "released")) and (timestamp is None or human["operator"] is None):
        raise ValueError("human_confirmation: operator and timestamp required for reported facts")


def normalize_sensor_snapshot(snapshot, *, active, now, max_age, last_sequence, last_stamp, clock_id):
    """조회 창의 진단값과 안전 차단만 반환한다. 입력/SM 상태를 변경하지 않는다."""
    snapshot = _object(snapshot, FIELDS, "snapshot")
    window = _window(snapshot["sample_window"])
    _text(clock_id, "clock_id")
    idle, force = _robot(snapshot["robot"]), _wrench(snapshot["wrench"])
    faults, width = _gripper(snapshot["gripper"])
    camera_reasons = _camera(snapshot["camera"])
    _human(snapshot["human_confirmation"])
    meta = snapshot["metadata"]
    guard = check_evidence_context(active, meta, now=now, max_age=max_age, last_sequence=last_sequence)
    reason = None
    if window["clock_id"] != clock_id:
        reason = "SENSOR_CLOCK_MISMATCH"
    elif window["started_at"] > window["finished_at"] or window["finished_at"] > now or meta["stamp"] != window["started_at"]:
        reason = "INVALID_ACQUISITION_WINDOW"
    elif last_stamp is not None and meta["stamp"] < last_stamp:
        reason = "OUT_OF_ORDER_STAMP"
    ordered_invalid = guard["reason"] == "INVALID_EVIDENCE" and check_evidence_context(active, {**meta, "valid":True}, now=now, max_age=max_age, last_sequence=last_sequence)["accepted"]
    if reason or (not guard["accepted"] and not ordered_invalid):
        return dict(accepted=False, reason=reason or guard["reason"], event=None, diagnostic=None)
    if ordered_invalid:
        idle, force, faults, width = None, None, [], None
        camera_reasons.append("INVALID_EVIDENCE")
    motion = False if faults and guard["accepted"] else None
    event = dict(source="motion_permitted", metadata={**meta, "valid":motion is False}, value=motion)
    diagnostic = dict(raw=deepcopy(snapshot), robot_idle_indication=idle,
        wrench_values=force, force_unit="N", moment_unit="N*m",
        wrench_time_basis="HOST_QUERY_WINDOW" if snapshot["wrench"]["device_stamp"] is None else "DEVICE_UNBOUND",
        wrench_contact_usable=False, gripper_width_mm=width, gripper_fault_bits=faults,
        rgbd_metadata_usable=not camera_reasons, rgbd_reasons=camera_reasons,
        depth_unit="mm" if not ordered_invalid and snapshot["camera"]["success"] and snapshot["camera"]["depth_encoding"] == "16UC1" and snapshot["camera"]["depth_unit"] == "mm" else None,
        depth_zero_meaning="MISSING_MEASUREMENT", depth_zero_scope="FULL_FRAME", image_content_verified=False,
        physical_facts=dict.fromkeys(("stopped", "execution_ended", "released", "at_observe")),
        execution_result=None, contact_state="UNKNOWN", vision_verdict="UNKNOWN", motion_permitted=motion)
    return dict(accepted=guard["accepted"], reason="GRIPPER_SAFETY_INHIBIT" if motion is False else guard["reason"] if ordered_invalid else "DIAGNOSTIC_ONLY",
                event=event, diagnostic=diagnostic)
