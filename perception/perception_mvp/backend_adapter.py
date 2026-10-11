"""Build common Observed. Region/stability evidence must come from observation, not ROI."""
from copy import deepcopy
import json

from .contracts import footprint, region_cells, validate_block
from .multiview import merge_views, compare_previous


def build_observed(check_id, observation_seq, views, previous_accepted_blocks,
                   target_after, *, scene_stable):
    if not isinstance(check_id, str) or not check_id:
        raise ValueError("Backend check_id required")
    if type(observation_seq) is not int or observation_seq < 0:
        raise ValueError("nonnegative bundle-start sequence required")
    validate_block(target_after)
    for block in previous_accepted_blocks:
        validate_block(block)
    if any((v["check_id"], v["observation_seq"]) != (check_id, observation_seq) for v in views):
        raise ValueError("view identifiers differ from requested bundle")
    merged = merge_views(views, scene_stable=scene_stable)
    regions, visible = merged["verified_regions"], merged["visible_blocks"]
    readable = footprint(target_after) <= region_cells(regions)
    # Expected selects necessary evidence only; mismatch does not filter actual blocks.
    observed = {"check_id": check_id, "observation_seq": observation_seq,
                "status": "OK" if readable else "UNOBSERVABLE",
                "visible_blocks": deepcopy(visible), "verified_regions": deepcopy(regions),
                "reason": None if readable else "target_region_unverified"}
    diagnostics = {"check_id": check_id, "observation_seq": observation_seq,
                   "issues": merged["issues"], "view_ids": [v["view_id"] for v in views],
                   "block_evidence": merged.get("block_evidence", []),
                   "tracking": compare_previous(visible, previous_accepted_blocks, regions),
                   "format_status": "proposed_diagnostics"}
    return observed, diagnostics


def deliver_observed(observed, callback):
    fields = {"check_id", "observation_seq", "status", "visible_blocks", "verified_regions", "reason"}
    if set(observed) != fields:
        raise ValueError("Observed requires exactly six common fields")
    if not isinstance(observed["check_id"], str) or not observed["check_id"]:
        raise ValueError("missing check_id")
    if type(observed["observation_seq"]) is not int or observed["observation_seq"] < 0:
        raise ValueError("invalid sequence")
    if observed["status"] not in ("OK", "UNOBSERVABLE"):
        raise ValueError("invalid observation status")
    if ((observed["status"] == "OK" and observed["reason"] is not None) or
            (observed["status"] == "UNOBSERVABLE" and not observed["reason"])):
        raise ValueError("invalid status/reason combination")
    for block in observed["visible_blocks"]:
        validate_block(block)
    region_cells(observed["verified_regions"])
    json.dumps(observed, allow_nan=False)
    return callback(deepcopy(observed))


def build_current_observed(check_id, observation_seq, views, previous_accepted_blocks,
                           required_regions, *, scene_stable):
    """CURRENT internal input: explicit requested coverage, not an invented after.

    Required regions select evidence to check; they do not assert observed occupancy.
    The D wire mapping must be agreed separately. No Current adoption is done here.
    """
    if not isinstance(check_id, str) or not check_id:
        raise ValueError("Backend check_id required")
    if type(observation_seq) is not int or observation_seq < 0:
        raise ValueError("nonnegative bundle-start sequence required")
    required = region_cells(required_regions)
    if not required:
        raise ValueError("CURRENT requires explicit nonempty observation scope")
    for block in previous_accepted_blocks:
        validate_block(block)
    if any((v["check_id"], v["observation_seq"]) != (check_id, observation_seq) for v in views):
        raise ValueError("view identifiers differ from requested bundle")
    merged = merge_views(views, scene_stable=scene_stable)
    regions, visible = merged["verified_regions"], merged["visible_blocks"]
    readable = required <= region_cells(regions)
    observed = {"check_id": check_id, "observation_seq": observation_seq,
                "status": "OK" if readable else "UNOBSERVABLE",
                "visible_blocks": deepcopy(visible), "verified_regions": deepcopy(regions),
                "reason": None if readable else "current_scope_unverified"}
    diagnostics = {"check_id": check_id, "observation_seq": observation_seq,
                   "issues": merged["issues"], "view_ids": [v["view_id"] for v in views],
                   "block_evidence": merged.get("block_evidence", []),
                   "tracking": compare_previous(visible, previous_accepted_blocks, regions),
                   "format_status": "proposed_diagnostics"}
    return observed, diagnostics
