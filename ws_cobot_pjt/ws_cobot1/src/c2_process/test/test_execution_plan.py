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
    # 경계 ±2mm는 가능하지만 실제 접촉점(+1mm, cut_contact 없는 기존 프로파일은 depth 가산 없음)은 IK 불가능한 모형.
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


def test_force_depth_applied_once_after_contact_and_checked_identically():
    """depth_m 가산은 cut_contact 프로파일(9/22)에서만. 기존 프로파일은 접촉점을 그대로 쓴다 (test_node 계약)."""
    path, ctx = inputs('force_touch', depth=.0005)
    ctx.tool_profile.update(touch_force_n=2., touch_step_n=2., cut_contact='chunk_adaptive', cut_force_min_n=1.5, cut_force_max_n=4.,
                            adaptive_step_m=.0003, adaptive_chunk_points=80, force_limit_n=6., air_force_limit_n=15.)
    original = copy.deepcopy(path)
    ad = Recorder()
    result = execute_path(path, ctx, adapter=ad)
    assert result.ok
    cuts = [p for p in ad.sent if p[2] > 0]
    assert len(cuts) == 3
    assert all(p[2] == pytest.approx(.0015) for p in cuts)
    assert all(p in ad.ik_points for p in cuts)
    plan = build_execution_plan(path, ctx)
    bounds = [s for s in plan['segments'] if s['movement_kind'] == 'CUT_OFFSET_BOUND']
    assert [s['waypoints'][0][2] for s in bounds] == pytest.approx([-.0015, .0025])
    assert path == original


@pytest.mark.parametrize('offset', [.0005, .0015])
def test_dual_entry_uses_confirmed_depth_without_adding_depth_again(offset):
    path, ctx = inputs('force_touch', depth=.0005)
    ctx.tool_profile.update(entry_confirmation='force_and_position',
                            touch_force_n=2., touch_speed_mm_s=5.,
                            touch_offset_range_m=[.0005, .002])
    ad = Recorder()
    def probe(direction, max_m, profile, deadline, cancel):
        assert profile['entry_target_tip_pose'][2] == pytest.approx(.0005)
        ad.pose = [0., 0., offset, 0., 0., 0., 1.]
        return StepResult('SUCCEEDED', observed_state=dict(contact=True, force_ok=True,
                          position_ok=True, entry_confirmed=True, tcp_pose=ad.pose[:]))
    ad.probe_touch = probe
    result = execute_path(path, ctx, adapter=ad)
    assert result.ok
    cuts = [p for p in ad.sent if p[2] > 0]
    assert len(cuts) == 3
    assert all(p[2] == pytest.approx(offset) for p in cuts)
    assert all(p in ad.ik_points for p in cuts)


def test_dual_entry_rejects_missing_search_bound_without_motion():
    path, ctx = inputs('force_touch', depth=.0005)
    ctx.tool_profile.update(entry_confirmation='force_and_position')
    del ctx.tool_profile['touch_offset_range_m']
    ad = Recorder()
    assert not execute_path(path, ctx, adapter=ad).ok
    assert not motion_calls(ad)



def test_force_signed_check_skips_stroke_ik_and_records_limit():
    """9/22: 세은 검사 서명이 같으면 획별 IK 를 반복하지 않는다. 범위 안 연속 증명은 미구현으로 기록한다."""
    path, ctx = inputs('force_touch')
    ad = Recorder()
    ctx.checked_tool_offset_m = ad.tool_offset_m
    ctx.checked_plan_signature = execution_signature(path, ctx)
    result = execute_path(path, ctx, adapter=ad)
    assert result.ok
    assert ad.ik_points == []
    assert result.observed_state['touches'][0]['ik_rechecked'] is False
    assert result.observed_state['normal_range_continuity_verified'] is False


def test_force_unsigned_run_still_checks_actual_stroke():
    """서명이 없으면(단독 시험) 실제 보정 획을 IK 검사하고, 실패하면 spline 을 보내지 않는다."""
    path, ctx = inputs('force_touch')
    ad = Recorder(lambda p: None if abs(p[2]-.001)<1e-8 else [0.]*6)
    result = execute_path(path, ctx, adapter=ad)
    assert not result.ok
    assert result.observed_state['inspection_scope'] == 'DYNAMIC_STROKE_FINAL'
    assert not any(c['fn']=='move_spline' for c in ad.calls)


def test_legacy_force_touch_profile_uses_contact_point_without_depth():
    """cut_contact 없는 기존 프로파일: 접촉점 = 실행점 (main 종전 동작, 팀 test_node 와 같은 계약)."""
    path, ctx = inputs('force_touch', depth=.0005)
    ad = Recorder()
    assert execute_path(path, ctx, adapter=ad).ok
    assert all(p[2] == pytest.approx(.001) for p in ad.sent if p[2] > 0)


@pytest.mark.parametrize('change', ['depth_m', 'touch_extra_m'])
def test_force_cached_settings_change_blocks_before_motion(change):
    path, ctx = inputs('force_touch')
    ad = Recorder()
    ctx.checked_tool_offset_m = ad.tool_offset_m
    ctx.checked_plan_signature = execution_signature(path, ctx)
    ctx.tool_profile[change] += .0001
    result = execute_path(path, ctx, adapter=ad)
    assert result.error_code == 'PROFILE_MISMATCH'
    assert not motion_calls(ad) and not ad.ik_points



def test_depth_correction_is_once_per_entry_not_per_segment_or_spline():
    path, ctx = inputs('force_touch', depth=.0005)
    ctx.tool_profile.update(entry_confirmation='force_and_position', touch_force_n=2.,
                            touch_speed_mm_s=5., touch_offset_range_m=[.0005, .002])
    approach, first, travel, retract = copy.deepcopy(path['segments'])
    first['waypoints'] = [[i*.00001,0.,0.,0.,0.,0.,1.] for i in range(90)]
    second = copy.deepcopy(first)
    second.update(segment_id='cut-continuation', waypoints=[[.00089+i*.00001,0.,0.,0.,0.,0.,1.] for i in range(90)])
    reentry = copy.deepcopy(first); reentry['segment_id']='cut-reentry'
    # 같은 stroke_id를 재사용하더라도 후퇴·접근 뒤에는 새 보정값을 얻어야 한다.
    path['segments'] = [approach, first, second, retract, approach, reentry, retract]
    original = copy.deepcopy(path)
    ad = Recorder(); offsets=iter([.0007,.0014]); probes=[]
    def probe(direction, max_m, profile, deadline, cancel):
        off = next(offsets); probes.append(off)
        ad.pose=[0.,0.,off,0.,0.,0.,1.]
        return StepResult('SUCCEEDED', observed_state=dict(contact=True,force_ok=True,
                         position_ok=True,entry_confirmed=True,tcp_pose=ad.pose[:]))
    ad.probe_touch=probe
    ctx.checked_tool_offset_m=ad.tool_offset_m
    ctx.checked_plan_signature=execution_signature(path,ctx)
    result=execute_path(path,ctx,adapter=ad)
    assert result.ok
    assert probes == [.0007,.0014]
    cuts=[p for p in ad.sent if p[2]>0]
    assert len(cuts)==270
    assert [p[2] for p in cuts[:180]] == pytest.approx([.0007]*180)
    assert [p[2] for p in cuts[180:]] == pytest.approx([.0014]*90)
    assert len(ad.ik_points)==0  # 9/22: 서명이 있으면 획별 IK 반복 없음
    assert len(result.observed_state['touches'])==2
    assert path==original
    candidates=build_execution_plan(path,ctx)
    assert sum(s['movement_kind']=='PROBE_START' for s in candidates['segments'])==2


# ---------------------------------------------------------------- 9/22 CUT 중 법선 힘 유지 (MoveSX + 순응/힘 제어) ----
from c2_process.engraving import validate_path


def hold_inputs(cut_contact='normal_force_hold', cut_points_n=3):
    path, ctx = inputs('force_touch')
    if cut_points_n != 3:
        path['segments'][1]['waypoints'] = [[i * .001, 0., 0., 0., 0., 0., 1.] for i in range(cut_points_n)]
    ctx.tool_profile.update(cut_contact=cut_contact, cut_force_n=2., cut_stiffness=[3000.] * 3 + [300.] * 3, ramp_s=.5,
                            force_limit_n=6., air_force_limit_n=15., cut_force_min_n=1.5, cut_force_max_n=4.,
                            adaptive_step_m=.0003, adaptive_chunk_points=2)
    return path, ctx


class HoldRecorder(Recorder):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.splines = []

    def move_spline(self, poses, *args):
        self.splines.append(copy.deepcopy(poses))
        return super().move_spline(poses, *args)


def sign(path, ctx, ad):
    ctx.checked_tool_offset_m = ad.tool_offset_m
    ctx.checked_plan_signature = execution_signature(path, ctx)


def fns(ad):
    return [c['fn'] for c in ad.calls if c['fn'] in ('probe_touch', 'move', 'move_spline', 'hold_begin', 'hold_end', 'stop')]


def test_hold_order_entry_then_hold_then_movesx_then_release_before_air():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); sign(path, ctx, ad)
    result = execute_path(path, ctx, adapter=ad)
    assert result.ok, result
    # APPROACH move → clearance move → probe → 진입 move(위치 제어) → 힘 유지 시작 → MoveSX → 해제 → TRAVEL → RETRACT
    assert fns(ad) == ['move', 'move', 'probe_touch', 'move', 'hold_begin', 'move_spline', 'hold_end', 'move', 'move']
    assert all(c['hold'] is False for c in ad.calls if c['fn'] == 'move')          # 공중·진입 이동은 힘 유지 밖
    assert [c['hold'] for c in ad.calls if c['fn'] == 'move_spline'] == [True]      # CUT MoveSX 만 힘 유지 중
    assert result.observed_state['hold_released'] is True and ad.hold_active is False
    assert ad.ik_points == []


def test_hold_sends_hongdong_points_unchanged_except_normal_offset():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); ad.force_fn = lambda p: [0.3, -0.2, -1.0]; sign(path, ctx, ad)
    assert execute_path(path, ctx, adapter=ad).ok
    original = path['segments'][1]['waypoints'][1:]
    sent = ad.splines[0]
    assert [p[:2] + p[3:] for p in sent] == [w[:2] + w[3:] for w in original]      # 접선(x,y)·자세 그대로
    assert all(p[2] == pytest.approx(.0013) for p in sent)                          # 법선(+z)만 접촉 offset + depth


def test_cut_force_limit_stops_releases_and_sends_no_air_motion():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); ad.force_fn = lambda p: [0., 0., -50.] if p[2] > 0 else [0., 0., 0.]; sign(path, ctx, ad)
    result = execute_path(path, ctx, adapter=ad)
    assert result.outcome == 'FAILED' and result.error_code == 'FORCE_LIMIT'
    assert fns(ad)[-3:] == ['move_spline', 'stop', 'hold_end']                      # 정지 → 해제, 그 뒤 이동 없음
    assert result.observed_state['hold_released'] is True


def test_cut_normal_range_exceeded_stops_and_requests_recheck():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); ad.deviation_fn = lambda p: .005; sign(path, ctx, ad)      # 허용 ±2 mm 밖으로 밀림
    result = execute_path(path, ctx, adapter=ad)
    assert result.outcome == 'FAILED' and result.error_code == 'VALIDATION_FAILED'
    assert '재검사' in result.message
    assert fns(ad)[-3:] == ['move_spline', 'stop', 'hold_end']


def test_hold_begin_failure_blocks_cut_motion():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); ad.hold_fail_at = 'begin'; sign(path, ctx, ad)
    result = execute_path(path, ctx, adapter=ad)
    assert result.outcome == 'FAILED' and result.error_code == 'NOT_READY'
    assert 'move_spline' not in fns(ad)


def test_hold_end_failure_blocks_air_motion():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); ad.hold_fail_at = 'end'; sign(path, ctx, ad)
    result = execute_path(path, ctx, adapter=ad)
    assert result.outcome == 'UNKNOWN' and result.error_code == 'STOP_UNCONFIRMED'
    assert fns(ad)[-2:] == ['move_spline', 'hold_end']                              # TRAVEL/RETRACT 이동 없음
    assert result.observed_state['hold_released'] is False


def test_cancel_during_cut_releases_hold():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); sign(path, ctx, ad)
    original = ad.move_spline
    def cancelling(poses, *args):
        ctx.cancel.set()
        return original(poses, *args)
    ad.move_spline = cancelling
    result = execute_path(path, ctx, adapter=ad)
    assert result.outcome == 'STOPPED'
    assert 'hold_end' in fns(ad) and ad.hold_active is False
    assert fns(ad)[-1] == 'hold_end'


def test_air_monitor_uses_absolute_limit_only():
    path, ctx = hold_inputs()
    ad = HoldRecorder(); sign(path, ctx, ad)
    ad.force_fn = lambda p: [0., 0., -2.] if p[2] > 0 else [8., 0., 0.]              # 공중 8 N: CUT 상한 6 초과지만 AIR 상한 15 이내
    assert execute_path(path, ctx, adapter=ad).ok
    ad2 = HoldRecorder(); ctx.cancel.clear(); sign(path, ctx, ad2)
    ad2.force_fn = lambda p: [0., 0., -2.] if p[2] > 0 else [20., 0., 0.]
    result = execute_path(path, ctx, adapter=ad2)
    assert result.error_code == 'FORCE_LIMIT' and 'AIR' in result.message
    assert result.observed_state['hold_released'] is True


def test_real_force_touch_requires_cut_contact_profile_keys():
    path, ctx = inputs('force_touch')
    ctx.source_mode = 'REAL'; path['source_mode'] = 'REAL'
    ctx.tool_profile.update(touch_force_n=.8, touch_speed_mm_s=1.5)
    assert validate_path(path, ctx) is None                       # cut_contact 없는 기존 프로파일은 그대로 허용 (획당 offset 고정 방식)
    ctx.tool_profile['cut_contact'] = 'normal_force_hold'
    err = validate_path(path, ctx)
    assert err.error_code == 'UNSUPPORTED_RECIPE' and 'force_limit_n' in err.message
    ctx.tool_profile.update(force_limit_n=6., air_force_limit_n=15., cut_force_n=2., cut_stiffness=[3000.] * 6, ramp_s=.5)
    assert validate_path(path, ctx) is None
    ctx.tool_profile['cut_contact'] = 'somewhere_else'
    assert validate_path(path, ctx).error_code == 'UNSUPPORTED_RECIPE'


def test_chunk_adaptive_shifts_offset_inward_within_range_without_hold():
    path, ctx = hold_inputs('chunk_adaptive', cut_points_n=5)
    ad = HoldRecorder(); ad.force_fn = lambda p: [0., 0., 0.]; sign(path, ctx, ad)     # 접촉력 0 → 매 묶음 0.3 mm 안쪽
    result = execute_path(path, ctx, adapter=ad)
    assert result.ok
    assert 'hold_begin' not in fns(ad)
    assert [round(p[2], 4) for chunk in ad.splines for p in chunk] == [.0013, .0013, .0016, .0016]
    ad2 = HoldRecorder(); ctx.cancel.clear(); sign(path, ctx, ad2); ad2.force_fn = lambda p: [0., 0., 0.]
    ctx.tool_profile['touch_offset_range_m'] = [-.002, .0014]; sign(path, ctx, ad2)
    assert execute_path(path, ctx, adapter=ad2).ok
    assert max(p[2] for chunk in ad2.splines for p in chunk) <= .0014 + 1e-9        # 허용 범위 상한을 넘지 않는다


# ---------------------------------------------------------------- 9/22 안전 홈 복귀 return_home ----
import math
from c2_process.engraving import return_home, _geometry_ok, _home_steps
from c2_process.robot_adapter import RobotState, apply_tool_offset, tool_axis_in_base, matrix_to_quat, quat_to_matrix


def home_workcell():
    return dict(frame_id='c2_base', tool_offset_m=[0.00085, -0.09955, 0.], seed_axis_xy_m=[0.4261, -0.0001], seed_radius_m=0.0343,
                top_z_m=0.2149, bottom_z_m=0.0649, outer_gap_m=0.022, slow_retract_gap_m=0.002, facing_tolerance_deg=2.0,
                tool_rear_protrusion_m=0.074, gripper_body_half_width_m=0.026,
                home=dict(tcp_pose=[0.4262, 0.00005, 0.33, 0., 1., 0., 0.], clearance_tcp_z_m=0.33, position_tolerance_m=0.0003, angle_tolerance_rad=0.0052),
                top=dict(contact_offset_tool_m=[0., 0., 0.02]), trial_scene=dict(tcp_min_m=[.26, -.17, .09], tcp_max_m=[.61, .18, .335]))


def home_ctx():
    _, ctx = inputs('force_touch')
    ctx.motion_profiles = {'candle_travel': dict(id='candle_travel', vel_mm_s=25., completion_timeout_s=90.),
                           'candle_retract': dict(id='candle_retract', vel_mm_s=5., completion_timeout_s=90.)}
    ctx.tool_profile['air_force_limit_n'] = 15.
    ctx.joint_limits_deg = [(-360., 360.), (-95., 95.), (-135., 135.), (-360., 360.), (-135., 135.), (-360., 360.)]
    return ctx


def facing_minus_y(tilt_deg=0.0, yaw_deg=0.0):
    """−Y 면에서 드릴(툴 −Y)이 축을 보는 자세: 툴 +Y = base −Y, 툴 +Z = base −Z. tilt 는 툴 x 축 기준 기울임, yaw 는 base z 회전."""
    M = [[1., 0., 0.], [0., -1., 0.], [0., 0., -1.]]
    def rot(R, M):
        return [[sum(R[r][k] * M[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
    if tilt_deg:
        a = math.radians(tilt_deg); M = rot([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]], M)
    if yaw_deg:
        a = math.radians(yaw_deg); M = rot([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]], M)
    return matrix_to_quat(M)


class HomeMock(MockRobotAdapter):
    """홈 복귀 시험용: 실제 관절값 비슷한 observe, 이동 기록, IK 거부 훅."""
    def __init__(self, tip, reject=None):
        super().__init__()
        self.pose = list(tip); self.tool_offset_m = [0.00085, -0.09955, 0.]
        self.reject = reject; self.moves = []; self.state = 1
    def observe(self):
        ty = tool_axis_in_base(self.pose, '+y'); j6 = math.atan2(ty[1], ty[0])
        return RobotState(joints_rad=[0., math.radians(10), math.radians(80), 0., math.radians(90), j6], tcp_pose=list(self.pose),
                          frame_id='c2_base', robot_state=self.state, force_n=[0., 0., 0.], measured_at=0., quality='VALID')
    def inverse_kinematics(self, pose, offset, ref):
        if self.reject and self.reject(pose):
            return None
        return super().inverse_kinematics(pose, offset, ref)
    def move(self, pose, frame, profile, deadline, cancel):
        self.moves.append((profile.get('id'), list(pose), 'air_monitor' in profile))
        return super().move(pose, frame, profile, deadline, cancel)


def cut_end_tip(w, inside_m=0.0008, z=0.17, **orient):
    c, r = w['seed_axis_xy_m'], w['seed_radius_m']
    return [c[0], c[1] - (r - inside_m), z, *facing_minus_y(**orient)]


def test_return_home_already_home_no_motion():
    w = home_workcell(); ad = HomeMock(apply_tool_offset(w['home']['tcp_pose'], w['tool_offset_m'], +1))
    r = return_home(home_ctx(), ad, w)
    assert r.ok and r.observed_state['moved'] is False and ad.moves == []


def test_return_home_retreats_lifts_aligns_then_home():
    w = home_workcell(); tip = cut_end_tip(w); ad = HomeMock(tip)
    r = return_home(home_ctx(), ad, w)
    assert r.ok, r
    labels = [s['label'] for s in r.observed_state['steps']]
    assert labels[:3] == ['return_retreat_slow', 'return_retreat', 'return_lift']
    tail = [l for l in labels if l in ('return_x', 'return_y', 'return_down')]
    assert tail and tail == [l for l in ('return_x', 'return_y', 'return_down') if l in tail]   # 1 mm 미만 단계(x 정렬·하강)는 생략될 수 있다
    first_tail = labels.index(tail[0])
    assert all(l == 'return_align' for l in labels[3:first_tail]) and first_tail > 3
    # 후퇴: 드릴 축(툴 +Y = base −Y) 방향으로만, 끝이 R + 22 mm 까지
    p_slow, p_out = ad.moves[0][1], ad.moves[1][1]
    assert p_slow[0] == pytest.approx(tip[0]) and p_slow[2] == pytest.approx(tip[2]) and p_slow[3:] == pytest.approx(tip[3:])
    assert math.hypot(p_out[0] - w['seed_axis_xy_m'][0], p_out[1] - w['seed_axis_xy_m'][1]) == pytest.approx(w['seed_radius_m'] + w['outer_gap_m'], abs=1e-6)
    assert ad.moves[0][0] == 'candle_retract' and ad.moves[1][0] == 'candle_travel'
    # 상승: xy·자세 유지, 도구 최저점(그리퍼 하단)이 윗면 + 50 mm 이상, TCP 가 홈 안전 높이 이상
    p_lift = ad.moves[2][1]
    assert p_lift[:2] == pytest.approx(p_out[:2]) and p_lift[3:] == pytest.approx(p_out[3:])
    tcp = apply_tool_offset(p_lift, w['tool_offset_m'], -1); bottom = apply_tool_offset(tcp, w['top']['contact_offset_tool_m'], +1)
    assert bottom[2] >= w['top_z_m'] + 0.05 - 1e-9 and tcp[2] >= w['home']['clearance_tcp_z_m'] - 1e-9
    # 정렬은 TCP 위치 고정, 마지막은 홈
    for _, p, _ in ad.moves[3:first_tail]:
        assert apply_tool_offset(p, w['tool_offset_m'], -1)[:3] == pytest.approx(tcp[:3], abs=1e-9)
    assert apply_tool_offset(ad.moves[-1][1], w['tool_offset_m'], -1) == pytest.approx(w['home']['tcp_pose'], abs=1e-9)
    assert all(m[2] for m in ad.moves)                          # 모든 단계에 공중 절대 상한 감시
    assert r.observed_state['full_mesh_checked'] is False and r.observed_state['checked_samples'] > 50


def test_return_home_tilted_posture_lifts_first_then_aligns():
    w = home_workcell(); tip = cut_end_tip(w, tilt_deg=10.0); ad = HomeMock(tip)
    r = return_home(home_ctx(), ad, w)
    assert r.ok, r
    labels = [s['label'] for s in r.observed_state['steps']]
    lift = ad.moves[labels.index('return_lift')][1]
    assert lift[3:] == pytest.approx(tip[3:])                     # 기울어진 채 먼저 올라가고
    assert 'return_align' in labels and labels.index('return_align') > labels.index('return_lift')


def test_return_home_refuses_when_drill_not_facing_axis():
    w = home_workcell(); tip = cut_end_tip(w, yaw_deg=90.0); ad = HomeMock(tip)   # 드릴 축이 접선 방향
    r = return_home(home_ctx(), ad, w)
    assert r.outcome == 'FAILED' and r.error_code == 'VALIDATION_FAILED' and '후퇴 불가' in r.message
    assert ad.moves == []


def test_return_home_refuses_when_tip_too_deep():
    w = home_workcell(); ad = HomeMock(cut_end_tip(w, inside_m=0.008))
    r = return_home(home_ctx(), ad, w)
    assert not r.ok and '안쪽' in r.message and ad.moves == []


def test_return_home_ik_failure_blocks_all_motion():
    w = home_workcell(); ad = HomeMock(cut_end_tip(w), reject=lambda p: p[2] > 0.30)
    r = return_home(home_ctx(), ad, w)
    assert r.outcome == 'FAILED' and r.error_code == 'VALIDATION_FAILED' and 'IK' in r.message and ad.moves == []


@pytest.mark.parametrize('case', ['not_standby', 'hold_unreleased', 'cancel', 'offset_mismatch'])
def test_return_home_refuses_unsafe_states(case):
    w = home_workcell(); ad = HomeMock(cut_end_tip(w)); ctx = home_ctx()
    if case == 'not_standby':
        ad.state = 2
    elif case == 'hold_unreleased':
        ad.hold_active = True; ad.hold_fail_at = 'end'
    elif case == 'cancel':
        ctx.cancel.set()
    else:
        ad.tool_offset_m = [0., -0.1, 0.]
    r = return_home(ctx, ad, w)
    assert not r.ok and ad.moves == []


def test_geometry_check_sees_drill_and_gripper_bottom_not_only_tcp():
    w = home_workcell(); c = w['seed_axis_xy_m']
    through = [c[0], c[1], 0.17, *facing_minus_y()]                # 드릴 끝이 축 위 (TCP 는 100 mm 바깥에 있어도 드릴이 양초를 관통)
    ok, why, _ = _geometry_ok(through, w, min_gap_m=0.010)
    assert not ok and 'drill' in why
    low = [c[0], c[1] - w['seed_radius_m'] - 0.05, w['bottom_z_m'] + 0.015, *facing_minus_y()]   # 끝은 받침대 위 15 mm 지만 그리퍼 하단은 −5 mm
    ok, why, _ = _geometry_ok(low, dict(w, trial_scene=None), min_gap_m=0.010)
    assert not ok and '받침대' in why
    over = apply_tool_offset([c[0], c[1], w['top_z_m'] + 0.03, 0., 1., 0., 0.], w['tool_offset_m'], +1)      # 양초 바로 위 30 mm, 하단은 +10 mm 뿐이지만 5 mm 기준은 통과
    assert _geometry_ok(over, w, min_gap_m=0.010)[0]


def test_return_home_lift_allowed_when_start_below_measurement_box():
    """9/22 실기: 조각 높이의 TCP(z 166 mm)가 측정용 상자(z ≥ 190)보다 낮아 상승 첫 샘플부터 거절됐다. 후퇴·상승은 xy 만 상자로 본다."""
    w = home_workcell(); w['trial_scene'] = dict(tcp_min_m=[.265, -.17, .19], tcp_max_m=[.59, .18, .335])
    tip = [0.4955, -0.0337, 0.1594, 0.469, 0.8827, 0.0048, 0.0294]        # 실기 9/22 현재 자세 (표면 밖 43 mm, 양초 높이 대역)
    ad = HomeMock(tip)
    r = return_home(home_ctx(), ad, w)
    assert r.ok, r
    labels = [s['label'] for s in r.observed_state['steps']]
    assert labels[0] == 'return_lift' and 'return_retreat' not in labels     # 이미 R + 22 mm 밖이라 후퇴 없음
    # 정렬 이후 단계는 상자 전체(z 포함) 검사를 받는다: 상자를 홈보다 낮게 만들면 거절
    w2 = dict(w, trial_scene=dict(tcp_min_m=[.265, -.17, .19], tcp_max_m=[.59, .18, .30]))
    r2 = return_home(home_ctx(), HomeMock(tip), w2)
    assert not r2.ok and '작업 범위 밖' in r2.message
