"""Offline engine receipt -> record-only intent. No native goal/controller dispatch."""
from copy import deepcopy
import json
from pathlib import Path

import yaml
if __package__:
    from .preflight import preflight, numeric, digest, BINDING
else:
    from preflight import preflight, numeric, digest, BINDING
from plan_only import prepare_d_candidate
from robot_control_integration.app import cumotion_transport

CPU='MOVEIT_LOCAL_PLANNING_RESULT'
CUMOTION=cumotion_transport.ENGINE
IDENTITY=('session_id','clock_basis','clock_epoch','replan_sequence','cancel_generation',
          'state_sequence','state_stamp_s','obstacle_version','obstacle_stamp_s','obstacle_digest')


class RecordOnlySink:
    def __init__(self):self.records=[]
    def record_intent(self, value):self.records.append(deepcopy(value))


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_context(planned, current, limits):
    if current['user_stop_latched'] is not False or current['failure_latched'] is not False or current['outcome_unknown'] is not False:
        raise ValueError('STOP_FAILURE_OR_UNKNOWN_OUTCOME_HOLD')
    if current['mode'] not in ('NORMAL_READY','OBSTACLE_REPLAN_READY'):
        raise ValueError('Normal obstacle wait is not ready; no automatic STOP resume')
    if current['single_writer']=='D' and current['stopped_verified'] is True:pass
    else:raise ValueError('Explicit D writer and stopped snapshot required')
    for key in IDENTITY:
        if type(planned[key]) is not type(current[key]) or planned[key]!=current[key]:
            raise ValueError('STALE_PLAN_CONTEXT:'+key)
    for key in ('clock_epoch','replan_sequence','cancel_generation','state_sequence','obstacle_version'):
        if type(current[key]) is not int or current[key]<0:raise ValueError('Invalid sequence '+key)
    if limits['scope']!='SIM_FIXTURE_TEST_LIMITS':raise ValueError('Explicit SIM/fixture limits only')
    if current['source_kind'] not in ('FIXTURE','SIM_SAVED_SNAPSHOT') or current['obstacle_source_kind']!='FIXTURE':
        raise ValueError('Dynamic Depth producer integration not accepted by this fixture adapter')
    if current['obstacle_status'] not in ('VISIBLE_PARTIAL','FIXTURE_VALID') or current['world_clear_allowed'] is not False:
        raise ValueError('Unobservable/stale is not empty world')
    now=numeric(current['now_s'])
    for stamp,age in (('state_stamp_s','max_pose_age_s'),('obstacle_stamp_s','max_sensor_age_s')):
        delta=now-numeric(current[stamp]); maximum=numeric(limits[age])
        if maximum<=0 or not 0<=delta<=maximum:raise ValueError('STALE_OR_RESET_'+stamp)
    skew=numeric(limits['max_pose_sensor_skew_s'])
    if skew<=0 or abs(current['state_stamp_s']-current['obstacle_stamp_s'])>skew:raise ValueError('POSE_SENSOR_SKEW')
    if current['visibility_complete'] is not False:raise ValueError('No full visibility proof in fixture adapter')


def receive_engine(engine, path, current):
    if engine not in (CPU,CUMOTION):raise ValueError('Explicit supported engine required; no fallback')
    pins=current['artifact_pins'];receipt=json.loads(Path(path).read_text())
    if sha(path)!=pins['receipt']:raise ValueError('Receipt hash changed')
    if receipt['engine']!=engine or receipt['execution_allowed'] is not False or receipt['hardware_execution_allowed'] is not False:
        raise ValueError('Engine/permission mismatch')
    if receipt['fcl_binary_sha256']!=pins['fcl_binary']:raise ValueError('FCL binary pin mismatch')
    required={'request','fcl_result','model_manifest'} | ({'external'} if engine==CUMOTION else set())
    if set(receipt['artifacts'])!=required or set(pins)!=required|{'receipt','fcl_binary'}:
        raise ValueError('Explicit complete artifact pins required')
    for key in required:
        artifact=receipt['artifacts'][key]
        if artifact['sha256']!=pins[key] or sha(artifact['path'])!=pins[key]:raise ValueError('Artifact changed '+key)
    if engine==CUMOTION:
        return cumotion_transport.receive_calculation(path,current['motion_request'],current['binding'],
            engine=engine,expected_fcl_sha256=pins['fcl_binary'])
    request=yaml.safe_load(Path(receipt['artifacts']['request']['path']).read_text())
    result=yaml.safe_load(Path(receipt['artifacts']['fcl_result']['path']).read_text())
    if result['result_provenance']!=CPU:raise ValueError('CPU provenance required')
    if digest(current['motion_request'])!=request['motion_input_digest']:raise ValueError('Current request changed')
    if receipt['artifacts']['model_manifest']['sha256']!=sha(Path(request['model_bundle']['bundle_path'])/'MODEL_MANIFEST.json'):
        raise ValueError('Model manifest changed')
    return prepare_d_candidate(result,request,current['binding'])


class EngineReceiptAdapter:
    def __init__(self):self.consumed=set();self.intent_keys=set()
    def prepare(self, engine, path, result_id, planned_context, latest, limits, sink):
        if type(sink) is not RecordOnlySink:raise ValueError('Record-only sink required, no action receiver')
        if not isinstance(result_id,str) or not result_id:raise ValueError('Explicit result identity required')
        if result_id in self.consumed:raise ValueError('DUPLICATE_RESULT')
        first=deepcopy(latest());check_context(planned_context,first,limits)
        packet=receive_engine(engine,path,first)
        current=deepcopy(latest());check_context(planned_context,current,limits)
        for key in ('binding','motion_request','artifact_pins','q_rad','v_rad_s','a_rad_s2'):
            if digest(first[key])!=digest(current[key]):raise ValueError('Context changed during receipt: '+key)
        for key in ('q_rad','v_rad_s','a_rad_s2'):
            if len(current[key])!=6:raise ValueError('Stamped q/v/a required')
            for value in current[key]:numeric(value)
        audit_context={k:current[k] for k in ('session_id','replan_sequence','clock_basis')}
        audit_context['obstacle_snapshot_digest']=current['obstacle_digest']
        start=dict(session_id=current['session_id'],clock_basis=current['clock_basis'],source_kind=current['source_kind'],
                   age_s=current['now_s']-current['state_stamp_s'],q_rad=current['q_rad'])
        audit=preflight(packet,current['binding'],audit_context,audit_context,start,
                        start_tolerance_rad=limits['start_tolerance_rad'],max_snapshot_age_s=limits['max_pose_age_s'])
        for key,field,limit in (('v_rad_s','velocities_rad_s','start_velocity_tolerance_rad_s'),
                               ('a_rad_s2','accelerations_rad_s2','start_acceleration_tolerance_rad_s2')):
            tolerance=numeric(limits[limit])
            if tolerance<=0 or max(abs(a-b) for a,b in zip(current[key],packet['trajectory']['points'][0][field]))>tolerance:
                raise ValueError('PVT start mismatch '+key)
        final=deepcopy(latest());check_context(planned_context,final,limits)
        if digest({k:v for k,v in current.items() if k!='now_s'})!=digest({k:v for k,v in final.items() if k!='now_s'}):
            raise ValueError('Context changed before intent')
        if digest(receive_engine(engine,path,final))!=digest(packet):
            raise ValueError('Receipt changed before intent')
        boundary=deepcopy(latest());check_context(planned_context,boundary,limits)
        if digest({k:v for k,v in final.items() if k!='now_s'})!=digest({k:v for k,v in boundary.items() if k!='now_s'}):
            raise ValueError('Context changed after final receipt')
        final=boundary
        intent_key=digest(dict(engine=engine,trajectory_digest=packet['trajectory_digest'],
                               binding=current['binding'],context=planned_context))
        if intent_key in self.intent_keys:raise ValueError('DUPLICATE_INTENT_DIFFERENT_RESULT_ID')
        intent=dict(scope='OFFLINE_ENGINE_DISPATCH_INTENT_RECORD_ONLY',engine=engine,result_id=result_id,
            candidate=deepcopy(packet),preflight=audit,planned_context=deepcopy(planned_context),
            pose_age_s=final['now_s']-final['state_stamp_s'],sensor_age_s=final['now_s']-final['obstacle_stamp_s'],
            execution_allowed=False,hardware_execution_allowed=False,execution_issued=False,physical_commands=0,
            dynamic_world_fcl_verified=False,full_visibility_verified=False,automatic_resume=False,
            handoff_success=False,commissioning_passed=False)
        self.consumed.add(result_id);self.intent_keys.add(intent_key);sink.record_intent(intent)
        return intent
