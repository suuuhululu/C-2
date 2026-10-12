"""Force contact at changed grasp heights and measured RG2 release feedback; no hardware."""
from copy import deepcopy
import math

import pytest

from app.assembly_step_bridge import build_plan, release_feedback_range
from app.assembly_step_runner import run_step
from tests.unit.test_assembly_step_bridge import CONNECTION, MOCK_PROFILE, STEPS, fixture_plan


@pytest.mark.parametrize('contact_z_offset', [-3., .2, 7., 12.])
def test_changed_grasp_reaches_force_above_or_below_nominal_without_intermediate_stop(contact_z_offset):
    plan, driver = fixture_plan()
    reference = plan['settings']['reference_pose']
    threshold_z = reference[2]+contact_z_offset
    driver.value.update(posx=[*reference[:2], reference[2]+20.1, *reference[3:]],
                        gripper_status=2, gripper_width_mm=40.)

    def descend(target, velocity, acceleration):
        driver.moves.append(target.copy())
        assert target[2] <= threshold_z < driver.value['posx'][2]
        driver.value.update(posx=[*target[:2], threshold_z, *target[3:]],
                            wrench=[0., 0., 35., 0., 0., 0.])
    driver.move_line_async = descend
    events = []
    result = run_step(driver, CONNECTION, plan, MOCK_PROFILE, lambda *args: True,
                      lambda e, d: events.append((e, d)), phase='contact', sleep=lambda _: None)
    assert len(driver.moves) == 1 and driver.stops == 1 and not driver.grips
    assert result['contact_status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert result['status'] == 'PAUSED_SEATED_RELEASE_PENDING'
    assert not result['assembly_completion'] and not result['current_update']
    threshold = next(d['threshold_sample'] for e, d in events if e == 'PRESS_RESULT')
    assert threshold['posx'][2] == threshold_z


def test_no_force_pauses_at_absolute_floor_without_opening_or_seating_request():
    plan, driver = fixture_plan()
    reference = plan['settings']['reference_pose']
    driver.value.update(posx=[*reference[:2], reference[2]+20.1, *reference[3:]], gripper_status=2)
    def descend(target, *args):
        driver.moves.append(target.copy())
        driver.value['posx'] = target.copy()
    driver.move_line_async = descend
    waits = []
    result = run_step(driver, CONNECTION, plan, MOCK_PROFILE,
                      lambda kind, *args: waits.append(kind) or True, lambda *args: None,
                      phase='contact', sleep=lambda _: None)
    assert driver.moves[-1][2] == pytest.approx(reference[2]-4.)
    assert result['status'] == 'PAUSED_MAX_TRAVEL_NO_FORCE'
    assert 'FULL_SEATING' not in waits and not driver.grips


def test_resuming_below_floor_cannot_add_another_five_mm():
    plan, driver = fixture_plan()
    driver.value.update(posx=plan['settings']['reference_pose'].copy(), gripper_status=2)
    driver.value['posx'][2] -= 5.
    result = run_step(driver, CONNECTION, plan, MOCK_PROFILE, lambda *args: True,
                      lambda *args: None, phase='contact', sleep=lambda _: None)
    assert result['status'] == 'PAUSED_CONTACT_TRAVEL_EXHAUSTED'
    assert not driver.moves and not driver.grips


def test_configured_travel_can_exceed_five_mm_without_one_or_two_mm_cap():
    plan, driver = fixture_plan()
    reference = plan['settings']['reference_pose']
    driver.value.update(posx=[*reference[:2], reference[2]+1., *reference[3:]], gripper_status=2)
    profile = dict(MOCK_PROFILE, max_press_travel_mm=9.)
    def descend(target, *args):
        driver.moves.append(target.copy())
        driver.value.update(posx=[*target[:2], reference[2]-7., *target[3:]],
                            wrench=[0., 0., 35., 0., 0., 0.])
    driver.move_line_async = descend
    result = run_step(driver, CONNECTION, plan, profile, lambda *args: True,
                      lambda *args: None, phase='contact', sleep=lambda _: None)
    assert driver.moves[0][2] == pytest.approx(reference[2]-8.)
    assert result['contact_status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert not driver.grips


def release_trial(actual_width, status=0, changes=None, explicit=True):
    plan, driver = fixture_plan()
    plan['settings']['release_width_mm'] = 62.4
    if explicit:
        plan['settings']['release_feedback_range_mm'] = [61.4, 64.2]
    driver.value.update(posx=plan['settings']['reference_pose'].copy(),
                        gripper_status=2, gripper_width_mm=40.4)
    def command(width, force):
        driver.grips.append((width, force))
        driver.value.update(gripper_status=status, gripper_width_mm=actual_width,
                            **(changes or {}))
    driver.command_gripper = command
    ticks = iter(range(1000))
    def run():
        return run_step(driver, CONNECTION, plan, MOCK_PROFILE, lambda *args: True,
                        lambda *args: None, phase='release',
                        clock=lambda: next(ticks), sleep=lambda _: None)
    return driver, run


def test_observed_64_2_mm_release_retreats_after_verified_opening():
    driver, run = release_trial(64.2)
    result = run()
    assert result['status'] == 'AWAITING_BACKEND_OBSERVATION'
    assert driver.grips == [(62.4, 40.)]
    assert driver.moves
    assert all(p[:2] == driver.reference[:2] and p[2] > driver.reference[2]+20.
               and p[3:] == driver.reference[3:] for p in driver.moves)
    assert not result['assembly_completion'] and not result['current_update']


def test_busy_sample_resets_three_consecutive_completion_samples():
    driver, run = release_trial(64.2)
    original = driver.sample
    statuses = iter([0, 0, 3, 0, 0, 0])
    post_command_samples = []
    def sample():
        feedback = original()
        if driver.grips:
            feedback['gripper_status'] = next(statuses, 0)
            post_command_samples.append(feedback['gripper_status'])
            if len(post_command_samples) <= 6:
                assert not driver.moves
        return feedback
    driver.sample = sample
    run()
    assert post_command_samples[:6] == [0, 0, 3, 0, 0, 0]
    assert driver.moves and all(p[2] > driver.reference[2]+20. for p in driver.moves)


@pytest.mark.parametrize('width,status,error', [
    (64.2, 1, 'GRIPPER_COMPLETION_NOT_VERIFIED'),
    (64.2, 3, 'GRIPPER_COMPLETION_NOT_VERIFIED'),
    (64.2, 2, 'GRIPPER_COMPLETION_NOT_VERIFIED'),
    (40.4, 0, 'GRIPPER_COMPLETION_NOT_VERIFIED'),
    (110.1, 0, 'INVALID_GRIPPER_WIDTH_FEEDBACK'),
    (-.1, 0, 'INVALID_GRIPPER_WIDTH_FEEDBACK'),
    (64.2, 4, 'GRIPPER_SAFETY_OR_STATUS_FAULT'),
])
def test_busy_held_insufficient_opening_overshoot_or_safety_never_retreats(width, status, error):
    driver, run = release_trial(width, status)
    with pytest.raises((RuntimeError, TimeoutError), match=error):
        run()
    assert not driver.moves and driver.stops == 1


@pytest.mark.parametrize('width', [64.2, 64.4, 65., 72.])
@pytest.mark.parametrize('explicit', [True, False])
def test_more_open_than_requested_does_not_abort_release(width, explicit):
    driver, run = release_trial(width, explicit=explicit)
    run()
    assert driver.grips == [(62.4, 40.)] and driver.moves


@pytest.mark.parametrize('changes,error', [
    ({'query_duration_s': .6}, 'FEEDBACK_TOO_OLD'),
    ({'tcp': 'wrong'}, 'TCP_TOOL_MISMATCH'),
    ({'drl_state': 2}, 'DRL_NOT_STOPPED'),
    ({'gripper_width_mm': math.nan}, 'INVALID_GRIPPER_WIDTH_FEEDBACK'),
    ({'motion_status': 1}, 'GRIPPER_COMPLETION_NOT_VERIFIED'),
])
def test_invalid_feedback_does_not_certify_opening(changes, error):
    changes = changes.copy()
    width = changes.pop('gripper_width_mm', 64.2)
    driver, run = release_trial(width, changes=changes)
    with pytest.raises((RuntimeError, TimeoutError), match=error):
        run()
    assert not driver.moves


@pytest.mark.parametrize('bounds', [None, [64., 62.], [63., 64.2], [61., 111.],
                                    [math.nan, 64.2], [True, 64.2], [61.]])
def test_invalid_release_range_rejected_when_building_plan(bounds):
    profile = deepcopy(MOCK_PROFILE)
    step = STEPS[0]
    settings = profile['steps'][step['case_id']+'/'+step['step_id']]
    settings.update(release_width_mm=62.4, release_feedback_range_mm=bounds)
    with pytest.raises(ValueError, match='INVALID_RELEASE_FEEDBACK_RANGE'):
        build_plan(step, profile)
    with pytest.raises(ValueError, match='INVALID_RELEASE_FEEDBACK_RANGE'):
        release_feedback_range(settings, 62.4)
