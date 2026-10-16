"""Small owner event recorder and archive projection. No executor, timers or commands."""
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
from .engine_receipt import sha
from .preflight import digest
from .native_boundary import OWNER_KEYS,review_stop,same_owner

EVENTS=('SUBMISSION_INTENT','GOAL_SUBMITTED','GOAL_ACCEPTED','CANCEL_REQUEST','CANCEL_ACK','GOAL_RESULT',
        'CONTROLLER_STATUS','COMMAND_COUNTS','PHYSICS_SAMPLE','IMAGE_SAMPLE','GOAL_APPLIED',
        'DEPTH_RISK','PLAN_REQUEST','SDK_RESULT','RESUME_REVIEW','TARGET_REVIEW')


def record_owner_event(kind,sequence,context,payload,*,observed_stamp_s,evidence):
    """Owner supplies IDs/clock and unmodified data; absent observed stamps remain null."""
    if kind not in EVENTS or type(sequence) is not int or sequence<0:raise ValueError('OWNER_EVENT_KIND_SEQUENCE')
    if observed_stamp_s is not None and (type(observed_stamp_s) not in (int,float) or not np.isfinite(observed_stamp_s)):raise ValueError('OWNER_EVENT_STAMP')
    record=dict(schema='native-owner-event/0.1',event=kind,record_sequence=sequence,context=deepcopy(context),
                original_payload=deepcopy(payload),observed_stamp_s=observed_stamp_s,stamp_semantics='OWNER_OBSERVATION_NOT_SENSOR_ACQUISITION',
                evidence=deepcopy(evidence),execution_allowed=False,hardware_execution_allowed=False)
    record['record_digest']=digest(record);return record


def write_owner_event(stream,*args,**kwargs):
    """Append to owner's supplied open log; no file open or control side effect here."""
    record=record_owner_event(*args,**kwargs);stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n');stream.flush();return record


def replay_owner_records(records,*,expected_context=None,limits=None):
    original=deepcopy(records);previous=-1;last_stamp=None;context=None;by_kind={};gaps=[];pins={}
    for r in original:
        if r['schema']!='native-owner-event/0.1' or r['record_digest']!=digest({k:v for k,v in r.items() if k!='record_digest'}):raise ValueError('OWNER_EVENT_CHANGED')
        if type(r['record_sequence']) is not int or r['record_sequence']<=previous:raise ValueError('OWNER_EVENT_REORDERED')
        previous=r['record_sequence'];stamp=r['observed_stamp_s']
        if stamp is not None:
            if last_stamp is not None and stamp<last_stamp:raise ValueError('OWNER_CLOCK_REVERSED')
            last_stamp=stamp
        evidence=r['evidence']
        if evidence is not None:
            path=evidence['path'];expected=evidence['sha256']
            if path not in pins:pins[path]=sha(path)
            if pins[path]!=expected:raise ValueError('OWNER_EVENT_SOURCE_CHANGED')
        c=r['context']
        if context is None:context=deepcopy(c)
        for key in ('session_id','clock_basis','clock_epoch','execution_id','goal_id'):
            if key in c and key in context and (type(c[key]) is not type(context[key]) or c[key]!=context[key]):raise ValueError('OWNER_EVENT_CONTEXT_CHANGED:'+key)
        old_generation=context.get('cancel_generation');new_generation=c.get('cancel_generation')
        if old_generation is not None and new_generation is not None and old_generation!=new_generation:
            if r['event']!='CANCEL_REQUEST' or type(new_generation) is not int or type(old_generation) is not int or new_generation!=old_generation+1:raise ValueError('OWNER_CANCEL_GENERATION_CHANGED_OUTSIDE_REQUEST')
        context=deepcopy(c)
        if expected_context is not None:
            for key in ('session_id','clock_basis','clock_epoch','execution_id','goal_id'):
                if c.get(key) is None:gaps.append('UNOBSERVED_'+key);continue
                if type(c[key]) is not type(expected_context[key]) or c[key]!=expected_context[key]:raise ValueError('OWNER_NOT_TARGET_CONTEXT:'+key)
        by_kind.setdefault(r['event'],[]).append(r)
    if not original:return dict(status='HOLD_OWNER_EVENTS_ABSENT',owner_context=None,dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False)
    # No record ordering inference from a summary file's own save time.
    for key in OWNER_KEYS:
        if context.get(key) is None:gaps.append('UNOBSERVED_'+key)
    for key in ('single_writer','mode','user_stop_latched','failure_latched','outcome_unknown'):
        if context.get(key) is None:gaps.append('UNOBSERVED_'+key)
    if context.get('user_stop_latched') is True or context.get('failure_latched') is True or context.get('outcome_unknown') is True:
        gaps.append('STOP_FAILURE_UNKNOWN_NO_AUTO_RESUME')
    if context.get('mode')!='OBSTACLE_HOLD':gaps.append('NOT_NORMAL_OBSTACLE_HOLD')
    for kind in ('GOAL_ACCEPTED','CANCEL_REQUEST','CANCEL_ACK','GOAL_RESULT','COMMAND_COUNTS','PHYSICS_SAMPLE'):
        if not by_kind.get(kind):gaps.append('UNOBSERVED_'+kind)
    for kind in ('GOAL_ACCEPTED','CANCEL_REQUEST','CANCEL_ACK','GOAL_RESULT'):
        if by_kind.get(kind) and by_kind[kind][-1]['observed_stamp_s'] is None:gaps.append('UNOBSERVED_'+kind+'_STAMP')
    if by_kind.get('GOAL_ACCEPTED') and by_kind['GOAL_ACCEPTED'][-1]['original_payload'].get('accepted') is not True:gaps.append('NO_ACCEPTED_GOAL_OBSERVATION')
    result=by_kind.get('GOAL_RESULT',[{}])[-1].get('original_payload',{})
    matched=[r for r in by_kind.get('CANCEL_ACK',[]) if context.get('goal_id') is not None and context['goal_id'] in r['original_payload'].get('goals_canceling_ids',[])]
    ack_record=matched[0] if matched else by_kind.get('CANCEL_ACK',[{}])[-1]
    ack=ack_record.get('original_payload',{})
    counts=by_kind.get('COMMAND_COUNTS',[{}])[-1].get('original_payload',{})
    if result.get('status')!=5 or result.get('error_code')!=0:gaps.append('NO_CANCELED_TERMINAL_SUCCESS')
    if ack.get('done') is not True or ack.get('return_code')!=0:gaps.append('NO_CONFIRMED_CANCEL_ACK')
    if not isinstance(ack.get('goals_canceling_ids'),list) or context.get('goal_id') not in ack.get('goals_canceling_ids',[]):gaps.append('CANCEL_ACK_GOAL_ID_UNOBSERVED')
    if counts.get('coverage')!='D_OWNER_AND_ARM_GRIPPER_ACTION_STATUS':gaps.append('OWNER_COUNT_COVERAGE_UNVERIFIED')
    for k in ('active_command_count','pending_command_count','pending_cancel_count'):
        if type(counts.get(k)) is not int or counts[k]!=0:gaps.append('UNVERIFIED_ZERO_'+k)
    terminal_stamp=by_kind.get('GOAL_RESULT',[{}])[-1].get('observed_stamp_s')
    sample_records=[r for r in by_kind.get('PHYSICS_SAMPLE',[]) if terminal_stamp is None or r['original_payload'].get('stamp_s',-1)>=terminal_stamp]
    samples=[r['original_payload'] for r in sample_records]
    if expected_context is not None:
        for r in sample_records+by_kind.get('COMMAND_COUNTS',[])[-1:]:
            for key in OWNER_KEYS:
                if r['context'].get(key) is None:gaps.append('UNOBSERVED_'+key)
                elif type(r['context'][key]) is not type(expected_context[key]) or r['context'][key]!=expected_context[key]:raise ValueError('OWNER_POST_STOP_CONTEXT_CHANGED:'+key)
    if not samples:gaps.append('POST_TERMINAL_SAMPLES_ABSENT')
    if by_kind.get('COMMAND_COUNTS') and by_kind['COMMAND_COUNTS'][-1]['observed_stamp_s'] is None:gaps.append('COMMAND_COUNTS_OBSERVED_STAMP_UNVERIFIED')
    for sample in samples:
        if any(sample.get(k) is None for k in ('q_rad','v_rad_s','a_rad_s2','stamp_s','attachment')):gaps.append('RAW_QVA_ATTACHMENT_INCOMPLETE')
    if limits is None:gaps.append('OWNER_REVIEW_LIMITS_NOT_SELECTED')
    if any(sha(p)!=v for p,v in pins.items()):raise ValueError('OWNER_SOURCE_CHANGED_DURING_REPLAY')
    if gaps:
        return dict(status='HOLD_OWNER_EVIDENCE_INCOMPLETE',gaps=sorted(set(gaps)),original_records=original,
            observed_cancel_ack=ack,observed_terminal_result=result,original_command_counts=counts,raw_sample_count=len(samples),
            owner_context=None,acceptance_stamp_s=by_kind.get('GOAL_ACCEPTED',[{}])[-1].get('observed_stamp_s'),
            apply_stamp_s=by_kind.get('GOAL_APPLIED',[{}])[-1].get('observed_stamp_s'),native_switch_verified=False,
            dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False)
    # Full hook records may be projected only after owner supplied complete evidence and thresholds.
    accepted=by_kind['GOAL_ACCEPTED'][-1];cancel=by_kind['CANCEL_REQUEST'][0];terminal=by_kind['GOAL_RESULT'][-1]
    if not accepted['observed_stamp_s']<=cancel['observed_stamp_s']<=ack_record['observed_stamp_s']<=terminal['observed_stamp_s']<=samples[0]['stamp_s']:raise ValueError('OWNER_LIFECYCLE_ORDER')
    owner=deepcopy(expected_context or context)
    same_owner(context,owner)
    record={k:owner[k] for k in OWNER_KEYS}
    record.update(source_kind=context['source_kind'],state_source_kind=context['state_source_kind'],
        stop_reason=context['stop_reason'],old_goal_terminal_status='CANCELED',cancel_acknowledged=True,
        cancel_terminal_stamp_s=terminal['observed_stamp_s'],**{k:counts[k] for k in ('active_command_count','pending_command_count','pending_cancel_count')},
        velocity_method=context['velocity_method'],acceleration_method=context['acceleration_method'],
        samples=[{k:s[k] for k in ('stamp_s','q_rad','v_rad_s','a_rad_s2')} for s in samples],
        original_owner_events_digest=digest(original))
    record['record_digest']=digest(record);owner['stop_record']=record
    owner.update({k:counts[k] for k in ('active_command_count','pending_command_count','pending_cancel_count')})
    last=samples[-1]
    if owner['state_stamp_s']!=last['stamp_s'] or any(owner[k]!=last[k] for k in ('q_rad','v_rad_s','a_rad_s2')):raise ValueError('OWNER_LATEST_NOT_RECORDED_SAMPLE')
    review_stop(owner,limits)
    return dict(status='OWNER_RECORD_PROJECTED_FOR_CPU_BOUNDARY',owner_context=owner,original_records=original,
        acceptance_stamp_s=accepted['observed_stamp_s'],apply_stamp_s=by_kind.get('GOAL_APPLIED',[{}])[-1].get('observed_stamp_s'),
        native_switch_verified=False,dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False)


def read_owner_journal(path,expected_sha):
    if sha(path)!=expected_sha:raise ValueError('CALLER_SELECTED_OWNER_JOURNAL_CHANGED')
    records=[json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if sha(path)!=expected_sha:raise ValueError('OWNER_JOURNAL_CHANGED_WHILE_READING')
    return records


def import_transport_stop_archive(run):
    """Explicit mappings from existing d_sim_transport files; no goal UUID/receipt timestamps invented."""
    root=Path(run).resolve();names=('transport_receipt.json','transport_status.json','stop_injection.json','transport_observations.jsonl','transport_controller.json')
    refs={n:dict(path=str(root/n),sha256=sha(root/n)) for n in names}
    receipt=json.loads((root/names[0]).read_text());status=json.loads((root/names[1]).read_text());injection=json.loads((root/names[2]).read_text())
    context=dict(source_kind='SIM_NATIVE_ARCHIVE',state_source_kind='SIM_SAVED_SNAPSHOT',session_id=None,clock_basis='SIM_TIME',clock_epoch=None,
        execution_id=None,goal_id=None,state_sequence=None,cancel_generation=None,replan_sequence=None,goal_version=None,
        state_digest=None,snapshot_digest=None,snapshot_version=None,single_writer=None,mode=None,stop_reason=injection['scope'],
        user_stop_latched=None,failure_latched=None,outcome_unknown=None,binding=receipt['binding'])
    events=[]
    def add(kind,payload,stamp,name,pointer):events.append(record_owner_event(kind,len(events),context,payload,observed_stamp_s=stamp,evidence=dict(refs[name],pointer=pointer)))
    add('SUBMISSION_INTENT',receipt,receipt['sim_time_s'],names[0],'')
    add('CANCEL_REQUEST',injection,injection['observation']['time_s'],names[2],'')
    # Summary list order is retained; ACK/result source receipt stamps are not present.
    for i,ack in enumerate(status['cancellation']):add('CANCEL_ACK',ack,None,names[1],f'/cancellation/{i}')
    if 'native_action_result' in status:add('GOAL_RESULT',status['native_action_result'],None,names[1],'/native_action_result')
    counts=deepcopy(status['native_command_counts']);counts.update(coverage='ARCHIVED_ARM_GRIPPER_STATUS_COUNTS_RAW_UUIDS_AND_STATUS_STAMPS_NOT_SAVED',pending_cancel_count=None)
    add('COMMAND_COUNTS',counts,None,names[1],'/native_command_counts')
    add('CONTROLLER_STATUS',json.loads((root/names[4]).read_text()),None,names[4],'')
    rows=[json.loads(line) for line in (root/names[3]).read_text().splitlines() if line.strip()]
    previous=None
    # History is original chronological samples, not lifecycle timestamp reconstruction.
    history=[]
    for idx,row in enumerate(rows):
        v=deepcopy(row.get('tracking',{}).get('physics_v_rad_s'))
        q=deepcopy(row['q_rad']);time=row['time_s'];estimate_a=None;estimate_v=None
        if previous is not None:
            dt=time-previous['time_s']
            if dt<=0:raise ValueError('ARCHIVED_OBSERVATION_REORDERED')
            estimate_v=((np.array(q)-np.array(previous['q_rad']))/dt).tolist()
            if v is not None and previous.get('tracking',{}).get('physics_v_rad_s') is not None:
                estimate_a=((np.array(v)-np.array(previous['tracking']['physics_v_rad_s']))/dt).tolist()
        history.append(dict(stamp_s=time,q_rad=q,v_rad_s=v,a_rad_s2=None,attachment=deepcopy(row['attachment']),
            grip_rad=row['grip_rad'],contact_fingers=row['contact_fingers'],position_difference_velocity_rad_s=estimate_v,
            adjacent_native_v_difference_acceleration_rad_s2=estimate_a,original_sample=row,evidence=dict(refs[names[3]],line=idx+1)))
        if time>=injection['observation']['time_s']:
            add('PHYSICS_SAMPLE',history[-1],time,names[3],f'/line/{idx+1}')
        previous=row
    if any(sha(r['path'])!=r['sha256'] for r in refs.values()):raise ValueError('ARCHIVE_CHANGED_DURING_IMPORT')
    review=replay_owner_records(events)
    controller_trace=root/'controller_tracking.jsonl'
    controller_reference=dict(path=str(controller_trace),sha256=sha(controller_trace),goal_uuid_recorded=False) if controller_trace.is_file() else None
    saved_hashes=root/'source_hashes.json';source_provenance=None
    if saved_hashes.is_file():
        original_hashes=json.loads(saved_hashes.read_text())
        source_provenance=dict(source_hashes_path=str(saved_hashes),source_hashes_sha256=sha(saved_hashes),original_source_sha256=original_hashes.get('d_sim_transport.py'))
    return dict(status='ACTUAL_ARCHIVED_STOP_EVENTS_IMPORTED_OWNER_CONTEXT_HOLD',original_archive_scope=status['scope'],
        original_stop_verified=status['stop_verified'],original_stop_metrics=status['stop_metrics'],events=events,history=history,
        review=review,source_files=refs,archived_source_provenance=source_provenance,controller_tracking_reference=controller_reference,latest_sim_owner_context=None,legacy_action_counts_not_all_controller_writers=True,
        acceptance_observed_stamp_s=None,apply_observed_stamp_s=None,native_switch_verified=False,
        dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False)


def import_capture_owner_history(run):
    """Current saved pose history remains goal-complete; no obstacle cancel is inferred."""
    root=Path(run).resolve();paths=[root/'wrist_depth/stop_evidence.json',root/'wrist_depth/state_draft.json',root/'wrist_depth/pose.json']
    pins={str(p):sha(p) for p in paths};stop=json.loads(paths[0].read_text());state=json.loads(paths[1].read_text());pose=json.loads(paths[2].read_text())
    if stop['session_id']!=state['session_id'] or pose['stamp_s']!=state['source_stamp_s']:raise ValueError('OWNER_CAPTURE_SESSION_STAMP_MIXING')
    context={k:deepcopy(state.get(k)) for k in OWNER_KEYS}
    context.update(source_kind='SIM_OWNER_RECORD',state_source_kind=state['source_kind'],single_writer=None,mode=None,
                   user_stop_latched=None,failure_latched=None,outcome_unknown=None,stop_reason=state['stop_reason'],
                   original_a_context=deepcopy(state['a_context']),original_reservation=deepcopy(state['reservation_binding']))
    events=[];evidence=dict(path=str(paths[0]),sha256=pins[str(paths[0])])
    for i,sample in enumerate(stop['samples']):
        data=deepcopy(sample)
        # The producer-provided a and observation method stay as they are; no replacement by optimizer rest.
        data['attachment']=deepcopy(sample.get('attachment'))
        data['capture_state_attachment_reference']=deepcopy(state['attachment_tcp_to_block'])
        data['attachment_source']='SAMPLE_ATTACHMENT' if 'attachment' in sample else 'UNOBSERVED_SAMPLE_ATTACHMENT'
        events.append(record_owner_event('PHYSICS_SAMPLE',i,context,data,observed_stamp_s=sample['stamp_s'],evidence=dict(evidence,pointer=f'/samples/{i}')))
    counts={k:stop.get(k) for k in ('active_command_count','pending_command_count')}
    counts.update(pending_cancel_count=None,coverage='CAPTURE_RECORDED_COUNTS_NO_ACTION_LIFECYCLE')
    events.append(record_owner_event('COMMAND_COUNTS',len(events),context,counts,observed_stamp_s=None,evidence=dict(evidence,pointer='/active_command_count')))
    if any(sha(p)!=v for p,v in pins.items()):raise ValueError('OWNER_CAPTURE_CHANGED')
    return dict(status='ACTUAL_CAPTURE_OWNER_HISTORY_REPLAYED_LIFECYCLE_HOLD',events=events,review=replay_owner_records(events),
        original_observation_contract=deepcopy(stop.get('observation')),original_stop_reason=state['stop_reason'],original_state_draft=state,
        source_files=pins,dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False)


def match_owner_to_capture(review,native):
    """Only complete same-session owner projections can join the current capture."""
    raw_context=review.get('original_records',[{}])[0].get('context',{})
    if raw_context.get('session_id') is not None and raw_context['session_id']!=native['session_id']:raise ValueError('OWNER_NOT_CURRENT_NATIVE_CAPTURE:session_id')
    b=raw_context.get('binding')
    if b is not None and b['current_revision']!=native['current_revision']:raise ValueError('OWNER_ARCHIVED_CURRENT_NOT_CURRENT_NATIVE')
    owner=review.get('owner_context')
    if owner is None:return dict(status='HOLD_OWNER_LIFECYCLE_NOT_PROJECTABLE',gaps=review.get('gaps',[]),execution_allowed=False,hardware_execution_allowed=False)
    for key,field in [('session_id','session_id'),('clock_basis','clock_basis'),('state_stamp_s','source_stamp_s')]:
        if owner[key]!=native[field]:raise ValueError('OWNER_NOT_CURRENT_NATIVE_CAPTURE:'+key)
    if owner.get('model_manifest_sha256') is None:return dict(status='HOLD_OWNER_MODEL_MANIFEST_MAPPING_ABSENT',execution_allowed=False,hardware_execution_allowed=False)
    if owner['model_manifest_sha256']!=native['model_manifest_sha256']:raise ValueError('OWNER_CURRENT_MODEL_MISMATCH')
    if owner['binding']['current_revision']!=native['current_revision']:raise ValueError('OWNER_CURRENT_REVISION_MISMATCH')
    if digest(owner['q_rad'])!=digest(native['original_state_draft']['q_rad']):raise ValueError('OWNER_Q_NOT_CURRENT_CAPTURE')
    if digest(owner.get('attachment_tcp_to_block'))!=native['attachment_digest']:raise ValueError('OWNER_ATTACHMENT_NOT_CURRENT_CAPTURE')
    return dict(status='OWNER_CURRENT_CAPTURE_MAPPING_CHECKED',execution_allowed=False,hardware_execution_allowed=False)


def audit_live_cycle(stop_records,resume_records,*,limits):
    """Same execution STOP->new goal evidence; no past complete pose promoted to STOP."""
    stopped=replay_owner_records(stop_records,limits=limits)
    if stopped['owner_context'] is None:return dict(stopped,cycle_complete=False)
    owner=stopped['owner_context'];seen={};previous=-1;last=None
    if owner['stop_record']['source_kind']!='SIM_OWNER_RECORD':return dict(status='HOLD_ACTUAL_SIM_CYCLE_REQUIRED',cycle_complete=False,execution_allowed=False,hardware_execution_allowed=False)
    for record in resume_records:
        if record['record_digest']!=digest({k:v for k,v in record.items() if k!='record_digest'}):raise ValueError('LIVE_CYCLE_RECORD_CHANGED')
        if record['record_sequence']<=previous:raise ValueError('LIVE_CYCLE_RECORD_REORDERED')
        previous=record['record_sequence'];c=record['context']
        for key in ('session_id','clock_basis','clock_epoch','execution_id','cancel_generation','replan_sequence'):
            if c[key]!=owner[key]:raise ValueError('LIVE_CYCLE_IDENTITY_CHANGED:'+key)
        if c['goal_version']!=owner['goal_version']+1 or not c['goal_id'] or c['goal_id']==owner['goal_id']:raise ValueError('LIVE_CYCLE_NEW_UUID_VERSION_REQUIRED')
        if last is not None and c['goal_id']!=last:raise ValueError('LIVE_CYCLE_RESUME_UUID_CHANGED')
        last=c['goal_id']
        if any(c[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):raise ValueError('LIVE_CYCLE_STOP_FAILURE_UNKNOWN')
        if record['evidence'] is not None and sha(record['evidence']['path'])!=record['evidence']['sha256']:raise ValueError('LIVE_CYCLE_SOURCE_CHANGED')
        seen.setdefault(record['event'],[]).append(record)
    needed=('SUBMISSION_INTENT','GOAL_ACCEPTED','GOAL_APPLIED','PHYSICS_SAMPLE','GOAL_RESULT','TARGET_REVIEW')
    gaps=['UNOBSERVED_'+k for k in needed if not seen.get(k)]
    risk=[r for r in stop_records if r['event']=='DEPTH_RISK']
    if not risk or risk[-1]['original_payload'].get('risk_scope')!='OBSERVED_DEPTH_IN_REMAINING_HELD_GRIPPER_VOLUME_NOT_TCP_PROXIMITY':gaps.append('REMAINING_VOLUME_DEPTH_RISK_UNOBSERVED')
    if seen.get('GOAL_ACCEPTED') and seen['GOAL_ACCEPTED'][-1]['original_payload'].get('accepted') is not True:gaps.append('RESUME_NOT_ACCEPTED')
    result=seen.get('GOAL_RESULT',[{}])[-1].get('original_payload',{})
    if result.get('status')!=4 or result.get('error_code')!=0:gaps.append('RESUME_TARGET_TERMINAL_UNVERIFIED')
    target=seen.get('TARGET_REVIEW',[{}])[-1].get('original_payload',{})
    if not all(target.get(k) is True for k in ('holding_confirmed','target_position_verified','target_orientation_verified','unexpected_contact_absent')):gaps.append('PHYSICAL_TARGET_GRASP_CONTACT_UNVERIFIED')
    # Required source/provenance/latency records remain separate; completion needs each one.
    required=('PLAN_REQUEST','SDK_RESULT','RESUME_REVIEW')
    for kind in required:
        if not any(r['event']==kind and r['evidence'] is not None for r in stop_records):gaps.append('PINNED_'+kind+'_UNOBSERVED')
    stamps=[seen[k][0]['observed_stamp_s'] for k in needed if seen.get(k)]
    if any(x is None for x in stamps) or any(a>b for a,b in zip(stamps,stamps[1:])):gaps.append('RESUME_LIFECYCLE_TIMING_UNVERIFIED')
    for record in list(stop_records)+list(resume_records):
        if record['event'] in ('DEPTH_RISK','CANCEL_REQUEST','CANCEL_ACK','GOAL_RESULT','PLAN_REQUEST','SDK_RESULT','RESUME_REVIEW','SUBMISSION_INTENT','GOAL_ACCEPTED','GOAL_APPLIED','TARGET_REVIEW'):
            wall=record['original_payload'].get('wall_monotonic_s')
            if type(wall) not in (int,float) or not np.isfinite(wall):gaps.append('WALL_LATENCY_UNOBSERVED')
    video=target.get('video_evidence')
    if not isinstance(video,dict) or not Path(video.get('path','')).is_file() or sha(video['path'])!=video.get('sha256') or not target.get('video_event_timestamps'):gaps.append('GUI_VIDEO_EVENT_TIMESTAMPS_UNVERIFIED')
    return dict(status='LIVE_CYCLE_EVIDENCE_COMPLETE' if not gaps else 'HOLD_LIVE_CYCLE_EVIDENCE_INCOMPLETE',
        gaps=gaps,cycle_complete=not gaps,old_goal_id=owner['goal_id'],new_goal_id=last,
        execution_allowed=False,hardware_execution_allowed=False,native_send_called=False)


def build_stop_verification(output_path,owner,evidence,*,journal_ref,owner_limits):
    """Bind actual D verdict/source refs to current rolling record. No new stop algorithm.

    The owner journal remains the authoritative lifecycle; controller/holding
    source flags are copied only after validation, never created from null criteria.
    """
    from .native_boundary import _pinned_json,_exclusive_json,review_stop,LIVE_IDENTITY,_review_owner_stop_verification
    if owner['stop_record']['stop_reason']!='OBSTACLE_RESPONSE_HOLD':raise ValueError('STOP_BUILDER_NOT_DEPTH_OBSTACLE_STOP:'+owner['stop_record']['stop_reason'])
    records=read_owner_journal(journal_ref['path'],journal_ref['sha256'])
    preliminary=replay_owner_records(records,expected_context=owner,limits=None)
    if set(preliminary.get('gaps',[]))-{'OWNER_REVIEW_LIMITS_NOT_SELECTED'}:raise ValueError('D_STOP_JOURNAL_NOT_COMPLETE:'+str(preliminary.get('gaps')))
    record=owner['stop_record']
    sample_records=[r for r in records if r['event']=='PHYSICS_SAMPLE' and r['original_payload']['stamp_s']>=record['cancel_terminal_stamp_s']]
    samples=[{k:r['original_payload'][k] for k in ('stamp_s','q_rad','v_rad_s','a_rad_s2')} for r in sample_records]
    if samples!=record['samples']:raise ValueError('STOP_BUILDER_SAMPLES_NOT_ORIGINAL_JOURNAL')
    loaded={key:_pinned_json(evidence[key]) for key in ('cancel_ack','terminal_result','command_counts','holding','controller_stop')}
    ack=loaded['cancel_ack'];terminal=loaded['terminal_result'];counts=loaded['command_counts']
    # Source files may hold full original event payloads; never fabricate UUID/stamps.
    by_kind={kind:[r for r in records if r['event']==kind] for kind in ('CANCEL_ACK','GOAL_RESULT','COMMAND_COUNTS','CANCEL_REQUEST')}
    matching=[r for r in by_kind['CANCEL_ACK'] if r['original_payload']==ack and owner['goal_id'] in ack.get('goals_canceling_ids',[])]
    if not matching or not by_kind['GOAL_RESULT'] or by_kind['GOAL_RESULT'][-1]['original_payload']!=terminal or by_kind['COMMAND_COUNTS'][-1]['original_payload']!=counts:raise ValueError('STOP_BUILDER_SOURCE_NOT_JOURNAL_PAYLOAD')
    terminal_record=by_kind['GOAL_RESULT'][-1]
    if terminal_record['observed_stamp_s']!=record['cancel_terminal_stamp_s']:raise ValueError('STOP_BUILDER_TERMINAL_STAMP_CHANGED')
    if not by_kind['CANCEL_REQUEST'] or not by_kind['CANCEL_REQUEST'][0]['observed_stamp_s']<=matching[0]['observed_stamp_s']<=terminal_record['observed_stamp_s']<=samples[0]['stamp_s']:raise ValueError('STOP_BUILDER_LIFECYCLE_TIME_ORDER')
    controller=loaded['controller_stop'];held=loaded['holding']
    identity={k:owner[k] for k in LIVE_IDENTITY}
    for current_source in (controller,held):
        if current_source.get('identity')!=identity or any(type(current_source['identity'][k]) is not type(owner[k]) for k in LIVE_IDENTITY) or current_source.get('state_stamp_s')!=owner['state_stamp_s']:raise ValueError('STOP_BUILDER_CURRENT_SOURCE_IDENTITY_OR_STAMP_CHANGED')
    proof=dict(scope='VERIFIED_D_OBSTACLE_STOP_AND_HOLDING_NOT_RESUME_APPROVAL',identity={k:owner[k] for k in LIVE_IDENTITY},
        stop_record_digest=record['record_digest'],samples_digest=digest(record['samples']),state_stamp_s=owner['state_stamp_s'],
        stop_verified=controller.get('stop_verified'),holding_confirmed=held.get('holding_confirmed'),verification_method=controller.get('verification_method'),
        evidence=deepcopy(evidence),journal=deepcopy(journal_ref),original_events_digest=digest(records),native_send_called=False,hardware_execution_allowed=False)
    # Stage a candidate only; return an immutable public receipt AFTER existing
    # consumer validates current record, observed criteria and canonical clock.
    target=Path(output_path);staged=target.with_name(target.name+'.unvalidated')
    candidate_ref=_exclusive_json(staged,proof);bound=deepcopy(owner);bound['stop_verification']=candidate_ref
    _review_owner_stop_verification(bound,record)
    audit={}
    review_stop(bound,owner_limits,observation_report=audit)
    if sha(journal_ref['path'])!=journal_ref['sha256'] or any(sha(ref['path'])!=ref['sha256'] for ref in evidence.values()):raise ValueError('STOP_BUILDER_SOURCE_CHANGED_DURING_REVIEW')
    receipt_ref=_exclusive_json(target,proof)
    # The staged file is evidence of validation, not a published owner pointer.
    return dict(stop_verification=receipt_ref,observation_report=audit,source_journal=journal_ref,
        stop_verdict_created_by_builder=False,original_record_unchanged=True,execution_allowed=False,native_send_called=False)
