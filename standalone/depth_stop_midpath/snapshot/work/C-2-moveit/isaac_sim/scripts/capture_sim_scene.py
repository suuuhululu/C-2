"""Read an already paused SIM scene/articulation into paired post-grasp files.

The caller supplies current control/holding evidence. This module does not start
Isaac, pause playback, move joints, close the gripper or attach a block.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import uuid

import numpy as np

from plan_only import digest, JOINTS, vector
from prepare_gpu_scene import inspect_gpu_inputs, tcp_fk
from prepare_cpu_model import read_model_bundle
from prepare_sim_scene import SEED_SCHEMA
from prepare_sim_snapshot import SIM_SCHEMA
from sim_utils import matrix_pose, rigid, save
from planning_trial.assembly_adapter import handle_step_motion


def prepare_capture_setup(seed, motion_request, model_bundle, archive_step):
    """Use matching historical postures only as new SIM setup references."""
    import json
    from hashlib import sha256
    folder = Path(archive_step)
    paths = {name: folder/name for name in ('model.json', 'PICKUP_DOWN.actual.json', 'LIFT.actual.json')}
    values = {name: json.loads(path.read_text()) for name, path in paths.items()}
    motion = handle_step_motion(deepcopy(motion_request))
    if (seed['schema_version'] != SEED_SCHEMA or seed['execution_allowed'] is not False or
            seed['production_B_confirmed'] is not False or motion['status'] != 'CANDIDATE' or
            seed['a_context'] != motion['context'] or seed['reservation_binding'] != motion['reservation_binding'] or
            seed['current'] != motion_request['latest_current']):
        raise ValueError('Stale or incompatible capture seed/A/Current/reservation')
    slot = seed['reservation_binding']['slot_id']
    current = next(o for o in seed['world_objects'] if o['id'] == slot)
    old = next(o for o in values['model.json']['supply']['slots'] if o['selected'])
    if (seed['motion_input_digest'] != digest(motion_request) or current['slot_index'] not in range(1,6) or
            old['slot_id'] != slot or old['size_m'] != current['size_m'] or
            not np.allclose(old['centre_m'], current['pose']['xyz_m'], atol=1e-9, rtol=0)):
        raise ValueError('Archived setup differs from current nominal reserved supply body')
    from scipy.spatial.transform import Rotation
    from sim_utils import pose_matrix, error
    if not np.allclose(Rotation.from_euler('z', old['yaw_rad']).as_matrix(),
                       pose_matrix(current['pose'])[:3,:3], atol=1e-9, rtol=0):
        raise ValueError('Archived setup supply orientation differs')
    bundle = read_model_bundle(model_bundle)
    poses, joints = [], []
    for name in ('PICKUP_DOWN.actual.json', 'LIFT.actual.json'):
        value = values[name]
        if value['selected_slot_id'] != slot or value['control_backend'] != 'isaacsim.ros2.control':
            raise ValueError('Matching native SIM posture reference required')
        fk = tcp_fk(bundle, value['q_rad'], value['grip_rad'])
        drift = error(fk, pose_matrix(value['tcp_pose']))
        if drift[0] > .0008 or drift[1] > .005:
            raise ValueError('Archived setup reference does not match current model FK')
        poses.append(fk); joints.append(value['q_rad'])
    delta = poses[1][:3,3]-poses[0][:3,3]
    if not .02 <= delta[2] <= .04 or np.linalg.norm(delta[:2]) > .002:
        raise ValueError('Setup lift must be a short vertical supply lift')
    return dict(scope='POSTURE_REFERENCES_FOR_NEW_SIM_SETUP_NOT_OLD_PLAN_EXECUTION',
        initial_q_rad=joints[0], lift_q_rad=joints[1], source_slot_id=slot,
        source_files={name: dict(path=str(path.resolve()), sha256=sha256(path.read_bytes()).hexdigest())
                      for name, path in paths.items()}, seed_digest=digest(seed), motion_input_digest=digest(motion_request),
        old_observation_reused_as_current=False, old_trajectory_executed=False, measured_lift_reference_m=delta.tolist())


def command_counts(statuses):
    """Read both action servers; unknown/missing status cannot mean empty."""
    if set(statuses) != {'arm_controller', 'gripper_controller'} or any(v is None for v in statuses.values()):
        raise ValueError('Both native action status observations required')
    states = [state for values in statuses.values() for state in values]
    if any(type(v) is not int or v not in range(1,7) for v in states):
        raise ValueError('Unknown native action state')
    return dict(active_command_count=sum(v in (2,3) for v in states), pending_command_count=states.count(1))


def contact_state(report):
    """PhysX candidates can be separated with zero impulse; not actual touch."""
    if report['contact_count'] == 0:
        return False, False
    separation, impulse = vector([report['minimum_separation_m'], report['maximum_impulse_ns']], 2)
    if impulse < 0:
        raise ValueError('Contact impulse magnitude cannot be negative')
    near = separation <= .0005  # Existing SIM runtime guard clearance, unchanged.
    return near, near and impulse > 0


def verified_stop(samples, current_positions=None):
    """Same position-history stop basis as sim_host; preserve raw SDK velocity."""
    if not samples or samples[-1]['time_s']-samples[0]['time_s'] < .5:
        raise ValueError('At least half a second of post-lift observations required')
    times = np.array([vector([s['time_s']],1)[0] for s in samples])
    positions = np.array([vector(s['q_rad'],6)+vector([s['grip_rad']],1) for s in samples])
    if np.any(np.diff(times)<=0):
        raise ValueError('SIM position observations must be chronological')
    speeds = np.abs(np.diff(positions,axis=0)/np.diff(times)[:,None])
    if np.max(np.ptp(positions,axis=0)) >= .002 or np.max(speeds) >= .02:
        raise ValueError('Position-derived joints/gripper are not stopped')
    if current_positions is not None and not np.allclose(positions[-1],current_positions,atol=1e-8,rtol=0):
        raise ValueError('Position observation is stale relative to paused articulation')
    return dict(basis='SIM_POSITION_HISTORY',peak_derived_velocity_rad_s=speeds.max(0).tolist(),
                joint_position_range_rad=np.ptp(positions,axis=0).tolist())


def verified_hold(samples, initial_body_z, cfg):
    """Lift, two force-bearing finger contacts, retention and observed stop."""
    from sim_utils import error
    verified_stop(samples)
    for row in samples:
        if (row['body_z_m']-initial_body_z < .02 or
                row['contact_fingers'] != ['rg2_left_inner_finger', 'rg2_right_inner_finger']):
            raise ValueError('Stopped, raised two-finger contact grasp not observed')
        drift = error(np.array(samples[0]['attachment']), np.array(row['attachment']))
        if drift[0] > cfg['position_drift_tolerance_m'] or drift[1] > cfg['orientation_drift_tolerance_rad']:
            raise ValueError('Observed held block slipped')
    return True


def read_scene_geometry(stage, seed, additional_objects=None):
    from pxr import Usd, UsdGeom, UsdPhysics
    if UsdGeom.GetStageMetersPerUnit(stage) != 1 or UsdGeom.GetStageUpAxis(stage) != 'Z':
        raise ValueError('SIM scene must use metres and Z up')
    if stage.GetRootLayer().customLayerData.get('seed_digest') != digest(seed):
        raise ValueError('Loaded scene belongs to another seed')

    def matrix(path):
        prim = stage.GetPrimAtPath(path)
        if not prim:
            raise ValueError('Missing observed prim: '+path)
        return np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T

    base = rigid(matrix(seed['robot_base_prim']))
    objects = []
    environment = stage.GetPrimAtPath('/World/Environment')
    if not environment or {str(p.GetPath()) for p in environment.GetChildren()} != {o['prim_path'] for o in seed['world_objects']}:
        raise ValueError('Observed environment differs from declared collision inventory')
    extra=additional_objects or []
    if (len({o['id'] for o in seed['world_objects']+extra})!=len(seed['world_objects'])+len(extra) or
            any(not o['prim_path'].startswith('/World/Committed/') for o in extra)):
        raise ValueError('Additional Current inventory must be unique committed prims')
    for obj in seed['world_objects']+extra:
        row = deepcopy(obj)
        world = rigid(matrix(row['prim_path']))
        parts = [('Body', [0,0,0], row['size_m'])]
        if row['studs']:
            nx, ny, _ = map(int, row['block']['brick_type'].split('x'))
            parts += [(f'Stud_{i}_{j}', [(i-(nx-1)/2)*.016, (j-(ny-1)/2)*.016, .01175], [.01,.01,.0045])
                      for i in range(nx) for j in range(ny)]
        prim = stage.GetPrimAtPath(row['prim_path'])
        if {p.GetName() for p in prim.GetChildren()} != {part[0] for part in parts}:
            raise ValueError('Observed body/stud inventory changed: '+row['id'])
        for name, centre, size in parts:
            path = row['prim_path']+'/'+name
            cube = UsdGeom.Cube(stage.GetPrimAtPath(path))
            expected = np.eye(4); expected[:3,:3] = np.diag(size); expected[:3,3] = centre
            if (not cube or cube.GetSizeAttr().Get() != 1 or
                    not cube.GetPrim().HasAPI(UsdPhysics.CollisionAPI) or
                    not np.allclose(np.linalg.inv(world) @ matrix(path), expected, atol=1e-8, rtol=0)):
                raise ValueError('Observed collision geometry changed: '+path)
        row['world_pose'] = dict(matrix_pose(world), frame_id='world')
        row['pose'] = matrix_pose(np.linalg.inv(base) @ world)
        row['geometry_evidence_ref'] = 'READ_ONLY_USD_PRIM:'+row['prim_path']
        objects.append(row)
    alignment = dict(world_frame_id='world', base_frame_id='base_link', T_world_base=base.tolist(),
                     evidence_ref='READ_ONLY_USD_BASE:'+seed['robot_base_prim'])
    tcp = rigid(np.linalg.inv(base) @ matrix(seed['robot_tcp_prim']))
    return objects, alignment, tcp


def capture_post_grasp(stage, robot, seed, motion_request, model_bundle, controls, output):
    """Call in one paused runtime callback with an initialized articulation."""
    output = Path(output)
    if output.exists():
        raise ValueError('Capture output must be new')
    if seed['schema_version'] != SEED_SCHEMA or seed['execution_allowed'] is not False:
        raise ValueError('Non-executable nominal scene seed required')
    motion = handle_step_motion(deepcopy(motion_request))
    if (motion['status'] != 'CANDIDATE' or seed['motion_input_digest'] != digest(motion_request) or
            seed['current'] != motion_request['latest_current'] or
            controls['a_context'] != motion['context'] or
            controls['reservation_binding'] != motion['reservation_binding'] or
            controls['current_revision'] != seed['current']['current_revision']):
        raise ValueError('Stale SIM/A/Current/reservation observation')
    kind = controls.get('source_kind')
    if kind not in ('ISAAC_SIM_SAVED_STATE', 'SIM_CONTRACT_FIXTURE') or not controls.get('evidence_ref'):
        raise ValueError('Explicit SIM control evidence and source kind required')
    if (controls.get('timeline_paused') is not True or controls.get('holding_confirmed') is not True or
            controls.get('stopped_verified') is not True or controls.get('virtual_attachment_used') is not False or
            controls.get('grasp_kind') != 'DYNAMIC_CONTACT_GRASP'):
        raise ValueError('Paused, stopped dynamic-contact grasp evidence required')
    if any(type(controls.get(k)) is not int or controls[k] != 0 for k in ('active_command_count', 'pending_command_count')):
        raise ValueError('SIM commands must be explicitly observed empty')
    duration = vector([controls['stop_observation_duration_s']], 1)[0]
    if duration < .5:
        raise ValueError('Stopped observation interval is too short')
    names = robot.dof_names
    positions, velocities = robot.get_joint_positions().tolist(), robot.get_joint_velocities().tolist()
    vector(positions, len(names)); vector(velocities, len(names))
    indices = [names.index(name) for name in [*JOINTS, 'rg2_finger_joint']]
    if kind == 'ISAAC_SIM_SAVED_STATE':
        verified_stop(controls['position_observations'],[positions[i] for i in indices])
    elif max(abs(velocities[i]) for i in indices) >= .02:
        raise ValueError('Observed joints/gripper are moving')
    objects, alignment, tcp = read_scene_geometry(stage, seed)
    pickup_error = None
    if controls.get('capture_boundary') == 'TAUGHT_PICKUP_AFTER_GRASP_PROOF':
        from prepare_taught_sim import verify_taught_capture_pose
        pickup_error = verify_taught_capture_pose(tcp, motion)
    from pxr import UsdPhysics
    slot = seed['reservation_binding']['slot_id']
    held = next(o for o in objects if o['id'] == slot)
    body = stage.GetPrimAtPath(held['prim_path'])
    if not body.HasAPI(UsdPhysics.RigidBodyAPI) or UsdPhysics.RigidBodyAPI(body).GetKinematicEnabledAttr().Get() is True:
        raise ValueError('Held block must remain a dynamic contact body')
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Joint):
            joint = UsdPhysics.Joint(prim)
            targets = [*joint.GetBody0Rel().GetTargets(), *joint.GetBody1Rel().GetTargets()]
            if any(str(p) == held['prim_path'] or str(p).startswith(held['prim_path']+'/') for p in targets):
                raise ValueError('Constraint attachment cannot confirm contact grasp')
    held['role'] = 'HELD_BLOCK'
    from sim_utils import pose_matrix
    attachment = np.linalg.inv(tcp) @ pose_matrix(held['pose'])
    common = dict(schema_version=SIM_SCHEMA, source_kind=kind, capture_id=str(uuid.uuid4()),
        captured_at=datetime.now(timezone.utc).isoformat(), execution_allowed=False, production_B_confirmed=False)
    scene = dict(common, current=deepcopy(seed['current']), world_objects=objects, frame_alignment=alignment,
        final_approach_policy=deepcopy(seed['final_approach_policy']), geometry_scope='SIM_NOMINAL_GEOMETRY',
        model_scope='SIM_NOMINAL_MODEL', seed_digest=digest(seed),
        **{k:deepcopy(seed[k]) for k in ('coordinate_provenance','d_gripper_reference','nominal_geometry_evidence') if k in seed})
    state = dict(common, a_context=deepcopy(motion['context']), reservation_binding=deepcopy(motion['reservation_binding']),
        q_rad=[positions[i] for i in indices[:6]], grip_rad=positions[indices[6]], tcp_pose=matrix_pose(tcp),
        attachment_tcp_to_block=attachment.tolist(), attachment_scope='SIM_NOMINAL_ATTACHMENT',
        holding_confirmed=True, stopped_verified=True, active_command_count=0, pending_command_count=0,
        raw_joint_velocity_rad_s=[velocities[i] for i in indices], observation_evidence=deepcopy(controls))
    # Publish the pair only after the existing producer/consumer/FK checks pass.
    with tempfile.TemporaryDirectory() as check_dir:
        scene_path, state_path = Path(check_dir)/'scene.json', Path(check_dir)/'post_grasp_state.json'
        save(scene_path, scene); save(state_path, state)
        _, checks = inspect_gpu_inputs(motion_request, scene_path, state_path, model_bundle)
    if pickup_error is not None:
        checks['captured_pickup_error_m_rad'] = pickup_error
    output.mkdir(parents=True)
    save(output/'scene.json', scene); save(output/'post_grasp_state.json', state)
    save(output/'capture_checks.json', dict(checks, capture_status='POST_GRASP_FILES_SAVED',
        simulator_started_by_exporter=False, joint_or_gripper_commands_issued=0, files_validated_before_save=True))
    return checks
