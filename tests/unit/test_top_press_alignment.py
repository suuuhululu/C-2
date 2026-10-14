import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.top_press_alignment import align_top, pad_approach


def case():
    points = np.array([[-10,-10,0], [10,-10,0], [10,10,0], [-10,10,0], [0,0,0], [5,4,0]], float)
    rotation = Rotation.from_euler('xyz', [3,-2,5], degrees=True).as_matrix()
    origin = np.array([300.,100.,50.])
    observed = points @ rotation.T + origin
    expected = points + origin
    record = dict(frame='robot_base', units='mm', source='RGBD', binding={'reservation_id':'one'},
                  feature_ids=list('abcdef'), points_mm=observed.tolist())
    target = dict(record, points_mm=expected.tolist())
    limits = dict(max_fit_error_mm=.1, max_check_error_mm=.1, max_translation_mm=20., max_rotation_deg=10.)
    return record, target, rotation, origin, limits


def test_tilt_yaw_correction_rotates_about_block_and_preserves_grasp():
    observed, target, rotation, origin, limits = case()
    tcp = origin + rotation @ np.array([0.,0.,10.])
    result = align_top(observed, target, [*tcp,0.,180.,0.], limits)
    assert np.allclose(result['aligned_held_tcp_mm_zyz_deg'][:3], origin+[0,0,10])
    assert np.allclose(result['correction_rotation_matrix'], rotation.T)
    assert result['check_error_mm'] < 1e-10 and result['execution_allowed'] is False
    assert result['observed_tilt_deg'] > 3. and result['target_tilt_deg'] == pytest.approx(0.)


def test_wrong_heldout_point_and_unbounded_rotation_rejected():
    observed, target, _, _, limits = case()
    target['points_mm'][-1][0] += 1.
    with pytest.raises(ValueError, match='ENVELOPE'): align_top(observed,target,[300,100,60,0,180,0],limits)
    observed, target, _, _, limits = case(); limits['max_rotation_deg']=1.
    with pytest.raises(ValueError, match='ENVELOPE'): align_top(observed,target,[300,100,60,0,180,0],limits)


def test_wrench_alone_is_not_contact_geometry():
    observed, target, _, _, limits = case(); observed['source']='WRENCH'
    with pytest.raises(ValueError, match='CONTACT_GEOMETRY'): align_top(observed,target,[300,100,60,0,180,0],limits)


def test_pad_approach_uses_pad_offset_and_measured_surface_normal():
    surface=np.eye(4);surface[:3,3]=[300,100,50]
    pad=np.eye(4);pad[2,3]=-10.
    result=pad_approach(surface.tolist(),pad.tolist(),5.)
    assert np.allclose(result['tcp_mm_zyz_deg'][:3],[300,100,65])
    assert result['surface_normal_base']==[0.,0.,1.]
    assert not result['execution_allowed']


def coordinate_case():
    request=dict(color='yellow',brick_type='2x3x1',slot_index=2,span_studs=3,height_mode='BASELINE')
    reference=dict(request,nominal_tcp_mm_zyz_deg=[100.,200.,30.,0.,180.,0.],taught_coordinate_verified=True,
        center_uv=[50.,55.],jacobian_base_xy_mm_per_pixel=[[1.,0.],[0.,1.]],
        mapping_independently_verified=True,center_reference_pairing_verified=True)
    parameters=dict(open_width_mm=70.,close_width_mm=40.,gripper_force_n=40.,approach_offset_mm=20.,max_center_shift_mm=5.)
    settings=dict(minimum_area=50,approx_fraction=.02,minimum_fill=.9,
        hsv_ranges={'yellow':[[[18,80,60],[40,255,255]]],'blue':[[[95,80,25],[135,255,255]]],
                    'red':[[[0,80,40],[10,255,255]]]})
    observation=dict(status='CENTER_CANDIDATE',color='yellow',brick_type='2x3x1',slot_id='yellow_2x3x1_02',
                      geometry=dict(corners_uv=[[42,40],[62,40],[62,70],[42,70]]))
    return observation,request,reference,parameters,settings


def test_coordinate_first_applies_only_center_xy_and_preserves_taught_axis():
    from app.vision_grasp_plan import coordinate_first_pick
    result=coordinate_first_pick(*coordinate_case())
    assert result['center_assist_applied'] is True
    assert result['candidate_tcp_mm_zyz_deg']==pytest.approx([102.,200.,30.,0.,180.,0.])


@pytest.mark.parametrize('cause',['unknown','mapping_unverified','large_shift','bad_geometry','bad_mapping'])
def test_user_requested_coordinate_fallback_retains_exact_pose(cause):
    from app.vision_grasp_plan import coordinate_first_pick
    observed,request,reference,parameters,settings=coordinate_case()
    if cause=='unknown':observed=dict(status='UNKNOWN',reason='low_confidence')
    if cause=='mapping_unverified':reference['mapping_independently_verified']=False
    if cause=='large_shift':parameters['max_center_shift_mm']=.5
    if cause=='bad_geometry':observed['geometry']['corners_uv']=None
    if cause=='bad_mapping':reference['jacobian_base_xy_mm_per_pixel']=[[0.,0.],[0.,0.]]
    result=coordinate_first_pick(observed,request,reference,parameters,settings)
    assert result['status']=='VISION_GRASP_PLAN_FOR_REVIEW' and not result['center_assist_applied']
    assert result['candidate_tcp_mm_zyz_deg']==reference['nominal_tcp_mm_zyz_deg']


@pytest.mark.parametrize('cause',['STOP','slot_mismatch','axis_mismatch'])
def test_coordinate_fallback_never_bypasses_stop_or_wrong_teaching(cause):
    from app.vision_grasp_plan import coordinate_first_pick
    observed,request,reference,parameters,settings=coordinate_case()
    if cause=='STOP':request['stop_requested']=True
    if cause=='slot_mismatch':observed['slot_id']='yellow_2x3x1_01'
    if cause=='axis_mismatch':reference['span_studs']=2
    result=coordinate_first_pick(observed,request,reference,parameters,settings)
    assert result['status']=='BLOCKED' and result['actions'] is None


def image_case():
    import cv2
    from supply_vision.stud_observation import experimental_config
    _,_,_,_,surface=coordinate_case()
    frame=np.zeros((160,240,3),np.uint8)
    cv2.rectangle(frame,(140,50),(180,90),(0,255,255),-1)
    studs=[[20,20],[100,20],[100,100],[20,100],[60,20],[60,100]]
    for center in studs:cv2.circle(frame,tuple(center),7,(255,255,255),2)
    bundle=dict(color='yellow',block_roi_xyxy=[130,40,200,110],stud_roi_xyxy=[5,5,115,115],
        surface_settings=surface,detector_config=experimental_config(),
        expected_visible_stud_centers_uv=studs,
        expected_block_corners_uv=[[138,51],[178,51],[178,91],[138,91]],
        limits=dict(max_stud_match_px=4.,max_heldout_error_px=1.,max_corner_error_px=1.))
    return frame,bundle


def test_opencv_no_model_corner_and_stud_comparison_uses_real_image_operations():
    from app.top_press_alignment import opencv_corner_stud_comparison
    frame,bundle=image_case();result=opencv_corner_stud_comparison(frame,bundle)
    assert result['status']=='OPENCV_CORNER_STUD_PIXEL_COMPARISON'
    assert result['pixel_center_error']==pytest.approx([-2.,1.],abs=.1)
    assert result['pixel_yaw_error_deg']==pytest.approx(0.,abs=.1)
    assert result['requires_registered_depth'] and not result['execution_allowed']


def test_opencv_missing_studs_or_adjacent_cell_window_never_creates_robot_target():
    from app.top_press_alignment import opencv_corner_stud_comparison
    frame,bundle=image_case();frame[:120,:120]=0
    result=opencv_corner_stud_comparison(frame,bundle)
    assert result['status']=='UNKNOWN' and result['robot_target'] is None
    frame,bundle=image_case();bundle['limits']['max_stud_match_px']=25.
    result=opencv_corner_stud_comparison(frame,bundle)
    assert result['status']=='UNKNOWN' and result['reason']=='MATCH_WINDOW_COULD_SELECT_ADJACENT_STUD_CELL'


def test_partial_color_block_survives_missing_bottom_corners_without_false_center():
    from app.top_press_alignment import visible_colored_block
    frame,bundle=image_case()
    result=visible_colored_block(frame,[130,40,200,75],'yellow',bundle['surface_settings'])
    assert result['status']=='PARTIAL_COLOR_BLOCK_OBSERVATION'
    assert len(result['visible_edges_uv'])>=1
    assert result['full_body_center_uv'] is None and result['centroid_is_full_body_center'] is False
    assert all(point[1]<74 for edge in result['visible_edges_uv'] for point in edge)
    assert result['physical_commands']==0 and result['execution_allowed'] is False


def test_two_visible_corners_with_depth_normal_align_without_centred_grasp():
    from app.top_press_alignment import align_visible_edge
    observed,target,rotation,origin,limits=case()
    observed.update(points_mm=observed['points_mm'][:2],top_normal_base=(rotation@np.array([0.,0.,1.])).tolist(),edge_id='BODY_TOP_FRONT')
    target.update(points_mm=target['points_mm'][:2],top_normal_base=[0.,0.,1.],edge_id='BODY_TOP_FRONT')
    offset=np.array([2.,-3.,10.]);tcp=origin+rotation@offset
    result=align_visible_edge(observed,target,[*tcp,0.,180.,0.],limits)
    assert result['visible_corner_count']==2 and result['centred_grasp_assumed'] is False
    assert result['aligned_held_tcp_mm_zyz_deg'][:3]==pytest.approx(origin+offset)
    assert np.allclose(result['correction_rotation_matrix'],rotation.T)
    assert result['execution_allowed'] is False


def test_visible_edge_requires_known_correspondence_and_usable_depth_normal():
    from app.top_press_alignment import align_visible_edge
    observed,target,rotation,origin,limits=case()
    observed.update(points_mm=observed['points_mm'][:2],top_normal_base=[0.,0.,1.],edge_id='FRONT')
    target.update(points_mm=target['points_mm'][:2],top_normal_base=[0.,0.,1.],edge_id='SIDE')
    with pytest.raises(ValueError,match='MATCHING_STEP_EDGE'):align_visible_edge(observed,target,[*origin,0.,180.,0.],limits)
