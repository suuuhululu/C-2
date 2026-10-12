"""This new extrapolation must preserve the live grasp and stop above the target."""
import importlib.util
import json
from pathlib import Path
import time

import pytest

spec = importlib.util.spec_from_file_location('onsite_prepare', Path(__file__).with_name('prepare_approach.py'))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
from app.assembly_step_bridge import build_plan
from app.assembly_step_runner import StepReplayDriver
from app.control_session import ControlSession, validate_execution
from app.control_driver import execute_step
from scripts.robot_control_trial import test_session as synthetic_session


def execute(confirm, *, different_reference=False):
    setup = helper.prepare_candidate()
    plan = build_plan(setup['step'], setup['d_profile'])
    raw = StepReplayDriver(plan['settings']['reference_pose'])
    ready = json.loads((helper.DIRECTORY/'readiness.json').read_text())
    raw.value.update(ready['samples'][-1])
    initial = raw.value['posx'].copy()
    if different_reference:
        plan['settings']['reference_pose'][3:] = [69., -177., 70.]
    ticks, trace = [0.], []
    clock = lambda: ticks[0]
    def sleep(seconds): ticks[0] += seconds
    def record(event, data): trace.append((event, data))
    s = synthetic_session(plan)
    s['stillness'] = helper.STILLNESS.copy()
    session = ControlSession(s, plan, record, clock=clock, wall=time.time)
    result = execute_step(raw, session, dict(tcp='GripperDA_v4', tool='ToolWeight0'),
        plan, setup['d_profile'], lambda *a: confirm, record,
        phase='approach', start_zone='assembly', clock=clock, sleep=sleep)
    return setup, raw, initial, result


def test_local_trial_coordinate_mapping():
    setup = helper.prepare_candidate()
    plan = build_plan(setup['step'], setup['d_profile'])
    assert plan['trial_footprint']['min_xy'] == [12, 1]
    assert plan['block']['layer'] == 5 and plan['block']['color'] == 'yellow'
    assert setup['source_execution_allowed'] is False
    assert setup['current_grasp_transform_verified'] is False


def test_experimental_parameters_require_explicit_review():
    with pytest.raises(ValueError, match='EXPLICIT_STILLNESS'):
        helper.make_session(helper.prepare_candidate(), stillness_reviewed=False)


def test_each_preparation_has_fresh_execution_and_epoch():
    setup = helper.prepare_candidate()
    a, sa = helper.make_session(setup, stillness_reviewed=True)
    b, sb = helper.make_session(setup, stillness_reviewed=True)
    assert sa['execution_id'] != sb['execution_id'] and sa['source_epoch'] != sb['source_epoch']
    assert sa['current_revision'] is None and sa['physical_verified'] is False
    assert a['physical_verified'] is False
    assert setup['d_profile']['physical_route_reviewed'] is False


def test_approach_session_does_not_authorize_contact_or_release():
    setup, session = helper.make_session(helper.prepare_candidate(), stillness_reviewed=True)
    plan = build_plan(setup['step'], setup['d_profile'])
    validate_execution(plan, setup['d_profile'], session, 'approach')
    with pytest.raises(ValueError, match='ALIGNMENT'):
        validate_execution(plan, setup['d_profile'], session, 'contact')
    with pytest.raises(ValueError, match='RELEASE_WIDTH'):
        validate_execution(plan, setup['d_profile'], session, 'release')


def test_zero_turn_preserves_live_abc_even_when_old_reference_differs():
    setup, raw, initial, result = execute(True, different_reference=True)
    assert result['status'] == 'PAUSED_APPROACH_REACHED'
    assert all(pose[3:] == pytest.approx(initial[3:]) for pose in raw.moves)
    assert raw.value['posx'][:2] == pytest.approx(setup['reference_pose'][:2])
    assert raw.value['posx'][2] == pytest.approx(setup['approach_z_mm'])
    assert min(pose[2] for pose in raw.moves) >= setup['approach_z_mm']
    assert raw.grips == [] and result['assembly_completion'] is False


def test_start_rejection_sends_no_move_or_gripper_command():
    _, raw, _, result = execute(False)
    assert result['status'] == 'PAUSED_START' and raw.moves == [] and raw.grips == []


def test_bad_grasp_feedback_cannot_prepare_trial(tmp_path):
    for name in ('held-target.candidate.json', 'readiness.json', 'ik-check.json'):
        value = json.loads((helper.DIRECTORY/name).read_text())
        if name == 'readiness.json': value['samples'][-1]['gripper_status'] = 0
        (tmp_path/name).write_text(json.dumps(value))
    with pytest.raises(ValueError, match='HELD_STOPPED'):
        helper.prepare_candidate(tmp_path)


def test_declining_parameter_review_creates_no_session_or_connection(monkeypatch, tmp_path):
    setup = helper.prepare_candidate()
    monkeypatch.setattr(helper, 'DIRECTORY', tmp_path)
    monkeypatch.setattr(helper, 'prepare_candidate', lambda: setup)
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    monkeypatch.setattr(helper.sys, 'argv', ['prepare_approach.py', '--run'])
    monkeypatch.setattr(helper.subprocess, 'run', lambda *a, **k: pytest.fail('device CLI must not start'))
    assert helper.main() == 1 and list(tmp_path.iterdir()) == []
