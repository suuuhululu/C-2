"""Position-only local contact correction; native force mode is never activated."""
from copy import deepcopy
import math
import time
import numpy as np
from app.assembly_motion import pose_error
from app.assembly_contact_alignment import prepare_contact,correction_pose,validate_sample,still

def prepare_position_alignment(value):
    # Position-only correction uses a live contact origin, not a taught free
    # approach. Keep the shared profile/units, but require only review and Z floor.
    pending=deepcopy(value);pending["reference"]=None
    plan=prepare_contact(pending)
    plan["config"]["reference"]=deepcopy(value["reference"])
    plan["missing"].remove("reference")
    plan["status"]="POSITION_ALIGNMENT_READY" if not plan["missing"] else "NOT_READY"
    return plan


def run_position_alignment(driver,plan,record, *, cancelled=lambda:False,
                           now=time.monotonic,sleep=time.sleep):
    """Fixed TCP-Z probes; XY reduces lateral force, tilt reduces roll/pitch moment.

    Wrench reductions are local observations, not proof of alignment or seating.
    No force/compliance, gripper, mode or vertical movement commands are issued.
    """
    c=plan["config"];timing=c["timing"];started=now();attempted=False;uncertain=False
    observations=[];q=[0.]*5;origin=None
    result=dict(assembled=False,gripper_commands=0,force_commands=0,
                position_only=True,observations=observations)
    def sample(phase):
        if cancelled():raise RuntimeError("OPERATOR_CANCELLED")
        if now()-started>=timing["session_timeout_s"]:raise TimeoutError("SESSION_TIMEOUT")
        s=driver.sample();record("POSITION_SAMPLE",dict(phase=phase,sample=s))
        return validate_sample(s,c,reference=True)
    def move(candidate):
        nonlocal attempted,uncertain
        s=sample("BEFORE_MOVE")
        target=correction_pose(origin,candidate)
        fk=driver.check_pose(target,max_joint_delta_deg=c["max_joint_step_deg"])
        if max(pose_error(fk,target))>.05:raise RuntimeError("IK_FK_MISMATCH")
        record("POSITION_MOVE_REQUEST",dict(target=target,q=candidate))
        attempted=True;uncertain=True
        driver.move_line_async(target,c["velocity"],c["acceleration"])
        uncertain=False;record("POSITION_COMMAND_ACK",dict(action="move"))
        deadline=now()+timing["motion_timeout_s"];seen_moving=False
        while now()<deadline:
            s=sample("MOVE");seen_moving=seen_moving or not still(s)
            mm,deg=pose_error(s["posx"],target)
            if still(s) and (seen_moving or (mm<=c["position_tolerance_mm"] and deg<=c["orientation_tolerance_deg"])):return
            sleep(timing["poll_interval_s"])
        raise TimeoutError("LOCAL_MOVE_TIMEOUT")
    def observe(candidate,phase):
        if len(observations)>=c["max_probes"]:raise RuntimeError("PROBE_BUDGET_EXHAUSTED")
        samples=[]
        for _ in range(3):
            sleep(timing["poll_interval_s"]);samples.append(sample(phase))
        lateral=[math.hypot(*s["wrench"][:2]) for s in samples]
        tilt=[math.hypot(*s["wrench"][3:5]) for s in samples]
        o=dict(q=candidate.copy(),lateral_force_n=float(np.median(lateral)),
               tilt_moment_nm=float(np.median(tilt)),
               lateral_range_n=[min(lateral),max(lateral)],tilt_range_nm=[min(tilt),max(tilt)],
               sample=samples[-1])
        observations.append(o);record("POSITION_OBSERVATION",o);return o
    try:
        if prepare_position_alignment(c)["status"]!="POSITION_ALIGNMENT_READY":raise ValueError("POSITION_PLAN_NOT_READY")
        if driver.mode!=c["mode"]:raise ValueError("DRIVER_MODE_MISMATCH")
        if driver.mode=="REAL":
            if driver.robot_system()!=0:raise RuntimeError("PHYSICAL_ROBOT_REQUIRED")
            driver.check_contact_services(native_force=False)
        s=sample("PREFLIGHT")
        if not still(s):raise RuntimeError("START_NOT_STOPPED")
        origin=s["posx"].copy();result["origin_posx"]=origin
        for phase,axes,step,metric,spread in (
            ("XY",(0,1),c["xy_step_mm"],"lateral_force_n","lateral_range_n"),
            ("TILT",(2,3),c["rotation_step_deg"],"tilt_moment_nm","tilt_range_nm")):
            centre=observe(q,phase);best=centre
            candidates=[]
            for axis in axes:
                for sign in (-1,1):
                    candidate=q.copy();candidate[axis]+=sign*step;candidates.append(candidate)
            for candidate in candidates:
                move(candidate);o=observe(candidate,phase)
                if o[metric]<best[metric]:best=o
            # Compare measured ranges rather than adding a guessed force/moment
            # threshold. Overlap records no clear improvement, never a fault.
            selected=best if best[spread][1]<centre[spread][0] else centre
            move(selected["q"]);confirmed=observe(selected["q"],phase+"_REPEAT")
            if selected is not centre and confirmed[spread][1]<centre[spread][0]:
                q=selected["q"].copy()
                record("POSITION_CORRECTION_SELECTED",dict(phase=phase,q=q,metric=metric,
                    before=centre[metric],after=confirmed[metric]))
            elif selected is not centre:move(q)
        driver.stop();final=sample("FINISHED")
        result.update(status="POSITION_ALIGNMENT_REVIEW_REQUIRED",correction=q,
                      stopped=still(final),probe_count=len(observations),final_sample=final)
        record("POSITION_TRIAL_RESULT",result)
    except (Exception,KeyboardInterrupt) as error:
        result.update(status="CONTACT_TRIAL_ABORTED",reason=str(error) or "KEYBOARD_INTERRUPT",
                      stopped=None,state_uncertain=uncertain,probe_count=len(observations),cleanup_errors=[])
        if attempted:
            try:
                driver.stop();result["stop_ack"]=True
                s=driver.motion_feedback();result["stopped"]=still(s) if not uncertain else None
            except Exception as e:result["cleanup_errors"].append(dict(action="stop",error=str(e)))
        try:record("POSITION_TRIAL_ABORT",result)
        except Exception as e:result["log_error"]=str(e)
    return result

