"""Step pickup/transport candidates; never issue motion, grip or Contact commands."""
from copy import deepcopy
import math
from uuid import uuid4

from planning_trial.assembly_optimizer import mode_options
from planning_trial.assembly_geometry import validate_context
from planning_trial.assembly_target import calculate_step_waypoints, validate_profile, trial_nominal_tcp
from planning_trial.assembly_wire import error, normalize_action, comparable_action, pose_mm_zyz
from planning_trial.planner import validate_current, validate_step, block_key
from planning_trial.supply_pick import calculate_supply_pick
from planning_trial.assembly_profiles import (IMPLEMENTED_MOTION_MODES,
                                             profile_content_digest, validate_supported_modes)


class MotionBlocked(ValueError):
    def __init__(self, code, reason, block=None):
        super().__init__(reason)
        self.code, self.block = code, block


def selected_step(plan, step_id, current):
    blocks, revision = validate_current(current)
    if (not isinstance(plan, dict) or set(plan) != {'plan_id', 'design_version', 'base_current_revision', 'steps'} or
            type(plan['base_current_revision']) is not int or plan['base_current_revision'] > revision):
        raise MotionBlocked('PLAN_NOT_VALID', 'Plan baseline must be non-future')
    seen = {}
    for i, item in enumerate(plan['steps']): seen[item['step_id']] = validate_step(item, i, seen)
    if step_id not in seen: raise MotionBlocked('PLAN_NOT_VALID', 'Unknown Step')
    step = next(s for s in plan['steps'] if s['step_id'] == step_id)
    present = {block_key(b) for b in blocks}
    if block_key(step['after']) in present:
        raise MotionBlocked('CURRENT_MISMATCH', 'Selected placement already confirmed', step['after'])
    if any(block_key(seen[p]) not in present for p in step['prerequisites']):
        raise MotionBlocked('CURRENT_MISMATCH', 'Prerequisite placements not confirmed', step['after'])
    return step, blocks, revision


def waypoint(label, pose):
    return {'label': label, 'motion_type': 'LINEAR', 'tcp_pose': pose_mm_zyz(pose)}


def plan_step_motion(*, plan, step_id, latest_current, action, supply_slot,
                     robot_state, frame_profile, assembly_context):
    """Local draft API. Registry freshness/physical feasibility remain D checks."""
    result = {'status': 'BLOCKED', 'execution_allowed': False, 'motion_proposal': None,
              'errors': [], 'coordinate_audit': None}
    try:
        step, blocks, revision = selected_step(plan, step_id, latest_current)
        target = step['after']
        validate_context(assembly_context)
        validate_supported_modes(assembly_context)
        if action['plan_id'] != plan['plan_id'] or action['step_id'] != step_id or action['block'] != target:
            raise MotionBlocked('REFERENCE_MISMATCH', 'Action does not match Plan Step', target)
        if action['mode'] not in IMPLEMENTED_MOTION_MODES:
            raise MotionBlocked('UNSUPPORTED_METHOD', 'Motion method not implemented; no automatic fallback', target)
        options, _ = mode_options(target, blocks, assembly_context)
        if not any(comparable_action(normalize_action(o, plan, step, assembly_context)) == comparable_action(action) for o in options):
            raise MotionBlocked('NO_FEASIBLE_METHOD', 'Action not feasible in latest Current/context', target)
        if supply_slot['brick_type'] != target['brick_type'] or supply_slot['color'] != target['color']:
            raise MotionBlocked('SLOT_NOT_READY', 'Reserved part differs from Step', target)
        if supply_slot['state'] != 'RESERVED' or supply_slot['part_confirmation'] != 'CONFIRMED':
            raise MotionBlocked('SLOT_NOT_READY', 'D-confirmed reserved part required', target)
        for key in ('profile_id', 'profile_version'):
            if not isinstance(frame_profile.get(key), str) or not frame_profile[key].strip():
                raise MotionBlocked('INVALID_INPUT', 'D profile ID and version required', target)
        profiles = frame_profile['calculation_profiles']
        p = profiles['assembly']
        validate_profile(p)
        if p['reference']['tcp_setting_name'] != frame_profile['tcp_setting_name']:
            raise MotionBlocked('REFERENCE_MISMATCH', 'Assembly TCP setting mismatch', target)
        if (robot_state['tcp_setting_name'] != frame_profile['tcp_setting_name'] or
                robot_state['tcp_frame_id'] != frame_profile['tcp_frame_id']):
            raise MotionBlocked('REFERENCE_MISMATCH', 'Robot and profile TCP differ', target)
        if robot_state['stopped_verified'] is not True:
            raise MotionBlocked('STOP_NOT_VERIFIED', 'Start-state stop not confirmed', target)
        if robot_state['holding_confirmed'] is not False:
            raise MotionBlocked('GRASP_NOT_VERIFIED', 'Already-held/unknown part needs D recovery or a separate request', target)
        if robot_state['active_command_count'] != 0 or robot_state['pending_command_count'] != 0:
            raise MotionBlocked('STOP_NOT_VERIFIED', 'Start command queues not empty', target)
        if robot_state['tcp_pose'] is None or robot_state['tcp_pose']['frame_id'] != 'base_link':
            raise MotionBlocked('INPUTS_REQUIRED', 'Explicit Base current TCP required', target)
        clearance = profiles['pickup_approach_clearance_mm']
        if type(clearance) not in (int, float) or not math.isfinite(clearance) or clearance <= 0:
            raise MotionBlocked('INVALID_INPUT', 'Explicit positive pickup approach clearance required', target)
        for name in ('body_height_mm', 'stud_height_mm'):
            if assembly_context['geometry'][name] != p['geometry'][name]:
                raise MotionBlocked('INVALID_CONTEXT', 'Target/context geometry mismatch: '+name, target)
        pick = calculate_supply_pick(target['brick_type'], target['color'], supply_slot['slot_index'], profile=profiles['supply'])
        if pick['grasp']['pad_bottom_above_block_bottom_mm'] != assembly_context['geometry']['grip_bottom_offset_mm']:
            raise MotionBlocked('INVALID_CONTEXT', 'Pickup and assessment grasp depth differ', target)
        pickup = pick['pickup_tcp_pose']['xyz_abc']
        manual = action['mode'] == 'HUMAN_ASSEMBLY'
        if manual:
            tray = profiles['tray']
            if tray is None:
                raise MotionBlocked('INPUTS_REQUIRED', 'Explicit D handover tray profile required', target)
            if not isinstance(tray.get('profile_id'), str) or not tray['profile_id']:
                raise MotionBlocked('INVALID_INPUT', 'Tray profile reference required', target)
            end = tray['tcp_pose_mm_zyz_deg']
            pose_mm_zyz(end)
            if (type(tray.get('travel_tcp_z_mm')) not in (int, float) or
                    not math.isfinite(tray['travel_tcp_z_mm'])):
                raise MotionBlocked('INVALID_INPUT', 'Finite explicit tray travel height required', target)
            nominal_top = max(trial_nominal_tcp(x, y, profile=p)[2] for x in (0, 22) for y in (0, 22))
            nominal_top += max([0]+[b['layer'] for b in blocks])*p['geometry']['body_height_mm']+p['geometry']['stud_height_mm']+20
            travel = max(nominal_top, tray['travel_tcp_z_mm'], pickup[2]+clearance, end[2]+clearance)
            transport = [waypoint('LIFT_HOLDING', pickup[:2]+[travel]+pickup[3:]),
                         waypoint('TRANSIT_ABOVE_TRAY', end[:2]+[travel]+end[3:]),
                         waypoint('HANDOVER_TRAY_HOLDING', end)]
            limits = ['D_TRAY_PROFILE_REQUIRED_AND_NOT_REVALIDATED_ON_DEVICE',
                      'OVERHEAD_WAYPOINTS_NOT_FULL_ROBOT_COLLISION_PROOF']
            audit = {'pickup': pick, 'tray': deepcopy(tray)}
        else:
            raw_route = calculate_step_waypoints(step, latest_current, pick, assembly_context,
                                                profile=p, grip_axis=action['grip_axis'], plan=plan)
            if raw_route['status'] != 'WAYPOINT_CANDIDATE':
                raise MotionBlocked('PATH_BLOCKED', str(raw_route.get('errors', raw_route['status'])), target)
            transport = [waypoint(w['label'], w['pose']['xyz_mm_zyz_deg']) for w in raw_route['waypoints']]
            limits, audit = raw_route['limits'], {'pickup': pick, 'transport': raw_route}
        approach = pickup[:]
        approach[2] += clearance
        # Pick approach uses the same overhead minimum as the loaded transport.
        overhead = approach[:]
        overhead[2] = max(transport[0]['tcp_pose']['xyz_m'][2]*1000, approach[2], robot_state['tcp_pose']['xyz_m'][2]*1000)
        current_high = deepcopy(robot_state['tcp_pose'])
        current_high['xyz_m'][2] = overhead[2]/1000
        result.update(status='CANDIDATE', motion_proposal={
            'motion_plan_id': 'motion-'+uuid4().hex,
            'motion_scope': 'PICK_TRANSPORT_TO_HANDOVER_TRAY' if manual else 'PICK_TRANSPORT_TO_PRE_CONTACT',
            'pickup_tcp_pose': pose_mm_zyz(pickup),
            'segments': [
                {'stage': 'APPROACH_PICK', 'waypoints': [
                    {'label': 'RISE_FROM_CURRENT', 'motion_type': 'LINEAR', 'tcp_pose': current_high},
                    waypoint('ABOVE_PICK', overhead), waypoint('PICK_APPROACH', approach), waypoint('PICK_TCP', pickup)],
                 'gripper_event': None},
                {'stage': 'D_PICK_AND_CONFIRM', 'waypoints': [], 'gripper_event': 'D_EXISTING_PICKUP_CLOSE_AND_CONFIRM'},
                {'stage': 'TRANSPORT_HOLDING', 'waypoints': transport, 'gripper_event': None}],
            'terminal_gripper_policy': 'HOLD_NO_AUTOMATIC_OPEN',
            'handoff_to': 'D_HANDOVER_RELEASE_AND_RETREAT' if manual else 'D_CONTACT',
            'assembly_completed': False,
            'validation': {k: False for k in ('ik_verified', 'full_path_collision_verified',
                                             'physical_grasp_verified', 'd_execution_approved')},
            'limits': list(limits)+['PICKUP_OPEN_CLOSE_AND_GRASP_CONFIRMATION_D_OWNED',
                                   'START_STATE_AND_RESERVATION_FRESHNESS_D_REGISTRY_REQUIRED',
                                   'UNLOADED_APPROACH_AND_ORIENTATION_CHANGE_NOT_COLLISION_VERIFIED'],
            'speed_profile_ref': deepcopy(frame_profile['speed_profile']),
            'profile_id': frame_profile['profile_id'], 'profile_version': frame_profile['profile_version'],
            'current_revision': revision}, coordinate_audit={**audit,
                'profile_content_digest': profile_content_digest(frame_profile)})
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        result['errors'] = [error(getattr(exc, 'code', 'INVALID_INPUT'), exc, getattr(exc, 'block', None))]
    return result
