"""Explicit TEST profile input through REAL preparation; no robot connection."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from app.cad_trial import load_release_press_profile,step_geometry
from app.cad_real_trial import live_robot_state
from app.mvp_real_trial import FullFeatureRealTrial,prepare_measured
from app.mvp_integration import MvpIntegration
from app.release_press_connection import d_motion

ROOT=Path(__file__).resolve().parents[2]
EXAMPLES=json.loads((ROOT/'planning_trial/fixtures/round2_strategy.examples.json').read_text())['examples']
MESSAGES=next(e['messages'] for e in EXAMPLES if e['case_id']=='release_press')


def entry():
    action=MESSAGES['reassessment_result']['action_proposal']
    return dict(block=deepcopy(action['block']),
        supply_slot=dict(color=action['block']['color'],brick_type=action['block']['brick_type'],slot_index=1),
        settings=dict(pickup_pose=[-300.,50.,50.,0.,180.,0.],reference_pose=[400.,80.,40.,0.,180.,0.],
            release_pose=[400.,80.,44.5,0.,180.,0.],press_start_pose=[401.,81.,61.,1.,179.,1.],
            press_approach_pose=[401.,81.,80.,1.,179.,1.],pickup_width_mm=35.,release_width_mm=62.,press_width_mm=4.),
        profile_settings=dict(force_stop_n=45.,target_only_motion=True,
                              round2_motion=dict(transfer_velocity=80.,vertical_velocity=6.)),
        measurement_refs=dict(release_pose='SYNTHETIC_TEST_NOT_REAL',press_start_pose='SYNTHETIC_TEST_NOT_REAL'))


def runtime(tmp_path,monkeypatch,record=None):
    def no_devices(self,robot_root,directory,**kwargs):self.received_settings=kwargs['runtime_settings']
    monkeypatch.setattr(MvpIntegration,'__init__',no_devices)
    path=None
    if record is not None:
        path=tmp_path/'explicit-profile.json'
        path.write_text(json.dumps(dict(profile_id='SYNTHETIC_TEST_NOT_REAL',
            calibration_refs=dict(tcp='TEST_TCP_SOURCE',tool='TEST_TOOL_SOURCE'),entries=[record])))
    return FullFeatureRealTrial(ROOT/'robot_control_integration',tmp_path,release_press_profile=path),path


def receipt(status=0,context=None):
    sample=dict(tcp='GripperDA_v4',tool='ToolWeight0',posx=[400.,-180.,200.,0.,180.,0.],velx=[0.]*6,
                query_duration_s=0.,gripper_width_mm=9.2 if status==2 else 62.,gripper_status=status,
                robot_state=1,robot_mode=1,drl_state=3,motion_status=0)
    value=dict(samples=[deepcopy(sample) for _ in range(3)],captured_unix_s=time.time(),physical_commands=0)
    if context is not None:value['last_step_gripper_context']=deepcopy(context)
    return value


def prepare(runtime,read=None):
    messages=deepcopy(MESSAGES);action=messages['reassessment_result']['action_proposal']
    whole=messages['whole_result']
    index=next(i for i,a in enumerate(whole['action_proposals']) if a['step_id']==action['step_id'])
    workflow=SimpleNamespace(whole_result=whole,completed=[{}]*index,settings=runtime.received_settings,
                             epoch='SYNTHETIC_TEST_ONLY',generation=7)
    payload=dict(step=messages['motion_request']['selected_step'],current=messages['reassessment_request']['latest_current'],generation=7)
    out=prepare_measured(workflow,runtime.inputs,payload,1,read or receipt(),'TEST_STATE','TEST_OPERATOR_REVIEW')
    request=messages['motion_request'];request['reserved_supply_slot']=out['slot']
    return out,d_motion(request,out['d_profile'])


def test_file_to_real_preparation_preserves_explicit_geometry_and_parameters(tmp_path,monkeypatch):
    record=entry();r,path=runtime(tmp_path,monkeypatch,record)
    before=deepcopy(r.inputs);out,candidate=prepare(r)
    settings=next(iter(out['d_profile']['steps'].values()))
    assert candidate['status']=='CANDIDATE' and not candidate['execution_allowed']
    for name,value in record['settings'].items():assert settings[name]==value
    assert settings['assembly_tcp_zyz_deg']==record['settings']['reference_pose'][3:]
    p=out['d_profile']
    assert p['force_stop_n']==45. and p['target_only_motion'] is True
    assert p['transfer_velocity']==80. and p['descent_velocity']==p['pickup_descent_velocity']==6.
    assert p['release_press_profile_ref']['path']==str(path.resolve())
    assert p['release_press_profile_ref']['measurement_refs']==record['measurement_refs']
    assert p['release_press_profile_ref']['calibration_refs']==dict(tcp='TEST_TCP_SOURCE',tool='TEST_TOOL_SOURCE')
    assert 'native_press' not in p and r.inputs==before


@pytest.mark.parametrize('field',['brick_type','color','x','y','layer','orientation_deg','slot_index'])
def test_profile_requires_exact_block_and_supply_identity(tmp_path,monkeypatch,field):
    record=entry()
    if field=='slot_index':record['supply_slot'][field]=2
    elif field=='brick_type':record['block'][field]='1x2x1'
    elif field=='color':record['block'][field]='red'
    elif field=='orientation_deg':record['block'][field]=90-record['block'][field]
    else:record['block'][field]+=1
    r,_=runtime(tmp_path,monkeypatch,record);out,candidate=prepare(r)
    assert candidate['status']=='INPUTS_REQUIRED'
    assert 'release_pose' not in next(iter(out['d_profile']['steps'].values()))
    assert 'release_press_profile_ref' not in out['d_profile']


def test_unset_release_height_is_not_generated_from_seated_or_pad_pose(tmp_path,monkeypatch):
    record=entry();record['settings'].pop('release_pose')
    r,_=runtime(tmp_path,monkeypatch,record);out,candidate=prepare(r)
    assert candidate['status']=='INPUTS_REQUIRED'
    assert 'release_pose' in candidate['errors'][0]['reason']
    assert 'release_pose' not in next(iter(out['d_profile']['steps'].values()))


def test_no_file_keeps_legacy_profile_and_release_press_inputs_required(tmp_path,monkeypatch):
    r,_=runtime(tmp_path,monkeypatch);out,candidate=prepare(r)
    assert r.inputs['release_press_profile'] is None and candidate['status']=='INPUTS_REQUIRED'
    assert out['d_profile']['force_stop_n']==40. and 'target_only_motion' not in out['d_profile']


def test_unknown_fields_cannot_replace_routes_or_review_flags(tmp_path,monkeypatch):
    record=entry();record['settings']['physical_reference_reviewed']='UNTRUSTED_FILE_FLAG'
    record['profile_settings'].update(clearance_z_mm=-999.,body_bypass_xy_mm=[999.,999.],physical_route_reviewed='UNTRUSTED')
    r,_=runtime(tmp_path,monkeypatch,record);out,_=prepare(r)
    assert out['d_profile']['clearance_z_mm']==r.inputs['profile']['clearance_z_mm']
    assert out['d_profile']['body_bypass_xy_mm']==r.inputs['profile']['body_bypass_xy_mm']
    assert out['d_profile']['physical_route_reviewed'] is True
    assert next(iter(out['d_profile']['steps'].values()))['physical_reference_reviewed'] is True


def test_non_release_press_action_does_not_consume_optional_profile(tmp_path,monkeypatch):
    r,_=runtime(tmp_path,monkeypatch,entry());request=MESSAGES['motion_request']
    action=deepcopy(request['assessed_action']);action.pop('assembly_strategy')
    frame,p,_,_=step_geometry(r.inputs,request['selected_step'],action,1)
    assert 'release_press_profile_ref' not in p
    assert 'release_pose' not in next(iter(p['steps'].values()))
    assert p['force_stop_n']==40.


@pytest.mark.parametrize('context',[None,dict(state='HELD_BLOCK',gripper_status=2),dict(state='EMPTY_PAD_CLOSED',gripper_status=0)])
def test_default_or_nonmatching_context_does_not_relabel_a_held_gripper(tmp_path,monkeypatch,context):
    r,_=runtime(tmp_path,monkeypatch)
    value=receipt(2,context)
    with pytest.raises(ValueError,match='OPEN_EMPTY_GRIPPER_REQUIRED'):
        live_robot_state(value,r.received_settings['frame_profile'],empty_gripper_context=context)


def test_closed_empty_pad_context_is_preserved_through_next_preparation(tmp_path,monkeypatch):
    r,_=runtime(tmp_path,monkeypatch,entry())
    value=receipt(2,dict(state='EMPTY_PAD_CLOSED',gripper_status=2));before=deepcopy(value)
    out,candidate=prepare(r,value)
    assert candidate['status']=='CANDIDATE' and out['robot_state']['holding_confirmed'] is False
    assert value==before and all(s['gripper_status']==2 for s in value['samples'])
