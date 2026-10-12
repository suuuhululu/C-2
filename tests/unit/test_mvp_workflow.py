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
    response=c.run_design_change(dict(design_version=1,blocks=[block()]),[],reason='USER_DESIGN_CHANGE',text_answers=['기존 목표 그대로 갈래'],inspection_context=context)
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
    result=handle_whole_plan(payload['input'])
    assert result['calculation_status']=='NO_FEASIBLE_ORDER'
    w.receive('a.whole',payload['request_id'],result)
    assert w.active['port']=='c.plan_failure' and w.status=='WAIT_INTENT'
    assert not any(p=='robot.EXECUTE' for p,_ in h.ports)


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
