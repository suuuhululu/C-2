"""Run C's public Mock Initial entry point through the existing A calculator.

The C checkout is an input to this check; its code is never copied or changed.
"""

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from planner import BLOCK_FIELDS, block_key, plan_from_current, validate_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("c_root", type=Path, help="Checkout containing app/c_design/main.py")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).parent / "integration_results" / "c_initial")
    args = parser.parse_args()
    c_root = args.c_root.resolve()
    c_commit = subprocess.check_output(
        ["git", "-C", str(c_root), "rev-parse", "HEAD"], text=True
    ).strip()
    # Reproduction uses C's existing Mock provider, even if the shell enables LLM.
    os.environ["C_DESIGN_USE_LLM"] = "0"
    sys.path.insert(0, str(c_root))
    from app.c_design import main as c_main

    assert Path(c_main.__file__).resolve().is_relative_to(c_root), "Unexpected C module loaded"
    c_result = c_main.create_initial_design(text="의자")
    assert c_result["status"] == "OK" and c_result["design"] is not None, c_result
    current = {"current_revision": 0, "blocks": []}  # Fixture, not a camera observation.
    original = copy.deepcopy((c_result, current))
    design = c_result["design"]
    result = plan_from_current(design, current)
    assert result["status"] == "READY", result
    plan = result["plan"]
    validate_plan(design, current["blocks"], current["current_revision"], plan)
    placements = [step["after"] for step in plan["steps"]]
    checks = {
        "c_success": c_result["error"] is None,
        "a_ready": result["errors"] == [],
        "common_design_fields": set(design) == {"design_version", "blocks"}
            and all(set(b) == set(BLOCK_FIELDS) for b in design["blocks"]),
        "input_not_mutated": (c_result, current) == original,
        "design_version_matches": plan["design_version"] == design["design_version"],
        "base_current_revision_matches": plan["base_current_revision"] == 0,
        "place_only": all(s["operation"] == "PLACE" and s["before"] is None
            and s["requires_delivery"] is True for s in plan["steps"]),
        "ordered_by_layer_then_y_desc_x_asc": placements == sorted(
            placements, key=lambda b: (b["layer"], -b["y"], b["x"])),
        "final_placements_equal_design_with_quantities": Counter(map(block_key, placements))
            == Counter(map(block_key, design["blocks"])),
        "plan_validator_support_geometry_prerequisites": True,
    }
    assert all(checks.values()), checks
    report = {
        "scenario": "C Mock Initial -> actual A planning function; empty fixture Current",
        "c_commit": c_commit,
        "c_provider": "MOCK",
        "c_entrypoint": "app.c_design.main.create_initial_design",
        "request_text": "의자",
        "a_entrypoint": "planning_trial.planner.plan_from_current",
        "a_source_sha256": hashlib.sha256(Path(__file__).with_name("planner.py").read_bytes()).hexdigest(),
        "c_status": c_result["status"], "a_status": result["status"],
        "design_version": design["design_version"],
        "base_current_revision": plan["base_current_revision"],
        "design_block_count": len(design["blocks"]), "plan_step_count": len(plan["steps"]),
        "steps_by_layer": dict(sorted(Counter(b["layer"] for b in placements).items())),
        "checks": checks,
        "not_tested": ["Revised Design path", "D Backend adoption", "HMI", "actual LLM",
                       "voice/STT/TTS", "camera/robot/physical assembly"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [("c_response.json", c_result), ("current.json", current),
                        ("a_result.json", result), ("verification.json", report)]:
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Saved:", args.output_dir.resolve())


if __name__ == "__main__":
    main()
