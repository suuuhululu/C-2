"""Full original mesh/stud FCL sampling for file-only stopping candidates.

Uses a separately compiled, explicitly pinned CPU FCL shim, not MoveIt's
ROS-initializing executable. No collision-sphere approximation or touch patch.
"""
import ctypes
from itertools import combinations
from pathlib import Path
from urllib.parse import unquote,urlparse
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from cumotion_geometry import read_closed_stl,object_boxes
from prepare_cpu_model import file_hash
from prepare_cumotion_model import urdf_transforms,TCP,TOUCH
from plan_only import checked_pose,prepare_d_candidate,BINDING,digest,vector
from stop_curve import quintic_intervals


def holding_error(desired,current,allow_yaw):
    # MoveIt2.12.4 ROTATION_VECTOR: target-frame log mapped to header/base frame.
    vector=np.abs(desired@Rotation.from_matrix(desired.T@current).as_rotvec())
    limits=np.array([.25,.25,np.pi if allow_yaw else .6])
    return vector if np.any(vector>=limits+np.finfo(float).eps) else None


class StopScene:
    def __init__(self,request,library,expected_sha256,extra_obstacles=()):
        if file_hash(library)!=expected_sha256:
            raise ValueError('PINNED_OFFLINE_FCL_REQUIRED')
        self.lib=ctypes.CDLL(str(Path(library).resolve()));self.parts=[]
        self.robot=ET.fromstring(request['model_bundle']['robot_description'])
        self.grip=request['planning_snapshot']['grip_rad']
        self.attachment=np.asarray(request['attachment'],float)
        self.orientation=checked_pose(request['holding_orientation'])[:3,:3]
        self.allow_yaw=request.get('allow_yaw_reorientation',False)
        self.pairs=[]
        pointer=ctypes.c_void_p;array=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
        integer=np.ctypeslib.ndpointer(dtype=np.int32,flags='C_CONTIGUOUS')
        self.lib.stop_mesh.argtypes=[array,ctypes.c_int,integer,ctypes.c_int];self.lib.stop_mesh.restype=pointer
        self.lib.stop_box.argtypes=[ctypes.c_double]*3;self.lib.stop_box.restype=pointer
        self.lib.stop_transform.argtypes=[pointer,array]
        self.lib.stop_transform.restype=None
        self.lib.stop_collide.argtypes=[pointer,pointer];self.lib.stop_collide.restype=ctypes.c_int
        self.lib.stop_destroy.argtypes=[pointer]
        self.lib.stop_destroy.restype=None
        try:
            for link in self.robot.findall('link'):
                for i,col in enumerate(link.findall('collision')):
                    mesh=col.find('geometry/mesh')
                    if mesh is None:raise ValueError('Original collision mesh required')
                    uri=urlparse(mesh.get('filename'))
                    if uri.scheme!='file' or uri.netloc:raise ValueError('Local verified mesh required')
                    vertices,triangles=read_closed_stl(Path(unquote(uri.path)))
                    scale=np.array(mesh.get('scale','1 1 1').split(),float)
                    vertices=np.ascontiguousarray(vertices*scale)
                    handle=self.lib.stop_mesh(vertices,len(vertices),triangles,len(triangles))
                    local=np.eye(4);origin=col.find('origin')
                    if origin is not None:
                        local[:3,3]=np.array(origin.get('xyz','0 0 0').split(),float)
                        local[:3,:3]=Rotation.from_euler('xyz',np.array(origin.get('rpy','0 0 0').split(),float)).as_matrix()
                    self.add(link.get('name'),handle,link.get('name'),local,'robot')
            robot_count=len(self.parts)
            selected=None;world_count=0
            for obj in request['planning_snapshot']['world_objects']:
                if obj['id']==request['planning_snapshot']['selected_slot_id']:
                    selected=obj;continue
                padding=.002 if obj['role'] in ('SUPPLY_BLOCK','CURRENT_BLOCK') else 0.
                self.boxes(obj,checked_pose(obj['pose']),padding,'world');world_count+=1
            if selected is None:raise ValueError('Attachment geometry missing')
            self.boxes(selected,self.attachment,0.,'held')
            for obj in extra_obstacles:
                if obj['id'] in {p['id'] for p in self.parts}:raise ValueError('Obstacle ID already present')
                self.boxes(obj,checked_pose(obj['pose']),0.,'world');world_count+=1
            srdf=ET.fromstring(request['model_bundle']['robot_description_semantic'])
            disabled={frozenset((p.get('link1'),p.get('link2'))) for p in srdf.findall('disable_collisions')}
            for first,second in combinations(self.parts,2):
                kinds={first['kind'],second['kind']}
                if 'robot' not in kinds and 'held' not in kinds:continue
                if first['kind']==second['kind']=='held':continue
                if first['kind']==second['kind']=='robot' and (first['link']==second['link'] or frozenset((first['link'],second['link'])) in disabled):continue
                if kinds=={'robot','held'} and (first if first['kind']=='robot' else second)['link'] in TOUCH:continue
                self.pairs.append((first,second))
            self.metadata=dict(robot_collision_mesh_parts=robot_count,world_objects=world_count,
                held_objects=1,held_primitives=sum(p['kind']=='held' for p in self.parts),
                collision_pairs=len(self.pairs),world_block_padding_m=.002,
                robot_geometry='ORIGINAL_TRIANGLE_MESH_BVH',touch_links=TOUCH,
                library_sha256=expected_sha256,initial_support_contact_exception=False)
        except Exception:
            self.close();raise

    def add(self,name,handle,link,local,kind):
        if not handle:raise ValueError('FCL geometry allocation failed')
        self.parts.append(dict(id=name,handle=handle,link=link,local=local,kind=kind))

    def boxes(self,obj,transform,padding,kind):
        for size,local in object_boxes(obj,transform,padding):
            if not np.isfinite(size).all() or np.any(size<=0):raise ValueError('Positive finite box required')
            self.add(obj['id'],self.lib.stop_box(*size),TCP if kind=='held' else None,local,kind)

    def check(self,q):
        frames=urdf_transforms(self.robot,q,self.grip)
        self.last_tcp=frames[TCP]
        for part in self.parts:
            t=frames[part['link']]@part['local'] if part['link'] else part['local']
            self.lib.stop_transform(part['handle'],np.ascontiguousarray(t))
        for first,second in self.pairs:
            if self.lib.stop_collide(first['handle'],second['handle']):
                return dict(collision_pair=[first['id'],second['id']],
                    collision_part_kinds=[first['kind'],second['kind']],
                    collision_components=[('GRIPPER' if (p['link'] or '').startswith('rg2_') else p['kind'].upper()) for p in (first,second)],
                    collision_links=[first['link'],second['link']],
                    collision_local_parts=[first['local'].tolist(),second['local'].tolist()])
        current=frames[TCP][:3,:3]
        vector=holding_error(self.orientation,current,self.allow_yaw)
        if vector is not None:
            return dict(holding_orientation_rejected=True,rotation_error_rad=vector.tolist())
        return None

    def close(self):
        for part in self.parts:self.lib.stop_destroy(part['handle'])
        self.parts=[]


def check_stop(scene,trajectory,*,trace=None):
    """Sample final quintic with a polynomial bound <=.001rad and <=5ms.

    Finite collision sampling, not continuous collision detection or a dynamic
    obstacle prediction. Includes both endpoints; returns first rejection.
    """
    checks=0;first_hit=None
    for start,h,c in quintic_intervals(trajectory):
        bound=float(np.max(np.sum(np.abs(c[1:])*np.arange(1,6)[:,None],axis=0)))
        count=max(1,int(np.ceil(bound/.001)),int(np.ceil(h/.005)))
        for u in np.linspace(0,1,count+1):
            q=np.polynomial.polynomial.polyval(u,c)
            hit=scene.check(q);checks+=1
            if trace is not None:
                trace.append(dict(time_s=float(start+u*h),tcp_xyz_m=scene.last_tcp[:3,3].tolist(),
                    collision=bool(hit),components=hit.get('collision_components',[]) if hit else []))
            if hit and first_hit is None:
                first_hit=dict(success=False,checks=checks,time_s=start+u*h,q_rad=q.tolist(),**hit)
                if trace is None:return first_hit
    if first_hit is not None:
        first_hit['total_checked_states']=checks
        return first_hit
    return dict(success=True,checks=checks,max_joint_interval_bound_rad=.001,
        max_time_interval_s=.005,continuous_collision_detection=False)


def check_baseline_with_obstacle(request,baseline_result,obstacle,*,source_kind,library,expected_sha256,record_tcp_path=False):
    """Inspect an unchanged timed baseline with one added object, never replan.

    GT is an explicitly separate stimulus audit. Depth geometry must have been
    replayed by the caller's existing verify_bound/admission before this check.
    A clear baseline is failure to demonstrate avoidance, not success.
    """
    if source_kind not in ('GT_PLACEMENT_AUDIT_ONLY','REPLAYED_DEPTH_BOUND'):
        raise ValueError('EXPLICIT_GT_OR_DEPTH_COMPARISON_SCOPE_REQUIRED')
    if (obstacle['pose']['frame_id']!='base_link' or obstacle['role']!='OTHER_OBSTACLE' or obstacle['studs'] is not False or
            min(vector(obstacle['size_m'],3))<=0):raise ValueError('POSITIVE_BASE_FRAME_STIMULUS_BOX_REQUIRED')
    prepare_d_candidate(baseline_result,request,{k:request[k] for k in BINDING})
    trajectory=baseline_result['planned_trajectory']
    scene=StopScene(request,library,expected_sha256,extra_obstacles=[obstacle])
    try:
        endpoints=[scene.check(p['positions_rad']) for p in (trajectory['points'][0],trajectory['points'][-1])]
        if any(x is not None for x in endpoints):
            result=dict(status='PLACEMENT_REJECTED_START_OR_GOAL_COLLISION',endpoints=endpoints)
        else:
            trace=[] if record_tcp_path else None
            checks=check_stop(scene,trajectory,trace=trace)
            if checks['success']:status='BASELINE_CLEAR_AVOIDANCE_NOT_PROVEN'
            elif obstacle['id'] in checks.get('collision_pair',[]):status='BASELINE_BLOCKED_BY_STIMULUS'
            else:status='BASELINE_REJECTED_UNRELATED_COLLISION_OR_HOLDING'
            result=dict(status=status,endpoints=endpoints,baseline_checks=checks)
            if trace is not None:result['tcp_path']=trace
    finally:scene.close()
    prepare_d_candidate(baseline_result,request,{k:request[k] for k in BINDING})
    if file_hash(library)!=expected_sha256:raise ValueError('COMPARISON_FCL_LIBRARY_CHANGED')
    return dict(scope='COUNTERFACTUAL_BASELINE_CHECK_NOT_REPLAN_OR_NATIVE_PROOF',source_kind=source_kind,
        original_request_digest=request['planning_request_digest'],model_digest=request['model_digest'],
        original_trajectory_digest=digest(trajectory),obstacle_geometry_digest=digest(obstacle),
        FCL_library_sha256=expected_sha256,**result,native_execution_allowed=False,hardware_execution_allowed=False)
