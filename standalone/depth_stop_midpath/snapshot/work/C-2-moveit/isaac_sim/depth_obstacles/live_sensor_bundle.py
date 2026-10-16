"""Actual writer readout evidence; no inferred renderer step or admission flags."""
from pathlib import Path
import hashlib,json
import numpy as np


def pin(path):
    path=Path(path);return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def save(path,data):
    Path(path).write_text(json.dumps(data,indent=2,default=lambda x:x.tolist() if isinstance(x,np.ndarray) else x.item())+'\n')


def capture(folder,image,env,row,context,loaded_source,profile):
    """Called synchronously in the native writer; exports the observed USD only.

    Readout time and image ReferenceTime are independent. This function never
    aliases them or assigns renderer frame/physics identifiers it did not read.
    """
    from pxr import Usd,UsdGeom
    from .capture_wrist_sim import rigid,select_masks
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    stage=env['stage'];own,held,obstacle,labels=select_masks(image['ids'],image['info'])
    for name,array in [('depth',image['depth']),('semantic_ids',image['ids']),('self_mask',own),('held_mask',held),('obstacle_mask',obstacle)]:
        np.save(folder/(name+'.npy'),array,allow_pickle=False)
    for name,value in [('semantic_info',image['info']),('camera_params',image['params']),('writer_observation',row),('geometry_context',context)]:save(folder/(name+'.json'),value)
    (folder/'capture_source.py').write_bytes(Path(loaded_source).read_bytes())
    (folder/'capture_profile.json').write_bytes(Path(profile).read_bytes())
    inventory=[]
    for root in ('/World/Robot',context['held_geometry']['prim_path']):
        for prim in Usd.PrimRange(stage.GetPrimAtPath(root),Usd.TraverseInstanceProxies()):
            if not prim.IsA(UsdGeom.Gprim):continue
            item=dict(prim_path=str(prim.GetPath()),type=prim.GetTypeName(),T_world_prim=rigid(stage,str(prim.GetPath())).tolist(),visibility=UsdGeom.Imageable(prim).ComputeVisibility(),purpose=UsdGeom.Imageable(prim).ComputePurpose())
            if prim.IsA(UsdGeom.Cube):item['size']=UsdGeom.Cube(prim).GetSizeAttr().Get()
            if prim.IsA(UsdGeom.Mesh):
                mesh=UsdGeom.Mesh(prim)
                item['mesh_array_sha256']={key:hashlib.sha256(np.asarray(getter()).tobytes()).hexdigest() for key,getter in [('points',mesh.GetPointsAttr().Get),('faceVertexCounts',mesh.GetFaceVertexCountsAttr().Get),('faceVertexIndices',mesh.GetFaceVertexIndicesAttr().Get)]}
            inventory.append(item)
    stage.Export(str(folder/'captured_scene.usda'))
    save(folder/'scene_inventory.json',dict(scope='ACTUAL_WRITER_READOUT_USD_INVENTORY_SOURCE_TICK_REVIEW_PENDING',scene=pin(folder/'captured_scene.usda'),geometry_context=context,prims=inventory))
    receipt=dict(scope='ACTUAL_RENDER_WRITER_RAW_REFERENCE_AND_READOUT_NOT_SOURCE_TICK_APPROVAL',reference_time=image['reference_time'],image_source_stamp_s=image['source_stamp_s'],readout_world_stamp_s=row['time_s'],readout_physics_step=row['tracking']['physics_step'],reference_annotator=image['reference_annotator'],writer_data_keys=image['writer_data_keys'],observation_wall_monotonic_s=image['observation_wall_monotonic_s'],T_world_camera=rigid(stage,env['camera_path']).tolist(),T_world_base=rigid(stage,env['base']).tolist(),source_sha256={name:pin(folder/(name+ext))['sha256'] for name,ext in [('depth','.npy'),('semantic_ids','.npy'),('capture_source','.py')]},same_tick_verified=False,renderer_frame_id=None,physics_image_step_verified=False)
    save(folder/'writer_source_receipt.json',receipt)
    mapping=dict(depth='depth.npy',semantic_ids='semantic_ids.npy',semantic_info='semantic_info.json',self_mask='self_mask.npy',held_mask='held_mask.npy',obstacle_mask='obstacle_mask.npy',capture_source='capture_source.py',source_receipt='writer_source_receipt.json',scene_inventory='scene_inventory.json')
    manifest=dict(schema='single-object-depth-evidence/0.1',source_kind='SIM_DEPTH',annotator='distance_to_image_plane',status='RAW_WRITER_BUNDLE_SOURCE_TICK_AND_MASK_CALIBRATION_REVIEW_PENDING',files={k:dict(path=v,sha256=pin(folder/v)['sha256']) for k,v in mapping.items()},execution_allowed=False,hardware_execution_allowed=False)
    save(folder/'manifest.pending.json',manifest)
    return pin(folder/'manifest.pending.json')


def review_source(image,matched):
    raw=image['writer_source_observation'];tracking=matched['raw_observation']['tracking']
    n,d=image['reference_time'];reasons=[]
    if type(image['renderer_frame_id']) is not int or image['renderer_frame_id']<0:reasons.append('ACTUAL_RENDERER_FRAME_ID_REQUIRED')
    if (n*1_000_000_000)%d or tracking['ros_clock_ns']!=(n*1_000_000_000)//d:reasons.append('RENDERER_REFERENCE_NOT_SOURCE_ROS_CLOCK')
    if raw['tracking']['physics_step']!=tracking['physics_step']:reasons.append('WRITER_AND_STATE_DIFFERENT_PHYSICS_STEPS')
    for key in ('q_rad','grip_rad','attachment'):
        if raw[key]!=matched['raw_observation'][key]:reasons.append('WRITER_STATE_MISMATCH:'+key)
    view=np.asarray(image['params']['cameraViewTransform']).reshape(4,4).T
    view_error=float(np.max(abs(np.linalg.inv(view)-np.asarray(matched['T_world_camera']))))
    if view_error>1e-8:reasons.append('RECORDED_RENDERER_CAMERA_MATRIX_MISMATCH')
    result=dict(scope='WRITER_RENDERER_PHYSICS_SOURCE_ASSOCIATION_REVIEW',reasons=reasons,same_tick_verified=not reasons,renderer_frame_id=image['renderer_frame_id'],view_matrix_max_error=view_error)
    return result


def complete(folder,image,matched,frame,limits,model):
    result=review_source(image,matched)
    save(folder/'source_association_review.json',result)
    if result['reasons']:return result
    raw=image['writer_source_observation'];tracking=matched['raw_observation']['tracking']
    step=tracking['physics_step']
    receipt=dict(scope='ACTUAL_SIM_RTX_SOURCE_TICK_STATE_TF',timeline_running=True,
        **{k:frame[k] for k in ('session_id','clock_basis','clock_epoch','frame_seq','source_stamp_s','q_rad','T_base_tool','T_tool_camera_optical','observation_wall_monotonic_s')},
        physics_step_index=step,state_physics_step_index=step,tf_physics_step_index=step,image_physics_step_index=step,
        renderer_frame_id=image['renderer_frame_id'],reference_time=image['reference_time'],source_ros_clock_ns=tracking['ros_clock_ns'],
        raw_native_world_stamp_s=matched['stamp_s'],native_state=pin(folder/'writer_observation.json'),
        raw_renderer_readout=pin(folder/'writer_source_receipt.json'),source_association_review=pin(folder/'source_association_review.json'),
        capture_source_sha256=pin(folder/'capture_source.py')['sha256'],grip_rad=raw['grip_rad'],state_sequence=step,
        source_sha256={k:pin(folder/(k+ext))['sha256'] for k,ext in [('depth','.npy'),('semantic_ids','.npy'),('capture_source','.py')]})
    save(folder/'source_tick.receipt.json',receipt)
    from prepare_cpu_model import read_model_bundle
    bundle=read_model_bundle(model)
    pose=dict(stamp_s=frame['source_stamp_s'],raw_native_world_stamp_s=matched['stamp_s'],clock_basis=frame['clock_basis'],q_rad=raw['q_rad'],grip_rad=raw['grip_rad'],state_sequence=step,
        image_source_stamp_verified=True,time_sync_scope='DYNAMIC_SOURCE_STAMP_VERIFIED',source_tick_evidence=pin(folder/'source_tick.receipt.json'),
        model_manifest_sha256=bundle['manifest_sha256'],capture_source_sha256=pin(folder/'capture_source.py')['sha256'],
        live_scene_motion_kind=frame['live_scene_motion_kind'],world_revision=frame['world_revision'])
    for name,value in [('pose',pose),('frame',frame),('limits',limits)]:save(folder/(name+'.json'),value)
    # Scene/mesh/semantic validation remains independent. Its failure cannot
    # promote masks or produce a completed evidence manifest.
    from .bind_native_inventory import bind
    try:
        validation=bind(folder,model)
        save(folder/'inventory_binding_result.json',validation)
    except (ValueError,KeyError) as exc:
        validation=dict(status='HOLD',reason=str(exc));save(folder/'inventory_binding_result.json',validation)
        return dict(result,inventory=validation)
    return dict(result,inventory=validation)
