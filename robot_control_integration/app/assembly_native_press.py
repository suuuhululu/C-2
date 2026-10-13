"""Reviewed local ROBOT_GRIP pressure stage inside the single-writer workflow."""
import json
import math
from pathlib import Path
import time

from app.assembly_contact_alignment import prepare_contact, run_contact, validate_sample, still, SEATING_Z_ABOVE_TOLERANCE_MM
from scripts.assembly_press_trial import press


def validate_native_press(plan,profile):
    policy=profile.get('native_press')
    if policy is None:return None
    if (not isinstance(policy,dict) or policy.get('enabled') is not True or
            not isinstance(policy.get('review_ref'),str) or not policy['review_ref'].strip() or
            policy.get('force_n')!=35. or profile['force_stop_n']!=35. or
            plan['mode']!='ROBOT_GRIP' or plan['assistance_kind'] not in ('NONE','HOLD') or
            plan['block']['brick_type'] not in ('2x2x1','2x3x1','1x2x1') or
            type(plan['settings'].get('turn_base_z_deg')) not in (int,float) or
            plan['settings']['turn_base_z_deg'] not in (0,90,-90)):
        raise ValueError('REVIEWED_NATIVE_35N_ROBOT_GRIP_REQUIRED')
    for key,upper in (('seek_above_reference_mm',20.),('hold_s',3.)):
        v=policy.get(key)
        if type(v) not in (float,int) or not math.isfinite(v) or not 0<v<=upper:
            raise ValueError('INVALID_NATIVE_PRESS_PARAMETER:'+key)
    if type(policy.get('alignment_trial',False)) is not bool:
        raise ValueError('EXPLICIT_ALIGNMENT_TRIAL_BOOLEAN_REQUIRED')
    return policy


def reaction_stop_press(driver,connection,plan,profile,travel,record,*,clock,sleep):
    # The current trial presses by descent and stops on measured reaction.
    # 35N is a STOP threshold, never a desired-force command or a hold target.
    goal=plan['settings']['reference_pose'][2]
    def emit(event,data):
        if event=='PRESS_SESSION':
            data.update(press_control='POSITION_DESCENT_REACTION_STOP',native_force=False,
                force_control_target_n=None,completion_force_metric='XYZ_FORCE_NORM',
                seating_z_upper_limit_mm=goal+SEATING_Z_ABOVE_TOLERANCE_MM,
                alignment_search=False)
        record('PRESS_THRESHOLD_RESULT' if event=='PRESS_RESULT' else event,data)
    result=press(driver,connection,emit,max_travel_mm=travel,force_stop_n=35.,
        velocity=profile.get('reaction_descent_velocity',profile['descent_velocity']),
        acceleration=profile.get('reaction_descent_acceleration',profile['descent_acceleration']),
        ik_fk_position_tolerance_mm=profile.get('ik_fk_position_tolerance_mm',.05),
        ik_fk_orientation_tolerance_deg=profile.get('ik_fk_orientation_tolerance_deg',.05),
        clock=clock,sleep=sleep)
    if result['status']!='FORCE_THRESHOLD_REACHED_STOP_VERIFIED':
        raise RuntimeError('PRESS_THRESHOLD_NOT_REACHED:'+result['status'])
    final=driver.stillness() if hasattr(driver,'stillness') else driver.sample()
    z_error=final['posx'][2]-goal
    xy_error=math.dist(final['posx'][:2],plan['settings']['reference_pose'][:2])
    seated=z_error<=SEATING_Z_ABOVE_TOLERANCE_MM and xy_error<=2.
    record('PRESS_SEATING_CHECK',dict(target_z_mm=goal,z_error_mm=z_error,xy_error_mm=xy_error,
        z_above_tolerance_mm=SEATING_Z_ABOVE_TOLERANCE_MM,lower_z_limit_enforced=False,
        seating_goal_verified=seated,sample=final,assembly_completion=False,
        diagnostic_only=True,release_blocked_by_height_or_xy=False))
    result.update(final_sample=final,seating_goal_verified=seated,
        release_after_verified_reaction_stop=True,completion_force_metric='XYZ_FORCE_NORM',
        press_control='POSITION_DESCENT_REACTION_STOP',force_control_target_n=None,
        force_control_active=False,alignment_trial=True)
    record('PRESS_RESULT',result)
    return result


def native_press(driver,connection,plan,profile,travel,record,*,clock,sleep):
    policy=validate_native_press(plan,profile)
    c=json.loads((Path(__file__).resolve().parents[1]/'interfaces/assembly_contact_trial.json').read_text())
    c['mode']='REAL' if driver.mode=='REAL' else 'FAKE'
    c['connection'].update(connection)
    if policy.get('alignment_trial',False):
        # Reaction descent validates feedback and stops at the measured 35N norm.
        # A free-force baseline belongs only to the separate native-force trial.
        return reaction_stop_press(driver,connection,plan,profile,travel,record,clock=clock,sleep=sleep)
    free=[driver.sample() for _ in range(3)]
    for s in free:
        validate_sample(s,c)
        if not still(s) or math.hypot(*s['wrench'][:3])>=c['free_force_max_n']:
            raise RuntimeError('NATIVE_PRESS_FREE_REFERENCE_REQUIRED')
    start=free[-1]
    c.update(reviewed=True,floor_z_mm=start['posx'][2]-travel,
        force_window_mm=plan['settings']['reference_pose'][2]+policy['seek_above_reference_mm']-(start['posx'][2]-travel),
        probe_force_n=30.,max_probes=1,velocity=[profile['descent_velocity']]*2,
        acceleration=[profile['descent_acceleration']]*2,
        reference=dict(posx=start['posx'],width_mm=start['gripper_width_mm'],
            captured_at_unix_s=time.time(),source='THIS_EXECUTION_TARGET_APPROACH',noncontact_verified=True))
    c['timing']['probe_timeout_s']=policy['hold_s']
    prepared=prepare_contact(c)
    if prepared['status']!='CONTACT_PLAN_READY':raise RuntimeError('NATIVE_PRESS_PLAN_NOT_READY')
    record('PRESS_SESSION',dict(native_force=True,force_n=35.,force_mode='ABSOLUTE',config=c,
        absolute_z_floor_enforced=True,seating_z_upper_limit_mm=None))
    tolerances=(profile.get('ik_fk_position_tolerance_mm',.05),profile.get('ik_fk_orientation_tolerance_deg',.05))
    result=run_contact(driver,prepared,record,pressure_stages=(35.,),ik_fk_tolerances=tolerances,now=clock,sleep=sleep)
    limited=(result['status']=='PRESS_ONLY_FORCE_LIMIT_REACHED_STOP_VERIFIED' and
        math.hypot(*result['force_limit_sample']['wrench'][:3])>=35.)
    loaded=(result['status']=='PRESS_ONLY_FORCE_RELEASED_REVIEW_REQUIRED' and
        result['observations'][-1]['measured_force_norm_n']>=35.)
    if not (limited or loaded) or not all(result.get(k) is True for k in ('stopped','force_released','compliance_released')):
        raise RuntimeError('NATIVE_PRESS_NOT_VERIFIED:'+str(result.get('reason',result['status'])))
    final=driver.stillness() if hasattr(driver,'stillness') else driver.sample()
    result.update(status='NATIVE_FORCE_LIMIT_STOP_VERIFIED' if limited else 'NATIVE_FORCE_LOAD_HOLD_VERIFIED',
        final_sample=final,force_stop_n=35.,native_force_n=35.,force_mode='ABSOLUTE',
        completion_force_metric='XYZ_FORCE_NORM',
        stop=dict(requested=True,acknowledged=True,stillness_verified=True),assembly_completion=False)
    record('PRESS_RESULT',result)
    return result
