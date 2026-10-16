"""Existing wrist profile/raw camera for baseline A. No detector or stimulus."""
from collections import deque
from pathlib import Path
from fractions import Fraction
import json,time
import numpy as np
from .camera_preview import save_preview
from .capture_wrist_sim import rigid
from .render_time_probe import _json
from sim_utils import save

class BaselineCamera:
    def __init__(self,app,stage,seed,out,session,*,source_context=None,direct_display=False):
        import omni.kit.app,omni.replicator.core as rep
        import omni.ui as ui
        from pxr import UsdGeom,Gf,Sdf
        omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate('isaacsim.sensors.experimental.rtx',True);app.update()
        from isaacsim.sensors.experimental.rtx import RtxCamera,CameraSensor
        self.direct_display=direct_display;self.display_latest=None;self.display_rows=[];self.display_retained=None;self.rgb_viewport=None
        self.display_stats=dict(writer_frames=0,superseded_display_pending=0,displayed=0,errors=0)
        self.source_context=source_context
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
                if direct_display and isinstance(depth,np.ndarray) and depth.size:parent.offer_display(depth,rgb,stamp,[int(n),int(d)],int(data['swhFrameNumber']),writer_entered_wall=writer_entered)
                if stamp-self.last<.2 or parent.count>=1000 or not isinstance(depth,np.ndarray) or not depth.size:return
                self.last=stamp
                owned_depth=depth.copy();owned_rgb=rgb.copy() if isinstance(rgb,np.ndarray) else None
                owned_done=time.monotonic()
                image=dict(source_stamp_s=stamp,reference_time=[int(n),int(d)],renderer_frame_id=int(data['swhFrameNumber']),observation_wall_monotonic_s=writer_entered,writer_callback_entered_wall_monotonic_s=writer_entered,owned_array_copy_completed_wall_monotonic_s=owned_done,writer_received_world_time_s=float(parent.world.current_time) if source_context else None,reference_time_annotator=json.loads(json.dumps(data['ReferenceTime'],default=_json)),depth=owned_depth,rgb=owned_rgb,params=json.loads(json.dumps(data['camera_params'],default=_json)))
                if source_context:
                    image['writer_native_time_mapping_s']=parent.sim_iface.get_simulation_time_at_time((int(n),int(d)))
                    tag=data.get('Attribute');tag=tag.get('data') if isinstance(tag,dict) else tag
                    image['render_buffer_request_tag']=dict(attribute='seeun:renderRequestId',prim=parent.path,values=np.asarray(tag).reshape(-1).tolist() if isinstance(tag,np.ndarray) else None,dtype=str(tag.dtype) if isinstance(tag,np.ndarray) else None,origin='ATTRIBUTE_ANNOTATOR_SAME_WRITER_REFERENCE_TIME_RENDER_RINGBUFFER')
                    parent.record_writer_lifecycle(image)
                    parent.accept_image(image)
                else:parent.pending.append(image)
            def write_metadata(self):pass
        self.writer=Writer();self.writer.attach(str(self.sensor.render_product.GetPath()))
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
            self.display_UI_update=omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(lambda event:self.refresh_display_label(),name='Seeun_display_last_frame_age')
            from omni.kit.viewport.utility import create_viewport_window
            self.rgb_viewport=create_viewport_window('Seeun / Wrist RGB / existing camera viewport',width=848,height=480,camera_path=self.path)
            if self.rgb_viewport is not None:
                self.rgb_viewport.viewport_api.resolution=(intr['width'],intr['height'])
                self.rgb.visible=False
            save(out/'direct_display_setup.json',dict(camera_path=self.path,RGB_route='EXISTING_CAMERA_SEPARATE_VIEWPORT_RENDER' if self.rgb_viewport is not None else 'ORIGINAL_WRITER_RGB_MEMORY_FALLBACK',depth_route='ORIGINAL_WRITER_DEPTH_TO_OWN_RGBA_PROVIDER',RGB_viewport_is_not_same_sensor_frame=self.rgb_viewport is not None,new_camera=False,new_RTX_sensor=False,file_read_or_PNG_completion_dependency=False,ui_thread_ident=self.ui_thread_ident,existing_worker_reused=True))
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
        self.display_UI_update=None
        self.save_display_metrics()
        self.writer.detach()
        if self.source_context:
            self.physics_subscription=None
            self.worker.shutdown(wait=True)
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
        self.physics_sequence=0;self.last_physics=None;self.writer_callback_sequence=0;self.last_poll_wall=None;self.current_render=None;self.known=None;self.completed=[]
        self.stats=dict(received=0,overwritten_pending=0,submitted=0,completed=0,associated=0,unassociated=0,worker_failures=0,shadow_calls=0)
        self.lifecycle=[];self.max_completion_age_s=0.;self.last_shadow_source=-float('inf')
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
        self.poll_source(float(row['time_s']))
        if self.future is not None:return
        if self.direct_display and self.display_latest is not None and (self.last_job_kind!='display' or self.waiting_image is None):
            from .camera_preview import prepare_memory_display
            packet=self.display_latest;self.display_latest=None;self.future_kind=self.last_job_kind='display'
            packet['worker_submitted_wall_monotonic_s']=time.monotonic()
            self.future=self.worker.submit(prepare_memory_display,packet);return
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
        payload=dict(image=image,candidate_events=deepcopy(events if events else diagnostics),event=deepcopy(match),association_reason=reason,clock=deepcopy(clocks[0]) if clocks else None,latest_clock=deepcopy(self.clock_records[-1]) if self.clock_records else None,submitted_source_s=float(row['time_s']),submitted_wall_monotonic_s=time.monotonic(),stats=dict(self.stats))
        self.stats['submitted']+=1
        self.future_kind=self.last_job_kind='export'
        self.future=self.worker.submit(self.export_source,payload)

    def export_source(self,payload):
        worker_entered=time.monotonic();export_started=worker_entered
        from copy import deepcopy
        from prepare_cumotion_model import urdf_transforms
        image=payload['image'];event=payload['event'];seq=image['frame_seq'];folder=self.out/'camera_preview'/f'{seq:05d}'
        result=save_preview(folder,image,self.session,self.path)
        source=event if event is not None else dict(q_rad=None,grip_rad=None,attachment_tcp_to_block=None,T_world_base=None,T_world_camera=None,T_base_tool=None)
        save(folder/'source_state.json',dict(scope='ACTUAL_RENDER_REQUEST_EVENT_NOT_NEAREST_TIMESTAMP',source=source,SDK_observation_tolerance=None))
        save(folder/'render_event.json',event);save(folder/'candidate_render_events_UNASSOCIATED_DIAGNOSTIC.json',payload['candidate_events']);save(folder/'clock_observation.json',dict(matching_observed_clock=payload['clock'],latest_delayed_clock=payload['latest_clock'],clock_value_synthesized=False))
        save(folder/'writer_event.json',{k:v for k,v in image.items() if k not in ('rgb','depth')})
        save(folder/'association_diagnostic.json',dict(reason=payload['association_reason'],buffer_tag=image.get('render_buffer_request_tag'),writer_callback_lifecycle=image.get('writer_render_lifecycle'),candidate_render_request_ids=[e['render_request_id'] for e in payload['candidate_events']],candidate_native_SIM_s=[e['after_render']['native_simulation_time_s'] for e in payload['candidate_events']],original_writer_native_time_mapping_s=image['writer_native_time_mapping_s'],nearest_or_rounded_mapping_used=False,source_from_callback_current_state=False))
        refs=[source_ref(folder/n) for n in ['source_state.json','render_event.json','clock_observation.json','writer_event.json','receipt.json','camera_params.json']]
        common=dict(session_id=self.session,clock_epoch=0,frame_seq=seq,q_rad=source['q_rad'],grip_rad=source['grip_rad'],attachment_tcp_to_block=source['attachment_tcp_to_block'],T_world_base=source['T_world_base'],T_world_camera=source['T_world_camera'],T_base_tool=source['T_base_tool'],T_tool_camera_optical=self.profile['T_tool_camera_optical'],reference_time=image['reference_time'],renderer_frame_id=image['renderer_frame_id'],depth_array_sha256=__import__('hashlib').sha256(image['depth'].tobytes(order='C')).hexdigest())
        same=event is not None
        tick=event['before_render']['native_physics_step_index'] if event else None
        association=dict(common,scope='ACTUAL_SOURCE_TICK',same_tick_verified=same,physical_source_pair_verified=same,ROS_delivery_verified=payload['clock'] is not None,latest_received_ros_clock_ns=payload['latest_clock']['clock_ns'] if payload['latest_clock'] else None,source_ros_clock_ns=payload['clock']['clock_ns'] if payload['clock'] else None,physics_step_index=tick,state_physics_step_index=tick,tf_physics_step_index=tick,image_physics_step_index=tick if event else None,source_refs=refs,proof_method=('INDEPENDENT_RENDER_BUFFER_REQUEST_TAG_PHYSICS_Q_TF_VIEW' if payload['association_reason']=='EXACT_RENDER_BUFFER_REQUEST_TAG_ACTUAL_PHYSICS_Q_TF_VIEW' else 'INDEPENDENT_NATIVE_RATIONAL_RENDER_REQUEST_AND_PHYSICS_COUNTER_CAMERA_VIEW_WITH_DELAYED_ORIGINAL_ROS_MESSAGE'),reason=payload['association_reason'],state_world_time_s=event['before_render']['world_time_s'] if event else None)
        state_stamp=event['before_render']['world_time_s'] if event else None
        frame=dict(common,schema='wrist-depth-frame/0.1',source_kind='SIM_DEPTH',clock_basis='SIM_TIME',source_stamp_s=image['source_stamp_s'],received_stamp_s=image['writer_received_world_time_s'],robot_state_stamp_s=event['after_render']['world_time_s'] if event else None,transform_stamp_s=event['after_render']['world_time_s'] if event else None,base_frame_id=self.seed['robot_base_prim'],tool_frame_id=self.seed['robot_tcp_prim'],optical_frame_id=self.profile['optical_frame_id'],calibration_id=self.profile['profile_id'],calibration_scope=self.profile['calibration_scope'],intrinsics=self.profile['intrinsics'],camera_params=image['params'],depth_unit='METER',depth_scale_m=1.,depth_representation='IMAGE_PLANE_Z',pixel_convention=dict(offset_uv=[0.,0.],status='UNVERIFIED',source_refs=[]),source_association=association,source_refs=refs)
        save(folder/'frame_input.json',frame)
        if event:
            fk=urdf_transforms(self.robot_xml,event['q_rad'],event['grip_rad'])
            save(folder/'actual_named_joint_and_link_review.json',dict(named_joint_positions_rad=event['named_joint_positions_rad'],actual_visual_link_T_base=event['actual_visual_link_T_base'],URDF_mimic_from_scalar_grip_T_base={k:v.tolist() for k,v in fk.items() if k in event['actual_visual_link_T_base']},max_matrix_error_by_link={k:float(np.max(abs(np.asarray(v)-fk[k]))) for k,v in event['actual_visual_link_T_base'].items() if k in fk},status='RAW_DIFFERENCES_RECORDED_NOT_MODEL_CORRECTED'))
        shadow=None
        if self.known is None:
            from isaac_sim.depth_obstacles.novel_depth.geometry import freeze_known_geometry
            self.known=freeze_known_geometry(self.map_snapshot,self.bundle,self.held_definition,self.approved_static_ids,self.map_refs)
            save(self.out/'known_depth_map/geometry_inventory.json',json.loads(json.dumps(dict(self.known['metadata']),default=plain_value)))
        if same and image['source_stamp_s']-self.last_shadow_source>=2.:
            from isaac_sim.depth_obstacles.novel_depth.replay_saved import evaluate_raw_frame
            self.last_shadow_source=image['source_stamp_s'];start=time.monotonic()
            try:
                model,qualification_evidence=self.shadow_error_model()
                review=evaluate_raw_frame(folder,self.known,model,dict(clock_basis='SIM_TIME',threshold_status='SIM_TEST_PARAMETER',max_age_s=.12,max_pose_skew_s=.001,min_depth_m=.02,max_depth_m=2.),now_source_s=payload['submitted_source_s'])
                shadow=dict(status=review['status'],guard=review['guard'],reason=review.get('reason'),projected_available=review.get('detection',{}).get('projected') is not None,qualification_evidence=qualification_evidence,classification_error_status=model['status'])
                if self.source_context.get('unlabelled_static_shadow') and review.get('detection'):
                    from isaac_sim.depth_obstacles.novel_depth.replay_saved import _diagnostics
                    diagnostics=folder/'shadow_diagnostics';diagnostics.mkdir()
                    d=review['detection'];refs=_diagnostics(diagnostics,review['expected'],d)
                    save(diagnostics/'projected.json',d['projected']);refs['projected']=source_ref(diagnostics/'projected.json')
                    shadow.update(counts=d['counts'],reason_counts={k:int(v.sum()) for k,v in d['reason_masks'].items()},qualification_ref=d.get('qualification_ref'),classification_scope=d.get('classification_scope'),point_uncertainty_status=d.get('uncertainty_status'),arrays_and_images=refs,live_observation_admitted=False)
                if review.get('expected'):
                    expected=review['expected'];np.save(folder/'expected_depth.npy',expected['nearest_z_m'],allow_pickle=False)
            except Exception as exc:shadow=dict(status='SHADOW_CONTRACT_REJECTED',error=str(exc),error_type=type(exc).__name__)
            shadow.update(start_wall_monotonic_s=start,end_wall_monotonic_s=time.monotonic(),automatic_cancel_allowed=False,original_frame_pixel_convention='UNVERIFIED',point_error_model='UNMEASURED')
            save(folder/'shadow_review.json',shadow)
        export_finished=time.monotonic()
        timings=dict(writer_callback_entered_wall_monotonic_s=image.get('writer_callback_entered_wall_monotonic_s'),owned_array_copy_completed_wall_monotonic_s=image.get('owned_array_copy_completed_wall_monotonic_s'),latest_slot_registered_wall_monotonic_s=image.get('latest_slot_registered_wall_monotonic_s'),worker_submitted_wall_monotonic_s=payload['submitted_wall_monotonic_s'],worker_entered_wall_monotonic_s=worker_entered,export_started_wall_monotonic_s=export_started,export_finished_wall_monotonic_s=export_finished,worker_queue_s=worker_entered-payload['submitted_wall_monotonic_s'],GPU_acquisition_measured=False)
        save(folder/'source_export_timing.json',timings)
        return dict(preview=result,frame_input=source_ref(folder/'frame_input.json'),source_associated=same,source_stamp_s=image['source_stamp_s'],submitted_source_s=payload['submitted_source_s'],submitted_wall_monotonic_s=payload['submitted_wall_monotonic_s'],completed_wall_monotonic_s=time.monotonic(),timings=timings,shadow=shadow)

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
            return model,dict(status='EXPLICIT_REPORT_REFS_PENDING_EXISTING_DEPTH_SCOPE_CHECK',report=source_ref(path),error_ref=ref,qualified_ref=model['qualification_ref'])
        except (ValueError,KeyError,OSError) as exc:
            return default,dict(status='QUALIFICATION_REF_REJECTED_UNMEASURED_PRESERVED',reason=str(exc))

    def poll_source(self,now):
        ui_poll_accepted=time.monotonic()
        previous=getattr(self,'last_poll_wall',None);self.last_poll_wall=ui_poll_accepted
        if previous is not None and ui_poll_accepted-previous>.1:
            with (self.out/'main_loop_poll_gaps.jsonl').open('a') as journal:journal.write(json.dumps(dict(previous_wall_monotonic_s=previous,poll_wall_monotonic_s=ui_poll_accepted,gap_wall_s=ui_poll_accepted-previous,actual_SIM_s=now))+'\n')
        if self.future is None or not self.future.done():return
        future=self.future;self.future=None;kind=self.future_kind;self.future_kind=None
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
                result['shadow'].update(completion_observation=dict(session_id=self.session,clock_epoch=0,clock_basis='SIM_TIME',source_s=now,wall_monotonic_s=ui_poll_accepted),completion_source_age_s=now-result['source_stamp_s'],completion_fresh=0<=now-result['source_stamp_s']<=.12,live_observation_admitted=False)
                save(Path(result['frame_input']['path']).parent/'shadow_completion.json',result['shadow'])
            age=now-result['source_stamp_s'];self.max_completion_age_s=max(self.max_completion_age_s,age)
            result.update(UI_poll_accepted_wall_monotonic_s=ui_poll_accepted,completed_observed_source_s=now,completion_source_age_s=age,completion_fresh=0<=age<=.12,automatic_cancel_allowed=False)
            self.completed.append(result)
            save(self.out/'camera_preview.pointer.json',result['preview'])
            if not self.direct_display:
                self.label.text=f'Raw source SIM {result["source_stamp_s"]:.4f}s / associated {result["source_associated"]} / shadow only'
                if result['preview']['rgb']:self.rgb.source_url=result['preview']['rgb']['path']
                self.depth.source_url=result['preview']['depth_display']['path']
            folder=Path(result['frame_input']['path']).parent;save(folder/'producer_completion.json',result)
        except Exception as exc:
            self.stats['worker_failures']+=1;save(self.out/'source_worker_error.json',dict(error=str(exc),error_type=type(exc).__name__,automatic_cancel_allowed=False))
        self.write_handoff(now)

    def write_handoff(self,now):
        value=dict(schema='moveit-depth-source-producer-handoff/0.1',session_id=self.session,clock_epoch=0,run=str(self.out),status='RAW_SOURCE_BASELINE_ONLY_NOT_B_C_PASS',known_map=dict(map_snapshot=source_ref(self.out/'known_depth_map/map_snapshot.json'),held_definition=source_ref(self.out/'known_depth_map/held_definition.json'),approved_static_ids=source_ref(self.out/'known_depth_map/approved_static_ids.json'),source_refs=source_ref(self.out/'known_depth_map/source_refs.json'),model_bundle=str(self.source_context['model_bundle'])),frames=self.completed,stats=dict(self.stats),current_source_s=now,max_completion_source_age_s=self.max_completion_age_s,at_most_one_inflight=True,pending_capacity=1,worker_count=1,automatic_cancel_allowed=False,new_unknown_actor_created=None if self.source_context.get('unlabelled_static_shadow') else False,SDK_execution=False,source_clock_was_paused_for_export=False)
        if self.direct_display:
            value['direct_display_runtime']=dict(stats=self.display_stats,last_upload=self.display_rows[-1] if self.display_rows else None)
            value['direct_display_implementation_handoff']=source_ref(self.out.parent/'implementation_handoff.json')
        if self.source_context.get('unlabelled_static_shadow'):
            value['status']='RAW_SOURCE_UNLABELLED_STATIC_SHADOW_NOT_C_PASS'
            pre=self.out/'pre_obstacle_handoff.json'
            if not pre.exists() and len(self.completed)>=2:
                save(pre,dict(value,scope='NEW_SESSION_ACTUAL_PRE_OBSTACLE_BASELINE',new_unknown_actor_created=False,camera_profile=source_ref(self.out/'baseline_camera_profile.json'),loaded_sources=source_ref(self.out/'loaded_runtime_source_pins.json')))
            public=Path(self.source_context.get('pre_obstacle_handoff_public_path',pre))
            if pre.exists() and not public.exists():
                # Stable transfer pathname; every raw/map/session ref continues
                # to point to the actual corrective run, never the failed run.
                save(public,json.loads(pre.read_text()))
        save(self.out/'producer_handoff.json',value)
        save(self.out.parent/'producer_handoff.json',value)

    def flush(self,app,sample,statuses):
        self.capture_closed=True
        self.display_latest=None
        deadline=time.monotonic()+30
        # Keep native HOLD/physics/render/source advancing while the last bounded job completes.
        while (self.future is not None or self.waiting_image is not None) and time.monotonic()<deadline and app.is_running():
            self.source_context['native_tick']();row=sample()
            from capture_sim_scene import command_counts
            if row['contact_fingers']!=['rg2_left_inner_finger','rg2_right_inner_finger'] or any(command_counts(statuses).values()):raise ValueError('SOURCE_FLUSH_HOLD_GUARD')
            self.source_sample(row,statuses)
            if self.future is None:break
        self.write_handoff(float(self.world.current_time))
        self.save_display_metrics()


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

    def refresh_display_label(self,*,force=False):
        from .camera_preview import display_frame_label
        now=time.monotonic()
        if not force and now-self.last_label_wall<.25:return
        self.last_label_wall=now
        row=getattr(self,'last_display_row',None)
        if row is not None:self.label.text=display_frame_label(row,now,rgb_viewport=self.rgb_viewport is not None)

    def save_display_metrics(self):
        if self.direct_display:save(self.out/'direct_display_metrics.json',dict(scope='WRITER_RECEIVE_TO_PROVIDER_UPLOAD_NOT_GPU_PRESENT_OR_ACQUISITION_LATENCY',stats=self.display_stats,rows=self.display_rows,pending_capacity=1,worker_count=1,source_array_mutated=False,recording_cadence_SIM_s=.2,display_cadence_tied_to_recording=False))


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
