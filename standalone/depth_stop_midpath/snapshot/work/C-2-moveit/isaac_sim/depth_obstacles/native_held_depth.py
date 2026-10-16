"""Fresh native SIM contact grasp + stationary wrist Depth, never hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import traceback
import uuid
from datetime import datetime,timezone

import numpy as np


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,default=lambda x:x.tolist())+'\n')


def capture_held(app,stage,world,robot,tick,seed,motion,controls,sample,statuses,out,model_bundle,profile_path,live_capture=None):
    import omni.kit.app,omni.timeline
    from pxr import Usd,UsdGeom,Gf
    manager=omni.kit.app.get_app().get_extension_manager()
    manager.set_extension_enabled_immediate('isaacsim.sensors.experimental.rtx',True);app.update()
    from isaacsim.sensors.experimental.rtx import RtxCamera,CameraSensor
    from scipy.ndimage import distance_transform_edt
    from scipy.spatial.transform import Rotation
    from isaac_sim.depth_obstacles.capture_wrist_sim import rigid,label,select_masks
    from isaac_sim.depth_obstacles.projection import project_frame
    from prepare_cpu_model import read_model_bundle
    from prepare_gpu_scene import tcp_fk
    from capture_sim_scene import command_counts,read_scene_geometry
    from plan_only import digest
    folder=out/'wrist_depth';folder.mkdir()
    profile=json.loads(Path(profile_path).read_text());intr=profile['intrinsics'];W,H=intr['width'],intr['height']
    if profile['hardware_execution_allowed'] is not False or profile['calibration_scope']!='SIM_NOMINAL_FROM_REAL_PUBLISHED_TF':
        raise ValueError('Explicit SIM published-nominal profile required')
    (folder/'capture_profile.json').write_bytes(Path(profile_path).read_bytes())
    (folder/'capture_source.py').write_bytes((out/'executed_source.py').read_bytes())
    tool_path=seed['robot_tcp_prim'];base_path=seed['robot_base_prim']
    selected=next(o for o in seed['world_objects'] if o['id']==seed['reservation_binding']['slot_id'])
    label(stage.GetPrimAtPath('/World/Robot'),'robot');label(stage.GetPrimAtPath(selected['prim_path']),'held')
    T_tool_optical=np.asarray(profile['T_tool_camera_optical']);flip=np.diag([1.,-1.,-1.,1.])
    if live_capture:
        camera_path=live_capture['camera_path'];sensor=live_capture['sensor'];camera_params=live_capture['camera_params']
    else:
        camera_path=tool_path+'/NativeHeldWristDepth';camera=UsdGeom.Camera.Define(stage,camera_path)
        camera.AddTransformOp().Set(Gf.Matrix4d((T_tool_optical@flip).T))
        usd=profile['usd_camera']
        for key,method in [('focal_length_mm','CreateFocalLengthAttr'),('horizontal_aperture_mm','CreateHorizontalApertureAttr'),
            ('vertical_aperture_mm','CreateVerticalApertureAttr'),('horizontal_aperture_offset_mm','CreateHorizontalApertureOffsetAttr'),
            ('vertical_aperture_offset_mm','CreateVerticalApertureOffsetAttr')]:getattr(camera,method)(float(usd[key]))
        camera.CreateClippingRangeAttr(Gf.Vec2f(.01,2.))
        sensor=CameraSensor(RtxCamera(camera_path),resolution=(H,W),annotators=['distance_to_image_plane','semantic_segmentation','rgb'])
        import omni.replicator.core as rep
        camera_params=rep.AnnotatorRegistry.get_annotator('camera_params');camera_params.attach(str(sensor.render_product.GetPath()))
        # Register the stimulus in the active render scene before stopping physics.
        # Only its translation changes after the baseline is observed.
        cube=UsdGeom.Cube.Define(stage,'/World/NativeHeldDepthStimulus');cube.CreateSizeAttr(.02)
        stimulus_op=cube.AddTranslateOp();stimulus_op.Set(Gf.Vec3d(10,10,-10));label(cube.GetPrim(),'moving_obstacle')
    timeline=omni.timeline.get_timeline_interface();timeline.play()
    rows=[];previous=None;quiet=False;start=float(world.current_time)
    criteria=dict(duration_s=.6,minimum_recorded_duration_s=.55,max_velocity_rad_s=.02,max_acceleration_rad_s2=.7,
        maximum_wait_sim_s=3.,scope='PREDECLARED_EXISTING_SIM_REST_LIMITS_NO_THRESHOLD_RELAXATION')
    save(folder/'rest_capture_criteria.json',criteria)
    while float(world.current_time)-start<criteria['maximum_wait_sim_s']:
        tick();row=sample();v=np.asarray(row['velocity_rad_s'][:6]);stamp=float(world.current_time)
        if previous:
            dt=stamp-previous[0]
            if dt<=0:raise ValueError('Actual rest clock did not advance')
            rows.append(dict(stamp_s=stamp,q_rad=row['q_rad'],v_rad_s=v.tolist(),
                a_rad_s2=((v-previous[1])/dt).tolist(),grip_rad=row['grip_rad'],attachment=row['attachment'],
                contact_fingers=row['contact_fingers'],**command_counts(statuses)))
        previous=(stamp,v)
        history=[r for r in rows if stamp-r['stamp_s']<=criteria['duration_s']]
        if history and stamp-history[0]['stamp_s']>=criteria['minimum_recorded_duration_s']:
            q=np.asarray([r['q_rad'] for r in history]);velocity=np.asarray([r['v_rad_s'] for r in history])
            acceleration=np.asarray([r['a_rad_s2'] for r in history]);times=np.asarray([r['stamp_s'] for r in history])
            # These are representation bounds on the numeric SIM readout,
            # not physical/solver accuracy certification or invented zeros.
            q_error=float(np.max(np.spacing(abs(q.astype(np.float32))))/2)
            v_error=float(np.max(np.spacing(abs(velocity.astype(np.float32))))/2)
            a_error=2*v_error/float(np.diff(times).min())+64*np.finfo(float).eps*max(1.,float(abs(acceleration).max()))
            observation=dict(velocity_method='PHYSX_NATIVE_JOINT_VELOCITY',
                acceleration_method='ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE',
                q_uncertainty_rad=q_error,v_uncertainty_rad_s=v_error,a_uncertainty_rad_s2=a_error,
                uncertainty_scope='FLOAT32_READOUT_REPRESENTATION_ONLY_NOT_PHYSICAL_OR_SOLVER_ERROR_BOUND',
                position_difference_velocity_peak_rad_s=float(abs(np.diff(q,axis=0)/np.diff(times)[:,None]).max()),
                native_velocity_vs_position_difference_max_rad_s=float(abs(velocity[1:]-np.diff(q,axis=0)/np.diff(times)[:,None]).max()),
                dt_minmax_s=[float(np.diff(times).min()),float(np.diff(times).max())],physical_model_certified=False)
            quiet=(float(abs(velocity).max())+v_error<=criteria['max_velocity_rad_s'] and
                float(abs(acceleration).max())+a_error<=criteria['max_acceleration_rad_s2'] and
                float(abs(np.diff(q,axis=0)/np.diff(times)[:,None]).max())<=criteria['max_velocity_rad_s'] and
                all(r['active_command_count']==r['pending_command_count']==0 for r in history) and
                all(r['contact_fingers']==['rg2_left_inner_finger','rg2_right_inner_finger'] for r in history))
            if quiet:break
    save(folder/'all_rest_samples.json',rows)
    if not quiet:raise ValueError('NO_VERIFIED_NUMERIC_REST_WINDOW_WITHIN_PREDECLARED_TIMEOUT')
    timeline.pause()
    for _ in range(30):app.update()
    raw,_=sensor.get_data('distance_to_image_plane');semantic,info=sensor.get_data('semantic_segmentation')
    if raw is None or semantic is None:raise ValueError('Native held camera has no raw frame')
    baseline=np.asarray(raw.numpy(),np.float32).squeeze();own,held,_,_=select_masks(semantic.numpy(),info)
    if live_capture:
        centre=rigid(stage,live_capture['obstacle_path'])[:,3]
        px=py=None;clearance=None
    else:
        free=(~(own|held))&((baseline>.12)|~np.isfinite(baseline));free[:6]=False;free[-6:]=False;free[:,:6]=False;free[:,-6:]=False
        clearance=distance_transform_edt(free);py,px=np.unravel_index(int(clearance.argmax()),clearance.shape)
        if clearance[py,px]<8:raise ValueError('Actual held geometry leaves no clear stimulus ray')
        z=min(.18,float(baseline[py,px])-.04) if np.isfinite(baseline[py,px]) else .18
        if z<.07:raise ValueError('Stimulus ray is too close')
        direction=np.array([(px-intr['cx'])/intr['fx']*z,(py-intr['cy'])/intr['fy']*z,z,1])
        centre=rigid(stage,tool_path)@T_tool_optical@direction
        stimulus_op.Set(Gf.Vec3d(*centre[:3]))
    before=sample();before_stamp=float(world.current_time)
    for _ in range(40):app.update()
    raw,depth_info=sensor.get_data('distance_to_image_plane');semantic,info=sensor.get_data('semantic_segmentation');rgb,_=sensor.get_data('rgb')
    depth=np.asarray(raw.numpy(),np.float32).squeeze();ids=np.asarray(semantic.numpy()).squeeze().copy()
    own,held,obstacle,labels=select_masks(ids,info);after=sample();stamp=float(world.current_time)
    # Failed visibility must retain actual raw evidence, rather than only a
    # presence flag or traceback that cannot explain which geometry was absent.
    for name,data in [('depth',depth),('semantic_ids',ids),('self_mask',own),('held_mask',held),('obstacle_mask',obstacle),('baseline_depth',baseline)]:
        np.save(folder/(name+'.npy'),data,allow_pickle=False)
    if rgb is not None:np.save(folder/'rgb.npy',rgb.numpy(),allow_pickle=False)
    save(folder/'semantic_info.json',info);save(folder/'all_rest_samples.json',rows)
    save(folder/'visibility_diagnostic.json',dict(self_pixels=int(own.sum()),held_pixels=int(held.sum()),obstacle_pixels=int(obstacle.sum()),
        labels=labels,selected_baseline_pixel_uv=[int(px),int(py)] if px is not None else None,baseline_clearance_pixels=float(clearance[py,px]) if clearance is not None else None,
        T_world_camera=rigid(stage,camera_path),T_world_tool=rigid(stage,tool_path),q_rad=after['q_rad'],
        gt_stimulus_centre_world_audit_only=centre[:3].tolist()))
    if not own.any() or not held.any() or not obstacle.any():raise ValueError('Self/actual held/controlled object not visible')
    if max(abs(np.asarray(before['q_rad'])-after['q_rad']))>1e-6:raise ValueError('Nonstationary render bracket')
    model=read_model_bundle(model_bundle);T_base_tool=np.linalg.inv(rigid(stage,base_path))@rigid(stage,tool_path)
    fk=tcp_fk(model,after['q_rad'],after['grip_rad'])
    fk_error=[float(np.linalg.norm(fk[:3,3]-T_base_tool[:3,3])),float(Rotation.from_matrix(fk[:3,:3].T@T_base_tool[:3,:3]).magnitude())]
    if fk_error[0]>.0008 or fk_error[1]>.005:raise ValueError('Native grasp Depth FK mismatch')
    session=live_capture['session_id'] if live_capture else 'native-held-depth-'+uuid.uuid4().hex
    cancel_generation=live_capture['cancel_generation']() if live_capture else 0
    stop_reason='OBSTACLE_RESPONSE_HOLD' if live_capture else 'GOAL_COMPLETE_STATIONARY_CAPTURE'
    frame=dict(schema='wrist-depth-frame/0.1',source_kind='SIM_DEPTH',session_id=session,frame_seq=0,
        source_stamp_s=stamp,received_stamp_s=stamp,robot_state_stamp_s=stamp,transform_stamp_s=stamp,clock_basis='SIM_TIME',
        optical_frame_id=profile['optical_frame_id'],tool_frame_id=tool_path,base_frame_id=base_path,
        calibration_id=profile['profile_id'],calibration_scope=profile['calibration_scope'],q_rad=after['q_rad'],
        T_base_tool=T_base_tool.tolist(),T_tool_camera_optical=T_tool_optical.tolist(),intrinsics=intr,
        depth_unit='METER',depth_scale_m=1.,depth_representation='IMAGE_PLANE_Z',
        self_mask_status='GEOMETRIC_UNVERIFIED',held_mask_status='GEOMETRIC_UNVERIFIED')
    limits=dict(clock_basis='SIM_TIME',threshold_status='SIM_TEST_PARAMETER',max_age_s=.1,max_pose_skew_s=.001,min_depth_m=.02,max_depth_m=2.)
    for name,data in [('depth',depth),('semantic_ids',ids),('self_mask',own),('held_mask',held),('obstacle_mask',obstacle),('baseline_depth',baseline)]:
        np.save(folder/(name+'.npy'),data,allow_pickle=False)
    if rgb is not None:np.save(folder/'rgb.npy',rgb.numpy(),allow_pickle=False)
    save(folder/'semantic_info.json',info);save(folder/'frame.json',frame);save(folder/'limits.json',limits)
    save(folder/'candidates.json',project_frame(frame,np.where(obstacle,depth,np.nan),own,held,now_s=stamp,limits=limits))
    save(folder/'camera_params.json',camera_params.get_data())
    save(folder/'pose.json',dict(stamp_s=stamp,before_stamp_s=before_stamp,after_stamp_s=stamp,clock_basis='SIM_TIME',
        q_rad=after['q_rad'],before_q_rad=before['q_rad'],after_q_rad=after['q_rad'],grip_rad=after['grip_rad'],
        before_grip_rad=before['grip_rad'],after_grip_rad=after['grip_rad'],image_source_stamp_verified=False,
        time_sync_scope='STATIONARY_POST_RENDER_BRACKET_NOT_DYNAMIC_SOURCE_STAMP',
        model_manifest_sha256=model['manifest_sha256'],capture_source_sha256=sha(folder/'capture_source.py'),state_sequence=1))
    objects,alignment,_=read_scene_geometry(stage,seed);actual_held=next(o for o in objects if o['id']==selected['id'])
    actual_held['role']='HELD_BLOCK';geometry_context=dict(grip_rad=after['grip_rad'],attachment=after['attachment'],held_geometry=actual_held)
    save(folder/'motion.request.json',motion)
    save(folder/'world_scene_snapshot.json',dict(scope='SAME_CAPTURE_NATIVE_SCENE_OBSERVATION_NOT_EXECUTION',
        a_context=seed['a_context'],current=seed['current'],reservation_binding=seed['reservation_binding'],
        world_objects=objects,frame_alignment=alignment,source_stamp_s=stamp))
    # Raw USD inventory binds the real rendered model, without pretending that
    # assigning URDF IDs or copying semantic masks verifies mesh correspondence.
    inventory=[]
    for root in ('/World/Robot',selected['prim_path']):
        for prim in Usd.PrimRange(stage.GetPrimAtPath(root),Usd.TraverseInstanceProxies()):
            if not prim.IsA(UsdGeom.Gprim):continue
            item=dict(prim_path=str(prim.GetPath()),type=prim.GetTypeName(),T_world_prim=rigid(stage,str(prim.GetPath())).tolist(),
                visibility=UsdGeom.Imageable(prim).ComputeVisibility(),purpose=UsdGeom.Imageable(prim).ComputePurpose())
            if prim.IsA(UsdGeom.Cube):item['size']=UsdGeom.Cube(prim).GetSizeAttr().Get()
            if prim.IsA(UsdGeom.Mesh):
                mesh=UsdGeom.Mesh(prim)
                item['mesh_array_sha256']={k:hashlib.sha256(np.asarray(getter()).tobytes()).hexdigest() for k,getter in
                    [('points',mesh.GetPointsAttr().Get),('faceVertexCounts',mesh.GetFaceVertexCountsAttr().Get),('faceVertexIndices',mesh.GetFaceVertexIndicesAttr().Get)]}
            inventory.append(item)
    stage.Export(str(folder/'captured_scene.usda'))
    save(folder/'scene_inventory.json',dict(scope='ACTUAL_NATIVE_HELD_BODY_STUD_USD_RAW_INVENTORY_MODEL_CORRESPONDENCE_PENDING',
        scene=dict(path=str((folder/'captured_scene.usda').resolve()),sha256=sha(folder/'captured_scene.usda')),
        original_model_manifest_sha256=model['manifest_sha256'],geometry_context=geometry_context,prims=inventory,
        model_visual_correspondence_verified=False,semantic_inventory_complete_verified=False))
    history=[r for r in rows if stamp-r['stamp_s']<=.6]
    proof=dict(scope='ACTUAL_SIM_STOP_RECORD',model_manifest_sha256=model['manifest_sha256'],session_id=session,clock_basis='SIM_TIME',
        state_sequence=1,cancel_generation=cancel_generation,stop_reason=stop_reason,
        acceleration_method=observation['acceleration_method'],grip_rad=after['grip_rad'],
        observation=observation,holding_confirmed=True,
        attachment_digest=digest(after['attachment']),**command_counts(statuses),samples=history)
    save(folder/'all_rest_samples.json',rows);save(folder/'stop_evidence.json',proof)
    state=dict(schema='stopped-robot-snapshot/0.1',source_kind='SIM_SAVED_SNAPSHOT',session_id=session,clock_basis='SIM_TIME',state_sequence=1,
        units='rad, seconds',joint_names=['joint_'+str(i) for i in range(1,7)],captured_at=datetime.now(timezone.utc).isoformat(),
        evidence_ref=str((folder/'stop_evidence.json').resolve()),stopped_verified=quiet,holding_confirmed=True,**command_counts(statuses),
        acceleration_method=observation['acceleration_method'],velocity_stamp_s=stamp,acceleration_stamp_s=stamp,stop_evidence_stamp_s=stamp,
        cancel_generation=cancel_generation,stop_reason=proof['stop_reason'],source_stamp_s=stamp,q_rad=after['q_rad'],grip_rad=after['grip_rad'],
        v_rad_s=history[-1]['v_rad_s'],a_rad_s2=history[-1]['a_rad_s2'],attachment_tcp_to_block=after['attachment'],
        a_context=motion['context'],reservation_binding=seed['reservation_binding'],execution_allowed=False,
        stop_evidence=dict(path=str((folder/'stop_evidence.json').resolve()),sha256=sha(folder/'stop_evidence.json'),
            capture_source_path=str((folder/'capture_source.py').resolve()),capture_source_sha256=sha(folder/'capture_source.py')))
    state['digest']=digest(state);save(folder/'state_draft.json',state)
    save(folder/'status.json',dict(scope='FRESH_NATIVE_CONTACT_GRASP_STATIONARY_RTX_CAPTURE',capture_success=True,
        obstacle_pixels=int(obstacle.sum()),self_pixels=int(own.sum()),held_pixels=int(held.sum()),fk_error_m_rad=fk_error,
        held_geometry_proxy=False,virtual_attachment_used=False,model_correspondence_complete=False,
        raw_rest_velocity_peak_rad_s=max(abs(v) for r in history for v in r['v_rad_s']),
        raw_rest_acceleration_peak_rad_s2=max(abs(a) for r in history for a in r['a_rad_s2']),
        gt_stimulus_centre_world_for_audit_only=centre[:3].tolist(),planner_receives_gt_pose=False,
        prior_scope='DECLARED_20MM_SIM_VISUAL_CUBE_SIZE_ONLY_ERROR_SPEED_LATENCY_PENDING',
        hardware_execution_allowed=False,consumer_status='HOLD_MODEL_CORRESPONDENCE_AND_PRIOR'))


def main(configure_runtime=None,add_arguments=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('scene','setup','model-bundle','mount-profile','runtime-reference','out'):parser.add_argument('--'+name,type=Path,required=True)
    if add_arguments:add_arguments(parser)
    args=parser.parse_args()
    if os.environ.get('ROS_DOMAIN_ID')!='194' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')!='LOCALHOST':parser.error('SIM194/LOCALHOST required')
    args.out.mkdir(exist_ok=False)
    (args.out/'executed_source.py').write_bytes(Path(__file__).read_bytes())
    runtime_source=Path(__file__).resolve().parents[1]/'scripts/capture_sim_runtime.py'
    (args.out/'executed_runtime.py').write_bytes(runtime_source.read_bytes())
    # Keep the taught q/seed bindings; reuse only the already selected SIM
    # numerical/control configuration, with its source files and hashes.
    reference=args.runtime_reference
    reference_setup=json.loads((reference/'setup.json').read_text())
    setup=json.loads(args.setup.read_text())
    setup.update({k:reference_setup[k] for k in ('physics_dt_s','solver_iterations')})
    save(args.out/'capture.setup.current.json',setup)
    controllers=reference/'controllers.trial.yaml'
    import yaml
    doc=yaml.safe_load(controllers.read_text())
    if (set(doc)!={'/sim/m0609/controller_manager','/sim/m0609/arm_controller','/sim/m0609/gripper_controller','/sim/m0609/joint_state_broadcaster'} or
            doc['/sim/m0609/controller_manager']['ros__parameters']['update_rate']!=240):
        raise ValueError('Existing chosen SIM240 controller reference required')
    (args.out/'controllers.reference.yaml').write_bytes(controllers.read_bytes())
    drive_source=reference/'nominal_gripper_drive.json';drive=json.loads(drive_source.read_text())['changes']
    if len(drive)!=1:raise ValueError('One chosen native SIM gripper drive required')
    save(args.out/'runtime_reference.json',dict(scope='EXISTING_SELECTED_SIM_CONFIGURATION_NOT_NEW_SOLVER_TRIAL',
        sources={str(p):sha(p) for p in (reference/'setup.json',controllers,drive_source,args.setup)},
        physics_dt_s=setup['physics_dt_s'],solver_iterations=setup['solver_iterations'],gripper_drive=drive[0]))
    from isaacsim import SimulationApp
    app=SimulationApp(dict(headless=True))
    try:
        from capture_sim_runtime import run_capture
        runtime=SimpleNamespace(model_bundle=args.model_bundle,archive_postures=None,capture_setup=args.out/'capture.setup.current.json',
            auto_start=False,capture_scene=args.scene,capture_interactive=False,capture_delay_s=None,sim_transport=False,
            wrist_runtime_reference=dict(controller_config_path=args.out/'controllers.reference.yaml',gripper_drive=drive[0]),
            wrist_depth_hook=lambda *values:capture_held(*values,profile_path=args.mount_profile))
        if configure_runtime:configure_runtime(args,runtime)
        run_capture(app,runtime,args.out,isolated_domain=194)
    except BaseException:
        (args.out/'failure.txt').write_text(traceback.format_exc());raise
    finally:app.close()


if __name__=='__main__':main()
