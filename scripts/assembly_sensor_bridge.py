"""기존 현장 조회 도구→7단계→Backend 단일 무이동 진단. 기본은 실행 안내다."""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

from app.assembly_sensor_readings import project_no_motion_readings
from app.backend import Backend
from app.jsonl_log import JsonlLog


def load_reader(path, expected_sha256):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("READER_SOURCE_CHANGED: review source before running")
    spec = importlib.util.spec_from_file_location("reviewed_no_motion_reader", path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader


def _forbid_dispatch(*args):
    raise RuntimeError("MOTION_DISPATCH_FORBIDDEN")


def diagnostic_backend(fixture, max_age, record=None):
    if type(max_age) not in (int, float) or not math.isfinite(max_age) or max_age <= 0:
        raise ValueError("max_age: positive finite query age required")
    collect, trial = fixture["attempt_collection"], fixture["completion_trial"]
    opened, token = time.monotonic(), str(uuid4())
    common = {**collect["common_context"], "job_id":token, "plan_id":"READ_ONLY_DIAGNOSTIC",
        "step_id":"READ_ONLY", "attempt_id":str(uuid4()), "calibration_id":"DIAGNOSTIC_UNCALIBRATED",
        "opened_at":opened}
    active = {name:{**common, **settings, "opened_at":opened, "source_epoch":f"{name}-{token}",
        "request_id":str(uuid4()) if settings["request_id"] is not None else None}
        for name,settings in collect["sources"].items()}
    physical = {**active["execution_result"], **trial["physical_source"], "source_epoch":f"physical-{token}"}
    backend = Backend(_forbid_dispatch, mode="FAKE", record=record)
    backend.begin_assembly_trial(active=active, max_age=dict.fromkeys(active, max_age),
        physical_context=physical, physical_max_age=max_age, world=deepcopy(trial["world"]),
        target=deepcopy(trial["target"]), now=opened)
    return backend, f"HOST_MONOTONIC-{token}"


def collect_once(backend, reader, node, config_path, out, clock_id, force_ref):
    """조회 직전 문맥을 동결하고 원문을 먼저 저장한다. old 파일은 입력받지 않는다."""
    state = backend.assembly_state
    active = deepcopy(state["collection"]["active"]["motion_permitted"])
    previous = state["collection"]["seen_sequence"]["motion_permitted"]
    window = dict(clock_id=clock_id, started_at=time.monotonic(), request_utc=reader.utc_now())
    feedback = reader.probe(node, config_path)
    reader.write_json(out / "feedback.json", feedback)
    camera = None
    try:
        camera = reader.save_rgbd(out, reader.receive_rgbd(node))
    except (OSError, TimeoutError, ValueError) as error:
        reader.write_json(out / "camera_error.json", dict(error=str(error)))
    window.update(finished_at=time.monotonic(), response_utc=reader.utc_now())
    config = json.loads(config_path.read_text())
    projected = project_no_motion_readings(feedback, camera, active=active,
        sequence=0 if previous is None else previous + 1, sample_window=window,
        service_prefix=f"/{config['settings']['robot_id']}/dsr_controller2/", force_ref=force_ref, live=True)
    reader.write_json(out / "projection.json", projected)
    reply = backend.on_assembly_sensor_snapshot(snapshot=projected["snapshot"], now=time.monotonic(), clock_id=clock_id)
    reader.write_json(out / "backend_reply.json", reply)
    reader.write_json(out / "backend_state.json", backend.assembly_state)
    complete = reply["accepted"] and all(projected["snapshot"][key]["success"] for key in ("robot", "wrench", "gripper"))
    complete = complete and reply["diagnostic"] is not None and reply["diagnostic"]["rgbd_metadata_usable"]
    return dict(status="CONNECTED_READ_ONLY" if complete else "PARTIAL_READS_OR_INPUT_REJECTED",
        source_mode="REAL_READ_ONLY", backend_mode="FAKE_DIAGNOSTIC", synthetic_geometry=True,
        decision=backend.assembly_state["decision"], input_accepted=reply["accepted"],
        physical_completion_verified=False, motion_commands_sent=0, gripper_commands_sent=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-read", action="store_true")
    parser.add_argument("--reader", type=Path)
    parser.add_argument("--reader-sha256")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--expected-domain", type=int)
    parser.add_argument("--max-age", type=float)
    parser.add_argument("--force-ref", type=int, choices=(0, 1), default=0)
    args = parser.parse_args(argv)
    if not args.live_read:
        print("읽기 연결 준비. 실제 조회는 --live-read와 검토한 reader/config/domain/max-age가 필요합니다.")
        return 0
    if any(getattr(args, key) is None for key in ("reader", "reader_sha256", "config", "fixture", "out", "expected_domain", "max_age")):
        parser.error("live read requires reader, reader-sha256, config, fixture, out, expected-domain, max-age")
    if args.expected_domain < 0 or os.environ.get("ROS_DOMAIN_ID") != str(args.expected_domain):
        parser.error("ROS_DOMAIN_ID must explicitly match expected-domain; no default domain is selected")
    args.out.mkdir(parents=True, exist_ok=False)
    reader, node, initialized = None, None, False
    try:
        reader = load_reader(args.reader, args.reader_sha256)
        backend, clock_id = diagnostic_backend(json.loads(args.fixture.read_text()), args.max_age,
            record=JsonlLog(args.out / "events"))
        import rclpy
        from rclpy.node import Node
        rclpy.init()
        initialized = True
        node = Node("c2_assembly_readonly_bridge")
        result = collect_once(backend, reader, node, args.config, args.out, clock_id, args.force_ref)
        result["reader_sha256"] = args.reader_sha256
        reader.write_json(args.out / "result.json", result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "CONNECTED_READ_ONLY" else 1
    except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError) as error:
        result = dict(status="FAILED", error=str(error), motion_commands_sent=0, gripper_commands_sent=0)
        (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
        return 1
    finally:
        if node is not None:
            node.destroy_node()
        if initialized:
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
