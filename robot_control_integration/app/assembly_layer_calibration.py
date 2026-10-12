"""Measured seating records and per-layer XYZ fits. Never extrapolate a layer height.

The common board convention is minimum occupied stud (X,Y), not legacy trial XY.
Fits report residuals and independent check errors; they never authorize motion.
"""
import time
import warnings
from uuid import uuid4
import numpy as np
from scipy.spatial.transform import Rotation
from app.contracts import validate_block,_integer
from app.current import _footprint
from app.assembly_contact_alignment import validate_sample,still

GROUP=("setup_id","grasp_id","brick_type","color","orientation_deg","layer","tcp","tool")


def validate_calibration_target(value):
    # Operator calibration includes layer5; the existing Day4 planner contract
    # remains separate. Validate shared block fields, preserving the real layer.
    _integer(value["layer"],1,5,"calibration.layer")
    target=validate_block({**value,"layer":1})
    target["layer"]=value["layer"]
    return target


def seated_record(target,sample,config, *, setup_id,grasp_id,role,confirmed=False):
    target=validate_calibration_target(target);_footprint(target)
    if not confirmed:raise ValueError("OPERATOR_SEATED_CONFIRMATION_REQUIRED")
    if not isinstance(setup_id,str) or not setup_id or not isinstance(grasp_id,str) or not grasp_id or role not in ("fit","check"):
        raise ValueError("SETUP_GRASP_AND_RECORD_ROLE_REQUIRED")
    validate_sample(sample,config,automatic=False)
    if not still(sample):raise ValueError("SEATED_CAPTURE_NOT_STOPPED")
    return dict(record_id=str(uuid4()),target=target,sample=sample,
        floor_z_mm=sample["posx"][2],setup_id=setup_id,grasp_id=grasp_id,role=role,
        tcp=sample["tcp"],tool=sample["tool"],captured_at_unix_s=time.time(),
        coordinate_convention="BOARD_MINIMUM_OCCUPIED_STUD_XY",
        source="OPERATOR_SEATED_CURRENT_GRASP",motion_commands=0,gripper_commands=0)


def group_key(record):
    return tuple(record.get(k,record["target"].get(k)) for k in GROUP)


def fit_layers(records):
    groups={}
    for record in records:
        validate_calibration_target(record["target"]);_footprint(record["target"])
        if record["coordinate_convention"]!="BOARD_MINIMUM_OCCUPIED_STUD_XY":
            raise ValueError("LEGACY_TRIAL_COORDINATES_REQUIRE_EXPLICIT_CONVERSION")
        groups.setdefault(group_key(record),[]).append(record)
    models=[]
    for key,rows in groups.items():
        fitting=[r for r in rows if r["role"]=="fit" and not r.get("model_excluded",False)]
        checking=[r for r in rows if r["role"]=="check" and not r.get("model_excluded",False)]
        model=dict(group=dict(zip(GROUP,key)),fit_record_ids=[r["record_id"] for r in fitting],
            check_record_ids=[r["record_id"] for r in checking],executable=False,
            taught_points=[dict(target=r["target"],posx=r["sample"]["posx"],record_id=r["record_id"]) for r in fitting])
        adopted=[r for r in fitting if r.get("adopt_as_layer_z") is True]
        if adopted:
            r=adopted[-1]
            model["seated_z_reference"]=dict(record_id=r["record_id"],floor_z_mm=r["floor_z_mm"],
                measured_target=r["target"],source="OPERATOR_ADOPTED_LAYER_Z")
        xy=np.array([[1.,r["target"]["x"],r["target"]["y"]] for r in fitting])
        if len(fitting)<3 or np.linalg.matrix_rank(xy)<3:
            model.update(status="POINT_REFERENCES_ONLY",global_fit_missing="THREE_NONCOLLINEAR_SEATED_POINTS");models.append(model);continue
        xyz=np.array([r["sample"]["posx"][:3] for r in fitting])
        coefficients=np.linalg.lstsq(xy,xyz,rcond=None)[0]
        attitude=Rotation.from_euler("ZYZ",[r["sample"]["posx"][3:] for r in fitting],degrees=True).mean()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",UserWarning)
            angles=attitude.as_euler("ZYZ",degrees=True).tolist()
        errors=[]
        for r in checking:
            predicted=np.array([1.,r["target"]["x"],r["target"]["y"]])@coefficients
            measured=r["sample"]["posx"]
            rotation=Rotation.from_euler("ZYZ",measured[3:],degrees=True)
            errors.append(dict(record_id=r["record_id"],xyz_error_mm=(np.array(measured[:3])-predicted).tolist(),
                orientation_error_deg=float(np.rad2deg((rotation*attitude.inv()).magnitude()))))
        model.update(status="MEASURED_FIT_REVIEW_REQUIRED" if checking else "NEEDS_INDEPENDENT_CHECK",
            xyz_coefficients=coefficients.tolist(),orientation_zyz_deg=angles,
            fit_residual_xyz_mm=(xyz-xy@coefficients).tolist(),independent_checks=errors,
            fit_orientation_deviation_deg=np.rad2deg((Rotation.from_euler("ZYZ",
                [r["sample"]["posx"][3:] for r in fitting],degrees=True)*attitude.inv()).magnitude()).tolist(),
            measured_xy_range=[[min(r["target"][axis] for r in fitting),max(r["target"][axis] for r in fitting)] for axis in ("x","y")])
        models.append(model)
    return dict(schema_version=1,status="MEASUREMENT_REPORT",models=models,
        excluded_record_ids=[r["record_id"] for r in records if r.get("model_excluded",False)],
        measured_layers=sorted({m["group"]["layer"] for m in models}),
        fitted_layers=sorted({m["group"]["layer"] for m in models if "xyz_coefficients" in m}),
        automatic_layer_height=False,automatic_motion=False)


def layer_pose(model,target):
    target=validate_calibration_target(target);_footprint(target)
    if any(target[k]!=model["group"][k] for k in ("brick_type","color","orientation_deg","layer")):
        raise ValueError("BLOCK_OR_LAYER_DOES_NOT_MATCH_MEASURED_MODEL")
    exact=[p for p in model["taught_points"] if p["target"]==target]
    if exact:
        result=dict(target=target,posx=exact[-1]["posx"].copy(),floor_z_mm=exact[-1]["posx"][2],
            source_record_id=exact[-1]["record_id"],status="EXACT_TAUGHT_LAYER_POINT",executable=False,group=model["group"])
    else:
        if "xyz_coefficients" not in model:raise ValueError("TARGET_NOT_TAUGHT_AND_LAYER_NOT_FITTED")
        if any(not limits[0]<=target[axis]<=limits[1] for axis,limits in zip(("x","y"),model["measured_xy_range"])):
            raise ValueError("OUTSIDE_MEASURED_XY_RANGE")
        xyz=np.array([1.,target["x"],target["y"]])@np.array(model["xyz_coefficients"])
        result=dict(target=target,posx=[*xyz.tolist(),*model["orientation_zyz_deg"]],
            floor_z_mm=float(xyz[2]),status="MEASURED_LAYER_POSE_CANDIDATE",executable=False,
            group=model["group"],independent_checks=model["independent_checks"])
    reference=model.get("seated_z_reference")
    if reference:
        result["seated_z_reference"]=reference
        if result["posx"][2]!=reference["floor_z_mm"]:
            result["original_pose_z_mm"]=result["posx"][2]
            result["posx"][2]=result["floor_z_mm"]=reference["floor_z_mm"]
            result["status"]="LAYER_Z_UPDATED_POSE_CANDIDATE"
    return result
