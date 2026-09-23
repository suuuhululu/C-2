"""실제 어댑터에 기록 형태의 관측·서비스 대역을 주입한다. 로봇 연결 없음."""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import c2_process.robot_adapter as module
from c2_process.robot_adapter import DoosanRobotAdapter, StepResult, posx_to_pose

ZERO = [0.] * 6
PROFILE = {'vel_mm_s': 10., 'pos_tol_mm': .1}


@pytest.fixture
def setup(monkeypatch):
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr(module, 'time', SimpleNamespace(
        monotonic=lambda: clock.now,
        sleep=lambda seconds: setattr(clock, 'now', clock.now + seconds)))
    adapter = object.__new__(DoosanRobotAdapter)
    adapter.frame_id, adapter.tool_offset_m = 'c2_base', None
    adapter._srv = {name: SimpleNamespace(Request=SimpleNamespace) for name in (
        'MoveLine', 'MoveSplineTask', 'MoveStop', 'Ikin', 'GetSolutionSpace')}
    # std_msgs 없이도 spline 직렬화와 호출 선택을 검증한다.
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', SimpleNamespace(Float64MultiArray=SimpleNamespace))
    calls = []
    def call(endpoint, kind, request, timeout=5.):
        calls.append((endpoint, request))
        return SimpleNamespace(success=True)
    adapter._call = call
    adapter._motion_sample = lambda timeout: (ZERO[:], 1, 0)
    return adapter, clock, calls


def samples(adapter, values):
    remaining = iter(values)
    last = values[-1]
    def read(timeout):
        nonlocal last
        last = next(remaining, last)
        return last
    adapter._motion_sample = read


def fake_stop(adapter, confirmed=True):
    stops = []
    def stop(profile, deadline):
        stops.append(profile)
        return StepResult('SUCCEEDED' if confirmed else 'UNKNOWN',
                          observed_state={'stop_confirmed': confirmed})
    adapter.stop = stop
    return stops


def test_closed_spline_waits_for_excursion_and_settle(setup):
    ad, clock, calls = setup
    away = [10., 0., 0., 0., 0., 0.]
    samples(ad, [(ZERO, 1, 0)] * 3 + [(away, 2, 2), (ZERO, 1, 0)])
    r = ad.move_spline([posx_to_pose(ZERO), posx_to_pose(away), posx_to_pose(ZERO)],
                       'c2_base', PROFILE, 5., None)
    assert r.ok and clock.now >= .3
    assert r.observed_state['motion_started'] is True
    assert len(calls) == 1 and calls[0][0] == 'motion/move_spline_task'
    assert calls[0][1].sync_type == 1 and calls[0][1].pos_cnt == 3
    assert calls[0][1].opt == 0  # 1mm 미만 조각 구간에도 기본 속도 옵션 사용


def test_closed_spline_no_movement_cannot_succeed_or_resend(setup):
    ad, clock, calls = setup
    stops = fake_stop(ad)
    r = ad.move_spline([posx_to_pose([10., 0., 0., 0., 0., 0.]), posx_to_pose(ZERO)],
                       'c2_base', PROFILE, 4., None)
    assert r.outcome == 'UNKNOWN' and r.error_code == 'TIMEOUT'
    assert len(calls) == 1 and len(stops) == 1


def test_motion_flag_alone_does_not_complete_closed_spline(setup):
    ad, clock, calls = setup
    fake_stop(ad)
    samples(ad, [(ZERO, 1, 0), (ZERO, 2, 2), (ZERO, 1, 0)])
    r = ad.move_spline([posx_to_pose([10., 0., 0., 0., 0., 0.]), posx_to_pose(ZERO)],
                       'c2_base', PROFILE, 1., None)
    assert r.outcome == 'UNKNOWN'


def test_exact_same_line_target_confirms_stationary_without_send(setup):
    ad, clock, calls = setup
    r = ad.move(posx_to_pose(ZERO), 'c2_base', PROFILE, 1., None)
    assert r.ok and clock.now >= .2 and not calls
    assert r.observed_state['motion_started'] is False


def test_small_plunge_not_skipped_by_position_tolerance(setup):
    ad, clock, calls = setup
    target = [0., 0., .5, 0., 0., 0.]
    samples(ad, [(ZERO, 1, 0), (target, 1, 0)])
    r = ad.move(posx_to_pose(target), 'c2_base', {'vel_mm_s': 10., 'pos_tol_mm': 2.}, 1., None)
    assert r.ok and len(calls) == 1


def test_tcp_offset_applied_once_in_line_request(setup):
    ad, clock, calls = setup
    ad.tool_offset_m = [0., 0., .1]
    target_tcp = [0., 0., 100., 0., 0., 0.]
    samples(ad, [(ZERO, 1, 0), (target_tcp, 1, 0)])
    r = ad.move([0., 0., .2, 0., 0., 0., 1.], 'c2_base', PROFILE, 2., None)
    assert r.ok and calls[0][1].pos[2] == pytest.approx(100.)
    assert r.observed_state['tcp_pose'][2] == pytest.approx(.2)


@pytest.mark.parametrize('confirmed', [True, False])
def test_cancellation_requires_confirmed_stop(setup, confirmed):
    ad, clock, calls = setup
    cancel = threading.Event()
    stops = fake_stop(ad, confirmed)
    def read(timeout):
        cancel.set()
        return ZERO, 1, 0
    ad._motion_sample = read
    r = ad._wait_motion(ZERO, 2., cancel, 'move', .1, start=ZERO)
    assert r.outcome == ('STOPPED' if confirmed else 'UNKNOWN')
    assert r.observed_state['stop_confirmed'] == confirmed and len(stops) == 1


def test_orientation_mismatch_is_not_complete(setup):
    ad, clock, calls = setup
    fake_stop(ad)
    target = [10., 0., 0., 0., 0., 0.]
    ad._motion_sample = lambda timeout: ([10., 0., 0., 0., 0., 30.], 1, 0)
    r = ad._wait_motion(target, 1., None, 'move', .1, start=ZERO)
    assert not r.ok


def test_lost_ack_requests_stop_without_resend(setup):
    ad, clock, calls = setup
    stops = fake_stop(ad)
    def call(*args, **kwargs):
        calls.append(args)
        raise TimeoutError('응답 없음')
    ad._call = call
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 2., None)
    assert r.outcome == 'UNKNOWN' and len(calls) == len(stops) == 1


@pytest.mark.parametrize('motion', [1, 2])
def test_busy_robot_does_not_receive_next_motion(setup, motion):
    ad, clock, calls = setup
    ad._motion_sample = lambda timeout: (ZERO, 2, motion)
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 2., None)
    assert r.outcome == 'FAILED' and not calls


def test_stop_ack_is_not_stop_confirmation(setup):
    ad, clock, calls = setup
    ad._motion_sample = lambda timeout: (ZERO, 2, 2)
    r = ad.stop({'mode': 1}, .4)
    assert r.outcome == 'UNKNOWN' and r.observed_state['stop_confirmed'] is False


def test_stop_waits_for_position_and_orientation_settle(setup):
    ad, clock, calls = setup
    samples(ad, [(ZERO, 2, 2), ([0., 0., 0., 0., 0., 10.], 1, 0), (ZERO, 1, 0)])
    r = ad.stop({'mode': 1}, 1.)
    assert r.ok and clock.now >= .3 and r.observed_state['stop_confirmed'] is True


def test_ikin_uses_ros_services_and_preserves_degrees(setup):
    ad, clock, calls = setup
    def call(endpoint, kind, request, timeout=5.):
        calls.append((endpoint, request))
        return SimpleNamespace(success=True, sol_space=2, conv_posj=[1.] * 6)
    ad._call = call
    result = ad.inverse_kinematics(posx_to_pose([100., 0., 0., 0., 0., 0.]), None, [0.] * 6)
    assert result == [1.] * 6
    assert [p for p, _ in calls] == ['aux_control/get_solution_space', 'motion/ikin']
    assert calls[-1][1].pos[0] == 100. and calls[-1][1].sol_space == 2


def test_empty_motion_spline_rejected(setup):
    ad, clock, calls = setup
    r = ad.move_spline([posx_to_pose(ZERO)] * 3, 'c2_base', PROFILE, 2., None)
    assert r.outcome == 'FAILED' and not calls


@pytest.mark.parametrize('confirmed', [True, False])
def test_probe_uses_async_line_and_requires_actual_stop(setup, confirmed):
    ad, clock, calls = setup
    ad.posx = lambda *values: list(values)
    positions = iter([ZERO, [2., 0., 0., 0., 0., 0.]])
    ad._posx_now = lambda **kwargs: next(positions)
    forces = iter([[0., 0., 0.]] * 8 + [[-10., 0., 0.]])
    ad._force_vec = lambda **kwargs: next(forces)
    stops = fake_stop(ad, confirmed)
    r = ad.probe_touch([1., 0., 0.], .01,
                       {'touch_speed_mm_s': 1., 'touch_force_n': 1.}, 3., None)
    assert r.outcome == ('SUCCEEDED' if confirmed else 'UNKNOWN')
    assert r.observed_state['stop_confirmed'] == confirmed
    assert len(stops) == len(calls) == 1
    assert calls[0][0] == 'motion/move_line' and calls[0][1].sync_type == 1


def test_closed_spline_standby_jitter_is_not_motion_start(setup):
    ad, clock, calls = setup
    fake_stop(ad)
    samples(ad, [(ZERO, 1, 0), ([.04, 0., 0., 0., 0., 0.], 1, 0), (ZERO, 1, 0)])
    r = ad.move_spline([posx_to_pose([10., 0., 0., 0., 0., 0.]), posx_to_pose(ZERO)],
                       'c2_base', PROFILE, 1., None)
    assert r.outcome == 'UNKNOWN'


def test_probe_baseline_uses_remaining_budget_without_motion(setup):
    ad, clock, calls = setup
    budgets = []
    ad._posx_now = lambda **kwargs: ZERO[:]
    def force(timeout):
        budgets.append(timeout)
        clock.now += min(.2, timeout)
        if timeout <= .2:
            raise TimeoutError('조회 지연')
        return [0.] * 3
    ad._force_vec = force
    result = ad.probe_touch([1., 0., 0.], .01,
                           {'touch_speed_mm_s': 1., 'touch_force_n': 1.}, .5, None)
    assert result.outcome == 'UNKNOWN' and result.error_code == 'TIMEOUT'
    assert budgets == pytest.approx([.5, .3, .1])
    assert clock.now == pytest.approx(.5) and not calls


def test_probe_loop_timeout_stops_and_never_accepts_late_contact(setup):
    ad, clock, calls = setup
    ad._posx_now = lambda **kwargs: ZERO[:]
    count = [0]
    def force(timeout):
        count[0] += 1
        if count[0] > 8:
            clock.now += timeout
            raise TimeoutError('접촉 중 응답 지연')
        return [0.] * 3
    ad._force_vec = force
    stops = fake_stop(ad)
    result = ad.probe_touch([1., 0., 0.], .01,
                           {'touch_speed_mm_s': 1., 'touch_force_n': 1.}, .5, None)
    assert result.outcome == 'UNKNOWN' and result.error_code == 'TIMEOUT'
    assert result.observed_state == {'contact': False, 'stop_confirmed': True}
    assert clock.now == pytest.approx(.5) and len(stops) == len(calls) == 1


def test_probe_cancellation_during_baseline_never_dispatches(setup):
    ad, clock, calls = setup
    cancel = threading.Event()
    ad._posx_now = lambda **kwargs: ZERO[:]
    def force(timeout):
        cancel.set()
        return [0.] * 3
    ad._force_vec = force
    stops = fake_stop(ad)
    result = ad.probe_touch([1., 0., 0.], .01,
                           {'touch_speed_mm_s': 1., 'touch_force_n': 1.}, 1., cancel)
    assert result.outcome == 'STOPPED' and result.observed_state['stop_confirmed']
    assert not calls and len(stops) == 1


def test_repeated_completed_target_with_observation_noise_is_not_resent(setup):
    ad, clock, calls = setup
    target = [10., 0., 0., 0., 0., 0.]
    noisy = [10.002, 0., 0., 0., 0., 0.]
    samples(ad, [(ZERO, 1, 0), (noisy, 1, 0)])
    assert ad.move(posx_to_pose(target), 'c2_base', PROFILE, 2., None).ok
    assert ad.move(posx_to_pose(target), 'c2_base', PROFILE, 2., None).ok
    assert len(calls) == 1


def test_new_small_depth_after_completed_target_is_sent(setup):
    ad, clock, calls = setup
    assert ad.move(posx_to_pose(ZERO), 'c2_base', PROFILE, 1., None).ok
    target = [0., 0., .05, 0., 0., 0.]
    samples(ad, [(ZERO, 1, 0), (target, 2, 2), (target, 1, 0)])
    assert ad.move(posx_to_pose(target), 'c2_base', PROFILE, 2., None).ok
    assert len(calls) == 1


def test_unconfirmed_target_is_not_cached(setup):
    ad, clock, calls = setup
    fake_stop(ad)
    target = [10., 0., 0., 0., 0., 0.]
    assert not ad.move(posx_to_pose(target), 'c2_base', PROFILE, .5, None).ok
    samples(ad, [([10.002, 0., 0., 0., 0., 0.], 1, 0)])
    assert not ad.move(posx_to_pose(target), 'c2_base', PROFILE, .5, None).ok
    assert len(calls) == 2


@pytest.mark.parametrize('positions,forces,ok', [
    ([.5, 1., 2., 2.1], [2.5, 2.5, 2.5, 2.5], True),
    ([2., 2.2, 2.4], [0., 2.5, 2.5], True),
    ([.5, 1., 2., 3.], [2.5, 2.5, 0., 0.], False),
    ([2., 2.5, 3.], [0., 0., 0.], False),
    ([2.], [5.], False),
])
def test_dual_entry_requires_concurrent_position_and_force(setup, positions, forces, ok):
    ad, clock, calls = setup
    # 제어기 TCP에서 1mm 앞인 드릴 끝을 기준으로 목표를 판단한다.
    ad.tool_offset_m = [.001, 0., 0.]
    readings = iter([ZERO[:]] + [[x, 0., 0., 0., 0., 0.] for x in positions])
    ad._posx_now = lambda timeout: next(readings)
    force = iter([[0., 0., 0.]]*8 + [[-x, 0., 0.] for x in forces])
    ad._force_vec = lambda timeout: next(force)
    stops = []
    def stop(profile, deadline):
        stops.append(profile)
        return StepResult('SUCCEEDED', observed_state=dict(stop_confirmed=True,
                          tcp_pose=[positions[-1]/1000.+.001, 0., 0., 0., 0., 0., 1.]))
    ad.stop = stop
    result = ad.probe_touch([1., 0., 0.], .003,
        dict(touch_speed_mm_s=5., touch_force_n=2., hard_limit_n=4.5,
             entry_confirmation='force_and_position',
             entry_target_tip_pose=[.003, 0., 0., 0., 0., 0., 1.]), 5., None)
    assert result.ok is ok
    assert len(stops) == 1 and len(calls) == 1
    if ok:
        assert result.observed_state['force_ok'] is True
        assert result.observed_state['position_ok'] is True
        assert result.observed_state['entry_confirmed'] is True
        assert result.observed_state['tcp_pose'][0] >= .003
        assert calls[0][1].vel[0] == 5.


def _monitored_move(ad, failures, max_read_failures):
    """이동 중 힘 서비스가 failures 번 연속 실패한 뒤 정상으로 돌아오는 상황."""
    stops = fake_stop(ad)
    samples(ad, [(ZERO[:], 1, 0), ([5., 0., 0., 0., 0., 0.], 2, 1), ([10., 0., 0., 0., 0., 0.], 1, 0)])
    left = [failures]
    def force(timeout=5.):
        if left[0] > 0:
            left[0] -= 1
            raise TimeoutError('service aux_control/get_tool_force timed out')
        return [0., 0., 0.]
    ad._force_vec = force
    ad.log = SimpleNamespace(warn=lambda *a: None, info=lambda *a: None, error=lambda *a: None)
    profile = dict(PROFILE, air_monitor=dict(kind='AIR', bias=[0., 0., 0.], force_limit_n=15., samples=[], max_read_failures=max_read_failures))
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', profile, 20., None)
    return r, stops


def test_air_monitor_tolerates_brief_force_service_timeouts(setup):
    """9/22 return_x: 힘 서비스 2 s timeout 한 번에 이동을 정지시켰다. 허용 횟수 안이면 계속 감시하며 완료한다."""
    ad, clock, calls = setup
    r, stops = _monitored_move(ad, failures=2, max_read_failures=3)
    assert r.ok and stops == []


def test_air_monitor_stops_after_repeated_force_service_timeouts(setup):
    ad, clock, calls = setup
    r, stops = _monitored_move(ad, failures=10, max_read_failures=3)
    assert r.outcome == 'UNKNOWN' and r.error_code == 'COMMUNICATION_LOST' and len(stops) == 1


def test_no_start_then_confirmed_rejection_is_failed_not_unknown(setup):
    """9/22: 3 s 무동작 뒤 2 s 더 상태를 읽어 시작 위치·STANDBY 가 유지되면 '명령 미수락 확정'. 정지 요청·재전송 없음."""
    ad, clock, calls = setup
    stops = fake_stop(ad)
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 20., None)
    assert r.outcome == 'FAILED' and r.error_code == 'NOT_ACCEPTED'
    assert r.observed_state['at_start'] is True and stops == [] and len(calls) == 1


def test_no_start_then_late_motion_is_followed_to_completion(setup):
    """시작 관측을 놓쳤지만 재확인에서 움직임이 보이면 계속 기다려 완료한다."""
    ad, clock, calls = setup
    stops = fake_stop(ad)
    reads = [(ZERO[:], 1, 0)] * 70 + [([5., 0., 0., 0., 0., 0.], 2, 1)] * 3 + [([10., 0., 0., 0., 0., 0.], 1, 0)]
    samples(ad, reads)
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 20., None)
    assert r.ok and stops == [] and len(calls) == 1


def test_no_start_then_found_at_target_completes_without_resend(setup):
    ad, clock, calls = setup
    stops = fake_stop(ad)
    reads = [(ZERO[:], 1, 0)] * 65 + [([10., 0., 0., 0., 0., 0.], 1, 0)]
    samples(ad, reads)
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 20., None)
    assert r.ok and stops == [] and len(calls) == 1          # 재확인에서 목표 도달을 보면 재전송 없이 완료 (시작 관측 유무와 무관)


def test_motion_failure_releases_force_hold_before_stop_confirmation(setup):
    """9/23 실기: 순응 중 힘 상한 정지가 정착 실패로 UNKNOWN. 실패 처리에서 힘 유지를 먼저 해제하고 정지를 확인한다."""
    ad, clock, calls = setup
    order = []
    ad._hold_active = True
    ad.hold_normal_force_end = lambda deadline: (order.append('release'), StepResult('SUCCEEDED', observed_state={'force_released': True}))[1]
    ad.stop = lambda profile, deadline: (order.append('stop'), StepResult('SUCCEEDED', observed_state={'stop_confirmed': True}))[1]
    r = ad._motion_failure('FAILED', 'FORCE_LIMIT', '힘 상한', 'move_spline')
    assert order == ['stop', 'release', 'stop'] and r.outcome == 'FAILED' and r.observed_state['force_released'] is True   # 9/23: 정지 요청 → 해제 → 정지 확인
    ad._hold_active = True
    ad.hold_normal_force_end = lambda deadline: StepResult('UNKNOWN', 'STOP_UNCONFIRMED', '해제 실패', observed_state={'force_released': False})
    r = ad._motion_failure('FAILED', 'FORCE_LIMIT', '힘 상한', 'move_spline')
    assert r.outcome == 'UNKNOWN' and r.error_code == 'STOP_UNCONFIRMED'


def _flaky_motion_sample(ad, fail_calls):
    """이동 중 관측이 fail_calls 번 연속 실패한 뒤 정상으로 돌아오는 상황. 성공 시엔 이동 완료 위치를 준다."""
    seq = [(ZERO[:], 1, 0), ([5., 0., 0., 0., 0., 0.], 2, 1)]
    state = dict(calls=0)
    def read(timeout):
        state['calls'] += 1
        if 2 < state['calls'] <= 2 + fail_calls:
            raise TimeoutError('service aux_control/get_current_posx timed out')
        return seq[min(state['calls'], 2) - 1] if state['calls'] <= 2 else ([10., 0., 0., 0., 0., 0.], 1, 0)
    ad._motion_sample = read
    ad._srv.update(MovePause=SimpleNamespace(Request=SimpleNamespace), MoveResume=SimpleNamespace(Request=SimpleNamespace))
    ad.log = SimpleNamespace(warn=lambda *a: None, info=lambda *a: None, error=lambda *a: None)
    return state


def test_transient_pose_timeout_pauses_recovers_and_resumes_without_resend(setup):
    """9/23 실기: get_current_posx 1회 timeout 으로 CUT 이 끝났다. 이제 move_pause → 2 s 연속 정상 관측 → move_resume, 같은 명령 재전송 없음."""
    ad, clock, calls = setup
    stops = fake_stop(ad)
    _flaky_motion_sample(ad, fail_calls=3)
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 30., None)
    endpoints = [c[0] for c in calls]
    assert r.ok and stops == []
    assert endpoints == ['motion/move_line', 'motion/move_pause', 'motion/move_resume']


def test_pause_rejected_falls_back_to_stop(setup):
    ad, clock, calls = setup
    stops = fake_stop(ad)
    _flaky_motion_sample(ad, fail_calls=3)
    original = ad._call
    def call(endpoint, kind, request, timeout=5.):
        if endpoint == 'motion/move_pause':
            raise TimeoutError('pause timed out')
        return original(endpoint, kind, request, timeout)
    ad._call = call
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 30., None)
    assert r.outcome == 'UNKNOWN' and r.error_code == 'COMMUNICATION_LOST' and len(stops) == 1
    assert 'motion/move_resume' not in [c[0] for c in calls]


def test_no_recovery_within_window_stops(setup):
    ad, clock, calls = setup
    stops = fake_stop(ad)
    _flaky_motion_sample(ad, fail_calls=10_000)
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', PROFILE, 60., None)
    assert r.outcome == 'UNKNOWN' and len(stops) == 1 and '복구 안 됨' in r.message


def test_under_hold_compliance_creep_is_not_motion_start_and_tolerance_relaxed(setup):
    """9/23 실기: 힘 유지 중 순응 변위(0.3 mm)만 있고 제어기가 MOVING 이 아니면 '미수락' 으로 판정한다. 완료 허용은 hold_pos_tol_mm."""
    ad, clock, calls = setup
    stops = fake_stop(ad)
    ad._srv.update(MovePause=SimpleNamespace(Request=SimpleNamespace), MoveResume=SimpleNamespace(Request=SimpleNamespace))
    ad.log = SimpleNamespace(warn=lambda *a: None, info=lambda *a: None, error=lambda *a: None)
    ad._force_vec = lambda timeout=5.: [0., 0., 0.]
    creep = [([.3, .1, 0., 0., 0., 0.], 1, 0)] * 200
    samples(ad, [(ZERO[:], 1, 0)] + creep)
    prof = dict(PROFILE, hold_pos_tol_mm=2.0, contact_monitor=dict(kind='CUT', bias=[0., 0., 0.], force_limit_n=10., surface=[[0., 0., 0., 0., 0., 0., 1.]],
                                                                    normals=[[0., 0., 1.]], offset_range=[-.01, .01], ignore_normal=True, samples=[]))
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', prof, 30., None)
    assert r.error_code == 'NOT_ACCEPTED' and stops == []
    # 제어기가 MOVING 을 보고하고 목표 근처 1.5 mm(접선) 에서 멈추면 hold_pos_tol_mm 2.0 으로 완료
    samples(ad, [(ZERO[:], 1, 0), ([5., 0., 0., 0., 0., 0.], 2, 1), ([8.5, 0., 0., 0., 0., 0.], 1, 0)])
    r = ad.move(posx_to_pose([10., 0., 0., 0., 0., 0.]), 'c2_base', prof, 30., None)
    assert r.ok


def test_motion_diagnostics_explain_orientation_wait_without_extra_reads(setup):
    """자세만 미달인 정체를 1 Hz로 기록하고, 추가 서비스 조회·허용오차 완화를 하지 않는다."""
    import json
    ad, clock, calls = setup
    records = []
    ad.log = SimpleNamespace(info=lambda line: records.append((clock.now, json.loads(line.removeprefix('motion_diag ')))))
    stops = fake_stop(ad)
    reads = {'motion': 0, 'force': 0}
    target = [10., 0., 0., 0., 0., 0.]
    cur = [9., 0., 1.5, 0., 0., .228]
    def observe(timeout):
        reads['motion'] += 1
        return cur, (2 if reads['motion'] == 1 else 1), (1 if reads['motion'] == 1 else 0)
    def force(timeout):
        reads['force'] += 1
        return [0., 0., -2.]
    ad._motion_sample = observe
    ad._force_vec = force
    monitor = dict(kind='CUT', surface=[posx_to_pose(target)], normals=[[0., 0., 1.]],
                   offset_range=[-.01, .01], force_limit_n=10., ignore_normal=True)
    r = ad._wait_motion(target, 2.4, None, 'move_spline', 2., start=ZERO,
                        angle_tol_deg=.15, require_controller_start=True, monitor=monitor)
    assert r.error_code == 'TIMEOUT' and len(stops) == 1
    assert not calls and reads['motion'] == reads['force'] == len(monitor['samples'])
    assert len(records) == 3
    assert all(b[0] - a[0] >= 1. for a, b in zip(records, records[1:]))
    d = records[-1][1]
    assert d['robot_state'] == 1 and d['check_motion'] == 0
    assert d['false_conditions'] == ['orientation', 'stable']
    assert d['tangent_error_mm'] == 1. and d['normal_error_mm'] == 1.5
    assert d['normal_dev_mm'] == 1.5 and d['angle_error_deg'] == .228
    assert d['force_base_n'] == [0., 0., -2.] and d['force_bias_corrected_n'] == 2.
    assert d['stable_s'] == 0.


def test_motion_diagnostics_lifecycle_and_stable_wait(setup):
    """전송·응답·안정 대기·완료를 연결하고 힘을 조회하지 않는 이동은 null로 남긴다."""
    import json
    ad, clock, calls = setup
    records = []
    ad.log = SimpleNamespace(info=lambda line: records.append(json.loads(line.removeprefix('motion_diag '))))
    target = [10., 0., 0., 0., 0., 0.]
    samples(ad, [(ZERO, 1, 0), (target, 1, 0)])
    r = ad.move(posx_to_pose(target), 'c2_base', PROFILE, 2., None)
    assert r.ok and len(calls) == 1
    assert [d['event'] for d in records] == ['send', 'response', 'wait', 'wait_result']
    assert records[2]['false_conditions'] == ['stable']
    assert records[2]['force_base_n'] is None and records[2]['normal_dev_mm'] is None
    assert records[3]['outcome'] == 'SUCCEEDED'


def test_motion_diagnostics_logger_failure_does_not_change_result(setup):
    """진단 출력 실패가 성공 모션을 정지·실패로 바꾸면 안 된다."""
    ad, clock, calls = setup
    def broken_logger(line):
        raise RuntimeError('진단 출력 실패')
    ad.log = SimpleNamespace(info=broken_logger)
    target = [10., 0., 0., 0., 0., 0.]
    samples(ad, [(ZERO, 1, 0), (target, 1, 0)])
    r = ad.move(posx_to_pose(target), 'c2_base', PROFILE, 2., None)
    assert r.ok and len(calls) == 1


@pytest.mark.parametrize('hold,expected', [(True, 'SUCCEEDED'), (False, 'TIMEOUT')])
def test_hold_angle_tolerance_only_applies_to_force_controlled_cut(setup, hold, expected):
    """같은 0.21도 잔류 오차에서도 일반 이동은 0.15도 기준을 유지한다."""
    ad,clock,calls=setup
    fake_stop(ad)
    target=[10.,0.,0.,0.,0.,0.];cur=[10.,0.,0.,0.,0.,.21]
    samples(ad,[(ZERO,1,0),(cur,2,1),(cur,1,0)])
    ad._force_vec=lambda **kw:[0.,0.,0.]
    prof=dict(PROFILE,angle_tol_deg=.15,hold_angle_tol_deg=.3)
    if hold:
        prof['contact_monitor']=dict(kind='CUT',ignore_normal=True,surface=[posx_to_pose(target)],normals=[[0.,0.,1.]])
    r=ad.move(posx_to_pose(target),'c2_base',prof,1.,None)
    assert (r.outcome if r.ok else r.error_code)==expected


@pytest.mark.parametrize('value',[float('nan'),float('inf'),0.,-1.])
def test_invalid_hold_angle_tolerance_rejected_before_dispatch(setup,value):
    ad,clock,calls=setup
    prof=dict(PROFILE,hold_angle_tol_deg=value,contact_monitor=dict(kind='CUT',ignore_normal=True))
    r=ad.move(posx_to_pose([10.,0.,0.,0.,0.,0.]),'c2_base',prof,1.,None)
    assert r.error_code=='INVALID_INPUT' and not calls
