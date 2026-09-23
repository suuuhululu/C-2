"""공정 내부에서 교체 호출하는 고정 경로 실행기. 별도 ROS 노드를 만들지 않는다.

execute_path(path, context, on_progress=None, adapter=None) -> StepResult.
원본 도구 끝 표면 경로와 fixed_depth 설정으로 최종 계획을 만들고 검사한 점을 실행한다.
접촉 탐색/획별 재보정은 하지 않으며, 완료는 경로 이동 완료만 뜻한다.
로컬 /tmp 시험기의 통신 복구·장치 초기화·고정 현장값은 이관하지 않는다.
"""
import copy
import time
from typing import Callable, Dict, Optional

from .robot_adapter import RobotAdapter, StepResult
from .engraving import (ExecutionContext, MAX_SPLINE_POINTS, _Progress, _seg_length,
                        build_execution_plan, execution_signature, _check_plan)


def execute_path(path: Dict, context: ExecutionContext,
                 on_progress: Optional[Callable[[Dict], None]] = None,
                 adapter: RobotAdapter = None) -> StepResult:
    """engraving.execute_path와 동일 계약. 설정을 몰래 fixed_depth로 바꾸지 않는다."""
    if (context.tool_profile or {}).get('contact_mode') != 'fixed_depth':
        return StepResult('FAILED', 'UNSUPPORTED_RECIPE',
                          '고정 경로 실행에는 검사 전 fixed_depth 설정이 필요함', 'execute_path')
    if adapter is None:
        return StepResult('FAILED', 'NOT_READY', 'robot_adapter 없음', 'execute_path')
    plan = build_execution_plan(path, context)
    if isinstance(plan, StepResult):
        return plan
    try:
        signature = execution_signature(path, context)
    except (ValueError, TypeError):
        return StepResult('FAILED', 'INVALID_INPUT', '경로/설정 fingerprint 생성 불가', 'execution_plan')
    offset_before = copy.deepcopy(getattr(adapter, 'tool_offset_m', None))
    if context.checked_plan_signature is not None:
        if (context.checked_plan_signature != signature
                or context.checked_tool_offset_m != offset_before):
            return StepResult('FAILED', 'PROFILE_MISMATCH',
                              '검사 후 경로/설정/도구 오프셋 변경', 'execution_plan')
    checked = _check_plan(plan, context, adapter)
    if not checked.ok:
        return checked

    segments = plan['segments']
    progress = _Progress(total_cut_m=sum(_seg_length(s['waypoints'])
                                       for s in segments if s['kind'] == 'CUT'))
    began = time.monotonic()

    def finish(outcome, code='NONE', message='', step='execute_path', observed=None):
        values = dict(observed or {})
        values.update(last_completed_segment_id=progress.completed_segment_id,
                      engraving_progress=progress.done_cut_m / progress.total_cut_m if progress.total_cut_m else 0.,
                      touches=[], elapsed_s=time.monotonic()-began,
                      inspection_scope=plan['inspection_scope'], plan_signature=signature,
                      execution_mode='FIXED_PATH_REPLAY', contact_verified=False,
                      engraving_quality_verified=False)
        return StepResult(outcome, code, message, step, values)

    def guard():
        if context.cancel.is_set():
            return finish('STOPPED', message='취소 후 후속 이동 차단')
        try:
            current = execution_signature(path, context)
        except (ValueError, TypeError):
            current = None
        if current != signature or getattr(adapter, 'tool_offset_m', None) != offset_before:
            return finish('FAILED', 'PROFILE_MISMATCH', '검사 후 경로/설정/도구 오프셋 변경')
        return None

    def report(phase):
        if on_progress:
            on_progress(dict(phase=phase, completed_segment_id=progress.completed_segment_id,
                             engraving_progress=progress.done_cut_m / progress.total_cut_m if progress.total_cut_m else 0.,
                             elapsed_s=time.monotonic()-began))

    def send(points, segment, spline=False):
        blocked = guard()
        if blocked:
            return blocked
        profile = context.motion_profiles[segment['motion_profile_id']]
        timeout = float(profile.get('completion_timeout_s', 60.))
        result = (adapter.move_spline(points, path['frame_id'], profile, timeout, context.cancel)
                  if spline else adapter.move(points, path['frame_id'], profile, timeout, context.cancel))
        if not result.ok:
            return finish(result.outcome, result.error_code,
                          f"{segment['kind']} {segment['segment_id']}: {result.message}",
                          f"segment:{segment['segment_id']}", result.observed_state)
        return None

    try:
        for segment in segments:
            blocked = guard()
            if blocked:
                return blocked
            kind, points = segment['kind'], segment['waypoints']
            report({'APPROACH': 'APPROACH', 'TRAVEL': 'ENGRAVE',
                    'CUT': 'ENGRAVE', 'RETRACT': 'RETRACT'}[kind])
            if kind == 'CUT':
                # 깊이는 계획에 적용했다. 각 구간의 첫 점으로 진입한 뒤 나머지를 spline으로 보낸다.
                result = send(points[0], segment)
                if result:
                    return result
                rest = points[1:]
                for i in range(0, len(rest), MAX_SPLINE_POINTS):
                    chunk = rest[i:i + MAX_SPLINE_POINTS]
                    result = send(chunk if len(chunk) >= 2 else chunk[0], segment, len(chunk) >= 2)
                    if result:
                        return result
                progress.done_cut_m += _seg_length(points)
            else:
                for point in points:
                    result = send(point, segment)
                    if result:
                        return result
            progress.completed_segment_id = segment.get('segment_id', '?')
            if kind == 'CUT':
                report('ENGRAVE')
        report('RETRACT')
        blocked = guard()
        if blocked:
            return blocked
        return finish('SUCCEEDED', message=f'{len(segments)} 구간 경로 이동 완료')
    except Exception as exc:
        # 접수 여부가 불명확한 명령은 재전송하지 않는다. 완료 구간은 그대로 남긴다.
        try:
            stopped = adapter.stop(context.stop_profile,
                                   float(context.stop_profile.get('confirmation_timeout_s', 2.)))
            confirmed = stopped.ok and stopped.observed_state.get('stop_confirmed') is True
        except Exception:
            confirmed = False
        return finish('UNKNOWN', 'COMMUNICATION_LOST', str(exc),
                      observed={'stop_confirmed': confirmed})
