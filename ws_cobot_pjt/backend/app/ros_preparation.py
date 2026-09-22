"""고정 PrepareWorkpiece 계약의 HMI 변환. 모션/로봇 관측은 수행하지 않는다."""
from copy import deepcopy
from datetime import datetime, timezone
import math

from .monitor_contract import uid


def action_goal(goal):
    return dict(schema_version=2, operation='MEASURE', **{
        k: goal[k] for k in ('request_id', 'preparation_id', 'measurement_id', 'source_mode',
                            'input_profile_snapshot_id', 'input_profile_sha256')},
        measurement_record_id='', measurement_record_sha256='', profile_snapshot_id='', profile_sha256='')


def stamp(value):
    sec, ns = value['sec'], value['nanosec']
    if type(sec) is not int or type(ns) is not int or sec <= 0 or not 0 <= ns < 1_000_000_000:
        raise ValueError('측정 시각 미확인')
    return datetime.fromtimestamp(sec, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + f'.{ns:09d}Z'


def display_result(raw, goal):
    """원본은 별도 보존. 기존 HTTP 화면 모델로만 변환한다."""
    observed = dict(partial=raw.get('partial'), stop_confirmed=raw.get('stop_confirmed'), measurement=None)
    if raw.get('outcome') == 'SUCCEEDED':
        validity = ('SIMULATED',) if goal['source_mode'] == 'SIMULATION' else ('ESTIMATED', 'FORCE_CONTACT_ESTIMATE')
        if (raw.get('error_code') != 'NONE' or raw.get('geometry_ready') is not True
                or raw.get('partial') is not False or raw.get('stop_confirmed') is not True
                or raw.get('snapshot_bound') is not False or raw.get('validity') not in validity
                or raw.get('source_mode') != goal['source_mode'] or raw.get('frame_id') != 'c2_base'):
            raise ValueError('측정 성공 조건·모드·좌표계 불일치')
        indices = raw.get('contact_indices')
        if indices != list(range(9)):
            raise ValueError('윗면과 옆면 8점 접촉 원본 필요')
        names = ('contact_tip_poses', 'contact_normal_force_n', 'contact_received_at',
                 'contact_monotonic_s', 'contact_sources')
        if any(not isinstance(raw.get(k), list) or len(raw[k]) != 9 for k in names):
            raise ValueError('접촉 배열 길이 불일치')
        for i in indices:
            pose = raw['contact_tip_poses'][i]
            xyz = [pose['position'][k] for k in ('x', 'y', 'z')]
            quat = [pose['orientation'][k] for k in ('x', 'y', 'z', 'w')]
            numbers = xyz + quat + [raw['contact_normal_force_n'][i], raw['contact_monotonic_s'][i]]
            if any(type(n) not in (int, float) or not math.isfinite(n) for n in numbers):
                raise ValueError('접촉 수치 오류')
            if not math.isclose(sum(n*n for n in quat), 1., abs_tol=1e-6):
                raise ValueError('접촉 quaternion 정규화 오류')
            if not raw['contact_sources'][i]:
                raise ValueError('접촉 출처 누락')
            stamp(raw['contact_received_at'][i])
        started, measured = stamp(raw['started_at']), stamp(raw['measured_at'])
        if measured < started:
            raise ValueError('측정 시각 역전')
        m = deepcopy(raw)
        m.update(profile_snapshot_id=goal['input_profile_snapshot_id'],
                 profile_sha256=goal['input_profile_sha256'], position_unit='m',
                 measured_at=measured, points=[dict(point_index=i) for i in range(1, 9)])
        observed['measurement'] = m
    return dict(outcome=raw['outcome'], error_code=raw['error_code'], message=raw['message'], observed_state=observed)


def bound_profile(base, goal, display, config, record):
    from .preparation import measured_profile
    if goal['source_mode'] == 'REAL':
        return real_bound_profile(goal, display, config, record)
    # /1 고정 기준은 변경하지 않는다. 동적 기하는 기존 /2 소비자에만 전달한다.
    from c2_path.pipeline import PROFILE_CONTRACT_V2, validate_profile
    profile = measured_profile(base, goal, display)
    profile.update(contract=PROFILE_CONTRACT_V2, source_mode='SIMULATION',
                   input_profile_snapshot_id=goal['input_profile_snapshot_id'],
                   input_profile_sha256=goal['input_profile_sha256'],
                   measurement_record_id=record['id'], measurement_record_sha256=record['sha256'],
                   label='ROS SIM 준비·측정 결과', note='ROS SIM 측정 결과. 실기 검증·실행 승인이 아닙니다.')
    for key in ('tool_id', 'tcp_id', 'load_id', 'tool_version', 'tcp_version', 'load_version',
                'tools_config_id', 'tools_config_version'):
        if key in config:
            profile[key] = config[key]
    if 'virtual_device' in config:
        profile['virtual_device'] = deepcopy(config['virtual_device'])
    validate_profile(profile)
    return profile


def bind_goal(measure_goal, record, profile):
    return dict(measure_goal, operation='BIND_SNAPSHOT', request_id=uid(),
                measurement_record_id=record['id'], measurement_record_sha256=record['sha256'],
                profile_snapshot_id=profile['id'], profile_sha256=profile['sha256'])


def real_bound_profile(goal, display, config, record):
    """등록 실행 설정 + 이번 측정. 신뢰도 값을 승인 값으로 변조하지 않는다."""
    from .preparation import measured_profile
    template = config.get('execution_profile')
    if not isinstance(template, dict):
        raise ValueError('REAL 가공 설정 execution_profile이 없습니다. 측정 원본은 보관했습니다. 배포 설정에 경로·공정 실행 설정을 연결하세요.')
    required = ('contract', 'workcell_id', 'workcell_version',
                'tools_config_id', 'tools_config_version', 'tool_id', 'tool_version',
                'tcp_id', 'tcp_version', 'load_id', 'load_version', 'surface',
                'execution_context', 'joint_check_arguments', 'tip_calibration')
    if any(k not in template for k in required):
        raise ValueError('REAL 가공 설정 누락: ' + ', '.join(k for k in required if k not in template))
    if (template.get('source_mode') != 'REAL' or template.get('schema_version') != 2
            or template.get('frame_id') != 'c2_base' or template.get('test_only') is not False
            or template.get('real_execution_allowed') is not True
            or template.get('gripper_open_allowed') is not False):
        raise ValueError('REAL 실행 후보 설정의 모드·스키마·실행 용도·그리퍼 설정 불일치')
    for key in ('tool_id', 'tcp_id', 'load_id', 'tool_version', 'tcp_version', 'load_version',
                'tools_config_id', 'tools_config_version'):
        actual = config.get(key, config['workcell'].get(key))
        if actual is not None and template[key] != actual:
            raise ValueError('준비/실행 설정 불일치: ' + key)
    if any(not isinstance(template[k], dict) for k in ('surface', 'execution_context', 'joint_check_arguments', 'tip_calibration')):
        raise ValueError('REAL 실행 설정 객체 형식 오류')
    for key in ('u_origin_angle_deg', 'seam_angle_deg', 'reachable_angle_deg'):
        if key not in template['surface']:
            raise ValueError('REAL 표면 설정 누락: ' + key)
    if template['execution_context'].get('source_mode') != 'REAL':
        raise ValueError('가공 실행 설정 모드 불일치')
    if template['tip_calibration'].get('offset_tool_m') != config['workcell'].get('tool_offset_m'):
        raise ValueError('측정/가공 도구 끝 오프셋 불일치')
    profile = measured_profile(template, goal, display)
    m = display['observed_state']['measurement']
    if m.get('work_v_origin', 'TOP') != 'TOP' or m.get('work_v_positive_direction', 'DOWN') != 'DOWN':
        raise ValueError('측정 작업 범위는 TOP/DOWN 계약이어야 합니다.')
    profile.update(source_mode='REAL', validity=m['validity'], label='REAL 실측 실행 후보',
        note='측정 신뢰도 보존. BIND 성공은 실제 실행 검사 통과를 의미하지 않습니다.',
        input_profile_snapshot_id=goal['input_profile_snapshot_id'],
        input_profile_sha256=goal['input_profile_sha256'],
        measurement_record_id=record['id'], measurement_record_sha256=record['sha256'])
    # 원본에 없는 검증 결과를 추측하지 않는다. 미확인 값은 null로 표시한다.
    profile['surface']['u_origin_angle_deg'] = template['surface']['u_origin_angle_deg']
    profile['measurement_assumptions']['absolute_top_verified'] = m.get('absolute_top_verified')
    if 'absolute_top_verified' in m:
        profile['absolute_top_verified'] = m['absolute_top_verified']
    profile['contact_calibration'] = deepcopy(config['workcell']['top'])
    for key in ('offset_status', 'offset_record_id', 'contact_offset_tool_m'):
        if key not in profile['contact_calibration']:
            raise ValueError('접촉 오프셋 출처 누락: ' + key)
    offset = profile['contact_calibration']['contact_offset_tool_m']
    if (not isinstance(offset, list) or len(offset) != 3
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in offset)
            or not profile['contact_calibration']['offset_record_id']):
        raise ValueError('접촉 오프셋 값·기록 ID 오류')
    profile['workcell'] = deepcopy(config['workcell'])
    profile['workcell'].update(axis_xy_m=m['axis_xy_m'], radius_m=m['radius_m'],
                               top_z_m=m['top_z_m'], bottom_z_m=m['bottom_z_m'], height_m=m['height_m'])
    return profile
