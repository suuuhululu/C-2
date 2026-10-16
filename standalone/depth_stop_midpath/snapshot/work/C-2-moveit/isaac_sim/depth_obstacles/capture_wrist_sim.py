"""Actual RTX wrist Depth at two reconstructed SIM checkpoints, no controller."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

import numpy as np


def rigid(stage,path):
    from pxr import Usd,UsdGeom
    return np.asarray(UsdGeom.Xformable(stage.GetPrimAtPath(path)).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T


def label(prim,value):
    import Semantics
    api=Semantics.SemanticsAPI.Apply(prim,'class')
    api.CreateSemanticTypeAttr().Set('class');api.CreateSemanticDataAttr().Set(value)


def select_masks(array,info):
    labels=info.get('idToLabels')
    if not isinstance(labels,dict):raise ValueError('Semantic annotator did not report labels')
    ids=np.asarray(array)
    if ids.ndim==3 and ids.shape[2]==1:ids=ids[:,:,0]
    if ids.ndim!=2:raise ValueError('Semantic image shape mismatch')
    own=np.zeros(ids.shape,bool);held=np.zeros(ids.shape,bool);obstacle=np.zeros(ids.shape,bool)
    known={}
    for key,tags in labels.items():
        if not isinstance(tags,dict):raise ValueError('Semantic label mapping changed')
        values=set(','.join(str(v) for v in tags.values()).split(','))
        mask=ids==int(key)
        if 'held' in values:held|=mask
        elif 'robot' in values:own|=mask
        if 'moving_obstacle' in values:obstacle|=mask
        known[str(key)]=dict(labels=tags,pixels=int(mask.sum()))
    if (own|held).any() and np.any(obstacle&(own|held)):
        raise ValueError('Obstacle/self semantic mask overlap')
    return own,held,obstacle,known


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True)
    parser.add_argument('--model-bundle',type=Path,required=True)
    parser.add_argument('--mount-profile',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--source-time-probe',action='store_true')
    args=parser.parse_args()
    if os.environ.get('ROS_DOMAIN_ID')!='194' or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE')!='LOCALHOST':
        parser.error('Explicit isolated SIM194/LOCALHOST required')
    args.out.mkdir(exist_ok=False)
    script=Path(__file__)
    (args.out/'executed_source.py').write_bytes(script.read_bytes())
    (args.out/'source.sha256').write_text(hashlib.sha256(script.read_bytes()).hexdigest())
    (args.out/'capture_profile.json').write_bytes(args.mount_profile.read_bytes())
    (args.out/'capture_profile.sha256').write_text(hashlib.sha256(args.mount_profile.read_bytes()).hexdigest())
    from isaacsim import SimulationApp
    app=SimulationApp(dict(headless=True,width=640,height=480))
    try:
        (args.out/'progress.json').write_text(json.dumps(dict(step='app_started')))
        run(app,args)
    except BaseException:
        (args.out/'failure.txt').write_text(traceback.format_exc())
        raise
    finally:app.close()


def run(app,args):
    import omni.usd,omni.timeline,omni.kit.app
    manager=omni.kit.app.get_app().get_extension_manager()
    for name in ('isaacsim.core.api','isaacsim.core.prims','isaacsim.sensors.experimental.rtx'):
        manager.set_extension_enabled_immediate(name,True);app.update()
    from pxr import Usd,UsdGeom,UsdPhysics,Gf
    from isaacsim.sensors.experimental.rtx import RtxCamera,CameraSensor
    from scipy.spatial.transform import Rotation
    from scipy.ndimage import distance_transform_edt
    from isaac_sim.depth_obstacles.projection import project_frame
    from capture_sim_runtime import initialize_native
    from d_sim_transport import native_goal
    from prepare_cpu_model import read_model_bundle
    from prepare_gpu_scene import tcp_fk
    source=args.source_run
    profile=json.loads(args.mount_profile.read_text())
    if (profile['schema']!='wrist-sim-mount/0.1' or
            profile['calibration_scope'] not in ('SIM_NOMINAL','SIM_NOMINAL_FROM_REAL_PUBLISHED_TF') or
            str(profile['tool_frame_id']).split('/')[-1]!='GripperDA_v4_tcp' or
            profile['hand_eye_independently_verified'] is not False or
            profile['hardware_execution_allowed'] is not False):
        raise ValueError('Unsupported or execution-enabled SIM mount profile')
    seed=json.loads((source/'preview_01/scene.seed.json').read_text())
    trace=[json.loads(line) for line in (source/'cycle_01/transport_observations.jsonl').read_text().splitlines()]
    checkpoints=(trace[0],trace[len(trace)//4])
    model=read_model_bundle(args.model_bundle)
    context=omni.usd.get_context();context.open_stage(str(source/'scene.usda'))
    stage=context.get_stage();stage.SetEditTarget(stage.GetSessionLayer())
    robot_path='/World/Robot';base_path=seed['robot_base_prim'];tool_path=seed['robot_tcp_prim']
    label(stage.GetPrimAtPath(robot_path),'robot')
    # Camera extrinsics/intrinsics are explicit per-session profile inputs.
    # Published TF is nominal evidence, never accepted physical hand-eye.
    camera_path=tool_path+'/WristDepthTrial';camera=UsdGeom.Camera.Define(stage,camera_path)
    T_usd_optical=np.diag([1.,-1.,-1.,1.])
    T_tool_optical=np.asarray(profile['T_tool_camera_optical'],float)
    if T_tool_optical.shape!=(4,4) or not np.isfinite(T_tool_optical).all():
        raise ValueError('Invalid profile hand-eye matrix')
    T_tool_usd=T_tool_optical@T_usd_optical
    camera.AddTransformOp().Set(Gf.Matrix4d(T_tool_usd.T))
    usd=profile['usd_camera']
    camera.CreateFocalLengthAttr(float(usd['focal_length_mm']))
    camera.CreateHorizontalApertureAttr(float(usd['horizontal_aperture_mm']))
    camera.CreateVerticalApertureAttr(float(usd['vertical_aperture_mm']))
    camera.CreateHorizontalApertureOffsetAttr(float(usd['horizontal_aperture_offset_mm']))
    camera.CreateVerticalApertureOffsetAttr(float(usd['vertical_aperture_offset_mm']))
    camera.CreateClippingRangeAttr(Gf.Vec2f(.01,2.))
    # USD camera: +X right, +Y up, -Z forward. Optical: +X right, +Y down, +Z forward.
    obstacle=UsdGeom.Cube.Define(stage,'/World/DepthTrial/MovingObstacle')
    obstacle.CreateSizeAttr(.02);obstacle.CreateDisplayColorAttr([Gf.Vec3f(1,.2,.1)])
    obstacle_op=obstacle.AddTranslateOp();obstacle_op.Set(Gf.Vec3d(0,0,0))
    label(obstacle.GetPrim(),'moving_obstacle')
    # Visible reconstruction of the held block is independent of supply-body
    # physics; both static captures are explicitly non-execution observations.
    held_object=next(o for o in seed['world_objects'] if o['id']=='blue_2x2x1_01')
    block=UsdGeom.Cube.Define(stage,tool_path+'/DepthTrialHeldBlock')
    block.CreateSizeAttr(1.);block.CreateDisplayColorAttr([Gf.Vec3f(.1,.3,1)])
    attachment=np.asarray(trace[0]['attachment'],float)
    block.AddTransformOp().Set(Gf.Matrix4d(attachment.T))
    block.AddScaleOp().Set(Gf.Vec3d(*held_object['size_m']))
    label(block.GetPrim(),'held')
    setup=json.loads((source/'setup.json').read_text())
    config_path=Path(__file__).resolve().parents[1]/'config/contact.sim.json'
    cfg=json.loads(config_path.read_text());cfg['physics_dt_s']=setup['physics_dt_s']
    cfg['render_every_physics_steps']=1
    world,arm,node,tick=initialize_native(app,stage,setup,cfg)
    import rclpy
    from rclpy.action import ActionClient
    from control_msgs.action import FollowJointTrajectory
    from isaacsim.ros2.control import Ros2ControlManager
    names=arm.dof_names;axes=[names.index('joint_'+str(i)) for i in range(1,7)]
    grip=names.index('rg2_finger_joint')
    intr=profile['intrinsics'];W,H=intr['width'],intr['height']
    sensor=CameraSensor(RtxCamera(camera_path),resolution=(H,W),annotators=['rgb','distance_to_image_plane','semantic_segmentation'])
    timeline=omni.timeline.get_timeline_interface()
    close_probe=None
    if args.source_time_probe:
        from isaac_sim.depth_obstacles.render_time_probe import install_probe
        collect_probe,close_probe=install_probe(sensor,args.out/'source_time_probe')
        original_tick=tick
        def tick():
            original_tick()
            collect_probe(dict(sim_time_s=float(world.current_time),timeline_time_s=timeline.get_current_time(),
                q_rad=arm.get_joint_positions()[axes].astype(float).tolist(),
                v_rad_s=arm.get_joint_velocities()[axes].astype(float).tolist(),
                T_world_base=rigid(stage,base_path).tolist(),
                T_base_tool=(np.linalg.inv(rigid(stage,base_path))@rigid(stage,tool_path)).tolist(),
                T_world_camera=rigid(stage,camera_path).tolist()))
    def move_controller(joint_names, target, seconds):
        client=ActionClient(node,FollowJointTrajectory,'/sim/m0609/'+
            ('gripper_controller' if len(joint_names)==1 else 'arm_controller')+'/follow_joint_trajectory')
        timeout=time.monotonic()+30
        while not client.server_is_ready() and time.monotonic()<timeout:tick()
        if not client.server_is_ready():raise RuntimeError('Isolated SIM action unavailable')
        actual=arm.get_joint_positions();current=[float(actual[names.index(name)]) for name in joint_names]
        packet=dict(trajectory=dict(joint_names=joint_names,points=[
            dict(positions_rad=current,velocities_rad_s=[0.]*len(current),accelerations_rad_s2=[0.]*len(current),time_from_start_s=0),
            dict(positions_rad=[float(x) for x in target],velocities_rad_s=[0.]*len(current),
                 accelerations_rad_s2=[0.]*len(current),time_from_start_s=seconds)]))
        future=client.send_goal_async(native_goal(packet));timeout=time.monotonic()+30
        while not future.done() and time.monotonic()<timeout:tick()
        if not future.done() or not future.result().accepted:raise RuntimeError('Isolated SIM action rejected')
        finished=future.result().get_result_async();timeout=time.monotonic()+seconds*8+30
        while not finished.done() and time.monotonic()<timeout:tick()
        if not finished.done() or finished.result().status!=4 or finished.result().result.error_code!=0:
            raise RuntimeError('Isolated SIM action did not finish successfully')
        for _ in range(240):tick()
    records=[];previous=None
    for i,checkpoint in enumerate(checkpoints):
        folder=args.out/f'pose_{i+1:02d}';folder.mkdir()
        q=np.asarray(checkpoint['q_rad'],float)
        timeline.play();move_controller([f'joint_{j}' for j in range(1,7)],q,4.)
        move_controller(['rg2_finger_joint'],[checkpoint['grip_rad']],2.)
        # PhysX q/v samples are taken after both action results complete. The
        # first acceleration is undefined and is deliberately not zero-filled.
        samples=[]
        for _ in range(121):
            tick()
            samples.append(dict(stamp_s=float(world.current_time),
                q_rad=arm.get_joint_positions()[axes].astype(float).tolist(),
                v_rad_s=arm.get_joint_velocities()[axes].astype(float).tolist()))
        stop_rows=[]
        for before,current in zip(samples,samples[1:]):
            dt=current['stamp_s']-before['stamp_s']
            if dt<=0:raise ValueError('Stationary SIM sample clock did not advance')
            stop_rows.append(dict(**current,a_rad_s2=((np.asarray(current['v_rad_s'])-
                np.asarray(before['v_rad_s']))/dt).tolist()))
        (folder/'stationary_samples.json').write_text(json.dumps(dict(
            scope='ACTUAL_SIM_POST_GOAL_SAMPLES_NOT_VERIFIED_STOP',
            source='PHYSX_ARTICULATION_Q_V',
            acceleration_method='ADJACENT_PHYSX_RETURNED_V_FINITE_DIFFERENCE',
            controller_action_results='ARM_AND_GRIPPER_SUCCEEDED',
            active_pending_counts='NOT_OBSERVED',
            stop_reason='GOAL_COMPLETE_STATIONARY_CAPTURE_NOT_OBSTACLE_STOP',
            samples=stop_rows),indent=2)+'\n')
        timeline.pause()
        # Stage world matrix is read after rendering, not inferred from the saved q.
        obstacle_op.Set(Gf.Vec3d(10,10,-10))
        for _ in range(30):app.update()
        baseline_raw,_=sensor.get_data('distance_to_image_plane')
        baseline_semantic,baseline_info=sensor.get_data('semantic_segmentation')
        if baseline_raw is None or baseline_semantic is None:raise ValueError('No baseline RTX Depth frame')
        baseline_depth=np.asarray(baseline_raw.numpy(),float).squeeze()
        baseline_self,baseline_held,_,_=select_masks(baseline_semantic.numpy(),baseline_info)
        free=(~(baseline_self|baseline_held)) & ((baseline_depth>.12)|~np.isfinite(baseline_depth))
        free[:6,:]=False;free[-6:,:]=False;free[:,:6]=False;free[:,-6:]=False
        clearance=distance_transform_edt(free)
        py,px=np.unravel_index(int(np.argmax(clearance)),clearance.shape)
        np.save(folder/'baseline_depth.npy',baseline_depth.astype(np.float32),allow_pickle=False)
        np.save(folder/'baseline_self_mask.npy',baseline_self,allow_pickle=False)
        np.save(folder/'baseline_held_mask.npy',baseline_held,allow_pickle=False)
        (folder/'baseline_diagnostic.json').write_text(json.dumps(dict(
            free_pixels=int(free.sum()),peak_clearance_pixels=float(clearance[py,px]),
            selected_pixel_uv=[int(px),int(py)],selected_pixel_depth_m=(float(baseline_depth[py,px])
                if np.isfinite(baseline_depth[py,px]) else None)),indent=2)+'\n')
        if clearance[py,px]<8:raise ValueError('No sufficiently clear baseline Depth pixel for SIM stimulus')
        T_base_tool=np.linalg.inv(rigid(stage,base_path))@rigid(stage,tool_path)
        T_world_camera=rigid(stage,base_path)@T_base_tool@T_tool_optical
        z=min(.18,float(baseline_depth[py,px])-.04) if np.isfinite(baseline_depth[py,px]) else .18
        if z<.07:raise ValueError('Baseline free-ray depth leaves no safe stimulus range')
        aim=np.asarray([(px-intr['cx'])/intr['fx']*z,(py-intr['cy'])/intr['fy']*z,z,1.])
        centre=T_world_camera@aim;obstacle_op.Set(Gf.Vec3d(*centre[:3]))
        begin=time.monotonic()
        # Rendering while paused leaves the controller-reached physics pose fixed.
        for _ in range(40):app.update()
        camera_world=rigid(stage,camera_path);T_base_tool=np.linalg.inv(rigid(stage,base_path))@rigid(stage,tool_path)
        T_base_camera=T_base_tool@T_tool_optical
        # Per-pose FK agreement is mandatory before accepting a Depth frame.
        measured=arm.get_joint_positions();actual_q=measured[axes]
        if not np.isfinite(measured).all():
            raise ValueError('Native isolated SIM checkpoint became nonfinite before Depth capture')
        predicted=tcp_fk(model,actual_q.astype(float).tolist(),float(measured[grip]))
        translation=float(np.linalg.norm(predicted[:3,3]-T_base_tool[:3,3]))
        rotation=float(Rotation.from_matrix(predicted[:3,:3].T@T_base_tool[:3,:3]).magnitude())
        (folder/'fk_diagnostic.json').write_text(json.dumps(dict(q=actual_q.tolist(),
            measured_grip=float(measured[grip]),position_error_m=translation,rotation_error_rad=rotation,
            predicted_T_base_tool=predicted.tolist(),usd_T_base_tool=T_base_tool.tolist()),indent=2)+'\n')
        if translation>.0008 or rotation>.005:raise ValueError('Stamped USD TCP and joint FK disagree')
        raw,depth_info=sensor.get_data('distance_to_image_plane')
        semantic,semantic_info=sensor.get_data('semantic_segmentation')
        rgb,_=sensor.get_data('rgb')
        if raw is None or semantic is None:raise ValueError('RTX annotator warming; no Depth evidence')
        depth=np.asarray(raw.numpy(),np.float32).squeeze()
        semantic_ids=np.asarray(semantic.numpy()).squeeze().copy()
        own,held,obstacle_mask,labels=select_masks(semantic_ids,semantic_info)
        (folder/'semantic_diagnostic.json').write_text(json.dumps(dict(
            self_pixels=int(own.sum()),held_pixels=int(held.sum()),obstacle_pixels=int(obstacle_mask.sum()),
            labels=labels),indent=2)+'\n')
        if not obstacle_mask.any():raise ValueError('No labelled moving obstacle pixels in actual Depth frame')
        if depth.shape!=(H,W) or obstacle_mask.shape!=depth.shape:raise ValueError('Depth/mask resolution mismatch')
        # Sensor annotators have no matching physical-step source stamp here.
        # Save a post-render bracket and require a stationary q/tool across it.
        stamp=world.current_time;after=arm.get_joint_positions()
        if float(np.max(abs(after-measured)))>1e-5:raise ValueError('Robot moved across rendering readout')
        delta=np.linalg.inv(rigid(stage,base_path)@T_base_camera)@camera_world@T_usd_optical
        cam_translation=float(np.linalg.norm(delta[:3,3]))
        cam_rotation=float(Rotation.from_matrix(delta[:3,:3]).magnitude())
        if cam_translation>1e-5 or cam_rotation>1e-5:raise ValueError('USD camera/optical axes disagree')
        observed=np.where(obstacle_mask,depth,np.nan)
        frame=dict(schema='wrist-depth-frame/0.1',source_kind='SIM_DEPTH',session_id='wrist-capture-'+args.out.name,
            frame_seq=i,source_stamp_s=stamp,received_stamp_s=stamp,transform_stamp_s=stamp,robot_state_stamp_s=stamp,
            clock_basis='SIM_TIME',optical_frame_id=profile['optical_frame_id'],tool_frame_id=tool_path,base_frame_id=base_path,
            calibration_id=profile['profile_id'],calibration_scope=profile['calibration_scope'],
            q_rad=actual_q.tolist(),T_base_tool=T_base_tool.tolist(),T_tool_camera_optical=T_tool_optical.tolist(),
            intrinsics=intr,depth_unit='METER',depth_scale_m=1.,depth_representation='IMAGE_PLANE_Z',
            self_mask_status='GEOMETRIC_UNVERIFIED',
            held_mask_status='GEOMETRIC_UNVERIFIED')
        limits=dict(clock_basis='SIM_TIME',threshold_status='SIM_TEST_PARAMETER',max_age_s=.1,
            max_pose_skew_s=.001,min_depth_m=.02,max_depth_m=2.)
        projected=project_frame(frame,observed,own,held,now_s=stamp,limits=limits,previous=previous)
        previous=frame
        np.save(folder/'depth.npy',depth,allow_pickle=False)
        np.save(folder/'semantic_ids.npy',semantic_ids,allow_pickle=False)
        (folder/'semantic_info.json').write_text(json.dumps(semantic_info,indent=2,default=str)+'\n')
        np.save(folder/'obstacle_pixels_depth.npy',observed,allow_pickle=False)
        np.save(folder/'self_mask.npy',own,allow_pickle=False)
        np.save(folder/'held_mask.npy',held,allow_pickle=False)
        np.save(folder/'obstacle_mask.npy',obstacle_mask,allow_pickle=False)
        if rgb is not None:np.save(folder/'rgb.npy',rgb.numpy(),allow_pickle=False)
        manifest_path=Path(args.model_bundle)/'MODEL_MANIFEST.json'
        (folder/'pose.json').write_text(json.dumps(dict(
            stamp_s=float(stamp),clock_basis='SIM_TIME',q_rad=actual_q.tolist(),
            before_q_rad=measured[axes].astype(float).tolist(),
            after_q_rad=after[axes].astype(float).tolist(),
            grip_rad=float(measured[grip]),
            model_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            state_sequence='STATIONARY_CAPTURE_NOT_EXECUTION_STATE',
            attachment_scope='SIM_NOMINAL_HELD_BODY_PROXY_NO_STUDS',
            sensor_source_stamp_scope='UNAVAILABLE_POST_RENDER_SIM_CLOCK_BRACKET'),indent=2)+'\n')
        (folder/'mask_audit.json').write_text(json.dumps(dict(
            scope='INCOMPLETE_HELD_PROXY_NO_INDEPENDENT_GEOMETRY_MASK',
            model_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            held_geometry_scope='BODY_CUBE_PROXY_FROM_PRIOR_TRACE_STUDS_OMITTED',
            semantic_ids_source='RTX_SEMANTIC_SEGMENTATION_ANNOTATOR',
            independent_full_model_self_mask=False,
            independent_full_model_held_mask=False,
            full_model_mask_array_evidence=False),indent=2)+'\n')
        for name,value in [('frame.json',frame),('limits.json',limits),('candidates.json',projected),
                           ('evidence.json',dict(source_trace=str(source/'cycle_01/transport_observations.jsonl'),
                            trace_index=0 if i==0 else len(trace)//4,scene_source=str(source/'scene.usda'),
                            mount_profile=str(args.mount_profile),mount_profile_source=profile['source_kind'],
                            stream_kind=profile['stream_kind'],fov_deg=profile['fov_deg'],
                            principal_offset_formula_scope=usd['principal_offset_formula_scope'],
                            actual_depth_annotator='distance_to_image_plane',depth_info=depth_info,
                            semantic_info=semantic_info,semantic_labels=labels,
                            gt_obstacle_center_world_m=centre[:3].tolist(),
                            fk_position_error_m=translation,fk_rotation_error_rad=rotation,
                            camera_axes_position_error_m=cam_translation,camera_axes_rotation_error_rad=cam_rotation,
                            sim_stamp_s=stamp,wall_capture_s=time.monotonic()-begin,
                            time_sync_scope='STATIONARY_POST_RENDER_BRACKET_NOT_DYNAMIC_SOURCE_STAMP',
                            held_geometry_scope='SIM_NOMINAL_PROXY_FROM_PRIOR_TRACE_NOT_PHYSICAL_ATTACHMENT',
                            held_size_m=held_object['size_m'],
                            stimulus_depth_only_selection=dict(pixel_uv=[int(px),int(py)],
                                baseline_clearance_pixels=float(clearance[py,px]),
                                baseline_depth_m=float(baseline_depth[py,px]) if np.isfinite(baseline_depth[py,px]) else None,
                                nominal_visual_cube_size_m=.02,
                                planner_receives_ground_truth=False),
                            capture_mode='NATIVE_ISOLATED_SIM_GOAL_THEN_STATIONARY_CAPTURE_NO_HARDWARE'))]:
            (folder/name).write_text(json.dumps(value,indent=2,default=str)+'\n')
        records.append(dict(frame=i,points=projected['valid_pixels'],gt_center=centre[:3].tolist(),
                            visible_center=np.mean(projected['points_base_m'],axis=0).tolist(),
                            masked_self=int(own.sum()),masked_held=int(held.sum()),
                            obstacle_pixels=int(obstacle_mask.sum()),stamp=stamp))
        available={key:dict(path=name,sha256=hashlib.sha256((folder/name).read_bytes()).hexdigest())
            for key,name in dict(frame='frame.json',depth='depth.npy',semantic_ids='semantic_ids.npy',
                semantic_info='semantic_info.json',self_mask='self_mask.npy',held_mask='held_mask.npy',
                obstacle_mask='obstacle_mask.npy',mask_audit='mask_audit.json',pose='pose.json',
                candidates='candidates.json',limits='limits.json').items()}
        (folder/'capture_source.py').write_bytes((args.out/'executed_source.py').read_bytes())
        available['capture_source']=dict(path='capture_source.py',
            sha256=hashlib.sha256((folder/'capture_source.py').read_bytes()).hexdigest())
        (folder/'manifest_draft.json').write_text(json.dumps(dict(
            schema='single-object-depth-evidence/0.1',source_kind='SIM_DEPTH',
            annotator='distance_to_image_plane',status='HOLD_INCOMPLETE_EVIDENCE',
            files=available,missing_files=['geometry_self_mask','geometry_held_mask'],
            limitations=['HELD_BLOCK_STUDS_OMITTED','NO_INDEPENDENT_FULL_MODEL_VISIBILITY_MASK',
                'NO_NATIVE_STOP_COMMAND_COUNTS','NO_SENSOR_HARDWARE_SOURCE_STAMP',
                'NO_DECLARED_SIZE_ERROR_SPEED_LATENCY_PRIOR']),indent=2)+'\n')
        timeline.pause()
    (args.out/'summary.json').write_text(json.dumps(dict(scope='ACTUAL_RTX_DEPTH_NATIVE_GOAL_STATIONARY_WRIST_POSES_NOT_DYNAMIC_CAPTURE',
        frames=records,hardware_execution=False,isolated_sim_controller_goals_sent=True),indent=2)+'\n')
    if close_probe:close_probe()
    Ros2ControlManager.teardown('/World/Robot');node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
