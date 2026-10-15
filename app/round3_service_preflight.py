"""Offline C/A/native coverage review. Plan prefixes are synthetic, never B Current."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from app.c_design.validator import validate_design
from app.cad_trial import measured_inputs
from app.mvp_calculation import whole_input, assessment_input
from app.mvp_real_trial import real_settings
from app.round3_approved_step import file_digest
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment

ROOT = Path(__file__).resolve().parents[1]
ROBOT = ROOT / 'robot_control_integration'
BUNDLE = ROBOT / 'settings/round3_supply_rgbd_20261015/execution-portable-20261015'


def review(robot_root, scenario_path, execution_profile):
    scenario = json.loads(Path(scenario_path).read_text())
    profile = json.loads(Path(execution_profile).read_text())
    baseline = [row['block'] for row in scenario['preplaced']]
    design = dict(design_version=1, blocks=baseline + [row['target'] for row in scenario['steps']])
    reasons = validate_design(design)
    if reasons:
        raise ValueError('OFFLINE_C_CANDIDATE_INVALID: ' + str(reasons))
    preview = subprocess.run([sys.executable, '-m', 'scripts.round2_three_step_trial', 'preview',
        '--scenario', str(Path(scenario_path).resolve()),
        '--execution-profile', str(Path(execution_profile).resolve())], cwd=robot_root,
        text=True, capture_output=True, timeout=30)
    if preview.returncode:
        raise ValueError('OFFLINE_NATIVE_PREVIEW_FAILED: ' + preview.stderr)
    native = json.loads(preview.stdout)
    if native['physical_commands'] != 0:
        raise ValueError('OFFLINE_NATIVE_PREVIEW_REQUIRED')
    settings = real_settings(measured_inputs(robot_root))
    current = dict(current_revision=0, blocks=baseline)
    request = whole_input(design, current, settings, 'SYNTHETIC_REVIEW', 1, 'OFFLINE_REVIEW')
    whole = handle_whole_plan(request)
    if not whole['planning_result'] or whole['planning_result']['status'] != 'READY':
        raise ValueError('OFFLINE_A_PLAN_NOT_READY: ' + str(whole['stage_errors']))
    steps = []
    mapped = set()
    for index, step in enumerate(whole['shared_planning_bundle']['plan']['steps']):
        # This is a fixture for independent reassessment, not an observed or accepted state.
        prefix = dict(current_revision=index, blocks=deepcopy(
            whole['shared_planning_bundle']['expected_steps'][index]['before_blocks']))
        assessment = handle_step_reassessment(assessment_input(request, whole, prefix, index, settings['frame_profile']))
        matches = [row for row in native['steps'] if row['config']['trial_step']['target'] == step['after']]
        binding = matches[0]['config']['educational_supply_binding'] if len(matches) == 1 else None
        case = matches[0]['config']['trial_step'] if len(matches) == 1 else None
        if binding: mapped.add(binding['slot_id'])
        action = assessment.get('action_proposal')
        steps.append(dict(plan_step_id=step['step_id'], target=step['after'],
            native_step_id=case['step_id'] if case else None,
            supply_slot_id=binding['slot_id'] if binding else None,
            supply_execution_mode=binding['execution_mode'] if binding else None,
            assessment_status=assessment['status'], action=action, errors=assessment['errors'],
            native_human_hold=case['human_hold'] if case else None,
            native_support_target=case['hold_lower'] if case and case['human_hold'] else None,
            additional_native_support_required=bool(case and case['human_hold'] and action
                                                    and action['assistance_kind']=='NONE'),
            actual_service_binding='FIRST_STEP_ONLY' if index == 0 else 'PREFIX_AND_SUPPORT_BINDING_REQUIRED'))
    return dict(status='OFFLINE_SERVICE_PREFLIGHT', sample_kind='SYNTHETIC_EXPECTED_PREFIX_NOT_B_CURRENT',
        user_design_approved=False, physical_commands=0, device_connections=0,
        candidate_blocks=len(design['blocks']), supply_physical_targets=len(profile['slots']),
        supply_slots=[dict(slot_id=row['slot_id'], execution_mode=row['execution_mode'],
            execution_approved=row['execution_approved'], mapped_in_limited_scenario=row['slot_id'] in mapped)
            for row in profile['slots']],
        native_preview_status=native['status'], steps=steps,
        source_sha256=dict(scenario=file_digest(scenario_path), execution_profile=file_digest(execution_profile)),
        pending=['Actual B Current and live D state', 'Remaining Current/prefix/native support bindings',
                 'Physical grasp/seating and B STEP/FINAL', 'Authenticated DB/web integration'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-root', type=Path, default=ROBOT)
    parser.add_argument('--scenario', type=Path, default=BUNDLE / 'scenario.json')
    parser.add_argument('--execution-profile', type=Path, default=BUNDLE / 'profile.json')
    args = parser.parse_args(argv)
    print(json.dumps(review(args.robot_root, args.scenario, args.execution_profile), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
