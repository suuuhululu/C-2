"""검토한 no_motion_check probe/save_rgbd 출력을 7단계 계약에 연결한다."""

from copy import deepcopy

from app.assembly_attempt import CONTEXT
from app.assembly_sensor import _utc, _window
from app.contracts import _integer, _object, _text


ROBOT_FIELDS = (("system/get_robot_state", "robot_state"), ("motion/check_motion", "status"),
                ("aux_control/get_current_velj", "joint_speed"), ("drl/get_drl_state", "drl_state"))


def _live_window(feedback, camera, sample_window):
    window = _window(sample_window)
    start, end = (_utc(window[key], f"sample_window.{key}") for key in ("request_utc", "response_utc"))
    if start is None or end is None:
        raise ValueError("live readings: host UTC query pair required")
    for record in [*feedback["service_reads"], feedback["gripper"]]:
        queried, received = (_utc(record[key], f"reading.{key}") for key in ("request_utc", "response_utc"))
        if queried is None or received is None or not start <= queried <= received <= end:
            raise ValueError("live readings: result outside acquisition window")
    if camera is not None:
        received = _utc(camera["received_utc"], "camera.received_utc")
        if received is None or not start <= received <= end:
            raise ValueError("live readings: camera receipt outside acquisition window")


def _read(feedback, prefix, path, request, field):
    matches = [record for record in feedback["service_reads"]
               if record["service"] == prefix + path and record["request"] == request]
    if len(matches) > 1:
        raise ValueError("readings: duplicate service/request result")
    if not matches:
        return None
    record = matches[0]
    response = record.get("response")
    if record["status"] != "READ" or not isinstance(response, dict) or response.get("success") is not True:
        return None
    return deepcopy(response.get(field))


def _camera_projection(camera):
    result = dict(success=False, rgb_stamp=None, depth_stamp=None, rgb_frame=None, depth_frame=None,
        rgb_encoding=None, depth_encoding=None, width=None, height=None, aligned_to_rgb=False,
        depth_zero_count=None, depth_unit="UNKNOWN")
    if camera is None:
        return result
    rgb, depth = camera["rgb_header"], camera["depth_header"]
    rgb_info, depth_info = camera["rgb_camera_info"], camera["depth_camera_info"]
    matching_size = all(rgb_info[key] == depth_info[key] for key in ("width", "height"))
    result.update(success=matching_size, rgb_stamp=deepcopy(rgb["stamp"]), depth_stamp=deepcopy(depth["stamp"]),
        rgb_frame=rgb["frame_id"], depth_frame=depth["frame_id"], rgb_encoding=camera["rgb_encoding"],
        depth_encoding=camera["depth_encoding"], width=rgb_info["width"], height=rgb_info["height"],
        aligned_to_rgb=camera["source_topic"] == "/camera/rgbd" and matching_size and rgb["frame_id"] == depth["frame_id"],
        depth_unit="mm" if camera["depth_unit"] == "mm (ROS RealSense 16UC1 output)" else "UNKNOWN")
    # 원본 fraction은 진단 원문에 남긴다. 반올림해 ROI나 정확한 zero_count로 바꾸지 않는다.
    return result


def project_no_motion_readings(feedback, camera, *, active, sequence, sample_window,
                              service_prefix, force_ref, live=False):
    """live=False가 기본이다. 과거 기록을 새 query 시각으로 완료 증거화하지 않는다.

live=True는 조회 직전 context/clock 창을 동결한 실행 도구만 사용한다.
원본의 per-query UTC/error·CameraInfo·hash는 반환 raw에 별도 보존한다.
"""
    _object(active, CONTEXT, "active")
    _integer(sequence, 0, None, "sequence")
    _integer(force_ref, 0, 1, "force_ref")
    _text(service_prefix, "service_prefix")
    if not service_prefix.startswith("/") or not service_prefix.endswith("/"):
        raise ValueError("service_prefix: absolute namespace ending in slash required")
    if type(live) is not bool:
        raise ValueError("live: expected explicit boolean")
    for key in ("motion_commands_sent", "gripper_commands_sent"):
        if type(feedback[key]) is not int or feedback[key] != 0:
            raise ValueError("readings: nonzero/unknown command count")
    if not isinstance(feedback["service_reads"], list):
        raise ValueError("readings.service_reads: expected array")
    if live:
        _live_window(feedback, camera, sample_window)
    values = [_read(feedback, service_prefix, path, {}, field) for path, field in ROBOT_FIELDS]
    robot = dict(success=all(value is not None for value in values), robot_state=values[0],
        motion_status=values[1], joint_speed=values[2], drl_state=values[3])
    force = _read(feedback, service_prefix, "aux_control/get_tool_force", {"ref":force_ref}, "tool_force")
    wrench = dict(success=force is not None, tool_force=force, ref=force_ref,
        force_frame="UNKNOWN", moment_frame="UNKNOWN", frames_verified=False,
        device_stamp=None, device_clock_id=None)
    raw_gripper = feedback["gripper"]
    readable = raw_gripper["status"] == "READ"
    if readable and raw_gripper["registers"] != {"width":267, "status":268}:
        raise ValueError("readings.gripper: unexpected register mapping")
    if readable and any(raw_gripper.get(key) is None for key in ("raw_status", "raw_width")):
        raise ValueError("readings.gripper: READ requires both raw registers")
    gripper = dict(success=readable, status_register=raw_gripper.get("raw_status") if readable else None,
        width_register=raw_gripper.get("raw_width") if readable else None)
    snapshot = dict(metadata={**{key:deepcopy(value) for key,value in active.items() if key != "opened_at"},
            "stamp":sample_window["started_at"], "sequence":sequence, "valid":live},
        sample_window=deepcopy(sample_window), robot=robot, wrench=wrench, gripper=gripper,
        camera=_camera_projection(camera),
        human_confirmation=dict.fromkeys(("operator", "confirmed_at_utc", "stopped", "execution_ended", "released")))
    return dict(snapshot=snapshot, raw=dict(feedback=deepcopy(feedback), camera=deepcopy(camera)))
