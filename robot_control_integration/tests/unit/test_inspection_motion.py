"""Inspection arrival and subsequent stop use the same supplied policy; no ROS."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.inspection_motion import InspectionMotion


class Driver:
    def __init__(self):
        self.config = dict(timing=dict(stop_timeout_s=.1))
        self.value = dict(posx=[0., 0., 300., 0., 180., 0.], velx=[.1] * 6,
            wrench=[0.] * 6, query_duration_s=.01, tcp='GripperDA_v4', tool='ToolWeight0',
            gripper_status=0, robot_state=1, robot_mode=1, drl_state=3, motion_status=0)
        self.moves, self.stops = [], 0

    def sample(self): return deepcopy(self.value)
    def stop(self): self.stops += 1

    def call(self, path, kind, **fields):
        if kind == 'Fkin':
            return SimpleNamespace(conv_posx=[10., 0., 300., 0., 180., 0.])
        assert kind == 'MoveJoint'
        self.moves.append(fields)
        self.value['posx'] = [10., 0., 300., 0., 180., 0.]


def setup():
    driver = Driver()
    settings = dict(route_reviewed=True, arrival=dict(position_mm=1., orientation_deg=1.),
        stillness=dict(linear_mm_s=5., angular_deg_s=5., position_mm=1., orientation_deg=1.),
        joint_motion=dict(velocity_deg_s=23., acceleration_deg_s2=23., timeout_s=.1),
        views=dict(D3=dict(posj=[0.] * 6, posx=[10., 0., 300., 0., 180., 0.])))
    motion = InspectionMotion(driver, dict(tcp='GripperDA_v4', tool='ToolWeight0'), sleep=lambda _:None)
    return driver, settings, motion


def test_residual_velocity_policy_is_shared_by_arrival_and_later_sample():
    driver, settings, motion = setup()
    result = motion.confirm('check', 'D3', settings, 'OPERATOR_TEST')
    assert result['stopped_verified'] and len(driver.moves) == 1
    assert driver.moves[0]['vel'] == 23. and driver.moves[0]['acc'] == 23.
    assert motion.state('check', 'D3')['stopped_verified']
    driver.value['velx'][0] = 5.01
    later = motion.state('check', 'D3')
    assert not later['stopped_verified'] and not later['motion_still']
    assert later['sample']['velx'][0] == 5.01 and later['position_error_mm'] == 0.
    assert later['stillness'] == settings['stillness']


def test_different_check_or_view_cannot_read_previous_arrival():
    _, settings, motion = setup()
    motion.confirm('check', 'D3', settings, 'OPERATOR_TEST')
    with pytest.raises(ValueError, match='INACTIVE'):
        motion.state('previous-check', 'D3')
    with pytest.raises(ValueError, match='INACTIVE'):
        motion.state('check', 'V0')


@pytest.mark.parametrize('fault', ['review', 'fk', 'gripper', 'stale', 'cancel'])
def test_invalid_inspection_never_sends_a_move(fault):
    driver, settings, motion = setup()
    if fault == 'review': settings['route_reviewed'] = False
    if fault == 'fk': settings['views']['D3']['posx'][0] += 2.
    if fault == 'gripper': driver.value['gripper_status'] = 2
    if fault == 'stale': driver.value['query_duration_s'] = .51
    if fault == 'cancel': motion.cancelled.set()
    with pytest.raises((ValueError, RuntimeError)):
        motion.confirm('check', 'D3', settings, 'OPERATOR_TEST')
    assert driver.moves == []


def test_pose_drift_and_controller_motion_are_not_confirmed():
    driver, settings, motion = setup()
    motion.confirm('check', 'D3', settings, 'OPERATOR_TEST')
    driver.value['posx'][0] += 1.01
    assert not motion.state('check', 'D3')['stopped_verified']
    driver.value['posx'][0] -= 1.01
    driver.value['motion_status'] = 1
    assert not motion.state('check', 'D3')['stopped_verified']


@pytest.mark.parametrize('moving', [False, True])
def test_stop_requires_actual_still_samples_after_cancel(moving):
    driver, settings, motion = setup()
    motion.settings = settings
    if moving: driver.value['velx'][0] = 5.01
    if moving:
        with pytest.raises(TimeoutError, match='STOP_NOT_VERIFIED'):
            motion.stop()
    else:
        assert motion.stop()['motion_status'] == 0
    assert motion.cancelled.is_set() and driver.stops == 1
    assert driver.moves == []


def test_cancel_after_move_stops_and_cannot_start_another_view():
    driver, settings, motion = setup()
    original = driver.call
    def call(path, kind, **fields):
        result = original(path, kind, **fields)
        if kind == 'MoveJoint': motion.cancelled.set()
        return result
    driver.call = call
    with pytest.raises(RuntimeError, match='CANCELED'):
        motion.confirm('check', 'D3', settings, 'OPERATOR_TEST')
    assert len(driver.moves) == 1 and driver.stops == 1
    with pytest.raises(RuntimeError, match='CANCELED'):
        motion.confirm('check', 'D3', settings, 'OPERATOR_TEST')
    assert len(driver.moves) == 1


@pytest.mark.parametrize('at_home',[False,True])
def test_inspection_start_home_check_never_moves_robot(at_home):
    driver, settings, motion=setup()
    settings['views']['HOME']=dict(posj=[0.]*6)
    if at_home:
        driver.value['posx'][0]=10.
        assert motion.confirm('check','HOME',settings,'OPERATOR_TEST',allow_move=False)['stopped_verified']
    else:
        with pytest.raises(RuntimeError,match='START_HOME_REQUIRED'):
            motion.confirm('check','HOME',settings,'OPERATOR_TEST',allow_move=False)
    assert driver.moves==[]
