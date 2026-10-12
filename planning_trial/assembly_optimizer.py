"""Minimize human-assisted Steps over feasible placement orders.

Searches deduplicated subsets of remaining blocks. Every Step ends with tools/hands
withdrawn; no old readiness response or support hold is reused across Steps.
Feasibility is the explicitly supplied envelope model, not physical execution.
"""

import argparse
from copy import deepcopy
from hashlib import sha256
from heapq import heappop, heappush
from itertools import count
import json
from pathlib import Path
from time import monotonic

from planning_trial.assembly_geometry import (
    MissingContext, block_box, contacts, footprint, grip_options, hand_options, human_press_assessment,
    human_press_options, press_options, support_assignments,
    intersects, validate_context,
)
from planning_trial.planner import (
    block_key, build_plan, calculate_remaining_blocks,
    check_placement, check_support, occupied_cells, validate_current,
    validate_step,
)


SCHEMA = "assembly-assistance-candidate/0.2"
MODES = ("ROBOT_GRIP", "ROBOT_RELEASE_PRESS", "HUMAN_ASSEMBLY")
HELP_OPTIMIZATION_WINDOW_S = 30.0
MINIMAL_RELEASE_INSTRUCTION = "이 블록을 조립한 후에는 그리퍼를 소폭 개방하고 후퇴해야 합니다."


def assess_step(design, plan, step_id, current, context):
    """Use fresh B-confirmed Current; D relays it and checks execution permits.

    Normal progress may increase Current revision beyond Plan's original base.
    A new hand readiness request remains a D/C responsibility, never assumed here.
    """
    result = {"schema_version": SCHEMA, "execution_allowed": False,
              "plan_id": None, "step_id": step_id, "assessment_current_revision": None,
              "context_digest": None, "options": [], "errors": []}
    try:
        blocks, revision = validate_current(current)
        calculate_remaining_blocks(design, blocks)
        occupied = set().union(*(occupied_cells(b) for b in blocks))
        for b in blocks:
            check_support(b, occupied, "Current", "NEEDS_CORRECTION")
        if (not isinstance(plan, dict) or
                set(plan) != {"plan_id", "design_version", "base_current_revision", "steps"} or
                not isinstance(plan["plan_id"], str) or not plan["plan_id"] or
                type(plan["base_current_revision"]) is not int or
                not 0 <= plan["base_current_revision"] <= revision or
                type(plan["design_version"]) is not int or
                plan["design_version"] != design["design_version"] or
                not isinstance(plan["steps"], list)):
            raise ValueError("Plan references must match Design and a non-future Current baseline")
        seen = {}
        for index, step in enumerate(plan["steps"]):
            seen[step["step_id"]] = validate_step(step, index, seen)
        design_keys = {block_key(b) for b in design["blocks"]}
        if any(block_key(b) not in design_keys for b in seen.values()):
            raise ValueError("Plan contains placements outside the adopted Design")
        if step_id not in seen:
            raise ValueError("Unknown step_id")
        keys = {block_key(b) for b in blocks}
        target = seen[step_id]
        result.update(plan_id=plan["plan_id"], assessment_current_revision=revision)
        if block_key(target) in keys:
            result["status"] = "ALREADY_ASSEMBLED"
            return result
        step = next(s for s in plan["steps"] if s["step_id"] == step_id)
        if any(block_key(seen[p]) not in keys for p in step["prerequisites"]):
            result.update(status="WAIT_PREREQUISITES", errors=[{
                "reason": "Predecessor placements are not confirmed in Current", "block": target}])
            return result
        validate_context(context)
        options, assessment = mode_options(target, blocks, context)
        result.update(status="CANDIDATE" if options else "NO_FEASIBLE_METHOD",
                      options=options, assessment=assessment,
                      context_digest=sha256(json.dumps(context, sort_keys=True).encode()).hexdigest())
    except ValueError as exc:
        result.update(status=("INPUTS_REQUIRED" if isinstance(exc, MissingContext) else
                              getattr(exc, "status", "INVALID")),
                      errors=[{"reason": str(exc), "block": getattr(exc, "block", None)}])
    return result


def mode_options(brick, current, context):
    """Methods meeting placement/tool checks; human access space is not checked."""
    occupied = set().union(*(occupied_cells(b) for b in current))
    try:
        check_placement(brick, occupied, "candidate")
    except ValueError as exc:
        return [], {"reason": str(exc)}
    if any(intersects(block_box(brick, context), obstacle) for obstacle in context["obstacles"]):
        return [], {"reason": "candidate: target block overlaps a static obstacle"}
    support = contacts(brick, current)
    weak, options, reasons = support["weak_supports"], [], []
    press_assessment = human_press_assessment(brick, support, context)
    supported_modes = context.get('supported_modes', MODES)
    # A held block may be inserted with human support despite adjacent voids.
    # The unheld release/press method still requires full footprint support.
    for mode in MODES[:2]:
        if mode not in supported_modes:
            reasons.append(mode + ': disabled by supported_modes')
            continue
        if mode == "ROBOT_RELEASE_PRESS":
            if support["support_studs"] != support["total_studs"]:
                reasons.append(mode + ": release requires full footprint support")
                continue
            if not context["press_contact_model_confirmed"]:
                reasons.append(mode + ": pressing contact model not confirmed")
                continue
            tools = press_options(brick, current, context)
        else:
            tools = grip_options(brick, current, context)
        if not tools:
            reasons.append(mode + ": local approach/release envelope blocked")
        for tool in tools:
            presses = (human_press_options(brick,current,context,support,tool["tool_boxes"])
                       if press_assessment["required"] else [None])
            if not presses:
                reasons.append(mode + ": no supported contact stud for required human press")
            for press in presses:
                assignments = support_assignments(weak, brick, current, context, tool["tool_boxes"],
                                                  press_hand=press)
                if not assignments:
                    reasons.append(mode + ": required human actions exceed two hands")
                for assignment in assignments:
                    options.append({"mode": mode, "grip_axis": tool["grip_axis"],
                                    "release_strategy": tool["release_strategy"],
                                    "release_margin_per_side_mm": tool["release_margin_per_side_mm"],
                                    "clearance_pitch_per_side":tool.get("clearance_pitch_per_side"),
                                    "support_targets": assignment, "assembly_hand": None,
                                    "press_hand":press,"press_assessment":press_assessment,
                                    "contacts": support})
    # One hand assembles; at most the other hand can support one lower block.
    hands = (hand_options(brick, current, context, assembly=True)
             if 'HUMAN_ASSEMBLY' in supported_modes else [])
    if 'HUMAN_ASSEMBLY' not in supported_modes:
        reasons.append('HUMAN_ASSEMBLY: disabled by supported_modes')
    if not hands:
        reasons.append("HUMAN_ASSEMBLY: no nominal assembly contact suggestion")
    for hand in hands:
        for assignment in support_assignments(weak, brick, current, context, assembly_hand=hand):
            options.append({"mode": "HUMAN_ASSEMBLY", "grip_axis": None,
                            "release_strategy": None, "release_margin_per_side_mm": None,
                            "clearance_pitch_per_side":None,
                            "support_targets": assignment, "assembly_hand": hand,
                            "press_hand":None,"press_assessment":press_assessment,
                            "contacts": support})
    if hands and not any(o["mode"] == "HUMAN_ASSEMBLY" for o in options):
        reasons.append("HUMAN_ASSEMBLY: required human actions exceed two hands")
    for option in options:
        minimal = option["release_strategy"] == "MINIMAL_OPEN"
        option.update(requires_minimal_release=minimal,
                      release_instruction=MINIMAL_RELEASE_INSTRUCTION if minimal else None)
        human_actions = [{"action":"HOLD","target_block":t["block"],"hand":t}
                         for t in option["support_targets"]]
        if option["press_hand"]:
            human_actions.append({"action":"PRESS","target_block":brick,"hand":option["press_hand"]})
        if option["assembly_hand"]:
            human_actions.append({"action":"MANUAL_PLACE","target_block":brick,"hand":option["assembly_hand"]})
        option["human_actions"] = human_actions
        kinds={a["action"] for a in human_actions}
        option["assistance_kind"] = (
            "MANUAL_ASSEMBLY_AND_HOLD" if kinds=={"MANUAL_PLACE","HOLD"} else
            "MANUAL_ASSEMBLY" if "MANUAL_PLACE" in kinds else
            "PRESS_AND_HOLD" if kinds=={"PRESS","HOLD"} else
            "PRESS" if "PRESS" in kinds else "HOLD" if "HOLD" in kinds else "NONE")
    return options, {**support, "press_assessment":press_assessment,
                     "reason": "; ".join(dict.fromkeys(reasons))}


def option_cost(option):
    manual = option["mode"] == "HUMAN_ASSEMBLY"
    return (int(bool(option["human_actions"])), int(manual), len(option["human_actions"]))


def _order_precedence(remaining, current, context):
    """Necessary ordering from existing insertion and local-access checks.

    An overlapping upper placement permanently prevents insertion from above,
    regardless of assembly mode. Disjoint footprints do not require whole layers.
    Grip edges additionally require every enabled axis to be blocked in the
    monotone STUD_RULES model; alternative assembly modes skip that grip proof.
    """
    predecessors = [0] * len(remaining)
    footprints = [footprint(brick) for brick in remaining]
    for i, lower in enumerate(remaining):
        for j, upper in enumerate(remaining):
            if lower["layer"] < upper["layer"] and footprints[i] & footprints[j]:
                predecessors[j] |= 1 << i
    if (context.get("space_model") != "STUD_RULES" or
            context.get("supported_modes") != ["ROBOT_GRIP"]):
        return predecessors, None
    for i, brick in enumerate(remaining):
        if not grip_options(brick, current, context):
            return predecessors, [{"block": brick, "assessment": {
                "reason": "ROBOT_GRIP corridor blocked by Current/static obstacles; adding blocks cannot clear it"}}]
        for j, other in enumerate(remaining):
            if i != j and not grip_options(brick, current + [other], context):
                predecessors[j] |= 1 << i
    full, resolved = (1 << len(remaining)) - 1, 0
    while resolved != full:
        available = sum(1 << i for i, required in enumerate(predecessors)
                        if not resolved & (1 << i) and required & resolved == required)
        if not available:
            return predecessors, [{"block": brick, "assessment": {
                "reason": "ROBOT_GRIP necessary ordering blocked by a cycle",
                "required_before": [remaining[j] for j in range(len(remaining))
                                    if predecessors[i] & (1 << j)]}}
                for i, brick in enumerate(remaining) if not resolved & (1 << i)]
        resolved |= available
    return predecessors, None


def _search_path(parent, mask):
    path = []
    while mask:
        previous, index, option = parent[mask]
        path.append((index, option))
        mask = previous
    return list(reversed(path))


def _minimize_help_search(remaining, current, context, incumbent_path=None, predecessors=None, deadline=None):
    """Minimize help until proven optimal or the window ends with a complete plan.

    No state-count cutoff. A deadline without any complete plan never aborts
    feasibility or turns a partial path into a candidate.
    """
    full = (1 << len(remaining)) - 1
    serial = count()
    queue = [((0, 0, 0), 0, next(serial), 0)]
    costs, parent, expanded, dead_end = {0: (0, 0, 0)}, {}, 0, None

    def completed_at_deadline(lower_bound):
        if deadline is None or monotonic() < deadline:
            return None
        best = incumbent_path
        best_cost = (tuple(sum(option_cost(o)[k] for _, o in best) for k in range(3))
                     if best is not None else None)
        if full in parent and (best_cost is None or costs[full] < best_cost):
            best, best_cost = _search_path(parent, full), costs[full]
        if best is None:
            return None
        return best, {"optimal": False, "expanded_states": expanded,
                      "cost": list(best_cost), "lower_bound_cost": list(lower_bound),
                      "best_known_complete_plan_retained": True,
                      "optimization_stop_reason": "HELP_OPTIMIZATION_WINDOW_ELAPSED"}

    while queue:
        cost, _, _, mask = heappop(queue)
        if costs[mask] != cost:
            continue
        if mask == full:
            return _search_path(parent, mask), {"optimal": True, "expanded_states": expanded,
                                         "cost": list(cost)}
        completed = completed_at_deadline(cost)
        if completed is not None:
            return completed
        expanded += 1
        placed = current + [b for i, b in enumerate(remaining) if mask & (1 << i)]
        left = [(i, b) for i, b in enumerate(remaining) if not mask & (1 << i)]
        lowest = min(b["layer"] for _, b in left)
        explanations, successors = [], 0
        for index, brick in left:
            completed = completed_at_deadline(cost)
            if completed is not None:
                return completed
            if predecessors and predecessors[index] & mask != predecessors[index]:
                continue
            if context["finish_layers"] and brick["layer"] != lowest:
                continue
            options, explanation = mode_options(brick, placed, context)
            if not options:
                explanations.append({"block": brick, "assessment": explanation})
                continue
            # Methods produce the same block effect; hands are released each Step.
            # A locally cheaper method cannot make a later state more expensive.
            option = min(options, key=lambda o: (option_cost(o), MODES.index(o["mode"]),
                                                o["release_strategy"] == "MINIMAL_OPEN"))
            new_cost = tuple(a + b for a, b in zip(cost, option_cost(option)))
            next_mask = mask | (1 << index)
            if next_mask not in costs or new_cost < costs[next_mask]:
                costs[next_mask] = new_cost
                parent[next_mask] = (mask, index, option)
                # Deeper states win equal-cost ties, avoiding exhaustive zero-cost
                # permutations while preserving Dijkstra's optimality guarantee.
                heappush(queue, (new_cost, -next_mask.bit_count(), next(serial), next_mask))
            successors += 1
        if not successors and (dead_end is None or mask.bit_count() > dead_end[0]):
            dead_end = (mask.bit_count(), explanations)
    return None, {"optimal": False, "expanded_states": expanded,
                  "reason": "NO_FEASIBLE_ORDER",
                  "blocked_candidates": dead_end[1] if dead_end else []}


def _complete_plan_first(remaining,current,context,predecessors=None):
    """Find a complete model-feasible witness before assistance optimization.

    A subset has the same future block effect for all feasible methods under the
    existing withdrawn-hands model. This is not MoveIt transport validation.
    """
    full=(1<<len(remaining))-1;visited=set();expanded=0;deepest=None
    ordered=sorted(enumerate(remaining),key=lambda pair:(pair[1]["layer"],-pair[1]["y"],pair[1]["x"],pair[0]))
    path=[]

    def visit(mask):
        nonlocal expanded, deepest
        if mask==full:return list(path)
        if mask in visited:return None
        visited.add(mask);expanded+=1
        placed=current+[b for i,b in enumerate(remaining) if mask&(1<<i)]
        lowest=min(b["layer"] for i,b in ordered if not mask&(1<<i));successors=0;blocked=[]
        for i,brick in ordered:
            if mask&(1<<i):continue
            if predecessors and predecessors[i]&mask!=predecessors[i]:continue
            if context["finish_layers"] and brick["layer"]!=lowest:continue
            options,assessment=mode_options(brick,placed,context)
            if not options:blocked.append({"block":brick,"assessment":assessment});continue
            option=min(options,key=lambda o:(option_cost(o),MODES.index(o["mode"]),o["release_strategy"]=="MINIMAL_OPEN"))
            # Check the next sibling only after this branch fails. A straightforward
            # complete order needs n method checks instead of n*(n+1)/2.
            successors+=1;path.append((i,option))
            complete=visit(mask|(1<<i));path.pop()
            if complete is not None:return complete
        if not successors and (deepest is None or mask.bit_count()>deepest[0]):deepest=(mask.bit_count(),blocked)
        return None

    complete=visit(0)
    if complete is not None:return complete,{"expanded_states":expanded}
    return None,{"expanded_states":expanded,"reason":"NO_FEASIBLE_ORDER","blocked_candidates":deepest[1] if deepest else []}


def order_search(remaining,current,context):
    started = monotonic()
    deadline = started + HELP_OPTIMIZATION_WINDOW_S
    policy = {"state_limit_applied": False,
              "help_optimization_window_s": HELP_OPTIMIZATION_WINDOW_S}
    predecessors,blocked=_order_precedence(remaining,current,context)
    if blocked is not None:
        return None,{**policy,"reason":"NO_FEASIBLE_ORDER","expanded_states":0,"optimal":False,
                     "complete_plan_found":False,"feasibility_expanded_states":0,
                     "completion_feasibility_basis":"A_SUPPORT_AND_LOCAL_ACCESS_NOT_MOVEIT_TRANSPORT",
                     "blocked_candidates":blocked,"selection":"PROVEN_GRIP_ORDERING_CONFLICT"}
    if context.get("planning_priority","COMPLETE_DESIGN_THEN_MIN_HELP")!="COMPLETE_DESIGN_THEN_MIN_HELP":
        path, info = _minimize_help_search(remaining,current,context,predecessors=predecessors,deadline=deadline)
        return path, {**info, **policy, "complete_plan_found": path is not None}
    witness,first=_complete_plan_first(remaining,current,context,predecessors)
    evidence={**policy,"priority":["COMPLETE_DESIGN","ASSISTED_STEPS","MANUAL_STEPS","HUMAN_ACTIONS"],
              "completion_feasibility_basis":"A_SUPPORT_AND_LOCAL_ACCESS_NOT_MOVEIT_TRANSPORT",
              "complete_plan_found":witness is not None,"feasibility_expanded_states":first["expanded_states"]}
    if witness is None:return None,{**first,**evidence,"optimal":False}
    cost=tuple(sum(option_cost(option)[k] for _,option in witness) for k in range(3))
    if cost==(0,0,0):
        return witness,{**evidence,"optimal":True,"expanded_states":first["expanded_states"],"help_optimization_expanded_states":0,"cost":list(cost),"selection":"COMPLETE_ZERO_HELP_PLAN"}
    if monotonic() >= deadline:
        return witness,{**evidence,"optimal":False,"expanded_states":first["expanded_states"],"help_optimization_expanded_states":0,"cost":list(cost),"selection":"FIRST_COMPLETE_PLAN_AFTER_WINDOW","optimization_stop_reason":"HELP_OPTIMIZATION_WINDOW_ELAPSED"}
    optimized,second=_minimize_help_search(remaining,current,context,incumbent_path=witness,predecessors=predecessors,deadline=deadline)
    if optimized is None:
        raise ValueError("Help search contradicted a verified complete feasibility witness")
    result={**second,**evidence,"expanded_states":first["expanded_states"]+second["expanded_states"],"help_optimization_expanded_states":second["expanded_states"]}
    result["selection"] = "COMPLETE_PLAN_MIN_HELP" if second["optimal"] else "BEST_KNOWN_COMPLETE_PLAN"
    return optimized,result


def action_signature(option):
    return (option["mode"], option["grip_axis"], option["release_strategy"],
            tuple((block_key(t["block"]), t["side"]) for t in option["support_targets"]),
            option["assembly_hand"]["side"] if option["assembly_hand"] else None,
            (option["press_hand"]["side"],tuple(option["press_hand"]["contact_point_board_mm"]))
            if option.get("press_hand") else None)


def validate_candidate(design, current, context, plan, actions):
    """Replay both block effects and chosen method/hand-access preconditions."""
    from planning_trial.planner import validate_plan
    blocks, revision = validate_current(current)
    validate_plan(design, blocks, revision, plan, finish_layers=context["finish_layers"])
    if len(actions) != len(plan["steps"]):
        raise ValueError("Each Step must have exactly one assembly action")
    total = (0, 0, 0)
    for step, action in zip(plan["steps"], actions):
        if (action["plan_id"] != plan["plan_id"] or action["step_id"] != step["step_id"] or
                action["block"] != step["after"] or action["base_current_revision"] != revision):
            raise ValueError("Action Plan/Step/block/revision reference mismatch")
        options, _ = mode_options(step["after"], blocks, context)
        if not any(action_signature(o) == action_signature(action) for o in options):
            raise ValueError("Selected assembly method/support access is no longer feasible")
        chosen = next(o for o in options if action_signature(o) == action_signature(action))
        for field in ("support_targets", "assembly_hand", "press_hand", "press_assessment",
                      "human_actions", "assistance_kind", "contacts", "release_margin_per_side_mm",
                      "clearance_pitch_per_side"):
            if json.dumps(action[field], sort_keys=True) != json.dumps(chosen[field], sort_keys=True):
                raise ValueError("Action contact/hand geometry differs from reassessment")
        if (action["needs_human_request"] is not bool(option_cost(chosen)[0]) or
                action["human_hands_used"] != len(chosen["human_actions"]) or
                action["human_hands_used"] > 2 or
                action["insertion_direction_board"] != [0, 0, -1] or
                action["requires_minimal_release"] is not (chosen["release_strategy"] == "MINIMAL_OPEN") or
                action["release_instruction"] != (MINIMAL_RELEASE_INSTRUCTION
                    if chosen["release_strategy"] == "MINIMAL_OPEN" else None) or
                action["requires_runtime_reassessment"] is not True):
            raise ValueError("Action assistance metadata is inconsistent")
        total = tuple(a + b for a, b in zip(total, option_cost(chosen)))
        blocks.append(step["after"])
    return list(total)


def plan_assembly(design, current, context):
    result = {"schema_version": SCHEMA, "status": None, "execution_allowed": False,
              "planning_result": None, "assembly_actions": [], "optimization": None,
              "contract_status": "DRAFT_NOT_CONNECTED_TO_D", "errors": [],
              "limits": ["Human hand access-space checks excluded by user policy; contact regions are nominal suggestions",
                         "Space rules/envelopes are not robot IK/full-path/human safety verification",
                         "Stud overlap and void rules are not physical stability proof",
                         "PRESS is a contact-hull heuristic, not a measured force requirement",
                         "Force control, contact success and readiness belong to D/C",
                         "Each assisted Step opens a new request; no readiness reuse"]}
    try:
        remaining = calculate_remaining_blocks(design, current.get("blocks") if isinstance(current, dict) else None)
        blocks, revision = validate_current(current)
        occupied = set().union(*(occupied_cells(b) for b in blocks))
        for b in blocks:
            check_support(b, occupied, "Current", "NEEDS_CORRECTION")
    except ValueError as exc:
        status = getattr(exc, "status", "INVALID")
        error = {"reason": str(exc), "block": getattr(exc, "block", None)}
        result.update(status=status, errors=[error],
                      planning_result={"status": status, "plan": None, "errors": [error]})
        return result
    try:
        validate_context(context)
    except MissingContext as exc:
        result.update(status="INPUTS_REQUIRED", errors=[{"reason": str(exc), "block": None}])
        return result
    except ValueError as exc:
        result.update(status="INVALID_CONTEXT", errors=[{"reason": str(exc), "block": None}])
        return result
    result["profile_source"] = context["profile_source"]
    result["space_model"] = context.get("space_model","LEGACY_ENVELOPE")
    result["human_press_policy"] = context.get("human_press_policy","NONE")
    result["context_digest"] = sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    path, optimization = order_search(remaining, blocks, context)
    result["optimization"] = optimization
    if path is None:
        result.update(status=optimization["reason"], errors=[{
            "reason": optimization["reason"], "block": None}])
        return result
    ordered = [remaining[index] for index, _ in path]
    plan = build_plan(design, blocks, revision, ordered_blocks=ordered,
                      finish_layers=context["finish_layers"])
    actions = []
    for step, (_, option) in zip(plan["steps"], path):
        actions.append({**deepcopy(option), "plan_id": plan["plan_id"],
                        "step_id": step["step_id"], "block": deepcopy(step["after"]),
                        "base_current_revision": revision,
                        "needs_human_request": bool(option_cost(option)[0]),
                        "human_hands_used": len(option["human_actions"]),
                        "insertion_direction_board": [0, 0, -1],
                        "requires_minimal_release": option["release_strategy"] == "MINIMAL_OPEN",
                        "release_instruction": (MINIMAL_RELEASE_INSTRUCTION
                            if option["release_strategy"] == "MINIMAL_OPEN" else None),
                        "requires_runtime_reassessment": True})
    if validate_candidate(design, current, context, plan, actions) != optimization["cost"]:
        raise ValueError("Candidate human-assistance cost does not match replay")
    result.update(status="CANDIDATE", planning_result={"status": "READY", "plan": plan,
                                                     "errors": []}, assembly_actions=actions)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, help="Design/Current/context JSON fixture")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        inputs = json.loads(args.inputs.read_text())
        result = plan_assembly(inputs["design"], inputs["current"], inputs["assembly_context"])
        if args.output:
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print("Status:", result["status"], "execution_allowed:", result["execution_allowed"])
        if result["status"] != "CANDIDATE":
            print(json.dumps(result["errors"], ensure_ascii=False))
            return 2
        print("Optimal in model:", result["optimization"]["optimal"],
              "[requests, manual Steps, support targets]:", result["optimization"]["cost"])
        for action in result["assembly_actions"]:
            b = action["block"]
            print(action["step_id"], action["mode"], b["color"], b["brick_type"],
                  (b["x"], b["y"], b["layer"]),
                  "support_targets=", len(action["support_targets"]),
                  "release_strategy=", action["release_strategy"])
            if action["release_instruction"]:
                print(" ", action["release_instruction"])
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print("INVALID_INPUT:", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
