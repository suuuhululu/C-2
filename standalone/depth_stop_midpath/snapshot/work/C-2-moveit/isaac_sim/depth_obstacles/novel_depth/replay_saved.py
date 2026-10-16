"""Saved run15 raw-frame CPU replay only. No semantic arrays, USD, SDK or ROS.

Run with repository and isaac_sim/scripts on PYTHONPATH. Output must be new.
The archived map subset and unmeasured errors never qualify native detection.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw

from prepare_cpu_model import read_model_bundle
from held_geometry_inputs import nominal_definition
from .geometry import freeze_known_geometry, _pin, _digest
from .expected_depth import render_expected_depth, NATIVE_PROOF_METHODS
from .difference import compare_depth, classify_depth, materialize_projection


def evaluate_depth_frame(actual_depth, known_geometry, frame_state, error_model, limits, *, now_source_s):
    """Worker compute boundary: complete expected geometry and classification.

    Original pinned source proofs are reviewed on each call. Reuse the existing
    immutable known_geometry, never dynamic expected arrays. No NPY/PNG/JSON
    export or point-list/digest materialization runs here. projected=None is a
    deliberately deferred point product, not a completed consumer observation.
    Caller must own raw/frame buffers for this call and retain this owned result
    through materialize_projection/export_depth_diagnostics. Report completion
    with a newly observed source clock; never replace captured frame timestamps.
    """
    if known_geometry is None or known_geometry['metadata']['map_scope']!='PRE_OBSTACLE_APPROVED':
        return dict(status='INPUT_UNASSOCIATED',guard=True,projected=None,
            reason='NEW_RUN_PRE_OBSTACLE_KNOWN_MAP_REQUIRED',world_clear_allowed=False)
    try:
        expected=render_expected_depth(known_geometry,frame_state,error_model)
    except ValueError as exc:
        if not str(exc).startswith(('SOURCE_CLOCK_','SOURCE_REFERENCE_','SOURCE_PHYSICS_','SOURCE_STATE_','RENDERER_SOURCE_')):
            raise
        return dict(status='INPUT_UNASSOCIATED',guard=True,projected=None,reason=str(exc),world_clear_allowed=False)
    detection=classify_depth(actual_depth,expected,frame_state,limits,now_source_s=now_source_s)
    return dict(status=detection['status'],guard=detection['guard'],expected=expected,detection=detection)


def export_depth_diagnostics(folder, expected, detection, *, error_model_ref, map_ref, source_frame_ref):
    """Optional audit export after compute publication, using existing arrays.

    All parent refs are exact and checked; changing any parent is rejected.
    Do not run concurrently with materialize_projection on the same result.
    This does not change original raw/frame/result records or clock fields.
    """
    for ref in (error_model_ref,map_ref,source_frame_ref):_pin(ref)
    inventory=_read(map_ref['path'])
    if (_digest(_read(error_model_ref['path']))!=expected['error_model_digest'] or
            inventory['map_digest']!=expected['map_digest'] or _digest(inventory['metadata'])!=expected['map_digest'] or
            _digest(_read(source_frame_ref['path']))!=_digest(expected['frame_state'])):
        raise ValueError('DIAGNOSTIC_PARENT_BINDING_MISMATCH')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    materialize_projection(detection)
    refs={}
    if detection['guard']:
        for name,value in detection.items():
            if isinstance(value,np.ndarray):
                np.save(folder/(name+'.npy'),value,allow_pickle=False);refs[name]=_ref(folder/(name+'.npy'))
    else:
        refs=_diagnostics(folder,expected,detection)
    if not detection['guard']:
        _save(folder/'projected.json',detection['projected']);refs['projected']=_ref(folder/'projected.json')
    scoped=expected.get('scoped_qualification',{})
    if scoped:
        for name in ('support_mask','face_id','expected_error_m'):
            np.save(folder/(name+'.npy'),scoped[name],allow_pickle=False);refs[name]=_ref(folder/(name+'.npy'))
        _save(folder/'qualification_companion.json',dict(qualification_ref=scoped['qualification_ref'],
            map_ref=map_ref,error_model_ref=error_model_ref,source_frame_ref=source_frame_ref,
            **{name:refs[name] for name in ('support_mask','face_id','expected_error_m')},
            risk_qualified=False,official_tolerance_m=None))
        refs['qualification_companion']=_ref(folder/'qualification_companion.json')
    _save(folder/'export_index.json',dict(error_model_ref=error_model_ref,map_ref=map_ref,
        source_frame_ref=source_frame_ref,map_digest=expected['map_digest'],guard=detection['guard'],
        status=detection['status'],counts=detection.get('counts'),
        qualification_ref=expected.get('scoped_qualification',{}).get('qualification_ref'),
        effective_pixel_convention=expected['effective_pixel_convention'],
        classification_scope=detection.get('classification_scope'),point_error_m=detection.get('point_uncertainty_bound_m'),
        arrays_and_images=refs,execution_allowed=False,world_clear_allowed=False))
    return _ref(folder/'export_index.json')


def _ref(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())


def _read(path):
    return json.loads(Path(path).read_text())


def _save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def _source_frame(raw):
    f = _read(raw/'frame.json'); receipt = _read(raw/'source_tick.receipt.json')
    review = _read(raw/'source_association_review.json'); state = _read(raw/'writer_observation.json')
    if review['same_tick_verified'] is not True or receipt['q_rad'] != state['q_rad'] or receipt['grip_rad'] != state['grip_rad']:
        raise ValueError('ARCHIVED_SOURCE_ASSOCIATION_NOT_VERIFIED')
    if any(f[k] != receipt[k] for k in ('session_id','clock_epoch','frame_seq','source_stamp_s','q_rad','T_base_tool','T_tool_camera_optical')):
        raise ValueError('ARCHIVED_FRAME_SOURCE_RECEIPT_MISMATCH')
    if (_ref(raw/'writer_observation.json')['sha256'] != receipt['native_state']['sha256'] or
            _ref(raw/'writer_source_receipt.json')['sha256'] != receipt['raw_renderer_readout']['sha256']):
        raise ValueError('ARCHIVED_NATIVE_OR_RENDER_READOUT_CHANGED')
    readout = _read(raw/'writer_source_receipt.json')
    if _ref(raw/'depth.npy')['sha256'] != receipt['source_sha256']['depth']:
        raise ValueError('ARCHIVED_RAW_DEPTH_SOURCE_CHANGED')
    f.update(grip_rad=state['grip_rad'], attachment_tcp_to_block=state['attachment'],
        T_world_base=readout['T_world_base'], T_world_camera=readout['T_world_camera'],
        camera_params=_read(raw/'camera_params.json'), reference_time=receipt['reference_time'],
        renderer_frame_id=receipt['renderer_frame_id'],
        depth_array_sha256=sha256(np.load(raw/'depth.npy',allow_pickle=False).tobytes()).hexdigest(),
        pixel_convention=dict(offset_uv=[.5,.5], status='UNVERIFIED',
                              reason='Recorded renderer-centre hypothesis; actual sampling baseline pending'))
    keys = ('session_id','clock_epoch','frame_seq','q_rad','grip_rad','attachment_tcp_to_block',
            'T_base_tool','T_tool_camera_optical','T_world_base','T_world_camera','reference_time','depth_array_sha256','renderer_frame_id')
    association = {k:deepcopy(f[k]) for k in keys}
    association.update(scope='ARCHIVED_SOURCE_TICK_REPLAY', same_tick_verified=True,
        source_ros_clock_ns=receipt['source_ros_clock_ns'], source_refs=[_ref(raw/n) for n in
        ('source_tick.receipt.json','source_association_review.json','writer_observation.json')])
    for k in ('physics_step_index','state_physics_step_index','tf_physics_step_index','image_physics_step_index'):
        association[k] = receipt[k]
    f['source_association'] = association
    f['source_refs'] = [_ref(raw/n) for n in ('depth.npy','frame.json','camera_params.json')]
    return f


def evaluate_raw_frame(raw, known_geometry, error_model, limits, *, now_source_s):
    """Shadow evaluation for a producer's raw folder; never qualify previews.

    A canonical folder contains depth.npy and the flat frame_input.json used by
    the three-function API. Existing baseline preview receipt/source_state are
    retained as evidence, but their nearest-state/nominal gate is insufficient.
    No historical map, state, clock or fixture is substituted for missing input.
    """
    raw=Path(raw)
    refs=[_ref(raw/n) for n in ('depth.npy','receipt.json','source_state.json','camera_params.json','frame_input.json') if (raw/n).is_file()]
    missing=[n for n in ('depth.npy','frame_input.json') if not (raw/n).is_file()]
    if missing:
        return dict(status='INPUT_UNASSOCIATED',guard=True,projected=None,input_refs=refs,
                    missing_files=missing,reason='EXACT_SOURCE_FRAME_REQUIRED_NEAREST_PREVIEW_NOT_APPROVAL',world_clear_allowed=False)
    f=_read(raw/'frame_input.json')
    association=f.get('source_association',{})
    required=('schema','source_kind','session_id','clock_epoch','frame_seq','clock_basis','source_stamp_s',
        'received_stamp_s','robot_state_stamp_s','transform_stamp_s','q_rad','grip_rad','attachment_tcp_to_block',
        'T_world_base','T_world_camera','T_base_tool','T_tool_camera_optical','intrinsics','camera_params',
        'reference_time','renderer_frame_id','depth_array_sha256','pixel_convention','depth_unit','depth_scale_m',
        'depth_representation','base_frame_id','tool_frame_id','optical_frame_id','calibration_id','calibration_scope')
    missing_fields=[k for k in required if k not in f]
    proof_required=('scope','same_tick_verified','source_ros_clock_ns','physics_step_index',
        'state_physics_step_index','tf_physics_step_index','image_physics_step_index','source_refs',
        'session_id','clock_epoch','frame_seq','q_rad','grip_rad','attachment_tcp_to_block',
        'T_base_tool','T_tool_camera_optical','T_world_base','T_world_camera','reference_time',
        'depth_array_sha256','renderer_frame_id')
    missing_fields += ['source_association.'+k for k in proof_required if k not in association]
    if missing_fields:
        return dict(status='INPUT_UNASSOCIATED',guard=True,projected=None,input_refs=refs,
                    missing_fields=missing_fields,reason='RAW_FRAME_FIELDS_INCOMPLETE',world_clear_allowed=False)
    native_proof=association.get('proof_method') in NATIVE_PROOF_METHODS
    if (f.get('source_kind')!='SIM_DEPTH' or association.get('scope')!='ACTUAL_SOURCE_TICK' or
            (association.get('same_tick_verified') is not True and not native_proof)):
        return dict(status='INPUT_UNASSOCIATED',guard=True,projected=None,input_refs=refs,
                    reason='INDEPENDENT_ACTUAL_SAME_TICK_PROOF_REQUIRED',world_clear_allowed=False)
    if known_geometry is None or known_geometry['metadata']['map_scope']!='PRE_OBSTACLE_APPROVED':
        return dict(status='INPUT_UNASSOCIATED',guard=True,projected=None,input_refs=refs,
                    reason='NEW_RUN_PRE_OBSTACLE_KNOWN_MAP_REQUIRED',world_clear_allowed=False)
    try:
        expected=render_expected_depth(known_geometry,f,error_model)
    except ValueError as exc:
        if not str(exc).startswith(('SOURCE_CLOCK_','SOURCE_REFERENCE_','SOURCE_PHYSICS_','SOURCE_STATE_','RENDERER_SOURCE_')):
            raise
        return dict(status='INPUT_UNASSOCIATED',guard=True,projected=None,input_refs=refs,
                    reason=str(exc),world_clear_allowed=False)
    detection=compare_depth(np.load(raw/'depth.npy',allow_pickle=False),expected,f,limits,now_source_s=now_source_s)
    return dict(status=detection['status'],guard=detection['guard'],expected=expected,detection=detection,input_refs=refs)


def _diagnostics(folder, expected, detection):
    refs = {}
    for prefix, data in [('expected', expected), ('detection', detection)]:
        for key, value in data.items():
            if isinstance(value, np.ndarray):
                path=folder/(key+'.npy'); np.save(path,value,allow_pickle=False); refs[key]=_ref(path)
    for key, mask in detection['reason_masks'].items():
        path=folder/(key+'.npy'); np.save(path,mask,allow_pickle=False); refs[key]=_ref(path)
    def gray(z):
        out=np.zeros(z.shape,np.uint8); valid=np.isfinite(z)&(z>0)
        out[valid]=np.rint(np.clip((2-z[valid])/2,0,1)*255).astype(np.uint8)
        return np.repeat(out[:,:,None],3,axis=2)
    residual=detection['residual_m']; finite=np.isfinite(residual)
    colour=np.zeros(residual.shape+(3,),np.uint8)
    colour[:,:,0][finite]=np.clip(residual[finite]/.02*255,0,255).astype(np.uint8)
    colour[:,:,2][finite]=np.clip(-residual[finite]/.02*255,0,255).astype(np.uint8)
    reasons=np.zeros_like(colour); reasons[detection['uncertain_candidate_mask']]=[255,170,0]
    reasons[detection['candidate_mask']]=[0,255,0]
    image=Image.fromarray(np.concatenate([gray(detection['observed_z_m']),gray(expected['nearest_z_m']),colour,reasons],axis=1))
    draw=ImageDraw.Draw(image)
    for i,label in enumerate(['saved actual Z','expected visual Z','residual red=closer / blue=farther; 20mm display scale','green=foreground / amber=uncertain']):
        draw.text((i*residual.shape[1]+8,8),label,fill='white',stroke_width=1,stroke_fill='black')
    image.save(folder/'residual_diagnostic.png'); refs['diagnostic_image']=_ref(folder/'residual_diagnostic.png')
    return refs


def replay(run, model, out, frame_names):
    run, model, out = Path(run), Path(model), Path(out)
    out.mkdir(parents=True,exist_ok=False)
    bootstrap=run/'live_post_grasp_bootstrap'; scene=_read(bootstrap/'scene.json')
    frame=_read(bootstrap/'frame.json'); state=_read(bootstrap/'source_tick.json')
    bundle=read_model_bundle(model)
    held=next(o for o in scene['world_objects'] if o['role']=='HELD_BLOCK')
    definition=nominal_definition({k:held[k] for k in ('id','size_m','studs','block')},bundle)
    # Explicit prior structure subset. Both scenario stimuli and all /World
    # guide curves are absent; this is not a new actual known-map freeze.
    approved=[o for o in scene['world_objects'] if o['role'] in
              ('SUPPLY_BOARD','ASSEMBLY_BOARD','SUPPLY_BLOCK','CURRENT_BLOCK') or o['id']=='HandoverTray']
    snapshot=dict(session_id=frame['session_id'],clock_epoch=frame['clock_epoch'],
        freeze_source_time=state['stamp_s'],map_scope='ARCHIVED_SUBSET_REPLAY_ONLY',
        T_world_base=state['T_world_base'],world_objects=approved)
    _save(out/'map_snapshot.json',snapshot)
    source_refs=[_ref(out/'map_snapshot.json'),_ref(bootstrap/'scene.json'),_ref(model/'MODEL_MANIFEST.json')]
    started=time.perf_counter()
    known=freeze_known_geometry(snapshot,bundle,definition,[o['id'] for o in approved],source_refs)
    freeze_wall=time.perf_counter()-started
    _save(out/'geometry_inventory.json',dict(map_digest=known['digest'],metadata=json.loads(json.dumps(
        dict(known['metadata']),default=lambda x:dict(x) if hasattr(x,'keys') else list(x)))))
    error=dict(status='UNMEASURED',source_refs=[],expected_error_m=None,depth_error_m=None,
               point_error_m=None,edge_jump_m=None)
    _save(out/'error_model.json',error)
    limits=dict(clock_basis='SIM_TIME',threshold_status='SIM_TEST_PARAMETER',max_age_s=.12,
                max_pose_skew_s=.001,min_depth_m=.02,max_depth_m=2.)
    rows=[]
    for name in frame_names:
        raw=run/'writer_sensor_raw'/name; folder=out/name; folder.mkdir()
        f=_source_frame(raw); _save(folder/'frame_input.json',f)
        actual=np.load(raw/'depth.npy',allow_pickle=False); started=time.perf_counter()
        expected=render_expected_depth(known,f,error)
        # Replay evaluation clock, not the current live SIM/wall clock.
        detection=compare_depth(actual,expected,f,limits,now_source_s=f['received_stamp_s'])
        pipeline_wall=time.perf_counter()-started
        if detection['guard']:
            raise ValueError('REPLAY_GUARD:'+detection['status'])
        refs=_diagnostics(folder,expected,detection)
        _save(folder/'projected.json',detection['projected']); refs['projected']=_ref(folder/'projected.json')
        row=dict(frame=name,status=detection['status'],source_stamp_s=f['source_stamp_s'],counts=detection['counts'],
            source_association_scope=expected['status'],map_digest=known['digest'],error_model_ref=_ref(out/'error_model.json'),
            source_frame_ref=_ref(folder/'frame_input.json'),render_wall_s=expected['render_wall_s'],
            compare_wall_s=detection['compare_wall_s'],pipeline_wall_s=pipeline_wall,
            render_timings_s=expected['render_timings_s'],compare_timings_s=detection['compare_timings_s'],
            fk_tool_readout_error=expected['fk_tool_readout_error'],arrays_and_images=refs,
            pixel_convention=f['pixel_convention'],uncertainty_bound_m=None,native_detection_verified=False)
        _save(folder/'result.json',row); rows.append(row)
    result=dict(scope='SAVED_ACTUAL_RAW_FRAME_CPU_REPLAY_NOT_LIVE',frames=rows,freeze_wall_s=freeze_wall,
        wall_distribution_s={k:float(np.quantile([r['pipeline_wall_s'] for r in rows],q)) for k,q in [('p50',.5),('p95',.95),('max',1.)]},
        output=str(out.resolve()),new_moving_wrist_baseline_verified=False,semantic_inputs_read=False,
        raw_overlay_contamination_retained=True,native_detection_verified=False)
    _save(out/'result.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('run','model','out'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--frames',nargs='+',default=['000','001','002'])
    a=parser.parse_args(); result=replay(a.run,a.model,a.out,a.frames)
    print(json.dumps({k:v for k,v in result.items() if k!='frames'},ensure_ascii=False))
