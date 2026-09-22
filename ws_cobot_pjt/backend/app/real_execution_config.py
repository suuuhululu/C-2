"""측정값을 합성하지 않는 REAL 정적 설정 사전 검사."""
import math


def validate_real_execution_config(config):
    template = config.get('execution_profile')
    if not isinstance(template, dict):
        raise ValueError('REAL 가공 설정 execution_profile이 없습니다. C2_EXECUTION_PROFILE 또는 --execution-profile로 배포 실행 설정을 연결하세요.')
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
    contact = config['workcell'].get('top', {})
    for key in ('offset_status', 'offset_record_id', 'contact_offset_tool_m'):
        if key not in contact:
            raise ValueError('접촉 오프셋 출처 누락: ' + key)
    offset = contact['contact_offset_tool_m']
    if (not isinstance(offset, list) or len(offset) != 3
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in offset)
            or not contact['offset_record_id']):
        raise ValueError('접촉 오프셋 값·기록 ID 오류')
    context = template['execution_context']
    for key in ('motion_profiles', 'tool_profile', 'stop_profile'):
        if not isinstance(context.get(key), dict):
            raise ValueError('REAL execution_context.' + key + ' 설정 누락')
    from c2_path.workcell import MOTION_PROFILE
    for name in MOTION_PROFILE.values():
        if name not in context['motion_profiles']:
            raise ValueError('REAL 이동 프로파일 누락: ' + name)
    for name, motion in context['motion_profiles'].items():
        if not isinstance(motion, dict):
            raise ValueError('REAL 이동 프로파일 누락: ' + name)
        for key in ('vel_mm_s', 'acc_mm_s2', 'pos_tol_mm', 'completion_timeout_s'):
            positive(motion.get(key), 'motion_profiles.' + name + '.' + key)
    stop = context['stop_profile']
    if type(stop.get('mode')) is not int:
        raise ValueError('stop_profile.mode 정수 설정 누락')
    positive(stop.get('confirmation_timeout_s'), 'stop_profile.confirmation_timeout_s')
    tool = context['tool_profile']
    if tool.get('tool_id') != template['tool_id']:
        raise ValueError('tool_profile.tool_id 불일치')
    if tool.get('contact_mode') not in ('fixed_depth', 'force_touch'):
        raise ValueError('tool_profile.contact_mode 설정 누락')
    clearance = tool.get('clearance_m')
    if isinstance(clearance, dict):
        clearance = clearance.get('stroke')
    positive(clearance, 'tool_profile.clearance_m')
    if tool['contact_mode'] == 'fixed_depth':
        depth = tool.get('depth_m')
        if type(depth) not in (int, float) or not math.isfinite(depth) or depth < 0:
            raise ValueError('tool_profile.depth_m 비음수 설정 필요')
    else:
        for key in ('touch_force_n', 'touch_speed_mm_s'):
            positive(tool.get(key), 'tool_profile.' + key)
    joints = template['joint_check_arguments']
    limits = joints.get('limits_deg')
    if (not isinstance(limits, list) or len(limits) != 6
            or any(not isinstance(pair, list) or len(pair) != 2
                   or any(type(v) not in (float, int) or not math.isfinite(v) for v in pair)
                   or pair[0] >= pair[1] for pair in limits)):
        raise ValueError('joint_check_arguments.limits_deg 6축 범위 오류')
    margin = joints.get('j6_margin_deg')
    if (type(margin) not in (float, int) or not math.isfinite(margin)
            or margin < 0 or 2 * margin >= limits[5][1] - limits[5][0]):
        raise ValueError('joint_check_arguments.j6_margin_deg 오류')
    return template


def positive(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + ' 양수 설정 필요')
