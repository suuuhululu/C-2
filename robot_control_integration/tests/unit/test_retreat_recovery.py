"""Open-tool recovery uses only one bounded vertical lift, with no gripper writes."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import time

import pytest

from app.assembly_step_bridge import build_plan, validate_physical
from app.assembly_step_runner import StepReplayDriver
from app.control_driver import execute_step
from app.control_session import ControlSession, validate_execution
from scripts.robot_control_trial import main, test_session as synthetic_session

spec = importlib.util.spec_from_file_location('onsite_retreat', Path(__file__).resolve().parents[2]/
    'settings/onsite_12_1_l5_20261011/prepare_retreat.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
CONNECTION = dict(tcp='GripperDA_v4', tool='ToolWeight0')


@pytest.fixture(autouse=True)
def archived_readonly_evidence(tmp_path, monkeypatch):
    # Historical read-only sample is a fixture, never a new physical execution grant.
    fixture = json.loads((Path(__file__).resolve().parents[2]/
                         'fixtures/retreat_recovery_readonly.json').read_text())
    directory = tmp_path/'logs/release-recovery-doctor-20261011'
    directory.mkdir(parents=True)
    (directory/'trial-fixture.jsonl').write_text(json.dumps(fixture['sample'])+'\n')
    monkeypatch.setattr(helper, 'ROOT', tmp_path)


def make_state():
    value = helper.prepare_candidate()
    profile = value['d_profile']
    plan = build_plan(value['step'], profile)
    raw = StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(posx=plan['settings']['recovery_start_pose'].copy(), gripper_status=0, gripper_width_mm=64.2)
    events, ticks = [], [0.]
    def record(e, d): events.append((e, deepcopy(d)))
    clock = lambda: ticks[0]
    def sleep(seconds): ticks[0] += seconds
    session = ControlSession(synthetic_session(plan), plan, record, clock=clock, wall=time.time)
    return profile, plan, raw, session, events, clock, sleep


def execute(state, answer=lambda *args: True):
    profile, plan, raw, session, _, clock, sleep = state
    return execute_step(raw, session, CONNECTION, plan, profile, answer, session.record,
                        phase='retreat', clock=clock, sleep=sleep)


def test_one_vertical_lift_preserves_xy_abc_with_zero_gripper_or_contact():
    state = make_state()
    _, _, raw, session, events, _, _ = state
    start = raw.value['posx'].copy()
    result = execute(state)
    assert len(raw.moves) == 1 and not raw.grips and raw.stops == 0
    target = raw.moves[0]
    assert target[:2] == start[:2] and target[3:] == start[3:]
    assert target[2] == pytest.approx(110.29197845458984)
    assert target[2]-start[2] == pytest.approx(20.557939147949218)
    assert result['status'] == 'RECOVERY_RETREAT_COMPLETE'
    assert not result['assembly_completion'] and not result['current_update']
    assert not result['physical_verified'] and not result['backend_current_committed']
    assert session.lease is None and not session.request
    assert not any(e in ('GRIPPER_REQUEST', 'PRESS_SESSION') for e, _ in events)
    move = next(d for e, d in events if e == 'MOVE_REQUEST')
    assert move['velocity'] == [2., 2.] and move['acceleration'] == [1., 1.]
    assert move['segment'] == 'LIFT'


def test_hmi_hold_starts_no_motion():
    state = make_state()
    assert execute(state, lambda *args: False)['status'] == 'PAUSED_START'
    assert not state[2].moves and not state[2].grips


@pytest.mark.parametrize('change', [
    {'gripper_status': 2}, {'gripper_status': 1}, {'gripper_width_mm': 40.4},
    {'gripper_width_mm': 110.1}, {'tcp': 'wrong'}, {'query_duration_s': .6},
    {'motion_status': 1}, {'wrench': [0., 0., 36., 0., 0., 0.]},
])
def test_invalid_start_never_moves_or_opens(change):
    state = make_state()
    state[2].value.update(change)
    with pytest.raises((RuntimeError, TimeoutError)):
        execute(state)
    assert not state[2].moves and not state[2].grips


def test_pose_changed_before_confirmation_blocks_recovery():
    state = make_state()
    state[2].value['posx'][0] += 1.
    with pytest.raises(RuntimeError, match='RECOVERY_START_POSE_CHANGED'):
        execute(state)
    assert not state[2].moves and not state[2].grips


def test_pose_changed_during_hmi_is_checked_again():
    state = make_state()
    def answer(*args):
        state[2].value['posx'][2] += 1.
        return True
    with pytest.raises(RuntimeError, match='RECOVERY_START_POSE_CHANGED'):
        execute(state, answer)
    assert not state[2].moves and not state[2].grips


def test_stop_during_hmi_cancels_without_motion_or_gripper():
    state = make_state()
    def answer(*args):
        state[3].request_stop()
        return True
    with pytest.raises(RuntimeError, match='STOP_REQUESTED'):
        execute(state, answer)
    assert not state[2].moves and not state[2].grips


@pytest.mark.parametrize('height', [89., 150.])
def test_downward_or_excessive_recovery_profile_is_rejected(height):
    value = helper.prepare_candidate()
    profile = value['d_profile']
    profile['clearance_z_mm'] = height
    profile['steps'][value['step']['case_id']+'/S01']['reference_pose'][2] = height-profile['approach_offset_mm']
    with pytest.raises(ValueError, match='UPWARD_TRAVEL_AT_MOST_30MM'):
        validate_physical(build_plan(value['step'], profile), profile, 'retreat')


def test_fresh_session_is_retreat_only_with_new_execution_identity():
    value = helper.prepare_candidate()
    a, b = helper.make_session(value), helper.make_session(value)
    assert a['execution_id'] != b['execution_id'] and a['source_epoch'] != b['source_epoch']
    plan = build_plan(value['step'], value['d_profile'])
    validate_execution(plan, value['d_profile'], a, 'retreat')
    for phase in ('contact', 'release', 'approach', 'full'):
        with pytest.raises(ValueError, match='CANNOT_EXECUTE_OTHER_PHASES'):
            validate_execution(plan, value['d_profile'], a, phase)
    for change in ({'allowed_trial_phase': 'release'}, {'recovery_evidence_ref': None}):
        with pytest.raises(ValueError, match='EXPLICIT_LOCAL_RETREAT'):
            validate_execution(plan, value['d_profile'], dict(a, **change), 'retreat')


def test_recovery_cli_replay_has_no_devices_or_mock_gripper(tmp_path):
    path = tmp_path/'profile.json'
    path.write_text(json.dumps(helper.prepare_candidate()))
    assert main(['replay', '--held-profile', str(path), '--phase', 'retreat', '--output', str(tmp_path)]) == 0
    result = json.loads((tmp_path/'result.json').read_text())
    assert result['status'] == 'RECOVERY_RETREAT_COMPLETE'
    assert result['device_connections'] == 0 and result['robot_motion_commands'] == 0
    assert result['robot_gripper_commands'] == 0 and result['mock_grips'] == 0
    assert result['mock_moves'] == 1
