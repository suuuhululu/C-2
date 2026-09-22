"""접촉 실행기와 고정 경로 실행기의 교체 경계. 실제 로봇을 사용하지 않는다."""
import copy
import inspect
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c2_process import engraving, run_fixed_path_trial as fixed
from c2_process.robot_adapter import StepResult
from test_execution_plan import inputs, Recorder, motion_calls


def test_same_public_call_signature():
    assert inspect.signature(fixed.execute_path) == inspect.signature(engraving.execute_path)


@pytest.mark.parametrize('entry', [fixed.execute_path, engraving.execute_path])
def test_fixed_route_no_touch_and_no_double_depth(entry):
    path, ctx = inputs()
    unchanged = copy.deepcopy(path)
    ad = Recorder()
    events = []
    ad.probe_touch = lambda *args: pytest.fail('고정 경로에서 접촉 탐색 금지')
    result = entry(path, ctx, events.append, ad)
    expected = [p for s in engraving.build_execution_plan(path, ctx)['segments'] for p in s['waypoints']]
    assert result.ok and ad.sent == ad.ik_points == expected
    assert path == unchanged and result.observed_state['touches'] == []
    assert result.observed_state['execution_mode'] == 'FIXED_PATH_REPLAY'
    assert result.observed_state['contact_verified'] is False
    assert result.observed_state['engraving_quality_verified'] is False
    assert events[-1]['completed_segment_id'] == 'retract'


def test_force_touch_keeps_original_executor_and_fixed_refuses_silent_conversion():
    path, ctx = inputs('force_touch')
    ad = Recorder()
    original = copy.deepcopy(ctx.tool_profile)
    rejected = fixed.execute_path(path, ctx, adapter=ad)
    assert rejected.error_code == 'UNSUPPORTED_RECIPE' and not ad.calls
    result = engraving.execute_path(path, ctx, adapter=ad)
    assert result.ok and any(c['fn'] == 'probe_touch' for c in ad.calls)
    assert ctx.tool_profile == original


def test_failure_does_not_switch_executor_or_send_retract():
    path, ctx = inputs()
    ad = Recorder()
    ad.move_spline = lambda *args: StepResult('UNKNOWN', 'TIMEOUT', observed_state={'stop_confirmed': False})
    result = fixed.execute_path(path, ctx, adapter=ad)
    assert result.outcome == 'UNKNOWN' and result.observed_state['stop_confirmed'] is False
    assert result.observed_state['last_completed_segment_id'] == 'approach'
    assert len(ad.sent) == 2 and result.observed_state['engraving_progress'] == 0.


def test_cancel_feedback_blocks_next_motion():
    path, ctx = inputs()
    ad = Recorder()
    result = fixed.execute_path(path, ctx, lambda _: ctx.cancel.set(), ad)
    assert result.outcome == 'STOPPED' and not motion_calls(ad)


def test_mode_switch_after_plan_check_invalidates_signature():
    path, ctx = inputs('force_touch')
    ctx.checked_plan_signature = engraving.execution_signature(path, ctx)
    ctx.tool_profile['contact_mode'] = 'fixed_depth'
    ad = Recorder()
    result = fixed.execute_path(path, ctx, adapter=ad)
    assert result.error_code == 'PROFILE_MISMATCH' and not motion_calls(ad)


def test_unknown_send_stops_without_resending():
    path, ctx = inputs()
    ad = Recorder()
    sent, stops = [], []
    def send(*args):
        sent.append(args)
        raise TimeoutError('응답 유실')
    def stop(*args):
        stops.append(args)
        return StepResult('SUCCEEDED', observed_state={'stop_confirmed': True})
    ad.move = send
    ad.stop = stop
    result = fixed.execute_path(path, ctx, adapter=ad)
    assert result.outcome == 'UNKNOWN' and result.observed_state['stop_confirmed'] is True
    assert len(sent) == len(stops) == 1
