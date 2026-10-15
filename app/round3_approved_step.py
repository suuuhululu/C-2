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


def restore_initial_inspection(connection, directory, expected_current):
    """Before Plan load, restore B's coverage restrictions as well as its Current."""
    observed, packet = load_initial_capture(directory)
    if (observed['status'] != 'OK'
            or packet['geometry_reference'] != connection.geometry_reference
            or not 0 <= time.time() - packet['captured_unix_s'] <= 300):
        raise ValueError('FRESH_REAL_INITIAL_REQUIRED_FOR_B_RESTORE')
    request = dict(check_id=observed['check_id'],check_kind='INITIAL',plan_id=None,step_id=None)
    # The connection's worker is idle here. Use B's public transaction methods;
    # a Current-only constructor cannot reconstruct unverified board columns.
    connection.inspection.start_check(request,geometry_reference=connection.geometry_reference)
    result = connection.inspection.finish_check(request,observed,
        geometry_reference=connection.geometry_reference)
    if result['current'] != expected_current:
        raise ValueError('RESTORED_INITIAL_DIFFERS_FROM_B_CURRENT')
    return packet


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
    live_sequence = document.get('execution_scope') == 'ROUND3_REAL_B_THREE_STEP'
    index = validate_b_prefix(document, plan, scenario) if live_sequence else 0
    expected_current = (document['b_confirmed_steps'][-1]['current'] if index else plan['plan_base_current'])
    if (document['approved'] != plan['design'] or prepared['current'] != expected_current
            or not same_blocks(plan['plan_base_current']['blocks'], baseline)
            or not same_blocks(document['approved']['blocks'], baseline + targets)
            or not same_blocks([s['after'] for s in plan['plan']['steps']], targets)
            or prepared['step'] != plan['plan']['steps'][index]
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
    binding = dict(execution_id=document['execution_id'], plan_id=action['plan_id'],
                step_id=action['step_id'], current_revision=prepared['current']['current_revision'],
                design_version=document['approved']['design_version'], native_step_id=case['step_id'],
                slot_id=slot['slot_id'], binding_sha256=digest(document))
    if live_sequence:
        from app.round3_initial_inspection import DEFAULT
        if (document.get('home_after_each_step') is not True
                or document.get('manual_step_confirmation') is not True
                or document.get('home_settings_sha256') != file_digest(DEFAULT)):
            raise ValueError('REAL_B_SEQUENCE_HOME_REVIEW_REQUIRED')
        binding.update(execution_scope=document['execution_scope'], b_confirmed_step_count=index)
    if 'trial_scope' in document:
        sources = document.get('baseline_source_sha256', {})
        registry = str(Path(execution_profile).resolve())
        if (document['trial_scope'] not in ('SIXPART_REAL_D_SINGLE_STEP','SIXPART_REAL_D_THREE_STEP_TRIAL')
                or document.get('state_basis') != 'SYNTHETIC_SCENARIO_NOT_B_OBSERVATION'
                or document.get('physical_assembly_verified') is not False
                or not isinstance(sources,dict) or len(sources) != 2 or registry not in sources
                or any(file_digest(path) != value for path,value in sources.items())):
            raise ValueError('CAMERA_FREE_TRIAL_SOURCE_REQUIRED')
        scenario_paths = [Path(path) for path in sources if path != registry]
        if len(scenario_paths) != 1 or json.loads(scenario_paths[0].read_text()) != scenario:
            raise ValueError('CAMERA_FREE_TRIAL_SCENARIO_CHANGED')
        binding.update(trial_scope=document['trial_scope'], physical_assembly_verified=False)
    return binding


def validate_b_prefix(document, plan, scenario):
    """Require B's accepted prefix, never manufacture Current from native success."""
    # Native and root D both use the package name app. Use B's placement
    # validator here so native's historical four-layer app.contracts cannot win.
    from perception.perception_mvp.inspection import _current
    initial, checks = document['b_initial_response'], document['b_confirmed_steps']
    steps = plan['plan']['steps']
    cases = {digest(case['target']): case for case in scenario['steps']}
    order = [cases.get(digest(step['after']), {}).get('step_id') for step in steps]
    if (order != ['T2', 'T1', 'T3'] or len(checks) >= len(steps)
            or initial['check_kind'] != 'INITIAL' or initial['status'] != 'OK'
            or initial['current'] != plan['plan_base_current']):
        raise ValueError('REAL_B_SEQUENCE_INITIAL_OR_ORDER_MISMATCH')
    _current(initial['current'])
    previous = initial
    identities = {initial['check_id']}
    for index, result in enumerate(checks):
        if (result['check_kind'] != 'STEP' or result['status'] != 'OK'
                or result['comparison'] != 'MATCH' or any(result['difference'].values())
                or result['plan_id'] != plan['plan']['plan_id']
                or result['step_id'] != steps[index]['step_id']
                or result['check_id'] in identities
                # B starts observation_seq at zero for each independent check_id.
                or type(result['observation']['observation_seq']) is not int
                or result['observation']['observation_seq'] < 0
                or result['current']['current_revision'] <= previous['current']['current_revision']
                or not same_blocks(result['current']['blocks'], plan['expected_steps'][index]['after_blocks'])):
            raise ValueError('REAL_B_SEQUENCE_CONFIRMED_PREFIX_REQUIRED')
        _current(result['current'])
        identities.add(result['check_id'])
        previous = result
    return len(checks)


def trial_sequence_entries(planning_bundle, prepared):
    """Bind the approved A order to fixed native cases, without creating B Current."""
    result = []
    for step in planning_bundle['plan']['steps']:
        matches = [item for item in prepared if item['case']['target'] == step['after']]
        if len(matches) != 1 or step['operation'] != 'PLACE' or step['before'] is not None:
            raise ValueError('TRIAL_EXACT_NATIVE_TARGET_REQUIRED')
        item = matches[0]
        result.append(dict(a_step_id=step['step_id'], native_step=item['case']['step_id'],
            native_config_sha256=digest(item['config']), additional_native_support_required=item['case']['human_hold']))
    if [item['native_step'] for item in result] != ['T2','T1','T3']:
        raise ValueError('TRIAL_REVIEWED_A_ORDER_T2_T1_T3_REQUIRED')
    return result


def validate_trial_sequence(document, prepared, scenario, execution_profile):
    from app.round3_initial_inspection import DEFAULT
    if (document.get('trial_scope') != 'SIXPART_REAL_D_THREE_STEP_TRIAL'
            or len(prepared) != 3 or document.get('manual_step_confirmation') is not True
            or document.get('home_after_each_step') is not True
            or document.get('home_settings_sha256') != file_digest(DEFAULT)):
        raise ValueError('TRIAL_SEQUENCE_REVIEW_REQUIRED')
    expected = trial_sequence_entries(document['planning_bundle'], prepared)
    if document.get('native_sequence') != expected:
        raise ValueError('TRIAL_SEQUENCE_CONFIG_CHANGED')
    ordered = [next(item for item in prepared if item['case']['step_id']==entry['native_step']) for entry in expected]
    binding = validate_binding(document, ordered[0]['config'], scenario, execution_profile)
    binding['trial_sequence_sha256'] = digest(expected)
    return ordered, binding
