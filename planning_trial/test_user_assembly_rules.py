"""Latest user-rule behavior and independent contact geometry checks; no devices."""
import copy
from itertools import permutations
import json
from pathlib import Path

import pytest

from planning_trial.assembly_geometry import (
    convex_hull, contacts, grip_options, hand_options, human_press_assessment,
    point_in_hull, support_assignments,
)
from planning_trial.assembly_optimizer import mode_options, option_cost, plan_assembly, validate_candidate
from planning_trial.planner import occupied_cells, plan_from_current


def b(x=6,y=6,layer=1,kind="2x2x1",angle=0):
    return dict(brick_type=kind,color="yellow",x=x,y=y,layer=layer,orientation_deg=angle)


@pytest.fixture
def inputs():
    return json.loads(Path(__file__).with_name("sample_user_rules_inputs.json").read_text())


@pytest.fixture
def context(inputs):
    return inputs["assembly_context"]


def weak_chain():
    return [b(4,4,1,"2x3x1"),b(5,4,2,"2x3x1")], b(6,4,3,"2x3x1")


def mixed_access_case():
    current = [b(2,4,1,"2x3x1"),b(4,4,1,"2x3x1"),b(7,4,1,"2x3x1"),
               b(5,7,1,"2x3x1"),b(3,4,2,"2x3x1"),b(5,4,2,"2x3x1"),b(7,4,2,"2x3x1")]
    upper,side=b(6,4,3,"2x3x1"),b(5,7,2,"2x3x1")
    return {"design_version":1,"blocks":current+[side,upper]}, {"current_revision":7,"blocks":current}


def test_one_pitch_gap_and_unknown_numeric_open_do_not_block_calculation(context):
    target=b()
    neighbors=[b(3,6),b(9,6)]
    context["grip_axes"]=["x"]
    choices=grip_options(target,neighbors,context)
    assert choices and all(c["release_strategy"]=="MINIMAL_OPEN" for c in choices)
    assert all(c["release_margin_per_side_mm"] is None for c in choices)
    assert all(c["clearance_pitch_per_side"]==1 for c in choices)
    assert "minimal_jaw_open_margin_mm" not in context["geometry"]
    assert grip_options(target,[b(4,6),b(8,6)],context)==[]


@pytest.mark.parametrize("angle,axis",[(0,"x"),(90,"y")])
def test_two_by_three_only_grips_long_side_centres(context,angle,axis):
    choices=grip_options(b(kind="2x3x1",angle=angle),[],context)
    assert choices and {c["grip_axis"] for c in choices}=={axis}


def test_lower_layer_neighbors_do_not_block_eight_mm_tip(context):
    target=b(layer=2)
    lower=[b(4,6),b(6,6),b(8,6)]
    context["grip_axes"]=["x"]
    assert grip_options(target,lower,context)


def test_hold_contacts_are_nominal_without_side_space_checks(context):
    lower=b(layer=2)
    context["human_sides"]=["-x","+x"]
    choices=hand_options(lower,[],context)
    assert choices and all(c["boxes"] == [] for c in choices)
    assert len(choices[0]['contact_regions_board_mm']) == 2
    blocked_sides = hand_options(lower,[b(4,6,2)],context)
    assert blocked_sides == choices
    assert all(c['access_assessment'] == 'HUMAN_ACCESS_NOT_CHECKED' for c in choices)


def test_lower_hold_does_not_check_gripper_hand_space(context):
    current,target=weak_chain()
    weak=contacts(target,current)["weak_supports"]
    intrusive_box=(0,0,0,500,500,200)
    assert support_assignments(weak,target,current,context,[intrusive_box])
    context["hold_gripper_nonintrusion_assumption"]=False
    assignments = support_assignments(weak,target,current,context,[intrusive_box])
    assert assignments and all(a[0]['block'] == current[1] for a in assignments)
    assert all(a[0]['access_assessment'] == 'HUMAN_ACCESS_NOT_CHECKED' for a in assignments)


@pytest.mark.parametrize("points,point,inside",[
    ([(0,0),(1,0)],(.5,0),True), ([(0,0),(1,0)],(.5,.5),False),
    ([(0,0),(1,0),(0,1)],(.5,.5),True), ([(0,0),(1,0),(0,1)],(.8,.8),False),
    ([(1,1),(1,1)],(1,1),True), ([],(0,0),False),
])
def test_contact_hull_handles_line_boundary_and_non_rectangle(points,point,inside):
    assert point_in_hull(point,convex_hull(points)) is inside


def test_partial_board_supported_contact_requests_press_not_lower_hold(context):
    lower,upper=b(),b(7,6,2)
    options,info=mode_options(upper,[lower],context)
    grips=[o for o in options if o["mode"]=="ROBOT_GRIP"]
    assert info["press_assessment"]["required"]
    assert grips and all(o["assistance_kind"]=="PRESS" for o in grips)
    assert all(o["support_targets"]==[] and option_cost(o)==(1,0,1) for o in grips)
    assert all(o["press_hand"]["force_command"] is None for o in grips)


def test_press_and_hold_targets_different_blocks(context):
    current,upper=weak_chain()
    options,info=mode_options(upper,current,context)
    grips=[o for o in options if o["mode"]=="ROBOT_GRIP"]
    assert grips and info["support_studs"]==3
    chosen=grips[0]
    assert chosen["assistance_kind"]=="PRESS_AND_HOLD" and option_cost(chosen)==(1,0,2)
    assert [(h["action"],h["target_block"]) for h in chosen["human_actions"]]==[
        ("HOLD",current[1]),("PRESS",upper)]


def test_total_four_studs_does_not_erase_per_lower_hold(context):
    bases=[b(4,6),b(8,6)]
    lowers=[b(5,6,2),b(7,6,2)]
    upper=b(6,6,3)
    options,info=mode_options(upper,bases+lowers,context)
    assert info["support_studs"]==4 and len(info["weak_supports"])==2
    grips=[o for o in options if o["mode"]=="ROBOT_GRIP"]
    assert grips and all(o["assistance_kind"]=="HOLD" for o in grips)
    assert all(option_cost(o)==(1,0,2) for o in grips)


def test_press_plus_two_lower_holds_keeps_all_three_human_actions(context):
    bases=[b(4,5),b(4,7)]
    lowers=[b(5,5,2),b(5,7,2)]
    upper=b(6,6,3,"2x3x1")
    options,info=mode_options(upper,bases+lowers,context)
    assert info["support_studs"]==3 and len(info["weak_supports"])==2
    assert info["press_assessment"]["required"]
    assert options
    robot = [o for o in options if o['mode']=='ROBOT_GRIP']
    assert robot and all(o['assistance_kind']=='PRESS_AND_HOLD' for o in robot)
    assert all(len(o['human_actions'])==3 and len(o['support_targets'])==2 for o in robot)
    assert all(sum(a['action']=='PRESS' for a in o['human_actions'])==1 and
               sum(a['action']=='HOLD' for a in o['human_actions'])==2 for o in robot)


def test_human_press_space_is_not_checked_when_robot_grip_is_clear(context):
    lower,upper=b(),b(7,6,2)
    # Cover every one-pitch upper finger patch, but keep the side-body grip height free.
    context["obstacles"]=[[104,88,45,136,120,61]]
    options,info=mode_options(upper,[lower],context)
    assert info["press_assessment"]["required"]
    grips = [o for o in options if o['mode'] == 'ROBOT_GRIP']
    assert grips and all(o['assistance_kind'] == 'PRESS' for o in grips)
    assert all(o['press_hand']['access_assessment'] == 'HUMAN_ACCESS_NOT_CHECKED' for o in grips)


def test_manual_placement_counts_its_hand_and_keeps_lower_hold(context):
    current,upper=weak_chain()
    current += [b(8,4,1,"2x3x1"),b(8,4,2,"2x3x1"),b(4,4,3,"2x3x1"),b(8,4,3,"2x3x1")]
    options,info=mode_options(upper,current,context)
    assert info["support_studs"]==3 and options
    assert all(o["mode"]=="HUMAN_ASSEMBLY" and option_cost(o)==(1,1,2) for o in options)
    assert all(o["press_hand"] is None for o in options)  # same assembly hand places/presses


def test_release_press_remains_a_separate_zero_help_method_with_full_support(context):
    target=b(kind="2x3x1")
    neighbors=[b(4,6),b(8,6)]
    options,_=mode_options(target,neighbors,context)
    assert not any(o["mode"]=="ROBOT_RELEASE_PRESS" for o in options)
    context["press_contact_model_confirmed"]=True  # explicit TEST_ONLY contact assumption
    options,_=mode_options(target,neighbors,context)
    press=[o for o in options if o["mode"]=="ROBOT_RELEASE_PRESS"]
    assert press and all(option_cost(o)==(0,0,0) for o in press)
    assert all(o["press_hand"] is None for o in press)  # robot press is not human PRESS


@pytest.mark.parametrize("field,value",[("human_hands_used",1),("assistance_kind","HOLD"),
                                       ("needs_human_request",False)])
def test_combined_help_metadata_cannot_be_silently_reduced(context,field,value):
    current,upper=weak_chain()
    design={"design_version":1,"blocks":current+[upper]}
    cur={"current_revision":2,"blocks":current}
    result=plan_assembly(design,cur,context)
    result["assembly_actions"][0][field]=value
    with pytest.raises(ValueError):
        validate_candidate(design,cur,context,result["planning_result"]["plan"],result["assembly_actions"])


def test_stud_rules_missing_help_policy_does_not_silently_disable_press(context):
    del context["human_press_policy"]
    result=plan_assembly({"design_version":1,"blocks":[b()]},{"current_revision":0,"blocks":[]},context)
    assert result["status"]=="INPUTS_REQUIRED" and result["planning_result"] is None


def test_user_rules_optimizer_matches_all_six_permutations(inputs):
    best=None
    for order in permutations(inputs["design"]["blocks"]):
        current=[]; total=(0,0,0)
        for block in order:
            options,_=mode_options(block,current,inputs["assembly_context"])
            if not options: break
            cost=min(map(option_cost,options))
            total=tuple(a+b for a,b in zip(total,cost)); current.append(block)
        else:
            best=total if best is None else min(best,total)
    result=plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    assert result["status"]=="CANDIDATE" and result["optimization"]["cost"]==list(best)==[0,0,0]
    original=plan_from_current(inputs["design"],inputs["current"])["plan"]
    current=[]; baseline=(0,0,0)
    for step in original["steps"]:
        opts,_=mode_options(step["after"],current,inputs["assembly_context"])
        baseline=tuple(a+b for a,b in zip(baseline,min(map(option_cost,opts))))
        current.append(step["after"])
    assert baseline==(1,1,1)


def test_layer_completion_is_possible_after_excluding_human_access_space(context):
    design,current=mixed_access_case()
    result=plan_assembly(design,current,context)
    assert result["status"]=="CANDIDATE"
    assert [s["after"]["layer"] for s in result["planning_result"]["plan"]["steps"]]==[2,3]
    assert result["optimization"]["cost"]==[1,0,1]
    assert validate_candidate(design,current,context,result["planning_result"]["plan"],result["assembly_actions"])==[1,0,1]
    context["finish_layers"]=True
    strict = plan_assembly(design,current,context)
    assert strict['status'] == 'CANDIDATE'
    assert [a['block']['layer'] for a in strict['assembly_actions']] == [2,3]
    assert strict['optimization']['cost'] == [1,0,1]


def test_partial_current_and_tampered_press_are_replayed(inputs):
    current,upper=weak_chain()
    design={"design_version":2,"blocks":current+[upper]}
    cur={"current_revision":7,"blocks":current}
    before=copy.deepcopy((design,cur,inputs["assembly_context"]))
    result=plan_assembly(design,cur,inputs["assembly_context"])
    assert result["status"]=="CANDIDATE"
    plan=result["planning_result"]["plan"]
    assert len(plan["steps"])==1 and plan["base_current_revision"]==7
    assert (design,cur,inputs["assembly_context"])==before
    action=result["assembly_actions"][0]
    assert action["human_hands_used"]==2
    action["press_hand"]["contact_point_board_mm"][0]+=1
    with pytest.raises(ValueError):
        validate_candidate(design,cur,inputs["assembly_context"],plan,[action])


def test_one_stud_support_is_invalid_despite_available_human_hands(context):
    design={"design_version":1,"blocks":[b(),b(7,7,2)]}
    result=plan_assembly(design,{"current_revision":0,"blocks":[]},context)
    assert result["status"]=="INVALID" and result["assembly_actions"]==[]


def test_d_execution_permission_never_inferred_from_local_rule(inputs):
    result=plan_assembly(inputs["design"],inputs["current"],inputs["assembly_context"])
    assert result["execution_allowed"] is False and result["contract_status"]=="DRAFT_NOT_CONNECTED_TO_D"
    assert result["schema_version"]=="assembly-assistance-candidate/0.2"
    assert result["space_model"]=="STUD_RULES" and result["human_press_policy"]=="CONTACT_HULL"
