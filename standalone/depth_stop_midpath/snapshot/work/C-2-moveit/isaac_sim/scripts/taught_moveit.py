"""Read taught TCPs into the existing MoveIt request format, without ROS or A forks.

This imports a recorded shared-A result, not a live D execution authorization.
It deliberately does not manufacture collision objects from TCP reference Z.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import sys
import warnings

import numpy as np
from scipy.spatial.transform import Rotation, Slerp
import yaml
from sim_utils import save, pose_matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from planning_trial.assembly_adapter import handle_step_motion
from planning_trial.assembly_contract import VERSION

GROUPS = [('yellow', '2x2x1'), ('yellow', '2x3x1'), ('blue', '2x2x1'),
          ('blue', '2x3x1'), ('red', '1x2x1')]


def pose_mm_zyz(point):
    if len(point) != 6 or any(type(v) not in (int, float) for v in point) or not np.isfinite(point).all():
        raise ValueError('Expected six finite mm/ZYZ-degree values')
    return dict(frame_id='base_link', xyz_m=(np.array(point[:3])/1000).tolist(),
                quaternion_xyzw=Rotation.from_euler('ZYZ', point[3:], degrees=True).as_quat().tolist())


def read_teaching(path):
    path = Path(path)
    raw = path.read_bytes()
    data = json.loads(raw)
    if (data.get('sample_kind') != 'OPERATOR_TAUGHT_READ_ONLY' or
            data.get('tcp') != 'GripperDA_v4' or data.get('tool') != 'ToolWeight0' or
            data.get('execution_allowed') is not False):
        raise ValueError('Matching read-only TCP/tool teaching required')
    for key, row in data['records'].items():
        pose_mm_zyz(row['tcp_pose_mm_zyz_deg'])
        if (row.get('case_id') != key or row.get('operator_confirmed') is not True or
                row.get('source') != 'READ_ONLY_DEVICE_QUERY' or
                row.get('receipt', {}).get('physical_commands') != 0):
            raise ValueError('Invalid taught record: '+key)
    return data, dict(path=str(path.resolve()), sha256=sha256(raw).hexdigest())


def supply_slots(data):
    slots = {}
    for color, kind in GROUPS:
        anchors = {}
        for i in (1, 3, 6):
            row = data['records'][f'supply/{color}/{kind}/{i}']
            if (row['color'], row['brick_type'], row['slot_index']) != (color, kind, i):
                raise ValueError('Supply identity mismatch')
            anchors[i] = row['tcp_pose_mm_zyz_deg']
        for i in range(1, 7):
            direct = i in anchors
            if direct:
                point = anchors[i]
            else:
                left, right = (1, 3) if i < 3 else (3, 6)
                fraction = (i-left)/(right-left)
                a, b = anchors[left], anchors[right]
                xyz = np.array(a[:3])+fraction*(np.array(b[:3])-a[:3])
                rotation = Slerp([0, 1], Rotation.from_euler('ZYZ', [a[3:], b[3:]], degrees=True))([fraction])
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    point = xyz.tolist()+rotation.as_euler('ZYZ', degrees=True)[0].tolist()
            slots[f'{color}_{kind}_{i:02}'] = dict(slot_index=i, color=color, brick_type=kind,
                tcp_pose_mm_zyz_deg=list(point), pickup_tcp_pose=pose_mm_zyz(point),
                coordinate_basis='TAUGHT_ANCHOR' if direct else 'XYZ_LINEAR_ROTATION_SLERP')
    return slots


def board_reference(data, block):
    kind, angle = block['brick_type'], block['orientation_deg']
    if kind not in ('2x3x1', '1x2x1') or angle not in (0, 90) or block['layer'] != 1:
        raise ValueError('Four-corner source covers 2x3/1x2 layer 1 only; layer records required otherwise')
    w, h = map(int, kind.split('x')[:2])
    if angle == 90:
        w, h = h, w
    x, y = block['x'], block['y']
    if type(x) is not int or type(y) is not int or not (0 <= x <= 24-w and 0 <= y <= 24-h):
        raise ValueError('Board coordinate outside footprint range')
    rows = []
    for cx, cy in ((0, 0), (24-w, 0), (0, 24-h), (24-w, 24-h)):
        row = data['records'][f'assembly/geometry/{kind}/{angle}/1/xy{cx}_{cy}']
        if (row['brick_type'], row['orientation_deg'], row['layer'], row['planner_xy']) != (kind, angle, 1, [cx, cy]):
            raise ValueError('Board identity mismatch')
        rows.append(row)
    design = np.array([[1., *r['planner_xy']] for r in rows])
    positions = np.array([r['tcp_pose_mm_zyz_deg'][:3] for r in rows])
    coefficients, _, rank, _ = np.linalg.lstsq(design, positions, rcond=None)
    if rank != 3:
        raise ValueError('Degenerate board fit')
    mean = Rotation.from_euler('ZYZ', [r['tcp_pose_mm_zyz_deg'][3:] for r in rows], degrees=True).mean()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        abc = mean.as_euler('ZYZ', degrees=True).tolist()
    point = (np.array([1., x, y])@coefficients).tolist()+abc
    return point


def require_same_pose(actual, expected):
    a, b = pose_matrix(actual), pose_matrix(expected)
    if (not np.allclose(a[:3, 3], b[:3, 3], atol=1e-8, rtol=0) or
            not np.allclose(a[:3, :3], b[:3, :3], atol=1e-8, rtol=0)):
        raise ValueError('Taught source and A/D pose disagree')


def prepare_taught_moveit(out, record_path, supply_path, board_path):
    supply, supply_ref = read_teaching(supply_path)
    board, board_ref = read_teaching(board_path)
    raw = Path(record_path).read_bytes()
    packet = json.loads(raw)
    request, motion, step = packet['request'], packet['motion'], packet['step']
    if (motion['status'] != 'CANDIDATE' or motion['execution_allowed'] is not False or
            motion['schema_version'] != VERSION or
            request['schema_version'] != motion['schema_version'] or
            step['action']['mode'] != 'ROBOT_GRIP' or step['action']['assistance_kind'] != 'NONE'):
        raise ValueError('Current shared-A ROBOT_GRIP/NONE candidate required')
    context = request['context']
    if (motion['context'] != context or request['selected_step']['after'] != step['block'] or
            request['selected_step']['step_id'] != step['step_id'] or
            motion['reservation_binding'] != step['reservation'] or
            context['plan_id'] != step['plan_id'] or context['step_id'] != step['step_id'] or
            context['input_current_revision'] != request['latest_current']['current_revision']):
        raise ValueError('Recorded step/context/reservation mismatch')
    profile = packet['d_profile']
    if profile['supply_teaching_sha256'] != supply_ref['sha256'] or profile['assembly_teaching_sha256'] != board_ref['sha256']:
        raise ValueError('Teaching hash differs from recorded D profile')
    slots = supply_slots(supply)
    sid = step['step_id']
    selected = slots[step['reservation']['slot_id']]
    if any(selected[k] != step['block'][k] for k in ('color', 'brick_type')):
        raise ValueError('Selected slot does not match block')
    d_step = profile['steps'][packet['case_id']+'/'+sid]
    pickup = pose_mm_zyz(d_step['pickup_pose'])
    reference = pose_mm_zyz(d_step['reference_pose'])
    require_same_pose(pickup, selected['pickup_tcp_pose'])
    require_same_pose(reference, pose_mm_zyz(board_reference(board, step['block'])))
    offset = profile['approach_offset_mm']
    if type(offset) not in (int, float) or not np.isfinite(offset) or offset <= 0:
        raise ValueError('Positive finite recorded TCP approach offset required')
    precontact = deepcopy(reference)
    precontact['xyz_m'][2] += offset/1000
    proposal = motion['motion_proposal']
    require_same_pose(pickup, proposal['pickup_tcp_pose'])
    waypoints = [w for s in proposal['segments'] for w in s['waypoints']]
    require_same_pose(precontact, waypoints[-1]['tcp_pose'])
    if waypoints[-1]['label'] != 'PRE_CONTACT_HOLDING' or proposal['terminal_gripper_policy'] != 'HOLD_NO_AUTOMATIC_OPEN' or proposal['assembly_completed'] is not False:
        raise ValueError('Expected pre-contact holding boundary')
    recalculated = handle_step_motion(deepcopy(request))
    if recalculated['status'] != 'CANDIDATE' or recalculated['execution_allowed'] is not False:
        raise ValueError('Shared current A rejected recorded calculation input: '+str(recalculated['errors']))
    require_same_pose(pickup, recalculated['motion_proposal']['pickup_tcp_pose'])
    latest_points = [w for s in recalculated['motion_proposal']['segments'] for w in s['waypoints']]
    latest_goal = latest_points[-1]['tcp_pose']
    if not np.allclose(precontact['xyz_m'], latest_goal['xyz_m'], atol=1e-8, rtol=0):
        raise ValueError('Current A and taught target positions disagree')
    rotation_delta = float(np.rad2deg((Rotation.from_quat(precontact['quaternion_xyzw']).inv()*
        Rotation.from_quat(latest_goal['quaternion_xyzw'])).magnitude()))
    # Keep both results. A nominal orientation must not silently replace taught orientation.
    rotation_matches = rotation_delta < 1e-6
    current_references = []
    for block in request['latest_current']['blocks']:
        current_references.append(dict(block=deepcopy(block), reference_tcp_pose=pose_mm_zyz(board_reference(board, block)),
            coordinate_kind='SEATED_GRASP_TCP_NOT_BLOCK_CENTRE', collision_geometry_verified=False))
    # Existing C++ input names; gates intentionally reject an executable replay.
    common = dict(kind='POSE', execute=False, sim_execution_authorized=False,
        hardware_execution_allowed=False, a_execution_allowed=False,
        plan_id=step['plan_id'], step_id=sid, current_revision=context['input_current_revision'],
        world_revision=context['world_state_revision'], profile_version=context['frame_profile_version'],
        reservation_id=step['reservation']['reservation_id'], adapter_request_id='TAUGHT_REPLAY_'+sid,
        held=False, contact_phase=False, cartesian=False, coordinate_replay_only=True)
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use an empty run directory; existing runs are preserved')
    save(out/'taught_coordinates.json', dict(scope='TAUGHT_COORDINATE_REPLAY_NOT_EXECUTABLE',
        source_record=dict(path=str(Path(record_path).resolve()), sha256=sha256(raw).hexdigest()),
        source_teaching=dict(supply=supply_ref, assembly=board_ref), supply_slots=slots,
        selected_slot_id=step['reservation']['slot_id'], context=context,
        current=deepcopy(request['latest_current']), current_provenance=packet['state_basis'],
        current_tcp_references=current_references, a_contract_version=VERSION,
        pickup_tcp_pose=pickup, reference_tcp_pose=reference, pre_contact_tcp_pose=precontact,
        approach_tcp_offset_mm=offset, physical_bottom_clearance_verified=False,
        a_target_rotation_matches=rotation_matches, a_target_rotation_delta_deg=rotation_delta,
        a_recalculated_precontact_pose=latest_goal,
        collision_scene_ready=False, planning_allowed=False, execution_allowed=False,
        planning_blockers=([] if rotation_matches else ['CURRENT_A_TARGET_ROTATION_MISMATCH'])+
            ['COLLISION_SCENE_AND_GRASP_ALIGNMENT_NOT_VERIFIED'],
        required_before_planning=['Fresh stopped post-grasp joint/TCP snapshot', 'World/base alignment',
            'Calibrated TCP-to-held-block transform', 'Supply/board physical surfaces and Current collision objects'],
        legacy_nominal_scene_reused=False))
    save(out/sid/'motion.result.json', motion)
    save(out/sid/'motion.recalculated.json', recalculated)
    for phase, goal in [('PICKUP_DOWN', pickup), ('PRE_CONTACT_HOLDING', precontact)]:
        dest = out/sid/(phase+'.request.yaml')
        dest.write_text(yaml.safe_dump(dict(common, phase=phase, goal=goal,
            held=phase == 'PRE_CONTACT_HOLDING'), sort_keys=False))
    return dict(pickup=pickup, reference=reference, precontact=precontact, slots=slots)
