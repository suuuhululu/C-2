"""Build initial and remaining PLACE Plans using the team's Day4 contract.

The caller relays B-confirmed actual blocks and their revision through D Backend.
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
MIN_SUPPORT_STUDS = 2  # A/C rule confirmed in Backend's 2026-10-06 reply.
BRICK_SIZES = {"2x2x1": (2, 2), "2x3x1": (2, 3)}
BLOCK_FIELDS = ("brick_type", "color", "x", "y", "layer", "orientation_deg")


class PlanningError(ValueError):
    """Carry failure details without deriving status or blocks from message text."""

    def __init__(self, reason, block=None, status="INVALID"):
        super().__init__(reason)
        self.block = block
        self.status = status


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
        raise PlanningError(f"{prefix}: expected an object")
    missing = [field for field in BLOCK_FIELDS if field not in value]
    if missing:
        raise PlanningError(f"{prefix}: missing fields {missing}")
    brick = {field: value[field] for field in BLOCK_FIELDS}
    if brick["brick_type"] not in tuple(BRICK_SIZES):
        raise PlanningError(f"{prefix}: unsupported brick_type", brick)
    if brick["color"] not in ("yellow", "blue"):
        raise PlanningError(f"{prefix}: color must be yellow or blue", brick)
    for field in ("x", "y"):
        if type(brick[field]) is not int or not 0 <= brick[field] < BOARD_SIZE:
            raise PlanningError(f"{prefix}: {field} must be an integer from 0 to 23", brick)
    if type(brick["layer"]) is not int or not 1 <= brick["layer"] <= MAX_LAYER:
        raise PlanningError(f"{prefix}: layer must be an integer from 1 to 4", brick)
    allowed = (0,) if brick["brick_type"] == "2x2x1" else (0, 90)
    angle = brick["orientation_deg"]
    if type(angle) is not int or angle not in allowed:
        raise PlanningError(f"{prefix}: orientation_deg must be an integer in {allowed}", brick)
    for cell in occupied_cells(brick):
        if cell[0] >= BOARD_SIZE or cell[1] >= BOARD_SIZE:
            raise PlanningError(f"{prefix}: outside board at {cell}", brick)
    return brick


def check_support(brick, occupied, label, status="INVALID"):
    """Check distinct studs directly below; this is not a physics simulation."""
    if brick["layer"] == 1:
        return
    below = {(x, y, layer - 1) for x, y, layer in occupied_cells(brick)}
    count = len(below.intersection(occupied))
    if count < MIN_SUPPORT_STUDS:
        raise PlanningError(
            f"{label}: support requires at least {MIN_SUPPORT_STUDS} studs "
            f"in the immediately lower layer; found {count}", brick, status
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
                raise PlanningError(
                    f"overlap: blocks[{i}] and blocks[{occupancy[cell]}] at {cell}", brick
                )
            occupancy[cell] = i
    for i, brick in enumerate(bricks):
        check_support(brick, occupancy, f"blocks[{i}]")
    return bricks


def calculate_remaining_blocks(design, current_blocks):
    """Subtract adopted actual placements from the full target.

    Only the common block list is used; plan_from_current handles the envelope.
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
            raise PlanningError(
                f"current_blocks[{i}]: {exc}", getattr(exc, "block", None)
            ) from exc
        key = block_key(actual)
        if remaining[key] == 0:
            # Never turn a conflict into an automatic move/remove operation.
            raise PlanningError(
                f"current_blocks[{i}]: placement or quantity is not preserved "
                f"in Design: {actual}", actual, "NEEDS_CORRECTION"
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
        raise PlanningError(f"{label}: placement overlaps an existing block", brick)
    # Conservative footprint check for insertion from above, not a hand path model.
    footprint = {(x, y) for x, y, _ in cells}
    if any((x, y) in footprint and layer > brick["layer"] for x, y, layer in occupied):
        raise PlanningError(
            f"{label}: insertion from above is blocked; manual correction needed",
            brick, "NEEDS_CORRECTION",
        )


def validate_plan(design, current_blocks, current_revision, plan, *, finish_layers=True):
    """Replay PLACE effects from adopted Current; this is not runtime Expected."""
    targets = validate_design(design)
    calculate_remaining_blocks(design, current_blocks)  # verifies preservation and quantity
    if type(current_revision) is not int or current_revision < 0:
        raise ValueError("current_revision must be a nonnegative integer")
    current = [validate_brick(value, i) for i, value in enumerate(current_blocks)]
    occupied = {cell for brick in current for cell in occupied_cells(brick)}
    for i, brick in enumerate(current):
        check_support(brick, occupied, f"current_blocks[{i}]", "NEEDS_CORRECTION")
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
        lower = {
            sid for sid, b in seen.items()
            if (b["layer"] < brick["layer"] if finish_layers else
                b["layer"] == brick["layer"] - 1 and
                {(x, y) for x, y, _ in occupied_cells(b)}.intersection(
                    (x, y) for x, y, _ in occupied_cells(brick)))
        }
        if not lower.issubset(step["prerequisites"]):
            raise ValueError(f"{label}: missing lower-layer prerequisite")
        if finish_layers and any(b["layer"] > brick["layer"] for b in seen.values()):
            raise ValueError(f"{label}: finish each lower layer before the next layer")
        check_placement(brick, occupied, label)
        occupied.update(occupied_cells(brick))
        seen[step["step_id"]] = brick
        placements.append(brick)
    if Counter(map(block_key, current + placements)) != Counter(map(block_key, targets)):
        raise ValueError("Current plus Plan placements must match all Design blocks and quantities")


def build_plan(design, current_blocks, current_revision, *, ordered_blocks=None,
               finish_layers=True):
    """Shared calculation API for initial planning and preservation-based Replan."""
    if type(current_revision) is not int or current_revision < 0:
        raise ValueError("current_revision must be a nonnegative integer")
    remaining = calculate_remaining_blocks(design, current_blocks)
    ordered = remaining if ordered_blocks is None else ordered_blocks
    if Counter(map(block_key, ordered)) != Counter(map(block_key, remaining)):
        raise ValueError("Ordered blocks must contain exactly the remaining target placements")
    steps = []
    for number, brick in enumerate(ordered, start=1):
        steps.append({
            "step_id": f"S{number:02d}",
            "operation": "PLACE",
            "before": None,
            "after": brick,
            "prerequisites": [
                step["step_id"] for step in steps
                if (step["after"]["layer"] < brick["layer"] if finish_layers else
                    step["after"]["layer"] == brick["layer"] - 1 and
                    {(x, y) for x, y, _ in occupied_cells(step["after"])}.intersection(
                        (x, y) for x, y, _ in occupied_cells(brick)))
            ],
            "requires_delivery": True,
        })
    plan = {
        "plan_id": f"P-{uuid4().hex}",
        "design_version": design["design_version"],
        "base_current_revision": current_revision,
        "steps": steps,
    }
    validate_plan(design, current_blocks, current_revision, plan,
                  finish_layers=finish_layers)
    return plan


def validate_current(current):
    """Read Backend's adopted Current; missing data is never an empty Board."""
    if not isinstance(current, dict):
        raise PlanningError("Current must be an object with current_revision and blocks")
    revision = current.get("current_revision")
    if type(revision) is not int or revision < 0:
        raise PlanningError("Current.current_revision must be a nonnegative integer")
    values = current.get("blocks")
    if not isinstance(values, list):
        raise PlanningError("Current.blocks must be a list")
    blocks, occupied = [], set()
    for i, value in enumerate(values):
        try:
            block = validate_brick(value, i)
        except ValueError as exc:
            raise PlanningError(
                f"Current.blocks[{i}]: {exc}", getattr(exc, "block", None)
            ) from exc
        cells = occupied_cells(block)
        if cells.intersection(occupied):
            raise PlanningError(f"Current.blocks[{i}]: overlapping actual placements", block)
        occupied.update(cells)
        blocks.append(block)
    return blocks, revision


def plan_from_current(design, current):
    """Backend boundary: Design + Current -> status / plan / errors.

    Backend still adopts Current and checks result freshness before execution.
    """
    try:
        validate_design(design)
        blocks, revision = validate_current(current)
        plan = build_plan(design, blocks, revision)
    except ValueError as exc:
        return {
            "status": getattr(exc, "status", "INVALID"),
            "plan": None,
            "errors": [{"reason": str(exc), "block": getattr(exc, "block", None)}],
        }
    return {"status": "READY", "plan": plan, "errors": []}


def plan_assembly_from_current(design, current, assembly_context):
    """Draft assembly-mode optimizer; uses the same geometry/Plan validators.

    Returns a separate candidate envelope, not the existing D execution contract.
    No SIM/REAL calculation branch or robot motion command is introduced.
    """
    from planning_trial.assembly_optimizer import plan_assembly
    return plan_assembly(design, current, assembly_context)


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
