"""A slot grasp ends holding, before loaded transport or seating; no hardware."""
from copy import deepcopy

import pytest

from app.assembly_step_bridge import build_plan, validate_physical
from app.assembly_step_runner import run_step
from app.control_session import validate_execution
from scripts.robot_control_trial import test_session as make_test_session
from tests.unit.test_assembly_step_bridge import CONNECTION, MOCK_PROFILE, fixture_plan


def pickup(denied=None, held=False):
    plan, driver = fixture_plan()
    if held:
        driver.value['gripper_status'] = 2
    events, waits = [], []

    def confirm(kind, *_):
        waits.append(kind)
        return kind != denied

    result = run_step(driver, CONNECTION, plan, MOCK_PROFILE, confirm,
                      lambda event, data: events.append((event, data)),
                      phase='pickup', start_zone='assembly', sleep=lambda _: None)
    return result, driver, events, waits, plan


def test_pickup_ends_at_taught_slot_holding_without_loaded_transport_or_press():
    result, driver, events, waits, plan = pickup()
    assert result['status'] == 'PAUSED_PICKUP_COMPLETE_HOLDING'
    assert waits == ['START_PICKUP', 'PICKUP_ALIGNMENT', 'GRASP_CONFIRMED']
    labels = [data['label'] for event, data in events if event == 'STEP_MOVE']
    assert labels == ['LIFT', 'PLACE_BOARD_EMPTY', 'BODY_BYPASS_EMPTY',
                      'SUPPLY_20_0_EMPTY', 'PICKUP_APPROACH', 'PICKUP_LOWER']
    assert driver.value['posx'] == plan['settings']['pickup_pose']
    assert driver.value['gripper_status'] == 2
    assert driver.grips == [(plan['settings']['release_width_mm'], 40.),
                            (plan['settings']['pickup_width_mm'], 40.)]
    assert not any(event == 'PRESS_SESSION' for event, _ in events)
    assert not result['assembly_completion'] and not result['current_update']


@pytest.mark.parametrize('denied,status,grips', [
    ('START_PICKUP', 'PAUSED_START', 0),
    ('PICKUP_ALIGNMENT', 'PAUSED_PICKUP_ALIGNMENT', 1),
    ('GRASP_CONFIRMED', 'PAUSED_GRASP_CONFIRMED', 2),
])
def test_each_pickup_observation_can_pause_without_next_stage(denied, status, grips):
    result, driver, _, waits, _ = pickup(denied)
    assert result['status'] == status and len(driver.grips) == grips
    assert waits[-1] == denied
    if denied == 'START_PICKUP':
        assert not driver.moves
    if denied == 'PICKUP_ALIGNMENT':
        assert driver.value['gripper_status'] == 0
    if denied == 'GRASP_CONFIRMED':
        assert driver.value['gripper_status'] == 2


def test_pickup_rejects_held_start_before_opening_existing_block():
    with pytest.raises(RuntimeError, match='ROBOT_OR_GRIP_NOT_READY'):
        pickup(held=True)


@pytest.mark.parametrize('field,error', [
    ('route', 'D_TAUGHT_ROUTE_REVIEW_REQUIRED'),
    ('pose', 'MISSING_OR_INVALID_POSE:pickup_pose'),
    ('close', 'D_MEASURED_PICKUP_WIDTH_REQUIRED'),
    ('open', 'D_MEASURED_RELEASE_WIDTH_REQUIRED'),
])
def test_real_pickup_requires_route_pose_and_both_gripper_widths(field, error):
    plan, _ = fixture_plan()
    plan = deepcopy(plan)
    profile = dict(MOCK_PROFILE, profile_id='LOCAL_PICKUP', physical_route_reviewed=True)
    plan['settings']['physical_reference_reviewed'] = True
    if field == 'route':
        profile['physical_route_reviewed'] = False
    else:
        plan['settings'][{'pose': 'pickup_pose', 'close': 'pickup_width_mm',
                          'open': 'release_width_mm'}[field]] = None
    with pytest.raises(ValueError, match=error):
        validate_physical(plan, profile, 'pickup')


@pytest.mark.parametrize('phase', ['full', 'approach', 'contact', 'release', 'retreat'])
def test_pickup_session_cannot_be_reused_for_another_phase(phase):
    plan, _ = fixture_plan()
    profile = dict(MOCK_PROFILE, profile_id='LOCAL_PICKUP')
    session = make_test_session(plan)
    session.update(backend='REAL', provenance='LOCAL_OPERATOR_TRIAL', source_epoch='ONSITE_SLOT',
                   profile_id=profile['profile_id'], allowed_trial_phase='pickup',
                   exclusive_control_reviewed=True, device_feedback_reviewed=True,
                   stillness_parameters_reviewed=True, hand_clear_reviewed=True)
    with pytest.raises(ValueError, match='PICKUP_SESSION_CANNOT_EXECUTE_OTHER_PHASES'):
        validate_execution(plan, profile, session, phase)


@pytest.mark.parametrize('width', [60., 60.2, 64.2])
def test_reviewed_open_pickup_start_sends_only_final_close_command(width):
    plan, driver = fixture_plan()
    plan['settings']['pickup_start_open_range_mm'] = [60., 64.2]
    driver.value['gripper_width_mm'] = width
    events = []
    result = run_step(driver, CONNECTION, plan, MOCK_PROFILE, lambda *_: True,
                      lambda event, data: events.append((event, data)),
                      phase='pickup', sleep=lambda _: None)
    assert result['status'] == 'PAUSED_PICKUP_COMPLETE_HOLDING'
    assert driver.grips == [(plan['settings']['pickup_width_mm'], 40.)]
    assert sum(event == 'PICKUP_START_OPEN_VERIFIED' for event, _ in events) == 3


@pytest.mark.parametrize('width', [59.9, 64.3, float('nan')])
def test_open_pickup_start_outside_reviewed_range_cannot_move_or_command_gripper(width):
    plan, driver = fixture_plan()
    plan['settings']['pickup_start_open_range_mm'] = [60., 64.2]
    driver.value['gripper_width_mm'] = width
    with pytest.raises(RuntimeError, match='PICKUP_OPEN_START_NOT_VERIFIED'):
        run_step(driver, CONNECTION, plan, MOCK_PROFILE, lambda *_: True,
                 lambda *_: None, phase='pickup', sleep=lambda _: None)
    assert not driver.moves and not driver.grips


def test_open_pickup_start_requires_three_valid_samples_before_any_motion():
    plan, driver = fixture_plan()
    plan['settings']['pickup_start_open_range_mm'] = [60., 64.2]
    original = driver.sample
    calls = [0]

    def sample():
        calls[0] += 1
        value = original()
        # Initial guard, START wait, then three fresh opening observations.
        if calls[0] == 5:
            value['gripper_width_mm'] = 59.9
        return value

    driver.sample = sample
    with pytest.raises(RuntimeError, match='PICKUP_OPEN_START_NOT_VERIFIED'):
        run_step(driver, CONNECTION, plan, MOCK_PROFILE, lambda *_: True,
                 lambda *_: None, phase='pickup', sleep=lambda _: None)
    assert not driver.moves and not driver.grips


@pytest.mark.parametrize('bounds', [None, [40., 64.2], [64.2, 60.], [60., 111.],
                                    [float('nan'), 64.2], [True, 64.2], [60.]])
def test_invalid_pickup_open_range_is_rejected_before_devices(bounds):
    plan, _ = fixture_plan()
    profile = deepcopy(MOCK_PROFILE)
    profile['steps'][plan['key']]['pickup_start_open_range_mm'] = bounds
    from tests.unit.test_assembly_step_bridge import STEPS
    step = next(step for step in STEPS if step['case_id']+'/'+step['step_id'] == plan['key'])
    with pytest.raises(ValueError, match='INVALID_PICKUP_START_OPEN_RANGE'):
        build_plan(step, profile)
