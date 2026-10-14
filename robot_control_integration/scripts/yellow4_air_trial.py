"""Prepare or explicitly run the yellow4 no-contact air pivot with existing MoveL."""
import argparse
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'robot_control_integration'),str(ROOT/'perception')]
import cv2
import numpy as np
from app.yellow4_air_trial import prepare_air,execute,route
from app.yellow4_observation import prepare,analyze,save_capture,source
from app.assembly_motion_ros import AssemblyMotionRos
from scripts.yellow4_observe import ReadOnlyRos
from scripts.yellow4_edge_first_preview import save_plot
from supply_vision.virtual_board_grid import VirtualBoardGrid


class TrialWindow:
    def __init__(self,observer,bundle,plan):
        self.observer=observer;self.bundle=deepcopy(bundle);self.bundle['geometry_config']=plan['air_config']
        self.plan=plan;self.sample=None;self.label='PREPARING'
        self.target=None;self.canvas=None;self.report={};self.pool=ThreadPoolExecutor(max_workers=1);self.pending=None
        self.error='not sampled'
        self.last_draw=0;self.last_analysis=0;self.grid=VirtualBoardGrid(bundle['virtual_grid'])
        self.title='Yellow4 AIR PIVOT | ESC STOP | no grip / contact / press'
        cv2.namedWindow(self.title,cv2.WINDOW_NORMAL);cv2.resizeWindow(self.title,1100,800)

    def pump(self):
        self.observer.ros.spin_once(self.observer.node,timeout_sec=.001)
        now=time.monotonic()
        if self.pending is not None and self.pending.done():
            self.canvas,self.report=self.pending.result();self.pending=None;self.last_analysis=now
        if self.pending is None and self.observer.frame is not None and self.sample is not None and now-self.last_analysis>.2:
            self.pending=self.pool.submit(analyze,self.observer.frame.copy(),self.bundle,'assembly',
                sample=self.sample.copy(),info=self.observer.info,grid=self.grid)
        if now-self.last_draw<.04:return
        self.last_draw=now
        frame=self.canvas if self.canvas is not None else self.observer.frame
        if frame is None:frame=np.zeros((480,640,3),np.uint8)
        ui=np.zeros((frame.shape[0]+244,frame.shape[1],3),np.uint8);ui[244:]=frame
        fmt=lambda value:None if value is None else [round(float(v),3) for v in value]
        lines=['AIR TEST / one MoveL writer / no contact / no gripper commands',
            f"Phase: {self.label} | grasp: {self.plan['grasp_mode']} / {self.plan['intended_pad_bottom_height_mm']}mm",
            f'Target TCP: {fmt(self.target)}',f"Actual TCP: {fmt(None if self.sample is None else self.sample.get('posx'))}",
            f'Position / SO(3) error: {self.error}',
            f"Width: {None if self.sample is None else self.sample.get('gripper_width_mm')} | Raw wrench: {fmt(None if self.sample is None else self.sample.get('wrench'))}",
            f"RGB age s: {None if self.observer.rgb_time is None else round(now-self.observer.rgb_time,2)} | image/pose sync NOT verified",
            'Saved geometry/feedback errors in events.jsonl | ESC stops trial motion']
        for i,line in enumerate(lines):cv2.putText(ui,line,(8,24+i*27),cv2.FONT_HERSHEY_SIMPLEX,.40,(255,255,255),1)
        cv2.imshow(self.title,ui)
        if cv2.waitKey(1)&255==27 or cv2.getWindowProperty(self.title,cv2.WND_PROP_VISIBLE)<1:
            raise KeyboardInterrupt('OPERATOR_STOP')

    def feedback(self,event,data):
        if event in ('START','PREVIEW_ACTUAL_START','FEEDBACK_REFRESH_WAIT'):self.sample=data['sample']
        if event=='SETTLING_WAIT':self.sample=data
        if event=='MOVE_REQUEST':self.label=data['label'];self.target=data['target']
        if event in ('MOTION_SAMPLE','WAYPOINT_REACHED'):
            self.sample=data['sample'];self.error=f"{data['position_error_mm']:.4f} mm / {data['so3_error_deg']:.4f} deg"

    def close(self):
        self.pool.shutdown(wait=False,cancel_futures=True)
        try:cv2.destroyWindow(self.title)
        except cv2.error:pass  # The operator may have already closed this window.

    def save_evidence(self,path,frame,sample,info,stamp,captured_unix):
        canvas,report=analyze(frame,self.bundle,'assembly',sample=sample,info=info,grid=self.grid)
        report['path_operation']=self.plan['operation']
        report['path_source']='AIR_TRANSLATION_OF_INPUT_GEOMETRY_NOT_PHYSICAL_CONTACT'
        return save_capture(path,frame,canvas,self.bundle,report,sample=sample,info=info,
            role='AIR_WAYPOINT',timing=dict(rgb_stamp_ns=stamp,unix_s=captured_unix,processed_unix_s=time.time(),synchronized_pose_image_verified=False))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/air_trial.json')
    p.add_argument('--observations',type=Path,default=ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/observation.json')
    p.add_argument('--measurements',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--operation',choices=('assembly','removal'),default='assembly');p.add_argument('--grasp-mode',choices=('standard','human-replacement'))
    p.add_argument('--start-zone',choices=('home','supply','assembly'),default='supply')
    p.add_argument('--execute',action='store_true');p.add_argument('--empty-gripper',action='store_true')
    p.add_argument('--confirm-hand-clear',action='store_true');p.add_argument('--confirm-route-clear',action='store_true')
    args=p.parse_args(argv);settings=json.loads(args.config.read_text());observations=json.loads(args.observations.read_text())
    if args.grasp_mode:observations['grasp_mode']=args.grasp_mode.upper().replace('-','_')
    bundle=prepare(ROOT,observations,json.loads(args.measurements.read_text()) if args.measurements else None)
    bundle['camera_info_topic']=observations['camera_info_topic'];plan=prepare_air(bundle,settings,args.operation)
    plan['sources']['air_trial_settings']=source(args.config);plan['sources']['observation_settings']=source(args.observations)
    if args.measurements:plan['sources']['field_measurements']=source(args.measurements)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'preview.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    if plan['execution_ready']:
        save_plot([plan['air_geometry']],args.output/'air-path.png')
    if not args.execute:
        print(json.dumps(dict(status=plan['status'],execution_ready=plan['execution_ready'],grasp_mode=plan['grasp_mode'],
            rates=plan['rates'],missing_measurements=plan['missing_measurements'],physical_commands=0,output=str(args.output)),ensure_ascii=False,indent=2));return 0
    if not plan['execution_ready']:p.error('실측된 파지 관계와 선택한 접촉축이 필요합니다. preview.json의 누락 항목을 확인하세요.')
    if not args.confirm_hand_clear or not args.confirm_route_clear:p.error('--confirm-hand-clear --confirm-route-clear required')
    if os.environ.get('ROS_DOMAIN_ID')!=str(plan['connection']['ros_domain_id']):raise ValueError('ROS_DOMAIN_MISMATCH')
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):raise RuntimeError('DESKTOP_DISPLAY_REQUIRED')
    run_dir=args.output/('run-'+str(time.time_ns()));run_dir.mkdir()
    with open('/tmp/c2-assembly-'+plan['connection']['robot_id']+'.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        observer=ReadOnlyRos(bundle,node_name='yellow4_air_trial_'+uuid4().hex[:8],disable_signal_handlers=True);driver=None;window=None;old={}
        try:
            window=TrialWindow(observer,bundle,plan)
            driver=AssemblyMotionRos(dict(connection=plan['connection'],timing=dict(service_timeout_s=3)),node=observer.node)
            driver.ui_pump=window.pump
            driver.stop_ui_pump=lambda:observer.ros.spin_once(observer.node,timeout_sec=.005)
            if driver.robot_system()!=0:raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
            def interrupt(*_):raise KeyboardInterrupt('OPERATOR_STOP')
            for sig in (signal.SIGINT,signal.SIGTERM):old[sig]=signal.signal(sig,interrupt)
            with (run_dir/'events.jsonl').open('x') as journal:
                evidence=[]
                def record(event,data):
                    window.feedback(event,data)
                    captured_unix=time.time()
                    journal.write(json.dumps(dict(event=event,data=data,unix_s=captured_unix,rgb_stamp_ns=observer.stamp_ns),ensure_ascii=False,allow_nan=False)+'\n');journal.flush()
                    if event in ('START','WAYPOINT_REACHED','RESULT') and observer.frame is not None:
                        frame=observer.frame.copy();sample=data.get('sample',data.get('final_sample'))
                        evidence.append(window.pool.submit(window.save_evidence,run_dir/('evidence-'+str(time.time_ns())),
                            frame,deepcopy(sample),deepcopy(observer.info),observer.stamp_ns,captured_unix))
                initial=driver.sample();record('PREVIEW_ACTUAL_START',dict(sample=initial,route=[dict(label=l,tcp=t) for l,t in route(plan,initial['posx'],args.start_zone)]))
                record('TRIAL_CONTEXT',dict(empty_gripper_trial=args.empty_gripper,
                    block_present_independently_verified=False,physical_contact_test=False,operation=args.operation))
                expected=initial['gripper_status'] if args.empty_gripper else 2
                result=execute(driver,plan,args.start_zone,record,expected_gripper_status=expected,
                    sleep=lambda seconds: _pump_sleep(window,seconds))
                for future in evidence:
                    while not future.done():_pump_sleep(window,.01)
                    future.result()
                print(json.dumps(result,ensure_ascii=False),flush=True)
        finally:
            for sig,handler in old.items():signal.signal(sig,handler)
            if driver:driver.close()
            if window:window.close()
            observer.close()
    return 0


def _pump_sleep(window,seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:window.pump();time.sleep(.005)


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('시험 종료 / 그리퍼 조작 없음',flush=True);raise SystemExit(130)
