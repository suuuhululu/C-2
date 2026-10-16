"""Verify explicit saved GPU SIM inputs without starting Isaac, ROS or a solver."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

from plan_only import prepare_request, prepare_files, vector, checked_pose
from prepare_cpu_model import read_model_bundle
from prepare_sim_snapshot import prepare_sim_snapshot, validate_sim_snapshot
from sim_utils import pose_matrix, rigid, error, save
from taught_moveit import GROUPS
from planning_trial.assembly_adapter import handle_step_motion

# D full-real's 2026-10-13 policy excludes physical slot 6. The board layout,
# original teaching and the legacy coordinate calculator remain unchanged.
UNAVAILABLE_IDS = {f'{color}_{kind}_06' for color, kind in GROUPS}


def tcp_fk(bundle, q_rad, grip_rad):
    """URDF chain FK/bounds only; no IK, mesh collision or physical verification."""
    robot = ET.fromstring(bundle['robot_description'])
    values = dict(zip(['joint_'+str(i) for i in range(1, 7)], vector(q_rad, 6)))
    values['rg2_finger_joint'] = vector([grip_rad], 1)[0]
    for name, value in values.items():
        joint = robot.find(f"joint[@name='{name}']")
        if joint is None or joint.find('limit') is None:
            raise ValueError('Model joint/position bounds missing: '+name)
        limit = joint.find('limit')
        if not float(limit.get('lower')) <= value <= float(limit.get('upper')):
            raise ValueError('Snapshot joint bounds violation: '+name)
    by_child = {j.find('child').get('link'): j for j in robot.findall('joint')}
    chain, child = [], 'GripperDA_v4_tcp'
    while child != 'base_link':
        if child not in by_child or child in [j.find('child').get('link') for j in chain]:
            raise ValueError('Model TCP chain does not reach base_link')
        joint = by_child[child]
        chain.append(joint)
        child = joint.find('parent').get('link')
    transform = np.eye(4)
    for joint in reversed(chain):
        origin, motion = np.eye(4), np.eye(4)
        item = joint.find('origin')
        if item is not None:
            origin[:3, 3] = np.array(item.get('xyz', '0 0 0').split(), float)
            origin[:3, :3] = Rotation.from_euler('xyz', np.array(item.get('rpy', '0 0 0').split(), float)).as_matrix()
        if joint.get('type') == 'revolute':
            axis = np.array(joint.find('axis').get('xyz').split(), float)
            motion[:3, :3] = Rotation.from_rotvec(axis*values[joint.get('name')]).as_matrix()
        elif joint.get('type') != 'fixed':
            raise ValueError('Unsupported joint in TCP chain')
        transform = transform @ origin @ motion
    return rigid(transform)


def inspect_gpu_inputs(motion_request, scene_path, state_path, model_bundle):
    """Check actual supplied poses, never infer body centres from taught TCPs."""
    slot = motion_request['reserved_supply_slot']
    if type(slot['slot_index']) is not int or not 1 <= slot['slot_index'] <= 5:
        raise ValueError('SUPPLY_SLOT_UNAVAILABLE: GPU full-real draft requires slots 1..5')
    snapshot = prepare_sim_snapshot(scene_path, state_path)
    motion = handle_step_motion(deepcopy(motion_request))
    request = prepare_request(motion_request, motion, snapshot, model_bundle)
    scene = json.loads(Path(scene_path).read_text())
    alignment = scene.get('frame_alignment')
    if (not isinstance(alignment, dict) or alignment.get('base_frame_id') != 'base_link' or
            not isinstance(alignment.get('world_frame_id'), str) or not alignment['world_frame_id'] or
            not alignment.get('evidence_ref') or 'T_world_base' not in alignment):
        raise ValueError('Explicit World/Base transform and evidence required')
    world_base = rigid(alignment['T_world_base'])
    fk = tcp_fk(read_model_bundle(model_bundle), snapshot['q_rad'], snapshot['grip_rad'])
    drift = error(fk, checked_pose(snapshot['tcp_pose']))
    # Same FK tolerances as the existing C++ start-state check; not enlarged.
    if drift[0] > .0008 or drift[1] > .005:
        raise ValueError('Snapshot FK/TCP mismatch')
    for obj in snapshot['world_objects']:
        if obj['id'] in UNAVAILABLE_IDS:
            raise ValueError('Empty supply slot 6 cannot be a collision block')
        if obj['role'] == 'SUPPLY_BLOCK':
            index = obj.get('slot_index')
            if type(index) is not int or not 1 <= index <= 5:
                raise ValueError('Supply collision block needs explicit available slot_index')
            block = obj['block']
            if obj['id'] != f"{block['color']}_{block['brick_type']}_{index:02d}":
                raise ValueError('Supply collision identity differs from slot')
            nx, ny, _ = map(int, block['brick_type'].split('x'))
            if obj['studs'] is not True or not np.allclose(obj['size_m'], [nx*.016, ny*.016, .019], atol=1e-9, rtol=0):
                raise ValueError('Supply collision body/studs must retain full dimensions')
        pose = obj.get('world_pose')
        if not isinstance(pose, dict) or pose.get('frame_id') != alignment['world_frame_id']:
            raise ValueError('Every collision object needs its saved World pose')
        vector(pose['xyz_m'], 3)
        q = vector(pose['quaternion_xyzw'], 4)
        if abs(sum(v*v for v in q)-1) > 1e-6:
            raise ValueError('Unit World quaternion required')
        mapped = np.linalg.inv(world_base) @ pose_matrix(pose)
        if not np.allclose(mapped, checked_pose(obj['pose']), atol=1e-8, rtol=0):
            raise ValueError('World/Base collision pose mismatch')
    validate_sim_snapshot(snapshot)
    checks = dict(status='GPU_INPUT_GEOMETRY_CHECKED_NO_SOLVER_RUN', fk_tcp_error_m_rad=drift,
        frame_alignment=deepcopy(alignment), supply_slot_count=5, supply_unavailable_slots=[6],
        source_kind=snapshot['simulation_provenance']['source_kind'],
        solver_input_ready=snapshot['simulation_provenance']['source_kind'] == 'ISAAC_SIM_SAVED_STATE',
        model_scope=request['model_bundle']['scope'], execution_allowed=False,
        MoveIt_planning_run=False, collision_feasibility_verified=False)
    return request, checks


def prepare_gpu_files(folder, motion_request, scene_path, state_path, model_bundle, *, controller_start_source=None):
    folder = Path(folder)
    if folder.exists():
        raise ValueError('GPU run folder must be new')
    inspected, checks = inspect_gpu_inputs(motion_request, scene_path, state_path, model_bundle)
    if not checks['solver_input_ready']:
        raise ValueError('Saved Isaac capture required; contract fixtures are not solver inputs')
    request = prepare_files(folder, motion_request, inspected['source_snapshot'], model_bundle, controller_start_source=controller_start_source)
    save(folder/'gpu_input_checks.json', checks)
    return request


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('motion-request', 'scene', 'state', 'model-bundle', 'run-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    prepare_gpu_files(args.run_dir, json.loads(args.motion_request.read_text()), args.scene, args.state, args.model_bundle)
    print('GPU_INPUT_FILES_PREPARED_NO_SOLVER_RUN:', args.run_dir)
