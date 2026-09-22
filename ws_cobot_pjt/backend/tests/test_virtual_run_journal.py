import json
import pytest
from c2_process.virtual_cell import VirtualRunJournal
from c2_process.robot_adapter import MockRobotAdapter, StepResult

@pytest.mark.parametrize('outcome',['SUCCEEDED','FAILED','STOPPED'])
def test_run_log_saved_before_shutdown_and_excludes_previous_calls(tmp_path,outcome):
    adapter=MockRobotAdapter();adapter.calls.append({'fn':'old'})
    journal=VirtualRunJournal(tmp_path/'execution.sqlite3',adapter,'normal')
    identity=('run-1','SIMULATION','path-1',1,'hash')
    assert journal.reserve('request-1',identity) is None
    adapter.calls.append({'fn':'move'})
    result=StepResult(outcome,'NONE','done','execute_path',{'plan_signature':'signature'})
    journal.finish('request-1',result)
    records=list(tmp_path.glob('motion-*.json'));assert len(records)==1
    data=json.loads(records[0].read_text())
    assert data['calls']==[{'fn':'move'}]
    assert data['run_id']=='run-1' and data['outcome']==outcome
    assert data['observed_state']['plan_signature']=='signature'
    assert journal.reserve('request-1',identity).outcome==outcome
    assert not journal.active
