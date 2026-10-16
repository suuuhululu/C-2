"""Scoped SIM half-pixel evidence and a box-face numerical trial model.

This is an explicit float32 arithmetic hypothesis, not an RTX specification or
future sensor/pose error guarantee. Unknown mesh and point errors stay unknown.
"""
import json
import math
from itertools import permutations
from pathlib import Path

import numpy as np
from scipy.ndimage import minimum_filter, maximum_filter

from cumotion_geometry import object_boxes
from .geometry import _digest, _pin, _pose
from .interval_kernel import IntervalKernel

_CPP_INTERVAL=None


def configure_cpp_intervals(path,expected_sha256,*,sim_scope):
    global _CPP_INTERVAL
    # Construct fully before publishing; wrong scope/SHA never selects a kernel.
    kernel=IntervalKernel(path,expected_sha256,sim_scope=sim_scope)
    _CPP_INTERVAL=kernel
    return dict(kernel.binding)



def camera_scope(frame):
    return dict(intrinsics=frame['intrinsics'], calibration_id=frame['calibration_id'],
        optical_frame_id=frame['optical_frame_id'], depth_unit=frame['depth_unit'],
        depth_scale_m=frame['depth_scale_m'], depth_representation=frame['depth_representation'],
        camera_params={k:v for k,v in frame['camera_params'].items() if k!='cameraViewTransform'})


def load_qualification(frame, known, error_model):
    ref=error_model.get('qualification_ref')
    if ref is None:
        return None
    _pin(ref);q=json.loads(Path(ref['path']).read_text())
    if (error_model['status']!='SIM_SCOPED_NUMERICAL_MODEL' or q['schema']!='depth-scoped-qualification/1.0' or
            q['scope']!='SIM_TEST_REPORT_ONLY' or q['offset_uv']!=[.5,.5] or
            q['numerical_model']!='FLOAT32_AFFINE_DOT_ROUNDING_TRIAL' or q['same_face_footprint_px']!=5):
        raise ValueError('EXPLICIT_SCOPED_SIM_QUALIFICATION_REQUIRED')
    if (frame['source_kind']!='SIM_DEPTH' or frame['depth_representation']!='IMAGE_PLANE_Z' or
            frame['session_id'] not in q['capture_sessions'] or camera_scope(frame)!=q['camera_scope'] or
            known['metadata']['model_manifest_sha256']!=q['model_manifest_sha256']):
        raise ValueError('QUALIFICATION_CAMERA_OR_MODEL_SCOPE_MISMATCH')
    for source in q['source_refs']:
        _pin(source)
    receipt=next((r for r in frame['source_refs'] if Path(r['path']).name=='receipt.json'),None)
    if receipt is None:
        raise ValueError('QUALIFICATION_CAMERA_RENDER_RECEIPT_REQUIRED')
    _pin(receipt)
    if json.loads(Path(receipt['path']).read_text())['camera_path']!=q['camera_path']:
        raise ValueError('QUALIFICATION_CAMERA_RENDER_PATH_MISMATCH')
    return dict(q, input_ref=ref, digest=_digest(q))


def known_boxes(known, frame):
    meta=known['metadata'];boxes=[]
    for obj in meta['static_objects']:
        # MappingProxyType tuples are immutable, not inputs to the JSON parser.
        obj=json.loads(json.dumps(dict(obj),default=lambda x:dict(x) if hasattr(x,'keys') else list(x)))
        for i,(size,t) in enumerate(object_boxes(obj,_pose(obj['pose']),0.)):
            boxes.append((0,obj['id']+'/'+str(i),size,np.asarray(meta['T_world_base'])@t))
    held=meta['held_definition']['geometry']
    held=json.loads(json.dumps(dict(held),default=lambda x:dict(x) if hasattr(x,'keys') else list(x)))
    for i,(size,t) in enumerate(object_boxes(held,np.eye(4),0.)):
        boxes.append((2,'held/'+str(i),size,np.asarray(frame['T_world_base'])@np.asarray(frame['T_base_tool'])@np.asarray(frame['attachment_tcp_to_block'])@t))
    return boxes


def _half_ulp32(x):
    x=np.abs(np.asarray(x,dtype=np.float32))
    return (np.nextafter(x,np.float32(np.inf)).astype(float)-x.astype(float))/2


def face_intervals(known, frame, ray_intrinsics, depth, qualification):
    """Support uses expected geometry only, including the complete robot layer.

    Trial assumptions: round each affine input to float32, one four-term dot
    (4 products+3 sums), one three-term dot (3+2), six ray-grid operations.
    Intervals propagate these declared operations; no observed depth/residual
    enters the mask or expected interval. Internal RTX operation order remains
    unverified. The independent held-out report must accompany this input.
    """
    h,w=depth.shape[1:];v,u=np.indices((h,w));k=ray_intrinsics
    rays=np.stack([(u-k['cx'])/k['fx'],(v-k['cy'])/k['fy'],np.ones((h,w))],axis=-1)
    eps=np.finfo(np.float32).eps/2
    gamma=lambda n:n*eps/(1-n*eps)
    abs_rays=np.abs(rays)
    ray_error=gamma(6)*(abs_rays+np.array([1.,1.,0.]))
    ray_error[:,:,2]=0
    camera=np.asarray(frame['T_world_camera'])@np.diag([1.,-1.,-1.,1.])
    nearest=np.full((h,w),np.inf);face=np.full((h,w),-1,int);bound=np.full((h,w),np.nan);labels=[]
    near,far=frame['camera_params']['cameraNearFar']
    owner=depth.argmin(axis=0)
    ray_range=(rays.min(axis=(0,1)),rays.max(axis=(0,1)))
    component_rows={component:np.flatnonzero(np.any((owner==component)&np.isfinite(depth[component]),axis=1)) for component in (0,2)}
    for bi,(component,label,size,t) in enumerate(known_boxes(known,frame)):
        inverse=np.linalg.inv(t);local=inverse@camera
        labels.append(dict(component=component,part=label))
        if not _box_intersection_possible(size,local,ray_range,near,far):
            continue
        rows=component_rows[component]
        if not len(rows):continue
        # Excluded rows can never satisfy owner + finite-depth agreement.
        # Preserve all 848 columns and each original matrix multiply shape.
        row_rays=rays[rows];row_abs=abs_rays[rows];row_error=ray_error[rows]
        # Rounding of the operands plus the affine dot's seven operations.
        affine_error=(_half_ulp32(inverse)@np.abs(camera)+np.abs(inverse)@_half_ulp32(camera)+
                      _half_ulp32(inverse)@_half_ulp32(camera)+gamma(7)*(np.abs(inverse)@np.abs(camera)))
        origin=local[:3,3];direction=row_rays@local[:3,:3].T
        direction_error=(row_abs@affine_error[:3,:3].T+row_error@np.abs(local[:3,:3]).T+
                         row_error@affine_error[:3,:3].T+gamma(5)*(row_abs@np.abs(local[:3,:3]).T))
        if _CPP_INTERVAL is not None:
            _CPP_INTERVAL.finish(size,origin,direction,direction_error,
                _half_ulp32(size/2)+affine_error[:3,3],depth[component,rows],owner[rows],rows,
                component,bi,near,far,nearest,face,bound)
            continue
        with np.errstate(divide='ignore',invalid='ignore'):
            z,exit,axis,den,de=_slab_intersection(size,origin,direction,direction_error)
            ne=(_half_ulp32(size/2)+affine_error[:3,3])[axis]
            err=(ne+np.abs(z)*de)/(np.abs(den)-de)
        visible=(exit>=z)&(z>=near)&(z<=far)&(owner[rows]==component)&(np.abs(den)>de)&np.isfinite(err)
        # Analytical boxes must agree with the full triangle renderer up to
        # binary64 arithmetic; this is a model-consistency test, not raw fitting.
        tolerance=128*np.finfo(float).eps*np.maximum(1.,np.abs(z))
        visible &= np.abs(z-depth[component,rows])<=tolerance
        take=visible&(z<nearest[rows]);yy,xx=np.nonzero(take);global_y=rows[yy]
        nearest[global_y,xx]=z[take];bound[global_y,xx]=err[take]+tolerance[take]
        face[global_y,xx]=(bi*6+axis*2+(den<0))[take]
    support=(face>=0)&(minimum_filter(face,5,mode='constant',cval=-2)==maximum_filter(face,5,mode='constant',cval=-3))
    bound[~support]=np.nan
    return dict(expected_error_m=bound,support_mask=support,face_id=face,face_labels=labels,
                qualification_digest=qualification['digest'],qualification_ref=qualification['input_ref'])


def _slab_intersection(size,origin,direction,direction_error):
    """Same full-grid slab arithmetic, without a 2 x H x W x 3 stack.

    Keep the original plane divisions, x/y/z reduction order and first-axis
    argmax tie rule. No ROI, geometry pruning or changed numerical tolerance.
    np.maximum/minimum retain NaN propagation just as ndarray max/min do.
    """
    low=-size/2-origin;high=size/2-origin
    entries=[];exits=[]
    for i in range(3):
        a=low[i]/direction[:,:,i];b=high[i]/direction[:,:,i]
        entries.append(np.minimum(a,b));exits.append(np.maximum(a,b))
    z=np.maximum(np.maximum(entries[0],entries[1]),entries[2])
    exit=np.minimum(np.minimum(exits[0],exits[1]),exits[2])
    # np.argmax chooses the first NaN, otherwise the first maximum.
    axis=np.zeros(z.shape,dtype=np.intp);best=entries[0]
    for i in (1,2):
        take=~np.isnan(best)&((entries[i]>best)|np.isnan(entries[i]))
        axis[take]=i;best=np.where(take,entries[i],best)
    # Gather the already selected axis directly from the existing H x W x 3
    # arrays. No arithmetic, ties, NaNs or signed-zero values are changed.
    den=np.take_along_axis(direction,axis[:,:,None],axis=2)[:,:,0]
    de=np.take_along_axis(direction_error,axis[:,:,None],axis=2)[:,:,0]
    return z,exit,axis,den,de


def _box_intersection_possible(size,local,ray_range,near,far):
    """Conservative whole-box rejection for the *computed* full-grid slabs.

    Bound every binary64 direction dot and subsequent slab division outward
    with nextafter, including all three-term summation orders. Fused products
    also lie in these product/sum enclosures. This is only a no-intersection
    proof; it does not change the numerical error model or skip image regions.
    If a denominator crosses zero or any operand/operation is nonfinite, retain
    that axis unbounded (or retain the box). Strict separation is required.
    The original near/far inclusive and entry/exit ordering remain unchanged.
    """
    if not np.isfinite(local).all() or not np.isfinite(size).all():
        return True
    down=lambda x:math.nextafter(x,-math.inf)
    up=lambda x:math.nextafter(x,math.inf)
    def dot_interval(coeff):
        terms=[]
        for i,c in enumerate(coeff):
            a=float(ray_range[0][i])*float(c);b=float(ray_range[1][i])*float(c)
            if not math.isfinite(a) or not math.isfinite(b):return None
            terms.append((down(min(a,b)),up(max(a,b))))
        lows=[];highs=[]
        for order in permutations(range(3)):
            x,y,z=(terms[i] for i in order)
            lo=down(down(x[0]+y[0])+z[0]);hi=up(up(x[1]+y[1])+z[1])
            if not math.isfinite(lo) or not math.isfinite(hi):return None
            lows.append(lo);highs.append(hi)
        return min(lows),max(highs)
    def quotient(n,den):
        if den[0]<=0<=den[1]:return -math.inf,math.inf
        a=float(n)/den[0];b=float(n)/den[1]
        if not math.isfinite(a) or not math.isfinite(b):return -math.inf,math.inf
        return down(min(a,b)),up(max(a,b))
    low=-size/2-local[:3,3];high=size/2-local[:3,3]
    if not np.isfinite(low).all() or not np.isfinite(high).all():return True
    entries=[];exits=[];directions=[]
    for i in range(3):
        den=dot_interval(local[i,:3])
        if den is None:return True
        directions.append(den)
        a=quotient(low[i],den);b=quotient(high[i],den)
        entries.append((min(a[0],b[0]),min(a[1],b[1])))
        exits.append((max(a[0],b[0]),max(a[1],b[1])))
    z_low=max(x[0] for x in entries);z_high=max(x[1] for x in entries)
    exit_high=min(x[1] for x in exits)
    if exit_high<z_low or z_high<near or z_low>far:return False
    # Any computed visible z is in this finite common range. A correctly
    # rounded division endpoint can differ from its exact quotient by <1 ULP;
    # expanding by one adjacent float encloses every possible exact endpoint
    # whose rounded slab interval contains that z. Thus an axis must overlap
    # [low,high] somewhere within this expanded z x direction rectangle.
    t_low=down(max(near,z_low));t_high=up(min(far,exit_high))
    if not math.isfinite(t_low) or not math.isfinite(t_high):return True
    for i,den in enumerate(directions):
        products=[t*d for t in (t_low,t_high) for d in den]
        if not all(math.isfinite(x) for x in products):return True
        if low[i]>up(max(products)) or high[i]<down(min(products)):return False
    return True
