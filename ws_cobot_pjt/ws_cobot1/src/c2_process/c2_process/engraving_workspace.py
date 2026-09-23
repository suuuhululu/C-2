"""조각용 도구 끝 작업영역. 측정용 trial_scene/TCP 박스와 독립적이다."""
import math
from collections.abc import Mapping
from .robot_adapter import StepResult

DEFAULT_WORKSPACE = {'frame_id': 'c2_base', 'waypoint_min_z_m': 0.05}


def validate_workspace(value=None):
    # 기존 스냅샷에도 동일한 사용자 지정 하한을 적용한다.
    value = DEFAULT_WORKSPACE if value is None else value
    if not isinstance(value, Mapping) or set(value) != set(DEFAULT_WORKSPACE):
        raise ValueError('engraving_workspace는 frame_id/waypoint_min_z_m 필요')
    minimum = value['waypoint_min_z_m']
    if (value['frame_id'] != 'c2_base' or type(minimum) not in (int, float)
            or not math.isfinite(minimum) or minimum < 0.05):
        raise ValueError('engraving_workspace: c2_base 도구 끝 Z 하한은 0.05 m 이상 필요')
    return dict(value)


def check_waypoints(waypoints, workspace=None):
    try:
        minimum = validate_workspace(workspace)['waypoint_min_z_m']
    except ValueError as exc:
        return StepResult('FAILED', 'INVALID_INPUT', str(exc), 'workspace_check')
    for index, pose in enumerate(waypoints):
        if (not isinstance(pose, (list, tuple)) or len(pose) != 7
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in pose)):
            return StepResult('FAILED', 'INVALID_INPUT', '조각 waypoint 형식 오류', 'workspace_check')
        if pose[2] < minimum:
            return StepResult('FAILED', 'VALIDATION_FAILED',
                              f'조각 도구 끝 Z {pose[2]:.6f} m < {minimum:.6f} m: sample {index}',
                              'workspace_check', {'sample_index': index, 'waypoint_z_m': pose[2]})
    return StepResult('SUCCEEDED', 'NONE', '조각 작업영역 검사 통과', 'workspace_check')


def check_path_workspace(path, workspace=None):
    if path.get('frame_id') != 'c2_base':
        return StepResult('FAILED', 'INVALID_INPUT', '조각 작업영역 frame_id 불일치', 'workspace_check')
    for segment in path.get('segments', []):
        result = check_waypoints(segment.get('waypoints', []), workspace)
        if not result.ok:
            result.observed_state['segment_id'] = segment.get('segment_id')
            return result
    return check_waypoints([], workspace)
