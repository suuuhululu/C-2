"""새 Robot 프로세스를 FAKE 입력으로 실행한다. 장치/Camera/LLM/DB 호출 없음."""
import argparse
from copy import deepcopy
import json
import queue
from pathlib import Path
import subprocess
import sys
import time

from app.robot_process import RobotProcess


def run(robot_root, scenario, output):
    source = ('from scripts.robot_integration_fixture import document;import json;'
              +('d=document()' if scenario=='robot' else "d=document(mode='HUMAN_ASSEMBLY',assistance='MANUAL_ASSEMBLY')")
              +';print(json.dumps(d))')
    result=subprocess.run([sys.executable,'-c',source],cwd=robot_root,capture_output=True,text=True,check=True)
    document=json.loads(result.stdout); events=[]; begin=time.monotonic()
    with RobotProcess(robot_root,mode='MOCK') as robot:
        robot.send('EXECUTE',document=document)
        active=None; sent_stop=False; inspection_sent=False; sequence=0; next_signal=0.
        while time.monotonic()-begin<40:
            try: row=robot.receive(timeout=.1)
            except queue.Empty:
                row=None
            if row:
                events.append(deepcopy(row))
                if row['event']=='COMMAND_REJECTED':
                    # A last in-flight camera frame may arrive after a request closes.
                    # Verify the stale boundary instead of treating that frame as a Robot failure.
                    if row['data']['reason'] not in ('NO_ACTIVE_SIGNAL_REQUEST','STALE_SIGNAL'):
                        raise RuntimeError(row)
                    active=None
                if row['event'] in ('CHANNEL_ERROR','PROCESS_EXITED'):
                    raise RuntimeError(row)
                if row['event']=='SIGNAL_REQUEST':
                    active=row['data'];next_signal=0.
                if row['event']=='SIGNAL_REQUEST_CLOSED' and active and active['request_id']==row['data']['request_id']:
                    active=None
                if row['event']=='INSPECTION_REQUIRED' and not inspection_sent:
                    # Explicit B fixture; the robot never constructs Current or declares completion.
                    inspection_sent=True
                    robot.send('INSPECTION',result=dict(plan_id=document['step']['plan_id'],step_id='S01',
                        execution_id=document['session']['execution_id'],decision='KEEP',
                        current=dict(current_revision=document['step']['current_revision']+1,blocks=[document['step']['block']])))
                if row['event']=='B_DECISION' or row['event']=='EXECUTION_HELD':break
            if active and active['kind']=='RECEIVE' and not sent_stop and time.monotonic()>=next_signal:
                next_signal=time.monotonic()+.1
                sequence+=1
                signal={k:active[k] for k in ('request_id','execution_id','plan_id','step_id','current_revision')}
                signal.update(sequence=sequence,source='FAKE',verified=True,
                              hand_present=scenario in ('direct','hand-hold'),receiving_ready=scenario=='direct')
                robot.send('SIGNAL',signal=signal)
                if scenario=='hand-hold' and time.monotonic()-begin>6:
                    robot.send('STOP');sent_stop=True
            if active and active['kind']=='ASSEMBLY_ACK':active=None
        else:raise TimeoutError('FAKE_SCENARIO_TIMEOUT')
    expected='EXECUTION_HELD' if scenario=='hand-hold' else 'B_DECISION'
    assert events[-1]['event']==expected
    if scenario=='hand-hold':
        assert not any(r['event']=='MOVE_STARTED' and r['data']['label']=='TRAY_LOWER' for r in events)
    output.parent.mkdir(parents=True,exist_ok=True)
    report=dict(scenario=scenario,status='PASS',mode='MOCK',device_connections=0,physical_simulation=False,
                b_result_kind='FAKE',elapsed_s=round(time.monotonic()-begin,3),events=events)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-root',type=Path,required=True)
    parser.add_argument('--scenario',choices=('robot','tray','direct','hand-hold'),default='robot')
    parser.add_argument('--output',type=Path,default=Path('/tmp/c2-robot-integration-smoke.json'))
    args=parser.parse_args(); result=run(args.robot_root.resolve(),args.scenario,args.output)
    print(f"PASS {result['scenario']} · MOCK · {result['elapsed_s']}초 · {args.output.resolve()}")
