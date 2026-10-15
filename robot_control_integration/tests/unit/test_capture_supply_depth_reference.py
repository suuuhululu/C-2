from collections import deque
from types import SimpleNamespace as NS

import numpy as np
import pytest

from scripts.capture_supply_depth_reference import Reader, bind_pickup_record, pair_packet, pickup_record, pose_gap, surface_point


def message(ns):
    return NS(header=NS(stamp=NS(sec=ns//10**9, nanosec=ns % 10**9)))


def test_packet_selects_matching_stamps_instead_of_latest_mismatched_pair():
    buffers = {k: deque([message(900_000_000)]) for k in ('rgb', 'depth', 'info')}
    buffers['depth'].append(message(1_000_000_000))
    result = pair_packet(buffers, 1_050_000_000, 800_000_000)
    assert result[1] is buffers['depth'][0]
    assert pair_packet(buffers, 1_250_000_001, 800_000_000) is None
    assert pair_packet(buffers, 1_050_000_000, 900_000_000) is None


def test_packet_rejects_skew_and_future_stamp():
    buffers = {k: deque([message(900_000_000)]) for k in ('rgb', 'depth', 'info')}
    buffers['depth'] = deque([message(960_000_000)])
    assert pair_packet(buffers, 1_000_000_000, 0) is None
    buffers['depth'] = deque([message(900_000_000)])
    assert pair_packet(buffers, 899_000_000, 0) is None


def info():
    return dict(width=1280, height=720, frame_id='camera_color_optical_frame',
                k=[500., 0., 640., 0., 500., 360., 0., 0., 1.],
                d=[0.]*5, distortion_model='plumb_bob')


def decision():
    return dict(recognized=True, center_basis='STUD_ARRAY', center_uv=[320., 240.],
                contour_uv=[[310., 230.], [330., 230.], [330., 250.], [310., 250.]])


def test_surface_uses_pixel_center_inverse_and_depth_not_pickup_z():
    depth = np.full((720, 1280), 500, np.uint16)
    result = surface_point(depth, info(), decision(), [1280, 720])
    assert result['center_source_uv'] == [640.5, 360.5]
    assert result['surface_center_camera_mm'] == pytest.approx([.5, .5, 500.])
    assert result['patch_spread_mm'] == 0.


def test_surface_rejects_zero_patch_even_when_median_is_valid():
    depth = np.full((720, 1280), 500, np.uint16)
    depth[360, 640] = 0
    with pytest.raises(ValueError, match='INVALID_DEPTH_PATCH'):
        surface_point(depth, info(), decision(), [1280, 720])


def test_surface_rejects_patch_crossing_object_boundary():
    value = decision()
    value['contour_uv'] = [[320., 240.], [330., 240.], [330., 250.], [320., 250.]]
    with pytest.raises(ValueError, match='CENTER_PATCH_OUTSIDE_BLOCK'):
        surface_point(np.full((720, 1280), 500, np.uint16), info(), value, [1280, 720])


def test_pose_gap_respects_equivalent_zyz_angles_and_known_translation():
    distance, angle = pose_gap([0., 0., 0., 0., 0., 0.], [3., 4., 0., 360., 0., 0.])
    assert distance == pytest.approx(5.)
    assert angle == pytest.approx(0., abs=1e-10)


def test_reader_exposes_only_read_queries():
    assert Reader.QUERIES == {'motion/check_motion': 'CheckMotion',
        'aux_control/get_current_posx': 'GetCurrentPosx',
        'tcp/get_current_tcp': 'GetCurrentTcp', 'tool/get_current_tool': 'GetCurrentTool'}


def test_pickup_binding_keeps_grasp_pose_separate_from_surface_and_does_not_mutate_row():
    row = dict(color='yellow', brick_type='2x2x1', slot=4, pickup_pose=[1., 2., 3., 0., 180., 0.])
    connection = dict(tcp='GripperDA_v4', tool='ToolWeight0')
    record = dict(schema_version='supply-preclose-teaching-record/1',
        status='OPERATOR_IDENTIFIED_PRE_CLOSE_PICKUP_POSE', slot_id='yellow_2x2x1_04',
        **connection, tcp_pose_mm_zyz_deg=[10., 20., 47., 0., 180., 0.],
        surface_center_base_mm=None)
    assert bind_pickup_record(row, connection, record) == record['tcp_pose_mm_zyz_deg']
    assert row['pickup_pose'][:3] == [1., 2., 3.]
    record['tcp'] = 'GripperDA_v1'
    with pytest.raises(ValueError, match='PICKUP_RECORD_BINDING_MISMATCH'):
        bind_pickup_record(row, connection, record)
    record.update(tcp=connection['tcp'], slot_id='yellow_2x2x1_03')
    with pytest.raises(ValueError, match='PICKUP_RECORD_BINDING_MISMATCH'):
        bind_pickup_record(row, connection, record)


def test_manual_pickup_record_rejects_observation_height_and_wrong_tcp(tmp_path):
    cfg = dict(connection=dict(tcp='GripperDA_v4', tool='ToolWeight0'),
        teaching_xy_bounds_mm=[[-600., -300.], [-100., 250.]], pickup_clearance_z_mm=194.,
        blocks=[dict(color='yellow',brick_type='2x2x1',slot=4,pickup_pose=[-510., 190., 50., 0., 180., 0.])])
    sample = dict(posx=[-518., 195., 47., 175., -179., 175.], **cfg['connection'])
    record = pickup_record(sample, cfg, tmp_path/'sample.json')
    assert record['tcp_pose_mm_zyz_deg'] == sample['posx']
    assert record['surface_center_base_mm'] is None
    assert not record['runtime_config_changed'] and not record['physical_grasp_verified']
    sample['posx'][2] = 374.
    with pytest.raises(ValueError, match='TEACH_PICKUP_REQUIRES_LOW_SUPPLY_POSE'):
        pickup_record(sample, cfg, tmp_path/'sample.json')
    sample['posx'][2] = 47.
    sample['tcp'] = 'GripperDA_v1'
    with pytest.raises(ValueError, match='TCP_TOOL_BINDING_MISMATCH'):
        pickup_record(sample, cfg, tmp_path/'sample.json')


def test_t2_reference_record_is_blue_slot3_and_never_binds_yellow_slot4(tmp_path):
    from scripts.capture_supply_depth_reference import reference_config
    cfg=reference_config('T2');row=cfg['blocks'][0]
    sample=dict(posx=row['pickup_pose'].copy(),**cfg['connection'])
    record=pickup_record(sample,cfg,tmp_path/'sample.json')
    assert record['slot_id']=='blue_2x3x1_03'
    assert record['surface_center_base_mm'] is None and record['physical_commands']==0
    assert bind_pickup_record(row,cfg['connection'],record)==sample['posx']
    yellow=reference_config('T1')
    with pytest.raises(ValueError,match='PICKUP_RECORD_BINDING_MISMATCH'):
        bind_pickup_record(yellow['blocks'][0],yellow['connection'],record)
    with pytest.raises(ValueError,match='UNIQUE_SUPPORTED_REFERENCE_STEP'):
        reference_config('T4')


def test_t3_reference_is_yellow_six_stud_slot5_without_promoting_verification(tmp_path):
    from scripts.capture_supply_depth_reference import reference_config
    cfg=reference_config('T3');row=cfg['blocks'][0]
    record=pickup_record(dict(posx=row['pickup_pose'].copy(),**cfg['connection']),cfg,tmp_path/'sample.json')
    assert record['slot_id']=='yellow_2x3x1_05'
    assert record['physical_commands']==0 and not record['physical_grasp_verified']
    assert not record['surface_reference_accepted'] and not record['runtime_config_changed']


def test_explicit_slot2_record_does_not_inherit_t1_slot4_or_assembly_target(tmp_path):
    from scripts.capture_supply_depth_reference import pickup_config, reference_config
    cfg = pickup_config('T1', 'yellow_2x2x1_02')
    assert 'trial_step' not in cfg and 'alignment_target' not in cfg
    sample = dict(posx=cfg['blocks'][0]['pickup_pose'].copy(), **cfg['connection'])
    record = pickup_record(sample, cfg, tmp_path/'sample.json')
    assert record['slot_id'] == 'yellow_2x2x1_02'
    assert record['slot'] == 2 and record['physical_commands'] == 0
    assert not record['physical_grasp_verified'] and not record['runtime_config_changed']
    t1 = reference_config('T1')
    with pytest.raises(ValueError, match='BINDING_MISMATCH'):
        bind_pickup_record(t1['blocks'][0], t1['connection'], record)
    assert t1['blocks'][0]['slot'] == 4


def test_explicit_pickup_slot_must_belong_to_current_five_slot_layout():
    from scripts.capture_supply_depth_reference import pickup_config
    with pytest.raises(ValueError, match='EXACT_CURRENT_SUPPLY_SLOT'):
        pickup_config('T1', 'yellow_2x2x1_06')
