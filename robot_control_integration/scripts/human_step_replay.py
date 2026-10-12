"""Replay the prepared human Step with synthetic feedback and no device imports."""
import argparse
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from app.assembly_step_bridge import build_plan
from app.assembly_step_runner import StepReplayDriver
from app.control_session import ControlSession
from app.control_driver import execute_step

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'settings/onsite_human_11_11_l4_20261011/current-trial.json')
    parser.add_argument('--start-width-mm',type=float,default=49.8)
    parser.add_argument('--no-thumb',action='store_true',help='Exercise post-release timeout and optional next pickup')
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text())
    setup=json.loads(Path(manifest['profile']).read_text())
    value=json.loads(Path(manifest['session']).read_text())
    profile=setup['d_profile'];plan=build_plan(setup['step'],profile)
    eid=str(uuid4());value.update(backend='TEST',provenance='SYNTHETIC',execution_id=eid,
        source_epoch='TEST_HUMAN_'+eid,expires_unix_s=1000.)
    tick=[1.];events=[]
    def clock():return tick[0]
    def sleep(seconds):tick[0]+=seconds
    def record(event,data):events.append(dict(event=event,data=deepcopy(data)))
    session=ControlSession(value,plan,record,clock=clock,wall=lambda:100.)
    raw=StepReplayDriver(plan['settings']['reference_pose'])
    raw.value.update(posx=value['automatic_start_pose'].copy(),gripper_width_mm=args.start_width_mm)
    if manifest['phase']=='human-wait':
        raw.value.update(gripper_status=2,gripper_width_mm=40.6)
    elif manifest['phase']=='human-ack':
        raw.value.update(gripper_status=0,gripper_width_mm=64.2)
    def grip(width,force):
        raw.grips.append((width,force))
        raw.value.update(gripper_status=2 if width==35. else 0,
            gripper_width_mm={35.:40.6,48.:49.8,62.4:64.2}[width])
    raw.command_gripper=grip
    def camera():
        sleep(.05);req=session.request
        if args.no_thumb and req['kind']=='HUMAN_ASSEMBLY_ACK':return None
        shape='OPEN_HAND' if req['kind']=='RECEIVE' else 'THUMBS_UP'
        held=round((clock()-req['opened_monotonic_s'])*1e9)
        threshold=400_000_000 if shape=='OPEN_HAND' else round(plan['settings']['human_step_gestures'].get('thumb_hold_seconds',.8)*1e9)
        return dict(**session.binding,execution_id=eid,source_epoch=value['source_epoch'],
            preview_request_id=req['request_id'],received_monotonic_ns=int(clock()*1e9),
            source_ns=int(clock()*1e9)+1,held_ns=held,continuity_estimate=held>50_000_000,
            hands=[dict(pose=shape)],provenance='SENSOR',pose_verified=False,
            candidate_event=('OPEN_HAND_HELD_ORIENTATION_UNKNOWN' if shape=='OPEN_HAND' else 'THUMBS_UP_HELD') if held>=threshold else None)
    def confirm(*args):raise AssertionError('Unexpected HMI prompt')
    result=execute_step(raw,session,dict(tcp='GripperDA_v4',tool='ToolWeight0'),plan,profile,
        confirm,record,phase=manifest['phase'],start_zone=manifest['start_zone'],camera_poll=camera,clock=clock,sleep=sleep)
    previous_result=deepcopy(result)
    if args.no_thumb:
        assert result['status']=='HUMAN_ACK_TIMEOUT_CONTINUE' and not result['human_completion_signal_received']
        if manifest.get('next_pickup_profile'):
            from app.human_step_continuation import execute_next_pickup
            ns=json.loads(Path(manifest['next_pickup_profile']).read_text())
            np=ns['d_profile'];nplan=build_plan(ns['step'],np)
            nv=json.loads(Path(manifest['next_pickup_session']).read_text())
            nv.update(backend='TEST',provenance='SYNTHETIC',execution_id=str(uuid4()),
                source_epoch='TEST_NEXT_PICKUP',expires_unix_s=1000.)
            nv['previous_step']['execution_id']=eid
            nxt=ControlSession(nv,nplan,record,clock=clock,wall=lambda:100.)
            result=execute_next_pickup(raw,session,plan,result,nxt,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
                nplan,np,confirm,record,clock=clock,sleep=sleep)
            assert result['status']=='PAUSED_PICKUP_COMPLETE_HOLDING'
            assert raw.value['gripper_status']==2 and raw.value['posx']==nplan['settings']['pickup_pose']
            # Already-open feedback can legitimately skip redundant preparation.
            assert raw.grips[-1]==(35.,40.) and len(raw.grips) in (1,2)
            assert all(w in (nplan['settings']['release_width_mm'],35.) for w,f in raw.grips)
    else:
        assert result['status']=='AWAITING_BACKEND_OBSERVATION' and result['human_completion_signal_received']
    assert not any(result[k] for k in ('assembly_completion','current_update','physical_verified'))
    if args.no_thumb:
        assert not session.cancelled and not any(e['event']=='SINGLE_WRITER_STOP' for e in events)
    elif manifest['phase']=='human-ack':
        assert not raw.grips and not raw.moves and not raw.blends
    elif manifest['phase']=='human-wait':
        assert raw.grips==[(62.4,40.)] and raw.moves==[]
    else:
        assert raw.grips==[(plan['settings']['release_width_mm'],40.),(35.,40.),(62.4,40.)]
        assert raw.value['posx'][:3]==plan['settings']['reference_pose'][:2]+[profile['clearance_z_mm']]
    assert not any(e['event']=='PRESS_SESSION' for e in events)
    result.update(device_connections=0,robot_motion_commands=0,robot_gripper_commands=0,
        physical_simulation=False,mock_moves=len(raw.moves),mock_grips=len(raw.grips),mock_blends=len(raw.blends))
    output=ROOT/'logs/human-step-replay'/eid;output.mkdir(parents=True)
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (output/'previous-step-result.json').write_text(json.dumps(previous_result,ensure_ascii=False,indent=2)+'\n')
    (output/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status='ACK_TIMEOUT_NEXT_PICKUP_OFFLINE_PASS' if args.no_thumb else 'HUMAN_STEP_OFFLINE_REPLAY_PASS',target=plan['block'],
        stages=(['ACK_TIMEOUT','NEXT_PICKUP'] if args.no_thumb and manifest.get('next_pickup_profile') else
            (['PICKUP','TARGET_HIGH'] if manifest['phase']=='full' else ['TARGET_HIGH_RESUME'])+['OPEN_HAND_HANDOVER','THUMBS_UP_COMPLETION']),
        device_connections=0,robot_motion_commands=0,robot_gripper_commands=0,output=str(output)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
