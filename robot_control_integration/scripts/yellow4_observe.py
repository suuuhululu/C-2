"""Yellow4 read-only source preparation, camera popup and evidence capture."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'robot_control_integration'),str(ROOT/'perception')]
import cv2
import numpy as np
from app.yellow4_observation import prepare,analyze,save_capture,source
from supply_vision.virtual_board_grid import VirtualBoardGrid


class ReadOnlyRos:
    # FK/check_motion are queries; this observer exposes no move/stop/tool-set client.
    SERVICES=[('posj','aux_control/get_current_posj','GetCurrentPosj','pos'),
        ('posx','motion/fkin','Fkin','conv_posx'),('velx','aux_control/get_current_velx','GetCurrentVelx','vel'),
        ('motion_status','motion/check_motion','CheckMotion','status'),
        ('wrench','aux_control/get_tool_force','GetToolForce','tool_force'),
        ('tcp','tcp/get_current_tcp','GetCurrentTcp','info'),('tool','tool/get_current_tool','GetCurrentTool','info')]

    def __init__(self,bundle,read_gripper=False,node_name=None,disable_signal_handlers=False):
        import rclpy
        from dsr_msgs2 import srv
        from sensor_msgs.msg import Image,CameraInfo
        from rclpy.qos import qos_profile_sensor_data
        self.ros=rclpy
        if disable_signal_handlers:
            from rclpy.signals import SignalHandlerOptions
            # A shared motion trial must send STOP before its ROS context closes.
            rclpy.init(args=[],signal_handler_options=SignalHandlerOptions.NO)
        else:rclpy.init(args=[])
        self.node=rclpy.create_node(node_name or 'yellow4_read_only_'+uuid4().hex[:8])
        prefix='/'+bundle['connection']['robot_id']+'/dsr_controller2/'
        self.clients=[self.node.create_client(getattr(srv,t),prefix+p) for _,p,t,_ in self.SERVICES]
        self.srv=srv;self.index=0;self.pending=None;self.sample={};self.times={}
        self.frame=None;self.info=None;self.rgb_time=None;self.stamp_ns=0;self.status='WAITING_READ_FEEDBACK'
        self.node.create_subscription(Image,bundle['vision']['rgb_topic'],self.rgb,qos_profile_sensor_data)
        self.node.create_subscription(CameraInfo,bundle['camera_info_topic'],self.camera,qos_profile_sensor_data)
        self.gripper=None;self.gripper_poll=0
        if read_gripper:
            from pymodbus.client import ModbusTcpClient
            self.gripper=ModbusTcpClient(bundle['connection']['gripper_ip'],port=502,timeout=.15)

    def rgb(self,msg):
        if msg.encoding not in ('rgb8','bgr8') or msg.step<msg.width*3:
            self.status='UNSUPPORTED_RGB_ENCODING';return
        frame=np.frombuffer(msg.data,np.uint8).reshape(msg.height,msg.step)[:,:msg.width*3].reshape(msg.height,msg.width,3).copy()
        self.frame=cv2.cvtColor(frame,cv2.COLOR_RGB2BGR) if msg.encoding=='rgb8' else frame
        self.rgb_time=time.monotonic();self.stamp_ns=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec

    def camera(self,msg):
        self.info=dict(width=msg.width,height=msg.height,k=list(msg.k),d=list(msg.d),
            distortion_model=msg.distortion_model,frame_id=msg.header.frame_id,
            stamp_ns=msg.header.stamp.sec*10**9+msg.header.stamp.nanosec)

    def poll(self):
        self.ros.spin_once(self.node,timeout_sec=.005);now=time.monotonic()
        if self.pending:
            key,future,started=self.pending
            if future.done():
                try:
                    response=future.result()
                    if response is None or not response.success:raise RuntimeError('READ_RESPONSE_FAILED')
                    value=getattr(response,self.SERVICES[self.index][3])
                    self.sample[key]=[float(v) for v in value] if key in ('posj','posx','velx','wrench') else value
                    self.times[key]=self.times['posj'] if key=='posx' else now
                    self.status='READ_FEEDBACK_AVAILABLE'
                except Exception as error:self.status='READ_ERROR: '+str(error)
                self.pending=None;self.index=(self.index+1)%len(self.SERVICES)
            elif now-started>2:
                future.cancel();self.pending=None;self.index=(self.index+1)%len(self.SERVICES);self.status='READ_TIMEOUT_WAITING'
        if self.pending is None:
            key,path,typename,_=self.SERVICES[self.index];client=self.clients[self.index]
            if not client.service_is_ready() or key=='posx' and 'posj' not in self.sample:
                self.status='WAITING_READ_SERVICE: '+path;self.index=(self.index+1)%len(self.SERVICES)
            else:
                request=getattr(self.srv,typename).Request()
                if key=='posx':request.pos=self.sample['posj'];request.ref=0
                if key in ('velx','wrench'):request.ref=0
                self.pending=(key,client.call_async(request),now)
        if self.gripper is not None and now-self.gripper_poll>1:
            self.gripper_poll=now
            try:
                response=self.gripper.read_holding_registers(address=258,count=18,slave=65)
                if response.isError() or len(response.registers)!=18:raise RuntimeError(str(response))
                self.sample.update(gripper_status=response.registers[10],gripper_width_mm=response.registers[9]/10)
                self.times['gripper']=time.monotonic();self.sample.pop('gripper_read_error',None)
            except Exception as error:self.sample['gripper_read_error']=str(error)

    def close(self):
        if self.gripper is not None:self.gripper.close()
        self.node.destroy_node()
        if self.ros.ok():self.ros.shutdown()


def popup(bundle,args):
    if not args.headless and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        raise RuntimeError('팝업은 데스크톱 터미널에서 실행하세요. 이미지 파일은 --headless로 관측 가능합니다.')
    reader=ReadOnlyRos(bundle,args.read_gripper) if args.live else None
    frame=cv2.imread(str(args.image)) if args.image else None
    if args.image and frame is None:raise ValueError('IMAGE_FILE_NOT_READABLE')
    packet=json.loads(args.sample.read_text()) if args.sample else {}
    image_source=source(args.image) if args.image else None
    packet_source=source(args.sample) if args.sample else None
    sample=packet.get('sample');info=packet.get('camera_info');view=args.view
    grid=VirtualBoardGrid(bundle['virtual_grid']);edge=[];axis=[];roi=None;selection=None;clicks=[];revision=0
    pool=ThreadPoolExecutor(max_workers=1);pending=None;captured=None;last_analysis=0;last_wait_log=0
    canvas=np.zeros((480,640,3),np.uint8);report=dict(reason='WAITING_RGB',roll_pitch_observed=False)
    picture=cv2.imread(str(ROOT/'docs/assets/yellow4-challenge-stage1.png'))
    if picture is not None:picture=cv2.resize(picture,(500,214))
    title='Yellow4 READ ONLY - 1 supply / 2 assembly / B ROI / E edge / L axis / SPACE save / ESC close'
    header=270
    def click(event,x,y,flags,param):
        nonlocal selection,roi,edge,axis,clicks,revision,captured
        if event!=cv2.EVENT_LBUTTONDOWN or selection is None or frame is None:return
        y-=header
        if not 0<=x<frame.shape[1] or not 0<=y<frame.shape[0]:return
        clicks.append([x,y])
        if len(clicks)==2:
            if selection=='B':
                a,b=clicks;roi=[min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])]
                if roi[2]<=roi[0] or roi[3]<=roi[1]:roi=None
            elif selection=='E':edge=clicks.copy()
            else:axis=clicks.copy()
            selection=None;clicks=[];revision+=1;captured=None
    if not args.headless:
        cv2.namedWindow(title,cv2.WINDOW_NORMAL);cv2.resizeWindow(title,1200,800);cv2.setMouseCallback(title,click)
    try:
        while True:
            timing=dict(source='LIVE_READ_ONLY' if reader else 'OFFLINE_IMAGE',snapshot_time_unix_s=time.time())
            if not reader:timing.update(input_image=image_source,input_packet=packet_source)
            if reader:
                if not reader.ros.ok():break
                reader.poll();frame=reader.frame;sample=reader.sample.copy();info=reader.info
                timing.update(rgb_stamp_ns=reader.stamp_ns,field_age_s={k:time.monotonic()-v for k,v in reader.times.items()},
                    rgb_age_s=None if reader.rgb_time is None else time.monotonic()-reader.rgb_time,read_status=reader.status)
                if args.headless and captured is None and time.monotonic()-last_wait_log>2:
                    print('관측 대기:',reader.status,'RGB:',frame is not None,'fields:',','.join(sample),flush=True)
                    last_wait_log=time.monotonic()
            if pending is not None and pending[0].done():
                future,data=pending;pending=None
                try:
                    new_canvas,new_report=future.result()
                    if data['view']==view and data['revision']==revision:canvas,report,captured=new_canvas,new_report,data
                except (ValueError,cv2.error) as error:
                    if data['view']==view and data['revision']==revision:
                        canvas=data['frame'].copy();report=dict(reason='DIAGNOSTIC_INPUT_ERROR: '+str(error),roll_pitch_observed=False);captured=data
                last_analysis=time.monotonic()
            live_ready=not (args.headless and reader) or (info is not None and all(k in sample for k in ('posx','tcp','tool','wrench','velx','motion_status')))
            if frame is not None and live_ready and pending is None and (captured is None or time.monotonic()-last_analysis>.15):
                current=sample if sample and 'posx' in sample else None
                if reader and timing['field_age_s'].get('posx',float('inf'))>1:current=None
                if reader and timing['rgb_age_s']>1:
                    report=dict(reason='WAITING_FRESH_RGB',roll_pitch_observed=False);captured=None
                else:
                    data=dict(frame=frame.copy(),sample=None if current is None else current.copy(),info=info,
                        timing=timing.copy(),view=view,revision=revision,submitted_monotonic=time.monotonic())
                    pending=(pool.submit(analyze,data['frame'],bundle,view,sample=data['sample'],info=info,
                        edge=edge.copy(),axis=axis.copy(),roi=roi,stamp_ns=timing.get('rgb_stamp_ns',0),grid=grid),data)
            decision=report.get('supply_decision',{})
            lines=['READ ONLY | no movement / grip commands',f"View: {view} | target: {bundle['target']} | select: {selection}",
                f"Vision attempted: {decision.get('vision_attempted')} recognized: {decision.get('recognized')} XY assist: {decision.get('center_assist_applied')}",
                f"Reason: {report.get('reason') or decision.get('fallback_reason') or decision.get('reason')}",
                f"Pixel yaw difference: {report.get('relative_angle_deg')} deg | actual block roll/pitch: UNKNOWN",
                f"Actual TCP: {None if not sample else sample.get('posx')}",
                f"TCP/tool: {None if not sample else (sample.get('tcp'),sample.get('tool'))} | read status: {timing.get('read_status')}",
                f"Raw wrench (N / Nm): {None if not sample else sample.get('wrench')}",
                f"Gripper width mm: {None if not sample else sample.get('gripper_width_mm')} | error: {None if not sample else sample.get('gripper_read_error')}",
                f"RGB age s: {timing.get('rgb_age_s')} | pose age s: {timing.get('field_age_s',{}).get('posx')}",
                'B/E/L: click TWO endpoints | SPACE: capture | 1/2: view | C: clear | ESC: close']
            ui=np.zeros((canvas.shape[0]+header,canvas.shape[1]+500,3),np.uint8);ui[header:,:canvas.shape[1]]=canvas
            for i,line in enumerate(lines):cv2.putText(ui,line,(10,22+i*23),cv2.FONT_HERSHEY_SIMPLEX,.44,(255,255,255),1)
            if picture is not None:
                height=min(214,canvas.shape[0]);ui[header:header+height,canvas.shape[1]:]=cv2.resize(picture,(500,height))
            for i,line in enumerate(['Stage1 SYNTHETIC geometry only','Orange image axis = pixel selection','3D actual contact axis: pending',f"Grasp: {bundle['grasp_mode']} / {bundle['intended_pad_bottom_height_mm']}mm",'SPACE does not verify grasp height']):
                cv2.putText(ui,line,(canvas.shape[1]+10,header+240+i*25),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
            key=32 if args.headless and captured is not None else -1
            if args.headless:time.sleep(.01)
            if not args.headless:cv2.imshow(title,ui);key=cv2.waitKey(10)&255
            if key==27 or not args.headless and cv2.getWindowProperty(title,cv2.WND_PROP_VISIBLE)<1:break
            if key in (ord('1'),ord('2')):view='supply' if key==ord('1') else 'assembly';edge=[];axis=[];captured=None;revision+=1
            if key in (ord('b'),ord('e'),ord('l')):selection=chr(key).upper();clicks=[]
            if key==ord('c'):edge=[];axis=[];roi=None;selection=None;clicks=[];captured=None;revision+=1
            if key==32 and captured is not None:
                captured['timing']['analysis_age_s']=time.monotonic()-captured['submitted_monotonic']
                out=save_capture(args.output/('capture-'+str(time.time_ns())),captured['frame'],canvas,bundle,report,
                    sample=captured['sample'],info=captured['info'],notes=args.notes,role=args.role,timing=captured['timing'])
                print('관측 저장:',out,flush=True)
                if args.headless:break
    finally:
        pool.shutdown(wait=False,cancel_futures=True)
        if reader:reader.close()
        if not args.headless:cv2.destroyWindow(title)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','observe'))
    parser.add_argument('--config',type=Path,default=ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/observation.json')
    parser.add_argument('--grasp-mode',choices=('standard','human-replacement'))
    parser.add_argument('--measurements',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true');parser.add_argument('--read-gripper',action='store_true')
    parser.add_argument('--image',type=Path);parser.add_argument('--sample',type=Path);parser.add_argument('--headless',action='store_true')
    parser.add_argument('--view',choices=('supply','assembly'),default='supply');parser.add_argument('--notes',default='')
    parser.add_argument('--role',choices=('OBSERVATION','SUPPLY_GRASP_CANDIDATE','SEATED_GRASP_CANDIDATE','CONTACT_AXIS_CANDIDATE'),default='OBSERVATION')
    args=parser.parse_args(argv);settings=json.loads(args.config.read_text())
    if args.grasp_mode:settings['grasp_mode']=args.grasp_mode.upper().replace('-','_')
    bundle=prepare(ROOT,settings,json.loads(args.measurements.read_text()) if args.measurements else None)
    bundle['camera_info_topic']=settings['camera_info_topic']
    if args.command=='prepare':
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(bundle,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps(dict(status=bundle['status'],output=str(args.output),missing_measurements=bundle['missing_measurements'],physical_commands=0),ensure_ascii=False));return 0
    if args.live==bool(args.image):parser.error('observe에는 --live 또는 --image 중 하나를 지정하세요.')
    popup(bundle,args);return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:
        print('읽기 전용 관측 종료 / 로봇 명령 없음',flush=True);raise SystemExit(130)
