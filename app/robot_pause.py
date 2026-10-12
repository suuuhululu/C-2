"""REAL 정지 요청/무이동 확인. 별도 프로세스로 실행 중 이동 서비스와 분리한다."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from app.jsonl_log import JsonlLog
from app.robot_trial import load_trial_config, prepare_plan, read_status, verify_observe_pose


def resume_checkpoint(commands, events, gripper_status):
    """확인된 실행 기록과 현재 그리퍼로 기존 경로의 재개 위치만 고른다."""
    starts = [e["payload"]["command_index"] for e in events if e["event"] == "ROBOT_TRIAL_COMMAND"]
    done = [e["payload"]["command_index"] for e in events if e["event"] == "ROBOT_TRIAL_COMMAND_DONE"]
    basis = [e["payload"] for e in events if e["event"] == "ROBOT_RESUME_CHECKPOINT"]
    index = starts[-1] if starts else basis[-1]["command_index"] if basis else 0
    if done and done[-1] == index:
        index += 1
    picked = any(e["event"] == "ROBOT_PICK_CONFIRMED" for e in events)
    released = any(e["event"] == "ROBOT_RELEASE_CONFIRMED" for e in events)
    close = next(i for i, c in enumerate(commands) if c[0] == "grip_close")
    release = next(i for i, c in enumerate(commands) if i > close and c[0] == "grip_open")
    if gripper_status == 2 and index >= close and not released:
        block_state = "HOLDING"
        index = max(index, close + 1)
    elif gripper_status == 0 and released and picked:
        block_state = "RELEASED"
        # 놓기 확인 직후 DONE 기록 전 정지해도 같은 개폐를 다시 하지 않는다.
        index = max(index, release + 1)
    elif gripper_status == 0 and index <= close and not picked and not released:
        block_state, index = "UNPICKED", 0
    else:
        raise RuntimeError("STOP_BLOCK_STATE_UNKNOWN")
    if not 0 <= index <= len(commands):
        raise ValueError("STOP_COMMAND_INDEX_INVALID")
    return dict(block_state=block_state, command_index=index, consumed=picked or block_state != "UNPICKED",
                released=released)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--request-id", required=True, type=UUID)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--previous-log")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--stop", action="store_true")
    action.add_argument("--probe", action="store_true")
    args = parser.parse_args(argv)
    identity = str(args.request_id)
    logger = JsonlLog(args.log_dir)
    robot = gripper = None

    def record(name, payload):
        logger(dict(event=name, execution_id=identity, job_id=identity, payload=payload))

    try:
        config = load_trial_config(args.config)
        source, settings, commands = prepare_plan(config)
        robot = source.RowRobot(settings)
        if args.stop:
            # 원본 stop과 같은 모드. ACK는 도착/정지 완료로 해석하지 않는다.
            robot.call("motion/move_stop", "MoveStop", timeout=5., stop_mode=1)
            record("ROBOT_STOP_ACK", dict(request_id=identity))
        else:
            gripper = source.Gripper(settings)
            facts = read_status(robot, gripper, config, allow_holding=True)
            events = ([json.loads(line) for line in Path(args.previous_log).read_text().splitlines()]
                      if args.previous_log else [])
            checkpoint = (resume_checkpoint(commands, events, facts["gripper_status"]) if args.previous_log
                          else dict(block_state="UNPICKED", command_index=0, consumed=False, released=False))
            if not args.previous_log and facts["gripper_status"] != 0:
                raise RuntimeError("STOP_BLOCK_STATE_UNKNOWN")
            joints = list(robot.call("aux_control/get_current_posj", "GetCurrentPosj").pos)
            at_observe = True
            try:
                verify_observe_pose(robot, config, joints)
            except RuntimeError as error:
                if str(error) != "OBSERVE_POSE_MISMATCH":
                    raise
                at_observe = False
            record("ROBOT_STOP_PROBE", dict(request_id=identity, stopped=True,
                at_observe=at_observe, checkpoint=checkpoint, facts=facts))
        return 0
    except Exception as error:
        record("ROBOT_STOP_FAILED", dict(reason=str(error)))
        print(f"정지 확인 보류: {error}", flush=True)
        return 1
    finally:
        if gripper is not None:
            gripper.close()
        if robot is not None:
            robot.close()


if __name__ == "__main__":
    raise SystemExit(main())
