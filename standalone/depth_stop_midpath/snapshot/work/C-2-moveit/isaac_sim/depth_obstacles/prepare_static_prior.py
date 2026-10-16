"""Freeze a declared current SIM static prior; no worker/job/execute approval."""
import json
import math
from pathlib import Path
from .live_sensor_bundle import pin,save


def prepare(run,sensor,policy_path,output):
    run,sensor,output=map(Path,(run,sensor,output));output.mkdir(exist_ok=False)
    frame=json.loads((sensor/'frame.json').read_text());pose=json.loads((sensor/'pose.json').read_text())
    scenario=json.loads((run/'moving_obstacle.script.json').read_text())
    policy=json.loads(Path(policy_path).read_text())
    if scenario['scope']!='EXPLICIT_CURRENT_STATIC_SIM_20MM_CUBE_ACTIVATION' or scenario['speed_upper_m_s']!=0:
        raise ValueError('ACTUAL_STATIC_SCENARIO_REQUIRED')
    if any(v['live_scene_motion_kind']!='STATIC_OBSTACLE' for v in (frame,pose)) or frame['world_revision']!=pose['world_revision']:
        raise ValueError('ACTUAL_FRAME_POSE_STATIC_BINDING_REQUIRED')
    with (run/'moving_obstacle.motion.jsonl').open() as stream:
        rows=[json.loads(line) for line in stream if line.strip()]
    if len(rows)<2 or any(b['stamp_s']<=a['stamp_s'] for a,b in zip(rows,rows[1:])) or any(r['position_world_m']!=rows[0]['position_world_m'] for r in rows):
        raise ValueError('ACTUAL_ACTIVATED_STATIC_WORLD_AUDIT_REQUIRED')
    # Positions are used only to audit the source's fixed-world assumption.
    # Geometry estimators receive raw Depth; no GT coordinates enter this prior.
    save(output/'source_motion_audit.json',dict(scope='FIXED_WORLD_AUDIT_NO_PLANNER_COORDINATES',samples=len(rows),first_stamp_s=rows[0]['stamp_s'],last_stamp_s=rows[-1]['stamp_s'],constant_position_verified=True,scenario_source=pin(run/'moving_obstacle.script.json')))
    assumption=dict(scope='DECLARED_CURRENT_SIM_FIXED_WORLD_SOURCE_NOT_REAL_OR_GT_POSE',source_session_id=frame['session_id'],clock_epoch=frame['clock_epoch'],obstacle_id='Dynamic_native_moving_cube',world_revision=frame['world_revision'],motion_disabled=True,fixed_world_geometry=True,scenario_source=pin(run/'moving_obstacle.script.json'))
    fields=('point_error_m','pose_translation_error_m','pose_rotation_error_rad','max_sensor_to_use_delay_s','min_visible_pixels','min_pixel_span','max_occlusion_s','max_latest_observation_age_s','max_trajectory_duration_s','apply_stop_margin_s','max_sensor_to_apply_wall_s')
    prior=dict(scope='DECLARED_SIM_SINGLE_OBJECT_BOUNDS_NOT_REAL',basis_ref='EXPLICIT_CURRENT_STATIC_SIM_TRIAL_DECLARATION',usage_scope='LIVE_DYNAMIC_SIM_CONDITIONAL_ENVELOPE',obstacle_id=assumption['obstacle_id'],size_upper_m=scenario['size_m'],max_speed_m_s=0.,live_scene_motion_kind='STATIC_OBSTACLE',world_revision=frame['world_revision'],static_scene_assumption=assumption,**{k:policy[k] for k in fields})
    calibration=json.loads((sensor/'calibration.json').read_text())
    sensor_limits=json.loads((sensor/'limits.json').read_text());intr=frame['intrinsics']
    max_x=max(abs((u-intr['cx'])/intr['fx']) for u in (0,intr['width']-1))
    max_y=max(abs((v-intr['cy'])/intr['fy']) for v in (0,intr['height']-1))
    max_sensor_range=sensor_limits['max_depth_m']*math.sqrt(1+max_x*max_x+max_y*max_y)
    ray_error=calibration['ray_validation']['max_normalized_ray_error']*max_sensor_range
    prior['point_error_m']=policy['point_error_m']+ray_error
    save(output/'point_error_basis.json',dict(scope='CONSERVATIVE_RECORDED_RENDERER_RAY_ERROR_PLUS_DECLARED_SIM_RESIDUAL',
        calibration=pin(sensor/'calibration.json'),sensor_limits=pin(sensor/'limits.json'),frame=pin(sensor/'frame.json'),
        max_sensor_range_m=max_sensor_range,normalized_ray_error=calibration['ray_validation']['max_normalized_ray_error'],
        renderer_ray_error_bound_m=ray_error,declared_residual_m=policy['point_error_m'],point_error_m=prior['point_error_m'],
        calculation='declared_residual + recorded_ray_error * max_range_over_clipped_pinhole_sensor_domain',
        scope_limits='Conditional nominal SIM error model; increases obstacle uncertainty, never relaxes a STOP/pose acceptance criterion'))
    basis=dict(prior,scope='DECLARED_SINGLE_SIM_OBJECT_AND_ERROR_MODEL',source_kind='SIM_DEPTH',policy_source=pin(policy_path),point_error_basis=pin(output/'point_error_basis.json'),source_motion_audit=pin(output/'source_motion_audit.json'),scope_limits=policy['basis'])
    save(output/'basis.json',basis);prior['basis_evidence']=pin(output/'basis.json');save(output/'prior.json',prior)
    return pin(output/'prior.json')
