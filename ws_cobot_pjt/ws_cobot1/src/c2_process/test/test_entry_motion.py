"""entry 위치 허용오차 격리와 실제 완료·정착 조건. 로봇 연결 없음."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c2_process.entry_motion import make_entry_motion_profile
from c2_process.robot_adapter import posx_to_pose
from test_robot_adapter_motion import setup, samples, fake_stop, ZERO

TRAVEL = dict(id='candle_travel', vel_mm_s=25., acc_mm_s2=10.,
              pos_tol_mm=.2, angle_tol_deg=.15, completion_timeout_s=90.)
ENTRY = dict(motion_overrides=dict(pos_tol_mm=.5))


def test_entry_does_not_mutate_general_profile():
    original = copy.deepcopy(TRAVEL)
    result = make_entry_motion_profile(TRAVEL, ENTRY)
    assert result == dict(TRAVEL, pos_tol_mm=.5)
    assert TRAVEL == original
    assert result['angle_tol_deg'] == .15


@pytest.mark.parametrize('entry,error_mm,angle_deg,ok', [
    (True, .3885, .0059, True),
    (False, .3885, .0059, False),
    (True, .6, .0059, False),
    (True, .3885, .16, False),
])
def test_position_and_orientation_completion(setup, entry, error_mm, angle_deg, ok):
    ad, clock, calls = setup
    profile = make_entry_motion_profile(TRAVEL, ENTRY) if entry else dict(TRAVEL)
    profile['air_monitor'] = dict(kind='AIR', bias=[0., 0., 0.], force_limit_n=15., samples=[])
    ad.log = SimpleNamespace(info=lambda line: None, warn=lambda line: None)
    ad._force_vec = lambda timeout: [0., 0., 4.]
    stops = fake_stop(ad)
    target = [10., 0., 0., 0., 0., 0.]
    settled = [10. - error_mm, 0., 0., 0., 0., angle_deg]
    samples(ad, [(ZERO, 1, 0), (settled, 1, 0)])
    result = ad.move(posx_to_pose(target), 'c2_base', profile, 1., None)
    assert result.ok is ok and len(calls) == 1
    assert result.observed_state['stop_confirmed'] is True
    if ok:
        assert clock.now >= .2 and not stops
    else:
        assert len(stops) == 1


def test_jitter_cannot_satisfy_stable(setup):
    ad, clock, calls = setup
    stops = fake_stop(ad)
    count = [0]
    def observe(timeout):
        count[0] += 1
        if count[0] == 1:
            return ZERO, 1, 0
        return [9.60 if count[0] % 2 else 9.70, 0., 0., 0., 0., 0.], 1, 0
    ad._motion_sample = observe
    result = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base',
                     make_entry_motion_profile(TRAVEL, ENTRY), 1., None)
    assert not result.ok and len(stops) == 1


@pytest.mark.parametrize('overrides', [
    {'pos_tol_mm': 0}, {'pos_tol_mm': -.5}, {'pos_tol_mm': float('nan')},
    {'pos_tol_mm': float('inf')}, {'pos_tol_mm': True}, {'pos_tol_mm': '.5'},
    {'pos_tol_mm': .5, 'angle_tol_deg': .3},
])
def test_invalid_or_out_of_scope_override_rejected(overrides):
    with pytest.raises(ValueError):
        make_entry_motion_profile(TRAVEL, dict(motion_overrides=overrides))
