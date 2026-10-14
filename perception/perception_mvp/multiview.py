"""Merge normalized calibrated placements; stable-bundle evidence is explicit input."""
from copy import deepcopy

from .contracts import footprint, placement_key, region_cells


def merge_views(views, *, scene_stable, vote_policy=None):
    if views:
        identity = (views[0]["check_id"], views[0]["observation_seq"], views[0]["calibration_id"])
        if any((v["check_id"], v["observation_seq"], v["calibration_id"]) != identity for v in views):
            raise ValueError("mixed check/sequence/calibration in bundle")
    vote_log = []
    if vote_policy is not None and scene_stable:
        from .class_vote import prepare_class_votes
        views, vote_log = prepare_class_votes(views, vote_policy)
    result = _merge_views(views, scene_stable=scene_stable)
    result['class_vote_log'] = vote_log
    result['issues'].extend('class_vote:'+v['decision'] for v in vote_log
                            if v['decision'] not in ('SELECTED', 'ABSTAIN'))
    return result


def merge_local_views(views, *, scene_stable):
    """Same fusion computation without inventing Backend IDs for standalone trials."""
    if views and any(v["calibration_id"] != views[0]["calibration_id"] for v in views):
        raise ValueError("mixed calibration in local bundle")
    return _merge_views(views, scene_stable=scene_stable)


def _merge_views(views, *, scene_stable):
    if type(scene_stable) is not bool:
        raise ValueError("explicit scene_stable evidence required")
    if not views:
        return {"visible_blocks": [], "verified_regions": [], "issues": ["no_views"]}
    ids, grouped, regions, issues = set(), {}, [], []
    for view in views:
        if view["view_id"] not in ("V0", "D1", "D2", "D3", "D4") or view["view_id"] in ids:
            raise ValueError("unsupported or duplicate view")
        ids.add(view["view_id"])
        region_cells(view["verified_regions"])
        if view["status"] not in ("OK", "UNOBSERVABLE"):
            raise ValueError("view status must be OK or UNOBSERVABLE")
        if view["status"] == "UNOBSERVABLE":
            if not view["reason"]:
                raise ValueError("unobservable view requires reason")
            issues.append(f"{view['view_id']}:{view['reason']}")
        seen = set()
        for block in view["visible_blocks"]:
            key = placement_key(block)
            if key in seen:
                raise ValueError("duplicate detection within one view")
            seen.add(key)
            grouped.setdefault(key, {"block": deepcopy(block), "views": []})["views"].append(view["view_id"])
        regions.extend(deepcopy(view["verified_regions"]))
    if not scene_stable:
        return {"visible_blocks": [], "verified_regions": [], "issues": ["scene_stability_unverified"]}
    entries = list(grouped.values())
    conflicts, conflict_cells = set(), set()
    for i, entry in enumerate(entries):
        occupied = footprint(entry["block"])
        for view in views:
            checked = region_cells(view["verified_regions"])
            local_occupied = set().union(*(footprint(b) for b in view["visible_blocks"]))
            if occupied & (checked - local_occupied):
                conflicts.add(i)
                conflict_cells.update(occupied)
                issues.append(f"{view['view_id']}:empty_vs_occupied_conflict")
    for i, first in enumerate(entries):
        for j in range(i + 1, len(entries)):
            second = entries[j]
            overlap = footprint(first["block"]) & footprint(second["block"])
            if overlap:
                conflicts.update((i, j))
                conflict_cells.update(footprint(first["block"]) | footprint(second["block"]))
    if conflicts:
        issues.append("overlapping_placement_conflict")
    # Exclude any region touched by unresolved evidence; never report it as empty.
    verified = [r for r in regions if not (region_cells([r]) & conflict_cells)]
    unique_regions = {tuple(sorted(r.items())): r for r in verified}
    return {"visible_blocks": [e["block"] for i, e in enumerate(entries) if i not in conflicts],
            "verified_regions": list(unique_regions.values()), "issues": issues,
            "block_evidence": [e for i, e in enumerate(entries) if i not in conflicts]}


def compare_previous(visible_blocks, previous_accepted_blocks, verified_regions):
    current = {placement_key(b): b for b in visible_blocks}
    previous = {placement_key(b): b for b in previous_accepted_blocks}
    if len(current) != len(visible_blocks) or len(previous) != len(previous_accepted_blocks):
        raise ValueError("duplicate normalized placements")
    verified = region_cells(verified_regions)
    added, removed, tracked = [], [], []
    for key, block in previous.items():
        if key not in current:
            if footprint(block) <= verified:
                removed.append(deepcopy(block))
            else:
                tracked.append({"placement": deepcopy(block),
                                "basis": "previous_backend_accepted_state",
                                "reason": "occluded_or_unverified"})
    for key, block in current.items():
        if key not in previous:
            added.append(deepcopy(block))
    # Physical identity is unknown; even a unique same-kind pair is only a candidate.
    movement = [{"before": deepcopy(old), "after": deepcopy(new), "identity": "UNCONFIRMED"}
                for old in removed for new in added
                if (old["brick_type"], old["color"]) == (new["brick_type"], new["color"])]
    return {"tracked_blocks": tracked, "added_candidates": added,
            "removed_candidates": removed, "movement_candidates": movement}
