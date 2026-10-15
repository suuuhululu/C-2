from copy import deepcopy
import pytest
from scripts.assembly_press_trial import press

CONNECTION = dict(tcp='GripperDA_v4', tool='ToolWeight0')


class Driver:
    def __init__(self, force=36., coast=0):
        self.value = dict(posx=[296., 198., 33.4, 73., -177., 73.3], velx=[0.]*6,
                          motion_status=0, query_duration_s=.04, **CONNECTION,
                          gripper_status=2, robot_state=1, robot_mode=1, drl_state=3,
                          wrench=[0., 0., 7., 0., 0., 0.])
        self.force, self.coast, self.moves, self.stops = force, coast, [], 0
        self.fail_stop = False
        self.lose_grip = False

    def sample(self):
        return deepcopy(self.value)

    def check_pose(self, pose):
        return pose.copy()

    def move_line_async(self, pose, velocity, acceleration):
        self.moves.append((pose.copy(), velocity.copy(), acceleration.copy()))
        self.value['posx'] = pose.copy()
        if self.force >= 35:
            self.value['posx'][2] += 2.
        self.value['wrench'][2] = self.force
        if self.lose_grip:
            self.value['gripper_status'] = 0

    def stop(self):
        self.stops += 1
        if self.fail_stop:
            raise TimeoutError('STOP_ACK_UNKNOWN')

    def motion_feedback(self):
        feedback = self.sample()
        if self.coast:
            self.coast -= 1
            feedback['velx'][2] = -.2
        return feedback


@pytest.mark.parametrize('force', [60.,65.,69.9])
def test_p_reaction_stop_60_has_no_compliance_or_native_force_commands(force):
    d=Driver(force=force)
    result=press(d,CONNECTION,lambda *_:None,force_stop_n=60.,force_abort_n=70.,
                 max_travel_mm=12.,velocity=3.,sleep=lambda _:None)
    assert result['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert result['native_force_commands']==0 and result['force_control_target_n'] is None
    assert result['force_stop_n']==60. and result['force_abort_n']==70.
    assert len(d.moves)==1 and d.stops==1


@pytest.mark.parametrize('final_only', [False,True])
def test_p_70n_is_fault_even_if_crossed_after_the_60n_stop(final_only):
    d=Driver(force=60. if final_only else 70.)
    original=d.stop
    def stop():
        original()
        if final_only:d.value['wrench'][2]=70.
    d.stop=stop
    with pytest.raises(RuntimeError,match='PRESS_FORCE_ABORT_LIMIT_REACHED'):
        press(d,CONNECTION,lambda *_:None,force_stop_n=60.,force_abort_n=70.,sleep=lambda _:None)
    assert d.stops>=1 and len(d.moves)==1


@pytest.mark.parametrize('force', [35., 36.])
def test_threshold_stops_before_travel_endpoint_without_claiming_seating(force):
    d = Driver(force)
    r = press(d, CONNECTION, lambda *e: None, sleep=lambda _: None)
    assert d.moves == [([296., 198., 28.4, 73., -177., 73.3], [2., 2.], [1., 1.])]
    assert d.stops == 1 and r['status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED'
    assert r['final_sample']['posx'][2] == 30.4
    assert not r['assembly_completion'] and not r['calibration_adopted']


def test_expected_stop_waits_for_coasting_feedback_to_settle():
    d = Driver(coast=2)
    waited = []
    r = press(d, CONNECTION, lambda *e: None, sleep=waited.append)
    assert waited == [.05] and r['stop']['stillness_verified']


def test_missing_force_ends_at_maximum_travel_and_reports_unreached_threshold():
    d = Driver(force=20.)
    r = press(d, CONNECTION, lambda *e: None, max_travel_mm=2.)
    assert d.moves[0][0][2] == 31.4
    assert r['status'] == 'MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD'
    assert not r['assembly_completion']


def test_already_loaded_threshold_never_commands_more_descent():
    d = Driver()
    d.value['wrench'][2] = 35.
    r = press(d, CONNECTION, lambda *e: None)
    assert not d.moves and d.stops == 1
    assert r['status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED'


def test_grip_loss_remains_a_fault_with_stop_not_a_force_success():
    d = Driver(force=20.)
    d.lose_grip = True
    with pytest.raises(RuntimeError, match='ROBOT_OR_GRIP_NOT_READY'):
        press(d, CONNECTION, lambda *e: None)
    assert d.stops == 1


def test_force_rising_before_dispatch_records_that_sample_without_motion():
    d = Driver()
    original = d.sample
    calls = 0
    def sample():
        nonlocal calls
        calls += 1
        if calls == 3:
            d.value['wrench'][2] = 36.
        return original()
    d.sample = sample
    r = press(d, CONNECTION, lambda *e: None)
    assert not d.moves and d.stops == 1
    assert r['threshold_force_norm_n'] == 36.


def test_failed_stop_ack_is_not_reported_as_a_success():
    d = Driver()
    d.fail_stop = True
    with pytest.raises(RuntimeError, match='FORCE_STOP_NOT_ACKNOWLEDGED'):
        press(d, CONNECTION, lambda *e: None)


def test_unending_coast_is_not_reported_as_verified_stop():
    d = Driver(coast=100)
    ticks = iter(range(0, 200, 2))
    with pytest.raises(RuntimeError, match='FORCE_STOP_NOT_VERIFIED'):
        press(d, CONNECTION, lambda *e: None, clock=lambda: next(ticks), sleep=lambda _: None)


@pytest.mark.parametrize('distance', [0, -1, float('nan'), True])
def test_invalid_travel_never_moves(distance):
    d = Driver()
    with pytest.raises(ValueError, match='POSITIVE_FINITE_PRESS_PARAMETERS_REQUIRED'):
        press(d, CONNECTION, lambda *e: None, max_travel_mm=distance)
    assert not d.moves


def test_force_threshold_does_not_mask_simultaneous_grip_loss():
    d = Driver(force=36.)
    d.lose_grip = True
    with pytest.raises(RuntimeError, match='ROBOT_OR_GRIP_NOT_READY'):
        press(d, CONNECTION, lambda *e: None)
    assert d.stops == 1


def test_configured_empty_press_tool_can_stop_on_force_without_false_grip_fault():
    d = Driver(force=36.)
    d.value['gripper_status'] = 0
    r = press(d, CONNECTION, lambda *e: None, required_gripper_status=0)
    assert r['status'] == 'FORCE_THRESHOLD_REACHED_STOP_VERIFIED' and d.stops == 1
