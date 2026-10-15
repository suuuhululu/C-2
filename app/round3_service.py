"""Empty-board C/A/B/D service. The GUI owns authentication; B owns observed state."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import sys
from threading import Event
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

from app import round3_stack_five as stack
from app.c_design import main as c_main
from app.jsonl_log import JsonlLog
from app.mvp_calculation import whole_input, assessment_input, motion_input
from app.round3_approved_step import digest, same_blocks, load_initial_capture
from app.round3_initial_inspection import ROOT, DEFAULT, load_settings, run_initial, open_motion
from app.round3_live_inspection import LiveInspectionObserver
from app.round3_stack_review import HMI_PREFIX, recover_initial_home
from planning_trial.assembly_adapter import (handle_whole_plan, handle_step_reassessment,
    handle_step_motion, receive_result_for_review)
from planning_trial.planning_bundle import validate_planning_bundle
from perception.perception_mvp.team_connection import connect_inspection


def sources():
    """Freeze code/config inputs; recordings, secrets and generated logs are excluded."""
    paths = {ROOT/'interfaces/round3_initial_inspection.json', stack.PROFILE}
    for folder, patterns in [('app',('*.py',)),('interfaces',('*.json',)),('planning_trial',('*.py','*.json')),
            ('perception/perception_mvp',('*.py','*.yaml')),
            ('perception/models',('*.pt',)),
            ('robot_control_integration/scripts',('*.py',)),
            ('robot_control_integration/app',('*.py',)),
            ('robot_control_integration/interfaces',('*.json',)),
            ('robot_control_integration/settings',('*.json','*.yaml')),
            ('robot_control_integration/calibration',('*.json',)),
            ('robot_control_integration/fixtures/teaching_sources',('*.json',)),
            ('perception/calibration',('*.json',)),('perception/recordings/assembly_board_roi',('*.json',))]:
        for pattern in patterns:paths.update((ROOT/folder).rglob(pattern))
    return {str(p):sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if '__pycache__' not in p.parts}


def check_sources(config):
    for name, expected in config['source_sha256'].items():
        p=Path(name)
        if not p.is_relative_to(ROOT) or sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError('SERVICE_SOURCE_CHANGED_REOPEN_HMI: '+name)


class Protocol:
    def __init__(self, source, sink):self.source,self.sink=source,sink
    def publish(self,event,data):
        self.sink.write(HMI_PREFIX+json.dumps(dict(event=event,data=data),ensure_ascii=False,allow_nan=False)+'\n')
        self.sink.flush()
    def ask(self,kind,**data):
        identity=str(uuid4());self.publish('REQUEST',dict(request_id=identity,kind=kind,**data))
        line=self.source.readline()
        if not line:raise KeyboardInterrupt('HMI_CLOSED')
        reply=json.loads(line)
        if set(reply)!={'request_id','answer'} or reply['request_id']!=identity:
            raise ValueError('SERVICE_REPLY_MISMATCH')
        return reply['answer']


def service_settings():
    from app.cad_trial import measured_inputs
    from app.mvp_real_trial import real_settings
    settings=real_settings(measured_inputs(ROOT/'robot_control_integration'))
    # Native pickup/held alignment currently binds this grip axis only. A must
    # plan within that capability rather than having its selected action replaced.
    settings['assembly_context'].update(supported_modes=['ROBOT_GRIP','HUMAN_ASSEMBLY'],grip_axes=['x'])
    settings.update(geometry_reference=load_settings(DEFAULT)['calibration_id'])
    return settings


def read_home(settings,review,cancelled):
    with open_motion(settings,cancelled) as motion:
        motion.confirm(review,'HOME',dict(settings,route_reviewed=True),review,allow_move=False)
        samples=[motion.raw.sample() for _ in range(3)]
    return dict(captured_unix_s=time.time(),physical_commands=0,samples=samples)


def dialogue(bridge, current, record, cancelled, previous=None, reason=None,planning_failure=None):
    question=['원하는 의자 설계를 설명해주세요.']
    def announce(text):
        question[0]=text;bridge.publish('C_QUESTION',dict(text=text))
    def progress(value):bridge.publish('C_PROGRESS',value)
    def answers():
        while not cancelled.is_set():
            text=bridge.ask('C_TEXT',prompt=question[0])
            if not isinstance(text,str) or not text.strip():raise ValueError('C_TEXT_REQUIRED')
            yield text
        raise KeyboardInterrupt('OPERATOR_STOP')
    options=dict(should_stop=cancelled.is_set,on_question=announce,on_progress=progress)
    if previous is None:
        text=bridge.ask('C_TEXT',prompt=question[0])
        result=c_main.create_initial_design(text=text,**options)
    else:
        result=c_main.run_design_change(previous,current['blocks'],reason=reason or 'USER_DESIGN_CHANGE',
            text_answers=answers(),planning_failure=planning_failure,**options)
        if result.get('status')=='OK' and result.get('hri_result')=='KEEP':
            record('SERVICE_C_KEEP',result);return deepcopy(previous)
    while True:
        record('SERVICE_C_RESULT',result)
        if result.get('status')!='OK' or not result.get('design'):
            raise ValueError('C_DESIGN_NOT_READY: '+str(result.get('error')))
        candidate=deepcopy(result['design'])
        bridge.publish('C_PREVIEW',dict(design=candidate,metadata=result.get('design_metadata')))
        question[0]='미리보기를 확인하고 승인 또는 수정 의견을 입력하세요.'
        reviewed=c_main.review_design_candidate(candidate,kind='revised' if previous else 'initial',
            previous_design=previous,current=current['blocks'],differences=[],
            design_metadata=result.get('design_metadata'),text_answers=answers(),
            change_reason=reason,planning_failure=planning_failure,**options)
        record('SERVICE_C_REVIEW',reviewed)
        if reviewed.get('status')!='OK':raise ValueError('C_REVIEW_FAILED: '+str(reviewed.get('error')))
        if reviewed.get('hri_result')=='APPROVE':
            if reviewed['design']!=candidate:raise ValueError('C_APPROVAL_CHANGED_PREVIEW')
            record('SERVICE_C_APPROVED',dict(design=candidate));return candidate
        if reviewed.get('hri_result')!='MODIFY' or reviewed.get('design')==candidate:
            raise ValueError('C_REVIEW_REQUIRES_CLEAR_NEW_CANDIDATE')
        result=reviewed


def plan_design(design,current,settings,job,generation):
    request=whole_input(design,current,settings,job,generation,job)
    result=handle_whole_plan(deepcopy(request))
    if result.get('context')!=request['context'] or result.get('execution_allowed') is not False:
        raise ValueError('A_WHOLE_CONTEXT_CHANGED')
    if (result.get('planning_result') or {}).get('status')!='READY':
        errors=result.get('stage_errors') or (result.get('planning_result') or {}).get('errors') or []
        error=ValueError('A_PLAN_NOT_READY: '+str(errors or result.get('calculation_status')))
        if result.get('calculation_status')=='NO_FEASIBLE_ORDER' or any(
                e.get('code')=='NO_FEASIBLE_ORDER' or e.get('reason')=='NO_FEASIBLE_ORDER' for e in errors):
            error.planning_failure=dict(failure_code='NO_FEASIBLE_ORDER',redesign_required=True,retryable=False,detail=str(errors))
        raise error
    bundle=validate_planning_bundle(result['shared_planning_bundle'])
    if bundle['design']!=design or bundle['plan_base_current']!=current:
        raise ValueError('A_PLAN_DESIGN_OR_REFERENCE_CHANGED')
    return request,result,bundle


def prepare_step(whole,result,current,index,case,settings,receipt,*,manual_only=False):
    """Actual A reassessment/motion, sharing the exact D-owned per-step poses."""
    from app.cad_trial import measured_inputs,step_geometry
    from app.cad_real_trial import live_robot_state
    native=stack.prepare_scenario(dict(preplaced=[],steps=[case],free_motion_speed_scale=2.))[0]
    action=result['action_proposals'][index]
    frame,profile,slot,_=step_geometry(measured_inputs(ROOT/'robot_control_integration'),
        result['shared_planning_bundle']['plan']['steps'][index],action,case['supply_slot'])
    frame['calculation_profiles']['tray']=deepcopy(settings['frame_profile']['calculation_profiles']['tray'])
    cfg=native['config'];onsite=frame['calculation_profiles']['assembly']['d_onsite_step']
    onsite.update(pickup_pose=deepcopy(cfg['blocks'][0]['pickup_pose']),
        reference_pose=deepcopy(cfg['alignment_target']['placement_tcp_reference']),
        assembly_tcp_zyz_deg=deepcopy(cfg['alignment_target']['placement_tcp_reference'][3:]),
        source_sha256=digest(cfg))
    supply=frame['calculation_profiles']['supply']
    supply['d_taught_slot']=dict(identity=dict(brick_type=case['target']['brick_type'],
        color=case['target']['color'],slot_index=case['supply_slot']),
        tcp_mm_zyz_deg=deepcopy(cfg['blocks'][0]['pickup_pose']),source_sha256=digest(cfg))
    def native_solo(action):
        return (action['mode']=='ROBOT_GRIP' and action['grip_axis']=='x'
            and action['assistance_kind']=='NONE' and action.get('assembly_strategy')!='RELEASE_PRESS')
    manual=manual_only or not native_solo(action)
    for attempt in range(2):
        if manual:
            frame['profile_id']='D_ROUND3_PLACE_BOARD_HANDOVER'
            frame['calculation_profiles']['assembly'].pop('d_onsite_step',None)
        assessment_request=assessment_input(whole,result,current,index,frame)
        if manual:
            # Request an actual A manual candidate; do not relabel a robot action.
            assessment_request['assembly_context']['supported_modes']=['HUMAN_ASSEMBLY']
            assessment_request['selected_action']=None
        assessment=handle_step_reassessment(deepcopy(assessment_request))
        if (assessment.get('status')!='CANDIDATE' or
                receive_result_for_review(assessment,assessment_request)['decision']!='STORE_FOR_REVIEW'):
            raise ValueError('A_STEP_REASSESSMENT_NOT_READY: '+str(assessment.get('errors')))
        action=assessment['action_proposal']
        if action['mode']=='HUMAN_ASSEMBLY' or native_solo(action):break
        manual=True
    if not (action['mode']=='HUMAN_ASSEMBLY' or native_solo(action)):
        raise ValueError('A_ACTION_NOT_SUPPORTED_BY_NATIVE_OR_HANDOVER')
    case=deepcopy(case);case.update(human_hold=False,hold_lower=None,execution_mode=action['mode'])
    native['case']=case;cfg['trial_step']=deepcopy(case)
    robot=live_robot_state(receipt,frame)
    receipt_ref='SERVICE_LIVE_STATE:'+digest(receipt)
    robot.update(source_epoch=whole['context']['source_epoch'],state_sequence=index+1,
        stop_observation_ref=receipt_ref,freshness_policy_ref='D_LIVE_QUERY_0.5_SECONDS')
    slot.update(bound_workflow_generation=whole['context']['workflow_generation'],valid_until_ref=receipt_ref)
    request=motion_input(assessment_request,assessment,frame,slot,robot)
    motion=handle_step_motion(deepcopy(request))
    if (motion.get('status')!='CANDIDATE' or
            receive_result_for_review(motion,request)['decision']!='STORE_FOR_REVIEW'):
        codes={e.get('code') for e in motion.get('errors',[])}
        if not manual and codes and codes<={'PATH_BLOCKED','NO_FEASIBLE_METHOD','UNSUPPORTED_METHOD'}:
            fallback,binding=prepare_step(whole,result,current,index,case,settings,receipt,manual_only=True)
            binding['handover_reason']='A_ROBOT_MOTION_NOT_FEASIBLE'
            binding['original_robot_motion_result']=motion
            return fallback,binding
        raise ValueError('A_STEP_MOTION_NOT_READY: '+str(motion.get('errors')))
    from planning_trial.assembly_wire import pose_mm_zyz
    if motion['motion_proposal']['pickup_tcp_pose']!=pose_mm_zyz(cfg['blocks'][0]['pickup_pose']):
        raise ValueError('A_NATIVE_PICKUP_BINDING_CHANGED')
    binding=dict(assessment_request=assessment_request,assessment=assessment,motion_request=request,
        motion=motion,native_config_sha256=digest(cfg),case=case)
    if action['mode']=='HUMAN_ASSEMBLY':
        from app.round3_handover import prepare
        native['handover']=prepare(native,profile,assessment,request,motion)
        binding['handover_sha256']=digest(native['handover'])
    return native,binding


def run_service(config,directory,bridge,cancelled,*,initial=run_initial,execute=stack.execute_step,
                observer_factory=LiveInspectionObserver,read_state=read_home,recover_home=recover_initial_home,
                plan_function=plan_design,prepare_function=prepare_step,execute_handover=None):
    if execute_handover is None:
        from app.round3_handover import execute as execute_handover
    job=str(UUID(config['job_id']));directory=Path(directory).resolve()
    if not directory.is_relative_to(ROOT/'logs'):raise ValueError('SERVICE_LOGS_MUST_STAY_UNDER_CHECKOUT')
    directory.mkdir(parents=True,exist_ok=False)
    settings=load_settings(DEFAULT);a_settings=service_settings();review='OPERATOR_SERVICE_'+job
    logger=JsonlLog(directory/'history');connection=None;plan=None;approved=None
    result=dict(job_id=job,status='HOLD',native_completed=[],handover_completed=[],human_assembly_confirmations=[],
        b_confirmed=[],operator_reviews=[],current=None,
        initial_b_confirmed=False,final_b_confirmed=False,physical_completion=False,reason=None,
        output_directory=str(directory),history_directory=str(directory/'history'))
    def record(event,data=None,*,step_id=None,request_id=None):
        logger(dict(job_id=job,event=event,result=deepcopy(data),plan_id=plan['plan_id'] if plan else None,
            step_id=step_id,request_id=request_id,reason=None))
        if event.startswith(('STACK_','SERVICE_C_','SERVICE_A_')):bridge.publish(event,deepcopy(data))
    def confirm(kind,**data):
        if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
        answer=bridge.ask(kind,**data)
        if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
        return answer
    try:
        check_sources(config)
        stack.save(directory/'.claimed.json',dict(job_id=job))
        record('JOB_STARTED',dict(scope='ROUND3_EMPTY_CABD_SERVICE',creator=config['creator']))
        closed=Event();token=SimpleNamespace(is_set=lambda:cancelled.is_set() or closed.is_set(),set=closed.set)
        record('STACK_INITIAL_BEGIN',dict(job_id=job))
        first=initial(settings,directory/'initial',review_ref=review,cancelled=token)
        record('STACK_INITIAL_RESULT',first)
        if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
        if (first['status']=='INITIAL_CAPTURED_HOME_RETURNED' and first.get('current',{}).get('blocks')==[]
                and all(first.get(k) is True for k in ('home_return_verified','actual_stop_verified','writer_released'))):
            observed,source=load_initial_capture(first['initial_capture_directory'])
            if (observed['status']!='OK' or observed['visible_blocks']
                    or source['geometry_reference']!=settings['calibration_id']
                    or not 0<=time.time()-source['captured_unix_s']<=300):
                raise ValueError('FRESH_REAL_EMPTY_INITIAL_REQUIRED')
            record('SERVICE_INITIAL_SOURCE',source)
            current=deepcopy(first['current']);result.update(current=deepcopy(current),initial_b_confirmed=True)
            basis='B_INITIAL'
        else:
            eligible=(first.get('current') is None and 'INITIAL_STATE_UNAVAILABLE' in str(first.get('reason'))
                and first.get('actual_stop_verified') is True and first.get('writer_released') is True
                and not first.get('stop_error'))
            if not eligible or confirm('B_FAILURE',check_kind='INITIAL',failure=first,target=None) is not True:
                raise ValueError('EMPTY_INITIAL_FAILED: '+str(first.get('reason')))
            home=recover_home(settings,review,cancelled,record)
            if not all(home.get(k) is True for k in ('home_return_verified','actual_stop_verified','writer_released')):
                raise ValueError('INITIAL_RECOVERY_HOME_NOT_VERIFIED')
            basis='OPERATOR_VISUAL_EMPTY_BOARD';current=dict(current_revision=0,blocks=[])
            approval=dict(kind='INITIAL',basis=basis,original_failure=first,approved_unix_s=time.time())
            result['operator_reviews'].append(approval);record('STACK_OPERATOR_REVIEW',approval)
        inbox=Queue();observer=observer_factory(ROOT,settings,directory/'b-checks',review)
        connection=connect_inspection(inbox.put,initial_current=current,geometry_reference=settings['calibration_id'],
            observe=lambda ctx,active:observer(ctx,lambda:active() and not cancelled.is_set()))
        if result['initial_b_confirmed']:
            from app.round3_approved_step import restore_initial_inspection
            restore_initial_inspection(connection,first['initial_capture_directory'],current)
        used=set();generation=0;change_reason=None;planning_failure=None
        while not cancelled.is_set():
            previous=deepcopy(approved)
            approved=dialogue(bridge,current,record,cancelled,approved,change_reason,planning_failure)
            if planning_failure is not None and approved==previous:
                raise ValueError('A_PLAN_FAILURE_REQUIRES_DESIGN_CHANGE')
            planning_failure=None
            generation+=1
            try:whole,a_result,bundle=plan_function(approved,current,a_settings,job,generation)
            except ValueError as error:
                planning_failure=getattr(error,'planning_failure',None)
                if planning_failure is None:raise
                change_reason='A_PLAN_FAILURE: '+str(error)
                record('SERVICE_A_HOLD',dict(reason=change_reason,planning_failure=planning_failure));continue
            plan=bundle['plan'];connection.load_plan(approved,plan,current,geometry_reference=settings['calibration_id'])
            record('PLAN_ADOPTED',dict(design=approved,plan=plan,base_current=current,confirmed_steps=[],state_basis=basis))
            record('SHARED_PLANNING_BUNDLE',bundle)
            record('SERVICE_A_PLAN',dict(design=approved,plan=plan,base_current=current,state_basis=basis))
            matched=0;replan=False
            for index,step in enumerate(plan['steps']):
                if step['operation']!='PLACE' or step['before'] is not None:raise ValueError('NATIVE_PLACE_ONLY')
                check_sources(config)
                target=step['after'];column=target['color']+'_'+target['brick_type']
                slots=[n for n in range(1,6) if (column,n) not in used]
                if not slots:
                    if confirm('REFILL',column=column) is not True:raise KeyboardInterrupt('SUPPLY_REFILL_NOT_CONFIRMED')
                    used={key for key in used if key[0]!=column};slots=[1]
                case=dict(step_id=step['step_id'],target=deepcopy(target),supply_slot=slots[0],human_hold=False)
                decision=confirm('STEP_READY',case=case,index=index,total=len(plan['steps']))
                if decision=='CHANGE':change_reason='USER_DESIGN_CHANGE';replan=True;break
                if decision is not True:raise KeyboardInterrupt('STEP_NOT_APPROVED')
                check_sources(config)
                receipt=read_state(settings,review,cancelled)
                item,binding=prepare_function(whole,a_result,current,index,case,a_settings,receipt)
                record('SERVICE_A_STEP_BOUND',dict(step_id=step['step_id'],binding=binding,state_basis=basis))
                if item['case']['target']!=target or digest(item['config'])!=binding['native_config_sha256']:
                    raise ValueError('C_A_NATIVE_BINDING_CHANGED')
                manual=item['case'].get('execution_mode')=='HUMAN_ASSEMBLY'
                if manual:
                    if digest(item['handover'])!=binding['handover_sha256']:
                        raise ValueError('A_HANDOVER_BINDING_CHANGED')
                    if confirm('HANDOVER_READY',case=item['case'],place_pose=item['handover']['profile']['place_pose']) is not True:
                        raise KeyboardInterrupt('PLACE_BOARD_NOT_CONFIRMED_CLEAR')
                    check_sources(config)
                    receipt=read_state(settings,review,cancelled)
                    item,binding=prepare_function(whole,a_result,current,index,case,a_settings,receipt)
                    if (item['case'].get('execution_mode')!='HUMAN_ASSEMBLY' or item['case']['target']!=target
                            or digest(item['config'])!=binding['native_config_sha256']
                            or digest(item['handover'])!=binding['handover_sha256']):
                        raise ValueError('HANDOVER_METHOD_CHANGED_AFTER_CONFIRMATION')
                    record('SERVICE_A_STEP_BOUND',dict(step_id=step['step_id'],binding=binding,state_basis=basis))
                record('STACK_STEP_BEGIN',dict(index=index+1,total=len(plan['steps']),case=item['case']))
                # Claim the slot before attempting pickup; a failed attempt is never auto-reused.
                used.add((column,slots[0]))
                outcome=(execute_handover if manual else execute)(item,
                    directory/('generation-'+str(generation))/step['step_id'],record,settings,review,cancelled)
                expected_status='PLACE_BOARD_DELIVERED_HOME_RETURNED' if manual else 'THREE_CYCLES_COMPLETED'
                if (outcome.get('status')!=expected_status or outcome.get('completed_steps')!=[step['step_id']]
                        or len(outcome.get('home_returns',[]))!=1 or outcome['home_returns'][0].get('stopped_verified') is not True):
                    raise ValueError('NATIVE_OR_HOME_INCOMPLETE')
                if manual and not all(outcome.get(k) is True for k in ('released','home_return_verified','actual_stop_verified','writer_released')):
                    raise ValueError('HANDOVER_RELEASE_HOME_STOP_OR_WRITER_NOT_VERIFIED')
                result['handover_completed' if manual else 'native_completed'].append(dict(plan_id=plan['plan_id'],step_id=step['step_id']))
                record('STACK_NATIVE_FINISHED',dict(step_id=step['step_id'],receipt=outcome))
                if manual:
                    record('SERVICE_HANDOVER_DELIVERED',dict(case=item['case'],receipt=outcome))
                    if confirm('HUMAN_ASSEMBLY_DONE',case=item['case'],human_actions=binding['assessment']['action_proposal']['human_actions']) is not True:
                        raise KeyboardInterrupt('HUMAN_ASSEMBLY_NOT_CONFIRMED')
                    review_record=dict(step_id=step['step_id'],target=target,confirmed_unix_s=time.time(),
                        b_confirmation=False,source='OPERATOR_COMPLETION_SIGNAL')
                    result['human_assembly_confirmations'].append(review_record)
                    record('SERVICE_HUMAN_ASSEMBLY_CONFIRMED',review_record)
                check_sources(config)
                response,home=inspect(connection,observer,inbox,plan,'STEP',step['step_id'],cancelled,record)
                if response.get('current') is not None:result['current']=deepcopy(response['current'])
                if not all(home.get(k) is True for k in ('home_return_verified','actual_stop_verified','writer_released')):
                    raise ValueError('B_HOME_STOP_OR_WRITER_NOT_VERIFIED')
                prefix=deepcopy(bundle['expected_steps'][index]['after_blocks'])
                if response['status']=='OK' and response['comparison']=='MATCH' and same_blocks(response['current']['blocks'],prefix):
                    current=deepcopy(response['current']);basis='B_CURRENT';matched+=1
                    result['b_confirmed'].append(dict(plan_id=plan['plan_id'],step_id=step['step_id']))
                else:
                    if response['status']=='CANCELED' or confirm('B_FAILURE',check_kind='STEP',failure=response,target=target) is not True:
                        raise ValueError('B_STEP_NOT_CONFIRMED: '+str(response.get('reason')))
                    basis='OPERATOR_VISUAL_STEP_REFERENCE'
                    current=dict(current_revision=current['current_revision']+1,blocks=prefix)
                    approval=dict(kind='STEP',step_id=step['step_id'],basis=basis,original_failure=response,
                        planning_reference=deepcopy(current),approved_unix_s=time.time())
                    result['operator_reviews'].append(approval);record('STACK_OPERATOR_REVIEW',approval)
                record('SERVICE_PLANNING_REFERENCE',dict(reference=current,basis=basis,b_current=result['current']))
            if replan:continue
            record('PLAN_WORK_EXHAUSTED')
            if matched==len(plan['steps']):
                response,home=inspect(connection,observer,inbox,plan,'FINAL',None,cancelled,record)
                if response.get('current') is not None:result['current']=deepcopy(response['current'])
                if not all(home.get(k) is True for k in ('home_return_verified','actual_stop_verified','writer_released')):
                    raise ValueError('FINAL_HOME_STOP_OR_WRITER_NOT_VERIFIED')
                result['final_b_confirmed']=response['status']=='OK' and response['comparison']=='MATCH'
                if not result['final_b_confirmed'] and confirm('B_FAILURE',check_kind='FINAL',failure=response,target=None) is not True:
                    raise ValueError('B_FINAL_NOT_CONFIRMED')
                if not result['final_b_confirmed']:result['operator_reviews'].append(dict(kind='FINAL',original_failure=response))
            else:
                record('STACK_FINAL_NOT_CONFIRMED',dict(reason='FINAL_REQUIRES_ALL_STEP_MATCH'))
            result['physical_completion']=result['final_b_confirmed'] and not result['operator_reviews']
            result['status']='CABD_FINAL_MATCH' if result['physical_completion'] else 'CABD_EXECUTED_WITH_OPERATOR_REVIEW'
            if result['physical_completion']:
                record('ASSEMBLY_COMPLETED',dict(final_check_id=response['check_id'],design_version=approved['design_version']))
            break
        if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
    except (Exception,KeyboardInterrupt) as error:
        result.update(status='HOLD',reason=str(error) or 'OPERATOR_STOP')
        record('STACK_HOLD',dict(reason=result['reason'],automatic_retry=False))
    finally:
        if connection is not None:connection.close();connection._worker.join()
        stack.save(directory/'result.json',result)
        record('STACK_FINISHED',result)
    return result


def inspect(connection,observer,inbox,plan,kind,step,cancelled,record):
    request=dict(check_id=str(uuid4()),check_kind=kind,plan_id=plan['plan_id'],step_id=step)
    record('STACK_B_BEGIN',request);connection.request(request);deadline=time.monotonic()+900.
    while not cancelled.is_set():
        if time.monotonic()>deadline:raise TimeoutError('B_CHECK_TIMEOUT')
        try:response=inbox.get(timeout=.1);break
        except Empty:continue
    else:raise KeyboardInterrupt('OPERATOR_STOP')
    if any(response[k]!=v for k,v in request.items()):raise ValueError('B_RESPONSE_ID_MISMATCH')
    record('CHECK_RESULT',dict(response=response,disposition='ACCEPTED',disposition_reason=None),
        step_id=step,request_id=request['check_id'])
    record('STACK_B_RESULT',response)
    return response,observer.outcomes.get(request['check_id'],{})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('hmi','run','preview'),nargs='?',default='preview')
    parser.add_argument('--config',type=Path);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--offline-c',action='store_true',help='Explicit device-free C verification; REAL run forbids this')
    args=parser.parse_args(argv)
    if args.command=='preview':
        print(json.dumps(dict(status='CABD_EMPTY_BOARD_PREVIEW_NO_DEVICES',initial_blocks=[],
            c='LIVE_DIALOGUE_AND_SEPARATE_APPROVAL',a='WHOLE_REASSESSMENT_AND_MOTION',b='REAL_WITH_PER_FAILURE_CHECKBOX',
            human_handover='A_MANUAL_CANDIDATE_PLACE_BOARD_HOME_OPERATOR_DONE_REAL_B',
            d='NATIVE_POSITION_DESCENT',i_stop_n=50,p_stop_n=60,p_abort_n=70,contact_velocity_mm_s=3,
            storage='AUTHENTICATED_PERSONAL_DB_AND_WEB',physical_commands=0)));return 0
    if args.command=='hmi':
        from app.round3_service_hmi import launch
        return launch()
    if not args.execute or args.offline_c or not args.config:parser.error('REAL run requires --execute --config; offline C is forbidden')
    if os.environ.get('ROS_DOMAIN_ID')!='20' or os.environ.get('C_DESIGN_USE_LLM')!='1' or not os.environ.get('OPENAI_LLM_API_KEY'):
        parser.error('ROS_DOMAIN_ID20, C_DESIGN_USE_LLM=1 and OPENAI_LLM_API_KEY are required')
    config=json.loads(args.config.read_text());cancelled=Event()
    def interrupt(*_):cancelled.set();raise KeyboardInterrupt('OPERATOR_STOP')
    previous={s:signal.signal(s,interrupt) for s in (signal.SIGINT,signal.SIGTERM)}
    try:
        result=run_service(config,args.config.parent/'run',Protocol(sys.stdin,sys.stdout),cancelled)
        return 0 if result['status'] in ('CABD_FINAL_MATCH','CABD_EXECUTED_WITH_OPERATOR_REVIEW') else 2
    finally:
        for s,handler in previous.items():signal.signal(s,handler)


if __name__=='__main__':raise SystemExit(main())
