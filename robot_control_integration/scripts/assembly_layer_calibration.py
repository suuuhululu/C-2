"""Read-only layer capture / fit / list. All seating and layer labels are operator supplied."""
import argparse
import fcntl
import json
import os
from pathlib import Path
from app.assembly_layer_calibration import seated_record,fit_layers,layer_pose,validate_calibration_target
from scripts.assembly_contact_trial import ROOT,TEMPLATE,save,real_driver


def main(argv=None, *, driver_factory=real_driver):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("capture","fit","list","predict"))
    p.add_argument("--records",type=Path,default=ROOT/"calibration/layer_records.json")
    p.add_argument("--out",type=Path,default=ROOT/"calibration/layer_models.json")
    p.add_argument("--brick",choices=("4","6"));p.add_argument("--color",choices=("yellow","blue"))
    p.add_argument("--orientation",type=int,choices=(0,90),default=0)
    p.add_argument("--layer",type=int,choices=(1,2,3,4,5))
    p.add_argument("--xy",type=int,nargs=2)
    p.add_argument("--setup-id");p.add_argument("--grasp-id")
    p.add_argument("--role",choices=("fit","check"),default="fit")
    p.add_argument("--confirm-seated",action="store_true")
    a=p.parse_args(argv)
    try:
        records=json.loads(a.records.read_text()) if a.records.exists() else []
        if a.action in ("capture","predict"):
            if not all((a.brick,a.color,a.layer,a.xy,a.setup_id,a.grasp_id)) or (a.action=="capture" and not a.confirm_seated):
                raise ValueError("BLOCK_LAYER_XY_SETUP_GRASP_AND_SEATED_CONFIRMATION_REQUIRED")
            target=dict(brick_type="2x2x1" if a.brick=="4" else "2x3x1",color=a.color,
                x=a.xy[0],y=a.xy[1],layer=a.layer,orientation_deg=a.orientation)
            from app.current import _footprint
            _footprint(validate_calibration_target(target))
            if a.action=="predict":
                models=fit_layers(records)["models"]
                matching=[m for m in models if m["group"]["setup_id"]==a.setup_id and m["group"]["grasp_id"]==a.grasp_id
                    and all(m["group"][k]==target[k] for k in ("brick_type","color","orientation_deg","layer"))]
                if len(matching)!=1:raise ValueError("EXACT_MEASURED_LAYER_GROUP_REQUIRED")
                print(json.dumps(layer_pose(matching[0],target),ensure_ascii=False,indent=2));return 0
            c=json.loads(TEMPLATE.read_text())
            if os.environ.get("ROS_DOMAIN_ID")!=str(c["connection"]["ros_domain_id"]):
                raise ValueError("MATCHING_ROS_DOMAIN_REQUIRED")
            c["timing"]["service_timeout_s"]=3.
            with Path('/tmp/c2-assembly-dsr01.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                driver=driver_factory(c)
                try:
                    if driver.robot_system()!=0:raise ValueError("PHYSICAL_ROBOT_REQUIRED")
                    sample=driver.sample()
                    record=seated_record(target,sample,c,setup_id=a.setup_id,grasp_id=a.grasp_id,
                        role=a.role,confirmed=a.confirm_seated)
                finally:driver.close()
                # Preserve each capture, including repeated points, for review.
                records=json.loads(a.records.read_text()) if a.records.exists() else []
                records.append(record);save(a.records,records)
            result=dict(status="LAYER_SEATED_POINT_RECORDED",record=record,file=str(a.records))
        else:
            result=fit_layers(records)
            if a.action=="fit":save(a.out,result);result["file"]=str(a.out)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except Exception as e:
        print(json.dumps(dict(status="LAYER_CALIBRATION_FAILED",reason=str(e)),ensure_ascii=False));return 1


if __name__=="__main__":raise SystemExit(main())
