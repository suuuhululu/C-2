"""Versioned, same-readout SIM inputs for a single fresh MoveIt request.

No simulator/ROS imports, commands, clock substitution, or tolerance policy.
The runner supplies original main-loop observations; existing input/FK checks
validate the saved scene/state pair before request generation.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import uuid

from capture_sim_scene import command_counts, verified_stop
from plan_only import digest
from prepare_cpu_model import read_model_bundle, file_hash
from prepare_gpu_scene import inspect_gpu_inputs
from sim_utils import save

PHASE = 'MAIN_LOOP_POST_TICK_RENDER_FLUSH_NO_PHYSICS_ADVANCE'
STATE_FIELDS = ('q_rad', 'grip_rad', 'tcp_pose', 'attachment_tcp_to_block',
                'world_objects', 'frame_alignment')


def physical_state(value):
    """Exact physical input identity; advancing source clocks remain distinct."""
    return {key: deepcopy(value[key]) for key in STATE_FIELDS}


def validate_readout(value):
    required = {'session_id', 'clock_epoch', 'clock_basis', 'source_stamp_s',
                'physics_step_index', 'readout_phase', 'before_stamp', 'after_stamp',
                'observation', 'observation_after', 'geometry_before', 'geometry_after', *STATE_FIELDS}
    if not required <= value.keys():
        raise ValueError('SETTLED_SOURCE_FIELDS_REQUIRED')
    if (not value['session_id'] or type(value['clock_epoch']) is not int or
            value['clock_epoch'] < 0 or value['clock_basis'] != 'SIM_TIME' or
            value['readout_phase'] != PHASE or type(value['physics_step_index']) is not int):
        raise ValueError('SETTLED_SOURCE_CLOCK_PHASE_REQUIRED')
    before, after = value['before_stamp'], value['after_stamp']
    fields = ('native_current_reference_time', 'native_simulation_time_s',
              'native_physics_step_index', 'world_time_s')
    if any(before[k] != after[k] for k in fields):
        raise ValueError('SETTLED_SOURCE_ADVANCED_DURING_READOUT')
    if (value['physics_step_index'] != after['native_physics_step_index'] or
            value['source_stamp_s'] != after['world_time_s']):
        raise ValueError('SETTLED_SOURCE_STAMP_MISMATCH')
    for geometry in (value['geometry_before'], value['geometry_after']):
        if (geometry['world_objects'] != value['world_objects'] or
                geometry['frame_alignment'] != value['frame_alignment']):
            raise ValueError('SETTLED_GEOMETRY_READOUT_MISMATCH')
    if value['geometry_before'] != value['geometry_after']:
        raise ValueError('SETTLED_GEOMETRY_CHANGED_DURING_READOUT')
    first, last = value['observation'], value['observation_after']
    for row in (first, last):
        if (row['time_s'] != value['source_stamp_s'] or
                row['q_rad'] != value['q_rad'] or row['grip_rad'] != value['grip_rad'] or
                row['tcp_pose'] != value['tcp_pose'] or
                row['attachment'] != value['attachment_tcp_to_block']):
            raise ValueError('SETTLED_SOURCE_COMPONENT_READOUT_MISMATCH')
        if row['contact_fingers'] != ['rg2_left_inner_finger', 'rg2_right_inner_finger']:
            raise ValueError('SETTLED_SOURCE_GRASP_REQUIRED')
    if first['contact_fingers'] != last['contact_fingers']:
        raise ValueError('SETTLED_SOURCE_CONTACT_CHANGED_DURING_READOUT')
    return physical_state(value)


def stop_history_for_readout(value, original_samples):
    """Select an original history view ending at this validated real readout.

    Never relabel or mutate cached samples. Equal-time different kinematics
    require explicit phase investigation rather than replacement or fake time.
    The caller preserves both raw inputs before invoking this selector.
    """
    from math import isfinite
    validate_readout(value)
    history = deepcopy(list(original_samples))
    times = [row['time_s'] for row in history]
    if (any(type(t) not in (int, float) or not isfinite(t) for t in times) or
            any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError('SETTLED_STOP_HISTORY_NOT_CHRONOLOGICAL')
    current = value['observation']
    previous_time = times[-1] if times else None
    if not history or current['time_s'] > previous_time:
        history.append(deepcopy(current))
        selection = 'APPEND_VALIDATED_CURRENT_READOUT'
    elif (current['time_s'] == previous_time and
            current['q_rad'] == history[-1]['q_rad'] and
            current['grip_rad'] == history[-1]['grip_rad']):
        selection = 'EXISTING_SAME_TIME_EXACT_Q_GRIP_NO_DUPLICATE'
    else:
        raise ValueError('SETTLED_STOP_HISTORY_CURRENT_TIME_OR_PHASE_MISMATCH')
    while history[-1]['time_s']-history[0]['time_s'] > 1:
        history.pop(0)
    return history, dict(selection=selection, previous_tail_time_s=previous_time,
                         selected_tail_time_s=history[-1]['time_s'],
                         current_source={k: deepcopy(value[k]) for k in
                             ('session_id', 'clock_epoch', 'clock_basis',
                              'source_stamp_s', 'physics_step_index', 'readout_phase')},
                         cached_sample_phase='ORIGINAL_HOOK_SAMPLE_NOT_RETAGGED',
                         raw_history_mutated=False, source_clock_relabelled=False)


def publish_settled_source(folder, value, *, stop_samples, statuses, seed,
                           motion, model_bundle, controls):
    """Save a new original scene/state pair, preserving the previous capture."""
    folder = Path(folder)
    if folder.exists():
        raise ValueError('SETTLED_SOURCE_OUTPUT_MUST_BE_NEW')
    validate_readout(value)
    counts = command_counts(statuses)
    if any(counts.values()):
        raise ValueError('SETTLED_SOURCE_COMMAND_ACTIVE')
    row = value['observation']
    stop = verified_stop(stop_samples, row['q_rad']+[row['grip_rad']])
    common = dict(schema_version='sim-plan-only-input-draft/0.1.0',
                  source_kind='ISAAC_SIM_SAVED_STATE', capture_id=str(uuid.uuid4()),
                  captured_at=datetime.now(timezone.utc).isoformat(),
                  execution_allowed=False, production_B_confirmed=False)
    bundle = read_model_bundle(model_bundle)
    folder.mkdir(parents=True)
    def ref(path):
        return dict(path=str(path.resolve()), sha256=file_hash(path))
    save(folder/'readout.json', value)
    binding = ref(folder/'readout.json')
    identity = {k: deepcopy(value[k]) for k in ('session_id', 'clock_epoch',
                'clock_basis', 'source_stamp_s', 'physics_step_index', 'readout_phase')}
    snapshot = dict(source_identity=identity,
                    field_sources={k: deepcopy(identity) for k in ('q_rad', 'grip_rad',
                        'tcp_pose', 'attachment', 'T_world_base', 'world_objects')},
                    observation=deepcopy(row), world_objects=deepcopy(value['world_objects']),
                    T_world_base=deepcopy(value['frame_alignment']['T_world_base']),
                    selected_slot_id=seed['reservation_binding']['slot_id'],
                    original_readout=binding, source_is_camera_event=False,
                    tcp_source_kind='OBSERVED_D_MAIN_READOUT', length_unit='m', joint_unit='rad',
                    transform_convention='COLUMN_VECTORS_LOCAL_TO_PARENT',
                    attachment_frames=dict(from_frame='BLOCK_BODY_CENTRE',to_frame='GripperDA_v4_tcp'),
                    model_manifest_ref=ref(Path(model_bundle)/'MODEL_MANIFEST.json'))
    save(folder/'snapshot.json', snapshot)
    scene = dict(common, current=deepcopy(seed['current']),
                 world_objects=deepcopy(value['world_objects']),
                 frame_alignment=deepcopy(value['frame_alignment']),
                 final_approach_policy=deepcopy(seed['final_approach_policy']),
                 geometry_scope='SIM_NOMINAL_GEOMETRY', model_scope='SIM_NOMINAL_MODEL',
                 seed_digest=digest(seed), settled_readout=binding, source_identity=deepcopy(identity),
                 **{k: deepcopy(seed[k]) for k in ('coordinate_provenance',
                    'd_gripper_reference', 'nominal_geometry_evidence') if k in seed})
    evidence = dict(scope='FINAL_DISCOVERY_SETTLED_MAIN_LOOP_READOUT',
                    readout=binding, stop_metrics=stop, position_observations=deepcopy(stop_samples),
                    native_action_statuses=deepcopy(statuses), **counts,
                    timeline_paused=False, virtual_attachment_used=False,
                    grasp_kind='DYNAMIC_CONTACT_GRASP', source_clock_relabelled=False)
    state = dict(common, a_context=deepcopy(controls['a_context']),
                 reservation_binding=deepcopy(controls['reservation_binding']),
                 q_rad=deepcopy(value['q_rad']), grip_rad=value['grip_rad'],
                 tcp_pose=deepcopy(value['tcp_pose']),
                 attachment_tcp_to_block=deepcopy(value['attachment_tcp_to_block']),
                 attachment_scope='SIM_NOMINAL_ATTACHMENT', holding_confirmed=True,
                 stopped_verified=True, **counts,
                 raw_joint_velocity_rad_s=deepcopy(row['velocity_rad_s']),
                 observation_evidence=evidence, settled_readout=binding, source_identity=deepcopy(identity))
    save(folder/'scene.json', scene); save(folder/'post_grasp_state.json', state)
    request, checks = inspect_gpu_inputs(motion, folder/'scene.json',
                                         folder/'post_grasp_state.json', model_bundle)
    save(folder/'input_checks.json', checks)
    result = dict(scope='SAME_READOUT_SETTLED_SOURCE_NOT_EXECUTION_APPROVAL',
                  session_id=value['session_id'], clock_epoch=value['clock_epoch'],
                  clock_basis=value['clock_basis'], source_stamp_s=value['source_stamp_s'],
                  physics_step_index=value['physics_step_index'], readout_phase=value['readout_phase'],
                  units='m_rad_s', matrix_convention='COLUMN_VECTORS_LOCAL_TO_PARENT',
                  attachment_from='BLOCK_BODY_CENTRE', attachment_to='GripperDA_v4_tcp',
                  readout=binding, scene=ref(folder/'scene.json'),
                  state=ref(folder/'post_grasp_state.json'), input_checks=ref(folder/'input_checks.json'),
                  model_manifest_sha256=bundle['manifest_sha256'],
                  original_goal=request['goal'], source_state_digest=digest(physical_state(value)),
                  execution_allowed=False, hardware_execution_allowed=False)
    save(folder/'source.json', result)
    return dict(result, source_ref=ref(folder/'source.json'),
                snapshot_ref=ref(folder/'snapshot.json'),
                scene_ref=ref(folder/'scene.json'), state_ref=ref(folder/'post_grasp_state.json'))


def review_current_source(original, current):
    """Same-readout integrity is exact; cross-tick changes are REPORT_ONLY.

    The D boundary still must validate STOP/holding, current geometry and the
    complete controller-start connection plus original suffix before send.
    """
    from sim_utils import error, rigid
    validate_readout(current)
    if (current['session_id'] != original['session_id'] or
            current['clock_epoch'] != original['clock_epoch'] or
            current['clock_basis'] != original['clock_basis'] or
            current['readout_phase'] != original['readout_phase'] or
            current['source_stamp_s'] < original['source_stamp_s'] or
            current['physics_step_index'] < original['physics_step_index']):
        raise ValueError('SETTLED_PLAN_SOURCE_IDENTITY_OR_CLOCK_CHANGED')
    before = {x['id']: x for x in original['world_objects']}
    after = {x['id']: x for x in current['world_objects']}
    return dict(scope='CROSS_TICK_OBSERVATION_CHANGE_REPORT_NOT_EXECUTION_APPROVAL',
                q_delta_rad=[b-a for a,b in zip(original['q_rad'],current['q_rad'])],
                grip_delta_rad=current['grip_rad']-original['grip_rad'],
                attachment_error_m_rad=error(rigid(original['attachment_tcp_to_block']),
                                             rigid(current['attachment_tcp_to_block'])),
                changed_world_ids=sorted(k for k in before.keys() | after.keys()
                                         if before.get(k) != after.get(k)),
                official_tolerance=None, observation='REPORT_ONLY',
                current_geometry_and_complete_start_connection_FCL_required=True,
                native_execution_allowed=False)
