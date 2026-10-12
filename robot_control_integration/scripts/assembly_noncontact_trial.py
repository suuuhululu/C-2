"""기본은 오프라인 검사; --probe는 상태 조회, --check는 경로 사전 검사, --execute는 이동."""

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

from app.assembly_motion import prepare_motion, preflight, run_noncontact
from app.jsonl_log import JsonlLog


def real_driver(config):
    from app.assembly_motion_ros import AssemblyMotionRos
    return AssemblyMotionRos(config)


def main(argv=None, *, driver_factory=real_driver):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="interfaces/assembly_noncontact_trial.json")
    parser.add_argument("--log-dir", default="logs/assembly_noncontact_trials")
    parser.add_argument("--stop-file", help="파일이 있으면 진행 중 중단; 자동 복귀/재시도 없음")
    parser.add_argument("--read-timeout", type=float, default=3., help="--probe 조회 timeout(초), motion 설정에 저장하지 않음")
    parser.add_argument("--probe-seconds", type=float, help="수동 모드의 --probe 연속 기록 시간(초); 이동/정지 명령 없음")
    parser.add_argument("--probe-interval", type=float, default=.1, help="연속 조회 사이 대기(초); 실제 주기는 조회 시간이 추가됨")
    parser.add_argument("--gripper-force-setting-n", type=float,
                        help="작업자가 알고 있는 파지 힘 설정값(N), 기록만 하며 장치에 쓰지 않음")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--probe", action="store_true", help="미완성 설정으로 상태만 조회; 시작점/확인 조건 자동 채택 없음")
    action.add_argument("--check", action="store_true")
    action.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    driver = None
    previous_sigterm = None
    identity = str(uuid4())
    logger = JsonlLog(args.log_dir)
    started = time.monotonic()
    session_started = False
    log_file = str(logger.directory.resolve()/f"{identity}.jsonl")
    def record(event, payload):
        logger(dict(job_id=identity, execution_id=identity, event=event, payload=payload,
                    elapsed_s=time.monotonic()-started, schema_version=1))
    try:
        if args.probe_seconds is not None and (not args.probe or not math.isfinite(args.probe_seconds) or args.probe_seconds <= 0):
            raise ValueError("--probe-seconds requires --probe and a positive finite duration")
        if not math.isfinite(args.probe_interval) or args.probe_interval <= 0:
            raise ValueError("--probe-interval must be positive and finite")
        if args.gripper_force_setting_n is not None and (
                not math.isfinite(args.gripper_force_setting_n) or args.gripper_force_setting_n <= 0):
            raise ValueError("--gripper-force-setting-n must be positive and finite")
        plan = prepare_motion(json.loads(Path(args.config).read_text()))
        preview = {k: v for k, v in plan.items() if k != "config"}
        if not (args.probe or args.check or args.execute):
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return 0
        if not args.probe and plan["status"] != "PLAN_READY":
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return 2
        config = plan["config"]
        if config["mode"] != "REAL":
            raise ValueError("explicit REAL configuration required for live flags")
        if os.environ.get("ROS_DOMAIN_ID") != str(config["connection"]["ros_domain_id"]):
            raise ValueError("ROS_DOMAIN_ID must explicitly match configuration")
        if args.probe:
            if not math.isfinite(args.read_timeout) or args.read_timeout <= 0:
                raise ValueError("--read-timeout must be positive and finite")
            config["timing"]["service_timeout_s"] = args.read_timeout
        if args.execute and not args.stop_file:
            raise ValueError("--execute requires --stop-file")
        if args.stop_file and Path(args.stop_file).exists():
            raise ValueError("STOP_FILE_PRESENT: clear only after onsite checks")
        lock = Path("/tmp")/f"c2-assembly-{config['connection']['robot_id']}.lock"
        with lock.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record("NONCONTACT_SESSION", dict(action="READ_ONLY_PROBE" if args.probe else "EXECUTE" if args.execute else "READ_ONLY_CHECK",
                    config=config, route=plan["route"], assembled=False, gripper_commands=0,
                    probe_duration_s=args.probe_seconds, probe_interval_s=args.probe_interval,
                    gripper_force_setting_n=args.gripper_force_setting_n,
                    gripper_force_setting_source="OPERATOR_REPORTED" if args.gripper_force_setting_n is not None else "UNKNOWN",
                    gripper_force_measured_n=None, gripper_force_measurement_status="NOT_EXPOSED_BY_CURRENT_READER",
                    wrench_source="DOOSAN_GET_TOOL_FORCE_REF_0", contact_force_verified=False,
                    units=dict(position="mm", orientation="ZYZ degree", force="N", moment="N m", time="s"),
                    timestamps="PC UTC and monotonic query window; not synchronized sensor timestamps"))
            session_started = True
            if args.execute:
                def interrupt(signum, frame):
                    raise KeyboardInterrupt(f"SIGNAL_{signum}")
                previous_sigterm = signal.signal(signal.SIGTERM, interrupt)
            driver = driver_factory(config)
            if args.probe:
                deadline = None if args.probe_seconds is None else time.monotonic()+args.probe_seconds
                count, baseline = 0, None
                while True:
                    sample = driver.sample()
                    if baseline is None:
                        baseline = sample["wrench"].copy()
                    delta = [v-b for v, b in zip(sample["wrench"], baseline)]
                    record("NONCONTACT_READ_ONLY_PROBE_SAMPLE", dict(sample, sample_index=count,
                        phase="READ_ONLY_RECORDING", baseline_wrench=baseline, wrench_delta=delta,
                        force_delta_norm_n=math.hypot(*delta[:3]), moment_delta_norm_nm=math.hypot(*delta[3:]),
                        contact_force_verified=False))
                    if deadline is not None and sample["robot_mode"] != 0:
                        raise RuntimeError("MANUAL_RECORDING_REQUIRES_ROBOT_MODE_0: recorder does not change robot mode")
                    count += 1
                    if count == 1 and deadline is not None:
                        print(f"수동 모드 확인, 연속 기록 중 (이동 명령 없음): {log_file}", flush=True)
                    if deadline is None or time.monotonic() >= deadline:
                        break
                    time.sleep(min(args.probe_interval, max(0., deadline-time.monotonic())))
                    if time.monotonic() >= deadline:
                        break
                result = dict(status="READ_ONLY_PROBE_COMPLETE", sample=sample,
                    sample_count=count,
                    grip_detected=bool(sample["gripper_status"] & 2),
                    execution_gripper_condition_met=sample["gripper_status"] == 2,
                    missing_execution_inputs=preview["missing"], start_pose_adopted=False,
                    execution_preflight_passed=False, motion_commands=0, gripper_commands=0)
                record("NONCONTACT_READ_ONLY_PROBE", result)
            elif args.check:
                preflight(driver, plan, record)
                result = dict(status="READ_ONLY_CHECK_COMPLETE", motion_commands=0, gripper_commands=0)
                record("NONCONTACT_READ_ONLY_COMPLETE", result)
            else:
                result = run_noncontact(driver, plan, record,
                    cancelled=lambda: Path(args.stop_file).exists())
            result["log_file"] = log_file
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] in ("READ_ONLY_PROBE_COMPLETE", "READ_ONLY_CHECK_COMPLETE", "NONCONTACT_TRIAL_COMPLETE") else 1
    except (Exception, KeyboardInterrupt) as error:
        if session_started:
            try:
                record("NONCONTACT_SESSION_ERROR", dict(reason=str(error) or "KEYBOARD_INTERRUPT"))
            except Exception as log_error:
                print(f"로그 기록 실패: {log_error}", flush=True)
            print(f"로그 파일: {log_file}", flush=True)
        print(f"비접촉 시험 실패/보류: {str(error) or 'KEYBOARD_INTERRUPT'}", flush=True)
        return 1
    finally:
        try:
            if driver is not None:
                driver.close()
        finally:
            if previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    raise SystemExit(main())
