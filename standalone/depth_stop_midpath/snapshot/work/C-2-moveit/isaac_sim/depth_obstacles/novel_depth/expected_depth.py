"""CPU two-sided opaque visual-surface z-buffer in the actual optical frame."""
from copy import deepcopy
from fractions import Fraction
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np

from prepare_cumotion_model import urdf_transforms
from .geometry import _digest, _pin, _rigid, _transform
from .qualification import load_qualification, face_intervals

NATIVE_PROOF_METHODS=frozenset({
    'INDEPENDENT_NATIVE_RATIONAL_RENDER_REQUEST_AND_PHYSICS_COUNTER_CAMERA_VIEW_WITH_DELAYED_ORIGINAL_ROS_MESSAGE',
    'INDEPENDENT_RENDER_BUFFER_REQUEST_TAG_PHYSICS_Q_TF_VIEW'})


def _render_tag_review(f,event,writer,paths):
    tag=writer.get('render_buffer_request_tag');authored=event.get('render_buffer_tag_authored')
    if not tag or not authored or 'receipt.json' not in paths:
        raise ValueError('SOURCE_CLOCK_RENDER_BUFFER_TAG_REQUIRED')
    _pin(paths['receipt.json']);receipt=json.loads(Path(paths['receipt.json']['path']).read_text())
    values=tag.get('values');request=event['render_request_id']
    if (type(request) is not int or request<=0 or not isinstance(values,list) or len(values)!=1 or
            type(values[0]) is not int or values!=[request] or type(authored.get('value')) is not int or authored.get('value')!=request or
            tag.get('attribute')!='seeun:renderRequestId' or authored.get('attribute')!=tag['attribute'] or
            tag.get('prim')!=receipt['camera_path'] or authored.get('prim')!=tag['prim'] or
            tag.get('origin')!='ATTRIBUTE_ANNOTATOR_SAME_WRITER_REFERENCE_TIME_RENDER_RINGBUFFER'):
        raise ValueError('SOURCE_CLOCK_RENDER_BUFFER_TAG_MISMATCH')
    try:dtype=np.dtype(tag['dtype'])
    except (TypeError,ValueError) as exc:raise ValueError('SOURCE_CLOCK_RENDER_BUFFER_TAG_DTYPE') from exc
    if dtype.kind!='i' or not np.iinfo(dtype).min<=request<=np.iinfo(dtype).max:
        raise ValueError('SOURCE_CLOCK_RENDER_BUFFER_TAG_DTYPE')
    if (event.get('state_readout_phase')!='AFTER_RENDER_FABRIC_SYNCHRONIZATION_NO_PHYSICS_ADVANCE' or
            event.get('q_unchanged_during_render') is not True or event['before_render_readout']['q_rad']!=event['q_rad'] or
            writer['params']!=f['camera_params'] or writer['source_stamp_s']!=f['source_stamp_s']):
        raise ValueError('SOURCE_CLOCK_RENDER_BUFFER_STATE_OR_PARAMS_MISMATCH')
    life=writer.get('writer_render_lifecycle')
    if (not life or life['reference_time']!=f['reference_time'] or life['renderer_frame_id']!=f['renderer_frame_id'] or
            life['writer_entered_wall_monotonic_s']!=writer['writer_callback_entered_wall_monotonic_s']):
        raise ValueError('SOURCE_CLOCK_RENDER_BUFFER_WRITER_RECEIPT_MISMATCH')
    # The callback may run during NEXT render. Its current request/state is
    # deliberately preserved as receipt metadata, never substituted for source.
    return dict(buffer_tag=deepcopy(tag),writer_callback_lifecycle=deepcopy(life),receipt_ref=deepcopy(paths['receipt.json']))


def _quantized_ns(value, rule):
    """An explicit representation rule, never a sensor timing tolerance."""
    exact = value if isinstance(value, Fraction) else Fraction.from_float(value)
    if rule == 'FLOOR_EXACT_NS':
        return math.floor(exact * 10**9)
    if rule == 'ROUND_NEAREST_EVEN_NS':
        return round(exact * 10**9)
    if rule == 'FLOAT64_MULTIPLY_TRUNCATE_NS':
        return int(float(exact) * 10**9)
    raise ValueError('SOURCE_CLOCK_QUANTIZATION_RULE_UNSUPPORTED')


def _native_event_review(f):
    """Review the MI producer's original records, not its admission boolean."""
    a=f['source_association'];paths={Path(r['path']).name:r for r in a['source_refs']}
    records={}
    for name in ('render_event.json','source_state.json','writer_event.json','clock_observation.json'):
        if name not in paths:
            raise ValueError('SOURCE_CLOCK_NATIVE_EVENT_REF_REQUIRED:'+name)
        _pin(paths[name]);records[name]=json.loads(Path(paths[name]['path']).read_text())
    event=records['render_event.json'];writer=records['writer_event.json'];state=records['source_state.json']
    if event is None or state['scope']!='ACTUAL_RENDER_REQUEST_EVENT_NOT_NEAREST_TIMESTAMP' or state['source']!=event:
        raise ValueError('SOURCE_CLOCK_NATIVE_STATE_EVENT_MISMATCH')
    before,after=event['before_render'],event['after_render'];tick=a['physics_step_index']
    if (before['native_physics_step_index']!=tick or after['native_physics_step_index']!=tick or
            event['physics_event'] is None or event['physics_event']['native_physics_step_index']!=tick):
        raise ValueError('SOURCE_CLOCK_NATIVE_PHYSICS_STEP_MISMATCH')
    n,d=f['reference_time'];rn,rd=after['native_current_reference_time']
    if (rd<=0 or writer['reference_time']!=[n,d] or writer['renderer_frame_id']!=f['renderer_frame_id'] or
            writer['frame_seq']!=f['frame_seq']):
        raise ValueError('SOURCE_CLOCK_NATIVE_RENDER_REFERENCE_MISMATCH')
    for key in ('q_rad','grip_rad','attachment_tcp_to_block','T_world_base','T_world_camera','T_base_tool'):
        if event[key]!=f[key]:
            raise ValueError('SOURCE_CLOCK_NATIVE_STATE_VALUE_MISMATCH')
    mapping=writer['writer_native_time_mapping_s'];native=after['native_simulation_time_s']
    tagged=a.get('proof_method')=='INDEPENDENT_RENDER_BUFFER_REQUEST_TAG_PHYSICS_Q_TF_VIEW'
    tag_review=_render_tag_review(f,event,writer,paths) if tagged else None
    if (not isinstance(mapping,(int,float)) or not np.isfinite(mapping) or not isinstance(native,(int,float)) or not np.isfinite(native) or
            native!=before['native_simulation_time_s'] or native!=event['physics_event']['native_simulation_time_s'] or
            (not tagged and mapping!=native)):
        raise ValueError('SOURCE_CLOCK_NATIVE_REFERENCE_TIME_MAPPING_MISMATCH')
    if event['publisher_input_time']!=native or event['graph_simulation_time']!=native:
        raise ValueError('SOURCE_CLOCK_NATIVE_GRAPH_INPUT_MAPPING_MISMATCH')
    clocks=records['clock_observation.json'];observed=clocks['matching_observed_clock']
    if clocks['clock_value_synthesized'] is not False:
        raise ValueError('SOURCE_CLOCK_NATIVE_SYNTHESIZED_VALUE_FORBIDDEN')
    if observed is None:
        if a['source_ros_clock_ns'] is not None:
            raise ValueError('SOURCE_CLOCK_NATIVE_UNOBSERVED_NS_NOT_NULL')
    elif observed['clock_ns']!=a['source_ros_clock_ns']:
        raise ValueError('SOURCE_CLOCK_NATIVE_OBSERVED_PUBLICATION_MISMATCH')
    return dict(method='INDEPENDENT_NATIVE_RENDER_PHYSICS_EVENTS',native_physics_step_index=tick,
        render_request_id=event['render_request_id'],native_reference_time=[rn,rd],
        writer_native_time_mapping_s=mapping,world_time_s=before['world_time_s'],
        event_native_simulation_time_s=native,render_buffer_tag_review=tag_review,
        writer_mapping_minus_event_native_s=mapping-native,
        publisher_input_time=event['publisher_input_time'],graph_simulation_time=event['graph_simulation_time'],
        native_reference_difference_ns=float(Fraction(rn,rd)*10**9-Fraction(n,d)*10**9),
        matching_original_clock=deepcopy(observed),latest_original_clock=deepcopy(clocks['latest_delayed_clock']),
        source_refs=[deepcopy(paths[k]) for k in records])


def _clock_review(f):
    a = f['source_association']
    if f['source_kind'] == 'FIXTURE':
        return dict(status='FIXTURE', raw_reference_time=f['reference_time'])
    n, d = f['reference_time']
    if type(n) is not int or type(d) is not int or n < 0 or d <= 0 or f['source_stamp_s'] != n/d:
        raise ValueError('SOURCE_REFERENCE_RATIONAL_INVALID')
    reference = Fraction(n,d)
    published = a.get('source_ros_clock_ns')
    result = dict(raw_reference_time=[n,d], source_published_clock_ns=published,
                  delayed_latest_callback_ns=a.get('latest_received_ros_clock_ns'))
    if a.get('proof_method') in NATIVE_PROOF_METHODS:
        event=_native_event_review(f)
        return dict(result,status='INDEPENDENT_NATIVE_EVENT_SOURCE',native_event_review=event,
                    ROS_delivery_verified=event['matching_original_clock'] is not None,
                    original_producer_same_tick_verified=a['same_tick_verified'])
    if type(published) is not int or published < 0:
        raise ValueError('SOURCE_CLOCK_PUBLICATION_INTEGER_REQUIRED')
    ref = a.get('clock_mapping_ref')
    if ref is None:
        # Preserve existing exact-source records. A delayed subscription clock
        # or fractional-ns time needs independent publication/event evidence.
        if (reference*10**9).denominator != 1 or published != reference*10**9:
            raise ValueError('SOURCE_CLOCK_MAPPING_REQUIRED')
        return dict(result,status='LEGACY_EXACT_SOURCE_NS')
    _pin(ref)
    mapping = json.loads(Path(ref['path']).read_text())
    if mapping['mapping_kind'] != 'RENDER_EVENT_PHYSICS_CLOCK_PUBLICATION':
        raise ValueError('SOURCE_CLOCK_MAPPING_KIND_UNSUPPORTED')
    for key in ('session_id','clock_epoch','reference_time','renderer_frame_id'):
        if mapping[key] != f[key]:
            raise ValueError('SOURCE_CLOCK_MAPPING_FRAME_MISMATCH')
    tick = a['physics_step_index']
    records = {}
    for key in ('writer_event_ref','physics_state_ref','clock_publication_ref'):
        _pin(mapping[key]); records[key] = json.loads(Path(mapping[key]['path']).read_text())
        if type(records[key]['physics_step_index']) is not int or records[key]['physics_step_index'] != tick:
            raise ValueError('SOURCE_CLOCK_EVENT_PHYSICS_STEP_MISMATCH')
        if any(records[key][name] != f[name] for name in ('session_id','clock_epoch')):
            raise ValueError('SOURCE_CLOCK_EVENT_SESSION_MISMATCH')
    writer, state, publication = (records[k] for k in ('writer_event_ref','physics_state_ref','clock_publication_ref'))
    if writer['reference_time'] != [n,d] or writer['renderer_frame_id'] != f['renderer_frame_id']:
        raise ValueError('SOURCE_CLOCK_WRITER_REFERENCE_MISMATCH')
    for key in ('q_rad','grip_rad','attachment_tcp_to_block','T_world_base','T_world_camera','T_base_tool'):
        if state[key] != f[key] or writer['source_state'][key] != state[key]:
            raise ValueError('SOURCE_CLOCK_INDEPENDENT_STATE_MISMATCH')
    if publication['input_time_s'] != state['source_stamp_s']:
        raise ValueError('SOURCE_CLOCK_PUBLICATION_STATE_TIME_MISMATCH')
    actual_ns = publication['published_clock_ns']
    if (type(actual_ns) is not int or actual_ns != published or
            _quantized_ns(publication['input_time_s'],publication['quantization_rule']) != actual_ns):
        raise ValueError('SOURCE_CLOCK_PUBLICATION_QUANTIZATION_MISMATCH')
    _pin(publication['publisher_source_ref'])
    return dict(result,status='INDEPENDENT_EVENT_CLOCK_MAPPING',clock_mapping_ref=deepcopy(ref),
        publication_input_time_s=publication['input_time_s'],quantization_rule=publication['quantization_rule'],
        reference_to_publication_delta_ns=float(Fraction(actual_ns)-reference*10**9))


def _association_status(f, *, clock_review=None):
    a = f['source_association']
    if f['source_kind'] == 'FIXTURE' and a['scope'] == 'FIXTURE':
        return 'FIXTURE'
    native_proof=a.get('proof_method') in NATIVE_PROOF_METHODS
    if f['source_kind'] != 'SIM_DEPTH' or (a.get('same_tick_verified') is not True and not native_proof):
        return 'INPUT_UNASSOCIATED'
    if clock_review is None:
        _clock_review(f)
    keys = ('session_id', 'clock_epoch', 'frame_seq', 'q_rad', 'grip_rad', 'attachment_tcp_to_block',
            'T_base_tool', 'T_tool_camera_optical', 'T_world_base', 'T_world_camera', 'reference_time', 'depth_array_sha256', 'renderer_frame_id')
    if any(a[k] != f[k] for k in keys):
        raise ValueError('SOURCE_STATE_ASSOCIATION_MISMATCH')
    if type(f['renderer_frame_id']) is not int or f['renderer_frame_id'] < 0:
        raise ValueError('RECORDED_RENDERER_FRAME_ID_REQUIRED')
    tick = a['physics_step_index']
    if type(tick) is not int or tick < 0 or any(a[k] != tick for k in
            ('state_physics_step_index', 'tf_physics_step_index', 'image_physics_step_index')):
        raise ValueError('SOURCE_PHYSICS_STEP_MISMATCH')
    if not a['source_refs']:
        raise ValueError('SOURCE_ASSOCIATION_REFS_REQUIRED')
    for ref in a['source_refs']:
        _pin(ref)
    view = np.asarray(f['camera_params']['cameraViewTransform'], float).reshape(4, 4).T
    world_camera = _rigid(f['T_world_camera'])
    arithmetic = 128*np.finfo(float).eps*max(1., abs(world_camera).max())
    if not np.allclose(np.linalg.inv(view), world_camera, rtol=0, atol=arithmetic):
        raise ValueError('RENDERER_SOURCE_CAMERA_MATRIX_MISMATCH')
    return a['scope']


def _camera(f, offset_uv=None):
    k = f['intrinsics']; p = f['camera_params']; convention = f['pixel_convention']
    h, w = k['height'], k['width']
    if (type(h) is not int or type(w) is not int or min(h, w) <= 0 or k['model'] != 'none' or
            p['renderProductResolution'] != [w, h] or p['cameraModel'] != 'pinhole' or p['metersPerSceneUnit'] != 1):
        raise ValueError('MATCHING_METRIC_PINHOLE_REQUIRED')
    projection = np.asarray(p['cameraProjection'], float).reshape(4, 4)
    allowed = {(0, 0), (1, 1), (2, 0), (2, 1), (2, 2), (2, 3), (3, 2)}
    if (not np.isfinite(projection).all() or min(projection[0, 0], projection[1, 1]) <= 0 or
            projection[2, 3] != -1 or any(projection[i, j] != 0 for i in range(4) for j in range(4) if (i, j) not in allowed)):
        raise ValueError('UNSUPPORTED_RENDERER_PROJECTION')
    offset = np.asarray(convention['offset_uv'] if offset_uv is None else offset_uv, float)
    if offset.shape != (2,) or not np.isfinite(offset).all():
        raise ValueError('EXPLICIT_PIXEL_OFFSET_REQUIRED')
    # Invert the recorded USD row-vector projection; do not also shift K.
    fx, fy = projection[0, 0] * w / 2, projection[1, 1] * h / 2
    cx, cy = (1 - projection[2, 0]) * w / 2 - offset[0], (1 + projection[2, 1]) * h / 2 - offset[1]
    near, far = map(float, p['cameraNearFar'])
    if not np.isfinite([near, far]).all() or not 0 < near < far:
        raise ValueError('EXPLICIT_OPTICAL_Z_CLIPS_REQUIRED')
    return h, w, (fx, fy, cx, cy), near, far


def _clip(triangles, near, far):
    inside = (triangles[:, :, 2] >= near) & (triangles[:, :, 2] <= far)
    result = [triangles[inside.all(axis=1)]]
    crossing = triangles[~inside.all(axis=1) & (triangles[:, :, 2].max(axis=1) >= near) & (triangles[:, :, 2].min(axis=1) <= far)]
    for triangle in crossing:
        polygon = list(triangle)
        for bound, sign in ((near, 1), (far, -1)):
            clipped = []
            for previous, current in zip(polygon[-1:] + polygon[:-1], polygon):
                pin, cin = sign * (previous[2] - bound) >= 0, sign * (current[2] - bound) >= 0
                if pin != cin:
                    clipped.append(previous + (current - previous) * ((bound - previous[2]) / (current[2] - previous[2])))
                if cin:
                    clipped.append(current)
            polygon = clipped
            if not polygon:
                break
        if len(polygon) >= 3:
            result.append(np.array([[polygon[0], polygon[i], polygon[i+1]] for i in range(1, len(polygon)-1)]))
    return np.concatenate(result)


_CPP_RASTER = None

def configure_cpp_raster(path,expected_sha256,*,sim_scope):
    from .raster_kernel import RasterKernel
    global _CPP_RASTER
    _CPP_RASTER=RasterKernel(path,expected_sha256,sim_scope=sim_scope)
    return dict(_CPP_RASTER.binding)


def _raster(triangles, h, w, camera, near, far):
    zbuffer = np.full(h * w, np.inf)
    triangles = _clip(triangles, near, far)
    fx, fy, cx, cy = camera
    uv = triangles[:, :, :2] / triangles[:, :, 2, None] * [fx, fy] + [cx, cy]
    low = np.maximum(np.ceil(uv.min(axis=1)), [0, 0])
    high = np.minimum(np.floor(uv.max(axis=1)), [w-1, h-1])
    keep = np.all(low <= high, axis=1)
    uv, triangles, low, high = uv[keep], triangles[keep], low[keep].astype(int), high[keep].astype(int)
    if _CPP_RASTER is not None:
        _CPP_RASTER.raster(uv,triangles,low,high,zbuffer,h,w)
        return zbuffer.reshape(h,w)
    # Batch small projected bounding boxes. This avoids rays x all mesh triangles.
    areas = np.prod(high - low + 1, axis=1); start = 0
    while start < len(uv):
        end = min(len(uv), start + max(1, int(np.searchsorted(np.cumsum(areas[start:start+512]), 262144, side='right'))))
        t, lo, hi = uv[start:end], low[start:end], high[start:end]
        count = areas[start:end]; indices = np.repeat(np.arange(len(t)), count)
        offset = np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
        width = (hi - lo + 1)[:, 0]
        x, y = lo[indices, 0] + offset % width[indices], lo[indices, 1] + offset // width[indices]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        det = (b[:, 1]-c[:, 1])*(a[:, 0]-c[:, 0]) + (c[:, 0]-b[:, 0])*(a[:, 1]-c[:, 1])
        nondegenerate = abs(det[indices]) > np.finfo(float).eps
        ix = indices[nondegenerate]; x, y = x[nondegenerate], y[nondegenerate]
        wa = ((b[ix, 1]-c[ix, 1])*(x-c[ix, 0]) + (c[ix, 0]-b[ix, 0])*(y-c[ix, 1])) / det[ix]
        wb = ((c[ix, 1]-a[ix, 1])*(x-c[ix, 0]) + (a[ix, 0]-c[ix, 0])*(y-c[ix, 1])) / det[ix]
        wc = 1-wa-wb
        inside = (wa >= -1e-12) & (wb >= -1e-12) & (wc >= -1e-12)
        inverse_z = 1 / triangles[start:end, :, 2]
        z = 1 / (wa*inverse_z[ix, 0] + wb*inverse_z[ix, 1] + wc*inverse_z[ix, 2])
        np.minimum.at(zbuffer, (y*w+x)[inside], z[inside])
        start = end
    return zbuffer.reshape(h, w)


def render_expected_depth(known_geometry, frame_state, error_model):
    """Return static/self/held optical-Z arrays plus unresolved-source/edge flags.

    frame_state is the existing flat wrist frame plus grip_rad, raw attachment,
    T_world_base, camera_params, pixel_convention and source_association. Numeric
    matching errors are accepted only as explicit FIXTURE_PARAMETER or measured
    baseline data with source_refs. UNMEASURED remains unknown, never zero.
    """
    started = time.perf_counter(); f = deepcopy(frame_state); known = known_geometry
    if (f['session_id'] != known['metadata']['session_id'] or f['clock_epoch'] != known['metadata']['clock_epoch'] or
            f['clock_basis'] != 'SIM_TIME' or f['source_stamp_s'] < known['metadata']['freeze_source_time']):
        raise ValueError('FRAME_MAP_IDENTITY_OR_TIME_MISMATCH')
    if any(k in f for k in ('semantic_ids', 'semantic_info', 'idToLabels', 'self_mask', 'held_mask', 'obstacle_mask', 'actor_pose', 'GT')):
        raise ValueError('SEMANTIC_OR_ACTOR_INPUT_FORBIDDEN')
    clock_review = _clock_review(f)
    q = np.asarray(f['q_rad'], float)
    if q.shape != (6,) or not np.isfinite(q).all() or not np.isfinite(f['grip_rad']):
        raise ValueError('FINITE_ACTUAL_Q_GRIP_REQUIRED')
    association = _association_status(f,clock_review=clock_review)
    qualification=load_qualification(f,known,error_model)
    if error_model['status']=='SIM_SCOPED_NUMERICAL_MODEL' and qualification is None:
        raise ValueError('EXPLICIT_SCOPED_SIM_QUALIFICATION_REQUIRED')
    h, w, camera, near, far = _camera(f,None if qualification is None else qualification['offset_uv'])
    world_base = _rigid(f['T_world_base']); tool = _rigid(f['T_base_tool'])
    nominal_camera = tool @ _rigid(f['T_tool_camera_optical'])
    base_camera = (np.linalg.inv(world_base) @ _rigid(f['T_world_camera']) @ np.diag([1.,-1.,-1.,1.])
                   if f['source_kind'] == 'SIM_DEPTH' else nominal_camera)
    camera_base = np.linalg.inv(base_camera)
    attachment = _rigid(f['attachment_tcp_to_block'])
    frames = urdf_transforms(ET.fromstring(known['robot_description']), q.tolist(), f['grip_rad'])
    delta = np.linalg.inv(frames['GripperDA_v4_tcp']) @ tool
    fk_error = dict(translation_m=float(np.linalg.norm(delta[:3,3])),
                    rotation_rad=float(np.arccos(np.clip((np.trace(delta[:3,:3])-1)/2, -1, 1))))
    own = np.concatenate([_transform(v['triangles'], frames[v['link']]) for v in known['robot_visuals']])
    layers = [
        _transform(known['static_world_triangles'], np.linalg.inv(world_base)), own,
        _transform(known['held_block_triangles'], tool @ attachment)]
    raster_started = time.perf_counter()
    depth = np.stack([_raster(_transform(t, camera_base), h, w, camera, near, far) for t in layers])
    raster_finished = time.perf_counter()
    nearest = depth.min(axis=0); valid = np.isfinite(nearest)
    owner = depth.argmin(axis=0).astype(np.int8); owner[~valid] = -1
    edge = np.zeros((h, w), bool); edge[[0, -1], :] = True; edge[:, [0, -1]] = True
    for axis in (0, 1):
        left, right = [slice(None)]*2, [slice(None)]*2
        left[axis], right[axis] = slice(None, -1), slice(1, None)
        left, right = tuple(left), tuple(right)
        changed = owner[left] != owner[right]
        jump = error_model.get('edge_jump_m')
        if jump is not None:
            if not np.isfinite(jump) or jump <= 0:
                raise ValueError('EXPLICIT_POSITIVE_EDGE_JUMP_REQUIRED')
            with np.errstate(invalid='ignore'):
                changed |= abs(nearest[left]-nearest[right]) > jump
        edge[left] |= changed; edge[right] |= changed
    if error_model['status'] not in ('FIXTURE_PARAMETER', 'MEASURED_BASELINE', 'UNMEASURED', 'SIM_SCOPED_NUMERICAL_MODEL'):
        raise ValueError('EXPLICIT_ERROR_MODEL_STATUS_REQUIRED')
    calibrated = error_model['status'] in ('FIXTURE_PARAMETER', 'MEASURED_BASELINE')
    if calibrated and (error_model['status'] == 'FIXTURE_PARAMETER' and f['source_kind'] != 'FIXTURE' or not error_model['source_refs']):
        raise ValueError('ERROR_MODEL_PROVENANCE_REQUIRED')
    if error_model['status'] == 'MEASURED_BASELINE':
        for ref in error_model['source_refs']:
            _pin(ref)
    error = error_model.get('expected_error_m') if calibrated else None
    if error is not None and (not np.isfinite(error) or error < 0):
        raise ValueError('FINITE_NONNEGATIVE_EXPECTED_ERROR_REQUIRED')
    ray_intrinsics=dict(width=w,height=h,fx=camera[0],fy=camera[1],cx=camera[2],cy=camera[3])
    scoped={}
    if qualification is not None:
        scoped=face_intervals(known,f,ray_intrinsics,depth,qualification)
        error=scoped['expected_error_m']
    lower = nearest-error if error is not None else np.full((h, w), np.nan)
    upper = nearest+error if error is not None else np.full((h, w), np.nan)
    second = np.partition(depth, 1, axis=0)[1]
    ambiguity = np.isfinite(second) & (second <= nearest+2*error) if error is not None else np.zeros((h,w),bool)
    return dict(status=association, frame_state=f, map_digest=known['digest'], error_model=deepcopy(error_model),
        source_clock_review=clock_review,
        map_scope=known['metadata']['map_scope'], fk_tool_readout_error=fk_error,
        T_base_camera_optical=base_camera.tolist(),
        nominal_mount_matrix_max_error=float(abs(base_camera-nominal_camera).max()),
        error_model_digest=_digest(error_model), expected_z_static_m=depth[0], expected_z_self_m=depth[1],
        expected_z_held_m=depth[2], nearest_z_m=nearest, nearest_component=owner, expected_valid=valid,
        z_lower_m=lower, z_upper_m=upper, edge_mask=edge, uncertainty_unknown=valid & ~np.isfinite(lower),
        occlusion_ambiguous=ambiguity, occlusion_order_unknown=np.isfinite(second) & ~np.isfinite(lower),
        occluded_static_mask=np.isfinite(depth[0]) & (owner != 0),
        ray_intrinsics=ray_intrinsics,scoped_qualification=scoped,
        effective_pixel_convention=(deepcopy(f['pixel_convention']) if qualification is None else
            dict(offset_uv=qualification['offset_uv'],status='SCOPED_SIM_TEST',qualification_ref=qualification['input_ref'])),
        coverage=known['coverage'], renderer_scope='TWO_SIDED_OPAQUE_VISUAL_TRIANGLES_NOT_RTX',
        render_timings_s=dict(source_and_FK_geometry=raster_started-started, raster=raster_finished-raster_started,
                              masks_and_intervals=time.perf_counter()-raster_finished),
        render_wall_s=time.perf_counter()-started)
