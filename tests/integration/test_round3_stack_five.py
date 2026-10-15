"""Actual B state/comparison; synthetic INITIAL and device transport only."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from app import round3_stack_five as stack


@pytest.fixture
def experiment(tmp_path):
    folder=stack.ROOT/'logs/stack-five-tests'/str(uuid4())
    folder.mkdir(parents=True)
    path=folder/'plan.json'
    doc=stack.freeze(20261015,13,11,stack.PROFILE,path)
    doc['_plan_path']=str(path)
    return folder,doc


def test_twenty_slots_all_sizes_layers_and_randomness_are_bound_without_devices(experiment):
    _,doc=experiment
    first=stack.build(20261015)
    assert first[0]==stack.build(20261015)[0]
    assert first[0]!=stack.build(20261016)[0]
    covered=set()
    for seed in range(40):
        scenario,prepared=stack.build(seed)
        assert len({(c['target']['color'],c['target']['brick_type'],c['supply_slot']) for c in scenario['steps']})==5
        for i,(case,item) in enumerate(zip(scenario['steps'],prepared)):
            block=case['target'];cfg=item['config']
            assert (block['x'],block['y'],block['layer'])==(13,11,i+1)
            assert block['color'] in ('blue','yellow') and block['brick_type'] in ('2x2x1','2x3x1')
            assert cfg['press_control']=='POSITION_DESCENT_REACTION_STOP' and cfg['press_force_target_n'] is None
            assert cfg['press_force_stop_n']==60. and cfg['press_force_abort_n']==70. and cfg['seating_velocity']==cfg['press_velocity']==3.
            assert cfg['seating_force_stop_n']==50.
            assert cfg['release_width_mm']==47. and cfg['release_feedback_range_mm']==[32.,55.]
            if cfg['vision'].get('depth_center_profile'):
                assert cfg['vision']['defer_depth_evidence'] and cfg['vision']['defer_depth_pose_validation']
            assert case['human_hold']==(i>0 and block['brick_type']=='2x3x1' and scenario['steps'][i-1]['target']['brick_type']=='2x2x1')
            covered.add(cfg['educational_supply_binding']['slot_id'])
    assert len(covered)==20 and all(not s.startswith('red_') for s in covered)
    assert len(stack.validate(doc))==5


def fixtures(folder,doc,fault=None):
    launches=[];kinds=[];blocks=[]
    def initial(settings,directory,**kwargs):
        if fault=='initial':return dict(status='HOLD',reason='EXPLICIT_TEST_INITIAL_FAILURE')
        directory.mkdir()
        archive=directory/'capture';archive.mkdir()
        check='synthetic-initial'
        def write(p,x):p.write_text(json.dumps(x))
        write(archive/'context.json',dict(manifest=dict(mode='REAL',check_kind='INITIAL',
            view_order=['V0','D1','D3'],check_id=check,observation_seq=0),calibration=dict(calibration_id=settings['calibration_id'])))
        write(archive/'observed.json',dict(check_id=check,observation_seq=0,status='OK',visible_blocks=[],
            verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in range(1,6)],reason=None))
        for v in ['V0','D1','D3']:
            p=archive/v;p.mkdir()
            write(p/'metadata.json',dict(mode='REAL',view_id=v,check_id=check,observation_seq=0,
                calibration_id=settings['calibration_id'],scene_id='SYNTHETIC_ONLY',captured_at=datetime.now(timezone.utc).isoformat()))
        kwargs['cancelled'].set()  # Reproduce real INITIAL's successful cleanup.
        return dict(status='INITIAL_CAPTURED_HOME_RETURNED',current=dict(current_revision=0,blocks=[]),
            initial_capture_directory=str(archive),home_return_verified=True,actual_stop_verified=True,writer_released=True)
    def execute(item,*args):
        launches.append(item['case']['step_id'])
        blocks.append(deepcopy(item['case']['target']))
        if fault=='native':return dict(status='SEQUENCE_STOPPED')
        return dict(status='THREE_CYCLES_COMPLETED',completed_steps=[launches[-1]],
            home_returns=[dict(stopped_verified=True)] if fault!='native_home' else [])
    class Observer:
        def __init__(self,*args):self.outcomes={}
        def __call__(self,context,active):
            kinds.append(context['check_kind'])
            assert active()
            if fault=='ERROR_HOME':
                self.outcomes[context['check_id']]=dict(home_return_verified=True,actual_stop_verified=True,writer_released=True)
                raise RuntimeError('EXPLICIT_TEST_CAMERA_PROCESSING_FAILURE_AFTER_HOME')
            if fault=='ERROR':raise RuntimeError('EXPLICIT_TEST_CAMERA_FAILURE')
            visible=deepcopy(blocks)
            if fault=='MISMATCH' or fault=='FINAL_MISMATCH' and context['check_kind']=='FINAL':
                visible[-1]['color']='yellow' if visible[-1]['color']=='blue' else 'blue'
            result=dict(check_id=context['check_id'],observation_seq=context['observation_seq'],
                status='OK',visible_blocks=visible,reason=None,
                verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in range(1,6)])
            if fault=='UNOBSERVABLE':result.update(status='UNOBSERVABLE',verified_regions=[],visible_blocks=[],reason='TEST_OCCLUSION')
            self.outcomes[context['check_id']]=dict(home_return_verified=fault!='b_home',
                actual_stop_verified=True,writer_released=fault!='writer')
            return result,dict(provenance='EXPLICIT_SYNTHETIC_CAMERA_FIXTURE')
    return initial,execute,Observer,launches,kinds


@pytest.mark.parametrize('fault',[None,'initial','native','native_home','ERROR','MISMATCH','UNOBSERVABLE','b_home','writer','FINAL_MISMATCH'])
def test_five_b_matches_and_separate_final_or_hold_without_another_pickup(experiment,fault):
    folder,doc=experiment
    initial,execute,observer,launches,kinds=fixtures(folder,doc,fault)
    result=stack.run_stack(doc,folder/'run',stack.load_settings(stack.DEFAULT),Event(),
        initial=initial,execute=execute,observer_factory=observer,confirm_step=lambda *a:True)
    if fault is None:
        assert result['status']=='FIVE_STEPS_AND_FINAL_MATCH'
        assert launches==[f'STACK{i:02d}' for i in range(1,6)]
        assert result['native_completed']==result['b_confirmed']==launches
        assert len(result['current']['blocks'])==5 and result['physical_completion']
        assert kinds==['STEP']*5+['FINAL']
    else:
        assert result['status']=='HOLD' and not result['physical_completion']
        assert len(launches)==(0 if fault=='initial' else 5 if fault=='FINAL_MISMATCH' else 1)
        if fault in ('initial','native','native_home'):assert kinds==[]


def test_changed_frozen_plan_and_cancelled_confirmation_do_not_move(experiment):
    folder,doc=experiment
    changed=deepcopy(doc);changed['scenario']['steps'][0]['supply_slot']=5
    with pytest.raises(ValueError,match='PLAN_OR_CONFIG_CHANGED'):stack.validate(changed)
    initial,execute,observer,launches,kinds=fixtures(folder,doc)
    result=stack.run_stack(doc,folder/'run',stack.load_settings(stack.DEFAULT),Event(),
        initial=initial,execute=execute,observer_factory=observer,confirm_step=lambda *a:False)
    assert result['status']=='HOLD' and not launches and not kinds


@pytest.mark.parametrize('unknown_at_target',[False,True])
def test_saved_initial_unverified_columns_survive_new_b_connection(experiment,unknown_at_target):
    folder,doc=experiment
    initial,execute,observer,launches,kinds=fixtures(folder,doc)
    def partial_initial(*args,**kwargs):
        result=initial(*args,**kwargs)
        path=Path(result['initial_capture_directory'])/'observed.json'
        observed=json.loads(path.read_text())
        x,y=(13,11) if unknown_at_target else (0,0)
        observed['verified_regions']=[dict(x=xx,y=yy,width=1,height=1,layer=layer)
            for yy in range(24) for xx in range(24) for layer in range(1,6)
            if (xx,yy,layer)!=(x,y,5)]
        path.write_text(json.dumps(observed))
        return result
    result=stack.run_stack(doc,folder/'run',stack.load_settings(stack.DEFAULT),Event(),
        initial=partial_initial,execute=execute,observer_factory=observer,confirm_step=lambda *a:True)
    if unknown_at_target:
        assert result['status']=='HOLD' and 'PLAN_REGION_UNVERIFIED' in result['reason']
        assert not launches and not kinds
    else:
        assert result['status']=='FIVE_STEPS_AND_FINAL_MATCH' and len(launches)==5


def test_run_without_all_physical_confirmations_never_starts_initial(monkeypatch):
    monkeypatch.setattr(stack,'run_stack',lambda *a,**kw:pytest.fail('must not reach devices'))
    with pytest.raises(SystemExit) as e:stack.main(['run','--execute'])
    assert e.value.code==2


@pytest.mark.parametrize('case',['normal','below_60','max_travel','no_P','stopped'])
def test_native_completion_after_press_needs_no_extra_60n_certificate(experiment,monkeypatch,case):
    from contextlib import contextmanager
    from types import SimpleNamespace
    folder,doc=experiment
    item=stack.validate(doc)[0]
    result=dict(status='CYCLE_COMPLETED',released=True,press_done=True,
        press_result=dict(status='FORCE_THRESHOLD_REACHED_STOP_VERIFIED'))
    if case=='below_60':result['press_result']=dict(threshold_force_norm_n=48.)
    if case=='max_travel':result['press_result']=dict(status='MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD')
    if case=='no_P':result['press_done']=False
    if case=='stopped':result['status']='STOPPED_BY_OPERATOR'
    raw=SimpleNamespace(config=dict(timing={}),stop=lambda:None)
    @contextmanager
    def opened(*args):
        yield SimpleNamespace(raw=raw,confirm=lambda *a,**kw:None)
    monkeypatch.setattr(stack,'open_motion',opened)
    trial=stack.native()
    monkeypatch.setattr(trial.held,'observe',lambda *a,**kw:result)
    monkeypatch.setattr(trial.held,'transfer',lambda *a,**kw:None)
    monkeypatch.setattr(trial.supply,'execute',lambda *a,**kw:None)
    homes=[]
    def home(*args):
        homes.append(True)
        return dict(stopped_verified=True)
    monkeypatch.setattr(trial,'trial_return_home',home)
    vision=SimpleNamespace(display=lambda *a:None,observe=lambda *a:None,
        pump_sleep=lambda *a:None,close=lambda:None,finalize_depth=lambda *a:None)
    sequence=trial.run_sequence
    monkeypatch.setattr(trial,'run_sequence',lambda *a,**kw:sequence(*a,**kw,vision_factory=lambda *a:vision))
    receipt=stack.execute_step(item,folder/'native',lambda *a:None,{},'review',Event())
    if case in ('no_P','stopped'):
        assert receipt['status']=='SEQUENCE_STOPPED' and not homes
    else:
        assert receipt['status']=='THREE_CYCLES_COMPLETED' and homes==[True]


def test_native_failure_keeps_original_reason_when_cleanup_stop_also_fails(experiment,monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    folder,doc=experiment
    item=stack.validate(doc)[0]
    events=[]
    def stop():raise RuntimeError('SERVICE_FAILED: motion/move_stop')
    raw=SimpleNamespace(config=dict(timing={}),stop=stop)
    @contextmanager
    def opened(*args):
        yield SimpleNamespace(raw=raw,confirm=lambda *a,**kw:None)
    monkeypatch.setattr(stack,'open_motion',opened)
    def failure(*args,**kwargs):raise RuntimeError('ROBOT_OR_GRIP_NOT_READY')
    monkeypatch.setattr(stack.native(),'run_sequence',failure)
    with pytest.raises(RuntimeError,match='^ROBOT_OR_GRIP_NOT_READY$'):
        stack.execute_step(item,folder/'native',lambda e,d:events.append((e,d)),{},'review',Event())
    assert events==[('STOP_FAILED',dict(original_reason='ROBOT_OR_GRIP_NOT_READY',
        stop_reason='SERVICE_FAILED: motion/move_stop',actual_stop_verified=False))]


def coverage_failure():
    return dict(status='HOLD',current=None,home_return_verified=False,
        actual_stop_verified=True,writer_released=True,
        reason='PROCESSING_FAILED: INITIAL_STATE_UNAVAILABLE: no confirmed Current; initial_scope_unverified')


def test_initial_checkbox_keeps_failed_b_initial_and_uses_labelled_operator_test_baseline(experiment):
    folder,doc=experiment
    _,execute,observer,launches,kinds=fixtures(folder,doc)
    first=coverage_failure()
    calls=[]
    def review(kind,failure,target):
        assert kind=='INITIAL' and failure==first and target is None
        calls.append('checkbox')
        return True
    def home(*a):
        calls.append('home')
        return dict(home_return_verified=True,actual_stop_verified=True,writer_released=True)
    result=stack.run_stack(doc,folder/'run',stack.load_settings(stack.DEFAULT),Event(),
        initial=lambda *a,**kw:deepcopy(first),execute=execute,observer_factory=observer,
        confirm_step=lambda *a:True,review_failure=review,recover_home=home)
    assert calls==['checkbox','home'] and len(launches)==5 and kinds==['STEP']*5+['FINAL']
    assert result['status']=='FIVE_STEPS_EXECUTED_WITH_OPERATOR_REVIEW'
    assert not result['initial_b_confirmed'] and result['final_b_confirmed'] and not result['physical_completion']
    assert stack.read(folder/'run/initial-attempt.json')==first
    assert result['operator_reviews'][0]['original_failure']==first
    assert stack.read(folder/'run/test-plan.json')['baseline_basis']=='OPERATOR_VISUAL_EMPTY_BOARD_TEST_ONLY'


@pytest.mark.parametrize('fault',['MISMATCH','UNOBSERVABLE','ERROR_HOME'])
def test_each_layer_failure_needs_review_and_preserves_b_current_and_final_gate(experiment,fault):
    folder,doc=experiment
    initial,execute,observer,launches,kinds=fixtures(folder,doc,fault)
    reviewed=[]
    def review(kind,response,target):
        assert kind=='STEP' and response['comparison']!='MATCH'
        reviewed.append(deepcopy(response))
        assert target['layer']==len(reviewed)
        return True
    result=stack.run_stack(doc,folder/'run',stack.load_settings(stack.DEFAULT),Event(),
        initial=initial,execute=execute,observer_factory=observer,confirm_step=lambda *a:True,review_failure=review)
    assert len(launches)==len(reviewed)==len(result['operator_reviews'])==5
    assert kinds==['STEP']*5 and result['b_confirmed']==[]
    assert result['status']=='FIVE_STEPS_EXECUTED_WITH_OPERATOR_REVIEW'
    assert not result['physical_completion'] and not result['final_b_confirmed']
    assert 'FINAL_REQUIRES_ALL_STEP_MATCH' in result['reason']
    for response in reviewed:
        assert stack.read(folder/'run'/(response['check_id']+'.response.json'))==response
    if reviewed[-1]['current'] is not None:
        assert result['current']==reviewed[-1]['current']
    else:
        assert result['current']==dict(current_revision=0,blocks=[])


@pytest.mark.parametrize('case',['decline_initial','cancel_initial','home_failure','decline_step','cancel_step','b_home','writer','stop_failure'])
def test_review_never_bypasses_cancel_or_physical_home_stop_writer_failure(experiment,case):
    folder,doc=experiment
    initial,execute,observer,launches,kinds=fixtures(folder,doc,
        case if case in ('b_home','writer') else 'MISMATCH' if case in ('decline_step','cancel_step') else None)
    token=Event();reviews=[];homes=[]
    if case in ('decline_initial','cancel_initial','home_failure','stop_failure'):
        failed=coverage_failure()
        if case=='stop_failure':failed['actual_stop_verified']=False
        initial=lambda *a,**kw:failed
    def review(*args):
        reviews.append(args[0])
        if case in ('cancel_initial','cancel_step'):token.set()
        return not case.startswith('decline')
    def home(*args):
        homes.append(True)
        return dict(home_return_verified=False,actual_stop_verified=True,writer_released=True)
    result=stack.run_stack(doc,folder/'run',stack.load_settings(stack.DEFAULT),token,
        initial=initial,execute=execute,observer_factory=observer,confirm_step=lambda *a:True,
        review_failure=review,recover_home=home)
    assert result['status']=='HOLD' and not result['physical_completion']
    assert len(launches)==(1 if case in ('decline_step','cancel_step','b_home','writer') else 0)
    if case in ('b_home','writer','stop_failure'):assert reviews==[]
    assert homes==([True] if case=='home_failure' else [])


@pytest.mark.parametrize('checked,accepted',[(False,True),(True,True),(True,False)])
def test_checkbox_is_unchecked_and_continue_disabled_until_operator_checks(monkeypatch,checked,accepted):
    from PyQt5.QtWidgets import QApplication,QCheckBox,QDialog,QPushButton
    from app.round3_stack_review import review_checkbox
    app=QApplication.instance() or QApplication([])
    def dialog(self):
        checkbox=self.findChild(QCheckBox,'operator_b_failure_review')
        button=self.findChild(QPushButton,'continue_after_b_failure')
        assert not checkbox.isChecked() and not button.isEnabled()
        checkbox.setChecked(checked)
        assert button.isEnabled()==checked
        return QDialog.Accepted if accepted else QDialog.Rejected
    monkeypatch.setattr(QDialog,'exec_',dialog)
    assert review_checkbox('INITIAL',coverage_failure())==(checked and accepted)


@pytest.mark.parametrize('stopped',[True,False])
def test_reviewed_initial_home_needs_actual_stopped_feedback_before_writer_handoff(monkeypatch,stopped):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app import round3_stack_review as review
    calls=[]
    def confirm(check,view,settings,reference):
        calls.append(view)
        assert settings['route_reviewed'] and reference=='review'
        return dict(stopped_verified=stopped)
    @contextmanager
    def opened(settings,cancelled):
        try:yield SimpleNamespace(confirm=confirm)
        finally:calls.append('writer_released')
    monkeypatch.setattr(review,'open_motion',opened)
    if stopped:
        result=review.recover_initial_home({},'review',Event(),lambda *a:None)
        assert all(result[k] for k in ('home_return_verified','actual_stop_verified','writer_released'))
    else:
        with pytest.raises(RuntimeError,match='HOME_NOT_VERIFIED'):
            review.recover_initial_home({},'review',Event(),lambda *a:None)
    assert calls==['HOME','writer_released']


@pytest.mark.parametrize('fault',[None,'MISMATCH'])
def test_runtime_events_reach_existing_hmi_with_real_b_results_and_separate_manual_progress(experiment,monkeypatch,fault):
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QProcess
    from app.round3_stack_hmi import StackFiveWindow
    app=QApplication.instance() or QApplication([])
    folder,doc=experiment
    monkeypatch.setattr(stack,'LAST_PLAN',folder/'test-last-plan.txt')
    window=StackFiveWindow(doc['seed']);window.active=True
    initial,execute,observer,launches,kinds=fixtures(folder,doc,fault)
    replies=[]
    monkeypatch.setattr(QProcess,'write',lambda self,b:replies.append(json.loads(bytes(b))))
    def review(kind,response,target):
        identity=response['check_id']
        window.handle_event('REQUEST',dict(request_id=identity,kind='B_FAILURE',
            check_kind=kind,failure=response,target=target))
        assert not window.review_check.isChecked()
        window.review_check.setChecked(True);window.reply(True)
        return replies[-1]['request_id']==identity and replies[-1]['approved']
    try:
        result=stack.run_stack(doc,folder/'run',stack.load_settings(stack.DEFAULT),Event(),
            initial=initial,execute=execute,observer_factory=observer,confirm_step=lambda *a:True,
            review_failure=review,on_event=window.handle_event)
        assert len(launches)==5 and window.current==result['current']
        assert 'D 완료 5 / 5 Step' in window.progress.text()
        assert all(window.layers.item(i,2).text()=='완료' for i in range(5))
        assert all(window.layers.item(i,3).text()==('MATCH' if fault is None else 'MISMATCH · 수동 진행') for i in range(5))
        assert window.terminal_result and window.inspection_view.current_board.blocks==result['current']['blocks']
        assert result['physical_completion']==(fault is None)
    finally:
        window.active=False;window.close()
