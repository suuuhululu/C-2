import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from app.robot_process import RobotProcess


ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),
                            reason='set C2_ROBOT_ROOT to integrated robot source')


def document():
    result=subprocess.run([sys.executable,'-c',
        'import json;from scripts.robot_integration_fixture import document;print(json.dumps(document()))'],
        cwd=ROOT,text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


def until(process, event, timeout=15):
    deadline=time.monotonic()+timeout; found=[]
    while time.monotonic()<deadline:
        row=process.receive(timeout=max(.1,deadline-time.monotonic()));found.append(row)
        assert row['event'] not in ('CHANNEL_ERROR','COMMAND_REJECTED'),row
        if row['event']==event:return row,found
    raise AssertionError((event,found))


def test_stdio_real_functions_and_b_gate_with_no_robot_connection():
    d=document()
    with RobotProcess(ROOT) as process:
        assert until(process,'PROCESS_READY')[0]['data']['mode']=='MOCK'
        process.send('EXECUTE',document=d)
        _,rows=until(process,'INSPECTION_REQUIRED')
        assert any(r['event']=='CONTACT_SUCCEEDED' for r in rows)
        process.send('EXECUTE',document=d)
        assert process.receive()['event']=='COMMAND_REJECTED'
        process.send('INSPECTION',result=dict(plan_id=d['step']['plan_id'],step_id='S01',
            execution_id=d['session']['execution_id'],decision='KEEP',
            current=dict(current_revision=1,blocks=[d['step']['block']])))
        assert until(process,'B_DECISION')[0]['data']['next_step_allowed'] is True
    assert process.process.returncode==0


def test_stop_command_is_read_during_worker_execution():
    d=document()
    with RobotProcess(ROOT) as process:
        until(process,'PROCESS_READY');process.send('EXECUTE',document=d)
        until(process,'EXECUTION_STARTED')
        process.send('STOP')
        ack,_=until(process,'STOP_ACCEPTED')
        assert ack['data']['actual_stop_verified'] is False
        proof,_=until(process,'STOP_VERIFIED')
        assert proof['data']['actual_stop_verified'] is True
        held,_=until(process,'EXECUTION_HELD')
        assert held['data']['status']=='STOPPED'
    assert process.process.returncode==0


def test_real_mode_rejects_fake_inputs_before_hardware_imports():
    d=document()
    completed=subprocess.run([sys.executable,'-m','scripts.robot_integration_runtime','--mode','REAL'],
        cwd=ROOT,input=json.dumps(dict(command='EXECUTE',document=d))+'\n'+json.dumps(dict(command='CLOSE'))+'\n',
        capture_output=True,text=True,timeout=5,check=True)
    replies=[json.loads(line) for line in completed.stdout.splitlines()]
    assert replies[-1]['event']=='COMMAND_REJECTED'
    assert not any(r['event']=='EXECUTION_STARTED' for r in replies)
    assert not completed.stderr


@pytest.mark.parametrize('mode,command,reason', [('MOCK','READ_STATE','REAL_READ_STATE_REQUIRED'),
    ('MOCK','ALIGNMENT_CONFIRM','NO_OPERATOR_ALIGNMENT_PENDING'),
    ('REAL','READ_STATE','REAL_CONFIG_REQUIRED')])
def test_read_and_alignment_commands_do_not_infer_device_permission(mode,command,reason):
    completed=subprocess.run([sys.executable,'-m','scripts.robot_integration_runtime','--mode',mode],
        cwd=ROOT,input=json.dumps(dict(command=command))+'\n'+json.dumps(dict(command='CLOSE'))+'\n',
        capture_output=True,text=True,timeout=5,check=True)
    replies=[json.loads(line) for line in completed.stdout.splitlines()]
    assert replies[0]['data']['device_connections']==0
    assert replies[-1]['event']=='COMMAND_REJECTED'
    assert replies[-1]['data']['reason']==reason
    assert not any(r['event'] in ('EXECUTION_STARTED','STATE_SNAPSHOT') for r in replies)
    assert not completed.stderr
