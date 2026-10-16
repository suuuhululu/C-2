"""Receive the bound plan-only draft in isolated Isaac; never connect REAL D.

One complete native FJT goal, followed by observed hold/stop and a pending
D contact handoff. No automatic pickup, open, insertion, retry or Current edit.
"""
from collections import deque
from copy import deepcopy
from pathlib import Path
import json
import os
import subprocess
import time

import numpy as np
import yaml

from capture_sim_scene import command_counts, contact_state, verified_stop
from plan_only import digest, receive_files, vector
from sim_utils import error, pose_matrix, rigid, save

FINGERS = ['rg2_left_inner_finger', 'rg2_right_inner_finger']


def verified_cumotion_stop_test(status, injection, guard_hits):
    """Cancellation ACK alone is insufficient: require native result and feedback."""
    return (status.get('error')=='STOP_REQUESTED' and status.get('transport_goal_sent') is True and
        status.get('stop_verified') is True and status.get('holding_confirmed') is True and not guard_hits and
        injection.get('active_command_count',0)>0 and
        status.get('native_command_counts')==dict(active_command_count=0,pending_command_count=0) and
        status.get('native_action_result',{}).get('status')==5 and
        any(c.get('done') is True and c.get('return_code')==0 and
            (c.get('goals_canceling_count') or 0)>0 for c in status.get('cancellation',[])))


def physical_contact(report):
    # PhysX reports contact-offset candidates across a positive, force-free
    # gap. Keep them in the trace; they are not geometry penetration/touch.
    near, loaded = contact_state(report)
    return near and (loaded or report['minimum_separation_m']<=0)


def check_live(packet, latest, observation, stop_requested=False, contact_grace_s=0):
    """Same binding on every runtime observation; STOP has no auto-resume."""
    if stop_requested:
        raise ValueError('STOP_REQUESTED')
    if (packet['binding'] != latest or
            any(type(value) is not type(latest.get(key)) for key,value in packet['binding'].items())):
        raise ValueError('STALE_TRANSPORT_CONTEXT')
    if not 0<=contact_grace_s<=.02: raise ValueError('Invalid dynamic contact observation window')
    if observation['contact_fingers'] != FINGERS:
        seen=observation.get('contact_last_loaded_s',{})
        now=vector([observation.get('time_s')],1)[0] if contact_grace_s else 0
        if (not contact_grace_s or set(seen)!=set(FINGERS) or
                any(not 0<=now-vector([seen[name]],1)[0]<=contact_grace_s for name in FINGERS)):
            raise ValueError('GRASP_CONTACT_LOST')
    vector(observation['q_rad'], 6)
    vector([observation['grip_rad']], 1)
    drift = error(rigid(packet['attachment']), rigid(observation['attachment']))
    if drift[0] > .005 or drift[1] > .15:
        raise ValueError('GRASP_ATTACHMENT_DRIFT')
    return drift


def check_start(packet, request, observation, statuses, stop_samples,
                latest, *, authorized=False, domain=None, discovery=None, interpolation=None,
                transport_engine='moveit',depth_owner_test=False,verified_initial_connection=False):
    from cumotion_timing import ENGINE, TIMING_ENGINE
    if transport_engine=='moveit':
        valid_route=(domain=='93' or (domain=='194' and depth_owner_test is True)) and packet['status']=='D_RECEIVE_ONLY_DRAFT_NOT_CONNECTED'
    elif transport_engine=='cumotion':
        valid_route=(domain=='194' and packet['status']=='D_RECEIVED_CUMOTION_CALCULATION_ONLY' and
            packet.get('calculation_engine')==ENGINE and packet.get('timing_engine')==TIMING_ENGINE and
            packet.get('d_receipt_scope')=='CALCULATION_ONLY_NOT_EXECUTION' and
            packet.get('execution_issued') is False and
            0<=packet.get('verification',{}).get('final_quintic',{}).get('max_jerk_rad_s3',float('inf'))<=5.00001)
    else:valid_route=False
    if (authorized is not True or not valid_route or discovery != 'LOCALHOST' or
            interpolation != 'splines' or packet['confirmation_kind'] != 'SIM_TEST_STATE' or
            packet['simulation_provenance']['source_kind'] != 'ISAAC_SIM_SAVED_STATE' or
            packet['production_B_confirmed'] is not False or
            packet['execution_allowed'] is not False or packet['hardware_execution_allowed'] is not False or
            packet['trajectory_interpolation'] != 'QUINTIC' or
            packet['terminal_gripper_policy'] != 'HOLD_NO_AUTOMATIC_OPEN' or
            packet['handoff_to'] != 'D_CONTACT' or packet['assembly_completed'] is not False or
            packet['trajectory_digest'] != digest(packet['trajectory'])):
        raise ValueError('ISOLATED_SIM_TRANSPORT_AUTHORIZATION_REQUIRED')
    counts = command_counts(statuses)
    if any(counts.values()):
        raise ValueError('NATIVE_COMMAND_ALREADY_PENDING_OR_ACTIVE')
    check_live(dict(packet, attachment=request['attachment']), latest, observation)
    if not verified_initial_connection:
        start = request['planning_snapshot']
        if (max(abs(np.array(vector(observation['q_rad'], 6))-start['q_rad'])) > .002 or
                abs(observation['grip_rad']-start['grip_rad']) > .002):
            raise ValueError('ACTUAL_JOINT_START_DRIFT')
        pe, re = error(pose_matrix(packet['start_tcp_pose']), pose_matrix(observation['tcp_pose']))
        if pe > .0008 or re > .005:
            raise ValueError('ACTUAL_TCP_START_DRIFT')
        verified_stop(stop_samples, vector(observation['q_rad'],6)+[observation['grip_rad']])


def check_world(request, objects):
    before={o['id']:o for o in request['planning_snapshot']['world_objects']}
    after={o['id']:o for o in objects}
    if before.keys()!=after.keys(): raise ValueError('TRANSPORT_WORLD_INVENTORY_CHANGED')
    selected=request['planning_snapshot']['selected_slot_id']
    settling={}
    for key,obj in after.items():
        if obj['size_m']!=before[key]['size_m'] or obj['studs']!=before[key]['studs']:
            raise ValueError('TRANSPORT_WORLD_SHAPE_CHANGED')
        if key==selected: continue
        old=pose_matrix(before[key]['world_pose']);new=pose_matrix(obj['world_pose'])
        if before[key].get('role')=='SUPPLY_BLOCK':
            # Waiting supplies are dynamic bodies resting on the board. Bound
            # their settling within the 2mm planning envelope, never delete them.
            drift=error(old,new);settling[key]=drift
            if drift[0]>.0005 or drift[1]>.005:
                raise ValueError('TRANSPORT_WAITING_SUPPLY_MOVED: '+key+' '+str(drift))
        elif not np.allclose(old,new,atol=1e-8,rtol=0):
            raise ValueError('TRANSPORT_STATIC_WORLD_POSE_CHANGED: '+key)
    return settling


def native_goal(packet):
    """Preserve every value; only convert seconds to the ROS duration wire form."""
    from control_msgs.action import FollowJointTrajectory
    from trajectory_msgs.msg import JointTrajectoryPoint
    goal = FollowJointTrajectory.Goal()
    goal.trajectory.joint_names = packet['trajectory']['joint_names']
    for p in packet['trajectory']['points']:
        point = JointTrajectoryPoint(positions=p['positions_rad'], velocities=p['velocities_rad_s'],
                                     accelerations=p['accelerations_rad_s2'])
        ns = round(p['time_from_start_s']*1_000_000_000)
        point.time_from_start.sec, point.time_from_start.nanosec = divmod(ns, 1_000_000_000)
        goal.trajectory.points.append(point)
    return goal


def validate_fresh_moveit_route(args, domain, discovery):
    """Shared preflight for the actual fresh route; no native execution permission."""
    if (getattr(args, 'fresh_moveit_baseline', None) is not True or domain != '194' or
            discovery != 'LOCALHOST' or getattr(args, 'transport_engine', None) != 'moveit' or
            not getattr(args, 'sim_transport', False) or getattr(args, 'depth_owner_test', None) is not True or
            getattr(args, 'prepared_transport', None) is not None or getattr(args, 'live_transport', None) is not None):
        raise ValueError('FRESH_MOVEIT_ONLY_ISOLATED_UNPREPARED_ROUTE')


def settled_fresh_source(bundle,now_s,*,expected=None,request=None):
    """Pinned same-phase MI input; no observation, retagging, FK or commands here."""
    from hashlib import sha256
    def read(ref):
        raw=Path(ref['path']).read_bytes()
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('FRESH_SOURCE_SHA_CHANGED')
        return json.loads(raw)
    try:
        snapshot=read(bundle['snapshot_ref']);scene=read(bundle['scene_ref']);state=read(bundle['state_ref'])
        source=snapshot['source_identity']
        if (not isinstance(source['session_id'],str) or not source['session_id'] or source['clock_basis']!='SIM_TIME' or
                type(source['clock_epoch']) is not int or type(source['physics_step_index']) is not int or
                source['clock_epoch']<0 or source['physics_step_index']<0 or
                not isinstance(source['readout_phase'],str) or not source['readout_phase']):
            raise ValueError('FRESH_SOURCE_PHASE_REQUIRED')
        if type(source['source_stamp_s']) not in (int,float):raise ValueError('FRESH_SOURCE_CLOCK_REQUIRED')
        stamp=vector([source['source_stamp_s']],1)[0];now=vector([now_s],1)[0]
        if not 0<=now-stamp<=.12:raise ValueError('FRESH_SOURCE_STALE_OR_FUTURE')
        names=('q_rad','grip_rad','tcp_pose','attachment','T_world_base','world_objects')
        for name in names:
            if digest(snapshot['field_sources'][name])!=digest(source):raise ValueError('FRESH_SOURCE_MIXED_PHASE:'+name)
        if any(digest(doc['source_identity'])!=digest(source) for doc in (scene,state)):
            raise ValueError('FRESH_SCENE_STATE_SOURCE_CHANGED')
        if (snapshot['tcp_source_kind']!='OBSERVED_D_MAIN_READOUT' or snapshot['length_unit']!='m' or
                snapshot['joint_unit']!='rad' or snapshot['transform_convention']!='COLUMN_VECTORS_LOCAL_TO_PARENT' or
                snapshot['attachment_frames']!=dict(from_frame='BLOCK_BODY_CENTRE',to_frame='GripperDA_v4_tcp')):
            raise ValueError('FRESH_OBSERVED_TRANSFORM_CONVENTION_REQUIRED')
        manifest_ref=snapshot['model_manifest_ref'];manifest_raw=Path(manifest_ref['path']).read_bytes()
        if sha256(manifest_raw).hexdigest()!=manifest_ref['sha256']:raise ValueError('FRESH_MODEL_MANIFEST_CHANGED')
        observation=snapshot['observation']
        if observation['time_s']!=source['source_stamp_s']:raise ValueError('FRESH_OBSERVATION_TIME_CHANGED')
        if observation['tcp_pose'].get('frame_id')!='base_link':raise ValueError('FRESH_OBSERVED_TCP_FRAME_REQUIRED')
        vector(observation['q_rad'],6);vector([observation['grip_rad']],1)
        rigid(snapshot['T_world_base']);rigid(observation['attachment']);pose_matrix(observation['tcp_pose'])
        values=dict(q_rad=observation['q_rad'],grip_rad=observation['grip_rad'],tcp_pose=observation['tcp_pose'],
            attachment_tcp_to_block=observation['attachment'],T_world_base=snapshot['T_world_base'],world_objects=snapshot['world_objects'],model_manifest_ref=manifest_ref,a_context=state['a_context'],reservation_binding=state['reservation_binding'],current=scene['current'],final_approach_policy=scene['final_approach_policy'])
        if (any(state[k]!=values[k] for k in ('q_rad','grip_rad','tcp_pose','attachment_tcp_to_block')) or
                scene['world_objects']!=values['world_objects'] or scene['frame_alignment']['T_world_base']!=values['T_world_base']):
            raise ValueError('FRESH_SAVED_VALUES_CHANGED')
        if (state['holding_confirmed'] is not True or state['stopped_verified'] is not True or
                state['active_command_count']!=0 or state['pending_command_count']!=0 or observation['contact_fingers']!=FINGERS):
            raise ValueError('FRESH_STOPPED_HOLD_REQUIRED')
        if snapshot['selected_slot_id']!=state['reservation_binding']['slot_id']:
            raise ValueError('FRESH_SELECTED_SLOT_CHANGED')
        if not {'SUPPLY_BOARD','ASSEMBLY_BOARD','HELD_BLOCK'}<={o['role'] for o in values['world_objects']}:
            raise ValueError('FRESH_COMPLETE_GEOMETRY_REQUIRED')
        if expected is not None:
            old=expected['source_identity']
            if any(type(source[k]) is not type(old[k]) or source[k]!=old[k] for k in ('session_id','clock_basis','clock_epoch','readout_phase')):
                raise ValueError('FRESH_CURRENT_SOURCE_CHANGED')
            if source['source_stamp_s']<old['source_stamp_s'] or source['physics_step_index']<old['physics_step_index']:
                raise ValueError('FRESH_SOURCE_ORDER_REVERSED')
            original=expected['values']
            if snapshot['selected_slot_id']!=expected['selected_slot_id'] or any(values[k]!=original[k] for k in ('model_manifest_ref','a_context','reservation_binding','current','final_approach_policy')):
                raise ValueError('FRESH_MODEL_CONTEXT_OR_GOAL_CHANGED')
            def shapes(objects):
                return sorted([{k:o.get(k) for k in ('id','role','size_m','studs','block','prim_path','coordinate_kind')} for o in objects],key=lambda o:o['id'])
            if shapes(values['world_objects'])!=shapes(original['world_objects']):raise ValueError('FRESH_WORLD_SHAPE_CHANGED')
            check_world(dict(planning_snapshot=dict(world_objects=original['world_objects'],selected_slot_id=expected['selected_slot_id'])),values['world_objects'])
            check_live(dict(binding={},attachment=original['attachment_tcp_to_block']),{},observation)
        if request is not None:
            plan=request['planning_snapshot']
            if (any(plan[k]!=values[k] for k in ('q_rad','grip_rad','tcp_pose','world_objects')) or
                    request['attachment']!=values['attachment_tcp_to_block'] or plan['selected_slot_id']!=snapshot['selected_slot_id'] or
                    request['simulation_provenance']['files']!=dict(scene=bundle['scene_ref'],state=bundle['state_ref']) or
                    request['model_bundle']['manifest_sha256']!=manifest_ref['sha256']):
                raise ValueError('FRESH_REQUEST_SOURCE_CHANGED')
        return dict(source_identity=deepcopy(source),values=deepcopy(values),observation=deepcopy(observation),selected_slot_id=snapshot['selected_slot_id'],refs=deepcopy(bundle))
    except (KeyError,TypeError,OSError) as exc:
        raise ValueError('FRESH_COHERENT_SOURCE_REQUIRED:'+str(exc)) from exc


def sim_command_limits(command_profile='conservative'):
    from moveit_command_timing import moveit_command_limits
    return moveit_command_limits(command_profile)


def deterministic_connection_duration(start,end,lower,upper,*,command_profile='conservative'):
    """One certified ns choice via exact-rational Bernstein control bounds.

    Triangle budgets are a conservative mathematical proof, not new limits.
    Nonzero endpoint v/a create both lower AND upper duration bounds; increasing
    duration is not presumed safe. No retry/search over command-limit failures.
    """
    from fractions import Fraction as F
    from math import isfinite
    limits=[sim_command_limits(command_profile)[k] for k in ('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')]
    if any(x<=0 for x in limits):raise ValueError('POSITIVE_CONNECTION_COMMAND_LIMITS_REQUIRED')
    caps=tuple(F(str(x)) for x in limits);minimum=1;maximum=None;constraints=[]
    def root_floor(n,k):
        if n<0:raise ValueError('NONNEGATIVE_INTEGER_ROOT_REQUIRED')
        lo=0;hi=1<<((n.bit_length()+k-1)//k)
        while lo<hi:
            mid=(lo+hi+1)//2
            if mid**k<=n:lo=mid
            else:hi=mid-1
        return lo
    def integer_bound(value,power,ceil):
        if ceil:
            target=(value.numerator+value.denominator-1)//value.denominator
            r=root_floor(target,power);return r if r**power==target else r+1
        return root_floor(value.numerator//value.denominator,power)
    def add(a,b,scale=1):
        out=dict(a)
        for k,v in b.items():out[k]=out.get(k,F(0))+scale*v
        return {k:v for k,v in out.items() if v}
    def bound(poly,limit,kind,joint,index):
        nonlocal minimum,maximum
        margin=limit-abs(poly.get(0,F(0)));terms=[(k,abs(v)) for k,v in poly.items() if k and v]
        if margin<0 or terms and margin<=0:raise ValueError('NO_CERTIFIABLE_CONNECTION_DURATION:'+kind)
        if not terms:return
        budget=margin/len(terms)
        for power,value in terms:
            if power<0:minimum=max(minimum,integer_bound(value/budget*10**(-9*power),-power,True))
            else:
                top=integer_bound(budget/value*10**(9*power),power,False)
                maximum=top if maximum is None else min(maximum,top)
        constraints.append(dict(kind=kind,joint=joint,control=index,margin=str(margin),nonconstant_terms=len(terms)))
    controls=[]
    for j in range(6):
        q0,v0,a0=[F(float(start[k][j])) for k in ('positions_rad','velocities_rad_s','accelerations_rad_s2')]
        q1,v1,a1=[F(float(end[k][j])) for k in ('positions_rad','velocities_rad_s','accelerations_rad_s2')]
        bezier=[{0:q0},{0:q0,1:v0/5},{0:q0,1:2*v0/5,2:a0/20},{0:q1,1:-2*v1/5,2:a1/20},{0:q1,1:-v1/5},{0:q1}]
        for i,p in enumerate(bezier):
            base=p.get(0,F(0));margin=min(base-F(float(lower[j])),F(float(upper[j]))-base)
            bound({0:F(0),**{k:v for k,v in p.items() if k}},margin,'position',j,i)
        levels=[bezier];current=bezier
        for order,limit in enumerate(caps,1):
            current=[{k-1:(6-order)*v for k,v in add(b,a,-1).items()} for a,b in zip(current[:-1],current[1:])]
            levels.append(current)
            for i,p in enumerate(current):bound(p,limit,('velocity','acceleration','jerk')[order-1],j,i)
        controls.append(levels)
    if maximum is not None and minimum>maximum:raise ValueError('NO_COMMON_CERTIFIED_CONNECTION_DURATION')
    h=F(minimum,10**9)
    for j,levels in enumerate(controls):
        for order,level in enumerate(levels):
            for p in level:
                value=sum((v*h**k for k,v in p.items()),F(0))
                if order==0:
                    if not F(float(lower[j]))<=value<=F(float(upper[j])):raise ValueError('CONNECTION_POSITION_CERTIFICATE_FAILED')
                elif abs(value)>caps[order-1]:raise ValueError('CONNECTION_DERIVATIVE_CERTIFICATE_FAILED')
    duration=minimum/1e9
    if not isfinite(duration) or round(duration*1e9)!=minimum:raise ValueError('CONNECTION_NANOSECOND_REPRESENTATION_FAILED')
    return duration,dict(method='EXACT_RATIONAL_BERNSTEIN_TRIANGLE_BUDGET_SINGLE_NS_CHOICE',selected_duration_ns=minimum,feasible_min_ns=minimum,feasible_max_ns=maximum,command_caps=[float(c) for c in caps],constraint_count=len(constraints),constraint_summary=constraints,duration_limit_retry_count=0,conservative_certificate=True)


def connection_command_context(current):
    """Raw A may be absent; full command/init PVA needs its OWN provenance."""
    from bounded_sim_evidence import pinned_json
    from prepare_cpu_model import file_hash
    try:
        pvt=pinned_json(current['refs']['controller_pvt_ref']);source=current['source_identity']
        if digest(pvt['source_identity'])!=digest(source):raise ValueError('FRESH_PVT_READOUT_SOURCE_CHANGED')
        command=pvt['desired'];observed=deepcopy(pvt['observed'])
        observed['a_rad_s2']=observed.get('a_rad_s2')  # Absent field is unknown/null, never a zero measurement.
        for value in (command,observed):
            for key in ('session_id','clock_epoch','clock_basis'):
                if type(value[key]) is not type(source[key]) or value[key]!=source[key]:raise ValueError('FRESH_PVT_IDENTITY_CHANGED')
            vector(value['q_rad'],6);vector(value['v_rad_s'],6)
        vector(command['a_rad_s2'],6)
        if observed.get('a_rad_s2') is not None:vector(observed['a_rad_s2'],6)
        if observed['stamp_s']!=source['source_stamp_s'] or observed['q_rad']!=current['observation']['q_rad']:
            raise ValueError('FRESH_RAW_OBSERVATION_SOURCE_CHANGED')
        if 'velocity_rad_s' in current['observation'] and observed['v_rad_s']!=current['observation']['velocity_rad_s'][:6]:raise ValueError('FRESH_RAW_OBSERVED_V_CHANGED')
        init=pinned_json(pvt['command_initialization_ref'])
        if (init['scope']!='VERIFIED_JTC_COMMAND_INITIALIZATION_MODEL' or init['mode']!='EXPLICIT_TIME0_CURRENT_COMMAND_PVA' or
                digest(init['source_identity'])!=digest(source) or init['controller_parameters_ref']!=pvt['controller_parameters_ref']):
            raise ValueError('CURRENT_COMMAND_INITIALIZATION_MODEL_REQUIRED')
        for key in ('q_rad','v_rad_s','a_rad_s2'):
            if init['command_pvt'][key]!=command[key]:raise ValueError('COMMAND_INIT_MODEL_PVT_CHANGED')
        if init['acceleration_basis'] not in ('ORIGINAL_CONTROLLER_COMMAND_FIELD','CONTROLLER_INTERPOLATION_MODEL'):
            raise ValueError('COMMAND_A_SOURCE_REQUIRED')
        if not init['source_refs']:raise ValueError('CONTROLLER_MODEL_SOURCE_REFS_REQUIRED')
        for r in init['source_refs']+[init['loaded_controller_library_ref']]:
            if file_hash(r['path'])!=r['sha256']:raise ValueError('CONTROLLER_INIT_PARENT_CHANGED')
        if init['loaded_controller_library_ref'] not in pvt['loaded_controller_libraries']:raise ValueError('ACTUAL_LOADED_CONTROLLER_REQUIRED')
        if init['acceleration_basis']=='CONTROLLER_INTERPOLATION_MODEL':
            derivation=pinned_json(init['derivation_ref'])
            if (derivation['mode']!=init['mode'] or derivation['command_a_rad_s2']!=command['a_rad_s2'] or
                    derivation['raw_observed_acceleration_used'] is not False):raise ValueError('COMMAND_A_MODEL_DERIVATION_REQUIRED')
        # Existing association protocol, with null A hashed/preserved rather than
        # passed through CU's mandatory-vector observed-A checker.
        proof=pinned_json(command['source_time_association'])
        if proof['scope']!='VERIFIED_CONTROLLER_REFERENCE_OBSERVATION_ASSOCIATION':raise ValueError('VERIFIED_PVT_ASSOCIATION_REQUIRED')
        for key in ('session_id','clock_basis','clock_epoch'):
            if type(proof[key]) is not type(source[key]) or proof[key]!=source[key]:raise ValueError('PVT_ASSOCIATION_IDENTITY_CHANGED')
        for role,value in (('desired',command),('observed',observed)):
            if proof[role+'_stamp_s']!=value['stamp_s'] or proof[role+'_pvt_digest']!=digest({k:value[k] for k in ('q_rad','v_rad_s','a_rad_s2')}):raise ValueError('PVT_ASSOCIATION_VALUES_CHANGED')
        times=vector([command['stamp_s'],observed['stamp_s'],source['source_stamp_s'],proof['valid_from_s'],proof['valid_until_s']],5)
        if max(times[:3])>source['source_stamp_s'] or not times[3]<=min(times[:3])<=max(times[:3])<=times[4]:raise ValueError('PVT_ASSOCIATION_CLOCK_INVALID')
        if proof['method']=='SAME_SOURCE_TICK':
            if any(type(proof[k]) is not int or proof[k]!=source['physics_step_index'] for k in ('source_step','desired_source_step','observed_source_step')):raise ValueError('PVT_ASSOCIATION_STEP_CHANGED')
        elif proof['method']!='CONFIRMED_CONTROLLER_HOLD_INTERVAL' or proof.get('reference_held_confirmed') is not True:raise ValueError('PVT_ASSOCIATION_METHOD_REQUIRED')
        evidence={k:pinned_json(r) for k,r in proof['evidence'].items()}
        for value,original in ((observed,evidence['observed_state']),(command,evidence['controller_reference']['desired'])):
            for key in ('session_id','clock_basis','clock_epoch','stamp_s','q_rad','v_rad_s','a_rad_s2'):
                if digest(value[key])!=digest(original.get(key) if key=='a_rad_s2' else original[key]):raise ValueError('ORIGINAL_PVT_PARENT_CHANGED:'+key)
        config=pinned_json(pvt['controller_parameters_ref']);params=config['values']
        if config['scope']!='ACTIVE_CONTROLLER_PARAMETERS' or not config['source_refs']:raise ValueError('ACTIVE_CONTROLLER_PARAMETER_EVIDENCE_REQUIRED')
        for r in config['source_refs']:pinned_json(r)
        from plan_only import JOINTS
        if (params['joints']!=JOINTS or params['interpolation_method']!='splines' or params['command_interfaces']!=['position'] or
                params['allow_partial_joints_goal'] is not False or
                any(type(params[k]) is not bool for k in ('interpolate_from_desired_state','open_loop_control','allow_integration_in_goal_trajectories'))):raise ValueError('UNSUPPORTED_CONTROLLER_INITIALIZATION')
        # goal tolerance remains native goal-completion policy, never silently
        # repurposed as an initial tracking-error threshold. D STOP/holding stays.
        report=dict(q_error_rad=max(abs(a-b) for a,b in zip(command['q_rad'],observed['q_rad'])),v_error_rad_s=max(abs(a-b) for a,b in zip(command['v_rad_s'],observed['v_rad_s'])),raw_observed_a_rad_s2=deepcopy(observed['a_rad_s2']),observed_A_criterion=None,tracking_criterion=None,official_status='OFFICIAL_NOT_DEFINED',check_mode='REPORT_ONLY',native_goal_constraints=deepcopy(params.get('constraints')))
        return dict(command=deepcopy(command),observed=deepcopy(observed),init_ref=pvt['command_initialization_ref'],pvt_ref=current['refs']['controller_pvt_ref'],params=params,association=deepcopy(proof),observation_report=report)
    except (KeyError,TypeError,OSError) as exc:raise ValueError('ACTUAL_COMMAND_INIT_AND_SOURCE_EVIDENCE_REQUIRED:'+str(exc)) from exc


def command_valid_timed_suffix(packet,request,artifacts,*,command_profile='conservative'):
    from bounded_sim_evidence import pinned_json
    from prepare_cpu_model import file_hash
    from plan_only import validate_trajectory
    try:
        limits=sim_command_limits(command_profile)
        receipt=pinned_json(artifacts['timing_receipt_ref']);suffix=validate_trajectory(pinned_json(artifacts['timed_trajectory_ref']))
        if receipt.get('command_profile','conservative')!=command_profile:raise ValueError('TIMED_SUFFIX_COMMAND_PROFILE_CHANGED')
        if (receipt['scope']!='MOVEIT_DERIVED_COMMAND_TIMING_NOT_EXECUTION_APPROVAL' or receipt['trajectory_ref']!=artifacts['timed_trajectory_ref'] or
                receipt['original_trajectory_digest']!=packet['trajectory_digest'] or receipt['trajectory_digest']!=digest(suffix) or
                receipt['original_goal']!=request['goal'] or receipt['method']!='SINGLE_INTEGER_UNIFORM_TIME_SCALE_FROM_ANALYTIC_EXTREMA'):
            raise ValueError('TIMED_MOVEIT_PARENT_OR_GOAL_CHANGED')
        for r in list(receipt['parents'].values())+[receipt['command_limit_source']]:
            if file_hash(r['path'])!=r['sha256']:raise ValueError('TIMED_MOVEIT_PARENT_SHA_CHANGED')
        req=yaml.load(Path(receipt['parents']['request']['path']).read_text(),Loader=yaml.CSafeLoader)
        raw_result=yaml.load(Path(receipt['parents']['result']['path']).read_text(),Loader=yaml.CSafeLoader)
        parent_packet=pinned_json(receipt['parents']['packet'])
        if digest(req)!=digest(request) or digest(parent_packet)!=digest(packet) or digest(raw_result['planned_trajectory'])!=packet['trajectory_digest']:
            raise ValueError('TIMED_SUFFIX_NOT_THIS_RAW_REQUEST_RESULT_PACKET')
        scale=receipt['selected_integer_scale']
        if type(scale) is not int or scale<1 or receipt['scale_search_iterations']!=0 or receipt['original_command_limits']!=limits:raise ValueError('TIMED_SUFFIX_COMMAND_POLICY_CHANGED')
        raw=packet['trajectory']['points']
        if len(raw)!=len(suffix['points']) or digest(packet['trajectory'])!=packet['trajectory_digest']:raise ValueError('RAW_SUFFIX_CHANGED')
        for old,new in zip(raw,suffix['points']):
            if (new['positions_rad']!=old['positions_rad'] or round(new['time_from_start_s']*1e9)!=round(old['time_from_start_s']*1e9)*scale or
                    new['velocities_rad_s']!=[v/scale for v in old['velocities_rad_s']] or new['accelerations_rad_s2']!=[a/(scale*scale) for a in old['accelerations_rad_s2']]):raise ValueError('TIMED_SUFFIX_PATH_OR_TIME_RULE_CHANGED')
        return suffix,receipt
    except (KeyError,TypeError,OSError) as exc:raise ValueError('NEW_TIMED_SUFFIX_ARTIFACT_REQUIRED:'+str(exc)) from exc


def fresh_moveit_connection(packet,request,current,*,timed_artifacts=None,command_profile='conservative'):
    """Deterministic boundary-PVT connection to a separately pinned timed suffix."""
    from plan_only import JOINTS
    from stop_curve import validate_quintic_limits
    import xml.etree.ElementTree as ET
    context=connection_command_context(current);command=context['command']
    if 'controller_command_start' in request:
        from command_start_plan import review_current_controller_start
        review_current_controller_start(request,current)
    limits=sim_command_limits(command_profile)
    suffix,receipt=command_valid_timed_suffix(packet,request,timed_artifacts,command_profile=command_profile)
    start=dict(time_from_start_s=0.,positions_rad=deepcopy(command['q_rad']),velocities_rad_s=deepcopy(command['v_rad_s']),accelerations_rad_s2=deepcopy(command['a_rad_s2']))
    robot=ET.fromstring(request['model_bundle']['robot_description']);bounds=[robot.find("joint[@name='"+n+"']/limit") for n in JOINTS]
    lower=[float(b.get('lower')) for b in bounds];upper=[float(b.get('upper')) for b in bounds]
    duration,derivation=deterministic_connection_duration(start,suffix['points'][0],lower,upper,command_profile=command_profile);ns=derivation['selected_duration_ns']
    curve=dict(joint_names=deepcopy(suffix['joint_names']),points=[start]+[dict(deepcopy(p),time_from_start_s=(round(p['time_from_start_s']*1e9)+ns)/1e9) for p in suffix['points']])
    checked=validate_quintic_limits(curve,lower,upper,command_limits=[limits[k] for k in ('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')])
    out=dict(scope='COMMAND_INIT_TO_DERIVED_MOVEIT_TIMED_SUFFIX_CPU_CANDIDATE',command_profile=command_profile,command_limits=limits,trajectory=curve,trajectory_digest=digest(curve),suffix_digest=packet['trajectory_digest'],timed_suffix_digest=digest(suffix),timing_artifacts=deepcopy(timed_artifacts),timing_parents=deepcopy(receipt['parents']),duration_s=duration,duration_derivation=derivation,desired=command,observed=context['observed'],command_initialization_ref=context['init_ref'],controller_pvt_ref=context['pvt_ref'],controller_parameters_digest=digest(context['params']),observation_report=context['observation_report'],checks=checked,source_identity=deepcopy(current['source_identity']),native_execution_allowed=False,whole_current_geometry_FCL_required=True)
    out['candidate_digest']=digest(out)
    return out


def review_fresh_connection(connection,packet,request,current,fcl_source,*,command_profile='conservative'):
    if digest({k:v for k,v in connection.items() if k!='candidate_digest'})!=connection['candidate_digest']:raise ValueError('CONNECTION_CANDIDATE_CHANGED')
    if connection.get('command_profile','conservative')!=command_profile or connection.get('command_limits',sim_command_limits())!=sim_command_limits(command_profile):raise ValueError('CONNECTION_COMMAND_PROFILE_CHANGED')
    suffix,_=command_valid_timed_suffix(packet,request,connection['timing_artifacts'],command_profile=command_profile)
    if (digest(connection['trajectory'])!=connection['trajectory_digest'] or digest(packet['trajectory'])!=connection['suffix_digest'] or digest(suffix)!=connection['timed_suffix_digest']):raise ValueError('CHECKED_COMMAND_OR_SUFFIX_CHANGED')
    context=connection_command_context(current)
    if 'controller_command_start' in request:
        from command_start_plan import review_current_controller_start
        review_current_controller_start(request,current)
    if any(context['command'][k]!=connection['desired'][k] for k in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2')):raise ValueError('ACTUAL_COMMAND_INIT_CHANGED_REBUILD_REQUIRED')
    if digest(context['params'])!=connection['controller_parameters_digest']:raise ValueError('ACTIVE_COMMAND_PARAMETERS_CHANGED')
    if digest(current['source_identity'])!=digest(fcl_source['source_identity']) or digest(current['values'])!=digest(fcl_source['values']):raise ValueError('CURRENT_WHOLE_FCL_PROOF_EXPIRED')
    check_world(request,current['values']['world_objects']);check_live(dict(binding=packet['binding'],attachment=request['attachment']),packet['binding'],current['observation'])
    return dict(status='FINAL_COMMAND_SOURCE_AND_FULL_WIRE_IDENTITY_REVIEWED',observation_report=context['observation_report'],native_execution_allowed=False)


def wait_sim_action_result(future, tick, running, source_time, budget_s, record,
                           *, wall_time=time.monotonic):
    """Client result wait only: actual SIM ceiling plus wall no-progress bound.

    tick retains original STOP/holding checks. No trajectory, JTC tolerance,
    sensor stamp, or freshness threshold is modified by this waiting policy.
    """
    from math import isfinite
    start_wall=wall_time();start_source=source_time()
    if not all(type(x) in (int,float) and isfinite(x) for x in (start_wall,start_source,budget_s)) or budget_s<=0:
        raise ValueError('NATIVE_TRANSPORT_RESULT_CLOCK_INVALID')
    last_source=start_source;last_wall=start_wall;progress_wall=start_wall
    while True:
        wall=wall_time();source=source_time()
        if not all(type(x) in (int,float) and isfinite(x) for x in (wall,source)):
            raise ValueError('NATIVE_TRANSPORT_RESULT_CLOCK_INVALID')
        if wall<last_wall or source<last_source:
            raise ValueError('NATIVE_TRANSPORT_RESULT_CLOCK_REVERSED')
        if source>last_source:progress_wall=wall
        row=dict(source_s=source,wall_monotonic_s=wall,source_elapsed_s=source-start_source,
                 wall_elapsed_s=wall-start_wall,wall_without_source_progress_s=wall-progress_wall,
                 future_done=future.done())
        if row['future_done']:decision='RESULT_RECEIVED'
        elif not running():decision='APP_STOPPED'
        elif row['source_elapsed_s']>=budget_s:decision='SIM_ELAPSED_LIMIT'
        elif row['wall_without_source_progress_s']>=budget_s:decision='WALL_NO_SOURCE_PROGRESS_LIMIT'
        else:decision='WAIT'
        record(dict(row,decision=decision))
        if decision=='RESULT_RECEIVED':return future.result()
        if decision!='WAIT':raise ValueError('NATIVE_TRANSPORT_TIMEOUT')
        last_source=source;last_wall=wall
        tick()


def run_transport(app, args, out, motion, sample, raw_tick, world, node,
                  statuses, guard_hits, stop_samples, set_phase, read_geometry):
    """Continue the same dynamic contact grasp; planning runs while paused."""
    import omni.timeline
    from rclpy.action import ActionClient
    from rcl_interfaces.srv import GetParameters
    from action_msgs.srv import CancelGoal
    from control_msgs.action import FollowJointTrajectory
    from prepare_gpu_scene import prepare_gpu_files

    run = out/'transport_plan'
    hooks=getattr(args,'transport_hooks',None)
    def emit(kind,payload):
        if hooks:hooks['event'](kind,payload,float(world.current_time))
    physics_dt=json.loads((out/'capture_setup.json').read_text())['physics_dt_s']
    fresh_moveit=bool(getattr(args,'fresh_moveit_baseline',False))
    if fresh_moveit:validate_fresh_moveit_route(args,os.environ.get('ROS_DOMAIN_ID'),os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE'))
    command_profile=getattr(args,'sim_command_profile','conservative')
    sim_command_limits(command_profile)
    if command_profile!='conservative' and (not fresh_moveit or not getattr(args,'source_depth_baseline',False)):
        raise ValueError('FAST_COMMAND_PROFILE_ONLY_ISOLATED_FRESH_SOURCE_SIM')
    fresh_source=None
    if fresh_moveit:
        producer=getattr(args,'settled_fresh_plan_inputs',None)
        if not callable(producer):raise ValueError('SETTLED_FRESH_PLAN_PRODUCER_REQUIRED')
        # Service discovery and observed stopping precede all fresh request/solver work.
        omni.timeline.get_timeline_interface().play()
        parameters=node.create_client(GetParameters,'/sim/m0609/arm_controller/get_parameters')
        client=ActionClient(node,FollowJointTrajectory,'/sim/m0609/arm_controller/follow_joint_trajectory')
        cancel=node.create_client(CancelGoal,'/sim/m0609/arm_controller/follow_joint_trajectory/_action/cancel_goal')
        settled_history=deque(stop_samples);anchor=deepcopy(sample())
        settled_loaded={name:stop_samples[-1]['time_s'] for name in stop_samples[-1]['contact_fingers']}
        def settle_tick():
            wall=time.monotonic();raw_tick();row=sample()
            for name in row['contact_fingers']:settled_loaded[name]=row['time_s']
            row['contact_last_loaded_s']=dict(settled_loaded);settled_history.append(row)
            while settled_history[-1]['time_s']-settled_history[0]['time_s']>1:settled_history.popleft()
            check_live(dict(binding={},attachment=anchor['attachment']),{},row,
                (out/'stop.request').exists() or (out/'shutdown.request').exists(),contact_grace_s=.02)
            if (any(command_counts(statuses).values()) or guard_hits or (hooks and hooks['stop_requested']())):
                raise ValueError('FRESH_MOVEIT_PREPLAN_HOLD_GUARD')
            if hooks:hooks['sample'](row,statuses)
            time.sleep(max(0,physics_dt-(time.monotonic()-wall)))
            return row
        deadline=time.monotonic()+30
        while not (parameters.service_is_ready() and client.server_is_ready() and cancel.service_is_ready()) and app.is_running() and time.monotonic()<deadline:settle_tick()
        if not (parameters.service_is_ready() and client.server_is_ready() and cancel.service_is_ready()):raise ValueError('NATIVE_TRANSPORT_SERVICES_UNAVAILABLE')
        parameter_names=['interpolation_method','interpolate_from_desired_state','open_loop_control','allow_integration_in_goal_trajectories','command_interfaces','state_interfaces','joints','allow_partial_joints_goal','constraints.stopped_velocity_tolerance']+[f'constraints.joint_{i}.{kind}' for i in range(1,7) for kind in ('goal','trajectory')]
        parameter_future=parameters.call_async(GetParameters.Request(names=parameter_names))
        deadline=time.monotonic()+30
        while not parameter_future.done() and app.is_running() and time.monotonic()<deadline:settle_tick()
        if not parameter_future.done():raise ValueError('NATIVE_TRANSPORT_TIMEOUT')
        params=parameter_future.result()
        if len(params.values)!=len(parameter_names):raise ValueError('ACTIVE_CONTROLLER_PARAMETERS_INCOMPLETE')
        recorder=getattr(args,'record_fresh_controller_parameters',None)
        if not callable(recorder):raise ValueError('ACTIVE_CONTROLLER_PARAMETER_RECORDER_REQUIRED')
        recorder(parameter_names,params.values)
        interpolation=params.values[0].string_value
        if interpolation!='splines':raise ValueError('FRESH_MOVEIT_SPLINES_REQUIRED')
        save(out/'transport_controller.json',dict(interpolation_method=interpolation))
        until=world.current_time+1
        while world.current_time<until and app.is_running():settle_tick()
        if not app.is_running():raise ValueError('FRESH_MOVEIT_PREPLAN_INTERRUPTED')
        verified_stop(list(settled_history))
        fresh_source=settled_fresh_source(producer('SETTLED_BEFORE_FRESH_MOVEIT'),float(world.current_time))
        fresh_stop_metrics=verified_stop(list(settled_history),vector(fresh_source['observation']['q_rad'],6)+[fresh_source['observation']['grip_rad']])
        stop_samples=list(settled_history)
        if (any(command_counts(statuses).values()) or guard_hits or (out/'stop.request').exists() or
                (out/'shutdown.request').exists() or (hooks and hooks['stop_requested']())):
            raise ValueError('FRESH_MOVEIT_STOP_OR_HOLD_GUARD')
    prepared=getattr(args,'prepared_transport',None)
    live=getattr(args,'live_transport',None)
    if live and (not prepared or os.environ.get('ROS_DOMAIN_ID')!='194' or not getattr(args,'depth_owner_test',False)):
        raise ValueError('LIVE_NATIVE_PREPARED_SIM194_ONLY')
    if prepared:
        if os.environ.get('ROS_DOMAIN_ID')!='194' or not args.sim_transport or getattr(args,'transport_engine',None)!='cumotion':
            raise ValueError('PREPARED_FIXED_SIM194_ONLY')
        run.mkdir(exist_ok=False)
        request,packet,result_path=prepared['receive'](run)
        engine='cumotion';context_path=out/'transport.latest_context.json'
        save(context_path,packet['binding'])
        save(run/'D_cumotion_calculation_receipt.json',packet)
        set_phase('VALIDATED_NEW_FIXED_CALCULATION_RECEIVED')
    else:
        scene_path=Path(fresh_source['refs']['scene_ref']['path']) if fresh_moveit else out/'capture/scene.json'
        state_path=Path(fresh_source['refs']['state_ref']['path']) if fresh_moveit else out/'capture/post_grasp_state.json'
        request = prepare_gpu_files(run,motion,scene_path,state_path,args.model_bundle,controller_start_source=(fresh_source if fresh_moveit and getattr(args,'command_start_planning',False) else None))
        if fresh_moveit:
            settled_fresh_source(fresh_source['refs'],float(world.current_time),request=request)
            save(run/'settled_source_binding.json',dict(source=fresh_source,planning_request_digest=request['planning_request_digest'],stop_metrics=fresh_stop_metrics,stop_observations=list(settled_history)))
            fresh_request_digest=digest(request)
        context_path = out/'transport.latest_context.json'
        save(context_path, json.loads((run/'scene_context.json').read_text()))
        set_phase('FRESH_MOVEIT_PLANNING_NATIVE_HOLD' if fresh_moveit else 'PLANNING_WHILE_PAUSED')
        if fresh_moveit:omni.timeline.get_timeline_interface().play()
        engine=getattr(args,'transport_engine','moveit')
        if engine=='cumotion':
            command=[str(args.cumotion_python),'-I','-B',str(Path(__file__).parent/'plan_cumotion_sim.py'),
                '--request',str(run/'TRANSPORT.request.yaml'),'--run',str(run),
                '--fcl-binary',str(args.cumotion_fcl_binary),'--fcl-sha256',args.cumotion_fcl_sha256]
            command+=['--timing-profile',getattr(args,'cumotion_timing_profile','nominal')]
            environment=args.cumotion_calculation_environment
        elif engine=='moveit':
            command=[str(Path(args.transport_calculator).resolve()),str(Path(__file__).resolve().parents[1]),
                     str(run),str(run/'TRANSPORT.request.yaml'),str(run/'result.yaml')]
            environment=None
        else:raise ValueError('EXPLICIT_SIM_TRANSPORT_ENGINE_REQUIRED')
        save(run/'planner_invocation.json',dict(command=command,wall_started_monotonic_s=time.monotonic(),source_start_SIM_s=float(world.current_time),fresh_moveit=fresh_moveit,external_trajectory_supplied=False if fresh_moveit else None))
        with (run/'solver.log').open('w') as log:
            process = subprocess.Popen(command,env=environment,stdout=log,stderr=subprocess.STDOUT)
            deadline = time.monotonic()+(600 if engine=='cumotion' else 120)
            try:
                while process.poll() is None and app.is_running() and time.monotonic()<deadline:
                    if fresh_moveit:
                        raw_tick()
                        poll_source=settled_fresh_source(producer('FRESH_MOVEIT_PLANNER_HOLD'),float(world.current_time),expected=fresh_source)
                        current=poll_source['observation']
                        binding=json.loads(context_path.read_text())
                        check_live(dict(binding=binding,attachment=request['attachment']),binding,current)
                        if any(command_counts(statuses).values()) or guard_hits or (out/'stop.request').exists():
                            process.terminate();process.wait(timeout=10);raise ValueError('FRESH_MOVEIT_PLANNING_HOLD_GUARD')
                        settled_history.append(current)
                        while settled_history[-1]['time_s']-settled_history[0]['time_s']>1:settled_history.popleft()
                        if hooks:hooks['sample'](current,statuses)
                    else:app.update()
                    time.sleep(1/240 if fresh_moveit else 1/60)
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=10)
                    raise ValueError('SIM_CALCULATOR_INTERRUPTED_OR_TIMED_OUT')
            except BaseException:
                if process.poll() is None:
                    process.terminate();process.wait(timeout=10)
                raise
            save(run/'process_exit.json', dict(exit_code=process.returncode))
        if engine=='cumotion':
            from robot_control_integration.app.cumotion_transport import receive_calculation
            from cumotion_timing import ENGINE
            result_path=run/'cumotion_calculation/final.fcl.yaml'
            packet=receive_calculation(run/'cumotion_calculation/calculation_report.json',motion,
                json.loads(context_path.read_text()),engine=ENGINE,expected_fcl_sha256=args.cumotion_fcl_sha256)
            save(run/'D_cumotion_calculation_receipt.json',packet)
        else:
            result_path=run/'result.yaml'
            packet = receive_files(run,result_path,json.loads(context_path.read_text()),run/'D_candidate.json')
    if fresh_moveit:
        retimer=getattr(args,'command_valid_moveit_suffix',None)
        if not callable(retimer):raise ValueError('NEW_MOVEIT_COMMAND_TIMING_PRODUCER_REQUIRED')
        from prepare_cpu_model import file_hash
        raw_parents={name:dict(path=str(Path(path).resolve()),sha256=file_hash(path)) for name,path in [('request',run/'TRANSPORT.request.yaml'),('result',result_path),('packet',run/'D_candidate.json')]}
        raw_packet_digest=digest(packet)
        save(run/'raw_moveit_parent_pins.json',raw_parents)
        timed_artifacts=retimer(run,request,result_path,packet)
        if digest(packet)!=raw_packet_digest or any(file_hash(r['path'])!=r['sha256'] for r in raw_parents.values()):raise ValueError('RETIMER_MODIFIED_ORIGINAL_MOVEIT_INPUT')
        _,timing_receipt=command_valid_timed_suffix(packet,request,timed_artifacts,command_profile=command_profile)
        if timing_receipt['parents']!=raw_parents:raise ValueError('TIMING_PARENTS_NOT_ORIGINAL_D_RECEIPT')
        save(run/'timed_suffix_binding.json',timed_artifacts)
        fresh_current=settled_fresh_source(producer('RECHECK_AFTER_FRESH_MOVEIT'),float(world.current_time),expected=fresh_source)
        stop_samples=list(settled_history)
        verified_stop(stop_samples,vector(fresh_current['observation']['q_rad'],6)+[fresh_current['observation']['grip_rad']])
        # Request still binds the ORIGINAL settled source files; never patch its q/attachment.
        from prepare_sim_snapshot import validate_sim_snapshot
        validate_sim_snapshot(request['source_snapshot'])
        if digest(request)!=fresh_request_digest:raise ValueError('FRESH_REQUEST_CHANGED_AFTER_CALCULATION')
        save(run/'settled_after_calculation.json',fresh_current)
    if prepared:prepared['check_world'](read_geometry())
    else:check_world(request,read_geometry())
    # Validate the calculation data without creating sensor-visible guide prims.
    calculated=yaml.load(result_path.read_text(),Loader=yaml.CSafeLoader)
    if (calculated.get('planning_block_padding_m')!=.002 or
            calculated.get('planning_padding_roles')!=['SUPPLY_BLOCK','CURRENT_BLOCK']):
        raise ValueError('NOMINAL_SIM_BLOCK_CLEARANCE_ENVELOPE_REQUIRED')
    if fresh_moveit and (calculated.get('result_provenance')!='MOVEIT_LOCAL_PLANNING_RESULT' or calculated.get('plan_success') is not True):raise ValueError('FRESH_MOVEIT_PROVENANCE_REQUIRED')
    monitor_packet = dict(packet, attachment=request['attachment'])
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    if not fresh_moveit:parameters = node.create_client(GetParameters, '/sim/m0609/arm_controller/get_parameters')
    if not fresh_moveit:client = ActionClient(node, FollowJointTrajectory, '/sim/m0609/arm_controller/follow_joint_trajectory')
    from threading import RLock
    owner_apply_lock=RLock() if live else None  # one lock owned by THIS existing SIM D
    resume_world_request=None;resume_submission=None;resume_failure=None
    if not fresh_moveit:cancel = node.create_client(CancelGoal, '/sim/m0609/arm_controller/follow_joint_trajectory/_action/cancel_goal')
    history = deque(stop_samples)
    last_loaded={name:stop_samples[-1]['time_s'] for name in stop_samples[-1]['contact_fingers']}
    trace = (out/'transport_observations.jsonl').open('w')
    sent = False; handle = None; action_result = None; action_future=None
    sent_sim_time=None
    accepted_source_s=None
    foreground_enabled=bool(getattr(args,'fresh_foreground_stop',False))
    foreground_gate=None;foreground_cancel_future=None;foreground_cancel_receipt=None
    foreground_cancel_attempted=False;foreground_entry=None;foreground_decision_key=None
    result_recorded=False
    def observe_result():
        nonlocal result_recorded
        if hooks and action_future is not None and action_future.done() and not result_recorded:
            response=action_future.result();result_recorded=True
            emit('GOAL_RESULT',dict(status=int(response.status),error_code=int(response.result.error_code),
                error_string=response.result.error_string,goal_id=bytes(handle.goal_id.uuid).hex()))
    def current_stop_readout():
        # Called only by MI's synchronized main-thread provider, never by a worker.
        # No spin/update/tick, command, file write, source-clock substitution or retry.
        if not foreground_enabled or not hooks or handle is None or not handle.accepted:
            return None
        publication=hooks['get_stop_publication']()
        if publication is None or publication.status_ref is None or publication.accepted_ref is None:
            return None
        if action_future is None or not action_future.done() or foreground_cancel_future is None or not foreground_cancel_future.done():
            return None
        response=action_future.result();ack=foreground_cancel_future.result()
        uuid=bytes(handle.goal_id.uuid).hex()
        if (response.status!=5 or response.result.error_code!=0 or ack.return_code!=0
                or [bytes(g.goal_id.uuid).hex() for g in ack.goals_canceling]!=[uuid]
                or not foreground_cancel_receipt or foreground_cancel_receipt['decision']!='SCOPED_CANCEL_CALL_RETURNED'
                or foreground_cancel_receipt['bound_goal_uuid']!=uuid
                or foreground_cancel_receipt['active_wire_digest']!=actual_wire_digest):
            return None
        if (guard_hits or hooks['stop_requested']() or any((out/name).exists() for name in
                ('stop.request','shutdown.request','failure.txt','capture_failure.json','transport_failure.json'))):
            return None
        counts=command_counts(statuses)
        if any(counts.values()):return None
        row=sample();loaded=dict(last_loaded)
        for name in row['contact_fingers']:loaded[name]=row['time_s']
        row['contact_last_loaded_s']=loaded
        context=json.loads(context_path.read_text())
        check_live(monitor_packet,context,row,False,contact_grace_s=.02)
        return dict(schema='native-current-stop-readout/1.0',goal_id=uuid,goal_accepted=bool(handle.accepted),
            terminal_status=int(response.status),terminal_error_code=int(response.result.error_code),
            cancel_ack_goal_ids=[bytes(g.goal_id.uuid).hex() for g in ack.goals_canceling],
            cancel_ack_return_code=int(ack.return_code),cancel_request_count=int(foreground_cancel_attempted),
            mode='OBSTACLE_HOLD',user_stop_latched=False,failure_latched=False,outcome_unknown=False,
            command_counts=dict(**counts,pending_cancel_count=0),current_context=context,
            accepted_ref=deepcopy(publication.accepted_ref),observation=row,
            **{k:deepcopy(request[k]) for k in ('a_context','reservation_binding','current_revision','world_revision','model_digest')},
            model_manifest_sha256=request['model_bundle']['manifest_sha256'],original_goal=deepcopy(request['goal']),
            active_wire_digest=actual_wire_digest)
    if foreground_enabled and hooks and hooks.get('get_stop_publication') is not None:
        hooks['current_stop_readout']=current_stop_readout
    def dispatch_foreground_stop(row):
        nonlocal foreground_gate,foreground_cancel_future,foreground_cancel_receipt,foreground_cancel_attempted,foreground_entry,foreground_decision_key
        if not foreground_enabled or handle is None or not handle.accepted or action_future is None:return
        from isaac_sim.real_execution.fresh_foreground_cancel import FreshForegroundCancelGate,SCOPE
        binding=hooks['foreground_stop_binding']()
        if foreground_gate is None:
            foreground_gate=FreshForegroundCancelGate(goal_uuid=bytes(handle.goal_id.uuid).hex(),active_wire_digest=actual_wire_digest,source_binding=binding,sim_conservative_stop_authorized=True,max_source_age_SIM_s=getattr(args,'foreground_stop_max_source_age_s',.12))
        entry=hooks['foreground_stop_entry']()
        notice=entry['notice'] if entry is not None else None
        sampled={}
        def read_current():
            counts=command_counts(statuses)
            sampled.update(binding,scope=SCOPE,ros_domain_id=int(os.environ['ROS_DOMAIN_ID']),localhost_only=os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')=='LOCALHOST',source_s=float(world.current_time),observed_wall_monotonic_s=time.monotonic(),active_goal_uuid=bytes(handle.goal_id.uuid).hex(),active_wire_digest=actual_wire_digest,goal_accepted=bool(handle.accepted),goal_terminal=bool(action_future.done()),accepted_source_s=accepted_source_s,**counts)
            return sampled
        def send_same_uuid(uuid):
            if (uuid!=bytes(handle.goal_id.uuid).hex() or not handle.accepted or action_future.done() or
                    float(world.current_time)!=sampled['source_s']):raise ValueError('CANCEL_SEND_ACTIVE_UUID_OR_SOURCE_CHANGED')
            scoped=CancelGoal.Request();scoped.goal_info.goal_id=handle.goal_id
            return cancel.call_async(scoped)
        try:
            receipt,future=foreground_gate.dispatch(notice,read_current=read_current,send_same_uuid=send_same_uuid)
        except Exception:
            receipt=foreground_gate.last_receipt
            if receipt.get('decision')=='CANCEL_SEND_OUTCOME_UNKNOWN':
                foreground_cancel_receipt=receipt;foreground_cancel_attempted=True;foreground_entry=entry
                hooks['retain_foreground_stop_entry'](entry,receipt)
                raise ValueError('FRESH_FOREGROUND_CANCEL_OUTCOME_UNKNOWN')
            raise
        if future is not None:
            foreground_cancel_receipt=receipt;foreground_cancel_future=future;foreground_cancel_attempted=True;foreground_entry=entry
            hooks['retain_foreground_stop_entry'](entry,receipt)
        metadata=receipt.get('notice_metadata') or {}
        key=(metadata.get('frame_seq'),receipt['decision'],tuple(receipt.get('reasons',[])))
        if key!=foreground_decision_key:
            # Dispatch/read-current/scoped send already returned: IO cannot delay it.
            with (out/'foreground_stop_decisions.jsonl').open('a') as stream:stream.write(json.dumps(receipt)+'\n')
            foreground_decision_key=key
        if future is not None:
            save(out/'foreground_dispatch_timing.json',dict(scope='PERFORMANCE_ONLY_NOT_SOURCE_TIME_OR_FRESHNESS',phase=row.get('foreground_dispatch_phase','AFTER_PHYSICS_STEP'),entry_publish_prepare_wall_monotonic_s=entry.get('publish_prepare_wall_monotonic_s'),actual_cancel_boundary=receipt['actual_cancel_boundary'],source_timestamp_rewritten=False))
            raise ValueError('FRESH_FOREGROUND_CONSERVATIVE_STOP')

    def tick(check=True):
        wall = time.monotonic()
        # A ready sealed notice need not wait for another physics step. All
        # live/STOP/contact checks and the same one-shot gate still precede send.
        if check and foreground_enabled and hooks['foreground_stop_entry']() is not None:
            import rclpy
            rclpy.spin_once(node,timeout_sec=0)
            observe_result()
            before_step=sample()
            before_step['contact_last_loaded_s']=dict(last_loaded)
            before_context=json.loads(context_path.read_text())
            check_live(monitor_packet,before_context,before_step,(out/'stop.request').exists() or (out/'shutdown.request').exists(),contact_grace_s=.02)
            if guard_hits:raise ValueError('UNEXPECTED_TRANSPORT_CONTACT: '+str(guard_hits[-1]))
            if hooks['stop_requested']():raise ValueError('OBSTACLE_RESPONSE_HOLD')
            before_step['foreground_dispatch_phase']='BEFORE_PHYSICS_STEP'
            dispatch_foreground_stop(before_step)
        raw_tick(); row = sample()
        observe_result()
        for name in row['contact_fingers']:last_loaded[name]=row['time_s']
        row['contact_last_loaded_s']=dict(last_loaded)
        history.append(row)
        while history[-1]['time_s']-history[0]['time_s']>1: history.popleft()
        latest = json.loads(context_path.read_text())
        row['holding_drift_m_rad'] = error(rigid(request['attachment']), rigid(row['attachment']))
        if check and foreground_enabled:
            check_live(monitor_packet,latest,row,(out/'stop.request').exists() or (out/'shutdown.request').exists(),contact_grace_s=.02)
            if guard_hits:raise ValueError('UNEXPECTED_TRANSPORT_CONTACT: '+str(guard_hits[-1]))
            dispatch_foreground_stop(row)
        trace.write(json.dumps(row)+'\n'); trace.flush()
        if hooks:hooks['sample'](row,statuses)
        if check:
            if hooks and hooks['stop_requested']():raise ValueError('OBSTACLE_RESPONSE_HOLD')
            stop_after=getattr(args,'transport_stop_after_s',None)
            if (engine=='cumotion' and stop_after is not None and handle is not None and handle.accepted and
                    sent_sim_time is not None and row['time_s']-sent_sim_time>=stop_after and
                    max(abs(np.array(row['q_rad'])-request['planning_snapshot']['q_rad']))>.02 and
                    not (out/'stop.request').exists()):
                counts=command_counts(statuses)
                if counts['active_command_count']<=0:raise ValueError('STOP_TEST_REQUIRES_ACTIVE_NATIVE_GOAL')
                save(out/'stop_injection.json',dict(scope='EXPLICIT_SIM_MOVING_STOP_TEST',
                    observation=row,**counts,sim_time_since_send_s=row['time_s']-sent_sim_time,
                    hardware_execution_allowed=False,automatic_resume=False))
                (out/'stop.request').touch()
            check_live(monitor_packet, latest, row, (out/'stop.request').exists() or (out/'shutdown.request').exists(),contact_grace_s=.02)
            if guard_hits: raise ValueError('UNEXPECTED_TRANSPORT_CONTACT: '+str(guard_hits[-1]))
        time.sleep(max(0,physics_dt-(time.monotonic()-wall)))
    def wait(future, timeout=30):
        deadline = time.monotonic()+timeout
        while not future.done() and app.is_running() and time.monotonic()<deadline: tick()
        if not future.done(): raise ValueError('NATIVE_TRANSPORT_TIMEOUT')
        return future.result()
    def finish_active_goal():
        nonlocal action_result
        operation_timeout=(curve if fresh_moveit else packet['trajectory'])['points'][-1]['time_from_start_s']*6+30
        if getattr(args,'source_depth_baseline',False):
            if not fresh_moveit or os.environ.get('ROS_DOMAIN_ID')!='194' or getattr(args,'source_transport_wall_budget_s',None)!=180.:raise ValueError('SOURCE_EXPORT_OPERATION_WALL_BUDGET_SIM194_ONLY')
            operation_timeout=max(operation_timeout,args.source_transport_wall_budget_s)
            save(out/'source_transport_operation_budget.json',dict(scope='CLIENT_RESULT_WAIT_ONLY_NOT_CONTROLLER_OR_SDK_LIMIT',seconds=operation_timeout,reason='native14 cumulative wall timeout while actual SIM advanced; unchanged numeric budget now bounds SIM elapsed and wall without source progress; JTC constraints unchanged',wait_basis='ACTUAL_SAME_D_SIM_ELAPSED_AND_WALL_NO_PROGRESS',SIM_elapsed_limit_s=operation_timeout,wall_no_progress_limit_s=operation_timeout,controller_goal_time_tolerance_changed=False))
        if getattr(args,'source_depth_baseline',False):
            # Same D/world clock; original guarded tick and JTC goal policy stay.
            with (out/'source_transport_result_wait_progress.jsonl').open('x') as progress:
                def record_wait(row):progress.write(json.dumps(row)+'\n')
                response=wait_sim_action_result(action_future,tick,app.is_running,
                    lambda:float(world.current_time),operation_timeout,record_wait)
        else:response=wait(action_future,operation_timeout)
        observe_result()
        action_result=dict(status=int(response.status),error_code=int(response.result.error_code),error_string=response.result.error_string)
        save(out/'transport_action_result.json',action_result)
        if response.status!=4 or response.result.error_code!=0: raise ValueError('NATIVE_TRANSPORT_FAILED')
        set_phase('PRE_CONTACT_HOLDING_STOP_CHECK')
        until=world.current_time+3
        while world.current_time<until: tick()
        counts=command_counts(statuses)
        if any(counts.values()): raise ValueError('TRANSPORT_COMMAND_NOT_FINISHED')
        stop=verified_stop(list(history)); final=sample()
        check_live(monitor_packet,json.loads(context_path.read_text()),final)
        pe,re=error(pose_matrix(packet['pre_contact_tcp_pose']),pose_matrix(final['tcp_pose']))
        if pe>.002 or re>np.deg2rad(1): raise ValueError('ACTUAL_PRE_CONTACT_NOT_REACHED')
        if max(abs(np.array(final['q_rad'])-packet['trajectory']['points'][-1]['positions_rad']))>.015:
            raise ValueError('ACTUAL_TERMINAL_JOINT_DRIFT')
        objects=read_geometry();save(out/'transport_final_scene.json',objects)
        settling=check_world(resume_world_request,objects) if resume_world_request is not None else (prepared['check_world'](objects) if prepared else check_world(request,objects))
        status=dict(success=True,scope='ISOLATED_SIM_TRANSPORT_TO_D_WAIT',binding=packet['binding'],
            actual_endpoint_error_m_rad=[pe,re],final_observation=final,stop_metrics=stop,
            native_action_result=action_result,**counts,holding_confirmed=True,assembly_completed=False,
            hardware_execution_allowed=False,virtual_attachment_used=False,contact_execution_issued=False,
            gripper_open_issued=False,handoff_status='D_CONTACT_PENDING_NOT_EXECUTED',
            native_complete_trajectory_sent=True,final_scene_objects=objects,physics_dt_s=physics_dt,
            waiting_supply_settling_m_rad=settling,dynamic_contact_observation_window_s=.02)
        save(out/'transport_status.json',status)
        if hooks:hooks['completed'](status,packet,request,list(history))
        return status
    try:
        if not fresh_moveit:
            deadline=time.monotonic()+30
            while (not parameters.service_is_ready() or not client.server_is_ready() or not cancel.service_is_ready()) and time.monotonic()<deadline: tick()
            if not parameters.service_is_ready() or not client.server_is_ready() or not cancel.service_is_ready():
                raise ValueError('NATIVE_TRANSPORT_SERVICES_UNAVAILABLE')
            params=wait(parameters.call_async(GetParameters.Request(names=['interpolation_method'])))
            interpolation=params.values[0].string_value if len(params.values)==1 else None
            save(out/'transport_controller.json',dict(interpolation_method=interpolation))
            # Settle after parameter discovery, then recheck the live start immediately.
            until=world.current_time+1
            while world.current_time<until: tick()
        if prepared and prepared.get('prepare_start'):
            prepared['prepare_start'](sample,tick,world)
        validated_goal=prepared['native_goal'](sample(),list(history),statuses) if prepared else None
        if 'controller_command_start' in request and (not fresh_moveit or not getattr(args,'command_start_planning',False)):
            raise ValueError('COMMAND_START_PLAN_REQUIRES_EXPLICIT_FRESH_MOVEIT_MODE')
        check_start(packet,request,sample(),statuses,list(history),json.loads(context_path.read_text()),
            authorized=args.sim_transport,domain=os.environ.get('ROS_DOMAIN_ID'),
            discovery=os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE'),interpolation=interpolation,
            transport_engine=engine,depth_owner_test=bool(hooks and getattr(args,'depth_owner_test',False)),verified_initial_connection=bool((prepared and validated_goal is not None) or fresh_moveit))
        receipt=out/'transport_receipt.json'
        if receipt.exists(): raise ValueError('DUPLICATE_TRANSPORT_REFUSED')
        goal=None if fresh_moveit else (validated_goal if prepared else native_goal(packet))
        if fresh_moveit:
            from run_fixed_depth_native import audit_current_geometry,sha
            fcl_source_reads=[]
            def actual_owner():
                current=settled_fresh_source(producer('FRESH_MOVEIT_FCL_OWNER'),float(world.current_time),expected=fresh_source)
                fcl_source_reads.append(current)
                save(run/'settled_FCL_source_reads.json',fcl_source_reads)
                row=current['observation']
                return dict(q_rad=row['q_rad'],grip_rad=row['grip_rad'],attachment_tcp_to_block=row['attachment'],world_objects=current['values']['world_objects'],time_s=row['time_s'],source_identity=current['source_identity'],settled_plan_source_ref=fresh_source['refs']['snapshot_ref'])
            connection_source=settled_fresh_source(producer('FRESH_MOVEIT_INITIAL_CONNECTION'),float(world.current_time),expected=fresh_source)
            connection=fresh_moveit_connection(packet,request,connection_source,timed_artifacts=timed_artifacts,command_profile=command_profile)
            save(run/'fresh_moveit_connection.json',connection)
            curve=deepcopy(connection['trajectory'])
            library=Path(__file__).resolve().parents[4]/'local_records/step6_cumotion_20261014/offline_stop_candidate/libstop_fcl.so'
            audit_current_geometry(out/'fresh_moveit_actual_geometry_FCL',request,curve,actual_owner,library)
            final_source=settled_fresh_source(producer('RECHECK_BEFORE_FRESH_GOAL'),float(world.current_time),expected=fresh_source)
            save(run/'settled_before_goal.json',final_source)
            validate_sim_snapshot(request['source_snapshot'])
            if digest(request)!=fresh_request_digest:raise ValueError('FRESH_REQUEST_CHANGED_BEFORE_GOAL')
            check_start(packet,request,sample(),statuses,list(history),json.loads(context_path.read_text()),authorized=args.sim_transport,domain=os.environ.get('ROS_DOMAIN_ID'),discovery=os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE'),interpolation=interpolation,transport_engine='moveit',depth_owner_test=True,verified_initial_connection=True)
            review_fresh_connection(connection,packet,request,final_source,fcl_source_reads[-1],command_profile=command_profile)
            if (any(command_counts(statuses).values()) or guard_hits or (out/'stop.request').exists() or
                    (out/'shutdown.request').exists() or (hooks and hooks['stop_requested']())):
                raise ValueError('FRESH_MOVEIT_STOP_OR_HOLD_GUARD')
            goal=native_goal(dict(packet,trajectory=curve,trajectory_digest=connection['trajectory_digest']))
        if prepared:
            final_goal=prepared['native_goal'](sample(),list(history),statuses)
            if final_goal!=goal:raise ValueError('FIXED_NATIVE_GOAL_CHANGED_BEFORE_SEND')
            goal=final_goal
        actual_wire=dict(joint_names=list(goal.trajectory.joint_names),points=[dict(time_from_start_s=(p.time_from_start.sec*10**9+p.time_from_start.nanosec)/1e9,positions_rad=list(p.positions),velocities_rad_s=list(p.velocities),accelerations_rad_s2=list(p.accelerations)) for p in goal.trajectory.points])
        if fresh_moveit and digest(actual_wire)!=digest(curve):raise ValueError('FRESH_WIRE_CHANGED_AFTER_FCL')
        if fresh_moveit:
            at_send=settled_fresh_source(producer('RECHECK_AT_FRESH_SEND'),float(world.current_time),expected=fresh_source)
            save(run/'settled_at_send.json',at_send)
            review_fresh_connection(connection,packet,request,at_send,fcl_source_reads[-1],command_profile=command_profile)
            if (any(command_counts(statuses).values()) or guard_hits or (out/'stop.request').exists() or
                    (out/'shutdown.request').exists() or (hooks and hooks['stop_requested']())):
                raise ValueError('FRESH_MOVEIT_STOP_OR_HOLD_GUARD')
        actual_wire_digest=digest(actual_wire)
        save(out/'actual_native_wire.json',actual_wire)
        save(receipt,dict(actual_wire_digest=actual_wire_digest,source_calculation_trajectory_digest=packet['trajectory_digest'],scope='ISOLATED_SIM_NATIVE_TRANSPORT',binding=packet['binding'],
            calculation_engine=packet.get('calculation_engine','MOVEIT_LOCAL_PLANNING_RESULT'),
            trajectory_digest=packet['trajectory_digest'],complete_point_count=len(goal.trajectory.points),
            arm_goal_send_count=1,transport_gripper_goal_count=0,hardware_execution_allowed=False,
            sim_time_s=world.current_time,wall_started_monotonic_s=time.monotonic()))
        set_phase('TRANSPORT_HOLDING')
        emit('SUBMISSION_INTENT',dict(trajectory_digest=actual_wire_digest,source_calculation_trajectory_digest=packet['trajectory_digest'],binding=packet['binding'],request=request,
            complete_point_count=len(goal.trajectory.points),header_ns=goal.trajectory.header.stamp.sec*10**9+goal.trajectory.header.stamp.nanosec))
        if owner_apply_lock is not None:
            with owner_apply_lock:future=client.send_goal_async(goal,**({'goal_uuid':hooks['goal_uuid']} if hooks else {}))
        else:future=client.send_goal_async(goal,**({'goal_uuid':hooks['goal_uuid']} if hooks else {}))
        sent=True;sent_sim_time=world.current_time
        emit('GOAL_SUBMITTED',dict(trajectory_digest=actual_wire_digest,source_calculation_trajectory_digest=packet['trajectory_digest'],request_issued=True))
        handle=wait(future)
        goal_stamp=getattr(handle,'stamp',None)
        accepted_source_s=float(world.current_time) if handle.accepted else None
        emit('GOAL_ACCEPTED',dict(accepted=bool(handle.accepted),goal_id=bytes(handle.goal_id.uuid).hex(),
            goal_stamp_ns=goal_stamp.sec*10**9+goal_stamp.nanosec if goal_stamp is not None else None))
        if not handle.accepted: raise ValueError('NATIVE_TRANSPORT_REJECTED')
        # Fine physics/rendering can run slower than wall time. The controller's
        # existing goal-time tolerance still operates on the SIM clock.
        action_future=handle.get_result_async()
        return finish_active_goal()
    except Exception as exc:
        # Cancel native control before pausing; pause alone is not a stop receipt.
        cancellation=[]
        if foreground_cancel_attempted:
            save(out/'foreground_cancel_dispatch.json',foreground_cancel_receipt)
            emit('CANCEL_REQUEST',dict(reason=str(exc),goal_id=bytes(handle.goal_id.uuid).hex(),conservative_stop=True,request_issued=foreground_cancel_future is not None,source_age_SIM_s=foreground_cancel_receipt.get('source_age_SIM_s')))
            if foreground_cancel_future is not None:
                future=foreground_cancel_future;deadline=time.monotonic()+5
                while not future.done() and time.monotonic()<deadline:tick(False)
                response=future.result() if future.done() else None
                ack=dict(done=future.done(),return_code=int(response.return_code) if response is not None else None,goals_canceling_count=len(response.goals_canceling) if response is not None else None,goals_canceling_ids=[bytes(g.goal_id.uuid).hex() for g in response.goals_canceling] if response is not None else None,goal_info_stamps_ns=[g.stamp.sec*10**9+g.stamp.nanosec for g in response.goals_canceling] if response is not None else None)
                cancellation.append(ack);emit('CANCEL_ACK',ack)
        elif sent:
            for _ in range(3):
                emit('CANCEL_REQUEST',dict(reason='OBSTACLE_RESPONSE_HOLD' if str(exc)=='OBSTACLE_RESPONSE_HOLD' else str(exc),
                    goal_id=bytes(handle.goal_id.uuid).hex() if handle else None))
                cancel_request=CancelGoal.Request()
                if live:
                    if handle is None:
                        live.latch_unknown('LIVE_CANCEL_GOAL_UUID_UNOBSERVED')
                        raise ValueError('LIVE_CANCEL_GOAL_UUID_UNOBSERVED')
                    cancel_request.goal_info.goal_id=handle.goal_id
                future=cancel.call_async(cancel_request); deadline=time.monotonic()+5
                while not future.done() and time.monotonic()<deadline: tick(False)
                ack={'done':future.done(),'return_code':int(future.result().return_code) if future.done() else None,
                     'goals_canceling_count':len(future.result().goals_canceling) if future.done() else None,
                     'goals_canceling_ids':[bytes(g.goal_id.uuid).hex() for g in future.result().goals_canceling] if future.done() else None,
                     'goal_info_stamps_ns':[g.stamp.sec*10**9+g.stamp.nanosec for g in future.result().goals_canceling] if future.done() else None}
                cancellation.append(ack);emit('CANCEL_ACK',ack)
                for _ in range(15): tick(False)
        until=world.current_time+3
        while app.is_running() and world.current_time<until: tick(False)
        stop=None;stop_error=None;counts=dict(active_command_count=None,pending_command_count=None)
        try:
            counts=command_counts(statuses)
            if any(counts.values()): raise ValueError('Native commands remain active')
            stop=verified_stop(list(history))
        except ValueError as stop_exc: stop_error=str(stop_exc)
        holding=False;holding_error=None
        try:
            check_live(monitor_packet,packet['binding'],sample())
            holding=True
        except ValueError as hold_exc: holding_error=str(hold_exc)
        status=dict(success=False,error=str(exc),scope='ISOLATED_SIM_TRANSPORT_TO_D_WAIT',
            transport_goal_sent=sent,cancellation=cancellation,stop_verified=stop is not None,
            stop_metrics=stop,stop_error=stop_error,hardware_execution_allowed=False,
            assembly_completed=False,gripper_open_issued=False,contact_execution_issued=False,
            automatic_retry=False,handoff_status='BLOCKED',holding_confirmed=holding,
            holding_error=holding_error,final_observation=sample(),native_command_counts=counts)
        if action_future is not None and action_future.done():
            observe_result()
            response=action_future.result()
            status['native_action_result']=dict(status=int(response.status),error_code=int(response.result.error_code),
                                               error_string=response.result.error_string)
        if foreground_cancel_attempted:
            bound_uuid=bytes(handle.goal_id.uuid).hex()
            ack_ok=(len(cancellation)==1 and cancellation[0]['done'] and cancellation[0]['return_code']==0 and cancellation[0]['goals_canceling_ids']==[bound_uuid])
            terminal=status.get('native_action_result') or {}
            status.update(conservative_stop=True,conservative_stop_receipt=foreground_cancel_receipt,conservative_stop_verified=bool(ack_ok and terminal.get('status')==5 and terminal.get('error_code')==0 and stop is not None and holding and not guard_hits and counts['active_command_count']==counts['pending_command_count']==0),cancel_request_count=1,cancel_bound_uuid=bound_uuid,cancel_send_outcome_unknown=foreground_cancel_future is None,risk_qualified=False,point3D_error_m=None,automatic_resume=False)
            if foreground_cancel_future is not None:save(out/'foreground_cancel_ack.json',cancellation[0])
        status['expected_stop_test_verified']=(engine=='cumotion' and
            getattr(args,'transport_stop_after_s',None) is not None and (out/'stop_injection.json').exists() and
            verified_cumotion_stop_test(status,json.loads((out/'stop_injection.json').read_text()),guard_hits))
        save(out/'transport_status.json',status)
        if live and str(exc)=='OBSTACLE_RESPONSE_HOLD':
            if not (status['stop_verified'] and status['holding_confirmed'] and
                    status.get('native_action_result',{}).get('status')==5 and
                    status['native_action_result']['error_code']==0 and
                    counts['active_command_count']==counts['pending_command_count']==0):
                live.latch_failure('LIVE_STOP_TERMINAL_HOLD_UNCONFIRMED')
                raise ValueError('LIVE_STOP_TERMINAL_HOLD_UNCONFIRMED')
            live.begin_hold(status,packet,request,list(history))
            set_phase('OBSTACLE_HOLD_WAIT_FRESH_SDK_PHYSICS_DEPTH_RUNNING')
            old_stop=deepcopy(status)
            old_uuid=bytes(handle.goal_id.uuid).hex()
            save(out/('old_goal.'+old_uuid+'.stop.json'),old_stop)
            def adopt_resume(goal,new_future,audit,adoption):
                nonlocal request,packet,monitor_packet,resume_world_request,resume_submission
                nonlocal handle,action_future,action_result,result_recorded,sent_sim_time,sent
                if resume_submission is not None:raise ValueError('RESUME_SUBMISSION_ALREADY_ADOPTED')
                request=deepcopy(adoption['request']);packet=deepcopy(adoption['packet'])
                monitor_packet=dict(packet,attachment=request['attachment'])
                resume_world_request=deepcopy(adoption['world_request'])
                save(context_path,packet['binding'])
                handle=None;action_future=None;action_result=None;result_recorded=False
                sent=True;sent_sim_time=world.current_time
                resume_submission=dict(goal=goal,future=new_future,audit=audit,adoption=adoption)
                live.on_resume_submitted(goal,audit,adoption)
                emit('SUBMISSION_INTENT',dict(binding=packet['binding'],request=adoption['original_request'],
                    trajectory_digest=packet['trajectory_digest'],complete_point_count=len(goal.trajectory.points),header_ns=0))
                emit('GOAL_SUBMITTED',dict(trajectory_digest=packet['trajectory_digest'],request_issued=True,new_goal_id=audit['new_goal_id']))
                set_phase('FRESH_RESUME_PENDING_ACTUAL_ACCEPTANCE')
            def fail_resume(failure):
                nonlocal resume_failure
                resume_failure=failure
                if failure['submission_attempted']:
                    live.latch_unknown('RESUME_SUBMISSION_OR_MONITOR_UNKNOWN')
                    reservation=failure['reservation']
                    if reservation is None:raise ValueError('SUBMITTED_RESUME_UUID_UNKNOWN')
                    scoped=CancelGoal.Request()
                    from unique_identifier_msgs.msg import UUID
                    scoped.goal_info.goal_id=UUID(uuid=list(bytes.fromhex(reservation['new_goal_id'])))
                    cancel_future=cancel.call_async(scoped);deadline=time.monotonic()+5
                    while not cancel_future.done() and time.monotonic()<deadline:tick(False)
                    until=world.current_time+3
                    while app.is_running() and world.current_time<until:tick(False)
                    quiet=command_counts(statuses)
                    if any(quiet.values()):raise ValueError('RESUME_CLEANUP_COMMANDS_PENDING')
                    cleanup_stop=verified_stop(list(history))
                    check_live(monitor_packet,json.loads(context_path.read_text()),history[-1],contact_grace_s=.02)
                    ack=cancel_future.result() if cancel_future.done() else None
                    save(out/'resume_scoped_cleanup.json',dict(scope='ACTUAL_SCOPED_CANCEL_AND_QUIET_CHECK_NOT_NEW_TERMINAL_PROOF',
                        new_goal_id=reservation['new_goal_id'],cancel_done=cancel_future.done(),
                        cancel_return_code=int(ack.return_code) if ack is not None else None,
                        goals_canceling_ids=[bytes(g.goal_id.uuid).hex() for g in ack.goals_canceling] if ack is not None else None,
                        command_counts=quiet,stop_metrics=cleanup_stop,holding_confirmed=True,
                        new_goal_terminal_verified=False,automatic_retry=False))
                elif (out/'stop.request').exists():
                    live.latch_user_stop('USER_STOP_DURING_RESUME_REVIEW')
                else:live.latch_failure('RESUME_REVIEW_REJECTED_NO_AUTOMATIC_RETRY')
                save(out/'resume_failure.json',{k:v for k,v in failure.items() if k not in ('future','goal')})
            live.bind_resume_sender(client=client,owner_apply_lock=owner_apply_lock,
                current_observation_provider=live.current_native_observation,on_submitted=adopt_resume,on_failure=fail_resume)
            # Keep this same action client/handle and the original actual
            # cancel result. No after-return dispatcher or synchronous SDK.
            while app.is_running() and not (out/'shutdown.request').exists():
                tick(False)
                held=history[-1]
                if (out/'stop.request').exists():
                    live.latch_user_stop('USER_STOP_DURING_OBSTACLE_HOLD');break
                check_live(monitor_packet,json.loads(context_path.read_text()),held,contact_grace_s=.02)
                if guard_hits:
                    live.latch_failure('UNEXPECTED_HELD_CONTACT');raise ValueError('UNEXPECTED_HELD_CONTACT:'+str(guard_hits[-1]))
                current_counts=command_counts(statuses)
                if any(current_counts.values()):
                    live.latch_unknown('COMMANDS_DURING_VERIFIED_HOLD');raise ValueError('COMMANDS_DURING_VERIFIED_HOLD')
                current_stop=verified_stop(list(history))
                live.publish_hold(held,statuses,list(history),current_stop)
                # Consumer readiness alone does not dispatch. The first unit
                # has no fresh model/job/SDK result and stays in normal HOLD.
                resume=live.poll_resume()
                if resume_failure is not None:
                    raise ValueError('FRESH_RESUME_FAILED_OWNER_HOLD:'+resume_failure['reason'])
                if resume is not None and resume.get('native_send_called') is True:
                    if resume_submission is None:raise ValueError('NEW_GOAL_NOT_ADOPTED_BY_EXISTING_D')
                    try:
                        handle=wait(resume_submission['future'])
                        reserved=resume_submission['audit']['new_goal_id']
                        if bytes(handle.goal_id.uuid).hex()!=reserved:raise ValueError('ACCEPTED_RESUME_UUID_MISMATCH')
                        stamp=getattr(handle,'stamp',None)
                        emit('GOAL_ACCEPTED',dict(accepted=bool(handle.accepted),goal_id=reserved,
                            goal_stamp_ns=stamp.sec*10**9+stamp.nanosec if stamp is not None else None))
                        if not handle.accepted:raise ValueError('FRESH_RESUME_NATIVE_REJECTED')
                        action_future=handle.get_result_async()
                        set_phase('FRESH_RESUME_TRANSPORT_HOLDING')
                        final_status=finish_active_goal()
                        final_status.update(old_obstacle_stop=old_stop,new_goal_id=reserved,
                            live_hold_scope='ACTUAL_OLD_DEPTH_CANCEL_STOP_NEW_NATIVE_GOAL_TARGET_VERIFIED')
                        save(out/'transport_status.json',final_status)
                        live.close();return final_status
                    except Exception as resume_exc:
                        fail_resume(dict(reason=str(resume_exc),submission_attempted=True,
                            reservation=resume_submission['audit']['reservation'],future=resume_submission['future'],
                            goal=resume_submission['goal'],audit=resume_submission['audit']))
                        raise
            live.close()
            status['live_hold_scope']='ACTUAL_CANCEL_STOP_ROLLING_SENSOR_OWNER_NO_RESUME_EXECUTED'
            save(out/'transport_status.json',status)
        if hooks:
            hooks['completed'](status,packet,request,list(history))
            if str(exc)=='OBSTACLE_RESPONSE_HOLD':return status
        if status['expected_stop_test_verified'] or status.get('conservative_stop_verified',False):return status
        raise
    finally:
        timeline.pause();trace.close()
