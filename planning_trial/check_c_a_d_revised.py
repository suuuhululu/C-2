"""Run public C Mock functions -> existing A -> D using D-adopted fixture Current."""

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from planner import block_key, plan_from_current, validate_plan


def observation(check_id, blocks):
    # Full-board evidence is a controlled fixture, not camera measurement.
    return {"check_id": check_id, "observation_seq": 0, "status": "OK",
            "visible_blocks": copy.deepcopy(blocks), "reason": None,
            "verified_regions": [{"x": 0, "y": 0, "width": 24, "height": 24,
                                  "layer": layer} for layer in range(1, 5)]}


def assemble_next(backend, driver):
    if backend.state["execution_id"] is None:
        check = backend.state["place_check"]["check_id"]
        assert backend.on_place(check, 0, "EMPTY")
    target = copy.deepcopy(backend._next_step()["after"])
    before = backend.state["current"]
    execution_id = backend.state["execution_id"]
    for operation in ("pick", "place", "observe"):
        assert driver.confirm(execution_id, operation)
    assert backend.state["current"] == before, "Delivery cannot count as assembly"
    check = backend.state["active_check"]["check_id"]
    assert backend.on_observation(observation(check, before["blocks"] + [target]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("team_root", type=Path, help="Team checkout with C and D (tested: main 101d9d8)")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).parent / "integration_results/c_a_d_revised")
    args = parser.parse_args()
    root = args.team_root.resolve()
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    os.environ["C_DESIGN_USE_LLM"] = "0"
    sys.path.insert(0, str(root))
    from app.backend import Backend
    from app.c_design import main as c_main
    from app.fake_robot_driver import FakeRobotDriver
    from app.jsonl_log import JsonlLog
    from app.planning_connection import current_blocks_for_c, on_c_intervention, run_planning_request
    from app.replan import open_current_check
    from app.robot_controller import RobotController
    from app.snapshot import make_snapshot

    assert Path(c_main.__file__).resolve().is_relative_to(root)
    calls, a_runs = [], []

    def calculate(design, current):
        # Record calls to the workspace's existing A calculator, not a replacement.
        result = plan_from_current(design, current)
        a_runs.append(copy.deepcopy({"design": design, "current": current, "result": result}))
        return result

    def emit(port, payload):
        calls.append((port, copy.deepcopy(payload)))
        if port == "planner" and "design" in payload:
            run_planning_request(backend, payload, planner=calculate)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    backend = Backend(emit, mode="FAKE", record=JsonlLog(args.output_dir / "jobs"))
    driver = FakeRobotDriver(ready_at_observe=True)
    config = json.loads((root / "interfaces/fixtures/robot.json").read_text())
    controller = RobotController(config, driver, backend.on_robot_result,
                                 on_stopped=backend.on_stopped, on_event=backend.on_robot_event)
    backend.connect_robot(controller)
    assert backend.command({"command": "START"})["accepted"]
    initial_request = backend.state["planning_request"]["request_id"]
    initial_response = c_main.create_initial_design(text="의자")
    assert initial_response["status"] == "OK", initial_response
    assert backend.on_initial_design(initial_request, initial_response)
    initial_context = backend.state["context"]
    assert len(initial_context["plan"]["steps"]) == 15
    for _ in range(4):
        assemble_next(backend, driver)
    assembled = backend.state["current"]
    assert assembled["current_revision"] == 4 and len(assembled["blocks"]) == 4
    pending = copy.deepcopy(backend._next_step()["after"])

    # One known moved block defines this fixture; this is NOT a generic association rule.
    expected = next(copy.deepcopy(b) for b in assembled["blocks"] if (b["x"], b["y"]) == (9, 9))
    actual = dict(expected, x=8)
    moved = [actual if block_key(b) == block_key(expected) else b for b in assembled["blocks"]]
    open_current_check(backend, "INTENT")
    check = backend.state["current_check"]["check_id"]
    assert backend.on_observation(observation(check, moved))
    assert backend.state["workflow_status"] == "WAIT_INTENT"
    hri = next(payload for port, payload in reversed(calls) if port == "hri")
    current = copy.deepcopy(hri["current"])
    assert current == backend.state["current"] and current["current_revision"] == 5
    diff = hri["difference"]
    assert not diff["unobservable"]
    # D Expected also includes the next unassembled Step. Its area is verified empty.
    assert Counter(map(block_key, diff["missing"])) == Counter([block_key(expected), block_key(pending)])
    assert Counter(map(block_key, diff["unexpected"])) == Counter([block_key(actual)])
    c_differences = [{"expected": expected, "actual": actual},
                     {"expected": pending, "actual": None}]
    question_id = hri["request_id"]
    c_inputs = {"design": hri["design"], "current": current,
                "d_difference": diff, "c_differences": c_differences, "text_answers": ["2번"]}
    original = copy.deepcopy(c_inputs)
    revised_response = c_main.run_intervention(
        hri["design"], current_blocks_for_c(hri), c_differences, text_answers=["2번"],
        on_question=lambda text: backend.on_question(question_id, text),
    )
    assert revised_response["status"] == "OK" and revised_response["hri_result"] == "REVISE", revised_response
    assert on_c_intervention(backend, question_id, revised_response)
    state = backend.state
    context = state["context"]
    design, plan = context["design"], context["plan"]
    assert len(a_runs) == 2, "Expect one Initial call and one Revised call"
    validate_plan(design, current["blocks"], current["current_revision"], plan)
    placed = [step["after"] for step in plan["steps"]]
    current_keys = Counter(map(block_key, current["blocks"]))
    lines = ["Initial: C OK -> A READY -> D adopted 15 PLACE",
             "Observed fixture: D Current 4 blocks, revision 4",
             "Moved fixture: (9,9,1) -> (8,9,1), D Current revision 5",
             "Revised: C OK/REVISE v2 -> A READY -> D adopted 11 PLACE"]
    for step in plan["steps"]:
        b = step["after"]
        lines.append(f"  {step['step_id']} {b['color']} {b['brick_type']} "
                     f"({b['x']}, {b['y']}, layer={b['layer']}) orientation_deg={b['orientation_deg']}")
    records = [json.loads(line) for line in (args.output_dir / "jobs" / f"{state['job_id']}.jsonl").read_text().splitlines()]
    checks = {
        "c_inputs_not_mutated": c_inputs == original,
        "d_current_not_changed_by_planning": state["current"] == current,
        "a_used_same_current": a_runs[-1]["current"] == current,
        "a_ready": a_runs[-1]["result"]["status"] == "READY" and a_runs[-1]["result"]["errors"] == [],
        "d_adopted_a_plan": plan == a_runs[-1]["result"]["plan"],
        "d_adopted_c_design": design == revised_response["design"],
        "version_two": design["design_version"] == plan["design_version"] == 2,
        "revision_matches": plan["base_current_revision"] == 5,
        "new_plan_identity": plan["plan_id"] != initial_context["plan"]["plan_id"],
        "remaining_eleven": len(placed) == 11,
        "current_preserved": context["base_current"] == current,
        "moved_block_preserved": actual in design["blocks"],
        "no_current_reissued": not (current_keys & Counter(map(block_key, placed))),
        "current_plus_plan_equals_design": current_keys + Counter(map(block_key, placed)) == Counter(map(block_key, design["blocks"])),
        "c_result_logged": any(r["event"] == "C_INTERVENTION_RESULT" and r["request_id"] == question_id for r in records),
        "plan_result_logged": sum(r["event"] == "PLAN_RESULT" for r in records) == 2,
        "plan_validator": True,
    }
    snapshot = make_snapshot(state)
    report = {"team_commit": commit, "job_id": state["job_id"],
              "c_provider": "MOCK", "observation": "FIXTURE", "robot": "FAKE",
              "a_source_sha256": hashlib.sha256(Path(__file__).with_name("planner.py").read_bytes()).hexdigest(),
              "initial_steps": 15, "current_blocks": 4, "base_current_revision": 5,
              "revised_design_version": 2, "remaining_steps": 11,
              "checks": checks, "all_checks_passed": all(checks.values()),
              "difference_mapping": "One explicit moved pair plus the verified-empty next Step; no generic D-to-C conversion implemented.",
              "not_tested": ["real LLM/voice", "real B callback/camera", "physical Robot/assembly",
                             "multiple-difference association", "Qt window display", "remaining robot cycle"]}
    evidence = {"initial_response": initial_response, "c_inputs": c_inputs,
                "revised_response": revised_response, "a_calls": a_runs,
                "d_adopted_design": design, "d_adopted_plan": plan, "hmi_snapshot": snapshot}
    (args.output_dir / "runs.json").write_text(json.dumps(evidence, ensure_ascii=False) + "\n")
    (args.output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines.append(f"Checks: {'PASS' if report['all_checks_passed'] else 'FAIL'} ({len(checks)} checks)")
    lines.append("Scope: public C Mock functions + actual A + D; observation fixture and Fake Robot.")
    (args.output_dir / "execution.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("Saved:", args.output_dir.resolve())
    assert report["all_checks_passed"], report


if __name__ == "__main__":
    main()
