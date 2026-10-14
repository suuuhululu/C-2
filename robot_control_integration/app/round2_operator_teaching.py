"""Apply operator-recorded poses and preserve their rigid landing/pad relation.

This module only changes configuration data. Operator reports remain reports;
applying a bundle does not certify seating, a grasp height, or a contact surface.
"""
from copy import deepcopy
import warnings

from app.assembly_motion import vector


def retarget_pose(taught_landing, taught_pad, current_release):
    """Return T_release @ inv(T_landing) @ T_pad, using robot ZYZ degrees."""
    from scipy.spatial.transform import Rotation
    landing = vector(taught_landing, 6, 'taught landing pose')
    pad = vector(taught_pad, 6, 'taught pad pose')
    release = vector(current_release, 6, 'current release pose')
    if release == landing:
        # Keep the exact recorded Euler representation when no retarget is needed.
        return pad
    delta = (Rotation.from_euler('ZYZ', release[3:], degrees=True)
             * Rotation.from_euler('ZYZ', landing[3:], degrees=True).inv())
    xyz = delta.apply([pad[i] - landing[i] for i in range(3)])
    rotation = delta * Rotation.from_euler('ZYZ', pad[3:], degrees=True)
    # At a ZYZ singularity scipy chooses an equivalent Euler representation.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Gimbal lock detected.*', category=UserWarning)
        abc = rotation.as_euler('ZYZ', degrees=True)
    return [release[i] + float(xyz[i]) for i in range(3)] + abc.tolist()


def _matching_row(config, bundle):
    target = config['alignment_target']['target']
    expected = dict(bundle['target'], color=bundle['color'], brick_type=bundle['brick_type'])
    if any(target.get(key) != expected.get(key)
           for key in ('color', 'brick_type', 'x', 'y', 'layer', 'orientation_deg')):
        raise ValueError('TEACHING_TARGET_MISMATCH')
    step_id = config.get('trial_step', {}).get('step_id')
    if step_id is not None and step_id != bundle['step_id']:
        raise ValueError('TEACHING_STEP_MISMATCH')
    if any(config['connection'][key] != bundle[key] for key in ('tcp', 'tool')):
        raise ValueError('TEACHING_TCP_TOOL_MISMATCH')
    rows = [row for row in config['blocks']
            if (row['color'], row['brick_type'], row['slot'])
            == (bundle['color'], bundle['brick_type'], bundle['supply_slot'])]
    if len(rows) != 1:
        raise ValueError('TEACHING_BLOCK_MISMATCH')
    return rows[0]


def apply_teaching(config, bundle):
    """Copy a matching trial config and install its three recorded poses.

    The caller loads any JSON files. No execution/approval flags in the capture
    artifact are treated as live hardware conditions here.
    """
    value = deepcopy(config)
    row = _matching_row(value, bundle)
    poses = {key: vector(bundle[key]['tcp_pose_mm_zyz_deg'], 6, f'{key} pose')
             for key in ('pickup', 'landing', 'pad_top')}
    alignment = value['alignment_target']
    old_landing = vector(alignment['placement_tcp_reference'], 6, 'placement reference')
    approach = vector([value['alignment_approach_z_mm']], 1, 'alignment approach Z')[0]
    clearance = approach - old_landing[2]
    baseline = dict(pickup_pose=deepcopy(row.get('baseline_pickup_pose', row['pickup_pose'])),
                    placement_tcp_reference=deepcopy(alignment.get(
                        'baseline_placement_tcp_reference', old_landing)),
                    pad_contact_pose=deepcopy(value.get('operator_teaching', {}).get(
                        'baseline', {}).get('pad_contact_pose', value['integrated_pad_contact_pose'])))
    row.setdefault('baseline_pickup_pose', deepcopy(baseline['pickup_pose']))
    alignment.setdefault('baseline_placement_tcp_reference',
                         deepcopy(baseline['placement_tcp_reference']))
    row['pickup_pose'] = poses['pickup'].copy()
    row['pose_source'] = bundle['pickup'].get('source', 'OPERATOR_THREE_POSE_BUNDLE')
    row['pose_basis'] = 'OPERATOR_RECORDED_CONTINUOUS_GRASP_PAIR'
    # An older nominal center mapping does not describe the newly recorded grasp.
    row.pop('center_mapping', None)
    alignment['placement_tcp_reference'] = poses['landing'].copy()
    alignment['source'] = bundle['landing'].get('source', 'OPERATOR_THREE_POSE_BUNDLE')
    value['assembly_target_xy'] = poses['landing'][:2]
    value['alignment_approach_z_mm'] = poses['landing'][2] + clearance
    value['integrated_pad_contact_pose'] = poses['pad_top'].copy()
    value['pad_contact_basis'] = 'OPERATOR_RECORDED_PAD_TO_LANDING_RIGID_RELATION'
    # Absolute recorded poses replace the previous +10 mm experiment, not add to it.
    value.pop('operator_raised_z_trial', None)
    value['operator_teaching'] = dict(
        version='round2-operator-teaching-config/1', step_id=bundle['step_id'],
        target=deepcopy(alignment['target']), supply_slot=bundle['supply_slot'],
        tcp=bundle['tcp'], tool=bundle['tool'], source_poses=deepcopy(poses),
        source_refs={key: bundle[key].get('source') for key in poses}, baseline=baseline,
        source_pair=bundle.get('source_pair'),
        operator_confirmation=deepcopy(bundle.get('operator_confirmation', {})),
        grasp_height_estimate_mm=bundle.get('grasp_height_estimate_mm'),
        grasp_height_independently_measured=bundle.get('grasp_height_independently_measured', False),
        pad_contact_independently_sensor_verified=bundle.get('pad_contact_independently_sensor_verified', False),
        additional_base_z_offset_mm=0., assembly_completion=False)
    return value


def retarget_assembly_reference(config, new_landing_pose):
    """Copy a config and carry its current pad relation with a corrected landing."""
    value = deepcopy(config)
    old_landing = vector(value['alignment_target']['placement_tcp_reference'], 6, 'placement reference')
    new_landing = vector(new_landing_pose, 6, 'new placement reference')
    pad = retarget_pose(old_landing, value['integrated_pad_contact_pose'], new_landing)
    clearance = value['alignment_approach_z_mm'] - old_landing[2]
    value['alignment_target']['placement_tcp_reference'] = new_landing
    value['assembly_target_xy'] = new_landing[:2]
    value['integrated_pad_contact_pose'] = pad
    value['alignment_approach_z_mm'] = new_landing[2] + clearance
    return value
