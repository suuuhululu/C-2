"""Calibration reproduction, nominal extensions, grip-depth edges and waypoint holds."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from planning_trial.assembly_target import (
    HANDOFF,calculate_step_tcp,calculate_step_waypoints,load_assembly_target_profile,
    quaternion_xyzw_from_zyz,trial_nominal_tcp,
)
from planning_trial.assembly_geometry import validate_context,grip_options
from planning_trial.supply_pick import calculate_supply_pick
from planning_trial.planner import build_plan


def step(x=6,y=6,layer=1,kind='2x2x1',angle=0):
    return {'step_id':'S01','operation':'PLACE','before':None,'after':{
        'brick_type':kind,'color':'blue','x':x,'y':y,'layer':layer,'orientation_deg':angle},
        'prerequisites':[],'requires_delivery':True}


@pytest.fixture
def ctx():
    return json.loads(Path(__file__).with_name('sample_user_rules_5mm_measured_rev2_inputs.json').read_text())['assembly_context']


@pytest.mark.parametrize('grid',[(0,0),(0,22),(22,0),(22,22)])
def test_nominal_reproduces_four_taught_tcp_corners_without_centre_or_flange_addition(grid):
    raw=json.loads((HANDOFF/'data/points.json').read_text())
    expected=next(p for p in raw['points'] if p['grid']==list(grid))['sample']['posx'][:3]
    assert trial_nominal_tcp(*grid)==pytest.approx(expected)
    # Planner and trial axis labels are explicitly swapped.
    result=calculate_step_tcp(step(x=grid[1],y=grid[0]))
    assert result['trial_grid_reference_2x2_anchor']==list(grid)
    assert result['nominal_seated_tcp']['xyz_mm_zyz_deg'][:3]==pytest.approx(expected)


@pytest.mark.parametrize('index',range(4))
def test_four_executed_minus2_targets_and_wire_quaternion_are_reproduced(index):
    expected=json.loads((HANDOFF/'generated/sim_targets.json').read_text())['targets'][index]
    tx,ty=expected['grid'];result=calculate_step_tcp(step(x=ty,y=tx))
    assert result['D_contact_minus2mm_trial_candidate']['xyz_mm_zyz_deg']==pytest.approx(expected['target_base_posx_mm_zyz_deg'])
    w,x,y,z=expected['target_base_quaternion_wxyz']
    assert result['nominal_seated_tcp']['quaternion_xyzw']==pytest.approx([x,y,z,w])
    assert result['pre_contact_tcp']['xyz_mm_zyz_deg'][2]-result['nominal_seated_tcp']['xyz_mm_zyz_deg'][2]==pytest.approx(24.5)
    # The -2 Contact experiment is not baked into the pre-contact movement.
    assert result['pre_contact_tcp']['xyz_mm_zyz_deg'][2]-expected['target_base_posx_mm_zyz_deg'][2]==pytest.approx(26.5)


def test_fifth_point_is_independent_residual_not_forced_into_corner_fit():
    raw=json.loads((HANDOFF/'data/points.json').read_text())
    measured=next(p for p in raw['points'] if p['grid']==[11,11])['sample']['posx'][:3]
    predicted=trial_nominal_tcp(11,11)
    assert math.dist(predicted,measured)==pytest.approx(.8708635938150311)


@pytest.mark.parametrize('grid',[(-1,0),(0,23),(float('nan'),0),(True,0)])
def test_reference_calibration_rejects_extrapolation_and_ambiguous_index(grid):
    with pytest.raises(ValueError):trial_nominal_tcp(*grid)


@pytest.mark.parametrize('angle,trial,axis',[(0,[5.5,5],'x'),(90,[5,5.5],'y')])
def test_two_by_three_uses_half_cell_centre_shift_and_long_face_grip(angle,trial,axis):
    result=calculate_step_tcp(step(x=5,y=5,layer=2,kind='2x3x1',angle=angle))
    assert result['trial_grid_reference_2x2_anchor']==trial
    assert result['grip_axis_planner']==axis
    assert result['scope']=='NOMINAL_GEOMETRIC_EXTENSION'
    assert result['execution_allowed'] is False
    assert result['nominal_seated_tcp']['xyz_mm_zyz_deg'][2]==pytest.approx(trial_nominal_tcp(*trial)[2]+19)


def test_world_z_grip_rotation_is_not_a_rotation_matrix_from_swapped_grid_labels():
    scipy=pytest.importorskip('scipy.spatial.transform')
    p=load_assembly_target_profile();abc=p['reference']['tcp_zyz_deg']
    r=calculate_step_tcp(step(),profile=p,grip_axis='y')
    expected=(scipy.Rotation.from_euler('z',90,degrees=True)*scipy.Rotation.from_euler('ZYZ',abc,degrees=True)).as_matrix()
    actual=scipy.Rotation.from_quat(r['nominal_seated_tcp']['quaternion_xyzw']).as_matrix()
    assert actual==pytest.approx(expected)


def test_explicitly_disabling_uncalibrated_extension_returns_no_pose():
    p=load_assembly_target_profile();p['extensions']['allow_nominal_sizes_layers_and_grip_rotation']=False
    r=calculate_step_tcp(step(layer=2),profile=p)
    assert r['status']=='INPUTS_REQUIRED' and 'nominal_seated_tcp' not in r


def test_grid_reflection_maps_footprint_centres_not_minimum_corner_naively():
    p=load_assembly_target_profile();p['grid_mapping']['planner_to_trial_xy']=[[-1,0],[0,1]];p['grid_mapping']['offset_trial_xy']=[23,0]
    r=calculate_step_tcp(step(x=0,y=0),profile=p)
    assert r['trial_grid_reference_2x2_anchor']==[22,0]


def test_geometry_or_grid_change_gets_new_profile_fingerprint_and_no_input_mutation():
    p=load_assembly_target_profile();saved=deepcopy(p)
    a=calculate_step_tcp(step(),profile=p);assert p==saved
    p['geometry']['body_height_mm']=21
    b=calculate_step_tcp(step(),profile=p)
    assert a['profile_id']!=b['profile_id']


def test_five_mm_grip_boundary_is_nominal_tangency_not_positive_clearance(ctx):
    # Historical 5mm stud vs 5mm grip remains a supported explicit test input.
    ctx['geometry']['stud_height_mm']=5
    validate_context(ctx)
    lower=[step(x=x)['after'] for x in (4,6,8)]
    assert grip_options(step(layer=2)['after'],lower,ctx)
    ctx['geometry']['grip_bottom_offset_mm']=4.9
    with pytest.raises(ValueError):validate_context(ctx)


def test_empty_current_route_holds_block_and_has_no_speed_or_execution_approval(ctx):
    pick=calculate_supply_pick('2x2x1','blue',1)
    r=calculate_step_waypoints(step(),{'current_revision':0,'blocks':[]},pick,ctx)
    assert r['status']=='WAYPOINT_CANDIDATE'
    assert [w['label'] for w in r['waypoints']]==['LIFT_HOLDING','TRANSIT_ABOVE_TARGET','PRE_CONTACT_HOLDING']
    assert r['waypoints'][0]['pose']['xyz_mm_zyz_deg'][:2]==pick['pickup_tcp_pose']['xyz_abc'][:2]
    assert r['waypoints'][-1]['pose']==r['target']['pre_contact_tcp']
    assert r['terminal_gripper_policy']=='HOLD_NO_AUTOMATIC_OPEN'
    assert r['execution_allowed'] is r['assembly_completed'] is r['full_robot_collision_checked'] is False
    assert r['speed_profile'] is None


def test_tall_current_increases_transport_above_recorded_trial_height(ctx):
    p=load_assembly_target_profile();current={'current_revision':7,'blocks':[step(x=10,y=10,layer=i)['after'] for i in range(1,5)]}
    pick=calculate_supply_pick('2x2x1','blue',1)
    r=calculate_step_waypoints(step(),current,pick,ctx,profile=p)
    assert r['status']=='WAYPOINT_CANDIDATE' and r['motion_current_revision']==7
    assert r['travel_tcp_z_mm']>p['recorded_transfer_height_candidate_mm']
    assert r['travel_tcp_z_mm']>=r['nominal_structure_envelope_tcp_z_mm']


def test_blocked_grip_and_already_assembled_never_publish_waypoints(ctx):
    pick=calculate_supply_pick('2x2x1','blue',1)
    blocked={'current_revision':2,'blocks':[step(x=x)['after'] for x in (4,8)]}
    assert calculate_step_waypoints(step(),blocked,pick,ctx,grip_axis='x')['status']=='BLOCKED'
    complete={'current_revision':3,'blocks':[step()['after']]}
    r=calculate_step_waypoints(step(),complete,pick,ctx)
    assert r['status']=='ALREADY_ASSEMBLED' and r['waypoints']==[]


def test_missing_below_support_does_not_get_motion_candidate(ctx):
    r=calculate_step_waypoints(step(layer=2),{'current_revision':0,'blocks':[]},calculate_supply_pick('2x2x1','blue',1),ctx)
    assert r['status']=='BLOCKED' and r['waypoints']==[]


def test_pick_depth_and_part_must_match_selected_step(ctx):
    pick=calculate_supply_pick('2x2x1','blue',1)
    pick['grasp']['pad_bottom_above_block_bottom_mm']=8
    with pytest.raises(ValueError):calculate_step_waypoints(step(),{'current_revision':0,'blocks':[]},pick,ctx)
    with pytest.raises(ValueError):calculate_step_waypoints(step(),{'current_revision':0,'blocks':[]},calculate_supply_pick('2x2x1','yellow',1),ctx)


def test_prerequisites_require_plan_and_observed_positions_before_waypoint(ctx):
    below=step()['after'];above=step(layer=2)['after']
    plan=build_plan({'design_version':1,'blocks':[below,above]},[],0,finish_layers=False)
    selected=plan['steps'][1];pick=calculate_supply_pick('2x2x1','blue',1)
    assert calculate_step_waypoints(selected,{'current_revision':0,'blocks':[]},pick,ctx)['status']=='BLOCKED'
    assert calculate_step_waypoints(selected,{'current_revision':0,'blocks':[]},pick,ctx,plan=plan)['status']=='WAIT_PREREQUISITES'
    assert calculate_step_waypoints(selected,{'current_revision':1,'blocks':[below]},pick,ctx,plan=plan)['status']=='WAYPOINT_CANDIDATE'
