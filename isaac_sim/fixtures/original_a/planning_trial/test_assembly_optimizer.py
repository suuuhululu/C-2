"""Behavioral tests of draft geometry/mode/order calculations; no device calls."""
import copy
from itertools import permutations
import json
from pathlib import Path

import pytest

from planning_trial.assembly_geometry import contacts, hand_options, grip_options
from planning_trial.assembly_optimizer import (
    assess_step, mode_options, option_cost, plan_assembly, validate_candidate,
)
from planning_trial.planner import build_plan, plan_from_current, plan_assembly_from_current


def brick(x=6, y=6, layer=1, kind="2x2x1", angle=0):
    return dict(brick_type=kind, color="yellow", x=x, y=y,
                layer=layer, orientation_deg=angle)


@pytest.fixture
def inputs():
    return json.loads(Path(__file__).with_name("sample_assembly_inputs.json").read_text())


@pytest.fixture
def context(inputs):
    return inputs["assembly_context"]


@pytest.mark.parametrize("kind,angle,dx,dy,count", [
    ("2x2x1",0,1,0,2), ("2x2x1",0,0,1,2),
    ("2x3x1",0,1,0,3), ("2x3x1",90,0,1,3),
])
def test_actual_overlap_and_adjacent_empty_cells(kind, angle, dx, dy, count):
    lower = brick(6,6,1,kind,angle)
    upper = brick(6+dx,6+dy,2,kind,angle)
    info = contacts(upper,[lower])
    assert info["support_studs"] == count
    assert info["largest_missing_component"] >= 2
    assert info["weak_supports"] == []  # Board-supported first layer is excluded.


def test_isolated_missing_cell_is_not_a_two_cell_component():
    upper = brick(6,6,2)
    # Three cells supplied by disjoint lower blocks; fourth is unsupported.
    lower = [brick(5,5),brick(7,5),brick(5,7)]
    info = contacts(upper,lower)
    assert info["support_studs"] == 3
    assert info["largest_missing_component"] == 1


def test_each_lower_block_is_assessed_and_lower_studs_are_summed():
    first = brick(6,6,1)
    second = brick(7,6,2)
    third = brick(8,6,3)
    info = contacts(third,[first,second])
    assert [(t["upper_studs"],t["lower_studs"]) for t in info["weak_supports"]] == [(2,2)]
    info = contacts(third,[first,brick(8,6,1),second])
    assert info["weak_supports"] == []  # 2+2 lower studs is four, not two weak links.


def test_partial_footprint_does_not_use_release_press(context):
    lower, upper = brick(), brick(7,6,2)
    context["press_contact_model_confirmed"] = True
    options,_ = mode_options(upper,[lower],context)
    assert any(o["mode"] == "ROBOT_GRIP" for o in options)
    assert all(o["mode"] != "ROBOT_RELEASE_PRESS" for o in options)


def test_adjacent_void_allows_robot_grip_with_lower_block_support(context):
    base, lower, upper = brick(), brick(7,6,2), brick(8,6,3)
    options, info = mode_options(upper,[base,lower],context)
    assert info["largest_missing_component"] == 2
    grips = [o for o in options if o["mode"] == "ROBOT_GRIP"]
    assert grips
    assert all([t["block"] for t in o["support_targets"]] == [lower] for o in grips)
    assert min(map(option_cost, options)) == (1,0,1)


def test_blocked_gripper_and_partial_support_fall_back_to_manual_assembly(context):
    lower, upper = brick(), brick(7,6,2)
    context["grip_axes"] = ["x"]
    context["human_sides"] = ["+y"]
    current = [lower,brick(5,6,2),brick(9,6,2)]
    assert grip_options(upper,current,context) == []
    context["press_contact_model_confirmed"] = True
    options, info = mode_options(upper,current,context)
    assert info["largest_missing_component"] == 2
    assert options and all(o["mode"] == "HUMAN_ASSEMBLY" for o in options)


def test_full_support_press_is_possible_without_final_gripper_clearance(context):
    target = brick()
    surround = [brick(4,6),brick(8,6),brick(6,4),brick(6,8)]
    assert grip_options(target,surround,context) == []
    context["press_contact_model_confirmed"] = True
    options,_ = mode_options(target,surround,context)
    assert any(o["mode"] == "ROBOT_RELEASE_PRESS" for o in options)
    context["press_contact_model_confirmed"] = False
    options,_ = mode_options(target,surround,context)
    assert all(o["mode"] != "ROBOT_RELEASE_PRESS" for o in options)


def test_full_support_alone_does_not_override_press_obstacle(context):
    target = brick()
    context["press_contact_model_confirmed"] = True
    context["obstacles"] = [[60,60,14,70,70,50]]
    options,_ = mode_options(target,[],context)
    assert all(o["mode"] != "ROBOT_RELEASE_PRESS" for o in options)


def test_hand_needs_a_clear_corridor_and_reach(context):
    target = brick(layer=2)
    context["human_sides"] = ["+x"]
    assert hand_options(target,[],context)
    context["obstacles"] = [[100,50,10,110,80,30]]
    assert hand_options(target,[],context) == []
    context["obstacles"] = []
    context["geometry"]["hand_reach_mm"] = 1
    assert hand_options(target,[],context) == []


def test_two_support_hands_are_not_reused_as_a_third_assembly_hand(context):
    base = [brick(4,6,1,"2x3x1"),brick(8,6,1,"2x3x1")]
    lower = [brick(5,6,2,"2x3x1"),brick(7,6,2,"2x3x1")]
    upper = brick(6,6,3,"2x3x1")
    options,info = mode_options(upper,base+lower,context)
    assert len(info["weak_supports"]) == 2
    supported = [o for o in options if o["mode"] == "ROBOT_GRIP"]
    assert supported and all(len(o["support_targets"]) == 2 for o in supported)
    assert all(o["mode"] != "HUMAN_ASSEMBLY" for o in options)


def test_three_required_supports_cannot_be_silently_reduced_to_two(context):
    lower = [brick(5,6,2),brick(7,5,2),brick(7,7,2)]
    base = [brick(4,6,1),brick(8,5,1),brick(8,7,1)]
    upper = brick(6,6,3,"2x3x1",90)
    options,info = mode_options(upper,base+lower,context)
    assert len(info["weak_supports"]) == 3
    assert options == []


def brute_force_cost(blocks,context):
    best = None
    for order in permutations(blocks):
        placed, cost = [], (0,0,0)
        for b in order:
            options,_ = mode_options(b,placed,context)
            if not options:
                break
            step_cost = min(map(option_cost,options))
            cost = tuple(a+b for a,b in zip(cost,step_cost))
            placed.append(b)
        else:
            best = cost if best is None else min(best,cost)
    return best


def test_optimizer_matches_independent_exhaustive_permutation_reference(inputs):
    before = copy.deepcopy(inputs)
    result = plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    assert result["status"] == "CANDIDATE"
    assert result["optimization"]["cost"] == list(brute_force_cost(
        inputs["design"]["blocks"],inputs["assembly_context"])) == [0,0,0]
    assert result["execution_allowed"] is False
    # Existing far-to-near order forces at least one human assembly here.
    legacy = plan_from_current(inputs["design"],inputs["current"])["plan"]
    placed, legacy_requests = [], 0
    for step in legacy["steps"]:
        options,_ = mode_options(step["after"],placed,inputs["assembly_context"])
        assert options
        legacy_requests += min(option_cost(o)[0] for o in options)
        placed.append(step["after"])
    assert legacy_requests > result["optimization"]["cost"][0]
    assert inputs == before


def test_remaining_revision_preservation_and_empty_completion(inputs):
    current = {"current_revision":7,"blocks":[inputs["design"]["blocks"][0]]}
    result = plan_assembly_from_current(inputs["design"],current,inputs["assembly_context"])
    plan = result["planning_result"]["plan"]
    assert plan["base_current_revision"] == 7 and len(plan["steps"]) == 4
    assert all(s["after"] not in current["blocks"] for s in plan["steps"])
    current["blocks"] = inputs["design"]["blocks"]
    result = plan_assembly(inputs["design"],current,inputs["assembly_context"])
    assert result["planning_result"]["plan"]["steps"] == []
    assert result["execution_allowed"] is False


def test_current_conflict_support_failure_and_unknown_geometry(inputs):
    result = plan_assembly(inputs["design"],{"current_revision":1,"blocks":[brick(0,0)]},inputs["assembly_context"])
    assert result["status"] == "NEEDS_CORRECTION"
    bad = {"design_version":1,"blocks":[brick(),brick(7,7,2)]}
    assert plan_assembly(bad,inputs["current"],inputs["assembly_context"])["status"] == "INVALID"
    result = plan_assembly(inputs["design"],inputs["current"],None)
    assert result["status"] == "INPUTS_REQUIRED" and result["planning_result"] is None


@pytest.mark.parametrize("field,value",[("pitch_mm",float("nan")),("hand_width_mm",-1),
                                      ("grip_bottom_offset_mm",50),("release_raise_mm",.1)])
def test_invalid_dimensions_are_not_replaced_with_defaults(inputs,field,value):
    inputs["assembly_context"]["geometry"][field] = value
    result = plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    assert result["status"] == "INVALID_CONTEXT" and result["assembly_actions"] == []


def test_search_limit_does_not_claim_optimality_or_return_partial_plan(inputs):
    inputs["assembly_context"]["max_states"] = 1
    result = plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    assert result["status"] == "SEARCH_LIMIT"
    assert result["planning_result"] is None and result["optimization"]["optimal"] is False


def test_fully_inaccessible_workspace_has_no_feasible_order(inputs):
    inputs["assembly_context"]["obstacles"] = [[0,0,3,240,240,200]]
    result = plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    assert result["status"] == "NO_FEASIBLE_ORDER" and result["assembly_actions"] == []


def test_tampered_hand_assignment_and_revision_are_rejected(inputs):
    result = plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    plan = result["planning_result"]["plan"]
    actions = result["assembly_actions"]
    actions[0]["base_current_revision"] = 99
    with pytest.raises(ValueError,match="reference mismatch"):
        validate_candidate(inputs["design"],inputs["current"],inputs["assembly_context"],plan,actions)
    actions[0]["base_current_revision"] = 0
    actions[0]["grip_axis"] = "not-an-axis"
    with pytest.raises(ValueError,match="no longer feasible"):
        validate_candidate(inputs["design"],inputs["current"],inputs["assembly_context"],plan,actions)


def test_interleaved_order_is_an_explicit_opt_in_and_has_support_dependencies():
    a, b, u = brick(), brick(15,15), brick(layer=2)
    design = {"design_version":1,"blocks":[a,b,u]}
    with pytest.raises(ValueError):
        build_plan(design,[],0,ordered_blocks=[a,u,b])
    plan = build_plan(design,[],0,ordered_blocks=[a,u,b],finish_layers=False)
    assert plan["steps"][1]["prerequisites"] == ["S01"]


def test_unknown_current_is_not_an_empty_board(inputs):
    result = plan_assembly(inputs["design"],None,inputs["assembly_context"])
    assert result["status"] == "INVALID"


def test_next_step_uses_latest_current_and_does_not_require_original_revision(inputs):
    result = plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    plan = result["planning_result"]["plan"]
    current = {"current_revision":1,"blocks":[plan["steps"][0]["after"]]}
    old = assess_step(inputs["design"],plan,"S01",current,inputs["assembly_context"])
    assert old["status"] == "ALREADY_ASSEMBLED" and old["options"] == []
    next_step = assess_step(inputs["design"],plan,"S02",current,inputs["assembly_context"])
    assert next_step["status"] == "CANDIDATE" and next_step["assessment_current_revision"] == 1
    assert next_step["execution_allowed"] is False
    inputs["assembly_context"]["obstacles"] = [[0,0,3,240,240,200]]
    changed = assess_step(inputs["design"],plan,"S02",current,inputs["assembly_context"])
    assert changed["status"] == "NO_FEASIBLE_METHOD"


def test_ready_support_does_not_bypass_unconfirmed_predecessors(context):
    lower,upper = brick(),brick(layer=2)
    design = {"design_version":1,"blocks":[lower,upper]}
    plan = build_plan(design,[],0)
    result = assess_step(design,plan,"S02",{"current_revision":0,"blocks":[]},context)
    assert result["status"] == "WAIT_PREREQUISITES" and result["options"] == []


def test_action_metadata_survives_json_roundtrip_but_tampering_is_rejected(inputs):
    result = json.loads(json.dumps(plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])))
    plan,actions = result["planning_result"]["plan"],result["assembly_actions"]
    assert validate_candidate(inputs["design"],inputs["current"],inputs["assembly_context"],plan,actions) == [0,0,0]
    actions[0]["contacts"]["support_studs"] = 999
    with pytest.raises(ValueError,match="differs from reassessment"):
        validate_candidate(inputs["design"],inputs["current"],inputs["assembly_context"],plan,actions)


def test_board_collision_is_not_ignored_even_on_fully_supported_first_layer(context):
    context["geometry"]["grip_bottom_offset_mm"] = -1
    assert grip_options(brick(),[],context) == []


def all_rectangle_cases():
    shapes = [("2x2x1",0,2,2),("2x3x1",0,2,3),("2x3x1",90,3,2)]
    cases = []
    for uk,ua,uw,uh in shapes:
        for lk,la,lw,lh in shapes:
            for dx in range(1-uw,lw):
                for dy in range(1-uh,lh):
                    width = max(0,min(lw,dx+uw)-max(0,dx))
                    height = max(0,min(lh,dy+uh)-max(0,dy))
                    if width*height in (2,3):
                        cases.append((uk,ua,lk,la,dx,dy,width*height))
    return cases


@pytest.mark.parametrize("uk,ua,lk,la,dx,dy,expected",all_rectangle_cases())
def test_every_two_or_three_stud_single_pair_matches_rectangle_area(uk,ua,lk,la,dx,dy,expected):
    upper = brick(10+dx,10+dy,2,uk,ua)
    lower = brick(10,10,1,lk,la)
    info = contacts(upper,[lower])
    assert info["support_studs"] == expected
    assert info["largest_missing_component"] >= 2
    assert info["weak_supports"] == []


def test_unfilled_measurement_template_cannot_produce_a_plan(inputs):
    context = json.loads(Path(__file__).with_name("assembly_context.template.json").read_text())
    result = plan_assembly(inputs["design"],inputs["current"],context)
    assert result["status"] == "INPUTS_REQUIRED" and result["planning_result"] is None


def narrow_gap_inputs(context):
    """One stud row gap on both gripping sides; normal opening exceeds that gap."""
    context["grip_axes"] = ["x"]
    context["geometry"]["jaw_open_margin_mm"] = 8
    target = brick()
    neighbors = [brick(3,6),brick(9,6)]
    design = {"design_version":1,"blocks":neighbors+[target]}
    current = {"current_revision":2,"blocks":neighbors}
    return design,current,target


def test_one_stud_gap_requires_minimal_open_and_explicit_instruction(context):
    design,current,target = narrow_gap_inputs(context)
    result = plan_assembly(design,current,context)
    assert result["status"] == "CANDIDATE"
    action = result["assembly_actions"][0]
    assert action["mode"] == "ROBOT_GRIP"
    assert action["release_strategy"] == "MINIMAL_OPEN"
    assert action["requires_minimal_release"] is True
    assert action["release_margin_per_side_mm"] == 1
    assert action["release_instruction"] == "이 블록을 조립한 후에는 그리퍼를 소폭 개방하고 후퇴해야 합니다."
    assert result["execution_allowed"] is False
    assessment = assess_step(design,result["planning_result"]["plan"],"S01",current,context)
    grips = [o for o in assessment["options"] if o["mode"] == "ROBOT_GRIP"]
    assert grips and all(o["requires_minimal_release"] for o in grips)


def test_unconfirmed_minimal_open_is_not_assumed_feasible(context):
    _,current,target = narrow_gap_inputs(context)
    context["minimal_release_model_confirmed"] = False
    assert grip_options(target,current["blocks"],context) == []


def test_gap_smaller_than_finger_and_minimal_margin_rejects_both(context):
    _,current,target = narrow_gap_inputs(context)
    context["geometry"]["finger_thickness_mm"] = 11
    assert grip_options(target,current["blocks"],context) == []


def test_normal_open_is_preferred_when_both_are_feasible(context):
    result = plan_assembly({"design_version":1,"blocks":[brick()]},
                           {"current_revision":0,"blocks":[]},context)
    action = result["assembly_actions"][0]
    assert action["release_strategy"] == "NORMAL_OPEN"
    assert action["requires_minimal_release"] is False
    assert action["release_instruction"] is None


@pytest.mark.parametrize("field,value",[("requires_minimal_release",False),
                                       ("release_instruction",None),
                                       ("release_margin_per_side_mm",8),
                                       ("release_strategy","NORMAL_OPEN")])
def test_minimal_open_metadata_cannot_be_changed_without_revalidation(context,field,value):
    design,current,_ = narrow_gap_inputs(context)
    result = plan_assembly(design,current,context)
    result["assembly_actions"][0][field] = value
    with pytest.raises(ValueError):
        validate_candidate(design,current,context,result["planning_result"]["plan"],
                           result["assembly_actions"])


def test_minimal_margin_larger_than_normal_is_invalid(inputs):
    inputs["assembly_context"]["geometry"]["minimal_jaw_open_margin_mm"] = 3
    result = plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    assert result["status"] == "INVALID_CONTEXT"


def test_optimizer_can_interleave_supported_layers(context):
    lower, upper, floor = brick(), brick(layer=2), brick(15,15)
    neighbors = [brick(13,15),brick(17,15),brick(15,17)]
    current = {"current_revision":4,"blocks":[lower]+neighbors}
    design = {"design_version":1,"blocks":current["blocks"]+[floor,upper]}
    result = plan_assembly(design,current,context)
    assert result["status"] == "CANDIDATE"
    # The free upper placement costs zero, so it precedes the floor placement
    # requiring a human. Both orders reach the same goal and minimum total cost.
    assert [a["block"]["layer"] for a in result["assembly_actions"]] == [2,1]
    # The third cost now includes the person's manual-placement hand as well.
    assert result["optimization"]["cost"] == [1,1,1]
    context["finish_layers"] = True
    strict = plan_assembly(design,current,context)
    assert [a["block"]["layer"] for a in strict["assembly_actions"]] == [1,2]
    assert strict["optimization"]["cost"] == result["optimization"]["cost"]
