"""Read-only controller start evidence; no PVT fabrication or execution gate."""
from copy import deepcopy
from pathlib import Path
import numpy as np

from prepare_cpu_model import file_hash
from plan_only import vector

JOINTS = ['joint_'+str(i) for i in range(1, 7)]


def controller_start_observation(readout, config, config_ref, loaded_libraries):
    row = readout['observation'];tracking = row.get('tracking', {})
    identity = {k: deepcopy(readout[k]) for k in ('session_id', 'clock_epoch',
                'clock_basis', 'source_stamp_s', 'physics_step_index', 'readout_phase')}
    arm = config['/sim/m0609/arm_controller']['ros__parameters']
    raw = dict(source_identity=identity, q_rad=vector(row['q_rad'], 6),
               v_rad_s=vector(row['velocity_rad_s'][:6], 6), a_rad_s2=None,
               acceleration_source='NOT_EXPOSED_BY_CONFIGURED_STATE_INTERFACES',
               state_interfaces=deepcopy(arm['state_interfaces']),
               raw_step_readout=deepcopy(row.get('step_readout')))
    records = deepcopy(tracking.get('controller_states', []));latest = records[-1] if records else None
    desired = None;missing = []
    if latest is not None and set(latest['joint_names']) == set(JOINTS):
        ix = [latest['joint_names'].index(name) for name in JOINTS]
        point = latest['reference']
        desired = dict(header_ns=latest['header_ns'],
                       received_world_time_s=latest['received_world_time_s'],
                       source='ORIGINAL_ROS_CONTROLLER_REFERENCE_MESSAGE',
                       q_rad=None, v_rad_s=None, a_rad_s2=None)
        for source, target in (('positions', 'q_rad'), ('velocities', 'v_rad_s'),
                               ('accelerations', 'a_rad_s2')):
            if len(point[source]) == len(JOINTS):desired[target] = vector([point[source][i] for i in ix], 6)
            else:missing.append('controller_reference_'+target)
    else:missing.append('controller_reference_message')
    drive = dict(source_identity=identity,
                 q_rad=deepcopy(tracking.get('drive_target_q_rad')),
                 v_rad_s=deepcopy(tracking.get('drive_target_v_rad_s')),
                 a_rad_s2=None, acceleration_source='NO_PHYSX_DRIVE_ACCELERATION_TARGET_READOUT')
    q_match = None
    if desired is not None and desired['q_rad'] is not None and drive['q_rad'] is not None:
        q_match = bool(np.array_equal(np.asarray(desired['q_rad'], np.float32),
                                      np.asarray(drive['q_rad'], np.float32)))
    # A matching position target and an old reference are useful evidence, but
    # do not prove all current controller P/V/A at the same update phase.
    missing.extend(['verified_current_controller_update_desired_PVT_source_association',
                    'controller_runtime_interpolate_from_desired_state_and_open_loop_parameters'])
    return dict(scope='RAW_DESIRED_OBSERVED_SOURCE_EVIDENCE_NOT_INITIAL_CONNECTION_APPROVAL',
                status='WAIT_VERIFIED_CONTROLLER_START_PVT_AND_RUNTIME_PARAMETERS',
                source_identity=identity, observed=raw, controller_reference=desired,
                original_controller_messages=records,
                controller_state_same_update=(dict(header_ns=latest['header_ns'],
                    received_world_time_s=latest['received_world_time_s'],
                    reference=deepcopy(latest['reference']),feedback=deepcopy(latest['feedback']),
                    output=deepcopy(latest['output']),
                    phase='JTC_PUBLISH_STATE_SAME_UPDATE_REFERENCE_FEEDBACK_OUTPUT',
                    reference_semantics='STATE_DESIRED_AT_TRAJ_TIME_NOT_COMMAND_NEXT',
                    command_next_semantics='JTC_SAMPLES_AT_TRAJ_TIME_PLUS_UPDATE_PERIOD',
                    planning_readout_stamp_not_substituted=True) if latest is not None else None),
                current_drive_targets=drive,
                reference_q_matches_current_drive_float32=q_match,
                reference_header_relabelled=False, observed_used_as_desired=False,
                missing=missing, controller_config=config_ref,
                configured_command_interfaces=deepcopy(arm['command_interfaces']),
                configured_state_interfaces=deepcopy(arm['state_interfaces']),
                runtime_parameters=None, loaded_controller_libraries=loaded_libraries,
                native_execution_allowed=False, hardware_execution_allowed=False,
                official_tolerance=None, observation='REPORT_ONLY')


def loaded_controller_libraries():
    """Read only this process' actual maps; never infer native12 library use."""
    paths = set()
    for line in Path('/proc/self/maps').read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and Path(fields[5]).name == 'libjoint_trajectory_controller.so':paths.add(fields[5])
    return [dict(path=str(Path(p).resolve()), sha256=file_hash(Path(p))) for p in sorted(paths)]
