"""Off-path STATIC scenario/GT audit only. Never imported by Depth/risk/planner."""
from pathlib import Path
import copy,json,time
import numpy as np
from sim_utils import pose_matrix,matrix_pose,save


def visibility_audit(center,size,board,request,curve,profile):
    from prepare_gpu_scene import tcp_fk
    inv_board=np.linalg.inv(pose_matrix(board['pose']));top=board['size_m'][2]/2
    corners=np.array([np.array(center)+np.array([i,j,k])*np.array(size)/2 for i in [-1,1] for j in [-1,1] for k in [-1,1]])
    intr=profile['intrinsics'];rows=[]
    for index in np.linspace(int(.7*(len(curve['points'])-1)),len(curve['points'])-1,8,dtype=int):
        q=curve['points'][index]['positions_rad'];camera=tcp_fk(request['model_bundle'],q,request['planning_snapshot']['grip_rad'])@np.array(profile['T_tool_camera_optical'])
        cam=(np.linalg.inv(camera)@np.c_[corners,np.ones(8)].T).T[:,:3]
        if np.any(cam[:,2]<=0):continue
        uv=np.c_[intr['fx']*cam[:,0]/cam[:,2]+intr['cx'],intr['fy']*cam[:,1]/cam[:,2]+intr['cy']]
        origin=(inv_board@np.r_[camera[:3,3],1])[:3];point=(inv_board@np.r_[center,1])[:3];direction=point-origin
        if direction[2]==0:continue
        t=(top-origin[2])/direction[2];hit=origin+t*direction
        interior=bool(t>1 and np.all(abs(hit[:2])<np.array(board['size_m'][:2])/2-.012))
        inside=bool(uv[:,0].min()>8 and uv[:,0].max()<intr['width']-8 and uv[:,1].min()>8 and uv[:,1].max()<intr['height']-8)
        rows.append(dict(planned_time_s=curve['points'][index]['time_from_start_s'],pixel_bbox=[uv.min(0).tolist(),uv.max(0).tolist()],known_board_behind_center_ray=interior,inside_original_camera_view=inside))
    return dict(scope='PLANNED_CAMERA_GEOMETRY_PLACEMENT_AUDIT_NOT_DETECTION',samples=rows,visible_board_samples=sum(x['known_board_behind_center_ray'] and x['inside_original_camera_view'] for x in rows))


class UnlabelledStaticShadow:
    def __init__(self,out,stage,seed,profile):
        self.out=Path(out);self.stage=stage;self.seed=seed;self.profile=profile
        self.accepted_source_s=None;self.prepared=None;self.spawned=False
        self.path='/World/UnlabelledStaticShadow/Body'
        (self.out/'scenario_GT_audit_only').mkdir(exist_ok=False)

    def prepare(self,request,curve,owner,library,service):
        """Actual new curve's whole robot/held swept-volume audit before spawn."""
        if self.prepared is not None:raise ValueError('SCENARIO_PLACEMENT_DUPLICATE_PREPARATION')
        from stop_fcl import StopScene,check_stop,file_hash
        board=next(o for o in owner['world_objects'] if o['id']=='AssemblyBoard')
        board_pose=pose_matrix(board['pose']);size=[.045,.045,.065];attempts=[]
        for dx,dy in [(-.14,.13),(.14,.13),(-.14,.095),(.14,.095),(-.12,.14),(.12,.14)]:
            center=(board_pose@np.array([dx,dy,board['size_m'][2]/2+size[2]/2,1]))[:3].tolist()
            view=visibility_audit(center,size,board,request,curve,self.profile)
            if view['visible_board_samples']<2:
                attempts.append(dict(center_m=center,view=view,reason='INSUFFICIENT_PLANNED_KNOWN_STATIC_VIEW'));continue
            actor=dict(id='SCENARIO_PLACEMENT_GT_ONLY',role='OTHER_OBSTACLE',pose=dict(frame_id='base_link',xyz_m=center,quaternion_xyzw=[0,0,0,1]),size_m=size,studs=False)
            scene=StopScene(request,library,file_hash(library),extra_obstacles=[actor]);last=time.monotonic();original=scene.check
            # Previous unchanged native admission checks all original pairs.
            # This additional scenario audit checks ONLY new actor pairs using
            # every original robot/gripper triangle and held body+stud primitive.
            scene.pairs=[pair for pair in scene.pairs if any(p['id']==actor['id'] for p in pair)]
            def check(q):
                nonlocal last
                if service and time.monotonic()-last>=.05:service();last=time.monotonic()
                return original(q)
            scene.check=check
            try:audit=check_stop(scene,curve);metadata=dict(scene.metadata);pairs=len(scene.pairs)
            finally:scene.close()
            attempts.append(dict(center_m=center,view=view,actor_robot_held_FCL=audit,actor_pair_count=pairs,full_geometry=metadata))
            if audit['success']:
                self.prepared=dict(actor=actor,view=view,actual_wire_points=len(curve['points']),FCL=audit,geometry=metadata,actor_pair_count=pairs,owner_before=copy.deepcopy(owner),attempts=attempts)
                save(self.out/'scenario_GT_audit_only/placement.json',dict(self.prepared,scope='GT_PLACEMENT_AND_OFF_PATH_AUDIT_ONLY_NEVER_DETECTOR_OR_PLANNER_INPUT',new_static_actor_not_yet_created=True));return
        save(self.out/'scenario_GT_audit_only/placement_rejected.json',dict(attempts=attempts));raise ValueError('NO_OFF_PATH_VISIBLE_STATIC_PLACEMENT')

    def event(self,kind,payload,stamp):
        if kind=='GOAL_ACCEPTED' and payload.get('accepted'):self.accepted_source_s=stamp

    def sample(self,row):
        if self.spawned or self.accepted_source_s is None or row['time_s']-self.accepted_source_s<.5:return
        if self.prepared is None:raise ValueError('UNLABELLED_ACTOR_NOT_AUDITED')
        if max(abs(v) for v in row['velocity_rad_s'][:6])==0:return
        from pxr import UsdGeom,UsdPhysics,Gf
        from sim_utils import matrix_pose
        actor=self.prepared['actor'];base=np.array(json.loads((self.out/'known_depth_map/map_snapshot.json').read_text())['T_world_base'])
        world=base@pose_matrix(actor['pose']);root=UsdGeom.Xform.Define(self.stage,str(Path(self.path).parent));root.AddTransformOp().Set(Gf.Matrix4d(world.T))
        cube=UsdGeom.Cube.Define(self.stage,self.path);cube.CreateSizeAttr(1.);cube.AddScaleOp().Set(Gf.Vec3d(*actor['size_m']));cube.CreateDisplayColorAttr([Gf.Vec3f(.7,.25,.12)]);UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        # Static: deliberately no RigidBody/semantic/instance annotation or seed/map change.
        self.spawned=True
        save(self.out/'scenario_GT_audit_only/spawn.json',dict(scope='POST_MAP_FREEZE_AFTER_NATIVE_ACCEPTANCE_GT_AUDIT_ONLY',prim_path=self.path,actual_source_s=row['time_s'],actual_wall_monotonic_s=time.monotonic(),accepted_source_s=self.accepted_source_s,q_rad=row['q_rad'],raw_v_rad_s=row['velocity_rad_s'][:6],world_pose=matrix_pose(world),actor=actor,semantic_annotation_added=False,known_map_or_planner_updated=False,detector_cancel_allowed=False))
