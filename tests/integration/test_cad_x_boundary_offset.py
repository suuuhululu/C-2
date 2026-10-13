"""Recorded S03/S04 and boundary correction; no device constructed."""
from copy import deepcopy
import json
import os
from pathlib import Path
import pytest
from app.cad_trial import measured_inputs,step_geometry
from app.assembly_board_calibration import board_target_pose
from planning_trial.assembly_target import calculate_step_tcp

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),reason='C2_ROBOT_ROOT required')


@pytest.mark.parametrize('x',[11,12,15])
@pytest.mark.parametrize('angle',[0,90])
@pytest.mark.parametrize('legacy',[False,True])
def test_six_point_region_offset_composes_once_with_rotation_and_preserves_pickup(x,angle,legacy):
    inputs=measured_inputs(ROOT)
    if legacy:inputs['board_calibration']=None
    original=deepcopy(inputs)
    b=dict(brick_type='2x3x1',color='blue',x=x,y=13,layer=1,orientation_deg=angle)
    step=dict(step_id='S03',operation='PLACE',before=None,after=b,prerequisites=[],requires_delivery=True)
    action=dict(grip_axis='x' if angle==0 else 'y')
    if legacy:
        expected=list(inputs['taught_assembly'][('blue',angle)])
        coeff=inputs['frame']['calculation_profiles']['assembly']['coefficient_xyz_mm']
        for j in range(2):expected[j]+=(x-11)*coeff['x_coefficient'][j]+2*coeff['y_coefficient'][j]
    else:expected=board_target_pose(inputs['board_calibration'],b,inputs['layers'])
    offset=(1.5 if angle==90 else 0.)+(-1. if x>11 else 0.)
    expected[0]+=offset
    frame,profile,_,correction=step_geometry(inputs,step,action,2)
    settings=profile['steps']['cad/S03']
    assert settings['reference_pose']==pytest.approx(expected)
    assert correction==[offset,0.]
    assert calculate_step_tcp(step,profile=frame['calculation_profiles']['assembly'],grip_axis=action['grip_axis'])['nominal_seated_tcp']['xyz_mm_zyz_deg']==pytest.approx(expected)
    assert step_geometry(inputs,step,action,2)[:2]==(frame,profile)
    assert inputs==original
    left=deepcopy(step);left['after']['x']=11
    _,unshifted,_,_=step_geometry(inputs,left,action,2)
    assert settings['pickup_pose']==unshifted['steps']['cad/S03']['pickup_pose']


@pytest.mark.parametrize('step_id',['S03','S04'])
def test_recorded_blue_six_point_targets_shift_minus_one_mm_only(step_id):
    records=json.loads((Path(__file__).resolve().parents[1]/'fixtures/robot_x_over_11_targets.json').read_text())['records']
    record=next(r for r in records if r['step_id']==step_id)
    step=dict(step_id=step_id,operation='PLACE',before=None,after=record['block'],prerequisites=[],requires_delivery=True)
    expected=record['previous_reference_pose'][:];expected[0]-=1.
    frame,profile,_,correction=step_geometry(measured_inputs(ROOT),step,dict(grip_axis='y'),2)
    assert profile['steps']['cad/'+step_id]['reference_pose']==pytest.approx(expected,abs=1e-9)
    assert correction==[.5,0.]
    assert frame['calculation_profiles']['assembly']['d_onsite_step']['reference_pose']==pytest.approx(expected)
