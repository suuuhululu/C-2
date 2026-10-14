"""Selected 1/3-stud axes must change the commanded plan, not only its label."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.vision_grasp_plan import grasp_geometry, plan_pick


SURFACE=dict(minimum_area=50,approx_fraction=.02,minimum_fill=.9,
             hsv_ranges={'yellow':[[[18,80,60],[40,255,255]]],
                         'blue':[[[95,80,25],[135,255,255]]],
                         'red':[[[0,80,40],[10,255,255]]]})


def inputs(kind='2x3x1',color='yellow',span=3):
    corners=[[40.,40.],[60.,40.],[60.,70.],[40.,70.]]
    obs=dict(status='CENTER_CANDIDATE',color=color,brick_type=kind,
             slot_id=f'{color}_{kind}_01',geometry={'corners_uv':corners})
    req=dict(color=color,brick_type=kind,slot_index=1,span_studs=span,height_mode='BASELINE')
    baseline={**req,'span_studs':2}
    geometry=grasp_geometry(obs,baseline,SURFACE)
    ref=dict(color=color,brick_type=kind,slot_index=1,center_uv=geometry['center_uv'],
             closing_midpoints_uv=geometry['closing_midpoints_uv'],
             nominal_tcp_mm_zyz_deg=[100.,200.,30.,0.,180.,0.],
             jacobian_base_xy_mm_per_pixel=[[1.,0.],[0.,1.]],
             reference_tcp_to_body_xy_mm=[0.,0.],new_tcp_to_body_xy_mm=[0.,0.],
             metric_basis='SYNTHETIC_CONTRACT_TEST')
    params=dict(open_width_mm=70.,close_width_mm=20.,gripper_force_n=30.,
                height_delta_mm=0.,approach_offset_mm=20.)
    return obs,req,ref,params


@pytest.mark.parametrize('kind,color,span',[('2x3x1','yellow',3),('1x2x1','red',1)])
def test_new_span_changes_actual_closing_axis_and_robot_rotation(kind,color,span):
    obs,req,ref,params=inputs(kind,color,span)
    result=plan_pick(obs,req,ref,params,SURFACE)
    assert result['status']=='VISION_GRASP_PLAN_FOR_REVIEW'
    assert abs(result['vision_yaw_delta_deg'])==pytest.approx(90.)
    old=Rotation.from_euler('ZYZ',ref['nominal_tcp_mm_zyz_deg'][3:],degrees=True)
    new=Rotation.from_euler('ZYZ',result['candidate_tcp_mm_zyz_deg'][3:],degrees=True)
    assert np.degrees((new*old.inv()).magnitude())==pytest.approx(90.)
    assert result['actions'][-1]==dict(kind='close',width_mm=20.,force_n=30.)
    assert result['execution_allowed'] is False


def test_vision_center_shift_reaches_robot_target():
    obs,req,ref,params=inputs();obs['geometry']['corners_uv']=(np.array(obs['geometry']['corners_uv'])+[4.,-2.]).tolist()
    result=plan_pick(obs,req,ref,params,SURFACE)
    assert result['candidate_tcp_mm_zyz_deg'][:3]==pytest.approx([104.,198.,30.])
    assert result['actions'][2]['pose_mm_zyz_deg'][:3]==pytest.approx([104.,198.,30.])


def test_pivot_compensation_is_applied_once():
    obs,req,ref,params=inputs();ref['reference_tcp_to_body_xy_mm']=[2.,1.];ref['new_tcp_to_body_xy_mm']=[-1.,4.]
    result=plan_pick(obs,req,ref,params,SURFACE)
    assert result['pivot_xy_compensation_mm']==pytest.approx([-2.,0.])
    assert result['candidate_tcp_mm_zyz_deg'][:2]==pytest.approx([98.,200.])


def test_raised_delta_changes_z_without_adding_tcp228():
    obs,req,ref,params=inputs();req['height_mode']='RAISED';params['height_delta_mm']=4.4
    result=plan_pick(obs,req,ref,params,SURFACE)
    assert result['candidate_tcp_mm_zyz_deg'][2]==pytest.approx(34.4)
    assert result['actions'][1]['pose_mm_zyz_deg'][2]==pytest.approx(54.4)


def test_new_profile_never_inherits_unknown_body_offset_as_zero():
    obs,req,ref,params=inputs();ref['new_tcp_to_body_xy_mm']=None
    result=plan_pick(obs,req,ref,params,SURFACE)
    assert result['status']=='BLOCKED' and result['actions'] is None
    assert 'new_tcp_to_body_xy_mm' in result['pending']


@pytest.mark.parametrize('change,reason',[
    ({'span_studs':3,'brick_type':'2x2x1'},'UNSUPPORTED_KIND_SPAN'),
    ({'slot_index':6},'RESERVED_SLOT_1_TO_5_REQUIRED'),
    ({'stop_requested':True},'STOP_OR_CANCELLED')])
def test_wrong_span_empty_slot_stop_rejected(change,reason):
    obs,req,ref,params=inputs();req.update(change)
    result=plan_pick(obs,req,ref,params,SURFACE)
    assert result['reason']==reason and result['actions'] is None


def test_model_ambiguity_never_creates_target():
    obs,req,ref,params=inputs();obs['status']='UNKNOWN'
    result=plan_pick(obs,req,ref,params,SURFACE)
    assert result['reason']=='UNIQUE_VISION_CENTER_REQUIRED' and result['actions'] is None


def test_vertical_and_landscape_rectangles_select_same_physical_span():
    obs,req,ref,params=inputs()
    a=grasp_geometry(obs,req,SURFACE)
    obs['geometry']['corners_uv']=[[40.,40.],[70.,40.],[70.,60.],[40.,60.]]
    b=grasp_geometry(obs,req,SURFACE)
    for geometry in (a,b):
        points=np.asarray(geometry['closing_midpoints_uv'])
        assert np.linalg.norm(points[1]-points[0])==pytest.approx(30.)
