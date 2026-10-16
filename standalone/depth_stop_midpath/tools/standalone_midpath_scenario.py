"""Mid-route SIM stimulus. GT placement audits never feed detection or planning."""
from pathlib import Path
import copy,time
import numpy as np
from sim_utils import rigid,pose_matrix,save
from prepare_gpu_scene import tcp_fk
from isaac_sim.depth_obstacles.unlabelled_static_shadow import UnlabelledStaticShadow


def midpoint_actor(request,curve,owner):
    """Use the actual held-block curve at the halfway plane between board centres."""
    objects={obj['id']:obj for obj in owner['world_objects']}
    supply=np.asarray(objects['SupplyBoard']['pose']['xyz_m'],float)
    assembly=np.asarray(objects['AssemblyBoard']['pose']['xyz_m'],float)
    direction=assembly[:2]-supply[:2];length=float(np.linalg.norm(direction))
    if not np.isfinite(length) or length<=0:raise ValueError('SEPARATE_SUPPLY_AND_ASSEMBLY_BOARDS_REQUIRED')
    direction/=length;midpoint=(supply+assembly)/2
    attachment=rigid(request['attachment']);samples=[]
    for index,point in enumerate(curve['points']):
        tool=tcp_fk(request['model_bundle'],point['positions_rad'],request['planning_snapshot']['grip_rad'])
        center=(tool@attachment)[:3,3]
        progress=float(np.dot(center[:2]-supply[:2],direction)/length)
        samples.append((abs(progress-.5),index,center,progress))
    _,index,center,progress=min(samples,key=lambda row:row[0])
    if not np.isfinite(center).all() or abs(progress-.5)>.02:raise ValueError('ACTUAL_BLOCK_CURVE_MUST_CROSS_BETWEEN_BOARD_MIDPOINT')
    actor=dict(id='SCENARIO_PLACEMENT_GT_ONLY',role='OTHER_OBSTACLE',pose=dict(frame_id='base_link',xyz_m=center.tolist(),quaternion_xyzw=[0,0,0,1]),size_m=[.045,.045,.065],studs=False)
    basis=dict(method='ACTUAL_HELD_BLOCK_CURVE_NEAREST_HALF_WAY_PLANE_BETWEEN_BOARD_CENTRES',supply_board_center_m=supply.tolist(),assembly_board_center_m=assembly.tolist(),board_center_midpoint_m=midpoint.tolist(),board_axis_progress=progress,selected_curve_index=index,selected_planned_time_s=curve['points'][index]['time_from_start_s'],total_planned_time_s=curve['points'][-1]['time_from_start_s'],actual_planned_block_center_m=center.tolist(),coordinate_frame='base_link',historical_trajectory_reused_at_runtime=False)
    return actor,basis


def camera_view_audit(actor,request,curve,profile):
    """Projection only; expected Depth/foreground is still evaluated by the original sensor."""
    center=np.asarray(actor['pose']['xyz_m']);size=np.asarray(actor['size_m'])
    corners=np.array([center+np.array([i,j,k])*size/2 for i in [-1,1] for j in [-1,1] for k in [-1,1]])
    plate=next(obj for obj in request['planning_snapshot']['world_objects'] if obj['id']=='MidpathReferencePlate')
    inverse_plate=np.linalg.inv(pose_matrix(plate['pose']));plate_top=plate['size_m'][2]/2
    intr=profile['intrinsics'];rows=[]
    for index in np.unique(np.linspace(0,len(curve['points'])-1,41,dtype=int)):
        point=curve['points'][index]
        camera=tcp_fk(request['model_bundle'],point['positions_rad'],request['planning_snapshot']['grip_rad'])@np.asarray(profile['T_tool_camera_optical'])
        cam=(np.linalg.inv(camera)@np.c_[corners,np.ones(8)].T).T[:,:3]
        if np.any(cam[:,2]<=0):continue
        uv=np.c_[intr['fx']*cam[:,0]/cam[:,2]+intr['cx'],intr['fy']*cam[:,1]/cam[:,2]+intr['cy']]
        visible=bool(uv[:,0].max()>8 and uv[:,0].min()<intr['width']-8 and uv[:,1].max()>8 and uv[:,1].min()<intr['height']-8)
        # Sample actual known support top rays. A tiny support need not lie behind
        # the actor centre ray to provide occluded known Depth pixels.
        top_local=np.array([[x,y,plate_top,1] for x in np.linspace(-.49,.49,9)*plate['size_m'][0] for y in np.linspace(-.49,.49,9)*plate['size_m'][1]])
        top_world=(pose_matrix(plate['pose'])@top_local.T).T[:,:3]
        rays=top_world-camera[:3,3];lo=center-size/2;hi=center+size/2
        with np.errstate(divide='ignore',invalid='ignore'):
            ta=(lo-camera[:3,3])/rays;tb=(hi-camera[:3,3])/rays
        near=np.minimum(ta,tb).max(axis=1);far=np.maximum(ta,tb).min(axis=1)
        top_cam=(np.linalg.inv(camera)@np.c_[top_world,np.ones(len(top_world))].T).T[:,:3]
        with np.errstate(divide='ignore',invalid='ignore'):
            top_uv=np.c_[intr['fx']*top_cam[:,0]/top_cam[:,2]+intr['cx'],intr['fy']*top_cam[:,1]/top_cam[:,2]+intr['cy']]
        pixels=(top_cam[:,2]>0)&(top_uv[:,0]>=0)&(top_uv[:,0]<intr['width'])&(top_uv[:,1]>=0)&(top_uv[:,1]<intr['height'])
        occluded=pixels&(far>np.maximum(near,0))&(near<1)&(near>0)
        background=bool(occluded.any())
        rows.append(dict(planned_time_s=point['time_from_start_s'],inside_or_intersects_original_camera_view=visible,known_support_occluded_in_camera=background,occluded_support_ray_samples=int(occluded.sum()),pixel_bbox=[uv.min(0).tolist(),uv.max(0).tolist()]))
    return dict(scope='PLANNED_CAMERA_PROJECTION_ONLY_NOT_ACTUAL_DEPTH_OR_STOP_PROOF',samples=rows,visible_samples=sum(row['inside_or_intersects_original_camera_view'] for row in rows),known_background_or_foreground_detection_guaranteed=False)


class MidpathStaticShadow(UnlabelledStaticShadow):
    def prepare(self,request,curve,owner,library,service):
        if self.prepared is not None:raise ValueError('SCENARIO_PLACEMENT_DUPLICATE_PREPARATION')
        from stop_fcl import StopScene,check_stop,file_hash
        actor,basis=midpoint_actor(request,curve,owner)
        support=copy.deepcopy(next(obj for obj in owner['world_objects'] if obj['id']=='MidpathReferencePlate'))
        if support['size_m']!=[.045,.045,.004]:raise ValueError('EXACT_SMALL_SUPPORT_REQUIRED')
        actor['pose']=copy.deepcopy(support['pose'])
        actor['pose']['xyz_m'][2]+=(support['size_m'][2]+actor['size_m'][2])/2
        basis['method']='UNKNOWN_ACTOR_ON_AUTHORED_SMALL_SUPPORT_AT_BOARD_MIDPATH'
        basis['actor_center_m']=list(actor['pose']['xyz_m'])
        basis['support_id']=support['id']
        basis['offset_from_actual_curve_midpoint_m']=(np.asarray(actor['pose']['xyz_m'])-np.asarray(basis['actual_planned_block_center_m'])).tolist()
        actor_ids={actor['id']}
        view=camera_view_audit(actor,request,curve,self.profile)
        if view['visible_samples']==0:raise ValueError('MIDPATH_ACTOR_OUTSIDE_PLANNED_CAMERA_VIEW')
        scene=StopScene(request,library,file_hash(library),extra_obstacles=[actor])
        scene.pairs=[pair for pair in scene.pairs if any(part['id'] in actor_ids for part in pair)]
        original=scene.check;last=time.monotonic()
        def check(q):
            nonlocal last
            if service and time.monotonic()-last>=.05:service();last=time.monotonic()
            return original(q)
        scene.check=check
        try:
            initial=scene.check(curve['points'][0]['positions_rad'])
            if initial:raise ValueError('MIDPATH_ACTOR_INTERSECTS_INITIAL_ROBOT_OR_HELD_BLOCK')
            audit=check_stop(scene,curve);metadata=dict(scene.metadata);pairs=len(scene.pairs)
        finally:scene.close()
        if audit['success'] or not actor_ids.intersection(audit.get('collision_pair',[])):raise ValueError('MIDPATH_ACTOR_MUST_BLOCK_FUTURE_PLANNED_ROUTE')
        if audit['time_s']<=.5:raise ValueError('MIDPATH_ACTOR_CONTACT_BEFORE_ORIGINAL_SPAWN_DELAY')
        view['pre_contact_visible_reference_plate_samples']=int(sum(row['inside_or_intersects_original_camera_view'] and row['known_support_occluded_in_camera'] and row['planned_time_s']<audit['time_s'] for row in view['samples']))
        if not view['pre_contact_visible_reference_plate_samples']:raise ValueError('MIDPATH_NO_REFERENCE_BACKGROUND_BEFORE_PREDICTED_CONTACT')
        self.prepared=dict(actor=actor,support=support,placement_basis=basis,view=view,actual_wire_points=len(curve['points']),FCL=audit,initial_actor_robot_held_clear=True,geometry=metadata,actor_pair_count=pairs,owner_before=copy.deepcopy(owner),intentional_future_route_blockage=True)
        save(self.out/'scenario_GT_audit_only/placement.json',dict(self.prepared,scope='GT_MIDPATH_STIMULUS_AUDIT_ONLY_NEVER_DETECTOR_OR_PLANNER_INPUT',new_static_actor_not_yet_created=True,actual_detection_and_cancel_not_yet_verified=True))
