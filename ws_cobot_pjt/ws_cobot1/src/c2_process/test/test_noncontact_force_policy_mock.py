"""비접촉 안전 구간의 자세 의존 외력 정책 (9/23 CONTINUE/WARNING).

근거: 9/23 실기 12:43·14:27 두 번 모두 point_7_retract 에서 |F| 10.1 N 으로
전체 측정이 종료됐다. 당시 드릴 끝은 양초 표면 바깥 5.47 mm 에서 멀어지는
중이었고 서보 추종 오차는 0.07 mm 로 정상이었다. 접촉이 아니라 팔을 뻗은
자세의 외력 추정 오프셋이다. 실기 검증 아님.
"""
import json, math
from copy import deepcopy
from pathlib import Path

import pytest

from test_workpiece_guarded_flow_mock import Clock, KinematicIO, SimulatedGuardedAdapter
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece
from c2_process.measurement_robot_adapter import check_measurement_scene

CONFIG = Path(__file__).resolve().parents[1] / 'config/workpiece_real_trial_0921.json'


def run_case(*, label=None, extra_n=0., axis=0, tracking_mm=0., after_gap_m=.006,
             toward_candle=False, config_edit=None):
    """label step 이 이동 중일 때 base X 방향으로 extra_n 만큼 외력을 얹는다.

    실기처럼 드릴 끝이 표면을 벗어난 뒤(after_gap_m)부터 얹는다. 9/23 실기의
    FORCE_LIMIT 도 양초 표면 바깥 5.47 mm 에서 발생했다.
    """
    config = json.loads(CONFIG.read_text())
    w = config['workcell']; w['source_mode'] = 'SIMULATION'
    if config_edit:
        config_edit(config)
    clock = Clock(); io = KinematicIO(w, clock, True)
    io.center = list(w['seed_axis_xy_m']); io.radius = w['seed_radius_m']
    ctx = MeasurementContext('force-policy', 'prepare', 'SIMULATION', monotonic=clock)

    def ready(c):
        return dict(ownership_confirmed=True, control_authority=True,
                    measurement_id=c.measurement_id, checked_at_monotonic_s=clock())

    ad = SimulatedGuardedAdapter(io, w['tool_offset_m'], config['guards'], ready,
                                 check_measurement_scene, clock=clock, sleep=clock.sleep)
    logs = []; ad.trace = lambda e, d: logs.append((e, deepcopy(d)))
    raw_execute = ad.execute_measurement_step; raw_read = io.read
    active = {'label': None}

    def execute(step, *args):
        active['label'] = step['label']
        return raw_execute(step, *args)

    ad.execute_measurement_step = execute

    def read():
        result = raw_read()
        if label is None or active['label'] != label or not io.active:
            return result
        from c2_process.robot_adapter import posx_to_pose
        tip = posx_to_pose(result['posx'], w['tool_offset_m'])
        gap = math.dist(tip[:2], io.center) - io.radius
        if gap < after_gap_m and not toward_candle:
            return result
        if extra_n:
            result['force_n'] = list(result['force_n'])
            result['force_n'][axis] -= extra_n
        if tracking_mm:
            result['desired_posx'] = list(result['posx'])
            result['desired_posx'][2] += tracking_mm
        if toward_candle:
            # 드릴 끝이 양초 쪽으로 다가가는 것처럼 보이게 한다.
            result['posx'] = list(result['posx'])
            result['posx'][0] = io.center[0] * 1000. + 20.
            result['posx'][1] = io.center[1] * 1000.
        return result

    io.read = read
    result = measure_workpiece(ad, w, config['profiles'], ctx)
    return result, logs, ad, config


def warnings(logs):
    return [d for e, d in logs if e == 'force_warning']


# ------------------------------------------------ CONTINUE / WARNING ----
def test_posture_offset_on_retract_warns_and_finishes_eight_points():
    """실기 재현: retract 구간 10~15 N → 경고 기록 후 8점 완주."""
    r, logs, ad, c = run_case(label='point_2_retract', extra_n=11.)
    assert r.ok, (r.error_code, r.message)
    assert len(r.observed_state['measurement']['points']) == 8
    assert r.observed_state['home_return_confirmed']
    w = warnings(logs)
    assert w, '경고가 기록되어야 한다'
    assert all(x['label'] == 'point_2_retract' for x in w)
    assert all(x['norm_n'] >= c['profiles']['retract']['hard_force_n'] for x in w)
    assert all(x['norm_n'] < c['guards']['noncontact_hard_force_n'] for x in w)
    assert all(x['candle_gap_m'] >= c['workcell']['slow_retract_gap_m'] for x in w)
    assert all(x['tracking_error_mm'] <= c['guards']['line_error_mm'] for x in w)
    assert r.observed_state['force_warnings'], '결과 JSON 에 남아야 한다'


@pytest.mark.parametrize('label', ['point_2_outer', 'orbit'])
def test_fast_outward_profiles_already_tolerate_the_band(label):
    """outer/orbit 은 프로파일 한계가 이미 15 N 이라 경고 구간이 비어 있다.

    즉 비접촉 안전 구간의 실질 한계는 라벨과 무관하게 15 N 으로 통일된다.
    """
    r, logs, _, c = run_case(label=label, extra_n=11.)
    assert r.ok, (r.error_code, r.message)
    assert c['profiles'][c['workcell'].get('outer_move_profile', 'escape')
                         if label.endswith('_outer') else 'travel']['hard_force_n'] == 15.
    assert warnings(logs) == []          # 한계에 닿지 않았으므로 경고도 없다


@pytest.mark.parametrize('label', ['point_2_outer', 'orbit'])
def test_fast_outward_profiles_still_stop_above_the_ceiling(label):
    r, logs, *_ = run_case(label=label, extra_n=20.)
    assert not r.ok and r.error_code == 'FORCE_LIMIT'
    assert warnings(logs) == []


def test_result_payload_with_warnings_is_json_serialisable():
    r, *_ = run_case(label='point_2_retract', extra_n=11.)
    json.dumps(dict(outcome=r.outcome, error_code=r.error_code, message=r.message,
                    completed_step=r.completed_step, observed_state=r.observed_state),
               ensure_ascii=False, allow_nan=False)


# -------------------------------------------------------- HARD STOP ----
def test_above_the_absolute_ceiling_still_stops():
    r, logs, _, c = run_case(label='point_2_retract', extra_n=20.)
    assert not r.ok and r.error_code == 'FORCE_LIMIT'
    assert not warnings(logs)
    assert c['guards']['noncontact_hard_force_n'] == 15.


def test_probe_contact_segment_keeps_the_old_limit():
    """접촉이 예상되는 PROBE 구간은 경고로 낮추지 않는다."""
    r, logs, *_ = run_case(label='point_2_touch', extra_n=11.)
    assert not r.ok and r.error_code == 'FORCE_LIMIT'
    assert not warnings(logs)


def test_moving_toward_the_candle_keeps_the_old_limit():
    """양초 쪽으로 가는 approach 는 대상이 아니다."""
    r, logs, *_ = run_case(label='point_2_approach', extra_n=11.)
    assert not r.ok and r.error_code == 'FORCE_LIMIT'
    assert not warnings(logs)


def test_large_tracking_error_means_obstruction_not_offset():
    """힘 초과 + 서보가 못 따라감 = 막힘. 즉시 중단."""
    r, logs, *_ = run_case(label='point_2_retract', extra_n=11., tracking_mm=2.0)
    assert not r.ok and r.error_code in ('FORCE_LIMIT', 'PATH_DEVIATION')
    assert not warnings(logs)


def test_gap_decreasing_means_approaching_the_candle():
    """바깥 이동 라벨이라도 실제로 양초에 다가가면 경고로 낮추지 않는다."""
    r, logs, *_ = run_case(label='point_2_retract', extra_n=11., toward_candle=True)
    assert not r.ok
    assert not warnings(logs)


def test_without_the_setting_behaviour_is_unchanged():
    def edit(c): c['guards'].pop('noncontact_hard_force_n')
    r, logs, *_ = run_case(label='point_2_retract', extra_n=11., config_edit=edit)
    assert not r.ok and r.error_code == 'FORCE_LIMIT'
    assert not warnings(logs)


def test_ceiling_below_a_profile_limit_is_rejected():
    """상한이 어떤 이동 프로파일의 한계보다 낮으면 설정 오류로 거절한다."""
    def edit(c): c['guards']['noncontact_hard_force_n'] = 12.
    r, logs, *_ = run_case(label='point_2_retract', extra_n=11., config_edit=edit)
    assert not r.ok and r.error_code == 'INVALID_INPUT'
    assert '비접촉 구간 상한' in r.message


def test_normal_run_records_no_warning():
    r, logs, *_ = run_case()
    assert r.ok and len(r.observed_state['measurement']['points']) == 8
    assert warnings(logs) == [] and r.observed_state['force_warnings'] == []


# ------------------------------------------------- 실기 기록 회귀 고정 ----
FIXTURE = Path(__file__).resolve().parent / 'fixtures/force_limit_20260923.json'


@pytest.mark.parametrize('run', ['1243', '1427'])
def test_recorded_real_force_limit_is_classified_as_continue(run):
    """9/23 실기 두 번의 FORCE_LIMIT 순간을 그대로 판정기에 넣는다.

    둘 다 point_7_retract, |F| 약 10.1 N, 양초에서 멀어지는 중, 추종 오차 0.04~0.07 mm.
    seed 원통 기준 여유가 2.51 mm 밖에 안 되는 점에 주의 — seed 중심이 실측과
    2.6 mm 어긋나 있어서 넓은 여유대를 요구하면 이 사례가 걸러진다.
    """
    from c2_process.measurement_robot_adapter import GuardedMeasurementAdapter
    case = json.loads(FIXTURE.read_text())[run]
    config = json.loads(CONFIG.read_text())
    ad = GuardedMeasurementAdapter.__new__(GuardedMeasurementAdapter)
    ad.g = config['guards']; ad.workcell = config['workcell']
    ad.offset = config['workcell']['tool_offset_m']
    o = case['trigger']
    norm = math.hypot(o['force_n'][0], math.hypot(o['force_n'][1], o['force_n'][2]))
    assert norm >= config['profiles']['retract']['hard_force_n']
    assert norm < config['guards']['noncontact_hard_force_n']
    previous_gap = (math.dist(case['previous_tip'][:2], config['workcell']['seed_axis_xy_m'])
                    - config['workcell']['seed_radius_m'])
    verdict = ad._noncontact_force_verdict({'kind': case['kind'], 'label': case['label']},
                                           o, norm, previous_gap)
    assert verdict is not None, '실기 사례가 HARD STOP 으로 분류되면 안 된다'
    assert verdict['candle_gap_m'] > previous_gap          # 멀어지는 중
    assert verdict['tracking_error_mm'] <= config['guards']['line_error_mm']


@pytest.mark.parametrize('run', ['1243', '1427'])
def test_recorded_case_stops_if_it_were_approaching_the_candle(run):
    """같은 힘이라도 양초 쪽으로 가고 있었다면 중단이어야 한다."""
    from c2_process.measurement_robot_adapter import GuardedMeasurementAdapter
    case = json.loads(FIXTURE.read_text())[run]
    config = json.loads(CONFIG.read_text())
    ad = GuardedMeasurementAdapter.__new__(GuardedMeasurementAdapter)
    ad.g = config['guards']; ad.workcell = config['workcell']
    ad.offset = config['workcell']['tool_offset_m']
    o = case['trigger']
    norm = math.hypot(o['force_n'][0], math.hypot(o['force_n'][1], o['force_n'][2]))
    far = ad._candle_gap(o) + .010          # 직전이 10 mm 더 바깥 = 다가오는 중
    assert ad._noncontact_force_verdict({'kind': case['kind'], 'label': case['label']},
                                        o, norm, far) is None
