"""이동 step 의 제한된 자동 복구(R1 PATH_DEVIATION · R2 MOTION_INCOMPLETE) 시험.

9/23 실기(console_20260923_122137)의 신호를 재현한다: 제어기 지시 TCP 는 계획
선분 위에 있고 실제 TCP 만 서보 추종 오차로 벗어난 경우. 실기 검증 아님.
허용 오차(line_error_mm 0.5)는 그대로 두고 반응만 바꾼 것을 확인한다.
"""
import json, math
from copy import deepcopy
from pathlib import Path

import pytest

from test_workpiece_guarded_flow_mock import Clock, KinematicIO, SimulatedGuardedAdapter
from c2_process.workpiece_calibration import (MeasurementContext, MeasurementError, MoveRecoveryError,
                                              build_side_plan, measure_workpiece)
from c2_process.measurement_robot_adapter import check_measurement_scene

CONFIG = Path(__file__).resolve().parents[1] / 'config/workpiece_real_trial_0921.json'
TARGET_LABEL = 'point_2_approach'


def run_case(*, offset_mm=0., axis=2, also_desired=False, forever=False,
             label=TARGET_LABEL, post_move_drift_mm=0., config_edit=None):
    """offset_mm: 실제 TCP 에만 주는 추종 오차. also_desired 면 지시 TCP 까지 함께 민다.

    post_move_drift_mm: 이동 완료·정지 확인 뒤에 목표에서 벗어난 상태 (R2 재현).
    """
    config = json.loads(CONFIG.read_text())
    w = config['workcell']; w['source_mode'] = 'SIMULATION'
    if config_edit:
        config_edit(config)
    clock = Clock(); io = KinematicIO(w, clock, True)
    io.center = list(w['seed_axis_xy_m']); io.radius = w['seed_radius_m']
    ctx = MeasurementContext('move-recovery', 'prepare', 'SIMULATION', monotonic=clock)

    def ready(c):
        return dict(ownership_confirmed=True, control_authority=True,
                    measurement_id=c.measurement_id, checked_at_monotonic_s=clock())

    ad = SimulatedGuardedAdapter(io, w['tool_offset_m'], config['guards'], ready,
                                 check_measurement_scene, clock=clock, sleep=clock.sleep)
    logs = []; ad.trace = lambda event, data: logs.append((event, deepcopy(data)))
    attempts = {}; raw_execute = ad.execute_measurement_step; raw_read = io.read
    raw_observe = ad.observe_measurement
    active = {'label': None}; drift = {'on': False}

    def execute(step, *args):
        drift['on'] = False
        active['label'] = step['label']
        attempts[step['label']] = attempts.get(step['label'], 0) + 1
        result = raw_execute(step, *args)
        if post_move_drift_mm and step['label'] == label and (forever or attempts[label] == 1):
            # 이동/정지는 정상으로 끝났는데 그 뒤 관측에서 목표를 벗어나 있는 상태 (R2).
            drift['on'] = True
        return result

    def observe():
        o = raw_observe()
        if drift['on']:
            o = deepcopy(o)
            o['tip_pose'] = list(o['tip_pose'])
            o['tip_pose'][axis] += post_move_drift_mm / 1000.
        return o

    ad.observe_measurement = observe

    ad.execute_measurement_step = execute

    def read():
        result = raw_read()
        if active['label'] != label:
            return result
        if not forever and attempts.get(label, 0) != 1:
            return result   # 첫 시도에만 주입. 재시도는 정상 추종.
        if post_move_drift_mm or not io.active:
            return result
        result['posx'] = list(result['posx'])
        result['posx'][axis] += offset_mm
        if also_desired:
            result['desired_posx'] = list(result['posx'])
        return result

    io.read = read
    result = measure_workpiece(ad, w, config['profiles'], ctx)
    return result, logs, attempts, config


def verdicts(logs):
    return [d for e, d in logs if e == 'move_deviation_verdict']


# ---------------------------------------------------------------- R1 ----
def test_transient_tracking_error_recovers_and_finishes_eight_points():
    """실기 0.504 mm 와 같은 형태: 지시 TCP 는 선분 위, 실제만 벗어남."""
    r, logs, attempts, _ = run_case(offset_mm=.6)
    assert r.ok, (r.error_code, r.message)
    assert len(r.observed_state['measurement']['points']) == 8
    assert r.observed_state['home_return_confirmed']
    # 같은 step 을 한 번 더 실행했고 그 뒤 계획이 끝까지 진행됐다.
    assert attempts[TARGET_LABEL] == 2
    assert [e['attempts'] for e in r.observed_state['move_recoveries']] == [1]
    verdict = verdicts(logs)
    assert len(verdict) == 1 and verdict[0]['label'] == TARGET_LABEL
    assert verdict[0]['line_error_mm'] > .5                 # 감지 기준은 그대로 동작
    assert verdict[0]['desired_line_error_mm'] <= .5        # 명령 경로는 정상
    assert verdict[0]['tracking_error_mm'] <= verdict[0]['hard_limit_mm']


def test_recovery_event_is_reported_with_existing_stage_names():
    r, logs, _, _ = run_case(offset_mm=.6)
    events = [e for e in r.observed_state['events'] if '복구' in e['message']]
    assert len(events) == 1
    baseline, *_ = run_case(offset_mm=.4)          # 복구가 일어나지 않는 같은 계획
    known = {e['stage'] for e in baseline.observed_state['events']}
    assert events[0]['stage'] in known, '복구 때문에 새 stage 가 생기면 안 된다'
    assert {e['stage'] for e in r.observed_state['events']} <= known
    assert events[0]['values']['reason'] == 'PATH_DEVIATION'
    assert events[0]['values']['attempt'] == 1


def test_commanded_path_off_line_is_not_recoverable():
    """제어기 명령 자체가 선분을 벗어나면 계획/충돌 보증이 깨진 것이므로 즉시 중단."""
    r, logs, attempts, _ = run_case(offset_mm=.6, also_desired=True)
    assert not r.ok and r.error_code == 'PATH_DEVIATION'
    assert '지시 TCP 자체가 선분 이탈' in r.message
    assert attempts[TARGET_LABEL] == 1
    assert r.observed_state['stop_confirmed']


def test_deviation_beyond_hard_limit_stops_immediately():
    r, logs, attempts, _ = run_case(offset_mm=4., forever=True)
    assert not r.ok and r.error_code == 'PATH_DEVIATION'
    assert '즉시 중단 한계' in r.message
    assert attempts[TARGET_LABEL] == 1


def test_persistent_tracking_error_stops_after_max_attempts():
    r, logs, attempts, config = run_case(offset_mm=.6, forever=True)
    assert not r.ok and r.error_code == 'RECOVERY_REQUIRED'
    assert attempts[TARGET_LABEL] == config['workcell']['move_recovery_max_attempts'] == 3
    assert r.observed_state['stop_confirmed']


def test_single_attempt_setting_keeps_old_fatal_behaviour():
    def edit(c): c['workcell']['move_recovery_max_attempts'] = 1
    r, _, attempts, _ = run_case(offset_mm=.6, config_edit=edit)
    assert not r.ok and r.error_code == 'PATH_DEVIATION'
    assert attempts[TARGET_LABEL] == 1


def test_detection_threshold_is_unchanged():
    """0.5 mm 를 넘지 않는 추종 오차는 예전처럼 아무 일도 일어나지 않는다."""
    r, logs, attempts, config = run_case(offset_mm=.4)
    assert r.ok and len(r.observed_state['measurement']['points']) == 8
    assert attempts[TARGET_LABEL] == 1
    assert verdicts(logs) == [] and r.observed_state['move_recoveries'] == []
    assert config['guards']['line_error_mm'] == .5


def test_hard_limit_requires_a_configured_value():
    def edit(c): c['guards'].pop('hard_line_error_mm')
    r, _, attempts, _ = run_case(offset_mm=.6, config_edit=edit)
    assert not r.ok and r.error_code == 'PATH_DEVIATION'
    assert '즉시 중단 한계 미설정' in r.message


def test_hard_limit_must_not_be_below_the_detection_limits():
    def edit(c): c['guards']['hard_line_error_mm'] = .4
    with pytest.raises(ValueError, match='hard_line_error_mm'):
        run_case(offset_mm=.6, config_edit=edit)


# ---------------------------------------------------------------- R2 ----
def test_motion_incomplete_recovers_and_finishes_eight_points():
    r, logs, attempts, _ = run_case(post_move_drift_mm=.8)
    assert r.ok, (r.error_code, r.message)
    assert len(r.observed_state['measurement']['points']) == 8
    assert attempts[TARGET_LABEL] == 2
    events = [e for e in r.observed_state['events'] if '복구' in e['message']]
    assert len(events) == 1 and events[0]['values']['reason'] == 'MOTION_INCOMPLETE'
    assert events[0]['values']['evidence']['position_error_m'] > 0


def test_motion_incomplete_stops_after_max_attempts():
    r, _, attempts, _ = run_case(post_move_drift_mm=.8, forever=True)
    assert not r.ok and r.error_code == 'RECOVERY_REQUIRED'
    assert attempts[TARGET_LABEL] == 3


# ------------------------------------------- hard limit vs scene_check ----
def test_hard_line_limit_is_well_inside_the_geometric_margin():
    """3.0 mm 가 scene_check 보다 먼저 불필요하게 막는 조건이 아닌지 확인한다.

    선분 감시(PATH_DEVIATION)는 MOVE 구간에만 적용된다. 그 구간들의 도구~양초
    최소 여유보다 hard cutoff 가 충분히 작아야, 3.0 mm 이하의 이탈이 애초에
    충돌 영역에 닿지 못하고 판단권은 계속 현장 검사에 남는다.
    """
    config = json.loads(CONFIG.read_text())
    w = config['workcell']; w['source_mode'] = 'SIMULATION'
    plan = build_side_plan(w, .215)
    moves = [s for s in plan if s['kind'] == 'MOVE']
    from c2_process.robot_adapter import pose_to_posx
    state = dict(posx=pose_to_posx(plan[0]['target_pose'], w['tool_offset_m']))
    report = check_measurement_scene(moves, w, state)
    margin_mm = report['min_model_shaft_gap_m'] * 1000
    hard = config['guards']['hard_line_error_mm']
    assert margin_mm == pytest.approx(9.05, abs=.01)
    assert hard < margin_mm, f'hard cutoff {hard} mm 가 MOVE 최소 여유 {margin_mm} mm 보다 크다'
    # 접촉 구간은 선분 감시가 아니라 더 좁은 probe 감시(pose_tolerance)가 맡는다.
    assert w['pose_tolerance_m'] * 1000 < hard


def test_probe_steps_are_not_governed_by_the_line_monitor():
    """PROBE 는 hard cutoff 와 무관하게 종전 횡오차 감시를 그대로 쓴다."""
    r, logs, _, config = run_case(offset_mm=.6)
    assert r.ok
    assert all(d['label'].endswith('_approach') or d['label'] in ('orbit', 'side_entry')
               for d in verdicts(logs))


def test_recovery_replan_is_rechecked_by_scene_check():
    """복구 재실행도 preflight/scene_check 를 그대로 다시 거친다."""
    r, logs, _, _ = run_case(offset_mm=.6)
    assert r.ok
    scene_calls = [d for e, d in logs if e == 'command']
    assert scene_calls, '복구 후에도 검사된 명령만 나간다'
    # plans 항목은 run() 이 preflight 를 통과할 때마다 한 건씩 쌓인다.
    assert len(r.observed_state['plans']) >= 3


def emit(result):
    """workpiece_test_node.emit / ROS String 발행과 같은 방식으로 직렬화한다."""
    from dataclasses import asdict
    return json.dumps(asdict(result), ensure_ascii=False, allow_nan=False)


def bad_keys(node, path='observed_state'):
    """dict 키 중 JSON 이 받지 못하는 것(tuple 등)을 전부 찾아낸다."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if not isinstance(k, (str, int, float, bool)) and k is not None:
                found.append((path, type(k).__name__, repr(k)))
            found += bad_keys(v, f'{path}.{k}')
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            found += bad_keys(v, f'{path}[{i}]')
    return found


def test_payload_is_serialisable_when_no_recovery_happens():
    """복구가 한 번도 없는 경우."""
    r, _, attempts, _ = run_case(offset_mm=.4)
    assert r.ok and attempts[TARGET_LABEL] == 1
    assert r.observed_state['move_recoveries'] == []
    assert bad_keys(r.observed_state) == []
    assert json.loads(emit(r))['observed_state']['move_recoveries'] == []


def test_payload_is_serialisable_when_recovery_happens():
    """복구가 있는 경우. 9/23 12:43 실기에서 여기서 TypeError 가 나 7점 결과를 잃었다."""
    r, _, attempts, _ = run_case(offset_mm=.6)
    assert r.ok and attempts[TARGET_LABEL] == 2
    assert bad_keys(r.observed_state) == [], r.observed_state['move_recoveries']
    restored = json.loads(emit(r))['observed_state']['move_recoveries']
    assert len(restored) == 1
    entry = restored[0]
    assert entry['label'] == TARGET_LABEL
    assert entry['attempts'] == 1
    assert entry['reasons'] == ['PATH_DEVIATION']
    assert len(entry['target_pose_m']) == 7 and all(isinstance(v, float) for v in entry['target_pose_m'])


def test_failure_payload_is_serialisable():
    """복구 한도 초과로 실패한 경우도 결과가 나가야 한다."""
    r, _, _, _ = run_case(offset_mm=.6, forever=True)
    assert not r.ok and r.error_code == 'RECOVERY_REQUIRED'
    assert bad_keys(r.observed_state) == []
    entry = json.loads(emit(r))['observed_state']['move_recoveries'][0]
    assert entry['attempts'] == 3 and entry['reasons'] == ['PATH_DEVIATION'] * 3


def test_motion_incomplete_recovery_is_also_serialisable():
    r, _, _, _ = run_case(post_move_drift_mm=.8)
    assert r.ok and bad_keys(r.observed_state) == []
    entry = json.loads(emit(r))['observed_state']['move_recoveries'][0]
    assert entry['reasons'] == ['MOTION_INCOMPLETE']


def test_point_attempts_keeps_its_existing_shape():
    """기존 계약. int 키는 JSON 이 문자열로 바꿔주므로 깨지지 않는다."""
    r, *_ = run_case(offset_mm=.6)
    assert all(isinstance(k, int) for k in r.observed_state['point_attempts'])
    json.loads(emit(r))


def test_move_recovery_error_is_still_a_measurement_error():
    """세은님 쪽 except MeasurementError 계약이 깨지지 않는다."""
    assert issubclass(MoveRecoveryError, MeasurementError)
