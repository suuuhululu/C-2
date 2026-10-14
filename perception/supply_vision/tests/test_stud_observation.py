import json
import cv2
import numpy as np
import pytest

from supply_vision.stud_observation import detect_circular_candidates, experimental_config


def image():
    return np.zeros((140, 180, 3), np.uint8)


def observe(frame, roi=None, config=None):
    return detect_circular_candidates(frame, roi_xyxy=roi or [0, 0, frame.shape[1], frame.shape[0]],
                                      config=config or experimental_config())


def test_rendered_circle_remains_unverified_and_concentric_edges_preserved():
    frame = image()
    cv2.circle(frame, (70, 60), 16, (255, 255, 255), -1)
    before = frame.copy()
    result = observe(frame)
    assert len(result['candidates']) >= 2  # Canny has two edge contours; never choose a winner.
    assert all(c['ambiguous'] for c in result['candidates'])
    for candidate in result['candidates']:
        np.testing.assert_allclose(candidate['center_uv'], [70, 60], atol=.6)
        assert candidate['lattice_id'] is None and candidate['projected_center_uv'] is None
        assert candidate['stud_verified'] is False and candidate['physical_circle_center_verified'] is False
        assert candidate['physical_uncertainty_px'] is None
        assert candidate['nearby_candidate_ids']
    np.testing.assert_array_equal(frame, before)
    assert result['status'] == 'CIRCULAR_FEATURE_CANDIDATES_UNVERIFIED'
    assert result['metric_pose']['status'] == 'UNKNOWN'
    assert result['e_xy_m'] is None and result['e_yaw_deg'] is None
    assert result['physical_commands'] == 0
    assert all(result[k] is False for k in ('execution_allowed', 'physical_gate_passed', 'next_motion_allowed'))


def test_tilted_synthetic_ellipse_in_original_roi_coordinates():
    frame = image()
    cv2.ellipse(frame, (95, 80), (25, 13), 28, 0, 360, (255, 255, 255), -1)
    result = observe(frame, [40, 30, 150, 130])
    assert result['candidates']
    for candidate in result['candidates']:
        np.testing.assert_allclose(candidate['center_uv'], [95, 80], atol=.7)
        assert max(candidate['ellipse_axes_px']) > min(candidate['ellipse_axes_px'])*1.5
        assert 0 <= candidate['normalized_fit_residual'] < .2
        assert candidate['source'] == 'OBSERVED_IMAGE_EDGE_CONTOUR'
        assert not candidate['physical_circle_center_verified']


def test_clipped_edges_never_verify_a_missing_circle():
    frame = image()
    cv2.circle(frame, (40, 60), 17, (255, 255, 255), -1)
    result = observe(frame, [40, 20, 100, 110])
    assert result['rejected_counts'].get('CONTOUR_TOUCHES_ROI_BOUNDARY', 0) > 0
    assert all(c['clipped'] and c['ambiguous'] for c in result['candidates'])
    assert result['actual_studs_verified'] is False


@pytest.mark.parametrize('value', [0, 57, 255])
def test_plain_background_does_not_invent_missing_features(value):
    result = observe(np.full_like(image(), value))
    assert result['status'] == 'UNKNOWN_NO_CIRCULAR_FEATURES'
    assert result['candidates'] == []


def test_separate_circles_keep_separate_unassigned_candidates():
    frame = image()
    for center in [(45, 60), (115, 60)]:
        cv2.circle(frame, center, 12, (255, 255, 255), -1)
    result = observe(frame)
    assert len(result['candidates']) >= 4
    assert all(c['lattice_id'] is None for c in result['candidates'])
    assert all(abs(c['center_uv'][0]-45) < 1 or abs(c['center_uv'][0]-115) < 1
               for c in result['candidates'])


def test_explicit_color_order_and_grayscale():
    frame = image()
    cv2.circle(frame, (80, 70), 16, (20, 170, 240), -1)
    bgr = observe(frame)
    rgb_config = experimental_config(); rgb_config['color_order'] = 'RGB'
    rgb = observe(frame[:, :, ::-1].copy(), config=rgb_config)
    gray_config = experimental_config(); gray_config['color_order'] = 'GRAY'
    gray = observe(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), config=gray_config)
    assert bgr['candidates'] == rgb['candidates'] == gray['candidates']


@pytest.mark.parametrize('change', [dict(scope='REAL'), dict(version='old'), dict(canny_low=True),
                                   dict(canny_high=1), dict(minimum_axis_ratio=2),
                                   dict(max_candidates=1.5), dict(unexpected=3)])
def test_invalid_or_unversioned_config_rejected(change):
    config = experimental_config(); config.update(change)
    with pytest.raises(ValueError):
        observe(image(), config=config)


@pytest.mark.parametrize('roi', [[-1, 0, 20, 20], [0, 0, 181, 140], [0, 0, 0, 20],
                                [0.0, 0, 20, 20], [False, 0, 20, 20]])
def test_bad_original_roi_rejected(roi):
    with pytest.raises(ValueError):
        observe(image(), roi)


@pytest.mark.parametrize('frame', [np.zeros((100, 100), np.uint8),
                                  np.zeros((100, 100, 4), np.uint8),
                                  np.zeros((100, 100, 3), np.float32)])
def test_wrong_image_channels_or_dtype_rejected(frame):
    with pytest.raises(ValueError):
        observe(frame)


def test_candidate_budget_failure_stays_unknown():
    frame = image()
    cv2.circle(frame, (60, 60), 15, (255, 255, 255), -1)
    config = experimental_config(); config['max_candidates'] = 1
    result = observe(frame, config=config)
    assert result['status'] == 'UNKNOWN_CANDIDATE_BUDGET_EXCEEDED'
    assert result['rejected_counts']['CANDIDATE_BUDGET_EXCEEDED'] > 0
    assert result['execution_allowed'] is False


def test_feature_payload_is_strict_json_serializable():
    frame = image()
    cv2.circle(frame, (60, 60), 14, (255, 255, 255), -1)
    result = observe(frame)
    assert json.loads(json.dumps(result, allow_nan=False)) == result
