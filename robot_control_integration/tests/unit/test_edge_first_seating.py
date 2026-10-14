from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from app.edge_first_seating import preview,rotate_about_contact_line
from app.assembly_motion import pose_error


def config():
    return json.loads((Path(__file__).resolve().parents[2]/'fixtures/yellow4_edge_first_preview.json').read_text())


def matrix(p):
    t=np.eye(4);t[:3,:3]=Rotation.from_euler('ZYZ',p[3:],degrees=True).as_matrix();t[:3,3]=p[:3]
    return t


@pytest.mark.parametrize('tilt',[5.,-5.,20.,-20.])
def test_contact_line_remains_fixed_and_tcp_follows_arc(tilt):
    c=config();c['initial_tilt_deg']=tilt;source=deepcopy(c);result=preview(c)
    line=np.column_stack((np.asarray(c['contact_line_points_mm']),np.ones(2)))
    local=(np.linalg.inv(matrix(c['seated_reference_tcp_mm_zyz_deg']))@line.T).T
    for point in result['waypoints']:
        assert (matrix(point['tcp_mm_zyz_deg'])@local.T).T==pytest.approx(line,abs=1e-9)
    assert result['max_tcp_translation_from_seated_mm']>0
    assert result['waypoints'][-1]['tcp_mm_zyz_deg']==c['seated_reference_tcp_mm_zyz_deg']
    assert c==source and result['physical_commands']==0


def test_positive_tilt_lifts_opposite_row_while_first_row_stays_fixed():
    c=config();goal=c['seated_reference_tcp_mm_zyz_deg']
    tool_point=np.linalg.inv(matrix(goal))@np.array([0.,8.,0.,1.])
    tilted=rotate_about_contact_line(goal,c['contact_line_points_mm'],10.)
    assert (matrix(tilted)@tool_point)[2]>0


def test_axes_are_supplied_in_frame_not_fixed_robot_x_or_y():
    c=config();c['contact_line_points_mm']=[[10.,-3.,2.],[12.,6.,4.]]
    t=rotate_about_contact_line(c['seated_reference_tcp_mm_zyz_deg'],c['contact_line_points_mm'],7.)
    assert pose_error(t,c['seated_reference_tcp_mm_zyz_deg'])[1]==pytest.approx(7.)


@pytest.mark.parametrize('color,kind',[('blue','2x2x1'),('yellow','2x3x1'),('red','1x2x1')])
def test_no_general_step_or_other_block_adoption(color,kind):
    c=config();c['block'].update(color=color,brick_type=kind)
    with pytest.raises(ValueError,match='SINGLE_YELLOW'):preview(c)


def test_live_mode_and_zero_length_pivot_are_rejected():
    c=config();c['mode']='REAL'
    with pytest.raises(ValueError,match='PREVIEW_ONLY'):preview(c)
    with pytest.raises(ValueError,match='MUST_HAVE_LENGTH'):
        rotate_about_contact_line([0.,0.,30.,0.,180.,0.],[[0.,0.,0.],[0.,0.,0.]],5.)


def pivot_config():
    return json.loads((Path(__file__).resolve().parents[2]/'fixtures/yellow4_pivot_preview.json').read_text())


@pytest.mark.parametrize('operation',['assembly','removal'])
@pytest.mark.parametrize('angle',[11.,-7.2])
def test_v2_arbitrary_axis_keeps_contacts_fixed_and_rigid_grasp(operation,angle):
    c=pivot_config();selected=c['operations'][operation]
    selected.update(tilt_deg=angle,angular_step_deg=.8)
    selected['contact_line']['points_mm']=[[3.,-5.,2.],[9.,7.,6.]]
    c['seated_block_pose_mm_zyz_deg']=[10.,20.,4.,12.,25.,31.]
    c['tcp_to_block_pose_mm_zyz_deg']=[1.,-3.,33.,5.,173.,-14.]
    original=deepcopy(c);r=preview(c,operation)
    local=np.column_stack((np.array(r['contact_line_points_in_block_mm']),np.ones(2)))
    fixed=np.column_stack((np.array(r['contact_line_points_mm']),np.ones(2)))
    grasp=matrix(c['tcp_to_block_pose_mm_zyz_deg'])
    for p in r['waypoints']:
        assert (matrix(p['block_mm_zyz_deg'])@local.T).T==pytest.approx(fixed,abs=1e-9)
        assert matrix(p['tcp_mm_zyz_deg'])@grasp==pytest.approx(matrix(p['block_mm_zyz_deg']),abs=1e-9)
    a=[p['tilt_deg'] for p in r['waypoints']]
    assert (a[0],a[-1])==((angle,0.) if operation=='assembly' else (0.,angle))
    assert max(abs(y-x) for x,y in zip(a,a[1:]))<=.8+1e-12
    assert c==original and r['physical_commands']==0 and not r['execution_allowed']
    assert not r['assembly_completion'] and not r['removal_completion'] and not r['all_studs_released']


@pytest.mark.parametrize('operation',['assembly','removal'])
def test_v2_world_frame_change_transforms_every_pose_and_scene_point(operation):
    c=pivot_config();first=preview(c,operation)
    c['frame_pose_in_output_mm_zyz_deg']=[110.,-40.,25.,32.,21.,-17.]
    frame=matrix(c['frame_pose_in_output_mm_zyz_deg']);changed=preview(c,operation)
    for a,b in zip(first['waypoints'],changed['waypoints']):
        for key in ('tcp_mm_zyz_deg','block_mm_zyz_deg'):
            assert matrix(b[key])==pytest.approx(frame@matrix(a[key]),abs=1e-9)
        points=np.column_stack((np.array(a['block_corners_mm']),np.ones(8)))
        assert b['block_corners_mm']==pytest.approx((frame@points.T).T[:,:3],abs=1e-9)
    for key in ('target_stud_centers_mm','contact_line_points_mm'):
        xyz=np.array(first[key]);points=np.column_stack((xyz,np.ones(len(xyz))))
        assert changed[key]==pytest.approx((frame@points.T).T[:,:3],abs=1e-9)
    assert changed['tcp_orbit_radius_mm']==pytest.approx(first['tcp_orbit_radius_mm'])


@pytest.mark.parametrize('operation',['assembly','removal'])
def test_new_grasp_relation_moves_tcp_without_changing_block_pivot(operation):
    c=pivot_config();before=preview(c,operation)
    c['tcp_to_block_pose_mm_zyz_deg'][2]+=10
    after=preview(c,operation)
    assert after['seated_reference_tcp_mm_zyz_deg'][2]-before['seated_reference_tcp_mm_zyz_deg'][2]==pytest.approx(10)
    for a,b in zip(before['waypoints'],after['waypoints']):
        assert np.linalg.norm(np.array(b['tcp_mm_zyz_deg'][:3])-a['tcp_mm_zyz_deg'][:3])==pytest.approx(10)
        assert matrix(a['block_mm_zyz_deg'])==pytest.approx(matrix(b['block_mm_zyz_deg']),abs=1e-9)
        assert np.array(a['block_corners_mm'])==pytest.approx(np.array(b['block_corners_mm']),abs=1e-9)


def test_removal_has_own_axis_and_does_not_claim_complete_detachment():
    c=pivot_config();assembly=preview(c,'assembly');removal=preview(c,'removal')
    assert assembly['contact_line_points_mm']!=removal['contact_line_points_mm']
    assert removal['waypoints'][0]['tilt_deg']==0 and removal['waypoints'][-1]['tilt_deg']==-8
    # The opposite bottom edge rises in the synthetic removal example.
    assert removal['waypoints'][-1]['block_corners_mm'][1][2]>0
    assert removal['sequence'][-1]=='INSPECT_REMAINING_ENGAGEMENT'
    del c['operations']['removal']
    with pytest.raises(KeyError,match='removal'):preview(c,'removal')
    with pytest.raises(ValueError,match='REQUIRES_V2'):preview(config(),'removal')


def test_chord_bound_matches_midpoint_geometry_and_refines_with_step():
    c=pivot_config();c['operations']['assembly'].update(tilt_deg=12.,angular_step_deg=12.)
    coarse=preview(c);a,b=coarse['waypoints'];grasp=matrix(c['tcp_to_block_pose_mm_zyz_deg'])
    tcp_mid=matrix(rotate_about_contact_line(coarse['seated_reference_tcp_mm_zyz_deg'],coarse['contact_line_points_mm'],6.))
    tcp_mid[:3,3]=(np.array(a['tcp_mm_zyz_deg'][:3])+b['tcp_mm_zyz_deg'][:3])/2
    local=np.array([*coarse['contact_line_points_in_block_mm'][0],1.])
    displaced=(tcp_mid@grasp@local)[:3]
    assert np.linalg.norm(displaced-coarse['contact_line_points_mm'][0])==pytest.approx(coarse['chord_error_bound_mm'])
    c['operations']['assembly']['angular_step_deg']=.5
    assert preview(c)['chord_error_bound_mm']<coarse['chord_error_bound_mm']


@pytest.mark.parametrize('bad',['mode','color','frame','source','height','axis','same_frame','angle','step'])
def test_v2_invalid_inputs_are_not_silently_adopted(bad):
    c=pivot_config()
    if bad=='mode':c['mode']='REAL'
    if bad=='color':c['block']['color']='blue'
    if bad=='frame':c['operations']['assembly']['contact_line']['frame']='CAMERA'
    if bad=='source':c['source_kind']=''
    if bad=='height':c['block_geometry']['height_mm']=float('nan')
    if bad=='axis':c['operations']['assembly']['contact_line']['points_mm']=[[0,0,0],[0,0,0]]
    if bad=='same_frame':c.update(output_frame=c['coordinate_frame'],frame_pose_in_output_mm_zyz_deg=[1,0,0,0,0,0])
    if bad=='angle':c['operations']['assembly']['tilt_deg']=float('inf')
    if bad=='step':c['operations']['assembly']['angular_step_deg']=0
    with pytest.raises(ValueError):preview(c)


def test_cli_both_json_and_saved_diagram_are_offline(tmp_path):
    import subprocess,sys
    from PIL import Image
    native=Path(__file__).resolve().parents[2]
    output=tmp_path/'both.json';image=tmp_path/'both.png'
    completed=subprocess.run([sys.executable,str(native/'scripts/yellow4_edge_first_preview.py'),
        '--config',str(native/'fixtures/yellow4_pivot_preview.json'),'--operation','both',
        '--output',str(output),'--plot',str(image)],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    result=json.loads(output.read_text())
    assert set(result['operation_previews'])=={'assembly','removal'}
    assert result['physical_commands']==0 and not result['execution_allowed']
    with Image.open(image) as diagram:assert diagram.width>1000 and diagram.height>500
