"""CPU consumption of producer files. Pending input is never a dispatch intent."""
from copy import deepcopy
import json
from pathlib import Path

import yaml
from .engine_receipt import receive_engine,CUMOTION,sha
from .preflight import digest,BINDING
from dynamic_cumotion_inputs import verify_seal,check_result_context
from prepare_cumotion_model import verify_request


def consume_hold_evidence(path, *, expected_sha256, authority_ref):
    """Diagnostic producer bundle with absent planner fields; no guessed mapping."""
    if not authority_ref or sha(path)!=expected_sha256:raise ValueError('Independent bundle source pin required')
    value=json.loads(Path(path).read_text())
    if value['schema']!='cumotion-input-preparation-bundle/0.1' or value['status']!='HOLD_INPUT_EVIDENCE_INCOMPLETE':
        raise ValueError('Incomplete evidence bundle required; use prepared API for planner input')
    for key in ('input_ready','dispatch_allowed','execution_allowed','hardware_execution_allowed','world_clear_allowed'):
        if value[key] is not False:raise ValueError('Diagnostic evidence cannot acquire readiness')
    if 'actual_sim_bound_accepted' in value and value['actual_sim_bound_accepted'] is not False:raise ValueError('Diagnostic evidence cannot acquire admission')
    held=value.get('substatus')=='NATIVE_HELD_GEOMETRY_ATTACHMENT_FULL_SEMANTIC_AND_CURRENT0_A_GEOMETRY_PASSED'
    bounded=value.get('implementation_status')=='BOUNDED_SIM_ADMISSION_IMPLEMENTED_CPU_CONTRACT_VERIFIED'
    for key in ('request','planner_input_envelope','state_digest','obstacle_snapshot_digest','obstacle_version',
                'planning_generation','replan_sequence','cancel_generation','assumptions','valid_until_s','result','fcl_result'):
        if value[key] is not None:raise ValueError('Do not fabricate planner fields in hold evidence')
    verified=[]
    def pins(obj):
        if isinstance(obj,dict):
            if 'path' in obj and 'sha256' in obj:
                if sha(obj['path'])!=obj['sha256']:raise ValueError('Producer evidence artifact changed: '+obj['path'])
                verified.append(deepcopy(obj))
            for part in obj.values():pins(part)
        elif isinstance(obj,list):
            for part in obj:pins(part)
    pins(value)
    if held:
        for key in ('raw_state','raw_frame','held_geometry_definition','held_snapshot_binding','native_validation'):
            if key not in value:raise ValueError('Published held source refs required')
    for capture in ([] if held else value['captures']):
        if capture['source_kind']!='SIM_DEPTH' or capture['status']!='HOLD':raise ValueError('Capture must retain actual SIM Depth/HOLD')
        if bounded:
            for key in ('raw_frame','raw_state_samples','raw_candidates'):
                if key not in capture:raise ValueError('Published capture refs required')
        else:
            view=json.loads(Path(capture['diagnostic_view']['path']).read_text());pins(view)
            if view['status']!='HOLD_NOT_PLANNER_INPUT':raise ValueError('Capture diagnostics must retain HOLD')
    if sha(path)!=expected_sha256 or any(sha(v['path'])!=v['sha256'] for v in verified):raise ValueError('Bundle or evidence changed while reading')
    return dict(status='HOLD_INPUT_EVIDENCE_INCOMPLETE',scope='REAL_FILES_SENSOR_DIAGNOSTICS_NOT_PLANNER_RECEIPT',
        authority_ref=authority_ref,source_sha256=expected_sha256,original_bundle=deepcopy(value),verified_artifacts=verified,
        audit_context=None,planner_context=None,dispatch_intent=None,input_context_verified=False,
        execution_allowed=False,hardware_execution_allowed=False,world_accuracy_verified=False,dynamic_safety_verified=False,
        missing_evidence=([key for key,status in value['checks'].items() if status=='HOLD' or status.endswith('PENDING')] if held else deepcopy(value['remaining_gaps'] if bounded else value['missing_evidence'])))


def read_bundle(folder):
    folder=Path(folder)
    names=('TRANSPORT.request.yaml','dynamic_inputs.json','dynamic_input.envelope.json')
    pins={n:sha(folder/n) for n in names}
    request=verify_request(folder/'TRANSPORT.request.yaml',allow_fixture_cpu=True)
    inputs=json.loads((folder/'dynamic_inputs.json').read_text())
    envelope=json.loads((folder/'dynamic_input.envelope.json').read_text())
    verify_seal(envelope,'envelope_digest')
    if envelope['request_sha256']!=pins[names[0]] or envelope['inputs_sha256']!=pins[names[1]]:
        raise ValueError('BUNDLE_FILE_INTEGRITY_MISMATCH')
    if envelope['binding']!={k:request[k] for k in BINDING}:raise ValueError('BUNDLE_REQUEST_BINDING_MISMATCH')
    return request,inputs,envelope,pins


def context_mapping(inputs,envelope):
    state=inputs['state'];obstacles=inputs['obstacles'];control=inputs['control'];planner=envelope['planner_context']
    if (envelope['audit_context']['obstacle_snapshot_digest']!=obstacles['digest'] or
        planner['state_digest']!=state['digest'] or planner['state_sequence']!=state['state_sequence'] or
        planner['obstacle_session_id']!=obstacles['obstacle_session_id'] or planner['obstacle_version']!=obstacles['version'] or
        planner['cancel_generation']!=control['cancel_generation']):raise ValueError('PLANNER_CONTEXT_MAPPING_MISMATCH')
    return dict(audit_context=deepcopy(envelope['audit_context']),planner_context=deepcopy(planner),
        original_state_packet=deepcopy(state),original_obstacle_packet=deepcopy(obstacles),
        state_source_kind=state['source_kind'],state_source_stamp_s=state['source_stamp_s'],
        obstacle_source_kind=obstacles['source_kind'],obstacle_stamp_s=obstacles['source_stamp_s'],
        obstacle_frame=obstacles['base_frame_id'],coverage=obstacles['coverage'],mask_status=obstacles['mask_status'],
        camera=deepcopy(obstacles['camera']),source_provenance=deepcopy(envelope.get('source_provenance')),
        bound_assumptions=deepcopy(obstacles.get('depth_bound',{}).get('assumptions')),
        perception_valid_until_s=envelope.get('perception_valid_until_s'),control_mode=control['mode'],
        control_mode_not_promoted_to_resume=True,model_preparation=deepcopy(envelope['model_preparation']))


def check_authority(envelope,inputs,authority,planned_epoch):
    if not authority['authority_ref'] or authority['authority_kind'] not in ('RECORDED_PRODUCER_REVIEW','FIXTURE','ACTIVE_CALLER_CONTEXT'):
        raise ValueError('Separate caller-selected authoritative context required')
    if type(planned_epoch) is not int or planned_epoch<0 or type(authority['clock_epoch']) is not int or authority['clock_epoch']!=planned_epoch:
        raise ValueError('CLOCK_EPOCH_CHANGED')
    if authority['outcome_unknown'] is not False:raise ValueError('UNKNOWN_OUTCOME_HOLD')
    check_result_context(envelope,authority['envelope'],authority['control'],
                         now_s=authority['now_s'],limits=authority['limits'])
    for key in ('state','obstacles'):
        verify_seal(authority[key])
        if authority[key]['digest']!=inputs[key]['digest']:raise ValueError('CURRENT_'+key.upper()+'_CHANGED')
    if digest(authority['limits'])!=envelope['thresholds_digest']:raise ValueError('Caller thresholds differ')


def archival_result(path,pins):
    """Original loader checks an archive against ITS original request, never current authority."""
    report=json.loads(Path(path).read_text())
    old_request=yaml.safe_load(Path(report['artifacts']['request']['path']).read_text())
    motion=json.loads((Path(report['artifacts']['request']['path']).parent/'motion.request.json').read_text())
    return receive_engine(CUMOTION,path,dict(artifact_pins=pins,motion_request=motion,
                                          binding={k:old_request[k] for k in BINDING}))


class PlannerBundleConsumer:
    def __init__(self):self.seen=set();self.previous=None;self.previous_envelope=None
    def consume(self,folder,latest,*,planned_epoch,result_path=None,result_pins=None):
        before=deepcopy(latest())
        request,inputs,envelope,pins=read_bundle(folder)
        mapping=context_mapping(inputs,envelope);check_authority(envelope,inputs,before,planned_epoch)
        after=deepcopy(latest());check_authority(envelope,inputs,after,planned_epoch)
        if digest({k:v for k,v in before.items() if k!='now_s'})!=digest({k:v for k,v in after.items() if k!='now_s'}):
            raise ValueError('AUTHORITY_CHANGED_DURING_CONSUMPTION')
        key=envelope['envelope_digest']
        receipt_key=(key,'INPUT' if result_path is None else 'RESULT')
        if receipt_key in self.seen:raise ValueError('DUPLICATE_BUNDLE')
        cursor=envelope['cursor'];previous=self.previous
        if previous is not None and key!=self.previous_envelope:
            if any(cursor[k]!=previous[k] for k in ('session_id','clock_basis','obstacle_session_id','base_request_digest')):
                raise ValueError('SESSION_RESET_REQUIRES_NEW_REVIEW')
            if any(cursor[k]<=previous[k] for k in ('replan_sequence','state_sequence','state_stamp_s','obstacle_version','obstacle_stamp_s','frame_seq')) or cursor['cancel_generation']<previous['cancel_generation']:
                raise ValueError('OLD_OR_REORDERED_BUNDLE')
            if not set(previous['obstacle_ids'])<=set(cursor['obstacle_ids']):
                raise ValueError('REMOVAL_WITHOUT_FREE_SPACE_EVIDENCE')
        packet=None
        if result_path is not None:
            if result_pins is None:raise ValueError('Independent archived-result pins required')
            packet=archival_result(result_path,result_pins)
            if packet['binding']!=envelope['binding'] or packet['model_digest']!=request['model_digest']:
                raise ValueError('OLD_STATIC_RESULT_NOT_NEW_WORLD_REQUEST')
            if packet['trajectory_digest']!=digest(packet['trajectory']):raise ValueError('Result trajectory changed')
        _,verified_inputs,verified_envelope,verified_pins=read_bundle(folder)
        if verified_pins!=pins or verified_envelope!=envelope or verified_inputs!=inputs:
            raise ValueError('Bundle changed before receipt')
        final=deepcopy(latest());check_authority(envelope,inputs,final,planned_epoch)
        if digest({k:v for k,v in after.items() if k!='now_s'})!=digest({k:v for k,v in final.items() if k!='now_s'}):
            raise ValueError('AUTHORITY_CHANGED_BEFORE_RECEIPT')
        if any(sha(Path(folder)/n)!=s for n,s in pins.items()):raise ValueError('Bundle changed during receipt')
        self.seen.add(receipt_key);self.previous=deepcopy(cursor);self.previous_envelope=key
        return dict(status='INPUT_CONTEXT_OK_RESULT_PENDING' if packet is None else 'RESULT_CONTEXT_CHECKED_NATIVE_DISPATCH_BLOCKED',
            scope='CPU_PRODUCER_BUNDLE_RECEIPT_NOT_GPU_OR_NATIVE_READY',folder=str(Path(folder).resolve()),source_files_sha256=pins,
            original_mapping=mapping,binding=deepcopy(envelope['binding']),envelope_digest=key,
            authority_ref=final['authority_ref'],authority_kind=final['authority_kind'],planned_clock_epoch=planned_epoch,
            evaluation_source_time_s=final['now_s'],sensor_age_s=final['now_s']-inputs['obstacles']['source_stamp_s'],
            pose_age_s=final['now_s']-inputs['state']['source_stamp_s'],actual_result_present=packet is not None,
            dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False,execution_issued=False,
            world_accuracy_verified=False,dynamic_safety_verified=False,
            model_preparation_status=envelope['model_preparation']['status'],
            native_dispatch_blockers=['Bounded source SDK admission and fresh generated model/SDK/final FCL',
                                      'D-owned atomic current/cancel/state/writer check and commissioning'])
