"""Shared draft wire conversions. Pure data conversion; no robot commands."""
from copy import deepcopy
import math

from planning_trial.assembly_optimizer import option_cost
from planning_trial.assembly_target import quaternion_xyzw_from_zyz


def error(code, reason, block=None):
    return {'code': code, 'reason': str(reason), 'block': deepcopy(block)}


def pose_mm_zyz(values):
    if (not isinstance(values, list) or len(values) != 6 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
        raise ValueError('Finite mm/ZYZ TCP pose required')
    return {'frame_id': 'base_link', 'xyz_m': [v/1000 for v in values[:3]],
            'quaternion_xyzw': quaternion_xyzw_from_zyz(values[3:])}


def box_to_region(box, stud_height_mm):
    # Internal support-face Z -> common first-stud-tip Z. XY axes stay Planner axes.
    if len(box) != 6 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
        raise ValueError('Finite contact box required')
    lo, hi = box[:3], box[3:]
    if any(lo[i] > hi[i] for i in range(3)):
        raise ValueError('Reversed contact box')
    axis = min(range(3), key=lambda i: hi[i]-lo[i])
    axes = [i for i in range(3) if i != axis]
    vertices = []
    for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
        point = [(lo[i]+hi[i])/2 for i in range(3)]
        point[axes[0]] = (lo, hi)[a][axes[0]]
        point[axes[1]] = (lo, hi)[b][axes[1]]
        point[2] -= stud_height_mm
        vertices.append([v/1000 for v in point])
    return {'frame_id': 'assembly_board', 'vertices_xyz_m': vertices}


def normalize_action(option, plan, step, assembly_context):
    manual = option['mode'] == 'HUMAN_ASSEMBLY'
    human = []
    for raw in option['human_actions']:
        hand = raw['hand']
        boxes = hand.get('contact_regions_board_mm') or [hand.get('contact_region_board_mm')]
        if not boxes or any(box is None for box in boxes):
            raise ValueError('Human contact region is required')
        human.append({'action': raw['action'], 'target_block': deepcopy(raw['target_block']),
                      'contact_regions': [box_to_region(b, assembly_context['geometry']['stud_height_mm']) for b in boxes],
                      'approach_sides': hand['side'].split('/'), 'hand_count': 1,
                      'force_direction_base': [0, 0, -1] if raw['action'] == 'PRESS' else None,
                      'force_magnitude_n': None,
                      'effect': {'HOLD': '아래 블록의 옆면을 잡아 유지', 'PRESS': '윗블록의 결합부를 아래로 누르기',
                                 'MANUAL_PLACE': '사람이 직접 조립'}[raw['action']],
                      'access_assessment': 'GEOMETRIC_CANDIDATE_NOT_RUNTIME_VERIFIED'})
    contacts = [{'lower_block': deepcopy(c['block']), 'upper_overlap_studs': c['upper_studs'],
                 'lower_overlap_studs': c['lower_studs'], 'board_supported': c['block']['layer'] == 1}
                for c in option['contacts']['weak_supports']]
    return {'plan_id': plan['plan_id'], 'step_id': step['step_id'], 'block': deepcopy(step['after']),
            'mode': option['mode'], 'grip_axis': option['grip_axis'],
            'gripper': {'pickup_policy': 'D_EXISTING_PICKUP',
                        'release_strategy': 'D_EXISTING_TRAY_RELEASE' if manual else option['release_strategy'],
                        'release_owner': 'D', 'policy_at_wait': 'D_TRAY_RELEASE_AND_RETREAT' if manual else 'HOLD_NO_AUTOMATIC_OPEN',
                        'numeric_open_command': None},
            'support_studs': option['contacts']['support_studs'], 'contacts': contacts,
            'robot_force_model': 'NOT_ROBOT_INSERTION' if manual else 'NOMINAL_BLOCK_CENTRE_BASE_MINUS_Z',
            'assistance_kind': option['assistance_kind'], 'human_actions': human,
            'human_hands_used': len(human), 'assistance_cost': list(option_cost(option)),
            'selection_basis': '기존 A 계산 후보를 동일 공간 설정으로 검증하고 선택',
            'requires_runtime_reassessment': True, 'optimality_verified': False}


def comparable_action(action):
    value = deepcopy(action)
    value.pop('selection_basis', None)
    return value
