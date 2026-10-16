"""Optional native D observation/video hooks; imports Kit only inside GUI calls."""
from pathlib import Path
import json,hashlib,time
import numpy as np


class NativeRunRecording:
    def __init__(self,folder,capture_frame=None,frame_interval_s=.1,maximum_frames=1000):
        self.folder=Path(folder);self.folder.mkdir(exist_ok=False)
        self.clip=None;self.capture_frame=capture_frame;self.interval=frame_interval_s;self.maximum=maximum_frames
        self.events=(self.folder/'native_events.jsonl').open('w');self.rows=(self.folder/'native_samples.jsonl').open('w')
        self.latest_sample=None;self.previous=None;self.last_frame=-float('inf');self.frames=[];self.captures=[]
        self.peak_v=0.;self.peak_a=0.;self.samples=0
    def event(self,kind,payload,stamp):
        self.events.write(json.dumps(dict(kind=kind,payload=payload,stamp_s=stamp))+'\n');self.events.flush()
        if self.clip:self.clip.event(kind,payload,stamp)
    def sample(self,row,statuses):
        stamp=float(row['time_s']);v=np.asarray(row['velocity_rad_s'][:6],float);a=None
        if self.previous:
            dt=stamp-self.previous[0]
            if dt<=0:
                # Preserve the rejected raw row before raising the original guard.
                (self.folder/'nonmonotonic_source.json').write_text(json.dumps(dict(previous_time_s=self.previous[0],current_time_s=stamp,dt_s=dt,current_row=row,native_action_statuses=statuses,wall_monotonic_s=time.monotonic()),indent=2)+'\n')
                raise ValueError('NATIVE_RECORDING_NONMONOTONIC_CLOCK')
            a=((v-self.previous[1])/dt).tolist();self.peak_a=max(self.peak_a,float(abs(np.asarray(a)).max()))
        self.peak_v=max(self.peak_v,float(abs(v).max()));self.previous=(stamp,v);self.samples+=1
        value=dict(row,actual_acceleration_rad_s2=a,acceleration_method='ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE',native_action_statuses=statuses)
        self.rows.write(json.dumps(value)+'\n');self.rows.flush();self.latest_sample=value
        if self.capture_frame and stamp-self.last_frame>=self.interval and len(self.frames)<self.maximum:
            # Keep outstanding captures bounded. The requested SIM stamp is
            # metadata; an asynchronous viewport image is not sensor evidence.
            self.captures=[x for x in self.captures if not x[0].exists()]
            if not self.captures:
                path=self.folder/f'frame_{len(self.frames):05d}.png';capture=self.capture_frame(path)
                request=dict(path=str(path),request_stamp_s=stamp,observed_q_rad=row['q_rad'])
                self.captures.append((path,capture));self.frames.append(request)
                # Append-only actual viewport REQUEST receipts. These stamps do
                # not certify asynchronous image acquisition or Depth timing.
                with (self.folder/'frame_requests.jsonl').open('a') as journal:
                    journal.write(json.dumps(dict(request,frame_index=len(self.frames)-1,
                        scope='ACTUAL_VIEWPORT_REQUEST_NOT_SENSOR_CAPTURE'))+'\n')
                self.last_frame=stamp
        if self.clip:self.clip.sample(row)
    def completed(self,status,packet,*extra):
        result=dict(scope='ACTUAL_NATIVE_D_EXECUTION_OBSERVATION_NOT_Q_SETTER_ANIMATION',native_result=status,trajectory_digest=packet['trajectory_digest'],samples=self.samples,
            native_v_peak_rad_s=self.peak_v,native_v_difference_a_peak_rad_s2=self.peak_a,
            actual_speed_limit_passed=self.peak_v<=.350001,actual_acceleration_limit_passed=self.peak_a<=.700001,
            observation_source_category='PROJECT_TEST_PARAMETER_MODEL_COMPARISON_REPORT_ONLY',SDK_official_observed_speed_acceleration_limits=None,observed_limit_status='OFFICIAL_NOT_DEFINED_NOT_NATIVE_EXECUTION_GATE',
            q_difference_velocity_not_substituted=True,requested_frames=self.frames,
            image_scope='ASYNCHRONOUS_VIEWPORT_VISUAL_RECORD_NOT_SENSOR_OR_COLLISION_CERTIFICATION',hardware_execution_allowed=False)
        (self.folder/'recording_result.json').write_text(json.dumps(result,indent=2)+'\n');return result
    def close(self):
        if self.clip:self.clip.close()
        self.events.close();self.rows.close()


def configure_view(stage,T_world_base,obstacle_xyz,start_xyz,goal_xyz):
    from pxr import UsdGeom,Gf
    from omni.kit.viewport.utility import get_active_viewport,capture_viewport_to_file
    camera=UsdGeom.Camera.Define(stage,'/World/FixedAvoidanceView');op=camera.AddTransformOp();camera.CreateFocalLengthAttr(24)
    camera.CreateClippingRangeAttr(Gf.Vec2f(.001,100))
    base=np.asarray(T_world_base);center=(base@np.r_[(np.asarray(start_xyz)+goal_xyz)/2+[0,0,.1],1])[:3]
    eye=center+np.array([-.45,-.95,.7]);op.Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*center),Gf.Vec3d(0,0,1)).GetInverse())
    viewport=get_active_viewport();viewport.set_active_camera(str(camera.GetPath()))
    return lambda path:capture_viewport_to_file(viewport,str(path))
