"""Existing wrist profile/raw camera for baseline A. No detector or stimulus."""
from collections import deque
from pathlib import Path
from fractions import Fraction
from queue import Queue,Empty
import json,time,hashlib,threading
import numpy as np
from .camera_preview import save_preview,save_preview_metadata,save_selected_detection_evidence
from .capture_wrist_sim import rigid
from .render_time_probe import _json
from sim_utils import save

class BaselineCamera:
    def __init__(self,app,stage,seed,out,session,*,source_context=None,direct_display=False,detection_only=False):
        import omni.kit.app,omni.replicator.core as rep
        import omni.ui as ui
        from pxr import UsdGeom,Gf,Sdf
        omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate('isaacsim.sensors.experimental.rtx',True);app.update()
        from isaacsim.sensors.experimental.rtx import RtxCamera,CameraSensor
        self.direct_display=direct_display;self.raw_display_enabled=bool(direct_display and not detection_only);self.display_latest=None;self.display_rows=[];self.display_retained=None;self.rgb_viewport=None
        self.display_stats=dict(writer_frames=0,superseded_display_pending=0,displayed=0,errors=0)
        self.source_context=source_context
        self.capture_diagnostic_phase='ACTIVE'
        self.minimal_evidence=bool(source_context and source_context.get('minimal_evidence_recording',False))
        self.evidence_budget_bytes=int((source_context or {}).get('evidence_budget_bytes',0))
        self.retention_kinds=set();self.baseline_retained=0;self.initial_recording_q=None
        self.recording_accepted_source_s=None;self.latest_evidence_product=None;self.trigger_evidence_product=None
        self.latest_foreground_entry=None;self.foreground_stop_binding=None
        self.out=out;self.session=session;self.stage=stage;self.seed=seed;self.states=deque(maxlen=480);self.pending=deque(maxlen=2);self.count=0
        profile_path=Path(__file__).resolve().parent/'config/rokey_published_raw_depth_nominal.json'
        profile=json.loads(profile_path.read_text());self.profile=profile
        self.path=seed['robot_tcp_prim']+'/DepthStopCamera';camera=UsdGeom.Camera.Define(stage,self.path)
        camera.AddTransformOp().Set(Gf.Matrix4d((np.asarray(profile['T_tool_camera_optical'])@np.diag([1.,-1.,-1.,1.])).T))
        for key,method in [('focal_length_mm','CreateFocalLengthAttr'),('horizontal_aperture_mm','CreateHorizontalApertureAttr'),('vertical_aperture_mm','CreateVerticalApertureAttr'),('horizontal_aperture_offset_mm','CreateHorizontalApertureOffsetAttr'),('vertical_aperture_offset_mm','CreateVerticalApertureOffsetAttr')]:getattr(camera,method)(float(profile['usd_camera'][key]))
        camera.CreateClippingRangeAttr(Gf.Vec2f(.01,2.));intr=profile['intrinsics']
        self.sensor=CameraSensor(RtxCamera(self.path),resolution=(intr['height'],intr['width']),annotators=['distance_to_image_plane','rgb'])
        if source_context:self.render_tag=camera.GetPrim().CreateAttribute('seeun:renderRequestId',Sdf.ValueTypeNames.Int,custom=True);self.render_tag.Set(0)
        parent=self
        class Writer(rep.Writer):
            def __init__(self):self.version='0.1.0';self.annotators=['distance_to_image_plane','rgb','camera_params','ReferenceTime'];self.last=-float('inf');self.annotators+=([rep.AnnotatorRegistry.get_annotator('Attribute',init_params=dict(prims=[parent.path],attribute='seeun:renderRequestId'))] if source_context else [])
            def write(self,data):
                writer_entered=time.monotonic()
                if source_context and getattr(parent,'capture_closed',False):return
                n,d=data['reference_time'];stamp=float(n/d)
                depth=data['distance_to_image_plane'];rgb=data.get('rgb');rgb=rgb.get('data') if isinstance(rgb,dict) else rgb
                if parent.raw_display_enabled and isinstance(depth,np.ndarray) and depth.size:parent.offer_display(depth,rgb,stamp,[int(n),int(d)],int(data['swhFrameNumber']),writer_entered_wall=writer_entered)
                if ((stamp<=self.last if source_context else stamp-self.last<.2) or parent.count>=1000 or not isinstance(depth,np.ndarray) or not depth.size):return
                self.last=stamp
                owned_depth=depth.copy();owned_rgb=rgb.copy() if isinstance(rgb,np.ndarray) else None
                owned_depth.setflags(write=False)
                if owned_rgb is not None:owned_rgb.setflags(write=False)
                owned_done=time.monotonic()
                image=dict(rgb_array_sha256=hashlib.sha256(owned_rgb.tobytes(order='C')).hexdigest() if owned_rgb is not None else None,source_stamp_s=stamp,reference_time=[int(n),int(d)],renderer_frame_id=int(data['swhFrameNumber']),observation_wall_monotonic_s=writer_entered,writer_callback_entered_wall_monotonic_s=writer_entered,owned_array_copy_completed_wall_monotonic_s=owned_done,writer_received_world_time_s=float(parent.world.current_time) if source_context else None,reference_time_annotator=json.loads(json.dumps(data['ReferenceTime'],default=_json)),depth=owned_depth,rgb=owned_rgb,params=json.loads(json.dumps(data['camera_params'],default=_json)))
                if source_context:
                    image['writer_native_time_mapping_s']=parent.sim_iface.get_simulation_time_at_time((int(n),int(d)))
                    tag=data.get('Attribute');tag=tag.get('data') if isinstance(tag,dict) else tag
                    image['render_buffer_request_tag']=dict(attribute='seeun:renderRequestId',prim=parent.path,values=np.asarray(tag).reshape(-1).tolist() if isinstance(tag,np.ndarray) else None,dtype=str(tag.dtype) if isinstance(tag,np.ndarray) else None,origin='ATTRIBUTE_ANNOTATOR_SAME_WRITER_REFERENCE_TIME_RENDER_RINGBUFFER')
                    parent.record_writer_lifecycle(image)
                    parent.accept_image(image)
                else:parent.pending.append(image)
            def write_metadata(self):pass
        self.writer=Writer();self.writer.attach(str(self.sensor.render_product.GetPath()))
        self.window=None
        if not direct_display or self.raw_display_enabled:
            self.window=ui.Window('Seeun / Wrist RGB + Depth / actual sensor',width=880,height=330)
            with self.window.frame:
                with ui.VStack():
                    self.label=ui.Label('Baseline A / raw camera / no obstacle detector',height=35)
                    with ui.HStack():
                        if direct_display:
                            self.rgb_provider=ui.ByteImageProvider();self.depth_provider=ui.ByteImageProvider()
                            self.rgb=ui.ImageWithProvider(self.rgb_provider,width=424,height=240);self.depth=ui.ImageWithProvider(self.depth_provider,width=424,height=240)
                        else:self.rgb=ui.Image('',width=424,height=240);self.depth=ui.Image('',width=424,height=240)
        if source_context:self.setup_source()
        if direct_display:
            import threading
            self.ui_thread_ident=threading.get_ident();self.last_display_row=None;self.last_label_wall=-float('inf')
            self.detection_display_retained=None;self.detection_display_rows=[];self.last_detection_display_row=None
            self.detection_display_stats=dict(displayed=0,rejected=0,errors=0)
            self.detection_window=ui.Window('Seeun / Detection / SAME captured frame',width=680,height=530)
            self.detection_window.position_x=740;self.detection_window.position_y=70
            with self.detection_window.frame:
                with ui.VStack():
                    self.detection_label=ui.Label('Waiting for classification / Green: obstacle candidate / Orange: uncertain / no STOP decision',height=140,word_wrap=True)
                    self.detection_provider=ui.ByteImageProvider()
                    self.detection_image=ui.ImageWithProvider(self.detection_provider,width=636,height=360)
            self.display_UI_update=omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(lambda event:self.refresh_display_label(),name='Seeun_display_last_frame_age')
            if self.raw_display_enabled:
                from omni.kit.viewport.utility import create_viewport_window
                self.rgb_viewport=create_viewport_window('Seeun / Wrist RGB / existing camera viewport',width=848,height=480,camera_path=self.path)
                if self.rgb_viewport is not None:
                    self.rgb_viewport.viewport_api.resolution=(intr['width'],intr['height'])
                    self.rgb.visible=False
            save(out/'direct_display_setup.json',dict(camera_path=self.path,RGB_route=('EXISTING_CAMERA_SEPARATE_VIEWPORT_RENDER' if self.rgb_viewport is not None else 'ORIGINAL_WRITER_RGB_MEMORY_FALLBACK') if self.raw_display_enabled else 'DISABLED_DETECTION_ONLY',depth_route='ORIGINAL_WRITER_DEPTH_TO_OWN_RGBA_PROVIDER' if self.raw_display_enabled else 'DISABLED_DETECTION_ONLY',RGB_viewport_is_not_same_sensor_frame=self.rgb_viewport is not None,new_camera=False,new_RTX_sensor=False,file_read_or_PNG_completion_dependency=False,ui_thread_ident=self.ui_thread_ident,existing_worker_reused=True))
        save(out/'baseline_camera_profile.json',dict(profile_path=str(profile_path),profile=profile,detector_enabled=False,stimulus_created=False,stage_path_guides_created=False))
    def sample(self,row,statuses):
        if self.source_context:return self.source_sample(row,statuses)
        base=rigid(self.stage,self.seed['robot_base_prim'])
        self.states.append(dict(source_stamp_s=float(row['time_s']),observation=row,statuses=json.loads(json.dumps(statuses)),T_world_camera=rigid(self.stage,self.path).tolist(),T_world_base=base.tolist(),T_base_tool=(np.linalg.inv(base)@rigid(self.stage,self.seed['robot_tcp_prim'])).tolist()))
        while self.pending:
            image=self.pending.popleft();matched=min(self.states,key=lambda r:abs(r['source_stamp_s']-image['source_stamp_s']))
            folder=self.out/'camera_preview'/f'{self.count:05d}';self.count+=1
            receipt=save_preview(folder,image,self.session,self.path)
            skew=abs(matched['source_stamp_s']-image['source_stamp_s']);view=np.asarray(image['params']['cameraViewTransform']).reshape(4,4).T
            pose_error=float(np.max(abs(np.linalg.inv(view)-matched['T_world_camera'])))
            save(folder/'source_state.json',dict(matched,source_skew_s=skew,renderer_pose_matrix_error=pose_error,source_qualified=skew<=.001 and pose_error<=1e-8,SDK_observation_tolerance=None,detector_enabled=False))
            save(self.out/'camera_preview.pointer.json',receipt)
            self.label.text=f'Actual wrist RGB/Depth SIM {image["source_stamp_s"]:.4f}s / no detector'
            if receipt['rgb']:self.rgb.source_url=receipt['rgb']['path']
            self.depth.source_url=receipt['depth_display']['path']
    def close(self):
        self.capture_diagnostic_phase='CLOSE'
        self.display_UI_update=None
        self.save_display_metrics()
        self.writer.detach()
        if self.source_context:
            self.physics_subscription=None
            self.worker.shutdown(wait=True)
            self.poll_shadow_result(float(self.world.current_time))
            self.node.destroy_subscription(self.clock_subscription)
        if self.rgb_viewport is not None:self.rgb_viewport.destroy()

    def setup_source(self):
        from concurrent.futures import ThreadPoolExecutor
        import xml.etree.ElementTree as ET
        import omni.physics.core
        from rosgraph_msgs.msg import Clock
        from isaacsim.core.simulation_manager import SimulationManager
        from capture_sim_scene import read_scene_geometry
        from prepare_cpu_model import read_model_bundle
        from held_geometry_inputs import nominal_definition
        c=self.source_context;self.world=c['world'];self.robot=c['robot'];self.node=c['node']
        self.SimulationManager=SimulationManager;self.sim_iface=SimulationManager._simulation_manager_interface
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='baseline-source-export');self.future=None;self.future_kind=None;self.last_job_kind=None;self.waiting_image=None
        self.render_records={};self.record_order=deque();self.clock_records=deque(maxlen=4096);self.render_sequence=0;self.image_sequence=0
        self.physics_sequence=0;self.last_physics=None;self.writer_callback_sequence=0;self.last_poll_wall=None;self.current_render=None;self.known=None;self.completed=deque(maxlen=1);self.first_source_frames=[];self.handoff_counts={};self.handoff_known_map=None
        self.stats=dict(received=0,overwritten_pending=0,submitted=0,completed=0,associated=0,unassociated=0,worker_failures=0,shadow_calls=0)
        self.lifecycle=[];self.max_completion_age_s=0.
        self.consumer_pending=None;self.consumer_completions=deque(maxlen=1);self.source_submission_rows=deque(maxlen=1);self.current_source_observation=None
        self.consumer_stats=dict(submitted=0,completed=0,pending_overwritten=0,failures=0)
        self.shadow_results=Queue(maxsize=1);self.latest_shadow_result=None;self.shadow_completions=deque(maxlen=1);self.source_epoch=0
        self.point_results=Queue(maxsize=1);self.latest_point_result=None;self.point_completions=deque(maxlen=1)
        self.bundle=read_model_bundle(c['model_bundle']);self.robot_xml=ET.fromstring(self.bundle['robot_description'])
        visual_links={x.get('name') for x in self.robot_xml.findall('link') if x.findall('visual')}
        self.link_paths={}
        for prim in self.stage.Traverse():
            if str(prim.GetPath()).startswith('/World/Robot/') and prim.GetName() in visual_links:self.link_paths.setdefault(prim.GetName(),[]).append(str(prim.GetPath()))
        self.link_paths={k:v[0] for k,v in self.link_paths.items() if len(v)==1}
        self.joint_names=list(self.robot.dof_names);self.arm_indices=[self.joint_names.index('joint_'+str(i)) for i in range(1,7)]
        self.grip_index=self.joint_names.index('rg2_finger_joint')
        folder=self.out/'known_depth_map';folder.mkdir(exist_ok=False)
        objects=read_scene_geometry(self.stage,self.seed)[0];approved=[o['id'] for o in self.seed['world_objects'] if o['role']!='HELD_BLOCK']
        selected=self.seed['reservation_binding']['slot_id'];approved=[i for i in approved if i!=selected]
        known=[o for o in objects if o['id'] in approved]
        if len(known)!=len(approved):raise ValueError('NEW_KNOWN_MAP_APPROVED_INVENTORY_MISMATCH')
        snapshot=dict(session_id=self.session,clock_epoch=0,freeze_source_time=float(self.world.current_time),map_scope='PRE_OBSTACLE_APPROVED',T_world_base=rigid(self.stage,self.seed['robot_base_prim']).tolist(),world_objects=known)
        held=nominal_definition(next(o for o in objects if o['id']==selected),self.bundle)
        save(folder/'map_snapshot.json',snapshot);save(folder/'held_definition.json',held)
        save(folder/'approved_static_ids.json',dict(scope='EXPLICIT_KNOWN_SEED_IDS_BEFORE_ANY_UNKNOWN_ACTOR',approved_static_ids=approved,selected_held_excluded=selected,unknown_actor_created=False))
        refs=[source_ref(q) for q in [c['source_scene'],c['source_state'],folder/'map_snapshot.json',folder/'held_definition.json',folder/'approved_static_ids.json',Path(self.bundle['bundle_path'])/'MODEL_MANIFEST.json']]
        save(folder/'source_refs.json',refs);self.map_snapshot=snapshot;self.held_definition=held;self.approved_static_ids=approved;self.map_refs=refs
        save(folder/'robot_source_inventory.json',dict(visual_link_paths=self.link_paths,missing_visual_links=sorted(visual_links-set(self.link_paths)),named_native_joints=self.joint_names,robot_description_ref=source_ref(Path(self.bundle['bundle_path'])/'robot.urdf'),native_mimic_or_link_difference_will_be_recorded=True))
        def physics(dt,context):
            self.physics_sequence+=1
            self.last_physics=dict(event_sequence=self.physics_sequence,native_physics_step_index=int(SimulationManager.get_num_physics_steps()),native_simulation_time_s=float(SimulationManager.get_simulation_time()),world_time_s=float(self.world.current_time),dt_s=float(dt),wall_monotonic_s=time.monotonic(),event='PHYSICS_POST_STEP_ORDER_2000')
        self.physics_subscription=omni.physics.core.get_physics_simulation_interface().subscribe_physics_on_step_events(pre_step=False,order=2000,on_update=physics)
        def clock(msg):
            self.clock_records.append(dict(clock_ns=int(msg.clock.sec)*10**9+int(msg.clock.nanosec),received_world_time_s=float(self.world.current_time),received_native_physics_step_index=int(SimulationManager.get_num_physics_steps()),received_wall_monotonic_s=time.monotonic(),subscription='/clock'))
        self.clock_subscription=self.node.create_subscription(Clock,'/clock',clock,100)

    def native_stamp(self):
        t=self.sim_iface.get_current_time()
        return dict(native_current_reference_time=[int(t.numerator),int(t.denominator)],native_simulation_time_s=float(self.SimulationManager.get_simulation_time()),native_physics_step_index=int(self.SimulationManager.get_num_physics_steps()),world_time_s=float(self.world.current_time),wall_monotonic_s=time.monotonic())

    def before_render(self):
        from copy import deepcopy
        self.render_sequence+=1;self.render_tag.Set(self.render_sequence);base=rigid(self.stage,self.seed['robot_base_prim']);tool=rigid(self.stage,self.seed['robot_tcp_prim'])
        q=self.robot.get_joint_positions().copy();body=rigid(self.stage,next(o['prim_path'] for o in self.seed['world_objects'] if o['id']==self.seed['reservation_binding']['slot_id']))
        self.current_render=dict(render_request_id=self.render_sequence,render_buffer_tag_authored=dict(attribute='seeun:renderRequestId',prim=self.path,value=self.render_sequence),before_render=self.native_stamp(),physics_event=deepcopy(self.last_physics),q_rad=q[self.arm_indices].tolist(),grip_rad=float(q[self.grip_index]),named_joint_positions_rad=dict(zip(self.joint_names,q.tolist())),attachment_tcp_to_block=(np.linalg.inv(tool)@body).tolist(),T_world_base=base.tolist(),T_base_tool=(np.linalg.inv(base)@tool).tolist(),T_world_camera=rigid(self.stage,self.path).tolist(),actual_visual_link_T_base={name:(np.linalg.inv(base)@rigid(self.stage,path)).tolist() for name,path in self.link_paths.items()},latest_ROS_clock_observed_before_render=deepcopy(self.clock_records[-1]) if self.clock_records else None)

    def after_render(self):
        import omni.graph.core as og
        import rclpy
        value=self.current_render
        if value is None:return
        value['after_render']=self.native_stamp()
        # Rendering flushes Fabric-to-USD transforms without another physics step.
        # Preserve the old readout and independently capture the synchronized one.
        names=('q_rad','grip_rad','attachment_tcp_to_block','T_world_base','T_base_tool','T_world_camera','named_joint_positions_rad','actual_visual_link_T_base')
        value['before_render_readout']={name:value[name] for name in names}
        base=rigid(self.stage,self.seed['robot_base_prim']);tool=rigid(self.stage,self.seed['robot_tcp_prim'])
        body=rigid(self.stage,next(o['prim_path'] for o in self.seed['world_objects'] if o['id']==self.seed['reservation_binding']['slot_id']))
        q=self.robot.get_joint_positions().copy()
        value.update(q_rad=q[self.arm_indices].tolist(),grip_rad=float(q[self.grip_index]),named_joint_positions_rad=dict(zip(self.joint_names,q.tolist())),attachment_tcp_to_block=(np.linalg.inv(tool)@body).tolist(),T_world_base=base.tolist(),T_base_tool=(np.linalg.inv(base)@tool).tolist(),T_world_camera=rigid(self.stage,self.path).tolist(),actual_visual_link_T_base={name:(np.linalg.inv(base)@rigid(self.stage,path)).tolist() for name,path in self.link_paths.items()})
        value['state_readout_phase']='AFTER_RENDER_FABRIC_SYNCHRONIZATION_NO_PHYSICS_ADVANCE'
        value['q_unchanged_during_render']=value['q_rad']==value['before_render_readout']['q_rad']
        for label,path in [('graph_simulation_time','/Stage3Clock/Time.outputs:simulationTime'),('publisher_input_time','/Stage3Clock/Clock.inputs:timeStamp')]:
            try:value[label]=og.Controller.get(og.Controller.attribute(path))
            except Exception as exc:value[label]=None;value[label+'_error']=str(exc)
        key=Fraction(*value['after_render']['native_current_reference_time'])
        self.render_records.setdefault(key,[]).append(value);self.record_order.append((key,value))
        while len(self.record_order)>2048:
            old,item=self.record_order.popleft();self.render_records[old].remove(item)
            if not self.render_records[old]:del self.render_records[old]
        for _ in range(8):rclpy.spin_once(self.node,timeout_sec=0)
        self.current_render=None

    def record_writer_lifecycle(self,image):
        # This is a causal receipt inside the actual Writer callback, never a
        # nearest-time lookup. The same request object is completed after render.
        self.writer_callback_sequence+=1
        receipt=dict(writer_callback_sequence=self.writer_callback_sequence,
            render_request_id=self.current_render['render_request_id'] if self.current_render else None,
            reference_time=list(image['reference_time']),renderer_frame_id=image['renderer_frame_id'],
            native_at_callback=self.native_stamp(),writer_entered_wall_monotonic_s=image['writer_callback_entered_wall_monotonic_s'])
        image['writer_render_lifecycle']=receipt
        if self.current_render is not None:self.current_render.setdefault('writer_callback_receipts',[]).append(receipt)

    def accept_image(self,image):
        self.stats['received']+=1;image['frame_seq']=self.image_sequence;self.image_sequence+=1
        image['latest_slot_registered_wall_monotonic_s']=time.monotonic()
        if self.waiting_image is not None:self.stats['overwritten_pending']+=1
        self.waiting_image=image

    def source_sample(self,row,statuses):
        self.current_source_observation=dict(session_id=self.session,clock_epoch=self.source_epoch,clock_basis='SIM_TIME',source_s=float(row['time_s']),observed_wall_monotonic_s=time.monotonic())
        compact=self.source_context.get('compact_stop_handoff')
        if compact is not None:
            compact_status=compact.poll(lifecycle_phase=getattr(self,'capture_diagnostic_phase','UNOBSERVED'))  # Same existing call; diagnostic data only.
            if compact_status is not None:
                save(self.out/'compact_stop_status.json',compact_status)
                contact=self.source_context.get('joint_compact_input_contact')
                if contact is not None and compact_status['status']=='CURRENT_COMPACT_STOP_INPUT_READY_NOT_SDK':
                    # Explicit main-thread source contact only, no SDK/planner.
                    joint_status=contact()
                    if joint_status is not None:save(self.out/'joint_current_input_status.json',joint_status)
        self.poll_source(float(row['time_s']))
        if self.future is not None:return
        if self.raw_display_enabled and self.display_latest is not None and (self.last_job_kind!='display' or self.waiting_image is None):
            from .camera_preview import prepare_memory_display
            packet=self.display_latest;self.display_latest=None;self.future_kind=self.last_job_kind='display'
            packet['worker_submitted_wall_monotonic_s']=time.monotonic()
            self.future=self.worker.submit(prepare_memory_display,packet);return
        if self.consumer_pending is not None:
            job=self.consumer_pending;self.consumer_pending=None
            self.consumer_stats['submitted']+=1;self.future_kind=self.last_job_kind='consumer'
            self.future=self.worker.submit(self.run_consumer_job,job);return
        if self.waiting_image is None:return
        image=self.waiting_image;n,d=image['reference_time']
        # Match the independent native render->simulation-time mapping, not a
        # nearby timestamp or the arrival time of a ROS subscription.
        events=render_candidates(image,self.record_order)
        match,reason=associate_render_event(image,events)
        clocks=[c for c in self.clock_records if c['clock_ns']*d==n*10**9]
        # ROS delivery is optional original evidence. Never hold a physical
        # source packet for .12s waiting for the matching subscription message.
        self.waiting_image=None
        from copy import deepcopy
        diagnostics=events if events else [e for _,e in list(self.record_order)[-4:]]
        payload=dict(source_identity=dict(session_id=self.session,clock_epoch=self.source_epoch),image=image,candidate_events=deepcopy(events if events else diagnostics),event=deepcopy(match),association_reason=reason,clock=deepcopy(clocks[0]) if clocks else None,latest_clock=deepcopy(self.clock_records[-1]) if self.clock_records else None,submitted_source_s=float(row['time_s']),submitted_wall_monotonic_s=time.monotonic(),stats=dict(self.stats))
        submission=dict(frame_seq=image['frame_seq'],source_stamp_s=image['source_stamp_s'],submitted_source_s=float(row['time_s']),submitted_wall_monotonic_s=payload['submitted_wall_monotonic_s'],source_age_at_submission_s=float(row['time_s'])-image['source_stamp_s'])
        self.record_handoff('submission',submission,self.source_submission_rows)
        self.stats['submitted']+=1
        self.future_kind=self.last_job_kind='export'
        self.future=self.worker.submit(self.export_source,payload)

    def export_source(self,payload):
        worker_entered=time.monotonic();export_started=worker_entered
        from copy import deepcopy
        image=payload['image'];event=payload['event'];seq=image['frame_seq'];folder=self.out/'camera_preview'/f'{seq:05d}'
        baseline_candidate=self.minimal_evidence and event is not None and self.baseline_retained<2
        full_diagnostics=not self.minimal_evidence
        if full_diagnostics and self.evidence_budget_bytes:
            full_diagnostics=self.recorded_bytes()+64*1024**2<=self.evidence_budget_bytes
        result=(save_preview if baseline_candidate or full_diagnostics else save_preview_metadata)(folder,image,payload['source_identity']['session_id'],self.path)
        payload['recording_preview']=result

        preview_persisted=time.monotonic()
        source=event if event is not None else dict(q_rad=None,grip_rad=None,attachment_tcp_to_block=None,T_world_base=None,T_world_camera=None,T_base_tool=None)
        save(folder/'source_state.json',dict(scope='ACTUAL_RENDER_REQUEST_EVENT_NOT_NEAREST_TIMESTAMP',source=source,SDK_observation_tolerance=None))
        save(folder/'render_event.json',event);save(folder/'candidate_render_events_UNASSOCIATED_DIAGNOSTIC.json',payload['candidate_events']);save(folder/'clock_observation.json',dict(matching_observed_clock=payload['clock'],latest_delayed_clock=payload['latest_clock'],clock_value_synthesized=False))
        save(folder/'writer_event.json',{k:v for k,v in image.items() if k not in ('rgb','depth')})
        save(folder/'association_diagnostic.json',dict(reason=payload['association_reason'],buffer_tag=image.get('render_buffer_request_tag'),writer_callback_lifecycle=image.get('writer_render_lifecycle'),candidate_render_request_ids=[e['render_request_id'] for e in payload['candidate_events']],candidate_native_SIM_s=[e['after_render']['native_simulation_time_s'] for e in payload['candidate_events']],original_writer_native_time_mapping_s=image['writer_native_time_mapping_s'],nearest_or_rounded_mapping_used=False,source_from_callback_current_state=False))
        refs=[source_ref(folder/n) for n in ['source_state.json','render_event.json','clock_observation.json','writer_event.json','receipt.json','camera_params.json']]
        tag_values=(image.get('render_buffer_request_tag') or {}).get('values')
        common=dict(**payload['source_identity'],frame_seq=seq,render_request_id=tag_values[0] if isinstance(tag_values,list) and len(tag_values)==1 else None,rgb_array_sha256=image.get('rgb_array_sha256'),q_rad=source['q_rad'],grip_rad=source['grip_rad'],attachment_tcp_to_block=source['attachment_tcp_to_block'],T_world_base=source['T_world_base'],T_world_camera=source['T_world_camera'],T_base_tool=source['T_base_tool'],T_tool_camera_optical=self.profile['T_tool_camera_optical'],reference_time=image['reference_time'],renderer_frame_id=image['renderer_frame_id'],depth_array_sha256=__import__('hashlib').sha256(image['depth'].tobytes(order='C')).hexdigest())
        same=event is not None
        if not same and self.source_context.get('fresh_foreground_stop',False):self.latest_foreground_entry=None
        tick=event['before_render']['native_physics_step_index'] if event else None
        association=dict(common,scope='ACTUAL_SOURCE_TICK',same_tick_verified=same,physical_source_pair_verified=same,ROS_delivery_verified=payload['clock'] is not None,latest_received_ros_clock_ns=payload['latest_clock']['clock_ns'] if payload['latest_clock'] else None,source_ros_clock_ns=payload['clock']['clock_ns'] if payload['clock'] else None,physics_step_index=tick,state_physics_step_index=tick,tf_physics_step_index=tick,image_physics_step_index=tick if event else None,source_refs=refs,proof_method=('INDEPENDENT_RENDER_BUFFER_REQUEST_TAG_PHYSICS_Q_TF_VIEW' if payload['association_reason']=='EXACT_RENDER_BUFFER_REQUEST_TAG_ACTUAL_PHYSICS_Q_TF_VIEW' else 'INDEPENDENT_NATIVE_RATIONAL_RENDER_REQUEST_AND_PHYSICS_COUNTER_CAMERA_VIEW_WITH_DELAYED_ORIGINAL_ROS_MESSAGE'),reason=payload['association_reason'],state_world_time_s=event['before_render']['world_time_s'] if event else None)
        state_stamp=event['before_render']['world_time_s'] if event else None
        frame=dict(common,schema='wrist-depth-frame/0.1',source_kind='SIM_DEPTH',clock_basis='SIM_TIME',source_stamp_s=image['source_stamp_s'],received_stamp_s=image['writer_received_world_time_s'],robot_state_stamp_s=event['after_render']['world_time_s'] if event else None,transform_stamp_s=event['after_render']['world_time_s'] if event else None,base_frame_id=self.seed['robot_base_prim'],tool_frame_id=self.seed['robot_tcp_prim'],optical_frame_id=self.profile['optical_frame_id'],calibration_id=self.profile['profile_id'],calibration_scope=self.profile['calibration_scope'],intrinsics=self.profile['intrinsics'],camera_params=image['params'],depth_unit='METER',depth_scale_m=1.,depth_representation='IMAGE_PLANE_Z',pixel_convention=dict(offset_uv=[0.,0.],status='UNVERIFIED',source_refs=[]),source_association=association,source_refs=refs)
        save(folder/'frame_input.json',frame)
        defer_named_link_diagnostic=bool(self.minimal_evidence and self.source_context.get('fresh_foreground_stop',False))
        if event and not defer_named_link_diagnostic:self.export_named_link_diagnostic(folder,event)
        frame_evidence_persisted=time.monotonic()
        # Only an explicitly configured postSTOP publisher consumes this raw
        # source tick. Classification/STOP do not depend on its success.
        publish_owner=self.source_context.get('publish_stopped_source')
        owner_publication_ref=publish_owner(folder,frame) if same and publish_owner is not None else None
        shadow=None
        if self.known is None:
            from isaac_sim.depth_obstacles.novel_depth.geometry import freeze_known_geometry
            self.known=freeze_known_geometry(self.map_snapshot,self.bundle,self.held_definition,self.approved_static_ids,self.map_refs)
            save(self.out/'known_depth_map/geometry_inventory.json',json.loads(json.dumps(dict(self.known['metadata']),default=plain_value)))
            if self.source_context.get('compact_stop_handoff') is not None:
                # Required original map parent is complete before selected point work.
                save(self.out/'known_depth_map/consumer_geometry_inventory.json',dict(map_digest=self.known['digest'],metadata=json.loads(json.dumps(dict(self.known['metadata']),default=plain_value))))
        if same:
            review,shadow=self.compute_shadow(folder,payload,frame,owner_publication_ref=owner_publication_ref)
            if event and defer_named_link_diagnostic:
                trace_start=time.monotonic()
                try:self.export_named_link_diagnostic(folder,event)
                except Exception as exc:shadow['named_link_diagnostic_error']=dict(error=str(exc),error_type=type(exc).__name__)
                shadow['named_link_diagnostic_timing']=dict(start_wall_monotonic_s=trace_start,end_wall_monotonic_s=time.monotonic(),source_frame_unchanged=True)

            diagnostic_start=time.monotonic()
            try:
                self.export_shadow_diagnostics(folder,review,shadow,persist=full_diagnostics,project_points=not (self.minimal_evidence and self.source_context.get('fresh_foreground_stop',False)))
            except Exception as exc:
                # A diagnostic failure does not replace an already published
                # compute result with a fictitious detector failure.
                shadow['diagnostic_error']=dict(error=str(exc),error_type=type(exc).__name__)
            shadow['diagnostic_export']=dict(start_wall_monotonic_s=diagnostic_start,end_wall_monotonic_s=time.monotonic())
            save(folder/'shadow_review.json',shadow)
        product=dict(folder=folder,payload=payload,frame=frame,review=review if same else None,shadow=shadow)
        reasons=['actual_stopped_owner'] if owner_publication_ref else []
        if baseline_candidate:reasons.append('baseline')
        counts=(shadow or {}).get('counts') or {}
        if self.minimal_evidence:
            if (not same or (shadow or {}).get('guard')) and 'first_failure' not in self.retention_kinds:reasons.append('first_failure')
            if counts.get('foreground',0)>0 and 'first_positive' not in self.retention_kinds:reasons.append('first_positive')
            if (same and self.recording_accepted_source_s is not None and image['source_stamp_s']>=self.recording_accepted_source_s and
                    self.initial_recording_q is not None and max(abs(np.asarray(frame['q_rad'])-self.initial_recording_q))>1e-4 and
                    counts.get('foreground')==0 and 'moving_zero' not in self.retention_kinds):reasons.append('moving_zero')
            if reasons:self.persist_selected_product(product,reasons)
        elif owner_publication_ref:self.persist_selected_product(product,reasons)
        if owner_publication_ref:
            capture_value=dict(scope='SAME_ORIGINAL_CAPTURE_FOR_NONEXECUTABLE_STOP_OWNER',owner_publication=owner_publication_ref,selected_raw_bundle=source_ref(folder/'retained_raw_artifacts.json'),frame_input=source_ref(folder/'frame_input.json'),recaptured=False)
            capture_path=folder/'stopped_owner_capture.json'
            if self.source_context.get('compact_stop_handoff') is not None and capture_path.exists():
                if json.loads(capture_path.read_text())!=capture_value:raise ValueError('EARLY_COMPLETE_CAPTURE_CHANGED')
            else:save(capture_path,capture_value)
        self.latest_evidence_product=product
        export_finished=time.monotonic()
        timings=dict(writer_callback_entered_wall_monotonic_s=image.get('writer_callback_entered_wall_monotonic_s'),owned_array_copy_completed_wall_monotonic_s=image.get('owned_array_copy_completed_wall_monotonic_s'),latest_slot_registered_wall_monotonic_s=image.get('latest_slot_registered_wall_monotonic_s'),worker_submitted_wall_monotonic_s=payload['submitted_wall_monotonic_s'],worker_entered_wall_monotonic_s=worker_entered,export_started_wall_monotonic_s=export_started,export_finished_wall_monotonic_s=export_finished,worker_queue_s=worker_entered-payload['submitted_wall_monotonic_s'],preview_persisted_wall_monotonic_s=preview_persisted,frame_evidence_persisted_wall_monotonic_s=frame_evidence_persisted,compute_started_wall_monotonic_s=shadow.get('start_wall_monotonic_s') if shadow else None,compute_finished_wall_monotonic_s=shadow.get('compute_finished_wall_monotonic_s') if shadow else None,compute_published_wall_monotonic_s=shadow.get('published_wall_monotonic_s') if shadow else None,diagnostic_export=shadow.get('diagnostic_export') if shadow else None,GPU_acquisition_measured=False)
        save(folder/'source_export_timing.json',timings)
        return dict(preview=result,frame_input=source_ref(folder/'frame_input.json'),source_associated=same,source_stamp_s=image['source_stamp_s'],submitted_source_s=payload['submitted_source_s'],submitted_wall_monotonic_s=payload['submitted_wall_monotonic_s'],completed_wall_monotonic_s=time.monotonic(),timings=timings,shadow=shadow,payload_retained=bool(result.get('depth') or (folder/'retained_raw_artifacts.json').exists()),retention_reasons=reasons)

    def export_named_link_diagnostic(self,folder,event):
        from prepare_cumotion_model import urdf_transforms
        fk=urdf_transforms(self.robot_xml,event['q_rad'],event['grip_rad'])
        save(folder/'actual_named_joint_and_link_review.json',dict(named_joint_positions_rad=event['named_joint_positions_rad'],actual_visual_link_T_base=event['actual_visual_link_T_base'],URDF_mimic_from_scalar_grip_T_base={k:v.tolist() for k,v in fk.items() if k in event['actual_visual_link_T_base']},max_matrix_error_by_link={k:float(np.max(abs(np.asarray(v)-fk[k]))) for k,v in event['actual_visual_link_T_base'].items() if k in fk},status='RAW_DIFFERENCES_RECORDED_NOT_MODEL_CORRECTED'))

    def compute_shadow(self,folder,payload,frame,*,owner_publication_ref=None):
        """Worker-only compute boundary; publication precedes diagnostic IO.

        The single worker owns review arrays until all exports finish. The
        capacity-one queue and one retained latest result extend that lifetime
        to the main thread without sharing a reusable renderer buffer.
        """
        from copy import deepcopy
        from isaac_sim.depth_obstacles.novel_depth.replay_saved import evaluate_depth_frame
        started=time.monotonic();review=None
        measure_worker=self.source_context.get('fresh_foreground_stop',False)
        if measure_worker:
            worker_ident=threading.get_ident();worker_wall_start_ns=time.perf_counter_ns();worker_cpu_start_ns=time.thread_time_ns()
        try:
            model,evidence=self.shadow_error_model()
            if self.known['metadata']['map_scope']!='PRE_OBSTACLE_APPROVED' or frame['source_association']['scope']!='ACTUAL_SOURCE_TICK':raise ValueError('ACTUAL_PRE_OBSTACLE_SOURCE_REQUIRED')
            review=evaluate_depth_frame(payload['image']['depth'],self.known,frame,model,dict(clock_basis='SIM_TIME',threshold_status='SIM_TEST_PARAMETER',max_age_s=.12,max_pose_skew_s=.001,min_depth_m=.02,max_depth_m=2.),now_source_s=payload['submitted_source_s'])
            review['raw_owned_depth']=payload['image']['depth']
            detection=review.get('detection') or {}
            shadow=dict(status=review['status'],guard=review['guard'],reason=review.get('reason'),projected_available=detection.get('projected') is not None,qualification_evidence=evidence,classification_error_status=model['status'],result_product='CLASSIFICATION_ONLY_PROJECTION_DEFERRED',projection_ready=False,execution_allowed=False,world_clear_allowed=False,risk_qualified=False,stop_intent=False,error_model_ref=evidence.get('error_ref'))
            if shadow['error_model_ref'] is None:
                save(folder/'classification_error_model.json',model);shadow['error_model_ref']=source_ref(folder/'classification_error_model.json')
            if detection.get('counts') is not None:
                shadow.update(map_digest=detection['map_digest'],error_model_digest=detection['error_model_digest'],effective_pixel_convention=detection['effective_pixel_convention'],source_clock_review=review['expected']['source_clock_review'])
                shadow['Depth_timings_s']=dict(expected=review.get('expected',{}).get('render_timings_s'),compare=detection.get('compare_timings_s'))
                shadow.update(counts=detection['counts'],reason_counts={k:int(v.sum()) for k,v in detection['reason_masks'].items()},qualification_ref=detection.get('qualification_ref'),classification_scope=detection.get('classification_scope'),point_uncertainty_status=detection.get('uncertainty_status'))
        except Exception as exc:
            shadow=dict(status='SHADOW_CONTRACT_REJECTED',guard=True,error=str(exc),error_type=type(exc).__name__)
        finished=time.monotonic()
        if measure_worker:
            worker_cpu_end_ns=time.thread_time_ns();worker_wall_end_ns=time.perf_counter_ns()
            shadow['worker_evaluation_performance']=dict(scope='SAME_EXISTING_WORKER_EVALUATION_PERFORMANCE_ONLY_NOT_SOURCE_CLOCK',thread_ident_start=worker_ident,thread_ident_end=threading.get_ident(),wall_start_perf_counter_ns=worker_wall_start_ns,wall_end_perf_counter_ns=worker_wall_end_ns,thread_CPU_start_ns=worker_cpu_start_ns,thread_CPU_end_ns=worker_cpu_end_ns,wall_s=(worker_wall_end_ns-worker_wall_start_ns)/1e9,thread_CPU_s=(worker_cpu_end_ns-worker_cpu_start_ns)/1e9,non_thread_CPU_wall_s=((worker_wall_end_ns-worker_wall_start_ns)-(worker_cpu_end_ns-worker_cpu_start_ns))/1e9,non_CPU_wall_is_not_exclusively_GIL_wait=True,other_native_worker_CPU_included=False,used_for_TTL_or_execution=False)
        shadow.update(start_wall_monotonic_s=started,compute_finished_wall_monotonic_s=finished,automatic_cancel_allowed=False,live_observation_admitted=False,original_frame_pixel_convention='UNVERIFIED',point_error_model='UNMEASURED')
        if self.source_context.get('fresh_foreground_stop',False):
            from .novel_depth.foreground_stop_notice import make_foreground_stop_notice
            self.latest_foreground_entry=None
            notice=make_foreground_stop_notice(review,frame,self.known,completed_source_observation=dict(self.current_source_observation)) if review is not None else None
            self.latest_foreground_entry=(dict(notice=notice,folder=folder,payload=payload,frame=frame,review=review,shadow=shadow,publish_prepare_wall_monotonic_s=time.monotonic()) if notice is not None else None)
        compact=self.source_context.get('compact_stop_handoff')
        if compact is not None and owner_publication_ref is not None and review is not None and not review['guard']:
            try:
                # The original foreground notice was already published. Required
                # raw/qTF/owner proof completes before legacy copy/UI/diagnostics.
                product=dict(folder=folder,payload=payload,frame=frame,review=review,shadow=shadow)
                shadow['compact_early_capture']=compact.prepare_worker(folder=folder,payload=payload,frame=frame,
                    review=review,shadow=shadow,owner_publication=owner_publication_ref,
                    map_ref=source_ref(self.out/'known_depth_map/consumer_geometry_inventory.json'),
                    model_ref=source_ref(Path(self.bundle['bundle_path'])/'MODEL_MANIFEST.json'),
                    persist=lambda:self.persist_selected_product(product,['actual_stopped_owner','compact_source_early']))
            except Exception as exc:
                # Failure of this additional input path does not erase a STOP
                # notice or become a complete point/current-owner claim.
                shadow['compact_early_capture_rejected']=dict(error=str(exc),error_type=type(exc).__name__,SDK_READY=False)
        image=payload['image']
        snapshot=None
        if review is not None:
            # Projection materialization mutates its private dictionary later.
            # The main thread gets a separate classification dictionary and
            # shared read-only arrays, never that mutable projection workspace.
            detection={}
            for key,value in review['detection'].items():
                if key=='_projection_inputs':continue
                if isinstance(value,np.ndarray):detection[key]=np.frombuffer(value.tobytes(order='C'),dtype=value.dtype).reshape(value.shape)
                elif key=='reason_masks':
                    detection[key]={name:np.frombuffer(mask.tobytes(order='C'),dtype=mask.dtype).reshape(mask.shape) for name,mask in value.items()}
                else:detection[key]=deepcopy(value)
            snapshot=dict(status=review['status'],guard=review['guard'],detection=detection)
        if snapshot is not None and not snapshot['guard'] and getattr(self,'direct_display',False):
            from .camera_preview import prepare_detection_display
            try:
                overlay=prepare_detection_display(dict(image,source_identity=payload['source_identity']),frame,snapshot['detection'])
                snapshot['display']=overlay
                review['display_result']=overlay
                shadow['display_preparation']={k:v for k,v in overlay.items() if k!='rgba'}
            except Exception as exc:
                shadow['display_rejected']=dict(error=str(exc),error_type=type(exc).__name__,visual_only=True)
        notice=dict(**payload['source_identity'],frame_seq=image['frame_seq'],source_stamp_s=image['source_stamp_s'],frame_input=source_ref(folder/'frame_input.json'),submitted_source_s=payload['submitted_source_s'],worker_submitted_wall_monotonic_s=payload['submitted_wall_monotonic_s'],summary=deepcopy(shadow),published_wall_monotonic_s=time.monotonic())
        # No blocking put, overwrite, extra thread, or unbounded completion list.
        # A full slot signals a caller lifecycle error and is not silently lost.
        self.shadow_results.put_nowait((notice,snapshot))
        shadow['published_wall_monotonic_s']=notice['published_wall_monotonic_s']
        return review,shadow

    def export_shadow_diagnostics(self,folder,review,shadow,*,persist=True,project_points=True):
        if not review:return
        if self.source_context.get('unlabelled_static_shadow') and review.get('detection') and not review['guard']:
            from isaac_sim.depth_obstacles.novel_depth.replay_saved import export_depth_diagnostics
            from isaac_sim.depth_obstacles.novel_depth.difference import materialize_projection
            inventory=self.out/'known_depth_map/consumer_geometry_inventory.json'
            if not inventory.exists():
                inventory.parent.mkdir(parents=True,exist_ok=True)
                save(inventory,dict(map_digest=self.known['digest'],metadata=json.loads(json.dumps(dict(self.known['metadata']),default=plain_value))))
            if not project_points:
                # The stop signal uses classification, not a 3D risk product.
                # Keep original raw/masks for selected postSTOP/offline export.
                shadow.update(point_projection_deferred=True,point_projection_scope='CLASSIFICATION_ONLY_SIM_FOREGROUND_STOP',projection_ready=False,projected_available=False)
                return
            frame=review['expected']['frame_state'];pending=review['detection'].get('_projection_inputs')
            if pending is not None:
                expected_camera=np.asarray(review['expected']['T_base_camera_optical']);projected_tool=np.asarray(pending['frame']['T_tool_camera_optical']);source_tool=np.asarray(frame['T_base_tool'])
                save(folder/'producer_TF_trace.json',dict(scope='ACTUAL_NATIVE_PRODUCER_INTERMEDIATES_NOT_RECONSTRUCTED',source_frame=source_ref(folder/'frame_input.json'),expected_T_base_camera_optical=expected_camera.tolist(),source_T_base_tool=source_tool.tolist(),source_T_world_base=frame['T_world_base'],source_T_world_camera=frame['T_world_camera'],source_T_tool_camera_optical=frame['T_tool_camera_optical'],expected_camera_operation='inv(asarray(T_world_base)) @ asarray(T_world_camera) @ diag(1,-1,-1,1) as implemented by original render_expected_depth',deferred_projected_frame_T_tool_camera_optical=projected_tool.tolist(),recomposed_T_base_camera_optical=(source_tool@projected_tool).tolist(),operation_order='projected_tool = inv(asarray(source_T_base_tool)) @ asarray(expected_T_base_camera_optical); recomposed = source_T_base_tool @ projected_tool',shape=list(expected_camera.shape),dtype=str(expected_camera.dtype),numpy_version=np.__version__,max_abs_recomposition_difference=float(np.max(abs(source_tool@projected_tool-expected_camera))),official_TF_tolerance=None))
            started=time.monotonic();materialize_projection(review['detection'])
            shadow['projection_materialization']=dict(start_wall_monotonic_s=started,end_wall_monotonic_s=time.monotonic())
            from copy import deepcopy
            frame=review['expected']['frame_state'];detection=review['detection']
            shadow.update(projected_available=detection.get('projected') is not None,projection_ready=True,result_product='FULL_POINT_PRODUCT_DIAGNOSTICS_SHADOW')
            summary=deepcopy(shadow);summary.update(result_product='FULL_POINT_PRODUCT_SHADOW',projection_ready=True,projected_available=True,projected_digest=detection['projected']['digest'],point_count=len(detection['projected']['pixel_uv']))
            notice=dict(session_id=frame['session_id'],clock_epoch=frame['clock_epoch'],frame_seq=frame['frame_seq'],source_stamp_s=frame['source_stamp_s'],frame_input=source_ref(folder/'frame_input.json'),summary=summary,published_wall_monotonic_s=time.monotonic())
            # Projection is now complete and its private workspace is gone.
            # Diagnostic export only reads it; no consumer may mutate it.
            self.point_results.put_nowait((notice,dict(status=review['status'],guard=review['guard'],detection=dict(detection),expected=review['expected'],raw_owned_depth=review['raw_owned_depth'],frame_state=frame,error_model_ref=shadow['error_model_ref'],map_ref=source_ref(inventory))))
            if persist:
                index=export_depth_diagnostics(folder/'shadow_diagnostics',review['expected'],review['detection'],error_model_ref=shadow['error_model_ref'],map_ref=source_ref(inventory),source_frame_ref=source_ref(folder/'frame_input.json'))
                shadow['diagnostic_export_index']=index
                shadow['arrays_and_images']=json.loads(Path(index['path']).read_text())['arrays_and_images']
        if persist and review.get('expected'):
            np.save(folder/'expected_depth.npy',review['expected']['nearest_z_m'],allow_pickle=False)
        if persist and review.get('display_result'):
            from PIL import Image
            overlay=review['display_result'];Image.fromarray(overlay['rgba']).save(folder/'detection_overlay.png')
            save(folder/'detection_overlay_payload.json',{k:v for k,v in overlay.items() if k!='rgba'})
            shadow['display_artifact']=source_ref(folder/'detection_overlay.png')

    def poll_shadow_result(self,now):
        """Main-thread actual clock observation, even while exports still run."""
        products=((self.shadow_results,self.shadow_completions,'latest_shadow_result','shadow_compute_completion.json'),(self.point_results,self.point_completions,'latest_point_result','shadow_point_completion.json'))
        for queue,history,attribute,filename in products:
            try:notice,review=queue.get_nowait()
            except Empty:continue
            observed=time.monotonic();age=now-notice['source_stamp_s']
            identity=notice['session_id']==self.session and notice['clock_epoch']==self.source_epoch
            ordered=not history or notice['source_stamp_s']>history[-1]['source_stamp_s']
            fresh=identity and ordered and 0<=age<=.12
            receipt=dict(notice,completion_observation=dict(session_id=self.session,clock_epoch=self.source_epoch,clock_basis='SIM_TIME',source_s=now,wall_monotonic_s=observed),completion_source_age_s=age,completion_fresh=fresh,identity_verified=identity,source_order_verified=ordered,main_loop_wait_after_publication_s=observed-notice['published_wall_monotonic_s'],live_observation_admitted=False,automatic_cancel_allowed=False,diagnostics_not_required_for_compute_publication=True)
            setattr(self,attribute,(receipt,review) if identity and ordered else None)
            if attribute=='latest_shadow_result' and getattr(self,'direct_display',False):
                if identity and ordered and review is not None and review.get('display') is not None:
                    try:self.apply_detection_display(review['display'],receipt,now)
                    except Exception as exc:
                        self.detection_display_stats['errors']+=1;save(self.out/'detection_display_error.json',dict(error=str(exc),visual_only=True))
                elif notice['summary'].get('display_rejected'):self.detection_display_stats['rejected']+=1
            save(Path(notice['frame_input']['path']).parent/filename,receipt)
            self.record_handoff(attribute,receipt,history,Path(notice['frame_input']['path']).parent/filename)
            if attribute=='latest_point_result' and identity and ordered and self.source_context.get('same_runtime_consumer_handoff') is not None:
                if self.consumer_pending is not None:self.consumer_stats['pending_overwritten']+=1
                self.consumer_pending=dict(folder=Path(notice['frame_input']['path']).parent,product=review,point_receipt=receipt)

    def run_consumer_job(self,job):
        """Existing worker only; no UI/D lock, live-owner creation, or commands."""
        import os,threading
        started=time.monotonic();product=job['product'];folder=job['folder']
        entry_clock=dict(self.current_source_observation)
        try:
            frame=product['frame_state'];age=entry_clock['source_s']-frame['source_stamp_s']
            identity=all(entry_clock[k]==frame[k] for k in ('session_id','clock_epoch','clock_basis'))
            if not identity or not 0<=age<=.12:
                result=dict(status='CURRENT_SOURCE_STALE_BEFORE_CONSUMER',guard=True,entry_age_SIM_s=age,source_identity_verified=identity,expensive_snapshot_not_called=True,risk=None,stop_intent=None,live_intent_eligible=False)
            else:
                from contextlib import nullcontext
                result=self.source_context['same_runtime_consumer_handoff'](product['raw_owned_depth'],dict(detection=product['detection'],expected=product['expected']),frame,producer_buffer_lock=nullcontext(),source_frame_ref=source_ref(folder/'frame_input.json'),classification_ref=source_ref(folder/'shadow_compute_completion.json'),point_ref=source_ref(folder/'shadow_point_completion.json'),map_ref=product['map_ref'],error_ref=product['error_model_ref'],model=self.bundle)
                result['producer_buffer_ownership']='EXCLUSIVE_SAME_WORKER_IMMUTABLE_JOB_LEASE_NO_UI_PHYSICS_D_LOCK'
            exit_clock=dict(self.current_source_observation);exit_identity=all(exit_clock[k]==frame[k] for k in ('session_id','clock_epoch','clock_basis'))
            result.update(final_actual_source_observation=exit_clock,final_age_SIM_s=exit_clock['source_s']-frame['source_stamp_s'],final_fresh=exit_identity and 0<=exit_clock['source_s']-frame['source_stamp_s']<=.12,execution_allowed=False,live_intent_eligible=False,risk=None,stop_intent=None)
        except Exception as exc:
            result=dict(status='SAME_RUNTIME_SHADOW_REJECTED',guard=True,error=str(exc),error_type=type(exc).__name__,execution_allowed=False,stop_intent=None)
        record=dict(frame_seq=product['frame_state']['frame_seq'],source_stamp_s=product['frame_state']['source_stamp_s'],worker_entry_source_observation=entry_clock,worker_exit_source_observation=dict(self.current_source_observation),worker_started_wall_monotonic_s=started,worker_finished_wall_monotonic_s=time.monotonic(),pid=os.getpid(),thread_ident=threading.get_ident(),numpy_version=np.__version__,numpy_file=np.__file__,same_existing_worker=True,current_owner=None,SDK=False,result=result)
        save(folder/'same_runtime_consumer.json',record)
        return record

    def shadow_error_model(self):
        default=dict(status='UNMEASURED',source_refs=[])
        path=self.source_context.get('qualification_report_path') if self.source_context else None
        if not path or not Path(path).exists():return default,dict(status='NO_NEW_SESSION_QUALIFICATION')
        try:
            report=json.loads(Path(path).read_text());ref=report.get('error_ref') or report.get('error_model_ref')
            if not ref:return default,dict(status='QUALIFICATION_ERROR_REF_NOT_PUBLISHED',report=source_ref(path))
            from isaac_sim.depth_obstacles.novel_depth.geometry import _pin
            _pin(ref);model=json.loads(Path(ref['path']).read_text());qualified=report.get('qualified_ref') or report.get('qualification_ref')
            if model.get('status')!='SIM_SCOPED_NUMERICAL_MODEL' or not model.get('qualification_ref'):return default,dict(status='QUALIFICATION_STATUS_NOT_SUPPORTED',report=source_ref(path))
            if qualified is not None and qualified!=model['qualification_ref']:raise ValueError('EXPLICIT_QUALIFICATION_REF_MISMATCH')
            _pin(model['qualification_ref'])
            qualification=json.loads(Path(model['qualification_ref']['path']).read_text())
            if self.session not in qualification['capture_sessions']:
                return default,dict(status='NEW_SESSION_QUALIFICATION_REQUIRED',report=source_ref(path),qualified_ref=model['qualification_ref'],current_session_id=self.session)
            if qualification['model_manifest_sha256']!=self.bundle['manifest_sha256'] or qualification['camera_path']!=self.path:
                raise ValueError('NEW_SESSION_QUALIFICATION_MODEL_OR_CAMERA_MISMATCH')
            return model,dict(status='EXPLICIT_REPORT_REFS_PENDING_EXISTING_DEPTH_SCOPE_CHECK',report=source_ref(path),error_ref=ref,qualified_ref=model['qualification_ref'])
        except (ValueError,KeyError,OSError) as exc:
            return default,dict(status='QUALIFICATION_REF_REJECTED_UNMEASURED_PRESERVED',reason=str(exc))

    def poll_source(self,now):
        ui_poll_accepted=time.monotonic()
        previous=getattr(self,'last_poll_wall',None);self.last_poll_wall=ui_poll_accepted
        if previous is not None and ui_poll_accepted-previous>.1:
            with (self.out/'main_loop_poll_gaps.jsonl').open('a') as journal:journal.write(json.dumps(dict(previous_wall_monotonic_s=previous,poll_wall_monotonic_s=ui_poll_accepted,gap_wall_s=ui_poll_accepted-previous,actual_SIM_s=now))+'\n')
        self.poll_shadow_result(now)
        if self.future is None or not self.future.done():return
        future=self.future;self.future=None;kind=self.future_kind;self.future_kind=None
        if kind=='consumer':
            try:
                record=future.result()
                # A new main-loop observation AFTER receiving the completed
                # consumer product. Never reuse its worker-exit freshness.
                native=self.native_stamp();received=time.monotonic()
                clock=dict(session_id=self.session,clock_epoch=self.source_epoch,clock_basis='SIM_TIME',source_s=float(self.world.current_time),native_stamp=native,wall_monotonic_s=received)
                folder=self.out/'camera_preview'/f"{record['frame_seq']:05d}"
                frame=json.loads((folder/'frame_input.json').read_text())
                identity=frame['session_id']==self.session and frame['clock_epoch']==self.source_epoch and frame['clock_basis']=='SIM_TIME'
                age=clock['source_s']-record['source_stamp_s']
                receipt=dict(scope='ACTUAL_MAIN_LOOP_RECEIPT_AFTER_CONSUMER_COMPLETION_SHADOW_ONLY',consumer_record=source_ref(folder/'same_runtime_consumer.json'),frame_input=source_ref(folder/'frame_input.json'),main_loop_observation=clock,source_age_SIM_s=age,identity_verified=identity,fresh_at_receipt=identity and 0<=age<=.12,final_use_status='UNKNOWN_NO_CURRENT_OWNER_RISK_PRODUCT',point3D_error_m=None,risk=None,stop_intent=None,live_intent_eligible=False,execution_allowed=False)
                save(folder/'same_runtime_consumer_main_receipt.json',receipt)
                self.record_handoff('consumer',dict(frame_seq=record['frame_seq'],source_stamp_s=record['source_stamp_s'],consumer_record=receipt['consumer_record'],main_loop_receipt=source_ref(folder/'same_runtime_consumer_main_receipt.json')),self.consumer_completions);self.consumer_stats['completed']+=1
            except Exception as exc:
                self.consumer_stats['failures']+=1;save(self.out/'consumer_worker_error.json',dict(error=str(exc),error_type=type(exc).__name__,automatic_cancel_allowed=False))
            self.write_handoff(now);return
        if kind=='display':
            try:self.apply_display(future.result(),now,ui_poll_accepted_wall=ui_poll_accepted)
            except Exception as exc:
                self.display_stats['errors']+=1;save(self.out/'direct_display_error.json',dict(error=str(exc),visual_only=True))
            return
        try:
            result=future.result();self.stats['completed']+=1;self.count+=1
            self.stats['associated' if result['source_associated'] else 'unassociated']+=1
            if result['shadow']:
                self.stats['shadow_calls']+=1
                result['shadow'].update(completion_scope='DIAGNOSTIC_EXPORT_COMPLETE_NOT_COMPUTE_COMPLETE',completion_observation=dict(session_id=self.session,clock_epoch=0,clock_basis='SIM_TIME',source_s=now,wall_monotonic_s=ui_poll_accepted),completion_source_age_s=now-result['source_stamp_s'],completion_fresh=0<=now-result['source_stamp_s']<=.12,live_observation_admitted=False)
                save(Path(result['frame_input']['path']).parent/'shadow_completion.json',result['shadow'])
            age=now-result['source_stamp_s'];self.max_completion_age_s=max(self.max_completion_age_s,age)
            result.update(UI_poll_accepted_wall_monotonic_s=ui_poll_accepted,completed_observed_source_s=now,completion_source_age_s=age,completion_fresh=0<=age<=.12,automatic_cancel_allowed=False)
            save(self.out/'camera_preview.pointer.json',result['preview'])
            if not self.direct_display:
                self.label.text=f'Raw source SIM {result["source_stamp_s"]:.4f}s / associated {result["source_associated"]} / shadow only'
                if result['preview']['rgb']:self.rgb.source_url=result['preview']['rgb']['path']
                self.depth.source_url=result['preview']['depth_display']['path']
            folder=Path(result['frame_input']['path']).parent;save(folder/'producer_completion.json',result)
            self.record_handoff('frame',result,self.completed,folder/'producer_completion.json')
            if self.minimal_evidence:
                if 'baseline' in result.get('retention_reasons',[]) and len(self.first_source_frames)<2:self.first_source_frames.append(result)
            elif len(self.first_source_frames)<3:self.first_source_frames.append(result)
        except Exception as exc:
            self.stats['worker_failures']+=1;save(self.out/'source_worker_error.json',dict(error=str(exc),error_type=type(exc).__name__,automatic_cancel_allowed=False))
        self.write_handoff(now)

    def recorded_bytes(self):
        return sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file())

    def persist_selected_product(self,product,reasons):
        from .novel_depth.geometry import _digest
        folder=product['folder'];bundle=folder/'retained_raw_artifacts.json'
        if not bundle.exists():
            preview=product['payload']['recording_preview']
            if not preview.get('depth'):
                preview=save_preview(folder/'retained_raw',product['payload']['image'],self.session,self.path)
            frame=product['frame'];raw=product['payload']['image']['depth']
            if hashlib.sha256(raw.tobytes(order='C')).hexdigest()!=frame['depth_array_sha256']:raise ValueError('SELECTED_RAW_SOURCE_CHANGED')
            index=save_selected_detection_evidence(folder/'retained_detection',product['review'],frame_ref=source_ref(folder/'frame_input.json'),error_ref=(product['shadow'] or {}).get('error_model_ref'),map_ref=source_ref(self.out/'known_depth_map/consumer_geometry_inventory.json') if (self.out/'known_depth_map/consumer_geometry_inventory.json').exists() else None)
            save(bundle,dict(scope='SELECTED_ORIGINAL_CAPTURE_AFTER_CLASSIFICATION_NOT_RECAPTURE',frame_input_ref=source_ref(folder/'frame_input.json'),source_frame_digest=_digest(frame),source_stamp_s=frame['source_stamp_s'],frame_seq=frame['frame_seq'],raw_preview=preview,selected_arrays=index,payload_retained=True,original_metadata_receipt_unchanged=True,selected_at_source_s=float(self.world.current_time)))
        with (self.out/'retention_events.jsonl').open('a') as stream:stream.write(json.dumps(dict(frame_seq=product['frame']['frame_seq'],reasons=reasons,bundle=source_ref(bundle)))+'\n')
        self.retention_kinds.update(reasons)
        if 'baseline' in reasons:
            self.baseline_retained+=1
            if self.initial_recording_q is None:self.initial_recording_q=np.asarray(product['frame']['q_rad']).copy()

    def configure_foreground_stop_binding(self):
        from .novel_depth.geometry import _digest
        from .novel_depth.qualification import load_qualification,camera_scope
        pre=json.loads((self.out/'pre_obstacle_handoff.json').read_text())
        frame=json.loads(Path(pre['frames'][0]['frame_input']['path']).read_text())
        model,evidence=self.shadow_error_model();qualification=load_qualification(frame,self.known,model)
        if qualification is None:raise ValueError('FRESH_CANCEL_NEW_QUALIFIED_BASELINE_REQUIRED')
        self.foreground_stop_binding=dict(session_id=self.session,clock_epoch=self.source_epoch,clock_basis='SIM_TIME',map_digest=self.known['digest'],model_manifest_sha256=self.bundle['manifest_sha256'],qualification_ref=qualification['input_ref'],qualification_digest=qualification['digest'],error_model_digest=_digest(model),calibration_digest=_digest(camera_scope(frame)))
        save(self.out/'foreground_stop_baseline_binding.json',self.foreground_stop_binding)
        return self.foreground_stop_binding

    def record_handoff(self,kind,row,latest,record_path=None):
        # Archive each event once; the live index never serializes growing history.
        entry=dict(kind=kind,frame_seq=row.get('frame_seq') if 'frame_seq' in row else int(Path(row['frame_input']['path']).parent.name),source_stamp_s=row['source_stamp_s'])
        entry.update(record_ref=source_ref(record_path)) if record_path is not None else entry.update(record=row)
        with (self.out/'producer_history.jsonl').open('a') as journal:
            journal.write(json.dumps(entry,ensure_ascii=False,separators=(',',':'))+'\n')
        self.handoff_counts[kind]=self.handoff_counts.get(kind,0)+1
        latest.append(row)

    def write_handoff(self,now):
        if self.handoff_known_map is None:self.handoff_known_map=dict(map_snapshot=source_ref(self.out/'known_depth_map/map_snapshot.json'),held_definition=source_ref(self.out/'known_depth_map/held_definition.json'),approved_static_ids=source_ref(self.out/'known_depth_map/approved_static_ids.json'),source_refs=source_ref(self.out/'known_depth_map/source_refs.json'),model_bundle=str(self.source_context['model_bundle']))
        frames=list(self.first_source_frames)
        if self.completed and (not frames or self.completed[-1]['frame_input']!=frames[-1]['frame_input']):frames.append(self.completed[-1])
        value=dict(schema='moveit-depth-source-producer-handoff/0.2',session_id=self.session,clock_epoch=0,run=str(self.out),status='RAW_SOURCE_BASELINE_ONLY_NOT_B_C_PASS',known_map=self.handoff_known_map,frames=frames,compute_completions=list(self.shadow_completions),point_completions=list(self.point_completions),consumer_completions=list(self.consumer_completions),consumer_stats=self.consumer_stats,source_submissions=list(self.source_submission_rows),source_selection='LATEST_DISTINCT_WRITER_SOURCE_NO_FIXED_SIM_CLASSIFICATION_INTERVAL',stats=dict(self.stats),current_source_s=now,max_completion_source_age_s=self.max_completion_age_s,at_most_one_inflight=True,pending_capacity=1,worker_count=1,automatic_cancel_allowed=False,new_unknown_actor_created=None if self.source_context.get('unlabelled_static_shadow') else False,SDK_execution=False,source_clock_was_paused_for_export=False)
        value['history']=dict(layout='APPEND_ONLY_PER_EVENT_REFS_LIVE_LISTS_BOUNDED',journal_path=str(self.out/'producer_history.jsonl'),event_counts=dict(self.handoff_counts),frames_scope='FIRST_THREE_AND_LATEST',completion_lists_scope='LATEST_ONLY',journal_sha256_deferred_to_offline_snapshot=True)
        if self.direct_display:
            value['direct_display_runtime']=dict(stats=self.display_stats,last_upload=self.display_rows[-1] if self.display_rows else None)
            value['direct_display_implementation_handoff']=source_ref(self.out.parent/'implementation_handoff.json')
        if self.source_context.get('unlabelled_static_shadow'):
            value['status']='RAW_SOURCE_UNLABELLED_STATIC_SHADOW_NOT_C_PASS'
            pre=self.out/'pre_obstacle_handoff.json'
            if not pre.exists() and len(self.first_source_frames)>=2:
                save(pre,dict(value,scope='NEW_SESSION_ACTUAL_PRE_OBSTACLE_BASELINE',new_unknown_actor_created=False,camera_profile=source_ref(self.out/'baseline_camera_profile.json'),loaded_sources=source_ref(self.out/'loaded_runtime_source_pins.json')))
            public=Path(self.source_context.get('pre_obstacle_handoff_public_path',pre))
            if pre.exists() and not public.exists():
                # Stable transfer pathname; every raw/map/session ref continues
                # to point to the actual corrective run, never the failed run.
                save(public,json.loads(pre.read_text()))
        save(self.out/'producer_handoff.json',value)
        save(self.out.parent/'producer_handoff.json',value)

    def flush(self,app,sample,statuses):
        self.capture_diagnostic_phase='FLUSH_DRAIN'
        self.capture_closed=True
        self.display_latest=None
        deadline=time.monotonic()+30
        # Keep native HOLD/physics/render/source advancing while the last bounded job completes.
        while (self.future is not None or self.waiting_image is not None or self.consumer_pending is not None) and time.monotonic()<deadline and app.is_running():
            self.source_context['native_tick']();row=sample()
            from capture_sim_scene import command_counts
            if row['contact_fingers']!=['rg2_left_inner_finger','rg2_right_inner_finger'] or any(command_counts(statuses).values()):raise ValueError('SOURCE_FLUSH_HOLD_GUARD')
            record_owner=self.source_context.get('post_stop_owner_sample')
            if record_owner is not None:record_owner(row,statuses)
            self.source_sample(row,statuses)
            if self.future is None:break
        if self.minimal_evidence:
            if self.trigger_evidence_product is not None:
                self.persist_selected_product(self.trigger_evidence_product,['actual_cancel_trigger'])
                from .novel_depth.foreground_stop_notice import verify_foreground_stop_notice
                entry=self.trigger_evidence_product;metadata=verify_foreground_stop_notice(entry['notice'])
                from .novel_depth.geometry import _digest
                if metadata['source_frame_digest']!=_digest(entry['frame']):raise ValueError('TRIGGER_RETAINED_FRAME_IDENTITY_CHANGED')
                if not np.array_equal(entry['notice'].candidate_mask,entry['review']['detection']['candidate_mask']):raise ValueError('TRIGGER_RETAINED_MASK_CHANGED')
                save(self.out/'conservative_stop_trigger.json',dict(notice=metadata,notice_metadata_sha256=entry['notice'].metadata_sha256,cancel_receipt=self.trigger_stop_receipt,selected_raw_bundle=source_ref(entry['folder']/'retained_raw_artifacts.json'),same_original_packet_retained=True,recaptured=False))
            if self.latest_evidence_product is not None:self.persist_selected_product(self.latest_evidence_product,['terminal_latest_original_capture'])
            save(self.out/'minimal_recording_summary.json',dict(mode='MINIMAL_EVIDENCE',target_bytes=self.evidence_budget_bytes,actual_bytes=self.recorded_bytes(),target_exceeded=self.recorded_bytes()>self.evidence_budget_bytes,essential_evidence_preserved=True,retained_kinds=sorted(self.retention_kinds),all_frame_raw_payloads_retained=False,all_projected_points_archived=False,target_is_not_safety_tolerance=True))
        self.write_handoff(float(self.world.current_time))
        self.save_display_metrics()
        self.capture_diagnostic_phase='FLUSH_COMPLETE'


    def offer_display(self,depth,rgb,stamp,reference_time,renderer_id,*,writer_entered_wall=None):
        # Independent display-only retained copy before the .2 SIM record throttle.
        entered=writer_entered_wall if writer_entered_wall is not None else time.monotonic()
        self.display_stats['writer_frames']+=1
        if self.display_latest is not None:self.display_stats['superseded_display_pending']+=1
        owned_depth=depth.copy();owned_depth.setflags(write=False)
        owned_rgb=rgb.copy() if isinstance(rgb,np.ndarray) else None
        if owned_rgb is not None:owned_rgb.setflags(write=False)
        copy_completed=time.monotonic()
        self.display_latest=dict(depth=owned_depth,rgb=owned_rgb,source_stamp_s=stamp,reference_time=reference_time,
            renderer_frame_id=renderer_id,writer_received_wall_monotonic_s=entered,writer_callback_entered_wall_monotonic_s=entered,owned_array_copy_completed_wall_monotonic_s=copy_completed,latest_slot_registered_wall_monotonic_s=time.monotonic(),writer_received_source_s=float(self.world.current_time))

    def apply_display(self,value,now_source_s,*,ui_poll_accepted_wall=None):
        import threading
        from .camera_preview import upload_memory_provider
        if threading.get_ident()!=self.ui_thread_ident:raise ValueError('UI_APP_THREAD_REQUIRED')
        poll_accepted=ui_poll_accepted_wall if ui_poll_accepted_wall is not None else time.monotonic()
        started=time.monotonic()
        # Retain payload ownership until a later provider upload has replaced it.
        self.display_retained=value
        upload_memory_provider(self.depth_provider,value['depth_rgba'])
        if self.rgb_viewport is None and value['rgb_rgba'] is not None:upload_memory_provider(self.rgb_provider,value['rgb_rgba'])
        ended=time.monotonic();packet=value['input'];self.display_stats['displayed']+=1
        row=dict(display_seq=self.display_stats['displayed'],source_stamp_s=packet['source_stamp_s'],reference_time=packet['reference_time'],renderer_frame_id=packet['renderer_frame_id'],writer_received_wall_monotonic_s=packet['writer_received_wall_monotonic_s'],UI_upload_started_wall_monotonic_s=started,UI_upload_returned_wall_monotonic_s=ended,writer_receive_to_UI_upload_s=ended-packet['writer_received_wall_monotonic_s'],source_age_at_upload_s=now_source_s-packet['source_stamp_s'],UI_upload_cost_s=ended-started,conversion_cost_s=value['conversion_finished_wall_monotonic_s']-value['conversion_started_wall_monotonic_s'],raw_depth_before_sha256=value['raw_depth_before_sha256'],raw_depth_after_sha256=value['raw_depth_after_sha256'],raw_depth_unchanged=value['raw_depth_before_sha256']==value['raw_depth_after_sha256'],GPU_present_or_acquisition_wall_verified=False,preview_files_opened=False)
        packet_times={k:v for k,v in packet.items() if k.endswith('_wall_monotonic_s')}
        row.update(packet_times,worker_entered_wall_monotonic_s=value['worker_entered_wall_monotonic_s'],conversion_started_wall_monotonic_s=value['conversion_started_wall_monotonic_s'],conversion_finished_wall_monotonic_s=value['conversion_finished_wall_monotonic_s'],worker_finished_wall_monotonic_s=value['worker_finished_wall_monotonic_s'],UI_poll_accepted_wall_monotonic_s=poll_accepted,worker_queue_s=value['worker_entered_wall_monotonic_s']-packet['worker_submitted_wall_monotonic_s'],main_loop_wait_after_worker_s=poll_accepted-value['worker_finished_wall_monotonic_s'])
        self.last_display_row=row
        self.display_rows.append(row)
        if len(self.display_rows)>20000:self.display_rows.pop(0)
        self.refresh_display_label(force=True)

    def apply_detection_display(self,value,receipt,now_source_s):
        import threading
        from .camera_preview import upload_memory_provider,detection_frame_label
        if threading.get_ident()!=self.ui_thread_ident:raise ValueError('DETECTION_UI_APP_THREAD_REQUIRED')
        identity=value['source_identity']
        if any(identity[k]!=receipt[k] for k in ('session_id','clock_epoch','frame_seq','source_stamp_s')):raise ValueError('OVERLAY_COMPLETION_IDENTITY_MISMATCH')
        started=time.monotonic();self.detection_display_retained=value
        upload_memory_provider(self.detection_provider,value['rgba']);ended=time.monotonic()
        row=dict(identity,background=value['background'],shape=value['shape'],rgba_sha256=value['rgba_sha256'],foreground_pixels=value['foreground_pixels'],uncertain_pixels=value['uncertain_pixels'],classification_observed_source_s=receipt['completion_observation']['source_s'],classification_age_SIM_s=receipt['completion_source_age_s'],display_observed_source_s=now_source_s,source_age_at_upload_s=now_source_s-identity['source_stamp_s'],fresh_at_upload=0<=now_source_s-identity['source_stamp_s']<=.12,UI_upload_started_wall_monotonic_s=started,UI_upload_returned_wall_monotonic_s=ended,raw_hashes_before=value['raw_hashes_before'],raw_hashes_after=value['raw_hashes_after'],point_or_diagnostic_wait=False,file_read_or_PNG_dependency=False,GPU_present_measured=False,classification_result_product=receipt['summary'].get('result_product'))
        self.last_detection_display_row=row;self.detection_display_rows.append(row);self.detection_display_stats['displayed']+=1
        self.detection_label.text=detection_frame_label(row,now_source_s,ended,computing=True)

    def refresh_display_label(self,*,force=False):
        from .camera_preview import display_frame_label
        now=time.monotonic()
        if not force and now-self.last_label_wall<.25:return
        self.last_label_wall=now
        row=getattr(self,'last_display_row',None)
        if row is not None:self.label.text=display_frame_label(row,now,rgb_viewport=self.rgb_viewport is not None)
        detection=getattr(self,'last_detection_display_row',None)
        if detection is not None:
            from .camera_preview import detection_frame_label
            self.detection_label.text=detection_frame_label(detection,float(self.world.current_time),now,computing=self.future is not None and self.future_kind=='export')

    def save_display_metrics(self):
        if self.direct_display:
            save(self.out/'detection_display_metrics.json',dict(stats=self.detection_display_stats,rows=self.detection_display_rows,display_pending_capacity=1,classification_queue_reused=True,worker_count=1,latest_RGB_viewport_never_used_as_mask_background=True))
        if self.direct_display:save(self.out/'direct_display_metrics.json',dict(scope='WRITER_RECEIVE_TO_PROVIDER_UPLOAD_NOT_GPU_PRESENT_OR_ACQUISITION_LATENCY',stats=self.display_stats,rows=self.display_rows,pending_capacity=1,worker_count=1,source_array_mutated=False,recording_cadence_SIM_s=None,source_selection='LATEST_DISTINCT_WRITER_SOURCE_NO_FIXED_SIM_DELAY',display_cadence_tied_to_recording=False))


def source_ref(path):
    import hashlib
    path=Path(path);return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def plain_value(value):
    from collections.abc import Mapping
    if isinstance(value,Mapping):return dict(value)
    if isinstance(value,(tuple,list)):return list(value)
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)


def render_candidates(image,record_order):
    tag=image.get('render_buffer_request_tag');values=tag.get('values') if tag else None
    if values is not None:
        if len(values)!=1 or type(values[0]) is not int or values[0]<=0:return []
        return [e for _,e in record_order if e['render_request_id']==values[0]]
    return [e for _,e in record_order if e['after_render']['native_simulation_time_s']==image.get('writer_native_time_mapping_s')]


def associate_render_event(image,events):
    """Same-render Attribute ringbuffer tag or original exact native mapping."""
    mapped=image.get('writer_native_time_mapping_s');candidates=[]
    if not isinstance(mapped,(int,float)) or not np.isfinite(mapped):return None,'NATIVE_RENDER_SIM_MAPPING_MISSING'
    for e in events:
        a,b=e['before_render'],e['after_render'];physics=e.get('physics_event')
        if physics is None:continue
        native=a['native_simulation_time_s'];tick=a['native_physics_step_index']
        if any(v!=native for v in (b['native_simulation_time_s'],physics['native_simulation_time_s'],e.get('publisher_input_time'),e.get('graph_simulation_time'))):continue
        if b['native_physics_step_index']!=tick or physics['native_physics_step_index']!=tick:continue
        if e.get('state_readout_phase')=='AFTER_RENDER_FABRIC_SYNCHRONIZATION_NO_PHYSICS_ADVANCE' and e.get('q_unchanged_during_render') is not True:continue
        if any(e.get(k) is None for k in ('q_rad','grip_rad','attachment_tcp_to_block','T_world_base','T_world_camera','T_base_tool')):continue
        camera=np.asarray(e['T_world_camera']);view=np.asarray(image['params']['cameraViewTransform']).reshape(4,4).T
        arithmetic=128*np.finfo(float).eps*max(1.,float(abs(camera).max()))
        if not np.allclose(np.linalg.inv(view),camera,atol=arithmetic,rtol=0):continue
        tag=image.get('render_buffer_request_tag')
        if tag is not None:
            authored=e.get('render_buffer_tag_authored');values=tag.get('values')
            if (not authored or values!=[e['render_request_id']] or type(values[0]) is not int or
                    authored['value']!=e['render_request_id'] or authored['prim']!=tag['prim'] or authored['attribute']!=tag['attribute'] or
                    tag['origin']!='ATTRIBUTE_ANNOTATOR_SAME_WRITER_REFERENCE_TIME_RENDER_RINGBUFFER'):continue
            # Keep old exact proof for existing consumers when it also holds.
            reason=('INDEPENDENT_RENDER_SIM_MAPPING_ACTUAL_PHYSICS_Q_TF_VIEW' if mapped==native else 'EXACT_RENDER_BUFFER_REQUEST_TAG_ACTUAL_PHYSICS_Q_TF_VIEW')
        elif mapped==native:reason='INDEPENDENT_RENDER_SIM_MAPPING_ACTUAL_PHYSICS_Q_TF_VIEW'
        else:continue
        candidates.append((e,reason))
    if len(candidates)==1:return candidates[0]
    return None,'NO_UNIQUE_INDEPENDENT_PHYSICAL_SOURCE_PAIR'
