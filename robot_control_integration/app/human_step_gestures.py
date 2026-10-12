"""Scoped local human-stage cues; shape permission is not assembly observation."""
import math
from copy import deepcopy

from app.assembly_motion import pose_error
from scripts.assembly_position_trial import guard

STAGES = {'HUMAN_ASSEMBLY_RECEIVE': ('OPEN_HAND', 2),
          'HUMAN_ASSEMBLY_ACK': ('THUMBS_UP', 0),
          'HUMAN_READY': ('THUMBS_UP', 2),
          'HUMAN_HOLD_READY': ('THUMBS_UP', 2),
          'HUMAN_PRESS_AND_HOLD_ACK': ('THUMBS_UP', 0)}


def validate_policy(plan, profile, session=None):
    config = plan['settings'].get('human_step_gestures')
    if config is None:
        return None
    z = config.get('wait_z_mm') if isinstance(config, dict) else None
    if (not isinstance(config, dict) or config.get('enabled') is not True or
            type(z) not in (int, float) or not math.isfinite(z) or
            z < profile['clearance_z_mm'] or
            z <= plan['settings']['reference_pose'][2]+profile['approach_offset_mm'] or
            not (plan['mode']=='HUMAN_ASSEMBLY' and plan['assistance_kind']=='MANUAL_ASSEMBLY' or
                 plan['mode']=='ROBOT_GRIP' and plan['assistance_kind'] in ('HOLD','PRESS_AND_HOLD'))):
        raise ValueError('EXPLICIT_HUMAN_STEP_ABOVE_APPROACH_POLICY_REQUIRED')
    if plan['mode']=='HUMAN_ASSEMBLY':
        width, bounds = config.get('handover_width_mm'), config.get('handover_feedback_range_mm')
        if (type(width) not in (int,float) or not math.isfinite(width) or
                not isinstance(bounds,list) or len(bounds)!=2 or
                any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds) or
                not 0<=bounds[0]<=width<=bounds[1]<=110):
            raise ValueError('HUMAN_HANDOVER_OPEN_WIDTH_REQUIRED')
    if session is not None and (session.get('provenance') not in ('LOCAL_OPERATOR_TRIAL','SYNTHETIC') or
            not session.get('human_step_gestures_review_ref')):
        raise ValueError('SCOPED_LOCAL_HUMAN_GESTURE_REVIEW_REQUIRED')
    if session is not None and session.get('automatic_stage_checks') is not None:
        from app.automatic_stage_trial import validate_policy as validate_routine_policy
        validate_routine_policy(session,plan)
    thumb=config.get('thumb_hold_seconds',.8)
    if type(thumb) not in (int,float) or not math.isfinite(thumb) or not .4<=thumb<=5:
        raise ValueError('INVALID_HUMAN_THUMB_HOLD_SECONDS')
    return config


def wait_stage(driver, plan, profile, kind, camera_poll):
    """Wait above target; callers distinguish readiness loss from post-release ACK timeout."""
    config = validate_policy(plan, profile, driver.session.value)
    pose, held = STAGES[kind]
    session = driver.session
    request = session.open_request('RECEIVE' if pose=='OPEN_HAND' else kind)
    first = deepcopy(driver.snapshot)
    expected = plan['settings']['reference_pose'][:2]+[config['wait_z_mm']]+first['posx'][3:]
    cue, watermark, source_watermark = None, None, None
    blocked, require_hold = False, False
    hold_ns = 400_000_000 if pose=='OPEN_HAND' else round(config.get('thumb_hold_seconds',.8)*1e9)

    def above_target(sample):
        guard(sample,driver.connection,profile['force_stop_n'],automatic=True,
              force_norm_limit=profile['force_stop_n'],required_gripper_status=held)
        width=sample['gripper_width_mm']
        if type(width) not in (int,float) or not math.isfinite(width) or not 0<=width<=110:
            raise RuntimeError('INVALID_HUMAN_WAIT_GRIPPER_WIDTH')
        mm,deg=pose_error(sample['posx'],expected)
        reasons=[]
        if sample['motion_status']!=0:reasons.append('MOTION_STATUS')
        if mm>1.:reasons.append('TARGET_POSITION')
        if deg>1.:reasons.append('TARGET_ORIENTATION')
        if reasons:
            session.record('HUMAN_WAIT_REJECTED',dict(kind=kind,reasons=reasons,
                target_distance_mm=mm,target_angle_deg=deg,sample=deepcopy(sample)))
            raise RuntimeError('HUMAN_GESTURE_WAIT_NOT_STILL_ABOVE_TARGET')

    def check(sample):
        nonlocal first, cue, watermark, source_watermark, blocked, require_hold
        above_target(sample)
        mm,deg=pose_error(sample['posx'],first['posx'])
        policy=session.value['stillness']
        linear=max(map(abs,sample['velx'][:3]));angular=max(map(abs,sample['velx'][3:]))
        if (mm>policy['position_mm'] or deg>policy['orientation_deg'] or
                linear>policy['linear_mm_s'] or angular>policy['angular_deg_s']):
            # A long wait can outlast the short stop window. Renew that window
            # inside the fixed target envelope before accepting another cue.
            session.record('HUMAN_WAIT_STABILITY_RECHECK',dict(kind=kind,
                position_drift_mm=mm,orientation_drift_deg=deg,
                linear_mm_s=linear,angular_deg_s=angular,sample=deepcopy(sample)))
            cue=None
            first=deepcopy(driver.stillness(during_stillness=above_target))
            session.record('HUMAN_WAIT_STABILITY_RECONFIRMED',dict(kind=kind,sample=first))
            return None
        row = camera_poll() if camera_poll else None
        if row is None:
            return None
        for key in ('execution_id','source_epoch',*session.binding):
            value = session.binding[key] if key in session.binding else session.value[key]
            if row.get(key)!=value:
                raise RuntimeError('HUMAN_GESTURE_CONTEXT_MISMATCH:'+key)
        if row.get('preview_request_id')!=request['request_id']:
            raise RuntimeError('HUMAN_GESTURE_REQUEST_MISMATCH')
        stamp=row.get('received_monotonic_ns');source=row.get('source_ns');now=driver.clock()*1e9
        if (type(stamp) is not int or stamp<request['opened_monotonic_s']*1e9 or
                not 0<=now-stamp<=session.value['frame_max_age_s']*1e9 or
                watermark is not None and stamp<=watermark or
                type(source) is not int or source<=0 or
                source_watermark is not None and source<=source_watermark):
            return None
        watermark,source_watermark=stamp,source
        hands=row.get('hands',[])
        held_ns=row.get('held_ns',0)
        same_shape=(isinstance(hands,list) and len(hands)==1 and isinstance(hands[0],dict) and
                    hands[0].get('pose')==pose)
        matching=(same_shape and row.get('continuity_estimate') is True and
                  type(held_ns) is int and held_ns>=hold_ns)
        event='OPEN_HAND_HELD_ORIENTATION_UNKNOWN' if pose=='OPEN_HAND' else 'THUMBS_UP_HELD'
        # Initial hold authorizes this request once. A fresh OPEN_HAND after a
        # preview timing reset still shows an open palm, not a withdrawn signal.
        if cue is not None and not same_shape:
            blocked=True
            if (isinstance(hands,list) and len(hands)==1 and isinstance(hands[0],dict) and
                    hands[0].get('pose') in ('FIST','THUMBS_UP','L')):
                require_hold=True
            return None
        if (cue is not None and same_shape and (not require_hold or matching) or
                matching and row.get('candidate_event')==event):
            cue=deepcopy(row)
            blocked,require_hold=False,False
        return None if blocked else cue

    def receiving_monitor(sample):
        deadline=min(request['deadline_monotonic_s'],driver.clock()+1.)
        waiting=False
        while True:
            session.check()
            if driver.clock()>request['deadline_monotonic_s']:
                raise TimeoutError('HUMAN_RECEIVING_CUE_REACQUIRE_TIMED_OUT')
            check(sample)
            if (cue is not None and not blocked and
                    0<=driver.clock()*1e9-cue['received_monotonic_ns']<=session.value['frame_max_age_s']*1e9):
                if waiting:session.record('HUMAN_RECEIVING_CUE_REACQUIRED',dict(request_id=request['request_id']))
                return
            if not waiting:
                session.record('HUMAN_RECEIVING_CUE_REACQUIRE_WAIT',dict(request_id=request['request_id'],max_wait_s=1.))
                waiting=True
            if driver.clock()>=deadline:
                raise TimeoutError('HUMAN_RECEIVING_CUE_REACQUIRE_TIMED_OUT')
            driver.sleep(.05)
            sample=driver.sample()

    keep_request=False
    try:
        while driver.clock()<=request['deadline_monotonic_s']:
            session.check()
            if check(driver.sample()) is not None:
                session.record('LOCAL_HUMAN_STAGE_GESTURE',dict(kind=kind,candidate=cue,
                    request_id=request['request_id'],verified_gesture=False,
                    authorization='EXPLICIT_LOCAL_OPERATOR_POLICY',assembly_completion=False))
                if pose=='OPEN_HAND':
                    driver.human_receive_monitor=receiving_monitor
                    keep_request=True
                return True
            driver.sleep(.05)
        session.record('HUMAN_GESTURE_WAIT_TIMED_OUT',dict(kind=kind,assembly_completion=False))
        return False
    finally:
        if not keep_request:
            session.close_request()
