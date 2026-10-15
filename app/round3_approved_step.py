"""Bind an approved A step to its native teaching and supply profile; no device APIs."""
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import time

from planning_trial.assembly_adapter import receive_result_for_review
from planning_trial.assembly_profiles import assessment_input_digest
from planning_trial.assembly_wire import pose_mm_zyz
from planning_trial.planning_bundle import validate_planning_bundle


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def file_digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def same_blocks(left, right):
    return Counter(digest(b) for b in left) == Counter(digest(b) for b in right)


def load_initial_capture(directory):
    """Read B's native archive (PR55 three-View INITIAL), preserving its source identity."""
    directory = Path(directory).resolve()
    read = lambda name: json.loads((directory / name).read_text())
    context = read('context.json')
    manifest = context['manifest']
    observed = read('observed.json')
    if (manifest['mode'] != 'REAL' or manifest['check_kind'] != 'INITIAL'
            or manifest['view_order'] != ['V0', 'D1', 'D3']
            or (manifest['check_id'], manifest['observation_seq']) !=
               (observed['check_id'], observed['observation_seq'])):
        raise ValueError('APPROVED_STEP_THREE_VIEW_REAL_INITIAL_REQUIRED')
    paths = [directory / name for name in ('context.json', 'observed.json')]
    captures, scenes = [], set()
    for view in manifest['view_order']:
        path = directory / view / 'metadata.json'
        metadata = json.loads(path.read_text())
        if (metadata['mode'] != 'REAL' or metadata['view_id'] != view
                or metadata['check_id'] != manifest['check_id']
                or metadata['observation_seq'] != manifest['observation_seq']
                or metadata['calibration_id'] != context['calibration']['calibration_id']):
            raise ValueError('APPROVED_STEP_INITIAL_CAPTURE_ID_MISMATCH')
        scenes.add(metadata['scene_id'])
        stamp = datetime.fromisoformat(metadata['captured_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('APPROVED_STEP_INITIAL_UTC_TIMESTAMP_REQUIRED')
        captures.append(stamp.timestamp())
        paths.append(path)
    if len(scenes) != 1:
        raise ValueError('APPROVED_STEP_INITIAL_SCENE_CHANGED')
    packet = dict(source_directory=str(directory), check_id=manifest['check_id'],
        observation_seq=manifest['observation_seq'], captured_unix_s=min(captures),
        geometry_reference=context['calibration']['calibration_id'],
        source_sha256={str(path):file_digest(path) for path in paths})
    return observed, packet


def validate_binding(document, config, scenario, execution_profile):
    """Recheck the saved approval/A/config binding before the native writer opens."""
    if (document['schema_version'] != 'round3-approved-step/1'
            or not time.time() < document['expires_unix_s'] <= time.time() + 600
            or not document['operator_review_ref']):
        raise ValueError('APPROVED_STEP_ACTIVE_REVIEW_REQUIRED')
    plan = validate_planning_bundle(document['planning_bundle'])
    prepared = document['prepared']
    request = prepared['request']
    case = config['trial_step']
    baseline = [row['block'] for row in scenario['preplaced']]
    targets = [row['target'] for row in scenario['steps']]
    if (document['approved'] != plan['design'] or prepared['current'] != plan['plan_base_current']
            or not same_blocks(prepared['current']['blocks'], baseline)
            or not same_blocks(document['approved']['blocks'], baseline + targets)
            or not same_blocks([s['after'] for s in plan['plan']['steps']], targets)
            or prepared['step'] != plan['plan']['steps'][0]
            or request['plan'] != plan['plan'] or request['selected_step'] != prepared['step']
            or request['latest_current'] != prepared['current']
            or prepared['step']['operation'] != 'PLACE' or prepared['step']['before'] is not None
            or case not in scenario['steps'] or prepared['step']['after'] != case['target']):
        raise ValueError('APPROVED_STEP_SCENARIO_MISMATCH')
    for result, source in ((prepared['assessment'], prepared['assessment_request']),
                           (prepared['motion'], request)):
        if (result['status'] != 'CANDIDATE'
                or receive_result_for_review(result, source)['decision'] != 'STORE_FOR_REVIEW'):
            raise ValueError('APPROVED_STEP_A_RESULT_BINDING_REQUIRED')
    action = prepared['assessment']['action_proposal']
    slot = prepared['slot']
    if (action != request['assessed_action'] or action != request['action_proposal']
            or action['block'] != case['target'] or action['plan_id'] != plan['plan']['plan_id']
            or action['step_id'] != prepared['step']['step_id']
            or (action['mode'], action['assistance_kind'], action['grip_axis']) != ('ROBOT_GRIP', 'NONE', 'x')
            or request['reserved_supply_slot'] != slot
            or slot['slot_id'] != f"{case['target']['color']}_{case['target']['brick_type']}_{case['supply_slot']:02d}"
            or slot['slot_index'] != case['supply_slot'] or slot['state'] != 'RESERVED'
            or slot['bound_workflow_generation'] != prepared['generation']
            or request['context']['workflow_generation'] != prepared['generation']):
        raise ValueError('APPROVED_STEP_ACTION_OR_SLOT_MISMATCH')
    assessment = prepared['assessment']
    if (request['assessment_context'] != assessment['context']
            or request['assessment_id'] != assessment['assessment_id']
            or request['assessment_current_revision'] != prepared['current']['current_revision']
            or request['assessment_input_digest'] != assessment['assessment_input_digest']
            or request['assessment_input_digest'] != assessment_input_digest(
                request['frame_profile'], request['assembly_context'])):
        raise ValueError('APPROVED_STEP_REASSESSMENT_CHANGED')
    settings = next(iter(prepared['d_profile']['steps'].values()))
    if (settings['pickup_pose'] != config['blocks'][0]['pickup_pose']
            or settings['reference_pose'] != config['alignment_target']['placement_tcp_reference']
            or config['educational_supply_binding']['execution_mode'] not in ('RGBD_XY', 'TEACHING_ONLY')
            or config['assembly_xy_correction_enabled'] is not False
            or document['native_config_sha256'] != digest(config)
            or document['scenario_sha256'] != digest(scenario)
            or document['execution_profile_sha256'] != file_digest(execution_profile)):
        raise ValueError('APPROVED_STEP_TEACHING_OR_PROFILE_CHANGED')
    if prepared['motion']['motion_proposal']['pickup_tcp_pose'] != pose_mm_zyz(settings['pickup_pose']):
        raise ValueError('APPROVED_STEP_A_PICKUP_POSE_MISMATCH')
    return dict(execution_id=document['execution_id'], plan_id=action['plan_id'],
                step_id=action['step_id'], current_revision=prepared['current']['current_revision'],
                design_version=document['approved']['design_version'], native_step_id=case['step_id'],
                slot_id=slot['slot_id'], binding_sha256=digest(document))
