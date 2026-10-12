"""Replay all original positive Steps through the integrated request/single-writer path."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from app.assembly_step_bridge import ROOT, build_plan, candidate_profile, load_steps
from app.assembly_step_runner import StepReplayDriver, replay_profile
from app.control_session import ControlSession
from app.control_driver import execute_step
from scripts.robot_control_trial import test_session
from scripts.assembly_contact_trial import save


def replay_all(output):
    steps=load_steps()
    profile=replay_profile(candidate_profile(steps),steps)
    results=[]
    for step in steps:
        plan=build_plan(step,profile)
        raw=StepReplayDriver(plan['settings']['reference_pose'])
        ticks=[0.]
        trace=[]
        def clock():return ticks[0]
        def sleep(seconds):ticks[0]+=seconds
        def record(event,data):trace.append(dict(event=event,data=deepcopy(data)))
        session=ControlSession(test_session(plan),plan,record,clock=clock,wall=time.time)
        result=execute_step(raw,session,dict(tcp='GripperDA_v4',tool='ToolWeight0'),plan,
                            profile,lambda *a:True,record,phase='full',clock=clock,sleep=sleep)
        result.update(device_connections=0,robot_motion_commands=0,robot_gripper_commands=0,
                      physical_simulation=False,mock_moves=len(raw.moves),mock_grips=len(raw.grips))
        save(Path(output)/(plan['key'].replace('/','_')+'.json'),dict(result=result,trace=trace))
        results.append(dict(key=plan['key'],status=result['status'],current_update=result['current_update'],
                            assembly_completion=result['assembly_completion']))
    report=dict(status='INTEGRATED_OFFLINE_REPLAY_COMPLETE',steps=len(results),
                cases=len({s['case_id'] for s in steps}),device_connections=0,
                robot_motion_commands=0,robot_gripper_commands=0,physical_simulation=False,results=results)
    save(Path(output)/'replay-summary.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'logs/integrated-replay')
    args=p.parse_args()
    report=replay_all(args.output)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if all(r['status']=='AWAITING_BACKEND_OBSERVATION' for r in report['results']) else 1


if __name__=='__main__':raise SystemExit(main())
