"""Preview or explicitly run yellow4 Stage4/5 seating or Stage6 partial removal."""
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
from uuid import uuid4
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'robot_control_integration'),str(ROOT/'perception')]
from app.yellow4_contact_trial import prepare_contact,execute
from app.yellow4_seating_trial import prepare_seating
from app.yellow4_removal_trial import prepare_removal
from app.yellow4_recovery_trial import prepare_recovery,execute_cycle
from app.yellow4_observation import prepare,analyze,source,save_capture
from app.assembly_motion_ros import AssemblyMotionRos
from scripts.yellow4_air_trial import TrialWindow,_pump_sleep
from scripts.yellow4_observe import ReadOnlyRos
from scripts.yellow4_edge_first_preview import save_plot
from supply_vision.virtual_board_grid import project_base


class ContactWindow(TrialWindow):
    def __init__(self,observer,bundle,plan,*,title=None):
        super().__init__(observer,bundle,plan,title=title or f"Yellow4 STAGE {plan.get('stage',4)} | operator contact trial | ESC STOP")
        c=plan['contact']
        self.banner=f"CONTACT INPUTS: {c['linear_velocity_mm_s']}mm/s, {c['angular_velocity_deg_s']}deg/s | STOP {c['force_stop_n']}N / dM {c['moment_delta_stop_nm']}Nm"
        self.view='assembly' if plan.get('stage') in (6,7) else 'supply';self.active={};self.answer=None;self.key_handler=self.key
        self.evidence_root=None;self.evidence_futures=[]
        self.selection=None;self.clicks=[]
        self.instructions=['G grasp / A aligned / N next descent / E stud engaged / R partial pivot / I inspected',
            'STOP: L board/structure lift | S grip slip | M contact moved | U unknown | ESC',
            'B ROI / T click TOP edge endpoints / C clear | pixel yaw only; block roll/pitch UNKNOWN']
        if plan.get('stage')==6:self.instructions[0]='V open empty / D closed empty / A seated / G regrasp / R pivot / I partial / W all / N none'
        cv2.setMouseCallback(self.title,self.click)

    def set_plan(self,plan):
        pending=self.pending
        if pending is not None:
            while not pending.done():_pump_sleep(self,.02)
            pending.result()
        self.pending=None;self.plan=deepcopy(plan);self.canvas=None;self.report={};self.target=None
        self.active={};self.answer=None;self.view='supply' if plan['stage']==5 else 'assembly'
        self.label='PREPARING_STAGE_'+str(plan['stage'])
        c=plan['contact'];self.banner=f"STAGE {plan['stage']} | {plan['operation']} | {c['linear_velocity_mm_s']}mm/s / {c['angular_velocity_deg_s']}deg/s | STOP {c['force_stop_n']}N / dM {c['moment_delta_stop_nm']}Nm"

    def pump(self):
        yaw=self.report.get('relative_angle_deg')
        self.instructions[2]=f'B ROI / T top edge / C clear | pixel yaw: {None if yaw is None else round(yaw,2)} | block RPY UNKNOWN'
        super().pump()

    def analyze_frame(self,frame,sample,info,view,edge,roi,*,stamp_ns=0,plan=None):
        # The Stage2 helper's default path reaches 0 degrees; Stage4 displays only its partial arc.
        canvas,report=analyze(frame,dict(self.bundle,geometry_config=None),view,
            sample=sample,info=info,grid=self.grid,edge=edge,roi=roi,stamp_ns=stamp_ns)
        plan=plan or self.plan
        g=plan.get('seating_geometry',plan['partial_geometry']);reference=report.get('grid_reference',{})
        if info is not None and 'T_base_from_camera_mm' in reference:
            transform=np.array(reference['T_base_from_camera_mm'])
            path,ok=project_base([p['tcp_mm_zyz_deg'][:3] for p in g['waypoints']],transform,info['k'],info['d'])
            axis,valid=project_base(g['contact_line_points_mm'],transform,info['k'],info['d'])
            if ok.all():cv2.polylines(canvas,[path.astype(np.int32)],False,(255,0,255),2)
            if valid.all():cv2.line(canvas,tuple(axis[0].astype(int)),tuple(axis[1].astype(int)),(0,140,255),3)
        report.update(planned_path_source='COMPLETION_GEOMETRY_NOT_PHYSICALLY_VERIFIED' if plan.get('stage')==7 else 'FULL_CONTACT_GEOMETRY_NOT_PHYSICALLY_VERIFIED' if plan.get('stage')==5 else 'PARTIAL_CONTACT_GEOMETRY_NOT_PHYSICALLY_VERIFIED',stage=plan.get('stage',4),
            planned_angle_basis='DELTA_FROM_PARTIAL_REFERENCE' if plan.get('stage')==7 else 'REGISTERED_SEATED_REFERENCE',
            path_operation=plan['operation'],planned_partial_tilt_deg=[g['waypoints'][0]['tilt_deg'],g['waypoints'][-1]['tilt_deg']])
        return canvas,report

    def key(self,key):
        letter=chr(key).upper()
        fault={'L':'STRUCTURE_OR_BOARD_LIFT','S':'GRIP_SLIP','M':'CONTACT_POINT_MOVED','U':'UNKNOWN'}
        if letter in fault:raise RuntimeError('OPERATOR_REPORT:'+fault[letter])
        if letter in ('B','T'):self.selection=letter;self.clicks=[]
        if letter=='C':self.selection=None;self.clicks=[];self.edge=[];self.roi=None
        if letter in self.active:self.answer=self.active[letter]

    def click(self,event,x,y,flags,param):
        if event!=cv2.EVENT_LBUTTONDOWN or self.selection is None or self.observer.frame is None:return
        y-=244+27*len(self.instructions)
        if not 0<=x<self.observer.frame.shape[1] or not 0<=y<self.observer.frame.shape[0]:return
        self.clicks.append([x,y])
        if len(self.clicks)==2:
            a,b=self.clicks
            if self.selection=='T':self.edge=self.clicks.copy()
            elif a[0]!=b[0] and a[1]!=b[1]:self.roi=[min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])]
            self.selection=None;self.clicks=[]

    def operator(self,phase,allowed,poll):
        keys={'GRASP_MATCH':'G','ALIGNED':'A','NO_ENGAGEMENT_NEXT':'N','STUD_ENGAGED':'E','PIVOT_READY':'R','PARTIAL_OBSERVED':'I',
            'FULL_PIVOT_READY':'F','SEATED_READY_TO_RELEASE':'O','POST_RELEASE_STABLE':'I','PRESS_READY':'P','POST_PRESS_OBSERVED':'I',
            'OPEN_EMPTY':'V','CLOSED_EMPTY_PAD':'D','CURRENT_BLOCK_SEATED_AND_BOARD_FIXED':'A',
            'REMOVAL_GRASP_MATCH':'G','REMOVAL_PIVOT_READY':'R','ONE_SIDE_RELEASED_REMAINING_ENGAGED':'I',
            'ALL_RELEASED_OBSERVED':'W','NO_RELEASE_OBSERVED':'N','PARTIAL_STATE_GRASP_BOARD_AND_AXIS_MATCH':'G',
            'ALL_STUDS_RELEASED_GRIP_AND_BOARD_STABLE':'W','RETURN_POSE_BLOCK_SUPPORTED_HAND_CLEAR':'O',
            'RECOVERED_BLOCK_TARGET_EMPTY_BOARD_STABLE':'I','SAME_BLOCK_SUPPLY_READY_TARGET_EMPTY_HAND_CLEAR':'Y'}
        self.active={keys[a]:a for a in allowed};self.answer=None;self.label=phase
        self.instructions[0]='NOW: '+' / '.join(f'{k}: {v}' for k,v in self.active.items())
        try:
            while self.answer is None:
                self.sample=poll();_pump_sleep(self,.02)
            return self.answer
        finally:self.active={};self.answer=None

    def observe_supply(self,poll):
        self.view='supply';self.label='SUPPLY_OPENCV_OBSERVATION'
        while self.observer.frame is None or self.observer.rgb_time is None or time.monotonic()-self.observer.rgb_time>1:
            self.sample=poll()
            _pump_sleep(self,.02)
        sample=poll();self.sample=sample
        frame=self.observer.frame.copy();info=deepcopy(self.observer.info);stamp=self.observer.stamp_ns;now=time.time()
        future=self.pool.submit(self.analyze_frame,frame,deepcopy(sample),info,'supply',deepcopy(self.edge),self.roi,stamp_ns=stamp)
        while not future.done():_pump_sleep(self,.02)
        self.canvas,report=future.result();self.report=report
        report['source_rgb_stamp_ns']=stamp
        if self.evidence_root is not None:
            self.evidence_futures.append(self.pool.submit(save_capture,self.evidence_root/('supply-vision-'+str(time.time_ns())),
                frame,self.canvas.copy(),self.bundle,deepcopy(report),sample=deepcopy(sample),info=info,role='SUPPLY_OPENCV',
                timing=dict(rgb_stamp_ns=stamp,unix_s=now,synchronized_pose_image_verified=False)))
        return report

    def feedback(self,event,data):
        super().feedback(event,data)
        if event in ('OPERATOR_WAIT_SAMPLE','OPERATOR_OBSERVATION','CONTACT_BASELINE'):
            self.sample=data['sample']
        if event=='MOVE_REQUEST' and data['label']=='ASSEMBLY_OBSERVATION':self.view='assembly'
        if event=='MOVE_REQUEST':self.instructions[0]='MOVING: phase confirmation keys disabled; fault keys / ESC remain active'
        if event=='PAD_MOVE_REQUEST':
            self.label='PAD_'+data['segment'];self.target=data['target']
            self.instructions[0]='PRESS MOVING: no automatic release/retry; ESC/fault keys active'
        if event=='PAD_WRENCH_SAMPLE':self.sample=data['sample']
        if event=='PAD_MOTION_SAMPLE':
            self.sample=data['sample'];self.error=f"{data['position_error_mm']:.4f} mm / {data['so3_error_deg']:.4f} deg"

    def save_evidence(self,path,frame,sample,info,stamp,captured_unix,view,event,edge,roi,plan=None):
        plan=plan or self.plan
        canvas,report=self.analyze_frame(frame,sample,info,view,edge,roi,stamp_ns=stamp,plan=plan)
        report.update(path_source='CONTACT_INPUT_GEOMETRY_NOT_PHYSICALLY_VERIFIED',path_operation=plan['operation'],phase_plan_sources=plan['sources'])
        return save_capture(path,frame,canvas,self.bundle,report,sample=sample,info=info,
            role='CONTACT_TRIAL_FRAME',notes=event,timing=dict(rgb_stamp_ns=stamp,unix_s=captured_unix,processed_unix_s=time.time(),
                synchronized_pose_image_verified=False))


def read_air_evidence(run):
    events=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    if any(e['event']=='ABORT' for e in events):raise ValueError('ABORTED_AIR_RUN_IS_NOT_COMPLETION_EVIDENCE')
    result=next((e['data'] for e in reversed(events) if e['event']=='RESULT'),None)
    context=next((e['data'] for e in events if e['event']=='TRIAL_CONTEXT'),None)
    if result is None or context is None:raise ValueError('AIR_RUN_RESULT_AND_CONTEXT_REQUIRED')
    return dict(result=result,context=context,preview=json.loads((run/'preview.json').read_text()),
        sources=dict(events=source(run/'events.jsonl'),preview=source(run/'preview.json')))


def read_trial_evidence(run,kind):
    events=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    if any(e['event'] in ('ABORT','CYCLE_ABORT') for e in events):raise ValueError('ABORTED_'+kind+'_RUN_IS_NOT_COMPLETION_EVIDENCE')
    result=next((e['data'] for e in reversed(events) if e['event']=='RESULT'),None)
    if result is None:raise ValueError(kind+'_RUN_RESULT_REQUIRED')
    return dict(result=result,events=events,preview=json.loads((run/'preview.json').read_text()),
        sources=dict(events=source(run/'events.jsonl'),preview=source(run/'preview.json')))


def read_partial_evidence(run):
    return read_trial_evidence(run,'PARTIAL')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',type=int,choices=(4,5,6,7),default=4)
    p.add_argument('--config',type=Path)
    p.add_argument('--contact-config',type=Path)
    p.add_argument('--observations',type=Path,default=ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/observation.json')
    p.add_argument('--measurements',type=Path);p.add_argument('--air-run',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--partial-run',type=Path)
    p.add_argument('--seating-run',type=Path)
    p.add_argument('--removal-run',type=Path)
    p.add_argument('--start-zone',choices=('home','supply','assembly'),default='home')
    p.add_argument('--execute',action='store_true');p.add_argument('--confirm-hand-clear',action='store_true')
    p.add_argument('--confirm-route-clear',action='store_true');p.add_argument('--confirm-target-empty',action='store_true')
    p.add_argument('--confirm-target-seated',action='store_true')
    p.add_argument('--confirm-partial-state',action='store_true')
    args=p.parse_args(argv)
    args.config=args.config or ROOT/('robot_control_integration/settings/yellow4_challenge_20261014/'+{4:'contact_trial.json',5:'seating_trial.json',6:'removal_trial.json',7:'recovery_cycle.json'}[args.stage])
    settings=json.loads(args.config.read_text());obs=json.loads(args.observations.read_text())
    partial=read_partial_evidence(args.partial_run) if args.stage==5 and args.partial_run else None
    # Reuse the exact inputs recorded by Stage4 when no new file is explicitly selected.
    if partial is not None:
        refs=partial['preview']['sources']
        if args.measurements is None and refs.get('field_measurements'):
            candidate=Path(refs['field_measurements']['path'])
            if candidate.exists():args.measurements=candidate
        if args.air_run is None and refs.get('air_run'):
            candidate=Path(refs['air_run']['events']['path']).parent
            if (candidate/'events.jsonl').exists():args.air_run=candidate
    measured=json.loads(args.measurements.read_text()) if args.measurements else None
    bundle=prepare(ROOT,obs,measured if args.stage in (4,5) else None)
    bundle['camera_info_topic']=obs['camera_info_topic']
    air_evidence=read_air_evidence(args.air_run) if args.air_run else None
    if args.stage==7:
        removal=read_trial_evidence(args.removal_run,'REMOVAL') if args.removal_run else None
        plan=prepare_recovery(bundle,settings,removal)
        plan['sources']['recovery_settings']=source(args.config)
        if removal is not None:plan['sources']['removal_run']=removal['sources']
    elif args.stage==6:
        seating=read_trial_evidence(args.seating_run,'SEATING') if args.seating_run else None
        plan=prepare_removal(bundle,settings,measured,seating)
        plan['sources']['removal_settings']=source(args.config)
        if seating is not None:plan['sources']['seating_run']=seating['sources']
    elif args.stage==5:
        if args.contact_config is not None:contact_settings=json.loads(args.contact_config.read_text());contact_source=source(args.contact_config)
        elif partial is not None:contact_settings=deepcopy(partial['preview']['settings']);contact_source=dict(recorded_in=partial['sources']['preview'])
        else:
            args.contact_config=ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/contact_trial.json'
            contact_settings=json.loads(args.contact_config.read_text());contact_source=source(args.contact_config)
        plan=prepare_seating(bundle,contact_settings,settings,air_evidence,partial)
        plan['sources'].update(seating_settings=source(args.config),contact_settings=contact_source)
        if partial is not None:plan['sources']['partial_run']=partial['sources']
    else:plan=prepare_contact(bundle,settings,air_evidence);plan['sources']['contact_settings']=source(args.config)
    plan['sources']['observation_settings']=source(args.observations)
    if args.measurements:plan['sources']['field_measurements']=source(args.measurements)
    if args.air_run:plan['sources']['air_run']=air_evidence['sources']
    plan['sources']['historical_moment_trial']=source(ROOT/'robot_control_integration/settings/held_corner_stud_20261014/README.md')
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'preview.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    if 'partial_geometry' in plan:save_plot([plan.get('seating_geometry',plan['partial_geometry'])],args.output/({5:'seating-path.png',6:'removal-path.png',7:'recovery-path.png'}.get(args.stage,'partial-path.png')))
    if not args.execute:
        print(json.dumps({k:plan[k] for k in ('status','execution_ready','grasp_mode','contact','missing_measurements','physical_commands')},ensure_ascii=False,indent=2));return 0
    if not plan['execution_ready']:p.error('실측 입력과 앞 단계 실제 시험·검토 기록이 필요합니다. preview.json의 누락 항목을 확인하세요.')
    if not args.confirm_hand_clear or not args.confirm_route_clear:p.error('--confirm-hand-clear --confirm-route-clear required')
    if args.stage==7:
        if not args.confirm_partial_state:p.error('--confirm-partial-state required for continuation')
    elif args.stage==6:
        if not args.confirm_target_seated:p.error('--confirm-target-seated required for removal')
    elif not args.confirm_target_empty:p.error('--confirm-target-empty required for seating')
    run_session(bundle,plan,args.output,args.start_zone)
    return 0


def run_session(bundle,plan,output,start_zone):
    """One locked ROS/popup writer, shared by standalone contact and cycle launchers."""
    if not plan['execution_ready']:raise ValueError('FIELD_INPUTS_REQUIRED_BEFORE_DEVICE_CONSTRUCTION')
    if os.environ.get('ROS_DOMAIN_ID')!=str(plan['connection']['ros_domain_id']):raise ValueError('ROS_DOMAIN_MISMATCH')
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):raise RuntimeError('DESKTOP_DISPLAY_REQUIRED')
    run=output/('run-'+str(time.time_ns()));run.mkdir()
    (run/'preview.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with open('/tmp/c2-assembly-'+plan['connection']['robot_id']+'.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        observer=ReadOnlyRos(bundle,node_name='yellow4_contact_'+uuid4().hex[:8],disable_signal_handlers=True)
        driver=None;window=None;old={}
        try:
            window=ContactWindow(observer,bundle,plan['seating_plan'] if plan['operation']=='cycle' else plan,
                title='Yellow4 CYCLE | seating / removal / recovery | ESC STOP' if plan['operation']=='cycle' else None)
            window.evidence_root=run
            driver=AssemblyMotionRos(dict(connection=plan['connection'],timing=dict(service_timeout_s=3)),node=observer.node)
            driver.ui_pump=window.pump;driver.stop_ui_pump=lambda:observer.ros.spin_once(observer.node,timeout_sec=.005)
            if driver.robot_system()!=0:raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
            def interrupt(*_):raise KeyboardInterrupt('OPERATOR_STOP')
            for sig in (signal.SIGINT,signal.SIGTERM):old[sig]=signal.signal(sig,interrupt)
            with (run/'events.jsonl').open('x') as journal:
                evidence=window.evidence_futures;last_motion_image=0
                def record(event,data):
                    nonlocal last_motion_image
                    window.feedback(event,data);now=time.time()
                    journal.write(json.dumps(dict(event=event,data=data,unix_s=now,rgb_stamp_ns=observer.stamp_ns),ensure_ascii=False,allow_nan=False)+'\n');journal.flush()
                    motion_image=event in ('MOTION_SAMPLE','PAD_MOTION_SAMPLE') and now-last_motion_image>=.2
                    if (event in ('START','WAYPOINT_REACHED','OPERATOR_OBSERVATION','ACTUAL_RELEASE_POSE','PAD_PRESS_RESULT','RESULT','ABORT') or motion_image) and observer.frame is not None:
                        if motion_image:last_motion_image=now
                        sample=data.get('sample',data.get('final_sample'))
                        evidence.append(window.pool.submit(window.save_evidence,run/('evidence-'+str(time.time_ns())),
                            observer.frame.copy(),deepcopy(sample),deepcopy(observer.info),observer.stamp_ns,now,window.view,event,
                            deepcopy(window.edge),deepcopy(window.roi),deepcopy(window.plan)))
                error=None
                try:
                    if plan['operation']=='cycle':result=execute_cycle(driver,plan,start_zone,record,window.observe_supply,window.operator,window.set_plan,sleep=lambda s:_pump_sleep(window,s))
                    else:result=execute(driver,plan,start_zone,record,window.observe_supply,window.operator,sleep=lambda s:_pump_sleep(window,s))
                except BaseException as failure:error=failure
                # Motion has finished or STOP was requested before draining fault evidence.
                for future in evidence:
                    while not future.done():observer.ros.spin_once(observer.node,timeout_sec=.005);time.sleep(.005)
                    try:future.result()
                    except Exception as failure:
                        if error is None:error=failure
                        else:error.add_note('IMAGE_EVIDENCE_SAVE_FAILED: '+str(failure))
                if error is not None:raise error
                print(json.dumps(result,ensure_ascii=False),flush=True)
        finally:
            for sig,handler in old.items():signal.signal(sig,handler)
            if driver:driver.close()
            if window:window.close()
            observer.close()
    return result


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('시험 종료 / 자동 개방·재시도 없음',flush=True);raise SystemExit(130)
