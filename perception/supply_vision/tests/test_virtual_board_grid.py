import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from supply_vision.virtual_board_grid import project_base,pose_matrix,static_transform,VirtualBoardGrid,parallel_axes_at_pixel

ROOT=Path(__file__).resolve().parents[3]


def test_projection_accounts_for_camera_pose_and_points_behind_camera():
    camera=np.eye(4);camera[:3,3]=[10,20,0]
    k=[100,0,320,0,100,240,0,0,1]
    pixels,valid=project_base([[10,20,100],[20,20,100],[10,20,-10]],camera,k,[])
    assert pixels[:2]==pytest.approx(np.array([[320,240],[330,240]]))
    assert valid.tolist()==[True,True,False]
    assert np.isnan(pixels[2]).all()


def test_static_tf_multidocument_path_preserves_mm_units(tmp_path):
    path=tmp_path/'tf.yaml'
    path.write_text('transforms:\n- header: {frame_id: a}\n  child_frame_id: b\n  transform: {translation: {x: 0.01, y: 0, z: 0}, rotation: {x: 0, y: 0, z: 0, w: 1}}\n---\ntransforms:\n- header: {frame_id: b}\n  child_frame_id: c\n  transform: {translation: {x: 0, y: 0.02, z: 0}, rotation: {x: 0, y: 0, z: 0, w: 1}}\n')
    assert static_transform(path,'a','c')[:3,3]==pytest.approx([10,20,0])
    assert static_transform(path,'c','a')[:3,3]==pytest.approx([-10,-20,0])


def model():
    c=json.loads((ROOT/'robot_control_integration/settings/held_corner_stud_20261014/config.json').read_text())
    return VirtualBoardGrid(c['virtual_grid'])


def test_missing_or_wrong_camera_info_returns_no_authority():
    m=model();frame=np.zeros((480,640,3),np.uint8)
    out,report=m.overlay(frame,dict(posx=[0,0,0,0,0,0]),None)
    assert report['status']=='UNKNOWN' and not report['execution_allowed']
    info=SimpleNamespace(width=320,height=240,header=SimpleNamespace(frame_id='wrong'))
    _,report=m.overlay(frame,dict(posx=[0,0,0,0,0,0]),info)
    assert report['reason']=='CAMERA_INFO_SIZE_OR_FRAME_MISMATCH'


def test_layers_and_hover_outline_use_distinct_height_planes():
    m=model();frame=np.zeros((480,640,3),np.uint8)
    info=SimpleNamespace(width=640,height=480,header=SimpleNamespace(frame_id='camera_color_optical_frame'),
        distortion_model='plumb_bob',k=[600,0,320,0,600,240,0,0,1],d=[0.]*5)
    sample=dict(posx=[472,85,194,102,-176,104])
    _,one=m.overlay(frame,sample,info,1,20.)
    _,two=m.overlay(frame,sample,info,2,20.)
    assert one['hover_body_top_offset_mm']-one['body_top_offset_mm']==20.
    assert two['support_plane_offset_mm']>one['support_plane_offset_mm']
    assert len(one['grid_segments_uv'])>0
    assert one['target_hover_outline_uv']!=one['target_seated_outline_uv']
    assert not one['projection_independently_verified'] and one['robot_correction'] is None


@pytest.mark.parametrize('height',[0.,19.6,39.2,58.8,78.4])
def test_parallel_direction_at_actual_edge_does_not_need_stud_center(height):
    from scipy.spatial.transform import Rotation
    camera=np.eye(4);board=np.eye(4)
    board[:3,:3]=Rotation.from_euler('xy',[20.,15.],degrees=True).as_matrix()
    board[:3,3]=[10.,30.,250.]
    k=[500.,0.,320.,0.,500.,240.,0.,0.,1.]
    # The edge is deliberately shifted from the stud grid in both XY axes.
    local=np.array([[53.7,41.3,height],[85.7,41.3,height]])
    base=(board@np.column_stack((local,np.ones(2))).T).T[:,:3]
    edge,valid=project_base(base,camera,k,[])
    assert valid.all()
    axes,segments=parallel_axes_at_pixel(edge.mean(axis=0),camera,board,k,[],height,16.)
    vector=edge[1]-edge[0]
    actual=float(np.degrees(np.arctan2(vector[1],vector[0]))%180)
    assert (axes[0]-actual+90)%180-90==pytest.approx(0.,abs=1e-8)
    assert len(segments)==2


def test_grid_report_uses_only_direction_even_when_edge_is_offset():
    m=model();frame=np.zeros((480,640,3),np.uint8)
    info=SimpleNamespace(width=640,height=480,header=SimpleNamespace(frame_id='camera_color_optical_frame'),
        distortion_model='plumb_bob',k=[600,0,320,0,600,240,0,0,1],d=[0.]*5)
    _,report=m.overlay(frame,dict(posx=[472,85,194,102,-176,104]),info,1,20.,
        edges=[[[290.,360.],[340.,361.]]])
    assert report['relative_angle_deg'] is not None
    assert report['comparison_scope']=='YAW_DIRECTION_ONLY'
    assert not report['stud_center_coincidence_required']
    assert not report['roll_pitch_observed']
    assert not report['projection_independently_verified']


def test_layer4_uses_adopted_record_and_preserves_historical_rows():
    from copy import deepcopy
    from supply_vision.virtual_board_grid import layer_reference
    m=model();before=deepcopy(m.layer_records)
    target=dict(brick_type='2x2x1',color='yellow',x=11,y=11,layer=4,orientation_deg=0)
    assert layer_reference(m.layer_records,target)['sample']['posx'][2]==pytest.approx(71.60824584960938)
    assert m.layer_records==before


def display_fixture():
    """Synthetic camera looks along board +Z; pixel positions have an analytic oracle."""
    m=model();m.T_base_board=np.eye(4);m.T_tool_camera=np.eye(4);m.T_tool_tcp=np.eye(4)
    frame=np.zeros((480,640,3),np.uint8)
    info=SimpleNamespace(width=640,height=480,header=SimpleNamespace(frame_id='camera_color_optical_frame'),
        distortion_model='plumb_bob',k=[500.,0.,320.,0.,500.,240.,0.,0.,1.],d=[0.]*5)
    sample=dict(posx=[0.,0.,-1000.,0.,0.,0.])
    return m,frame,info,sample


@pytest.mark.parametrize('color,kind,x,y,orientation,center,extent,footprint',[
    ('yellow','2x2x1',3,5,0,[56.,88.],[31.8,31.8],[2,2]),
    ('blue','2x3x1',4,9,0,[72.,160.],[31.8,47.9],[2,3]),
    ('yellow','2x3x1',11,9,0,[184.,160.],[31.8,47.9],[2,3]),
    ('blue','2x3x1',4,9,90,[80.,152.],[47.9,31.8],[3,2]),
    ('red','1x2x1',4,9,0,[64.,152.],[15.6,31.8],[1,2]),
])
def test_common_block_projects_its_occupied_stud_center_and_measured_rectangle(color,kind,x,y,orientation,center,extent,footprint):
    from copy import deepcopy
    m,frame,info,sample=display_fixture()
    target=dict(color=color,brick_type=kind,x=x,y=y,layer=1,orientation_deg=orientation)
    before=deepcopy((target,m.layer_records))
    _,report=m.overlay(frame,sample,info,target=target)
    assert report['target']==target and report['target_footprint_studs']==footprint
    assert report['target_center_board_mm']==pytest.approx(center)
    assert report['target_outer_extent_mm']==pytest.approx(extent)
    # Pinhole projection in the synthetic camera, independently of project_base().
    signs=np.array([[-1.,-1.],[1.,-1.],[1.,1.],[-1.,1.]])
    corners=np.asarray(center)+signs*np.asarray(extent)/2
    depth=1000.+report['hover_body_top_offset_mm']
    expected=corners*500./depth+[320.,240.]
    assert np.asarray(report['target_hover_outline_uv'])==pytest.approx(expected)
    assert not report['execution_allowed'] and not report['projection_independently_verified']
    assert (target,m.layer_records)==before


@pytest.mark.parametrize('orientation',[0,90])
@pytest.mark.parametrize('layer',[2,4,5])
def test_rectangular_target_layer_uses_existing_yellow_square_height_anchor(orientation,layer):
    m,frame,info,sample=display_fixture()
    target=dict(color='blue',brick_type='2x3x1',x=4,y=9,layer=layer,orientation_deg=orientation)
    _,legacy=m.overlay(frame,sample,info,layer)
    # The explicit common block is authoritative, including its layer.
    _,actual=m.overlay(frame,sample,info,target=target)
    assert actual['target']==target
    assert actual['layer_height_reference_target']==dict(
        color='yellow',brick_type='2x2x1',x=11,y=11,layer=layer,orientation_deg=0)
    assert actual['support_plane_offset_mm']==legacy['support_plane_offset_mm']
    assert actual['body_top_offset_mm']==legacy['body_top_offset_mm']
    assert actual['hover_body_top_offset_mm']-actual['body_top_offset_mm']==20.
    assert actual['target_hover_outline_uv']!=actual['target_seated_outline_uv']


def test_legacy_square_arguments_match_explicit_square_target():
    m,frame,info,sample=display_fixture()
    legacy_canvas,legacy=m.overlay(frame,sample,info,2,20.,(),None,(12,9))
    target=dict(color='yellow',brick_type='2x2x1',x=12,y=9,layer=2,orientation_deg=0)
    explicit_canvas,explicit=m.overlay(frame,sample,info,target=target)
    assert np.array_equal(legacy_canvas,explicit_canvas) and legacy==explicit


def test_blue_target_hover_outline_is_blue():
    m,frame,info,sample=display_fixture()
    target=dict(color='blue',brick_type='2x3x1',x=4,y=9,layer=1,orientation_deg=0)
    canvas,report=m.overlay(frame,sample,info,clearance_mm=100.,target=target)
    u,v=np.asarray(report['target_hover_outline_uv'][0],int)
    assert canvas[v,u].tolist()==[255,100,0]
