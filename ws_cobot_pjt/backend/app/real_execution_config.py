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
    validate_entry_planning(context.get('entry_planning'), context['motion_profiles'])
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
    cut_contact = tool.get('cut_contact')
    if cut_contact is not None:
        if tool['contact_mode'] != 'force_touch':
            raise ValueError('tool_profile.cut_contact는 force_touch에서만 사용 가능')
        if cut_contact not in ('normal_force_hold', 'chunk_adaptive'):
            raise ValueError('tool_profile.cut_contact 미지원: ' + repr(cut_contact))
        if tool.get('tool_axis') not in ('x', '+x', '-x', 'y', '+y', '-y', 'z', '+z', '-z'):
            raise ValueError('tool_profile.tool_axis ±x/±y/±z 명시 필요')
        for key in ('force_limit_n', 'air_force_limit_n'):
            positive(tool.get(key), 'tool_profile.' + key)
        bounds = tool.get('touch_offset_range_m')
        extra = tool.get('touch_extra_m')
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
                or bounds[0] > bounds[1] or type(extra) not in (int, float)
                or not math.isfinite(extra) or extra < 0
                or bounds[0] < -clearance or bounds[1] > extra):
            raise ValueError('tool_profile.touch_offset_range_m/clearance_m/touch_extra_m 범위 오류')
        if cut_contact == 'normal_force_hold':
            positive(tool.get('cut_force_n'), 'tool_profile.cut_force_n')
            stiffness = tool.get('cut_stiffness')
            if (not isinstance(stiffness, (list, tuple)) or len(stiffness) != 6
                    or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                           for v in stiffness)):
                raise ValueError('tool_profile.cut_stiffness 6축 범위 오류')
            ramp = tool.get('ramp_s')
            if (type(ramp) not in (int, float) or not math.isfinite(ramp)
                    or not 0 <= ramp <= 1):
                raise ValueError('tool_profile.ramp_s 0~1 범위 오류')
        else:
            low, high = tool.get('cut_force_min_n'), tool.get('cut_force_max_n')
            if (type(low) not in (int, float) or not math.isfinite(low) or low <= 0
                    or type(high) not in (int, float) or not math.isfinite(high)
                    or high <= 0 or low > high):
                raise ValueError('tool_profile.cut_force_min_n/cut_force_max_n 범위 오류')
            positive(tool.get('adaptive_step_m'), 'tool_profile.adaptive_step_m')
            points = tool.get('adaptive_chunk_points')
            if type(points) is not int or not 2 <= points <= 80:
                raise ValueError('tool_profile.adaptive_chunk_points 2~80 정수 필요')
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


def validate_entry_planning(policy, motion_profiles):
    """REAL 진입 정책을 읽기 전용으로 검사한다.

    양초 중심·반지름·윗면은 측정 스냅샷에서 공급한다. 여기서는 그 값에
    상대적인 상공 탐색 범위와 IK/관절 검사 기준만 검증한다.
    """
    if not isinstance(policy, dict) or policy.get('enabled') is not True:
        raise ValueError('REAL execution_context.entry_planning.enabled=true 설정 필요')
    bounds = policy.get('tcp_clearance_above_top_range_m')
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in bounds)
            or bounds[0] <= 0 or bounds[0] > bounds[1]):
        raise ValueError('entry_planning.tcp_clearance_above_top_range_m 범위 오류')
    required = ('tcp_z_step_m', 'sample_m', 'sample_deg', 'min_radial_gap_m',
                'min_j3_abs_deg', 'min_j5_margin_deg', 'max_joint_step_deg',
                'start_position_tolerance_m', 'start_angle_tolerance_deg')
    for key in required:
        positive(policy.get(key), 'entry_planning.' + key)
    if (policy['tcp_z_step_m'] > bounds[1] - bounds[0]
            and not math.isclose(bounds[0], bounds[1])):
        raise ValueError('entry_planning.tcp_z_step_m이 탐색 범위보다 큼')
    profile_id = policy.get('motion_profile_id')
    if (not isinstance(profile_id, str) or not profile_id
            or profile_id not in motion_profiles):
        raise ValueError('entry_planning.motion_profile_id가 이동 프로파일에 없음')
    return policy


def positive(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + ' 양수 설정 필요')
