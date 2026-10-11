"""Execute C Mock Revised and A Replan with the same fixture Current."""

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("c_root", type=Path)
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).parent / "integration_results" / "c_revised")
    args = parser.parse_args()
    c_root = args.c_root.resolve()
    c_commit = subprocess.check_output(
        ["git", "-C", str(c_root), "rev-parse", "HEAD"], text=True
    ).strip()
    # This check intentionally selects C's existing Mock provider, not a separate A mode.
    os.environ["C_DESIGN_USE_LLM"] = "0"
    sys.path.insert(0, str(c_root))
    from app.c_design import main as c_main

    assert Path(c_main.__file__).resolve().is_relative_to(c_root)
    initial = c_main.create_initial_design(text="의자")
    assert initial["status"] == "OK" and initial["design"] is not None, initial
    design = initial["design"]
    placed = [copy.deepcopy(b) for b in design["blocks"] if b["layer"] == 1]
    expected = copy.deepcopy(placed[0])
    placed[0]["x"] -= 1  # Fixture: one leg placed one stud left of its original target.
    current = {"current_revision": 1, "blocks": placed}
    differences = [{"expected": expected, "actual": copy.deepcopy(placed[0])}]
    inputs = {"initial_design": design, "current": current,
              "differences": differences, "text_answers": ["2번"]}
    original = copy.deepcopy(inputs)
    before = plan_from_current(design, current)
    assert before["status"] == "NEEDS_CORRECTION" and before["plan"] is None, before
    # C consumes a block list; A consumes Backend's full Current with its revision.
    revised = c_main.run_intervention(
        design, current["blocks"], differences, text_answers=inputs["text_answers"]
    )
    assert revised["status"] == "OK" and revised["hri_result"] == "REVISE", revised
    result = plan_from_current(revised["design"], current)
    assert result["status"] == "READY", result
    plan = result["plan"]
    validate_plan(revised["design"], current["blocks"], current["current_revision"], plan)
    targets = Counter(map(block_key, revised["design"]["blocks"]))
    actual = Counter(map(block_key, current["blocks"]))
    placements = [s["after"] for s in plan["steps"]]
    checks = {
        "input_not_mutated": inputs == original,
        "design_version_increased": revised["design"]["design_version"] == design["design_version"] + 1,
        "current_preserved_with_quantities": all(targets[k] >= n for k, n in actual.items()),
        "moved_block_stays_at_actual_position": targets[block_key(placed[0])] == 1,
        "no_current_block_reissued": all(block_key(b) not in actual for b in placements),
        "remaining_count_matches": len(placements) == len(revised["design"]["blocks"]) - len(placed),
        "plan_design_version_matches": plan["design_version"] == revised["design"]["design_version"],
        "base_current_revision_matches": plan["base_current_revision"] == current["current_revision"],
        "final_current_plus_plan_matches_target": actual + Counter(map(block_key, placements)) == targets,
        "plan_validator_support_geometry_prerequisites": True,
    }
    assert all(checks.values()), checks
    report = {
        "scenario": "C Mock Revised -> actual A Replan; fixture Current with one moved leg",
        "c_commit": c_commit, "c_provider": "MOCK", "c_entrypoint": "app.c_design.main.run_intervention",
        "a_entrypoint": "planning_trial.planner.plan_from_current",
        "a_source_sha256": hashlib.sha256(Path(__file__).with_name("planner.py").read_bytes()).hexdigest(),
        "before_revised_result": before,
        "c_status": revised["status"], "hri_result": revised["hri_result"], "a_status": result["status"],
        "initial_design_version": design["design_version"], "revised_design_version": revised["design"]["design_version"],
        "base_current_revision": plan["base_current_revision"], "current_block_count": len(placed),
        "revised_block_count": len(revised["design"]["blocks"]), "remaining_step_count": len(placements),
        "steps_by_layer": dict(sorted(Counter(b["layer"] for b in placements).items())), "checks": checks,
        "not_tested": ["real LLM/voice", "D Backend adoption", "HMI", "camera/robot/physical assembly"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [("inputs.json", inputs), ("c_response.json", revised),
                        ("a_result.json", result), ("verification.json", report)]:
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Saved:", args.output_dir.resolve())


if __name__ == "__main__":
    main()
