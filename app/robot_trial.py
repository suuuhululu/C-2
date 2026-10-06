"""검증된 원본 경로를 재사용하는 한 블록 장치 시험. 기본은 계획 출력이다."""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from .contracts import _integer, _object, _text
from .jsonl_log import JsonlLog


def load_trial_config(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    _object(value, ("config_id", "mode", "source_path", "source_sha256", "slot",
                    "settings", "observe_posj", "observe_posx", "confirmations") +
                    (("pick_line",) if "pick_line" in value else ()), "trial")
    for field in ("config_id", "source_path", "source_sha256"):
        _text(value[field], f"trial.{field}")
    if value["mode"] != "REAL":
        raise ValueError("trial.mode: explicit REAL required; default action remains offline")
    _integer(value["slot"], 1, 6, "trial.slot")
    fields = ("robot_id", "tcp", "tool", "gripper_ip", "lift", "joint_speed", "joint_acc",
              "local_speed", "transit_speed", "linear_acc", "transit_z", "bypass_y",
              "supply_staging_x", "open_width", "close_width", "force")
    settings = _object(value["settings"], fields, "trial.settings")
    for field in fields[:4]:
        _text(settings[field], f"trial.settings.{field}")
    for field in fields[4:]:
        number = settings[field]
        if type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError(f"trial.settings.{field}: finite number required")
    if settings["lift"] < 30 or not 0 <= settings["close_width"] < settings["open_width"] <= 110:
        raise ValueError("trial.settings: unsupported lift or RG2 width")
    if not 0 < settings["force"] <= 40 or min(settings[f] for f in fields[5:10]) <= 0:
        raise ValueError("trial.settings: positive speeds/acceleration and RG2 force required")
    for field in ("observe_posj", "observe_posx"):
        pose = value[field]
        if not isinstance(pose, list) or len(pose) != 6 or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in pose):
            raise ValueError(f"trial.{field}: six finite values required")
    confirmations = _object(value["confirmations"],
                            ("onsite_operator", "unchanged_setup", "empty_place_and_slot",
                             "return_route_verified"), "trial.confirmations")
    if any(type(flag) is not bool for flag in confirmations.values()):
        raise ValueError("trial.confirmations: booleans required")
    config = deepcopy(value)
    # JSON의 20도 수치상 유효하지만 ROS C 변환기는 float64에 Python float를 요구한다.
    for field in fields[4:]:
        config["settings"][field] = float(config["settings"][field])
    for field in ("observe_posj", "observe_posx"):
        config[field] = [float(v) for v in config[field]]
    if "pick_line" in config:
        line = _object(config["pick_line"], ("brick_type", "color", "start", "end",
                       "measurements_path", "measurements_sha256"), "trial.pick_line")
        if line["brick_type"] != "2x2x1" or line["color"] not in ("yellow", "blue"):
            raise ValueError("trial.pick_line: only 4-stud measured supply rows supported")
        for field in ("start", "end"):
            pose = line[field]
            if not isinstance(pose, list) or len(pose) != 6 or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in pose):
                raise ValueError(f"trial.pick_line.{field}: six finite values required")
            line[field] = [float(v) for v in pose]
        for field in ("measurements_path", "measurements_sha256"):
            _text(line[field], f"trial.pick_line.{field}")
    return config


def prepare_plan(config):
    path = Path(config["source_path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != config["source_sha256"]:
        raise ValueError("trial.source: changed source; review required")
    spec = importlib.util.spec_from_file_location("taught_yellow4_row", path)
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)  # 원본 main을 호출하지 않으며 장치 import는 생성자 안에 있다.
    if "pick_line" in config:
        line = config["pick_line"]
        measurements = Path(line["measurements_path"])
        if hashlib.sha256(measurements.read_bytes()).hexdigest() != line["measurements_sha256"]:
            raise ValueError("trial.measurements: changed source; review required")
        measured = json.loads(measurements.read_text(encoding="utf-8"))["lines"][f"{line['color']}_4"]
        if line["start"] != measured["start"] or line["end"] != measured["end"]:
            raise ValueError("trial.pick_line: endpoints differ from recorded measurements")
        # 동일한 보간/경유 알고리즘에 기록된 공급열 끝점만 주입한다. 원본 파일은 보존한다.
        # 잘못 복사된 blue posj를 쓰지 않고 기존 해 분기로 IK/FK를 검사한다.
        source.START, source.END = line["start"].copy(), line["end"].copy()
    args = SimpleNamespace(**config["settings"], start_block=config["slot"])
    original = source.plan(args)
    # start_block만 지정하면 원본은 6번까지 실행한다. 선택 슬롯만 남긴다.
    selected = [step for step in original if step[3] == config["slot"] and step[0] != "clear_place"]
    commands = [original[0], *selected, original[-1],
                ("joint", "검증된 observe point 복귀", config["observe_posj"], None)]
    if sum(step[0] == "grip_close" for step in commands) != 1:
        raise ValueError("trial.plan: exactly one pick required")
    if args.transit_z <= max(p[2] + args.lift for p in source.picks() + [source.PLACE]):
        raise ValueError("trial.settings: transit Z must exceed approach points")
    return source, args, commands


def verify_observe_pose(robot, config, joints):
    from scipy.spatial.transform import Rotation
    actual = list(robot.call("motion/fkin", "Fkin", pos=list(joints), ref=0).conv_posx)
    expected = config["observe_posx"]
    if len(actual) != 6 or not all(math.isfinite(v) for v in actual):
        raise RuntimeError("OBSERVE_POSE_INVALID")
    error = (Rotation.from_euler("ZYZ", actual[3:], degrees=True).inv() *
             Rotation.from_euler("ZYZ", expected[3:], degrees=True)).magnitude()
    # 원본 RowRobot.ik와 같은 FK 일치 기준. 충돌/시야 검증을 대신하지 않는다.
    if math.dist(actual[:3], expected[:3]) > 2 or math.degrees(error) > 1:
        raise RuntimeError("OBSERVE_POSE_MISMATCH")
    return actual


def read_status(robot, gripper, config):
    state = robot.call("system/get_robot_state", "GetRobotState").robot_state
    motion = robot.call("motion/check_motion", "CheckMotion").status
    mode = robot.call("system/get_robot_mode", "GetRobotMode").robot_mode
    tcp = robot.call("tcp/get_current_tcp", "GetCurrentTcp").info
    tool = robot.call("tool/get_current_tool", "GetCurrentTool").info
    status, width = gripper.read(268), gripper.read(267) / 10
    facts = dict(robot_state=state, motion_status=motion, robot_mode=mode,
                 tcp=tcp, tool=tool, gripper_status=status, gripper_width_mm=width)
    if state != 1 or motion != 0 or mode != 1:
        raise RuntimeError(f"ROBOT_NOT_IDLE_AUTONOMOUS: {facts}")
    if tcp != config["settings"]["tcp"] or tool != config["settings"]["tool"]:
        raise RuntimeError(f"TCP_TOOL_MISMATCH: {facts}")
    if status != 0:
        raise RuntimeError(f"GRIPPER_NOT_EMPTY_IDLE: {facts}")
    return facts


def check_motion_messages(source, settings, commands, initial):
    """원본 이동 호출의 ROS 직렬화만 검사한다. 노드/클라이언트/송신은 없다."""
    from dsr_msgs2 import srv
    from rclpy.serialization import serialize_message
    count = 0

    def serialize(path, typename, timeout, **fields):
        nonlocal count
        request = getattr(srv, typename).Request()
        for key, value in fields.items():
            setattr(request, key, value)
        serialize_message(request)
        count += 1

    robot = SimpleNamespace(args=settings, call=serialize)
    for kind, label, target, block in commands:
        if kind in ("joint", "initial_approach"):
            source.RowRobot.movej(robot, initial if kind == "initial_approach" else target)
        elif kind in ("line_local", "line_transit"):
            source.RowRobot.line(robot, target, settings.local_speed if kind == "line_local" else settings.transit_speed)
    return count


def run_commands(commands, robot, gripper, initial, config, record):
    consumed = False
    lifted = False
    for kind, label, target, block in commands:
        record("ROBOT_TRIAL_COMMAND", dict(operation=kind, label=label, slot=block, target=target))
        print(label, flush=True)
        if kind == "joint":
            robot.movej(target)
        elif kind == "initial_approach":
            robot.movej(initial)
        elif kind in ("line_local", "line_transit"):
            robot.line(target, getattr(robot.args, "local_speed" if kind == "line_local" else "transit_speed"))
            if lifted:
                status = gripper.read(268)
                if status != 2:
                    raise RuntimeError(f"PICK_HOLD_UNCONFIRMED: status={status}")
                consumed = True
                lifted = False
                record("ROBOT_PICK_CONFIRMED", dict(slot=config["slot"], next_slot=config["slot"] + 1
                                                    if config["slot"] < 6 else None))
        elif kind == "grip_close":
            gripper.move(robot.args.close_width, require_grip=True)
            lifted = True
        elif kind == "grip_open":
            gripper.move(robot.args.open_width)
            if consumed:
                if gripper.read(268) != 0:
                    raise RuntimeError("RELEASE_UNCONFIRMED")
                record("ROBOT_RELEASE_CONFIRMED", dict(slot=config["slot"]))
        else:
            raise ValueError(f"trial.operation: unsupported {kind}")
    facts = read_status(robot, gripper, config)
    joints = list(robot.call("aux_control/get_current_posj", "GetCurrentPosj").pos)
    facts["observe_posx_actual"] = verify_observe_pose(robot, config, joints)
    if not consumed:
        raise RuntimeError("PICK_UNCONFIRMED")
    record("ROBOT_RETURN_CONFIRMED", facts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--execution-id", type=UUID, help="HMI가 발행한 시험 실행 UUID")
    parser.add_argument("--require-observe-start", action="store_true", help="현재 실제 관절 FK가 observe point와 일치해야 시작")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="실제 통신·IK/FK 조회만, 이동 없음")
    action.add_argument("--execute", action="store_true", help="실제 선택 슬롯 한 블록 전달")
    parser.add_argument("--log-dir", default="logs/robot_trials")
    args = parser.parse_args(argv)
    robot = gripper = None
    started = False
    identity = str(args.execution_id or uuid4())
    logger = JsonlLog(args.log_dir)

    def record(event, payload):
        logger(dict(event=event, job_id=identity, execution_id=identity, payload=payload))

    try:
        config = load_trial_config(args.config)
        source, settings, commands = prepare_plan(config)
        for kind, label, target, slot in commands:
            print(json.dumps(dict(operation=kind, label=label, target=target, slot=slot), ensure_ascii=False))
        if not (args.check or args.execute):
            print("계획만 출력했습니다. 장치 연결/명령 없음.")
            return 0
        if args.execute and not all(config["confirmations"].values()):
            raise ValueError("ONSITE_CONFIRMATION_REQUIRED")
        record("ROBOT_TRIAL_CONFIG", config)
        robot = source.RowRobot(settings)
        gripper = source.Gripper(settings)
        record("ROBOT_PREFLIGHT", read_status(robot, gripper, config))
        if args.require_observe_start:
            joints = list(robot.call("aux_control/get_current_posj", "GetCurrentPosj").pos)
            verify_observe_pose(robot, config, joints)
        sol = robot.verify_setup()
        initial = robot.check_plan(commands, sol)
        verify_observe_pose(robot, config, config["observe_posj"])
        count = check_motion_messages(source, settings, commands, initial)
        record("ROBOT_REQUEST_CHECK", dict(motion_requests=count, motion_commands_sent=False))
        print(f"이동 요청 {count}개 ROS 메시지 변환 검사 완료. 송신 없음.", flush=True)
        if args.check:
            record("ROBOT_CHECK_COMPLETE", dict(motion_commands_sent=False))
            print(f"조회 완료, 이동/그리퍼 개폐 명령 없음. 로그: {identity}.jsonl")
            return 0
        record("ROBOT_TRIAL_STARTED", dict(slot=config["slot"], preflight=read_status(robot, gripper, config)))
        started = True
        run_commands(commands, robot, gripper, initial, config, record)
        record("ROBOT_TRIAL_RESULT", dict(execution_id=identity, success=True, reason=None))
        print(f"한 블록 전달/복귀 명령 완료. 현장 전달 결과 확인 필요. 로그: {identity}.jsonl")
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # STOP ACK를 정지 완료로 반환하지 않는다. 재집기/복구 명령은 없다.
        if started and robot is not None:
            robot.stop()
        reason = str(exc) or "INTERRUPTED"
        print(f"보류: {reason}. 자동 재시도 없음.", flush=True)
        try:
            record("ROBOT_TRIAL_RESULT", dict(execution_id=identity, success=False, reason=reason))
        except Exception as log_error:
            print(f"실패 기록도 저장하지 못했습니다: {log_error}", flush=True)
        return 1
    finally:
        if gripper is not None:
            gripper.close()
        if robot is not None:
            robot.close()


if __name__ == "__main__":
    raise SystemExit(main())
