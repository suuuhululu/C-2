"""A assembly-strategy classification; no release/press trajectory calculation."""
from copy import deepcopy

from planning_trial.assembly_geometry import MissingContext, validate_context
from planning_trial.assembly_optimizer import mode_options, option_cost
from planning_trial.planner import (
    block_key, check_support, occupied_cells, validate_brick, validate_current,
)


def assess_release_press(target, current, assembly_context):
    """Classify from fresh Current using the same policy as whole/step planning."""
    result = dict(schema_version="round2-assembly-strategy-local/0.2", status="INVALID",
        execution_allowed=False, assembly_completed=False, current_update=False,
        assessment_current_revision=None, assembly_strategy=None, action=None,
        assessment=None, errors=[])
    try:
        target = validate_brick(target, "target")
        blocks, revision = validate_current(current)
        result["assessment_current_revision"] = revision
        validate_context(assembly_context)
        occupied = {cell for b in blocks for cell in occupied_cells(b)}
        for b in blocks:
            check_support(b, occupied, "Current", "NEEDS_CORRECTION")
        if any(block_key(b) == block_key(target) for b in blocks):
            result["status"] = "ALREADY_ASSEMBLED"
            return result
        options, assessment = mode_options(target, blocks, assembly_context)
        result["assessment"] = deepcopy(assessment)
        if not options:
            result.update(status="BLOCKED", errors=[assessment["reason"]])
            return result
        action = min(options, key=lambda o: (option_cost(o), o["mode"], o["grip_axis"] or ""))
        result.update(status="CANDIDATE", action=deepcopy(action),
                      assembly_strategy=action.get("assembly_strategy"))
    except (ValueError, KeyError, TypeError) as error:
        result.update(status="INPUTS_REQUIRED" if isinstance(error, MissingContext)
                      else getattr(error, "status", "INVALID"), errors=[str(error)])
    return result
