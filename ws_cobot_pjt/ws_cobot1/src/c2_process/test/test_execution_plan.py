"""모의 IK와 실제 execute_path 명령 경계 비교. 실물/연속 충돌 검증 아님."""
import copy
import threading
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from c2_process.engraving import (ExecutionContext, build_execution_plan, execute_path,
                                  execution_signature)
from c2_process.joint_check import check_path_joints
from c2_process.robot_adapter import MockRobotAdapter, StepResult


def inputs(mode='fixed_depth', depth=0.0003):
    pose = lambda x, z: [x, 0., z, 0., 0., 0., 1.]
    segments = [dict(segment_id=kind.lower(), stroke_id='stroke-1', kind=kind,
                     motion_profile_id='p', waypoints=points) for kind, points in [
        ('APPROACH', [pose(0., -.01)]),
        ('CUT', [pose(0., 0.), pose(.001, 0.), pose(.002, 0.)]),
        ('TRAVEL', [pose(.003, -.01)]), ('RETRACT', [pose(.003, -.02)])]]
    path = dict(schema_version=2, source_mode='SIMULATION', frame_id='c2_base',
                position_unit='m', orientation='quaternion_xyzw', path_id='p', path_version=1,
                config=dict(profile_snapshot_id='s', profile_sha256='1'*64), segments=segments)
    ctx = ExecutionContext('run', 'SIMULATION', threading.Event(),
                           {'p': {'completion_timeout_s': 2}},
                           dict(contact_mode=mode, tool_axis='+z', depth_m=depth,
                                clearance_m=.01, touch_extra_m=.004,
                                touch_offset_range_m=[-.002, .002]))
    return path, ctx


class Recorder(MockRobotAdapter):
    def __init__(self, reject=None, on_ik=None):
        super().__init__(surface_fn=lambda p,d: .011)
        self.ik_points, self.sent = [], []
        self.reject, self.on_ik = reject, on_ik

    def inverse_kinematics(self, pose, offset, ref):
        self.ik_points.append(copy.deepcopy(pose))
        if self.on_ik:
            self.on_ik()
        return self.reject(pose) if self.reject else [0.]*6

    def move(self, pose, *args):
        self.sent.append(copy.deepcopy(pose))
        return super().move(pose, *args)

    def move_spline(self, poses, *args):
        self.sent.extend(copy.deepcopy(poses))
        return super().move_spline(poses, *args)


def motion_calls(ad):
    return [c for c in ad.calls if c['fn'] in ('move','move_spline','probe_touch')]


def test_zero_depth_matches_surface_and_exact_command_sequence():
    path, ctx = inputs(depth=0)
    ad = Recorder()
    assert execute_path(path, ctx, adapter=ad).ok
    surface = [p for s in path['segments'] for p in s['waypoints']]
    assert ad.ik_points == ad.sent == surface


def test_fixed_final_plan_checked_and_consumed_once_without_source_mutation():
    path, ctx = inputs()
    original = copy.deepcopy(path)
    plan = build_execution_plan(path, ctx)
    ad = Recorder()
    result = execute_path(path, ctx, adapter=ad)
    assert result.ok and result.observed_state['inspection_scope'] == 'FINAL_EXECUTION_PLAN'
    final = [p for s in plan['segments'] for p in s['waypoints']]
    assert final == ad.ik_points == ad.sent
    assert [p[2] for p in ad.sent[1:4]] == [.0003]*3  # .0006로 이중 적용 안 함
    assert path == original
    rejected = build_execution_plan(plan, ctx)
    assert isinstance(rejected, StepResult) and not rejected.ok


@pytest.mark.parametrize('index', [0,1,2])
def test_surface_passes_but_depth_ik_failure_prevents_every_motion(index):
    path, ctx = inputs()
    def ik(p):
        return None if p[0] == index*.001 and p[2] > 0 else [0.]*6
    assert check_path_joints(path, Recorder(ik), None, [0.]*6).ok
    ad = Recorder(ik)
    r = execute_path(path, ctx, adapter=ad)
    assert not r.ok and not motion_calls(ad)
    assert r.observed_state['index'] == index
    assert r.observed_state['segment_id'] == 'cut'
    assert r.observed_state['stroke_id'] == 'stroke-1'
    assert r.observed_state['applied_depth_m'] == .0003
    assert r.observed_state['movement_kind'] == 'CUT_ENTRY_AND_CUT'


@pytest.mark.parametrize('joint,value', [(4,136.), (5,355.)])
def test_middle_depth_point_joint_limit(joint,value):
    path, ctx = inputs()
    def ik(p):
        q = [0.]*6
        q[5] = 340.
        if p[0] == .001 and p[2] > 0: q[joint] = value
        return q
    ad = Recorder(ik)
    # J6의 연속 해를 340도에서 시작한다.
    from dataclasses import replace
    import math
    observe = ad.observe
    ad.observe = lambda: replace(observe(), joints_rad=[0.]*5+[math.radians(340.)])
    r = execute_path(path, ctx, adapter=ad)
    assert not r.ok and not motion_calls(ad)
    assert r.observed_state['worst']['joint'] == joint+1
    assert r.observed_state['worst']['index'] == 1
    assert r.observed_state['worst']['margin_deg'] == (10. if joint == 5 else 0.)


@pytest.mark.parametrize('kind', ['APPROACH','TRAVEL','RETRACT'])
def test_non_cut_failure_blocks_all_motion(kind):
    path, ctx = inputs()
    bad = next(s['waypoints'][0] for s in path['segments'] if s['kind'] == kind)
    ad = Recorder(lambda p: None if p == bad else [0.]*6)
    r = execute_path(path, ctx, adapter=ad)
    assert not r.ok and not motion_calls(ad)
    assert r.observed_state['movement_kind'] == kind


@pytest.mark.parametrize('mutation', ['depth','waypoint','path_sha','snapshot_sha'])
def test_prior_check_binding_cannot_be_reused_after_change(mutation):
    path, ctx = inputs()
    ctx.path_binding = {'path_sha256':'a'*64}
    ctx.checked_plan_signature = execution_signature(path, ctx)
    if mutation == 'depth': ctx.tool_profile['depth_m'] = .001
    elif mutation == 'waypoint': path['segments'][1]['waypoints'][0][0] += .001
    elif mutation == 'path_sha': ctx.path_binding['path_sha256'] = 'b'*64
    else: path['config']['profile_sha256'] = '2'*64
    ad = Recorder()
    r = execute_path(path, ctx, adapter=ad)
    assert r.error_code == 'PROFILE_MISMATCH' and not ad.ik_points and not motion_calls(ad)


@pytest.mark.parametrize('when', ['ik','progress'])
def test_mutation_during_check_or_progress_blocks_motion(when):
    path, ctx = inputs()
    def mutate(): ctx.tool_profile['depth_m'] += .0001
    ad = Recorder(on_ik=mutate if when == 'ik' else None)
    r = execute_path(path, ctx, adapter=ad, on_progress=(lambda _: mutate()) if when == 'progress' else None)
    assert r.error_code == 'PROFILE_MISMATCH' and not motion_calls(ad)


def test_force_missing_offset_bound_fails_before_probe_or_move():
    path, ctx = inputs('force_touch')
    del ctx.tool_profile['touch_offset_range_m']
    ad = Recorder()
    r = execute_path(path, ctx, adapter=ad)
    assert r.error_code == 'NOT_READY' and not motion_calls(ad)


def test_force_boundary_candidates_and_actual_offset_are_separate():
    path, ctx = inputs('force_touch')
    plan = build_execution_plan(path, ctx)
    assert plan['inspection_scope'] == 'BOUNDED_FORCE_TOUCH_CANDIDATES'
    assert {s['movement_kind'] for s in plan['segments']} >= {'PROBE_START','PROBE_END_BOUND','CUT_OFFSET_BOUND'}
    # 경계 ±2mm는 가능하지만 실제 접촉한 +1mm의 내부점은 IK 불가능한 모형.
    ad = Recorder(lambda p: None if abs(p[2]-.001) < 1e-8 else [0.]*6)
    r = execute_path(path, ctx, adapter=ad)
    assert not r.ok and r.observed_state['inspection_scope'] == 'DYNAMIC_STROKE_FINAL'
    assert any(c['fn'] == 'probe_touch' for c in ad.calls)
    assert not any(c['fn'] == 'move_spline' for c in ad.calls)
    assert all(p[2] < 0 for p in ad.sent)  # CUT 첫 진입도 없음


def test_force_actual_offset_outside_bound_never_enters_cut():
    path, ctx = inputs('force_touch')
    ad = Recorder(); ad.surface_fn = lambda p,d: .013
    r = execute_path(path, ctx, adapter=ad)
    assert r.error_code == 'VALIDATION_FAILED'
    assert not any(c['fn'] == 'move_spline' for c in ad.calls)


@pytest.mark.parametrize('when', ['before','ik','progress','after_contact'])
def test_cancel_blocks_later_checks_and_motion(when):
    path, ctx = inputs('force_touch' if when == 'after_contact' else 'fixed_depth')
    ad = Recorder(on_ik=ctx.cancel.set if when == 'ik' else None)
    if when == 'before': ctx.cancel.set()
    if when == 'after_contact':
        probe = ad.probe_touch
        def cancelled(*a, **kw):
            r = probe(*a, **kw); ctx.cancel.set(); return r
        ad.probe_touch = cancelled
    r = execute_path(path, ctx, adapter=ad,
                     on_progress=(lambda _: ctx.cancel.set()) if when == 'progress' else None)
    assert r.outcome == 'STOPPED'
    if when in ('before','ik','progress'):
        assert not motion_calls(ad)
        assert len(ad.ik_points) <= (1 if when == 'ik' else 6)
    else:
        assert len(ad.ik_points) == sum(len(s['waypoints']) for s in build_execution_plan(path,ctx)['segments'])
        assert all(p[2] < 0 for p in ad.sent)


def test_checked_offset_change_blocks_before_new_ik_or_motion():
    path, ctx = inputs()
    ctx.checked_tool_offset_m = [0., -.09955, 0.]
    ctx.checked_plan_signature = execution_signature(path, ctx)
    ad = Recorder(); ad.tool_offset_m = [0., -.05, 0.]
    r = execute_path(path, ctx, adapter=ad)
    assert r.error_code == 'PROFILE_MISMATCH' and not ad.ik_points and not motion_calls(ad)


def test_ik_exception_is_unknown_and_blocks_motion():
    path, ctx = inputs()
    def unavailable(): raise TimeoutError('mock IK timeout')
    ad = Recorder(on_ik=unavailable)
    r = execute_path(path, ctx, adapter=ad)
    assert r.outcome == 'UNKNOWN' and r.error_code == 'VALIDATION_UNAVAILABLE'
    assert not motion_calls(ad)


def test_node_depth_check_precedes_tool_check_and_all_motion(tmp_path):
    from test_node import _file_integration
    from c2_process.node import ProcessCoordinator
    from c2_process.engraving import cut_points
    goal, loader, ad, files = _file_integration(tmp_path)
    loaded = loader(goal)
    loaded.context.tool_profile.update(contact_mode='fixed_depth', depth_m=.0003)
    cut = next(s for s in loaded.path['segments'] if s['kind'] == 'CUT')
    bad = cut_points(cut, loaded.context.tool_profile, .0003)[0]
    def ik(p, *a): return None if p == bad else [0.]*6
    ad.inverse_kinematics = ik
    assert check_path_joints(loaded.path, ad, loaded.calibration.offset_tool_m, [0.]*6).ok
    result = ProcessCoordinator(lambda _: loaded).execute(goal)
    assert result.error_code == 'NOT_READY' and not motion_calls(ad)
    assert result.observed_state['inspection_scope'] == 'FINAL_EXECUTION_PLAN'
    assert result.observed_state['index'] == 0


def test_context_keeps_explicit_zero_margin_from_file():
    from test_node import _handoff_settings
    from c2_process.node import resolve_simulation_settings
    cfg, path, goal, ad, evidence = _handoff_settings()
    fields = resolve_simulation_settings(cfg, goal, evidence=evidence, adapter=ad)
    assert fields['context'].j6_margin_deg == fields['j6_margin_deg'] == 0
    assert fields['context'].joint_limits_deg == fields['joint_limits_deg']
