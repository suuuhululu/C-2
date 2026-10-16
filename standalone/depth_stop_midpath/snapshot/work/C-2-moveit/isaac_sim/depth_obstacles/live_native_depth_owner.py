"""One native D's Depth/cancel/rolling-HOLD adapter; no SDK or ActionClient."""
from copy import deepcopy
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,uuid,time
import numpy as np

from plan_only import digest,JOINTS
from sim_utils import save,pose_matrix,matrix_pose
from capture_sim_scene import verified_stop,command_counts,read_scene_geometry
from isaac_sim.real_execution.native_boundary import (
    NativeOnlineIPC,LIVE_IDENTITY,OWNER_KEYS,remaining_volume_depth_risk,
)

DEPTH_VISIBILITY=dict(min_visible_pixels=16,min_pixel_span=3)


def partial_visibility(sensor):
    """Same visibility policy; a newer partial frame cannot borrow an old bound."""
    pixels=np.asarray(sensor['projected']['pixel_uv']);height,width=sensor['image']['depth'].shape
    if (pixels.ndim!=2 or pixels.shape[1:]!=(2,) or not np.isfinite(pixels).all() or
            len(pixels)!=len(sensor['projected']['points_base_m']) or len(pixels)<DEPTH_VISIBILITY['min_visible_pixels']):return True
    return bool(np.any(np.ptp(pixels,axis=0)<DEPTH_VISIBILITY['min_pixel_span']) or
        pixels[:,0].min()<=0 or pixels[:,1].min()<=0 or pixels[:,0].max()>=width-1 or pixels[:,1].max()>=height-1)


def ref(path):
    path=Path(path);return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def observe_depth_geometry(projected,shape,prior,*,range_m,fk_error,age_s):
    """Only missing/clipped visibility becomes UNKNOWN; other guards still fail."""
    from depth_obstacle_envelope import bounded_geometry
    points=np.asarray(projected['points_base_m']);pixels=np.asarray(projected['pixel_uv'])
    try:
        return bounded_geometry(points,pixels,shape,prior,range_m=range_m,fk_error=fk_error,age_s=age_s),None
    except ValueError as exc:
        reason=str(exc)
        valid_arrays=(points.ndim==2 and points.shape[1:]==(3,) and
            pixels.shape==(len(points),2) and np.isfinite(points).all() and np.isfinite(pixels).all())
        empty=(points.size==0 and pixels.size==0)
        if ((reason=='INSUFFICIENT_OR_CLIPPED_VISIBILITY' and valid_arrays) or
                (reason=='UNOBSERVABLE' and empty)):
            return None,reason
        raise


class LiveNativeDepthOwner:
    """Initial transport uses the pinned fixed curve; a resumed curve never does.

    No actual worker job is published until current new model/request/cache
    inputs exist. The first execution unit remains in observed normal HOLD.
    """
    def __init__(self,out,request,packet,session,model,profile):
        self.out=Path(out);self.request=request;self.session=session;self.model=Path(model);self.profile=Path(profile)
        self.depth=None;self.environment=None;self.last=None;self.hold=None;self.status=None
        self.rows=deque(maxlen=480);self.PVA=deque(maxlen=480);self.risk_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='remaining-volume')
        self.admission_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='D-prepared-admission')
        self.publication_lock_skips=0
        self.risk_future=None;self.risk_input=None;self.volume=None;self.wire=None
        self.ipc=None;self.last_publish_seq=None;self.last_publish_key=None;self.stop_started=None
        self.goal_start_stamp_s=None;self.accepted_ref=None
        self.bootstrap_saved=False;self.publication_count=0;self.latest_complete_sensor=None
        self.pending=dict(reason='FRESH_LIVE_MODEL_REQUEST_CACHE_JOB_NOT_YET_AVAILABLE',SDK_started=False,resume_executed=False)
        self.initial_packet=packet;self.resume_sender=None;self.resume_adoption_future=None;self.ready_resume_adoption=None;self.prepared_admission=None
        self.camera_preview_future=None;self.camera_preview_count=0;self.camera_preview_last_s=-float('inf');self.camera_preview_UI=None

    def task_event(self,kind,**fields):
        row=self.last
        record=dict(kind=kind,wall_monotonic_s=time.monotonic(),native_source_clock_s=None if row is None else row['time_s'],
            physics_step=None if row is None else row['tracking']['physics_step'],
            canonical_source_stamp_s=None if self.latest_complete_sensor is None else self.latest_complete_sensor['frame']['source_stamp_s'],
            publication_lock_skips=self.publication_lock_skips,**fields)
        with (self.out/'CPU_queue_timeline.jsonl').open('a') as f:f.write(json.dumps(record,allow_nan=False)+'\n')

    def attach(self,args,runtime,app,stage,world,robot,tick,seed,motion,controls,sample,statuses,folder,model):
        from .live_depth_stop import configure
        self.runtime=runtime;self.args=args
        args.dynamic_session_id=self.session;args.dynamic_speed_m_s=0. if getattr(args,'static_depth_replan',False) else .001
        revision=self.request['world_revision']
        if type(revision) is not int or revision<0:raise ValueError('LIVE_WORLD_REVISION_REQUIRED')
        args.live_scene_motion_kind='STATIC_OBSTACLE' if getattr(args,'static_depth_replan',False) else 'DYNAMIC_OBSTACLE'
        args.live_world_revision=revision
        args.dynamic_read_geometry=lambda:read_scene_geometry(stage,seed)[0]
        args.dynamic_stimulus_segment=self.stimulus_segment
        args.dynamic_remaining_volume_risk=self.risk
        self.writer_bundle_count=0;self.sensor_bundle_jobs=[]
        args.dynamic_capture_writer_bundle=self.capture_writer_bundle
        args.dynamic_complete_writer_bundle=self.complete_writer_bundle
        args.dynamic_camera_preview=self.capture_camera_preview
        self.depth=configure(args,runtime,preserve_existing=True)
        self.depth['install'](app,stage,world,robot,tick,seed,motion,controls,sample,statuses,folder,model)
        self.environment=dict(app=app,stage=stage,world=world,robot=robot,tick=tick,seed=seed,motion=motion,controls=controls,sample=sample,statuses=statuses)
        if getattr(args,'show_wrist_camera',False):self.setup_camera_preview()
        runtime.fixed_obstacle_prim_paths.append(self.depth['env']['obstacle_path'])
        previous=runtime.transport_hooks['event']
        def event(kind,payload,stamp):
            previous(kind,payload,stamp)
            if kind=='GOAL_ACCEPTED' and payload['accepted']:
                if payload.get('goal_stamp_ns') is None:raise ValueError('ACTUAL_ACCEPTED_GOAL_START_STAMP_REQUIRED')
                self.goal_start_stamp_s=payload['goal_stamp_ns']/1e9
                self.bind_accepted(payload['goal_id'])
        runtime.transport_hooks['event']=event
        previous_sample=runtime.transport_hooks['sample']
        def sample(row,statuses):
            previous_sample(row,statuses)
            self.last=deepcopy(row);self.rows.append(deepcopy(row))
            self.poll_camera_preview()
            pva=self.depth['work']['previous_sample']
            if pva['a_rad_s2'] is not None:self.PVA.append(deepcopy(pva))
            self.poll_risk(row,statuses)
        runtime.transport_hooks['sample']=sample
        runtime.live_transport=self
        # Existing owner must expose its SAME client/lock and monitoring
        # callbacks. Missing capability remains HOLD; no substitute client.
        runtime.transport_hooks['bind_resume_sender']=self.bind_resume_sender
        limits=dict(scope='CPU_D_BOUNDARY_REVIEW_LIMITS',max_state_age_s=.12,min_stop_observation_s=.5,criteria_sources={})
        for key,unit in [('max_stop_velocity_rad_s','rad/s'),('max_stop_acceleration_rad_s2','rad/s^2'),('q_tolerance_rad','rad'),('v_tolerance_rad_s','rad/s'),('a_tolerance_rad_s2','rad/s^2')]:
            limits[key]=None
            limits['criteria_sources'][key]=dict(value=None,unit=unit,source_category='OFFICIAL_NOT_DEFINED',check_mode='REPORT_ONLY',runtime_version='standalone cuMotion1.1.0',reference='https://nvidia-isaac.github.io/cumotion/api/python_api.html')
        limits['criteria_sources'].update(max_state_age_s=dict(value=.12,unit='s',source_category='EXPLICIT_SIM_SENSOR_FRESHNESS_POLICY',reference=ref(self.out/'moving_obstacle.script.json')),
            min_stop_observation_s=dict(value=.5,unit='s',source_category='EXISTING_CURRENT_NATIVE_WINDOW_POLICY',reference=ref(self.out/'loaded_sources/live_native_depth_owner.py')))
        save(self.out/'selected_owner_review_limits.json',limits);self.owner_review_limits=ref(self.out/'selected_owner_review_limits.json')
        self.bootstrap_capture()

    def setup_camera_preview(self):
        try:
            import omni.ui as ui
            window=ui.Window('Seeun / Wrist RGB + Depth / actual sensor',width=880,height=330)
            with window.frame:
                with ui.VStack():
                    label=ui.Label('Waiting for actual wrist camera frames',height=35)
                    with ui.HStack():
                        with ui.VStack():
                            ui.Label('RGB / original annotator pixels',height=25);rgb=ui.Image('',width=424,height=240)
                        with ui.VStack():
                            ui.Label('Depth metres / near white / invalid black',height=25);depth=ui.Image('',width=424,height=240)
            self.camera_preview_UI=(window,label,rgb,depth)
        except Exception as exc:save(self.out/'camera_preview_UI_error.json',dict(error=str(exc),visual_only=True))

    def capture_camera_preview(self,image,env,camera_path):
        # Reuse the bounded existing CPU worker; never block rendering/physics
        # on PNG encoding, accumulate queued jobs, or create a new sensor.
        if self.camera_preview_count>=1000 or image['source_stamp_s']-self.camera_preview_last_s<.1:return
        if self.camera_preview_future is not None:return
        from .camera_preview import save_preview
        folder=self.out/'camera_preview'/f'{self.camera_preview_count:05d}'
        self.camera_preview_count+=1;self.camera_preview_last_s=image['source_stamp_s']
        self.camera_preview_future=self.risk_pool.submit(save_preview,folder,image,self.session,camera_path)

    def poll_camera_preview(self):
        future=self.camera_preview_future
        if future is None or not future.done():return
        self.camera_preview_future=None
        try:
            result=future.result()
            temp=self.out/'camera_preview.pointer.tmp';save(temp,result);temp.replace(self.out/'camera_preview.pointer.json')
            if self.camera_preview_UI is not None:
                _,label,rgb,depth=self.camera_preview_UI
                label.text=f"{self.session} / actual source SIM {result['source_stamp_s']:.4f}s / renderer {result['renderer_frame_id']}"
                if result['rgb'] is not None:rgb.source_url=result['rgb']['path']
                depth.source_url=result['depth_display']['path']
        except Exception as exc:save(self.out/'camera_preview_error.json',dict(error=str(exc),visual_only=True,SDK_admitted=False))

    def capture_writer_bundle(self,image,env):
        if self.status is None or any(not job.done() for job in self.sensor_bundle_jobs):return
        from .live_sensor_bundle import capture
        row=self.environment['sample']()
        objects=self.args.dynamic_read_geometry()
        selected=next(o for o in objects if o['id']==self.request['planning_snapshot']['selected_slot_id'])
        selected=deepcopy(selected);selected['role']='HELD_BLOCK'
        context=dict(held_geometry=selected,grip_rad=row['grip_rad'],attachment=row['attachment'])
        folder=self.out/'writer_sensor_raw'/f'{self.writer_bundle_count:03d}'
        manifest=capture(folder,image,env,row,context,self.out/'executed_live_depth_stop.py',self.profile)
        image['writer_raw_folder']=str(folder);image['writer_source_observation']=deepcopy(row)
        self.writer_bundle_count+=1
        save(self.out/'writer_sensor_raw.pointer.json',dict(manifest=manifest,status='ACTUAL_WRITER_RAW_PENDING_SOURCE_TICK_REVIEW',SDK_admitted=False))

    def complete_writer_bundle(self,image,matched,frame,limits):
        """Require independent writer/physics/ROS clock equality, not nearest time."""
        from .live_sensor_bundle import complete
        folder=Path(image['writer_raw_folder'])
        # Pure CPU validation works on the immutable writer snapshot off the
        # native physics path. It does not invent STOP or start an SDK worker.
        image=deepcopy(image);matched=deepcopy(matched);frame=deepcopy(frame);queued_wall=time.monotonic()
        def build():
            started_wall=time.monotonic()
            self.task_event('SENSOR_CANONICAL_START',frame_seq=frame['frame_seq'],queued_wall_monotonic_s=queued_wall,queue_wait_wall_s=started_wall-queued_wall)
            result=complete(folder,image,matched,frame,limits,self.model)
            if result.get('inventory',{}).get('status')!='ORIGINAL_MODEL_AND_NATIVE_HELD_PIECES_VERIFIED':
                save(folder/'consumer_completion_review.json',result);return result
            from .complete_sensor_bundle import package
            try:
                result=package(folder,self.model,folder/'canonical_sensor',self.args.root,state_required=False)
            except (ValueError,KeyError,FileNotFoundError) as exc:
                result=dict(status='HOLD_SENSOR_COMPLETION',reason=str(exc),execution_allowed=False)
            save(folder/'consumer_completion_review.json',result)
            if result.get('status')=='SENSOR_BUNDLE_REPLAYED_CPU':
                from .prepare_static_prior import prepare
                from depth_obstacle_envelope import build_envelope,verify_bound
                from prepare_cpu_model import read_model_bundle
                canonical=folder/'canonical_sensor'
                try:
                    prior=prepare(self.out,canonical,self.args.root/'work/C-2-moveit/isaac_sim/config/live_static_depth_trial.policy.json',folder/'static_prior')
                    spec=json.loads((canonical/'evidence_spec.json').read_text());spec['prior_sha256']=prior['sha256']
                    save(folder/'evidence_spec_with_prior.json',spec)
                    context=json.loads((canonical/'geometry_context.json').read_text())
                    model=read_model_bundle(self.model);now=self.last['time_s']
                    bound=build_envelope(spec,prior['path'],model,context,now_s=now)
                    verify_bound(bound,model,now_s=self.last['time_s'])
                    save(folder/'canonical_bound.json',bound)
                    # Atomic replacement preserves both image source time and
                    # the original raw sensor; current D state remains separate.
                    self.latest_complete_sensor=dict(frame=json.loads((canonical/'frame.json').read_text()),
                        projected=json.loads((canonical/'candidates.json').read_text()),image=image,matched=matched,
                        self_mask=np.load(canonical/'self_mask.npy',allow_pickle=False),held_mask=np.load(canonical/'held_mask.npy',allow_pickle=False),
                        obstacle_mask=np.load(canonical/'obstacle_mask.npy',allow_pickle=False),canonical_bound=bound)
                except (ValueError,KeyError,FileNotFoundError) as exc:
                    save(folder/'canonical_bound_review.json',dict(status='HOLD_CURRENT_CANONICAL_BOUND',reason=str(exc),source_stamp_s=frame['source_stamp_s'],actual_now_s=self.last['time_s']))
                    return result
                completion_source_time=self.last['time_s']
                pointer_temp=self.out/('canonical_sensor.pointer.'+uuid.uuid4().hex+'.tmp')
                save(pointer_temp,dict(evidence_spec=ref(folder/'evidence_spec_with_prior.json'),bound=ref(folder/'canonical_bound.json'),prior=prior,
                    source_stamp_s=frame['source_stamp_s'],frame_seq=frame['frame_seq'],session_id=self.session,
                    status='SENSOR_REPLAY_COMPLETE_SEPARATE_CURRENT_STOP_AND_PRIOR_JOB_ADMISSION_REQUIRED',
                    current_source_time_at_completion_s=completion_source_time,source_age_at_completion_s=completion_source_time-frame['source_stamp_s'],queue_wait_wall_s=started_wall-queued_wall,CPU_completion_wall_s=time.monotonic()-started_wall,SDK_admitted=False,execution_allowed=False))
                pointer_temp.replace(self.out/'canonical_sensor.pointer.json')
                self.task_event('SENSOR_CANONICAL_COMPLETE',frame_seq=frame['frame_seq'],source_stamp_s=frame['source_stamp_s'],completion_age_s=completion_source_time-frame['source_stamp_s'],CPU_wall_s=time.monotonic()-started_wall)
            return result
        self.sensor_bundle_jobs=[job for job in self.sensor_bundle_jobs if not job.done()]
        self.task_event('SENSOR_CANONICAL_QUEUED',frame_seq=frame['frame_seq'])
        def observed_build():
            try:return build()
            finally:self.task_event('SENSOR_CANONICAL_END',frame_seq=frame['frame_seq'])
        self.sensor_bundle_jobs.append(self.risk_pool.submit(observed_build))

    def bootstrap_capture(self):
        """Save one real running-source model-bootstrap frame; not obstacle STOP."""
        import omni.timeline
        from d_sim_transport import check_live,FINGERS
        from prepare_gpu_scene import inspect_gpu_inputs
        e=self.environment;timeline=omni.timeline.get_timeline_interface();timeline.play();start=e['world'].current_time
        window=deque();last_loaded={};monitor=dict(self.initial_packet,attachment=self.request['attachment'])
        folder=self.out/'live_post_grasp_bootstrap';folder.mkdir()
        while e['world'].current_time-start<4.:
            e['tick']();row=e['sample']()
            for name in row['contact_fingers']:last_loaded[name]=row['time_s']
            row['contact_last_loaded_s']=dict(last_loaded)
            self.runtime.transport_hooks['sample'](row,e['statuses']);window.append(deepcopy(row))
            while row['time_s']-window[0]['time_s']>1.2:window.popleft()
            sensor=self.depth['work'].get('latest_sensor')
            if sensor is None or not (sensor['self_mask'].any() and sensor['held_mask'].any()):continue
            stamp=sensor['matched']['stamp_s'];rows=[r for r in window if stamp-1.<=r['time_s']<=stamp]
            if len(rows)<2 or rows[-1]['time_s']-rows[0]['time_s']<.6:continue
            counts=sensor['matched']['command_counts']
            if any(counts.values()):continue
            metrics=verified_stop(rows)
            for r in rows:check_live(monitor,monitor['binding'],r,contact_grace_s=.02)
            observed=sensor['matched']['raw_observation']
            scene=json.loads((self.out/'capture/scene.json').read_text());state=json.loads((self.out/'capture/post_grasp_state.json').read_text())
            capture_id=str(uuid.uuid4());captured=datetime.now(timezone.utc).isoformat()
            common=dict(capture_id=capture_id,captured_at=captured,source_stamp_s=stamp)
            scene.update(common,world_objects=deepcopy(sensor['matched']['world_objects']),frame_alignment=dict(world_frame_id='world',base_frame_id='base_link',T_world_base=sensor['matched']['T_world_base'],evidence_ref=str(folder/'source_tick.json')))
            slot=self.request['planning_snapshot']['selected_slot_id']
            next(o for o in scene['world_objects'] if o['id']==slot)['role']='HELD_BLOCK'
            controls=dict(source_kind='ISAAC_SIM_SAVED_STATE',evidence_ref=str(folder/'verified_hold.json'),a_context=state['a_context'],reservation_binding=state['reservation_binding'],current_revision=scene['current']['current_revision'],timeline_paused=False,timeline_running=timeline.is_playing(),holding_confirmed=True,stopped_verified=True,virtual_attachment_used=False,grasp_kind='DYNAMIC_CONTACT_GRASP',stop_observation_duration_s=rows[-1]['time_s']-rows[0]['time_s'],position_observations=rows,**counts,capture_boundary='LIVE_POST_GRASP_MODEL_BOOTSTRAP_HOLD_NOT_OBSTACLE_STOP',verification_method='EXISTING_D_VERIFIED_STOP_AND_CURRENT_CONTACT_HISTORY_NO_PENDING_COMMANDS',stop_metrics=metrics)
            state.update(common,q_rad=observed['q_rad'],grip_rad=observed['grip_rad'],tcp_pose=observed['tcp_pose'],attachment_tcp_to_block=observed['attachment'],raw_joint_velocity_rad_s=observed['velocity_rad_s'],holding_confirmed=True,stopped_verified=True,**counts,observation_evidence=controls)
            for name,value in [('scene',scene),('post_grasp_state',state),('verified_hold',controls),('source_tick',sensor['matched']),('frame',sensor['frame']),('camera_params',sensor['image']['params']),('semantic_info',sensor['image']['info'])]:save(folder/(name+'.json'),value)
            for name,data in [('depth',sensor['image']['depth']),('semantic_ids',sensor['image']['ids']),('self_mask',sensor['self_mask']),('held_mask',sensor['held_mask'])]:np.save(folder/(name+'.npy'),data,allow_pickle=False)
            _,checks=inspect_gpu_inputs(e['motion'],folder/'scene.json',folder/'post_grasp_state.json',self.model)
            save(folder/'existing_CPU_input_checks.json',checks)
            save(folder/'inputs.json',dict(scope='ACTUAL_POST_GRASP_RUNNING_SOURCE_MODEL_BOOTSTRAP_NOT_OBSTACLE_STOP',scene=ref(folder/'scene.json'),state=ref(folder/'post_grasp_state.json'),motion_request=ref(self.out/'prepared_input/motion.request.json'),model_manifest=ref(self.model/'MODEL_MANIFEST.json'),camera_profile=ref(self.profile),frame=ref(folder/'frame.json'),source_tick=ref(folder/'source_tick.json'),verified_hold=ref(folder/'verified_hold.json'),timeline_running=True,source_clock_advanced_during_capture=True,SDK_started=False,obstacle_STOP_claimed=False,GT_and_old_Dynamic_obstacles_not_future_planner_inputs=True,hardware_execution_allowed=False))
            self.bootstrap_rows=deepcopy(list(window));self.bootstrap_saved=True;return
        raise ValueError('NO_SOURCE_COHERENT_VERIFIED_MODEL_BOOTSTRAP_FRAME')

    def prepare_wire(self,wire):
        if self.wire is not None:
            if self.wire!=wire:raise ValueError('INITIAL_LIVE_WIRE_CHANGED')
            return
        from isaac_sim.real_execution.remaining_volume import RemainingVolume
        self.wire=deepcopy(wire)
        # Precompute before dispatch; no CPU interval FK in the native tick.
        self.volume=RemainingVolume(self.request,self.wire)

    def bind_accepted(self,goal_id):
        if self.volume is None:raise ValueError('REMAINING_VOLUME_NOT_PRECOMPUTED')
        binding=dict(scope='ACCEPTED_NATIVE_GOAL_BINDING',goal_id=goal_id,goal_version=self.depth['state']['goal_version'],
            session_id=self.session,clock_basis='SIM_TIME',clock_epoch=0,goal_start_stamp_s=self.goal_start_stamp_s,
            **self.volume.geometry_binding)
        path=self.out/('accepted_transport_binding.json' if self.depth['state']['goal_version']==1 else 'accepted_transport_binding.'+str(self.depth['state']['goal_version'])+'.json');save(path,binding);self.accepted_ref=ref(path)
        self.volume.bind(self.accepted_ref)

    def stimulus_segment(self,row,env,work):
        from prepare_cumotion_model import urdf_transforms,TCP
        import xml.etree.ElementTree as ET
        camera=np.asarray(self.depth['states'][-1]['T_world_camera'])
        base=np.asarray(self.depth['states'][-1]['T_world_base'])
        optical_world=camera@np.diag([1.,-1.,-1.,1.])
        robot=ET.fromstring(self.request['model_bundle']['robot_description'])
        elapsed=row['time_s']-work['start_stamp'];intr=env['profile']['intrinsics'];chosen=None
        old_point=None
        for future in np.arange(1.2,4.1,.1):
            point=min(self.wire['points'],key=lambda p:abs(p['time_from_start_s']-(elapsed+future)))
            tcp=urdf_transforms(robot,point['positions_rad'],row['grip_rad'])[TCP]
            centre=(base@tcp@np.asarray(row['attachment']))[:3,3]
            p=np.linalg.inv(optical_world)@np.r_[centre,1.]
            if p[2]<=.02:continue
            u=intr['fx']*p[0]/p[2]+intr['cx'];v=intr['fy']*p[1]/p[2]+intr['cy']
            if 24<u<intr['width']-24 and 24<v<intr['height']-24:chosen=centre;old_point=point;break
        if chosen is None:raise ValueError('NO_VISIBLE_FORWARD_BODY_STIMULUS_POINT')
        axis=optical_world[:3,0];start=chosen-.0075*axis;end=chosen+.0075*axis
        shift=getattr(self.args,'obstacle_path_shift_m',0.)
        if shift:
            # Scenario layout ONLY. Choose an actual later body-centre path
            # sample, not a World straight-line offset or planner GT input.
            from sim_utils import pose_matrix
            old_index=self.wire['points'].index(old_point);previous=chosen.copy();arc=0.;candidates=[];fov_rejections=[]
            audit_FOV_only=shift>.15
            arc_lower,arc_upper=(shift-.02,shift+.02) if audit_FOV_only else (.08,.15)
            cube_offsets=np.array([[x,y,z] for x in (-.01,.01) for y in (-.01,.01) for z in (-.01,.01)])
            goal=self.wire['points'][-1]
            goal_centre=(base@urdf_transforms(robot,goal['positions_rad'],row['grip_rad'])[TCP]@np.asarray(row['attachment']))[:3,3]
            boxes=[]
            for obj in self.depth['states'][-1]['world_objects']:
                if obj['id']==self.request['planning_snapshot']['selected_slot_id'] or obj['id'].startswith('Dynamic_'):continue
                transform=pose_matrix(obj['world_pose']) if 'world_pose' in obj else base@pose_matrix(obj['pose'])
                # Conservative World AABB, including stud height, used only to
                # avoid placing the demo cube into existing scene furniture.
                size=np.asarray(obj['size_m']);low=-size/2;high=size/2
                if obj.get('studs'):high[2]=max(high[2],.014)
                corners=np.array([[x,y,z,1.] for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])])
                world=(transform@corners.T).T[:,:3];boxes.append((obj['id'],world.min(axis=0),world.max(axis=0)))
            for index in range(old_index+1,len(self.wire['points'])):
                point=self.wire['points'][index]
                centre=(base@urdf_transforms(robot,point['positions_rad'],row['grip_rad'])[TCP]@np.asarray(row['attachment']))[:3,3]
                arc+=float(np.linalg.norm(centre-previous));previous=centre
                # Scan the complete accepted body path, retaining full length
                # in the audit; the requested30cm window is NOT the old10cm.
                if not arc_lower<=arc<=arc_upper:continue
                overlaps=[name for name,lo,hi in boxes if np.all(centre+.01>=lo) and np.all(centre-.01<=hi)]
                if overlaps or float(np.linalg.norm(centre-goal_centre))<.04:continue
                # Layout preview only: all eight corners must project inside
                # the unchanged image, in addition to the original centre FOV
                # screen. Actual later Depth/masks still need original replay.
                corners=(np.linalg.inv(optical_world)@np.c_[centre+cube_offsets,np.ones(8)].T).T[:,:3]
                if np.any(corners[:,2]<=.02):
                    if audit_FOV_only:
                        projection=dict(uv_min=None,uv_max=None,camera_z_min_m=float(corners[:,2].min()),edge_margin_pixels=None,status='OUTSIDE_FORWARD_CUE_FOV_AUDIT_ONLY')
                        candidates.append((abs(arc-shift),index,arc,centre.copy(),projection))
                    continue
                uv=np.c_[intr['fx']*corners[:,0]/corners[:,2]+intr['cx'],intr['fy']*corners[:,1]/corners[:,2]+intr['cy']]
                mid=np.linalg.inv(optical_world)@np.r_[centre,1.]
                u=intr['fx']*mid[0]/mid[2]+intr['cx'];v=intr['fy']*mid[1]/mid[2]+intr['cy']
                projection=dict(uv_min=uv.min(axis=0).tolist(),uv_max=uv.max(axis=0).tolist(),
                    camera_z_min_m=float(corners[:,2].min()),edge_margin_pixels=float(min(uv[:,0].min(),uv[:,1].min(),intr['width']-1-uv[:,0].max(),intr['height']-1-uv[:,1].max())))
                if not audit_FOV_only and not (24<u<intr['width']-24 and 24<v<intr['height']-24 and projection['edge_margin_pixels']>1.):
                    fov_rejections.append(dict(index=index,arc_shift_m=arc,projection=projection));continue
                candidates.append((abs(arc-shift),index,arc,centre.copy(),projection))
            total_path_arc_from_nearpoint=arc
            if not candidates:raise ValueError('NO_REQUESTED_ARC_WINDOW_PATH_POINT_CLEAR_OF_SCENE_AND_GOAL')
            _,index,arc,centre,projection=min(candidates,key=lambda x:x[0]);point=self.wire['points'][index]
            prior_start=start.copy();old_centre=chosen.copy();start=centre;end=centre+.015*axis
            save(self.out/'farther_obstacle_placement.audit.json',dict(scope='STATIC_DEMO_LAYOUT_AND_POSTHOC_AUDIT_NOT_PLANNER_INPUT',
                prim_path='/World/DepthStopStimulus',size_m=[.02]*3,requested_path_arc_shift_m=shift,
                actual_sampled_body_path_arc_shift_m=arc,path_arc_error_from_requested_m=arc-shift,
                path_arc_window_m=[arc_lower,arc_upper],total_body_path_arc_from_original_nearpoint_m=total_path_arc_from_nearpoint,
                distance_basis='ACCEPTED_Q_PVT_TRAJECTORY_TO_MODEL_TCP_FK_TIMES_ACTUAL_TCP_TO_HELD_BODY_TRANSFORM_WORLD_METRES',
                initial_cue_FOV_used_as_rejection=not audit_FOV_only,old_path_index=old_index,new_path_index=index,
                old_path_time_s=old_point['time_from_start_s'],new_path_time_s=point['time_from_start_s'],
                old_path_body_centre_world_m=old_centre.tolist(),old_static_start_world_m=prior_start.tolist(),
                new_path_body_centre_world_m=centre.tolist(),new_static_start_world_m=start.tolist(),
                old_to_new_world_distance_m=float(np.linalg.norm(start-prior_start)),
                source_wire=ref(self.out/'actual_native_wire.json'),model_manifest_sha256=self.request['model_bundle']['manifest_sha256'],
                actual_grip_rad=row['grip_rad'],actual_attachment_tcp_to_block=row['attachment'],
                T_world_base=base.tolist(),original_goal=self.request['goal'],cue_elapsed_s=elapsed,
                goal_centre_clearance_m=float(np.linalg.norm(centre-goal_centre)),
                layout_prefilter='CONSERVATIVE_STATIC_WORLD_AABB_NO_FULL_PATH_COLLISION_CERTIFICATION',
                static_world_pose=True,original_trigger_delay_s=.8,forced_detection_delay=False,
                cube_corner_projection_at_cue=projection,T_world_camera_optical=optical_world.tolist(),
                original_camera_intrinsics=intr,scene_only_FOV_rejected_candidates=fov_rejections,
                full_Depth_visibility_verified=False,projection_is_not_actual_Depth_admission=True,
                initial_visibility_required=False,GT_to_planner=False,full_FCL_and_remaining_volume_unchanged=True))
        return start,end

    def risk(self,projected,row,counts,state,work):
        pending=dict(risk=False,status='WAIT_ASYNC_REMAINING_VOLUME_NOT_WORLD_CLEAR',execution_allowed=False)
        if self.risk_future is not None:return pending
        refs=row.get('tracking',{}).get('controller_states',[])
        if not refs or self.volume is None:return pending
        r=refs[-1];ns=r['reference'].get('time_from_start_ns')
        if ns is None:raise ValueError('ACTUAL_CONTROLLER_REFERENCE_NS_REQUIRED')
        if r['header_ns']/1e9<self.goal_start_stamp_s:return pending
        owner=dict(goal_id=state['goal_id'],goal_version=state['goal_version'],session_id=self.session,clock_basis='SIM_TIME',clock_epoch=0,
            goal_start_stamp_s=self.goal_start_stamp_s,active_wire_digest=digest(self.wire),model_digest=self.request['model_digest'],
            selected_block_id=self.request['planning_snapshot']['selected_slot_id'],mode='TRANSPORT',**counts,
            user_stop_latched=state['user_stop_latched'],failure_latched=state['failure_latched'],outcome_unknown=state['outcome_unknown'],
            q_rad=deepcopy(row['q_rad']),grip_rad=row['grip_rad'],attachment_tcp_to_block=deepcopy(row['attachment']),
            holding_confirmed=row['contact_fingers']==['rg2_left_inner_finger','rg2_right_inner_finger'],contact_fingers=deepcopy(row['contact_fingers']),
            trajectory_progress_ns=ns,trajectory_progress_s=ns/1e9,progress_stamp_s=row['time_s'],state_stamp_s=row['time_s'],now_s=row['time_s'],
            progress_source='ACCEPTED_CONTROLLER_REFERENCE',raw_controller_reference=r,raw_reference_header_stamp_s=r['header_ns']/1e9)
        if not owner['holding_confirmed']:return pending
        self.risk_input=dict(projected=deepcopy(projected),owner=owner,sensor=self.depth['work']['latest_sensor'])
        self.risk_future=self.risk_pool.submit(self.volume.remaining,owner)
        return pending

    def poll_risk(self,row,statuses):
        if self.risk_future is None or not self.risk_future.done():return
        item=self.risk_input;volume=self.risk_future.result();self.risk_future=None;self.risk_input=None
        work=self.depth['work'];state=self.depth['state'];counts=command_counts(statuses)
        if work['trigger'] is not None or counts['active_command_count']<=0:return
        if row['time_s']-item['projected']['source_stamp_s']>.12:
            self.depth['event']('ASYNC_RISK_DROPPED_STALE_NOT_CLEAR',dict(source_stamp_s=item['projected']['source_stamp_s']),row['time_s']);return
        owner=dict(item['owner'],now_s=row['time_s'],**counts)
        result=remaining_volume_depth_risk(item['projected'],volume,owner,max_age_s=.12,max_pose_skew_s=.001)
        self.depth['event']('DEPTH_REMAINING_VOLUME_RESULT',result,row['time_s'])
        if not result['risk']:return
        work['trigger']=dict(source_stamp_s=item['projected']['source_stamp_s'],remaining_volume_risk=result)
        state.update(stop_reason='OBSTACLE_RESPONSE_HOLD',snapshot_version=1,snapshot_digest=item['projected']['digest'])
        folder=self.out/'depth_trigger';folder.mkdir()
        sensor=item['sensor']
        for key,data in [('depth',sensor['image']['depth']),('semantic_ids',sensor['image']['ids']),('self_mask',sensor['self_mask']),('held_mask',sensor['held_mask']),('obstacle_mask',sensor['obstacle_mask'])]:np.save(folder/(key+'.npy'),data,allow_pickle=False)
        save(folder/'frame.json',sensor['frame']);save(folder/'candidates.json',item['projected']);save(folder/'remaining_volume.json',volume);save(folder/'risk.json',result)

    def begin_hold(self,status,packet,request,history):
        goal_id=self.depth['state']['goal_id'];counts=status['native_command_counts']
        if not (status['error']=='OBSTACLE_RESPONSE_HOLD' and self.depth['work']['trigger'] is not None and status['stop_verified'] and status['holding_confirmed'] and status.get('native_action_result',{}).get('status')==5 and status['native_action_result']['error_code']==0 and self.depth['work']['cancel_pending']==0 and all(type(v) is int and v==0 for v in counts.values()) and any(a['done'] and a['return_code']==0 and goal_id in a['goals_canceling_ids'] for a in status['cancellation'])):
            raise ValueError('ACTUAL_SAME_UUID_CANCEL_STOP_HOLD_REQUIRED')
        verified_stop(history)
        self.status=deepcopy(status);self.packet=packet;self.active_request=request;self.stop_started=history[0]['time_s']
        state=self.depth['state'];state.update(mode='OBSTACLE_HOLD',stop_reason='OBSTACLE_RESPONSE_HOLD')
        save(self.out/'actual_depth_cancel_hold.json',dict(scope='ACTUAL_NATIVE_D_DEPTH_CANCEL_AND_VERIFIED_HOLD_NOT_RESUME',native_status=status,goal_id=state['goal_id'],sensor_running=True,obstacle_motion_policy='CONTINUE_WHILE_ROBOT_HOLDS'))
        folder=self.out/'live_ipc';folder.mkdir()
        self.ipc=NativeOnlineIPC(folder,owner_pointer=folder/'owner.pointer.json',job_pointer=folder/'job.pointer.json',result_pointer=folder/'result.pointer.json',calculated_context_pointer=folder/'calculated_context.pointer.json',observation_provider=lambda:self.hold)

    def latch_unknown(self,reason):self._latch('outcome_unknown',reason)
    def latch_failure(self,reason):self._latch('failure_latched',reason)
    def latch_user_stop(self,reason):self._latch('user_stop_latched',reason)
    def _latch(self,key,reason):
        if self.depth:self.depth['state'][key]=True
        save(self.out/'live_latch.json',dict(latch=key,reason=reason,automatic_resume=False))

    def publish_hold(self,row,statuses,history,stop):
        # Filled from the current actual STOP sample and source Depth; no job
        # or candidate is synthesized from a cached fixed SDK result.
        save(self.out/'rolling_hold_status.json',dict(scope='ACTUAL_NATIVE_ROLLING_HOLD_CURRENT_INPUT_PRODUCTION',stamp_s=row['time_s'],physics_step=row['tracking']['physics_step'],goal_id=self.depth['state']['goal_id'],cancel_generation=self.depth['state']['cancel_generation'],native_command_counts=command_counts(statuses),pending_cancel_count=self.depth['work']['cancel_pending'],holding_contact_fingers=row['contact_fingers'],stop_metrics=stop,current_native_PVA=self.depth['work']['previous_sample'],latest_depth_frame_seq=self.depth['work'].get('latest_sensor',{}).get('frame',{}).get('frame_seq'),timeline_running=True,SDK_started=False,resume_executed=False,owner_packet_exists=self.hold is not None,canonical_owner_packet_ready=self.hold is not None and self.hold['packet']['normalized_bound_replay_pending'] is False))
        sensor=self.depth['work'].get('latest_sensor')
        completed=self.latest_complete_sensor
        if completed is not None and (sensor is None or not partial_visibility(sensor)) and 0<=row['time_s']-completed['frame']['source_stamp_s']<=.12:
            sensor=completed
        if sensor is None:return
        publication_key=(sensor['frame']['frame_seq'],'canonical_bound' in sensor)
        if publication_key==self.last_publish_key:return
        if row['time_s']-sensor['frame']['source_stamp_s']>.12:return
        self.hold=self.current_observation(row,statuses,history,stop,sensor)
        lock=self.resume_sender.lock if self.resume_sender is not None else None
        # Admission uses the same owner lock off-thread. Never block physics
        # waiting for its cache/source review; raw sensing continues this tick.
        if lock is not None and not lock.acquire(blocking=False):
            self.publication_lock_skips+=1
            if self.publication_lock_skips%60==1:self.task_event('OWNER_IPC_PUBLICATION_SKIPPED_D_APPLY_LOCK')
            return
        try:publication=self.ipc.publish_tick()
        finally:
            if lock is not None:lock.release()
        self.last_publish_seq=sensor['frame']['frame_seq'];self.last_publish_key=publication_key;self.publication_count+=1
        save(self.out/'live_publication_status.json',dict(status='ACTUAL_STOP_AND_ROLLING_NATIVE_OWNER_PUBLISHED_NO_JOB_OR_RESUME',publications=self.publication_count,source_stamp_s=row['time_s'],frame_seq=self.last_publish_seq,owner_pointer=str(self.ipc.owner_pointer),packet_ref=publication,SDK_started=False,resume_executed=False,normalized_bound_replay_pending=self.hold['packet']['normalized_bound_replay_pending'],current_bound_pending_reason=self.hold['packet'].get('current_bound_pending_reason')))

    def current_observation(self,row,statuses,history,stop,sensor):
        from dynamic_cumotion_inputs import sealed,held_mask_context
        from prepare_gpu_scene import tcp_fk
        from sim_utils import error
        import omni.timeline
        stamp=row['time_s'];seq=row['tracking']['physics_step'];folder=self.out/'live_ipc'/'evidence'/f'{seq:012d}';folder.mkdir(parents=True)
        live=deepcopy(self.depth['state']);counts=command_counts(statuses);pending=self.depth['work']['cancel_pending']
        if any(counts.values()) or pending!=0:raise ValueError('PENDING_COMMANDS_IN_CURRENT_STOP_PUBLICATION')
        current=self.PVA[-1]
        if current['stamp_s']!=stamp:raise ValueError('CURRENT_NATIVE_PVA_NOT_THIS_SOURCE_TICK')
        refs=row['tracking']['controller_states'];latest=refs[-1];r=latest['reference']
        if any(len(r[k])!=6 for k in ('positions','velocities','accelerations')):raise ValueError('CURRENT_HOLD_REFERENCE_PVT_INCOMPLETE')
        if len(refs)<2 or any(refs[-2]['reference'][k]!=r[k] for k in ('positions','velocities','accelerations')):raise ValueError('CURRENT_CONTROLLER_HELD_INTERVAL_UNCONFIRMED')
        if not np.array_equal(np.asarray(r['positions'],np.float32),np.asarray(row['tracking']['drive_target_q_rad'],np.float32)):raise ValueError('CURRENT_HOLD_REFERENCE_NOT_CURRENT_DRIVE')
        observed=dict(session_id=self.session,clock_basis='SIM_TIME',clock_epoch=0,stamp_s=stamp,**{k:current[k] for k in ('q_rad','v_rad_s','a_rad_s2')})
        desired=dict(session_id=self.session,clock_basis='SIM_TIME',clock_epoch=0,stamp_s=latest['header_ns']/1e9,q_rad=r['positions'],v_rad_s=r['velocities'],a_rad_s2=r['accelerations'])
        if any(v!=0 for v in desired['v_rad_s']+desired['a_rad_s2']):raise ValueError('CURRENT_REFERENCE_NOT_COMMAND_HOLD')
        for name,data in [('clock',dict(raw_tracking=row['tracking'],observed_stamp_s=stamp)),('reference',dict(desired=desired,current_drive_targets=row['tracking'])),('observed',observed)]:save(folder/(name+'.json'),data)
        assoc=dict(scope='VERIFIED_CONTROLLER_REFERENCE_OBSERVATION_ASSOCIATION',session_id=self.session,clock_basis='SIM_TIME',clock_epoch=0,desired_stamp_s=desired['stamp_s'],observed_stamp_s=stamp,desired_pvt_digest=digest({k:desired[k] for k in ('q_rad','v_rad_s','a_rad_s2')}),observed_pvt_digest=digest({k:observed[k] for k in ('q_rad','v_rad_s','a_rad_s2')}),valid_from_s=desired['stamp_s'],valid_until_s=stamp,method='CONFIRMED_CONTROLLER_HOLD_INTERVAL',reference_held_confirmed=True,evidence={k:ref(folder/(n+'.json')) for k,n in [('clock','clock'),('controller_reference','reference'),('observed_state','observed')]})
        save(folder/'reference_time_association.json',assoc);desired['source_time_association']=ref(folder/'reference_time_association.json')
        projected=sensor['projected'];frame=sensor['frame'];matched=sensor['matched']
        for name,array in [('depth',sensor['image']['depth']),('semantic_ids',sensor['image']['ids']),('self_mask',sensor['self_mask']),('held_mask',sensor['held_mask']),('obstacle_mask',sensor['obstacle_mask'])]:np.save(folder/(name+'.npy'),array,allow_pickle=False)
        save(folder/'frame.json',frame);save(folder/'candidates.json',projected);save(folder/'camera_params.json',sensor['image']['params']);save(folder/'source_tick.json',matched)
        save(folder/'semantic_info.json',sensor['image']['info'])
        save(folder/'limits.json',dict(clock_basis='SIM_TIME',threshold_status='SIM_TEST_PARAMETER',max_age_s=.12,max_pose_skew_s=.001,min_depth_m=.02,max_depth_m=2.))
        (folder/'capture_profile.json').write_bytes(self.profile.read_bytes())
        # Snapshot of the source actually loaded at startup, not edited disk code.
        (folder/'capture_source.py').write_bytes((self.out/'executed_live_depth_stop.py').read_bytes())
        save(folder/'raw_render_source.json',dict(reference_time=sensor['image']['reference_time'],
            observation_wall_monotonic_s=sensor['image']['observation_wall_monotonic_s'],
            pairing_scope='RECORDED_RENDERER_REFERENCE_TIME_AND_NEAREST_NATIVE_STATE_NOT_FULL_TICK_RECEIPT',
            source_state=ref(folder/'source_tick.json'),source_frame=ref(folder/'frame.json'),
            same_tick_verified=False,full_scene_inventory_pending=True))
        points=np.asarray(projected['points_base_m']);camera=np.asarray(projected['T_base_camera_optical']);range_m=float(np.linalg.norm(points-camera[:3,3],axis=1).max()) if len(points) else None
        fk=tcp_fk(self.request['model_bundle'],matched['q_rad'],matched['grip_rad']);fk_error=error(fk,np.asarray(matched['T_base_tool']))
        prior=dict(scope='DECLARED_SIM_SINGLE_OBJECT_BOUNDS_NOT_REAL',size_upper_m=[.02]*3,point_error_m=.00005,pose_translation_error_m=.00005,pose_rotation_error_rad=.0001,max_speed_m_s=self.args.dynamic_speed_m_s,max_sensor_to_use_delay_s=35.,**DEPTH_VISIBILITY)
        prior.update(live_scene_motion_kind=self.args.live_scene_motion_kind,world_revision=self.args.live_world_revision)
        # Canonical prior/basis/job freeze requires independent complete source
        # evidence; this provisional record must not impersonate that admission.
        save(folder/'prior.pending_completion.json',prior)
        geometry,pending_reason=observe_depth_geometry(projected,sensor['image']['depth'].shape,prior,range_m=range_m,fk_error=fk_error,age_s=stamp-frame['source_stamp_s'])
        # This transparent provisional bound preserves real source evidence.
        # A worker must replay the full calibrated envelope before admission.
        if pending_reason is None:
            centre,size,checks=geometry
            bound=dict(schema='bounded-depth-obstacle/0.1',source_kind='SIM_DEPTH',status='CURRENT_SOURCE_CONDITIONAL_BOUND_FULL_CALIBRATED_REPLAY_PENDING',source_session_id=self.session,frame_seq=frame['frame_seq'],source_stamp_s=frame['source_stamp_s'],received_stamp_s=frame['received_stamp_s'],clock_basis='SIM_TIME',valid_until_s=frame['source_stamp_s']+35.,candidate_digest=projected['digest'],geometry=dict(id='Dynamic_native_moving_cube',role='OTHER_OBSTACLE',size_m=size.tolist(),studs=False,coordinate_kind='SIM_BODY_CENTRE',pose=dict(frame_id='base_link',xyz_m=centre.tolist(),quaternion_xyzw=[0,0,0,1])),geometry_context=held_mask_context(self.request,dict(grip_rad=row['grip_rad'],attachment_tcp_to_block=row['attachment'])),assumptions=prior,checks=checks,raw_source_evidence=ref(folder/'frame.json'),source_pose_evidence=ref(folder/'source_tick.json'),calibration_profile=ref(self.profile),execution_allowed=False,hardware_execution_allowed=False,world_clear_allowed=False)
        else:
            # Not the bounded-depth-obstacle schema: no invented centre, size,
            # valid-until, evidence_spec, online_motion, or approval flags.
            bound=dict(schema='depth-bound-pending/0.1',source_kind='SIM_DEPTH',status='CURRENT_BOUND_PENDING_PARTIAL_DEPTH',
                reason=pending_reason,source_session_id=self.session,clock_basis='SIM_TIME',frame_seq=frame['frame_seq'],
                source_stamp_s=frame['source_stamp_s'],received_stamp_s=frame['received_stamp_s'],
                candidate_digest=projected['digest'],geometry=None,raw_source_evidence=ref(folder/'frame.json'),
                source_pose_evidence=ref(folder/'source_tick.json'),SDK_admitted=False,READY=False,apply_allowed=False,
                execution_allowed=False,hardware_execution_allowed=False,world_clear_allowed=False)
        if pending_reason is None and 'canonical_bound' in sensor:
            bound=deepcopy(sensor['canonical_bound'])
        bound=sealed(bound);save(folder/('bound.pending_visibility.json' if pending_reason else ('bound.canonical.json' if 'canonical_bound' in sensor else 'bound.pending_replay.json')),bound)
        state=sealed(dict(schema='stopped-robot-snapshot/0.1',source_kind='SIM_SAVED_SNAPSHOT',session_id=self.session,clock_basis='SIM_TIME',state_sequence=seq,source_stamp_s=stamp,received_stamp_s=stamp,joint_names=JOINTS,units='rad, seconds',**{k:current[k] for k in ('q_rad','v_rad_s','a_rad_s2')},grip_rad=row['grip_rad'],attachment_tcp_to_block=row['attachment'],holding_confirmed=True,stopped_verified=True,active_command_count=counts['active_command_count'],pending_command_count=counts['pending_command_count'],cancel_generation=live['cancel_generation'],stop_reason='OBSTACLE_RESPONSE_HOLD',velocity_method='PHYSX_NATIVE_JOINT_VELOCITY',acceleration_method='ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE',q_uncertainty_rad=float(np.max(np.spacing(abs(np.asarray(row['q_rad'],np.float32))))/2),v_uncertainty_rad_s=float(np.max(np.spacing(abs(np.asarray(current['v_rad_s'],np.float32))))/2),a_uncertainty_rad_s2=float((np.max(np.spacing(abs(np.asarray(current['v_rad_s'],np.float32))))/2+np.max(np.spacing(abs(np.asarray(self.PVA[-2]['v_rad_s'],np.float32))))/2)/(stamp-self.PVA[-2]['stamp_s'])+64*np.finfo(float).eps*max(1.,max(abs(v) for v in current['a_rad_s2']))),uncertainty_scope='FLOAT32_READOUT_REPRESENTATION_ONLY_NOT_PHYSICAL_OR_SOLVER_ERROR_BOUND',evidence_ref=str(folder/'observed.json'),execution_allowed=False,hardware_execution_allowed=False))
        live.update(state_sequence=seq,state_digest=state['digest'],snapshot_version=frame['frame_seq'],snapshot_digest=projected['digest'],q_rad=current['q_rad'],v_rad_s=current['v_rad_s'],a_rad_s2=current['a_rad_s2'],state_stamp_s=stamp,now_s=stamp,grip_rad=row['grip_rad'],attachment_tcp_to_block=row['attachment'],contact_fingers=row['contact_fingers'],desired=desired,**counts,pending_cancel_count=pending,static_world=self.args.dynamic_read_geometry(),motion_request=self.environment['motion'],binding=self.packet['binding'])
        samples=[{k:deepcopy(p[k]) for k in ('stamp_s','q_rad','v_rad_s','a_rad_s2')} for p in self.PVA if stamp-.7<=p['stamp_s']<=stamp and p['stamp_s']>=self.depth['work']['terminal_stamp']]
        if len(samples)<2 or samples[-1]['stamp_s']-samples[0]['stamp_s']<.5:raise ValueError('CURRENT_ACTUAL_STOP_WINDOW_SHORT')
        capture_source=folder/'capture_source.py'
        stop_observation={k:state[k] for k in ('q_uncertainty_rad','v_uncertainty_rad_s','a_uncertainty_rad_s2','velocity_method','acceleration_method')}
        stop_observation.update(raw_current_native_PVA=current,raw_position_window=stop)
        stop_evidence=dict(scope='ACTUAL_SIM_STOP_RECORD',model_manifest_sha256=ref(self.model/'MODEL_MANIFEST.json')['sha256'],
            session_id=self.session,clock_basis='SIM_TIME',state_sequence=seq,cancel_generation=live['cancel_generation'],
            stop_reason='OBSTACLE_RESPONSE_HOLD',grip_rad=row['grip_rad'],attachment_digest=digest(row['attachment']),
            observation=stop_observation,holding_confirmed=True,**counts,samples=samples,
            independent_D_stop_verification_scope='CURRENT_POSITION_WINDOW_AND_SAME_UUID_CANCEL_TERMINAL')
        save(folder/'actual_sim_stop_record.json',stop_evidence)
        state={k:v for k,v in state.items() if k!='digest'}
        state['stop_evidence']=dict(**ref(folder/'actual_sim_stop_record.json'),capture_source_path=str(capture_source),capture_source_sha256=ref(capture_source)['sha256'])
        state=sealed(state);live['state_digest']=state['digest']
        live.update(world_objects=deepcopy(live['static_world']),selected_block_id=self.request['planning_snapshot']['selected_slot_id'],
            current_revision=self.request['current_revision'],a_context=deepcopy(live['original_a_context']),
            reservation_binding=deepcopy(live['original_reservation']),holding_confirmed=True,
            world_observation_stamp_s=stamp,a_context_scope='UNCHANGED_ORIGINAL_A_CONTEXT_OF_THIS_CONTROLLED_SIM_GOAL_NOT_NEW_B_OBSERVATION')
        record=dict(source_kind='SIM_OWNER_RECORD',state_source_kind='SIM_SAVED_SNAPSHOT',**{k:live[k] for k in OWNER_KEYS},stop_reason='OBSTACLE_RESPONSE_HOLD',old_goal_terminal_status='CANCELED',cancel_acknowledged=True,cancel_terminal_stamp_s=self.depth['work']['terminal_stamp'],**counts,pending_cancel_count=pending,samples=samples,velocity_method=state['velocity_method'],acceleration_method=state['acceleration_method'])
        record['record_digest']=digest(record);live['stop_record']=record
        ack=next(a for a in self.status['cancellation'] if a['done'] and a['return_code']==0 and live['goal_id'] in a['goals_canceling_ids'])
        result=self.status['native_action_result'];terminal=dict(result,goal_id=live['goal_id'])
        counts_payload=deepcopy(next(r['original_payload'] for r in reversed(self.depth['records']) if r['event']=='COMMAND_COUNTS' and r['observed_stamp_s']<=stamp))
        if any(counts_payload[k]!=v for k,v in dict(**counts,pending_cancel_count=pending).items()):raise ValueError('CURRENT_COMMAND_COUNTS_DIFFER_FROM_RAW_JOURNAL')
        evidence=dict(cancel_ack=ack,terminal_result=terminal,command_counts=counts_payload,holding=dict(holding_confirmed=True,contact_fingers=row['contact_fingers'],grip_rad=row['grip_rad'],attachment_tcp_to_block=row['attachment']),controller_stop=dict(stop_verified=True,goal_id=live['goal_id'],verification_method='EXISTING_D_VERIFIED_POSITION_HISTORY_PLUS_SAME_UUID_CANCEL_TERMINAL_EMPTY_COMMANDS',stop_metrics=stop))
        for name in ('holding','controller_stop'):evidence[name].update(identity={k:live[k] for k in LIVE_IDENTITY},state_stamp_s=stamp)
        for name,data in evidence.items():save(folder/(name+'.json'),data)
        proof=dict(scope='VERIFIED_D_OBSTACLE_STOP_AND_HOLDING_NOT_RESUME_APPROVAL',identity={k:live[k] for k in LIVE_IDENTITY},stop_record_digest=record['record_digest'],samples_digest=digest(samples),state_stamp_s=stamp,stop_verified=True,holding_confirmed=True,verification_method='ACTUAL_D_CANCEL_ACK_CANCELED5_EMPTY_COMMANDS_AND_CURRENT_POSITION_CONTACT_WINDOW',evidence={k:ref(folder/(k+'.json')) for k in evidence})
        from .rolling_owner_view import seal_view
        original_events,current_view=seal_view(self.depth['records'],live)
        # Bind exactly the reader's current-view provenance before either
        # record/proof is sealed and published; original events stay unchanged.
        record.pop('record_digest')
        record['original_owner_events_digest']=digest(current_view)
        record['record_digest']=digest(record)
        proof['stop_record_digest']=record['record_digest']
        save(folder/'stop_verification.json',proof);live['stop_verification']=ref(folder/'stop_verification.json')
        save(folder/'original_window_events.json',original_events);(folder/'current_rolling_journal_view.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in current_view))
        live['current_rolling_journal_view']=ref(folder/'current_rolling_journal_view.jsonl')
        live['original_window_events']=ref(folder/'original_window_events.json')
        live['journal_view_scope']='CURRENT_SEALED_WINDOW_BOUND_HISTORY_ORIGINAL_EVENT_CONTEXTS_PRESERVED_REVIEW_PENDING'
        live['owner_review_limits']=self.owner_review_limits
        control={k:live[k] for k in ('session_id','clock_basis','clock_epoch','cancel_generation','replan_sequence','mode','user_stop_latched','failure_latched')}
        packet=dict(state=state,control=control,desired=desired,latest_depth=projected,latest_depth_bound=bound,timeline_running=omni.timeline.get_timeline_interface().is_playing(),obstacle_motion_policy='CONTINUE_WHILE_ROBOT_HOLDS',observation_sequence=seq,normalized_bound_replay_pending=pending_reason is not None or 'canonical_bound' not in sensor,current_bound_pending_reason=pending_reason,SDK_admitted=False,READY=False,apply_allowed=False,execution_allowed=False,hardware_execution_allowed=False)
        return dict(owner=live,packet=packet)

    def approve_prepared_calculation(self,prepared_job_ref,before_SDK_phase_ref,*,observation_provider=None,request_ref=None):
        """Explicit D selection BEFORE SDK. This never calls an optimizer/send."""
        from .prepared_job_selection import approval_inputs,pinned
        if self.resume_sender is None or self.ipc is None:raise ValueError('EXISTING_D_BOUND_VERIFIED_HOLD_REQUIRED')
        if not all(callable(getattr(self.ipc,name,None)) for name in ('prepare_job','commit_prepared_job')):
            raise ValueError('LOADED_NATIVE_PREPARED_ADMISSION_UNAVAILABLE_NORMAL_ACTIVATION_REQUIRED')
        # The original common-A anchor was selected at startup, not by the
        # private preparer's mutable path or its prepared attachment.
        handoff=pinned(json.loads((self.out/'input_pins.json').read_text())['handoff'])
        anchor=handoff['request']
        observe=observation_provider or self.published_input_selection_observation
        # Immutable preparation runs on the dedicated CPU queue without D lock.
        with self.resume_sender.lock:
            self.task_event('ADMISSION_CHECKPOINT_START')
            try:source=observe()
            finally:self.task_event('ADMISSION_CHECKPOINT_END')
        ticket=approval_inputs(job_ref=prepared_job_ref,anchor_ref=anchor,
            phase_ref=before_SDK_phase_ref,observation=source)
        folder=self.out/'prepared_D_admission'/uuid.uuid4().hex;folder.mkdir(parents=True)
        save(folder/'input_approval.json',ticket)
        job=deepcopy(pinned(prepared_job_ref));job['D_input_approval']=ref(folder/'input_approval.json')
        save(folder/'approved_job.json',job)
        if self.ipc.job_ref is not None:
            # Existing failed/expired selection stays immutable. No implicit
            # replacement, legacy heavy-lock fallback, or closure fabrication.
            raise ValueError('SPLIT_ADMISSION_FRESH_FIRST_SELECTION_ONLY')
        self.task_event('ADMISSION_PREPARE_START')
        try:
            prepared=self.ipc.prepare_job(ref(folder/'approved_job.json'),source['owner_ref'],source['packet_ref'])
        finally:self.task_event('ADMISSION_PREPARE_END')
        self.task_event('ADMISSION_D_LOCK_WAIT_START')
        with self.resume_sender.lock:
            self.task_event('ADMISSION_COMMIT_START')
            try:
                latest=observe()
                if {k:source['owner'][k] for k in LIVE_IDENTITY}!={k:latest['owner'][k] for k in LIVE_IDENTITY}:raise ValueError('ADMISSION_IDENTITY_CHANGED_DURING_CPU_REVIEW')
                stable=('current_revision','selected_block_id','a_context','reservation_binding','model_manifest_sha256','holding_confirmed','mode')
                if any(source['owner'][k]!=latest['owner'][k] for k in stable):raise ValueError('ADMISSION_STABLE_CURRENT_SOURCE_CHANGED_DURING_CPU_REVIEW')
                selected=self.ipc.commit_prepared_job(prepared,owner_lock=self.resume_sender.lock,
                    current_observation_provider=observe)
                after=observe()
                if any(latest['owner'][k]!=after['owner'][k] for k in tuple(LIVE_IDENTITY)+stable):
                    raise ValueError('NATIVE_JOB_SELECTED_BUT_STABLE_SOURCE_CHANGED_NO_SDK_AUTHORITY')
            finally:self.task_event('ADMISSION_COMMIT_END')
        save(folder/'selected_native_job.json',dict(scope='D_NATIVE_INPUT_SELECTION_BEFORE_SDK_NOT_READY_OR_APPLY',
            original_prepared_job=prepared_job_ref,D_input_approval=job['D_input_approval'],input_preparation_ref=prepared,
            selected_native_job=selected,required_selected_ref_for_calculation_and_proofs=selected,
            READY=False,apply_allowed=False,SDK_started=False,native_send_called=False))
        return selected

    def published_admission_observation(self):
        # CPU worker reads immutable native publications only; no USD/PhysX or
        # ROS calls from this thread and no fabricated current clock/state.
        source=deepcopy(self.hold)
        if source is None:raise ValueError('CURRENT_NATIVE_PUBLICATION_REQUIRED')
        limits=json.loads(Path(source['owner']['owner_review_limits']['path']).read_text())
        age=self.last['time_s']-source['owner']['state_stamp_s']
        if not 0<=age<=limits['max_state_age_s']:raise ValueError('ADMISSION_NATIVE_PUBLICATION_STALE')
        for key in ('user_stop_latched','failure_latched','outcome_unknown'):
            if source['owner'][key]!=self.depth['state'][key] or source['owner'][key] is not False:
                raise ValueError('ADMISSION_CURRENT_OWNER_LATCH_CHANGED')
        return source

    def published_input_selection_observation(self):
        """Exact published refs + actual tick clock; CPU never reads native APIs.

        The latest unpublished hold is checked for STOP/latch/count changes;
        its raw values never replace the pinned publication or its seal.
        """
        current=deepcopy(self.ipc.current)
        if current is None:raise ValueError('NATIVE_SELECTED_SOURCE_NOT_PUBLISHED')
        if current['packet'].get('current_bound_pending_reason') is not None:
            raise ValueError('CURRENT_BOUND_PENDING_PARTIAL_DEPTH_NO_CALCULATION_ADMISSION')
        native=self.published_admission_observation()
        owner=current['owner'];latest=native['owner']
        stable=tuple(LIVE_IDENTITY)+('current_revision','selected_block_id','a_context',
            'reservation_binding','model_manifest_sha256','mode','owner_review_limits')
        if any(owner[k]!=latest[k] for k in stable):raise ValueError('ADMISSION_PUBLISHED_AUTHORITY_CHANGED')
        if any(latest[k]!=self.depth['state'][k] for k in LIVE_IDENTITY):raise ValueError('ADMISSION_NATIVE_LIFECYCLE_CHANGED')
        for observation in (current,native):
            actual=observation['owner'];state=observation['packet']['state']
            if actual['mode']!='OBSTACLE_HOLD' or actual['holding_confirmed'] is not True or state['holding_confirmed'] is not True or state['stopped_verified'] is not True:
                raise ValueError('ADMISSION_CURRENT_STOP_HOLD_REQUIRED')
            if any(actual[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):
                raise ValueError('ADMISSION_CURRENT_OWNER_LATCH_CHANGED')
            if any(type(actual[k]) is not int or actual[k]!=0 for k in ('active_command_count','pending_command_count','pending_cancel_count')):
                raise ValueError('ADMISSION_CURRENT_COMMANDS_NOT_QUIET')
        row=self.last
        limits=json.loads(Path(owner['owner_review_limits']['path']).read_text())
        if not 0<=row['time_s']-owner['state_stamp_s']<=limits['max_state_age_s']:
            raise ValueError('ADMISSION_SELECTED_PUBLICATION_STALE')
        # The clock is a separate latest native tick observation. No old owner
        # timestamp, q/v/a, geometry, journal, or source receipt is retagged.
        return dict(owner=owner,packet=current['packet'],owner_ref=current['owner_ref'],packet_ref=current['packet_ref'],
            clock_now=dict(session_id=self.depth['state']['session_id'],clock_basis=self.depth['state']['clock_basis'],
                clock_epoch=self.depth['state']['clock_epoch'],now_s=row['time_s']))

    def run_admission_CPU(self,job,phase,*,request_ref=None):
        self.task_event('ADMISSION_REVIEW_START')
        try:return self.approve_prepared_calculation(job,phase,observation_provider=self.published_input_selection_observation,request_ref=request_ref)
        finally:self.task_event('ADMISSION_REVIEW_END')

    def poll_prepared_admission(self):
        if getattr(getattr(self,'args',None),'initial_transport_demo_only',False):return
        if self.resume_sender is None:return
        if self.prepared_admission is None:
            from .prepared_admission_ipc import PreparedAdmissionIPC
            self.prepared_admission=PreparedAdmissionIPC(self.out/'live_ipc/prepared_admission',self.admission_pool,
                self.run_admission_CPU,
                lambda:{k:self.depth['state'][k] for k in LIVE_IDENTITY},telemetry=self.task_event)
        try:self.prepared_admission.poll()
        except (ValueError,KeyError,json.JSONDecodeError) as exc:
            save(self.out/'prepared_admission_protocol_rejection.json',dict(status='HOLD_PROTOCOL_REJECTED',reason=str(exc),SDK_started=False,native_send_called=False))

    def bind_resume_sender(self,*,client,owner_apply_lock,current_observation_provider,on_submitted,on_failure):
        import os
        from d_sim_transport import native_goal
        from unique_identifier_msgs.msg import UUID
        from .native_resume_sender import SameDResumeSender,encoded_selection_provider
        if os.environ.get('ROS_DOMAIN_ID')!='194' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')!='LOCALHOST':
            raise ValueError('EXISTING_ISOLATED_SIM_D_ONLY')
        if client._action_name!='/sim/m0609/arm_controller/follow_joint_trajectory':
            raise ValueError('EXISTING_SIM_ARM_CLIENT_REQUIRED')
        # Snapshot files were frozen at the actual import boundary. Current
        # edited disk source is deliberately not accepted as loaded provenance.
        if self.ipc is None:raise ValueError('VERIFIED_OBSTACLE_HOLD_IPC_REQUIRED_BEFORE_OWNER_BIND')
        if self.resume_sender is not None:raise ValueError('D_SENDER_ALREADY_BOUND_NEW_SEQUENCE_REQUIRED')
        pins={name:ref(self.out/'loaded_sources'/name) for name in ('d_sim_transport.py','run_fixed_depth_native.py','native_resume_sender.py','live_native_depth_owner.py')}
        self.resume_sender=SameDResumeSender(ipc=self.ipc,client=client,owner_lock=owner_apply_lock,
            current_observation_provider=current_observation_provider,goal_builder=native_goal,
            uuid_message=lambda value:UUID(uuid=list(value)),encoded_proof_provider=encoded_selection_provider(self.out/'encoded_resume'),
            encoding_source_pins=pins,on_submitted=on_submitted,on_failure=on_failure,prepare_adoption=self.prepare_resume_adoption)
        # The existing D monitor owns when this callback is invoked and consumes
        # its submission future. Legacy HOLD loop is not silently changed here.
        return self.resume_sender.try_submit

    def current_native_observation(self):
        if self.hold is None:raise ValueError('CURRENT_NATIVE_HOLD_PUBLICATION_REQUIRED')
        if self.hold['packet'].get('current_bound_pending_reason') is not None:
            raise ValueError('CURRENT_BOUND_PENDING_PARTIAL_DEPTH_NO_RESUME')
        if (self.out/'stop.request').exists():self.latch_user_stop('USER_STOP_BEFORE_RESUME')
        source=deepcopy(self.hold);owner=source['owner']
        if owner['state_stamp_s']!=self.last['time_s']:
            raise ValueError('CURRENT_ATOMIC_PUBLICATION_NOT_THIS_D_TICK')
        for key in ('user_stop_latched','failure_latched','outcome_unknown'):
            if owner[key]!=self.depth['state'][key]:raise ValueError('CURRENT_D_LATCH_CHANGED:'+key)
        row=self.environment['sample']()
        if row['time_s']!=owner['state_stamp_s'] or any(row[a]!=owner[b] for a,b in
                (('q_rad','q_rad'),('grip_rad','grip_rad'),('attachment','attachment_tcp_to_block'))):
            raise ValueError('CURRENT_OWNER_NOT_ACTUAL_NATIVE_READBACK')
        if any(owner[k]!=v for k,v in command_counts(self.environment['statuses']).items()):
            raise ValueError('CURRENT_D_COMMANDS_CHANGED')
        return source  # sealed clock/state/evidence never retimestamped or relabelled

    def prepare_resume_adoption(self,goal,audit):
        from .resume_monitor import prepare_monitor
        from isaac_sim.real_execution.native_boundary import typed_goal_snapshot
        if self.ready_resume_adoption is None:raise ValueError('FRESH_RESUME_MONITOR_AND_RISK_NOT_PREPARED')
        if audit.get('encoded_selection') is None:raise ValueError('CURRENT_ENCODED_PROOF_REQUIRED_FOR_MONITOR')
        adoption=prepare_monitor(audit['encoded_selection'],self.initial_packet['pre_contact_tcp_pose'])
        wire,header=typed_goal_snapshot(goal)
        if header!=0 or wire!=adoption['packet']['trajectory'] or digest(wire)!=self.ready_resume_adoption['wire_digest']:
            raise ValueError('FRESH_MONITOR_NOT_SAME_ACTUAL_TYPED_WIRE')
        adoption['volume']=self.ready_resume_adoption['volume']
        return adoption

    def on_resume_submitted(self,goal,audit,adoption):
        state=self.depth['state']
        if any(state[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):
            raise ValueError('RESUME_LATCH_CHANGED_AFTER_SUBMISSION')
        save(self.out/'consumed_obstacle_trigger.json',self.depth['work']['trigger'])
        self.depth['work'].update(trigger=None,terminal_stamp=None,complete=None,accepted=False)
        state.update(goal_id=audit['new_goal_id'],goal_version=audit['reservation']['next_goal_version'],
                     replan_sequence=state['replan_sequence']+1,mode='TRANSPORT',stop_reason=None)
        if self.risk_future is not None:self.risk_future.cancel()
        self.risk_future=None;self.risk_input=None
        self.request=adoption['request'];self.volume=adoption['volume'];self.wire=adoption['packet']['trajectory']
        self.status=None;self.latest_complete_sensor=None

    def poll_resume(self):
        if getattr(getattr(self,'args',None),'initial_transport_demo_only',False):return None
        self.poll_prepared_admission()
        if self.hold is not None and self.hold['packet'].get('current_bound_pending_reason') is not None:
            return None
        if any(self.depth['state'][k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):
            return None
        if (self.resume_sender is None or self.ipc.job_ref is None or self.ipc.geometry_handoff_ref is None or
                self.ipc.current_geometry is None):
            save(self.out/'online_resume_latest_review.json',dict(status='HOLD_WAIT_NEW_CURRENT_MODEL_CACHE_JOB_SDK_AND_WHOLE_FCL',**self.pending))
            return None
        # CPU risk precompute is outside the D apply lock and native tick.
        if self.resume_adoption_future is None:
            selection=dict(self.ipc.current_geometry)
            def prepare():
                from .resume_monitor import prepare_monitor
                from isaac_sim.real_execution.remaining_volume import RemainingVolume
                from isaac_sim.real_execution.native_boundary import typed_goal_snapshot
                from d_sim_transport import native_goal
                adoption=prepare_monitor(selection,self.initial_packet['pre_contact_tcp_pose'])
                wire,header=typed_goal_snapshot(native_goal(adoption['packet']))
                if header!=0:raise ValueError('RESUME_IMMEDIATE_HEADER_ONLY')
                adoption['wire_digest']=digest(wire)
                adoption['volume']=RemainingVolume(adoption['request'],wire)
                return adoption
            self.resume_adoption_future=self.risk_pool.submit(prepare)
            return None
        if not self.resume_adoption_future.done():return None
        if self.ready_resume_adoption is None:
            try:self.ready_resume_adoption=self.resume_adoption_future.result()
            except Exception as exc:
                self.latch_failure('FRESH_RESUME_MONITOR_PREPARATION_FAILED:'+str(exc))
                return dict(status='HOLD_MONITOR_PREPARATION_FAILED_NO_SEND',native_send_called=False,reason=str(exc))
        if self.hold is None or self.hold['owner']['state_stamp_s']!=self.last['time_s']:return None
        return self.resume_sender.try_submit()

    def close(self):
        if self.risk_future is not None:self.risk_future.cancel()
        self.risk_pool.shutdown(wait=False,cancel_futures=True)
        self.admission_pool.shutdown(wait=False,cancel_futures=True)
        if self.depth:self.depth['close']()
