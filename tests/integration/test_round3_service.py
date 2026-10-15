"""C public dialogue/review, real A calculations and B transactions; no devices."""
from copy import deepcopy
from io import StringIO
import json
from threading import Event
import time
from uuid import uuid4

import pytest

from app import round3_service as service
from test_round3_stack_five import fixtures,coverage_failure


class Bridge:
    def __init__(self,review=True):self.events=[];self.requests=[];self.review=review
    def publish(self,event,data):self.events.append((event,deepcopy(data)))
    def ask(self,kind,**data):
        self.requests.append((kind,deepcopy(data)))
        if kind=='C_TEXT':return '의자' if len([r for r in self.requests if r[0]=='C_TEXT'])==1 else '좋아 이걸로 하자'
        return self.review if kind=='B_FAILURE' else True


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    # Only the generator is synthetic. Public C validation and explicit review
    # remain real, as do A whole/reassessment/motion and B comparison.
    design=dict(design_version=1,blocks=[dict(brick_type='2x2x1',color='yellow',x=11,y=11,
        layer=n,orientation_deg=0) for n in (1,2)])
    monkeypatch.setattr(service.c_main.designer,'build_initial_design',lambda *a,**kw:
        dict(design=deepcopy(design),reasons=[],attempts=1,source='EXPLICIT_TEST_ONLY'))
    folder=service.ROOT/'logs/round3-service-tests'/str(uuid4())
    config=dict(job_id=str(uuid4()),creator=dict(user_id=str(uuid4()),username='fixture',display_name='시험'),source_sha256={})
    return folder,config,design


def state(*_):
    sample=dict(tcp='GripperDA_v4',tool='ToolWeight0',robot_state=1,robot_mode=1,drl_state=3,
        motion_status=0,velx=[0.]*6,posx=[450.,0.,400.,0.,180.,0.],query_duration_s=.01,
        gripper_width_mm=62.1,gripper_status=0)
    return dict(captured_unix_s=time.time(),physical_commands=0,samples=[deepcopy(sample) for _ in range(3)])


def run(setup,fault=None,review=True,**overrides):
    folder,config,design=setup
    first,execute,observer,launches,kinds=fixtures(folder,{},{'initial_bad':'initial'}.get(fault,fault))
    def initial(*a,**kw):
        result=first(*a,**kw)
        if result.get('initial_capture_directory'):
            path=service.Path(result['initial_capture_directory'])/'observed.json'
            observed=json.loads(path.read_text())
            observed['verified_regions']=[dict(x=0,y=0,width=24,height=24,layer=n) for n in range(1,6)]
            path.write_text(json.dumps(observed))
        return result
    if fault=='initial_review':initial=lambda *a,**kw:coverage_failure()
    bridge=overrides.pop('bridge',Bridge(review))
    def handover(item,*args):
        outcome=execute(item,*args)
        outcome.update(status='PLACE_BOARD_DELIVERED_HOME_RETURNED',released=True,
            home_return_verified=fault!='handover_home',actual_stop_verified=fault!='handover_stop',
            writer_released=fault!='handover_writer')
        return outcome
    options=dict(initial=initial,execute=execute,observer_factory=observer,read_state=state,
        execute_handover=handover,
        recover_home=lambda *a:dict(home_return_verified=True,actual_stop_verified=True,writer_released=True))
    options.update(overrides)
    result=service.run_service(config,folder/'run',bridge,Event(),**options)
    history=[json.loads(line) for line in (folder/'run/history'/(config['job_id']+'.jsonl')).read_text().splitlines()]
    return result,bridge,launches,kinds,history


def test_c_preview_approval_actual_a_each_step_b_and_separate_final(setup):
    result,bridge,launches,kinds,history=run(setup)
    assert result['status']=='CABD_FINAL_MATCH',result['reason']
    assert result['physical_completion'] and len(launches)==2 and kinds==['STEP','STEP','FINAL']
    events=[e for e,_ in bridge.events]
    assert events.index('C_PREVIEW')<events.index('SERVICE_C_APPROVED')<events.index('SERVICE_A_PLAN')<events.index('STACK_STEP_BEGIN')
    bindings=[data['binding'] for event,data in bridge.events if event=='SERVICE_A_STEP_BOUND']
    assert len(bindings)==2
    for binding in bindings:
        assert binding['assessment']['status']==binding['motion']['status']=='CANDIDATE'
        assert binding['motion_request']['robot_state']['stop_observation_ref'].startswith('SERVICE_LIVE_STATE:')
        assert binding['motion_request']['reserved_supply_slot']['bound_workflow_generation']==1
    assert sum(h['event']=='ASSEMBLY_COMPLETED' for h in history)==1
    from history.records import parse_record
    for n,row in enumerate(history,1):parse_record(json.dumps(row).encode(),'explicit-service-fixture',n,contract='final-mvp-20261008')


@pytest.mark.parametrize('fault',['MISMATCH','UNOBSERVABLE','ERROR_HOME','initial_review'])
def test_b_failure_checkbox_preserves_original_and_unconfirmed_completion(setup,fault):
    result,bridge,launches,kinds,history=run(setup,fault)
    assert result['status']=='CABD_EXECUTED_WITH_OPERATOR_REVIEW',result['reason']
    assert len(launches)==2 and not result['physical_completion'] and result['operator_reviews']
    assert not any(row['event']=='ASSEMBLY_COMPLETED' for row in history)
    reviews=[r for r in bridge.requests if r[0]=='B_FAILURE']
    assert len(reviews)==(1 if fault=='initial_review' else 2)
    if fault!='initial_review':assert kinds==['STEP','STEP'] and not result['final_b_confirmed']


@pytest.mark.parametrize('fault',['initial_bad','native','native_home','b_home','writer','ERROR'])
def test_device_stop_home_writer_faults_cannot_be_checkbox_bypassed(setup,fault):
    result,bridge,launches,kinds,history=run(setup,fault)
    assert result['status']=='HOLD' and not result['physical_completion']
    assert len(launches)==(0 if fault=='initial_bad' else 1)
    assert not any(kind=='B_FAILURE' for kind,_ in bridge.requests)


def test_reject_b_review_stops_before_next_pickup(setup):
    result,bridge,launches,_,_=run(setup,'MISMATCH',review=False)
    assert result['status']=='HOLD' and len(launches)==1


def test_stale_sources_hold_before_initial(setup):
    folder,config,_=setup
    config['source_sha256']={str(service.ROOT/'app/round3_service.py'):'0'*64}
    result,*_=run(setup,initial=lambda *a,**kw:pytest.fail('source change must not reach INITIAL'))
    assert result['status']=='HOLD' and 'SOURCE_CHANGED' in result['reason']


def test_protocol_rejects_stale_reply_and_eof():
    protocol=service.Protocol(StringIO('{"request_id":"stale","answer":true}\n'),StringIO())
    with pytest.raises(ValueError,match='REPLY_MISMATCH'):protocol.ask('STEP_READY')
    with pytest.raises(KeyboardInterrupt,match='HMI_CLOSED'):service.Protocol(StringIO(''),StringIO()).ask('C_TEXT')


@pytest.mark.parametrize('unknown_at_target',[True,False])
def test_real_initial_coverage_is_retained_before_a_plan_load(setup,unknown_at_target):
    folder,_,_=setup
    initial,_,_,_,_=fixtures(folder,{})
    def partial(*args,**kwargs):
        result=initial(*args,**kwargs)
        path=service.Path(result['initial_capture_directory'])/'observed.json'
        observed=json.loads(path.read_text());x,y=(11,11) if unknown_at_target else (0,0)
        observed['verified_regions']=[dict(x=xx,y=yy,width=1,height=1,layer=layer)
            for yy in range(24) for xx in range(24) for layer in range(1,6) if (xx,yy,layer)!=(x,y,5)]
        path.write_text(json.dumps(observed));return result
    result,_,launches,_,_=run(setup,initial=partial)
    if unknown_at_target:
        assert result['status']=='HOLD' and 'PLAN_REGION_UNVERIFIED' in result['reason'] and launches==[]
    else:assert result['physical_completion'] and len(launches)==2


def test_a_contract_error_holds_instead_of_starting_c_redesign(setup):
    def invalid(*a):raise ValueError('A_INVALID_CONTEXT')
    result,bridge,launches,_,_=run(setup,plan_function=invalid)
    assert result['status']=='HOLD' and not launches and result['reason']=='A_INVALID_CONTEXT'
    assert len([kind for kind,_ in bridge.requests if kind=='C_TEXT'])==2


def test_all_twenty_five_registered_slots_can_be_bound_without_devices():
    service.stack.native()
    from app.supply_stud.execution_profile import load
    registry=load(service.stack.PROFILE)
    assert len(registry['slots'])==25
    for row in registry['slots']:
        color,kind,slot=row['slot_id'].split('_')
        case=dict(step_id='EXPLICIT_NO_DEVICE_CHECK',target=dict(brick_type=kind,color=color,x=11,y=11,
            layer=1,orientation_deg=0),supply_slot=int(slot),human_hold=False)
        item=service.stack.prepare_scenario(dict(preplaced=[],steps=[case],free_motion_speed_scale=2.))[0]
        cfg=item['config']
        assert cfg['educational_supply_binding']['slot_id']==row['slot_id']
        assert cfg['seating_force_stop_n']==50. and cfg['press_force_stop_n']==60. and cfg['press_force_abort_n']==70.
        assert cfg['seating_velocity']==cfg['press_velocity']==3.


def test_design_change_uses_real_c_separate_approval_a_replan_and_remaining_slots(setup,monkeypatch):
    replies=iter(['의자','좋아 이걸로 하자','수정해줘','좋아 이걸로 하자'])
    class ChangedBridge(Bridge):
        changed=False
        def ask(self,kind,**data):
            self.requests.append((kind,deepcopy(data)))
            if kind=='C_TEXT':return next(replies)
            if kind=='STEP_READY' and data['index']==1 and not self.changed:
                self.changed=True;return 'CHANGE'
            return True
    design=deepcopy(setup[2]);design['design_version']=2
    design['blocks'].append(dict(design['blocks'][0],layer=3))
    monkeypatch.setattr(service.c_main.designer,'build_revised_design',lambda *a,**kw:
        dict(design=deepcopy(design),reasons=[],attempts=1,source='EXPLICIT_TEST_ONLY'))
    result,bridge,launches,kinds,history=run(setup,bridge=ChangedBridge())
    assert result['physical_completion'],result['reason']
    approvals=[d for e,d in bridge.events if e=='SERVICE_C_APPROVED']
    plans=[d for e,d in bridge.events if e=='SERVICE_A_PLAN']
    assert [d['design']['design_version'] for d in approvals]==[1,2]
    assert [len(d['plan']['steps']) for d in plans]==[2,2]
    assert plans[-1]['base_current']['blocks']==[setup[2]['blocks'][0]]
    bindings=[d['binding'] for e,d in bridge.events if e=='SERVICE_A_STEP_BOUND']
    assert [d['case']['supply_slot'] for d in bindings]==[1,2,3]
    assert bindings[-1]['motion_request']['reserved_supply_slot']['bound_workflow_generation']==2
    assert len(launches)==3 and kinds==['STEP']*3+['FINAL']


def manual_design(setup):
    design=setup[2]
    design['blocks'][:]=[dict(brick_type='2x3x1',color='blue',x=11,y=11,layer=1,orientation_deg=0),
        dict(brick_type='2x3x1',color='yellow',x=11,y=11,layer=2,orientation_deg=90)]
    return design


def test_rotated_block_is_a_manual_candidate_and_waits_for_human_then_real_b(setup):
    manual_design(setup)
    class ReviewBridge(Bridge):
        def ask(self,kind,**data):
            if kind=='HUMAN_ASSEMBLY_DONE':
                seen=[d for e,d in self.events if e=='STACK_B_RESULT']
                assert len(seen)==1 and len(seen[0]['current']['blocks'])==1
            return super().ask(kind,**data)
    result,bridge,launches,kinds,_=run(setup,bridge=ReviewBridge())
    assert result['physical_completion'],result['reason']
    assert len(result['native_completed'])==len(result['handover_completed'])==len(result['human_assembly_confirmations'])==1
    requests=[kind for kind,_ in bridge.requests]
    assert requests.count('HANDOVER_READY')==requests.count('HUMAN_ASSEMBLY_DONE')==1
    bindings=[d['binding'] for e,d in bridge.events if e=='SERVICE_A_STEP_BOUND']
    manual=[d for d in bindings if d['assessment']['action_proposal']['mode']=='HUMAN_ASSEMBLY']
    assert len(manual)==2  # Fresh state/reassessment after the tray-clear checkbox.
    assert all(d['motion']['motion_proposal']['motion_scope']=='PICK_TRANSPORT_TO_HANDOVER_TRAY' for d in manual)
    assert kinds==['STEP','STEP','FINAL'] and len(launches)==2


@pytest.mark.parametrize('rejected',['HANDOVER_READY','HUMAN_ASSEMBLY_DONE'])
def test_no_pickup_or_b_inspection_until_corresponding_human_confirmation(setup,rejected):
    manual_design(setup)
    class RejectBridge(Bridge):
        def ask(self,kind,**data):
            if kind==rejected:self.requests.append((kind,data));return False
            return super().ask(kind,**data)
    result,_,launches,kinds,_=run(setup,bridge=RejectBridge())
    assert result['status']=='HOLD' and not result['physical_completion']
    assert len(launches)==(1 if rejected=='HANDOVER_READY' else 2)
    assert kinds==['STEP'] and len(result['current']['blocks'])==1


@pytest.mark.parametrize('fault',['handover_home','handover_stop','handover_writer'])
def test_handover_device_failure_cannot_be_accepted_by_human_or_b_checkbox(setup,fault):
    manual_design(setup)
    result,bridge,launches,kinds,_=run(setup,fault)
    assert result['status']=='HOLD' and len(launches)==2 and kinds==['STEP']
    assert not any(kind in ('B_FAILURE','HUMAN_ASSEMBLY_DONE') for kind,_ in bridge.requests)


def test_a_geometric_robot_path_failure_requests_real_manual_candidate_before_pickup(setup,monkeypatch):
    original=service.handle_step_motion
    def blocked_robot(request):
        result=original(request)
        if request['action_proposal']['mode']=='ROBOT_GRIP':
            result.update(status='BLOCKED',motion_proposal=None,errors=[dict(code='PATH_BLOCKED',reason='EXPLICIT_TEST_PATH_OBSTACLE',block=request['selected_step']['after'])])
        return result
    monkeypatch.setattr(service,'handle_step_motion',blocked_robot)
    result,bridge,launches,kinds,_=run(setup)
    assert result['physical_completion'],result['reason']
    assert len(result['handover_completed'])==2 and result['native_completed']==[]
    assert len(launches)==2 and kinds==['STEP','STEP','FINAL']
    bindings=[d['binding'] for e,d in bridge.events if e=='SERVICE_A_STEP_BOUND']
    assert all(d['handover_reason']=='A_ROBOT_MOTION_NOT_FEASIBLE' for d in bindings)
