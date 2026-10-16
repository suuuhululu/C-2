"""D boundary review and ROS goal construction only. No action/service clients."""
from copy import deepcopy
from pathlib import Path
import json

from .engine_receipt import receive_engine,CUMOTION,sha
from .planner_bundle import PlannerBundleConsumer,consume_hold_evidence,read_bundle
from .preflight import digest,BINDING
from .switch_contract import SwitchContract,finite,JOINTS

OWNER_KEYS=('session_id','clock_basis','clock_epoch','execution_id','goal_id','goal_version',
            'state_digest','state_sequence','snapshot_digest','snapshot_version','cancel_generation','replan_sequence')


def blocked(status,**fields):
    return dict(status=status,dispatch_intent=None,resume_candidate=None,execution_allowed=False,
                hardware_execution_allowed=False,automatic_resume=False,**fields)



def review_capture_index(index_path,*,index_sha,summary_sha):
    """Read capture evidence as HOLD, not as a planner request or observed D stop."""
    path=Path(index_path);folder=path.parent;summary_path=folder/'summary.json'
    if sha(path)!=index_sha or sha(summary_path)!=summary_sha:raise ValueError('CAPTURE_PUBLICATION_CHANGED')
    index=json.loads(path.read_text());summary=json.loads(summary_path.read_text());verified=[];poses=[]
    if index['schema']!='wrist-sim-producer-evidence-index/0.1' or not index['scope'].startswith('HOLD_'):raise ValueError('HOLD_CAPTURE_INDEX_REQUIRED')
    def pin(p,expected):
        if sha(p)!=expected:raise ValueError('CAPTURE_ARTIFACT_CHANGED:'+str(p))
        verified.append(dict(path=str(p.resolve()),sha256=expected))
    pin(folder/'executed_source.py',index['capture_source_sha256']);pin(folder/'capture_profile.json',index['profile_sha256'])
    for name,files in index['poses'].items():
        pose=folder/name
        if pose.resolve().parent!=folder.resolve():raise ValueError('POSE_PATH_ESCAPE')
        for filename,expected in files.items():
            p=pose/filename
            if p.resolve().parent!=pose.resolve():raise ValueError('ARTIFACT_PATH_ESCAPE')
            pin(p,expected)
        manifest=json.loads((pose/'manifest_draft.json').read_text())
        if manifest['source_kind']!='SIM_DEPTH' or manifest['status']!='HOLD_INCOMPLETE_EVIDENCE':raise ValueError('CAPTURE_NOT_A_PREPARED_PLANNER_BUNDLE')
        for artifact in manifest['files'].values():
            p=pose/artifact['path']
            if p.resolve().parent!=pose.resolve():raise ValueError('MANIFEST_PATH_ESCAPE')
            pin(p,artifact['sha256'])
        history=json.loads((pose/'stationary_samples.json').read_text())
        poses.append(dict(pose=name,manifest=manifest,sample_count=len(history['samples']),
            sample_source=history['source'],acceleration_method=history['acceleration_method'],
            active_pending_counts=history['active_pending_counts'],stop_reason=history['stop_reason']))
    if sha(path)!=index_sha or sha(summary_path)!=summary_sha or any(sha(v['path'])!=v['sha256'] for v in verified):raise ValueError('CAPTURE_CHANGED_DURING_REVIEW')
    return blocked('HOLD_CAPTURE_NOT_PLANNER_BUNDLE',source_kind='SIM_DEPTH',capture_index_sha256=index_sha,
                   summary_sha256=summary_sha,verified_artifacts=verified,poses=poses,original_summary=summary,
                   resolved_data=['RAW_SEMANTIC_IDS_AND_LABEL_TABLE_AVAILABLE','SAVED_Q_NATIVE_V_FINITE_DIFFERENCE_A_HISTORY_AVAILABLE'],
                   remaining=['FULL_SCENE_MODEL_AND_HELD_BODY_STUD_ATTACHMENT_BINDING','D_CANCEL_TERMINAL_AND_OBSERVED_STOP_COMMAND_COUNTS',
                              'DECLARED_ERROR_VISIBILITY_SPEED_LATENCY_AND_RENDERER_RAY_BASIS','ACTIVE_A_STATE_WORLD_CANCEL_BINDING',
                              'NEW_ADMITTED_MODEL_SDK_FINAL_FCL_RESULT'])


def same_owner(planned,current):
    for k in OWNER_KEYS:
        if type(planned[k]) is not type(current[k]) or planned[k]!=current[k]:raise ValueError('OWNER_CONTEXT_CHANGED:'+k)
    if current['single_writer']!='D':raise ValueError('D_SINGLE_WRITER_REQUIRED')
    if any(current[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):raise ValueError('STOP_FAILURE_UNKNOWN_NO_AUTO_RESUME')
    if current['mode']!='OBSTACLE_HOLD':raise ValueError('NORMAL_OBSTACLE_HOLD_REQUIRED')
    for k in ('clock_epoch','goal_version','state_sequence','snapshot_version','cancel_generation','replan_sequence'):
        if type(current[k]) is not int or current[k]<0:raise ValueError('INVALID_OWNER_VERSION')


def review_stop(owner,limits,*,observation_report=None):
    """Original obstacle STOP lifecycle; existing callers keep the same policy."""
    return _review_stop(owner,limits,observation_report=observation_report,
        expected_reason='OBSTACLE_RESPONSE_HOLD',
        verification_scope='VERIFIED_D_OBSTACLE_STOP_AND_HOLDING_NOT_RESUME_APPROVAL')


def review_conservative_stop(owner,limits,*,observation_report=None):
    """SIM-only conservative foreground stop; no risk or SDK admission."""
    record=owner['stop_record']
    if (record['source_kind']!='SIM_OWNER_RECORD' or
            record['state_source_kind']!='SIM_SAVED_SNAPSHOT' or
            record.get('scope')!='ACTUAL_SIM_CONSERVATIVE_FOREGROUND_STOP_RECORD'):
        raise ValueError('EXPLICIT_CONSERVATIVE_SIM_STOP_RECORD_REQUIRED')
    if limits['max_state_age_s']!=.12 or limits['min_stop_observation_s']<.5:
        raise ValueError('ORIGINAL_CURRENT_STATE_FRESHNESS_AND_STOP_WINDOW_REQUIRED')
    for name in STOP_OBSERVATION_KEYS:
        value=limits[name]
        if value is not None and not (isinstance(value,dict) and value.get('value') is None and
                value.get('check_mode')=='REPORT_ONLY' and value.get('source_category')=='OFFICIAL_NOT_DEFINED'):
            raise ValueError('CONSERVATIVE_OBSERVATIONS_REQUIRE_NULL_REPORT_ONLY:'+name)
    if not record['samples']:
        raise ValueError('CONSERVATIVE_STOP_SAMPLES_REQUIRED')
    for key in ('q_rad','v_rad_s','a_rad_s2'):
        if digest(owner[key])!=digest(record['samples'][-1][key]):
            raise ValueError('CONSERVATIVE_OWNER_NOT_EXACT_LAST_SOURCE_SAMPLE:'+key)
    return _review_stop(owner,limits,observation_report=observation_report,
        expected_reason='FRESH_FOREGROUND_CONSERVATIVE_STOP',
        verification_scope='VERIFIED_D_CONSERVATIVE_FOREGROUND_STOP_AND_HOLDING_NOT_RESUME_APPROVAL')


def _review_stop(owner,limits,*,observation_report,expected_reason,verification_scope):
    """Shared original lifecycle, sample, freshness and independent verdict checks."""
    record=owner['stop_record'];source=record['source_kind']
    if source not in ('FIXTURE','SIM_OWNER_RECORD','REAL_OWNER_RECORD'):raise ValueError('OWNER_RECORD_SOURCE_REQUIRED')
    if record['record_digest']!=digest({k:v for k,v in record.items() if k!='record_digest'}):raise ValueError('STOP_RECORD_CHANGED')
    for k in OWNER_KEYS:
        if type(record[k]) is not type(owner[k]) or record[k]!=owner[k]:raise ValueError('STOP_RECORD_BINDING:'+k)
    if record['stop_reason']!=expected_reason:raise ValueError('GOAL_COMPLETE_IS_NOT_OBSTACLE_STOP' if expected_reason=='OBSTACLE_RESPONSE_HOLD' else 'DIFFERENT_CONSERVATIVE_STOP_CAUSE')
    if record['old_goal_terminal_status']!='CANCELED' or record['cancel_acknowledged'] is not True:raise ValueError('CANCEL_TERMINAL_REQUIRED')
    if any(type(record[k]) is not int or record[k]!=0 for k in ('active_command_count','pending_command_count','pending_cancel_count')):raise ValueError('COMMANDS_REMAIN_PENDING')
    for k in ('active_command_count','pending_command_count','pending_cancel_count'):
        if type(owner[k]) is not int or owner[k]!=0:raise ValueError('OWNER_COMMANDS_REMAIN_PENDING')
    now=finite(owner['now_s']);cancel_stamp=finite(record['cancel_terminal_stamp_s'])
    if limits['scope']!='CPU_D_BOUNDARY_REVIEW_LIMITS':raise ValueError('EXPLICIT_REVIEW_LIMITS_REQUIRED')
    same_owner(owner,owner)
    for k in ('max_state_age_s','min_stop_observation_s'):
        if finite(limits[k])<=0:raise ValueError('POSITIVE_REVIEW_LIMIT_REQUIRED')
    rows=[]
    for key in ('max_stop_velocity_rad_s','max_stop_acceleration_rad_s2','q_tolerance_rad','v_tolerance_rad_s','a_tolerance_rad_s2'):
        _stop_observation_difference(limits,key,0.,applies_to='CRITERION_REPRESENTATION_ONLY')
    samples=record['samples']
    if len(samples)<2 or not record['velocity_method'] or not record['acceleration_method']:raise ValueError('OBSERVED_QVA_METHOD_REQUIRED')
    previous=None
    for s in samples:
        t=finite(s['stamp_s'])
        if t<cancel_stamp or (previous is not None and t<=previous):raise ValueError('STOP_OBSERVATION_ORDER')
        previous=t
        for k in ('q_rad','v_rad_s','a_rad_s2'):
            if len(s[k])!=6:raise ValueError('SIX_QVA_VALUES_REQUIRED')
            for value in s[k]:finite(value)
        for field,key in (('v_rad_s','max_stop_velocity_rad_s'),('a_rad_s2','max_stop_acceleration_rad_s2')):
            rows.append(dict(_stop_observation_difference(limits,key,max(abs(x) for x in s[field]),applies_to='RAW_STOP_SAMPLE_MAGNITUDE:'+field),sample_stamp_s=t))
    last=samples[-1]
    if samples[-1]['stamp_s']-samples[0]['stamp_s']<limits['min_stop_observation_s'] or not 0<=now-last['stamp_s']<=limits['max_state_age_s']:raise ValueError('STOP_HISTORY_SHORT_STALE_OR_FUTURE')
    if finite(owner['state_stamp_s'])!=last['stamp_s']:raise ValueError('OWNER_STAMP_NOT_ORIGINAL_OBSERVATION')
    if not 0<=now-finite(owner['state_stamp_s'])<=limits['max_state_age_s']:raise ValueError('LATEST_OWNER_STATE_STALE')
    for k,unit in (('q_rad','q_tolerance_rad'),('v_rad_s','v_tolerance_rad_s'),('a_rad_s2','a_tolerance_rad_s2')):
        if len(owner[k])!=6:raise ValueError('SIX_OWNER_QVA_VALUES_REQUIRED')
        rows.append(_stop_observation_difference(limits,unit,max(abs(finite(x)-y) for x,y in zip(owner[k],last[k])),applies_to='OWNER_VS_ORIGINAL_LAST_SAMPLE:'+k))
    stop_proof=None
    if any(row['check_mode']=='REPORT_ONLY' for row in rows):
        stop_proof=_review_owner_stop_verification(owner,record,expected_scope=verification_scope)
    if observation_report is not None:
        observation_report.update(observation_criteria=rows,owner_stop_verification=stop_proof,
            stop_success_inferred_from_report_only=False,original_record_digest=record['record_digest'],
            freshness_window=dict(max_state_age_s=limits['max_state_age_s'],min_stop_observation_s=limits['min_stop_observation_s'],source_category='PROJECT_TEST_PARAMETER',reference='owner-selected current freshness/window contract, not SDK official'))
    return deepcopy(record)


def prepare_obstacle_resume(*,planned_owner,latest_owner,limits,prepared_folder=None,planner_latest=None,
                            receipt_path=None,receipt_pins=None,diagnostic_path=None,diagnostic_sha=None):
    """Return a held reason or non-executable candidate. No wait loop or D state mutation."""
    before=deepcopy(latest_owner())
    if before is not None:same_owner(planned_owner,before)
    if diagnostic_path is not None:
        diagnostic=consume_hold_evidence(diagnostic_path,expected_sha256=diagnostic_sha,authority_ref='D_BOUNDARY_ARCHIVE_DIAGNOSTIC_ONLY')
        after=deepcopy(latest_owner())
        if after!=before:raise ValueError('OWNER_CHANGED_DURING_DIAGNOSTIC_REVIEW')
        return blocked('HOLD_INPUT_EVIDENCE_INCOMPLETE',diagnostic=diagnostic,owner_stop_reviewed=False)
    if before is None:return blocked('WAIT_D_OWNER_STOP_CONTEXT')
    record=review_stop(before,limits)
    if prepared_folder is None:return blocked('WAIT_FRESH_PLANNER_REQUEST',stop_record=record)
    request,inputs,envelope,pins=read_bundle(prepared_folder)
    state=inputs['state'];control=inputs['control'];obstacles=inputs['obstacles']
    for k,statekey in (('session_id','session_id'),('clock_basis','clock_basis'),('state_sequence','state_sequence'),('cancel_generation','cancel_generation'),('state_digest','digest')):
        if before[k]!=state[statekey]:raise ValueError('REQUEST_NOT_OBSERVED_STOP_CONTEXT:'+k)
    if before['snapshot_digest']!=obstacles['digest'] or before['snapshot_version']!=obstacles['version'] or before['replan_sequence']!=control['replan_sequence']:raise ValueError('REQUEST_NOT_CURRENT_WORLD_CANCEL')
    if state['source_kind']!=record['state_source_kind'] or state['source_stamp_s']!=before['state_stamp_s']:raise ValueError('STATE_SOURCE_OR_STAMP_CHANGED')
    for k in ('q_rad','v_rad_s','a_rad_s2'):
        if state[k]!=before[k]:raise ValueError('REQUEST_QVA_NOT_OWNER_OBSERVATION')
    if planner_latest is None:raise ValueError('INDEPENDENT_LATEST_PLANNER_CONTEXT_REQUIRED')
    review=PlannerBundleConsumer().consume(prepared_folder,planner_latest,planned_epoch=before['clock_epoch'],
                    result_path=receipt_path,result_pins=receipt_pins)
    after=deepcopy(latest_owner());same_owner(planned_owner,after);review_stop(after,limits)
    if digest({k:v for k,v in before.items() if k!='now_s'})!=digest({k:v for k,v in after.items() if k!='now_s'}):raise ValueError('OWNER_CHANGED_DURING_RECEIPT')
    if receipt_path is None:return blocked('WAIT_FRESH_SDK_FINAL_FCL_RESULT',stop_record=record,planner_review=review)
    packet=receive_engine(CUMOTION,receipt_path,dict(artifact_pins=receipt_pins,motion_request=after['motion_request'],binding=after['binding']))
    if packet['binding']!=envelope['binding'] or packet['model_digest']!=request['model_digest']:raise ValueError('RECEIPT_NOT_FRESH_BOUND_REQUEST')
    for k,field,unit in (('q_rad','positions_rad','q_tolerance_rad'),('v_rad_s','velocities_rad_s','v_tolerance_rad_s'),('a_rad_s2','accelerations_rad_s2','a_tolerance_rad_s2')):
        if max(abs(x-y) for x,y in zip(after[k],packet['trajectory']['points'][0][field]))>limits[unit]:
            return blocked('SDK_SUFFIX_RECEIVED_CURRENT_REFERENCE_CONNECTION_REVIEW_REQUIRED',reviewed_suffix=packet,stop_record=record,planner_review=review,original_observation=after)
    final=deepcopy(latest_owner());same_owner(planned_owner,final);review_stop(final,limits)
    if digest({k:v for k,v in final.items() if k!='now_s'})!=digest({k:v for k,v in after.items() if k!='now_s'}):raise ValueError('OWNER_CHANGED_BEFORE_CANDIDATE')
    if digest(receive_engine(CUMOTION,receipt_path,dict(artifact_pins=receipt_pins,motion_request=final['motion_request'],binding=final['binding'])))!=digest(packet):raise ValueError('FINAL_RECEIPT_CHANGED')
    if any(sha(Path(prepared_folder)/name)!=value for name,value in pins.items()):raise ValueError('PLANNER_FILES_CHANGED')
    boundary=deepcopy(latest_owner());same_owner(planned_owner,boundary);review_stop(boundary,limits)
    if digest({k:v for k,v in boundary.items() if k!='now_s'})!=digest({k:v for k,v in final.items() if k!='now_s'}):raise ValueError('OWNER_CHANGED_AFTER_FINAL_RECEIPT')
    return blocked('RESUME_CANDIDATE_REVIEWED_NATIVE_DISPATCH_BLOCKED',reviewed_candidate=packet,stop_record=record,planner_review=review)


def build_future_goal(candidate,latest,limits,clock_mapping,*,controller_type):
    """Build the installed ROS message, never an ActionClient; fixture timing review only."""
    if controller_type!='joint_trajectory_controller/JointTrajectoryController':
        return None,blocked('UNSUPPORTED_CONTROLLER_FUTURE_STAMP')
    c=deepcopy(candidate);current=deepcopy(latest())
    review=SwitchContract().review(c,latest,limits)
    m=clock_mapping
    if m['scope']!='CPU_IDENTITY_CLOCK_FIXTURE' or m['clock_basis']!=c['clock_basis'] or m['clock_epoch']!=c['clock_epoch']:raise ValueError('EXPLICIT_CLOCK_MAPPING_REQUIRED')
    for k in ('source_origin_ns','ros_origin_ns'):
        if type(m[k]) is not int or m[k]<0:raise ValueError('INTEGER_CLOCK_ORIGIN_REQUIRED')
    def ns(value):
        value=finite(value)
        if value<0:raise ValueError('NONNEGATIVE_ROS_TIME_REQUIRED')
        return round(value*1e9)
    stamp=m['ros_origin_ns']+ns(c['planned_switch_stamp_s'])-m['source_origin_ns']
    if not 0<stamp<2**31*10**9:raise ValueError('NONZERO_REPRESENTABLE_HEADER_STAMP_REQUIRED')
    from control_msgs.action import FollowJointTrajectory
    from trajectory_msgs.msg import JointTrajectoryPoint
    goal=FollowJointTrajectory.Goal();goal.trajectory.joint_names=JOINTS[:]
    goal.trajectory.header.stamp.sec,goal.trajectory.header.stamp.nanosec=divmod(stamp,10**9)
    prior=-1
    for p in c['new_trajectory']['points']:
        ticks=ns(p['time_from_start_s'])
        if ticks<=prior:raise ValueError('NANOSECOND_QUANTIZATION_COLLAPSED_POINTS')
        prior=ticks
        if ticks>=2**31*10**9:raise ValueError('DURATION_NOT_REPRESENTABLE')
        point=JointTrajectoryPoint(positions=p['positions_rad'],velocities=p['velocities_rad_s'],accelerations=p['accelerations_rad_s2'])
        point.time_from_start.sec,point.time_from_start.nanosec=divmod(ticks,10**9);goal.trajectory.points.append(point)
    final=deepcopy(latest())
    if digest({k:v for k,v in current.items() if k!='now_s'})!=digest({k:v for k,v in final.items() if k!='now_s'}):raise ValueError('AUTHORITY_CHANGED_DURING_MESSAGE_BUILD')
    SwitchContract().review(c,lambda:final,limits)
    return goal,blocked('ROS_FUTURE_GOAL_BUILT_NOT_SENT_CONTROLLER_SWITCH_UNVERIFIED',switch_review=review,
        header_stamp_ns=stamp,message_source_kind='FIXTURE',goal_lifecycle=dict(old_goal_id=c['goal_id'],old_goal_expected_result='ABORTED/INVALID_GOAL_ON_JTC_PREEMPT',
        new_acceptance='NOT_REQUESTED',new_result='NOT_REQUESTED',normal_cancel_required=False,
        preserves_old_curve_until_switch_verified=False),native_blockers=['Existing D active-goal guard and handle lifecycle',
        'JTC replaces trajectory at acceptance; pre-first-point interpolation is a different curve requiring swept FCL',
        'Loaded controller/native SIM timing and replacement need owner test'])


def sim_resume_context_checker(planned_owner,planned_envelope,latest_owner,planner_latest,*,owner_limits,planner_limits):
    """Owner callbacks, not files or an actor. Re-read source clock and controls at each boundary."""
    from dynamic_cumotion_inputs import check_result_context,verify_seal
    if not callable(latest_owner) or not callable(planner_latest):raise ValueError('OWNER_CALLBACKS_REQUIRED')
    if planned_envelope.get('calculation_scope')=='ARCHIVED_STATIC_SIM_CALCULATION_ONLY' or planned_envelope.get('schema_version')=='static-sim-calculation-preparation/0.1':
        raise ValueError('ARCHIVED_STATIC_NOT_LIVE_RESUME')
    planned_owner=deepcopy(planned_owner);planned_envelope=deepcopy(planned_envelope)
    previous=[None]
    def check(phase):
        if phase not in ('REQUEST','CALCULATION_START','SDK_FINISHED','FINAL_FCL_FINISHED','RESULT_READY','TRANSITION_FCL_START','TRANSITION_FCL_FINISHED','D_APPLY_REVIEW'):raise ValueError('EXPLICIT_RESUME_CHECKPOINT_REQUIRED')
        if phase not in ('REQUEST','CALCULATION_START') and previous[0] is None:raise ValueError('CALC_REQUEST_CHECKPOINT_REQUIRED')
        first=deepcopy(latest_owner())
        if first is None:raise ValueError('CURRENT_OWNER_UNOBSERVED')
        same_owner(planned_owner,first);review_stop(first,owner_limits)
        if first['stop_record']['source_kind'] not in ('SIM_OWNER_RECORD','FIXTURE'):raise ValueError('SIM_ONLY_RESUME_REVIEW')
        packet=deepcopy(planner_latest())
        if 'clock_epoch' in packet and packet['clock_epoch']!=first['clock_epoch']:raise ValueError('OWNER_PLANNER_EPOCH_CHANGED')
        check_result_context(planned_envelope,packet['envelope'],packet['control'],now_s=first['now_s'],limits=planner_limits)
        verify_seal(packet['state'])
        if packet['state']['digest']!=first['state_digest'] or packet['state']['digest']!=packet['envelope']['planner_context']['state_digest']:raise ValueError('OWNER_LATEST_STATE_CHANGED')
        if packet['envelope']['audit_context']['obstacle_snapshot_digest']!=first['snapshot_digest'] or packet['envelope']['planner_context']['obstacle_version']!=first['snapshot_version']:raise ValueError('OWNER_LATEST_WORLD_CHANGED')
        if 'obstacles' in packet:
            verify_seal(packet['obstacles'])
            if packet['obstacles']['digest']!=first['snapshot_digest']:raise ValueError('OWNER_LATEST_WORLD_CHANGED')
        for key in ('q_rad','v_rad_s','a_rad_s2'):
            if packet['state'][key]!=first[key]:raise ValueError('RAW_OWNER_PLANNER_OBSERVATION_CHANGED:'+key)
        if packet['control']['cancel_generation']!=first['cancel_generation']:raise ValueError('OWNER_CANCEL_CHANGED')
        second=deepcopy(latest_owner());same_owner(planned_owner,second);review_stop(second,owner_limits)
        if digest({k:v for k,v in first.items() if k!='now_s'})!=digest({k:v for k,v in second.items() if k!='now_s'}):raise ValueError('OWNER_CHANGED_DURING_CHECKPOINT')
        now=finite(second['now_s'])
        check_result_context(planned_envelope,packet['envelope'],packet['control'],now_s=now,limits=planner_limits)
        if previous[0] is not None and now<previous[0]:raise ValueError('OWNER_SOURCE_CLOCK_REVERSED')
        advanced=previous[0] is None or now>previous[0]
        previous[0]=now
        return dict(phase=phase,status='SIM_OWNER_CALLBACK_CONTEXT_CHECKED_NOT_SEND_APPROVAL',source_now_s=now,
            original_owner=second,original_planner_packet=packet,owner_context_digest=digest({k:v for k,v in second.items() if k!='now_s'}),
            envelope_digest=packet['envelope']['envelope_digest'],owner_provider_called=True,source_clock_advanced=advanced,
            clock_association=packet.get('clock_association'),
            observed={k:deepcopy(second[k]) for k in ('session_id','clock_basis','q_rad','v_rad_s','a_rad_s2')},
            desired=deepcopy(packet.get('desired')),live_source_verified=False,execution_allowed=False,hardware_execution_allowed=False)
    return check


def review_sim_reference_resume(candidate,suffix,request,whole_curve_receipt,*,context_check,tracking_limits,lower,upper,
                                expected_fcl_sha256,wire_header_stamp_ns,next_goal_version,request_path=None,suffix_receipt_path=None,suffix_receipt_pins=None,motion_request=None,observed_source_verification=None):
    """Separate SIM PVT transition scope; original calculator/REAL start rules are unchanged."""
    transition_candidate=native_transition_candidate;review_transition=review_native_transition
    if request_path is not None and (Path(request_path).parent/'static_calculation.admission.json').exists():raise ValueError('ARCHIVED_STATIC_NOT_LIVE_RESUME')
    if candidate is None or suffix is None:return blocked('WAIT_NEW_SDK_SUFFIX_AND_INITIAL_PVT_CONNECTION')
    if candidate['scope']!='CONTROLLER_PVT_TO_SDK_REST_TRANSITION_NOT_PHYSICAL_APPROVAL':raise ValueError('EXPLICIT_CU_SIM_TRANSITION_SCOPE_REQUIRED')
    if candidate['trajectory_digest']!=digest(candidate['trajectory']) or candidate['suffix_digest']!=digest(suffix):raise ValueError('TRANSITION_OR_SUFFIX_CHANGED')
    before=context_check('SDK_FINISHED');owner=before['original_owner']
    import xml.etree.ElementTree as ET
    robot=ET.fromstring(request['model_bundle']['robot_description'])
    original=[robot.find(f"joint[@name='{name}']/limit") for name in JOINTS]
    if list(lower)!=[float(x.get('lower')) for x in original] or list(upper)!=[float(x.get('upper')) for x in original]:raise ValueError('TRANSITION_BOUNDS_NOT_ORIGINAL_MODEL')
    if {k:request[k] for k in BINDING}!=before['original_planner_packet']['envelope']['binding']:raise ValueError('SDK_REQUEST_NOT_CURRENT_LIVE_BINDING')
    if suffix_receipt_path is None:return blocked('WAIT_FRESH_SDK_SUFFIX_RECEIPT')
    report=json.loads(Path(suffix_receipt_path).read_text());original_request_path=Path(report['artifacts']['request']['path'])
    if (original_request_path.parent/'static_calculation.admission.json').exists():raise ValueError('ARCHIVED_STATIC_NOT_LIVE_RESUME')
    if suffix_receipt_pins is None or motion_request is None:raise ValueError('INDEPENDENT_SUFFIX_RECEIPT_PINS_AND_REQUEST_REQUIRED')
    packet=receive_engine(CUMOTION,suffix_receipt_path,dict(artifact_pins=suffix_receipt_pins,motion_request=motion_request,binding={k:request[k] for k in BINDING}))
    if packet['trajectory']!=suffix or packet['model_digest']!=request['model_digest']:raise ValueError('SUFFIX_NOT_ORIGINAL_CURRENT_SDK_RECEIPT')
    observed=candidate['observed'];desired=candidate['desired']
    for value in (observed,desired):
        if value['session_id']!=owner['session_id'] or value['clock_basis']!=owner['clock_basis']:raise ValueError('TRANSITION_NOT_CURRENT_OWNER')
    if before.get('dynamic_validity') is not None:
        if observed_source_verification is None:raise ValueError('ORIGINAL_NATIVE_TRANSITION_OBSERVATION_PIN_REQUIRED')
        source=_pinned_json(observed_source_verification['owner_ref'])
        recorded_packet=_pinned_json(observed_source_verification['packet_ref'])
        if any(source[k]!=owner[k] for k in LIVE_IDENTITY):raise ValueError('TRANSITION_OBSERVATION_LIFECYCLE_CHANGED')
        if observed['stamp_s']!=source['state_stamp_s'] or any(observed[k]!=source[k] for k in ('q_rad','v_rad_s','a_rad_s2')):raise ValueError('TRANSITION_OBSERVATION_NOT_ORIGINAL_NATIVE_SAMPLE')
        if desired!=recorded_packet['desired']:raise ValueError('TRANSITION_REFERENCE_NOT_ORIGINAL_NATIVE_REFERENCE')
        # Fresh current observation is reviewed independently by CU's online
        # drift/rest/desired-vs-observed tests, not equated to an older tick.
    elif observed['stamp_s']!=owner['state_stamp_s'] or any(observed[k]!=owner[k] for k in ('q_rad','v_rad_s','a_rad_s2')):raise ValueError('OBSERVATION_NOT_RAW_CURRENT_OWNER')
    rebuilt=transition_candidate(suffix,desired,observed,duration_s=candidate['transition_duration_s'],limits=tracking_limits,lower=lower,upper=upper)
    if rebuilt!=candidate:raise ValueError('CU_TRANSITION_RECIPE_CHANGED')
    if whole_curve_receipt is None:return blocked('WAIT_FRESH_WHOLE_CONNECTION_SUFFIX_FCL',original_observation=deepcopy(observed),original_desired=deepcopy(desired))
    if (whole_curve_receipt['scope']!='WHOLE_TRANSITION_AND_SUFFIX_FCL_NOT_D_APPROVAL' or
        whole_curve_receipt['library_sha256']!=expected_fcl_sha256 or whole_curve_receipt['FCL']['success'] is not True or
        type(whole_curve_receipt['FCL']['checks']) is not int or whole_curve_receipt['FCL']['checks']<=0):raise ValueError('PINNED_FRESH_WHOLE_CURVE_FCL_REQUIRED')
    if type(wire_header_stamp_ns) is not int or wire_header_stamp_ns<0 or type(next_goal_version) is not int or next_goal_version!=owner['goal_version']+1:raise ValueError('HEADER_NEXT_GOAL_VERSION_REQUIRED')
    context_check('FINAL_FCL_FINISHED')
    reviewed=review_transition(candidate,whole_curve_receipt,request,context_check,expected_library_sha256=expected_fcl_sha256)
    # This ticket is not permission to send. The same owner holds its lock across last check and send.
    value=dict(status='SIM_REFERENCE_RESUME_REVIEWED_NATIVE_SEND_BLOCKED',scope=candidate['scope'],
        command_trajectory=deepcopy(reviewed['trajectory']),command_digest=digest(reviewed['trajectory']),
        observation_review=deepcopy(reviewed.get('observation_review',{'observation_criteria':reviewed.get('observation_criteria')})),
        original_observation=deepcopy(observed),original_desired=deepcopy(desired),tracking_limits=deepcopy(candidate['tracking_limits']),whole_curve_receipt=deepcopy(whole_curve_receipt),
        request_binding={k:request[k] for k in BINDING},context=deepcopy(reviewed['context']),
        wire_header_stamp_ns=wire_header_stamp_ns,next_goal_version=next_goal_version,
        suffix_receipt_source=dict(path=str(Path(suffix_receipt_path).resolve()),sha256=sha(suffix_receipt_path)),
        dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False,native_send_called=False)
    value['review_digest']=digest(value);return value


def final_sim_resume_check(reviewed,context_check,*,wire_trajectory,wire_header_stamp_ns,next_goal_version):
    """Immediately before owner send; no await or callback to an action receiver here."""
    if reviewed['review_digest']!=digest({k:v for k,v in reviewed.items() if k!='review_digest'}):raise ValueError('RESUME_REVIEW_CHANGED')
    if sha(reviewed['suffix_receipt_source']['path'])!=reviewed['suffix_receipt_source']['sha256']:raise ValueError('SDK_RECEIPT_CHANGED_BEFORE_SEND')
    if digest(wire_trajectory)!=reviewed['command_digest'] or wire_header_stamp_ns!=reviewed['wire_header_stamp_ns'] or next_goal_version!=reviewed['next_goal_version']:raise ValueError('WIRE_CURVE_HEADER_VERSION_CHANGED')
    current=context_check('D_APPLY_REVIEW')
    if current['owner_context_digest']!=reviewed['context']['owner_context_digest'] or current['envelope_digest']!=reviewed['context']['envelope_digest']:raise ValueError('FINAL_OWNER_STATE_WORLD_CANCEL_CHANGED')
    desired=current.get('desired')
    if desired is None:raise ValueError('CURRENT_CONTROLLER_REFERENCE_REQUIRED_AT_SEND')
    for key in ('q_rad','v_rad_s','a_rad_s2'):
        if desired[key]!=reviewed['original_desired'][key]:raise ValueError('FINAL_REFERENCE_CHANGED')
    observed=deepcopy(current['observed']);owner=current['original_owner']
    observed.update(session_id=owner['session_id'],clock_basis=owner['clock_basis'],clock_epoch=owner['clock_epoch'],stamp_s=owner['state_stamp_s'])
    observation_review=review_tracking_observations(desired,observed,reviewed['tracking_limits'],source_now_s=current['source_now_s'])
    return dict(status='FINAL_SIM_CONTEXT_RECHECKED_OWNER_SEND_NOT_CALLED',context=current,command_digest=reviewed['command_digest'],
        dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False,live_source_verified=False,
        native_send_called=False,owner_lock_and_actual_send_outside_this_module=True,observation_review=observation_review)


def native_wire_expected(curve):
    """Existing factory rounds seconds to integer ns; preserve PVA exactly."""
    expected=deepcopy(curve)
    previous=-1
    for point in expected['points']:
        ns=round(point['time_from_start_s']*10**9)
        if ns<=previous:raise ValueError('FIXED_NATIVE_TIME_COLLAPSED_OR_REVERSED')
        point['time_from_start_s']=ns/1e9
        previous=ns
    return expected


def fixed_scene_handoff(path,expected_sha):
    """New same-checkpoint handoff only. Preserve frozen calculation provenance; not live/REAL permission."""
    import yaml
    p=Path(path)
    if sha(p)!=expected_sha:raise ValueError('FIXED_HANDOFF_CHANGED')
    h=json.loads(p.read_text())
    if h['schema']!='blocked-path-same-checkpoint-input-handoff/0.1' or h['hardware_execution_allowed'] is not False:raise ValueError('NEW_FIXED_SCENE_HANDOFF_REQUIRED')
    for ref in h['source_pins'].values():
        if sha(ref['path'])!=ref['sha256']:raise ValueError('FIXED_SOURCE_PIN_CHANGED:'+ref['path'])
    request=yaml.safe_load(Path(h['request']['path']).read_text());base=yaml.safe_load(Path(h['baseline_request']['path']).read_text())
    checkpoint=json.loads(Path(h['checkpoint']['path']).read_text());placement=json.loads(Path(h['GT_placement']['path']).read_text())
    for key in ('goal','expected_precontact','attachment','holding_orientation','model_digest'):
        if request[key]!=base[key]:raise ValueError('SAME_CHECKPOINT_BASELINE_MISMATCH:'+key)
    for key in ('q_rad','grip_rad','selected_slot_id'):
        if request['planning_snapshot'][key]!=base['planning_snapshot'][key]:raise ValueError('SAME_CHECKPOINT_START_MISMATCH:'+key)
    base_world={o['id']:o for o in base['planning_snapshot']['world_objects']};new_world={o['id']:o for o in request['planning_snapshot']['world_objects']}
    if not set(base_world)<set(new_world) or any(new_world[k]!=v for k,v in base_world.items()):raise ValueError('FIXED_EXISTING_FULL_WORLD_CHANGED')
    if checkpoint['actual_raw_pvt']['q_rad']!=request['planning_snapshot']['q_rad'] or checkpoint['actual_raw_pvt']['grip_rad']!=request['planning_snapshot']['grip_rad']:raise ValueError('FIXED_CHECKPOINT_NOT_REQUEST_START')
    if sha(p)!=expected_sha:raise ValueError('FIXED_HANDOFF_CHANGED_DURING_READ')
    return dict(handoff=h,handoff_sha256=expected_sha,request=request,checkpoint=checkpoint,
        expected_physical_world=deepcopy(base['planning_snapshot']['world_objects'])+[deepcopy(placement['obstacle'])],
        planned_world=deepcopy(request['planning_snapshot']['world_objects']),
        scope='NEW_IDENTICAL_FIXED_SCENE_SIM_INPUT_NOT_LIVE_NOT_REAL',execution_allowed=False,hardware_execution_allowed=False)


def fixed_scene_native_goal(path,expected_sha,*,receipt_path=None,receipt_pins=None,latest_fixed_owner=None,
                            header_stamp_ns=0,next_goal_version=None,review_limits=None,initial_transition=None,whole_curve_receipt=None,whole_curve_library_sha256=None,tracking_limits=None,actual_geometry_receipt=None):
    """Existing native_goal factory only. Caller single writer submits; this function never does."""
    from plan_only import validate_trajectory,checked_pose
    from sim_utils import error,rigid
    import numpy as np
    data=fixed_scene_handoff(path,expected_sha);h=data['handoff'];request=data['request']
    if receipt_path is None:return None,blocked('WAIT_NEW_FIXED_SCENE_CUMOTION_SDK_FINAL_FCL',fixed_inputs=data)
    report=json.loads(Path(receipt_path).read_text())
    if report['artifacts']['request']['sha256']!=h['request']['sha256'] or sha(report['artifacts']['request']['path'])!=h['request']['sha256']:raise ValueError('OLD_CALCULATION_NOT_THIS_FIXED_HANDOFF')
    if receipt_pins is None:raise ValueError('INDEPENDENT_FIXED_RECEIPT_PINS_REQUIRED')
    motion=json.loads((Path(h['request']['path']).parent/'motion.request.json').read_text())
    packet=receive_engine(CUMOTION,receipt_path,dict(artifact_pins=receipt_pins,motion_request=motion,binding={k:request[k] for k in BINDING}))
    curve=validate_trajectory(packet['trajectory'])
    if latest_fixed_owner is None:return None,blocked('HOLD_ACTUAL_FIXED_SCENE_RESTORE_AND_START_UNOBSERVED',validated_calculation=packet,fixed_inputs=data)
    if review_limits is None:raise ValueError('OWNER_SELECTED_FIXED_REVIEW_LIMITS_REQUIRED')
    owner=deepcopy(latest_fixed_owner())
    if any(finite(v)<=0 for v in review_limits.values()):raise ValueError('FIXED_REVIEW_LIMITS_POSITIVE')
    def check(value):
        if value['scope']!='FIXED_SCENE_SIM_OWNER_STATE' or value['single_writer']!='D' or value['physics_state_observed'] is not True or value['scene_restored'] is not True:raise ValueError('ACTUAL_FIXED_SIM_OWNER_RESTORE_REQUIRED')
        if any(value[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):raise ValueError('FIXED_STOP_FAILURE_UNKNOWN')
        for k in ('active_command_count','pending_command_count','pending_cancel_count'):
            if type(value[k]) is not int or value[k]!=0:raise ValueError('FIXED_OWNER_COMMAND_STATE_UNKNOWN_OR_ACTIVE')
        if value['contact_fingers']!=data['checkpoint']['actual_raw_pvt']['contact_fingers']:raise ValueError('FIXED_ACTUAL_GRASP_CONTACT_UNCONFIRMED')
        if value['checkpoint_sha256']!=h['checkpoint']['sha256'] or value['model_manifest_sha256']!=request['model_bundle']['manifest_sha256'] or value['current_revision']!=request['current_revision'] or value['selected_block_id']!=request['planning_snapshot']['selected_slot_id']:raise ValueError('FIXED_CHECKPOINT_MODEL_CURRENT_CHANGED')
        if actual_geometry_receipt is None and abs(value['grip_rad']-request['planning_snapshot']['grip_rad'])>review_limits['grip_tolerance_rad']:raise ValueError('FIXED_GRIP_GEOMETRY_CHANGED')
        pe,re=error(rigid(value['attachment_tcp_to_block']),rigid(request['attachment']))
        if actual_geometry_receipt is None and (pe>review_limits['attachment_translation_tolerance_m'] or re>review_limits['attachment_rotation_tolerance_rad']):raise ValueError('FIXED_ATTACHMENT_CHANGED')
        expected={o['id']:o for o in data['expected_physical_world']};actual={o['id']:o for o in value['world_objects']}
        if set(actual)!=set(expected) or len(value['world_objects'])!=len(actual):raise ValueError('FIXED_FULL_WORLD_INVENTORY_CHANGED')
        for id,obj in expected.items():
            other=actual[id]
            if other['size_m']!=obj['size_m'] or other['studs']!=obj['studs']:raise ValueError('FIXED_WORLD_SHAPE_CHANGED:'+id)
            p,r=error(checked_pose(other['pose']),checked_pose(obj['pose']))
            # The fixed GT stimulus cannot move outside the original Depth box
            # merely because a current-geometry audit omitted it.
            gt_id=data['expected_physical_world'][-1]['id']
            if (actual_geometry_receipt is None or id==gt_id) and (p>review_limits['world_translation_tolerance_m'] or r>review_limits['world_rotation_tolerance_rad']):raise ValueError('FIXED_WORLD_POSE_CHANGED:'+id)
        finite(value['grip_rad'])
        for field in ('q_rad','v_rad_s','a_rad_s2'):
            if len(value[field])!=6 or not np.isfinite(value[field]).all():raise ValueError('FIXED_RAW_PVT_REQUIRED')
    check(owner)
    reference=owner.get('desired')
    if reference is None:return None,blocked('HOLD_FIXED_INITIAL_REFERENCE_PVT_UNOBSERVED',original_observation=owner,validated_calculation=packet)
    for field in ('q_rad','v_rad_s','a_rad_s2'):
        if len(reference[field])!=6 or not np.isfinite(reference[field]).all():raise ValueError('FIXED_CURRENT_REFERENCE_PVT_REQUIRED')
    first=curve['points'][0]
    # Direct command must be the already FCL-checked curve; otherwise validate
    # a complete connection. This is curve integrity, not an SDK sensor tolerance.
    mismatch=any(reference[k]!=first[field] for k,field in (('q_rad','positions_rad'),('v_rad_s','velocities_rad_s'),('a_rad_s2','accelerations_rad_s2')))
    tracking_audit=None
    if tracking_limits is not None:
        if any(tracking_limits.get(k) is None or isinstance(tracking_limits.get(k),dict) for k in OBSERVATION_UNITS):
            raw=dict(session_id=owner['session_id'],clock_basis=owner['clock_basis'],clock_epoch=owner['clock_epoch'],stamp_s=owner['state_stamp_s'],**{k:owner[k] for k in ('q_rad','v_rad_s','a_rad_s2')})
            tracking_audit=review_tracking_observations(reference,raw,tracking_limits,source_now_s=owner['now_s'])
        else:
            for key,limit in (('q_rad','q_tolerance_rad'),('v_rad_s','v_tolerance_rad_s'),('a_rad_s2','a_tolerance_rad_s2')):
                if max(abs(a-b) for a,b in zip(owner[key],reference[key]))>finite(tracking_limits[limit]):return None,blocked('HOLD_FIXED_SELECTED_CONTROLLER_TRACKING_ERROR',original_observation=owner,original_desired=reference,validated_calculation=packet)
    elif any(owner[k]!=reference[k] for k in ('q_rad','v_rad_s','a_rad_s2')):
        return None,blocked('HOLD_FIXED_CURRENT_REFERENCE_TRACKING_REVIEW_REQUIRED',original_observation=owner,original_desired=reference,validated_calculation=packet)
    if mismatch:
        if initial_transition is None or whole_curve_receipt is None:
            return None,blocked('HOLD_FIXED_PVT_CONNECTION_AND_WHOLE_CURVE_FCL_REQUIRED',original_observation=owner,original_desired=reference,validated_calculation=packet)
        transition_candidate=native_transition_candidate;review_transition=review_native_transition
        import xml.etree.ElementTree as ET
        robot=ET.fromstring(request['model_bundle']['robot_description']);bounds=[robot.find(f"joint[@name='{name}']/limit") for name in JOINTS]
        lower=[float(x.get('lower')) for x in bounds];upper=[float(x.get('upper')) for x in bounds]
        observed={k:deepcopy(owner[k]) for k in ('session_id','clock_basis','q_rad','v_rad_s','a_rad_s2')};observed['stamp_s']=owner['state_stamp_s'];observed['clock_epoch']=owner['clock_epoch']
        rebuilt=transition_candidate(curve,reference,observed,duration_s=initial_transition['transition_duration_s'],limits=tracking_limits,lower=lower,upper=upper)
        if rebuilt!=initial_transition:raise ValueError('FIXED_CU_CONNECTION_RECIPE_CHANGED')
        def fixed_check(phase):
            current=deepcopy(latest_fixed_owner());check(current)
            if digest({k:v for k,v in current.items() if k!='now_s'})!=digest({k:v for k,v in owner.items() if k!='now_s'}):raise ValueError('FIXED_CONTEXT_CHANGED_DURING_CONNECTION_REVIEW')
            return dict(phase=phase,source_now_s=current['now_s'],desired=current['desired'],observed={k:current[k] for k in ('q_rad','v_rad_s','a_rad_s2')},original_owner=current,execution_allowed=False,hardware_execution_allowed=False)
        review_transition(initial_transition,whole_curve_receipt,request,fixed_check,expected_library_sha256=whole_curve_library_sha256)
        curve=validate_trajectory(initial_transition['trajectory'])
    if type(header_stamp_ns) is not int or not 0<=header_stamp_ns<2**31*10**9 or type(next_goal_version) is not int or next_goal_version!=owner['goal_version']+1:raise ValueError('FIXED_HEADER_NEXT_VERSION_REQUIRED')
    geometry_review=None
    if actual_geometry_receipt is not None:
        geometry_review=review_fixed_actual_geometry(actual_geometry_receipt,request,curve,owner,expected_library_sha256=whole_curve_library_sha256)
    from d_sim_transport import native_goal
    goal=native_goal(dict(trajectory=curve))
    goal.trajectory.header.stamp.sec,goal.trajectory.header.stamp.nanosec=divmod(header_stamp_ns,10**9)
    wire=dict(joint_names=list(goal.trajectory.joint_names),points=[dict(time_from_start_s=(p.time_from_start.sec*10**9+p.time_from_start.nanosec)/1e9,
        positions_rad=list(p.positions),velocities_rad_s=list(p.velocities),accelerations_rad_s2=list(p.accelerations)) for p in goal.trajectory.points])
    if wire!=native_wire_expected(curve):raise ValueError('FIXED_NATIVE_WIRE_CURVE_CHANGED')
    final=deepcopy(latest_fixed_owner());check(final)
    if digest(final)!=digest(owner):raise ValueError('FIXED_OWNER_CHANGED_BEFORE_NATIVE_GOAL_RETURN')
    if sha(path)!=expected_sha or sha(receipt_path)!=receipt_pins['receipt']:raise ValueError('FIXED_INPUT_CHANGED_BEFORE_NATIVE_GOAL_RETURN')
    return goal,dict(status='FIXED_SIM_NATIVE_GOAL_BUILT_OWNER_SEND_NOT_CALLED',scope=data['scope'],fixed_inputs=data,
        original_calculation=packet,original_observation=owner,original_desired=reference,wire_trajectory=wire,observation_review=tracking_audit,actual_geometry_review=geometry_review,
        wire_digest=digest(wire),wire_header_stamp_ns=header_stamp_ns,next_goal_version=next_goal_version,
        handoff_sha256=expected_sha,receipt_sha256=receipt_pins['receipt'],execution_allowed=False,hardware_execution_allowed=False,
        live_resume_approved=False,native_send_called=False,physical_tracking_or_grasp_success=False)


def receive_fixed_scene_delivery(delivery_path,delivery_sha,*,input_handoff_path,input_handoff_sha,**owner_review_args):
    """Actual CU execution-format package -> existing native_goal wire; no sender or scope promotion."""
    delivery=json.loads(Path(delivery_path).read_text())
    if sha(delivery_path)!=delivery_sha or delivery['scope']!='SDK_FIXED_SCENE_EXECUTION_FORMAT_DELIVERY_NOT_D_AUTHORIZATION':raise ValueError('FIXED_DELIVERY_CHANGED_OR_UNSUPPORTED')
    package_ref=delivery['package'];package=json.loads(Path(package_ref['path']).read_text())
    if sha(package_ref['path'])!=package_ref['sha256']:raise ValueError('FIXED_EXECUTION_PACKAGE_CHANGED')
    for value in list(delivery.values())+list(package.values()):
        if isinstance(value,dict) and 'path' in value and 'sha256' in value and sha(value['path'])!=value['sha256']:raise ValueError('FIXED_DELIVERY_ARTIFACT_CHANGED:'+value['path'])
    source=json.loads(Path(input_handoff_path).read_text())
    if package['new_request']['sha256']!=source['request']['sha256']:raise ValueError('FIXED_DELIVERY_NOT_NEW_INPUT_HANDOFF')
    report_ref=package['calculation_report'];report=json.loads(Path(report_ref['path']).read_text())
    pins=dict(receipt=report_ref['sha256'],fcl_binary=package['FCL_binary_sha256'],
        request=package['new_request']['sha256'],external=package['new_external_timed']['sha256'],
        fcl_result=package['new_FCL']['sha256'],model_manifest=package['new_model_manifest']['sha256'])
    goal,review=fixed_scene_native_goal(input_handoff_path,input_handoff_sha,receipt_path=report_ref['path'],receipt_pins=pins,**owner_review_args)
    packet=review.get('validated_calculation',review.get('original_calculation'))
    if packet is None:raise ValueError('DELIVERY_CALCULATION_NOT_VALIDATED')
    raw=json.loads(Path(package['joint_trajectory']['path']).read_text())
    delivered=raw.get('trajectory',raw)
    if delivered!=packet['trajectory']:raise ValueError('DELIVERED_CURVE_NOT_VALIDATED_FINAL_FCL')
    from d_sim_transport import native_goal
    diagnostic=native_goal(dict(trajectory=packet['trajectory']))
    wire=dict(joint_names=list(diagnostic.trajectory.joint_names),points=[dict(time_from_start_s=(p.time_from_start.sec*10**9+p.time_from_start.nanosec)/1e9,
        positions_rad=list(p.positions),velocities_rad_s=list(p.velocities),accelerations_rad_s2=list(p.accelerations)) for p in diagnostic.trajectory.points])
    if wire!=native_wire_expected(packet['trajectory']):raise ValueError('FIXED_SDK_NATIVE_WIRE_MAPPING_CHANGED')
    if sha(delivery_path)!=delivery_sha or sha(package_ref['path'])!=package_ref['sha256']:raise ValueError('FIXED_DELIVERY_CHANGED_DURING_RECEIVE')
    return goal,dict(status=review['status'],scope='FIXED_SCENE_SIM_CALCULATION_RECEIVED_NOT_NATIVE_OR_LIVE_APPROVAL',
        delivery_path=str(Path(delivery_path).resolve()),delivery_sha256=delivery_sha,package_sha256=package_ref['sha256'],
        report_sha256=report_ref['sha256'],receipt_pins=pins,native_review=review,calculation_wire_trajectory=wire,
        calculation_wire_digest=digest(wire),source_scope_preserved=report.get('archived_static_source'),
        time_quantization_max_error_s=max(abs(a['time_from_start_s']-b['time_from_start_s']) for a,b in zip(wire['points'],packet['trajectory']['points'])),
        time_mapping='round(source_seconds * 1e9) integer ns; source curve preserved',
        actual_native_owner_observed=owner_review_args.get('latest_fixed_owner') is not None,
        native_send_called=False,execution_allowed=False,hardware_execution_allowed=False,live_resume_approved=False)


LIVE_IDENTITY=('session_id','clock_basis','clock_epoch','execution_id','goal_id','goal_version','cancel_generation','replan_sequence')


def adapt_novel_depth_detection(detection,expected,frame_state,owner,*,source_refs,
                                model_bundle,max_age_s,max_pose_skew_s):
    """Read-only adapter; owner=None verifies saved input without a risk output."""
    from .novel_depth_consumer import adapt_novel_depth_detection as adapt
    return adapt(detection,expected,frame_state,owner,source_refs=source_refs,
        model_bundle=model_bundle,max_age_s=max_age_s,max_pose_skew_s=max_pose_skew_s)


def adapt_depth_shadow_snapshot(snapshot,current_owner,*,source_owner=None,max_age_s,max_pose_skew_s):
    """Owned memory packet; preserves source/current roles and forbids intent."""
    from .novel_depth_consumer import adapt_depth_shadow_snapshot as adapt
    return adapt(snapshot,current_owner,source_owner=source_owner,
        max_age_s=max_age_s,max_pose_skew_s=max_pose_skew_s)


def _risk_work_reason(work_check,computed,projected,max_age_s):
    """Poll existing owner/worker state; no timer, default budget or sender.

    Callback must be nonblocking and return an atomic current_owner snapshot
    plus optional worker_cancelled bool. Actual source seconds are compared
    only with the same source clock. Caller cancellation is not robot cancel.
    """
    from .remaining_volume import IDENTITY
    try:
        packet=work_check()
        if not isinstance(packet,dict):return 'CURRENT_SOURCE_UNAVAILABLE:INVALID_PACKET'
        cancelled=packet.get('worker_cancelled',False)
        if cancelled is True:return 'WORKER_CANCELLED'
        if cancelled is not False:return 'WORKER_CANCEL_STATE_INVALID'
        current=packet['current_owner']
        if not isinstance(current,dict):return 'CURRENT_SOURCE_UNAVAILABLE:INVALID_OWNER'
        keys=IDENTITY+tuple(k for k in ('known_geometry_digest','cancel_generation') if k in computed)
        for key in keys:
            if type(current[key]) is not type(computed[key]) or current[key]!=computed[key]:
                return 'ACTIVE_IDENTITY_CHANGED:'+key
        if current['mode']!='TRANSPORT' or type(current['active_command_count']) is not int or current['active_command_count']<=0:
            return 'OWNER_NO_ACTIVE_TRANSPORT'
        for key in ('user_stop_latched','failure_latched','outcome_unknown'):
            if current[key] is not False:return 'OWNER_LATCHED:'+key
        if current['holding_confirmed'] is not True or not {'rg2_left_inner_finger','rg2_right_inner_finger'}<=set(current['contact_fingers']):
            return 'OWNER_HOLDING_UNKNOWN'
        now=finite(current['now_s']);ns=current['trajectory_progress_ns']
        if now<computed['now_s']:return 'CURRENT_SOURCE_CLOCK_REVERSED'
        if not 0<=now-projected['source_stamp_s']<=max_age_s:return 'CURRENT_DEPTH_STALE_OR_FUTURE'
        if now!=current['state_stamp_s'] or now!=current['progress_stamp_s'] or current['progress_source']!='ACCEPTED_CONTROLLER_REFERENCE':
            return 'CURRENT_SOURCE_TICK_UNASSOCIATED'
        if type(ns) is not int or current['trajectory_progress_s']!=ns/1_000_000_000 or ns<computed['trajectory_progress_ns']:
            return 'CURRENT_PROGRESS_INVALID_OR_REVERSED'
        q=current['q_rad'];attachment=current['attachment_tcp_to_block']
        if len(q)!=6 or len(attachment)!=4 or any(len(row)!=4 for row in attachment) or list(attachment[3])!=[0.,0.,0.,1.]:
            return 'CURRENT_POSE_INVALID'
        for value in list(q)+[current['grip_rad']]+[v for row in attachment for v in row]:finite(value)
    except (KeyError,ValueError,TypeError) as exc:
        return 'CURRENT_SOURCE_UNAVAILABLE:'+type(exc).__name__
    return None


def _numeric_first_witness(volume,points,known,errors,point_low,point_high,checkpoint,statistics):
    """Validate all immutable coverage/hierarchy before exact spatial rejection.

    Return any first witness, not the legacy exhaustive hit list. Coarse hulls
    reject only; every positive is a particular original interval/part or the
    separately observed current pose. No interval or point subsampling.
    """
    import hashlib
    import numpy as np
    from .remaining_volume import COMPONENTS
    excluded={'numeric_curve','partial_bounds','observed_bounds','receipt','receipt_digest'}
    receipt={k:v for k,v in volume.items() if k not in excluded}
    if receipt!=volume['receipt'] or digest(receipt)!=volume['receipt_digest']:
        raise ValueError('NUMERIC_VOLUME_RECEIPT_CHANGED')
    curve=volume['numeric_curve'];raw=curve['manifest']
    if not isinstance(raw,bytes) or hashlib.sha256(raw).hexdigest()!=curve['curve_digest'] or curve['curve_digest']!=volume['curve_digest']:
        raise ValueError('NUMERIC_CURVE_MANIFEST_CHANGED')
    m=json.loads(raw);parts=m['part_inventory'];count=m['interval_count'];part_count=m['part_count']
    pairs=[(p['part'],p['component']) for p in parts]
    if len(pairs)!=part_count or len(set(pairs))!=part_count or any(c not in COMPONENTS for _,c in pairs):
        raise ValueError('NUMERIC_ORIGINAL_PART_INVENTORY_CHANGED')
    inv=digest(dict(model_digest=volume['inventory_model_digest'],collisions=m['collision_inventory'],parts=parts))
    if inv!=m['inventory_digest'] or inv!=volume['inventory_digest'] or m['geometry_binding']!=volume['nominal_geometry_binding'] or m['geometry_binding']['model_digest']!=volume['source_identity']['model_digest'] or volume['inventory_model_digest']!=volume['source_identity']['model_digest'] or m['geometry_binding']['active_wire_digest']!=volume['source_trajectory_digest']:
        raise ValueError('NUMERIC_ORIGINAL_MODEL_INVENTORY_CHANGED')
    if {(p['part'],p['component']) for p in m['collision_inventory']}!={p for p in pairs if p[1]!='HELD_BLOCK'}:
        raise ValueError('NUMERIC_ORIGINAL_COLLISION_COVERAGE_CHANGED')
    def array(value,shape,dtype,expected):
        if not isinstance(value,np.ndarray) or value.shape!=shape or value.dtype!=np.dtype(dtype) or not value.flags.c_contiguous or value.flags.writeable:
            raise ValueError('NUMERIC_IMMUTABLE_ARRAY_REQUIRED')
        backing=value
        while isinstance(backing,np.ndarray):backing=backing.base
        if not isinstance(backing,bytes) or hashlib.sha256(memoryview(value)).hexdigest()!=expected:
            raise ValueError('NUMERIC_ARRAY_SOURCE_CHANGED')
        return value
    times=array(curve['interval_ns'],(count,2),np.int64,m['times_sha256'])
    bounds=array(curve['bounds'],(count,part_count,2,3),np.float64,m['bounds_sha256'])
    if count<=0 or np.any(times[:,1]<=times[:,0]) or np.any(times[1:,0]!=times[:-1,1]):raise ValueError('NUMERIC_INTERVAL_COVERAGE_CHANGED')
    if not np.isfinite(bounds).all() or np.any(bounds[:,:,1]<=bounds[:,:,0]):raise ValueError('NUMERIC_BOUNDS_INVALID')
    ns=volume['trajectory_progress_ns'];first=int(np.searchsorted(times[:,1],ns,side='left'))
    if first>=count or first!=volume['first_interval_index'] or ns<times[first,0] or volume['remaining_intervals']!=count-first or volume['wire_end_ns']!=int(times[-1,1]):
        raise ValueError('NUMERIC_REMAINING_INTERVAL_CHANGED')
    partial=volume['partial_bounds']
    if times[first,0]<ns:
        partial=array(partial,(part_count,2,3),np.float64,volume['partial_bounds_sha256'])
    else:
        if partial is not None or volume['partial_bounds_sha256'] is not None:raise ValueError('NUMERIC_UNEXPECTED_PARTIAL_INTERVAL')
    current=array(volume['observed_bounds'],(part_count,2,3),np.float64,volume['observed_bounds_sha256'])
    for value in (partial,current):
        if value is not None and (not np.isfinite(value).all() or np.any(value[:,1]<=value[:,0])):raise ValueError('NUMERIC_CURRENT_OR_PARTIAL_BOUNDS_INVALID')
    from .risk_spatial import validate_hierarchy,query_hierarchy
    size=m['spatial_node_count']
    tree=array(curve['spatial_bounds'],(size,2,3),np.float64,m['spatial_bounds_sha256'])
    nodes=array(curve['spatial_nodes'],(size,6),np.int64,m['spatial_nodes_sha256'])
    order=array(curve['spatial_order'],(count*part_count,),np.int64,m['spatial_order_sha256'])
    validate_hierarchy(bounds,tree,nodes,order)
    found=query_hierarchy(bounds,tree,nodes,order,first,partial,current,points,known,errors,
                          point_low,point_high,checkpoint,statistics)
    if found is None:return []
    flat,index,nominal=found;interval,part=divmod(flat,part_count);is_current=interval==count
    box=current[part] if is_current else (partial[part] if partial is not None and interval==first else bounds[interval,part])
    witness=dict(group_index=count-first if is_current else interval-first,box_index=part,
        kind='CURRENT_OBSERVED_POSE' if is_current else 'ACCEPTED_REFERENCE_INTERVAL',
        interval_index=None if is_current else interval,part=parts[part]['part'],component=parts[part]['component'],
        point_indices=[index],nominal_point_indices=[index] if nominal else [],min_m=box[0].tolist(),max_m=box[1].tolist())
    if is_current:witness['stamp_s']=volume['stamp_s']
    else:witness.update(start_ns=max(ns,int(times[interval,0])),end_ns=int(times[interval,1]))
    return [witness]


def remaining_volume_depth_risk(projected,remaining,owner,*,max_age_s,max_pose_skew_s,work_check=None):
    """Candidate bounds against current pose and individual accepted-curve intervals.

    A risk witness only; absent hit is not a collision-free or visibility proof.
    Swept-volume generation/FK and its conservatism remain the native owner responsibility.
    """
    import hashlib
    import numpy as np
    if owner['mode']!='TRANSPORT' or type(owner['active_command_count']) is not int or owner['active_command_count']<=0:raise ValueError('ACTIVE_NATIVE_TRANSPORT_REQUIRED')
    if any(owner[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):raise ValueError('STOP_FAILURE_UNKNOWN_NO_AUTO_RESUME')
    original={k:v for k,v in projected.items() if k!='digest'}
    if hashlib.sha256(json.dumps(original,sort_keys=True,allow_nan=False).encode()).hexdigest()!=projected['digest']:raise ValueError('DEPTH_PROJECTION_CHANGED')
    novel=projected.get('novel_depth_companion')
    if projected.get('detector_kind')=='EXPECTED_ACTUAL_DEPTH_DIFFERENCE':
        if novel is None:raise ValueError('NOVEL_FULL_DETECTION_ADAPTER_REQUIRED')
        if novel['digest']!=digest({k:v for k,v in novel.items() if k!='digest'}):raise ValueError('NOVEL_COMPANION_CHANGED')
        if novel['selected_points_digest']!=digest({k:projected[k] for k in ('points_base_m','pixel_uv','point_uncertainty_m')}):raise ValueError('NOVEL_SELECTED_POINTS_CHANGED')
        if novel['known_geometry_digest']!=owner.get('known_geometry_digest') or any(type(owner[k]) is not type(v) or owner[k]!=v for k,v in novel['source_identity'].items()):raise ValueError('NOVEL_ACTIVE_SOURCE_BINDING_CHANGED')
        if len(projected['points_base_m'])!=novel['selected_foreground_count']:raise ValueError('NOVEL_FOREGROUND_SELECTION_CHANGED')
        if (novel.get('shadow_only') is True or novel.get('qualification_scope')=='SIM_TEST_REPORT_ONLY' or novel.get('point_bounds_ref') is not None) and novel['live_intent_eligible'] is not False:
            raise ValueError('NOVEL_REPORT_ONLY_CANNOT_ADMIT_INTENT')
    elif novel is not None:raise ValueError('NOVEL_DETECTOR_KIND_CHANGED')
    fixture_only=novel is not None and projected['source_kind']=='FIXTURE' and novel['source_scope']=='FIXTURE' and novel['live_intent_eligible'] is False
    if (projected['source_kind']!='SIM_DEPTH' and not fixture_only) or projected['session_id']!=owner['session_id'] or projected['clock_basis']!=owner['clock_basis']:raise ValueError('CURRENT_SIM_DEPTH_REQUIRED')
    if not 0<=owner['now_s']-projected['source_stamp_s']<=finite(max_age_s):raise ValueError('DEPTH_RISK_STALE')
    if any(abs(projected['source_stamp_s']-projected[k])>finite(max_pose_skew_s) for k in ('robot_state_stamp_s','transform_stamp_s')):raise ValueError('DEPTH_RISK_SOURCE_POSE_SKEW')
    from .remaining_volume import FULL_SCOPE, COMPONENTS, IDENTITY, NUMERIC
    full=remaining['scope']==FULL_SCOPE
    numeric=remaining.get('representation')==NUMERIC
    if numeric and not full:raise ValueError('NUMERIC_FULL_ROBOT_SCOPE_REQUIRED')
    if novel is not None and (not full or remaining.get('source_identity',{}).get('known_geometry_digest')!=novel['known_geometry_digest']):
        raise ValueError('NOVEL_FULL_ROBOT_ACCEPTED_MAP_BINDING_REQUIRED')
    if remaining['scope'] not in (FULL_SCOPE,'CONSERVATIVE_REMAINING_HELD_GRIPPER_SWEPT_VOLUME') or remaining['goal_id']!=owner['goal_id'] or remaining['goal_version']!=owner['goal_version']:raise ValueError('CURRENT_REMAINING_GOAL_VOLUME_REQUIRED')
    if full and remaining.get('method')!='EXACT_RATIONAL_BERNSTEIN_80_BIT_DIRECTED_INTERVAL_FK':raise ValueError('FULL_ROBOT_INTERVAL_METHOD_REQUIRED')
    if remaining['source_trajectory_digest']!=owner['active_wire_digest'] or remaining['frame_id']!='base_link' or remaining['conservative'] is not True:raise ValueError('REMAINING_VOLUME_CURVE_OR_FRAME_CHANGED')
    if remaining.get('method')=='EXACT_RATIONAL_BERNSTEIN_80_BIT_DIRECTED_INTERVAL_FK':
        keys=set(IDENTITY)|set(remaining['source_identity'])
        if any(type(remaining['source_identity'][k]) is not type(owner[k]) or remaining['source_identity'][k]!=owner[k] for k in keys):
            raise ValueError('REMAINING_VOLUME_SOURCE_BINDING_CHANGED')
        if owner['now_s']!=owner['state_stamp_s'] or owner['now_s']!=owner['progress_stamp_s'] or owner['progress_source']!='ACCEPTED_CONTROLLER_REFERENCE':
            raise ValueError('CURRENT_SOURCE_TICK_PROGRESS_REQUIRED')
        if type(owner['trajectory_progress_ns']) is not int or owner['trajectory_progress_s']!=owner['trajectory_progress_ns']/1_000_000_000:
            raise ValueError('EXACT_CONTROLLER_REFERENCE_NANOSECONDS_REQUIRED')
        if remaining['trajectory_progress_s']!=owner['trajectory_progress_s'] or remaining['trajectory_progress_ns']!=owner['trajectory_progress_ns'] or remaining['stamp_s']!=owner['progress_stamp_s']:
            raise ValueError('REMAINING_VOLUME_SOURCE_PROGRESS_CHANGED')
        if remaining['source_q_rad']!=owner['q_rad']:raise ValueError('REMAINING_VOLUME_OBSERVED_Q_CHANGED')
        if any(remaining['current_geometry'][k]!=owner[k] for k in ('grip_rad','attachment_tcp_to_block','holding_confirmed','contact_fingers')):
            raise ValueError('REMAINING_VOLUME_CURRENT_RAW_GEOMETRY_CHANGED')
    if remaining['stamp_s']<projected['source_stamp_s'] or owner['now_s']-remaining['stamp_s']>max_age_s:raise ValueError('REMAINING_VOLUME_STALE')
    if (full or 'clock_epoch' in projected) and (type(projected.get('clock_epoch')) is not type(owner['clock_epoch']) or projected['clock_epoch']!=owner['clock_epoch']):
        raise ValueError('DEPTH_RISK_CLOCK_EPOCH_CHANGED')
    if full and (projected['robot_state_stamp_s']!=owner['state_stamp_s'] or projected['q_rad']!=owner['q_rad']):
        raise ValueError('DEPTH_RISK_SOURCE_STATE_UNASSOCIATED')
    if 'known_geometry_digest' in remaining.get('source_identity',{}) and projected.get('known_geometry_digest')!=owner['known_geometry_digest']:
        raise ValueError('DEPTH_RISK_KNOWN_GEOMETRY_CHANGED')
    points=np.asarray(projected['points_base_m'],dtype=float)
    if points.shape==(0,):points=points.reshape(0,3)
    if points.ndim!=2 or points.shape[1:]!=(3,) or not np.isfinite(points).all():raise ValueError('DEPTH_POINT_SHAPE_OR_NONFINITE')
    # Missing uncertainty is unknown, never an implicit zero-width error bound.
    uncertainty=projected.get('point_uncertainty_m')
    known=np.zeros(len(points),dtype=bool);errors=np.zeros_like(points)
    if uncertainty is not None:
        if len(uncertainty)!=len(points):raise ValueError('DEPTH_UNCERTAINTY_LENGTH_CHANGED')
        known=np.fromiter((v is not None for v in uncertainty),dtype=bool,count=len(points))
        if known.any():
            try:values=np.asarray([v for v in uncertainty if v is not None],dtype=float)
            except (TypeError,ValueError) as exc:raise ValueError('DEPTH_UNCERTAINTY_INVALID') from exc
            if values.shape!=(int(known.sum()),3) or not np.isfinite(values).all() or np.any(values<0):raise ValueError('DEPTH_UNCERTAINTY_INVALID')
            errors[known]=values
    # Expand outwards, including round-off in p +/- error.
    point_low=np.nextafter(points-errors,-np.inf);point_high=np.nextafter(points+errors,np.inf)
    groups=[] if numeric else [dict(kind='LEGACY_MERGED_HELD_GRIPPER',boxes=remaining['boxes'])]
    if full and not numeric:
        inventory=remaining['part_inventory'];pairs=[(p['part'],p['component']) for p in inventory]
        expected=digest(dict(model_digest=remaining['inventory_model_digest'],collisions=remaining['collision_inventory'],parts=inventory))
        if remaining['inventory_model_digest']!=owner['model_digest'] or remaining['inventory_digest']!=expected or len(set(pairs))!=len(pairs):
            raise ValueError('FULL_ROBOT_INVENTORY_CHANGED')
        if {(p['part'],p['component']) for p in remaining['collision_inventory']}!={p for p in pairs if p[1]!='HELD_BLOCK'}:
            raise ValueError('FULL_ROBOT_COLLISION_INVENTORY_INCOMPLETE')
        groups=remaining['interval_boxes']
        if not groups or len(groups)!=remaining['remaining_intervals']+1 or groups[-1]['kind']!='CURRENT_OBSERVED_POSE' or groups[-1]['stamp_s']!=owner['now_s']:
            raise ValueError('FULL_ROBOT_CURRENT_AND_INTERVAL_BOUNDS_REQUIRED')
        previous_end=owner['trajectory_progress_ns']
        for group in groups[:-1]:
            if group['kind']!='ACCEPTED_REFERENCE_INTERVAL' or group['start_ns']!=previous_end or group['end_ns']<group['start_ns']:
                raise ValueError('REMAINING_INTERVAL_GAP_OR_ORDER_CHANGED')
            previous_end=group['end_ns']
        if previous_end!=remaining['wire_end_ns']:raise ValueError('REMAINING_INTERVAL_TAIL_MISSING')
    work=dict(complete=True,reason=None,checks=0);statistics={}
    if work_check is not None and not callable(work_check):raise ValueError('WORK_CHECK_CALLBACK_REQUIRED')
    def checkpoint():
        if not work['complete']:return False
        if work_check is None:return True
        work['checks']+=1
        reason=_risk_work_reason(work_check,owner,projected,max_age_s)
        if reason is not None:work.update(complete=False,reason=reason)
        return work['complete']
    hits=_numeric_first_witness(remaining,points,known,errors,point_low,point_high,checkpoint,statistics) if numeric else []
    for group_index,group in enumerate(groups):
        if not checkpoint():break
        if full and [(b['part'],b['component']) for b in group['boxes']]!=pairs:
            raise ValueError('FULL_ROBOT_INTERVAL_PARTS_CHANGED')
        for i,box in enumerate(group['boxes']):
            if box['component'] not in (COMPONENTS if full else ('HELD_BLOCK','GRIPPER')):raise ValueError('EXPLICIT_ROBOT_COLLISION_COMPONENT_REQUIRED')
            low=np.asarray(box['min_m']);high=np.asarray(box['max_m'])
            if low.shape!=(3,) or high.shape!=(3,) or not np.isfinite([low,high]).all() or np.any(high<=low):raise ValueError('REMAINING_VOLUME_INVALID')
            nominal=np.all((points>=low)&(points<=high),axis=1)
            inside=np.flatnonzero(nominal | (known & np.all((point_high>=low)&(point_low<=high),axis=1)))
            if len(inside):hits.append(dict(group_index=group_index,kind=group['kind'],box_index=i,
                part=box.get('part'),component=box['component'],point_indices=inside.tolist(),nominal_point_indices=np.flatnonzero(nominal).tolist()))
    checkpoint()
    if not work['complete']:hits=[]
    unresolved=(novel is not None and novel['unresolved_observation']) or not work['complete']
    bounded_negative=uncertainty is not None and known.all() and not unresolved
    result=dict(risk=True if hits else (False if bounded_negative else None),
        status=('NOVEL_FOREGROUND_RISK_WITNESS' if novel is not None else 'RISK_WITNESS') if hits else ('NO_BOUNDED_CANDIDATE_OVERLAP' if bounded_negative else 'UNKNOWN_CANDIDATE_UNCERTAINTY'),
        uncertainty_status='BOUNDED' if uncertainty is not None and known.all() else 'UNKNOWN_OR_PARTIAL',
        risk_scope='CANDIDATE_IN_FULL_ROBOT_REMAINING_INTERVAL_BOUNDS' if full else 'OBSERVED_DEPTH_IN_REMAINING_HELD_GRIPPER_VOLUME_NOT_TCP_PROXIMITY',
        depth_digest=projected['digest'],frame_seq=projected['frame_seq'],source_stamp_s=projected['source_stamp_s'],
        source_q_rad=projected['q_rad'],source_T_base_camera_optical=projected['T_base_camera_optical'],
        goal_id=owner['goal_id'],goal_version=owner['goal_version'],remaining_digest=remaining['receipt_digest'] if numeric else digest(remaining),hits=hits,
        source_owner_digest=digest(owner),source_identity=deepcopy(remaining.get('source_identity')),
        accepted_binding_ref=deepcopy(remaining.get('accepted_binding_ref')),as_of_stamp_s=owner['now_s'],
        world_clear_allowed=False,execution_allowed=False,hardware_execution_allowed=False)
    if novel is not None:
        result.update(native_intent_eligible=novel['live_intent_eligible'],
            novelty_witness=bool(hits),confidence_loss_guard=bool(unresolved),
            uncertainty_status='UNKNOWN_OR_PARTIAL' if unresolved else result['uncertainty_status'])
        if numeric:
            result['novel_depth_companion_summary']={k:deepcopy(novel[k]) for k in ('digest','parent_refs','original_projection_ref',
                'original_projection_digest','guard_reasons','selected_foreground_count','excluded_unresolved_count','source_identity')}
            result['novel_depth_companion_summary'].update({k:deepcopy(novel[k]) for k in
                ('classification_scope','qualification_ref','qualification_scope','effective_pixel_convention','pixel_convention',
                 'point_bound_source','point_bounds_ref','point_bounds_risk_qualified','point_bounds_status',
                 'point_bounds_scope','point_bounds_missing_fields','shadow_only','owned_snapshot_digest',
                 'source_owner_digest','calculation_owner_digest','source_state_stamp_s','calculation_state_stamp_s') if k in novel})
        else:result['novel_depth_companion']=deepcopy(novel)
    if numeric:
        result.update(hits_scope='FIRST_WITNESS_EXISTENCE_ALL_INTERVALS_ALL_POINTS',remaining_digest_scope='COMPACT_SOURCE_RECEIPT_AND_FULL_CURVE_HASHES',
            curve_digest=remaining['curve_digest'],numeric_receipt=deepcopy(remaining['receipt']))
    if numeric or work_check is not None:
        result.update(calculation_complete=work['complete'],incomplete_reason=work['reason'],
            cooperative_checks=work['checks'],spatial_statistics=statistics)
    if not work['complete']:
        result.update(risk=None,status='INCOMPLETE_UNKNOWN',hits=[],native_intent_eligible=False,
            confidence_loss_guard=True,automatic_resume=False)
        if novel is not None:result['novelty_witness']=False
    result['risk_digest']=digest(result)
    return result


def review_remaining_volume_risk(result,computed_owner,current_owner,*,max_age_s):
    """D calls under its existing lock with a NEW actual snapshot before any intent.

    A still-fresh positive is an as-of conservative caution witness, not proof of
    collision now. This function never cancels, retries, resumes or certifies STOP.
    """
    from .remaining_volume import IDENTITY
    if result['risk_digest']!=digest({k:v for k,v in result.items() if k!='risk_digest'}):raise ValueError('RISK_RESULT_CHANGED')
    if result['source_owner_digest']!=digest(computed_owner) or result['source_identity'] is None:
        raise ValueError('RISK_COMPUTATION_SOURCE_CHANGED')
    keys=set(IDENTITY)|set(result['source_identity'])
    for key in keys:
        value=result['source_identity'][key]
        if type(current_owner[key]) is not type(value) or current_owner[key]!=value or computed_owner[key]!=value:
            raise ValueError('RISK_ACTIVE_GOAL_MODEL_OR_CLOCK_REPLACED:'+key)
    accepted=_pinned_json(result['accepted_binding_ref'])
    if any(accepted[k]!=current_owner[k] or type(accepted[k]) is not type(current_owner[k]) for k in keys):
        raise ValueError('RISK_ACCEPTED_BINDING_REPLACED')
    if current_owner['mode']!='TRANSPORT' or type(current_owner['active_command_count']) is not int or current_owner['active_command_count']<=0:
        raise ValueError('RISK_NO_CURRENT_ACTIVE_TRANSPORT')
    if any(current_owner[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):
        raise ValueError('RISK_CURRENT_STOP_FAILURE_UNKNOWN')
    if current_owner['holding_confirmed'] is not True or not {'rg2_left_inner_finger','rg2_right_inner_finger'}<=set(current_owner['contact_fingers']):
        raise ValueError('RISK_CURRENT_HOLDING_UNKNOWN')
    now=finite(current_owner['now_s']);ns=current_owner['trajectory_progress_ns']
    if now!=current_owner['state_stamp_s'] or now!=current_owner['progress_stamp_s'] or current_owner['progress_source']!='ACCEPTED_CONTROLLER_REFERENCE':
        raise ValueError('RISK_CURRENT_SOURCE_TICK_REQUIRED')
    if type(ns) is not int or current_owner['trajectory_progress_s']!=ns/1_000_000_000 or ns<computed_owner['trajectory_progress_ns']:
        raise ValueError('RISK_CURRENT_PROGRESS_CHANGED_OR_REVERSED')
    if result['as_of_stamp_s']!=computed_owner['now_s'] or not 0<=now-result['as_of_stamp_s']<=finite(max_age_s) or not 0<=now-result['source_stamp_s']<=max_age_s:
        raise ValueError('RISK_RESULT_STALE_OR_REVERSED')
    if current_owner.get('known_geometry_digest')!=computed_owner.get('known_geometry_digest'):
        raise ValueError('RISK_CURRENT_KNOWN_GEOMETRY_CHANGED')
    import numpy as np
    q=np.asarray(current_owner['q_rad'],float);attachment=np.asarray(current_owner['attachment_tcp_to_block'],float)
    finite(current_owner['grip_rad'])
    if q.shape!=(6,) or attachment.shape!=(4,4) or not np.isfinite(q).all() or not np.isfinite(attachment).all() or list(attachment[3])!=[0.,0.,0.,1.]:
        raise ValueError('RISK_CURRENT_RAW_GEOMETRY_INVALID')
    return dict(result,decision_stamp_s=now,decision_scope='AS_OF_SNAPSHOT_CAUTION_ONLY',
        decision_owner_digest=digest(current_owner),
        stop_intent=dict(goal_id=current_owner['goal_id'],goal_version=current_owner['goal_version'],
            session_id=current_owner['session_id'],clock_epoch=current_owner['clock_epoch'],reason='REMAINING_VOLUME_CAUTION') if result['risk'] is True and result.get('native_intent_eligible',True) else None,
        automatic_resume=False,native_cancel_called=False)


def live_owner_context_checker(base,calculated,planned_owner,owner_provider,limits):
    """Fresh atomic provider each boundary; allow sample/frame advancement under CU validity rules."""
    from live_cumotion_boundary import live_context_checker
    from bounded_sim_evidence import pinned_json
    previous=[None];snapshot=[None]
    def read():
        snapshot[0]=deepcopy(owner_provider())
        return snapshot[0]
    cu_check=live_context_checker(base,calculated,limits,read)
    def check(phase):
        checked=cu_check(phase);packet=snapshot[0]
        owner=pinned_json(packet['state']['owner_evidence']);owner=owner.get('owner_context',owner)
        stop_report={};review_stop(owner,limits['owner_review_limits'],observation_report=stop_report)
        # Reuse the producer's bound proof, then test the latest measured points against it.
        # Keeping the old envelope is allowed only within its original finite horizon.
        # CU now replays online bounds including hidden volume, motion through
        # the whole trajectory horizon, occlusion and wall/SIM budgets. Point
        # containment alone must not replace that stronger producer contract.
        if 'online_validity' not in calculated or checked.get('dynamic_validity') is None:raise ValueError('ONLINE_DYNAMIC_VALIDITY_REQUIRED')
        for key in LIVE_IDENTITY:
            if type(owner[key]) is not type(planned_owner[key]) or owner[key]!=planned_owner[key]:raise ValueError('LIVE_LIFECYCLE_CHANGED:'+key)
        if packet.get('timeline_running') is not True:raise ValueError('LIVE_CALCULATION_TIMELINE_MUST_RUN')
        if packet.get('obstacle_motion_policy')!='CONTINUE_WHILE_ROBOT_HOLDS':raise ValueError('LIVE_OBSTACLE_MOTION_FROZEN')
        observation=packet['observation_sequence']
        if type(observation) is not int or previous[0] is not None and observation<previous[0]:raise ValueError('LIVE_OBSERVATION_REVERSED')
        previous[0]=observation
        # CU validates retained conservative envelope/TTL; a new frame alone does not invalidate it.
        # CU provider must update envelope/reject if new obstacle is outside that bound.
        return dict(checked,original_owner=owner,original_planner_packet=packet,stop_observation_review=stop_report,
            owner_context_digest=digest({k:owner[k] for k in LIVE_IDENTITY}),
            observed={k:deepcopy(owner[k]) for k in ('q_rad','v_rad_s','a_rad_s2')},
            observation_sequence=observation,clock_association=dict(packet_evidence=packet['_source_packet_evidence'],clock_epoch=owner['clock_epoch']) if packet.get('_source_packet_evidence') else packet.get('clock_association'),live_source_verified=False)
    return check


class LiveObstacleResume:
    """Per-cancel consumer; no scheduler, process launch, sender or synthetic owner data.

    Native owner keeps ticking sensors/physics and calls poll(). Worker result is
    a nonblocking callback returning None or a fully published verified-input dictionary.
    """
    def __init__(self,context_check,worker_result):
        if not callable(context_check) or not callable(worker_result):raise ValueError('LIVE_CALLBACKS_REQUIRED')
        self.check=context_check;self.worker_result=worker_result;self.phase='OBSTACLE_HOLD'
        self.reviewed=None;self.candidate=None;self.request=None;self.used=False;self.last=None

    def request_plan(self):
        if self.phase!='OBSTACLE_HOLD':raise ValueError('DUPLICATE_PLAN_REQUEST')
        current=self.check('REQUEST');self.identity={k:current['original_owner'][k] for k in LIVE_IDENTITY}
        self.check('CALCULATION_START');self.phase='PLAN_REQUEST';self.last=current
        return blocked('PLAN_REQUEST_VALIDATED_OWNER_STARTS_EXISTING_WORKER',identity=self.identity)

    def poll(self):
        if self.phase!='PLAN_REQUEST':raise ValueError('PLAN_NOT_PENDING')
        try:
            current=self.check('RESULT_READY')
            if self.last is not None and current['source_now_s']<=self.last['source_now_s']:
                return blocked('WAIT_OWNER_PHYSICS_SENSOR_TICK_NO_RESULT_APPLY')
            self.last=current
            delivery=self.worker_result()  # must not wait(), join(), calculate() or launch SDK here
            if delivery is None:return blocked('WAIT_LIVE_SDK_FCL_WORKER_SENSOR_LOOP_CONTINUES')
            self.candidate=delivery['candidate'];self.request=delivery['request']
            args={k:v for k,v in delivery.items() if k not in ('candidate','request','suffix','whole_curve_receipt')}
            r=review_sim_reference_resume(delivery['candidate'],delivery['suffix'],delivery['request'],delivery['whole_curve_receipt'],context_check=self.check,**args)
            if 'review_digest' not in r:return r
            self.reviewed=r;self.phase='RESULT_REVIEWED';return r
        except (ValueError,KeyError) as exc:
            self.phase='DISCARDED';return blocked('DISCARD_LIVE_RESULT_NEW_REQUEST_REQUIRED',reason=str(exc))

    def final_goal(self):
        """Owner invokes under its existing lock immediately before its existing send."""
        review_transition=review_native_transition
        from d_sim_transport import native_goal
        if self.used or self.phase!='RESULT_REVIEWED':raise ValueError('LIVE_CANDIDATE_USED_OR_NOT_REVIEWED')
        r=self.reviewed
        if r['review_digest']!=digest({k:v for k,v in r.items() if k!='review_digest'}):raise ValueError('LIVE_REVIEW_CHANGED')
        if sha(r['suffix_receipt_source']['path'])!=r['suffix_receipt_source']['sha256']:raise ValueError('LIVE_SUFFIX_RECEIPT_CHANGED')
        current=self.check('D_APPLY_REVIEW')
        if {k:current['original_owner'][k] for k in LIVE_IDENTITY}!=self.identity:raise ValueError('LIVE_CANCEL_OR_GOAL_GENERATION_CHANGED')
        review_transition(self.candidate,r['whole_curve_receipt'],self.request,self.check,expected_library_sha256=r['whole_curve_receipt']['library_sha256'])
        if r['command_digest']!=digest(self.candidate['trajectory']):raise ValueError('LIVE_COMMAND_CURVE_CHANGED')
        goal=native_goal(dict(trajectory=r['command_trajectory']))
        goal.trajectory.header.stamp.sec,goal.trajectory.header.stamp.nanosec=divmod(r['wire_header_stamp_ns'],10**9)
        expected=native_wire_expected(r['command_trajectory'])
        wire=dict(joint_names=list(goal.trajectory.joint_names),points=[dict(time_from_start_s=(p.time_from_start.sec*10**9+p.time_from_start.nanosec)/1e9,positions_rad=list(p.positions),velocities_rad_s=list(p.velocities),accelerations_rad_s2=list(p.accelerations)) for p in goal.trajectory.points])
        if wire!=expected or r['next_goal_version']!=current['original_owner']['goal_version']+1:raise ValueError('LIVE_WIRE_OR_VERSION_CHANGED')
        self.used=True;self.phase='SUBMISSION_RESERVED'  # send outcome belongs to owner; never retry this candidate
        return goal,dict(status='LIVE_GOAL_RESERVED_OWNER_SEND_NOT_CALLED',identity=self.identity,next_goal_version=r['next_goal_version'],
            suffix_receipt_sha256=r['suffix_receipt_source']['sha256'],suffix_digest=self.candidate['suffix_digest'],
            connection_digest=self.candidate['trajectory_digest'],wire_digest=digest(wire),wire_header_stamp_ns=r['wire_header_stamp_ns'],
            native_send_called=False,execution_allowed=False,hardware_execution_allowed=False)


def read_live_worker_delivery(pointer_path,identity,*,expected_library_sha256=None,expected_receipt_pins=None,selected_review_args=None,job_ref=None,calculated_context_ref=None,current_geometry=None,current_owner=None):
    """Read owner's atomic worker publication once, never wait or start a process.

    Producer writes tmp+rename after all artifacts finish; pending publication is
    not completion. Identity comes from the current PLAN_REQUEST, not the worker.
    """
    import yaml
    p=Path(pointer_path)
    if not p.is_file():return None
    raw=p.read_bytes();value=json.loads(raw)
    if value['schema']!='live-resume-worker-publication/0.1' or value['identity']!=identity:raise ValueError('WORKER_OLD_SESSION_GOAL_OR_GENERATION')
    if value['status']=='PENDING':return None
    if value['status']!='READY':raise ValueError('WORKER_FAILED_OR_DISCARDED')
    if expected_library_sha256 is None or selected_review_args is None:raise ValueError('OWNER_SELECTED_WORKER_PINS_AND_LIMITS_REQUIRED')
    if value['review_args']!=selected_review_args or selected_review_args['expected_fcl_sha256']!=expected_library_sha256:raise ValueError('WORKER_PINS_OR_LIMITS_NOT_OWNER_SELECTED')
    loaded={}
    for key,ref in value['artifacts'].items():
        if sha(ref['path'])!=ref['sha256']:raise ValueError('LIVE_WORKER_ARTIFACT_CHANGED:'+key)
        loaded[key]=yaml.safe_load(Path(ref['path']).read_text()) if key=='request' else json.loads(Path(ref['path']).read_text())
    report=loaded['suffix_report']
    if report.get('archived_static_source') is not None:raise ValueError('ARCHIVED_WORKER_RESULT_NOT_LIVE')
    if job_ref is not None:
        expected_receipt_pins=validate_online_delivery(value,loaded,job_ref,calculated_context_ref,current_geometry=current_geometry,current_owner=current_owner)
    elif current_geometry is not None:raise ValueError('CURRENT_GEOMETRY_SELECTED_ONLINE_JOB_REQUIRED')
    if expected_receipt_pins is None:raise ValueError('VERIFIED_NEW_OUTPUT_PINS_REQUIRED')
    if value['suffix_receipt_pins']!=expected_receipt_pins:raise ValueError('WORKER_OUTPUT_PINS_CHANGED')
    if p.read_bytes()!=raw:raise ValueError('LIVE_WORKER_PUBLICATION_CHANGED_DURING_READ')
    return dict(candidate=loaded['candidate'],suffix=loaded['suffix'],request=loaded['request'],whole_curve_receipt=loaded['whole_curve_receipt'],
        suffix_receipt_path=value['artifacts']['suffix_report']['path'],suffix_receipt_pins=value['suffix_receipt_pins'],
        motion_request=loaded['motion_request'],request_path=value['artifacts']['request']['path'],
        **value['review_args'])


def _pinned_json(ref):
    if sha(ref['path'])!=ref['sha256']:raise ValueError('ONLINE_SELECTED_FILE_CHANGED:'+ref['path'])
    value=json.loads(Path(ref['path']).read_text())
    if sha(ref['path'])!=ref['sha256']:raise ValueError('ONLINE_SELECTED_FILE_CHANGED_DURING_READ')
    return value


def _file_ref(path):
    return dict(path=str(Path(path).resolve()),sha256=sha(path))


def _exclusive_json(path,value):
    import os
    data=json.dumps(value,sort_keys=True,allow_nan=False).encode()
    with Path(path).open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    return _file_ref(path)


def _atomic_pointer(path,value):
    import os,uuid
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temporary=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    _exclusive_json(temporary,value);os.replace(temporary,p)
    return _file_ref(p)


def publish_native_owner(folder,pointer,observation):
    """Serialize one supplied native observation verbatim; never measure/synthesize controls here."""
    import uuid
    from dynamic_cumotion_inputs import sealed,verify_seal
    owner=deepcopy(observation['owner']);packet=deepcopy(observation['packet'])
    state=packet['state'];control=packet['control'];sequence=packet['observation_sequence']
    if type(sequence) is not int or sequence<0:raise ValueError('NATIVE_OBSERVATION_SEQUENCE_REQUIRED')
    if packet['timeline_running'] is not True or packet['obstacle_motion_policy']!='CONTINUE_WHILE_ROBOT_HOLDS':raise ValueError('PHYSICS_DEPTH_MOTION_MUST_CONTINUE')
    # Publication is observation, not admission. Publish STOP/latch changes too,
    # so a concurrent worker cannot continue reading the previous safe snapshot.
    if owner['single_writer']!='D':raise ValueError('NATIVE_D_OWNER_REQUIRED')
    if owner['stop_record']['source_kind']!='SIM_OWNER_RECORD':raise ValueError('ACTUAL_SIM_STOP_OWNER_REQUIRED')
    for key in ('q_rad','v_rad_s','a_rad_s2'):
        if len(owner[key])!=6 or state[key]!=owner[key]:raise ValueError('RAW_NATIVE_STATE_MISMATCH:'+key)
        for number in owner[key]:finite(number)
    if state['state_sequence']!=owner['state_sequence']:raise ValueError('NATIVE_RAW_STATE_SEQUENCE_MISMATCH')
    if state['source_stamp_s']!=owner['state_stamp_s'] or state['grip_rad']!=owner['grip_rad'] or state['attachment_tcp_to_block']!=owner['attachment_tcp_to_block']:raise ValueError('NATIVE_STAMP_GRIP_ATTACHMENT_MISMATCH')
    for key in ('session_id','clock_basis','cancel_generation','replan_sequence'):
        if control[key]!=owner[key]:raise ValueError('NATIVE_CONTROL_IDENTITY_MISMATCH')
    for key in ('user_stop_latched','failure_latched'):
        if control[key]!=owner[key]:raise ValueError('NATIVE_CONTROL_LATCH_MISMATCH')
    bound=packet['latest_depth_bound']
    if bound['candidate_digest']!=packet['latest_depth']['digest'] or bound['source_session_id']!=owner['session_id']:raise ValueError('LATEST_NATIVE_DEPTH_BOUND_MISMATCH')
    desired=packet['desired']
    for key in ('session_id','clock_basis'):
        if desired[key]!=owner[key]:raise ValueError('NATIVE_REFERENCE_IDENTITY_MISMATCH')
    for key in ('q_rad','v_rad_s','a_rad_s2'):
        if len(desired[key])!=6:raise ValueError('NATIVE_REFERENCE_PVT_REQUIRED')
        for number in desired[key]:finite(number)
    finite(desired['stamp_s']);finite(owner['now_s'])
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    unique=f'{sequence:012d}_{uuid.uuid4().hex}'
    owner_ref=_exclusive_json(folder/(unique+'.owner.json'),owner)
    # Only the evidence reference/seal changes; all raw observed fields are retained.
    state['owner_evidence']=owner_ref;packet['state']=sealed({k:v for k,v in state.items() if k!='digest'})
    verify_seal(packet['state'])
    packet_ref=_exclusive_json(folder/(unique+'.packet.json'),packet)
    _atomic_pointer(pointer,dict(schema='live-cumotion-owner-publication/0.1',packet=packet_ref,
        observation_sequence=sequence,source_now_s=owner['now_s']))
    return dict(packet=packet,owner=owner,packet_ref=packet_ref,owner_ref=owner_ref,live_source_verified=False)


def review_prepared_job_inputs(job,base,request,*,context=None):
    """Pinned computational selection only; never SDK success or apply approval.

    Original A/target/model stay immutable. The distinct prepared geometry is
    tied to its original raw D observation and outward Depth receipt.
    """
    from dynamic_cumotion_inputs import verify_seal,normalize_owner_stop_state
    from online_cumotion_validity import online_contract
    import yaml
    if job['limits'].get('geometry_observation_mode')!='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF':
        raise ValueError('EXPLICIT_PREPARED_GEOMETRY_MODE_REQUIRED')
    if any(key not in job for key in ('source_owner','source_packet','prepared_inputs','calculated_envelope')):
        raise ValueError('PREPARED_SOURCE_REFS_REQUIRED')
    refs={k:job[k] for k in ('base_request','cache_request','cache_model_manifest',
                             'source_owner','source_packet','prepared_inputs','calculated_envelope')}
    for key,ref in refs.items():
        if sha(ref['path'])!=ref['sha256']:raise ValueError('PREPARED_INPUT_PIN_CHANGED:'+key)
    pinned_base=yaml.safe_load(Path(refs['base_request']['path']).read_text())
    prepared=yaml.safe_load(Path(refs['cache_request']['path']).read_text())
    if digest(base)!=digest(pinned_base) or digest(request)!=digest(prepared):raise ValueError('PREPARED_REQUEST_NOT_SELECTED_PIN')
    # Only the explicit geometry/snapshot provenance may change. All target,
    # A/Current/reservation/robot model and otherwise unknown fields stay exact.
    derived={'scene_digest','planning_request_digest','attachment','planning_snapshot','source_snapshot','simulation_provenance'}
    if set(base)!=set(request) or any(digest(base[k])!=digest(request[k]) for k in base if k not in derived):
        raise ValueError('PREPARED_ORIGINAL_ANCHOR_CHANGED')
    b=base['planning_snapshot'];r=request['planning_snapshot']
    geometry={'q_rad','grip_rad','tcp_pose','world_objects'}
    if set(b)!=set(r) or any(digest(b[k])!=digest(r[k]) for k in b if k not in geometry):
        raise ValueError('PREPARED_ORIGINAL_SNAPSHOT_SELECTION_CHANGED')
    envelope=_pinned_json(refs['calculated_envelope']);inputs=_pinned_json(refs['prepared_inputs'])
    owner=_pinned_json(refs['source_owner']);packet=_pinned_json(refs['source_packet'])
    verify_seal(envelope,'envelope_digest');verify_seal(inputs['state']);verify_seal(inputs['obstacles'])
    if (any(type(owner[k]) is not type(job['identity'][k]) or owner[k]!=job['identity'][k] for k in LIVE_IDENTITY) or
            inputs['state']['owner_evidence']!=refs['source_owner'] or packet['state']['owner_evidence']!=refs['source_owner']):
        raise ValueError('PREPARED_SOURCE_IDENTITY_OR_OWNER_CHANGED')
    if (owner['a_context']!=base['a_context'] or owner['reservation_binding']!=base['reservation_binding'] or
            owner['model_manifest_sha256']!=base['model_bundle']['manifest_sha256']):
        raise ValueError('PREPARED_OWNER_ORIGINAL_A_RESERVATION_MODEL_CHANGED')
    if (Path(inputs['base_request_path']).resolve()!=Path(refs['base_request']['path']).resolve() or
            inputs['base_request_sha256']!=refs['base_request']['sha256'] or inputs['limits']!=job['limits'] or
            inputs['control']!=packet['control'] or inputs['now_s']!=owner['now_s'] or
            inputs['obstacles']['depth_bound']!=packet['latest_depth_bound']):
        raise ValueError('PREPARED_SOURCE_INPUT_BINDING_CHANGED')
    # Canonical source verifier derives only proven stamps; compare its entire
    # view with the prepared input, keeping the pinned raw packet untouched.
    state=normalize_owner_stop_state(packet['state'],job['limits'],base['model_bundle'],refs['source_packet'])
    if state!=inputs['state'] or any(packet['state'][k]!=owner[k] for k in ('q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block')):
        raise ValueError('PREPARED_RAW_STATE_OR_PROVENANCE_CHANGED')
    if request['attachment']!=owner['attachment_tcp_to_block'] or r['q_rad']!=owner['q_rad'] or r['grip_rad']!=owner['grip_rad']:
        raise ValueError('PREPARED_GEOMETRY_NOT_SOURCE_OBSERVATION')
    binding={k:request[k] for k in BINDING};prep=envelope['model_preparation']
    if (envelope['request_sha256']!=refs['cache_request']['sha256'] or envelope['inputs_sha256']!=refs['prepared_inputs']['sha256'] or
            envelope['thresholds_digest']!=digest(job['limits']) or envelope['binding']!=binding or
            prep['source_model']!=base['model_bundle'] or prep['binding']!=binding or
            prep['attachment']!=request['attachment'] or prep['grip_rad']!=r['grip_rad'] or
            prep['world_geometry_digest']!=digest(r['world_objects']) or
            envelope['online_validity']!=online_contract(request,inputs)):
        raise ValueError('PREPARED_ENVELOPE_GEOMETRY_OR_RECEIPT_CHANGED')
    if context is not None and (context['identity']!=job['identity'] or context['envelope']!=refs['calculated_envelope'] or context['obstacles']!=refs['prepared_inputs']):
        raise ValueError('PREPARED_CONTEXT_NOT_SELECTED_INPUTS')
    for key,ref in refs.items():
        if sha(ref['path'])!=ref['sha256']:raise ValueError('PREPARED_SOURCE_CHANGED_DURING_REVIEW:'+key)
    return dict(scope='PREPARED_INPUT_ADMISSION_NOT_SDK_OR_NATIVE_APPROVAL',identity=deepcopy(job['identity']),
        source_refs=deepcopy(refs),original_anchor_digest=digest(base),prepared_request_digest=digest(request),
        current_geometry_proof_required=True,encoded_current_proof_required=True,READY=False,apply_allowed=False,
        native_execution_allowed=False,hardware_execution_allowed=False)


def review_input_reselection(job,owner,pointer,request_ref,closed_selection_provider,owner_lock):
    """D-locked, explicitly closed UNSTARTED expired selection only.

    The D provider must read its authoritative worker registry and revoked
    start gate under the same lock. Caller-supplied SDK_started=false is not
    evidence. No worker cancellation, lease revocation or retry occurs here.
    """
    import time
    import yaml
    if not callable(getattr(owner_lock,'_is_owned',None)) or owner_lock._is_owned() is not True:
        raise ValueError('INPUT_RESELECTION_REQUIRES_D_HELD_LOCK')
    if not callable(closed_selection_provider):raise ValueError('D_CLOSED_SELECTION_PROVIDER_REQUIRED')
    pointer_ref=_file_ref(pointer);selected=_pinned_json(pointer_ref)['job'];old=_pinned_json(selected)
    request=_pinned_json(request_ref)
    if (request.get('schema')!='same-d-prepared-admission-request/0.1' or request.get('previous_selected_job')!=selected or
            digest(request.get('identity'))!=digest(old['identity']) or digest(job['identity'])!=digest(old['identity']) or
            any(type(owner[k]) is not type(old['identity'][k]) or owner[k]!=old['identity'][k] for k in LIVE_IDENTITY)):
        raise ValueError('INPUT_RESELECTION_OLD_REF_OR_IDENTITY_CHANGED')
    prior=old.get('input_selection',{}).get('sequence',1)
    seq=request['sequence'];attempt=request['attempt_id']
    if type(seq) is not int or seq!=prior+1 or not isinstance(attempt,str) or not attempt or len(attempt)>128:
        raise ValueError('INPUT_RESELECTION_SEQUENCE_OR_ATTEMPT_INVALID')
    if old.get('input_selection',{}).get('attempt_id')==attempt:raise ValueError('INPUT_RESELECTION_DUPLICATE_ATTEMPT')
    if job['limits'].get('geometry_observation_mode')!='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF':
        raise ValueError('INPUT_RESELECTION_EXPLICIT_PREPARED_MODE_REQUIRED')
    if job['base_request']!=old['base_request'] or digest(job['limits'])!=digest(old['limits']):
        raise ValueError('INPUT_RESELECTION_ORIGINAL_ANCHOR_OR_LIMITS_CHANGED')
    original=_pinned_json(request['prepared_job'])
    # D adds its immutable approval; all actual private input values stay exact.
    if {k:v for k,v in job.items() if k!='D_input_approval'}!=original:
        raise ValueError('INPUT_RESELECTION_NOT_EXACT_APPROVED_PRIVATE_JOB')
    approval=_pinned_json(job['D_input_approval']);phase=_pinned_json(request['before_SDK_phase'])
    base=yaml.safe_load(Path(job['base_request']['path']).read_text())
    refs=('base_request','cache_request','cache_model_manifest','prepared_inputs','calculated_envelope','fcl_binary','fcl_library','source_owner','source_packet')
    if (approval.get('scope')!='D_PREPARED_CALCULATION_APPROVAL_NOT_READY_OR_APPLY' or
            approval['original_anchor']!=old['base_request'] or approval['original_prepared_job']!=request['prepared_job'] or
            approval['before_SDK']!=request['before_SDK_phase'] or approval['identity']!=job['identity'] or
            approval['prepared_geometry_pins']!={k:job[k] for k in refs} or approval['limits']!=job['limits'] or
            approval['original_target']!=base['goal'] or approval['held_id']!=base['planning_snapshot']['selected_slot_id'] or
            approval.get('requires_original_full_FCL') is not True or approval.get('requires_current_geometry_and_encoded_proof') is not True or
            approval.get('READY') is not False or approval.get('apply_allowed') is not False or
            phase.get('scope')!='NATIVE_PREPARED_CALCULATION_BEFORE_SDK' or phase['job']!=request['prepared_job'] or
            any(phase.get(k) is not False for k in ('SDK_started','FCL_started','READY','apply_allowed'))):
        raise ValueError('INPUT_RESELECTION_D_APPROVAL_BINDING_CHANGED')
    receipt_ref=deepcopy(closed_selection_provider());closed=_pinned_json(receipt_ref)
    if any(k not in closed for k in ('worker_registry','start_gate','original_request','owner')):
        raise ValueError('INPUT_RESELECTION_AUTHORITATIVE_CLOSURE_REQUIRED')
    original_request=_pinned_json(closed['original_request'])
    old_approval=_pinned_json(old['D_input_approval'])
    if (original_request['sequence']!=prior or original_request['identity']!=old['identity'] or
            original_request['prepared_job']!=old_approval['original_prepared_job'] or
            original_request['before_SDK_phase']!=old_approval['before_SDK']):
        raise ValueError('INPUT_RESELECTION_ORIGINAL_REQUEST_NOT_SELECTED')
    seen=set();ancestor=old
    while 'input_selection' in ancestor:
        previous=ancestor['input_selection']
        if previous['attempt_id']==attempt or previous['previous_selected_job']['path'] in seen:
            raise ValueError('INPUT_RESELECTION_DUPLICATE_ATTEMPT_OR_HISTORY_CYCLE')
        seen.add(previous['previous_selected_job']['path'])
        ancestor=_pinned_json(previous['previous_selected_job'])
    if original_request['attempt_id']==attempt:raise ValueError('INPUT_RESELECTION_DUPLICATE_ATTEMPT')
    registry=_pinned_json(closed['worker_registry']);gate=_pinned_json(closed['start_gate'])
    if (closed.get('scope')!='D_CLOSED_UNSTARTED_INPUT_SELECTION_NOT_EXECUTION_SUCCESS' or closed.get('single_writer')!='D' or
            closed.get('selected_job')!=selected or closed.get('selection_sequence')!=prior or
            closed.get('next_request')!=request_ref or _pinned_json(closed['owner'])!=owner or
            closed.get('reason')!='EXPIRED_BEFORE_ANY_WORKER_START' or not closed.get('source_pins')):
        raise ValueError('INPUT_RESELECTION_AUTHORITATIVE_CLOSURE_REQUIRED')
    if (registry.get('scope')!='D_COMPLETE_INPUT_WORKER_REGISTRY' or registry.get('selected_job')!=selected or
            registry.get('complete_for')!=['SDK','FCL','WORKER','APPLY','SEND'] or registry.get('registered')!=[] or
            registry.get('started_counts')!={k:0 for k in ('SDK','FCL','WORKER','APPLY','SEND')} or
            any(type(v) is not int for v in registry.get('started_counts',{}).values()) or
            gate.get('scope')!='D_INPUT_START_GATE_REVOKED' or gate.get('selected_job')!=selected or
            gate.get('revoked') is not True or type(gate.get('outstanding_permits')) is not int or gate['outstanding_permits']!=0 or
            type(gate.get('generation')) is not int or gate['generation']<0 or registry.get('gate_generation')!=gate['generation']):
        raise ValueError('INPUT_RESELECTION_ACTIVE_OR_UNKNOWN_WORKER_HOLD')
    oldenv=_pinned_json(old['calculated_envelope'])['online_validity']
    newenv=_pinned_json(job['calculated_envelope'])['online_validity'];now=time.monotonic()
    if newenv['policy']!=oldenv['policy']:raise ValueError('INPUT_RESELECTION_ORIGINAL_DEADLINE_POLICY_CHANGED')
    oldage=now-finite(oldenv['observation_wall_monotonic_s']);newage=now-finite(newenv['observation_wall_monotonic_s'])
    if oldage<=finite(oldenv['policy']['max_sensor_to_apply_wall_s']):raise ValueError('INPUT_RESELECTION_OLD_INPUT_NOT_EXPIRED')
    if not 0<=newage<finite(newenv['policy']['max_sensor_to_apply_wall_s']):raise ValueError('INPUT_RESELECTION_NEW_INPUT_EXPIRED')
    if any(job[k]['sha256']==old[k]['sha256'] or job[k]['path']==old[k]['path'] for k in ('cache_request','source_packet')):
        raise ValueError('INPUT_RESELECTION_REQUIRES_NEW_INPUT_NOT_ALIAS')
    previous_owner=_pinned_json(old['source_owner']);next_owner=_pinned_json(job['source_owner'])
    if next_owner['state_sequence']<=previous_owner['state_sequence'] or next_owner['state_stamp_s']<=previous_owner['state_stamp_s']:
        raise ValueError('INPUT_RESELECTION_SOURCE_NOT_ADVANCED')
    same_owner(owner,owner);review_stop(owner,job['limits']['owner_review_limits'])
    checked=[selected,request_ref,request['prepared_job'],request['before_SDK_phase'],job['D_input_approval'],
             receipt_ref,closed['owner'],closed['worker_registry'],closed['start_gate'],closed['original_request'],old['D_input_approval'],
             old['calculated_envelope'],job['calculated_envelope'],old['source_owner'],job['source_owner']]+list(closed['source_pins'].values())
    if sha(pointer_ref['path'])!=pointer_ref['sha256'] or any(sha(ref['path'])!=ref['sha256'] for ref in checked) or closed_selection_provider()!=receipt_ref:
        raise ValueError('INPUT_RESELECTION_SOURCE_RACE_HOLD')
    return dict(scope='D_EXPLICIT_INPUT_RESELECTION_NOT_RETRY_OR_EXECUTION',sequence=seq,attempt_id=attempt,
        request=deepcopy(request_ref),previous_selected_job=selected,previous_selected_pointer=pointer_ref,
        previous_selected_pointer_as_read=_pinned_json(pointer_ref),
        closed_selection=receipt_ref,D_input_approval=job['D_input_approval'],reason=closed['reason'],
        new_input_deadline_wall_monotonic_s=newenv['observation_wall_monotonic_s']+newenv['policy']['max_sensor_to_apply_wall_s'],
        old_input_age_wall_s=oldage,checked_source_pins=checked,READY=False,apply_allowed=False)


def _freeze_online_job(job,owner):
    """Bounded synchronous CPU input review; caller chooses scheduling/lock."""
    import yaml
    from calculate_cumotion import solver_fingerprint
    from prepare_cumotion_model import read_cumotion_model
    identity={k:owner[k] for k in LIVE_IDENTITY}
    if job['identity']!=identity:raise ValueError('JOB_NOT_CURRENT_STOP_OWNER')
    same_owner(owner,owner)
    stop_report={};review_stop(owner,job['limits']['owner_review_limits'],observation_report=stop_report)
    if owner['stop_record']['source_kind']!='SIM_OWNER_RECORD':raise ValueError('ACTUAL_SIM_STOP_JOB_REQUIRED')
    frozen=deepcopy(job)
    frozen['stop_observation_review']=stop_report
    frozen['observation_criteria']=describe_observation_limits(job['limits']['owner_review_limits'],applies_to='actual owner STOP observation',sources=job.get('criteria_sources'))
    for key in ('base_request','fcl_binary','fcl_library','cache_request','cache_model_manifest'):
        ref=frozen[key]
        if sha(ref['path'])!=ref['sha256']:raise ValueError('JOB_SELECTED_INPUT_CHANGED:'+key)
    if frozen.get('previous_cursor'):_pinned_json(frozen['previous_cursor'])
    model=Path(frozen['cache_model_manifest']['path']).parent
    request,manifest=read_cumotion_model(model,Path(frozen['cache_request']['path']))
    frozen['cache_files']={name:_file_ref(model/name) for name in manifest['files']}
    if any(frozen['cache_files'][name]['sha256']!=expected for name,expected in manifest['files'].items()):raise ValueError('JOB_CACHE_CHANGED_DURING_FREEZE')
    frozen['cache_fingerprint']=solver_fingerprint(request,model)
    if frozen['review_args']['expected_fcl_sha256']!=frozen['fcl_library']['sha256'] or frozen['review_args']['next_goal_version']!=owner['goal_version']+1:raise ValueError('JOB_LIBRARY_OR_NEXT_VERSION_CHANGED')
    if finite(frozen['transition_duration_s'])<=0:raise ValueError('JOB_TRANSITION_DURATION_REQUIRED')
    base=yaml.safe_load(Path(frozen['base_request']['path']).read_text())
    if frozen['limits'].get('geometry_observation_mode')=='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF':
        frozen['prepared_input_admission']=review_prepared_job_inputs(frozen,base,request)
    elif base['model_bundle']!=request['model_bundle'] or base['attachment']!=owner['attachment_tcp_to_block']:raise ValueError('JOB_BASE_MODEL_OR_ATTACHMENT_CHANGED')
    return frozen


def _admission_source_pins():
    """Files must stay unchanged; loaded-source provenance remains D-owned."""
    import sys
    roots=(Path(__file__).resolve().parent,Path(__file__).resolve().parents[1]/'scripts')
    paths={Path(__file__).resolve()}
    for module in list(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if filename and filename.endswith('.py'):
            path=Path(filename).resolve()
            if path.is_file() and any(path.is_relative_to(root) for root in roots):paths.add(path)
    return [_file_ref(path) for path in sorted(paths)]


def _input_refs(*values):
    found={}
    def visit(value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):
                found[(value['path'],value['sha256'])]=dict(path=value['path'],sha256=value['sha256'])
            for item in value.values():visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    for value in values:visit(value)
    return list(found.values())


def prepare_online_job(folder,job_ref,checkpoint_owner_ref,checkpoint_packet_ref):
    """One CPU call outside D lock. Immutable review ONLY, never current approval."""
    import time
    import yaml
    # Import the commit validator before source pin collection, without running it.
    from live_cumotion_boundary import verify_owner_state
    started=time.monotonic();job=_pinned_json(job_ref)
    owner=_pinned_json(checkpoint_owner_ref);packet=_pinned_json(checkpoint_packet_ref)
    if (packet['state']['owner_evidence']!=checkpoint_owner_ref or
            any(packet['state'][k]!=owner[k] for k in ('q_rad','v_rad_s','a_rad_s2','grip_rad','attachment_tcp_to_block'))):
        raise ValueError('PREPARE_CHECKPOINT_NOT_PINNED_RAW_OWNER')
    if 'input_selection' in job or job['limits'].get('geometry_observation_mode')!='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF':
        raise ValueError('SPLIT_ADMISSION_FRESH_FIRST_PREPARED_INPUT_ONLY')
    if any(job.get(k) is not False for k in ('READY','apply_allowed','hardware_execution_allowed')):
        raise ValueError('SPLIT_PREPARATION_NOT_NONEXECUTABLE_INPUT')
    source_before=_admission_source_pins()
    frozen=_freeze_online_job(job,owner)
    base=yaml.safe_load(Path(job['base_request']['path']).read_text())
    approval=_pinned_json(job['D_input_approval']);private=_pinned_json(approval['original_prepared_job'])
    if (approval.get('scope')!='D_PREPARED_CALCULATION_APPROVAL_NOT_READY_OR_APPLY' or
            {k:v for k,v in job.items() if k!='D_input_approval'}!=private or
            approval['original_anchor']!=job['base_request'] or approval['identity']!=job['identity'] or
            approval['limits']!=job['limits'] or approval['original_target']!=base['goal'] or
            approval['held_id']!=base['planning_snapshot']['selected_slot_id'] or
            approval.get('READY') is not False or approval.get('apply_allowed') is not False or
            approval.get('requires_original_full_FCL') is not True or approval.get('requires_current_geometry_and_encoded_proof') is not True):
        raise ValueError('SPLIT_PREPARATION_D_APPROVAL_CHANGED')
    if verify_owner_state(base,packet['state'],packet['control'],job['limits'])!=owner:
        raise ValueError('SPLIT_PREPARATION_CHECKPOINT_CHANGED')
    manifest=_pinned_json(job['cache_model_manifest'])
    pins=_input_refs(job_ref,checkpoint_owner_ref,checkpoint_packet_ref,frozen,owner,packet,approval,manifest)
    # Original model files and derived cache files keep their full original pins.
    bundle=base['model_bundle']
    pins+=[dict(path=str(Path(bundle['bundle_path'])/name),sha256=value) for name,value in bundle['files'].items()]
    source_after=_admission_source_pins()
    pins=_input_refs(pins,source_after)
    if any(sha(ref['path'])!=ref['sha256'] for ref in pins+source_before):raise ValueError('SPLIT_PREPARATION_SOURCE_CHANGED')
    envelope=_pinned_json(job['calculated_envelope']);contract=envelope['online_validity']
    deadline=finite(contract['observation_wall_monotonic_s'])+finite(contract['policy']['max_sensor_to_apply_wall_s'])
    value=dict(scope='PREPARED_NATIVE_INPUT_REVIEW_NOT_CURRENT_SELECTION_OR_EXECUTION',job_ref=job_ref,
        checkpoint_owner=checkpoint_owner_ref,checkpoint_packet=checkpoint_packet_ref,frozen_job=frozen,
        original_base=base,immutable_pins=pins,source_pins=source_after,original_input_deadline_wall_monotonic_s=deadline,
        prepare_wall_s=time.monotonic()-started,READY=False,apply_allowed=False,actual_current_verified=False,
        current_full_FCL_and_encoded_proof_required=True)
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    return _exclusive_json(folder/('prepare_'+digest([job_ref,checkpoint_owner_ref,checkpoint_packet_ref])+'.json'),value)


def _review_selection_clock(observation,job):
    from dynamic_cumotion_inputs import verify_seal
    owner=observation['owner'];packet=observation['packet'];clock=observation['clock_now']
    if any(type(clock[k]) is not type(owner[k]) or clock[k]!=owner[k] for k in ('session_id','clock_basis','clock_epoch')):
        raise ValueError('COMMIT_CURRENT_SOURCE_CLOCK_IDENTITY_CHANGED')
    now=finite(clock['now_s'])
    if now<finite(owner['now_s']) or not 0<=now-finite(owner['state_stamp_s'])<=job['limits']['owner_review_limits']['max_state_age_s']:
        raise ValueError('COMMIT_ACTUAL_CURRENT_STATE_STALE')
    bound=packet['latest_depth_bound'];depth=packet['latest_depth']
    verify_seal(bound);verify_seal(depth)
    if (bound['candidate_digest']!=depth['digest'] or bound['source_session_id']!=owner['session_id'] or
            bound['clock_basis']!=owner['clock_basis'] or
            bound['source_stamp_s']!=depth['source_stamp_s'] or
            not 0<=now-finite(bound['source_stamp_s'])<=job['limits']['max_obstacle_age_s'] or
            now>finite(bound['valid_until_s'])):
        raise ValueError('COMMIT_ACTUAL_CURRENT_DEPTH_STALE_OR_CHANGED')
    return deepcopy(clock)


def _commit_prepared_online_job(folder,pointer,prepared_ref,*,owner_pointer,owner_lock,current_observation_provider):
    """Trusted D-issued preparation; no model reader/fingerprint/envelope replay."""
    import time
    from dynamic_cumotion_inputs import verify_seal,check_control
    from live_cumotion_boundary import verify_owner_state
    if not callable(getattr(owner_lock,'_is_owned',None)) or owner_lock._is_owned() is not True:
        raise ValueError('SPLIT_COMMIT_REQUIRES_D_HELD_LOCK')
    if not callable(current_observation_provider):raise ValueError('SPLIT_COMMIT_ACTUAL_CURRENT_PROVIDER_REQUIRED')
    prepared=_pinned_json(prepared_ref)
    if (prepared.get('scope')!='PREPARED_NATIVE_INPUT_REVIEW_NOT_CURRENT_SELECTION_OR_EXECUTION' or
            prepared.get('READY') is not False or prepared.get('apply_allowed') is not False):
        raise ValueError('SPLIT_COMMIT_PREPARATION_SCOPE_CHANGED')
    if Path(pointer).exists():raise ValueError('SPLIT_COMMIT_FIRST_SELECTION_ONLY_NO_REPLACEMENT')
    pins=prepared['immutable_pins']
    if any(sha(ref['path'])!=ref['sha256'] for ref in pins):raise ValueError('SPLIT_COMMIT_IMMUTABLE_INPUT_OR_SOURCE_CHANGED')
    if time.monotonic()>=prepared['original_input_deadline_wall_monotonic_s']:raise ValueError('SPLIT_COMMIT_ORIGINAL_INPUT_WALL_EXPIRED')
    job=deepcopy(prepared['frozen_job']);base=prepared['original_base']
    latest=deepcopy(current_observation_provider())
    if not isinstance(latest,dict) or any(k not in latest for k in ('owner','packet','owner_ref','packet_ref','clock_now')):
        raise ValueError('SPLIT_COMMIT_ACTUAL_CURRENT_OBSERVATION_REQUIRED')
    owner=latest['owner'];packet=latest['packet']
    pointer_ref=_file_ref(owner_pointer)
    if (_pinned_json(pointer_ref).get('packet')!=latest['packet_ref'] or _pinned_json(latest['owner_ref'])!=owner or
            _pinned_json(latest['packet_ref'])!={k:v for k,v in packet.items() if k!='_source_packet_evidence'} or
            packet['state']['owner_evidence']!=latest['owner_ref']):raise ValueError('SPLIT_COMMIT_NOT_ACTUAL_CURRENT_PUBLICATION')
    if any(type(owner[k]) is not type(job['identity'][k]) or owner[k]!=job['identity'][k] for k in LIVE_IDENTITY):
        raise ValueError('SPLIT_COMMIT_CURRENT_LIFECYCLE_CHANGED')
    if (job['limits'].get('stop_observation_mode')=='D_OWNER_VERIFIED_REPORT_ONLY' or 'owner_review_limits' in owner):
        if _pinned_json(owner['owner_review_limits'])!=job['limits']['owner_review_limits']:
            raise ValueError('SPLIT_COMMIT_CURRENT_OWNER_LIMITS_CHANGED')
    verify_seal(packet['state']);check_control(packet['control']);clock=_review_selection_clock(latest,job)
    if verify_owner_state(base,packet['state'],packet['control'],job['limits'])!=owner:
        raise ValueError('SPLIT_COMMIT_CURRENT_RAW_OWNER_CHANGED')
    if (owner['model_manifest_sha256']!=base['model_bundle']['manifest_sha256'] or
            owner.get('holding_confirmed') is not True or packet['state'].get('holding_confirmed') is not True or
            not owner.get('contact_fingers') or packet.get('timeline_running') is not True or
            packet.get('obstacle_motion_policy')!='CONTINUE_WHILE_ROBOT_HOLDS'):
        raise ValueError('SPLIT_COMMIT_CURRENT_MODEL_HOLDING_OR_SOURCE_INVALID')
    same_owner(owner,owner)
    report={};review_stop(owner,job['limits']['owner_review_limits'],observation_report=report)
    job['preparation_stop_observation_review']=job['stop_observation_review'];job['stop_observation_review']=report
    job['input_preparation_ref']=deepcopy(prepared_ref)
    job['input_commit_observation']=dict(owner=latest['owner_ref'],packet=latest['packet_ref'],clock_now=clock,
        scope='D_CURRENT_INPUT_SELECTION_ONLY_NOT_SDK_FCL_OR_APPLY',READY=False,apply_allowed=False)
    # Refuse changed latest data immediately before immutable write/atomic select.
    after=deepcopy(current_observation_provider())
    if {k:v for k,v in after.items() if k!='clock_now'}!={k:v for k,v in latest.items() if k!='clock_now'}:
        raise ValueError('SPLIT_COMMIT_CURRENT_SOURCE_RACE')
    _review_selection_clock(after,job)
    if (sha(owner_pointer)!=pointer_ref['sha256'] or sha(prepared_ref['path'])!=prepared_ref['sha256'] or
            any(sha(ref['path'])!=ref['sha256'] for ref in pins+[latest['owner_ref'],latest['packet_ref']]) or
            time.monotonic()>=prepared['original_input_deadline_wall_monotonic_s'] or owner_lock._is_owned() is not True):
        raise ValueError('SPLIT_COMMIT_FINAL_SOURCE_OR_TIME_CHANGED')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    ref=_exclusive_json(folder/('job_'+digest(job['identity'])+'.json'),job)
    final=deepcopy(current_observation_provider())
    if {k:v for k,v in final.items() if k!='clock_now'}!={k:v for k,v in latest.items() if k!='clock_now'}:
        raise ValueError('SPLIT_COMMIT_SOURCE_CHANGED_DURING_WRITE')  # immutable orphan is NOT selected
    _review_selection_clock(final,job)
    if (sha(owner_pointer)!=pointer_ref['sha256'] or any(sha(pin['path'])!=pin['sha256'] for pin in pins) or
            time.monotonic()>=prepared['original_input_deadline_wall_monotonic_s'] or owner_lock._is_owned() is not True):
        raise ValueError('SPLIT_COMMIT_SOURCE_OR_TIME_CHANGED_DURING_WRITE')
    _atomic_pointer(pointer,dict(schema='live-cumotion-job-publication/0.1',job=ref))
    return ref


def publish_online_job(folder,pointer,job,owner,*,reselection=None):
    """Legacy one-call review/publication. New callers use split prepare/commit."""
    frozen=_freeze_online_job(job,owner);identity=frozen['identity']
    selection=None
    if reselection is not None:
        selection=review_input_reselection(job,owner,pointer,**reselection)
        frozen['input_selection']=selection
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    for ref in [frozen[k] for k in ('base_request','fcl_binary','fcl_library','cache_request','cache_model_manifest')]+list(frozen['cache_files'].values()):
        if sha(ref['path'])!=ref['sha256']:raise ValueError('JOB_INPUT_CHANGED_DURING_FREEZE')
    suffix='' if selection is None else '_input_'+str(selection['sequence'])+'_'+digest(selection['request'])
    job_path=folder/('job_'+digest(identity)+suffix+'.json')  # exclusive creation prevents duplicate attempts after restart
    ref=_exclusive_json(job_path,frozen)
    publication=dict(schema='live-cumotion-job-publication/0.1',job=ref)
    if selection is not None:
        import time
        if (any(sha(pin['path'])!=pin['sha256'] for pin in selection['checked_source_pins']) or
                sha(pointer)!=selection['previous_selected_pointer']['sha256'] or
                reselection['closed_selection_provider']()!=selection['closed_selection'] or
                time.monotonic()>=selection['new_input_deadline_wall_monotonic_s'] or
                reselection['owner_lock']._is_owned() is not True):
            raise ValueError('INPUT_RESELECTION_SOURCE_RACE_HOLD')  # orphan immutable input is NOT selected
        history=_exclusive_json(folder/(job_path.stem+'.selection.json'),dict(selection,new_selected_job=ref))
        publication['input_selection_history']=history
    _atomic_pointer(pointer,publication)
    return ref


def read_calculated_context(pointer,identity):
    """Context pointer appears after preparation, before model/SDK result; freeze it once."""
    from dynamic_cumotion_inputs import verify_seal
    p=Path(pointer)
    if not p.is_file():return None
    ref=_file_ref(p);value=_pinned_json(ref)
    if value['schema']!='live-cumotion-calculated-context/0.1' or value['identity']!=identity:raise ValueError('CALCULATED_CONTEXT_IDENTITY_CHANGED')
    envelope=_pinned_json(value['envelope']);inputs=_pinned_json(value['obstacles'])
    verify_seal(envelope,'envelope_digest')
    if envelope.get('online_validity',{}).get('identity')!=identity:raise ValueError('ARCHIVED_OR_OTHER_CALCULATION_CONTEXT')
    if envelope['inputs_sha256']!=value['obstacles']['sha256']:raise ValueError('CALCULATED_INPUT_PIN_CHANGED')
    request_path=Path(value['envelope']['path']).parent/'TRANSPORT.request.yaml'
    if sha(request_path)!=envelope['request_sha256']:raise ValueError('CALCULATED_REQUEST_PIN_CHANGED')
    return dict(pointer_ref=ref,envelope=envelope,inputs=inputs,request_ref=_file_ref(request_path))


def review_live_current_geometry(selection,publication,loaded,job_ref,calculated_context_ref,*,current_owner):
    """Additional LIVE proof only; no exemption from original context/geometry gates.

    Selection is D-owned {proof_ref,files,snapshot_provider}. Original receipt,
    candidate and whole curve stay immutable. Archive proofs never authorize.
    """
    from current_geometry_fcl import LIVE,review_current_geometry_proof,exact_encoded_command
    if not callable(selection['snapshot_provider']) or current_owner is None:
        raise ValueError('INDEPENDENT_CURRENT_GEOMETRY_PROVIDER_AND_OWNER_REQUIRED')
    proof=_pinned_json(selection['proof_ref']);files=selection['files']
    if proof['scope']!=LIVE or proof['snapshot']['scope']!=LIVE:
        raise ValueError('ARCHIVED_GEOMETRY_PROOF_NOT_LIVE')
    if proof['calculation_files']!=files:raise ValueError('CURRENT_GEOMETRY_FILES_NOT_PROOF')
    job=_pinned_json(job_ref);context=_pinned_json(calculated_context_ref)
    if 'input_selection' in job and (context.get('selected_job')!=job_ref or publication.get('selected_job')!=job_ref):
        raise ValueError('INPUT_RESELECTION_OUTPUT_NOT_EXACT_SELECTED_JOB')
    if (files['report']!=publication['artifacts']['suffix_report'] or files['candidate']!=publication['artifacts']['candidate'] or
        files['fcl_binary']!=job['fcl_binary'] or files['fcl_library']!=job['fcl_library']):
        raise ValueError('CURRENT_GEOMETRY_NOT_SELECTED_JOB_FILES')
    command=_pinned_json(files['command']);candidate=_pinned_json(files['candidate'])
    if candidate!=loaded['candidate'] or proof['whole_command_digest']!=digest(command):
        raise ValueError('CURRENT_GEOMETRY_WHOLE_WIRE_CHANGED')
    if 'command_encoding' in files:
        exact_encoded_command(candidate['trajectory'],command)  # canonical encoded loader/reviewer checks all receipt/delivery pins below
    elif command!=candidate['trajectory'] or digest(command)!=digest(candidate['trajectory']):
        raise ValueError('CURRENT_GEOMETRY_WHOLE_WIRE_CHANGED')
    if proof['original_suffix_digest']!=candidate['suffix_digest'] or candidate['suffix_digest']!=digest(loaded['suffix']):
        raise ValueError('CURRENT_GEOMETRY_ORIGINAL_SUFFIX_CHANGED')
    snapshot=deepcopy(selection['snapshot_provider']())
    if snapshot!=proof['snapshot']:raise ValueError('CURRENT_GEOMETRY_PROVIDER_CHANGED')
    if (snapshot['selected_job']!=job_ref or snapshot['calculated_envelope']!=context['envelope'] or
        snapshot['calculation_report']!=files['report'] or snapshot['selected_fcl_binary']!=files['fcl_binary'] or
        snapshot['selected_fcl_library']!=files['fcl_library']):raise ValueError('CURRENT_GEOMETRY_JOB_CONTEXT_CHANGED')
    original_owner=_pinned_json(snapshot['calculation_owner']);owner=_pinned_json(snapshot['owner'])
    if owner!=current_owner:raise ValueError('CURRENT_GEOMETRY_NOT_CURRENT_INDEPENDENT_OWNER')
    if proof['raw_current_PVT']!={k:owner[k] for k in ('q_rad','v_rad_s','a_rad_s2','state_stamp_s')}:
        raise ValueError('CURRENT_GEOMETRY_PROOF_RAW_PVT_CHANGED')
    if proof['actual_geometry']!=dict(grip_rad=owner['grip_rad'],attachment=owner['attachment_tcp_to_block'],
        world_digest=digest({o['id']:o for o in owner['world_objects']})):
        raise ValueError('CURRENT_GEOMETRY_PROOF_SHAPE_CHANGED')
    if any(type(owner[k]) is not type(job['identity'][k]) or owner[k]!=job['identity'][k] or
           type(original_owner[k]) is not type(job['identity'][k]) or original_owner[k]!=job['identity'][k] for k in LIVE_IDENTITY):
        raise ValueError('CURRENT_GEOMETRY_OWNER_LIFECYCLE_CHANGED')
    if any(proof[k] is not False for k in ('calculation_provenance_modified','actual_live_source_verified',
                                          'native_execution_allowed','hardware_execution_allowed','live_resume_approved')):
        raise ValueError('CURRENT_GEOMETRY_PROOF_NOT_COMPUTATIONAL_ONLY')
    if (proof['current_geometry_checked'] is not True or proof['raw_start_FCL']['checked'] is not True or
        proof['raw_start_FCL']['collision'] is not None or proof['analytic_command_limits']['final_quintic_extrema_qva_j_verified'] is not True):
        raise ValueError('CURRENT_GEOMETRY_FULL_COMMAND_RAW_START_REQUIRED')
    if proof['FCL_geometry']['library_sha256']!=files['fcl_library']['sha256'] or proof['FCL_geometry']['robot_geometry']!='ORIGINAL_TRIANGLE_MESH_BVH':
        raise ValueError('CURRENT_GEOMETRY_ORIGINAL_MESH_LIBRARY_REQUIRED')
    # Canonical CU reviewer keeps STOP/clock/desired/geometry/world/Depth TTL and budgets.
    reviewed=review_current_geometry_proof(selection['proof_ref'],files,selection['snapshot_provider'])
    if selection['snapshot_provider']()!=snapshot:raise ValueError('CURRENT_GEOMETRY_PROVIDER_RACE_HOLD')
    refs=list(files.values())+list(snapshot['source_pins'].values())+[snapshot[k] for k in
        ('owner','world','selected_job','calculation_owner','packet','limits','calculated_envelope','calculation_report','selected_fcl_binary','selected_fcl_library')]
    refs+=list(_pinned_json(files['report'])['artifacts'].values())
    if any(sha(ref['path'])!=ref['sha256'] for ref in refs):raise ValueError('CURRENT_GEOMETRY_SOURCE_CHANGED_DURING_REVIEW')
    _pinned_json(selection['proof_ref']);_pinned_json(job_ref);_pinned_json(calculated_context_ref)
    if reviewed['scope']!=LIVE:raise ValueError('CURRENT_GEOMETRY_REVIEW_SCOPE_CHANGED')
    return dict(reviewed,selected_job=deepcopy(job_ref),calculated_context=deepcopy(calculated_context_ref),
        whole_command_digest=digest(command),original_calculation_unchanged=True,geometry_guard_bypassed=False)


def validate_online_delivery(publication,loaded,job_ref,calculated_context_ref,*,current_geometry=None,current_owner=None,pending_handoff=False):
    """Freeze NEW output pins only after binding them to selected job and actual receipt/model/FCL loader."""
    import yaml
    from calculate_cumotion import solver_fingerprint
    from dynamic_cumotion_inputs import verify_seal
    job=_pinned_json(job_ref);context=_pinned_json(calculated_context_ref)
    if 'input_selection' in job and (context.get('selected_job')!=job_ref or publication.get('selected_job')!=job_ref):
        raise ValueError('INPUT_RESELECTION_OUTPUT_NOT_EXACT_SELECTED_JOB')
    if pending_handoff and (publication.get('status')!='PENDING' or publication.get('phase')!='PENDING_CURRENT_GEOMETRY_PROOF_REQUIRED' or
        publication.get('READY') is not False or publication.get('apply_allowed') is not False or
        job['limits'].get('geometry_observation_mode')!='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF'):
        raise ValueError('EXPLICIT_PENDING_HANDOFF_ADMISSION_REQUIRED')
    if not pending_handoff and publication.get('status')!='READY':raise ValueError('WORKER_FAILED_OR_DISCARDED')
    prepared_mode=job['limits'].get('geometry_observation_mode')=='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF'
    if prepared_mode and not pending_handoff and current_geometry is None:
        raise ValueError('PREPARED_CURRENT_FULL_GEOMETRY_PROOF_REQUIRED')
    for key in ('base_request','fcl_binary','fcl_library','cache_request','cache_model_manifest'):
        ref=job[key]
        if sha(ref['path'])!=ref['sha256']:raise ValueError('READY_JOB_INPUT_CHANGED:'+key)
    for ref in job['cache_files'].values():
        if sha(ref['path'])!=ref['sha256']:raise ValueError('READY_CACHE_GEOMETRY_CHANGED')
    if publication['identity']!=job['identity'] or context['identity']!=job['identity']:raise ValueError('READY_JOB_IDENTITY_CHANGED')
    envelope=_pinned_json(context['envelope']);inputs=_pinned_json(context['obstacles'])
    verify_seal(envelope,'envelope_digest')
    if 'online_validity' not in envelope or envelope['online_validity']['identity']!=job['identity']:raise ValueError('READY_CONTEXT_NOT_ONLINE')
    if inputs['limits']!=job['limits'] or (not pending_handoff and publication['review_args']!=job['review_args']):raise ValueError('READY_OWNER_LIMITS_CHANGED')
    report=loaded['suffix_report'];request=loaded['request'];manifest_ref=report['artifacts']['model_manifest']
    manifest=_pinned_json(manifest_ref)
    if report.get('archived_static_source') is not None:raise ValueError('ARCHIVED_WORKER_RESULT_NOT_LIVE')
    if (envelope['request_sha256']!=publication['artifacts']['request']['sha256'] or
            envelope['inputs_sha256']!=context['obstacles']['sha256'] or
            report['artifacts']['request']!=publication['artifacts']['request']):raise ValueError('READY_NOT_PINNED_CALCULATED_REQUEST')
    base=yaml.safe_load(Path(job['base_request']['path']).read_text())
    if pending_handoff and request['goal']!=base['goal']:raise ValueError('FINAL_REPLAN_TARGET_NOT_ORIGINAL_SELECTED_TARGET')
    if (Path(inputs['base_request_path']).resolve()!=Path(job['base_request']['path']).resolve() or
            inputs['base_request_sha256']!=job['base_request']['sha256']):raise ValueError('READY_DIFFERENT_SELECTED_BASE_ANCHOR')
    new_binding={k:request[k] for k in BINDING}
    if new_binding!=envelope['binding'] or any(type(new_binding[k]) is not type(envelope['binding'][k]) for k in BINDING):raise ValueError('READY_NEW_REQUEST_BINDING_NOT_CALCULATED_ENVELOPE')
    # Only these two digests are derived anew by common-A scene preparation.
    # Stable A/Current/reservation/model identity remains bound to the selected anchor.
    stable=tuple(k for k in BINDING if k not in ('scene_digest','planning_request_digest'))
    if prepared_mode:
        admission=review_prepared_job_inputs(job,base,request,context=context)
        if job.get('prepared_input_admission')!=admission:raise ValueError('PREPARED_JOB_NOT_NATIVE_ADMITTED')
    if (any(type(request[k]) is not type(base[k]) or request[k]!=base[k] for k in stable) or
            request['motion_input_digest']!=base['motion_input_digest'] or
            request['model_bundle']!=base['model_bundle'] or (not prepared_mode and request['attachment']!=base['attachment'])):raise ValueError('READY_CHANGED_OWNER_BASE_BINDING_OR_MODEL')
    if manifest['geometry_reuse']['original_model_manifest_sha256']!=job['cache_model_manifest']['sha256']:raise ValueError('READY_DIFFERENT_CACHE_GEOMETRY')
    if (not pending_handoff and publication['cache_fingerprint']!=job['cache_fingerprint']) or solver_fingerprint(request,Path(report['model_folder']))!=job['cache_fingerprint']:raise ValueError('READY_CACHE_FINGERPRINT_CHANGED')
    pins={key:ref['sha256'] for key,ref in report['artifacts'].items()}
    pins.update(receipt=publication['artifacts']['suffix_report']['sha256'],fcl_binary=job['fcl_binary']['sha256'])
    packet=receive_engine(CUMOTION,publication['artifacts']['suffix_report']['path'],
        dict(artifact_pins=pins,motion_request=loaded['motion_request'],binding=new_binding))
    if packet['trajectory']!=loaded['suffix']:raise ValueError('READY_SUFFIX_NOT_VERIFIED_FCL_CURVE')
    if loaded['candidate']['suffix_digest']!=digest(packet['trajectory']):raise ValueError('READY_CONNECTION_CHANGED_SUFFIX')
    transition_source=loaded['transition_source']
    if transition_source['phase']!='TRANSITION_PREPARE' or transition_source['observed']!=loaded['candidate']['observed'] or transition_source['desired']!=loaded['candidate']['desired']:raise ValueError('READY_TRANSITION_SOURCE_PVT_CHANGED')
    _pinned_json(transition_source['owner_evidence']);_pinned_json(transition_source['source_packet_evidence'])
    if sha(job['fcl_library']['path'])!=job['fcl_library']['sha256']:raise ValueError('READY_WHOLE_FCL_LIBRARY_CHANGED')
    if current_geometry is not None:
        review_live_current_geometry(current_geometry,publication,loaded,job_ref,calculated_context_ref,current_owner=current_owner)
    # The later live review validates full connection receipt and current PVT/envelope again.
    return pins


def review_pending_geometry_handoff(publication_ref,job_ref,context_ref,selection,observation_provider,*,transition_source_verification=None):
    """Dedicated D final-review path, not computational CU D_APPLY or READY relabelling.

    Reads a pinned PENDING publication plus independent current LIVE geometry
    evidence. No FCL/SDK solve, dispatcher, reservation or send here.
    """
    if selection is None or not selection.get('proof_ref') or not callable(observation_provider):
        return blocked('WAIT_CURRENT_GEOMETRY_PROOF_AND_INDEPENDENT_D_OBSERVATION')
    import yaml
    from dynamic_cumotion_inputs import verify_seal,check_control,validate_stopped_state,owner_observations,normalize_owner_stop_state
    from live_cumotion_boundary import verify_owner_state,verify_reference_time_association
    from online_cumotion_validity import check_online_context
    publication=_pinned_json(publication_ref);job=_pinned_json(job_ref);context=_pinned_json(context_ref)
    if (publication['schema']!='live-resume-worker-publication/0.1' or publication['status']!='PENDING' or
        publication.get('phase')!='PENDING_CURRENT_GEOMETRY_PROOF_REQUIRED' or
        publication.get('READY') is not False or publication.get('apply_allowed') is not False or
        publication.get('current_geometry_proof_required') is not True or publication.get('original_geometry_FCL_only') is not True):
        raise ValueError('ORIGINAL_COMPUTATIONAL_PENDING_REQUIRED')
    if publication['identity']!=job['identity'] or context['identity']!=job['identity']:
        raise ValueError('PENDING_JOB_OR_CONTEXT_CHANGED')
    if job['limits'].get('geometry_observation_mode')!='COMPUTE_ONLY_GRIP_ATTACHMENT_REQUIRES_CURRENT_GEOMETRY_PROOF':
        raise ValueError('FROZEN_OWNER_COMPUTATIONAL_MODE_REQUIRED')
    proof=_pinned_json(selection['proof_ref'])
    if proof['scope']!='LIVE_CURRENT_GEOMETRY_FCL_CANDIDATE_NOT_D_APPROVAL' or proof['snapshot']['scope']!=proof['scope']:
        raise ValueError('ARCHIVED_GEOMETRY_PROOF_NOT_LIVE')
    loaded={}
    for key,ref in publication['artifacts'].items():
        if sha(ref['path'])!=ref['sha256']:raise ValueError('PENDING_ARTIFACT_PIN_CHANGED:'+key)
        loaded[key]=yaml.safe_load(Path(ref['path']).read_text()) if key=='request' else _pinned_json(ref)
    first=deepcopy(observation_provider());owner=first['owner'];packet=first['packet']
    # Keep ORIGINAL job/cache/request/SDK/FCL admission even in the dedicated path.
    pins=validate_online_delivery(publication,loaded,job_ref,context_ref,pending_handoff=True)
    candidate=loaded['candidate'];curve=candidate['trajectory'];wire=native_wire_expected(curve)
    # ROS JointTrajectory PVA arrays serialize as doubles, including integer zeros.
    # Keep originals untouched; predict exact delivered JSON/digest independently.
    for point in wire['points']:
        for field in ('positions_rad','velocities_rad_s','accelerations_rad_s2'):
            point[field]=[float(v) for v in point[field]]
    from current_geometry_fcl import exact_encoded_command
    encoding_equivalence=exact_encoded_command(curve,wire)
    args=job['review_args'];request=loaded['request'];whole=loaded['whole_curve_receipt']
    import xml.etree.ElementTree as ET
    robot=ET.fromstring(request['model_bundle']['robot_description'])
    model_bounds=[robot.find(f"joint[@name='{name}']/limit") for name in JOINTS]
    if args['lower']!=[float(b.get('lower')) for b in model_bounds] or args['upper']!=[float(b.get('upper')) for b in model_bounds]:
        raise ValueError('PENDING_BOUNDS_NOT_ORIGINAL_MODEL')
    if transition_source_verification is None:return blocked('WAIT_ORIGINAL_NATIVE_TRANSITION_SOURCE_PIN')
    source=loaded['transition_source'];original_owner=_pinned_json(transition_source_verification['owner_ref'])
    original_packet=_pinned_json(transition_source_verification['packet_ref'])
    if source['owner_evidence']!=transition_source_verification['owner_ref'] or source['source_packet_evidence']!=transition_source_verification['packet_ref']:
        raise ValueError('PENDING_TRANSITION_NOT_NATIVE_D_PUBLISHED_SOURCE')
    if any(type(original_owner[k]) is not type(job['identity'][k]) or original_owner[k]!=job['identity'][k] for k in LIVE_IDENTITY):
        raise ValueError('PENDING_ORIGINAL_NATIVE_SOURCE_LIFECYCLE_CHANGED')
    if (candidate['observed']['stamp_s']!=original_owner['state_stamp_s'] or
        any(candidate['observed'][k]!=original_owner[k] for k in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2')) or
        candidate['desired']!=original_packet['desired']):raise ValueError('PENDING_ORIGINAL_RAW_PVT_OR_DESIRED_CHANGED')
    original_clock=verify_reference_time_association(candidate['desired'],candidate['observed'],now_s=original_owner['now_s'])
    if candidate['tracking_limits']!=args['tracking_limits']:
        raise ValueError('PENDING_OWNER_REVIEW_CRITERIA_CHANGED')
    rebuilt=native_transition_candidate(loaded['suffix'],candidate['desired'],candidate['observed'],
        duration_s=candidate['transition_duration_s'],limits=args['tracking_limits'],lower=args['lower'],upper=args['upper'])
    if rebuilt!=candidate:raise ValueError('PENDING_ORIGINAL_CANDIDATE_RECIPE_CHANGED')
    if (whole['scope']!='WHOLE_TRANSITION_AND_SUFFIX_FCL_NOT_D_APPROVAL' or whole['success'] is not True or
        whole['FCL']['success'] is not True or type(whole['FCL']['checks']) is not int or whole['FCL']['checks']<=0 or
        whole['library_sha256']!=job['fcl_library']['sha256'] or whole['trajectory_digest']!=digest(curve) or
        whole['request_digest']!=request['planning_request_digest'] or whole['model_digest']!=request['model_digest'] or
        whole['binding']!={k:request[k] for k in BINDING}):raise ValueError('ORIGINAL_PENDING_WHOLECURVE_FCL_CHANGED')
    snapshot=proof['snapshot']
    if _pinned_json(snapshot['limits'])!=job['limits']:raise ValueError('CURRENT_GEOMETRY_LIMITS_NOT_FROZEN_JOB')
    if _pinned_json(snapshot['packet'])!={k:v for k,v in packet.items() if k!='_source_packet_evidence'}:
        raise ValueError('CURRENT_GEOMETRY_NOT_INDEPENDENT_CURRENT_PACKET')
    if packet.get('_source_packet_evidence') is not None and packet['_source_packet_evidence']!=snapshot['packet']:
        raise ValueError('CURRENT_PACKET_SOURCE_REF_CHANGED')
    verify_seal(packet['state']);check_control(packet['control'])
    base=yaml.safe_load(Path(job['base_request']['path']).read_text())
    if request['goal']!=base['goal']:raise ValueError('FINAL_REPLAN_TARGET_NOT_ORIGINAL_SELECTED_TARGET')
    if verify_owner_state(base,packet['state'],packet['control'],job['limits'])!=owner:
        raise ValueError('FINAL_INDEPENDENT_RAW_OWNER_MISMATCH')
    same_owner(owner,owner)
    validation_state=packet['state']
    if owner_observations(job['limits']):
        validation_state=normalize_owner_stop_state(packet['state'],job['limits'],base['model_bundle'],snapshot['packet'])
    validate_stopped_state(validation_state,packet['control'],job['limits'])
    if packet.get('timeline_running') is not True or packet.get('obstacle_motion_policy')!='CONTINUE_WHILE_ROBOT_HOLDS':
        raise ValueError('FINAL_NATIVE_PHYSICS_DEPTH_MUST_CONTINUE')
    if any(type(owner[k]) is not type(job['identity'][k]) or owner[k]!=job['identity'][k] for k in LIVE_IDENTITY):
        raise ValueError('FINAL_PENDING_UUID_CANCEL_EPOCH_CHANGED')
    if owner['desired']!=packet['desired']:raise ValueError('FINAL_CURRENT_DESIRED_PACKET_CHANGED')
    for k in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2'):
        if owner['desired'][k]!=candidate['desired'][k]:raise ValueError('FINAL_DESIRED_START_CHANGED_NEW_CANDIDATE_REQUIRED')
    observed=dict(stamp_s=owner['state_stamp_s'],**{k:owner[k] for k in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2')})
    clock=verify_reference_time_association(owner['desired'],observed,now_s=owner['now_s'])
    tracking=review_tracking_observations(owner['desired'],observed,args['tracking_limits'],source_now_s=owner['now_s'])
    envelope=_pinned_json(context['envelope'])
    if packet['envelope']!=envelope:raise ValueError('FINAL_PACKET_NOT_ORIGINAL_CALCULATED_ENVELOPE')
    dynamic=check_online_context(base,envelope,packet,owner,job['limits'])
    if curve['points'][-1]['time_from_start_s']>dynamic['max_trajectory_duration_s']:
        raise ValueError('FINAL_WHOLE_COMMAND_EXCEEDS_CURRENT_DEPTH_HORIZON')
    geometry=review_live_current_geometry(selection,publication,loaded,job_ref,context_ref,current_owner=owner)
    if deepcopy(observation_provider())!=first:raise ValueError('FINAL_PENDING_SOURCE_CHANGED_REVALIDATE')
    for ref in (publication_ref,job_ref,context_ref):_pinned_json(ref)
    value=dict(scope='D_DEDICATED_PENDING_CURRENT_GEOMETRY_REVIEW_NOT_SEND',
        status='PENDING_CURRENT_GEOMETRY_REVIEWED_D_SERIALIZED_RESERVATION_REQUIRED',
        original_pending_ref=deepcopy(publication_ref),selected_job=deepcopy(job_ref),calculated_context=deepcopy(context_ref),
        selection={k:deepcopy(v) for k,v in selection.items() if k!='snapshot_provider'},
        identity={k:deepcopy(owner[k]) for k in LIVE_IDENTITY},owner_digest=digest(owner),
        current_packet_digest=digest(packet),command_digest=digest(wire),original_suffix_digest=candidate['suffix_digest'],
        original_command_digest=digest(curve),wire_encoding_equivalence=encoding_equivalence,
        encoded_current_proof_required=job.get('prepared_input_admission',{}).get('encoded_current_proof_required',False),
        verified_original_output_pins=pins,current_geometry_review=geometry,clock_review=clock,tracking_review=tracking,
        original_transition_source_verification=deepcopy(transition_source_verification),original_clock_review=original_clock,
        dynamic_review=dynamic,wire_header_stamp_ns=args['wire_header_stamp_ns'],next_goal_version=args['next_goal_version'],
        current_source_stamp_s=owner['state_stamp_s'],pending_promoted_to_READY=False,
        computational_D_APPLY_bypassed=False,dedicated_D_review=True,
        native_send_called=False,actual_live_success=False,execution_allowed=False,hardware_execution_allowed=False)
    if type(value['wire_header_stamp_ns']) is not int or not 0<=value['wire_header_stamp_ns']<2**31*10**9 or type(value['next_goal_version']) is not int or value['next_goal_version']!=owner['goal_version']+1:
        raise ValueError('FROZEN_HEADER_OR_NEXT_GOAL_VERSION_CHANGED')
    if value['wire_header_stamp_ns']!=0:raise ValueError('DELAYED_HEADER_REQUIRES_VERIFIED_SOURCE_CLOCK_AND_HORIZON_MAPPING')
    value['review_digest']=digest(value);return value


def typed_goal_snapshot(goal):
    """Actual message data only; no int->double coercion to conceal a bad factory."""
    stamp=goal.trajectory.header.stamp
    if type(stamp.sec) is not int or type(stamp.nanosec) is not int or not 0<=stamp.nanosec<10**9:
        raise ValueError('ACTUAL_TYPED_HEADER_INVALID')
    wire=dict(joint_names=list(goal.trajectory.joint_names),points=[])
    for p in goal.trajectory.points:
        if type(p.time_from_start.sec) is not int or type(p.time_from_start.nanosec) is not int or not 0<=p.time_from_start.nanosec<10**9:
            raise ValueError('ACTUAL_TYPED_DURATION_INVALID')
        wire['points'].append(dict(time_from_start_s=(p.time_from_start.sec*10**9+p.time_from_start.nanosec)/1e9,
            positions_rad=list(p.positions),velocities_rad_s=list(p.velocities),accelerations_rad_s2=list(p.accelerations)))
    return wire,stamp.sec*10**9+stamp.nanosec


class NativeOnlineIPC:
    """One native replan's file connection. Native owner ticks and owns all sends."""
    def __init__(self,folder,*,owner_pointer,job_pointer,result_pointer,calculated_context_pointer,observation_provider):
        if not callable(observation_provider):raise ValueError('NATIVE_OBSERVATION_CALLBACK_REQUIRED')
        self.folder=Path(folder);self.owner_pointer=Path(owner_pointer);self.job_pointer=Path(job_pointer)
        self.result_pointer=Path(result_pointer);self.context_pointer=Path(calculated_context_pointer)
        self.provider=observation_provider;self.current=None;self.job_ref=None;self.job=None
        self.context=None;self.cycle=None;self.last_sequence=None;self.validated_output=None;self.discarded=False
        self.observation_refs={};self.verifier=None;self.verification=None
        self.current_geometry=None
        self.geometry_handoff_ref=None;self.geometry_handoff_used=False
        self.input_selection_sequence=0
        self.prepared_job_ref=None

    def prepare_job(self,job_ref,checkpoint_owner_ref,checkpoint_packet_ref):
        """D's bounded CPU queue calls OUTSIDE owner lock. No selection mutation."""
        if self.discarded or self.job_ref is not None or self.prepared_job_ref is not None:
            raise ValueError('SPLIT_PREPARE_FRESH_FIRST_SELECTION_ONLY')
        prepared=prepare_online_job(self.folder/'input_preparation',job_ref,checkpoint_owner_ref,checkpoint_packet_ref)
        if self.discarded or self.job_ref is not None or self.prepared_job_ref is not None:
            raise ValueError('SPLIT_PREPARE_OWNER_SELECTION_CHANGED')
        self.prepared_job_ref=prepared
        return prepared

    def commit_prepared_job(self,prepared_ref,*,owner_lock,current_observation_provider):
        """D caller holds original lock; only this IPC's issued receipt is accepted."""
        if (self.discarded or self.job_ref is not None or self.prepared_job_ref is None or prepared_ref!=self.prepared_job_ref or
                self.context is not None or self.cycle is not None or self.verification is not None or
                self.geometry_handoff_ref is not None or self.geometry_handoff_used):
            raise ValueError('SPLIT_COMMIT_RECEIPT_NOT_ISSUED_OR_SELECTION_CHANGED')
        ref=_commit_prepared_online_job(self.folder/'jobs',self.job_pointer,prepared_ref,owner_pointer=self.owner_pointer,
            owner_lock=owner_lock,current_observation_provider=current_observation_provider)
        self.job_ref=ref;self.job=_pinned_json(ref);self.input_selection_sequence=1
        return ref

    def review_pending_geometry(self,current_observation_provider):
        """CPU review off the fast tick; no publication/READY mutation."""
        if self.discarded or self.job_ref is None or self.context is None:raise ValueError('CURRENT_PENDING_JOB_NOT_BOUND')
        if self.current_geometry is None:return blocked('WAIT_CURRENT_GEOMETRY_PROOF_AND_INDEPENDENT_D_OBSERVATION')
        publication_ref=_file_ref(self.result_pointer);publication=_pinned_json(publication_ref)
        candidate=_pinned_json(publication['artifacts']['candidate'])
        recorded=self.observation_refs.get(candidate['observed']['stamp_s'])
        value=review_pending_geometry_handoff(publication_ref,self.job_ref,self.context['pointer_ref'],
            self.current_geometry,current_observation_provider,transition_source_verification=recorded)
        if 'review_digest' not in value:return value
        if self.geometry_handoff_ref is not None:
            if _pinned_json(self.geometry_handoff_ref)!=value:raise ValueError('PENDING_HANDOFF_CHANGED_NEW_REVIEW_OR_JOB_REQUIRED')
        else:self.geometry_handoff_ref=_exclusive_json(self.folder/'pending_geometry_handoff.review.json',value)
        return value

    def final_current_geometry_goal(self,*,current_observation_provider,owner_lock,reserve_new_goal,goal_builder=None,
                                    encoded_proof_provider=None,encoding_source_pins=None):
        """Dedicated final check inside D's existing lock; reserve once, never send.

        Reservation remains separate from the canceled owner's raw source until
        submission. A changed source after reservation rejects; D owns cleanup.
        """
        if not callable(reserve_new_goal):raise ValueError('D_SERIALIZED_RESERVATION_CALLBACK_REQUIRED')
        if not callable(getattr(owner_lock,'_is_owned',None)) or owner_lock._is_owned() is not True:
            raise ValueError('D_CALLER_MUST_ALREADY_HOLD_REENTRANT_APPLY_LOCK_THROUGH_SEND')
        with owner_lock:
            if self.discarded or self.geometry_handoff_used or self.geometry_handoff_ref is None:
                raise ValueError('PENDING_HANDOFF_NOT_REVIEWED_OR_ALREADY_RESERVED')
            frozen=_pinned_json(self.geometry_handoff_ref)
            current=self.review_pending_geometry(current_observation_provider)
            if current!=frozen:raise ValueError('PENDING_HANDOFF_CHANGED_BEFORE_RESERVATION')
            publication=_pinned_json(frozen['original_pending_ref'])
            curve=_pinned_json(publication['artifacts']['candidate'])['trajectory']
            if digest(curve)!=frozen['original_command_digest']:raise ValueError('PENDING_ORIGINAL_CURVE_CHANGED_BEFORE_RESERVATION')
            if encoded_proof_provider is None and (frozen.get('encoded_current_proof_required') is True or frozen['original_command_digest']!=frozen['command_digest']):
                raise ValueError('ACTUAL_ENCODED_LIVE_PROOF_CALLBACK_REQUIRED_BEFORE_RESERVATION')
            if encoded_proof_provider is not None:
                if not callable(encoded_proof_provider) or not encoding_source_pins:
                    raise ValueError('ACTUAL_ENCODING_PRODUCER_AND_SOURCE_PINS_REQUIRED')
                if any(sha(ref['path'])!=ref['sha256'] for ref in encoding_source_pins.values()):raise ValueError('ENCODING_SOURCE_PIN_CHANGED')
            self.geometry_handoff_used=True  # even a reservation exception must not auto-retry
            reservation=deepcopy(reserve_new_goal(dict(identity=frozen['identity'],old_owner_digest=frozen['owner_digest'],
                command_digest=frozen['command_digest'],next_goal_version=frozen['next_goal_version'],wire_header_stamp_ns=frozen['wire_header_stamp_ns'])))
            if (reservation['scope']!='D_SERIALIZED_NATIVE_RESERVATION_NOT_SEND' or reservation['single_writer']!='D' or
                reservation['native_send_called'] is not False or any(reservation[k]!=frozen[k] for k in
                    ('identity','command_digest','next_goal_version','wire_header_stamp_ns')) or reservation['old_owner_digest']!=frozen['owner_digest']):
                raise ValueError('D_PENDING_RESERVATION_NOT_CURRENT_HANDOFF')
            from uuid import UUID
            new_uuid=UUID(reservation['new_goal_id']).hex
            if new_uuid==frozen['identity']['goal_id'].replace('-',''):raise ValueError('D_NEW_UUID_REQUIRED')
            if goal_builder is None:
                from d_sim_transport import native_goal
                goal_builder=native_goal
            goal=goal_builder(dict(trajectory=deepcopy(curve)))
            goal.trajectory.header.stamp.sec,goal.trajectory.header.stamp.nanosec=divmod(frozen['wire_header_stamp_ns'],10**9)
            from current_geometry_fcl import exact_encoded_command,review_encoding_delivery
            wire,actual_header=typed_goal_snapshot(goal);goal_object=id(goal);goal_data=deepcopy(goal)
            exact_encoded_command(curve,wire)
            if digest(wire)!=frozen['command_digest'] or actual_header!=frozen['wire_header_stamp_ns']:
                raise ValueError('ACTUAL_TYPED_WIRE_OR_HEADER_CHANGED')
            final_selection=self.current_geometry;encoding_review=None
            if encoded_proof_provider is not None:
                reservation_ref=_exclusive_json(self.folder/'pending_geometry.reservation.json',reservation)
                wire_ref=_exclusive_json(self.folder/'pending_geometry.actual_wire.json',wire)
                original_proof=_pinned_json(self.current_geometry['proof_ref'])
                delivery=dict(schema='exact-encoded-command-delivery/0.1',scope=original_proof['snapshot']['scope'],
                    command=wire_ref,raw_owner=original_proof['snapshot']['owner'],wire_header_stamp_ns=actual_header,
                    next_goal_version=frozen['next_goal_version'],source_pins=deepcopy(encoding_source_pins),
                    selected_job=self.job_ref,D_reservation=reservation_ref,new_goal_id=reservation['new_goal_id'])
                delivery_ref=_exclusive_json(self.folder/'pending_geometry.encoding_delivery.json',delivery)
                # Caller invokes existing CU encoded producer; no original full-FCL rerun here.
                final_selection=encoded_proof_provider(wire_ref,delivery_ref,self.current_geometry)
                encoded_files=final_selection['files'];receipt=_pinned_json(encoded_files['command_encoding'])
                if (encoded_files['command']!=wire_ref or receipt['delivery']!=delivery_ref or
                    receipt['original_geometry_proof']!=self.current_geometry['proof_ref'] or
                    receipt['original_files']!=self.current_geometry['files']):raise ValueError('ENCODED_PROOF_NOT_THIS_TYPED_GOAL_AND_ORIGINAL_PROOF')
                encoding_review=review_encoding_delivery(delivery_ref,wire_ref,original_proof['snapshot'])
                for ref in (reservation_ref,wire_ref,delivery_ref):_pinned_json(ref)
            # Recheck real independent source/proof/STOP/clock/Depth after reservation.
            after=review_pending_geometry_handoff(frozen['original_pending_ref'],self.job_ref,self.context['pointer_ref'],
                final_selection,current_observation_provider,transition_source_verification=frozen['original_transition_source_verification'])
            unchanged=lambda value:{k:v for k,v in value.items() if k not in ('review_digest','selection','current_geometry_review')}
            if unchanged(after)!=unchanged(frozen):raise ValueError('PENDING_SOURCE_CHANGED_AFTER_RESERVATION_HOLD')
            last_wire,last_header=typed_goal_snapshot(goal)
            if id(goal)!=goal_object or goal!=goal_data or last_wire!=wire or digest(last_wire)!=frozen['command_digest'] or last_header!=actual_header:
                raise ValueError('SAME_GOAL_OBJECT_OR_DATA_CHANGED_BEFORE_SEND')
            if encoded_proof_provider is not None:
                if _pinned_json(reservation_ref)!=reservation or _pinned_json(wire_ref)!=last_wire or _pinned_json(delivery_ref)!=delivery:
                    raise ValueError('ENCODED_RESERVATION_WIRE_DELIVERY_CHANGED')
            return goal,dict(status='D_PENDING_CURRENT_GEOMETRY_NEW_UUID_RESERVED_SEND_NOT_CALLED',
                handoff_ref=deepcopy(self.geometry_handoff_ref),reservation=reservation,new_goal_id=new_uuid,
                command_digest=frozen['command_digest'],original_pending_ref=frozen['original_pending_ref'],
                original_command_digest=frozen['original_command_digest'],current_geometry_review=after['current_geometry_review'],
                encoded_selection=None if encoding_review is None else {k:v for k,v in final_selection.items() if k!='snapshot_provider'},
                encoded_delivery=None if encoding_review is None else delivery_ref,same_goal_object_and_data_rechecked=True,
                pending_promoted_to_READY=False,native_send_called=False,actual_live_success=False,
                execution_allowed=False,hardware_execution_allowed=False)

    def select_current_geometry(self,selection):
        """D selects the immutable additional proof before READY is consumed."""
        if self.discarded or self.validated_output is not None or self.current_geometry is not None:
            raise ValueError('CURRENT_GEOMETRY_SELECTION_REQUIRES_NEW_JOB')
        if not callable(selection['snapshot_provider']):raise ValueError('INDEPENDENT_GEOMETRY_PROVIDER_REQUIRED')
        self.current_geometry=dict(proof_ref=deepcopy(selection['proof_ref']),files=deepcopy(selection['files']),
                                   snapshot_provider=selection['snapshot_provider'])

    def _bind_context(self):
        if self.job_ref is None:return False
        observed=read_calculated_context(self.context_pointer,self.job['identity'])
        if observed is None:return False
        if self.context is not None and observed['pointer_ref']!=self.context['pointer_ref']:raise ValueError('IMMUTABLE_CALCULATED_CONTEXT_CHANGED')
        if self.context is None:
            if 'input_selection' in self.job and _pinned_json(observed['pointer_ref']).get('selected_job')!=self.job_ref:
                raise ValueError('INPUT_RESELECTION_CONTEXT_NOT_EXACT_SELECTED_JOB')
            self.context=observed
            if observed['inputs']['limits']!=self.job['limits']:raise ValueError('CALCULATED_CONTEXT_JOB_LIMITS_CHANGED')
        return True

    def _publish_tick(self):
        """Call after one real native physics/Depth/owner sample; does not poll/start a worker."""
        observation=deepcopy(self.provider());sequence=observation['packet']['observation_sequence']
        if self.last_sequence is not None and sequence<=self.last_sequence:
            self.discarded=True
            _atomic_pointer(self.owner_pointer,dict(schema='live-cumotion-owner-invalid/0.1',reason='NATIVE_TICK_DUPLICATE_OR_REVERSED'))
            raise ValueError('NATIVE_TICK_DUPLICATE_OR_REVERSED')
        if self.job is not None and {k:observation['owner'][k] for k in LIVE_IDENTITY}!=self.job['identity']:self.discarded=True
        if any(observation['owner'][k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):self.discarded=True
        self._bind_context()
        packet=observation['packet']
        if self.context is None:
            if 'envelope' in packet or 'obstacles' in packet:raise ValueError('OLD_CALCULATED_SCENE_IN_NEW_OWNER_TICK')
        else:
            # Original calculation is fixed; latest state/Depth/control/reference remain untouched.
            packet['envelope']=deepcopy(self.context['envelope'])
            packet['obstacles']=deepcopy(self.context['inputs']['obstacles'])
        try:self.current=publish_native_owner(self.folder/'observations',self.owner_pointer,observation)
        except (ValueError,KeyError) as exc:
            self.discarded=True
            _atomic_pointer(self.owner_pointer,dict(schema='live-cumotion-owner-invalid/0.1',reason=str(exc)))
            raise
        self.last_sequence=sequence;return self.current['packet_ref']

    def request_job(self,job,*,reselection=None):
        if self.discarded:raise ValueError('DISCARDED_OR_STOPPED_NATIVE_OWNER_NO_JOB')
        if self.job_ref is not None and reselection is None:raise ValueError('REPLAN_JOB_ALREADY_PUBLISHED')
        if self.current is None:raise ValueError('NATIVE_STOP_OBSERVATION_NOT_PUBLISHED')
        if reselection is not None:
            if (self.job_ref is None or self.input_selection_sequence<1 or self.context is not None or self.cycle is not None or
                    self.verifier is not None or self.verification is not None or self.validated_output is not None or
                    self.current_geometry is not None or self.geometry_handoff_ref is not None or self.geometry_handoff_used or
                    self.result_pointer.exists() or self.context_pointer.exists()):
                raise ValueError('INPUT_RESELECTION_ACTIVE_OR_UNKNOWN_IPC_HOLD')
            request=_pinned_json(reselection['request_ref'])
            if request.get('previous_selected_job')!=self.job_ref or request.get('sequence')!=self.input_selection_sequence+1:
                raise ValueError('INPUT_RESELECTION_IPC_OLD_SELECTION_CHANGED')
        if reselection is None:
            self.job_ref=publish_online_job(self.folder/'jobs',self.job_pointer,job,self.current['owner'])
        else:
            self.job_ref=publish_online_job(self.folder/'jobs',self.job_pointer,job,self.current['owner'],reselection=reselection)
        self.job=_pinned_json(self.job_ref)
        self.input_selection_sequence=self.job.get('input_selection',{}).get('sequence',1)
        if reselection is not None:
            # New worker output namespace; no old context/result file is reused.
            attempt=self.folder/'input_selections'/self.job_ref['sha256']
            self.context_pointer=attempt/'calculated_context.pointer.json';self.result_pointer=attempt/'result.pointer.json'
        return self.job_ref

    def _current_packet(self):
        from online_cumotion_worker import read_owner_publication
        packet=read_owner_publication(self.owner_pointer,self.job['identity'])
        if packet.get('envelope')!=self.context['envelope'] or packet.get('obstacles')!=self.context['inputs']['obstacles']:raise ValueError('CURRENT_OWNER_NOT_BOUND_TO_CALCULATED_SCENE')
        return packet

    def _result(self):
        value=read_live_worker_delivery(self.result_pointer,self.job['identity'],
            expected_library_sha256=self.job['fcl_library']['sha256'],selected_review_args=self.job['review_args'],
            job_ref=self.job_ref,calculated_context_ref=self.context['pointer_ref'],
            current_geometry=self.current_geometry,current_owner=self.current['owner'])
        if value is not None and self.validated_output is None:
            observed_stamp=value['candidate']['observed']['stamp_s']
            if observed_stamp not in self.observation_refs:raise ValueError('WORKER_TRANSITION_NATIVE_SOURCE_TICK_NOT_RECORDED')
            value['observed_source_verification']=self.observation_refs[observed_stamp]
            publication=json.loads(self.result_pointer.read_text())
            source=_pinned_json(publication['artifacts']['transition_source'])
            if source['owner_evidence']!=value['observed_source_verification']['owner_ref'] or source['source_packet_evidence']!=value['observed_source_verification']['packet_ref']:raise ValueError('TRANSITION_NOT_OWNER_PUBLISHED_NATIVE_SOURCE')
            review=dict(job_ref=self.job_ref,calculated_context_ref=self.context['pointer_ref'],
                verified_new_output_pins=value['suffix_receipt_pins'],result_pointer_ref=_file_ref(self.result_pointer),
                original_suffix_digest=digest(value['suffix']),connection_digest=value['candidate']['trajectory_digest'],
                observed_source_verification=value['observed_source_verification'],
                completed_artifact_refs=list(json.loads(self.result_pointer.read_text())['artifacts'].values()),
                report_artifact_refs=list(json.loads(Path(value['suffix_receipt_path']).read_text())['artifacts'].values()),
                current_geometry_selection=None if self.current_geometry is None else {k:deepcopy(v) for k,v in self.current_geometry.items() if k!='snapshot_provider'},
                actual_sdk_receive_validated=True,native_send_called=False)
            self.validated_output=_exclusive_json(self.folder/'verified_output_pins.json',review)
        elif value is not None:
            frozen=_pinned_json(self.validated_output)
            if frozen['verified_new_output_pins']!=value['suffix_receipt_pins'] or frozen['result_pointer_ref']!=_file_ref(self.result_pointer):raise ValueError('VERIFIED_OUTPUT_PUBLICATION_CHANGED')
            value['observed_source_verification']=frozen['observed_source_verification']
        return value

    def poll(self):
        """Once per tick. Handles preparation/context-before-result ordering without waiting."""
        from dynamic_cumotion_inputs import verify_input_anchor
        if self.discarded:return blocked('DISCARD_ONLINE_JOB_NEW_SEQUENCE_REQUIRED')
        if self.job_ref is None:return blocked('WAIT_NATIVE_STOP_JOB_REQUEST')
        try:
            # Worker may FAIL before publishing context; report that instead of waiting forever.
            if self.result_pointer.is_file():
                result=json.loads(self.result_pointer.read_bytes())
                if 'input_selection' in self.job and result.get('selected_job')!=self.job_ref:
                    raise ValueError('INPUT_RESELECTION_RESULT_NOT_EXACT_SELECTED_JOB')
                if result.get('identity')==self.job['identity'] and result.get('status')=='FAILED':raise ValueError('ONLINE_WORKER_FAILED:'+result.get('reason',''))
            if not self._bind_context():return blocked('WAIT_WORKER_CALCULATED_CONTEXT_NATIVE_TICKS_CONTINUE')
            if self.current['packet'].get('envelope')!=self.context['envelope']:
                return blocked('WAIT_NEXT_NATIVE_TICK_TO_BIND_CALCULATED_CONTEXT')
            if self.cycle is None:
                base=verify_input_anchor(Path(self.job['base_request']['path']),self.job['limits'])
                checker=live_owner_context_checker(base,self.context['envelope'],self.current['owner'],self._current_packet,self.job['limits'])
                self.cycle=LiveObstacleResume(checker,self._result)
                self.cycle.request_plan()
                return blocked('ONLINE_CONTEXT_BOUND_PENDING_NATIVE_ADVANCEMENT')
            if self.verification is None:
                if not self.result_pointer.is_file():return blocked('WAIT_ONLINE_WORKER_RESULT_POINTER')
                publication=json.loads(self.result_pointer.read_bytes())
                if publication.get('identity')!=self.job['identity']:raise ValueError('ONLINE_RESULT_IDENTITY_CHANGED')
                if publication.get('status')=='PENDING':
                    if publication.get('phase')=='PENDING_CURRENT_GEOMETRY_PROOF_REQUIRED':
                        if self.geometry_handoff_used:return blocked('PENDING_GEOMETRY_UUID_RESERVED_NO_AUTORETRY')
                        if self.geometry_handoff_ref is not None:
                            return blocked('PENDING_GEOMETRY_HANDOFF_REVIEWED_AWAIT_D_SERIALIZED_FINAL',handoff_ref=deepcopy(self.geometry_handoff_ref))
                        return blocked('WAIT_CURRENT_GEOMETRY_PROOF_AND_D_FINAL_HANDSHAKE',missing=publication.get('missing',[]))
                    return blocked('WAIT_ONLINE_SDK_NATIVE_TICKS_CONTINUE')
                from concurrent.futures import ThreadPoolExecutor
                self.verifier=ThreadPoolExecutor(max_workers=1,thread_name_prefix='cpu-live-receipt')
                self.verification=self.verifier.submit(self.cycle.poll)
                return blocked('WAIT_CPU_RECEIPT_REVIEW_NATIVE_TICKS_CONTINUE')
            if not self.verification.done():return blocked('WAIT_CPU_RECEIPT_REVIEW_NATIVE_TICKS_CONTINUE')
            review=self.verification.result()  # already done: no wait/join on physics tick
            self.verifier.shutdown(wait=False)
            if self.cycle.phase=='DISCARDED':self.discarded=True
            elif self.cycle.phase=='PLAN_REQUEST':self.verification=None;self.verifier=None
            return review
        except (ValueError,KeyError) as exc:
            self.discarded=True;return blocked('DISCARD_ONLINE_JOB_NEW_SEQUENCE_REQUIRED',reason=str(exc))

    def final_goal(self):
        if self.discarded or self.cycle is None or self.validated_output is None:raise ValueError('ONLINE_JOB_NOT_READY_OR_DISCARDED')
        # Recheck selected job inputs/cache and frozen output pins before the owner reserves/send.
        frozen=_pinned_json(self.validated_output)
        selection=None if self.current_geometry is None else {k:deepcopy(v) for k,v in self.current_geometry.items() if k!='snapshot_provider'}
        if frozen.get('current_geometry_selection')!=selection:raise ValueError('CURRENT_GEOMETRY_SELECTION_CHANGED_BEFORE_SEND')
        if frozen['result_pointer_ref']!=_file_ref(self.result_pointer):raise ValueError('ONLINE_RESULT_CHANGED_BEFORE_SEND')
        _pinned_json(self.job_ref);_pinned_json(self.context['pointer_ref'])
        for ref in frozen['completed_artifact_refs']+frozen['report_artifact_refs']+list(self.job['cache_files'].values())+[self.job[k] for k in ('base_request','fcl_binary','fcl_library','cache_request','cache_model_manifest')]:
            if sha(ref['path'])!=ref['sha256']:raise ValueError('ONLINE_PIN_CHANGED_BEFORE_SEND')
        if self.current_geometry is None:return self.cycle.final_goal()
        publication=json.loads(self.result_pointer.read_text())
        loaded={k:_pinned_json(publication['artifacts'][k]) for k in ('candidate','suffix')}
        review_live_current_geometry(self.current_geometry,publication,loaded,self.job_ref,self.context['pointer_ref'],current_owner=self.current['owner'])
        goal,audit=self.cycle.final_goal()  # original D_APPLY context/STOP/clock/TTL/reservation guards remain
        audit['current_geometry_review']=review_live_current_geometry(self.current_geometry,publication,loaded,self.job_ref,self.context['pointer_ref'],current_owner=self.current['owner'])
        return goal,audit

    def publish_tick(self):
        try:
            ref=self._publish_tick()
            self.observation_refs[self.current['owner']['state_stamp_s']]={k:self.current[k] for k in ('owner_ref','packet_ref')}
            return ref
        except Exception as exc:
            # Fail closed for both the native consumer and concurrently reading
            # worker; never leave an old apparently safe pointer after a bad tick.
            self.discarded=True
            _atomic_pointer(self.owner_pointer,dict(schema='live-cumotion-owner-invalid/0.1',reason=str(exc)))
            raise


def describe_observation_limits(limits,*,applies_to,sources=None):
    """Provenance only: SDK1.1.0 publishes no universal measured start/rest tolerance.

    Selected execution/test criteria still review raw observations. Their
    values are not replaced with IK tolerances or invented SDK defaults.
    """
    units=dict(max_state_age_s='s',min_stop_observation_s='s',max_stop_velocity_rad_s='rad/s',
        max_stop_acceleration_rad_s2='rad/s^2',q_tolerance_rad='rad',v_tolerance_rad_s='rad/s',a_tolerance_rad_s2='rad/s^2',
        max_reference_skew_s='s',grip_tolerance_rad='rad',attachment_translation_tolerance_m='m',
        attachment_rotation_tolerance_rad='rad',world_translation_tolerance_m='m',world_rotation_tolerance_rad='rad',
        max_start_drift_rad='rad',max_obstacle_age_s='s',max_pose_skew_s='s')
    rows=[]
    for key,value in limits.items():
        if key not in units:continue
        source=deepcopy((sources or {}).get(key,{}))
        if (key in OBSERVATION_UNITS or key in STOP_OBSERVATION_KEYS) and (value is None or isinstance(value,dict)):
            criterion=_stop_observation_difference(limits,key,0.,applies_to='CRITERION_REPRESENTATION_ONLY') if key in STOP_OBSERVATION_KEYS else _observation_criterion(limits,key)
            source.update(criterion);value=criterion['value']
        category=source.get('source_category','PROJECT_TEST_PARAMETER')
        if category=='SDK_OFFICIAL_OBSERVATION':raise ValueError('SDK_1_1_0_OFFICIAL_OBSERVATION_NOT_DEFINED_FOR:'+key)
        rows.append(dict(name=key,value=None if value is None else finite(value),unit=units[key],applies_to=applies_to,check_mode=source.get('check_mode','ENFORCE'),
            source_category=category,reference=source.get('reference','owner-selected existing review limit; not SDK official'),
            runtime_version=source.get('runtime_version','standalone cuMotion1.1.0 / selected native owner'),
            sdk_official_observation_value=None,sdk_official_status='OFFICIAL_NOT_DEFINED'))
    return rows


OBSERVATION_UNITS={'q_tolerance_rad':'rad','v_tolerance_rad_s':'rad/s','a_tolerance_rad_s2':'rad/s^2','max_reference_skew_s':'s'}


def _observation_criterion(limits,name):
    from live_cumotion_boundary import review_observation_difference
    if name not in limits:raise ValueError('OBSERVATION_CRITERION_MISSING:'+name)
    return review_observation_difference(limits,name,0.,applies_to='CRITERION_REPRESENTATION_ONLY')


def review_tracking_observations(desired,observed,limits,*,source_now_s=None):
    """Thin CU canonical criterion/clock adapter; no invented opt-out or curve math."""
    from live_cumotion_boundary import review_observation_difference,verify_reference_time_association
    from plan_only import vector
    for key in ('session_id','clock_basis'):
        if not desired.get(key) or desired[key]!=observed.get(key):raise ValueError('OBSERVATION_SESSION_CLOCK_ASSOCIATION_REQUIRED')
    desired_stamp=finite(desired['stamp_s']);observed_stamp=finite(observed['stamp_s'])
    now=max(desired_stamp,observed_stamp) if source_now_s is None else finite(source_now_s)
    if now<desired_stamp or now<observed_stamp:raise ValueError('OBSERVATION_SOURCE_TIME_REVERSED_OR_FUTURE')
    rows=[]
    skew=abs((now if source_now_s is not None else observed_stamp)-desired_stamp)
    if 'max_reference_skew_s' not in limits:raise ValueError('OBSERVATION_CRITERION_MISSING:max_reference_skew_s')
    rows.append(review_observation_difference(limits,'max_reference_skew_s',skew,applies_to='CURRENT_REFERENCE_SOURCE_AGE',error_code='OBSERVED_REFERENCE_TIME_SKEW'))
    association=None
    if rows[0]['check_mode']=='REPORT_ONLY':
        # Canonical proof is desired.source_time_association; packet/flag shortcuts are not accepted.
        association=verify_reference_time_association(desired,observed,now_s=now)
    for field,name in (('q_rad','q_tolerance_rad'),('v_rad_s','v_tolerance_rad_s'),('a_rad_s2','a_tolerance_rad_s2')):
        if name not in limits:raise ValueError('OBSERVATION_CRITERION_MISSING:'+name)
        error=max(abs(a-b) for a,b in zip(vector(desired[field],6),vector(observed[field],6)))
        rows.append(review_observation_difference(limits,name,error,applies_to='APPLY_DESIRED_VS_RAW_OBSERVED_'+field,error_code='OBSERVED_REFERENCE_ERROR'))
    return dict(observation_criteria=rows,source_time_association=association,source_now_s=now,physical_observation_verified=False,execution_allowed=False)


def native_transition_candidate(suffix,desired,observed,*,duration_s,limits,lower,upper):
    """Exact producer function and candidate/digest; no separate connection implementation."""
    from live_cumotion_boundary import transition_candidate
    return transition_candidate(suffix,desired,observed,duration_s=duration_s,limits=limits,lower=lower,upper=upper)


def review_native_transition(candidate,receipt,request,context_check,*,expected_library_sha256):
    from live_cumotion_boundary import review_transition
    return review_transition(candidate,receipt,request,context_check,expected_library_sha256=expected_library_sha256)


def review_fixed_actual_geometry(receipt,request,curve,owner,*,expected_library_sha256):
    """Consume MoveIt's audit_current_geometry receipt, exactly bound to current wire/owner.

    Nominal pose tolerances are replaced only by this full actual-geometry
    proof, not by increased tolerances or modifications to the SDK receipt.
    """
    proof=_pinned_json(receipt) if 'scope' not in receipt else deepcopy(receipt)
    if proof['scope']!='CURRENT_FIXED_OWNER_ACTUAL_GEOMETRY_WHOLE_CURVE_FCL_NOT_NATIVE_APPROVAL':raise ValueError('EXPLICIT_FIXED_ACTUAL_GEOMETRY_RECEIPT_REQUIRED')
    if any(proof.get(k) is not False for k in ('native_send_called','hardware_execution_allowed','live_resume_approved')):raise ValueError('ACTUAL_GEOMETRY_RECEIPT_NOT_CALCULATION_ONLY')
    wire=native_wire_expected(curve)
    if proof['trajectory_digest']!=digest(wire) or proof['original_request_digest']!=request['planning_request_digest'] or proof['model_digest']!=request['model_digest']:raise ValueError('ACTUAL_GEOMETRY_NOT_THIS_WIRE_REQUEST_OR_MODEL')
    library=proof['library']
    if expected_library_sha256 is None or library['sha256']!=expected_library_sha256 or sha(library['path'])!=expected_library_sha256:raise ValueError('ACTUAL_GEOMETRY_LIBRARY_NOT_OWNER_SELECTED')
    before=_pinned_json(proof['owner_before']);after=_pinned_json(proof['owner_after'])
    if before!=after or before!=owner or proof['owner_digest']!=digest(owner):raise ValueError('ACTUAL_GEOMETRY_OWNER_CHANGED')
    actual=_pinned_json(proof['measured_request']);audit=_pinned_json(proof['FCL_result'])
    if audit!=proof['FCL'] or audit['success'] is not True or type(audit['checks']) is not int or audit['checks']<=0:raise ValueError('ACTUAL_GEOMETRY_FULL_CURVE_FCL_FAILED')
    if _pinned_json(proof['wire_trajectory'])!=wire:raise ValueError('ACTUAL_GEOMETRY_AUDITED_WIRE_CHANGED')
    terminal=_pinned_json(proof['terminal_block_goal_review'])
    expected=deepcopy(request);expected['attachment']=deepcopy(owner['attachment_tcp_to_block'])
    expected['planning_snapshot']['grip_rad']=owner['grip_rad']
    world={o['id']:o for o in owner['world_objects']}
    objects=[deepcopy(world.get(o['id'],o)) for o in request['planning_snapshot']['world_objects']]
    ids={o['id'] for o in objects};objects.extend(deepcopy(o) for o in owner['world_objects'] if o['id'] not in ids)
    expected['planning_snapshot']['world_objects']=objects
    if actual!=expected:raise ValueError('ACTUAL_GEOMETRY_MODEL_SHAPE_WORLD_OR_ATTACHMENT_CHANGED')
    import xml.etree.ElementTree as ET
    robot=ET.fromstring(request['model_bundle']['robot_description'])
    for name,q in zip(JOINTS,owner['q_rad']):
        bound=robot.find(f"joint[@name='{name}']/limit")
        if not float(bound.get('lower'))<=q<=float(bound.get('upper')):raise ValueError('ACTUAL_GEOMETRY_RAW_Q_OUTSIDE_MODEL_LIMITS')
    from stop_fcl import StopScene
    scene=StopScene(expected,Path(library['path']),expected_library_sha256)
    try:hit=scene.check(owner['q_rad'])
    finally:scene.close()
    if hit:raise ValueError('ACTUAL_GEOMETRY_RAW_START_FCL_FAILED:'+str(hit))
    # Recheck referenced files after reading/current-start review. Caller also
    # rechecks current owner at final send; this function never submits.
    for key in ('owner_before','owner_after','measured_request','wire_trajectory','FCL_result','terminal_block_goal_review'):
        ref=proof[key]
        if sha(ref['path'])!=ref['sha256']:raise ValueError('ACTUAL_GEOMETRY_EVIDENCE_CHANGED_DURING_REVIEW')
    if sha(library['path'])!=expected_library_sha256 or 'scope' not in receipt and sha(receipt['path'])!=receipt['sha256']:raise ValueError('ACTUAL_GEOMETRY_LIBRARY_OR_RECEIPT_CHANGED_DURING_REVIEW')
    return dict(receipt=deepcopy(receipt),wire_digest=digest(wire),owner_digest=proof['owner_digest'],full_curve_checks=audit['checks'],actual_raw_start_checked=True,
        terminal_block_goal_review=terminal,original_sdk_receipt_unchanged=True,execution_allowed=False,native_send_called=False)


STOP_OBSERVATION_KEYS={'max_stop_velocity_rad_s':'v_tolerance_rad_s','max_stop_acceleration_rad_s2':'a_tolerance_rad_s2',
    'q_tolerance_rad':'q_tolerance_rad','v_tolerance_rad_s':'v_tolerance_rad_s','a_tolerance_rad_s2':'a_tolerance_rad_s2'}


def _stop_observation_difference(limits,name,error,*,applies_to):
    """Only name/unit mapping; the CU canonical checker owns numeric/report-only semantics."""
    from live_cumotion_boundary import review_observation_difference
    if name not in limits:raise ValueError('STOP_OBSERVATION_CRITERION_MISSING:'+name)
    canonical=STOP_OBSERVATION_KEYS[name]
    mapped={canonical:limits[name],'criteria_sources':{canonical:limits.get('criteria_sources',{}).get(name,{})}}
    row=review_observation_difference(mapped,canonical,error,applies_to=applies_to,error_code='STOP_OBSERVATION_COMPARISON_FAILED')
    row['name']=name;return row


def _review_owner_stop_verification(owner,record,*,expected_scope='VERIFIED_D_OBSTACLE_STOP_AND_HOLDING_NOT_RESUME_APPROVAL'):
    """REPORT_ONLY requires independent current owner stop/holding verdict plus real lifecycle refs.

    This is receipt binding, not a new physical stop algorithm. D produces its
    verified outcome using controller/observations; missing/unknown never passes.
    """
    from live_cumotion_boundary import verify_reference_time_association
    if 'stop_verification' not in owner:raise ValueError('VERIFIED_D_STOP_EVIDENCE_REQUIRED_FOR_REPORT_ONLY')
    ref=owner['stop_verification'];proof=_pinned_json(ref)
    if proof['scope']!=expected_scope:raise ValueError('VERIFIED_D_STOP_SCOPE_REQUIRED')
    if proof['identity']!={k:owner[k] for k in LIVE_IDENTITY} or any(type(proof['identity'][k]) is not type(owner[k]) for k in LIVE_IDENTITY):raise ValueError('VERIFIED_D_STOP_IDENTITY_CHANGED')
    if proof['stop_record_digest']!=record['record_digest'] or proof['samples_digest']!=digest(record['samples']) or proof['state_stamp_s']!=owner['state_stamp_s']:raise ValueError('VERIFIED_D_STOP_NOT_ORIGINAL_RECORD')
    if proof.get('stop_verified') is not True or proof.get('holding_confirmed') is not True or not proof.get('verification_method'):raise ValueError('UNKNOWN_D_STOP_OR_HOLDING')
    evidence=proof['evidence'];ack=_pinned_json(evidence['cancel_ack']);terminal=_pinned_json(evidence['terminal_result']);counts=_pinned_json(evidence['command_counts'])
    held=_pinned_json(evidence['holding']);controller=_pinned_json(evidence['controller_stop'])
    if ack.get('done') is not True or ack.get('return_code')!=0 or owner['goal_id'] not in ack.get('goals_canceling_ids',[]):raise ValueError('VERIFIED_D_STOP_ACK_UUID_UNCONFIRMED')
    if terminal.get('status')!=5 or terminal.get('error_code')!=0 or terminal.get('goal_id')!=owner['goal_id']:raise ValueError('VERIFIED_D_STOP_TERMINAL_UNCONFIRMED')
    if counts.get('coverage')!='D_OWNER_AND_ARM_GRIPPER_ACTION_STATUS' or any(type(counts.get(k)) is not int or counts[k]!=0 for k in ('active_command_count','pending_command_count','pending_cancel_count')):raise ValueError('VERIFIED_D_STOP_COUNTS_UNKNOWN')
    if held.get('holding_confirmed') is not True or held.get('contact_fingers')!=owner.get('contact_fingers') or not held.get('contact_fingers') or held.get('attachment_tcp_to_block')!=owner.get('attachment_tcp_to_block') or held.get('grip_rad')!=owner.get('grip_rad'):raise ValueError('VERIFIED_D_STOP_HOLDING_CHANGED')
    if controller.get('stop_verified') is not True or controller.get('goal_id')!=owner['goal_id'] or not controller.get('verification_method'):raise ValueError('D_CONTROLLER_STOP_NOT_VERIFIED')
    if expected_scope=='VERIFIED_D_CONSERVATIVE_FOREGROUND_STOP_AND_HOLDING_NOT_RESUME_APPROVAL':
        if (controller.get('state_stamp_s')!=owner['state_stamp_s'] or
                controller.get('samples_digest')!=digest(record['samples'])):
            raise ValueError('CURRENT_CONSERVATIVE_STOP_WINDOW_REQUIRED')
        original=_pinned_json(controller['source_status_ref'])
        if (original.get('error')!='FRESH_FOREGROUND_CONSERVATIVE_STOP' or
                original.get('conservative_stop_verified') is not True or
                original.get('cancel_bound_uuid')!=owner['goal_id'] or
                original.get('cancel_request_count')!=1 or
                original.get('cancel_send_outcome_unknown') is not False or
                original.get('stop_verified') is not True or original.get('holding_confirmed') is not True or
                original.get('native_command_counts')!={'active_command_count':0,'pending_command_count':0}):
            raise ValueError('ORIGINAL_SAME_UUID_CONSERVATIVE_STOP_STATUS_REQUIRED')
        if (ack.get('goals_canceling_ids')!=[owner['goal_id']] or
                original.get('cancellation')!=[ack] or
                original.get('native_action_result',{}).get('status')!=5 or
                original['native_action_result'].get('error_code')!=0):
            raise ValueError('CONSERVATIVE_CANCEL_LIFECYCLE_CHANGED')
        if sha(controller['source_status_ref']['path'])!=controller['source_status_ref']['sha256']:
            raise ValueError('CONSERVATIVE_STATUS_CHANGED_DURING_REVIEW')
    observed=dict(stamp_s=owner['state_stamp_s'],**{k:owner[k] for k in ('session_id','clock_basis','clock_epoch','q_rad','v_rad_s','a_rad_s2')})
    association=verify_reference_time_association(owner['desired'],observed,now_s=owner['now_s'])
    for value in evidence.values():
        if sha(value['path'])!=value['sha256']:raise ValueError('D_STOP_VERIFICATION_EVIDENCE_CHANGED')
    if sha(ref['path'])!=ref['sha256']:raise ValueError('D_STOP_VERIFICATION_CHANGED_DURING_REVIEW')
    return dict(receipt=ref,source_time_association=association,stop_verdict_source='D_OWNER_VERIFIED_RESULT_NOT_NULL_COMPARISON',execution_allowed=False)
