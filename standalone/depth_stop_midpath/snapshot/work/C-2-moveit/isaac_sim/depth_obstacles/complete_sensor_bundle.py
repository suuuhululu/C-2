"""Package validated raw SIM capture for CPU replay; no stop/prior approval."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n')


def package(raw,model_path,output,source_root,*,state_required=True):
    from prepare_cpu_model import read_model_bundle
    from bounded_sim_evidence import published_calibration
    from depth_obstacle_envelope import replay_candidates,verify_sim_stop
    from isaac_sim.depth_obstacles.projection import project_frame
    raw,output,source_root=map(lambda p:Path(p).resolve(),(raw,output,source_root))
    if json.loads((raw/'inventory_binding_result.json').read_text())['status']!='ORIGINAL_MODEL_AND_NATIVE_HELD_PIECES_VERIFIED':
        raise ValueError('Native model/held verification required before packaging')
    model=read_model_bundle(model_path);output.mkdir(exist_ok=False)
    names=['frame.json','depth.npy','semantic_ids.npy','semantic_info.json','self_mask.npy','held_mask.npy','obstacle_mask.npy',
        'mask_audit.json','pose.json','limits.json','capture_source.py','capture_profile.json','camera_params.json','stop_evidence.json',
        'state_draft.json','geometry_context.json','held.definition.json','held.snapshot_binding.json','held.piece_audit.json']
    if not state_required:names=[name for name in names if name not in ('stop_evidence.json','state_draft.json')]
    if (raw/'source_tick.receipt.json').is_file():names.append('source_tick.receipt.json')
    for name in names:(output/name).write_bytes((raw/name).read_bytes())
    (output/'packaging_source.py').write_bytes(Path(__file__).read_bytes())
    profile=json.loads((output/'capture_profile.json').read_text());params=json.loads((output/'camera_params.json').read_text())
    intr=profile['intrinsics'];W,H=intr['width'],intr['height']
    uv=np.array([[0,0],[W-1,0],[0,H-1],[W-1,H-1],[W//2,H//2]],float)
    projection=np.array(params['cameraProjection']).reshape(4,4).T
    clip=np.column_stack([2*(uv[:,0]+.5)/W-1,1-2*(uv[:,1]+.5)/H,np.zeros(len(uv)),np.ones(len(uv))])
    camera=(np.linalg.inv(projection)@clip.T).T
    directions=(camera[:,:3]/camera[:,3,None])*[1,-1,-1]
    directions/=np.linalg.norm(directions,axis=1)[:,None]
    error=np.linalg.norm(directions[:,:2]/directions[:,2,None]-(uv-[intr['cx'],intr['cy']])/[intr['fx'],intr['fy']],axis=1)
    messages=source_root/'local_records/real_execution_20261014/realsense_ingress01/live_capture.json'
    calibration=dict(profile=dict(path=str(output/'capture_profile.json'),sha256=sha(output/'capture_profile.json')),
        published_messages=dict(path=str(messages),sha256=sha(messages)),source_root=str(source_root),
        model_urdf_sha256=sha(Path(model['bundle_path'])/'robot.urdf'),
        capture_source_sha256=sha(output/'capture_source.py'),
        ray_validation=dict(scope='SIM_RENDERER_PIXEL_RAY_VALIDATION',profile_sha256=sha(output/'capture_profile.json'),
            capture_source_sha256=sha(output/'capture_source.py'),pixel_uv=uv.tolist(),renderer_optical_directions=directions.tolist(),
            max_normalized_ray_error=float(error.max()+64*np.finfo(float).eps),
            basis='INVERSE_RECORDED_RENDERER_CAMERA_PARAMS_PROJECTION_PIXEL_CENTER_NOT_INTRINSIC_REPLAY',
            camera_params_sha256=sha(output/'camera_params.json'),pixel_coordinate_convention='INTEGER_UV_RENDER_CENTER_PLUS_HALF'))
    save(output/'calibration.json',calibration)
    frame=json.loads((output/'frame.json').read_text())
    published_calibration(frame,dict(path=str(output/'calibration.json'),sha256=sha(output/'calibration.json')),model)
    # Status changes are supported by actual mesh/pose/semantic checks and are
    # confined to a derived bundle. Original capture files remain unchanged.
    frame.update(self_mask_status='VALIDATED_SIM',held_mask_status='VALIDATED_SIM')
    save(output/'frame.json',frame)
    depth=np.load(output/'depth.npy',allow_pickle=False);obstacle=np.load(output/'obstacle_mask.npy',allow_pickle=False)
    own=np.load(output/'self_mask.npy',allow_pickle=False);held=np.load(output/'held_mask.npy',allow_pickle=False)
    candidates=project_frame(frame,np.where(obstacle,depth,np.nan),own,held,now_s=frame['received_stamp_s'],
        limits=json.loads((output/'limits.json').read_text()))
    save(output/'candidates.json',candidates)
    mapping=dict(frame='frame.json',depth='depth.npy',semantic_ids='semantic_ids.npy',semantic_info='semantic_info.json',
        self_mask='self_mask.npy',held_mask='held_mask.npy',obstacle_mask='obstacle_mask.npy',mask_audit='mask_audit.json',
        pose='pose.json',candidates='candidates.json',limits='limits.json',capture_source='capture_source.py',calibration='calibration.json')
    completion=dict(status='COMPLETE',source_kind='SIM_DEPTH',session_id=frame['session_id'],
        capture_source_sha256=sha(output/'capture_source.py'),frames=[dict(frame_seq=frame['frame_seq'],frame_sha256=sha(output/'frame.json'))],
        scope='SENSOR_FRAME_MODEL_CALIBRATION_MASK_BUNDLE_ONLY_NOT_STOP_PRIOR_OR_EXECUTION',hardware_execution_allowed=False)
    save(output/'completion.json',completion)
    manifest=dict(schema='single-object-depth-evidence/0.1',source_kind='SIM_DEPTH',annotator='distance_to_image_plane',
        mask_evidence_kind='SEMANTIC_FULL_SCENE_BINDING',calibration_scope=frame['calibration_scope'],
        completion=dict(path=str(output/'completion.json'),sha256=sha(output/'completion.json')),
        files={key:dict(path=name,sha256=sha(output/name)) for key,name in mapping.items()},
        packaging_source_sha256=sha(output/'packaging_source.py'),execution_allowed=False,hardware_execution_allowed=False)
    save(output/'manifest.json',manifest)
    spec=dict(folder=str(output),manifest_sha256=sha(output/'manifest.json'),capture_source_kind='SIM_DEPTH',
        capture_source_sha256=sha(output/'capture_source.py'),source_frames={k:frame[k] for k in ('base_frame_id','tool_frame_id','optical_frame_id')})
    save(output/'evidence_spec.json',spec)
    context=json.loads((output/'geometry_context.json').read_text())
    replay_candidates(spec,model,context,now_s=frame['received_stamp_s'])
    if not state_required:
        stop=dict(status='NOT_REVIEWED',reason='SEPARATE_CURRENT_NATIVE_OWNER_STOP_REQUIRED_NO_ARCHIVE_STATE_COPY')
    else:
        state=json.loads((output/'state_draft.json').read_text())
        stop_limits=dict(min_verified_stop_duration_s=.5,max_abs_velocity_rad_s=.02,max_abs_acceleration_rad_s2=.7)
        try:
            verify_sim_stop(state,model,stop_limits);stop=dict(status='RAW_STOP_CHECK_PASSED',limits=stop_limits)
        except ValueError as exc:stop=dict(status='HOLD',reason=str(exc),limits=stop_limits)
        except KeyError as exc:
            stop=dict(status='HOLD',reason='STOP_READER_REQUIRED_FIELD_MISSING:'+str(exc.args[0]),limits=stop_limits)
    save(output/'stop_consumer_check.json',stop)
    missing=['DECLARED_POINT_POSE_SPEED_LATENCY_PRIOR','OBSTACLE_RESPONSE_HOLD_CAPTURE','NATIVE_REPLAN_RESUME_EXECUTION']
    if stop['status']!='RAW_STOP_CHECK_PASSED':missing.append('NATIVE_STOP_METHOD_UNCERTAINTY_METADATA_OR_NUMERIC_REST')
    result=dict(status='SENSOR_BUNDLE_REPLAYED_CPU',visible_pixels=candidates['valid_pixels'],stop=stop,
        missing=missing,optimizer_rest_projection='NOT_ADMITTED_NONZERO_NATIVE_V_A_RETAINED',
        hardware_execution_allowed=False,execution_allowed=False,prior_assumptions_generated=False,
        raw_capture_folder=str(raw),raw_frame_sha256=sha(raw/'frame.json'),derived_frame_sha256=sha(output/'frame.json'),
        original_capture_modified=False)
    save(output/'bundle_result.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('raw','model','output','source-root'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(package(args.raw,args.model,args.output,args.source_root),indent=2))
