"""사용자 지정 2×2 회전 보정: 장치 연결 없이 공유 A/D 목표를 확인한다."""
from copy import deepcopy
from pathlib import Path
import os
import pytest
from app.cad_trial import measured_inputs,step_geometry,rotation_correction
from planning_trial.assembly_target import calculate_step_tcp

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),reason='C2_ROBOT_ROOT required')

@pytest.mark.parametrize('color',['yellow','blue'])
@pytest.mark.parametrize('axis',['x','y'])
@pytest.mark.parametrize('slot',[1,2,6])
def test_square_rotation_offsets_assembly_base_x_only(color,axis,slot):
    inputs=measured_inputs(ROOT)
    block=dict(brick_type='2x2x1',color=color,x=12,y=12,layer=1,orientation_deg=0)
    step=dict(step_id='S02',operation='PLACE',before=None,after=block,prerequisites=[],requires_delivery=True)
    action=dict(grip_axis=axis)
    nominal=calculate_step_tcp(step,profile=inputs['frame']['calculation_profiles']['assembly'],grip_axis=axis)
    turn=0 if axis=='x' else 90
    trial=nominal['trial_grid_reference_2x2_anchor'];assembly=inputs['frame']['calculation_profiles']['assembly']
    baseline=list(inputs['layers'][1]['sample']['posx'])
    for j in range(2):
        for name,k in [('x_coefficient',0),('y_coefficient',1)]:
            baseline[j]+=(trial[k]-inputs['layers'][1]['target'][('x','y')[k]])*assembly['coefficient_xyz_mm'][name][j]
    existing=rotation_correction(assembly,trial,turn=turn)
    frame,profile,_,correction=step_geometry(inputs,step,action,slot)
    settings=profile['steps']['cad/S02'];offset=-1.5 if turn else 0.
    assert correction==pytest.approx([existing[0]+offset,existing[1]])
    assert settings['reference_pose'][:2]==pytest.approx([baseline[0]+existing[0]+offset,baseline[1]+existing[1]])
    assert settings['reference_pose'][2:]==baseline[2:]
    assert settings['turn_base_z_deg']==turn
    other=deepcopy(inputs);other['frame']['calculation_profiles']['assembly']['reference']['grip_axis_planner']=axis
    _,unturned,_,_=step_geometry(other,step,action,slot)
    assert settings['pickup_pose']==unturned['steps']['cad/S02']['pickup_pose']
    a=calculate_step_tcp(step,profile=frame['calculation_profiles']['assembly'],grip_axis=axis)
    assert a['nominal_seated_tcp']['xyz_mm_zyz_deg'][:3]==settings['reference_pose'][:3]
