"""Local contact test: smoke / doctor / teach-seat / arm / check / run / stop.

Default REAL run corrects XY/tilt at the current TCP Z, using an absolute seated-Z
floor and explicit --execute. Native force trials require --native-force and a
fresh noncontact reference. Capture never moves the robot.
"""
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import signal
import time
from uuid import uuid4

from app.assembly_contact_alignment import prepare_contact,run_contact,still,validate_sample
from app.assembly_position_alignment import prepare_position_alignment,run_position_alignment
from app.assembly_motion import pose_error
from app.jsonl_log import JsonlLog

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/"interfaces/assembly_contact_trial.json"
DEFAULT_PROFILE=ROOT/"logs/contact_trials/onsite.json"
DEFAULT_STOP=ROOT/"logs/contact_trials/STOP"


def real_driver(c):
    from app.assembly_motion_ros import AssemblyMotionRos
    return AssemblyMotionRos(c)


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+".tmp-"+uuid4().hex)
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    temp.replace(path)


def main(argv=None, *, driver_factory=real_driver):
    parser=argparse.ArgumentParser(description=__doc__,epilog="모드·그리퍼를 쓰지 않음. STOP 후 자동 복귀/재시도 없음. floor_z_mm은 현재 파지·목표의 결착 TCP Z.")
    parser.add_argument("action",choices=["smoke","doctor","teach-seat","arm","check","run","stop"])
    parser.add_argument("--profile",type=Path)
    parser.add_argument("--out",type=Path)
    parser.add_argument("--floor-z-mm",type=float)
    parser.add_argument("--seated-reference",type=Path)
    parser.add_argument("--confirm-seated",action="store_true")
    parser.add_argument("--confirm-noncontact",action="store_true")
    parser.add_argument("--confirm-envelope",action="store_true",help="TCP/tool·작업자·단독제어·국소경로·힘제어 비활성 확인")
    parser.add_argument("--execute",action="store_true")
    parser.add_argument("--native-force",action="store_true",help="나중에 검증할 네이티브 힘 모드; 기본은 위치 제어로 XY/기울기만 보정")
    parser.add_argument("--finish-contact",action="store_true",help="최종 후보에서 같은 탐색 힘으로 재접촉 후 힘 해제·정지; 결착 성공으로 채택하지 않음")
    parser.add_argument("--in-contact",action="store_true",help="Z힘/순응 제어를 유지한 채 XY·자세 후보 탐색; 후보별 상승·힘 해제 없음")
    parser.add_argument("--stop-file",type=Path,default=DEFAULT_STOP)
    parser.add_argument("--log-dir",type=Path,default=ROOT/"logs/contact_trials")
    args=parser.parse_args(argv);driver=None;previous={};identity=str(uuid4())
    logger=JsonlLog(args.log_dir);started=time.monotonic()
    def record(event,payload):logger(dict(job_id=identity,event=event,payload=payload,elapsed_s=time.monotonic()-started))
    def report(value):print(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),flush=True)
    try:
        if args.action=="stop":
            args.stop_file.parent.mkdir(parents=True,exist_ok=True);args.stop_file.touch()
            report(dict(status="SOFTWARE_STOP_REQUESTED",stop_file=str(args.stop_file),controller_stop_ack=False));return 0
        if args.execute and args.action!="run":raise ValueError("EXECUTE_ONLY_WITH_RUN")
        if args.finish_contact and args.action!="run":raise ValueError("FINISH_CONTACT_ONLY_WITH_RUN")
        if (args.in_contact or args.finish_contact) and not args.native_force:
            raise ValueError("NATIVE_FORCE_OPT_IN_REQUIRED")
        reuse_profile=args.action in ("run","check") or (args.action=="arm" and DEFAULT_PROFILE.exists())
        path=args.profile or (DEFAULT_PROFILE if reuse_profile else TEMPLATE)
        c=json.loads(path.read_text())
        if args.action=="smoke":
            from app.assembly_contact_fake import ContactFake,fake_config
            c=fake_config(c);plan=prepare_contact(c) if args.native_force else prepare_position_alignment(c)
            driver=ContactFake(c,allow_force_moves=args.in_contact)
            record("SESSION",dict(mode="FAKE",config=c,physical_validation=False))
            result=(run_contact(driver,plan,record,in_contact=args.in_contact) if args.native_force
                    else run_position_alignment(driver,plan,record))
            save(args.log_dir/f"{identity}-summary.json",result)
            report(dict(status=result["status"],correction=result.get("correction"),probe_count=result["probe_count"],
                        assembled=False,gripper_commands=0,real_motion_commands=0,log_file=str(args.log_dir/f"{identity}.jsonl")))
            return 0 if result["status"]!="CONTACT_TRIAL_ABORTED" else 1
        if args.action=="run" and not args.native_force and args.floor_z_mm is not None:
            c["floor_z_mm"]=args.floor_z_mm
            if args.confirm_envelope:c["reviewed"]=True
        plan=prepare_contact(c) if args.native_force or args.action not in ("run","check") else prepare_position_alignment(c)
        if args.action=="run" and not args.execute:
            report({k:v for k,v in plan.items() if k!="config"});return 0
        if c["mode"]!="REAL" or os.environ.get("ROS_DOMAIN_ID")!=str(c["connection"]["ros_domain_id"]):
            raise ValueError("EXPLICIT_REAL_AND_MATCHING_ROS_DOMAIN_REQUIRED")
        if args.action in ("run","check") and plan["status"] not in ("CONTACT_PLAN_READY","POSITION_ALIGNMENT_READY"):
            report({k:v for k,v in plan.items() if k!="config"});return 2
        if args.action=="teach-seat" and not args.confirm_seated:raise ValueError("OPERATOR_SEATED_CONFIRMATION_REQUIRED")
        if args.action=="arm" and not (args.confirm_noncontact and args.confirm_envelope):
            raise ValueError("NONCONTACT_AND_LOCAL_ENVELOPE_CONFIRMATIONS_REQUIRED")
        if args.action in ("run","check") and args.stop_file.exists():raise ValueError("STOP_FILE_PRESENT")
        lock=Path("/tmp")/f"c2-assembly-{c['connection']['robot_id']}.lock"
        with lock.open("a") as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            record("SESSION",dict(action=args.action,config=c,assembled=False,gripper_commands=0))
            transport=deepcopy(c)
            if args.action in ("doctor","teach-seat","arm","check"):
                transport['timing']['service_timeout_s']=3.
            driver=driver_factory(transport)
            if driver.robot_system()!=0:raise RuntimeError("PHYSICAL_ROBOT_REQUIRED")
            services=driver.check_contact_services(native_force=args.native_force)
            if args.action=="doctor":
                s=driver.sample();record("READ_ONLY_SAMPLE",s)
                report(dict(status="READ_ONLY_DOCTOR_COMPLETE",services=services,sample=s,motion_commands=0));return 0
            if args.action in ("teach-seat","arm","check"):
                samples=[driver.sample() for _ in range(3)]
                for s in samples:
                    record("READ_ONLY_SAMPLE",s)
                    if args.action=="teach-seat":
                        if not still(s) or s["gripper_status"]!=2 or s["tcp"]!=c["connection"]["tcp"] or s["tool"]!=c["connection"]["tool"]:
                            raise RuntimeError("SEATED_CAPTURE_STATE_INVALID")
                    else:validate_sample(s,c,automatic=args.action=="check")
                    mm,angle=pose_error(s["posx"],samples[0]["posx"])
                    if (not still(s) or mm>c["position_tolerance_mm"] or angle>c["orientation_tolerance_deg"]
                            or abs(s["gripper_width_mm"]-samples[0]["gripper_width_mm"])>c["width_drift_mm"]):
                        raise RuntimeError("CAPTURE_NOT_STABLE")
                s=samples[-1]
                if args.action=="teach-seat":
                    out=args.out or args.log_dir/"seated-reference.json"
                    save(out,dict(floor_z_mm=s["posx"][2],sample=s,source="OPERATOR_SEATED_CURRENT_GRASP",captured_at_unix_s=time.time()))
                    report(dict(status="SEATED_Z_RECORDED_READ_ONLY",floor_z_mm=s["posx"][2],file=str(out)));return 0
                if args.action=="arm":
                    if args.floor_z_mm is not None and args.seated_reference:raise ValueError("CHOOSE_ONE_Z_FLOOR_SOURCE")
                    floor=args.floor_z_mm
                    if args.seated_reference:
                        seat=json.loads(args.seated_reference.read_text());floor=seat["floor_z_mm"]
                        if seat["source"]!="OPERATOR_SEATED_CURRENT_GRASP" or not 0<=time.time()-seat["captured_at_unix_s"]<=c["timing"]["reference_max_age_s"]:
                            raise RuntimeError("SEATED_REFERENCE_INVALID_OR_EXPIRED")
                        if seat["sample"]["tcp"]!=s["tcp"] or seat["sample"]["tool"]!=s["tool"] or floor!=seat["sample"]["posx"][2]:
                            raise RuntimeError("SEATED_REFERENCE_TCP_TOOL_OR_Z_CHANGED")
                        if abs(seat["sample"]["gripper_width_mm"]-s["gripper_width_mm"])>c["width_drift_mm"]:
                            raise RuntimeError("SEATED_REFERENCE_GRIP_WIDTH_CHANGED")
                        mm,angle=pose_error([*s["posx"][:2],floor,*s["posx"][3:]],seat["sample"]["posx"])
                        if mm>2**.5*c["xy_limit_mm"] or angle>3**.5*c["rotation_limit_deg"]:
                            raise RuntimeError("APPROACH_NOT_ABOVE_CURRENT_SEATED_REFERENCE")
                    if floor is None:raise ValueError("ABSOLUTE_Z_FLOOR_REQUIRED")
                    if any(sum(v*v for v in x["wrench"][:3])**.5>=c["free_force_max_n"] for x in samples):
                        raise RuntimeError("FREE_BASELINE_TOO_HIGH")
                    c.update(floor_z_mm=floor,reviewed=True,reference=dict(posx=s["posx"],width_mm=s["gripper_width_mm"],
                        captured_at_unix_s=time.time(),source=str(args.seated_reference or "OPERATOR_ABSOLUTE_Z_FLOOR"),noncontact_verified=True))
                    plan=prepare_contact(c);out=args.out or DEFAULT_PROFILE
                    if plan["status"]!="CONTACT_PLAN_READY":raise ValueError("CAPTURE_PROFILE_NOT_READY")
                    save(out,c);report(dict(status="FRESH_CONTACT_PROFILE_RECORDED",file=str(out),max_descent_mm=plan["max_descent_mm"],motion_commands=0));return 0
                for s in samples:validate_sample(s,c,reference=c["reference"])
                if args.native_force and (pose_error(s["posx"],c["reference"]["posx"])[0]>c["position_tolerance_mm"] or pose_error(s["posx"],c["reference"]["posx"])[1]>c["orientation_tolerance_deg"]):
                    raise RuntimeError("NOT_AT_CAPTURED_APPROACH")
                from app.assembly_contact_alignment import correction_pose,neighbours
                origin=c['reference']['posx'] if args.native_force else s['posx']
                poses=[origin,*[correction_pose(origin,q) for q in neighbours([0.]*5,[c['xy_step_mm']]*2+[c['rotation_step_deg']]*3,c) if args.native_force or q[4]==0]]
                for pose in poses:
                    seek=pose.copy();seek[2]=c['floor_z_mm']+c['force_window_mm']
                    for target in ((pose,seek) if args.native_force else (pose,)):
                        mm,angle=pose_error(driver.check_pose(target,max_joint_delta_deg=c['max_joint_step_deg']),target)
                        if mm>c['position_tolerance_mm'] or angle>c['orientation_tolerance_deg']:
                            raise RuntimeError('LOCAL_IK_FK_MISMATCH')
                report(dict(status="READ_ONLY_CONTACT_CHECK_COMPLETE",max_descent_mm=plan["max_descent_mm"],ik_fk_checks=(2 if args.native_force else 1)*len(poses),motion_commands=0));return 0
            def interrupt(signum,frame):raise KeyboardInterrupt(f"SIGNAL_{signum}")
            for sig in (signal.SIGINT,signal.SIGTERM):previous[sig]=signal.signal(sig,interrupt)
            result=(run_contact(driver,plan,record,cancelled=args.stop_file.exists,finish_contact=args.finish_contact,in_contact=args.in_contact)
                    if args.native_force else run_position_alignment(driver,plan,record,cancelled=args.stop_file.exists))
            save(args.log_dir/f"{identity}-summary.json",result)
            if result["status"]=="CONTACT_TRIAL_ABORTED":
                args.stop_file.parent.mkdir(parents=True,exist_ok=True);args.stop_file.touch()
            report(dict(status=result["status"],reason=result.get("reason"),correction=result.get("correction"),
                        probe_count=result["probe_count"],stopped=result["stopped"],assembled=False,
                        log_file=str(args.log_dir/f"{identity}.jsonl")))
            return 1 if result["status"]=="CONTACT_TRIAL_ABORTED" else 0
    except (Exception,KeyboardInterrupt) as e:
        failure=dict(status="CONTACT_COMMAND_FAILED",reason=str(e) or "KEYBOARD_INTERRUPT",assembled=False)
        try:record('COMMAND_FAILED',failure)
        except Exception as log_error:failure['log_error']=str(log_error)
        report(failure);return 1
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
        if driver is not None:driver.close()


if __name__=="__main__":raise SystemExit(main())
