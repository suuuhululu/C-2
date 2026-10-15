"""HMI/process boundaries with explicit device-free child processes."""
from copy import deepcopy
from io import StringIO
import json
import sys

import pytest
from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QApplication

from app import round3_stack_five as stack
from app.round3_stack_hmi import StackFiveWindow
from app.round3_stack_review import HmiProtocol


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp,tmp_path,monkeypatch):
    monkeypatch.setattr(stack,'LAST_PLAN',tmp_path/'test-last-plan.txt')
    w=StackFiveWindow(599221482);w.show();qapp.processEvents()
    yield w
    w.active=False;w.close();qapp.processEvents()


def test_opening_hmi_freezes_same_slots_without_starting_devices_and_new_plan_preserves_old(window,monkeypatch):
    assert window.process.state()==QProcess.NotRunning
    assert not window.buttons['START'].isEnabled() and not window.active
    previous=window.plan_path
    assert len(stack.validate(stack.read(previous)))==5
    assert window.document['press_force_target_n'] is None and window.document['press_force_stop_n']==60.
    assert '반력 60N 정지' in window.supply.text() and '70N 이상 보류' in window.supply.text()
    window.buttons['RESUME'].click()
    assert window.plan_path!=previous and previous.exists()
    assert stack.read(previous)['scenario']==window.document['scenario']
    launches=[]
    monkeypatch.setattr(QProcess,'start',lambda *a:launches.append(a))
    window.ready.setChecked(True);window.buttons['START'].click()
    assert len(launches)==1 and '--hmi-protocol' in launches[0][2]
    assert '--operator-b-review' in launches[0][2]
    window.start_run()
    assert len(launches)==1


def test_failed_b_checkbox_preserves_response_and_requires_each_explicit_approval(window,monkeypatch):
    window.active=True
    responses=[]
    monkeypatch.setattr(QProcess,'write',lambda self,b:responses.append(json.loads(bytes(b))))
    for index in range(2):
        case=window.document['scenario']['steps'][index]
        window.handle_event('STACK_STEP_BEGIN',dict(index=index+1,case=case))
        response=dict(check_id=str(index),check_kind='STEP',step_id=case['step_id'],plan_id='test',
            status='ERROR',comparison=None,current=None,expected=None,difference=None,observation=None,reason='TEST_B_ERROR')
        original=deepcopy(response)
        window.handle_event('STACK_B_RESULT',response)
        window.handle_event('REQUEST',dict(request_id=str(index),kind='B_FAILURE',
            check_kind='STEP',failure=response,target=case['target']))
        assert not window.review_check.isChecked() and not window.continue_button.isEnabled()
        window.reply(True);assert len(responses)==index
        window.review_check.setChecked(True);window.continue_button.click()
        assert responses[-1]==dict(request_id=str(index),approved=True)
        window.handle_event('STACK_OPERATOR_REVIEW',dict(kind='STEP'))
        assert 'ERROR · 수동 진행'==window.layers.item(index,3).text()
        assert response==original and window.current is None


def test_stop_blocks_late_review_and_never_claims_actual_stopped(window,monkeypatch):
    window.active=True
    monkeypatch.setattr(QProcess,'processId',lambda self:0)
    window.request_stop()
    window.handle_event('REQUEST',dict(request_id='late',kind='B_FAILURE'))
    assert window.pending is None and '실제 정지 확인 대기' in window.status.text()
    window.finished(2)
    assert '미확인' in window.status.text()


def test_next_step_updates_expected_prefix_even_when_b_current_stays_empty(window):
    window.active=True
    window.current=dict(current_revision=0,blocks=[])
    cases=window.document['scenario']['steps']
    window.handle_event('STACK_STEP_BEGIN',dict(index=1,case=cases[0]))
    assert window.inspection_view.expected_board.blocks==[cases[0]['target']]
    # Reproduce a B failure followed by operator review, then next Step.
    window.handle_event('STACK_B_RESULT',dict(check_id='synthetic',check_kind='STEP',step_id=cases[0]['step_id'],
        plan_id='test',status='UNOBSERVABLE',comparison='UNOBSERVABLE',current=deepcopy(window.current),
        expected=dict(blocks=[cases[0]['target']]),difference=dict(missing=[],unexpected=[],unobservable=[]),
        observation=None,reason='TEST_ONLY'))
    window.handle_event('REQUEST',dict(request_id='next',kind='STEP_READY',index=1,total=5,case=cases[1]))
    assert window.inspection_view.expected_board.blocks==[c['target'] for c in cases[:2]]
    assert window.current==dict(current_revision=0,blocks=[])
    assert window.inspection_view.current_board.blocks==[]
    assert '계획 기준' in window.inspection_view.board_panels[1].title()


def test_child_protocol_eof_stale_reply_and_explicit_false_never_approve():
    assert not HmiProtocol(StringIO(''),StringIO()).review('INITIAL',{},None)
    source=StringIO();sink=StringIO()
    protocol=HmiProtocol(source,sink)
    def publish(event,data):
        source.write(json.dumps(dict(request_id=data['request_id'],approved=False))+'\n');source.seek(0)
    protocol.publish=publish
    assert protocol.step_ready({},0,5) is False
    protocol.publish=lambda *a:None
    protocol.source=StringIO(json.dumps(dict(request_id='stale',approved=True))+'\n')
    with pytest.raises(ValueError,match='REPLY_MISMATCH'):protocol.review('STEP',{},None)


def test_same_plan_cli_reuse_reports_hold_without_robot_connection(window,monkeypatch,capsys):
    window.plan_path.with_suffix('.claimed.json').write_text('{}')
    monkeypatch.setenv('ROS_DOMAIN_ID','20')
    monkeypatch.setattr(stack,'run_stack',lambda *a,**kw:pytest.fail('used plan must not reach devices'))
    rc=stack.main(['run','--plan',str(window.plan_path),'--execute','--confirm-empty-board',
        '--confirm-empty-gripper','--confirm-home-route-reviewed','--confirm-hand-clear'])
    assert rc==2 and 'PLAN_ALREADY_USED_CREATE_NEW_PREVIEW' in capsys.readouterr().out


def test_actual_subprocess_protocol_updates_hmi_without_devices(window,qapp,tmp_path):
    script=tmp_path/'explicit_mock_child.py'
    script.write_text('''import json,sys
p="C2_STACK_HMI "
request=dict(event="REQUEST",data=dict(request_id="explicit-fixture",kind="B_FAILURE",check_kind="INITIAL",failure=dict(reason="SYNTHETIC_ONLY"),target=None))
print(p+json.dumps(request),flush=True)
reply=json.loads(sys.stdin.readline())
assert reply==dict(request_id="explicit-fixture",approved=True)
print(p+json.dumps(dict(event="STACK_FINISHED",data=dict(status="HOLD",reason="EXPLICIT_DEVICE_FREE_CHILD",output_directory="synthetic"))),flush=True)
''')
    window.active=True
    window.process.setProgram(sys.executable);window.process.setArguments([str(script)])
    window.process.start()
    from PyQt5.QtTest import QTest
    for _ in range(200):
        QTest.qWait(5)
        if window.pending:break
    assert window.pending and not window.continue_button.isEnabled()
    window.review_check.setChecked(True);window.continue_button.click()
    for _ in range(200):
        QTest.qWait(5)
        if not window.active:break
    assert not window.active and window.terminal_result
    assert 'EXPLICIT_DEVICE_FREE_CHILD' in window.notice.toPlainText()


def test_all_five_layer_rows_are_visible_without_scrolling(window,qapp):
    qapp.processEvents()
    last=window.layers.visualItemRect(window.layers.item(4,0))
    assert last.bottom()<window.layers.viewport().height()
