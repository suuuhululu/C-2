from copy import deepcopy

import pytest

from scripts.assembly_position_trial import run


CONNECTION = dict(tcp='GripperDA_v4', tool='ToolWeight0')
TARGET = [327., -55., 16.68, 78., -178., 77.7]


class Driver:
    def __init__(self):
        self.value = dict(posx=[471., 87., 111., *TARGET[3:]], velx=[0.]*6,
                          motion_status=0, query_duration_s=.04, tcp=CONNECTION['tcp'],
                          tool=CONNECTION['tool'], gripper_status=2, robot_state=1,
                          robot_mode=0, drl_state=3, wrench=[0., 0., 15., 0., 0., 0.])
        self.moves, self.stops = [], 0
        self.rates = []
        self.after_move = lambda: None

    def sample(self):
        return deepcopy(self.value)

    def check_pose(self, pose):
        return pose.copy()

    def call(self, path, typename, **fields):
        assert path == 'system/set_robot_mode' and fields == dict(robot_mode=1)
        self.value['robot_mode'] = 1

    def move_line_async(self, pose, velocity, acceleration):
        assert velocity == acceleration
        self.rates.append(velocity.copy())
        self.moves.append(pose.copy())
        self.value['posx'] = pose.copy()
        self.after_move()

    def stop(self):
        self.stops += 1

    def motion_feedback(self):
        return self.sample()


def test_transfer_only_holds_height_and_never_descends():
    driver = Driver()
    driver.value['robot_mode'] = 1
    result = run(driver, CONNECTION, TARGET, 30.056, lambda *e: None,
                 transfer_only=True, set_automatic_mode=False, transfer_rate=16., sleep=lambda _: None)
    assert driver.moves == [[*TARGET[:2], 111., *TARGET[3:]]]
    assert driver.rates == [[16., 16.]]
    assert result['contact_sample'] is None
    assert result['status'] == 'ABOVE_TARGET_REACHED_NO_DESCENT'


def test_transfer_only_lifts_to_same_height_destination_without_descending():
    driver = Driver()
    driver.value['robot_mode'] = 1
    driver.value['posx'][2] = 24.
    destination = [*TARGET[:2], 32., *TARGET[3:]]
    result = run(driver, CONNECTION, destination, 35., lambda *e: None,
                 clearance_z=32., transfer_only=True, set_automatic_mode=False,
                 force_norm_stop_n=35., sleep=lambda _: None)
    assert driver.moves == [[471., 87., 32., *TARGET[3:]], destination]
    assert result['contact_sample'] is None and result['final_sample']['posx'] == destination


def test_vertical_lift_does_not_repeat_identical_above_target_command():
    driver=Driver();driver.value['robot_mode']=1
    destination=[*driver.value['posx'][:2],194.,*driver.value['posx'][3:]]
    result=run(driver,CONNECTION,destination,35.,lambda *e:None,
        clearance_z=194.,transfer_only=True,set_automatic_mode=False,sleep=lambda _:None)
    assert driver.moves==[destination] and result['final_sample']['posx']==destination


def test_released_gripper_can_retreat_only_when_explicitly_selected():
    driver = Driver()
    driver.value.update(gripper_status=0, robot_mode=1)
    result = run(driver, CONNECTION, TARGET, 35., lambda *e: None,
                 lift_only=True, clearance_z=143., set_automatic_mode=False,
                 required_gripper_status=0, force_norm_stop_n=35., sleep=lambda _: None)
    assert driver.moves == [[471., 87., 143., *TARGET[3:]]]
    assert result['status'] == 'CLEARANCE_REACHED_NO_DESCENT'


def test_default_still_rejects_released_gripper_before_motion():
    driver = Driver()
    driver.value.update(gripper_status=0, robot_mode=1)
    with pytest.raises(RuntimeError, match='ROBOT_OR_GRIP_NOT_READY'):
        run(driver, CONNECTION, TARGET, 35., lambda *e: None,
            lift_only=True, clearance_z=143., set_automatic_mode=False)
    assert not driver.moves


def test_released_retreat_stops_if_grip_detection_returns():
    driver = Driver()
    driver.value.update(gripper_status=0, robot_mode=1)
    driver.after_move = lambda: driver.value.update(gripper_status=2)
    with pytest.raises(RuntimeError, match='ROBOT_OR_GRIP_NOT_READY'):
        run(driver, CONNECTION, TARGET, 35., lambda *e: None,
            lift_only=True, clearance_z=143., set_automatic_mode=False, required_gripper_status=0)
    assert len(driver.moves) == 1 and driver.stops == 1


def test_transfer_only_force_stop_requests_stop():
    driver = Driver()
    driver.value['robot_mode'] = 1
    driver.after_move = lambda: driver.value['wrench'].__setitem__(2, 31.)
    with pytest.raises(RuntimeError, match='FZ_STOP_LIMIT_REACHED'):
        run(driver, CONNECTION, TARGET, 30.056, lambda *e: None,
            transfer_only=True, set_automatic_mode=False)
    assert len(driver.moves) == 1 and driver.stops == 1


@pytest.mark.parametrize('force', [[35., 0., 0.], [21., 28., 0.]])
def test_force_norm_threshold_stops_even_with_zero_fz(force):
    driver = Driver()
    driver.value['robot_mode'] = 1
    driver.after_move = lambda: driver.value['wrench'].__setitem__(slice(0, 3), force)
    with pytest.raises(RuntimeError, match='FORCE_NORM_STOP_LIMIT_REACHED'):
        run(driver, CONNECTION, TARGET, 35., lambda *e: None,
            transfer_only=True, set_automatic_mode=False, force_norm_stop_n=35.)
    assert len(driver.moves) == 1 and driver.stops == 1


@pytest.mark.parametrize('limit', [0, -1, float('nan'), True])
def test_invalid_force_norm_limit_never_dispatches(limit):
    driver = Driver()
    with pytest.raises(ValueError, match='POSITIVE_FINITE_FORCE_NORM_LIMIT_REQUIRED'):
        run(driver, CONNECTION, TARGET, 35., lambda *e: None, force_norm_stop_n=limit)
    assert not driver.moves and not driver.stops


def test_transit_keeps_start_height_then_descends_without_extra_mm():
    driver = Driver()
    events = []
    result = run(driver, CONNECTION, TARGET, 30.056, lambda *e: events.append(e), sleep=lambda _: None)
    assert driver.moves == [[*TARGET[:2], 111., *TARGET[3:]], TARGET]
    assert driver.rates == [[6., 6.], [6., 6.]]
    assert driver.stops == 0 and result['target_posx'] == TARGET
    assert result['status'] == 'POSITION_TARGET_REACHED_SEATING_NOT_VERIFIED'
    assert events[-1][0] == 'RESULT'


def test_extra_descent_preserves_xy_orientation_and_skips_horizontal_move():
    driver = Driver()
    driver.value['posx'] = [*TARGET[:2], TARGET[2]+1, *TARGET[3:]]
    run(driver, CONNECTION, TARGET, 30.056, lambda *e: None, sleep=lambda _: None)
    assert driver.moves == [TARGET]


def test_initial_residual_speed_waits_before_dispatching_next_step():
    driver = Driver()
    driver.value['velx'][2] = .0057
    waited = []
    def settle(seconds):
        assert not driver.moves
        waited.append(seconds)
        driver.value['velx'] = [0.]*6
    run(driver, CONNECTION, TARGET, 35., lambda *e: None, sleep=settle)
    assert waited == [.05] and driver.moves[-1] == TARGET


def test_lift_precedes_horizontal_transfer_and_descent_from_low_start():
    driver = Driver()
    start = [300., -80., 14., *TARGET[3:]]
    driver.value['posx'] = start.copy()
    run(driver, CONNECTION, TARGET, 30.056, lambda *e: None,
        clearance_z=111., sleep=lambda _: None)
    assert driver.moves == [[300., -80., 111., *TARGET[3:]],
                            [*TARGET[:2], 111., *TARGET[3:]], TARGET]


def test_force_stop_while_lifting_never_transfers_or_descends():
    driver = Driver()
    driver.value['posx'][2] = 14.
    driver.after_move = lambda: driver.value['wrench'].__setitem__(2, 31.)
    with pytest.raises(RuntimeError, match='FZ_STOP_LIMIT_REACHED'):
        run(driver, CONNECTION, TARGET, 30.056, lambda *e: None, clearance_z=111.)
    assert len(driver.moves) == 1 and driver.stops == 1


def test_sequence_rates_and_final_lift_preserve_contact_sample():
    driver = Driver()
    driver.value['posx'][2] = 14.
    result = run(driver, CONNECTION, TARGET, 30.056, lambda *e: None,
                 clearance_z=111., transfer_rate=16., descent_rate=8.,
                 finish_lift=True, sleep=lambda _: None)
    assert driver.rates == [[16., 16.], [16., 16.], [8., 8.], [16., 16.]]
    assert result['contact_sample']['posx'] == TARGET
    assert result['final_sample']['posx'][2] == 111.
    assert result['returned_to_clearance']


def test_force_stop_on_descent_never_performs_final_lift():
    driver = Driver()
    def overload_at_contact():
        if driver.value['posx'][2] == TARGET[2]:
            driver.value['wrench'][2] = 31.
    driver.after_move = overload_at_contact
    with pytest.raises(RuntimeError, match='FZ_STOP_LIMIT_REACHED'):
        run(driver, CONNECTION, TARGET, 30.056, lambda *e: None, clearance_z=111.,
            transfer_rate=16., descent_rate=8., finish_lift=True)
    assert driver.moves[-1] == TARGET and driver.stops == 1


def test_lift_only_never_translates_xy_or_descends():
    driver = Driver()
    driver.value['posx'] = [300., -80., 14., *TARGET[3:]]
    result = run(driver, CONNECTION, TARGET, 30.056, lambda *e: None,
                 clearance_z=111., transfer_rate=16., lift_only=True, sleep=lambda _: None)
    assert driver.moves == [[300., -80., 111., *TARGET[3:]]]
    assert result['contact_sample'] is None
    assert result['status'] == 'CLEARANCE_REACHED_NO_DESCENT'


def test_next_point_accepts_arrival_rounding_at_clearance_without_tiny_lift():
    driver = Driver()
    driver.value['posx'][2] = 111.02
    run(driver, CONNECTION, TARGET, 30.056, lambda *e: None,
        clearance_z=111., transfer_rate=16., descent_rate=8., finish_lift=True,
        sleep=lambda _: None)
    assert len(driver.moves) == 3
    assert driver.moves[0] == [*TARGET[:2], 111., *TARGET[3:]]


def test_residual_speed_before_move_waits_for_exact_zero():
    driver = Driver()
    original = driver.sample
    count = 0
    events = []
    def sample():
        nonlocal count
        count += 1
        value = original()
        if count == 2:
            value['velx'][2] = .0015
        return value
    driver.sample = sample
    run(driver, CONNECTION, TARGET, 30.056, lambda *e: events.append(e), sleep=lambda _: None)
    assert any(e[0] == 'PRE_MOVE_STILL_WAIT_SAMPLE' for e in events)
    assert len(driver.moves) == 2


@pytest.mark.parametrize('fz', [30.056, -30.056, 31.])
def test_force_trip_at_or_above_limit_stops_and_never_descends(fz):
    driver = Driver()
    driver.after_move = lambda: driver.value['wrench'].__setitem__(2, fz)
    events = []
    with pytest.raises(RuntimeError, match='FZ_STOP_LIMIT_REACHED'):
        run(driver, CONNECTION, TARGET, 30.056, lambda *e: events.append(e))
    assert len(driver.moves) == 1 and driver.stops == 1
    assert events[-1][0] == 'ABORT' and events[-1][1]['stop']['acknowledged']


def test_unacknowledged_move_also_requests_stop():
    driver = Driver()
    def failed():
        raise TimeoutError('ACK_UNKNOWN')
    driver.after_move = failed
    with pytest.raises(TimeoutError):
        run(driver, CONNECTION, TARGET, 30.056, lambda *e: None)
    assert driver.stops == 1 and len(driver.moves) == 1


@pytest.mark.parametrize('changes', [dict(gripper_status=0), dict(query_duration_s=.6),
                                    dict(tcp='other'), dict(drl_state=1), dict(velx=[1.]*6)])
def test_initial_invalid_state_never_moves(changes):
    driver = Driver()
    driver.value.update(changes)
    with pytest.raises(RuntimeError):
        run(driver, CONNECTION, TARGET, 30.056, lambda *e: None)
    assert driver.moves == [] and driver.stops == 0


@pytest.mark.parametrize('dx,da,commands',[(.017,0.,1),(0.,.03,1),(.08,0.,2),(0.,.08,2)])
def test_vertical_lift_uses_existing_arrival_tolerance_to_avoid_duplicate_command(dx,da,commands):
    driver=Driver();driver.value['robot_mode']=1
    original=driver.value['posx'].copy()
    destination=original.copy();destination[0]+=dx;destination[2]=194.;destination[3]+=da
    result=run(driver,CONNECTION,destination,35.,lambda *e:None,
        clearance_z=194.,transfer_only=True,set_automatic_mode=False,sleep=lambda _:None)
    assert len(driver.moves)==commands
    assert driver.moves[0]==[*original[:2],194.,*original[3:]]
    assert result['contact_sample'] is None
    if commands==2:assert driver.moves[-1]==destination


def test_reviewed_arrival_tolerance_accepts_small_feedback_error_at_original_target():
    driver=Driver()
    driver.after_move=lambda:driver.value['posx'].__setitem__(0,driver.value['posx'][0]+.4)
    result=run(driver,CONNECTION,TARGET,35.,lambda *e:None,
        position_tolerance_mm=1.,orientation_tolerance_deg=1.)
    assert result['final_sample']['posx'][0]==TARGET[0]+.4
    assert driver.moves[-1]==TARGET and not driver.stops


@pytest.mark.parametrize('tolerance',[0.,True,float('nan'),1.1])
def test_invalid_motion_arrival_tolerance_rejected_before_commands(tolerance):
    driver=Driver()
    with pytest.raises(ValueError,match='INVALID_MOTION_ARRIVAL_TOLERANCES'):
        run(driver,CONNECTION,TARGET,35.,lambda *e:None,position_tolerance_mm=tolerance)
    assert not driver.moves
