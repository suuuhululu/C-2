"""Execute four fake Design/Current cases and print the actual A results.

Use the C response saved by check_c_initial.py; keep the existing calculator.
"""

import argparse
import copy
import json
from pathlib import Path

from planner import plan_from_current, validate_plan


def main():
    root = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-response", type=Path,
                        default=root / "integration_results/c_initial/c_response.json")
    parser.add_argument("--output-dir", type=Path,
                        default=root / "integration_results/fake_cases")
    args = parser.parse_args()
    response = json.loads(args.initial_response.read_text())
    assert response["status"] == "OK" and response["design"] is not None, response
    design = response["design"]
    empty = {"current_revision": 0, "blocks": []}
    assembled = [copy.deepcopy(b) for b in design["blocks"] if b["layer"] == 1]
    partial = {"current_revision": 1, "blocks": assembled}
    misplaced = copy.deepcopy(assembled[0])
    misplaced["color"] = "yellow" if misplaced["color"] == "blue" else "blue"
    conflicting = {"current_revision": 1, "blocks": [misplaced]}
    invalid = copy.deepcopy(design)
    invalid["blocks"][0]["layer"] = 6
    cases = [
        ("empty", design, empty, "READY", len(design["blocks"])),
        ("partial", design, partial, "READY", len(design["blocks"]) - len(assembled)),
        ("needs_correction", design, conflicting, "NEEDS_CORRECTION", None),
        ("invalid", invalid, empty, "INVALID", None),
    ]
    records, lines = {}, []
    for name, target, current, expected_status, expected_count in cases:
        original = copy.deepcopy((target, current))
        result = plan_from_current(target, current)
        assert (target, current) == original, name
        assert result["status"] == expected_status, result
        assert set(result) == {"status", "plan", "errors"}
        if expected_status == "READY":
            plan = result["plan"]
            assert result["errors"] == []
            assert len(plan["steps"]) == expected_count
            assert plan["base_current_revision"] == current["current_revision"]
            assert all(s["after"] not in current["blocks"] for s in plan["steps"])
            validate_plan(target, current["blocks"], current["current_revision"], plan)
            lines.append(f"{name}: READY, Current={len(current['blocks'])}, "
                         f"PLACE={len(plan['steps'])}, revision={plan['base_current_revision']}")
            for step in plan["steps"]:
                b = step["after"]
                lines.append(f"  {step['step_id']} {b['color']} {b['brick_type']} "
                             f"({b['x']}, {b['y']}, layer={b['layer']}) "
                             f"orientation_deg={b['orientation_deg']}")
        else:
            assert result["plan"] is None and result["errors"]
            expected_block = misplaced if name == "needs_correction" else invalid["blocks"][0]
            assert result["errors"][0]["block"] == expected_block
            lines.append(f"{name}: {result['status']}, plan=null")
            for error in result["errors"]:
                lines.append(f"  reason={error['reason']}")
                lines.append(f"  block={json.dumps(error['block'], ensure_ascii=False)}")
        records[name] = {"design": target, "current": current, "result": result}
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "runs.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    lines.append("Scope: direct A execution with fake inputs; D/HMI/physical devices not connected.")
    (out / "execution.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("Saved:", out.resolve())


if __name__ == "__main__":
    main()
