"""Shared held geometry and same-snapshot binding; CPU data only.

Nominal pieces come directly from object_boxes. Measured REAL dimensions
remain a separate visual/reference profile, never physical readiness.
"""
import json
from pathlib import Path
import numpy as np
from cumotion_geometry import object_boxes
import cumotion_geometry
from plan_only import digest
from prepare_cpu_model import file_hash,read_model_bundle
from sim_utils import rigid


def pinned(ref):
    path=Path(ref['path']).resolve(strict=True)
    if file_hash(path)!=ref['sha256']:raise ValueError('HELD_SOURCE_CHANGED')
    return json.loads(path.read_text())


def nominal_definition(obj,model):
    if model!=read_model_bundle(model['bundle_path']):raise ValueError('HELD_MODEL_CHANGED')
    if 'kinematic_alignment' in json.loads((Path(model['bundle_path'])/'MODEL_MANIFEST.json').read_text()):
        raise ValueError('REAL_ALIGNED_MODEL_IS_NOT_NOMINAL_HELD_PROFILE')
    geometry={k:obj[k] for k in ('id','size_m','studs','block')}
    pieces=[dict(kind='BODY' if i==0 else 'STUD',index=i,size_m=s.tolist(),T_block_piece=t.tolist())
            for i,(s,t) in enumerate(object_boxes(obj,np.eye(4)))]
    source=Path(cumotion_geometry.__file__).resolve()
    profile=dict(kind='ORIGINAL_NOMINAL_SIM_OBJECT_BOXES',source_path=str(source),source_sha256=file_hash(source),pieces=pieces)
    return dict(schema_version='held-geometry-definition/0.1',scope='NOMINAL_SIM_ONLY',units='m',
        frame_id='BLOCK_BODY_CENTRE',transform_convention='COLUMN_VECTORS_LOCAL_TO_PARENT',
        model_manifest_sha256=model['manifest_sha256'],geometry=geometry,profile=profile,profile_digest=digest(profile),
        execution_allowed=False,hardware_execution_allowed=False)


def bind_snapshot(definition,snapshot):
    if (definition['scope']!='NOMINAL_SIM_ONLY' or snapshot['source_kind']!='SIM_DEPTH' or
            snapshot['selected_id']!=definition['geometry']['id'] or snapshot['clock_basis']!='SIM_TIME' or
            snapshot['model_manifest_sha256']!=definition['model_manifest_sha256'] or
            snapshot['profile_digest']!=definition['profile_digest']):raise ValueError('HELD_SNAPSHOT_MODEL_PROFILE_MISMATCH')
    if (not isinstance(snapshot['session_id'],str) or not snapshot['session_id'] or
            type(snapshot['state_sequence']) is not int or snapshot['state_sequence']<0 or
            not np.isfinite(snapshot['stamp_s'])):raise ValueError('EXPLICIT_HELD_SNAPSHOT_REQUIRED')
    attachment=np.linalg.inv(rigid(snapshot['T_base_tcp']))@rigid(snapshot['T_base_block'])
    if 'recorded_attachment' in snapshot and not np.allclose(attachment,rigid(snapshot['recorded_attachment']),atol=1e-12,rtol=0):
        raise ValueError('SAME_SNAPSHOT_ATTACHMENT_MISMATCH')
    result=dict(schema_version='held-snapshot-binding/0.1',definition_digest=digest(definition),snapshot=snapshot,
        snapshot_digest=digest(snapshot),attachment_tcp_to_block=attachment.tolist(),
        tool_frame_id='GripperDA_v4_tcp',block_frame_id='BLOCK_BODY_CENTRE',units='m',
        execution_allowed=False,hardware_execution_allowed=False)
    result['digest']=digest(result);return result


def verify_binding(binding,definition,snapshot):
    if binding!=bind_snapshot(definition,snapshot):raise ValueError('HELD_SNAPSHOT_BINDING_CHANGED')
    return binding


def held_pieces(definition,attachment):
    return [dict(kind=x['kind'],index=x['index'],size_m=x['size_m'],
                 T_tool_piece=(rigid(attachment)@rigid(x['T_block_piece'])).tolist()) for x in definition['profile']['pieces']]


def verify_native_cubes(definition,binding,inventory,T_world_base):
    """Compare saved native cube matrices with whole body/stud boxes.

    Float32-export representation allowance is scaled separately for matrix
    columns and translation. It is not an attachment or physical tolerance.
    """
    verify_binding(binding,definition,binding['snapshot'])
    obj=inventory['geometry_context']['held_geometry'];root=obj['prim_path']+'/'
    if {k:obj[k] for k in ('id','size_m','studs','block')}!=definition['geometry']:
        raise ValueError('NATIVE_HELD_GEOMETRY_CHANGED')
    actual=[x for x in inventory['prims'] if x['prim_path'].startswith(root)]
    expected=held_pieces(definition,binding['attachment_tcp_to_block'])
    if len(actual)!=len(expected) or len({x['prim_path'] for x in actual})!=len(actual):raise ValueError('NATIVE_HELD_BODY_STUD_COUNT_CHANGED')
    world_tool=rigid(T_world_base)@rigid(binding['snapshot']['T_base_tcp']);remaining=list(actual);matched=[]
    epsilon=8*np.finfo(np.float32).eps
    for piece in expected:
        transform=world_tool@rigid(piece['T_tool_piece']);target=transform.copy();target[:3,:3]*=piece['size_m']
        tolerance=np.zeros((4,4));tolerance[:3,:3]=epsilon*np.asarray(piece['size_m'])[None,:]
        tolerance[:3,3]=epsilon*np.maximum(abs(target[:3,3]),.001);tolerance[3,:]=1e-12
        candidates=[]
        for item in remaining:
            matrix=np.asarray(item['T_world_prim'],float).copy()
            if item['type']!='Cube' or matrix.shape!=(4,4) or not np.isfinite(matrix).all():continue
            matrix[:3,:3]*=item['size']
            if item['visibility']!='invisible' and item['purpose']=='default' and np.all(abs(matrix-target)<=tolerance):
                candidates.append((item,float(np.max(abs(matrix-target)))))
        if len(candidates)!=1:raise ValueError('NATIVE_HELD_PIECE_TRANSFORM_OR_SIZE_MISMATCH')
        item,error=candidates[0];remaining.remove(item)
        matched.append(dict(**piece,prim_path=item['prim_path'],max_matrix_error=error))
    return dict(status='HELD_BODY_AND_ALL_STUDS_MATCHED',pieces=matched,representation_epsilon=epsilon,
        representation_scope='FLOAT32_USD_EXPORT_ONLY_NOT_PHYSICAL_MARGIN',profile_digest=definition['profile_digest'],
        snapshot_digest=binding['snapshot_digest'],full_robot_semantic_binding_verified=False,
        execution_allowed=False,hardware_execution_allowed=False)


def measured_outer_geometry(profile_ref,brick_type,*,measurement_pointer='',legacy_pitch_ref=None,declared_padding_m=None):
    """Explicit measured profile input; unknown pitch/uncertainty stays unknown.

    JSON pointer allows a source report/producer wrapper to preserve original
    measurements without inventing aliases or changing Rosbridge-owned files.
    """
    profile=pinned(profile_ref);measurement=profile;reported_profile=None
    if profile.get('schema')=='real-reported-block-profile/0.1':
        from isaac_sim.real_execution.held_attachment import pinned_profile
        reported_profile=pinned_profile(profile_ref['path'],profile_ref['sha256'])
        if measurement_pointer or legacy_pitch_ref is not None:raise ValueError('REPORTED_PROFILE_LAYOUT_CANNOT_BE_OVERRIDDEN')
        measurement=reported_profile['source_records'][0]['original_content']
    for key in measurement_pointer.strip('/').split('/') if measurement_pointer else []:
        key=key.replace('~1','/').replace('~0','~')
        measurement=measurement[int(key)] if isinstance(measurement,list) else measurement[key]
    if measurement['schema_version']!='round2-user-measurement-reference/1':raise ValueError('EXPLICIT_REPORTED_MEASUREMENT_SCHEMA_REQUIRED')
    if measurement['physical_gate_passed'] is not False or measurement['execution_allowed'] is not False:
        raise ValueError('MEASUREMENT_REFERENCE_IS_NOT_REAL_APPROVAL')
    nx,ny,nz=map(int,brick_type.split('x'))
    if nx not in (1,2,3) or ny not in (1,2,3) or nz!=1:raise ValueError('SUPPORTED_SINGLE_HEIGHT_BRICK_REQUIRED')
    d=measurement['reported_dimensions'];body_h=d['body_height_without_studs_mm']/1000;total=d['height_with_studs_mm']/1000
    stud_h=total-body_h;diameter=d['stud_diameter_mm']/1000
    size=[d[f'span_{n}_outer_length_mm']/1000 for n in (nx,ny)]+[body_h]
    if not np.isfinite(size+[stud_h,diameter]).all() or min(size+[stud_h,diameter])<=0:raise ValueError('VALID_MEASURED_OUTER_DIMENSIONS_REQUIRED')
    pitch=None;pieces=None
    if reported_profile is not None:
        pitch=reported_profile['studs']['pitch_m']
        legacy_pitch_ref=dict(**profile_ref,json_pointer='/studs',pitch_scope='LEGACY_NOMINAL_NOT_REMEASURED')
    elif legacy_pitch_ref is not None:
        legacy=pinned(legacy_pitch_ref)
        if legacy['pitch_scope']!='LEGACY_NOMINAL_NOT_REMEASURED':raise ValueError('EXPLICIT_LEGACY_PITCH_REFERENCE_REQUIRED')
        pitch=float(legacy['pitch_m'])
        if not np.isfinite(pitch) or pitch<=0:raise ValueError('POSITIVE_DECLARED_PITCH_REQUIRED')
    if pitch is not None:
        pieces=[dict(size_m=size,T_block_piece=np.eye(4).tolist(),kind='BODY')]
        for x in range(nx):
            for y in range(ny):
                local=np.eye(4);local[:3,3]=[(x-(nx-1)/2)*pitch,(y-(ny-1)/2)*pitch,(body_h+stud_h)/2]
                pieces.append(dict(size_m=[diameter,diameter,stud_h],T_block_piece=local.tolist(),kind='STUD_CYLINDER_CIRCUMSCRIBED_BOX'))
    if declared_padding_m is not None and (not np.isfinite(declared_padding_m) or declared_padding_m<0):raise ValueError('NONNEGATIVE_DECLARED_PADDING_REQUIRED')
    collision=None if pieces is None or declared_padding_m is None else [dict(p,size_m=(np.array(p['size_m'])+2*declared_padding_m).tolist()) for p in pieces]
    if reported_profile is not None:
        variant=reported_profile['brick_variants'][brick_type]
        if not np.allclose(variant['visual_reference_body_size_m'],size,atol=1e-15,rtol=0):raise ValueError('PROFILE_OUTER_GEOMETRY_CHANGED')
        if not np.allclose(variant['stud_centres_body_m'],[np.array(p['T_block_piece'])[:3,3] for p in pieces[1:]],atol=1e-15,rtol=0):
            raise ValueError('PROFILE_STUD_CENTRES_CHANGED')
    return dict(schema_version='measured-held-outer-reference/0.1',scope='REAL_REPORTED_DIMENSIONS_SEPARATE_FROM_NOMINAL_SIM',
        geometry_profile_id=reported_profile['profile_id'] if reported_profile is not None else None,geometry_profile_sha256=profile_ref['sha256'],
        profile_ref=profile_ref,measurement_pointer=measurement_pointer,measurement_digest=digest(measurement),brick_type=brick_type,
        units='m',frame_id='BLOCK_BODY_CENTRE',body_size_m=size,body_centre_above_bottom_m=body_h/2,
        stud_height_m=stud_h,stud_height_basis='TOTAL_MINUS_BODY_NOT_DIRECT_MEASUREMENT',stud_diameter_m=diameter,
        stud_centre_z_m=(body_h+stud_h)/2,stud_count=nx*ny,pitch_m=pitch,legacy_pitch_ref=legacy_pitch_ref,
        visual_reference_pieces=pieces,declared_collision_padding_m=declared_padding_m,collision_reference_pieces=collision,
        cylinder_box_containment='ABS_X_AND_Y_LE_DIAMETER_OVER_2_Z_WITHIN_HEIGHT_OVER_2',
        uncertainty=measurement['uncertainty'],certified_margin=False,tcp_to_brick_transform=measurement['pending']['tcp_to_brick_transform'],
        assembly_layer_increment_changed=False,gripper_or_taught_tcp_changed=False,real_planning_ready=False,
        execution_allowed=False,hardware_execution_allowed=False)


def prepare_geometry_anchor(scene_ref,state_ref,motion_ref,frame_ref,binding,model,history,output):
    """Fresh common-A geometry request with an explicit optimizer-rest gate.

    Preserve the established position-history SIM stop meaning for common A;
    never promote it to the stricter optimizer's q-only rest requirement.
    """
    from datetime import datetime,timezone
    from copy import deepcopy
    from capture_sim_scene import verified_stop
    from prepare_sim_snapshot import prepare_sim_snapshot
    from plan_only import prepare_files
    from prepare_cumotion_model import verify_request
    from sim_utils import matrix_pose,pose_matrix
    scene,state,motion,frame=[pinned(ref) for ref in (scene_ref,state_ref,motion_ref,frame_ref)]
    snapshot=binding['snapshot'];selected=next(o for o in scene['world_objects'] if o['id']==snapshot['selected_id'])
    definition=nominal_definition(selected,model);verify_binding(binding,definition,snapshot)
    if (scene['current']!=motion['latest_current'] or state['a_context']!=motion['context'] or
            frame['session_id']!=snapshot['session_id'] or frame['source_stamp_s']!=snapshot['stamp_s'] or
            frame['q_rad']!=snapshot['q_rad'] or not np.array_equal(rigid(frame['T_base_tool']),rigid(snapshot['T_base_tcp']))):
        raise ValueError('CURRENT_NATIVE_A_SNAPSHOT_MISMATCH')
    if (any(r['active_command_count']!=0 or r['pending_command_count']!=0 or
            set(r['contact_fingers'])!={'rg2_left_inner_finger','rg2_right_inner_finger'} for r in history) or
            history[-1]['stamp_s']!=snapshot['stamp_s'] or history[-1]['q_rad']!=snapshot['q_rad']):
        raise ValueError('CURRENT_NATIVE_HOLD_HISTORY_REQUIRED')
    rows=[dict(time_s=r['stamp_s'],q_rad=r['q_rad'],grip_rad=r['grip_rad']) for r in history]
    stop=verified_stop(rows,snapshot['q_rad']+[snapshot['grip_rad']])
    output=Path(output)
    if output.exists():raise ValueError('NEVER_OVERWRITE_NATIVE_GEOMETRY_ANCHOR')
    output.mkdir(parents=True)
    scene=deepcopy(scene);state=deepcopy(state)
    # This timestamp is archive record creation, never image generation time.
    for value in (scene,state):value.update(capture_id='native-held-geometry:'+binding['digest'],
        captured_at=datetime.now(timezone.utc).isoformat(),capture_time_scope='NORMALIZED_ARCHIVE_RECORD_TIME_SOURCE_SIM_STAMP_PRESERVED')
    scene['captured_at']=state['captured_at']
    world_base=rigid(snapshot['T_world_base']);scene['frame_alignment']['T_world_base']=world_base.tolist()
    for obj in scene['world_objects']:
        if obj['world_pose']['frame_id']!='world':raise ValueError('NATIVE_WORLD_FRAME_REQUIRED')
        obj['pose']=matrix_pose(np.linalg.inv(world_base)@rigid(pose_matrix(obj['world_pose'])))
        if obj['id']==snapshot['selected_id']:
            obj.update(role='HELD_BLOCK',pose=matrix_pose(rigid(snapshot['T_base_block'])),world_pose=matrix_pose(world_base@rigid(snapshot['T_base_block'])))
            obj['world_pose']['frame_id']='world'
    state.update(q_rad=snapshot['q_rad'],grip_rad=snapshot['grip_rad'],tcp_pose=matrix_pose(rigid(snapshot['T_base_tcp'])),
        attachment_tcp_to_block=snapshot.get('recorded_attachment',binding['attachment_tcp_to_block']),raw_joint_velocity_rad_s=history[-1]['v_rad_s'],
        calculation_scope='GEOMETRY_ALIGNMENT_ONLY_PENDING_OPTIMIZER_REST',
        observation_evidence=dict(source_refs=[scene_ref,state_ref,motion_ref,frame_ref],snapshot_binding=binding,
            source_stamp_s=snapshot['stamp_s'],clock_basis=snapshot['clock_basis'],stop_basis=stop,
            optimizer_rest_verified=False,holding_confirmed=True,stopped_verified=True,active_command_count=0,pending_command_count=0))
    for name,value in [('scene',scene),('state',state),('held_definition',definition),('held_binding',binding)]:
        (output/(name+'.json')).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    request=prepare_files(output/'common_A',motion,prepare_sim_snapshot(output/'scene.json',output/'state.json'),model['bundle_path'])
    verify_request(output/'common_A/TRANSPORT.request.yaml',allow_geometry_cpu=True,allow_fixture_cpu=True)
    return request
