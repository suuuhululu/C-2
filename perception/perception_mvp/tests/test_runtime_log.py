import json
from pathlib import Path
from queue import Queue
import pytest
from perception_mvp.runtime_log import progress
from perception_mvp.runtime_log import periodic_progress
from threading import Event
from perception_mvp.replay_inspection import make_sample_observer
from perception_mvp.team_connection import connect_inspection
from perception_mvp.main import run_observation_cycle


def test_progress_is_immediate_single_line_with_identity(monkeypatch):
    calls = []
    monkeypatch.setattr('builtins.print', lambda *args, **kw: calls.append((args, kw)))
    progress({'check_id': 'req', 'check_kind': 'STEP'}, '이동 요청·도착 대기', view='D1', reason='line1\nline2')
    text = calls[0][0][0]
    assert '이동 요청·도착 대기' in text and 'D1' in text and 'req' in text
    assert '\n' not in text and calls[0][1]['flush'] is True


def test_connection_logs_start_result_delivery_without_changing_result(capsys):
    sample = json.loads(Path(__file__).resolve().parents[2].joinpath('samples/inspection_replay/sample.json').read_text())
    inbox = Queue()
    connection = connect_inspection(inbox.put,
        observe=make_sample_observer(sample, scenario_name='normal-and-failure'),
        geometry_reference=sample['geometry_reference'])
    try:
        connection.request(sample['scenarios'][0]['actions'][0]['request'])
        result = inbox.get(timeout=5)
        connection._queue.join()
        assert result['status'] == 'OK' and result['check_id'] == 'initial'
        output = capsys.readouterr().out
        assert '검사 시작' in output and '검사 결과' in output and '결과 전달 완료·검사 종료' in output
    finally:
        connection.close()


def test_stop_confirmation_failure_logs_wait_and_failure_not_false_stop(capsys):
    class Gate:
        state = None
    gate = Gate()
    context = dict(mode='REAL', view_order=['V0'], check_id='fail',
                   observation_seq=0, check_kind='INITIAL')
    with pytest.raises(RuntimeError, match='stopped'):
        run_observation_cycle(gate, None, None, None, context, None, {}, {}, .25,
            callback=lambda v: None, confirm_view=lambda v: False,
            workflow_valid=lambda: True, bundle_valid=lambda: True)
    output = capsys.readouterr().out
    assert '이동 요청·도착 대기' in output and '관측 시작 실패·중단' in output
    assert '정지 확인' not in output and gate.state == 'HOLD'


def test_periodic_status_reports_latest_stage_and_stops_after_exit(monkeypatch):
    calls, reported = [], Event()
    def output(*args, **kwargs):
        calls.append(args[0])
        if '진행 중' in args[0]:
            reported.set()
    monkeypatch.setattr('builtins.print', output)
    with periodic_progress({'check_id': 'check'}, lambda: True, interval=.02):
        progress({'check_id': 'check'}, '이동 요청·도착 대기', view='D3')
        assert reported.wait(1.)
    heartbeat = [value for value in calls if '진행 중' in value]
    assert heartbeat and 'D3' in heartbeat[0] and '이동 요청·도착 대기' in heartbeat[0]
    assert 'elapsed_seconds' in heartbeat[0] and 'stage_seconds' in heartbeat[0]
    size = len(calls)
    assert not Event().wait(.05)
    assert len(calls) == size


def test_periodic_status_stops_on_cancel_and_exception(monkeypatch):
    calls = []
    monkeypatch.setattr('builtins.print', lambda *args, **kwargs: calls.append(args[0]))
    with periodic_progress({'check_id': 'cancel'}, lambda: False, interval=.01):
        Event().wait(.03)
    assert not calls
    with pytest.raises(ValueError):
        with periodic_progress({'check_id': 'error'}, lambda: True, interval=.01):
            raise ValueError('failure')
    Event().wait(.03)
    assert not calls
