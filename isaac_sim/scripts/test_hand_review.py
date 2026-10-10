"""Check candidate hand geometry independently from whole-plan success."""
import sys,json
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from planning_trial.assembly_geometry import hand_options,manual_approach_top_options,body_box,paired_hand_options
from planning_trial.assembly_adapter import handle_whole_plan
REQ=json.loads((ROOT/'config/whole.hand_review.request.json').read_text())
TARGET={'brick_type':'2x3x1','color':'yellow','x':4,'y':4,'layer':2,'orientation_deg':90}
CURRENT=[b for b in REQ['design']['blocks'] if b!=TARGET]
CTX=REQ['assembly_context']
def test_old_seated_rule_blocks_but_review_has_geometric_regions():
    old=deepcopy(CTX);old.pop('human_assembly_model')
    assert not hand_options(TARGET,CURRENT,old,assembly=True)
    result=hand_options(TARGET,CURRENT,CTX,assembly=True)
    assert result and all(h['boxes'] and h['contact_regions_board_mm'] for h in result)
    assert all(not h['continuous_hand_transition_verified'] and not h['physical_insertion_verified'] for h in result)
def test_hold_geometry_remains_identical():
    old=deepcopy(CTX);old.pop('human_assembly_model')
    assert hand_options(TARGET,CURRENT,old,assembly=False)==hand_options(TARGET,CURRENT,CTX,assembly=False)
    assert not hand_options(TARGET,CURRENT,CTX,assembly=False)
def test_top_obstacle_rejects_new_candidate():
    context=deepcopy(CTX);b=body_box(TARGET,context);cx=(b[0]+b[3])/2;cy=(b[1]+b[4])/2
    context['obstacles']=[[cx-3,cy-3,100,cx+3,cy+3,110]]
    assert not manual_approach_top_options(TARGET,CURRENT,context)
def test_target_vertical_corridor_obstacle_rejects_candidate():
    context=deepcopy(CTX);b=body_box(TARGET,context);cx=(b[0]+b[3])/2;cy=(b[1]+b[4])/2
    context['obstacles']=[[cx-2,cy-2,b[2]+2,cx+2,cy+2,b[2]+8]]
    assert not manual_approach_top_options(TARGET,CURRENT,context)
def test_both_side_approaches_blocked_rejects_candidate():
    context=deepcopy(CTX);b=body_box(TARGET,context);cx=(b[0]+b[3])/2;cy=(b[1]+b[4])/2;z=b[2]+24.5
    context['obstacles']=[[b[0]-10,cy-2,z,b[0]-2,cy+2,z+19],[cx-2,b[1]-10,z,cx+2,b[1]-2,z+19]]
    assert not manual_approach_top_options(TARGET,CURRENT,context)
def test_no_forced_human_or_unsupported_robot_method():
    req=deepcopy(REQ);req['assembly_context']['supported_modes']=['ROBOT_GRIP']
    assert handle_whole_plan(req)['calculation_status']=='NO_FEASIBLE_ORDER'
def test_original_default_still_blocked_and_review_is_candidate_only():
    req=deepcopy(REQ);req['assembly_context'].pop('human_assembly_model')
    assert handle_whole_plan(req)['calculation_status']=='NO_FEASIBLE_ORDER'
    result=handle_whole_plan(REQ)
    assert result['calculation_status']=='COMPLETED' and not result['execution_allowed']
    assert len(result['planning_result']['plan']['steps'])==12
    modes=[a['mode'] for a in result['action_proposals']]
    assert modes.count('ROBOT_GRIP')==10 and modes.count('HUMAN_ASSEMBLY')==2
    assert 'ROBOT_RELEASE_PRESS' not in modes
