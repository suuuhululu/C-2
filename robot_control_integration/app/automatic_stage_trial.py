"""Opt-in local trial checks; sensor permission is never a human seating claim."""
import math
from copy import deepcopy
from app.assembly_motion import pose_error

KINDS = {'START_PICKUP','START_FULL','START_APPROACH','START_CONTACT','START_HUMAN-WAIT','START_HUMAN-ACK','PICKUP_ALIGNMENT','GRASP_CONFIRMED',
         'START_HANDOVER','START_ASSEMBLE-HELD','ALIGNMENT_AND_PARALLEL','FULL_SEATING','RELEASE'}


def validate_policy(session, plan):
    policy = session.get('automatic_stage_checks')
    if policy is None:return None
    human = plan['settings'].get('human_step_gestures', {})
    human_routine = (isinstance(human,dict) and human.get('enabled') is True and
        bool(session.get('human_step_gestures_review_ref')) and
        (plan['mode']=='HUMAN_ASSEMBLY' and plan['assistance_kind']=='MANUAL_ASSEMBLY' or
         plan['mode']=='ROBOT_GRIP' and plan['assistance_kind']=='HOLD'))
    if (not isinstance(policy,dict) or policy.get('enabled') is not True or
            not isinstance(policy.get('review_ref'),str) or not policy['review_ref'].strip() or
            policy.get('block') != plan['block'] or policy.get('release_after_contact_stop') is not True or
            session.get('provenance') not in ('LOCAL_OPERATOR_TRIAL','SYNTHETIC') or
            not (plan['mode']=='ROBOT_GRIP' and plan['assistance_kind']=='NONE' or human_routine) or
            plan['settings'].get('turn_base_z_deg') != 0):
        raise ValueError('EXPLICIT_SCOPED_AUTOMATIC_STAGE_TRIAL_REQUIRED')
    return policy


def check_stage(driver, kind, plan, profile, sample):
    if validate_policy(driver.session.value,plan) is None:
        raise RuntimeError('AUTOMATIC_STAGE_POLICY_NOT_ENABLED')
    if kind not in KINDS:raise RuntimeError('AUTOMATIC_STAGE_NOT_SUPPORTED:'+kind)
    status = 0 if kind in ('START_PICKUP','START_FULL','START_HUMAN-ACK','PICKUP_ALIGNMENT') else 2
    width=sample['gripper_width_mm']
    if (sample['gripper_status']!=status or type(width) not in (int,float) or
            not math.isfinite(width) or not 0<=width<=110):
        raise RuntimeError('AUTOMATIC_STAGE_GRIPPER_NOT_VERIFIED')
    settings=plan['settings']; expected=None
    if kind in ('START_PICKUP','START_FULL'):
        # Opening is the next action. Its clearance is checked before slot descent.
        if driver.session.value.get('automatic_start_pose') is not None:
            expected=driver.session.value['automatic_start_pose']
    if kind in ('START_HUMAN-WAIT','START_HUMAN-ACK'):
        expected=driver.session.value.get('automatic_start_pose')
        if expected is None:raise RuntimeError('HUMAN_WAIT_START_POSE_REQUIRED')
    if kind in ('START_APPROACH','START_CONTACT'):
        expected=driver.session.value.get('automatic_start_pose')
        if expected is None:raise RuntimeError('HELD_APPROACH_START_POSE_REQUIRED')
    if kind=='PICKUP_ALIGNMENT':
        bounds=settings['pickup_start_open_range_mm']
        if not bounds[0]<=width<=bounds[1]:raise RuntimeError('AUTOMATIC_PICKUP_NOT_OPEN')
        expected=settings['pickup_pose'].copy()
        expected[2]=max(profile['clearance_z_mm'],settings['reference_pose'][2]+profile['approach_offset_mm'])
    elif kind in ('GRASP_CONFIRMED','START_HANDOVER'):
        expected=settings['pickup_pose']
    elif kind=='ALIGNMENT_AND_PARALLEL':
        grasp=driver.trial_grasp_reference
        if grasp is None and driver.session.value.get('allowed_trial_phase')=='contact' and driver.session.value.get('alignment_evidence_ref'):
            grasp=driver.session.value.get('automatic_start_pose')
        if grasp is None:raise RuntimeError('THIS_EXECUTION_GRASP_OR_REVIEWED_CONTACT_POSE_REQUIRED')
        expected=settings['reference_pose'][:3]+grasp[3:]
        expected[2]+=profile['approach_offset_mm']
    if expected is not None:
        mm,deg=pose_error(sample['posx'],expected)
        if mm>1. or deg>1.:raise RuntimeError('AUTOMATIC_STAGE_POSE_MISMATCH')
    if kind=='ALIGNMENT_AND_PARALLEL' and driver.trial_grasp_reference is None:
        driver.trial_grasp_reference=deepcopy(grasp)
    contact=None
    if kind in ('FULL_SEATING','RELEASE'):
        contact=driver.last_contact_result
        native=(contact and contact.get('status') in ('NATIVE_FORCE_LIMIT_STOP_VERIFIED','NATIVE_FORCE_LOAD_HOLD_VERIFIED') and
            contact.get('native_force_n')==35. and contact.get('force_mode')=='ABSOLUTE' and
            contact.get('force_released') is True and contact.get('compliance_released') is True)
        if (not contact or not (contact.get('status')=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED' or native) or
                any(contact.get('stop',{}).get(k) is not True for k in ('requested','acknowledged','stillness_verified')) or
                contact.get('force_stop_n')!=profile['force_stop_n']):
            raise RuntimeError('AUTOMATIC_RELEASE_REQUIRES_THIS_EXECUTION_CONTACT_STOP')
        mm,deg=pose_error(sample['posx'],contact['final_sample']['posx'])
        if mm>1. or deg>1.:raise RuntimeError('AUTOMATIC_CONTACT_POSE_CHANGED')
        reference=settings['reference_pose'][:2]+[sample['posx'][2]]+driver.trial_grasp_reference[3:]
        mm,deg=pose_error(sample['posx'],reference)
        if mm>1. or deg>1.:raise RuntimeError('AUTOMATIC_CONTACT_TARGET_DRIFT')
    return dict(kind=kind,decision='CONTINUE',basis='LOCAL_OPERATOR_AUTHORIZED_SENSOR_POLICY',
                sample=deepcopy(sample),contact_stop_verified=contact is not None,
                operator_confirmation=False,assembly_completion=False,physical_verified=False)
