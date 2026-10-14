from copy import deepcopy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.round2_operator_teaching import apply_teaching, retarget_assembly_reference, retarget_pose
from scripts import held_xy_seating_trial as seating


PICKUP = [-459.1122741699219, 11.112536430358887, 50.55427551269531,
          9.841970443725586, 179.1219482421875, 10.311335563659668]
LANDING = [503.7802734375, 91.63031005859375, 37.008758544921875,
           159.39271545410156, 179.65969848632812, 159.3231201171875]
PAD = [504.09613037109375, 91.23787689208984, 55.559078216552734,
       161.0828094482422, 179.6298065185547, 161.05162048339844]


def bundle():
    # Recorded coordinates are data only; these unit tests command no device.
    return dict(version='round2-T2-operator-teaching-bundle/1', step_id='T2',
                target=dict(x=13, y=11, layer=2, orientation_deg=0),
                color='blue', brick_type='2x3x1', supply_slot=3,
                tcp='GripperDA_v4', tool='ToolWeight0',
                pickup=dict(tcp_pose_mm_zyz_deg=PICKUP.copy(), source='fixture/pickup.json'),
                landing=dict(tcp_pose_mm_zyz_deg=LANDING.copy(), source='fixture/landing.json'),
                pad_top=dict(tcp_pose_mm_zyz_deg=PAD.copy(), source='fixture/pad.json'),
                operator_confirmation=dict(full_seating_confirmed=True,
                    confirmation_basis='HUMAN_OPERATOR_REPORT'),
                grasp_height_estimate_mm=8., grasp_height_independently_measured=False,
                pad_contact_independently_sensor_verified=False,
                control_config_adopted=False, execution_allowed=False)


def config():
    return dict(connection=dict(tcp='GripperDA_v4', tool='ToolWeight0'),
                trial_step=dict(step_id='T2'),
                blocks=[dict(color='blue', brick_type='2x3x1', slot=3,
                             pickup_pose=[-450., 5., 60., 10., 179., 11.],
                             center_mapping=dict(old_nominal_mapping=True))],
                alignment_target=dict(target=dict(color='blue', brick_type='2x3x1',
                    x=13, y=11, layer=2, orientation_deg=0),
                    placement_tcp_reference=[500., 90., 40., 160., 179., 160.]),
                assembly_target_xy=[500., 90.], alignment_approach_z_mm=60.,
                integrated_pad_contact_pose=[500., 90., 58.91496849, 160., 179., 160.],
                target_only_motion=True)


def matrix(pose):
    value = np.eye(4)
    value[:3, :3] = Rotation.from_euler('ZYZ', pose[3:], degrees=True).as_matrix()
    value[:3, 3] = pose[:3]
    return value


def test_absolute_three_pose_apply_keeps_original_baseline_and_distinct_pad_pose():
    cfg = config(); source = deepcopy(cfg); captured = bundle()
    cfg['operator_raised_z_trial'] = dict(base_z_offset_mm=10., nominal_pad_bottom_height_mm=15.)
    cfg['blocks'][0]['baseline_pickup_pose'] = [-450., 5., 50., 10., 179., 11.]
    cfg['alignment_target']['baseline_placement_tcp_reference'] = [500., 90., 30., 160., 179., 160.]
    before = deepcopy(cfg)
    taught = apply_teaching(cfg, captured)
    assert cfg == before and captured == bundle()
    assert taught['blocks'][0]['pickup_pose'] == PICKUP
    assert taught['alignment_target']['placement_tcp_reference'] == LANDING
    assert taught['integrated_pad_contact_pose'] == PAD
    assert taught['assembly_target_xy'] == LANDING[:2]
    assert taught['alignment_approach_z_mm'] == pytest.approx(LANDING[2] + 20.)
    assert 'operator_raised_z_trial' not in taught and 'center_mapping' not in taught['blocks'][0]
    assert taught['blocks'][0]['baseline_pickup_pose'] == before['blocks'][0]['baseline_pickup_pose']
    assert taught['alignment_target']['baseline_placement_tcp_reference'] == before['alignment_target']['baseline_placement_tcp_reference']
    assert taught['operator_teaching']['baseline']['pad_contact_pose'] == source['integrated_pad_contact_pose']
    assert not taught['operator_teaching']['grasp_height_independently_measured']
    assert not taught['operator_teaching']['pad_contact_independently_sensor_verified']
    assert not taught['operator_teaching']['assembly_completion']
    reapplied = apply_teaching(taught, captured)
    assert reapplied['operator_teaching']['baseline'] == taught['operator_teaching']['baseline']


@pytest.mark.parametrize('field,value,error', [
    ('target', dict(x=12, y=11, layer=2, orientation_deg=0), 'TARGET_MISMATCH'),
    ('brick_type', '2x2x1', 'TARGET_MISMATCH'),
    ('supply_slot', 4, 'BLOCK_MISMATCH'),
    ('tcp', 'OtherTCP', 'TCP_TOOL_MISMATCH'),
    ('tool', 'OtherTool', 'TCP_TOOL_MISMATCH'),
    ('step_id', 'T3', 'STEP_MISMATCH'),
])
def test_teaching_requires_consistent_config_binding(field, value, error):
    captured = bundle(); captured[field] = value
    with pytest.raises(ValueError, match=error):
        apply_teaching(config(), captured)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True])
def test_teaching_pose_must_be_finite_numeric_data(value):
    captured = bundle(); captured['pad_top']['tcp_pose_mm_zyz_deg'][0] = value
    with pytest.raises(ValueError, match='pad_top pose: expected 6 finite numbers'):
        apply_teaching(config(), captured)


def test_offcenter_and_yaw_retarget_rotate_pad_offset_instead_of_fixing_release_xy():
    yaw = Rotation.from_euler('Z', 90., degrees=True)
    release = [LANDING[0] + 3.7, LANDING[1] - 2.2, LANDING[2] + .4,
               *(yaw * Rotation.from_euler('ZYZ', LANDING[3:], degrees=True)).as_euler('ZYZ', degrees=True).tolist()]
    contact = retarget_pose(LANDING, PAD, release)
    offset = np.array(PAD[:3]) - np.array(LANDING[:3])
    assert contact[:3] == pytest.approx(np.array(release[:3]) + [-offset[1], offset[0], offset[2]])
    assert contact[:2] != release[:2]
    assert np.allclose(np.linalg.inv(matrix(release)) @ matrix(contact),
                       np.linalg.inv(matrix(LANDING)) @ matrix(PAD), atol=1e-9)


def test_general_attitude_retarget_preserves_rigid_relation_not_euler_difference():
    # A nonvertical datum makes raw Euler addition produce a different rotation.
    landing = [1., 2., 3., 20., 110., 35.]
    pad = [4., -1., 18., 70., 130., -15.]
    release = [80., 90., 25., -45., 80., 60.]
    contact = retarget_pose(landing, pad, release)
    assert np.allclose(np.linalg.inv(matrix(release)) @ matrix(contact),
                       np.linalg.inv(matrix(landing)) @ matrix(pad), atol=1e-9)
    raw_abc = [release[i] + pad[i] - landing[i] for i in range(3, 6)]
    error = Rotation.from_euler('ZYZ', contact[3:], degrees=True).inv() * Rotation.from_euler('ZYZ', raw_abc, degrees=True)
    assert np.degrees(error.magnitude()) > 10.


def test_corrected_reference_carries_pad_once_and_keeps_original_sources():
    taught = apply_teaching(config(), bundle()); before = deepcopy(taught)
    corrected = LANDING.copy(); corrected[0] += 4.; corrected[1] -= 3.; corrected[3] += 30.
    shifted = retarget_assembly_reference(taught, corrected)
    assert taught == before
    assert shifted['operator_teaching']['source_poses']['landing'] == LANDING
    assert shifted['operator_teaching']['source_poses']['pad_top'] == PAD
    plan = seating.same_xy_press_plan(corrected, shifted)
    assert np.allclose(matrix(plan['estimated_contact_pose']), matrix(retarget_pose(LANDING, PAD, corrected)))
    assert plan['estimated_contact_pose'][:2] != corrected[:2]
    assert plan['rise_pose'][:2] == corrected[:2] and plan['rise_pose'][3:] == corrected[3:]
    assert plan['press_rise_pose'][:2] == plan['estimated_contact_pose'][:2]
    assert plan['press_rise_pose'][3:] == plan['estimated_contact_pose'][3:]
    assert not plan['no_xy_or_attitude_reposition'] and not plan['contact_height_physically_verified']
    sample = dict(posx=[100., 200., 70., 9., 179., 10.])
    assert seating.seating_targets(sample, shifted)[0][:3] == [*corrected[:3]]


def test_unretargeted_recorded_pad_preserves_exact_xyz_and_abc():
    taught = apply_teaching(config(), bundle())
    plan = seating.same_xy_press_plan(LANDING, taught)
    assert plan['estimated_contact_pose'] == PAD
    assert plan['above_pose'] == [*PAD[:2], PAD[2] + 10., *PAD[3:]]
    assert plan['pad_z_offset_mm'] == pytest.approx(18.55031967163086)


def test_actual_pressure_function_uses_taught_pad_and_vertical_pad_retreat_in_mock():
    from app.assembly_step_runner import StepReplayDriver
    from scripts.assembly_position_trial import run
    cfg = apply_teaching(config(), bundle())
    cfg.update(force_stop_n=45., motion_force_stop_n=None, press_velocity=12.)
    plan = seating.same_xy_press_plan(LANDING, cfg)
    driver = StepReplayDriver(plan['estimated_contact_pose'], reaction_force_n=48.)
    driver.value.update(posx=plan['rise_pose'].copy(), gripper_status=2, gripper_width_mm=9.3)
    events = []
    def record(event, data):
        events.append((event, deepcopy(data)))
    def move(driver, config, target, record, required_gripper_status):
        rising = target[2] > driver.sample()['posx'][2]
        return run(driver, config['connection'], target, None, record,
                   clearance_z=target[2] if rising else None, transfer_only=rising,
                   transfer_rate=12., descent_rate=12., set_automatic_mode=False,
                   required_gripper_status=required_gripper_status, target_only_motion=True,
                   sleep=lambda _: None)
    result = seating.same_xy_press_cycle(driver, cfg, plan, 2, record, move)
    assert result['status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert result['force_stop_n'] == 45. and result['threshold_force_norm_n'] == 48.
    assert driver.sample()['posx'] == plan['press_rise_pose'] and not driver.grips
    press_session = next(data for event, data in events if event == 'PRESS_SESSION')
    assert press_session['initial_sample']['posx'] == plan['above_pose']
    assert press_session['travel_endpoint_posx'][:2] == PAD[:2]
    assert press_session['travel_endpoint_posx'][3:] == PAD[3:]
    assert events[-1][1]['tilt_control'] == 'OPERATOR_TAUGHT_PAD_ATTITUDE_RETARGETED'
    assert not result['assembly_completion'] and not events[-1][1]['contact_height_physically_verified']
