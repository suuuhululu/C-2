"""CPU provenance checks for nominal SIM calibration and semantic scene binding.

Producer inventories are recorded evidence, not an independent USD renderer.
No acquisition, ROS, SDK, physical calibration acceptance or execution.
"""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from prepare_cpu_model import file_hash
from plan_only import digest
from sim_utils import rigid


def pinned_json(ref):
    path=Path(ref['path']).resolve(strict=True)
    if file_hash(path)!=ref['sha256']:raise ValueError('SIM_EVIDENCE_PIN_CHANGED')
    return json.loads(path.read_text())


def projection_rays(params,pixels):
    """Invert saved RTX pinhole row-vector USD projection into optical rays."""
    if params['cameraModel']!='pinhole' or params['metersPerSceneUnit']!=1:raise ValueError('NOMINAL_METRIC_PINHOLE_REQUIRED')
    P=np.asarray(params['cameraProjection'],float).reshape(4,4);W,H=params['renderProductResolution']
    allowed={(0,0),(1,1),(2,0),(2,1),(2,2),(2,3),(3,2)}
    if (not np.isfinite(P).all() or P[0,0]<=0 or P[1,1]<=0 or P[2,3]!=-1 or
            any(P[i,j]!=0 for i in range(4) for j in range(4) if (i,j) not in allowed)):
        raise ValueError('SUPPORTED_RTX_PROJECTION_CONVENTION_REQUIRED')
    uv=np.asarray(pixels,float)
    if (uv.ndim!=2 or uv.shape[1:]!=(2,) or not np.isfinite(uv).all() or
            np.any(uv<0) or np.any(uv[:,0]>=W) or np.any(uv[:,1]>=H)):raise ValueError('VALID_PROJECTION_PIXELS_REQUIRED')
    return np.column_stack(((2*uv[:,0]/W-1+P[2,0])/P[0,0],(2*uv[:,1]/H-1-P[2,1])/P[1,1],np.ones(len(uv))))


def published_calibration(frame,ref,model):
    evidence=pinned_json(ref);profile=pinned_json(evidence['profile'])
    live=pinned_json(evidence['published_messages'])
    if (profile['source_kind']!='ROKEY_PUBLISHED_STATIC_TF_CAMERAINFO_NOT_HAND_EYE' or
            profile['calibration_scope']!='SIM_NOMINAL_FROM_REAL_PUBLISHED_TF' or
            profile['hand_eye_independently_verified'] is not False or
            profile['hardware_execution_allowed'] is not False or
            profile['stream_kind']!='RAW_RECTIFIED_DEPTH' or frame['source_kind']!='SIM_DEPTH'):
        raise ValueError('PUBLISHED_NOMINAL_SIM_ONLY')
    for path,sha in profile['source_evidence'].items():
        if file_hash(Path(evidence['source_root'])/path)!=sha:raise ValueError('PROFILE_SOURCE_CHANGED')
    if (evidence['model_urdf_sha256']!=file_hash(Path(model['bundle_path'])/'robot.urdf') or
            evidence['model_urdf_sha256'] not in profile['source_evidence'].values()):
        raise ValueError('PUBLISHED_PROFILE_MODEL_MISMATCH')
    if evidence['published_messages']['sha256'] not in profile['source_evidence'].values():
        raise ValueError('PUBLISHED_MESSAGES_NOT_PROFILE_SOURCE')
    robot=ET.fromstring(model['robot_description'])
    joint=next(j for j in robot.findall('joint') if j.find('child').get('link')=='GripperDA_v4_tcp')
    if joint.get('type')!='fixed' or joint.find('parent').get('link')!='link_6':raise ValueError('TCP_FIXED_ORIGIN_REQUIRED')
    origin=joint.find('origin');T=np.eye(4)
    T[:3,3]=np.array(origin.get('xyz','0 0 0').split(),float)
    T[:3,:3]=Rotation.from_euler('xyz',np.array(origin.get('rpy','0 0 0').split(),float)).as_matrix()
    transform=np.linalg.inv(T)
    chain=['link_6','tool0','bracket_link','camera_bottom_screw_frame','camera_link','camera_depth_frame','camera_depth_optical_frame']
    if profile['source_chain']!=['->'.join(x) for x in zip(chain,chain[1:])]:raise ValueError('RAW_OPTICAL_CHAIN_REQUIRED')
    for parent,child in zip(chain,chain[1:]):
        edge=live['tf_static'][parent+'->'+child]
        if edge['header']['frame_id']!=parent or edge['child_frame_id']!=child:raise ValueError('TF_FRAME_CHANGED')
        local=np.eye(4);local[:3,3]=edge['translation'];local[:3,:3]=Rotation.from_quat(edge['quaternion_xyzw']).as_matrix()
        transform=transform@local
    info=live['infos']['raw'];intr=profile['intrinsics']
    if (info['header']['frame_id']!='camera_depth_optical_frame' or any(info['d']) or
            frame['optical_frame_id']!=info['header']['frame_id'] or frame['intrinsics']!=intr or
            [intr[k] for k in ('width','height','fx','fy','cx','cy')]!=
            [info['width'],info['height'],info['k'][0],info['k'][4],info['k'][2],info['k'][5]]):
        raise ValueError('RAW_CAMERAINFO_MISMATCH')
    if (frame['calibration_id']!=profile['profile_id'] or
            not np.allclose(transform,rigid(profile['T_tool_camera_optical']),atol=1e-12,rtol=0) or
            not np.allclose(transform,rigid(frame['T_tool_camera_optical']),atol=1e-12,rtol=0)):
        raise ValueError('PUBLISHED_TCP_OPTICAL_MISMATCH')
    rays=evidence['ray_validation']
    if (rays['scope']!='SIM_RENDERER_PIXEL_RAY_VALIDATION' or rays['profile_sha256']!=evidence['profile']['sha256'] or
            rays['capture_source_sha256']!=evidence['capture_source_sha256']):raise ValueError('SIM_PIXEL_RAY_EVIDENCE_REQUIRED')
    # Recorded renderer optical rays at noncentral pixels, not points replayed
    # from the same intrinsics. Include error in the declared point prior.
    pixels=np.asarray(rays['pixel_uv'],float);actual=np.asarray(rays['renderer_optical_directions'],float)
    if 'projection_ref' in rays:
        params=pinned_json(rays['projection_ref'])
        if params['renderProductResolution']!=[intr['width'],intr['height']]:raise ValueError('RTX_PROJECTION_RESOLUTION_CHANGED')
        offset=rays.get('renderer_pixel_offset_uv',[0.,0.])
        if offset not in ([0.,0.],[.5,.5]):raise ValueError('SUPPORTED_RENDERER_PIXEL_OFFSET_REQUIRED')
        if 'pixel_convention_source' in rays:
            convention=rays['pixel_convention_source']
            if file_hash(convention['path'])!=convention['sha256']:raise ValueError('PIXEL_CONVENTION_SOURCE_CHANGED')
        if not np.allclose(projection_rays(params,pixels+offset),actual,atol=1e-14,rtol=0):raise ValueError('RTX_PROJECTION_RAY_REPLAY_CHANGED')
    if pixels.ndim!=2 or pixels.shape[1:]!=(2,) or len(pixels)<3 or actual.shape!=(len(pixels),3):
        raise ValueError('SIM_PIXEL_RAY_SAMPLES_REQUIRED')
    if (not np.isfinite([pixels]).all() or not np.isfinite(actual).all() or np.any(actual[:,2]<=0) or
            np.ptp(pixels[:,0])<intr['width']/2 or np.ptp(pixels[:,1])<intr['height']/2):
        raise ValueError('SIM_PIXEL_RAY_COVERAGE_REQUIRED')
    observed=actual[:,:2]/actual[:,2,None]
    expected=(pixels-[intr['cx'],intr['cy']])/[intr['fx'],intr['fy']]
    error=float(np.max(np.linalg.norm(observed-expected,axis=1)))
    if not np.isfinite(rays['max_normalized_ray_error']) or not 0<=error<=rays['max_normalized_ray_error']:
        raise ValueError('SIM_PIXEL_RAY_ERROR_EXCEEDED')
    evidence['normalized_ray_error']=rays['max_normalized_ray_error']
    return evidence


def robot_visual_inventory(model):
    """Expected visual geometry/origin signatures, including mesh bytes."""
    from urllib.parse import unquote,urlparse
    expected={}
    for link in ET.fromstring(model['robot_description']).findall('link'):
        for i,visual in enumerate(link.findall('visual')):
            geometry=visual.find('geometry');origin=visual.find('origin')
            mesh=geometry.find('mesh')
            signature=dict(geometry=ET.tostring(geometry,encoding='unicode').strip(),
                origin_xyz=origin.get('xyz','0 0 0') if origin is not None else '0 0 0',
                origin_rpy=origin.get('rpy','0 0 0') if origin is not None else '0 0 0',
                mesh_sha256=file_hash(Path(unquote(urlparse(mesh.get('filename')).path))) if mesh is not None else None)
            expected[link.get('name')+':'+str(i)]=digest(signature)
    if not expected:raise ValueError('ORIGINAL_ROBOT_VISUAL_GEOMETRY_REQUIRED')
    return expected


def semantic_scene_binding(audit,paths,frame,model,geometry_context):
    from prepare_cumotion_model import urdf_transforms
    if (audit['scene']['sha256']!=file_hash(audit['scene']['path']) or
            audit['semantic_ids_sha256']!=file_hash(paths['semantic_ids']) or
            audit['capture_source_sha256']!=file_hash(paths['capture_source']) or
            audit['session_id']!=frame['session_id'] or audit['frame_seq']!=frame['frame_seq'] or
            audit['source_stamp_s']!=frame['source_stamp_s'] or audit['clock_basis']!=frame['clock_basis'] or
            audit['geometry_context']!=geometry_context):raise ValueError('SEMANTIC_SCENE_BINDING_CHANGED')
    expected=robot_visual_inventory(model);items=audit['robot_visuals']
    robot=ET.fromstring(model['robot_description'])
    transforms=urdf_transforms(robot,frame['q_rad'],geometry_context['grip_rad'])
    if (len(items)!=len(expected) or {x['model_visual_id'] for x in items}!=set(expected) or
            len({x['prim_path'] for x in items})!=len(items)):
        raise ValueError('FULL_ROBOT_VISUAL_INVENTORY_REQUIRED')
    peak=[0.,0.]
    for item in items:
        if (item['geometry_signature']!=expected[item['model_visual_id']] or item['semantic_class']!='robot' or
                not item['prim_path'].startswith(audit['robot_root_prim']+'/') or item['render_enabled'] is not True):
            raise ValueError('ROBOT_RENDER_GEOMETRY_CHANGED')
        link,index=item['model_visual_id'].rsplit(':',1)
        origin=robot.find(f"link[@name='{link}']").findall('visual')[int(index)].find('origin')
        local=np.eye(4)
        if origin is not None:
            local[:3,3]=np.array(origin.get('xyz','0 0 0').split(),float)
            local[:3,:3]=Rotation.from_euler('xyz',np.array(origin.get('rpy','0 0 0').split(),float)).as_matrix()
        expected_transform=transforms[link]@local;actual=rigid(item['T_base_visual'])
        error=[float(np.linalg.norm(expected_transform[:3,3]-actual[:3,3])),
               float(Rotation.from_matrix(expected_transform[:3,:3].T@actual[:3,:3]).magnitude())]
        peak=np.maximum(peak,error).tolist()
        if error[0]>.0008 or error[1]>.005:
            raise ValueError('ROBOT_RENDER_TRANSFORM_CHANGED')
    held=geometry_context['held_geometry']
    from held_geometry_inputs import nominal_definition,held_pieces
    definition=nominal_definition(held,model)
    if 'held_definition_ref' in audit and pinned_json(audit['held_definition_ref'])!=definition:
        raise ValueError('SEMANTIC_HELD_DEFINITION_CHANGED')
    pieces=[(np.asarray(x['size_m']),np.asarray(x['T_tool_piece']))
            for x in held_pieces(definition,geometry_context['attachment'])]
    items=audit['held_pieces']
    if {x['prim_path'] for x in items}&{x['prim_path'] for x in audit['robot_visuals']}:raise ValueError('DUPLICATE_RENDER_PRIM')
    if len(items)!=len(pieces) or len({x['prim_path'] for x in items})!=len(items):raise ValueError('HELD_BODY_AND_STUDS_REQUIRED')
    for item,(size,transform) in zip(items,pieces):
        # Matmul may differ by a few binary64 ULPs across NumPy/BLAS builds.
        # This is arithmetic replay allowance, not a physical pose tolerance.
        arithmetic=8*np.finfo(float).eps*max(1.,float(abs(transform).max()))
        if (item['semantic_class']!='held' or item['render_enabled'] is not True or
                not np.array_equal(np.asarray(item['size_m']),size) or
                not np.allclose(rigid(item['T_tool_piece']),transform,atol=arithmetic,rtol=0)):
            raise ValueError('HELD_BODY_STUD_ATTACHMENT_CHANGED')
    if set(audit['collision_only_visual_exceptions'])!=set(audit['collision_only_expected']):
        raise ValueError('COLLISION_ONLY_RENDER_SCOPE_REQUIRED')
    # The producer must enumerate collision-only links directly from the same
    # model, not merely claim a list of exceptions is complete.
    robot=ET.fromstring(model['robot_description'])
    expected={l.get('name') for l in robot.findall('link') if l.findall('collision') and not l.findall('visual')}
    if set(audit['collision_only_expected'])!=expected:raise ValueError('COLLISION_ONLY_MODEL_SCOPE_CHANGED')
    if expected:raise ValueError('COLLISION_ONLY_SENSOR_MASK_POLICY_NOT_IMPLEMENTED')
    return peak


def stationary_pose(pose,frame,paths=None):
    scope=pose['time_sync_scope']
    if scope not in ('STATIONARY_POST_RENDER_BRACKET_NOT_DYNAMIC_SOURCE_STAMP','DYNAMIC_SOURCE_STAMP_VERIFIED'):
        raise ValueError('EXPLICIT_IMAGE_TIME_SCOPE_REQUIRED')
    if scope=='DYNAMIC_SOURCE_STAMP_VERIFIED':
        proof=pinned_json(pose['source_tick_evidence'])
        if (paths is None or proof['scope']!='ACTUAL_SIM_RTX_SOURCE_TICK_STATE_TF' or
                proof['timeline_running'] is not True or pose['image_source_stamp_verified'] is not True):
            raise ValueError('DYNAMIC_SOURCE_TICK_EVIDENCE_REQUIRED')
        for key in ('session_id','clock_basis','clock_epoch','frame_seq','source_stamp_s','q_rad','T_base_tool','T_tool_camera_optical'):
            if proof[key]!=frame[key]:raise ValueError('DYNAMIC_IMAGE_STATE_TF_MISMATCH:'+key)
        if (proof['capture_source_sha256']!=pose['capture_source_sha256'] or
                proof['grip_rad']!=pose['grip_rad'] or proof['state_sequence']!=pose['state_sequence'] or
                pose['stamp_s']!=frame['source_stamp_s'] or pose['q_rad']!=frame['q_rad']):
            raise ValueError('DYNAMIC_POSE_SOURCE_MISMATCH')
        tick=proof['physics_step_index']
        if (type(tick) is not int or tick<0 or any(proof[k]!=tick for k in ('state_physics_step_index','tf_physics_step_index','image_physics_step_index')) or
                type(proof['renderer_frame_id']) is not int or proof['renderer_frame_id']<0):
            raise ValueError('DYNAMIC_SAME_SOURCE_TICK_REQUIRED')
        for key in ('depth','semantic_ids','capture_source'):
            if proof['source_sha256'][key]!=file_hash(paths[key]):raise ValueError('DYNAMIC_RAW_SOURCE_CHANGED:'+key)
        if proof['observation_wall_monotonic_s']!=frame['observation_wall_monotonic_s']:
            raise ValueError('DYNAMIC_WALL_OBSERVATION_MISMATCH')
        return
    stamps=[pose['before_stamp_s'],pose['after_stamp_s'],pose['stamp_s']]
    if not np.isfinite(stamps).all() or not stamps[0]<=stamps[2]<=stamps[1]:raise ValueError('STATIONARY_BRACKET_TIME_REQUIRED')
    if pose['image_source_stamp_verified'] is not False or pose['capture_source_sha256']=='':raise ValueError('STATIONARY_IS_NOT_DYNAMIC_CAPTURE')
    if max(abs(pose[k]-pose['grip_rad']) for k in ('before_grip_rad','after_grip_rad'))>1e-6:
        raise ValueError('NONSTATIONARY_GRIP_BRACKET')
