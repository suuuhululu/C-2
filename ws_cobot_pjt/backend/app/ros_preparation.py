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


def copy_confidence(profile, m):
    profile['validity'] = m['validity']
    known = m.get('absolute_top_verification_known')
    verified = m.get('absolute_top_verified')
    if any(value is not None and type(value) is not bool for value in (known, verified)):
        raise ValueError('윗면 확인 수준은 bool 또는 미전달이어야 합니다.')
    if known is False and verified is True:
        raise ValueError('미확인 윗면의 verified=true는 허용되지 않습니다.')
    for key, value in (('absolute_top_verification_known', known), ('absolute_top_verified', verified)):
        profile[key] = value
        profile['measurement_assumptions'][key] = value


def bound_profile(base, goal, display, config, record):
    from .preparation import measured_profile
    if goal['source_mode'] == 'REAL':
        return real_bound_profile(goal, display, config, record)
    # /1 고정 기준은 변경하지 않는다. 동적 기하는 기존 /2 소비자에만 전달한다.
    from c2_path.pipeline import PROFILE_CONTRACT_V2, validate_profile
    profile = measured_profile(base, goal, display)
    copy_confidence(profile, display['observed_state']['measurement'])
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


def real_preview_profile(base, goal, display, config, record):
    """REAL 실측 기하만으로 만드는 미리보기 전용 스냅샷.

    실행 프로파일과 BIND는 사용하지 않는다. 이 스냅샷으로 생성한 경로는
    c2_path의 /3 계약에 따라 test_only이며 실제 공정 실행 입력이 아니다.
    """
    from .preparation import measured_profile
    from c2_path.pipeline import (CALIBRATION_STATUS_REAL_PREVIEW,
                                  PROFILE_CONTRACT_V3, validate_profile)
    profile = measured_profile(base, goal, display)
    measurement = display['observed_state']['measurement']
    profile.update(
        contract=PROFILE_CONTRACT_V3,
        source_mode='REAL',
        calibration_status=CALIBRATION_STATUS_REAL_PREVIEW,
        measurement_status=measurement['validity'],
        preparation_id=goal['preparation_id'],
        measurement_id=goal['measurement_id'],
        input_profile_snapshot_id=goal['input_profile_snapshot_id'],
        input_profile_sha256=goal['input_profile_sha256'],
        measurement_record_id=record['id'],
        measurement_record_sha256=record['sha256'],
        measured_at=measurement['measured_at'],
        label='REAL 실측 미리보기',
        note='실측 기하 기반 미리보기 전용. BIND·최종 관절 검사·실행 승인이 아닙니다.',
    )
    copy_confidence(profile, measurement)
    validate_profile(profile)
    return profile


def real_bound_profile(goal, display, config, record):
    """등록 실행 설정 + 이번 측정. 신뢰도 값을 승인 값으로 변조하지 않는다."""
    from .preparation import measured_profile
    from .real_execution_config import validate_real_execution_config
    template = validate_real_execution_config(config)
    profile = measured_profile(template, goal, display)
    # 2026-09-22 사용자 전달 승인: J6만 ±170°, 추가 여유 0°. J1~J5는 원본 유지.
    # measured_profile은 깊은 복사이므로 입력 설정과 기존 저장 스냅샷은 변경하지 않는다.
    profile['joint_check_arguments']['limits_deg'][5] = [-170.0, 170.0]
    profile['joint_check_arguments']['j6_margin_deg'] = 0.0
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
    copy_confidence(profile, m)
    profile['contact_calibration'] = deepcopy(config['workcell']['top'])
    profile['workcell'] = deepcopy(config['workcell'])
    profile['workcell'].update(axis_xy_m=m['axis_xy_m'], radius_m=m['radius_m'],
                               top_z_m=m['top_z_m'], bottom_z_m=m['bottom_z_m'], height_m=m['height_m'])
    return profile
