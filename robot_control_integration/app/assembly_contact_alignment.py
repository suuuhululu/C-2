"""Bounded local contact trials. No transport, grip commands or seating commitment.

The controller owns compliance/force response. PC supervision probes one pose at a
time and compares depth at similar normal load. It never estimates a unique block
pose from one wrench. Timed software guards are not a safety-rated controller or
an independent watchdog; lost PC/controller connectivity needs the onsite stop.
"""
from copy import deepcopy
import math
import time
import warnings

import numpy as np
from scipy.spatial.transform import Rotation

from app.assembly_motion import pose_error, vector
from app.contracts import _integer, _object

FIELDS = ("schema_version", "mode", "connection", "reference", "floor_z_mm", "reviewed",
    "probe_force_n", "force_band_n", "raw_force_stop_n", "raw_moment_stop_nm", "free_force_max_n",
    "stiffness", "transition_s", "force_window_mm", "xy_limit_mm", "rotation_limit_deg", "max_joint_step_deg",
    "xy_step_mm", "rotation_step_deg", "improvement_mm", "repeatability_mm", "width_drift_mm",
    "baseline_return_n", "position_tolerance_mm", "orientation_tolerance_deg", "velocity",
    "acceleration", "rounds", "max_probes", "timing", "parameter_source")
TIMING = ("service_timeout_s", "sample_max_duration_s", "poll_interval_s", "motion_timeout_s",
          "stop_timeout_s", "probe_timeout_s", "session_timeout_s", "reference_max_age_s")
SEATING_Z_ABOVE_TOLERANCE_MM = 10.


def positive(number, name):
    if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name}: positive finite number required")
    return float(number)


def prepare_contact(value, *, utc=time.time):
    c = deepcopy(_object(value, FIELDS, "contact trial"))
    if type(c["schema_version"]) is not int or c["schema_version"] != 1 or c["mode"] not in ("FAKE", "REAL"):
        raise ValueError("EXPLICIT_CONTACT_MODE_AND_VERSION_REQUIRED")
    from app.assembly_motion import CONNECTION
    _object(c["connection"], CONNECTION, "connection")
    _integer(c["connection"]["ros_domain_id"], 0, 232, "domain")
    import re
    if not isinstance(c["connection"]["robot_id"], str) or not re.fullmatch(r"[A-Za-z0-9_]+", c["connection"]["robot_id"]):
        raise ValueError("INVALID_ROBOT_ID")
    if any(not isinstance(c["connection"][k], str) or not c["connection"][k]
           for k in ("tcp", "tool", "gripper_ip")):
        raise ValueError("INVALID_CONNECTION")
    if type(c["reviewed"]) is not bool:
        raise ValueError("REVIEW_FLAG_MUST_BE_BOOLEAN")
    scalar = set(FIELDS)-{"schema_version", "mode", "connection", "reference", "floor_z_mm",
                          "reviewed", "stiffness", "velocity", "acceleration", "rounds",
                          "max_probes", "timing", "parameter_source", "transition_s", "raw_moment_stop_nm"}
    for k in scalar:
        c[k] = positive(c[k], k)
    if c["raw_moment_stop_nm"] is not None:
        c["raw_moment_stop_nm"]=positive(c["raw_moment_stop_nm"],"raw_moment_stop_nm")
    if type(c["transition_s"]) not in (int, float) or not math.isfinite(c["transition_s"]) or not 0 <= c["transition_s"] <= 1:
        raise ValueError("TRANSITION_TIME_MUST_BE_WITHIN_ZERO_AND_ONE")
    c["transition_s"]=float(c["transition_s"])
    for k in ("stiffness", "velocity", "acceleration"):
        c[k] = vector(c[k], 6 if k == "stiffness" else 2, k)
        if min(c[k]) <= 0:
            raise ValueError(f"{k}: positive components required")
    _object(c["timing"], TIMING, "timing")
    for k in TIMING:
        c["timing"][k] = positive(c["timing"][k], k)
    _integer(c["rounds"], 1, 20, "rounds")
    _integer(c["max_probes"], 1, 250, "max_probes")
    if not (c["probe_force_n"]+c["force_band_n"] < c["raw_force_stop_n"] <= 35
            and c["force_band_n"] < c["probe_force_n"] and c["transition_s"] <= 1
            and c["xy_step_mm"] <= c["xy_limit_mm"] <= 3
            and c["rotation_step_deg"] <= c["rotation_limit_deg"] <= 6
            and c["max_joint_step_deg"] <= 10
            and c["free_force_max_n"] < c["raw_force_stop_n"]
            and c["position_tolerance_mm"] < c["force_window_mm"]):
        raise ValueError("CONTACT_PARAMETER_LIMITS_INVALID")
    t=c["timing"]
    if max(t["service_timeout_s"],t["sample_max_duration_s"],t["poll_interval_s"]) >= min(t["stop_timeout_s"],t["probe_timeout_s"],t["motion_timeout_s"]):
        raise ValueError("QUERY_WINDOW_EXCEEDS_CONTROL_TIMEOUT")
    missing=[]
    if not c["reviewed"]: missing.append("reviewed")
    if c["floor_z_mm"] is None: missing.append("floor_z_mm")
    elif type(c["floor_z_mm"]) not in (int,float) or not math.isfinite(c["floor_z_mm"]):
        raise ValueError("INVALID_ABSOLUTE_Z_FLOOR")
    if c["reference"] is None: missing.append("reference")
    else:
        r=_object(c["reference"], ("posx","width_mm","captured_at_unix_s","source","noncontact_verified"),"reference")
        r["posx"]=vector(r["posx"],6,"reference pose")
        positive(r["width_mm"],"reference width")
        positive(r["captured_at_unix_s"],"capture time")
        if r["noncontact_verified"] is not True: missing.append("reference.noncontact_verified")
        age=utc()-r["captured_at_unix_s"]
        if not 0 <= age <= t["reference_max_age_s"]: missing.append("reference.expired")
        if c["floor_z_mm"] is not None and r["posx"][2]-c["floor_z_mm"] <= c["force_window_mm"]:
            raise ValueError("TAUGHT_NONCONTACT_Z_MUST_EXCEED_FLOOR_PLUS_FORCE_WINDOW")
    return dict(status="CONTACT_PLAN_READY" if not missing else "NOT_READY", missing=missing,
                config=c, max_descent_mm=None if missing else c["reference"]["posx"][2]-c["floor_z_mm"],
                gripper_commands=0, assembled=False)


def correction_pose(reference, q):
    """Base-frame XYZ corrections and SO(3) rotation about the active TCP.

    Rotation is NOT an Euler-angle increment and does not assume a block contact
    pivot coincides with TCP. The first trial uses a reviewed small local envelope.
    """
    p=vector(reference,6,"reference");q=vector(q,5,"correction")
    rot=Rotation.from_rotvec(np.deg2rad(q[2:]))*Rotation.from_euler("ZYZ",p[3:],degrees=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # equivalent ZYZ at pole; compare matrices
        angles=rot.as_euler("ZYZ",degrees=True).tolist()
    return [p[0]+q[0],p[1]+q[1],p[2],*angles]


def neighbours(q, steps, config):
    bounds=[config["xy_limit_mm"]]*2+[config["rotation_limit_deg"]]*3
    for axis in range(5):
        for sign in (-1,1):
            candidate=q.copy();candidate[axis]+=sign*steps[axis]
            if all(abs(v)<=b+1e-10 for v,b in zip(candidate,bounds)):
                yield candidate


def validate_sample(s,c, *, automatic=True, reference=None):
    for key in ("posx","velx","wrench"): vector(s[key],6,key)
    for key in ("robot_state","robot_mode","drl_state","motion_status","gripper_status"):
        _integer(s[key],0,None,key)
    if s["robot_state"] not in (1,2) or s["drl_state"] not in (1,3) or s["motion_status"] not in (0,1,2):
        raise RuntimeError("ROBOT_STATE_INVALID")
    if automatic and s["robot_mode"] != 1: raise RuntimeError("AUTOMATIC_MODE_REQUIRED")
    if s["tcp"] != c["connection"]["tcp"] or s["tool"] != c["connection"]["tool"]:
        raise RuntimeError("TCP_TOOL_CHANGED")
    if s["gripper_status"] != 2: raise RuntimeError("GRASP_NOT_CONFIRMED")
    width=s["gripper_width_mm"]
    if type(width) not in (int,float) or not math.isfinite(width) or not 0<=width<=110:
        raise RuntimeError("INVALID_GRIPPER_WIDTH")
    duration=s["query_duration_s"]
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<=duration<=c["timing"]["sample_max_duration_s"]:
        raise RuntimeError("FEEDBACK_QUERY_TOO_SLOW")
    if math.hypot(*s["wrench"][:3])>=c["raw_force_stop_n"]: raise RuntimeError("RAW_FORCE_STOP")
    if c["raw_moment_stop_nm"] is not None and math.hypot(*s["wrench"][3:])>=c["raw_moment_stop_nm"]:
        raise RuntimeError("RAW_MOMENT_STOP")
    if reference:
        p=s["posx"]
        if p[2]<c["floor_z_mm"]:
            raise RuntimeError("ABSOLUTE_Z_ENVELOPE_EXCEEDED")
    return s


def still(s):
    # Controller motion state is the completion signal. A PC velocity cutoff
    # rejects stationary feedback jitter and normal force-release transients.
    return s["motion_status"]==0


def validate_pressure_stages(stages,c):
    if stages is None:return
    if (not isinstance(stages,(list,tuple)) or not stages or len(stages)>c['max_probes'] or
            any(type(v) not in (int,float) or not math.isfinite(v) or
                not 0<v<=min(c['raw_force_stop_n'],35.) for v in stages) or
            any(a>=b for a,b in zip(stages,stages[1:]))):
        raise ValueError('INVALID_PRESSURE_STAGES')


def run_contact(driver,plan,record, *, cancelled=lambda:False, finish_contact=False, in_contact=False,
                pressure_stages=None,seating_goal_z_mm=None,seek_motion=None,ik_fk_tolerances=(.05,.05),
                now=time.monotonic,sleep=time.sleep,utc=time.time):
    c=plan["config"];r=c["reference"];timing=c["timing"]
    # Native seating accepts insertion below the target; standalone comparison trials retain their floor.
    sample_reference = None if seating_goal_z_mm is not None else r
    attempted=False;force_active=False;uncertain=False;started=now();probe_count=0
    observations=[];contact_baseline=None;last_sample=None;pressure_target=None;q=[0.]*5;applied_q=None
    def check_cancel():
        if cancelled(): raise RuntimeError("OPERATOR_CANCELLED")
        if now()-started>=timing["session_timeout_s"]: raise TimeoutError("SESSION_TIMEOUT")
    def sample(phase):
        nonlocal last_sample
        check_cancel();s=driver.sample();last_sample=s
        record("CONTACT_SAMPLE",dict(phase=phase,sample=s))
        validate_sample(s,c,reference=sample_reference);check_cancel();return s
    def write(name,fn):
        nonlocal attempted,uncertain
        check_cancel();attempted=True;uncertain=True;fn();uncertain=False
        record("CONTACT_COMMAND_ACK",dict(action=name))
    def wait_still():
        deadline=now()+timing["stop_timeout_s"]
        while now()<deadline:
            s=driver.motion_feedback()
            if still(s) and 0<=s["query_duration_s"]<=timing["sample_max_duration_s"] and now()<deadline:return
            sleep(timing["poll_interval_s"])
        raise TimeoutError("STOP_NOT_CONFIRMED")
    def move(pose, *, vertical=False):
        check_cancel();s=sample("BEFORE_MOVE")
        if force_active:
            # Z belongs to native force control; command only XY/orientation.
            pose=[*pose[:2],s["posx"][2],*pose[3:]]
        validate_sample(dict(s,posx=pose),c,reference=sample_reference)
        # Force release can leave a brief settling velocity after STOP ACK.
        # Wait for the same stop confirmation instead of rejecting one sample.
        stop_deadline=now()+timing["stop_timeout_s"]
        while not still(s):
            if now()>=stop_deadline:raise TimeoutError("STOP_NOT_CONFIRMED")
            sleep(timing["poll_interval_s"]);s=sample("BEFORE_MOVE_SETTLING")
        if vertical:
            pose=[*s["posx"][:2],pose[2],*s["posx"][3:]]
            validate_sample(dict(s,posx=pose),c,reference=sample_reference)
        fk=driver.check_pose(pose,max_joint_delta_deg=c["max_joint_step_deg"])
        mm,deg=pose_error(fk,pose)
        record('IK_FK_CHECK',dict(target=pose,fk=fk,position_error_mm=mm,orientation_error_deg=deg))
        if mm>ik_fk_tolerances[0] or deg>ik_fk_tolerances[1]:raise RuntimeError('IK_FK_MISMATCH')
        if mm>.05 or deg>.05:record('IK_FK_NUMERICAL_WARNING',dict(target=pose,fk=fk,position_error_mm=mm,orientation_error_deg=deg))
        record("CONTACT_MOVE_REQUEST",dict(target=pose))
        velocity,acceleration=seek_motion if vertical and seek_motion is not None else (c["velocity"],c["acceleration"])
        write("move",lambda:driver.move_line_async(pose,velocity,acceleration))
        deadline=now()+timing["motion_timeout_s"];seen_moving=False
        while now()<deadline:
            s=sample("MOVE")
            seen_moving=seen_moving or s["motion_status"]!=0
            mm,angle=pose_error(s["posx"],pose)
            if force_active:
                xy=math.dist(s["posx"][:2],pose[:2])
                if still(s) and (seen_moving or (xy<=c["position_tolerance_mm"] and angle<=c["orientation_tolerance_deg"])):
                    record("CONTACT_MOTION_MEASURED",dict(target=pose,actual=s["posx"],xy_error_mm=xy))
                    return s
            if now()<deadline and still(s) and mm<=c["position_tolerance_mm"] and angle<=c["orientation_tolerance_deg"]:return s
            sleep(timing["poll_interval_s"])
        raise TimeoutError("LOCAL_MOVE_TIMEOUT")
    def release():
        nonlocal force_active
        write("release_force",lambda:driver.release_force(0.))
        write("stop",driver.stop);wait_still()
        write("release_compliance",driver.release_compliance);wait_still();force_active=False
    def probe(q, *, leave_contact=False):
        nonlocal force_active,probe_count,contact_baseline,applied_q
        if probe_count>=c["max_probes"]:raise RuntimeError("PROBE_BUDGET_EXHAUSTED")
        approach=correction_pose(r["posx"],q)
        if in_contact and force_active:
            # Re-observe the selected pose without undoing a successful insertion.
            if seating_goal_z_mm is not None:
                if q!=applied_q:
                    current=sample('BEFORE_SEATING_CORRECTION')
                    # Native compliance may change tilt. Command only the selected
                    # XY correction and incremental Base yaw, never reset roll/pitch.
                    target=correction_pose(current['posx'],[0.,0.,0.,0.,q[4]-applied_q[4]])
                    target[:2]=approach[:2]
                    move(target)
                    applied_q=q.copy()
                else:
                    record('CONTACT_REOBSERVE',dict(q=q.copy(),position_command_sent=False))
            else:
                move(approach)
            baseline=contact_baseline
            probe_count+=1
        else:
            return start_probe(q,approach,leave_contact=leave_contact)
        return observe_probe(q,approach,baseline,leave_contact=leave_contact)

    def start_probe(q,approach, *, leave_contact=False):
        nonlocal force_active,probe_count,contact_baseline,applied_q
        entry=sample("CONTACT_ENTRY")
        if in_contact and entry['posx'][2]<approach[2]-c['position_tolerance_mm']:
            # An operator-directed new trial may start near existing contact.
            # Do not label this a free baseline or raise it back to clearance.
            free_baseline=None;s=entry
        else:
            if seating_goal_z_mm is None or max(pose_error(entry['posx'],approach))>c['position_tolerance_mm']:
                move(approach)
            free=[sample("FREE_BASELINE") for _ in range(3)]
            if any(not still(s) or math.hypot(*s["wrench"][:3])>=c["free_force_max_n"] for s in free):
                raise RuntimeError("NONCONTACT_BASELINE_NOT_CONFIRMED")
            free_baseline=np.median([s["wrench"] for s in free],axis=0);s=free[-1]
        # Position-limited slow seek precedes force mode; no free-space force
        # drive across the full gap. Each seek target is above the absolute floor.
        p=s["posx"].copy();p[2]=min(p[2],c["floor_z_mm"]+c["force_window_mm"])
        s=move(p,vertical=True)
        # Relative controller force is referenced to the stopped seek pose,
        # not the earlier moving/approach wrench. Raw force/moment guards remain.
        force_active=True;probe_count+=1
        write("compliance",lambda:driver.enable_compliance(c["stiffness"],c["transition_s"]))
        # Do not overlap compliance activation and force activation. The
        # relative force reference is captured after the compliance transition.
        sleep(c["transition_s"])
        reference_samples=[sample("FORCE_REFERENCE") for _ in range(3)]
        baseline=np.median([s["wrench"] for s in reference_samples],axis=0)
        if seating_goal_z_mm is not None:
            # An absolute target prevents a loaded baseline from accumulating force.
            baseline=np.zeros(6)
        contact_baseline=baseline
        record("CONTACT_FORCE_REFERENCE",dict(approach_wrench=None if free_baseline is None else free_baseline.tolist(),seek_wrench=baseline.tolist(),relative_force_n=c['probe_force_n'] if seating_goal_z_mm is None else None,
            absolute_force_n=c['probe_force_n'] if seating_goal_z_mm is not None else None))
        kwargs={} if seating_goal_z_mm is None else dict(relative=False)
        write("desired_force",lambda:driver.set_downward_force(c["probe_force_n"],c["transition_s"],**kwargs))
        applied_q=q.copy()
        return observe_probe(q,approach,baseline,leave_contact=leave_contact)

    def observe_probe(q,approach,baseline, *, leave_contact=False):
        deadline=now()+timing["probe_timeout_s"];settled=[];response=[]
        while now()<deadline:
            s=sample("FORCE_PROBE");reaction=s["wrench"][2]-baseline[2]
            # Compliance/force transition can first unload an existing contact.
            # A transient negative delta is not an immediate contact fault.
            # Raw guards remain active; the observation criteria depend on trial mode.
            response.append(s)
            if now()>=deadline:break
            # Seating follows measured depth under native force control. Exact
            # force matching is only needed by the standalone load-comparison trial.
            if still(s) and (seating_goal_z_mm is not None or abs(reaction-c["probe_force_n"])<=c["force_band_n"]):
                settled.append(s)
                if len(settled)==3:
                    if (seating_goal_z_mm is not None and
                            np.ptp([v['posx'][2] for v in settled])>c['repeatability_mm']):
                        # Motion status can be idle during native force descent.
                        # Keep observing that descent instead of probing XY mid-air.
                        settled=settled[-2:]
                    else:break
            else:settled=[]
            sleep(timing["poll_interval_s"])
        response_ready=len(settled)==3
        matched_load=response_ready and all(abs(s['wrench'][2]-baseline[2]-c['probe_force_n'])<=c['force_band_n'] for s in settled)
        measured=settled if response_ready else response[-3:]
        depths=[r["posx"][2]-s["posx"][2] for s in measured]
        observation=dict(q=q.copy(),depth_mm=float(np.median(depths)),noise_mm=float(np.ptp(depths)),
                         delta_wrench=(np.median([s["wrench"] for s in measured],axis=0)-baseline).tolist(),
                         matched_load=matched_load,
                         response_ready=response_ready,
                         outcome="MATCHED_LOAD" if matched_load else "DEPTH_RESPONSE" if response_ready else "LOAD_NOT_SETTLED",
                         sample=measured[-1])
        observations.append(observation);record("CONTACT_OBSERVATION",observation)
        if in_contact:return observation
        release()
        # An unmatched response is a measured candidate, not a transport fault.
        # Always unload and retract it before trying a different XY/rotation.
        if not leave_contact or not matched_load:
            s=sample("RELEASED");up=s["posx"].copy();up[2]=approach[2]
            s=move(up,vertical=True)
            # Return to the taught clearance before correcting. A small wrench
            # drift after extraction is not proof of remaining contact.
            s=move(approach)
        return observation
    result=dict(assembled=False,gripper_commands=0,observations=observations,in_contact_search=in_contact)
    try:
        if len(ik_fk_tolerances)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=1 for v in ik_fk_tolerances):
            raise ValueError('INVALID_IK_FK_TOLERANCES')
        if seating_goal_z_mm is not None:
            if (type(seating_goal_z_mm) not in (int,float) or not math.isfinite(seating_goal_z_mm)
                    or not in_contact or pressure_stages is not None or
                    not c['floor_z_mm']<seating_goal_z_mm<r['posx'][2]):
                raise ValueError('INVALID_SEATING_SEARCH_GOAL')
            if seek_motion is None:raise ValueError('SEATING_SEEK_MOTION_REQUIRED')
        if seek_motion is not None:
            if len(seek_motion)!=2 or any(min(vector(v,2,'seek motion'))<=0 for v in seek_motion):
                raise ValueError('INVALID_SEEK_MOTION')
        validate_pressure_stages(pressure_stages,c)
        if pressure_stages is not None and in_contact:raise ValueError('PRESS_ONLY_REQUIRES_FREE_REFERENCE')
        fresh=prepare_contact(c,utc=utc)
        if fresh["status"]!="CONTACT_PLAN_READY" or fresh["config"]!=c:
            raise ValueError("CONTACT_PLAN_NOT_READY_OR_CHANGED")
        if driver.mode!=c["mode"] and not (driver.mode=='MOCK' and c['mode']=='FAKE'):
            raise ValueError("DRIVER_MODE_MISMATCH")
        if driver.mode=="REAL":
            if driver.robot_system()!=0:raise RuntimeError("PHYSICAL_ROBOT_REQUIRED")
            driver.check_contact_services()
        for _ in range(3):
            s=sample("PREFLIGHT");mm,deg=pose_error(s["posx"],r["posx"])
            if not still(s) or (not in_contact and (mm>c["position_tolerance_mm"] or deg>c["orientation_tolerance_deg"])):
                raise RuntimeError("START_NOT_AT_FRESH_TAUGHT_APPROACH")
        if pressure_stages is not None:
            # Hold the current XY/orientation. No candidate search or position
            # commands while loaded, and no automatic extraction on completion.
            p=s['posx'].copy();p[2]=min(p[2],c['floor_z_mm']+c['force_window_mm'])
            move(p,vertical=True)
            force_active=True
            write('compliance',lambda:driver.enable_compliance(c['stiffness'],c['transition_s']))
            sleep(c['transition_s'])
            for force in pressure_stages:
                pressure_target=force
                probe_count+=1
                record('PRESSURE_STAGE',dict(force_n=force,force_mode='ABSOLUTE',hold_s=timing['probe_timeout_s']))
                # ABS replaces the target. Repeated REL targets could reference
                # an already loaded wrench and accumulate unwanted force.
                write('desired_force',lambda:driver.set_downward_force(force,c['transition_s'],relative=False))
                deadline=now()+timing['probe_timeout_s'];response=[]
                while now()<deadline:
                    response.append(sample('PRESS_ONLY'))
                    sleep(timing['poll_interval_s'])
                measured=response[-3:]
                observation=dict(force_target_n=force,force_mode='ABSOLUTE',
                    measured_fz_n=float(np.median([s['wrench'][2] for s in measured])),
                    measured_force_norm_n=float(np.median([math.hypot(*s['wrench'][:3]) for s in measured])),
                    depth_mm=float(np.median([r['posx'][2]-s['posx'][2] for s in measured])),
                    sample=measured[-1])
                observations.append(observation);record('PRESSURE_OBSERVATION',observation)
            release()
            result.update(status='PRESS_ONLY_FORCE_RELEASED_REVIEW_REQUIRED',correction=[0.]*5,
                stopped=True,force_released=True,compliance_released=True,probe_count=probe_count,
                final_sample=sample('FINISHED'))
            record('CONTACT_TRIAL_RESULT',result);return result
        steps=[c["xy_step_mm"]]*2+[c["rotation_step_deg"]]*3
        status="LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED"
        rotate=True
        for iteration in range(c["rounds"]):
            centre=probe(q);best=centre if (centre["response_ready"] if seating_goal_z_mm is not None else centre["matched_load"]) else None
            if seating_goal_z_mm is not None:
                # An unsettled centre is a search candidate, not proof that all
                # nearby XY/yaw positions fail. Explore the same bounded envelope.
                if best is not None and centre['sample']['posx'][2]<=seating_goal_z_mm+.5:break
            for candidate in neighbours(q,steps,c):
                if seating_goal_z_mm is not None and (any(candidate[2:4]) or not rotate and candidate[4]!=q[4]):
                    continue
                observation=probe(candidate)
                if not (observation["response_ready"] if seating_goal_z_mm is not None else observation["matched_load"]):continue
                if best is None:
                    best=observation;continue
                margin=max(c["improvement_mm"],best["noise_mm"],observation["noise_mm"])
                matched=seating_goal_z_mm is not None or abs(observation["delta_wrench"][2]-best["delta_wrench"][2])<=c["force_band_n"]/2
                if matched and observation["depth_mm"]>best["depth_mm"]+margin:
                    best=observation
                    if seating_goal_z_mm is not None:
                        rotate=False
                        break
                if seating_goal_z_mm is not None and observation['sample']['posx'][2]<=seating_goal_z_mm+.5:
                    best=observation;break
            if seating_goal_z_mm is not None:
                if best is None:
                    status='CONTACT_RESPONSE_NOT_READY';break
                final=probe(best['q'])
                if not final['response_ready']:
                    status='CONTACT_RESPONSE_NOT_READY';break
                q=best['q'].copy()
                record('CONTACT_CORRECTION_SELECTED',dict(iteration=iteration,q=q,
                    depth_gain_mm=best['depth_mm']-centre['depth_mm']))
                if final['sample']['posx'][2]<=seating_goal_z_mm+.5 or best is centre:break
                continue
            repeated=probe(q)
            if best is None:
                status="NO_MATCHED_LOAD_HOLD";break
            if not centre["matched_load"]:
                # A newly found loaded candidate needs its own repeat; an
                # unloaded centre cannot provide a comparable depth baseline.
                confirmed=probe(best["q"])
                if (not confirmed["matched_load"] or
                        abs(confirmed["depth_mm"]-best["depth_mm"])>c["repeatability_mm"] or
                        abs(confirmed["delta_wrench"][2]-best["delta_wrench"][2])>c["force_band_n"]/2):
                    status="CONTACT_RESPONSE_CHANGED_HOLD";break
            elif (not repeated["matched_load"] or
                    abs(repeated["depth_mm"]-centre["depth_mm"])>c["repeatability_mm"]
                    or abs(repeated["delta_wrench"][2]-centre["delta_wrench"][2])>c["force_band_n"]/2):
                status="CONTACT_RESPONSE_CHANGED_HOLD";break
            if best is centre:
                status="NO_CLEAR_IMPROVEMENT_HOLD";break
            q=best["q"].copy()
            record("CONTACT_CORRECTION_SELECTED",dict(iteration=iteration,q=q,
                depth_gain_mm=best["depth_mm"]-centre["depth_mm"] if centre["matched_load"] else None))
        if seating_goal_z_mm is not None:
            if status=='CONTACT_RESPONSE_NOT_READY':
                raise RuntimeError(status)
            # XY/yaw is finished. The controller owns only vertical pressing now.
            final=probe(q,leave_contact=True)
            if not final['response_ready']:raise RuntimeError('CONTACT_RESPONSE_NOT_READY')
            pressure_target=c['raw_force_stop_n']
            record('PRESSURE_STAGE',dict(force_n=pressure_target,force_mode='ABSOLUTE',hold_s=timing['probe_timeout_s']))
            write('desired_force',lambda:driver.set_downward_force(pressure_target,c['transition_s'],relative=False))
            deadline=now()+timing['probe_timeout_s'];response=[]
            while now()<deadline:
                response.append(sample('SEATING_PRESS'))
                if (len(response)>=3 and all(still(s) and s['posx'][2]<=seating_goal_z_mm+SEATING_Z_ABOVE_TOLERANCE_MM
                        and math.hypot(*s['wrench'][:3])>=pressure_target for s in response[-3:])):break
                sleep(timing['poll_interval_s'])
            observation=dict(force_target_n=pressure_target,force_mode='ABSOLUTE',
                measured_fz_n=float(np.median([s['wrench'][2] for s in response[-3:]])),
                measured_force_norm_n=float(np.median([math.hypot(*s['wrench'][:3]) for s in response[-3:]])),sample=response[-1])
            observations.append(observation);release()
            result.update(status='PRESS_ONLY_FORCE_RELEASED_REVIEW_REQUIRED',correction=q,
                stopped=True,force_released=True,compliance_released=True,probe_count=probe_count,
                final_sample=sample('FINISHED'),seating_goal_z_mm=seating_goal_z_mm)
            record('CONTACT_TRIAL_RESULT',result);return result
        if finish_contact and status not in ("CONTACT_RESPONSE_CHANGED_HOLD","NO_MATCHED_LOAD_HOLD"):
            final=probe(q,leave_contact=True)
            status="CONTACT_CANDIDATE_REVIEW_REQUIRED" if final["matched_load"] else "NO_MATCHED_LOAD_HOLD"
        elif status!="CONTACT_RESPONSE_CHANGED_HOLD":move(correction_pose(r["posx"],q))
        if force_active:release()
        result.update(status=status,correction=q,stopped=True,force_released=True,
                      compliance_released=True,probe_count=probe_count,final_sample=sample("FINISHED"))
        record("CONTACT_TRIAL_RESULT",result);return result
    except (Exception,KeyboardInterrupt) as error:
        result.update(status="CONTACT_TRIAL_ABORTED",reason=str(error) or "KEYBOARD_INTERRUPT",
                      stopped=None,state_uncertain=uncertain,probe_count=probe_count,cleanup_errors=[])
        # Logging, force-release and STOP failures must never skip the other
        # cleanup actions. There is no automatic retreat or retry after a fault.
        if attempted:
            actions=[("stop",driver.stop)]
            if force_active:actions += [("release_force",lambda:driver.release_force(0.)),("release_compliance",driver.release_compliance)]
            for name,action in actions:
                try:action();result[name+"_ack"]=True
                except (Exception,KeyboardInterrupt) as e:result["cleanup_errors"].append(dict(action=name,error=str(e)))
            try:
                wait_still()
                if not uncertain and not result["cleanup_errors"]:result["stopped"]=True
            except (Exception,KeyboardInterrupt) as e:result["cleanup_errors"].append(dict(action="confirm_stop",error=str(e)))
        # The final pressure target may equal the existing raw-force guard.
        # Crossing that guard ends pressing, never raises the guard or resumes.
        # Report the planned boundary only after every cleanup ACK and STOP.
        if ((pressure_stages is not None or seating_goal_z_mm is not None) and pressure_target==c['raw_force_stop_n'] and
                str(error)=='RAW_FORCE_STOP' and result['stopped'] is True and
                result.get('release_force_ack') and result.get('release_compliance_ack')):
            result.update(status='PRESS_ONLY_FORCE_LIMIT_REACHED_STOP_VERIFIED',
                force_released=True,compliance_released=True,force_limit_sample=last_sample,
                correction=q if seating_goal_z_mm is not None else [0.]*5)
            record('PRESSURE_LIMIT_STOP',dict(limit_n=c['raw_force_stop_n'],sample=last_sample))
        try:record("CONTACT_TRIAL_ABORT" if result['status']=='CONTACT_TRIAL_ABORTED' else "CONTACT_TRIAL_RESULT",result)
        except Exception as e:result["log_error"]=str(e)
        return result
