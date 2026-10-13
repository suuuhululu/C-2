from copy import deepcopy
from queue import Queue

import pytest

from app.c_design import main as c
from app.mvp_fake import settings, prepare
from app.mvp_workflow import MvpWorkflow
from perception.perception_mvp.team_connection import connect_inspection
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment, handle_step_motion


def block(layer=1,color='blue',kind='2x2x1',angle=0):
    return dict(brick_type=kind,color=color,x=6,y=6,layer=layer,orientation_deg=angle)


class Harness:
    def __init__(self,path):
        self.ports,self.results=[],Queue()
        self.scene,self.layers=[],list(range(1,6))
        self.workflow=MvpWorkflow(lambda port,payload:self.ports.append((port,deepcopy(payload))),settings(),path)
        self.b=connect_inspection(self.results.put,observe=self.observe,geometry_reference='FAKE_19_4.5_16')
        self.workflow.b=self.b
    def observe(self,context,active):
        return dict(check_id=context['check_id'],observation_seq=context['observation_seq'],status='OK',
            visible_blocks=deepcopy(self.scene),verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in self.layers],reason=None),{}
    def check(self):
        self.b._queue.join()
        return self.workflow.receive_check(self.results.get(timeout=2))
    def calculations(self):
        functions={'a.whole':handle_whole_plan,'a.assess':handle_step_reassessment,'a.motion':handle_step_motion}
        while self.ports:
            port,payload=self.ports[0]
            if port=='d.prepare_step':
                self.ports.pop(0);self.workflow.prepared_step(prepare(self.workflow,payload))
            elif port in functions:
                self.ports.pop(0);self.workflow.receive(port,payload['request_id'],functions[port](payload['input']))
            else:break
    def approved(self,design):
        self.workflow.start();self.check()
        port,payload=self.ports.pop(0)
        self.workflow.receive(port,payload['request_id'],dict(status='OK',design=design,hri_result=None))
        preview=self.workflow.candidate['request_id']
        assert self.workflow.approved is None
        self.workflow.preview_ready(preview)
        port,payload=self.ports.pop(0)
        response=c.review_design_candidate(design,kind='initial',text_answers=['좋아 이걸로 하자'])
        self.workflow.receive(port,payload['request_id'],response)
        self.calculations()
    def close(self):self.b.close()


@pytest.fixture
def h(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    harness=Harness(tmp_path)
    yield harness
    harness.close()


@pytest.mark.parametrize('kind,color,angle',[('2x2x1','blue',0),('2x2x1','yellow',0),
    ('2x3x1','blue',0),('2x3x1','blue',90),('2x3x1','yellow',0),('2x3x1','yellow',90),
    ('1x2x1','red',0),('1x2x1','red',90)])
def test_c_supported_design_reaches_a_motion_candidate_without_execution_permission(h,kind,color,angle):
    h.approved(dict(design_version=1,blocks=[block(color=color,kind=kind,angle=angle)]))
    assert h.ports[0][0]=='robot.EXECUTE',h.workflow.reason
    assert not h.workflow.step_inputs['motion']['execution_allowed']
    assert h.b.inspection.current==h.workflow.current
    assert h.workflow.bundle['plan_base_current']==h.workflow.current
    h.workflow.snapshot()


def test_initial_partial_evidence_never_starts_c_or_a(h):
    h.layers=[1];h.workflow.start();h.check()
    assert h.workflow.status=='HOLD' and not h.ports
    with pytest.raises(ValueError,match='Current is not known'):
        h.b.inspection.current
    h.workflow.snapshot()


def test_actual_mismatch_keep_replans_instead_of_marking_step_success(h):
    h.approved(dict(design_version=1,blocks=[block()]))
    w=h.workflow;h.ports.clear()
    w.robot_event(dict(event='INSPECTION_REQUIRED',data=dict(execution_id=w.execution_id)))
    h.scene=[block(color='yellow')];h.check()
    assert w.current==h.b.inspection.current
    port,payload=next((p,r) for p,r in h.ports if p=='c.intent')
    assert payload['expected']['blocks']==[block()]
    assert payload['current']['blocks']==h.scene
    w.receive(port,payload['request_id'],dict(status='OK',hri_result='KEEP',design=w.approved))
    assert not w.completed and w.active['port']=='a.whole'


def test_user_change_finishes_step_check_and_blocks_next_step(h):
    h.approved(dict(design_version=1,blocks=[block(),block(2)]))
    w=h.workflow;h.ports.clear()
    assert w.change_design()
    assert w.status=='DELIVERING' and not w.active
    h.scene=[block()]
    w.robot_event(dict(event='INSPECTION_REQUIRED',data=dict(execution_id=w.execution_id)))
    h.check()
    assert len(w.completed)==1
    w.robot_event(dict(event='B_DECISION',data=dict(execution_id=w.execution_id)))
    assert w.status=='WAIT_INTENT' and w.active['port']=='c.intent'
    assert not any(p=='robot.EXECUTE' for p,_ in h.ports)


def test_stop_ack_is_not_stop_proof_and_old_result_cannot_approve(h):
    w=h.workflow;w.start();h.check()
    old=deepcopy(w.active)
    assert w.stop()
    w.robot_event(dict(event='STOP_ACCEPTED',data=dict(actual_stop_verified=False)))
    assert w.status=='HOLD' and w.reason=='STOP_PENDING'
    assert not w.receive(old['port'],old['request']['request_id'],dict(status='OK',design={'design_version':1,'blocks':[block()]}))
    w.robot_event(dict(event='STOP_VERIFIED',data=dict(actual_stop_verified=True)))
    assert w.status=='STOPPED' and w.approved is None


def test_final_without_new_evidence_keeps_revision_and_blocks_completion(h):
    h.approved(dict(design_version=1,blocks=[block()]))
    w=h.workflow;h.ports.clear();h.scene=[block()]
    w.robot_event(dict(event='INSPECTION_REQUIRED',data=dict(execution_id=w.execution_id)));h.check()
    current=deepcopy(w.current);h.layers=[];h.scene=[]
    w.robot_event(dict(event='B_DECISION',data=dict(execution_id=w.execution_id)));h.check()
    assert w.status=='HOLD' and w.current==current and w.assembly=='UNOBSERVABLE'
    assert w.storage=='NOT_STARTED'
    w.snapshot()


def test_new_design_change_entry_does_not_require_fabricated_deviation(h):
    design=dict(design_version=1,blocks=[block()])
    response=c.run_design_change(design,[],reason='사용자 설계 변경',text_answers=['1번'])
    assert response['status']=='OK' and response['hri_result']=='KEEP'
    assert c.run_intervention(design,[],[],text_answers=['1번'])['status']=='FAILED'


def test_a_no_order_opens_c_but_invalid_input_does_not(h):
    w=h.workflow;w.start();h.check()
    w.approved=dict(design_version=1,blocks=[block()]);w.plan()
    request=w.active['request']['request_id']
    result=handle_whole_plan(w.active['request']['input'])
    result.update(calculation_status='NO_FEASIBLE_ORDER',planning_result=None,action_proposals=[],shared_planning_bundle=None,
        stage_errors=[dict(code='NO_FEASIBLE_ORDER',reason='NO_FEASIBLE_ORDER',block=None)])
    w.receive('a.whole',request,result)
    assert w.active['port']=='c.plan_failure' and w.status=='WAIT_INTENT'
    w.plan();request=w.active['request']['request_id']
    malformed=deepcopy(w.active['request']['input']);malformed['assembly_context']['geometry']['pitch_mm']=0
    result=handle_whole_plan(malformed)
    w.receive('a.whole',request,result)
    assert w.status=='HOLD' and w.active is None


def test_a_result_with_foreign_context_never_adopts_plan(h):
    w=h.workflow;w.start();h.check()
    w.approved=dict(design_version=1,blocks=[block()]);w.plan()
    active=deepcopy(w.active)
    result=handle_whole_plan(active['request']['input'])
    result['context']['workflow_generation']+=1
    assert not w.receive('a.whole',active['request']['request_id'],result)
    assert w.bundle is None and w.status=='HOLD'
    assert not any(port=='robot.EXECUTE' for port,_ in h.ports)


def test_revised_candidate_cannot_remove_confirmed_blocks(h):
    h.approved(dict(design_version=1,blocks=[block()]))
    w=h.workflow;w.current=dict(current_revision=1,blocks=[block()])
    with pytest.raises(ValueError,match='preserve B Current'):
        w.receive_c('c.intent',dict(status='OK',hri_result='REVISE',design=dict(design_version=2,blocks=[block(color='yellow')])))
    assert w.approved['design_version']==1


def test_inspection_context_keeps_expected_and_unknown_regions_for_c(h,monkeypatch):
    from app.c_design import llm
    context=dict(expected=dict(blocks=[block()]),difference=dict(missing=[],unexpected=[],unobservable=[block()]),reason='USER_DESIGN_CHANGE')
    seen=[]
    def interpret(text,pairs,should_stop=None,context=None):
        seen.append(deepcopy(context))
        return dict(decision='KEEP',reason='시험',style_hint='',reply='목표 유지')
    monkeypatch.setenv('C_DESIGN_USE_LLM','1')
    monkeypatch.setattr(llm,'interpret_intervention_answer',interpret)
    response=c.run_design_change(dict(design_version=1,blocks=[block()]),[],reason='USER_DESIGN_CHANGE',text_answers=['이 배치하고 비교해서 결정해줘'],inspection_context=context)
    assert response['hri_result']=='KEEP' and seen[0]['expected']==context['expected']
    assert seen[0]['difference']['unobservable']==[block()]


def test_log_failure_holds_before_any_a_request(h):
    w=h.workflow
    def fail(event):raise OSError('fixture disk full')
    w.record=fail
    assert not w.start()
    assert w.status=='HOLD' and [p for p,_ in h.ports]==['robot.STOP']


def test_robot_only_offline_chair_without_feasible_order_opens_c_not_robot(h):
    w=h.workflow;w.start();h.check()
    w.settings['assembly_context']['supported_modes']=['ROBOT_GRIP']
    w.approved=c.create_initial_design(text='의자')['design'];w.plan()
    payload=deepcopy(w.active['request'])
    import json
    from pathlib import Path
    # D 소비부 계약 검사: 실제 A의 의자 개선과 무관하게 실패 응답을 유지한다.
    result=json.loads((Path(__file__).resolve().parents[2]/'interfaces/fixtures/mvp_a_no_feasible_order.json').read_text())
    assert result['calculation_status']=='NO_FEASIBLE_ORDER'
    result['context']=deepcopy(payload['input']['context'])
    w.receive('a.whole',payload['request_id'],result)
    assert w.active['port']=='c.plan_failure' and w.status=='WAIT_INTENT'
    assert not any(p=='robot.EXECUTE' for p,_ in h.ports)


def test_duplicate_stale_and_conflicting_check_results_remain_distinct(h):
    from uuid import uuid4
    w=h.workflow
    h.approved(dict(design_version=1,blocks=[block(),block(2)]))
    h.ports.clear();h.scene=[block()]
    w.robot_event(dict(event='INSPECTION_REQUIRED',data=dict(execution_id=w.execution_id)))
    h.check()
    accepted=deepcopy(w.inspection);current=deepcopy(w.current);completed=deepcopy(w.completed)
    ports=deepcopy(h.ports)
    assert not w.receive_check(accepted)
    assert w.current==current and w.completed==completed and h.ports==ports
    stale=deepcopy(accepted);stale['check_id']=str(uuid4())
    assert not w.receive_check(stale)
    assert w.check_conflict is None
    conflict=deepcopy(accepted)
    extra=block();extra['x']=15
    conflict['current']['current_revision']+=1
    conflict['current']['blocks'].append(extra)
    conflict['observation']['visible_blocks'].append(extra)
    conflict['comparison']='MISMATCH';conflict['difference']['unexpected']=[extra]
    assert not w.receive_check(conflict)
    assert w.reason=='STOP_PENDING' and h.ports[-1][0]=='robot.STOP'
    assert w.check_conflict['original']==accepted and w.check_conflict['conflicting']==conflict
    assert w.current==current and w.completed==completed
    w.robot_event(dict(event='STOP_VERIFIED',data=dict(execution_id=w.execution_id,actual_stop_verified=True)))
    assert w.status=='HOLD' and w.reason=='CONFLICTING_CHECK_RESULT'
    assert not w.resume() and not w.reinspect()
    assert w.snapshot()['notice']['reason']=='CONFLICTING_CHECK_RESULT'


def test_revise_without_design_waits_then_reviews_the_same_request_candidate(h):
    w=h.workflow;h.approved(dict(design_version=1,blocks=[block()]))
    before=(deepcopy(w.approved),deepcopy(w.current),deepcopy(w.completed))
    h.ports.clear();w.status='WAIT_INTENT'
    request=w.call('c.intent',dict(design=w.approved,current=w.current,reason='USER_DESIGN_CHANGE'))
    assert w.receive('c.intent',request['request_id'],dict(status='OK',hri_result='REVISE',design=None,questions=['수정 중']))
    assert w.status=='WAIT_INTENT' and w.reason=='DESIGN_CHANGE_PENDING'
    assert w.active['request']['request_id']==request['request_id']
    assert (w.approved,w.current,w.completed)==before and w.candidate is None
    assert not any(p.startswith('a.') or p=='robot.EXECUTE' for p,_ in h.ports)
    candidate=dict(design_version=2,blocks=[block(color='yellow')])
    assert w.receive('c.intent',request['request_id'],dict(status='OK',hri_result='REVISE',design=candidate))
    assert w.candidate['design']==candidate and w.approved==before[0]
    assert w.preview_ready(w.candidate['request_id'])
    request=w.active['request']
    assert w.active['port']=='c.review'
    assert w.receive('c.review',request['request_id'],dict(status='OK',hri_result='APPROVE',design=candidate))
    assert w.approved==candidate and w.active['port']=='a.whole'


def test_stop_closes_delayed_revise_request_and_rejects_late_design(h):
    w=h.workflow;h.approved(dict(design_version=1,blocks=[block()]))
    w.status='WAIT_INTENT'
    request=w.call('c.intent',dict(design=w.approved,current=w.current,reason='USER_DESIGN_CHANGE'))
    w.receive('c.intent',request['request_id'],dict(status='OK',hri_result='REVISE',design=None))
    before=deepcopy(w.approved)
    assert w.stop()
    assert not w.receive('c.intent',request['request_id'],dict(status='OK',hri_result='REVISE',design=dict(design_version=2,blocks=[block()])))
    assert w.approved==before and w.candidate is None


@pytest.mark.parametrize('mode,expected',[('FAKE','STOPPED'),('REAL','HOLD')])
def test_stop_idle_is_only_mock_idle_confirmation(h,mode,expected):
    w=h.workflow;w.mode=mode
    w.start();h.check()
    assert w.execution_id is None and w.stop()
    w.robot_event(dict(event='STOP_IDLE',data=dict(actual_stop_verified=False,physical_commands=0)))
    assert w.status==expected
    if mode=='REAL':assert w.reason=='STOP_PENDING' and not w.resume()
    w.snapshot()


def test_offline_chair_with_manual_help_returns_complete_candidate(h):
    w=h.workflow;w.start();h.check()
    design=c.create_initial_design(text='의자')['design']
    w.approved=design;w.plan()
    payload=deepcopy(w.active['request'])
    result=handle_whole_plan(payload['input'])
    assert result['calculation_status']=='COMPLETED'
    assert result['planning_result']['status']=='READY'
    actions=result['action_proposals']
    assert len(actions)==len(design['blocks'])==15
    assert sum(a['mode']=='HUMAN_ASSEMBLY' for a in actions)==2
    assert all(human['access_assessment']=='HUMAN_ACCESS_NOT_CHECKED'
               for a in actions for human in a['human_actions'])
    assert result['execution_allowed'] is False
    assert not any(p=='robot.EXECUTE' for p,_ in h.ports)


@pytest.mark.parametrize('allowed',[True,False])
def test_hmi_preserves_recovery_reason_and_only_enables_verified_resumable_step(h,allowed):
    h.approved(dict(design_version=1,blocks=[block()]))
    w=h.workflow;identity=w.execution_id
    w.robot_event(dict(event='STOP_VERIFIED',data=dict(execution_id=identity,actual_stop_verified=True)))
    w.robot_event(dict(event='EXECUTION_HELD',data=dict(execution_id=identity,status='RECOVERY_REQUIRED',
        reason='IK_FK_ROUNDTRIP_MISMATCH',resume_allowed=allowed)))
    assert w.status==('STOPPED' if allowed else 'HOLD') and w.reason=='IK_FK_ROUNDTRIP_MISMATCH'
    assert w.snapshot()['actions']['resume']['enabled'] is allowed
    if not allowed:assert not w.resume()


def test_plan_failure_keep_preserves_goal_and_current_without_repeating_same_request(h):
    w=h.workflow;w.start();h.check()
    w.approved=dict(design_version=1,blocks=[block()]);w.plan()
    request=deepcopy(w.active)
    result=handle_whole_plan(request['request']['input'])
    result.update(calculation_status='NO_FEASIBLE_ORDER',planning_result=None,action_proposals=[],shared_planning_bundle=None,
        stage_errors=[dict(code='NO_FEASIBLE_ORDER',reason='NO_FEASIBLE_ORDER',block=None)])
    assert w.receive('a.whole',request['request']['request_id'],result)
    active=deepcopy(w.active);goal=deepcopy(w.approved);current=deepcopy(w.current)
    calls=len(h.ports);generation=w.generation;reason=w.reason
    assert w.receive('c.plan_failure',active['request']['request_id'],dict(status='OK',hri_result='KEEP',design=goal))
    assert w.status=='HOLD' and w.active is None and w.reason==reason
    assert w.approved==goal and w.current==current and w.bundle is None
    assert len(h.ports)==calls and w.generation==generation
    assert not w.receive('c.plan_failure',active['request']['request_id'],dict(status='OK',hri_result='KEEP',design=goal))
    assert w.snapshot()['user_requests']['change_design']['enabled']
    assert w.change_design() and w.active['port']=='c.intent'


def test_plan_failure_unclear_preserves_approval_and_waits_for_explicit_change(h):
    w=h.workflow;w.start();h.check()
    w.approved=dict(design_version=1,blocks=[block()]);w.plan()
    request=deepcopy(w.active)
    result=handle_whole_plan(request['request']['input'])
    result.update(calculation_status='NO_FEASIBLE_ORDER',planning_result=None,action_proposals=[],shared_planning_bundle=None,
        stage_errors=[dict(code='NO_FEASIBLE_ORDER',reason='NO_FEASIBLE_ORDER',block=None)])
    assert w.receive('a.whole',request['request']['request_id'],result)
    active=deepcopy(w.active);goal=deepcopy(w.approved);current=deepcopy(w.current);calls=len(h.ports)
    response=c.run_design_change(goal,current['blocks'],reason=active['request']['reason'],text_answers=['음','음'])
    assert response['hri_result']=='UNCLEAR'
    assert w.receive('c.plan_failure',active['request']['request_id'],response)
    assert w.status=='HOLD' and w.active is None and len(h.ports)==calls
    assert w.approved==goal and w.current==current and w.bundle is None
    assert not w.receive('c.plan_failure',active['request']['request_id'],response)
    assert w.snapshot()['user_requests']['change_design']['enabled']
    assert w.change_design() and w.active['port']=='c.intent'


@pytest.mark.parametrize('code',['SEARCH_LIMIT','CALCULATION_ERROR','INVALID_CONTEXT'])
def test_non_design_planning_failures_do_not_ask_to_change_approved_design(h,code):
    w=h.workflow;w.start();h.check()
    w.approved=dict(design_version=1,blocks=[block()]);w.plan()
    request=deepcopy(w.active);calls=len(h.ports)
    result=handle_whole_plan(request['request']['input'])
    result.update(calculation_status=code,planning_result=None,action_proposals=[],shared_planning_bundle=None,
        stage_errors=[dict(code=code,reason=code,block=None)])
    assert w.receive('a.whole',request['request']['request_id'],result)
    assert w.status=='HOLD' and w.active is None and len(h.ports)==calls


def test_plan_failure_question_keeps_machine_details_in_result_not_speech(h):
    w=h.workflow;w.start();h.check()
    w.approved=dict(design_version=1,blocks=[block()]);w.plan()
    request=deepcopy(w.active)
    result=handle_whole_plan(request['request']['input'])
    result.update(calculation_status='NO_FEASIBLE_ORDER',planning_result=None,action_proposals=[],shared_planning_bundle=None,
        stage_errors=[dict(code='NO_FEASIBLE_ORDER',reason='NO_FEASIBLE_ORDER',block=None)])
    assert w.receive('a.whole',request['request']['request_id'],result)
    assert w.active['request']['calculation_result']==result
    response=c.run_design_change(w.approved,[],reason=w.active['request']['reason'],text_answers=['1번'])
    assert response['hri_result']=='KEEP'
    assert all('NO_FEASIBLE_ORDER' not in q and "'code'" not in q for q in response['questions'])


def test_c_candidate_metadata_is_preserved_for_review(h):
    w=h.workflow;w.start();h.check()
    request=deepcopy(w.active['request'])
    metadata=dict(description='공급판 시험 구조',concept='test')
    design=dict(design_version=1,blocks=[block()])
    assert w.receive('c.initial',request['request_id'],dict(status='OK',hri_result=None,
        design=design,design_metadata=metadata))
    metadata['description']='changed outside workflow'
    assert w.preview_ready(w.candidate['request_id'])
    assert w.active['request']['design_metadata']['description']=='공급판 시험 구조'


def test_plan_failure_uses_pr30_structured_contract_and_keep_holds(h):
    import json
    from pathlib import Path
    w=h.workflow;w.start();h.check();w.approved=dict(design_version=1,blocks=[block()]);w.plan()
    request=deepcopy(w.active['request'])
    result=json.loads((Path(__file__).resolve().parents[2]/'interfaces/fixtures/mvp_a_no_feasible_order.json').read_text())
    result['context']=deepcopy(request['input']['context'])
    assert w.receive('a.whole',request['request_id'],result)
    payload=deepcopy(w.active['request']);failure=payload['planning_failure']
    assert failure['failure_code']=='NO_FEASIBLE_ORDER' and failure['redesign_required'] is True
    response=c.run_design_change(payload['design'],payload['current']['blocks'],
        reason=payload['reason'],planning_failure=failure,text_answers=['유지할래'])
    assert response['status']=='OK' and response['hri_result']=='KEEP'
    assert w.receive('c.plan_failure',payload['request_id'],response)
    assert w.status=='HOLD' and w.active is None
    assert not any(port=='robot.EXECUTE' for port,_ in h.ports)


def test_stop_after_handover_recovery_leaves_confirmed_hold_instead_of_stop_pending(h):
    h.approved(dict(design_version=1,blocks=[block()]))
    w=h.workflow;identity=w.execution_id
    w.robot_event(dict(event='STOP_VERIFIED',data=dict(execution_id=identity,actual_stop_verified=True)))
    w.robot_event(dict(event='EXECUTION_HELD',data=dict(execution_id=identity,status='RECOVERY_REQUIRED',reason='HAND_PRESENT_BEFORE_LOWER',resume_allowed=False)))
    assert w.stop() and w.reason=='STOP_PENDING'
    w.robot_event(dict(event='STOP_VERIFIED',data=dict(execution_id=identity,actual_stop_verified=True,previous_state='RECOVERY_REQUIRED')))
    w.robot_event(dict(event='EXECUTION_HELD',data=dict(execution_id=identity,status='RECOVERY_REQUIRED',reason='RECOVERY_REQUIRED',resume_allowed=False)))
    assert w.status=='HOLD' and w.reason=='RECOVERY_REQUIRED' and w.robot_status=='STOPPED'
    assert w.snapshot()['actions']['resume']['enabled'] is False and not w.resume()


def test_confirmed_pre_descent_handover_hold_enables_resume(h):
    h.approved(dict(design_version=1,blocks=[block()]))
    w=h.workflow;identity=w.execution_id
    w.robot_event(dict(event='STOP_VERIFIED',data=dict(execution_id=identity,actual_stop_verified=True)))
    w.robot_event(dict(event='EXECUTION_HELD',data=dict(execution_id=identity,status='RECOVERY_REQUIRED',reason='HAND_PRESENT_BEFORE_LOWER',resume_allowed=True)))
    assert w.status=='STOPPED' and w.snapshot()['actions']['resume']['enabled'] is True
    assert w.resume() and w.status=='PREPARING' and w.reason=='B_INITIAL_CHECK_PENDING'
