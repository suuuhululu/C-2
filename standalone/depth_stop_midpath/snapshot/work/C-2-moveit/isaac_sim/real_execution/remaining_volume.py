"""CPU interval enclosure of every original robot collision and held part; no sender.

Bernstein coefficients use exact rational arithmetic on the delivered binary
floats. Directed interval trigonometry/matrix operations cover full rotations.
Mesh AABBs enclose triangles and their interior, not only sampled vertices.
This is a risk corridor, never a collision-free or measured-tracking proof.
"""
from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
from math import comb, isfinite, nextafter, inf
from pathlib import Path
from urllib.parse import urlparse, unquote
import json
import xml.etree.ElementTree as ET

import numpy as np
from mpmath.ctx_iv import MPIntervalContext
from plan_only import digest, JOINTS, validate_trajectory
from prepare_cpu_model import read_model_bundle
from prepare_cumotion_model import TCP
from cumotion_geometry import read_closed_stl, object_boxes

IDENTITY = ('goal_id', 'goal_version', 'session_id', 'clock_basis', 'clock_epoch',
            'goal_start_stamp_s', 'active_wire_digest', 'model_digest',
            'selected_block_id')
FULL_SCOPE = 'CONSERVATIVE_REMAINING_FULL_ROBOT_HELD_SWEPT_VOLUME'
COMPONENTS = ('ROBOT_BASE', 'ROBOT_ARM', 'GRIPPER', 'HELD_BLOCK')
NUMERIC = 'IMMUTABLE_NUMERIC_INTERVAL_BOUNDS_V1'


def _readonly(value,dtype=float):
    a=np.asarray(value,dtype=dtype)
    return np.frombuffer(a.tobytes(),dtype=a.dtype).reshape(a.shape)


def _pin(ref):
    data = Path(ref['path']).read_bytes()
    if sha256(data).hexdigest() != ref['sha256']:
        raise ValueError('ACCEPTED_GOAL_SOURCE_CHANGED')
    return json.loads(data)


def _coefficients(left, right):
    h = _wire_time(right['time_from_start_s']) - _wire_time(left['time_from_start_s'])
    columns = []
    for j in range(6):
        q, v, a = (F(left[k][j]) for k in
                   ('positions_rad', 'velocities_rad_s', 'accelerations_rad_s2'))
        dq = F(right['positions_rad'][j])-q-v*h-a*h*h/2
        dv = F(right['velocities_rad_s'][j])*h-v*h-a*h*h
        da = F(right['accelerations_rad_s2'][j])*h*h-a*h*h
        columns.append([q, v*h, a*h*h/2, 10*dq-4*dv+da/2,
                        -15*dq+7*dv-da, 6*dq-3*dv+da/2])
    return columns


def _wire_time(value):
    ns=round(value*1_000_000_000)
    if value!=ns/1_000_000_000:raise ValueError('EXACT_NATIVE_NANOSECOND_WIRE_REQUIRED')
    return F(ns,1_000_000_000)


def bernstein_bounds(coefficients, start=F(0)):
    """Exact convex hull of degree-five Bernstein coefficients on [start,1]."""
    power = [sum(coefficients[k]*comb(k,j)*start**(k-j)*(1-start)**j
                 for k in range(j,6)) for j in range(6)]
    b = [sum(power[j]*F(comb(k,j),comb(5,j)) for j in range(k+1))
         for k in range(6)]
    return min(b), max(b)


class RemainingVolume:
    """Precompute before dispatch, then bind the actual accepted goal.

    D supplies a pinned accepted binding and current source-tick progress in
    seconds (controller reference time from this goal, not waypoint snapping).
    A new UUID/version, wire, model, grip, attachment or source clock requires
    a fresh binding (new curve instance for geometry/wire changes).
    STOP/unknown/idle ticks are rejected. Do not call concurrently on one instance.
    """
    def __init__(self, request, wire, accepted_ref=None):
        self.request = deepcopy(request); self.wire = deepcopy(wire)
        self.accepted_ref = None; self.accepted = None
        validate_trajectory(wire)
        bundle = read_model_bundle(request['model_bundle']['bundle_path'])
        if digest(bundle) != request['model_digest']:
            raise ValueError('ORIGINAL_MODEL_CHANGED')
        snapshot = request['planning_snapshot']
        if type(snapshot['grip_rad']) not in (int,float) or not isfinite(snapshot['grip_rad']):
            raise ValueError('FINITE_FIXED_GRIP_REQUIRED')
        attachment_raw=np.asarray(request['attachment'],float)
        if attachment_raw.shape!=(4,4) or not np.isfinite(attachment_raw).all() or list(attachment_raw[3])!=[0.,0.,0.,1.]:
            raise ValueError('RAW_FINITE_ATTACHMENT_REQUIRED')
        self.geometry_binding=dict(active_wire_digest=digest(wire),model_digest=request['model_digest'],
            selected_block_id=snapshot['selected_slot_id'],grip_rad=snapshot['grip_rad'],attachment_tcp_to_block=deepcopy(request['attachment']))
        self.iv = MPIntervalContext(); self.iv.prec = 80
        self._previous_progress = None
        self.robot = ET.fromstring(bundle['robot_description'])
        self.joints = self.robot.findall('joint')
        for j in self.joints:
            if j.get('type')=='revolute':
                axis=[F(float(v)) for v in j.find('axis').get('xyz').split()]
                if sum(v*v for v in axis)!=1:raise ValueError('ORIGINAL_UNIT_JOINT_AXIS_REQUIRED')
        self.origins = {j.get('name'):self._origin(j.find('origin')) for j in self.joints}
        self.parts = []; self.mesh_pins = {}; self.collision_inventory = []
        # Classify by kinematic ancestry, not by skipping non-RG2 link names.
        parent_joint = {j.find('child').get('link'):j for j in self.joints}
        def component(name):
            moving = False; seen = set()
            while name != 'base_link':
                if name == 'rg2_base_link':return 'GRIPPER'
                if name in seen or name not in parent_joint:
                    raise ValueError('COLLISION_LINK_NOT_ROOTED_AT_BASE')
                seen.add(name); joint = parent_joint[name]
                moving |= joint.get('type') != 'fixed'
                name = joint.find('parent').get('link')
            return 'ROBOT_ARM' if moving else 'ROBOT_BASE'
        for link in self.robot.findall('link'):
            for index,col in enumerate(link.findall('collision')):
                mesh = col.find('geometry/mesh')
                if mesh is None: raise ValueError('ORIGINAL_COLLISION_MESH_REQUIRED')
                uri = urlparse(mesh.get('filename'))
                if uri.scheme != 'file' or uri.netloc: raise ValueError('LOCAL_MESH_REQUIRED')
                path = Path(unquote(uri.path)); vertices,triangles = read_closed_stl(path)
                self.mesh_pins[str(path)] = sha256(path.read_bytes()).hexdigest()
                raw_scale = list(map(float,mesh.get('scale','1 1 1').split()))
                if len(raw_scale)!=3 or not all(isfinite(s) and s!=0 for s in raw_scale):
                    raise ValueError('FINITE_NONZERO_MESH_SCALE_REQUIRED')
                scale = [self.iv.mpf(s) for s in raw_scale]
                xyz = [self.iv.mpf([float(vertices[:,i].min()),float(vertices[:,i].max())])*scale[i] for i in range(3)]
                local = self._point(self._origin(col.find('origin')),xyz)
                name=f'{link.get("name")}/collision_{index}'; kind=component(link.get('name'))
                self.parts.append(dict(name=name,component=kind,link=link.get('name'),xyz=local))
                origin=col.find('origin')
                self.collision_inventory.append(dict(part=name,component=kind,link=link.get('name'),
                    collision_index=index,mesh_path=str(path),mesh_sha256=self.mesh_pins[str(path)],
                    scale=raw_scale,origin_xyz_m=list(map(float,origin.get('xyz','0 0 0').split())) if origin is not None else [0.,0.,0.],
                    origin_rpy_rad=list(map(float,origin.get('rpy','0 0 0').split())) if origin is not None else [0.,0.,0.],
                    mesh_min_m=vertices.min(axis=0).tolist(),mesh_max_m=vertices.max(axis=0).tolist(),
                    triangle_count=len(triangles),closed_two_manifold=True))
        selected = next(o for o in snapshot['world_objects'] if o['id']==snapshot['selected_slot_id'])
        if selected['size_m'] != [.032,.032,.019] or selected['studs'] is not True:
            raise ValueError('REVIEWED_BODY_4_STUD_GEOMETRY_REQUIRED')
        # Reuse canonical body/stud offsets; multiply the raw attachment in interval arithmetic.
        attachment = [[self.iv.mpf(v) for v in row] for row in request['attachment']]
        for index,(size,local) in enumerate(object_boxes(selected,np.eye(4),0.)):
            local_iv = [[self.iv.mpf(v) for v in row] for row in local.tolist()]
            xyz = [self.iv.mpf([-float(s)/2,float(s)/2]) for s in size]
            held_local=self._point(local_iv,xyz)
            self.parts.append(dict(name='held/body' if index==0 else f'held/stud_{index}',
                component='HELD_BLOCK',link=TCP,xyz=self._point(attachment,held_local),held_local=held_local))
        if not any(p['component']=='GRIPPER' for p in self.parts):
            raise ValueError('FULL_GRIPPER_GEOMETRY_REQUIRED')
        self.part_inventory=[dict(part=p['name'],component=p['component'],link=p['link']) for p in self.parts]
        self.inventory_digest=digest(dict(model_digest=request['model_digest'],
            collisions=self.collision_inventory,parts=self.part_inventory))
        self.intervals = []
        for left,right in zip(wire['points'][:-1],wire['points'][1:]):
            start,end = _wire_time(left['time_from_start_s']),_wire_time(right['time_from_start_s'])
            coefficients = _coefficients(left,right)
            self.intervals.append((start,end,coefficients,self._boxes(coefficients)))
        # Bytes-backed arrays cannot be made writeable by a caller. Every
        # original interval/part remains present; no curve sampling or reduction.
        times=_readonly([[int(a*10**9),int(b*10**9)] for a,b,_,_ in self.intervals],np.int64)
        bounds=_readonly([[[b['min_m'],b['max_m']] for b in boxes] for _,_,_,boxes in self.intervals])
        from .risk_spatial import build_hierarchy
        tree,nodes,order=build_hierarchy(bounds)
        tree=_readonly(tree);nodes=_readonly(nodes,np.int64);order=_readonly(order,np.int64)
        metadata=dict(geometry_binding=self.geometry_binding,inventory_digest=self.inventory_digest,
            collision_inventory=self.collision_inventory,part_inventory=self.part_inventory,
            interval_count=len(times),part_count=len(self.parts),
            times_sha256=sha256(times.tobytes()).hexdigest(),bounds_sha256=sha256(bounds.tobytes()).hexdigest(),
            spatial_node_count=len(nodes),spatial_leaf_capacity=16,
            spatial_bounds_sha256=sha256(tree.tobytes()).hexdigest(),spatial_nodes_sha256=sha256(nodes.tobytes()).hexdigest(),
            spatial_order_sha256=sha256(order.tobytes()).hexdigest())
        raw=json.dumps(metadata,sort_keys=True,allow_nan=False).encode()
        self._numeric_curve=dict(manifest=raw,curve_digest=sha256(raw).hexdigest(),interval_ns=times,bounds=bounds,
            spatial_bounds=tree,spatial_nodes=nodes,spatial_order=order)
        self._numeric_coefficients=tuple(tuple(tuple(col) for col in c) for _,_,c,_ in self.intervals)
        self._numeric_geometry_digest=digest(self.geometry_binding)
        self._numeric_part_keys=tuple((p['name'],p['component']) for p in self.parts)
        if accepted_ref is not None:self.bind(accepted_ref)

    def bind(self,accepted_ref):
        """Fresh D acceptance only; precomputation itself supplies no UUID approval."""
        a=_pin(accepted_ref)
        if a['scope']!='ACCEPTED_NATIVE_GOAL_BINDING' or not a['goal_id']:
            raise ValueError('EXPLICIT_ACCEPTED_GOAL_REQUIRED')
        if type(a['goal_version']) is not int or a['goal_version']<0:
            raise ValueError('GOAL_VERSION_REQUIRED')
        if type(a['clock_epoch']) is not int or a['clock_epoch']<0 or a['clock_basis']!='SIM_TIME' or not a['session_id']:
            raise ValueError('EXPLICIT_SIM_SOURCE_CLOCK_REQUIRED')
        if any(type(a[k]) is not type(v) or a[k]!=v for k,v in self.geometry_binding.items()):
            raise ValueError('ACCEPTED_WIRE_MODEL_OR_HELD_GEOMETRY_CHANGED')
        for k in ('goal_start_stamp_s','grip_rad'):
            if type(a[k]) not in (int,float) or not isfinite(a[k]):raise ValueError('FINITE_ACCEPTED_BINDING_REQUIRED')
        if digest(read_model_bundle(self.request['model_bundle']['bundle_path']))!=a['model_digest']:
            raise ValueError('MODEL_SOURCE_CHANGED')
        self.identity=IDENTITY + (('known_geometry_digest',) if 'known_geometry_digest' in a else ())
        if 'known_geometry_digest' in a and (not isinstance(a['known_geometry_digest'],str) or not a['known_geometry_digest']):
            raise ValueError('EXPLICIT_KNOWN_GEOMETRY_DIGEST_REQUIRED')
        self.accepted_ref=deepcopy(accepted_ref);self.accepted=deepcopy(a);self._previous_progress=None

    def _mul(self,a,b):
        return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

    def _point(self,t,xyz):
        return [sum(t[i][j]*xyz[j] for j in range(3))+t[i][3] for i in range(3)]

    def _rotation(self,axis,angle):
        iv = self.iv; c,s = iv.cos(angle),iv.sin(angle)
        norm = iv.sqrt(sum(v*v for v in axis)); x,y,z = [v/norm for v in axis]
        cross = [[0,-z,y],[z,0,-x],[-y,x,0]]; unit=[x,y,z]
        return [[c*(i==j)+(1-c)*unit[i]*unit[j]+s*cross[i][j] if i<3 and j<3
                 else iv.mpf(int(i==j)) for j in range(4)] for i in range(4)]

    def _origin(self,item):
        identity = [[self.iv.mpf(int(i==j)) for j in range(4)] for i in range(4)]
        if item is None: return identity
        angles = [float(v) for v in item.get('rpy','0 0 0').split()]
        result = identity
        for axis,angle in zip(([1,0,0],[0,1,0],[0,0,1]),angles):
            result = self._mul(self._rotation([self.iv.mpf(v) for v in axis],self.iv.mpf(angle)),result)
        for i,v in enumerate(item.get('xyz','0 0 0').split()):result[i][3]=self.iv.mpf(float(v))
        return result

    def _boxes(self,coefficients,start=F(0),*,grip_rad=None,attachment=None):
        iv = self.iv
        def rational(v):return iv.mpf(v.numerator)/v.denominator
        values = {name:iv.mpf([rational(lo).a,rational(hi).b]) for name,(lo,hi) in
                  zip(JOINTS,[bernstein_bounds(c,start) for c in coefficients])}
        values['rg2_finger_joint'] = iv.mpf(self.geometry_binding['grip_rad'] if grip_rad is None else grip_rad)
        for j in self.joints:
            mimic = j.find('mimic')
            if mimic is not None:
                values[j.get('name')] = values[mimic.get('joint')]*iv.mpf(float(mimic.get('multiplier','1')))+iv.mpf(float(mimic.get('offset','0')))
        frames = {'base_link':[[iv.mpf(int(i==j)) for j in range(4)] for i in range(4)]}
        for _ in self.joints:
            for joint in self.joints:
                parent,child = joint.find('parent').get('link'),joint.find('child').get('link')
                if parent not in frames or child in frames:continue
                local = self.origins[joint.get('name')]
                if joint.get('type')=='revolute':
                    axis = [iv.mpf(float(v)) for v in joint.find('axis').get('xyz').split()]
                    local = self._mul(local,self._rotation(axis,values[joint.get('name')]))
                elif joint.get('type')!='fixed':raise ValueError('UNSUPPORTED_KINEMATIC_JOINT')
                frames[child] = self._mul(frames[parent],local)
        boxes=[]
        for part in self.parts:
            local=part['xyz']
            if attachment is not None and part['component']=='HELD_BLOCK':
                local=self._point([[iv.mpf(v) for v in row] for row in attachment],part['held_local'])
            xyz = self._point(frames[part['link']],local)
            boxes.append(dict(component=part['component'],part=part['name'],
                min_m=[nextafter(float(v.a),-inf) for v in xyz],
                max_m=[nextafter(float(v.b),inf) for v in xyz]))
        return boxes

    def _observe(self,owner):
        if self.accepted is None:raise ValueError('ACTUAL_ACCEPTED_BINDING_NOT_ATTACHED')
        if _pin(self.accepted_ref)!=self.accepted:raise ValueError('ACCEPTED_BINDING_CHANGED')
        if any(type(owner[k]) is not type(self.accepted[k]) or owner[k]!=self.accepted[k] for k in self.identity):
            raise ValueError('CURRENT_GOAL_MODEL_CLOCK_OR_ATTACHMENT_CHANGED')
        if owner['mode']!='TRANSPORT' or type(owner['active_command_count']) is not int or owner['active_command_count']<=0:
            raise ValueError('ACTIVE_TRANSPORT_REQUIRED')
        if any(owner[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):
            raise ValueError('STOP_OR_UNKNOWN_NO_REMAINING_VOLUME')
        if owner['holding_confirmed'] is not True or not {'rg2_left_inner_finger','rg2_right_inner_finger'}<=set(owner['contact_fingers']):
            raise ValueError('CURRENT_HOLDING_CONTACT_REQUIRED')
        p=owner['trajectory_progress_s'];stamp=owner['progress_stamp_s']
        if type(p) not in (int,float) or not isfinite(p) or not 0<=p<=self.wire['points'][-1]['time_from_start_s']:
            raise ValueError('SOURCE_PROGRESS_OUTSIDE_ACCEPTED_CURVE')
        ns=owner['trajectory_progress_ns']
        if type(ns) is not int or p!=ns/1_000_000_000:
            raise ValueError('EXACT_CONTROLLER_REFERENCE_NANOSECONDS_REQUIRED')
        progress=F(ns,1_000_000_000)
        if stamp!=owner['state_stamp_s'] or stamp!=owner['now_s'] or owner['progress_source']!='ACCEPTED_CONTROLLER_REFERENCE':
            raise ValueError('CURRENT_SOURCE_TICK_PROGRESS_REQUIRED')
        if type(stamp) not in (int,float) or not isfinite(stamp) or stamp<owner['goal_start_stamp_s']:
            raise ValueError('FINITE_CURRENT_SOURCE_CLOCK_REQUIRED')
        if self._previous_progress is not None and (p<self._previous_progress[0] or stamp<self._previous_progress[1]):
            raise ValueError('SOURCE_PROGRESS_OR_CLOCK_REVERSED')
        if digest(read_model_bundle(self.request['model_bundle']['bundle_path']))!=self.accepted['model_digest']:
            raise ValueError('MODEL_SOURCE_CHANGED')
        q=owner['q_rad']
        if not isinstance(q,list) or len(q)!=6 or any(type(v) not in (int,float) or not isfinite(v) for v in q):
            raise ValueError('CURRENT_FINITE_OBSERVED_Q_REQUIRED')
        grip=owner['grip_rad'];attachment=owner['attachment_tcp_to_block']
        raw=np.asarray(attachment,float)
        if type(grip) not in (int,float) or not isfinite(grip) or raw.shape!=(4,4) or not np.isfinite(raw).all() or list(raw[3])!=[0.,0.,0.,1.]:
            raise ValueError('CURRENT_RAW_FINITE_GRIP_ATTACHMENT_REQUIRED')
        observed=self._boxes([[F(v)]+[F(0)]*5 for v in q],grip_rad=grip,attachment=attachment)
        self._previous_progress = (p,stamp)
        return p,ns,progress,stamp,q,grip,attachment,observed

    def remaining(self,owner):
        """Original mutable JSON diagnostic API; unchanged full hit-list consumer."""
        p,ns,progress,stamp,q,grip,attachment,observed=self._observe(owner)
        selected=[]; interval_boxes=[]
        for index,(start,end,c,boxes) in enumerate(self.intervals):
            if end<progress:continue
            if start<progress:boxes=self._boxes(c,(progress-start)/(end-start))
            selected.append(boxes)
            interval_boxes.append(dict(kind='ACCEPTED_REFERENCE_INTERVAL',interval_index=index,
                start_ns=int(max(start,progress)*1_000_000_000),end_ns=int(end*1_000_000_000),boxes=boxes))
        remaining_intervals=len(selected)
        selected.append(observed)
        interval_boxes.append(dict(kind='CURRENT_OBSERVED_POSE',stamp_s=stamp,boxes=observed))
        merged=[]
        for index,part in enumerate(self.parts):
            merged.append(dict(component=part['component'],part=part['name'],
                min_m=[min(row[index]['min_m'][i] for row in selected) for i in range(3)],
                max_m=[max(row[index]['max_m'][i] for row in selected) for i in range(3)]))
        self._previous_progress = (p,stamp)
        return dict(scope=FULL_SCOPE,
            goal_id=owner['goal_id'],goal_version=owner['goal_version'],
            source_trajectory_digest=self.accepted['active_wire_digest'],frame_id='base_link',
            stamp_s=stamp,conservative=True,boxes=merged,trajectory_progress_s=p,
            trajectory_progress_ns=ns,
            wire_end_ns=int(_wire_time(self.wire['points'][-1]['time_from_start_s'])*1_000_000_000),
            interval_boxes=deepcopy(interval_boxes),boxes_role='MERGED_BROAD_PHASE_ONLY',
            collision_inventory=deepcopy(self.collision_inventory),part_inventory=deepcopy(self.part_inventory),
            inventory_digest=self.inventory_digest,inventory_model_digest=self.request['model_digest'],
            remaining_intervals=remaining_intervals,accepted_binding_ref=deepcopy(self.accepted_ref),
            source_q_rad=deepcopy(q),current_observed_pose_included=True,
            nominal_geometry_binding=deepcopy(self.geometry_binding),
            current_geometry=dict(grip_rad=grip,attachment_tcp_to_block=deepcopy(attachment),
                                  holding_confirmed=True,contact_fingers=deepcopy(owner['contact_fingers'])),
            source_identity={k:deepcopy(owner[k]) for k in self.identity},
            model_mesh_sha256=self.mesh_pins,method='EXACT_RATIONAL_BERNSTEIN_80_BIT_DIRECTED_INTERVAL_FK',
            coverage='ALL_ORIGINAL_URDF_COLLISION_MESH_AABB_INTERIORS_AND_HELD_BODY_4_STUD_BOXES',
            conservatism_scope='ACCEPTED_REFERENCE_QUINTIC_AND_CURRENT_REPORTED_GEOMETRY_ONLY',
            tracking_error_included=False,live_source_verified=False,
            world_clear_allowed=False,execution_allowed=False)

    def remaining_numeric(self,owner):
        """Internal coherent view; use depth_risk for a small JSON first witness.

        Shares immutable full-curve data, not mutable diagnostic dictionaries.
        Original accepted-file/model checks and actual partial/current FK remain
        per observation. Native consumer verifies ALL array bytes and inventory.
        """
        if digest(self.geometry_binding)!=self._numeric_geometry_digest:
            raise ValueError('NUMERIC_ORIGINAL_GEOMETRY_BINDING_CHANGED')
        if digest(dict(model_digest=self.geometry_binding['model_digest'],collisions=self.collision_inventory,
                       parts=self.part_inventory))!=self.inventory_digest:
            raise ValueError('NUMERIC_ORIGINAL_INVENTORY_CHANGED')
        p,ns,progress,stamp,q,grip,attachment,observed=self._observe(owner)
        times=self._numeric_curve['interval_ns']
        first=int(np.searchsorted(times[:,1],ns,side='left'))
        partial=None
        if times[first,0]<ns:
            start,end=map(int,times[first]);coefficients=self._numeric_coefficients[first]
            partial=self._numeric_boxes(self._boxes(coefficients,F(ns-start,end-start)))
        current=self._numeric_boxes(observed)
        receipt=dict(scope=FULL_SCOPE,representation=NUMERIC,method='EXACT_RATIONAL_BERNSTEIN_80_BIT_DIRECTED_INTERVAL_FK',
            goal_id=owner['goal_id'],goal_version=owner['goal_version'],source_trajectory_digest=self.accepted['active_wire_digest'],
            frame_id='base_link',stamp_s=stamp,conservative=True,trajectory_progress_s=p,trajectory_progress_ns=ns,
            wire_end_ns=int(times[-1,1]),first_interval_index=first,remaining_intervals=len(times)-first,
            accepted_binding_ref=deepcopy(self.accepted_ref),source_q_rad=deepcopy(q),
            current_geometry=dict(grip_rad=grip,attachment_tcp_to_block=deepcopy(attachment),
                holding_confirmed=True,contact_fingers=deepcopy(owner['contact_fingers'])),
            source_identity={k:deepcopy(owner[k]) for k in self.identity},
            inventory_digest=self.inventory_digest,inventory_model_digest=self.geometry_binding['model_digest'],
            nominal_geometry_binding=deepcopy(self.geometry_binding),curve_digest=self._numeric_curve['curve_digest'],
            partial_bounds_sha256=None if partial is None else sha256(partial.tobytes()).hexdigest(),
            observed_bounds_sha256=sha256(current.tobytes()).hexdigest(),
            current_observed_pose_included=True,tracking_error_included=False,live_source_verified=False,
            world_clear_allowed=False,execution_allowed=False)
        return dict(receipt,numeric_curve=dict(self._numeric_curve),partial_bounds=partial,observed_bounds=current,
                    receipt=deepcopy(receipt),receipt_digest=digest(receipt))

    def _numeric_boxes(self,boxes):
        if tuple((b['part'],b['component']) for b in boxes)!=self._numeric_part_keys:
            raise ValueError('NUMERIC_ORIGINAL_PART_ORDER_CHANGED')
        return _readonly([[b['min_m'],b['max_m']] for b in boxes])

    def depth_risk(self,projected,owner,*,max_age_s,max_pose_skew_s,work_check=None):
        """Small first witness on existing worker; never a sender.

        Optional nonblocking work_check() returns {current_owner: NEW atomic
        snapshot, worker_cancelled: bool}. No default wall-time budget. Abort
        returns INCOMPLETE_UNKNOWN and never a positive intent or final no-hit.
        """
        from .native_boundary import remaining_volume_depth_risk
        return remaining_volume_depth_risk(projected,self.remaining_numeric(owner),owner,
            max_age_s=max_age_s,max_pose_skew_s=max_pose_skew_s,work_check=work_check)
