from copy import deepcopy
import json
from pathlib import Path
import shutil
import pytest

from app.assembly_step_bridge import (FIXTURES, build_plan, candidate_profile, load_step,
                                      load_steps, read, require_candidate, step_from_messages, trial_footprint,
                                      validate_physical)
from app.assembly_step_runner import replay_profile, run_step, StepReplayDriver
from scripts.assembly_step_trial import replay, validate_runtime

CONNECTION = dict(tcp='GripperDA_v4', tool='ToolWeight0')
STEPS = load_steps()
PROFILE = candidate_profile(STEPS)
MOCK_PROFILE = replay_profile(PROFILE, STEPS)


def fixture_plan(case='02', number='S01'):
    step = next(s for s in STEPS if s['case_id'].startswith(case+'_') and s['step_id'] == number)
    plan = build_plan(step, MOCK_PROFILE)
    return plan, StepReplayDriver(plan['settings']['reference_pose'])


def execute(plan, driver, confirmations=None, phase='full'):
    events = []
    result = run_step(driver, CONNECTION, plan, MOCK_PROFILE,
                      lambda kind, *_: (confirmations or {}).get(kind, True),
                      lambda event, data: events.append((event, data)), phase=phase, sleep=lambda _: None)
    return result, events


@pytest.mark.parametrize('step', STEPS, ids=[s['case_id']+'/'+s['step_id'] for s in STEPS])
def test_all_19_steps_finish_replay_without_claiming_physical_seating(step):
    plan = build_plan(step, MOCK_PROFILE)
    driver = StepReplayDriver(plan['settings']['reference_pose'])
    result, events = execute(plan, driver)
    assert result['status'] == 'AWAITING_BACKEND_OBSERVATION'
    assert result['assembly_completion'] is False and result['current_update'] is False
    assert plan['source_execution_allowed'] is False and not plan['hardware_verified']
    assert driver.grips and events


@pytest.mark.parametrize('orientation,minimum,size,centre', [
    (0, [10, 3], [3, 2], [11, 3.5]), (90, [10, 3], [2, 3], [10.5, 4])])
def test_six_stud_axis_swap_maps_minimum_dimensions_and_centre_together(orientation, minimum, size, centre):
    block = dict(brick_type='2x3x1', color='yellow', x=3, y=10, layer=1, orientation_deg=orientation)
    footprint = trial_footprint(block)
    assert footprint['min_xy'] == minimum
    assert footprint['size_xy'] == size
    assert footprint['centre_xy'] == centre
    assert footprint['grip_axis_mapping']['x'] == 'y'


def test_grid_bounds_depend_on_footprint_not_outer_stud_corner():
    b = dict(brick_type='2x3x1', color='blue', x=22, y=21, layer=5, orientation_deg=0)
    assert trial_footprint(b)['min_xy'] == [21, 22]
    b['y'] = 22
    with pytest.raises(ValueError, match='FOOTPRINT_OUTSIDE_BOARD'):
        trial_footprint(b)


def test_centre_layers_use_latest_adoption_and_exclude_other_location_as_global_z():
    p = PROFILE['steps']['02_layers_1_to_4/S02']['reference_pose']
    assert p[2] == pytest.approx(33.63553237915039)
    p = PROFILE['steps']['02_layers_1_to_4/S04']['reference_pose']
    assert p[2] == pytest.approx(71.60824584960938)
    assert not PROFILE['physical_route_reviewed']
    assert all(not s['physical_reference_reviewed'] for s in PROFILE['steps'].values())


@pytest.mark.parametrize('change,error', [('revision','CURRENT_REVISION'), ('slot','RESERVATION_BINDING'),
                                        ('action','REASSESSMENT_MOTION_BINDING')])
def test_modified_fixture_binding_is_rejected(tmp_path, change, error):
    source = FIXTURES / '02_layers_1_to_4/S01'
    shutil.copytree(source, tmp_path/'step')
    path = tmp_path/'step/motion.request.json'
    value = read(path)
    if change == 'revision':
        value['latest_current']['current_revision'] = 123
    elif change == 'slot':
        value['reserved_supply_slot']['slot_id'] = 'other_slot'
    else:
        value['action_proposal']['mode'] = 'HUMAN_ASSEMBLY'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match=error):
        load_step(tmp_path/'step')


@pytest.mark.parametrize('path', ['06_release_press_unsupported/unsupported/reassessment.result.json',
                                  '08_red_full_support/partial_support_0/whole.result.json',
                                  '08_red_full_support/partial_support_90/whole.result.json'])
def test_actual_negative_samples_never_enter_the_execution_plan(path):
    with pytest.raises(ValueError, match='ASSESSMENT_NOT_CANDIDATE'):
        require_candidate(read(FIXTURES/path))


def test_supply_route_has_body_bypass_and_place_before_assembly():
    plan, driver = fixture_plan()
    result, events = execute(plan, driver)
    labels = [data['label'] for event, data in events if event == 'STEP_MOVE']
    assert labels.index('SUPPLY_20_0') < labels.index('BODY_BYPASS') < labels.index('PLACE_BOARD')
    assert labels.index('PLACE_BOARD') < labels.index('TARGET_APPROACH_20MM')
    approach = next(d['target'] for e,d in events if e == 'STEP_MOVE' and d['label'] == 'TARGET_APPROACH_20MM')
    assert approach[2]-plan['settings']['reference_pose'][2] >= 20.


def test_contact_press_is_continuous_with_same_lowest_endpoint():
    plan, driver = fixture_plan()
    _, events = execute(plan, driver)
    pressures = [d for e,d in events if e == 'PRESS_SESSION']
    assert len(pressures) == 1
    assert pressures[0]['max_travel_mm'] == pytest.approx(24.1)
    assert pressures[0]['travel_endpoint_posx'][2] == pytest.approx(plan['settings']['reference_pose'][2]-4.)
    assert all(d['force_stop_n'] == 35. and not d['endpoint_is_seating_target'] for d in pressures)


def test_seating_not_confirmed_keeps_grip_without_release_or_next_step():
    plan, driver = fixture_plan()
    result, events = execute(plan, driver, {'FULL_SEATING':False})
    assert result['status'] == 'PAUSED_FULL_SEATING'
    assert driver.value['gripper_status'] == 2
    assert driver.grips == [(62.,40.), (40.,40.)]


def test_contact_phase_stops_holding_until_separate_release_authorization():
    plan, driver = fixture_plan()
    driver.value.update(gripper_status=2, gripper_width_mm=40.)
    driver.value['posx'] = plan['settings']['reference_pose'].copy()
    driver.value['posx'][2] += 20.1
    result, _ = execute(plan, driver, phase='contact')
    assert result['status'] == 'PAUSED_SEATED_RELEASE_PENDING'
    assert not driver.grips and driver.value['gripper_status'] == 2


def test_human_press_and_hold_releases_and_retreats_before_press_ack():
    plan, driver = fixture_plan('05')
    result, events = execute(plan, driver)
    names = [e for e,d in events]
    assert names.index('WAIT_HUMAN_HOLD_READY') < names.index('WAIT_SUPPORT_AND_RELEASE_FOR_HUMAN_PRESS')
    assert names.index('WAIT_SUPPORT_AND_RELEASE_FOR_HUMAN_PRESS') < names.index('WAIT_HUMAN_PRESS_AND_HOLD_ACK')
    assert len([1 for e,d in events if e == 'PRESS_SESSION']) == 1  # near-contact only; no extra 35N robot press
    assert result['contact_status'] == 'HUMAN_REPORTED'
    assert driver.value['gripper_status'] == 0


def test_original_release_press_keeps_original_grip_axis_and_uses_empty_press_tool():
    plan, driver = fixture_plan('07')
    assert next(s for s in STEPS if s['case_id'].startswith('07'))['action']['grip_axis'] == 'x'
    _, events = execute(plan, driver)
    assert (0.,40.) in driver.grips
    assert any(e == 'STEP_MOVE' and d['label'] == 'PRESS_TOOL_LOWER' and d['gripper_status'] == 0 for e,d in events)
    assert any(e == 'PRESS_RESULT' and d['status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED' for e,d in events)


def test_gripper_write_ack_does_not_imply_opening_completion():
    plan, driver = fixture_plan()
    driver.value.update(gripper_status=2, gripper_width_mm=40.)
    driver.command_gripper = lambda *args: None
    ticks = iter(range(1000))
    with pytest.raises(TimeoutError, match='GRIPPER_COMPLETION_NOT_VERIFIED'):
        run_step(driver, CONNECTION, plan, MOCK_PROFILE, lambda *args: True, lambda *args: None,
                 phase='release', clock=lambda: next(ticks), sleep=lambda _: None)
    assert driver.stops == 1 and not driver.moves


def test_physical_candidate_is_not_promoted_by_replay_settings():
    plan = build_plan(STEPS[0], PROFILE)
    with pytest.raises(ValueError, match='PHYSICAL_REFERENCE_REVIEW'):
        validate_physical(plan, PROFILE, 'full')
    plan, _ = fixture_plan('07')
    plan['settings']['physical_reference_reviewed'] = True
    plan['settings']['press_start_pose'] = None
    with pytest.raises(ValueError, match='press_start_pose'):
        validate_physical(plan, dict(MOCK_PROFILE, profile_id='D_TEST'), 'contact')


def test_offline_replay_writes_trace_without_ros_modbus_or_socket(tmp_path, monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('NO_NETWORK_IN_OFFLINE_REPLAY')
    monkeypatch.setattr(socket, 'socket', forbidden)
    from app.assembly_motion_ros import AssemblyMotionRos
    monkeypatch.setattr(AssemblyMotionRos, '__init__', forbidden)
    report = replay(STEPS, PROFILE, tmp_path)
    assert report['steps'] == 19 and len(report['cases']) == 8
    assert report['device_connections'] == 0 and report['robot_motion_commands'] == 0
    assert len(list(tmp_path.glob('*.trace.json'))) == 19


def test_live_receipt_rejects_mock_expiry_wrong_mode_and_slot():
    plan, _ = fixture_plan()
    receipt = dict(sample_kind='LIVE_D_RUNTIME', source_epoch='D_LIVE', valid_until_unix_s=200,
                   plan_id=plan['plan_id'], step_id=plan['step_id'], current_revision=plan['current_revision'],
                   profile_id=PROFILE['profile_id'], execution_id='one', reassessment_ref='A_new',
                   reassessed_block=plan['block'], reassessed_mode=plan['mode'],
                   reassessed_assistance_kind=plan['assistance_kind'], current_ref='B_current',
                   reservation_ref='D_slot', start_pose_ref='D_still_sample', reservation_confirmed=True,
                   slot_id=plan['reservation']['slot_id'])
    validate_runtime(plan, receipt, PROFILE, now=100)
    for change in [dict(source_epoch='OFFLINE_MOCK'), dict(valid_until_unix_s=99),
                   dict(reassessed_mode='HUMAN_ASSEMBLY'), dict(slot_id='wrong')]:
        with pytest.raises(ValueError):
            validate_runtime(plan, dict(receipt, **change), PROFILE, now=100)


def test_backend_can_pass_three_messages_without_intermediate_sample_files():
    step = STEPS[0]
    assessment = read(Path(step['source_directory'])/'reassessment.result.json')
    converted = step_from_messages(assessment, step['request'], step['motion'], case_id=step['case_id'])
    assert converted['action'] == step['action']
    assert converted['reservation'] == step['reservation']
    assert converted['current_revision'] == step['current_revision']


def test_direct_real_runner_rejects_candidate_before_even_reading_robot_state():
    plan = build_plan(STEPS[0], PROFILE)
    class Driver:
        mode = 'REAL'
        def sample(self):
            raise AssertionError('NO_DEVICE_SAMPLE_ALLOWED')
    with pytest.raises(ValueError, match='PHYSICAL_REFERENCE_REVIEW'):
        run_step(Driver(), CONNECTION, plan, PROFILE, lambda *args: True, lambda *args: None)


def test_clockwise_base_z_turn_is_matrix_correct_and_preserves_tcp_xyz():
    from scipy.spatial.transform import Rotation
    from app.assembly_step_runner import rotate_base_z_pose
    import numpy as np
    start = [471., 86., 112., 70.231, -177.078, 70.49]
    target = rotate_base_z_pose(start, -90.)
    expected = Rotation.from_euler('Z', -90., degrees=True)*Rotation.from_euler('ZYZ', start[3:], degrees=True)
    actual = Rotation.from_euler('ZYZ', target[3:], degrees=True)
    assert np.rad2deg((actual.inv()*expected).magnitude()) < 1e-10
    assert target[:3] == start[:3]


def test_held_approach_turns_once_above_target_without_gripper_or_descent_contact():
    plan, driver = fixture_plan('02', 'S03')
    plan['settings']['turn_base_z_deg'] = -90.
    driver.value.update(gripper_status=2, gripper_width_mm=40.)
    initial = driver.value['posx'].copy()
    result, events = execute(plan, driver, phase='approach')
    moves = [(d['label'], d['target']) for e,d in events if e == 'STEP_MOVE']
    before = next(p for label,p in moves if label == 'TARGET_HIGH_BEFORE_TURN')
    after = next(p for label,p in moves if label == 'TURN_AT_TARGET_CLEARANCE')
    assert before[:3] == after[:3] and before[2] >= plan['settings']['reference_pose'][2]+20.
    assert before[3:] == initial[3:]
    assert after[3] == pytest.approx((initial[3]-90.+180.) % 360.-180.)
    assert after[4:] == initial[4:]
    assert moves[-1][0] == 'TARGET_APPROACH_20MM' and moves[-1][1][3:] == after[3:]
    assert result['status'] == 'PAUSED_APPROACH_REACHED'
    assert not driver.grips and not any(e == 'PRESS_SESSION' for e,d in events)


def test_contact_after_clockwise_approach_does_not_rotate_again_or_restore_old_attitude():
    from app.assembly_step_runner import rotate_base_z_pose
    plan, driver = fixture_plan('02', 'S03')
    plan['settings']['turn_base_z_deg'] = -90.
    start = rotate_base_z_pose(plan['settings']['reference_pose'], -90.)
    start[2] += 20.1
    driver.value.update(posx=start.copy(), gripper_status=2, gripper_width_mm=40.)
    result, events = execute(plan, driver, phase='contact')
    assert not any(e == 'TURN_REFERENCE' for e,d in events)
    assert all(p[3:] == start[3:] for p in driver.moves)
    assert result['status'] == 'PAUSED_SEATED_RELEASE_PENDING'
