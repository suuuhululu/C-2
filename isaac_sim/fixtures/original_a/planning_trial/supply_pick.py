"""Pure supply-slot TCP calculation from four hole references and one taught grip.

No slot counters, reservation, robot commands, or separate SIM/REAL calculation.
Native controller mm/ZYZ degrees are labelled; wire conversion belongs to adapter.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path


MEASUREMENTS = Path(__file__).resolve().parent / 'measurements'
SOURCES = {
    'corners': 'supply_board_corners.user_20261007.pass2.json',
    'layout': 'supply_layout.user_20261007.json',
    'first_grasp': 'first_supply_grasp.user_20261007.json',
    'closed_tip': 'closed_tip_reference.user_20261007.json',
    'held_offset': 'pedestal_grasp.user_20261007.json',
    'grasp_depth_policy': 'supply_grasp_depth_policy.user_20261008.json',
    'latest_geometry': 'block_geometry.user_20261008.rev2.json',
    'material_reference': 'abs_reference_properties.user_20261008.json',
}


def finite(values, size, label):
    if (not isinstance(values, list) or len(values) != size or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
        raise ValueError(label + ': finite numeric list required')


def load_supply_profile(measurements_dir=MEASUREMENTS):
    """Read user measurements without modifying them; retain their assumptions."""
    directory = Path(measurements_dir)
    data, hashes = {}, {}
    for key, name in SOURCES.items():
        raw = (directory / name).read_bytes()
        data[key] = json.loads(raw)
        hashes[name] = sha256(raw).hexdigest()
    for key in ('corners', 'first_grasp', 'closed_tip', 'held_offset'):
        if data[key]['xyz_unit'] != 'mm' or data[key]['orientation_unit'] != 'degree':
            raise ValueError('User measurement units must remain mm/degree')
    layout = data['layout']
    depth = data['grasp_depth_policy']
    profile = {
        'profile_version': 'supply-pick-measured-rule/0.2',
        'profile_id': 'supply-' + sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16],
        'source_hashes': hashes,
        'corners_tcp_mm_zyz_deg': data['corners']['reported_base_poses_xyz_abc'],
        'grid_feature_count': layout['grid_feature_count'],
        'grid_count_source': layout['count_source'],
        'origin_corner': layout['supply_grid_origin_corner'],
        'positive_x_corner': layout['supply_grid_positive_x_corner'],
        'positive_y_corner': layout['supply_grid_positive_y_corner'],
        'opposite_corner': '1',
        'first_pick_tcp_mm_zyz_deg': data['first_grasp']['reported_base_pose_xyz_abc'],
        'first_pick_identity': {'brick_type': data['first_grasp']['brick_type'],
                                'color': data['first_grasp']['color'], 'slot_index': 1},
        'columns': deepcopy(layout['columns']),
        'same_setup_confirmed': data['first_grasp']['grasp_and_new_board_coordinates_same_setup_confirmed'],
        'support_surface_kind': 'FLIPPED_PLATE_UPPER_FACE_WITH_HOLES',
        'z_policy': 'TAUGHT_FIRST_PICK_Z_PLUS_EXPLICIT_GRIP_HEIGHT_SHIFT',
        'orientation_policy': 'PRESERVE_TAUGHT_FIRST_PICK_ZYZ',
        'closed_tip_z_offset_reference_mm': data['closed_tip']['closed_tip_below_reported_tcp_base_z_mm'],
        'held_tcp_above_bottom_reference_mm': data['held_offset']['tcp_to_block_bottom_height_difference_mm'],
        'anchor_grip_height_above_bottom_mm': data['first_grasp']['gripper_tip_to_block_bottom_distance_reported_mm'],
        'desired_grip_height_above_bottom_mm': depth['target_grip_height_above_block_bottom_mm'],
        'grip_height_reference_equivalence': depth['reference_equivalence'],
        'target_grip_reference': depth['target_reference_point'],
        'block_body_height_mm': data['latest_geometry']['body_height_mm'],
        'material_metadata': {**data['latest_geometry']['material'], 'reference_properties':data['material_reference']},
        'absolute_first_block_grid_footprint': layout['absolute_first_block_grid_footprint'],
        'execution_allowed': False,
    }
    validate_profile(profile)
    return profile


def validate_profile(p):
    counts = p['grid_feature_count']
    if (not isinstance(counts, list) or len(counts) != 2 or
            any(type(v) is not int or v < 2 for v in counts)):
        raise ValueError('Two grid feature counts >=2 required; intervals = count-1')
    ids = [p[k] for k in ('origin_corner', 'positive_x_corner', 'positive_y_corner', 'opposite_corner')]
    if len(set(ids)) != 4 or set(ids) != set(p['corners_tcp_mm_zyz_deg']):
        raise ValueError('Four unique corner IDs required')
    for pose in p['corners_tcp_mm_zyz_deg'].values():
        finite(pose, 6, 'corner pose')
    finite(p['first_pick_tcp_mm_zyz_deg'], 6, 'first taught TCP pose')
    finite([p['closed_tip_z_offset_reference_mm'], p['held_tcp_above_bottom_reference_mm']], 2, 'reference Z offsets')
    finite([p['anchor_grip_height_above_bottom_mm'], p['desired_grip_height_above_bottom_mm'], p['block_body_height_mm']], 3, 'grip heights')
    if any(not 0 <= p[k] < p['block_body_height_mm'] for k in ('anchor_grip_height_above_bottom_mm','desired_grip_height_above_bottom_mm')):
        raise ValueError('Taught and desired pad heights must lie along the block body side')
    if p['grip_height_reference_equivalence'] not in ('ASSUMED_PENDING_USER_CONFIRMATION','USER_CONFIRMED_SAME_REFERENCE'):
        raise ValueError('Different tip/pad references require a measured reference offset; do not infer a 3mm shift')
    if p['same_setup_confirmed'] is not True:
        raise ValueError('Corner measurements and taught pick must be from same setup')
    if p['z_policy'] != 'TAUGHT_FIRST_PICK_Z_PLUS_EXPLICIT_GRIP_HEIGHT_SHIFT':
        raise ValueError('Unsupported Z policy; never infer tilt from noisy corner heights')
    if p['orientation_policy'] != 'PRESERVE_TAUGHT_FIRST_PICK_ZYZ':
        raise ValueError('Unsupported grasp attitude policy')
    if p['first_pick_identity'] != {'brick_type': '2x2x1', 'color': 'yellow', 'slot_index': 1}:
        raise ValueError('Expected taught anchor is yellow 2x2 slot 1')
    cols = sorted(p['columns'], key=lambda c: c['photo_order_left_to_right'])
    expected = [('2x2x1', 'yellow'), ('2x3x1', 'yellow'), ('2x2x1', 'blue'), ('2x3x1', 'blue')]
    if [(c['brick_type'], c['color']) for c in cols] != expected:
        raise ValueError('Supply column identities/order differ from measured layout')
    for c in cols:
        if c['occupied_grid_x'] != 2 or c['occupied_grid_y'] != (2 if c['brick_type'] == '2x2x1' else 3):
            raise ValueError('2x3 long face must run along supply grid Y; grip width 2 along X')
        for key in ('slot_count', 'gap_between_slots_x'):
            if type(c[key]) is not int or c[key] < (1 if key == 'slot_count' else 0):
                raise ValueError('Invalid slot count/gap')
        gap = c['gap_before_column_y']
        if c != cols[0] and (type(gap) is not int or gap < 0):
            raise ValueError('Column gap required')
        if c['slot_count'] != 6:
            raise ValueError('Current measured layout has six slots per type/color')
    span_x = max((c['slot_count'] - 1) * (c['occupied_grid_x'] + c['gap_between_slots_x']) + c['occupied_grid_x'] for c in cols)
    span_y = sum(c['occupied_grid_y'] for c in cols) + sum(c['gap_before_column_y'] for c in cols[1:])
    if span_x > counts[0] or span_y > counts[1]:
        raise ValueError('Relative layout span exceeds board grid; absolute edge alignment still requires anchor')
    return cols


def fit_grid_xy(profile):
    """Average both opposite edges: four-corner affine XY fit, not Z tilt."""
    validate_profile(profile)
    poses = profile['corners_tcp_mm_zyz_deg']
    o, x, y, opposite = [poses[profile[k]] for k in
                          ('origin_corner', 'positive_x_corner', 'positive_y_corner', 'opposite_corner')]
    nx, ny = profile['grid_feature_count']
    ex = [((x[j] - o[j]) + (opposite[j] - y[j])) / (2 * (nx - 1)) for j in range(2)]
    ey = [((y[j] - o[j]) + (opposite[j] - x[j])) / (2 * (ny - 1)) for j in range(2)]
    if abs(ex[0] * ey[1] - ex[1] * ey[0]) < 1e-9:
        raise ValueError('Degenerate hole-grid geometry')
    closure = [opposite[j] - x[j] - y[j] + o[j] for j in range(2)]
    return {'x_step_xy_mm': ex, 'y_step_xy_mm': ey,
            'x_pitch_mm': math.hypot(*ex), 'y_pitch_mm': math.hypot(*ey),
            'interval_counts': [nx - 1, ny - 1],
            'corner_closure_residual_xy_mm': closure,
            'affine_corner_residual_norm_xy_mm': math.hypot(*closure) / 4,
            'raw_corner_tcp_z_spread_mm': max(v[2] for v in poses.values()) - min(v[2] for v in poses.values())}


def relative_centres(profile):
    """Derive centre offsets from occupied cell widths and empty-row gaps."""
    cols = validate_profile(profile)
    offset_y, last_width = 0.0, None
    centres = {}
    for c in cols:
        width = c['occupied_grid_y']
        if last_width is not None:
            offset_y -= last_width / 2 + c['gap_before_column_y'] + width / 2
        centres[(c['brick_type'], c['color'])] = {
            'first_centre_relative_grid': [0.0, offset_y],
            'slot_step_grid_x': -(c['occupied_grid_x'] + c['gap_between_slots_x']),
            'slot_count': c['slot_count'],
        }
        last_width = width
    return centres


def calculate_supply_pick(brick_type, color, slot_index, *, profile=None):
    """Calculate a D-selected slot's TCP candidate; never select/wrap/consume slots."""
    if type(slot_index) is not int or not 1 <= slot_index <= 6:
        raise ValueError('slot_index must be an integer from 1 to 6; D manages refill/wrap')
    if not isinstance(brick_type, str) or not isinstance(color, str):
        raise ValueError('brick_type/color must be supported strings')
    p = load_supply_profile() if profile is None else profile
    grid = fit_grid_xy(p)
    mapping = relative_centres(p)
    if (brick_type, color) not in mapping:
        raise ValueError('Only yellow/blue 2x2x1/2x3x1 slots are supported')
    c = mapping[(brick_type, color)]
    dx = c['slot_step_grid_x'] * (slot_index - 1)
    dy = c['first_centre_relative_grid'][1]
    anchor = p['first_pick_tcp_mm_zyz_deg']
    shift_z = p['desired_grip_height_above_bottom_mm'] - p['anchor_grip_height_above_bottom_mm']
    pose = [anchor[j] + dx * grid['x_step_xy_mm'][j] + dy * grid['y_step_xy_mm'][j]
            for j in range(2)] + [anchor[2] + shift_z] + list(anchor[3:])
    return {
        'schema_version': 'supply-pick-coordinate-candidate/0.2',
        'profile_id': p['profile_id'], 'status': 'COORDINATE_CANDIDATE',
        'brick_type': brick_type, 'color': color, 'slot_index': slot_index,
        'relative_block_centre_grid': [dx, dy],
        'pickup_tcp_pose': {'frame_id': 'robot_base', 'position_unit': 'mm',
                            'orientation_unit': 'degree', 'orientation_convention': 'ZYZ',
                            'xyz_abc': pose},
        'grasp': {'width_grid_cells': 2, 'closing_axis': 'SUPPLY_GRID_X',
                  'contact': 'LONG_SIDE_MIDPOINT' if brick_type == '2x3x1' else 'OPPOSITE_SIDE_MIDPOINT',
                  'pad_bottom_above_block_bottom_mm': p['desired_grip_height_above_bottom_mm'],
                  'taught_reference_height_mm': p['anchor_grip_height_above_bottom_mm'],
                  'tcp_z_shift_from_taught_mm': shift_z,
                  'reference_equivalence': p['grip_height_reference_equivalence'],
                  'target_reference': p['target_grip_reference'],
                  'derived_not_remeasured': True,
                  'close_command_source': 'D_EXISTING_SETTINGS_NO_A_OVERRIDE'},
        'execution_allowed': False, 'slot_readiness_checked': False,
        'slot_management_owner': 'D',
        'provenance': 'FOUR_CORNER_XY_SPACING_PLUS_TAUGHT_FIRST_PICK_TCP',
        'height_policy': p['z_policy'], 'orientation_policy': p['orientation_policy'],
    }


def calculate_all_supply_picks(*, profile=None):
    p = load_supply_profile() if profile is None else profile
    grid = fit_grid_xy(p)
    picks = [calculate_supply_pick(c['brick_type'], c['color'], slot, profile=p)
             for c in validate_profile(p) for slot in range(1, 7)]
    ref_plane_z = (sum(v[2] for v in p['corners_tcp_mm_zyz_deg'].values()) / 4
                   - p['closed_tip_z_offset_reference_mm'])
    alternate_z = ref_plane_z + p['held_tcp_above_bottom_reference_mm']
    shift_z = p['desired_grip_height_above_bottom_mm'] - p['anchor_grip_height_above_bottom_mm']
    return {'schema_version': 'supply-pick-coordinate-table/0.2', 'profile_id': p['profile_id'],
            'execution_allowed': False, 'source_hashes': p['source_hashes'],
            'grid': grid, 'grid_count_source': p['grid_count_source'],
            'z_diagnostic': {'approx_surface_from_closed_tip_mean_mm': ref_plane_z,
                             'approx_pick_tcp_from_two_offsets_mm': alternate_z,
                             'selected_taught_pick_tcp_z_mm': p['first_pick_tcp_mm_zyz_deg'][2],
                             'desired_grip_height_mm': p['desired_grip_height_above_bottom_mm'],
                             'tcp_z_shift_from_taught_mm': shift_z,
                             'selected_pick_candidate_tcp_z_mm': p['first_pick_tcp_mm_zyz_deg'][2] + shift_z,
                             'derived_tcp_above_bottom_for_target_mm': p['held_tcp_above_bottom_reference_mm'] + shift_z,
                             'taught_minus_two_offset_estimate_mm': p['first_pick_tcp_mm_zyz_deg'][2] - alternate_z,
                             'policy': 'Use taught grip Z plus explicit desired-minus-anchor depth; corner estimate remains diagnostic.'},
            'limits': ['24x24 hole count inherited from existing record; intervals are 23, not 24.',
                       'Absolute first block hole footprint and full TCP-to-block XY transform are uncalibrated.',
                       'Offsets transfer the first taught centre grip under identical block alignment/height/grasp assumptions.',
                       'Board is level; raw corner Z variation is not modelled as actual tilt.',
                       'User confirmed old 8mm tip and new 5mm pad-bottom reference coincide; new depth pose is derived, not remeasured.',
                       'D verifies slots, actual grasp/path, TCP setting, and execution approval.'],
            'count': len(picks), 'slots': picks}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    p = load_supply_profile()
    result = calculate_all_supply_picks(profile=p)
    (args.output_dir / 'profile.json').write_text(json.dumps(p, ensure_ascii=False, indent=2) + '\n')
    (args.output_dir / 'pickup_coordinates.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lines = ['# 공급판 픽업 TCP 계산표', '', '단위: Base XYZ mm, ABC degree/ZYZ. 실측 첫 픽업 기준 상대 계산 후보.', '',
             '| 블록 | 슬롯 | X | Y | Z |', '|---|---:|---:|---:|---:|']
    for pick in result['slots']:
        x, y, z, a, b, c = pick['pickup_tcp_pose']['xyz_abc']
        lines.append(f"| {pick['color']} {pick['brick_type']} | {pick['slot_index']} | {x:.3f} | {y:.3f} | {z:.3f} |")
        print(f"{pick['color']:6} {pick['brick_type']} slot {pick['slot_index']}: ({x:.3f}, {y:.3f}, {z:.3f}, {a:.2f}, {b:.2f}, {c:.2f})")
    lines += ['', '모든 ABC는 첫 실측 (62.73, -179.99, 63.50)를 유지한다.',
              f"구멍 24×24의 23개 간격으로 보간. 파지 높이 {p['desired_grip_height_above_bottom_mm']:g}mm, 실측8mm 기준 TCP Z에 {p['desired_grip_height_above_bottom_mm']-p['anchor_grip_height_above_bottom_mm']:+g}mm 적용.",
              '기존8mm 끝단과 새5mm 패드 하단이 동일 기준점이라는 조건의 계산이며 변경 자세는 아직 재실측하지 않았다.',
              '슬롯 예약·보충·실제 집기/경로 확인과 D 실행 승인은 별도다.',
              '블록 중심의 격자 이동량을 TCP에 적용한 후보이며, 블록 밑면 pose 자체가 아니다.']
    (args.output_dir / 'pickup_coordinates.md').write_text('\n'.join(lines) + '\n')
    print('Saved:', args.output_dir.resolve())


if __name__ == '__main__':
    main()
