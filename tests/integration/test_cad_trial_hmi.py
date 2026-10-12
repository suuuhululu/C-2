import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from PyQt5.QtWidgets import QApplication, QTabWidget, QScrollArea

from app.cad_trial_hmi import TrialWindow

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),
    reason='C2_ROBOT_ROOT required')


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def window(tmp_path, execute=False, gestures=False):
    return TrialWindow(SimpleNamespace(robot_root=ROOT, log_directory=tmp_path, execute=execute,
        voice=False, design=Path('interfaces/fixtures/cad_trial_yellow_blue_stack.json'),start_zone='assembly',gestures=gestures))


@pytest.mark.parametrize('gestures',[False,True])
def test_one_page_shows_design_candidates_stop_without_device(qapp,tmp_path,gestures):
    w=window(tmp_path,gestures=gestures);w.show();qapp.processEvents()
    assert len(w.target.blocks)==2 and w.prefix.blocks==[]
    assert w.trial.robot is None
    assert w.findChildren(QTabWidget)==[] and w.findChildren(QScrollArea)==[]
    assert 'C 승인 후 A 계획·경로 계산' in w.details.toPlainText()
    assert '픽업 TCP' not in w.details.toPlainText()
    assert w.trial.prepared is None
    for widget in (w.target,w.prefix,w.reviewed,w.answer,w.submit,w.align,w.resume_button,w.footer):
        assert widget.isVisible()
        point=widget.mapTo(w,widget.rect().bottomRight())
        assert point.x()<w.width() and point.y()<w.height()
    out=Path('logs/cad-trial-20261012');out.mkdir(parents=True,exist_ok=True)
    assert w.grab().save(str(out/'cad-preparation-screen.png'))
    w.close()


def test_long_failure_wraps_without_growing_window_or_listing_blocks(qapp,tmp_path):
    w=window(tmp_path,gestures=True);w.show();qapp.processEvents()
    size=w.size()
    rejected=dict(brick_type='2x2x1',color='yellow',x=11,y=11,layer=2,orientation_deg=0)
    error=dict(code='DESIGN_GENERATION_FAILED',message='no valid design within the attempt limit',
        details=[dict(rule='support',message='block support studs=0 < 2',blocks=[rejected]*40)]*300)
    w.inbox.put(('C_CANDIDATE',dict(status='FAILED',error=error)));w.poll();qapp.processEvents()
    assert w.size()==size and w.status.wordWrap()
    assert '아래층 지지 부족' in w.status.text()
    assert '300건' in w.details.toPlainText()
    assert 'brick_type' not in w.details.toPlainText()
    w.inbox.put(('QUESTION',dict(text='줄바꿈없는긴오류'*10000)));w.poll();qapp.processEvents()
    assert w.size()==size and len(w.status.text())<=400
    for widget in (w.status,w.target,w.prefix,w.align,w.resume_button,w.footer):
        point=widget.mapTo(w,widget.rect().bottomRight())
        assert point.x()<w.width() and point.y()<w.height()
    w.inbox.put(('C_CANDIDATE',dict(status='FAILED',error=error)));w.poll();qapp.processEvents()
    out=Path('logs/cad-trial-20261012');out.mkdir(parents=True,exist_ok=True)
    assert w.grab().save(str(out/'cad-failure-bounded-screen.png'))
    assert w.trial.robot is None
    w.close()


def test_events_yield_to_ui_and_history_stays_bounded(qapp,tmp_path):
    w=window(tmp_path)
    for _ in range(1000):
        w.inbox.put(('C_PROGRESS',dict(stage='DESIGN_ATTEMPT',message='생성 중 '*1000)))
    w.poll()
    assert not w.inbox.empty()  # 남은 이벤트는 다음 Qt 타이머 주기에 처리한다.
    while not w.inbox.empty():
        w.poll()
    assert w.details.document().blockCount()<=200
    assert len(w.details.toPlainText())<125000
    w.close()


def test_initial_c_failure_saves_full_reason_and_progress_and_allows_retry(qapp,tmp_path,monkeypatch):
    import json
    import app.cad_trial_hmi as module
    failed=dict(status='FAILED',error=dict(code='DESIGN_GENERATION_FAILED',
        message='no valid design within the attempt limit',
        details=[dict(rule='connectivity',message='multiple disconnected components',
                      blocks=[dict(color='yellow')]*40)]))
    def generate(**kw):
        kw['on_question']('어떤 설계를 만들까요?')
        kw['on_progress'](dict(stage='DESIGN_ATTEMPT',message='attempt 1'))
        return failed
    monkeypatch.setattr(module,'create_initial_design',generate)
    w=TrialWindow(SimpleNamespace(robot_root=ROOT,log_directory=tmp_path,execute=False,
        voice=True,design=None,start_zone='assembly',gestures=False))
    w.initial_voice();w.worker.join(timeout=2);w.poll()
    assert not w.worker.is_alive()
    assert json.loads((w.trial.directory/'c-initial.json').read_text())==failed
    events=[json.loads(line) for line in (w.trial.directory/'c-events.jsonl').read_text().splitlines()]
    assert len(events)==3
    assert not (w.trial.directory/'events.jsonl').exists()
    assert '하나의 구조로 연결되지 않음' in w.details.toPlainText()
    assert w.voice.isEnabled() and not w.submit.isEnabled()
    assert w.trial.prepared is None and w.trial.robot is None
    w.close()


def test_real_execution_requires_actual_preparation_review(qapp,tmp_path):
    w=window(tmp_path,execute=True);w.answer.setText('좋아요');w.review()
    assert w.worker is None and w.trial.robot is None
    assert '시험 준비' in w.status.text()
    w.close()


def test_c_approval_in_prepare_mode_runs_a_without_robot(qapp,tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    w=window(tmp_path);w.answer.setText('좋아요');w.review()
    deadline=time.monotonic()+5
    while w.worker.is_alive() and time.monotonic()<deadline:
        qapp.processEvents();time.sleep(.01)
    w.poll()
    assert not w.worker.is_alive()
    assert w.used and w.trial.result['status']=='PREPARED_NO_DEVICE_CONNECTION'
    assert w.trial.robot is None
    w.close()


def test_alignment_button_only_responds_to_active_d_request(qapp,tmp_path,monkeypatch):
    w=window(tmp_path)
    calls=[];monkeypatch.setattr(w.trial,'alignment',calls.append)
    w.confirm_alignment();assert calls==[]
    w.inbox.put(('SIGNAL_REQUEST',dict(kind='ALIGNMENT_READY',request_id='active')));w.poll()
    assert w.align.isEnabled()
    w.confirm_alignment();assert calls==['active'] and not w.align.isEnabled()
    w.inbox.put(('SIGNAL_REQUEST_CLOSED',dict(request_id='active')));w.poll()
    assert w.alignment_request is None
    w.close()


def test_resume_button_keeps_approval_and_only_sends_resume_for_active_pause(qapp,tmp_path,monkeypatch):
    w=window(tmp_path,execute=True);w.used=True;calls=[]
    monkeypatch.setattr(w.trial,'resume',lambda:calls.append('RESUME'))
    monkeypatch.setattr(w,'review',lambda:pytest.fail('C approval repeated'))
    assert not w.resume_button.isEnabled()
    w.resume();assert calls==[]
    w.trial.paused=True
    w.inbox.put(('TRIAL_PAUSED',dict(reason='STOP_REQUESTED',resume_allowed=True)));w.poll()
    assert w.resume_button.isEnabled()
    w.resume_button.click()
    assert calls==['RESUME'] and w.used and not w.resume_button.isEnabled()
    w.inbox.put(('TRIAL_RESULT',dict(status='HOLD',reason='RECOVERY_REQUIRED')));w.poll()
    assert not w.resume_button.isEnabled()
    w.close()


def test_start_retry_uses_saved_c_approval_without_llm_or_review(qapp,tmp_path,monkeypatch):
    import app.cad_trial_hmi as module
    saved=dict(status='OK',hri_result='APPROVE',design=module.read('interfaces/fixtures/cad_trial_yellow_blue_five_layers.json'))
    args=SimpleNamespace(robot_root=ROOT,log_directory=tmp_path,execute=False,voice=False,
        design=None,start_zone='assembly',approved_review=saved,retry_start_directory=tmp_path/'old',llm_context=True)
    monkeypatch.setattr(module,'review_design_candidate',lambda *a,**k:pytest.fail('C approval repeated'))
    monkeypatch.setattr(module.llm,'describe_initial_design',lambda *a,**k:pytest.fail('LLM repeated'))
    w=TrialWindow(args)
    assert w.candidate==saved['design'] and not w.answer.isEnabled()
    w.review()
    deadline=time.monotonic()+5
    while w.worker.is_alive() and time.monotonic()<deadline:
        qapp.processEvents();time.sleep(.01)
    w.poll()
    assert w.used and w.trial.result['status']=='PREPARED_NO_DEVICE_CONNECTION'
    assert w.trial.robot is None
    w.close()


def test_free_c_design_is_passed_unchanged_to_a_preparation_with_gesture_mode(qapp,tmp_path,monkeypatch):
    import app.cad_trial_hmi as module
    value=dict(design_version=1,blocks=[dict(brick_type=kind,color=color,x=11,y=11,layer=layer,orientation_deg=0)
        for layer,(kind,color) in enumerate([('2x3x1','yellow'),('2x2x1','blue'),('1x2x1','red')],1)])
    args=SimpleNamespace(robot_root=ROOT,log_directory=tmp_path,execute=False,voice=True,
        design=None,start_zone='assembly',gestures=True)
    monkeypatch.setattr(module,'create_initial_design',lambda **k:dict(status='OK',design=value))
    reviewed=[]
    def approve(design,**kw):
        reviewed.append(design);return dict(status='OK',hri_result='APPROVE',design=design)
    monkeypatch.setattr(module,'review_design_candidate',approve)
    w=TrialWindow(args);w.initial_voice()
    def finish():
        deadline=time.monotonic()+5
        while w.worker.is_alive() and time.monotonic()<deadline:
            qapp.processEvents();time.sleep(.01)
        w.poll();assert not w.worker.is_alive()
    finish();assert w.candidate==value
    w.review();finish()
    assert reviewed==[value] and w.trial.prepared['design']==value
    assert [r['step']['after']['brick_type'] for r in w.trial.prepared['preview']]==['2x3x1','2x2x1','1x2x1']
    assert w.trial.gestures and w.trial.robot is None
    w.close()


@pytest.mark.parametrize('failed', [False,True])
def test_fixed_five_layer_design_reaches_llm_before_a_or_device(qapp,tmp_path,monkeypatch,failed):
    import json
    from app.cad_trial_hmi import llm
    monkeypatch.setenv('C_DESIGN_USE_LLM','1')
    calls=[]
    def fake_llm(system_prompt,user_message,should_stop,model=None):
        calls.append(json.loads(user_message.split('\n',1)[1]))
        return dict(llm_error='UNIT_FAILURE') if failed else dict(design_summary='노랑과 파랑 5층 기둥')
    monkeypatch.setattr(llm,'_json_call',fake_llm)
    w=TrialWindow(SimpleNamespace(robot_root=ROOT,log_directory=tmp_path,execute=False,voice=False,
        llm_context=True,design=Path('interfaces/fixtures/cad_trial_yellow_blue_five_layers.json'),start_zone='assembly'))
    w.answer.setText('좋아요');w.review()
    deadline=time.monotonic()+8
    while w.worker.is_alive() and time.monotonic()<deadline:
        qapp.processEvents();time.sleep(.01)
    w.poll()
    assert not w.worker.is_alive()
    assert calls[0]['design']==w.candidate
    assert len(calls[0]['design']['blocks'])==5
    assert w.trial.robot is None
    if failed:
        assert w.trial.result['status']=='PREPARING' and w.trial.prepared is None
        assert not (w.trial.directory/'c-review.json').exists()
        assert 'LLM 설계 전달 실패' in w.status.text()
    else:
        assert w.trial.result['status']=='PREPARED_NO_DEVICE_CONNECTION'
        assert w.used
    assert json.loads((w.trial.directory/'llm-input-design.json').read_text())==w.candidate
    w.close()
