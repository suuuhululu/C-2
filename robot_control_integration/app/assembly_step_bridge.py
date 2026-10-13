"""A 샘플을 D의 단계 작업으로 변환. 입력 파일은 계산 자료이며 실행 허가가 아니다."""
from copy import deepcopy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'fixtures/a_step_samples_20261010'


def read(path):
    return json.loads(Path(path).read_text())


def require_candidate(result):
    if result.get('status') != 'CANDIDATE' or result.get('errors'):
        raise ValueError('ASSESSMENT_NOT_CANDIDATE')


def load_step(directory):
    directory = Path(directory)
    request_path = directory / 'motion.request.json'
    result = step_from_messages(
        read(directory / 'reassessment.result.json'),
        read(request_path) if request_path.exists() else None,
        read(directory / 'motion.result.json') if request_path.exists() else None,
        summary=read(directory / 'step_summary.json'))
    result['source_directory'] = str(directory.resolve())
    return result


def step_from_messages(assessment, request, motion, *, case_id=None, summary=None):
    """Backend는 파일 저장 없이 A의 세 JSON 메시지를 직접 넘길 수 있다."""
    require_candidate(assessment)
    if summary is None:
        action = assessment['action_proposal']
        summary = dict(case_id=case_id, step_id=action['step_id'], plan_id=action['plan_id'],
                       block=action['block'], mode=action['mode'],
                       current_revision=request['latest_current']['current_revision'],
                       reserved_supply_slot=request['reserved_supply_slot'])
        if not case_id:
            raise ValueError('D_CASE_PROFILE_KEY_REQUIRED')
    action = assessment.get('action_proposal', summary.get('action'))
    if not action or action['block'] != summary['block'] or action['mode'] != summary['mode']:
        raise ValueError('STEP_ACTION_MISMATCH')
    if 'action_proposal' not in assessment and not any(
            all(action.get(k) == v for k, v in option.items()) for option in assessment.get('options', [])):
        raise ValueError('LEGACY_SELECTED_OPTION_NOT_ASSESSED')
    for key in ('plan_id', 'step_id'):
        if action[key] != summary.get(key, action[key]):
            raise ValueError('STEP_ID_MISMATCH')
    if request:
        if (request['assessment_context'] != assessment['context']
                or request['assessment_id'] != assessment['assessment_id']
                or request['assessment_input_digest'] != assessment['assessment_input_digest']):
            raise ValueError('ASSESSMENT_CONTEXT_OR_DIGEST_MISMATCH')
        if request['context']['plan_id'] != action['plan_id'] or request['context']['step_id'] != action['step_id']:
            raise ValueError('REQUEST_CONTEXT_ID_MISMATCH')
        if request['reserved_supply_slot'] != summary['reserved_supply_slot']:
            raise ValueError('RESERVATION_BINDING_MISMATCH')
        if request['assessed_action'] != action or request['action_proposal'] != action:
            raise ValueError('REASSESSMENT_MOTION_BINDING_MISMATCH')
        revision = request['latest_current']['current_revision']
        if revision != summary['current_revision'] or request['assessment_current_revision'] != revision:
            raise ValueError('CURRENT_REVISION_MISMATCH')
        if (motion.get('status') != 'CANDIDATE' or motion.get('errors') or not motion.get('motion_proposal')
                or motion['context'] != request['context'] or motion['assessment_id'] != request['assessment_id']):
            raise ValueError('MOTION_NOT_CANDIDATE')
    else:
        revision = assessment['assessment_current_revision']
        motion = None
    return dict(case_id=summary['case_id'], step_id=action['step_id'], plan_id=action['plan_id'],
                block=deepcopy(action['block']), action=deepcopy(action), current_revision=revision,
                reservation=deepcopy(summary.get('reserved_supply_slot')), summary=summary,
                request=request, motion=motion, source_execution_allowed=False)


def load_steps(directory=FIXTURES):
    return [load_step(p.parent) for p in sorted(Path(directory).glob('*/S*/step_summary.json'))]


def trial_footprint(block):
    """최소 점 좌표와 크기를 축 교환. 3D 자세를 반사하는 변환이 아니다."""
    dimensions = {'1x2x1': (1, 2), '2x2x1': (2, 2), '2x3x1': (2, 3)}
    nx, ny = dimensions[block['brick_type']]
    if block['orientation_deg'] not in (0, 90):
        raise ValueError('ORIENTATION_0_OR_90_REQUIRED')
    if block['orientation_deg'] == 90:
        nx, ny = ny, nx
    x, y, layer = block['x'], block['y'], block['layer']
    if any(type(v) is not int for v in (x, y, layer)) or not (1 <= layer <= 5):
        raise ValueError('INTEGER_GRID_AND_LAYER_REQUIRED')
    if not (0 <= x <= 24-nx and 0 <= y <= 24-ny):
        raise ValueError('FOOTPRINT_OUTSIDE_BOARD')
    return dict(min_xy=[y, x], size_xy=[ny, nx], centre_xy=[y+(ny-1)/2, x+(nx-1)/2],
                grip_axis_mapping={'x': 'y', 'y': 'x'})


def candidate_profile(steps):
    """수치 후보와 미확인 항목을 함께 출력. 교시 원자료를 승격하거나 덮어쓰지 않는다."""
    calibration = ROOT / 'calibration'
    layers = {}
    for row in read(calibration / 'layer_records.json'):
        if row.get('model_excluded') or row.get('adopt_as_layer_z') is False:
            continue
        if row['target']['x'] == 11 and (row['target']['y'] == 11 or row.get('adopt_as_layer_z')):
            layers[row['target']['layer']] = row
    affine = read(calibration / 'assembly_board_16mm_20261007.json')['affine_comparison']
    bypass = read(calibration / 'supply_place_bypass_waypoint_20261010.json')
    place = read(calibration / 'place_board_regrasp_5mm_20261010.json')['posx']
    yellow6 = read(calibration / 'yellow6_slot1_teaching_20261010.json')
    values = {}
    for step in steps:
        s = step['summary']
        nominal = s.get('nominal_assembly_target')
        reference = deepcopy(nominal['nominal_seated_tcp']['xyz_mm_zyz_deg']) if nominal else None
        if step['action']['mode'] == 'HUMAN_ASSEMBLY':
            reference = place.copy()
        notes = ['SAME_GRASP_TCP_AND_ORIENTATION_MUST_BE_REVIEWED', 'PICKUP_AND_MINIMAL_RELEASE_WIDTH_MUST_BE_TAUGHT']
        if step['block']['brick_type'] == '2x2x1' and step['block']['orientation_deg'] == 0:
            row = layers[step['block']['layer']]
            reference = row['sample']['posx'].copy()
            tx, ty = trial_footprint(step['block'])['min_xy']
            for i in (0, 1):
                reference[i] += ((tx-row['target']['x'])*affine['x_step_xyz_mm'][i]
                                 +(ty-row['target']['y'])*affine['y_step_xyz_mm'][i])
            notes.append('LAYER_MEASURED_AT_CENTRE_XY_SPATIAL_CANDIDATE_ONLY')
        if step['block']['brick_type'] == '2x3x1':
            notes.append('FAR_CORNER_22_21_EXCLUDED_NO_VALIDATED_FULL_BOARD_SIX_STUD_MODEL')
        pickup = yellow6['pickup_posx'] if (step['reservation'] and
                    step['reservation']['slot_id'] == 'yellow_2x3x1_01') else None
        values[step['case_id']+'/'+step['step_id']] = dict(
            reference_pose=reference, pickup_pose=pickup, physical_reference_reviewed=False,
            pickup_width_mm=40. if pickup else None, release_width_mm=None,
            release_pose=None, press_approach_pose=None, press_start_pose=None,
            press_width_mm=None, notes=notes)
    return dict(profile_id='D_STEP_CANDIDATE_20261010', physical_route_reviewed=False,
                human_collaboration_commissioning_ref=None,
                clearance_z_mm=111.83796691894531,
                supply_transit_xy_mm=bypass['latest_supply_transit_xy_mm'],
                body_bypass_xy_mm=bypass['posx'][:2], place_pose=place,
                approach_offset_mm=20.1, near_contact_offset_mm=1.,
                force_stop_n=35., max_press_travel_mm=5., transfer_velocity=32.,
                transfer_acceleration=16., descent_velocity=2., descent_acceleration=1.,
                gripper_force_n=40., steps=values)


def pose(value, name):
    if not isinstance(value, list) or len(value) != 6 or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('MISSING_OR_INVALID_POSE:'+name)
    return value.copy()


def release_feedback_range(settings, width):
    """Require sufficient opening; legacy task upper bounds no longer abort release.

    110mm is the RG2 measurement range, not a task clearance restriction.
    """
    bounds = settings.get('release_feedback_range_mm', [max(0., width-1.), min(110., width+1.)])
    if (not isinstance(bounds, list) or len(bounds) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds) or
            not 0 <= bounds[0] <= width <= bounds[1] <= 110):
        raise ValueError('INVALID_RELEASE_FEEDBACK_RANGE')
    return [bounds[0], 110.]


def build_plan(step, profile):
    for name in ('clearance_z_mm', 'approach_offset_mm', 'near_contact_offset_mm',
                 'force_stop_n', 'max_press_travel_mm', 'transfer_velocity',
                 'transfer_acceleration', 'descent_velocity', 'descent_acceleration', 'gripper_force_n'):
        v = profile[name]
        if type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
            raise ValueError('INVALID_PROFILE_PARAMETER:'+name)
    for name in ('pickup_descent_velocity','pickup_descent_acceleration'):
        if name in profile:
            v=profile[name]
            if type(v) not in (int,float) or not math.isfinite(v) or v<=0:
                raise ValueError('INVALID_PROFILE_PARAMETER:'+name)
    if profile['approach_offset_mm'] < 20 or profile['near_contact_offset_mm'] >= profile['approach_offset_mm']:
        raise ValueError('APPROACH_MUST_BE_AT_LEAST_20MM_ABOVE_REFERENCE')
    if profile['gripper_force_n'] > 40:
        raise ValueError('RG2_FORCE_OUT_OF_RANGE')
    key = step['case_id']+'/'+step['step_id']
    settings = deepcopy(profile['steps'][key])
    if 'assembly_tcp_zyz_deg' in settings:
        abc=settings['assembly_tcp_zyz_deg']
        if not isinstance(abc,list) or len(abc)!=3:
            raise ValueError('ASSEMBLY_TCP_ZYZ_TRIPLE_REQUIRED')
        pose([0.,0.,0.]+abc,'assembly_tcp_zyz_deg')
    if 'release_feedback_range_mm' in settings:
        width = settings.get('release_width_mm')
        if type(width) not in (int, float) or not math.isfinite(width):
            raise ValueError('D_MEASURED_RELEASE_WIDTH_REQUIRED')
        release_feedback_range(settings, width)
    if 'pickup_start_open_range_mm' in settings:
        bounds = settings['pickup_start_open_range_mm']
        close = settings.get('pickup_width_mm')
        if (not isinstance(bounds, list) or len(bounds) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds) or
                type(close) not in (int, float) or not math.isfinite(close) or
                not 0 <= close < bounds[0] <= bounds[1] <= 110):
            raise ValueError('INVALID_PICKUP_START_OPEN_RANGE')
    action = step['action']
    mode, assistance = action['mode'], action.get('assistance_kind', 'NONE')
    if mode not in ('ROBOT_GRIP', 'HUMAN_ASSEMBLY', 'ROBOT_RELEASE_PRESS') or assistance not in (
            'NONE', 'HOLD', 'PRESS', 'PRESS_AND_HOLD', 'MANUAL_ASSEMBLY', 'MANUAL_ASSEMBLY_AND_HOLD'):
        raise ValueError('UNSUPPORTED_METHOD')
    footprint = trial_footprint(step['block'])
    operations = ['PICK_AND_CONFIRM', 'LIFT', 'SUPPLY_20_0', 'BODY_BYPASS', 'PLACE_BOARD']
    if mode == 'HUMAN_ASSEMBLY':
        operations += ['TRAY_LOWER', 'CONFIRM_RELEASE', 'OPEN', 'RETREAT', 'HUMAN_ASSEMBLY_ACK']
    else:
        operations += ['TARGET_APPROACH_20MM', 'CONFIRM_ALIGNMENT']
        if mode == 'ROBOT_RELEASE_PRESS':
            operations += ['RELEASE_POSITION', 'CONFIRM_RELEASE', 'OPEN', 'PRESS_TOOL_APPROACH',
                           'CLOSE_EMPTY_PRESS_TOOL', 'PRESS_TOOL_LOWER', 'PRESS_35N']
        elif assistance in ('PRESS', 'PRESS_AND_HOLD'):
            operations += ['HUMAN_HOLD_READY', 'DESCEND_TO_NEAR_CONTACT', 'CONFIRM_SUPPORTED_RELEASE', 'OPEN', 'RETREAT',
                           'HUMAN_PRESS_AND_HOLD_ACK']
        else:
            if assistance == 'HOLD':
                operations.append('HUMAN_READY')
            operations += ['DESCEND_TO_NEAR_CONTACT', 'PRESS_35N']
        operations += ['CONFIRM_FULL_SEATING']
        if mode != 'ROBOT_RELEASE_PRESS' and assistance not in ('PRESS', 'PRESS_AND_HOLD'):
            operations += ['CONFIRM_RELEASE', 'OPEN']
        if assistance not in ('PRESS', 'PRESS_AND_HOLD'):
            operations.append('RETREAT')
    if settings.get('human_step_gestures'):
        if mode == 'HUMAN_ASSEMBLY':
            operations=operations[:5]+['TARGET_HIGH_HUMAN_WAIT','OPEN_HAND_RECEIVE',
                'HANDOVER_OPEN','THUMBS_UP_HUMAN_ASSEMBLY_ACK']
        else:
            ready='HUMAN_READY' if assistance=='HOLD' else 'HUMAN_HOLD_READY'
            operations.remove(ready)
            operations.insert(5,'TARGET_HIGH_HUMAN_WAIT')
            operations.insert(6,'THUMBS_UP_'+ready)
    operations.append('BACKEND_OBSERVATION_REQUIRED')
    plan = dict(key=key, plan_id=step['plan_id'], step_id=step['step_id'], block=step['block'],
                current_revision=step['current_revision'], reservation=step['reservation'],
                mode=mode, assistance_kind=assistance, human_actions=action.get('human_actions', []),
                trial_footprint=footprint, operations=operations, settings=settings,
                source_execution_allowed=False, hardware_verified=False, assembly_completion=False)
    from app.human_step_gestures import validate_policy as validate_human_policy
    validate_human_policy(plan, profile)
    from app.assembly_native_press import validate_native_press
    validate_native_press(plan,profile)
    return plan


def validate_physical(plan, profile, phase):
    """샘플의 false 플래그를 변경하는 대신 별도 D 교시 설정의 준비 상태를 검사한다."""
    s = plan['settings']
    if s.get('human_step_gestures') and phase not in ('full','pickup','approach','human-wait','human-ack'):
        raise ValueError('HUMAN_GESTURE_TRIAL_REQUIRES_FULL_OR_UPPER_APPROACH')
    if phase in ('human-wait','human-ack') and (plan['mode']!='HUMAN_ASSEMBLY' or
            plan['assistance_kind']!='MANUAL_ASSEMBLY' or not s.get('human_step_gestures')):
        raise ValueError('HUMAN_WAIT_REQUIRES_MANUAL_TARGET_HIGH_HANDOVER')
    if 'MOCK' in profile['profile_id'].upper():
        raise ValueError('MOCK_PROFILE_CANNOT_EXECUTE')
    if not s.get('physical_reference_reviewed'):
        raise ValueError('D_PHYSICAL_REFERENCE_REVIEW_REQUIRED')
    pose(s['reference_pose'], 'reference_pose')
    blend = profile.get('transport_blending')
    if blend is not None and (not isinstance(blend, dict) or blend.get('reviewed') is not True or
            type(blend.get('radius_mm')) not in (int, float) or
            not math.isfinite(blend['radius_mm']) or not 0 < blend['radius_mm'] <= 40):
        raise ValueError('REVIEWED_SMALL_TRANSPORT_BLEND_REQUIRED')
    if phase == 'grasp-recovery':
        if (plan['mode'] != 'ROBOT_GRIP' or plan['assistance_kind'] != 'NONE' or
                s.get('grasp_recovery_reviewed') is not True):
            raise ValueError('REVIEWED_UNASSISTED_GRASP_RECOVERY_REQUIRED')
        start = pose(s.get('grasp_recovery_start_pose'), 'grasp_recovery_start_pose')
        pickup = pose(s.get('pickup_pose'), 'pickup_pose')
        if any(abs(a-b) > .05 for a, b in zip(start, pickup)):
            raise ValueError('GRASP_RECOVERY_REQUIRES_TAUGHT_SLOT_POSE')
        bounds = s.get('grasp_recovery_start_width_range_mm')
        width = s.get('pickup_width_mm')
        if (not isinstance(bounds, list) or len(bounds) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds) or
                not 0 <= bounds[0] <= bounds[1] <= 110 or
                type(width) not in (int, float) or not math.isfinite(width) or
                not 0 <= width < bounds[0] or bounds[1]-width > 2):
            raise ValueError('GRASP_RECOVERY_REQUIRES_BOUNDED_ADDITIONAL_CLOSURE')
    if phase in ('full', 'pickup', 'approach', 'handover', 'assemble-held') and not profile.get('physical_route_reviewed'):
        raise ValueError('D_TAUGHT_ROUTE_REVIEW_REQUIRED')
    if phase in ('full', 'pickup'):
        pose(s['pickup_pose'], 'pickup_pose')
        if type(s['pickup_width_mm']) not in (int, float) or not 0 <= s['pickup_width_mm'] <= 110:
            raise ValueError('D_MEASURED_PICKUP_WIDTH_REQUIRED')
    if phase in ('full', 'pickup', 'release', 'retreat', 'handover', 'assemble-held'):
        width = s['release_width_mm']
        if type(width) not in (int, float) or not 0 <= width <= 110:
            raise ValueError('D_MEASURED_RELEASE_WIDTH_REQUIRED')
    if phase == 'retreat':
        if plan['mode'] != 'ROBOT_GRIP' or plan['assistance_kind'] != 'NONE':
            raise ValueError('RECOVERY_REQUIRES_UNASSISTED_ROBOT_GRIP')
        start = pose(s.get('recovery_start_pose'), 'recovery_start_pose')
        if 'release_feedback_range_mm' not in s:
            raise ValueError('REVIEWED_RECOVERY_RELEASE_RANGE_REQUIRED')
        release_feedback_range(s, s['release_width_mm'])
        height = max(profile['clearance_z_mm'], s['reference_pose'][2]+profile['approach_offset_mm'])
        if not 0 < height-start[2] <= 30.:
            raise ValueError('RECOVERY_REQUIRES_UPWARD_TRAVEL_AT_MOST_30MM')
    if phase == 'assemble-held' and (plan['mode'] != 'ROBOT_GRIP' or plan['assistance_kind'] != 'NONE'):
        raise ValueError('HELD_ASSEMBLY_REQUIRES_UNASSISTED_ROBOT_GRIP')
    if plan['mode'] == 'ROBOT_RELEASE_PRESS' and phase in ('full', 'contact'):
        for name in ('release_pose', 'press_approach_pose', 'press_start_pose'):
            pose(s[name], name)
        if type(s['press_width_mm']) not in (int, float) or not 0 <= s['press_width_mm'] <= 110:
            raise ValueError('D_PRESS_TOOL_WIDTH_REQUIRED')
    if plan['assistance_kind'] in ('HOLD', 'PRESS', 'PRESS_AND_HOLD', 'MANUAL_ASSEMBLY_AND_HOLD') and not profile.get('human_collaboration_commissioning_ref'):
        raise ValueError('D_HUMAN_COLLABORATION_COMMISSIONING_REQUIRED')
