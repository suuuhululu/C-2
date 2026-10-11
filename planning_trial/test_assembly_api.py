"""Meaningful stage/ref/candidate tests; local consumer is explicitly not actual D."""
from copy import deepcopy

import pytest

from planning_trial.assembly_adapter import (handle_whole_plan, handle_step_reassessment,
                                            handle_step_motion, receive_result_for_review, AdapterInputError)
from planning_trial.assembly_api_fixtures import whole_request, reassess_request, motion_request, brick, frame_profile
from planning_trial.assembly_contract import validate_message
from planning_trial.assembly_profiles import profile_content_digest
from planning_trial.planning_bundle import validate_planning_bundle
from planning_trial.assembly_wire import box_to_region, pose_mm_zyz
from planning_trial.assembly_optimizer import mode_options
from planning_trial.assembly_wire import normalize_action


def chain():
    req = whole_request()
    whole = handle_whole_plan(req)
    reassess_req = reassess_request(req, whole)
    assessment = handle_step_reassessment(reassess_req)
    return req, whole, reassess_req, assessment, motion_request(reassess_req, assessment)


def test_three_actual_calls_return_only_candidates_and_do_not_mutate_inputs():
    req, whole, re_req, assessment, mo_req = chain()
    before = deepcopy(mo_req)
    result = handle_step_motion(mo_req)
    assert whole['planning_result']['status'] == 'READY'
    assert assessment['status'] == result['status'] == 'CANDIDATE', result
    assert result['motion_proposal']['handoff_to'] == 'D_CONTACT'
    assert [s['stage'] for s in result['motion_proposal']['segments']] == ['APPROACH_PICK', 'D_PICK_AND_CONFIRM', 'TRANSPORT_HOLDING']
    assert result['motion_proposal']['terminal_gripper_policy'] == 'HOLD_NO_AUTOMATIC_OPEN'
    assert not result['execution_allowed'] and not any(result['motion_proposal']['validation'].values())
    assert result['context'] == mo_req['context'] and before == mo_req
    for response in (whole, assessment, result): validate_message(response)


def test_completed_step_revision_advances_without_changing_plan_baseline():
    req, whole, _, _, _ = chain()
    plan = whole['planning_result']['plan']
    current = {'current_revision': 1, 'blocks': [plan['steps'][0]['after']]}
    re_req = reassess_request(req, whole, current, 1)
    assessment = handle_step_reassessment(re_req)
    result = handle_step_motion(motion_request(re_req, assessment))
    assert assessment['status'] == result['status'] == 'CANDIDATE', (assessment, result)
    assert re_req['plan']['base_current_revision'] == 0
    assert result['motion_proposal']['current_revision'] == 1
    assert len(handle_whole_plan(whole_request(req['design'], current))['planning_result']['plan']['steps']) == 1


def test_all_current_returns_empty_plan_and_already_assembled_reassessment():
    req = whole_request()
    whole = handle_whole_plan(req)
    re_req = reassess_request(req, whole, {'current_revision': 1, 'blocks': [whole['planning_result']['plan']['steps'][0]['after']]})
    assert handle_step_reassessment(re_req)['status'] == 'ALREADY_ASSEMBLED'
    full = handle_whole_plan(whole_request(req['design'], {'current_revision': 2, 'blocks': req['design']['blocks']}))
    assert full['planning_result']['plan']['steps'] == full['action_proposals'] == []


def test_unexpected_current_is_not_accepted_even_when_expected_field_is_forged():
    _, _, re_req, _, _ = chain()
    re_req['latest_current'] = {'current_revision': 1, 'blocks': [brick(x=10)]}
    re_req['expected_current_before_step'] = deepcopy(re_req['latest_current'])
    re_req['context']['input_current_revision'] = 1
    result = handle_step_reassessment(re_req)
    assert result['status'] == 'BLOCKED' and result['action_proposal'] is None
    assert result['errors'][0]['code'] == 'CURRENT_MISMATCH'


@pytest.mark.parametrize('condition', ['slot_color', 'unknown_slot', 'released', 'workflow', 'assessment_revision',
                                      'profile_hash', 'robot_tcp', 'stop', 'holding', 'queue', 'epoch', 'assessed_action'])
def test_invalid_or_mismatched_motion_inputs_never_create_a_path(condition):
    _, _, _, _, req = chain()
    if condition == 'slot_color': req['reserved_supply_slot']['color'] = 'yellow'
    elif condition == 'unknown_slot': req['reserved_supply_slot']['part_confirmation'] = 'UNKNOWN'
    elif condition == 'released': req['reserved_supply_slot']['state'] = 'RELEASED'
    elif condition == 'workflow': req['reserved_supply_slot']['bound_workflow_generation'] += 1
    elif condition == 'assessment_revision': req['assessment_current_revision'] += 1
    elif condition == 'profile_hash': req['frame_profile']['calculation_profiles']['pickup_approach_clearance_mm'] += 1
    elif condition == 'robot_tcp': req['robot_state']['tcp_setting_name'] = 'different_tcp'
    elif condition == 'stop': req['robot_state']['stopped_verified'] = None
    elif condition == 'holding': req['robot_state']['holding_confirmed'] = True
    elif condition == 'queue': req['robot_state']['pending_command_count'] = 1
    elif condition == 'epoch': req['robot_state']['source_epoch'] = 'old'
    elif condition == 'assessed_action': req['assessed_action']['block']['color'] = 'yellow'
    result = handle_step_motion(req)
    assert result['status'] == 'BLOCKED' and result['motion_proposal'] is None and result['errors'], result


@pytest.mark.parametrize('condition', ['request_id', 'workflow', 'reservation'])
def test_old_result_is_ignored_by_local_consumer_fixture(condition):
    _, _, _, _, req = chain()
    result = handle_step_motion(req)
    if condition == 'request_id': req['context']['request_id'] = 'new-request'
    elif condition == 'workflow': req['context']['workflow_generation'] += 1
    else:
        req['reserved_supply_slot']['reservation_generation'] += 1
        req['reserved_supply_slot']['reservation_id'] = 'new-reservation'
    check = receive_result_for_review(result, req)
    assert check['decision'] == 'IGNORE_STALE_RESULT' and check['robot_commands_issued'] == 0


def test_adapter_rejects_nonfinite_unknown_field_and_missing_correlation():
    req = whole_request()
    req['unexpected'] = 1
    result = handle_whole_plan(req)
    assert result['planning_result'] is None and result['stage_errors']
    req = whole_request(); req['assembly_context']['geometry']['pitch_mm'] = float('nan')
    assert handle_whole_plan(req)['planning_result'] is None
    with pytest.raises(AdapterInputError): handle_whole_plan({})


def test_help_polygon_and_units_use_stud_top_origin_and_no_fake_hold_force():
    region = box_to_region([10, 20, 25, 10, 30, 45], 5)
    assert region['vertices_xyz_m'] == [[.01, .02, .02], [.01, .03, .02], [.01, .03, .04], [.01, .02, .04]]
    pose = pose_mm_zyz([100, 200, 300, 0, 180, 0])
    assert pose['xyz_m'] == [.1, .2, .3]
    assert sum(v*v for v in pose['quaternion_xyzw']) == pytest.approx(1)


def test_manual_branch_needs_explicit_tray_and_holds_until_d_release():
    context = whole_request()['assembly_context']; context['grip_axes'] = ['x']
    sides = [brick(x=4), brick(x=8)]
    req = whole_request({'design_version': 1, 'blocks': sides+[brick()]}, {'current_revision': 2, 'blocks': sides}, context)
    whole = handle_whole_plan(req)
    assert whole['action_proposals'][0]['mode'] == 'HUMAN_ASSEMBLY', whole
    re_req = reassess_request(req, whole); assessment = handle_step_reassessment(re_req)
    mo_req = motion_request(re_req, assessment)
    missing = handle_step_motion(mo_req)
    assert missing['errors'][0]['code'] == 'INPUTS_REQUIRED'
    p = frame_profile()
    # Explicit fixture coordinates only, not a claimed real D tray calibration.
    p['calculation_profiles']['tray'] = {'profile_id': 'TEST_ONLY_TRAY', 'tcp_pose_mm_zyz_deg': [200, 0, 60, 0, 180, 0], 'travel_tcp_z_mm': 180}
    p['profile_version'] = 'fixture-tray-v2'
    re_req['context']['frame_profile_version'] = p['profile_version']
    re_req['frame_profile'] = deepcopy(p)
    assessment = handle_step_reassessment(re_req)
    result = handle_step_motion(motion_request(re_req, assessment, p))
    assert result['status'] == 'CANDIDATE', result
    assert result['motion_proposal']['handoff_to'] == 'D_HANDOVER_RELEASE_AND_RETREAT'
    assert result['motion_proposal']['terminal_gripper_policy'] == 'HOLD_NO_AUTOMATIC_OPEN'


def test_unimplemented_press_is_excluded_before_search_and_reassessment():
    req = whole_request(); req['assembly_context']['press_contact_model_confirmed'] = True
    whole = handle_whole_plan(req); re_req = reassess_request(req, whole)
    step = re_req['plan']['steps'][0]
    geometric_context = deepcopy(req['assembly_context']); geometric_context.pop('supported_modes')
    option = next(o for o in mode_options(step['after'], [], geometric_context)[0] if o['mode'] == 'ROBOT_RELEASE_PRESS')
    re_req['selected_action'] = normalize_action(option, re_req['plan'], step, req['assembly_context'])
    assessment = handle_step_reassessment(re_req)
    assert all(a['mode'] != 'ROBOT_RELEASE_PRESS' for a in whole['action_proposals'])
    assert assessment['status'] == 'BLOCKED' and assessment['action_proposal'] is None
    assert assessment['errors'][0]['code'] == 'UNSUPPORTED_METHOD'
    old_press = deepcopy(re_req['selected_action'])
    re_req['selected_action'] = None  # Explicit fresh selection; not an implicit replacement.
    assessment = handle_step_reassessment(re_req)
    assert assessment['action_proposal']['mode'] == 'ROBOT_GRIP'
    mo_req = motion_request(re_req, assessment)
    # An explicit unsupported motion request is rejected, not converted to grip.
    mo_req['action_proposal'] = deepcopy(old_press)
    mo_req['assessed_action'] = deepcopy(old_press)
    result = handle_step_motion(mo_req)
    assert result['status'] == 'BLOCKED' and result['errors'][0]['code'] == 'UNSUPPORTED_METHOD'


def test_diagnostic_out_of_board_block_is_preserved_and_null_error_allowed():
    req = whole_request(); req['design']['blocks'][0]['x'] = 24
    result = handle_whole_plan(req)
    assert result['stage_errors'][0]['block']['x'] == 24
    req = whole_request(); req['assembly_context']['max_states'] = 1
    result = handle_whole_plan(req)
    assert result['calculation_status'] == 'SEARCH_LIMIT' and result['stage_errors'][0]['block'] is None


def test_preservation_and_support_errors_keep_legacy_result_branches():
    req = whole_request(current={'current_revision': 1, 'blocks': [brick(x=10)]})
    result = handle_whole_plan(req)
    assert result['planning_result']['status'] == 'NEEDS_CORRECTION'
    req = whole_request(design={'design_version': 1, 'blocks': [brick(layer=2)]})
    result = handle_whole_plan(req)
    assert result['planning_result']['status'] == 'INVALID'


def test_press_hold_geometry_keeps_targets_separate_without_inventing_hold_force():
    lower = [{'brick_type': '2x3x1', 'color': 'blue', 'x': x, 'y': 4, 'layer': layer, 'orientation_deg': 0}
             for x, layer in ((4, 1), (5, 2))]
    upper = dict(lower[-1], x=6, layer=3)
    req = whole_request({'design_version': 1, 'blocks': lower+[upper]}, {'current_revision': 2, 'blocks': lower})
    result = handle_whole_plan(req)
    action = result['action_proposals'][0]
    assert action['assistance_kind'] == 'PRESS_AND_HOLD'
    hold = next(h for h in action['human_actions'] if h['action'] == 'HOLD')
    press = next(h for h in action['human_actions'] if h['action'] == 'PRESS')
    assert hold['target_block'] == lower[-1] and hold['force_direction_base'] is None
    assert len(hold['contact_regions']) == 2
    assert press['target_block'] == upper and press['force_direction_base'] == [0, 0, -1]


def test_non_normalized_robot_quaternion_is_rejected():
    _, _, _, _, req = chain()
    req['robot_state']['tcp_pose']['quaternion_xyzw'] = [0, 0, 0, 2]
    result = handle_step_motion(req)
    assert result['status'] == 'BLOCKED' and result['motion_proposal'] is None


def test_changed_profile_version_requires_new_assessment():
    _, _, _, _, req = chain()
    req['frame_profile']['calculation_profiles']['pickup_approach_clearance_mm'] = 31
    req['frame_profile']['profile_version'] = 'D-v2'
    req['context']['frame_profile_version'] = 'D-v2'
    result = handle_step_motion(req)
    assert result['status'] == 'BLOCKED' and result['errors'][0]['code'] == 'REFERENCE_MISMATCH'


def test_arbitrary_d_profile_id_and_version_are_preserved_independent_of_hash():
    p = frame_profile(); p.update(profile_id='D-calibration-2026', profile_version='v17')
    req = whole_request(profile=p)
    whole = handle_whole_plan(req)
    re_req = reassess_request(req, whole)
    assessed = handle_step_reassessment(re_req)
    result = handle_step_motion(motion_request(re_req, assessed, p))
    assert result['status'] == 'CANDIDATE', result
    assert result['motion_proposal']['profile_id'] == p['profile_id']
    assert result['motion_proposal']['profile_version'] == 'v17'
    assert p['profile_id'] != profile_content_digest(p)


def test_context_change_with_same_action_requires_new_assessment():
    _, _, _, _, req = chain()
    req['assembly_context']['max_states'] += 1
    result = handle_step_motion(req)
    assert result['status'] == 'BLOCKED' and result['errors'][0]['code'] == 'FRAME_PROFILE_CHANGED'


def test_fresh_reassessment_accepts_changed_content_without_renaming_d_profile_id():
    req, whole, re_req, old, _ = chain()
    p = deepcopy(re_req['frame_profile'])
    p['calculation_profiles']['pickup_approach_clearance_mm'] = 31
    p['profile_version'] = 'D-v2'
    re_req['frame_profile'] = p
    re_req['context']['frame_profile_version'] = p['profile_version']
    fresh = handle_step_reassessment(re_req)
    result = handle_step_motion(motion_request(re_req, fresh, p))
    assert fresh['assessment_input_digest'] != old['assessment_input_digest']
    assert result['status'] == 'CANDIDATE' and result['motion_proposal']['profile_id'] == p['profile_id']


@pytest.mark.parametrize('mutation', ['plan', 'digest', 'expected', 'profile'])
def test_tampered_common_bundle_is_rejected_by_local_consumer(mutation):
    req = whole_request()
    result = handle_whole_plan(req)
    b = result['shared_planning_bundle']
    if mutation == 'plan': b['plan']['plan_id'] = 'other-plan'
    elif mutation == 'digest': b['bundle_digest'] = '0'*64
    elif mutation == 'expected': b['expected_steps'][0]['after_blocks'][0]['x'] += 1
    else: b['profile_snapshot']['profile_version'] = 'other-version'
    with pytest.raises(ValueError): receive_result_for_review(result, req)


def test_only_grip_enabled_blocks_instead_of_selecting_manual_or_press():
    ctx = whole_request()['assembly_context']
    ctx.update(grip_axes=['x'], supported_modes=['ROBOT_GRIP'], press_contact_model_confirmed=True)
    sides = [brick(x=4), brick(x=8)]
    req = whole_request({'design_version': 1, 'blocks': sides+[brick()]},
                        {'current_revision': 2, 'blocks': sides}, ctx)
    whole = handle_whole_plan(req)
    assert whole['calculation_status'] == 'NO_FEASIBLE_ORDER'
    assert whole['planning_result'] is whole['shared_planning_bundle'] is None
    assert whole['stage_errors'][0]['code'] == 'NO_FEASIBLE_ORDER'


def test_reassessment_with_no_supported_feasible_option_is_blocked():
    ctx = whole_request()['assembly_context']; ctx['grip_axes'] = ['x']
    sides = [brick(x=4), brick(x=8)]
    req = whole_request({'design_version': 1, 'blocks': sides+[brick()]},
                        {'current_revision': 2, 'blocks': sides}, ctx)
    whole = handle_whole_plan(req)
    re_req = reassess_request(req, whole)
    re_req['assembly_context']['supported_modes'] = ['ROBOT_GRIP']
    result = handle_step_reassessment(re_req)
    assert result['status'] == 'BLOCKED' and result['action_proposal'] is None
    assert result['errors'][0]['code'] == 'NO_FEASIBLE_METHOD'


@pytest.mark.parametrize('current', [None, {'current_revision': 5, 'blocks': [brick()]}])
def test_common_bundle_replays_same_plan_baseline_and_exact_target_without_observed_revisions(current):
    req = whole_request(current=current)
    before = deepcopy(req)
    result = handle_whole_plan(req)
    bundle = result['shared_planning_bundle']
    validate_planning_bundle(bundle)
    assert bundle['plan'] == result['planning_result']['plan']
    assert bundle['plan_base_current'] == req['current'] and req == before
    assert bundle['current_provenance'] == 'D_ADOPTED_CURRENT'
    assert bundle['geometry']['layer_increment_m'] == .019
    assert bundle['geometry']['first_layer_body_bottom_z_m'] == -.0045
    assert bundle['final_expected_blocks'] == req['design']['blocks']
    assert len(bundle['expected_steps']) == len(bundle['plan']['steps'])
    assert all('current_revision' not in s for s in bundle['expected_steps'])
    changed = deepcopy(bundle); changed['expected_steps'][0]['after_blocks'][0]['color'] = 'yellow'
    with pytest.raises(ValueError): validate_planning_bundle(changed)


def test_empty_plan_still_returns_common_bundle_and_failures_do_not():
    req = whole_request()
    req['current'] = {'current_revision': 8, 'blocks': deepcopy(req['design']['blocks'])}
    req['context']['input_current_revision'] = 8
    result = handle_whole_plan(req)
    assert result['shared_planning_bundle']['expected_steps'] == []
    failed = handle_whole_plan(whole_request(current={'current_revision': 1, 'blocks': [brick(x=10)]}))
    assert failed['shared_planning_bundle'] is None


def test_latest_dimensions_change_layer_spacing_without_moving_pick_anchor():
    req, whole, _, _, mo_req = chain()
    first = handle_step_motion(mo_req)
    current = {'current_revision': 1, 'blocks': [whole['planning_result']['plan']['steps'][0]['after']]}
    next_req = reassess_request(req, whole, current, 1)
    next_result = handle_step_motion(motion_request(next_req, handle_step_reassessment(next_req)))
    geometry = req['assembly_context']['geometry']
    assert geometry['body_height_mm'] == 19 and geometry['stud_height_mm'] == 4.5 and geometry['pitch_mm'] == 16
    get_z = lambda r: r['motion_proposal']['segments'][-1]['waypoints'][-1]['tcp_pose']['xyz_m'][2]
    assert get_z(next_result)-get_z(first) == pytest.approx(.019)
    assert first['motion_proposal']['pickup_tcp_pose']['xyz_m'][2] == pytest.approx(.05004)
    assert req['policy']['hand_hold_height_m'] == .019


def test_old_geometry_context_cannot_silently_mix_with_latest_target_profile():
    _, _, _, _, req = chain()
    req['assembly_context']['geometry']['body_height_mm'] = 20
    result = handle_step_motion(req)
    assert result['status'] == 'BLOCKED' and result['errors'][0]['code'] == 'FRAME_PROFILE_CHANGED'


def test_five_layer_whole_reassessment_and_motion_keep_d_current_and_draft_gate():
    design = {'design_version': 3, 'blocks': [brick(layer=n) for n in range(1, 6)]}
    req = whole_request(design=design)
    before = deepcopy(req)
    whole = handle_whole_plan(req)
    assert whole['planning_result']['status'] == 'READY'
    plan = whole['planning_result']['plan']
    bundle = whole['shared_planning_bundle']
    assert bundle['bundle_schema'] == 'a-b-d-planning-bundle-draft/0.1.1'
    assert bundle['current_provenance'] == 'D_ADOPTED_CURRENT'
    validate_message(whole)
    current = {'current_revision': 17, 'blocks': deepcopy(design['blocks'][:4])}
    re_req = reassess_request(req, whole, current, 4)
    assessed = handle_step_reassessment(re_req)
    assert assessed['status'] == 'CANDIDATE'
    assert assessed['context']['input_current_revision'] == 17
    motion = handle_step_motion(motion_request(re_req, assessed))
    assert motion['status'] == 'CANDIDATE'
    assert motion['motion_proposal']['current_revision'] == 17
    assert plan['base_current_revision'] == 0
    assert all(result['execution_allowed'] is False for result in (whole, assessed, motion))
    partial = handle_whole_plan(whole_request(design=design, current=current))
    assert partial['planning_result']['status'] == 'READY'
    assert partial['planning_result']['plan']['base_current_revision'] == 17
    assert [s['after'] for s in partial['planning_result']['plan']['steps']] == [brick(layer=5)]
    assert req == before and current['current_revision'] == 17


@pytest.mark.parametrize('layer,calculation_status', [
    (0, 'INVALID_CONTEXT'), (6, 'INVALID_CONTEXT'), (True, 'INVALID_CONTEXT'),
    (5.0, 'COMPLETED'),  # JSON integer accepts 5.0; Python planner rejects its type.
])
def test_layer_out_of_contract_cannot_produce_a_plan(layer, calculation_status):
    req = whole_request(design={'design_version': 1, 'blocks': [brick(layer=layer)]})
    result = handle_whole_plan(req)
    assert result['calculation_status'] == calculation_status
    if result['planning_result'] is not None:
        assert result['planning_result']['status'] == 'INVALID'
        assert result['planning_result']['plan'] is None and result['planning_result']['errors']
    else:
        assert result['stage_errors']
    assert result['shared_planning_bundle'] is None and result['execution_allowed'] is False


def test_previous_contract_version_and_b_owned_current_bundle_are_rejected():
    req = whole_request()
    req['schema_version'] = 'assembly-ad-calculation-draft/0.5'
    result = handle_whole_plan(req)
    assert result['calculation_status'] == 'INVALID_CONTEXT'
    assert result['planning_result'] is None and result['execution_allowed'] is False
    result = handle_whole_plan(whole_request())
    result['shared_planning_bundle']['current_provenance'] = 'B_CONFIRMED_D_RELAYED'
    with pytest.raises(ValueError):
        validate_message(result)
    with pytest.raises(ValueError):
        validate_planning_bundle(result['shared_planning_bundle'])
