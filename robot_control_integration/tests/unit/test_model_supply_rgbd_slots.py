import numpy as np
import pytest

from scripts.model_supply_rgbd_slots import affine_model, roi_candidate, valid_packet, row_grid, validate_frozen_layout


def test_generated_roi_transforms_all_corners_without_stretching_source_pixels():
    matrix = affine_model([[0, 0], [100, 0], [0, 100]], [[20, 60], [70, 60], [20, 110]])
    assert roi_candidate([20, 40, 80, 100], matrix) == [30, 80, 60, 110]
    assert np.array([50, 70, 1]) @ matrix == pytest.approx([45, 95])


def test_degenerate_anchors_cannot_generate_slot_models():
    with pytest.raises(ValueError, match='NONCOLLINEAR'):
        affine_model([[0, 0], [1, 1], [2, 2]], [[10, 20], [11, 21], [12, 22]])


def test_out_of_view_candidate_is_rejected_instead_of_clipped_or_filled():
    with pytest.raises(ValueError, match='OUTSIDE'):
        roi_candidate([0, 0, 20, 20], np.array([[1, 0], [0, 1], [-1, 0]]))


def test_visual_grid_is_not_tilted_by_one_displaced_block():
    rows = []
    for group in range(5):
        for slot in range(1, 6):
            center = np.array([500-55*(slot-1), 100+group*50.], float)
            if group == 0 and slot == 4: center += [2, 8]
            rows.append((dict(color=str(group), brick_type='2x2x1', slot=slot), center))
    step, origins = row_grid(rows)
    assert step == pytest.approx([-55, 0])
    assert origins[('0', '2x2x1')] == pytest.approx([500, 100])
    with pytest.raises(ValueError, match='THREE_VISIBLE'):
        row_grid(rows[:2])


def test_frozen_model_rejects_changed_tcp_calibration_or_missing_slots():
    rows = [dict(color='yellow', brick_type='2x2x1', slot=n) for n in range(1, 26)]
    ids = [f'yellow_2x2x1_{n:02d}' for n in range(1, 26)]
    binding = dict(tcp='GripperDA_v4', matrix_version='v4_derived')
    layout = dict(schema_version='supply-rgbd-model-layout-candidate/1', model_binding=binding,
                  slots=rows, image_size=[640, 480])
    validate_frozen_layout(layout, binding, ids)
    for changed in (dict(tcp='GripperDA_v1', matrix_version='v4_derived'),
                    dict(tcp='GripperDA_v4', matrix_version='other')):
        with pytest.raises(ValueError, match='BINDING_MISMATCH'):
            validate_frozen_layout(layout, changed, ids)
    layout['slots'] = rows[:-1]
    with pytest.raises(ValueError, match='BINDING_MISMATCH'):
        validate_frozen_layout(layout, binding, ids)


def packet():
    return dict(width=1280, height=720, frame_id='camera_color_optical_frame',
                depth_encoding='16UC1', stamps_ns=[100_000_000]*3, ages_at_capture_ms=[150]*3)


@pytest.mark.parametrize('key,value', [('width', 640), ('frame_id', 'depth_frame'),
    ('depth_encoding', '32FC1'), ('ages_at_capture_ms', [150, 301, 150]),
    ('ages_at_capture_ms', [-1, 150, 150]), ('stamps_ns', [100_000_000, 151_000_000, 100_000_000])])
def test_stale_unaligned_or_wrong_unit_packets_are_not_evidence(key, value):
    info = packet()
    assert valid_packet(info)
    info[key] = value
    assert not valid_packet(info)
