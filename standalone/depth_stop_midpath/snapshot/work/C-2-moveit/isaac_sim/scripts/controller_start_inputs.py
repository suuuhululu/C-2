"""Pinned actual parameter observations and completed-HOLD command input.

No ROS/SIM calls. Missing observations stay missing. The runner supplies the
original GetParameters response, native receipt identity and readout evidence.
"""
from pathlib import Path
from copy import deepcopy
import xml.etree.ElementTree as ET
import numpy as np

from capture_sim_scene import command_counts
from prepare_cpu_model import file_hash
from plan_only import digest, JOINTS
from sim_utils import save

PARAMETER_NAMES = ['interpolation_method','interpolate_from_desired_state','open_loop_control',
    'allow_integration_in_goal_trajectories','command_interfaces','state_interfaces','joints',
    'allow_partial_joints_goal','constraints.stopped_velocity_tolerance'] + [
    'constraints.joint_'+str(i)+'.'+name for i in range(1,7) for name in ('goal','trajectory')]



def ref(p):return dict(path=str(Path(p).resolve()),sha256=file_hash(Path(p)))


def record_controller_parameters(folder,names,values,source_identity,libraries):
    folder=Path(folder)
    if folder.exists():raise ValueError('NEW_PARAMETER_OBSERVATION_REQUIRED')
    if set(names)!=set(PARAMETER_NAMES) or len(names)!=len(set(names)) or len(values)!=len(names):raise ValueError('COMPLETE_ACTIVE_PARAMETER_QUERY_REQUIRED')
    fields={1:'bool_value',2:'integer_value',3:'double_value',4:'string_value',
            5:'byte_array_value',6:'bool_array_value',7:'integer_array_value',8:'double_array_value',9:'string_array_value'}
    raw=[];parsed={};missing=[]
    for name,value in zip(names,values):
        kind=int(value.type)
        if kind not in fields:missing.append(name);raw.append(dict(name=name,type=kind,value=None));continue
        data=getattr(value,fields[kind]);data=list(data) if kind>=5 else data
        raw.append(dict(name=name,type=kind,value=data));node=parsed;keys=name.split('.')
        for key in keys[:-1]:node=node.setdefault(key,{})
        node[keys[-1]]=data
    folder.mkdir(parents=True);save(folder/'parameter_response.json',dict(scope='ACTUAL_GET_PARAMETERS_RESPONSE_RECEIPT',source_identity=source_identity,raw_values=raw,loaded_libraries=libraries))
    record=dict(scope='ACTIVE_CONTROLLER_PARAMETERS' if not missing else 'INCOMPLETE_CONTROLLER_PARAMETERS',values=parsed,missing=missing,source_refs=[ref(folder/'parameter_response.json')],source_identity=source_identity,loaded_libraries=libraries,observed_receipt_is_service_response_not_controller_sample=True)
    save(folder/'parameters.json',record)
    return ref(folder/'parameters.json')


def publish_completed_hold_pvt(folder,readout,bundle,parameters_ref,statuses,libraries):
    """Emit command PVT only for original zero-v/a completed HOLD evidence."""
    import json
    folder=Path(folder);missing=[];counts=command_counts(statuses)
    if any(counts.values()):missing.append('completed_empty_command_state')
    if parameters_ref is None:missing.append('actual_controller_parameters')
    if not libraries:missing.append('actual_loaded_JTC_library')
    row=readout['observation'];track=row.get('tracking',{});records=track.get('controller_states',[])
    if len(records)<2:missing.append('two_original_HOLD_reference_messages')
    if missing:
        save(folder/'controller_input_blocker.json',dict(status='WAIT_ACTUAL_CONTROLLER_START_INPUTS',missing=missing,observed_a_rad_s2=None));return dict(controller_input_blocker_ref=ref(folder/'controller_input_blocker.json'))
    if file_hash(Path(parameters_ref['path']))!=parameters_ref['sha256']:raise ValueError('PARAMETER_PARENT_CHANGED')
    params=json.loads(Path(parameters_ref['path']).read_text())
    if params['scope']!='ACTIVE_CONTROLLER_PARAMETERS':raise ValueError('COMPLETE_ACTIVE_PARAMETERS_REQUIRED')
    for key in ('session_id','clock_epoch','clock_basis'):
        if type(params['source_identity'][key]) is not type(readout[key]) or params['source_identity'][key]!=readout[key]:raise ValueError('ACTIVE_PARAMETER_SESSION_CHANGED')
    if params['source_identity']['source_stamp_s']>readout['source_stamp_s']:raise ValueError('FUTURE_PARAMETER_RECEIPT')
    p=params['values']
    if (p['joints']!=JOINTS or p['command_interfaces']!=['position'] or p['state_interfaces']!=['position','velocity'] or p['interpolation_method']!='splines' or p['allow_partial_joints_goal'] is not False or any(type(p[k]) is not bool for k in ('interpolate_from_desired_state','open_loop_control','allow_integration_in_goal_trajectories'))):raise ValueError('SUPPORTED_ACTIVE_JTC_CONFIGURATION_REQUIRED')
    old,latest=records[-2:];point=latest['reference'];fields=('positions','velocities','accelerations')
    if (latest['joint_names']!=JOINTS or old['joint_names']!=JOINTS or latest['header_ns']<=old['header_ns'] or
        any(len(point[k])!=6 or point[k]!=old['reference'][k] for k in fields) or
        any(x!=0 for x in point['velocities']+point['accelerations'])):raise ValueError('ORIGINAL_CONSTANT_HOLD_PVT_REQUIRED')
    if not np.array_equal(np.asarray(point['positions'],np.float32),np.asarray(track.get('drive_target_q_rad'),np.float32)):raise ValueError('CURRENT_DRIVE_NOT_HELD_REFERENCE')
    packages=[]
    for library in libraries:
        if file_hash(Path(library['path']))!=library['sha256']:raise ValueError('LOADED_JTC_BYTES_CHANGED')
        package=Path(library['path']).parent.parent/'share/joint_trajectory_controller/package.xml'
        if ET.fromstring(package.read_text()).findtext('version')!='4.42.1':raise ValueError('VERIFIED_JTC_VERSION_REQUIRED')
        packages.append(ref(package))
    identity={k:deepcopy(readout[k]) for k in ('session_id','clock_epoch','clock_basis','source_stamp_s','physics_step_index','readout_phase')}
    common={k:identity[k] for k in ('session_id','clock_epoch','clock_basis')}
    desired=dict(common,stamp_s=latest['header_ns']/1e9,q_rad=deepcopy(point['positions']),v_rad_s=deepcopy(point['velocities']),a_rad_s2=deepcopy(point['accelerations']))
    observed=dict(common,stamp_s=readout['source_stamp_s'],q_rad=deepcopy(row['q_rad']),v_rad_s=deepcopy(row['velocity_rad_s'][:6]),a_rad_s2=None,acceleration_source='NOT_EXPOSED_BY_STATE_INTERFACE')
    if desired['stamp_s']>observed['stamp_s']:raise ValueError('FUTURE_CONTROLLER_REFERENCE')
    selector='LAST_COMMANDED_STATE' if p['interpolate_from_desired_state'] or p['open_loop_control'] else 'HARDWARE_STATE_INTERFACES'
    model=dict(scope='CONTROLLER_INTERPOLATION_MODEL',controller_parameters_ref=parameters_ref,loaded_libraries=libraries,package_refs=packages,
        state_before_selector=selector,
        selected_initial_acceleration_rad_s2=([0.]*6 if selector=='HARDWARE_STATE_INTERFACES' else deepcopy(desired['a_rad_s2'])),
        selected_initial_acceleration_source=('JTC_MISSING_HARDWARE_A_INITIALIZATION_MODEL' if selector=='HARDWARE_STATE_INTERFACES' else 'ORIGINAL_VERIFIED_HELD_COMMAND_REFERENCE'),
        full_PVA_wire=True,missing_hardware_A_model_rad_s2=[0.]*6,model_rule='JTC4.42.1 set_point_before_trajectory_msg fills absent hardware A when first wire point contains A',
        state_before_current_input_model=dict(q_rad=deepcopy(observed['q_rad'] if selector=='HARDWARE_STATE_INTERFACES' else desired['q_rad']),v_rad_s=deepcopy(observed['v_rad_s'] if selector=='HARDWARE_STATE_INTERFACES' else desired['v_rad_s']),a_rad_s2=([0.]*6 if selector=='HARDWARE_STATE_INTERFACES' else deepcopy(desired['a_rad_s2'])),scope='CURRENT_INPUT_TO_CONTROLLER_ALGORITHM_NOT_FUTURE_ACCEPTANCE_MEASUREMENT'),
        model_is_observed_measurement=False,raw_observed_a_rad_s2=None,wire_first_point_time_zero_rule='Direct full-PVA first command point; no hidden positive-time prefix is assumed',native_execution_allowed=False)
    save(folder/'controller_init_model.json',model)
    save(folder/'original_controller_reference.json',dict(desired=deepcopy(desired),records=records[-2:],current_drive_targets=deepcopy(track),**counts))
    save(folder/'raw_observed_pvt.json',dict(observed,original_readout=bundle['readout'],raw_observation=deepcopy(row)))
    proof=dict(scope='VERIFIED_CONTROLLER_REFERENCE_OBSERVATION_ASSOCIATION',**common,
        desired_stamp_s=desired['stamp_s'],observed_stamp_s=observed['stamp_s'],
        desired_pvt_digest=digest({k:desired[k] for k in ('q_rad','v_rad_s','a_rad_s2')}),
        observed_pvt_digest=digest({k:observed[k] for k in ('q_rad','v_rad_s','a_rad_s2')}),
        observed_acceleration_nullable=True,method='CONFIRMED_CONTROLLER_HOLD_INTERVAL',reference_held_confirmed=True,
        valid_from_s=old['header_ns']/1e9,valid_until_s=observed['stamp_s'],
        evidence=dict(clock=bundle['readout'],controller_reference=ref(folder/'original_controller_reference.json'),observed_state=ref(folder/'raw_observed_pvt.json')),
        native_execution_allowed=False)
    save(folder/'controller_association.json',proof);desired['source_time_association']=ref(folder/'controller_association.json')
    initialization=dict(scope='VERIFIED_JTC_COMMAND_INITIALIZATION_MODEL',mode='EXPLICIT_TIME0_CURRENT_COMMAND_PVA',
        source_identity=identity,controller_parameters_ref=parameters_ref,
        command_pvt={k:deepcopy(desired[k]) for k in ('q_rad','v_rad_s','a_rad_s2')},
        acceleration_basis='ORIGINAL_CONTROLLER_COMMAND_FIELD',
        source_refs=[ref(folder/'original_controller_reference.json'),ref(folder/'controller_init_model.json'),*packages],
        loaded_controller_library_ref=libraries[0],state_before_model_ref=ref(folder/'controller_init_model.json'),
        raw_observed_acceleration_used=False,native_execution_allowed=False)
    save(folder/'command_initialization.json',initialization)
    value=dict(scope='CURRENT_COMPLETED_HOLD_COMMAND_AND_RAW_OBSERVATION',source_identity=identity,desired=desired,observed=observed,command_init=deepcopy(desired),command_reference_kind='VERIFIED_HELD_CONTROLLER_REFERENCE',controller_parameters_ref=parameters_ref,controller_model_ref=ref(folder/'controller_init_model.json'),command_initialization_ref=ref(folder/'command_initialization.json'),loaded_controller_libraries=libraries,native_execution_allowed=False)
    save(folder/'controller_pvt.json',value)
    return dict(controller_pvt_ref=ref(folder/'controller_pvt.json'),controller_model_ref=value['controller_model_ref'],controller_parameters_ref=parameters_ref,command_initialization_ref=value['command_initialization_ref'])
