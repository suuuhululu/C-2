"""Execute C's shared JSON fixtures through the existing A planning boundary."""

import argparse
import copy
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from planner import block_key, plan_from_current, validate_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("c_root", type=Path, help="C checkout containing tests/unit/c_design/fixtures")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).parent / "integration_results/c_fixtures")
    args = parser.parse_args()
    root = args.c_root.resolve()
    fixture_dir = root / "tests/unit/c_design/fixtures"
    names = ["design_initial_valid.json", "current_cases.json",
             "difference_cases.json", "revised_before_after.json"]
    raw = {name: (fixture_dir / name).read_bytes() for name in names}
    fixtures = {name: json.loads(value) for name, value in raw.items()}
    initial = fixtures["design_initial_valid.json"]
    # _note describes the fixture; only the actual Design is a planner input.
    initial = {key: initial[key] for key in ("design_version", "blocks")}
    current_cases = fixtures["current_cases.json"]
    revised = fixtures["revised_before_after.json"]
    expected = {
        "matches_design": ("READY", 6),
        "position_changed": ("NEEDS_CORRECTION", None),
        "orientation_changed": ("NEEDS_CORRECTION", None),
        "color_changed": ("NEEDS_CORRECTION", None),
        "board_position_moved": ("NEEDS_CORRECTION", None),
        "layer_changed": ("NEEDS_CORRECTION", None),
        "support_violation": ("NEEDS_CORRECTION", None),
        "overlap_violation": ("INVALID", None),
    }
    assert {case["case"] for case in current_cases["cases"]} == set(expected), "Review changed C cases"
    cases = [("initial_empty", initial, [], 0, "READY", 8),
             ("fully_assembled", initial, initial["blocks"], 2, "READY", 0),
             ("before_revised", revised["design"], revised["current"], 1,
              "NEEDS_CORRECTION", None),
             ("after_revised", revised["revised"], revised["current"], 1, "READY", 4)]
    for case in current_cases["cases"]:
        status, count = expected[case["case"]]
        cases.append((case["case"], current_cases["design"], case["current"], 1, status, count))

    records, summary, lines = {}, {}, []
    for name, design, blocks, revision, expected_status, expected_count in cases:
        # These revisions belong to test inputs, not Backend-adopted observations.
        current = {"current_revision": revision, "blocks": copy.deepcopy(blocks)}
        before = copy.deepcopy((design, current))
        result = plan_from_current(design, current)
        checks = {
            "input_not_mutated": (design, current) == before,
            "result_fields": set(result) == {"status", "plan", "errors"},
            "expected_status": result["status"] == expected_status,
        }
        if result["status"] == "READY":
            plan = result["plan"]
            placed = [step["after"] for step in plan["steps"]]
            actual = Counter(map(block_key, current["blocks"]))
            target = Counter(map(block_key, design["blocks"]))
            validate_plan(design, current["blocks"], revision, plan)
            checks.update({
                "empty_errors": result["errors"] == [],
                "expected_step_count": len(placed) == expected_count,
                "revision_matches": plan["base_current_revision"] == revision,
                "design_version_matches": plan["design_version"] == design["design_version"],
                "no_current_reissued": not (actual & Counter(map(block_key, placed))),
                "final_placements_match_target": actual + Counter(map(block_key, placed)) == target,
                "coordinate_order": placed == sorted(placed, key=lambda b: (b["layer"], -b["y"], b["x"])),
                "plan_validation": True,
            })
            lines.append(f"{name}: READY, Current={len(blocks)}, PLACE={len(placed)}, revision={revision}")
            for step in plan["steps"]:
                b = step["after"]
                lines.append(f"  {step['step_id']} {b['color']} {b['brick_type']} "
                             f"({b['x']}, {b['y']}, layer={b['layer']}) "
                             f"orientation_deg={b['orientation_deg']}")
        else:
            checks.update({"no_plan": result["plan"] is None,
                           "error_details": bool(result["errors"]) and all(
                               set(error) == {"reason", "block"} and bool(error["reason"])
                               for error in result["errors"])})
            lines.append(f"{name}: {result['status']}, plan=null")
            for error in result["errors"]:
                lines.append(f"  reason={error['reason']}")
                lines.append(f"  block={json.dumps(error['block'], ensure_ascii=False)}")
        summary[name] = {"status": result["status"], "expected_status": expected_status,
                         "step_count": len(result["plan"]["steps"]) if result["plan"] else None,
                         "checks": checks}
        records[name] = {"design": design, "current": current, "result": result}

    passed = all(all(case["checks"].values()) for case in summary.values())
    report = {
        "c_commit": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
        "fixture_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
        "a_source_sha256": hashlib.sha256(Path(__file__).with_name("planner.py").read_bytes()).hexdigest(),
        "case_count": len(cases), "all_checks_passed": passed, "cases": summary,
        "difference_fixture_usage": "Reference only; A consumes Design and Current, not Difference.",
        "current_revision_source": "Explicit fixture values, not Backend observations.",
        "not_tested": ["C public function execution in this runner", "real LLM/voice",
                       "D Consumer/adoption", "HMI", "camera/robot/physical assembly"],
    }
    lines.append(f"Checks: {'PASS' if passed else 'FAIL'} ({len(cases)} cases)")
    lines.append("Scope: C JSON fixture -> actual A function; D/HMI/devices not connected.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # Compact full inputs/results keep the evidence small; the summary is readable.
    (args.output_dir / "runs.json").write_text(json.dumps(records, ensure_ascii=False) + "\n")
    (args.output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "execution.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("Saved:", args.output_dir.resolve())
    if not passed:
        raise SystemExit("Fixture checks failed; see verification.json")


if __name__ == "__main__":
    main()
