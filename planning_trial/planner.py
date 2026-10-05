"""Build initial and remaining PLACE Plans using the team's Day4 contract.

The caller provides Backend's adopted actual blocks and their revision.
Samples and live integration use the same calculation and validation.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from uuid import uuid4


BOARD_SIZE = 24
MAX_LAYER = 4
MIN_SUPPORT_STUDS = 2  # A's selected rule; shared A/C confirmation is pending.
BRICK_SIZES = {"2x2x1": (2, 2), "2x3x1": (2, 3)}
BLOCK_FIELDS = ("brick_type", "color", "x", "y", "layer", "orientation_deg")


def occupied_cells(brick):
    """Return stud cells, anchored at the rotated footprint's minimum x/y."""
    width, depth = BRICK_SIZES[brick["brick_type"]]
    if brick["orientation_deg"] == 90:
        width, depth = depth, width
    return {
        (brick["x"] + dx, brick["y"] + dy, brick["layer"])
        for dx in range(width)
        for dy in range(depth)
    }


def block_key(brick):
    """Compare placement and quantity without depending on an internal ID."""
    return tuple(brick[field] for field in BLOCK_FIELDS)


def validate_brick(value, index):
    prefix = f"blocks[{index}]"
    if not isinstance(value, dict):
        raise ValueError(f"{prefix}: expected an object")
    missing = [field for field in BLOCK_FIELDS if field not in value]
    if missing:
        raise ValueError(f"{prefix}: missing fields {missing}")
    brick = {field: value[field] for field in BLOCK_FIELDS}
    if brick["brick_type"] not in tuple(BRICK_SIZES):
        raise ValueError(f"{prefix}: unsupported brick_type")
    if brick["color"] not in ("yellow", "blue"):
        raise ValueError(f"{prefix}: color must be yellow or blue")
    for field in ("x", "y"):
        if type(brick[field]) is not int or not 0 <= brick[field] < BOARD_SIZE:
            raise ValueError(f"{prefix}: {field} must be an integer from 0 to 23")
    if type(brick["layer"]) is not int or not 1 <= brick["layer"] <= MAX_LAYER:
        raise ValueError(f"{prefix}: layer must be an integer from 1 to 4")
    allowed = (0,) if brick["brick_type"] == "2x2x1" else (0, 90)
    angle = brick["orientation_deg"]
    if type(angle) is not int or angle not in allowed:
        raise ValueError(f"{prefix}: orientation_deg must be an integer in {allowed}")
    for cell in occupied_cells(brick):
        if cell[0] >= BOARD_SIZE or cell[1] >= BOARD_SIZE:
            raise ValueError(f"{prefix}: outside board at {cell}")
    return brick


def check_support(brick, occupied, label):
    """Check distinct studs directly below; this is not a physics simulation."""
    if brick["layer"] == 1:
        return
    below = {(x, y, layer - 1) for x, y, layer in occupied_cells(brick)}
    count = len(below.intersection(occupied))
    if count < MIN_SUPPORT_STUDS:
        raise ValueError(
            f"{label}: support requires at least {MIN_SUPPORT_STUDS} studs "
            f"in the immediately lower layer; found {count}"
        )


def validate_design(design):
    """Recheck the planner's input and return copies of the six common fields."""
    if not isinstance(design, dict):
        raise ValueError("design must be an object")
    version = design.get("design_version")
    if type(version) is not int or version < 1:
        raise ValueError("design_version must be a positive integer")
    values = design.get("blocks")
    if not isinstance(values, list) or not values:
        raise ValueError("blocks must be a nonempty list")
    bricks = [validate_brick(value, i) for i, value in enumerate(values)]
    occupancy = {}
    for i, brick in enumerate(bricks):
        for cell in occupied_cells(brick):
            if cell in occupancy:
                raise ValueError(f"overlap: blocks[{i}] and blocks[{occupancy[cell]}] at {cell}")
            occupancy[cell] = i
    for i, brick in enumerate(bricks):
        check_support(brick, occupancy, f"blocks[{i}]")
    return bricks


def calculate_remaining_blocks(design, current_blocks):
    """Subtract adopted actual placements from the full target.

    Only the common block list is used, not a proposed Current envelope.
    This returns ordered remaining blocks, not an executable Replan.
    """
    targets = validate_design(design)
    if not isinstance(current_blocks, list):
        raise ValueError("current_blocks must be a list from Backend's adopted Current")
    remaining = Counter(map(block_key, targets))
    for i, value in enumerate(current_blocks):
        try:
            actual = validate_brick(value, i)
        except ValueError as exc:
            raise ValueError(f"current_blocks[{i}]: {exc}") from exc
        key = block_key(actual)
        if remaining[key] == 0:
            # Never turn a conflict into an automatic move/remove operation.
            raise ValueError(
                f"current_blocks[{i}]: placement or quantity is not preserved "
                f"in Design: {actual}"
            )
        remaining[key] -= 1
    return sorted(
        [b for b in targets if remaining[block_key(b)] > 0],
        key=lambda b: (b["layer"], -b["y"], b["x"]),
    )


def validate_step(step, index, earlier_steps):
    label = f"steps[{index}]"
    if not isinstance(step, dict) or set(step) != {
        "step_id", "operation", "before", "after", "prerequisites", "requires_delivery"
    }:
        raise ValueError(f"{label}: Step fields must match the Day4 contract")
    step_id = step["step_id"]
    if not isinstance(step_id, str) or not step_id.strip() or step_id in earlier_steps:
        raise ValueError(f"{label}: step_id must be nonempty and unique within Plan")
    if step["operation"] != "PLACE" or step["before"] is not None or step["requires_delivery"] is not True:
        raise ValueError(f"{label}: only PLACE with before=null and requires_delivery=true is supported")
    brick = validate_brick(step["after"], index)
    if set(step["after"]) != set(BLOCK_FIELDS):
        raise ValueError(f"{label}: after must contain the six common block fields")
    prerequisites = step["prerequisites"]
    if not isinstance(prerequisites, list) or any(
        not isinstance(ref, str) or ref not in earlier_steps for ref in prerequisites
    ):
        raise ValueError(f"{label}: prerequisites must reference earlier Steps in this Plan")
    if len(prerequisites) != len(set(prerequisites)):
        raise ValueError(f"{label}: duplicate prerequisite")
    return brick


def check_placement(brick, occupied, label):
    check_support(brick, occupied, label)
    cells = occupied_cells(brick)
    if cells.intersection(occupied):
        raise ValueError(f"{label}: placement overlaps an existing block")
    # Conservative footprint check for insertion from above, not a hand path model.
    footprint = {(x, y) for x, y, _ in cells}
    if any((x, y) in footprint and layer > brick["layer"] for x, y, layer in occupied):
        raise ValueError(f"{label}: insertion from above is blocked; manual correction needed")


def validate_plan(design, current_blocks, current_revision, plan):
    """Replay PLACE effects from adopted Current; this is not runtime Expected."""
    targets = validate_design(design)
    calculate_remaining_blocks(design, current_blocks)  # verifies preservation and quantity
    if type(current_revision) is not int or current_revision < 0:
        raise ValueError("current_revision must be a nonnegative integer")
    current = [validate_brick(value, i) for i, value in enumerate(current_blocks)]
    occupied = {cell for brick in current for cell in occupied_cells(brick)}
    for i, brick in enumerate(current):
        check_support(brick, occupied, f"current_blocks[{i}]")
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    if set(plan) != {"plan_id", "design_version", "base_current_revision", "steps"}:
        raise ValueError("plan fields must match the Day4 contract")
    if not isinstance(plan["plan_id"], str) or not plan["plan_id"].strip():
        raise ValueError("plan_id must be a nonempty string")
    if type(plan["design_version"]) is not int or plan["design_version"] != design["design_version"]:
        raise ValueError("plan design_version must match Design")
    if type(plan["base_current_revision"]) is not int or plan["base_current_revision"] != current_revision:
        raise ValueError(f"plan must match input Current revision {current_revision}")
    if not isinstance(plan["steps"], list):
        raise ValueError("steps must be a list")
    seen, placements = {}, []
    for i, step in enumerate(plan["steps"]):
        label = f"steps[{i}]"
        brick = validate_step(step, i, seen)
        lower = {sid for sid, b in seen.items() if b["layer"] < brick["layer"]}
        if not lower.issubset(step["prerequisites"]):
            raise ValueError(f"{label}: missing lower-layer prerequisite")
        if any(b["layer"] > brick["layer"] for b in seen.values()):
            raise ValueError(f"{label}: finish each lower layer before the next layer")
        check_placement(brick, occupied, label)
        occupied.update(occupied_cells(brick))
        seen[step["step_id"]] = brick
        placements.append(brick)
    if Counter(map(block_key, current + placements)) != Counter(map(block_key, targets)):
        raise ValueError("Current plus Plan placements must match all Design blocks and quantities")


def build_plan(design, current_blocks, current_revision):
    """Internal three-argument calculation API, pending Backend envelope wiring."""
    if type(current_revision) is not int or current_revision < 0:
        raise ValueError("current_revision must be a nonnegative integer")
    ordered = calculate_remaining_blocks(design, current_blocks)
    steps = []
    for number, brick in enumerate(ordered, start=1):
        steps.append({
            "step_id": f"S{number:02d}",
            "operation": "PLACE",
            "before": None,
            "after": brick,
            "prerequisites": [
                step["step_id"] for step in steps
                if step["after"]["layer"] < brick["layer"]
            ],
            "requires_delivery": True,
        })
    plan = {
        "plan_id": f"P-{uuid4().hex}",
        "design_version": design["design_version"],
        "base_current_revision": current_revision,
        "steps": steps,
    }
    validate_plan(design, current_blocks, current_revision, plan)
    return plan


def validate_initial_plan(design, plan):
    """Compatibility entry point for an empty Board at revision 0."""
    validate_plan(design, [], 0, plan)


def build_initial_plan(design):
    """Initial planning uses the same calculation and validator as Replan."""
    return build_plan(design, [], 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--output", type=Path, help="Optional JSON result file")
    args = parser.parse_args()
    try:
        design = json.loads(args.design.read_text(encoding="utf-8"))
        plan = build_initial_plan(design)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"INVALID_INPUT: {exc}", file=sys.stderr)
        return 2
    if args.output:
        try:
            args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"OUTPUT_ERROR: {exc}", file=sys.stderr)
            return 2
    for step in plan["steps"]:
        brick = step["after"]
        print(f'{step["step_id"]} {brick["color"]} {brick["brick_type"]} '
              f'({brick["x"]}, {brick["y"]}, layer={brick["layer"]}) '
              f'orientation_deg={brick["orientation_deg"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
