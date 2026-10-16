"""Non-executable SIM D measurement publication at existing lifecycle hooks.

No sampling, controller, planner, geometry construction or automatic resume.
The caller supplies original ticks and already checked D STOP/holding results.
"""
from collections import deque
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import uuid

from isaac_sim.real_execution.preflight import digest

CAUSE='FRESH_FOREGROUND_CONSERVATIVE_STOP'
ACCELERATION='ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE'


def ref(path):
    path=Path(path).resolve()
    return dict(path=str(path),sha256=sha256(path.read_bytes()).hexdigest())


def exclusive(path,value):
    path=Path(path)
    with path.open('x') as stream:stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n')
    return ref(path)


class SimStopOwnerPublication:
    """One actual accepted goal; versions originate in this new D execution."""
    def __init__(self,folder,binding,request_path,wire_path):
        import yaml
        self.folder=Path(folder);self.folder.mkdir(exist_ok=False)
        self.identity={k:deepcopy(binding[k]) for k in ('session_id','clock_basis','clock_epoch')}
        if self.identity['clock_basis']!='SIM_TIME' or type(self.identity['clock_epoch']) is not int:raise ValueError('SIM_OWNER_SOURCE_CLOCK_REQUIRED')
        self.request_ref=ref(request_path);self.request=yaml.safe_load(Path(request_path).read_text())
        self.wire_ref=ref(wire_path);self.wire=json.loads(Path(wire_path).read_text())
        self.context_path=self.folder.parent/'transport.latest_context.json';self.context=json.loads(self.context_path.read_text())
        anchors={k:self.request[k] for k in ('current_revision','world_revision','model_digest','reservation_id','reservation_generation','planning_request_digest')}
        for context_key,request_key in [('job_id','job_id'),('request_id','request_id'),('workflow_generation','workflow_generation'),('source_epoch','source_epoch'),('design_version','design_version'),('plan_id','plan_id'),('step_id','step_id'),('current_revision','input_current_revision'),('world_revision','world_state_revision'),('profile_id','frame_profile_id'),('profile_version','frame_profile_version')]:anchors[context_key]=self.request['a_context'][request_key]
        if any(digest(self.context.get(k))!=digest(value) for k,value in anchors.items()):raise ValueError('OWNER_SELECTED_A_REQUEST_CONTEXT_MISMATCH')
        self.context_ref=exclusive(self.folder/'selected_context.json',self.context)
        self.execution_id='sim-D-'+uuid.uuid4().hex;self.execution_version=0;self.goal_id=None;self.goal_version=0
        self.cancel_generation=0;self.replan_sequence=0;self.terminal=None;self.status_ref=None
        self.history=deque(maxlen=1024);self.published_frames=set();self.last_state_sequence=-1;self.accepted_ref=None
        self._event('EXECUTION_INITIALIZED',None)

    def _event(self,kind,source_s):
        value=dict(kind=kind,source_s=source_s,execution_id=self.execution_id,execution_version=self.execution_version,goal_id=self.goal_id,goal_version=self.goal_version,cancel_generation=self.cancel_generation,replan_sequence=self.replan_sequence,**self.identity)
        with (self.folder/'lifecycle.jsonl').open('a') as stream:stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n')

    def accepted(self,goal_id,source_s):
        if self.goal_id is not None:raise ValueError('OWNER_DUPLICATE_ACCEPTANCE')
        if ref(self.request_ref['path'])!=self.request_ref or ref(self.wire_ref['path'])!=self.wire_ref:raise ValueError('OWNER_SELECTED_INPUT_CHANGED')
        self.goal_id=goal_id;self.goal_version=1;self.execution_version=1
        value=dict(scope='ACCEPTED_NATIVE_GOAL_BINDING',**self.identity,execution_id=self.execution_id,execution_version=self.execution_version,goal_id=goal_id,goal_version=1,cancel_generation=0,replan_sequence=0,accepted_source_s=source_s,original_request=self.request_ref,accepted_wire=self.wire_ref,current_context=self.context_ref,binding=deepcopy(self.context),active_wire_digest=digest(self.wire),model_digest=self.request['model_digest'],model_manifest_sha256=self.request['model_bundle']['manifest_sha256'],**{k:deepcopy(self.request[k]) for k in ('a_context','reservation_binding','current_revision','world_revision')},execution_allowed=False,hardware_execution_allowed=False)
        self.accepted_ref=exclusive(self.folder/'accepted.json',value);self._event('ACTUAL_GOAL_ACCEPTED',source_s)
        return self.accepted_ref

    def cancel_requested(self,goal_id,source_s):
        if goal_id!=self.goal_id or self.cancel_generation:raise ValueError('OWNER_CANCEL_UUID_OR_GENERATION_CHANGED')
        self.cancel_generation=1;self._event('ACTUAL_CANCEL_CALL_RETURNED',source_s)

    def terminal_result(self,goal_id,status,error_code,source_s):
        if goal_id!=self.goal_id or self.terminal is not None:raise ValueError('OWNER_TERMINAL_UUID_OR_DUPLICATE')
        self.terminal=dict(goal_id=goal_id,status=status,error_code=error_code,source_s=source_s)
        self._event('ACTUAL_GOAL_TERMINAL',source_s)

    def observe(self,record,counts):
        if self.goal_id is None or self.terminal is None:return
        if self.history and record['time_s']<=self.history[-1]['stamp_s']:raise ValueError('OWNER_SOURCE_HISTORY_REVERSED')
        if record.get('actual_acceleration_rad_s2') is None:return
        if record.get('acceleration_method')!=ACCELERATION:raise ValueError('OWNER_ORIGINAL_ACCELERATION_METHOD_REQUIRED')
        value=dict(stamp_s=record['time_s'],q_rad=deepcopy(record['q_rad']),v_rad_s=deepcopy(record['velocity_rad_s'][:6]),a_rad_s2=deepcopy(record['actual_acceleration_rad_s2']),raw_observed_a_rad_s2=None,acceleration_method=ACCELERATION,grip_rad=record['grip_rad'],attachment_tcp_to_block=deepcopy(record['attachment']),contact_fingers=deepcopy(record['contact_fingers']),controller_states=deepcopy(record['tracking']['controller_states']),command_counts=deepcopy(counts))
        self.history.append(value)

    def verified_stop(self,status_path):
        status=json.loads(Path(status_path).read_text())
        if (status.get('conservative_stop_verified') is not True or status.get('cancel_bound_uuid')!=self.goal_id or status.get('cancel_request_count')!=1 or status.get('cancel_send_outcome_unknown') is not False or self.cancel_generation!=1 or self.terminal is None or self.terminal['status']!=5 or self.terminal['error_code']!=0):raise ValueError('OWNER_ACTUAL_CONSERVATIVE_STOP_REQUIRED')
        self.status_ref=ref(status_path);self._event('ORIGINAL_D_STOP_AND_HOLD_VERIFIED',status['final_observation']['time_s'])

    def publish_frame(self,frame_ref,frame,*,now_s,limits,limits_ref,builder,verified_stop):
        """Existing source worker calls only after actual STOP; failure is HOLD.

        No absent controller acceleration/versions/clock are synthesized. The
        finite-difference A already comes from the original native recorder.
        """
        if self.status_ref is None:return None
        if ref(limits_ref['path'])!=limits_ref or digest(json.loads(Path(limits_ref['path']).read_text()))!=digest(limits):raise ValueError('OWNER_SELECTED_LIMITS_CHANGED')
        if digest(json.loads(self.context_path.read_text()))!=digest(self.context):raise ValueError('OWNER_CURRENT_A_CONTEXT_CHANGED')
        seq=frame['frame_seq']
        if seq in self.published_frames:return None
        if frame['source_association']['state_physics_step_index']<=self.last_state_sequence:raise ValueError('OWNER_SOURCE_SEQUENCE_REVERSED')
        if frame['robot_state_stamp_s']!=frame['transform_stamp_s']:raise ValueError('OWNER_FRAME_STATE_TF_TICK_CHANGED')
        stamp=frame['robot_state_stamp_s'];history=list(self.history)
        if any((self.folder.parent/name).exists() for name in ('stop.request','shutdown.request')):raise ValueError('OWNER_USER_STOP_OR_SHUTDOWN_LATCHED')
        if not history or history[-1]['stamp_s']!=now_s:raise ValueError('OWNER_CURRENT_PVA_CLOCK_NOT_AVAILABLE')
        matches=[x for x in history if x['stamp_s']==stamp]
        if len(matches)!=1:raise ValueError('OWNER_EXACT_SOURCE_PVA_NOT_AVAILABLE')
        last=matches[0]
        for a,b in [('q_rad','q_rad'),('grip_rad','grip_rad'),('attachment_tcp_to_block','attachment_tcp_to_block')]:
            if digest(last[a])!=digest(frame[b]):raise ValueError('OWNER_RAW_FRAME_CHANGED:'+a)
        if any(self.identity[k]!=frame[k] for k in self.identity):raise ValueError('OWNER_FRAME_IDENTITY_CHANGED')
        if not 0<=now_s-stamp<=limits['max_state_age_s']:raise ValueError('OWNER_CURRENT_SOURCE_STALE')
        window=[x for x in history if max(self.terminal['source_s'],stamp-1.)<=x['stamp_s']<=stamp]
        if len(window)<2 or window[-1]['stamp_s']-window[0]['stamp_s']<limits['min_stop_observation_s']:raise ValueError('OWNER_POST_TERMINAL_WINDOW_NOT_READY')
        if any(any(x['command_counts'].values()) or x['contact_fingers']!=['rg2_left_inner_finger','rg2_right_inner_finger'] for x in window):raise ValueError('OWNER_CURRENT_HOLD_COUNTS_OR_CONTACT')
        stop_metrics=verified_stop([dict(time_s=x['stamp_s'],q_rad=x['q_rad'],grip_rad=x['grip_rad']) for x in window])
        hold_rows=[x for x in history if window[0]['stamp_s']<=x['stamp_s']<=now_s]
        if any(any(x['command_counts'].values()) or x['contact_fingers']!=last['contact_fingers'] for x in hold_rows):raise ValueError('OWNER_CURRENT_TAIL_HOLD_CHANGED')
        reference=[];latest_reference=[]
        canonical_joints=["joint_"+str(i) for i in range(1,7)]
        for row in hold_rows:
            previous_header=None
            for state in row['controller_states']:
                if state.get('joint_names')!=canonical_joints:raise ValueError('OWNER_CONTROLLER_REFERENCE_JOINT_NAMES_REQUIRED')
                header=state['header_ns'];received=state['received_world_time_s']
                if type(header) is not int or header<0 or not 0<=header/1e9<=received<=row['stamp_s']:raise ValueError('OWNER_CONTROLLER_REFERENCE_CLOCK_ORDER')
                if previous_header is not None and header<previous_header:raise ValueError('OWNER_CONTROLLER_REFERENCE_HEADER_REVERSED')
                previous_header=header
                p=state['reference'];values={k:p[src] for k,src in [('q_rad','positions'),('v_rad_s','velocities'),('a_rad_s2','accelerations')]}
                if any(len(x)!=6 for x in values.values()):raise ValueError('OWNER_CONTROLLER_REFERENCE_PVA_REQUIRED')
                reference.append(dict(stamp_s=state['header_ns']/1e9,received_world_time_s=state['received_world_time_s'],**values))
            if not row['controller_states']:raise ValueError('OWNER_CONTROLLER_REFERENCE_MISSING')
            latest_reference.append(reference[-1])
        if not reference:raise ValueError('OWNER_CONTROLLER_REFERENCE_MISSING')
        for previous,current in zip(latest_reference,latest_reference[1:]):
            if current['stamp_s']<previous['stamp_s'] or current['received_world_time_s']<previous['received_world_time_s']:raise ValueError('OWNER_CONTROLLER_REFERENCE_PROGRESS_REVERSED')
        if not (latest_reference[-1]['stamp_s']>latest_reference[0]['stamp_s'] and latest_reference[-1]['received_world_time_s']>latest_reference[0]['received_world_time_s']):raise ValueError('OWNER_CONTROLLER_REFERENCE_ONLY_REPEATED_CACHE')
        if not all(0<=now_s-latest_reference[-1][key]<=limits['max_state_age_s'] for key in ('stamp_s','received_world_time_s')):raise ValueError('OWNER_CONTROLLER_REFERENCE_STALE')
        desired_values={k:reference[-1][k] for k in ('q_rad','v_rad_s','a_rad_s2')}
        if any(any(row[k]!=desired_values[k] for k in desired_values) for row in reference):raise ValueError('OWNER_REFERENCE_NOT_CONSTANT_DURING_HOLD')
        if any(abs(x)>0 for k in ('v_rad_s','a_rad_s2') for x in desired_values[k]):raise ValueError('OWNER_REFERENCE_NOT_NATIVE_HOLD')
        if ref(self.status_ref['path'])!=self.status_ref:raise ValueError('OWNER_ORIGINAL_STATUS_CHANGED')
        # Source frame and state use original robot/TF world time. Image time is
        # preserved separately in frame_ref, including rational representation.
        from isaac_sim.depth_obstacles.novel_depth.expected_depth import _clock_review,_association_status
        source_clock_review=_clock_review(frame)
        if _association_status(frame,clock_review=source_clock_review)!='ACTUAL_SOURCE_TICK':raise ValueError('OWNER_INDEPENDENT_RAW_SOURCE_PROOF_REQUIRED')
        folder=self.folder/f'frame_{seq:06d}';folder.mkdir(exist_ok=False)
        source_clock_ref=exclusive(folder/'original_source_clock_review.json',source_clock_review)
        state=dict(source_kind='SIM_SAVED_SNAPSHOT',**self.identity,state_sequence=frame['source_association']['state_physics_step_index'],source_stamp_s=stamp,frame_input_ref=frame_ref,source_clock_review_ref=source_clock_ref,**{k:deepcopy(last[k]) for k in ('q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block','raw_observed_a_rad_s2','acceleration_method')})
        state['digest']=digest(state);state_ref=exclusive(folder/'current_state.json',state)
        owner=dict(**self.identity,execution_id=self.execution_id,execution_version=self.execution_version,goal_id=self.goal_id,goal_version=self.goal_version,cancel_generation=self.cancel_generation,replan_sequence=self.replan_sequence,owner_limits_ref=limits_ref,single_writer='D',mode='OBSTACLE_HOLD',user_stop_latched=False,failure_latched=False,outcome_unknown=False,now_s=now_s,state_stamp_s=stamp,state_digest=state['digest'],state_sequence=state['state_sequence'],snapshot_version=seq,snapshot_digest=sha256(json.dumps(frame,sort_keys=True,allow_nan=False).encode()).hexdigest(),**{k:deepcopy(last[k]) for k in ('q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block','contact_fingers')},active_command_count=0,pending_command_count=0,pending_cancel_count=0,model_digest=self.request['model_digest'],model_manifest_sha256=self.request['model_bundle']['manifest_sha256'],original_goal=deepcopy(self.request['goal']),active_wire_digest=digest(self.wire),**{k:deepcopy(self.request[k]) for k in ('a_context','reservation_binding','current_revision','world_revision')})
        observed_pvt={k:owner[k] for k in desired_values};desired=dict(**self.identity,stamp_s=reference[-1]['stamp_s'],**desired_values)
        controller_ref=exclusive(folder/'controller_reference.json',dict(scope='ORIGINAL_CONTROLLER_STATE_HOLD_WINDOW',rows=reference))
        clocks=[p for p in frame['source_refs'] if Path(p['path']).name=='clock_observation.json']
        if len(clocks)!=1:raise ValueError('OWNER_ORIGINAL_CLOCK_REF_REQUIRED')
        association=dict(scope='VERIFIED_CONTROLLER_REFERENCE_OBSERVATION_ASSOCIATION',method='CONFIRMED_CONTROLLER_HOLD_INTERVAL',reference_held_confirmed=True,**self.identity,desired_stamp_s=desired['stamp_s'],observed_stamp_s=stamp,desired_pvt_digest=digest(desired_values),observed_pvt_digest=digest(observed_pvt),valid_from_s=window[0]['stamp_s'],valid_until_s=now_s,evidence=dict(clock=clocks[0],controller_reference=controller_ref,observed_state=state_ref))
        desired['source_time_association']=exclusive(folder/'reference_clock_association.json',association);owner['desired']=desired
        from isaac_sim.real_execution.native_boundary import OWNER_KEYS
        record=dict(scope='ACTUAL_SIM_CONSERVATIVE_FOREGROUND_STOP_RECORD',source_kind='SIM_OWNER_RECORD',state_source_kind='SIM_SAVED_SNAPSHOT',**{k:owner[k] for k in OWNER_KEYS},stop_reason=CAUSE,old_goal_terminal_status='CANCELED',cancel_acknowledged=True,cancel_terminal_stamp_s=self.terminal['source_s'],active_command_count=0,pending_command_count=0,pending_cancel_count=0,velocity_method='PHYSX_RETURNED_VELOCITY',acceleration_method=ACCELERATION,samples=[{k:deepcopy(x[k]) for k in ('stamp_s','q_rad','v_rad_s','a_rad_s2')} for x in window])
        record['record_digest']=digest(record);owner['stop_record']=record
        original=json.loads(Path(self.status_ref['path']).read_text());ack=original['cancellation'][0]
        evidence=dict(cancel_ack=exclusive(folder/'cancel_ack.json',ack),terminal_result=exclusive(folder/'terminal_result.json',self.terminal),command_counts=exclusive(folder/'command_counts.json',dict(coverage='D_OWNER_AND_ARM_GRIPPER_ACTION_STATUS',active_command_count=0,pending_command_count=0,pending_cancel_count=0,scope='ACTUAL_POST_TERMINAL_RAW_SAMPLE_WINDOW')),holding=exclusive(folder/'holding.json',dict(holding_confirmed=True,**{k:owner[k] for k in ('contact_fingers','grip_rad','attachment_tcp_to_block')})),controller_stop=exclusive(folder/'controller_stop.json',dict(stop_verified=True,goal_id=self.goal_id,verification_method='ORIGINAL_D_POSITION_HISTORY_STOP_AND_SAME_UUID_TERMINAL',state_stamp_s=stamp,samples_digest=digest(record['samples']),metrics=stop_metrics,source_status_ref=self.status_ref)))
        result=builder(folder/'verified',owner,limits,evidence=evidence,accepted_ref=self.accepted_ref,original_request_ref=self.request_ref,dispatch_ref=ref(self.folder.parent/'foreground_cancel_dispatch.json'),current_state_ref=state_ref,frame_ref=frame_ref,accepted_wire_ref=self.wire_ref,observation_scope='CURRENT_D_STOP_OBSERVATION_EXPORT_ONLY')
        result=dict(result,owner_limits_ref=limits_ref)
        result_ref=exclusive(folder/'publication.json',result);self.published_frames.add(seq);self.last_state_sequence=state['state_sequence']
        latest=self.folder/'latest.json';temp=self.folder/'latest.tmp';temp.write_text(json.dumps(dict(scope='NONEXECUTABLE_CURRENT_D_STOP_OWNER_POINTER',publication=result_ref,owner_ref=result['owner_ref'],state_ref=state_ref,frame_ref=frame_ref,accepted_ref=self.accepted_ref,owner_limits_ref=limits_ref,now_s=now_s,state_stamp_s=stamp,valid_until_source_s=stamp+limits['max_state_age_s'],freshness_requires_independent_current_clock=True,execution_allowed=False,hardware_execution_allowed=False),sort_keys=True)+'\n');temp.replace(latest)
        return result_ref
