"""Reproducible offline API calls, stage artifacts and local consumer checks."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

from planning_trial.assembly_adapter import (handle_whole_plan, handle_step_reassessment,
                                            handle_step_motion, receive_result_for_review)
from planning_trial.assembly_api_fixtures import (whole_request, reassess_request, motion_request,
                                                frame_profile, brick)
from planning_trial.assembly_contract import schema, VERSION
from planning_trial.assembly_optimizer import mode_options
from planning_trial.assembly_wire import normalize_action
from planning_trial.planning_bundle import validate_planning_bundle


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--actor', choices=('agent', 'user'), required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report, lines = [], []

    def run(case, stage, request, expected):
        path = args.output_dir/case
        path.mkdir(exist_ok=True)
        audit = {}
        handler = {'whole': handle_whole_plan, 'reassessment': handle_step_reassessment, 'motion': handle_step_motion}[stage]
        result = handler(request, audit=audit)
        dump(path/(stage+'.request.json'), request)
        dump(path/(stage+'.raw.json'), audit['raw_result'])
        dump(path/(stage+'.result.json'), result)
        if result.get('shared_planning_bundle') is not None:
            dump(path/'common_planning_bundle.json', result['shared_planning_bundle'])
        consumer = receive_result_for_review(result, request)
        dump(path/(stage+'.local_consumer.json'), consumer)
        observed = (result['planning_result']['status'] if result.get('planning_result') else
                    result.get('calculation_status', result.get('status')))
        passed = observed == expected and result['execution_allowed'] is False and consumer['robot_commands_issued'] == 0
        line = f'{case}/{stage}: {observed} (expected={expected}) -> {"PASS" if passed else "FAIL"}'
        print(line, flush=True); lines.append(line)
        report.append({'case': case, 'stage': stage, 'expected': expected, 'observed': observed, 'pass': passed})
        return result

    initial = whole_request()
    whole = run('01_initial', 'whole', initial, 'READY')
    reassessment = reassess_request(initial, whole)
    assessed = run('01_initial', 'reassessment', reassessment, 'CANDIDATE')
    motion = motion_request(reassessment, assessed)
    run('01_initial', 'motion', motion, 'CANDIDATE')

    current = {'current_revision': 1, 'blocks': [whole['planning_result']['plan']['steps'][0]['after']]}
    next_request = reassess_request(initial, whole, current, 1)
    next_assessed = run('02_same_plan_next_step', 'reassessment', next_request, 'CANDIDATE')
    run('02_same_plan_next_step', 'motion', motion_request(next_request, next_assessed), 'CANDIDATE')
    run('03_partial_replan', 'whole', whole_request(initial['design'], current), 'READY')
    run('04_needs_correction', 'whole', whole_request(current={'current_revision': 1, 'blocks': [brick(x=10)]}), 'NEEDS_CORRECTION')
    run('05_support_invalid', 'whole', whole_request(design={'design_version': 1, 'blocks': [brick(layer=2)]}), 'INVALID')
    run('06_no_remaining', 'whole', whole_request(initial['design'], {'current_revision': 2, 'blocks': initial['design']['blocks']}), 'READY')
    for name, mutate in (
        ('07_wrong_slot', lambda r: r['reserved_supply_slot'].update(color='yellow')),
        ('08_unknown_slot', lambda r: r['reserved_supply_slot'].update(part_confirmation='UNKNOWN')),
        ('09_profile_changed', lambda r: r['frame_profile']['calculation_profiles'].update(pickup_approach_clearance_mm=31)),
        ('10_old_assessment_revision', lambda r: r.update(assessment_current_revision=1)),
    ):
        request = deepcopy(motion); mutate(request)
        run(name, 'motion', request, 'BLOCKED')

    old_response = handle_step_motion(motion)
    new_request = deepcopy(motion)
    new_request['context']['request_id'] = 'new-active-request'
    consumer = receive_result_for_review(old_response, new_request)
    path = args.output_dir/'11_old_result'; path.mkdir()
    dump(path/'old.result.json', old_response); dump(path/'active.request.json', new_request)
    dump(path/'local_consumer.json', consumer)
    passed = consumer['decision'] == 'IGNORE_STALE_RESULT' and consumer['robot_commands_issued'] == 0
    report.append({'case': '11_old_result', 'expected': 'IGNORE_STALE_RESULT', 'observed': consumer['decision'], 'pass': passed})
    lines.append(f'11_old_result: {consumer["decision"]} -> {"PASS" if passed else "FAIL"}')
    print(lines[-1], flush=True)

    press_request = whole_request(); press_request['assembly_context']['press_contact_model_confirmed'] = True
    press_whole = run('12_press_excluded', 'whole', press_request, 'READY')
    press_re = reassess_request(press_request, press_whole)
    step = press_re['plan']['steps'][0]
    geometric_context = deepcopy(press_request['assembly_context']); geometric_context.pop('supported_modes')
    option = next(o for o in mode_options(step['after'], [], geometric_context)[0] if o['mode'] == 'ROBOT_RELEASE_PRESS')
    legacy_press = normalize_action(option, press_re['plan'], step, press_request['assembly_context'])
    press_assessed = run('12_press_excluded', 'reassessment', press_re, 'CANDIDATE')
    run('12_press_excluded', 'motion', motion_request(press_re, press_assessed), 'CANDIDATE')

    context = deepcopy(initial['assembly_context']); context['grip_axes'] = ['x']
    sides = [brick(x=4), brick(x=8)]
    manual_req = whole_request({'design_version': 1, 'blocks': sides+[brick()]}, {'current_revision': 2, 'blocks': sides}, context)
    manual_whole = run('13_manual_missing_tray', 'whole', manual_req, 'READY')
    manual_re = reassess_request(manual_req, manual_whole)
    manual_assessed = run('13_manual_missing_tray', 'reassessment', manual_re, 'CANDIDATE')
    run('13_manual_missing_tray', 'motion', motion_request(manual_re, manual_assessed), 'BLOCKED')
    tray = frame_profile()
    tray['calculation_profiles']['tray'] = {'profile_id': 'TEST_ONLY_TRAY_NOT_REAL_D',
                                           'tcp_pose_mm_zyz_deg': [200, 0, 60, 0, 180, 0], 'travel_tcp_z_mm': 180}
    tray['profile_version'] = 'fixture-tray-v2'
    manual_re = deepcopy(manual_re)
    manual_re['context']['frame_profile_id'] = tray['profile_id']
    manual_re['context']['frame_profile_version'] = tray['profile_version']
    manual_re['frame_profile'] = deepcopy(tray)
    manual_re['context']['request_id'] = 'manual-reassessment-with-test-tray-profile'
    manual_assessed = run('14_manual_test_tray', 'reassessment', manual_re, 'CANDIDATE')
    run('14_manual_test_tray', 'motion', motion_request(manual_re, manual_assessed, tray), 'CANDIDATE')

    limited = deepcopy(initial); limited['assembly_context']['max_states'] = 1
    run('15_search_limit', 'whole', limited, 'SEARCH_LIMIT')
    bad = deepcopy(initial); bad['design']['blocks'][0]['x'] = 24
    run('16_outside_board', 'whole', bad, 'INVALID_CONTEXT')
    mismatch = deepcopy(reassessment)
    mismatch['latest_current'] = {'current_revision': 1, 'blocks': [brick(x=10)]}
    mismatch['expected_current_before_step'] = deepcopy(mismatch['latest_current'])
    mismatch['context']['input_current_revision'] = 1
    run('17_unexpected_current', 'reassessment', mismatch, 'BLOCKED')

    # Requested D changes: identity/version, no unsupported selection, one B/D payload.
    p = frame_profile(); p.update(profile_id='D-frame-calibration-custom', profile_version='D-v17')
    custom_req = whole_request(profile=p)
    custom_whole = run('18_d_profile_reference', 'whole', custom_req, 'READY')
    custom_re = reassess_request(custom_req, custom_whole)
    custom_assessed = run('18_d_profile_reference', 'reassessment', custom_re, 'CANDIDATE')
    custom_motion = motion_request(custom_re, custom_assessed, p)
    run('18_d_profile_reference', 'motion', custom_motion, 'CANDIDATE')
    changed = deepcopy(custom_motion)
    changed['frame_profile']['profile_version'] = 'D-v18'
    changed['context']['frame_profile_version'] = 'D-v18'
    run('19_old_profile_version', 'motion', changed, 'BLOCKED')
    only_grip = deepcopy(manual_req); only_grip['assembly_context']['supported_modes'] = ['ROBOT_GRIP']
    only_grip['assembly_context']['press_contact_model_confirmed'] = True
    run('20_no_supported_method', 'whole', only_grip, 'NO_FEASIBLE_ORDER')
    re_no_method = deepcopy(reassessment)
    re_no_method['assembly_context']['grip_axes'] = ['x']
    # Block the chosen x corridor with a fixture obstacle, not actual observation.
    re_no_method['assembly_context']['supported_modes'] = ['ROBOT_GRIP']
    re_no_method['assembly_context']['obstacles'] = [[60, 60, 0, 160, 160, 100]]
    run('21_reassessment_no_method', 'reassessment', re_no_method, 'BLOCKED')
    forced = deepcopy(motion_request(press_re, press_assessed))
    forced['action_proposal'] = deepcopy(legacy_press)
    forced['assessed_action'] = deepcopy(forced['action_proposal'])
    run('22_forced_unsupported_motion', 'motion', forced, 'BLOCKED')
    bundle = custom_whole['shared_planning_bundle']
    validate_planning_bundle(bundle)
    path = args.output_dir/'23_common_b_d_bundle'; path.mkdir()
    dump(path/'common_planning_bundle.json', bundle)
    # Both references point to the identical artifact; actual fan-out is D-owned.
    file_hash = sha256((path/'common_planning_bundle.json').read_bytes()).hexdigest()
    refs = {role: {'file': 'common_planning_bundle.json', 'sha256': file_hash,
                   'plan_id': bundle['plan']['plan_id']} for role in ('B', 'D')}
    dump(path/'distribution_refs.json', refs)
    passed = refs['B'] == refs['D'] and bundle['plan'] == custom_whole['planning_result']['plan']
    report.append({'case': '23_common_b_d_bundle', 'expected': 'IDENTICAL_PLAN_AND_PAYLOAD',
                   'observed': 'IDENTICAL_PLAN_AND_PAYLOAD' if passed else 'MISMATCH', 'pass': passed})
    lines.append(f'23_common_b_d_bundle: identical B/D payload -> {"PASS" if passed else "FAIL"}')
    print(lines[-1], flush=True)
    old_press_request = deepcopy(press_re)
    old_press_request['selected_action'] = legacy_press
    run('24_old_press_action', 'reassessment', old_press_request, 'BLOCKED')

    dump(args.output_dir/'schema.draft.json', schema())
    sources = ['assembly_adapter.py', 'assembly_motion.py', 'assembly_contract.py', 'assembly_wire.py',
               'assembly_api_fixtures.py', 'run_assembly_apis.py', 'planner.py', 'assembly_optimizer.py',
               'assembly_geometry.py', 'assembly_target.py', 'supply_pick.py', 'sample_user_rules_5mm_measured_rev2_inputs.json',
               'measurement_geometry.py', 'assembly_profiles.py', 'planning_bundle.py',
               'measurements/block_geometry.user_20261008.rev2.json',
               'measurements/abs_reference_properties.user_20261008.json',
               'connection_contract_review_20261008_v4/schema.json']
    root = Path(__file__).resolve().parent
    manifest = {'actor': args.actor, 'utc_time': datetime.now(timezone.utc).isoformat(), 'schema_version': VERSION,
                'source_sha256': {f: sha256((root/f).read_bytes()).hexdigest() for f in sources},
                'scope': 'ACTUAL_A_FUNCTIONS_AND_LOCAL_ADAPTER; SAMPLE_INPUTS; LOCAL_CONSUMER_NOT_ACTUAL_D',
                'fixture_state_is_not_device_observation': True, 'execution_allowed': False,
                'current_contract_provenance': 'D_ADOPTED_CURRENT',
                'd_receipt_verified': False, 'isaac_ik_collision_verified': False,
                'python_version': sys.version, 'checks': report,
                'passed': sum(r['pass'] for r in report), 'total': len(report)}
    dump(args.output_dir/'report.json', manifest)
    lines.append(f'Checks: {manifest["passed"]}/{manifest["total"]} PASS; actor={args.actor}; no robot/D/Isaac execution')
    (args.output_dir/'run.log').write_text('\n'.join(lines)+'\n')
    print(lines[-1]); print('Saved:', args.output_dir.resolve())
    return 0 if all(r['pass'] for r in report) else 1


if __name__ == '__main__': raise SystemExit(main())
