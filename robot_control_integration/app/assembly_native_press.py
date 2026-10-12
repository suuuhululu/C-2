"""Reviewed local ROBOT_GRIP pressure stage inside the single-writer workflow."""
import json
import math
from pathlib import Path
import time

from app.assembly_contact_alignment import prepare_contact, run_contact, validate_sample, still


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
    return policy


def native_press(driver,connection,plan,profile,travel,record,*,clock,sleep):
    policy=validate_native_press(plan,profile)
    c=json.loads((Path(__file__).resolve().parents[1]/'interfaces/assembly_contact_trial.json').read_text())
    c['mode']='REAL' if driver.mode=='REAL' else 'FAKE'
    c['connection'].update(connection)
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
    record('PRESS_SESSION',dict(native_force=True,force_n=35.,force_mode='ABSOLUTE',config=c))
    result=run_contact(driver,prepared,record,pressure_stages=(35.,),now=clock,sleep=sleep)
    limited=result['status']=='PRESS_ONLY_FORCE_LIMIT_REACHED_STOP_VERIFIED'
    loaded=(result['status']=='PRESS_ONLY_FORCE_RELEASED_REVIEW_REQUIRED' and
        result['observations'][-1]['measured_fz_n']>=35.-c['force_band_n'])
    if not (limited or loaded) or not all(result.get(k) is True for k in ('stopped','force_released','compliance_released')):
        raise RuntimeError('NATIVE_PRESS_NOT_VERIFIED:'+str(result.get('reason',result['status'])))
    final=driver.stillness() if hasattr(driver,'stillness') else driver.sample()
    result.update(status='NATIVE_FORCE_LIMIT_STOP_VERIFIED' if limited else 'NATIVE_FORCE_LOAD_HOLD_VERIFIED',
        final_sample=final,force_stop_n=35.,native_force_n=35.,force_mode='ABSOLUTE',
        stop=dict(requested=True,acknowledged=True,stillness_verified=True),assembly_completion=False)
    record('PRESS_RESULT',result)
    return result
