"""이미 파지한 블록의 비접촉 접근/정지/복귀. 장치 생성과 조립 완료 채택은 하지 않는다."""

from copy import deepcopy
import math
import re
import time

from app.contracts import _integer, _object, _text, validate_block


CONNECTION = ("robot_id", "tcp", "tool", "gripper_ip", "ros_domain_id")
TIMING = ("service_timeout_s", "sample_max_duration_s", "poll_interval_s", "motion_timeout_s", "stop_timeout_s", "hold_s")
LIMITS = ("position_tolerance_mm", "orientation_tolerance_deg", "linear_still_mm_s",
          "angular_still_deg_s", "force_delta_n", "moment_delta_nm", "path_min_clearance_mm")
CONFIRMATIONS = ("onsite_operator", "exclusive_control", "tcp_tool_verified", "already_holding",
                 "noncontact_route_reviewed", "compliance_inactive", "feedback_and_wrench_verified")


def vector(value, count, name):
    if not isinstance(value, list) or len(value) != count or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError(f"{name}: expected {count} finite numbers")
    return [float(v) for v in value]


def motion_still(sample, policy=None):
    policy=policy or {}
    speed=vector(sample['velx'],6,'motion velocity')
    return (sample['motion_status']==0 and
            max(map(abs,speed[:3]))<=policy.get('linear_mm_s',0.) and
            max(map(abs,speed[3:]))<=policy.get('angular_deg_s',0.))


def pose_error(actual, expected):
    from scipy.spatial.transform import Rotation
    actual, expected = vector(actual, 6, "actual pose"), vector(expected, 6, "expected pose")
    rotation = Rotation.from_euler("ZYZ", actual[3:], degrees=True).inv() * Rotation.from_euler("ZYZ", expected[3:], degrees=True)
    return math.dist(actual[:3], expected[:3]), math.degrees(rotation.magnitude())


def prepare_motion(value):
    config = deepcopy(_object(value, ("config_id", "mode", "target", "connection", "start_posx",
        "waypoints", "velocity", "acceleration", "timing", "limits", "confirmations", "pose_source"), "motion"))
    _text(config["config_id"], "config_id")
    if config["mode"] not in ("FAKE", "REAL"):
        raise ValueError("mode: explicit FAKE or REAL required")
    target = validate_block(config["target"])
    if (target["brick_type"], target["layer"]) != ("2x2x1", 1) or max(target["x"], target["y"]) > 22:
        raise ValueError("target: layer-1 2x2 inside board required")
    connection = _object(config["connection"], CONNECTION, "connection")
    for field in CONNECTION[:-1]:
        _text(connection[field], field)
    if not re.fullmatch(r"[A-Za-z0-9_]+", connection["robot_id"]):
        raise ValueError("robot_id: invalid identifier")
    missing = []
    if connection["ros_domain_id"] is None:
        missing.append("connection.ros_domain_id")
    else:
        _integer(connection["ros_domain_id"], 0, 232, "ros_domain_id")
    if config["pose_source"] != "ON_SITE_TAUGHT_NONCONTACT":
        raise ValueError("pose_source: onsite taught noncontact poses required")
    for field, names in (("timing", TIMING), ("limits", LIMITS)):
        values = _object(config[field], names, field)
        for name, number in values.items():
            if number is None:
                missing.append(f"{field}.{name}")
            elif type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
                raise ValueError(f"{field}.{name}: positive finite value required")
            else:
                values[name] = float(number)
    flags = _object(config["confirmations"], CONFIRMATIONS, "confirmations")
    for name, flag in flags.items():
        if type(flag) is not bool:
            raise ValueError(f"confirmations.{name}: boolean required")
        if not flag:
            missing.append(f"confirmations.{name}")
    for name in ("velocity", "acceleration", "start_posx"):
        if config[name] is None:
            missing.append(name)
        else:
            config[name] = vector(config[name], 6 if name == "start_posx" else 2, name)
            if name != "start_posx" and min(config[name]) <= 0:
                raise ValueError(f"{name}: positive linear/angular values required")
    if config["waypoints"] is None or config["waypoints"] == []:
        missing.append("waypoints")
    elif not isinstance(config["waypoints"], list):
        raise ValueError("waypoints: pose array required")
    else:
        config["waypoints"] = [vector(p, 6, "waypoint") for p in config["waypoints"]]
        if config["start_posx"] is not None:
            for p in config["waypoints"]:
                # 실측 교시 방향의 차이는 현장에서 검토한 허용각으로 검사한다.
                # 미입력 상태에서는 이미 missing에 기록되어 경로가 실행되지 않는다.
                tolerance = config["limits"]["orientation_tolerance_deg"]
                if tolerance is not None and pose_error(p, config["start_posx"])[1] > tolerance:
                    raise ValueError("waypoints: taught orientation difference exceeds reviewed orientation_tolerance_deg")
    forward = config["waypoints"] or []
    if not missing:
        timing = config["timing"]
        if (timing["service_timeout_s"] >= min(timing["motion_timeout_s"], timing["stop_timeout_s"])
                or timing["poll_interval_s"] > min(timing["motion_timeout_s"], timing["stop_timeout_s"], timing["hold_s"])):
            raise ValueError("timing: query/poll must fit the motion, stop and hold windows")
    route = forward + list(reversed([config["start_posx"], *forward[:-1]])) if not missing else []
    return dict(status="NOT_READY" if missing else "PLAN_READY", missing=missing,
                config=config, route=route, gripper_commands=0, assembly_completion=False)


def _still(sample, config):
    _integer(sample["motion_status"], 0, 2, "motion_status")
    duration = sample["query_duration_s"]
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= config["timing"]["sample_max_duration_s"]:
        raise RuntimeError("FEEDBACK_QUERY_TOO_SLOW")
    speed = vector(sample["velx"], 6, "velx")
    limits = config["limits"]
    return (sample["motion_status"] == 0 and max(abs(v) for v in speed[:3]) <= limits["linear_still_mm_s"]
            and max(abs(v) for v in speed[3:]) <= limits["angular_still_deg_s"])


def _at(sample, pose, config):
    mm, degrees = pose_error(sample["posx"], pose)
    return mm <= config["limits"]["position_tolerance_mm"] and degrees <= config["limits"]["orientation_tolerance_deg"]


def checked_sample(driver, config, baseline=None, *, record=None):
    sample = driver.sample()
    vector(sample["posx"], 6, "feedback posx")
    wrench = vector(sample["wrench"], 6, "wrench")
    vector(sample["velx"], 6, "velx")
    if record is not None:
        delta = None if baseline is None else [v-b for v, b in zip(wrench, baseline)]
        record("NONCONTACT_SAMPLE", dict(sample, baseline_wrench=baseline,
            wrench_delta=delta, force_delta_norm_n=None if delta is None else math.hypot(*delta[:3]),
            moment_delta_norm_nm=None if delta is None else math.hypot(*delta[3:]),
            contact_force_verified=False))
    for key in ("robot_state", "robot_mode", "motion_status", "gripper_status", "drl_state"):
        _integer(sample[key], 0, None, key)
    duration = sample["query_duration_s"]
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= config["timing"]["sample_max_duration_s"]:
        raise RuntimeError("FEEDBACK_QUERY_TOO_SLOW")
    if (sample["robot_state"] not in (1, 2) or sample["robot_mode"] != 1
            or sample["motion_status"] not in (0, 1, 2) or sample["drl_state"] not in (1, 3)):
        raise RuntimeError("ROBOT_STATE_INVALID")
    if sample["tcp"] != config["connection"]["tcp"] or sample["tool"] != config["connection"]["tool"]:
        raise RuntimeError("TCP_TOOL_CHANGED")
    if sample["gripper_status"] != 2:
        raise RuntimeError("GRASP_NOT_CONFIRMED_OR_GRIPPER_FAULT")
    if type(sample["gripper_width_mm"]) not in (int, float) or not math.isfinite(sample["gripper_width_mm"]) or not 0 <= sample["gripper_width_mm"] <= 110:
        raise RuntimeError("GRIPPER_WIDTH_INVALID")
    if baseline is not None and (math.dist(wrench[:3], baseline[:3]) >= config["limits"]["force_delta_n"]
                                or math.dist(wrench[3:], baseline[3:]) >= config["limits"]["moment_delta_nm"]):
        raise RuntimeError("UNEXPECTED_WRENCH_CHANGE")
    return sample


def preflight(driver, plan, record):
    if plan != prepare_motion(plan["config"]):
        raise ValueError("NONCONTACT_PLAN_CHANGED")
    if plan["status"] != "PLAN_READY":
        raise ValueError("NONCONTACT_INPUTS_NOT_READY")
    config = plan["config"]
    if driver.mode != config["mode"]:
        raise ValueError("DRIVER_MODE_MISMATCH")
    first = checked_sample(driver, config, record=lambda event, data: record(event, dict(data, phase="PREFLIGHT")))
    if first["robot_state"] != 1 or not _still(first, config) or not _at(first, config["start_posx"], config):
        raise RuntimeError("START_NOT_CONFIRMED_IDLE_AT_TAUGHT_POSE")
    for pose in config["waypoints"] + [config["start_posx"]]:
        if not _at(dict(posx=driver.check_pose(pose)), pose, config):
            raise RuntimeError("IK_FK_MISMATCH")
    record("NONCONTACT_PREFLIGHT", first)
    return first["wrench"]


def run_noncontact(driver, plan, record, *, cancelled=lambda: False,
                   now=time.monotonic, sleep=time.sleep):
    config, attempted, ack_pending = plan["config"], False, False
    def check_cancel():
        if cancelled():
            raise RuntimeError("OPERATOR_CANCELLED")
    def read_sample(phase, index, pose):
        return checked_sample(driver, config, baseline, record=lambda event, data:
            record(event, dict(data, phase=phase, segment_index=index, target_posx=pose)))
    def wait_at(pose, index):
        deadline = now() + config["timing"]["motion_timeout_s"]
        while True:
            check_cancel()
            if now() >= deadline:
                raise TimeoutError("MOTION_TIMEOUT")
            sample = read_sample("MOVE", index, pose)
            record("NONCONTACT_FEEDBACK", sample)
            if now() >= deadline:
                raise TimeoutError("MOTION_TIMEOUT")
            if _still(sample, config) and _at(sample, pose, config):
                return
            sleep(config["timing"]["poll_interval_s"])
    try:
        check_cancel()
        baseline = preflight(driver, plan, record)
        for index, pose in enumerate(plan["route"]):
            check_cancel()
            sample = read_sample("BEFORE_MOVE", index, pose)
            if not _still(sample, config):
                raise RuntimeError("NOT_IDLE_BEFORE_NEXT_MOVE")
            previous = config["start_posx"] if index == 0 else plan["route"][index-1]
            if not _at(sample, previous, config):
                raise RuntimeError("TAUGHT_SEGMENT_START_LOST")
            record("NONCONTACT_MOVE_REQUEST", dict(index=index, posx=pose,
                velocity=config["velocity"], acceleration=config["acceleration"]))
            attempted = True  # ACK 미수신/timeout도 이동이 시작됐을 가능성이 있다.
            ack_pending = True
            driver.move_line_async(pose, config["velocity"], config["acceleration"])
            ack_pending = False
            record("NONCONTACT_MOVE_ACK", dict(index=index, posx=pose))
            wait_at(pose, index)
            record("NONCONTACT_POSE_CONFIRMED", dict(index=index, posx=pose))
            if index == len(config["waypoints"])-1:
                deadline = now() + config["timing"]["hold_s"]
                while now() < deadline:
                    check_cancel()
                    sample = read_sample("HOLD", index, pose)
                    if not _still(sample, config) or not _at(sample, pose, config):
                        raise RuntimeError("PRECONTACT_HOLD_LOST")
                    record("NONCONTACT_HOLD_FEEDBACK", sample)
                    sleep(config["timing"]["poll_interval_s"])
        check_cancel()
        result = dict(status="NONCONTACT_TRIAL_COMPLETE", returned_to_start=True, stopped=True,
                      block_still_held=True, assembled=False, gripper_commands=0)
        record("NONCONTACT_COMPLETE", result)
        return result
    except (Exception, KeyboardInterrupt) as error:
        result = dict(status="NONCONTACT_FAILED", reason=str(error) or "KEYBOARD_INTERRUPT",
                      returned_to_start=False, stopped=None, assembled=False, stop_ack=False, gripper_commands=0)
        if attempted:
            try:
                result["stop_requested"] = True
                driver.stop()
                result["stop_ack"] = True
                record("NONCONTACT_STOP_ACK", dict(stop_mode=1))
                deadline = now() + config["timing"]["stop_timeout_s"]
                while now() < deadline:
                    sample = driver.motion_feedback()
                    record("NONCONTACT_STOP_FEEDBACK", sample)
                    if now() < deadline and _still(sample, config):
                        result["stopped"] = True
                        break
                    sleep(config["timing"]["poll_interval_s"])
                if result["stopped"] is not True:
                    result["stop_confirmation_error"] = "STOP_NOT_CONFIRMED"
                if ack_pending:
                    result.update(stopped=None, stop_confirmation_error="MOVE_ACK_UNCONFIRMED")
            except (Exception, KeyboardInterrupt) as stop_error:
                result["stop_confirmation_error"] = str(stop_error) or "STOP_INTERRUPTED"
        record("NONCONTACT_FAILED", result)
        return result
