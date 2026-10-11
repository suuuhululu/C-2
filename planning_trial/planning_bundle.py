"""One immutable expected-plan payload for B and D; never an observed Current."""
from copy import deepcopy

from planning_trial.assembly_profiles import content_digest, profile_content_digest
from planning_trial.planner import BRICK_SIZES, validate_plan


def build_planning_bundle(design, plan, plan_base_current, assembly_context, frame_profile):
    validate_plan(design, plan_base_current['blocks'], plan_base_current['current_revision'],
                  plan, finish_layers=assembly_context['finish_layers'])
    g = assembly_context['geometry']
    target_g = frame_profile['calculation_profiles']['assembly']['geometry']
    if any(g[k] != target_g[k] for k in ('body_height_mm', 'stud_height_mm')):
        raise ValueError('Common bundle geometry differs from target profile')
    supply = frame_profile['calculation_profiles']['supply']
    if g['body_height_mm'] != supply['block_body_height_mm']:
        raise ValueError('Common bundle geometry differs from supply profile')
    blocks = deepcopy(plan_base_current['blocks'])
    expected_steps = []
    for step in plan['steps']:
        before = deepcopy(blocks)
        blocks.append(deepcopy(step['after']))
        expected_steps.append({'step_id': step['step_id'], 'before_blocks': before,
                               'after_blocks': deepcopy(blocks)})
    # No guessed future current_revision: expected geometry is not observation.
    payload = {
        'bundle_schema': 'a-b-d-planning-bundle-draft/0.1.1',
        'contract_status': 'DRAFT_NOT_FROZEN', 'execution_allowed': False,
        'current_provenance': 'B_CONFIRMED_D_RELAYED',
        'expected_state_kind': 'PLAN_EXPECTATION_NOT_OBSERVATION',
        'design': deepcopy(design), 'plan': deepcopy(plan),
        'plan_base_current': deepcopy(plan_base_current),
        'profile_snapshot': deepcopy(frame_profile),
        'profile_content_digest': profile_content_digest(frame_profile),
        'geometry': {
            'frame_id': 'assembly_board', 'length_unit': 'm',
            'placement_xy_reference': 'MINIMUM_OCCUPIED_STUD_CENTRE_ZERO_BASED',
            'z_origin': 'BOARD_STUD_TIP', 'layer_start': 1,
            'orientation_definition': '0_X_SIZE_FIRST_90_SWAPS_X_Y_SIZES',
            'pitch_m': g['pitch_mm']/1000, 'body_height_m': g['body_height_mm']/1000,
            'stud_height_m': g['stud_height_mm']/1000,
            'layer_increment_m': g['body_height_mm']/1000,
            'first_layer_body_bottom_z_m': -g['stud_height_mm']/1000,
            'nominal_body_sizes_m': {name: [w*g['pitch_mm']/1000, d*g['pitch_mm']/1000,
                                          g['body_height_mm']/1000]
                                     for name, (w, d) in BRICK_SIZES.items()},
            'body_size_basis': 'NOMINAL_ENVELOPE_FROM_STUD_PITCH_NOT_FACTORY_TOLERANCE',
            'socket_geometry_verified': False,
        },
        'expected_steps': expected_steps, 'final_expected_blocks': deepcopy(blocks),
        'limits': ['B_OWNS_CAMERA_CALIBRATION_MODEL_GENERATION_AND_ACTUAL_COMPARISON',
                   'B_OWNS_CURRENT_REVISION_EXPECTED_AND_COMPARISON',
                   'TCP_CALIBRATION_IS_NOT_A_MEASURED_BOARD_SURFACE_TRANSFORM',
                   'NO_SOCKET_FRICTION_OR_PHYSICAL_INTERLOCK_VERIFICATION'],
    }
    digest = content_digest(payload)
    return {'bundle_id': 'planning-bundle-'+digest[:20], 'bundle_digest': digest, **payload}


def validate_planning_bundle(bundle):
    """Check replay, references and digest before distribution; B and D receive this same payload."""
    g = bundle['geometry']
    ctx = {'finish_layers': False, 'geometry': {
        'pitch_mm': g['pitch_m']*1000, 'body_height_mm': g['body_height_m']*1000,
        'stud_height_mm': g['stud_height_m']*1000}}
    expected = build_planning_bundle(bundle['design'], bundle['plan'], bundle['plan_base_current'],
                                     ctx, bundle['profile_snapshot'])
    if expected != bundle:
        raise ValueError('Planning bundle differs from validated Plan replay or profile snapshot')
    return bundle
