"""Optional native SIM owner hooks and synchronized Depth proximity STOP test.

The existing D SIM owner submits/cancels. This module observes and requests its
normal obstacle hold; it has no ActionClient or additional executor.
"""
from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import uuid

import numpy as np

from .capture_wrist_sim import rigid,label,select_masks
from .projection import project_frame
from .render_time_probe import _json
from isaac_sim.real_execution.owner_records import write_owner_event,replay_owner_records
from capture_sim_scene import command_counts
from plan_only import digest
from sim_utils import save


def configure(args,runtime,*,preserve_existing=False):
    out=args.out;source=out/'executed_live_depth_stop.py';source.write_bytes(Path(__file__).read_bytes())
    evidence=dict(path=str(source.resolve()),sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    existing=dict(getattr(runtime,'transport_hooks',{}) or {}) if preserve_existing else {}
    session=getattr(args,'dynamic_session_id',None) or 'depth-stop-'+uuid.uuid4().hex
    goal_bytes=bytes(existing['goal_uuid'].uuid) if existing.get('goal_uuid') is not None else uuid.uuid4().bytes
    log=(out/'transport.owner.events.jsonl').open('x');setup_log=(out/'setup.owner.events.jsonl').open('x')
    records=[];states=deque(maxlen=480);pending=deque();sensor_rows=[]
    state=dict(session_id=session,clock_basis='SIM_TIME',clock_epoch=0,execution_id='transport-'+uuid.uuid4().hex,
        goal_id=goal_bytes.hex(),goal_version=1,state_digest=None,state_sequence=0,snapshot_digest=None,
        snapshot_version=0,cancel_generation=0,replan_sequence=0,source_kind='SIM_OWNER_RECORD',state_source_kind='SIM_SAVED_SNAPSHOT',
        single_writer='D',mode='INITIALIZING',stop_reason=None,user_stop_latched=False,failure_latched=False,outcome_unknown=False,
        velocity_method='PHYSX_NATIVE_JOINT_VELOCITY',acceleration_method='ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE',
        controller_entire_writer_count=None,controller_entire_writer_scope='UNOBSERVED_DIRECT_SERVICE_WRITERS_NOT_COUNTED_AS_ZERO')
    work=dict(record_sequence=0,accepted=False,trigger=None,terminal_stamp=None,last_v=None,previous_sample=None,last_counts=None,
        start_stamp=None,cancel_pending=0,complete=None,cue_start=None,cue_start_point=None,cue_end_point=None,closed=False)
    def event(kind,payload,stamp):
        if kind=='SUBMISSION_INTENT':
            state.update(mode='TRANSPORT',binding=payload['binding'],original_a_context=payload['request']['a_context'],
                original_reservation=payload['request']['reservation_binding'],model_manifest_sha256=hashlib.sha256((args.model_bundle/'MODEL_MANIFEST.json').read_bytes()).hexdigest())
            work['start_stamp']=stamp
        elif kind=='GOAL_ACCEPTED':
            if payload['goal_id']!=state['goal_id']:raise ValueError('ACTUAL_GOAL_UUID_DIFFERS_FROM_SUBMITTED_WIRE_UUID')
            work['accepted']=payload['accepted']
        elif kind=='CANCEL_REQUEST':
            state['cancel_generation']+=1;work['cancel_pending']+=1;state['stop_reason']=payload['reason']
            if payload['reason']=='OBSTACLE_RESPONSE_HOLD':state['mode']='OBSTACLE_HOLD'
            elif payload['reason']=='STOP_REQUESTED':state.update(mode='USER_STOP',user_stop_latched=True)
            else:state.update(mode='FAILURE_HOLD',failure_latched=True)
        elif kind=='CANCEL_ACK':
            if payload['done']:work['cancel_pending']-=1
        elif kind=='GOAL_RESULT':work['terminal_stamp']=stamp
        from isaac_sim.real_execution.owner_records import EVENTS
        if kind in EVENTS:
            record=write_owner_event(log,kind,work['record_sequence'],state,payload,observed_stamp_s=stamp,evidence=evidence)
            work['record_sequence']+=1;records.append(record)
            if work['terminal_stamp'] is not None and kind=='COMMAND_COUNTS':
                # The immutable full journal stays on disk. Keep only the
                # lifecycle and current raw window in the producer's RAM view.
                lifecycle={'GOAL_ACCEPTED','CANCEL_REQUEST','CANCEL_ACK','GOAL_RESULT'}
                records[:]=[r for r in records if r['event'] in lifecycle or r is record or
                    (r['event']=='PHYSICS_SAMPLE' and r['observed_stamp_s']>=stamp-1.2)]
        else:
            # Sensor/risk diagnostics are not controller lifecycle events.
            # Keep the shared journal vocabulary and raw diagnostics separate.
            with (out/'depth_risk_diagnostics.jsonl').open('a') as stream:stream.write(json.dumps(dict(kind=kind,payload=payload,stamp_s=stamp))+'\n')
    setup_sequence=0
    def setup_event(kind,payload,stamp):
        nonlocal setup_sequence
        context=dict(session_id=session,clock_basis='SIM_TIME',clock_epoch=0,phase='NATIVE_SETUP',goal_id=payload.get('goal_id'))
        write_owner_event(setup_log,kind,setup_sequence,context,payload,observed_stamp_s=stamp,evidence=evidence);setup_sequence+=1
        if kind=='COMMAND_COUNTS':work.setdefault('raw_status',{})[payload['controller']]=dict(payload,owner_received_stamp_s=stamp)
    env={}
    def install(app,stage,world,robot,raw_tick,seed,motion,controls,sample,statuses,out,model):
        from unique_identifier_msgs.msg import UUID
        runtime.transport_hooks['goal_uuid']=UUID(uuid=list(goal_bytes))
        import omni.kit.app,omni.replicator.core as rep
        from pxr import UsdGeom,UsdPhysics,Gf
        omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate('isaacsim.sensors.experimental.rtx',True);app.update()
        from isaacsim.sensors.experimental.rtx import RtxCamera,CameraSensor
        profile=json.loads(args.mount_profile.read_text());tool=seed['robot_tcp_prim'];base=seed['robot_base_prim']
        selected=next(o for o in seed['world_objects'] if o['id']==seed['reservation_binding']['slot_id'])
        label(stage.GetPrimAtPath('/World/Robot'),'robot');label(stage.GetPrimAtPath(selected['prim_path']),'held')
        path=tool+'/DepthStopCamera';camera=UsdGeom.Camera.Define(stage,path);optical=np.asarray(profile['T_tool_camera_optical'])
        camera.AddTransformOp().Set(Gf.Matrix4d((optical@np.diag([1.,-1.,-1.,1.])).T));usd=profile['usd_camera']
        for key,method in [('focal_length_mm','CreateFocalLengthAttr'),('horizontal_aperture_mm','CreateHorizontalApertureAttr'),
            ('vertical_aperture_mm','CreateVerticalApertureAttr'),('horizontal_aperture_offset_mm','CreateHorizontalApertureOffsetAttr'),
            ('vertical_aperture_offset_mm','CreateVerticalApertureOffsetAttr')]:getattr(camera,method)(float(usd[key]))
        camera.CreateClippingRangeAttr(Gf.Vec2f(.01,2.));intr=profile['intrinsics']
        sensor=CameraSensor(RtxCamera(path),resolution=(intr['height'],intr['width']),annotators=['distance_to_image_plane','semantic_segmentation','rgb'])
        params=rep.AnnotatorRegistry.get_annotator('camera_params');params.attach(str(sensor.render_product.GetPath()))
        obstacle_path='/World/DepthStopStimulus';cube=UsdGeom.Cube.Define(stage,obstacle_path);cube.CreateSizeAttr(.02)
        cube.CreateDisplayColorAttr([Gf.Vec3f(1,.2,.1)]);op=cube.AddTranslateOp();op.Set(Gf.Vec3d(10,10,-10))
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim());label(cube.GetPrim(),'moving_obstacle')
        class DepthWriter(rep.Writer):
            def __init__(self):self.version='0.1.0';self.annotators=['distance_to_image_plane','semantic_segmentation','camera_params','ReferenceTime']+(['rgb'] if getattr(args,'show_wrist_camera',False) else []);self.last=None
            def write(self,data):
                n,d=data['reference_time'];stamp=n/d
                if not preserve_existing and self.last is not None and stamp-self.last<.1:return
                depth=data['distance_to_image_plane']
                if not isinstance(depth,np.ndarray) or not depth.size:return
                self.last=stamp;sem=data['semantic_segmentation']
                pending.append(dict(source_stamp_s=stamp,reference_time=[n,d],reference_annotator=json.loads(json.dumps(data['ReferenceTime'],default=_json)),renderer_frame_id=int(data['swhFrameNumber']),writer_data_keys=list(data),observation_wall_monotonic_s=time.monotonic(),depth=depth.copy(),ids=sem['data'].copy(),
                    info=json.loads(json.dumps(sem['info'],default=_json)),params=json.loads(json.dumps(data['camera_params'],default=_json))))
                if preserve_existing and getattr(args,'show_wrist_camera',False):
                    rgb=data.get('rgb');rgb=rgb.get('data') if isinstance(rgb,dict) else rgb
                    pending[-1]['rgb']=rgb.copy() if isinstance(rgb,np.ndarray) else None
                    args.dynamic_camera_preview(pending[-1],env,path)
                if preserve_existing and work.get('terminal_stamp') is not None:
                    args.dynamic_capture_writer_bundle(pending[-1],env)
            def write_metadata(self):pass
        writer=DepthWriter();writer.attach(str(sensor.render_product.GetPath()))
        env.update(stage=stage,world=world,robot=robot,tool=tool,base=base,camera_path=path,optical=optical,
            profile=profile,sensor=sensor,camera_params=params,obstacle_path=obstacle_path,op=op,writer=writer,seed=seed)
        save(out/'moving_obstacle.script.json',dict(scope='EXPLICIT_CURRENT_STATIC_SIM_20MM_CUBE_ACTIVATION' if preserve_existing and args.dynamic_speed_m_s==0 else 'EXPLICIT_CONTROLLED_SIM_MOVING_20MM_CUBE',size_m=[.02]*3,
            speed_upper_m_s=args.dynamic_speed_m_s if preserve_existing else .25,optical_sweep_speed_m_s=args.dynamic_speed_m_s if preserve_existing else .04,start_after_active_goal_s=.8,
            position_rule='CONTROLLED_CAMERA_RELATIVE_ENTRY_WITH_WORLD_STEP_SPEED_CAP_NOT_PLANNER_INPUT',
            initial_placement='OUTSIDE_FOV_ON_SCRIPT_ACTIVATION_NOT_A_MEASURED_MOTION_SEGMENT',
            risk_rule='ORIGINAL_HELD_BODY_FOUR_STUDS_AND_GRIPPER_REMAINING_VOLUME' if preserve_existing else 'VISIBLE_DEPTH_POINTS_WITHIN_150MM_OF_STAMPED_TCP_CAUTION_NOT_FULL_SWEPT_COLLISION',
            min_visible_pixels=16,min_pixel_span=3,max_sensor_age_sim_s=.12,max_source_pose_skew_s=.001,
            motion_on_obstacle_stop='FIXED_SCENARIO_WORLD_POSE_SENSOR_AND_CLOCK_CONTINUE' if preserve_existing and args.dynamic_speed_m_s==0 else ('CONTINUE_WORLD_SEGMENT_WHILE_ROBOT_HOLDS' if preserve_existing else 'FREEZE_AT_OBSERVED_STOP_REQUEST_TEST_SCENARIO_ONLY'),static_archive_prior_reused=False))
    def on_sample(row,statuses):
        if not env:return
        stamp=float(row['time_s']);stage=env['stage'];base_world=rigid(stage,env['base'])
        current=dict(stamp_s=stamp,q_rad=row['q_rad'],T_base_tool=(np.linalg.inv(base_world)@rigid(stage,env['tool'])).tolist(),
            T_world_camera=rigid(stage,env['camera_path']).tolist(),T_world_base=base_world.tolist(),grip_rad=row['grip_rad'],attachment=row['attachment'])
        if preserve_existing:current['world_objects']=args.dynamic_read_geometry()
        states.append(current)
        if work['accepted'] and work['start_stamp'] is not None and stamp-work['start_stamp']>=.8 and (preserve_existing or not work['trigger']):
            if work['cue_start'] is None:
                intr=env['profile']['intrinsics'];camera_world=rigid(stage,env['tool'])@env['optical']
                def ray(u,v,z):return (camera_world@np.array([(u-intr['cx'])/intr['fx']*z,(v-intr['cy'])/intr['fy']*z,z,1.]))[:3]
                work.update(cue_start=stamp,cue_start_point=ray(-100,213,.18),cue_end_point=ray(213,213,.18))
                if preserve_existing:
                    start,end=args.dynamic_stimulus_segment(row,env,work)
                    work.update(cue_start_point=start,cue_end_point=end)
                    save(out/'moving_obstacle.activation.json',dict(stamp_s=stamp,start_world_m=start.tolist(),end_world_m=end.tolist(),region_diameter_m=float(np.linalg.norm(end-start)),initial_spawn_is_not_a_measured_motion_segment=True,planner_receives_stimulus_world_pose=False))
            start=work['cue_start_point'];end=work['cue_end_point'];length=float(np.linalg.norm(end-start))
            fraction=min(1.,.04*(stamp-work['cue_start'])/length)
            if preserve_existing:
                # Controlled World segment, continuous while the arm holds;
                # endpoints are a stimulus audit, never planner coordinates.
                fraction=(args.dynamic_speed_m_s*(stamp-work['cue_start'])/length)%2.
                if fraction>1.:fraction=2.-fraction
            intr=env['profile']['intrinsics'];u=-100+313*fraction
            camera_world=rigid(stage,env['tool'])@env['optical']
            target=(camera_world@np.array([(u-intr['cx'])/intr['fx']*.18,(213-intr['cy'])/intr['fy']*.18,.18,1.]))[:3]
            if preserve_existing:target=start+(end-start)*fraction
            previous_position=work.get('cue_position')
            if previous_position is None:position=target
            else:
                delta=target-previous_position;limit=.25*(stamp-work['cue_position_stamp'])
                position=previous_position+delta*min(1.,limit/max(float(np.linalg.norm(delta)),1e-12))
            work.update(cue_position=position,cue_position_stamp=stamp)
            if preserve_existing:
                with (out/'moving_obstacle.motion.jsonl').open('a') as stream:stream.write(json.dumps(dict(stamp_s=stamp,position_world_m=position.tolist(),scope='STIMULUS_GROUND_TRUTH_MOTION_AUDIT_NOT_PLANNER_INPUT'))+'\n')
            from pxr import Gf
            env['op'].Set(Gf.Vec3d(*position))
        v=np.asarray(row['velocity_rad_s'][:6]);previous=work['previous_sample'];a=None;qfd=None
        if previous:
            dt=stamp-previous['stamp_s']
            if dt<=0:raise ValueError('OWNER_PHYSICS_CLOCK_REVERSED')
            a=((v-np.asarray(previous['v_rad_s']))/dt).tolist();qfd=((np.asarray(row['q_rad'])-previous['q_rad'])/dt).tolist()
        payload=dict(stamp_s=stamp,q_rad=row['q_rad'],v_rad_s=v.tolist(),a_rad_s2=a,grip_rad=row['grip_rad'],
            attachment=row['attachment'],contact_fingers=row['contact_fingers'],position_difference_velocity_rad_s=qfd,
            tracking=row.get('tracking'),step_readout=row.get('step_readout'),wall_monotonic_s=time.monotonic())
        work['previous_sample']=payload;event('PHYSICS_SAMPLE',payload,stamp)
        current.update(raw_observation=deepcopy(row),native_PVA=deepcopy(payload),T_world_base=base_world.tolist())
        counts=command_counts(statuses);work['last_counts']=counts
        current['command_counts']=dict(counts)
        event('COMMAND_COUNTS',dict(**counts,pending_cancel_count=work['cancel_pending'],
            coverage='D_OWNER_AND_ARM_GRIPPER_ACTION_STATUS',raw_status_by_controller=work.get('raw_status'),
            controller_entire_writer_count=None,controller_entire_writer_scope='UNOBSERVED'),stamp)
        while pending:
            image=pending.popleft();source_stamp=image['source_stamp_s']
            matched=min(states,key=lambda s:abs(s['stamp_s']-source_stamp));skew=abs(matched['stamp_s']-source_stamp)
            if skew>.001:continue
            view=np.asarray(image['params']['cameraViewTransform']).reshape(4,4).T
            error=float(np.max(abs(np.linalg.inv(view)-matched['T_world_camera'])))
            if error>1e-8:raise ValueError('DYNAMIC_RENDER_SOURCE_POSE_DISAGREES')
            own,held,mask,labels=select_masks(image['ids'],image['info'])
            frame=dict(schema='wrist-depth-frame/0.1',source_kind='SIM_DEPTH',session_id=session,frame_seq=len(sensor_rows),
                source_stamp_s=source_stamp,received_stamp_s=stamp,robot_state_stamp_s=matched['stamp_s'],transform_stamp_s=matched['stamp_s'],
                clock_basis='SIM_TIME',optical_frame_id=env['profile']['optical_frame_id'],tool_frame_id=env['tool'],base_frame_id=env['base'],
                calibration_id=env['profile']['profile_id'],calibration_scope=env['profile']['calibration_scope'],q_rad=matched['q_rad'],
                T_base_tool=matched['T_base_tool'],T_tool_camera_optical=env['optical'].tolist(),intrinsics=env['profile']['intrinsics'],
                depth_unit='METER',depth_scale_m=1.,depth_representation='IMAGE_PLANE_Z',self_mask_status='GEOMETRIC_UNVERIFIED',held_mask_status='GEOMETRIC_UNVERIFIED')
            if preserve_existing:
                frame.update(live_scene_motion_kind=args.live_scene_motion_kind,world_revision=args.live_world_revision,
                    clock_epoch=state['clock_epoch'],observation_wall_monotonic_s=image['observation_wall_monotonic_s'])
            limits=dict(clock_basis='SIM_TIME',threshold_status='SIM_TEST_PARAMETER',max_age_s=.12,max_pose_skew_s=.001,min_depth_m=.02,max_depth_m=2.)
            if preserve_existing and stamp-source_stamp>limits['max_age_s']:
                event('IMAGE_DROPPED_STALE_NOT_WORLD_CLEAR',dict(source_stamp_s=source_stamp,received_stamp_s=stamp),stamp);continue
            if preserve_existing and image.get('writer_raw_folder'):
                args.dynamic_complete_writer_bundle(image,matched,frame,limits)
            projected=project_frame(frame,np.where(mask,image['depth'],np.nan),own,held,now_s=stamp,limits=limits)
            work['latest_sensor']=dict(frame=frame,projected=projected,image=image,matched=deepcopy(matched),self_mask=own,held_mask=held,obstacle_mask=mask,received_stamp_s=stamp)
            points=np.asarray(projected['points_base_m']);tcp=np.asarray(matched['T_base_tool'])[:3,3]
            distance=float(np.linalg.norm(points-tcp,axis=1).min()) if len(points) else None
            meta=dict(source_stamp_s=source_stamp,received_stamp_s=stamp,frame_seq=len(sensor_rows),source_state_skew_s=skew,
                camera_matrix_max_error=error,obstacle_pixels=int(mask.sum()),nearest_observed_point_to_tcp_m=distance,
                source_q_rad=matched['q_rad'],source_T_base_tool=matched['T_base_tool'],reference_time=image['reference_time'],
                time_sync_scope='ACTUAL_RENDER_REFERENCE_TIME_MATCHED_NATIVE_STATE',world_clear_allowed=False)
            sensor_rows.append(meta);event('IMAGE_SAMPLE',meta,stamp)
            span=np.ptp(np.asarray(projected['pixel_uv']),axis=0) if len(points) else [0,0]
            risky=distance is not None and distance<.15
            if preserve_existing:
                risky=False
                if work['accepted'] and work['trigger'] is None and counts['active_command_count']>0 and len(points)>=16 and min(span)>=3:
                    risk=args.dynamic_remaining_volume_risk(projected,row,counts,state,work)
                    risky=risk['risk'];meta['remaining_volume_risk']=risk
                    event('DEPTH_REMAINING_VOLUME_REVIEW',risk,stamp)
            if work['accepted'] and work['trigger'] is None and counts['active_command_count']>0 and len(points)>=16 and min(span)>=3 and risky:
                if not preserve_existing and max(abs(np.asarray(row['q_rad'])-np.asarray(states[0]['q_rad'])))<.02:continue
                work['trigger']=meta;state.update(stop_reason='OBSTACLE_RESPONSE_HOLD',snapshot_version=1,snapshot_digest=projected['digest'])
                folder=out/'depth_trigger';folder.mkdir()
                for name,data in [('depth',image['depth']),('semantic_ids',image['ids']),('self_mask',own),('held_mask',held),('obstacle_mask',mask)]:np.save(folder/(name+'.npy'),data,allow_pickle=False)
                save(folder/'frame.json',frame);save(folder/'semantic_info.json',image['info']);save(folder/'candidates.json',projected)
                save(folder/'trigger.json',dict(meta,actual_active_goal_id=state['goal_id'],active_command_count=counts['active_command_count'],
                    decision='OBSERVED_DEPTH_PROXIMITY_CAUTION_STOP',planner_receives_gt_pose=False))
    def completed(status,packet,request,history):
        work['complete']=status;work['packet']=packet
        save(out/'depth_frames.json',sensor_rows)
    def after(app,stage,world,robot,tick,seed,motion,controls,sample,statuses,out,model,result):
        try:
            if not (work['trigger'] and result['stop_verified'] and result['holding_confirmed'] and
                    result.get('native_action_result',{}).get('status')==5):raise ValueError('DEPTH_CANCEL_REST_OR_GRASP_NOT_VERIFIED')
            from .native_held_depth import capture_held
            def record_tick():tick();on_sample(sample(),statuses)
            live=dict(env,session_id=session,cancel_generation=lambda:state['cancel_generation'])
            capture_held(app,stage,world,robot,record_tick,seed,motion,controls,sample,statuses,out,model,args.mount_profile,live_capture=live)
            snapshot=json.loads((out/'wrist_depth/state_draft.json').read_text());image=json.loads((out/'wrist_depth/frame.json').read_text())
            state.update(state_sequence=snapshot['state_sequence'],state_digest=snapshot['digest'],snapshot_version=2,snapshot_digest=digest(image),
                q_rad=snapshot['q_rad'],v_rad_s=snapshot['v_rad_s'],a_rad_s2=snapshot['a_rad_s2'],state_stamp_s=snapshot['source_stamp_s'],
                now_s=float(world.current_time),motion_request=motion,binding=work['packet']['binding'])
            event('COMMAND_COUNTS',dict(**command_counts(statuses),pending_cancel_count=work['cancel_pending'],coverage='D_OWNER_AND_ARM_GRIPPER_ACTION_STATUS'),float(world.current_time))
            proof=json.loads((out/'wrist_depth/stop_evidence.json').read_text());first=proof['samples'][0]['stamp_s'];last=proof['samples'][-1]['stamp_s']
            selected=[r for r in records if r['event']!='PHYSICS_SAMPLE' or first<=r['original_payload']['stamp_s']<=last]
            limits=dict(scope='CPU_D_BOUNDARY_REVIEW_LIMITS',max_state_age_s=.1,min_stop_observation_s=.5,max_stop_velocity_rad_s=.02,
                max_stop_acceleration_rad_s2=.7,q_tolerance_rad=1e-6,v_tolerance_rad_s=1e-6,a_tolerance_rad_s2=1e-6)
            review=replay_owner_records(selected,limits=limits)
            save(out/'owner_reader.review.json',review);save(out/'latest_owner_context.json',state)
            with (out/'owner.rest_window.events.jsonl').open('x') as stream:
                for r in selected:stream.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n')
            save(out/'depth_stop.status.json',dict(depth_triggered=True,canceled_terminal=True,observed_rest=True,holding=True,
                scope='ACTUAL_NATIVE_DEPTH_PROXIMITY_CANCEL_AND_SNAPSHOT',owner_reader_status=review['status'],
                resume_status='HOLD_WAIT_NEW_LIVE_SDK_FCL_AND_INITIAL_PVT',hardware_execution_allowed=False,automatic_resume=False))
        finally:
            if env:env['writer'].detach()
            log.close();setup_log.close();work['closed']=True
    if preserve_existing:
        def composed_event(kind,payload,stamp):existing['event'](kind,payload,stamp);event(kind,payload,stamp)
        def composed_sample(row,statuses):existing['sample'](row,statuses);on_sample(row,statuses)
        def composed_completed(status,packet,request,history):existing['completed'](status,packet,request,history);completed(status,packet,request,history)
        runtime.capture_event_hook=setup_event
        runtime.transport_hooks=dict(existing,event=composed_event,sample=composed_sample,stop_requested=lambda:work['trigger'] is not None or existing['stop_requested'](),completed=composed_completed)
        return dict(install=install,event=event,sample=on_sample,work=work,state=state,env=env,records=records,states=states,close=lambda:(env['writer'].detach(),log.close(),setup_log.close()))
    runtime.sim_transport=True;runtime.depth_owner_test=True;runtime.transport_engine='moveit';runtime.transport_calculator=args.transport_calculator
    runtime.capture_event_hook=setup_event;runtime.wrist_depth_hook=install;runtime.after_transport_hook=after
    runtime.transport_hooks=dict(goal_uuid=None,event=event,sample=on_sample,stop_requested=lambda:work['trigger'] is not None,completed=completed)


def add_arguments(parser):parser.add_argument('--transport-calculator',type=Path,required=True)
