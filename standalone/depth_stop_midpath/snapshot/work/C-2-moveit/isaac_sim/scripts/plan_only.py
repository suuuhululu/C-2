"""File-only post-grasp input and D receive-only draft; no ROS/driver imports.

Geometry is supplied explicitly. Taught TCP references are never treated as
block centres. A's shared calculation and B's Current ownership stay unchanged.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import yaml

from sim_utils import pose_matrix, rigid, save
from prepare_cpu_model import read_model_bundle
from prepare_sim_snapshot import SIM_KIND, validate_sim_snapshot
from planning_trial.planner import block_key, validate_current
from planning_trial.assembly_contract import validate_message

JOINTS = ['joint_'+str(i) for i in range(1, 7)]
GATES = ('execute', 'sim_execution_authorized', 'hardware_execution_allowed', 'a_execution_allowed')
TRANSPORT_BOUNDARY = 'POST_GRASP_TO_PRE_CONTACT_POSE'
BINDING = ('plan_id', 'step_id', 'job_id', 'request_id', 'workflow_generation', 'source_epoch',
           'design_version', 'current_revision', 'world_revision', 'profile_id', 'profile_version',
           'assessment_id', 'assessment_input_digest', 'scene_digest', 'reservation_id',
           'reservation_generation', 'motion_input_digest', 'motion_result_digest', 'model_digest',
           'planning_request_digest')


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def vector(value, count):
    if not isinstance(value, list) or len(value) != count or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('Expected finite vector of length '+str(count))
    return value


def checked_pose(value):
    if value['frame_id'] != 'base_link':
        raise ValueError('Explicit base_link pose required')
    vector(value['xyz_m'], 3)
    q = vector(value['quaternion_xyzw'], 4)
    if abs(sum(v*v for v in q)-1) > 1e-6:
        raise ValueError('Unit quaternion required')
    return pose_matrix(value)


def precontact_target(proposal):
    """Use shared A's terminal D pose, without adopting its legacy route points."""
    points = [w for s in proposal['segments'] for w in s['waypoints']]
    if (not points or points[-1]['label'] != 'PRE_CONTACT_HOLDING' or
            proposal['assembly_completed'] is not False or
            proposal['terminal_gripper_policy'] != 'HOLD_NO_AUTOMATIC_OPEN' or proposal['handoff_to'] != 'D_CONTACT'):
        raise ValueError('Shared-A pre-contact holding boundary required')
    final=deepcopy(points[-1]['tcp_pose']);checked_pose(final)
    return final


def prepare_request(motion_request, motion, snapshot, model_bundle):
    """Construct a draft only from explicit post-grasp state and collision geometry.

    snapshot.confirmation_kind describes Current evidence, not execution
    permission. Missing geometry and calibration produce errors, not defaults.
    """
    if any(snapshot.get(g, False) is not False for g in (*GATES, 'execution_allowed')):
        raise ValueError('Snapshot execution gates must remain false')
    validate_message(motion_request, 'StepMotionRequest')
    validate_message(motion, 'StepMotionResult')
    current = motion_request['latest_current']
    if motion['context'] != motion_request['context'] or motion['assessment_id'] != motion_request['assessment_id']:
        raise ValueError('Motion result does not match calculation input')
    action = motion_request['action_proposal']
    if action['mode'] != 'ROBOT_GRIP' or action['assistance_kind'] != 'NONE':
        raise ValueError('First transport draft requires ROBOT_GRIP/NONE')
    validate_current(current)
    if motion['status'] != 'CANDIDATE' or motion['execution_allowed'] is not False:
        raise ValueError('Shared-A non-executable motion candidate required')
    ctx = motion['context']
    if current['current_revision'] != ctx['input_current_revision'] or snapshot['current'] != current:
        raise ValueError('Current/revision mismatch')
    if snapshot['a_context'] != ctx or snapshot['reservation_binding'] != motion['reservation_binding']:
        raise ValueError('Stale request/profile/reservation/workflow')
    kind = snapshot['confirmation_kind']
    simulation = {}
    if kind != SIM_KIND and 'simulation_provenance' in snapshot:
        raise ValueError('SIM provenance cannot be relabelled as manual/B confirmation')
    if kind == 'B_CONFIRMED_CURRENT':
        if snapshot['confirmed_by'] != 'B' or snapshot['relayed_by'] != 'D':
            raise ValueError('B confirmation and D relay required')
    elif kind == 'MANUALLY_CONFIRMED_TEST_STATE':
        if not snapshot['confirmed_by'] or snapshot.get('production_B_confirmed') is not False:
            raise ValueError('Manual test evidence must remain separate from B production')
    elif kind == 'REAL_D_SYNTHETIC_B_OPERATOR_TRIAL_STATE':
        if (snapshot.get('state_source')!='LIVE_D_DEVICE_FEEDBACK' or
                snapshot.get('confirmed_by')!='D' or snapshot.get('relayed_by')!='D' or
                snapshot.get('production_B_confirmed') is not False or
                snapshot.get('b_observation_kind')!='SYNTHETIC' or not snapshot.get('operator_review_ref')):
            raise ValueError('Explicit REAL D feedback / synthetic B operator trial required')
    elif kind == SIM_KIND:
        simulation = validate_sim_snapshot(snapshot)
    else:
        raise ValueError('Unconfirmed/synthetic Current cannot prepare a taught planning scene')
    timestamp = datetime.fromisoformat(snapshot['confirmed_at'])
    if timestamp.tzinfo is None or not snapshot['evidence_ref']:
        raise ValueError('Timestamp with timezone and evidence reference required')
    if snapshot['holding_confirmed'] is not True or snapshot['stopped_verified'] is not True:
        raise ValueError('Explicit post-grasp stopped/holding state required')
    if snapshot['active_command_count'] != 0 or snapshot['pending_command_count'] != 0:
        raise ValueError('Post-grasp snapshot has pending motion')
    vector(snapshot['q_rad'], 6)
    vector([snapshot['grip_rad']], 1)
    checked_pose(snapshot['tcp_pose'])
    rigid(snapshot['attachment_tcp_to_block'])
    geometry_scopes = ('SIM_NOMINAL_GEOMETRY',) if kind == SIM_KIND else (
        'MANUALLY_MEASURED_TEST_GEOMETRY', 'CALIBRATED_GEOMETRY', 'USER_CONFIRMED_SHARED_GEOMETRY')
    if not snapshot['geometry_evidence_ref'] or snapshot['geometry_scope'] not in geometry_scopes:
        raise ValueError('Explicit geometry/attachment evidence required')
    final = precontact_target(motion['motion_proposal'])
    bundle = read_model_bundle(model_bundle)
    objects = snapshot['world_objects']
    ids = [o['id'] for o in objects]
    slot = motion['reservation_binding']['slot_id']
    if len(ids) != len(set(ids)) or slot not in ids or not all(isinstance(i, str) and i for i in ids):
        raise ValueError('Unique world IDs and held object required')
    current_objects = []
    for obj in objects:
        checked_pose(obj['pose'])
        centre_kind = 'SIM_BODY_CENTRE' if kind == SIM_KIND else 'PHYSICAL_BODY_CENTRE'
        if obj['coordinate_kind'] != centre_kind:
            raise ValueError('TCP reference is not collision geometry')
        if any(v <= 0 for v in vector(obj['size_m'], 3)):
            raise ValueError('Positive collision body size required')
        if type(obj['studs']) is not bool or not obj['geometry_evidence_ref']:
            raise ValueError('Explicit studs and geometry evidence required')
        # Box bodies plus stud envelopes are the current draft. Mesh inputs need
        # independent validation before being enabled through this boundary.
        if 'mesh_vertices_m' in obj or 'mesh_triangles' in obj:
            raise ValueError('Mesh collision inputs are not supported by this draft')
        if obj['role'] == 'CURRENT_BLOCK':
            current_objects.append(obj['block'])
        if obj['role'] in ('CURRENT_BLOCK', 'HELD_BLOCK', 'SUPPLY_BLOCK') and obj['studs'] is not True:
            raise ValueError('Block studs cannot be omitted')
        if obj['role'] in ('CURRENT_BLOCK', 'HELD_BLOCK', 'SUPPLY_BLOCK'):
            nx, ny, _ = map(int, obj['block']['brick_type'].split('x'))
            if not np.allclose(obj['size_m'], [nx*.016, ny*.016, .019], atol=1e-9, rtol=0):
                raise ValueError('Collision body must include the full block dimensions')
    if Counter(map(block_key, current_objects)) != Counter(map(block_key, current['blocks'])):
        raise ValueError('Collision scene must cover every Current block exactly once')
    if sum(o['role'] == 'HELD_BLOCK' for o in objects) != 1:
        raise ValueError('Exactly one held object required')
    held = next(o for o in objects if o['id'] == slot)
    if held['role'] != 'HELD_BLOCK' or held['block'] != motion_request['selected_step']['after']:
        raise ValueError('Held object differs from selected A block')
    held_world = checked_pose(held['pose'])
    from_grasp = checked_pose(snapshot['tcp_pose']) @ rigid(snapshot['attachment_tcp_to_block'])
    if not np.allclose(held_world, from_grasp, atol=1e-8, rtol=0):
        raise ValueError('Held body pose differs from the supplied TCP-to-block transform')
    if not {'ASSEMBLY_BOARD', 'SUPPLY_BOARD'} <= {o['role'] for o in objects}:
        raise ValueError('Both physical board bodies required')
    binding = dict(plan_id=ctx['plan_id'], step_id=ctx['step_id'], job_id=ctx['job_id'],
        request_id=ctx['request_id'], workflow_generation=ctx['workflow_generation'], source_epoch=ctx['source_epoch'],
        design_version=ctx['design_version'], current_revision=ctx['input_current_revision'],
        world_revision=ctx['world_state_revision'], profile_id=ctx['frame_profile_id'],
        profile_version=ctx['frame_profile_version'], assessment_id=motion['assessment_id'],
        assessment_input_digest=motion_request['assessment_input_digest'], scene_digest=digest(snapshot), motion_input_digest=digest(motion_request),
        motion_result_digest=digest(motion), model_digest=digest(bundle),
        reservation_id=motion['reservation_binding']['reservation_id'],
        reservation_generation=motion['reservation_binding']['reservation_generation'])
    state = {k: deepcopy(snapshot[k]) for k in ('q_rad', 'grip_rad', 'tcp_pose', 'world_objects')}
    state['selected_slot_id'] = slot
    request = dict(binding, **{g: False for g in GATES}, kind='POSE', phase='TRANSPORT',
        held=True, contact_phase=False, cartesian=False, planning_allowed=True,
        goal=final, expected_precontact=deepcopy(final), transport_boundary=TRANSPORT_BOUNDARY,
        mandatory_waypoint_count=0, trajectory_interpolation='QUINTIC', contact_approach_owner='D', model_bundle=bundle,
        # Hold the tool's tilt while allowing the taught target's assembly yaw.
        holding_orientation=deepcopy(snapshot['tcp_pose']), allow_yaw_reorientation=True,
        attachment=deepcopy(snapshot['attachment_tcp_to_block']), planning_snapshot=state,
        terminal_gripper_policy='HOLD_NO_AUTOMATIC_OPEN', handoff_to='D_CONTACT',
        confirmation_kind=kind, geometry_scope=snapshot['geometry_scope'], assembly_completed=False,
        a_context=deepcopy(ctx), reservation_binding=deepcopy(motion['reservation_binding']),
        source_snapshot=deepcopy(snapshot), **simulation)
    request['planning_request_digest'] = digest(request)
    return request


def validate_trajectory(value):
    """Preserve GPU's complete timed points in rad/seconds, with strict units."""
    if value['joint_names'] != JOINTS or len(value['points']) < 2:
        raise ValueError('M0609 ordered timed trajectory required')
    last = -1.
    for index, point in enumerate(value['points']):
        t = vector([point['time_from_start_s']], 1)[0]
        if t < 0 or t <= last or (index == 0 and t != 0):
            raise ValueError('Time must start at zero and strictly increase')
        for field in ('positions_rad', 'velocities_rad_s', 'accelerations_rad_s2'):
            vector(point[field], 6)
        if max(map(abs, point['velocities_rad_s'])) > .350001 or max(map(abs, point['accelerations_rad_s2'])) > .700001:
            raise ValueError('Timed trajectory exceeds current calculation limits')
        last = t
    return deepcopy(value)


def prepare_d_candidate(result, request, latest_binding):
    """Receive-only draft. Actual D execution/stop/Contact adapter is pending."""
    if not isinstance(result,dict) or result.get('plan_success') is not True:
        raise ValueError('Failed or incomplete plan cannot produce a D trajectory candidate')
    if set(result['binding']) != set(BINDING) or set(latest_binding) != set(BINDING):
        raise ValueError('Complete active trajectory binding required')
    if result['binding'] != latest_binding or any(request.get(k) != v for k, v in latest_binding.items()):
        raise ValueError('Late or foreign trajectory context')
    if (result['scope'] != 'FILE_ONLY_PLAN_CANDIDATE' or result['plan_success'] is not True or
            result['execution_allowed'] is not False or result['execution_issued'] is not False or
            result['hardware_execution_allowed'] is not False or result.get('error') or
            result['assembly_completed'] is not False or result['post_timing_collision_checks'] <= 0 or
            result['endpoint_validation_passed'] is not True or
            result['terminal_gripper_policy'] != 'HOLD_NO_AUTOMATIC_OPEN' or result['handoff_to'] != 'D_CONTACT'):
        raise ValueError('Complete non-executable validated candidate required')
    if (any(request[g] is not False for g in GATES) or request['phase'] != 'TRANSPORT' or
            request.get('transport_boundary')!=TRANSPORT_BOUNDARY or request['cartesian'] is not False or
            request.get('trajectory_interpolation')!='QUINTIC' or
            type(request.get('mandatory_waypoint_count')) is not int or request['mandatory_waypoint_count']!=0 or
            request.get('contact_approach_owner')!='D' or
            'final_goal' in request):
        raise ValueError('Plan-only request required')
    if digest({k: v for k, v in request.items() if k != 'planning_request_digest'}) != request['planning_request_digest']:
        raise ValueError('Goal or planning input changed after preparation')
    if result['actual_start'] != request['planning_snapshot'] or result['validated_target'] != request['goal'] or result['planned_attachment'] != request['attachment']:
        raise ValueError('Computed state/goal/attachment differs from bound request')
    if (request['goal'] != request['expected_precontact'] or
            result.get('transport_boundary')!=TRANSPORT_BOUNDARY or
            result.get('single_transport_trajectory') is not True or result.get('cartesian_tail_executed') is not False or
            result.get('trajectory_interpolation')!=request['trajectory_interpolation'] or
            type(result.get('mandatory_waypoint_count')) is not int or result['mandatory_waypoint_count']!=0 or
            'final_cartesian_fraction' in result):
        raise ValueError('Single endpoint-only trajectory ending at A pre-contact required')
    if result['model_digest'] != request['model_digest'] or digest(read_model_bundle(request['model_bundle']['bundle_path'])) != request['model_digest']:
        raise ValueError('Model bundle changed after calculation')
    if digest(request['source_snapshot']) != request['scene_digest']:
        raise ValueError('Planning scene changed after request preparation')
    original = request['source_snapshot']
    if any(request[k] != original[k] for k in ('confirmation_kind', 'geometry_scope')):
        raise ValueError('Planning provenance differs from bound snapshot')
    simulation = {}
    if original['confirmation_kind'] == SIM_KIND or 'simulation_provenance' in original:
        simulation = validate_sim_snapshot(original)
        if any(request.get(k) != v for k, v in simulation.items()):
            raise ValueError('SIM provenance differs from bound snapshot')
    if any(request['planning_snapshot'][k] != original[k] for k in ('q_rad', 'grip_rad', 'tcp_pose', 'world_objects')) or request['attachment'] != original['attachment_tcp_to_block']:
        raise ValueError('Planner input differs from bound snapshot')
    trajectory = validate_trajectory(result['planned_trajectory'])
    expected_start_q=request['planning_snapshot']['q_rad']
    if 'controller_command_start' in request:
        from command_start_plan import validate_controller_command_start
        command=validate_controller_command_start(request)
        if (result.get('controller_command_start')!=command or result.get('observed_start_separately_collision_checked') is not True or
                result.get('planning_start',{}).get('q_rad')!=command['command']['q_rad'] or
                result['planning_start'].get('grip_rad')!=request['planning_snapshot']['grip_rad'] or
                result['planning_start'].get('tcp_source_kind')!='MODEL_DERIVED_COMMAND_START_TCP'):
            raise ValueError('COMPUTED_COMMAND_PLANNING_START_MISMATCH')
        expected_start_q=command['command']['q_rad']
    elif 'controller_command_start' in result or 'planning_start' in result:
        raise ValueError('UNREQUESTED_COMMAND_PLANNING_START')
    if not np.allclose(trajectory['points'][0]['positions_rad'], expected_start_q, atol=1e-6, rtol=0):
        raise ValueError('Trajectory starts at a different snapshot')
    if any(abs(v) > 1e-6 for v in trajectory['points'][-1]['velocities_rad_s']):
        raise ValueError('Pre-contact terminal velocity must be zero')
    return dict(status='D_RECEIVE_ONLY_DRAFT_NOT_CONNECTED', binding=deepcopy(latest_binding),
        a_context=deepcopy(request['a_context']), reservation_binding=deepcopy(request['reservation_binding']),
        pre_contact_tcp_pose=deepcopy(request['goal']), start_tcp_pose=deepcopy(original['tcp_pose']),
        transport_boundary=TRANSPORT_BOUNDARY, mandatory_waypoint_count=0, contact_approach_owner='D',
        trajectory_interpolation=request['trajectory_interpolation'],
        model_digest=request['model_digest'], motion_result_digest=request['motion_result_digest'],
        model_scope=request['model_bundle']['scope'], geometry_scope=request['geometry_scope'],
        result_provenance=result['result_provenance'],
        trajectory=trajectory, trajectory_digest=digest(trajectory), units='rad, seconds', execution_allowed=False,
        hardware_execution_allowed=False, confirmation_kind=request['confirmation_kind'],
        terminal_gripper_policy='HOLD_NO_AUTOMATIC_OPEN', handoff_to='D_CONTACT', assembly_completed=False,
        checks_required_by_D=['latest Current/world/request/reservation', 'actual start drift',
                              'actual grasp retained', 'stop feedback', 'device/model alignment'], **simulation)


def prepare_files(folder, motion_request, snapshot, model_bundle, *, controller_start_source=None):
    """Write C++ inputs through the same shared A; never start the calculator."""
    from planning_trial.assembly_adapter import handle_step_motion
    folder = Path(folder)
    if folder.exists():
        raise ValueError('Run folder must be new; previous requests/results are preserved')
    result = handle_step_motion(deepcopy(motion_request))
    request = prepare_request(motion_request, result, snapshot, model_bundle)
    if controller_start_source is not None:
        from command_start_plan import attach_controller_command_start
        request=attach_controller_command_start(request,controller_start_source)
    binding = {k: request[k] for k in BINDING}
    folder.mkdir(parents=True)
    save(folder/'motion.request.json', motion_request)
    save(folder/'motion.result.json', result)
    save(folder/'planning_snapshot.json', snapshot)
    save(folder/'scene_context.json', binding)
    (folder/'TRANSPORT.request.yaml').write_text(yaml.safe_dump(request, sort_keys=False, allow_unicode=True))
    save(folder/'preparation_status.json', dict(status='INPUT_PREPARED_NO_MOVEIT_RUN',
        model_scope=request['model_bundle']['scope'], confirmation_kind=request['confirmation_kind'],
        geometry_scope=request['geometry_scope'],
        **({k: deepcopy(request[k]) for k in ('production_B_confirmed', 'simulation_provenance')}
           if request['confirmation_kind'] == SIM_KIND else {}),
        execution_allowed=False, MoveIt_planning_run=False, physical_assembly_verified=False))
    return request


def receive_files(folder, result_path, latest_binding, output_path):
    """File consumer rehearsal for D, not an installed D execution receiver."""
    output_path = Path(output_path)
    if output_path.exists():
        raise ValueError('D candidate output must be new')
    request = yaml.safe_load((Path(folder)/'TRANSPORT.request.yaml').read_text())
    result = yaml.safe_load(Path(result_path).read_text())
    packet = prepare_d_candidate(result, request, latest_binding)
    save(output_path, packet)
    return packet
