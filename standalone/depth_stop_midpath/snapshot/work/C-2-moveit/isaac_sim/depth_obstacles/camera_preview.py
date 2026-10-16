"""File-only RGB/Depth preview from one actual render-writer callback."""
from pathlib import Path
import hashlib,json
import numpy as np
from PIL import Image


def save_preview(folder,image,session,camera_path):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    def pin(path):return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    depth=image['depth'];np.save(folder/'depth.npy',depth,allow_pickle=False)
    valid=np.isfinite(depth)&(depth>=.02)&(depth<=2.)
    gray=np.zeros(depth.shape,dtype=np.uint8)
    gray[valid]=np.rint((2.-depth[valid])/1.98*255).astype(np.uint8)
    Image.fromarray(gray).save(folder/'depth_display.png')
    rgb=image.get('rgb');rgb_ref=None
    if isinstance(rgb,np.ndarray) and rgb.dtype==np.uint8 and rgb.shape[:2]==depth.shape and rgb.ndim==3 and rgb.shape[2] in (3,4):
        Image.fromarray(rgb).save(folder/'rgb.png');rgb_ref=pin(folder/'rgb.png')
    (folder/'camera_params.json').write_text(json.dumps(image['params'])+'\n')
    receipt=dict(scope='ACTUAL_RENDER_WRITER_RGB_DEPTH_PREVIEW_NOT_SOURCE_TICK_OR_BOUND_APPROVAL',
        session_id=session,camera_path=camera_path,source_stamp_s=float(image['source_stamp_s']),
        reference_time=[int(v) for v in image['reference_time']],renderer_frame_id=int(image['renderer_frame_id']),
        observation_wall_monotonic_s=image['observation_wall_monotonic_s'],
        pairing='SAME_RENDER_WRITER_CALLBACK_REFERENCE_TIME_NO_RETIMESTAMP',rgb=rgb_ref,
        depth=pin(folder/'depth.npy'),depth_display=pin(folder/'depth_display.png'),camera_params=pin(folder/'camera_params.json'),
        depth_display_mapping='LINEAR_0.02_TO_2_METRES_NEAR_WHITE_FAR_BLACK_INVALID_BLACK_RAW_NPY_UNCHANGED',
        RGB_annotator_available=rgb_ref is not None,calibration_or_mask_changed=False,SDK_admitted=False,execution_allowed=False)
    (folder/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return dict(receipt=pin(folder/'receipt.json'),**receipt)


def colorize_depth_memory(depth):
    """Owned RGBA display buffer only; sensor pixels are never modified."""
    if not isinstance(depth,np.ndarray) or depth.ndim!=2:raise ValueError('RAW_DEPTH_IMAGE_REQUIRED')
    valid=np.isfinite(depth)&(depth>=.02)&(depth<=2.)
    scaled=np.zeros(depth.shape,dtype=np.float32)
    scaled[valid]=np.clip((depth[valid]-.02)/1.98,0.,1.)
    rgba=np.zeros((*depth.shape,4),dtype=np.uint8);rgba[:,:,3]=255
    rgba[:,:,0][valid]=np.rint(255*(1-scaled[valid])).astype(np.uint8)
    rgba[:,:,1][valid]=np.rint(255*(1-abs(2*scaled[valid]-1))).astype(np.uint8)
    rgba[:,:,2][valid]=np.rint(255*scaled[valid]).astype(np.uint8)
    rgba.setflags(write=False);return rgba


def prepare_memory_display(packet):
    """Existing bounded CPU worker task. No files, Kit, new sensor, or control."""
    import time
    entered=time.monotonic();depth=packet['depth'];before=hashlib.sha256(depth.tobytes(order='C')).hexdigest()
    started=time.monotonic();rgba=colorize_depth_memory(depth);conversion_finished=time.monotonic()
    after=hashlib.sha256(depth.tobytes(order='C')).hexdigest()
    if before!=after:raise ValueError('DISPLAY_MUTATED_RAW_DEPTH')
    rgb=packet.get('rgb');rgb_rgba=None
    if isinstance(rgb,np.ndarray) and rgb.dtype==np.uint8 and rgb.shape[:2]==depth.shape:
        if rgb.shape[2]==4:rgb_rgba=np.ascontiguousarray(rgb)
        elif rgb.shape[2]==3:
            rgb_rgba=np.empty((*depth.shape,4),np.uint8);rgb_rgba[:,:,:3]=rgb;rgb_rgba[:,:,3]=255
        if rgb_rgba is not None:rgb_rgba.setflags(write=False)
    return dict(depth_rgba=rgba,rgb_rgba=rgb_rgba,raw_depth_before_sha256=before,raw_depth_after_sha256=after,
        input=packet,worker_entered_wall_monotonic_s=entered,conversion_started_wall_monotonic_s=started,conversion_finished_wall_monotonic_s=conversion_finished,worker_finished_wall_monotonic_s=time.monotonic())


def upload_memory_provider(provider,rgba):
    """Installed omni.ui ndarray API; caller owns app-thread/lifetime policy."""
    if rgba.dtype!=np.uint8 or rgba.ndim!=3 or rgba.shape[2]!=4:raise ValueError('RGBA8_UI_BUFFER_REQUIRED')
    provider.set_data_array(rgba.reshape(-1),[rgba.shape[1],rgba.shape[0]],strict=True)


def display_frame_label(row,now_wall,*,rgb_viewport):
    """Last uploaded frame, elapsed wall age, and actual RGB route; never 'current'."""
    route='RGB separate viewport / independent render' if rgb_viewport else 'RGB writer memory / same packet'
    elapsed=max(0.,now_wall-row['UI_upload_returned_wall_monotonic_s'])
    return (f"LAST frame {row['display_seq']} / source SIM {row['source_stamp_s']:.4f}s "
            f"/ last upload {elapsed:.2f}s ago / source age at upload {row['source_age_at_upload_s']:.4f}s / {route}")


def prepare_detection_display(image,frame,detection):
    """Same Writer pixels only. Classification overlay, never a point/risk view."""
    import time
    started=time.monotonic()
    for key in ('frame_seq','source_stamp_s','reference_time','renderer_frame_id'):
        if image[key]!=frame[key]:raise ValueError('OVERLAY_WRITER_FRAME_MISMATCH:'+key)
    if detection['source_association']!=frame['source_association'] or detection['pixel_convention']!=frame['pixel_convention']:
        raise ValueError('OVERLAY_MASK_SOURCE_OR_GRID_MISMATCH')
    if image['source_identity']!={k:frame[k] for k in ('session_id','clock_epoch')}:
        raise ValueError('OVERLAY_SESSION_OR_EPOCH_MISMATCH')
    tag=image['render_buffer_request_tag']
    if tag['values']!=[frame['render_request_id']] or tag['prim']!=frame['tool_frame_id']+'/DepthStopCamera' or tag['attribute']!='seeun:renderRequestId':raise ValueError('OVERLAY_RENDER_REQUEST_OR_CAMERA_MISMATCH')
    depth=image['depth'];shape=(frame['intrinsics']['height'],frame['intrinsics']['width'])
    if depth.shape!=shape:raise ValueError('OVERLAY_RAW_GRID_SHAPE_MISMATCH')
    masks={k:detection[k] for k in ('candidate_mask','uncertain_candidate_mask')}
    masks['invalid']=detection['reason_masks']['invalid_actual']
    for key in ('matched_static','matched_self','matched_held'):masks[key]=detection['reason_masks'][key]
    if any(not isinstance(m,np.ndarray) or m.dtype!=np.bool_ or m.shape!=shape for m in masks.values()):
        raise ValueError('OVERLAY_MASK_GRID_OR_DTYPE_MISMATCH')
    if not np.all(sum(m.astype(np.uint8) for m in masks.values())==1):raise ValueError('OVERLAY_PRIMARY_MASK_PARTITION_MISMATCH')
    candidate,uncertain,invalid=(masks[k] for k in ('candidate_mask','uncertain_candidate_mask','invalid'))
    if (candidate&uncertain).any() or ((candidate|uncertain)&invalid).any():raise ValueError('OVERLAY_MASK_OVERLAP_OR_INVALID_COLOUR')
    if not np.array_equal(invalid,~(np.isfinite(depth)&(depth>=.02)&(depth<=2.))):raise ValueError('OVERLAY_INVALID_DEPTH_RANGE_MISMATCH')
    arrays=dict(depth=depth,**masks);rgb=image.get('rgb')
    if rgb is not None:
        if not isinstance(rgb,np.ndarray) or rgb.dtype!=np.uint8 or rgb.shape[:2]!=shape or rgb.ndim!=3 or rgb.shape[2] not in (3,4):raise ValueError('OVERLAY_RGB_GRID_OR_DTYPE_MISMATCH')
        arrays['rgb']=rgb
    before={k:hashlib.sha256(a.tobytes(order='C')).hexdigest() for k,a in arrays.items()}
    if before['depth']!=frame['depth_array_sha256']:raise ValueError('OVERLAY_RAW_DEPTH_HASH_MISMATCH')
    if rgb is not None and (before['rgb']!=frame['rgb_array_sha256'] or before['rgb']!=image['rgb_array_sha256']):raise ValueError('OVERLAY_RAW_RGB_HASH_MISMATCH')
    rgba=np.empty((*shape,4),np.uint8);rgba[:,:,3]=255
    if rgb is not None:
        rgba[:,:,:rgb.shape[2]]=rgb;route='SAME_WRITER_RGB'
    else:
        gray=np.zeros(shape,np.uint8);valid=~invalid
        gray[valid]=np.rint((2.-depth[valid])/1.98*255).astype(np.uint8)
        rgba[:,:,:3]=gray[:,:,None];route='SAME_WRITER_DEPTH_NO_RGB_SUBSTITUTION'
    for mask,colour in ((candidate,[0,255,0]),(uncertain,[255,170,0])):
        rgba[:,:,:3][mask]=np.rint(.55*rgba[:,:,:3][mask].astype(float)+.45*np.asarray(colour)).astype(np.uint8)
    after={k:hashlib.sha256(a.tobytes(order='C')).hexdigest() for k,a in arrays.items()}
    if before!=after:raise ValueError('OVERLAY_MUTATED_SOURCE_ARRAY')
    rgba.setflags(write=False)
    return dict(rgba=rgba,rgba_sha256=hashlib.sha256(rgba.tobytes(order='C')).hexdigest(),source_identity={k:frame[k] for k in ('session_id','clock_epoch','frame_seq','source_stamp_s','reference_time','renderer_frame_id','render_request_id','optical_frame_id','calibration_id')},background=route,pixel_grid='ORIGINAL_WRITER_ARRAY_ROW_COLUMN_NO_FLIP_RESAMPLE',shape=list(shape),raw_hashes_before=before,raw_hashes_after=after,foreground_pixels=int(candidate.sum()),uncertain_pixels=int(uncertain.sum()),prepared_started_wall_monotonic_s=started,prepared_finished_wall_monotonic_s=time.monotonic(),point_product_required=False,PNG_read_required=False)


def detection_frame_label(row,now_source_s,now_wall,*,computing):
    age=now_source_s-row['source_stamp_s'];fresh=0<=age<=.12
    return (f"HISTORICAL detection frame {row['frame_seq']} / session {row['session_id']} / epoch {row['clock_epoch']}\n"
            f"render request {row['render_request_id']} / renderer {row['renderer_frame_id']} / source SIM {row['source_stamp_s']:.4f}s / classified observed SIM {row['classification_observed_source_s']:.4f}s\n"
            f"age NOW {age:.4f} SIM s / {'FRESH <=0.12s' if fresh else 'STALE >0.12s or clock mismatch'} / last upload {max(0.,now_wall-row['UI_upload_returned_wall_monotonic_s']):.2f} wall s ago\n"
            f"{'Computing next classification' if computing else 'Waiting for next classification'} / {row['background']}\n"
            'Green: obstacle candidate / Orange: uncertain / known pixels unchanged / no STOP decision')


def save_preview_metadata(folder,image,session,camera_path):
    """Keep native source proof without claiming unretained raw array files."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    def pin(p):return dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    (folder/'camera_params.json').write_text(json.dumps(image['params'])+'\n')
    receipt=dict(scope='ACTUAL_RENDER_WRITER_RGB_DEPTH_PREVIEW_NOT_SOURCE_TICK_OR_BOUND_APPROVAL',
        session_id=session,camera_path=camera_path,source_stamp_s=float(image['source_stamp_s']),
        reference_time=[int(v) for v in image['reference_time']],renderer_frame_id=int(image['renderer_frame_id']),
        observation_wall_monotonic_s=image['observation_wall_monotonic_s'],
        pairing='SAME_RENDER_WRITER_CALLBACK_REFERENCE_TIME_NO_RETIMESTAMP',
        rgb=None,depth=None,depth_display=None,camera_params=pin(folder/'camera_params.json'),
        RGB_annotator_available=isinstance(image.get('rgb'),np.ndarray),
        depth_array_sha256=hashlib.sha256(image['depth'].tobytes(order='C')).hexdigest(),
        rgb_array_sha256=image.get('rgb_array_sha256'),payload_retained=False,
        later_selected_raw_bundle='retained_raw_artifacts.json only if actually created',
        calibration_or_mask_changed=False,SDK_admitted=False,execution_allowed=False)
    (folder/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return dict(receipt=pin(folder/'receipt.json'),**receipt)


def save_selected_detection_evidence(folder,review,*,frame_ref,error_ref,map_ref):
    """Selected original arrays only; no full projected-point JSON or recapture."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    def pin(p):return dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    refs={};expected=(review or {}).get('expected') or {};detection=(review or {}).get('detection') or {}
    sources=[(expected,('nearest_z_m','nearest_component','expected_valid','z_lower_m','z_upper_m','edge_mask','uncertainty_unknown','occlusion_ambiguous','occlusion_order_unknown')),
             (detection,('observed_z_m','residual_m','candidate_mask','uncertain_candidate_mask')),
             (expected.get('scoped_qualification') or {},('support_mask','face_id','expected_error_m'))]
    for values,keys in sources:
        for key in keys:
            value=values.get(key)
            if isinstance(value,np.ndarray):np.save(folder/(key+'.npy'),value,allow_pickle=False);refs[key]=pin(folder/(key+'.npy'))
    for key,value in detection.get('reason_masks',{}).items():
        if key not in refs:np.save(folder/(key+'.npy'),value,allow_pickle=False);refs[key]=pin(folder/(key+'.npy'))
    overlay=(review or {}).get('display_result')
    if overlay is not None:
        Image.fromarray(overlay['rgba']).save(folder/'detection_overlay.png');refs['detection_overlay']=pin(folder/'detection_overlay.png')
    index=dict(scope='SELECTED_ORIGINAL_CLASSIFICATION_EVIDENCE_NOT_FULL_POINT_ARCHIVE',source_frame_ref=frame_ref,
        error_model_ref=error_ref,map_ref=map_ref,arrays_and_images=refs,
        projected_3D_points_retained=False,all_expected_components_retained=False,
        counts=detection.get('counts'),risk_qualified=False,point3D_error_m=None)
    (folder/'export_index.json').write_text(json.dumps(index,indent=2)+'\n');return pin(folder/'export_index.json')
