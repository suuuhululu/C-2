from copy import deepcopy
import math

import numpy as np
import pytest

from supply_vision.assembly_alignment import estimate_alignment, synthetic_alignment_case


INVENTORY = [('2x2x1', 'blue', 0), ('2x2x1', 'yellow', 0),
             ('2x3x1', 'blue', 0), ('2x3x1', 'blue', 90),
             ('2x3x1', 'yellow', 0), ('2x3x1', 'yellow', 90),
             ('1x2x1', 'red', 0), ('1x2x1', 'red', 90)]


def evaluate(case):
    return estimate_alignment(**case)


def unknown(case):
    result = evaluate(case)
    assert result['status'] == 'UNKNOWN'
    assert result['e_xy_m'] is result['e_yaw_deg'] is result['residuals'] is None
    denied(result)
    return result


def denied(result):
    assert result['robot_target'] is result['metric_pose'] is None
    for key in ('execution_allowed', 'physical_gate_passed', 'next_motion_allowed',
                'actual_alignment_verified', 'actual_assembly_confirmed', 'b_current_changed',
                'projection_consistency_verified', 'registered_mapping_physically_verified'):
        assert result[key] is False
    assert result['physical_commands'] == 0


@pytest.mark.parametrize('kind,color,orientation', INVENTORY)
@pytest.mark.parametrize('yaw', [-3.0, 0.0, 2.5])
def test_known_se2_error_is_about_body_centre_with_independent_stud_holdout(kind, color, orientation, yaw):
    case = synthetic_alignment_case(brick_type=kind, color=color, orientation_deg=orientation,
                                    translation_error_m=(.0012, -.0008), yaw_error_deg=yaw)
    original = deepcopy(case)
    result = evaluate(case)
    assert result['status'] == 'OFFLINE_ALIGNMENT_ESTIMATE'
    np.testing.assert_allclose(result['e_xy_m'], [.0012, -.0008], atol=1e-12)
    assert result['e_yaw_deg'] == pytest.approx(yaw, abs=1e-10)
    assert not set(result['residuals']['inlier_corner_ids']) & set(result['residuals']['heldout_stud_ids'])
    assert max(result['residuals']['heldout_m']) < 1e-12
    assert case == original
    denied(result)


def test_perspective_pixel_centre_is_not_arithmetic_mean_and_is_not_metric_estimator():
    case = synthetic_alignment_case()
    case['observation']['corner_uv'] = [[0., 0.], [120., 0.], [100., 100.], [0., 80.]]
    result = evaluate(case)
    assert result['status'] == 'OFFLINE_ALIGNMENT_ESTIMATE'
    np.testing.assert_allclose(result['observed_center_uv'], [48., 48.], atol=1e-3)
    assert not np.allclose(result['observed_center_uv'], np.mean(case['observation']['corner_uv'], axis=0))
    assert result['projection_consistency_verified'] is False


def test_one_corner_outlier_uses_three_other_corners_and_heldout_studs():
    case = synthetic_alignment_case()
    case['observation']['metric_points'][0]['xy_m'][0] += .0003
    result = evaluate(case)
    assert result['status'] == 'OFFLINE_ALIGNMENT_ESTIMATE'
    assert result['residuals']['excluded_corner_ids'] == ['corner:0']
    np.testing.assert_allclose(result['e_xy_m'], [.001, -.0005], atol=1e-12)


@pytest.mark.parametrize('change', ['pending', 'depth_missing', 'depth_scale', 'depth_old', 'height_missing',
                                   'homography_only', 'body_pixel_plane', 'stud_pixel_plane', 'metric_plane',
                                   'tilt_unknown', 'tilt_high', 'occluded', 'symmetry', 'marker_missing'])
def test_unavailable_registration_different_planes_or_uncertain_observation_remain_unknown(change):
    case = synthetic_alignment_case()
    o, c = case['observation'], case['calibration']
    if change == 'pending': c['status'] = 'PENDING'
    elif change == 'depth_missing': c['registered_depth']['status'] = 'UNKNOWN'
    elif change == 'depth_scale': c['registered_depth']['scale_m_per_unit'] = None
    elif change == 'depth_old': c['registered_depth']['stamp_ns'] -= 1
    elif change == 'height_missing': c['height_aware_mapping']['status'] = 'PENDING'
    elif change == 'homography_only': c['height_aware_mapping']['method'] = 'SINGLE_BOARD_HOMOGRAPHY'
    elif change == 'body_pixel_plane': o['pixel_plane'] = 'BODY_BOTTOM'
    elif change == 'stud_pixel_plane': o['stud_pixel_plane'] = o['pixel_plane']
    elif change == 'metric_plane': o['metric_plane'] = 'BLOCK_TOP'
    elif change == 'tilt_unknown': o['tilt_verified'] = None
    elif change == 'tilt_high': o['tilt_deg'] = .2
    elif change == 'occluded': o['occluded'] = True
    elif change == 'symmetry': o['symmetry_resolved'] = False
    else: o['corner_identity_source'] = 'SORTED_PIXELS_ONLY'
    unknown(case)


@pytest.mark.parametrize('key,value', [('request_id', 'other'), ('reservation_id', 'other'),
                                     ('reservation_generation', 2), ('calibration_id', 'old'),
                                     ('setup_id', 'old'), ('grasp_id', 'other'), ('teaching_version', 'old'),
                                     ('rgb_frame_id', 'assembly'), ('board_frame', 'camera')])
def test_request_reservation_profile_or_calibration_version_mismatch(key, value):
    case = synthetic_alignment_case()
    case['observation']['binding'][key] = value
    unknown(case)


@pytest.mark.parametrize('key,value', [('slot_index', 6), ('slot_index', True), ('epoch', True),
                                     ('reservation_generation', 0), ('workflow_generation', 1.0)])
def test_slot6_and_detyped_generations_do_not_get_alignment(key, value):
    case = synthetic_alignment_case()
    for record in ('observation', 'expected', 'calibration'): case[record]['binding'][key] = value
    case['binding'][key] = value
    unknown(case)


@pytest.mark.parametrize('key,value', [('stamp_ns', 129), ('stamp_ns', 151), ('stamp_ns', True),
                                     ('stamp_ns', -1), ('now_ns', 140), ('now_ns', True)])
def test_stale_future_and_invalid_clock_values(key, value):
    case = synthetic_alignment_case()
    if key == 'now_ns': case[key] = value
    else: case['observation'][key] = value
    unknown(case)


@pytest.mark.parametrize('change', ['scope', 'unit', 'pixel_unit', 'coordinates', 'image_size', 'outside_image',
                                   'K_bool', 'K_nan', 'K_missing', 'K_focal', 'transform_reflection',
                                   'transform_direction', 'transform_unit', 'transform_missing'])
def test_scopes_frames_units_intrinsics_and_rigid_transform_are_strict(change):
    case = synthetic_alignment_case()
    c, o, e = case['calibration'], case['observation'], case['expected']
    if change == 'scope': c['scope'] = 'REAL'
    elif change == 'unit': c['units'] = 'mm'
    elif change == 'pixel_unit': o['pixel_units'] = 'm'
    elif change == 'coordinates': o['image_coordinates'] = 'CROPPED'
    elif change == 'image_size': e['image_size'] = [1280, 720]
    elif change == 'outside_image': o['corner_uv'][0][0] = -1
    elif change == 'K_bool': c['K'][0][0] = True
    elif change == 'K_nan': c['K'][0][0] = float('nan')
    elif change == 'K_missing': c['K'] = None
    elif change == 'K_focal': c['K'][0][0] = 0
    elif change == 'transform_reflection': c['T_board_from_camera']['matrix'][0][0] = -1
    elif change == 'transform_direction': c['T_board_from_camera']['from_frame'] = 'wrong'
    elif change == 'transform_unit': c['T_bottom_from_top']['units'] = 'mm'
    else: c['T_bottom_from_stud_top']['matrix'] = None
    unknown(case)


@pytest.mark.parametrize('change', ['missing', 'extra', 'bool', 'nan', 'float_age', 'negative', 'outliers'])
def test_reviewed_limit_fields_do_not_allow_defaults_or_invalid_numbers(change):
    case = synthetic_alignment_case()
    limits = case['calibration']['reviewed_limits']
    if change == 'missing': del limits['max_fit_residual_m']
    elif change == 'extra': limits['grasp_height_mm'] = 9.4
    elif change == 'bool': limits['max_candidate_xy_m'] = True
    elif change == 'nan': limits['max_fit_residual_m'] = float('nan')
    elif change == 'float_age': limits['max_age_ns'] = 20.0
    elif change == 'negative': limits['max_candidate_yaw_deg'] = -1
    else: limits['max_outliers'] = 2
    unknown(case)


@pytest.mark.parametrize('change', ['duplicate_observed', 'duplicate_expected', 'missing_corner', 'wrong_role',
                                   'wrong_index', 'same_fit_holdout', 'same_cal_capture', 'no_cal_holdout',
                                   'bad_uncertainty', 'nonfinite', 'bool_point', 'heldout_mismatch',
                                   'reflect', 'axis_swap', 'collinear'])
def test_metric_correspondence_roles_independence_and_geometry_quality(change):
    case = synthetic_alignment_case()
    o, e, c = case['observation'], case['expected'], case['calibration']
    if change == 'duplicate_observed': o['metric_points'].append(deepcopy(o['metric_points'][0]))
    elif change == 'duplicate_expected': e['metric_points'].append(deepcopy(e['metric_points'][0]))
    elif change == 'missing_corner': o['metric_points'].pop(0)
    elif change == 'wrong_role': o['metric_points'][4]['role'] = 'BODY_BOTTOM_CORNER'
    elif change == 'wrong_index': o['metric_points'][0]['id'] = 'corner:1'
    elif change == 'same_fit_holdout': c['heldout_feature_ids'] = deepcopy(c['fit_feature_ids'])
    elif change == 'same_cal_capture': c['heldout_capture_ids'] = deepcopy(c['fit_capture_ids'])
    elif change == 'no_cal_holdout': c['heldout_capture_ids'] = []
    elif change == 'bad_uncertainty': o['metric_uncertainty']['xy_m'] = None
    elif change == 'nonfinite': o['metric_points'][0]['xy_m'][0] = float('inf')
    elif change == 'bool_point': o['metric_points'][0]['xy_m'][0] = False
    elif change == 'heldout_mismatch': o['metric_points'][4]['xy_m'][0] += .001
    elif change == 'reflect':
        for p in o['metric_points']: p['xy_m'][0] = .1-p['xy_m'][0]
    elif change == 'axis_swap':
        for p in o['metric_points']: p['xy_m'] = list(reversed(p['xy_m']))
    else:
        for i in range(4): o['metric_points'][i]['xy_m'] = [.04+i*.01, .06]
    unknown(case)


@pytest.mark.parametrize('yaw,translation', [(90, (0, 0)), (180, (0, 0)), (0, (.01, 0))])
def test_symmetric_axes_or_neighbouring_grid_cell_are_not_small_alignment_errors(yaw, translation):
    case = synthetic_alignment_case(yaw_error_deg=yaw, translation_error_m=translation)
    assert unknown(case)['reason'] == 'OTHER_GRID_CELL_OR_SYMMETRIC_AXIS'


def test_red_two_studs_without_body_corners_cannot_resolve_a_2d_fit():
    case = synthetic_alignment_case(brick_type='1x2x1', color='red')
    case['observation']['metric_points'] = case['observation']['metric_points'][4:]
    unknown(case)


@pytest.mark.parametrize('record,key,value', [('observation', 'execution_allowed', True),
                                            ('expected', 'physical_gate_passed', True),
                                            ('calibration', 'next_motion_allowed', 0),
                                            ('observation', 'actual_alignment_verified', True),
                                            ('expected', 'robot_target', [0, 0, 0])])
def test_input_authority_claim_is_rejected_without_normalizing_it_to_a_good_estimate(record, key, value):
    case = synthetic_alignment_case()
    case[record][key] = value
    assert unknown(case)['reason'] in ('INPUT_AUTHORITY_PROMOTION', 'INPUT_ROBOT_TARGET_PROMOTION')


def test_field_pixel_only_replay_has_no_synthetic_metric_completion():
    case = synthetic_alignment_case()
    for record in ('observation', 'expected', 'calibration'): case[record]['scope'] = 'FIELD_REPLAY'
    case['calibration']['status'] = 'PENDING'
    case['observation']['metric_points'] = []
    case['expected']['metric_points'] = []
    case['expected']['projected_corner_uv'] = case['expected']['projected_stud_uv'] = None
    assert unknown(case)['reason'] == 'CALIBRATION_PENDING'


def test_explicit_offline_evidence_candidate_has_no_physical_validation_or_reprojection_claim():
    result = evaluate(synthetic_alignment_case(scope='OFFLINE_EVIDENCE'))
    assert result['status'] == 'OFFLINE_ALIGNMENT_ESTIMATE'
    assert 'NO_RAW_DEPTH_REPROJECTION_VALIDATION' in result['limitations']
    denied(result)


@pytest.mark.parametrize('change', ['clock_observed', 'clock_expected', 'clock_missing', 'resolution',
                                   'distortion_missing', 'distortion_raw', 'distortion_bool',
                                   'distortion_nan', 'distortion_size', 'depth_none', 'limits_none',
                                   'command_claim', 'consumption_claim'])
def test_clock_resolution_distortion_and_missing_evidence_are_explicit(change):
    case = synthetic_alignment_case()
    c, o, e = case['calibration'], case['observation'], case['expected']
    if change == 'clock_observed': o['clock_domain'] = 'OTHER_CLOCK'
    elif change == 'clock_expected': e['clock_domain'] = 'OTHER_CLOCK'
    elif change == 'clock_missing': o['clock_domain'] = None
    elif change == 'resolution': c['image_size'] = [1280, 720]
    elif change == 'distortion_missing': c['distortion'] = None
    elif change == 'distortion_raw': c['distortion']['status'] = 'UNACCOUNTED_RAW_PIXELS'
    elif change == 'distortion_bool': c['distortion']['D'][0] = False
    elif change == 'distortion_nan': c['distortion']['D'][0] = float('nan')
    elif change == 'distortion_size': c['distortion']['D'].pop()
    elif change == 'depth_none': c['registered_depth'] = None
    elif change == 'limits_none': c['reviewed_limits'] = None
    elif change == 'command_claim': o['physical_commands'] = 1
    else: o['slot_consumption'] = 1
    result = unknown(case)
    if change == 'depth_none': assert result['reason'] == 'REGISTERED_DEPTH_MISSING'
