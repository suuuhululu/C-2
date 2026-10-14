"""Command/workflow regressions; replay outcomes are not contact physics."""
from copy import deepcopy

import pytest

from app import assembly_step_runner as runner
from app.round2_step_controller import prepare_round2_step
from tests.unit.test_human_step_raised_press import fixture


CONNECTION = dict(tcp='GripperDA_v4', tool='ToolWeight0')


def candidate():
    plan, profile, measured, _ = fixture('yellow', '2x2x1', 0)
    measured['press_width_mm'] = 4.
    prepared = prepare_round2_step(plan, profile, measured)
    profile = prepared['profile']
    # Explicit TEST rates for this command trace, not new required inputs.
    profile.update(angular_velocity=6., angular_acceleration=3.,
                   supply_transit_xy_mm=[-300., 0.], body_bypass_xy_mm=[0., -200.],
                   place_pose=[400., -150., 150., 0., 180., 0.])
    return prepared['execution_candidate'], profile, measured


class CommandReplay(runner.StepReplayDriver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands = []

    def move_line_async(self, target, velocity, acceleration):
        self.commands.append(dict(start=self.value['posx'].copy(), target=target.copy(),
                                  velocity=velocity.copy(), acceleration=acceleration.copy()))
        super().move_line_async(target, velocity, acceleration)


def approach(driver, plan, profile):
    driver.value.update(posx=plan['settings']['pickup_pose'].copy(), gripper_status=2)
    return runner.run_step(driver, CONNECTION, plan, profile, lambda *_: True, lambda *_: None,
                           phase='approach', start_zone='supply', sleep=lambda _: None)


def test_round2_vertical_horizontal_and_rotation_have_separate_units():
    plan, profile, _ = candidate()
    plan['settings']['turn_base_z_deg'] = 90.
    plan['settings']['assembly_tcp_zyz_deg'] = [90., 180., 0.]
    driver = CommandReplay(plan['settings']['reference_pose'])
    assert approach(driver, plan, profile)['status'] == 'PAUSED_APPROACH_REACHED'
    vertical = [c for c in driver.commands if c['start'][:2] == c['target'][:2]
                and c['start'][2] != c['target'][2]]
    horizontal = [c for c in driver.commands if c['start'][:2] != c['target'][:2]]
    rotations = [c for c in driver.commands if c['start'][:3] == c['target'][:3]
                 and c['start'][3:] != c['target'][3:]]
    assert len(vertical) == 2 and horizontal and len(rotations) == 1
    assert all(c['velocity'] == [12., 6.] and c['acceleration'] == [1., 3.] for c in vertical)
    assert all(c['velocity'] == [120., 6.] and c['acceleration'] == [2., 3.] for c in horizontal)
    assert rotations[0]['velocity'][1] == 6. and rotations[0]['acceleration'][1] == 3.


def test_round2_mixed_rise_splits_vertical_motion_before_horizontal_observation():
    plan, profile, _ = candidate()
    observation = [-350., 30., 200., 0., 180., 0.]
    profile['round2_supply_observation_pose'] = observation
    driver = CommandReplay(plan['settings']['reference_pose'])
    result = runner.run_step(driver, CONNECTION, plan, profile, lambda *_: True, lambda *_: None,
                             phase='pickup', start_zone='assembly', sleep=lambda _: None)
    assert result['status'] == 'PAUSED_PICKUP_COMPLETE_HOLDING'
    observation_index = next(i for i, command in enumerate(driver.commands) if command['target'] == observation)
    lift = driver.commands[observation_index-1]
    assert lift['target'][:2] == lift['start'][:2]
    assert lift['target'][2] == 200. and lift['velocity'] == [12., 6.]
    assert driver.commands[observation_index]['start'][2] == 200.
    assert driver.commands[observation_index]['velocity'] == [120., 6.]


@pytest.mark.parametrize('missing', [('angular_velocity',), ('angular_acceleration',),
                                     ('angular_velocity', 'angular_acceleration')])
def test_optional_angular_inputs_use_original_fallback_when_omitted(missing):
    plan, profile, _ = candidate()
    for name in missing:
        profile.pop(name)
    driver = CommandReplay(plan['settings']['reference_pose'])
    assert approach(driver, plan, profile)['status'] == 'PAUSED_APPROACH_REACHED'
    vertical = [c for c in driver.commands if c['start'][:2] == c['target'][:2]
                and c['start'][2] != c['target'][2]]
    assert vertical
    assert all(c['velocity'] == [12., 12. if 'angular_velocity' in missing else 6.] for c in vertical)
    assert all(c['acceleration'] == [1., 1. if 'angular_acceleration' in missing else 3.] for c in vertical)


def test_round1_command_policy_remains_unchanged():
    plan, profile, _ = candidate()
    profile.pop('round2')
    profile['transfer_velocity'] = 12.
    driver = CommandReplay(plan['settings']['reference_pose'])
    approach(driver, plan, profile)
    assert driver.commands and all(c['velocity'] == [12., 12.] for c in driver.commands)


class PressWorkflowReplay(CommandReplay):
    """Position outcomes before opening; a synthetic reaction after empty close."""
    def __init__(self, contact_pose, *, stop_force_z_n=25.):
        super().__init__(contact_pose, reaction_force_n=45., stop_force_z_n=stop_force_z_n)
        self.empty_closed = False
        self.value.update(posx=[400., 80., 65., 0., 180., 0.], gripper_status=2, gripper_width_mm=40.6)

    def command_gripper(self, width, force):
        super().command_gripper(width, force)
        self.empty_closed = width == 4.
        if self.empty_closed:
            self.value.update(gripper_status=2, gripper_width_mm=9.2)

    def move_line_async(self, target, velocity, acceleration):
        if self.empty_closed:
            super().move_line_async(target, velocity, acceleration)
        else:
            self.commands.append(dict(start=self.value['posx'].copy(), target=target.copy(),
                                      velocity=velocity.copy(), acceleration=acceleration.copy()))
            self.moves.append(target.copy())
            self.value.update(posx=target.copy(), wrench=[0., 0., 5., 0., 0., 0.])


def finish_press(*, phase='assemble-held'):
    plan, profile, measured = candidate()
    driver = PressWorkflowReplay(measured['pad_contact_pose'])
    events = []
    result = runner.run_step(driver, CONNECTION, plan, profile, lambda *_: True,
                             lambda event, data: events.append((event, deepcopy(data))),
                             phase=phase, start_zone='assembly', sleep=lambda _: None)
    return driver, plan, profile, result, events


def test_next_pickup_uses_last_empty_pad_context_without_receipt_metadata():
    driver, plan, profile, result, _ = finish_press()
    assert result['final_gripper_context'] == dict(state='EMPTY_PAD_CLOSED', gripper_status=2)
    assert driver.value['posx'][2] == profile['clearance_z_mm']
    assert not hasattr(driver, 'execution_generation') and not hasattr(driver, 'session')
    assert 'empty_pad_closed_evidence' not in result
    next_plan = deepcopy(plan)
    next_plan.update(key='square/S5', step_id='S5')
    previous_grips = len(driver.grips)
    next_result = runner.run_step(driver, CONNECTION, next_plan, profile, lambda *_: True, lambda *_: None,
                                  phase='pickup', start_zone='assembly', sleep=lambda _: None)
    assert next_result['status'] == 'PAUSED_PICKUP_COMPLETE_HOLDING'
    assert driver.grips[previous_grips][0] == next_plan['settings']['release_width_mm']
    assert driver.last_step_gripper_context is None


def test_contact_then_release_reuses_empty_pad_status_for_vertical_retreat():
    driver, plan, profile, result, _ = finish_press(phase='contact')
    assert result['status'] == 'PAUSED_TOP_PRESS_RETREAT_PENDING'
    assert result['final_gripper_context'] == dict(state='EMPTY_PAD_CLOSED', gripper_status=2)
    assert driver.value['posx'][2] == 60.2 and driver.value['gripper_status'] == 2
    prior_grips = len(driver.grips)
    result = runner.run_step(driver, CONNECTION, plan, profile, lambda *_: True, lambda *_: None,
                             phase='release', sleep=lambda _: None)
    assert result['status'] == 'AWAITING_BACKEND_OBSERVATION'
    assert driver.value['posx'][2] == profile['clearance_z_mm']
    assert len(driver.grips) == prior_grips
    assert not result['assembly_completion'] and not result['current_update']


def test_existing_gripper_guard_still_rejects_held_start_without_empty_context():
    plan, profile, _ = candidate()
    driver = CommandReplay(plan['settings']['reference_pose'])
    driver.value.update(gripper_status=2, gripper_width_mm=9.2)
    with pytest.raises(RuntimeError, match='ROBOT_OR_GRIP_NOT_READY'):
        runner.run_step(driver, CONNECTION, plan, profile, lambda *_: True, lambda *_: None,
                        phase='pickup', sleep=lambda _: None)
    assert not driver.commands and not driver.grips


def test_persistent_45n_load_uses_original_force_guard_without_new_review_pause():
    plan, profile, measured = candidate()
    driver = PressWorkflowReplay(measured['pad_contact_pose'], stop_force_z_n=None)
    events = []
    with pytest.raises(RuntimeError, match='FORCE_NORM_STOP_LIMIT_REACHED'):
        runner.run_step(driver, CONNECTION, plan, profile, lambda *_: True,
                        lambda event, data: events.append((event, deepcopy(data))),
                        phase='assemble-held', sleep=lambda _: None)
    assert driver.value['posx'][2] == 60.2 and driver.value['wrench'][2] == 45.
    assert any(event == 'PRESS_RESULT' for event, _ in events)
    assert not any(event == 'PRESS_RESIDUAL_LOAD_REVIEW_REQUIRED' for event, _ in events)
    assert driver.last_step_gripper_context is None


def test_press_descent_and_empty_retreat_use_explicit_optional_angular_policy():
    driver, _, _, result, events = finish_press()
    assert result['status'] == 'AWAITING_BACKEND_OBSERVATION'
    pressure_request = next(data for event, data in events if event == 'PRESS_SESSION')
    pressure_command = next(c for c in driver.commands if c['target'] == pressure_request['travel_endpoint_posx'])
    assert pressure_command['velocity'] == [12., 6.]
    assert pressure_command['acceleration'] == [1., 3.]
    retreats = [c for c in driver.commands if c['start'][:2] == c['target'][:2]
                and c['target'][2] > c['start'][2]]
    assert retreats and all(c['velocity'] == [12., 6.] for c in retreats)


def test_round2_release_press_full_finishes_with_last_empty_pad_context():
    plan, profile, measured = candidate()
    driver = PressWorkflowReplay(measured['pad_contact_pose'])
    driver.value.update(posx=[418., -181., 112., 0., 180., 0.], gripper_status=0, gripper_width_mm=62.)
    result = runner.run_step(driver, CONNECTION, plan, profile, lambda *_: True, lambda *_: None,
                             phase='full', sleep=lambda _: None)
    assert result['status'] == 'AWAITING_BACKEND_OBSERVATION'
    assert result['final_gripper_context'] == dict(state='EMPTY_PAD_CLOSED', gripper_status=2)
    assert driver.value['posx'][2] == profile['clearance_z_mm']
    assert not result['assembly_completion'] and not result['current_update']
