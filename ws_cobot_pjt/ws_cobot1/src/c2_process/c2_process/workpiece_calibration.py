"""양초 윗면 + 옆면 8점 측정. ROS 비의존, 이시율 담당.

Action 수신부는 measure_workpiece()를 작업 스레드에서 호출하고 on_progress를
Feedback으로 변환한다. 세은님의 상태 기계를 호출하지 않는다.
기존 RobotAdapter의 느슨한 완료/정지 판정을 자동 재사용하지 않는다.
measurement_contract_version=1 백엔드 계약은 WORKPIECE_CALIBRATION.md 참조.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import threading
import time
from typing import Callable

from .robot_adapter import StepResult, apply_tool_offset, matrix_to_quat


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MeasurementContext:
    measurement_id: str
    preparation_id: str
    source_mode: str
    cancel: threading.Event = field(default_factory=threading.Event)
    # Action 서버/조각 실행기가 공유해야 한다. 프로세스 간 배타 제어는 서버 책임.
    motion_lock: object = field(default_factory=threading.Lock)
    profile_snapshot_id: str = ""
    profile_sha256: str = ""
    monotonic: Callable = time.monotonic
    utc_now: Callable = utc_now


class MeasurementError(Exception):
    def __init__(self, code, message, outcome="FAILED"):
        super().__init__(message)
        self.code, self.outcome = code, outcome


def number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: 유한 숫자 필요")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name}: {minimum} 이상 필요")
    return float(value)


def vector(value, n, name):
    if not isinstance(value, (list, tuple)) or len(value) != n:
        raise ValueError(f"{name}: 길이 {n} 배열 필요")
    return [number(v, name) for v in value]


def pose(value):
    result = vector(value, 7, "pose_m_quat")
    norm = math.sqrt(sum(v*v for v in result[3:]))
    if abs(norm-1) > 1e-5:
        raise ValueError("단위 quaternion 필요")
    return result


def rotation_distance(a, b):
    return 2*math.acos(min(1.,abs(sum(x*y for x,y in zip(a[3:],b[3:])))))


def _solve3(a, b):
    rows = [list(a[i])+[b[i]] for i in range(3)]
    for i in range(3):
        pivot = max(range(i, 3), key=lambda k: abs(rows[k][i]))
        if abs(rows[pivot][i]) < 1e-12:
            raise ValueError("원 맞춤 불가: 중복/일직선 측정점")
        rows[i], rows[pivot] = rows[pivot], rows[i]
        d = rows[i][i]
        rows[i] = [v/d for v in rows[i]]
        for j in range(3):
            if j != i:
                d = rows[j][i]
                rows[j] = [v-d*w for v, w in zip(rows[j], rows[i])]
    return [row[3] for row in rows]


def fit_circle(points):
    """중심/반지름을 모두 추정. 고정 반지름 사용 없음. 입력/출력 m."""
    if len(points) < 3:
        raise ValueError("최소 3점 필요")
    xy = [vector(p, 3, "point_tip_xyz_m")[:2] for p in points]
    # 원점 이동/스케일 정규화로 작은 SI 좌표의 조건수 개선.
    origin = [sum(p[k] for p in xy)/len(xy) for k in range(2)]
    scale = max(math.dist(p, origin) for p in xy)
    if scale < 1e-9:
        raise ValueError("서로 다른 측정점 필요")
    pts = [[(p[k]-origin[k])/scale for k in range(2)] for p in xy]
    rows = [[2*x, 2*y, 1.] for x, y in pts]
    a = [[sum(r[i]*r[j] for r in rows) for j in range(3)] for i in range(3)]
    b = [sum(r[i]*(p[0]**2+p[1]**2) for r,p in zip(rows,pts)) for i in range(3)]
    cx, cy, d = _solve3(a,b)
    radius = math.sqrt(max(0, d+cx*cx+cy*cy))
    for _ in range(30):
        distances = [math.hypot(cx-x, cy-y) for x,y in pts]
        if min(distances) < 1e-12:
            raise ValueError("퇴화한 원 맞춤")
        jac = [[(cx-x)/r, (cy-y)/r, -1.] for (x,y),r in zip(pts,distances)]
        residual = [r-radius for r in distances]
        a = [[sum(r[i]*r[j] for r in jac) for j in range(3)] for i in range(3)]
        b = [-sum(r[i]*e for r,e in zip(jac,residual)) for i in range(3)]
        delta = _solve3(a,b)
        cx += delta[0]; cy += delta[1]; radius += delta[2]
        if max(abs(v) for v in delta) < 1e-12:
            break
    else:
        raise ValueError("원 맞춤 수렴 실패")
    center = [origin[0]+cx*scale, origin[1]+cy*scale]
    radius *= scale
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("유효하지 않은 반지름")
    residual = [math.dist(p,center)-radius for p in xy]
    return dict(axis_xy_m=center, radius_m=radius,
                residual_rms_m=math.sqrt(sum(e*e for e in residual)/len(residual)),
                residual_max_m=max(abs(e) for e in residual), residuals_m=residual)


def facing_pose(center, radius, z, angle_deg):
    """tool -Y는 원 중심, tool +Z는 base -Z. 반환은 드릴 끝 pose."""
    a = math.radians(angle_deg); c, s = math.cos(a), math.sin(a)
    rotation = [[-s,c,0],[c,s,0],[0,0,-1]]
    return [center[0]+radius*c,center[1]+radius*s,z]+matrix_to_quat(rotation)


def _validate(workcell, profiles, context):
    if context.source_mode not in ("SIMULATION", "REAL"):
        raise ValueError("source_mode 필요")
    if not context.measurement_id or not context.preparation_id:
        raise ValueError("measurement_id/preparation_id 필요")
    if not callable(getattr(context.cancel, "is_set", None)):
        raise ValueError("cancel Event 필요")
    if workcell["frame_id"] != "c2_base":
        raise ValueError("지원 좌표계는 c2_base")
    if workcell["source_mode"] != context.source_mode:
        raise ValueError("설정/실행 source_mode 불일치")
    for name in ("height_m","top_margin_m","bottom_margin_m","side_depth_m", "seed_radius_m",
                 "outer_gap_m","start_gap_m","inside_limit_m","slow_retract_gap_m",
                 "orbit_step_deg","max_center_shift_m","max_radius_error_m",
                 "max_fit_rms_m","max_fit_residual_m","max_point_z_spread_m",
                 "max_state_age_s","pose_tolerance_m", "angle_tolerance_rad", "runtime_timeout_s"):
        number(workcell[name], name, 1e-9)
    if workcell["height_m"] <= workcell["top_margin_m"]+workcell["bottom_margin_m"]:
        raise ValueError("상하 제외 구간이 높이보다 큼")
    if not workcell["top_margin_m"] <= workcell["side_depth_m"] <= workcell["height_m"]-workcell["bottom_margin_m"]:
        raise ValueError("옆면 측정 높이가 작업 영역 밖")
    if not workcell["inside_limit_m"] < workcell["seed_radius_m"]:
        raise ValueError("접촉 최대 깊이가 반지름 이상")
    if not workcell["slow_retract_gap_m"] < workcell["start_gap_m"] < workcell["outer_gap_m"]:
        raise ValueError("후퇴/접촉 시작/외곽 간격 순서 오류")
    if workcell["orbit_step_deg"] > 22.5:
        raise ValueError("현재 원호 분할은 22.5도 이하")
    if not isinstance(workcell["height_source"],str) or not workcell["height_source"]:
        raise ValueError("height_source 출처 필요")
    vector(workcell["seed_axis_xy_m"],2,"seed_axis_xy_m")
    vector(workcell["tool_offset_m"],3,"tool_offset_m")
    # 모르는 값을 0으로 대체하지 않는다. REAL은 출처도 필수.
    scope=workcell.get("measurement_scope","ABSOLUTE_GEOMETRY")
    if scope not in ("ABSOLUTE_GEOMETRY","CONTACT_REFERENCE"):
        raise ValueError("지원하지 않는 측정 범위")
    if scope=="ABSOLUTE_GEOMETRY":
        vector(workcell["top"]["contact_offset_tool_m"],3,"그리퍼 밑면 접촉 오프셋")
    elif workcell["top"]["contact_offset_tool_m"] is not None:
        raise ValueError("CONTACT_REFERENCE는 미확인 밑면 오프셋을 null로 명시")
    if workcell["top"].get("auto_entry"):
        number(workcell["top"]["clearance_tcp_z_m"],"clearance_tcp_z_m",1e-9)
    if "side_entry_clearance_z_m" in workcell:
        number(workcell["side_entry_clearance_z_m"],"side_entry_clearance_z_m",1e-9)
    pose(workcell["top"]["approach_tcp_pose"])
    for key in ("entry_tcp_poses", "exit_tcp_poses"):
        for item in workcell["top"][key]:
            pose(item)
    number(workcell["top"]["max_probe_m"],"top.max_probe_m",1e-9)
    number(workcell["top"]["retract_m"],"top.retract_m",1e-9)
    angles = vector(workcell["angles_deg"],8,"angles_deg")
    for a,b in zip(angles,angles[1:]):
        if abs(abs(b-a)-45)>1e-6:
            raise ValueError("옆면은 연속 45도 간격 8점 필요")
    if len({round(a%360,6) for a in angles}) != 8:
        raise ValueError("중복 측정 각도")
    for name in ("travel","approach","retract","top_touch","side_touch"):
        p = profiles[name]
        for key in ("speed_m_s","acceleration_m_s2","timeout_s","hard_force_n"):
            number(p[key],name+"."+key,1e-9)
        if name.endswith("touch"):
            for key in ("contact_force_n","max_force_delta_n","baseline_window_s"):
                number(p[key],name+"."+key,1e-9)
            if p["contact_force_n"] >= p["max_force_delta_n"]:
                raise ValueError("접촉 힘은 최대 힘 변화 미만이어야 함")
    number(profiles["stop"]["timeout_s"],"stop.timeout_s",1e-9)
    if context.source_mode == "REAL":
        if not context.profile_snapshot_id or len(context.profile_sha256)!=64:
            raise ValueError("REAL은 등록 스냅샷 ID/해시 필요")
        int(context.profile_sha256,16)
        if scope=="ABSOLUTE_GEOMETRY" and workcell["top"].get("offset_status") != "VERIFIED":
            raise ValueError("그리퍼 밑면 오프셋 미확인: 실제 윗면 Z 계산 불가")
        if scope=="ABSOLUTE_GEOMETRY" and not workcell["top"].get("offset_record_id"):
            raise ValueError("밑면 오프셋 확인 기록 ID 필요")


def _move(target, profile, label):
    return dict(kind="MOVE",target_pose=pose(target),profile=profile,label=label)


def _probe(start, direction, distance, profile, label, point_index=0):
    end = list(start)
    for k in range(3):
        end[k] += direction[k]*distance
    return dict(kind="PROBE", start_pose=start, target_pose=end,
                direction=direction, max_m=distance, profile=profile, label=label,
                point_index=point_index)


def build_top_plan(w, initial_tip_pose=None):
    offset = w["tool_offset_m"]; top=w["top"]
    entry=top["entry_tcp_poses"]
    if top.get("auto_entry"):
        if initial_tip_pose is None:raise ValueError("자동 수직 진입은 현재 위치 필요")
        current=apply_tool_offset(pose(initial_tip_pose),offset,-1)
        lifted=current[:];lifted[2]=top["clearance_tcp_z_m"]
        aligned=lifted[:3]+top["approach_tcp_pose"][3:]
        along_x=aligned[:];along_x[0]=top["approach_tcp_pose"][0]
        above=along_x[:];above[1]=top["approach_tcp_pose"][1]
        entry=[lifted,aligned,along_x,above]
    steps = [_move(apply_tool_offset(p,offset),"travel","top_entry") for p in entry]
    start = apply_tool_offset(top["approach_tcp_pose"],offset)
    steps.append(_move(start,"approach","top_approach"))
    steps.append(_probe(start,[0.,0.,-1.],top["max_probe_m"],"top_touch","top_touch"))
    # 실측 후퇴의 시작 위치는 probe 구간 안. 백엔드는 전체 접촉 구간에서 후퇴를 검사한다.
    target = start[:]; target[2] += top["retract_m"]
    steps.append(_move(target,"retract","top_retract"))
    steps.extend(_move(apply_tool_offset(p,offset),"travel","top_exit") for p in top["exit_tcp_poses"])
    return steps


def build_side_plan(w, top_z):
    center=w["seed_axis_xy_m"]; radius=w["seed_radius_m"]
    z=top_z-w["side_depth_m"]; outer=radius+w["outer_gap_m"]
    steps=[]; previous=None
    for index,angle in enumerate(w["angles_deg"],1):
        if previous is None:
            # 임의 현재 위치에서 여기로 직행하지 않는다. preflight가 진입 전 구간도 검사.
            if "side_entry_clearance_z_m" in w:
                steps.append(_move(facing_pose(center,outer,w["side_entry_clearance_z_m"],angle),"travel","side_entry_above"))
            steps.append(_move(facing_pose(center,outer,z,angle),"travel","side_entry"))
        else:
            count=math.ceil(abs(angle-previous)/w["orbit_step_deg"])
            for k in range(1,count+1):
                steps.append(_move(facing_pose(center,outer,z,previous+(angle-previous)*k/count),"travel","orbit"))
        start=facing_pose(center,radius+w["start_gap_m"],z,angle)
        steps.append(_move(start,"approach",f"point_{index}_approach"))
        a=math.radians(angle); direction=[-math.cos(a),-math.sin(a),0.]
        steps.append(_probe(start,direction,w["start_gap_m"]+w["inside_limit_m"],"side_touch",f"point_{index}_touch",index))
        steps.append(_move(facing_pose(center,radius+w["slow_retract_gap_m"],z,angle),"retract",f"point_{index}_retract"))
        steps.append(_move(facing_pose(center,outer,z,angle),"approach",f"point_{index}_outer"))
        previous=angle
    return steps


def measure_workpiece(adapter, workcell, profiles, context, on_progress=None):
    """윗면·8점 + 정상 후퇴 완료 뒤 StepResult 반환. 실패 후 자동 후퇴/홈 없음.

    adapter: measurement_contract_version=1 구현(모의 구현 제공).
    반환 observed_state: measurement, events, stop_confirmed, partial, plans.
    REAL 백엔드가 없거나 준비/IK/배타 소유권을 확인할 수 없으면 이동 전에 거절.
    """
    data=dict(measurement_id=context.measurement_id, preparation_id=context.preparation_id,
              source_mode=context.source_mode, frame_id="c2_base", position_unit="m",
              schema="workpiece-measurement/1", validity="INCOMPLETE", geometry_ready=False,
              profile_snapshot_id=context.profile_snapshot_id,profile_sha256=context.profile_sha256,
              points=[],top=None,axis_xy_m=None,radius_m=None,top_z_m=None,bottom_z_m=None,
              measured_at=None,started_at=context.utc_now(),measurement_time_basis="completed_utc; contact_samples_monotonic")
    observed=dict(measurement=data,events=[],plans=[],stop_confirmed=None,partial=True)
    acquired=False; attempted=False; started=context.monotonic()
    w={}; p={}

    def event(stage,status,message,point_index=0,values=None):
        item=dict(measurement_id=context.measurement_id,sequence=len(observed["events"])+1,
                  measured_at=context.utc_now(),stage=stage,status=status,message=message,
                  point_index=point_index,total_points=8,values=values)
        observed["events"].append(item)
        if on_progress:
            on_progress(deepcopy(item))

    def check():
        if context.cancel.is_set():
            raise MeasurementError("CANCELLED","측정 취소 요청", "STOPPED")
        if context.monotonic()-started >= w["runtime_timeout_s"]:
            raise MeasurementError("TIMEOUT","측정 전체 제한 시간 초과")

    def state():
        check()
        o=adapter.observe_measurement()
        if o["quality"]!="VALID" or o["frame_id"]!=w["frame_id"]:
            raise MeasurementError("NOT_READY","현재 위치/좌표계 관측 불가")
        age=context.monotonic()-number(o["measured_at_monotonic_s"],"state time")
        if not 0 <= age <= w["max_state_age_s"]:
            raise MeasurementError("STALE_DATA","오래되거나 미래 시각인 로봇 상태")
        pose(o["tip_pose"]); vector(o["joints_rad"],6,"joints_rad")
        if o["robot_state"]!=1 or o["motion_status"]!=0:
            raise MeasurementError("NOT_READY","현재 로봇의 정상 정지 미확인")
        return o

    def run(steps):
        nonlocal attempted
        initial=state()
        check()
        # 백엔드는 시작 상태와 모든 구간(보간·접촉 탐색 범위·후퇴) 검사 및 소유권 확인.
        raw=json.dumps(dict(steps=steps,workcell=w,profiles=p),sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        plan_hash=hashlib.sha256(raw).hexdigest()
        report=adapter.preflight_measurement(deepcopy(steps),deepcopy(w),deepcopy(p),context)
        if not isinstance(report,StepResult) or not report.ok:
            raise MeasurementError(getattr(report,"error_code","NOT_READY"),getattr(report,"message","측정 이동 검사 미완료"),getattr(report,"outcome","UNKNOWN"))
        required=("all_segments_checked","probe_envelopes_checked","ownership_confirmed","drill_off_confirmed","tcp_load_match")
        if any(report.observed_state.get(k) is not True for k in required):
            raise MeasurementError("NOT_READY","측정 전 검사 필수 항목 미확인")
        current=state()
        if math.dist(current["tip_pose"][:3],initial["tip_pose"][:3])>w["pose_tolerance_m"] or max(abs(a-b) for a,b in zip(current["joints_rad"],initial["joints_rad"]))>w["angle_tolerance_rad"]:
            raise MeasurementError("NOT_READY","검사 도중 시작 위치/관절 변경")
        observed["plans"].append(dict(plan_sha256=plan_hash,checked_at=context.utc_now(),report=deepcopy(report.observed_state)))
        for step in steps:
            check()
            if step["kind"]=="PROBE":
                index=step["point_index"]
                event("TOP_TOUCH" if not index else "SIDE_TOUCH","RUNNING",
                      "윗면 접촉 확인 중" if not index else f"{index}/8번째 점 측정 중",index)
            # 예외/통신 단절도 이미 전달된 명령의 실행 가능성이 있어 정지 확인이 필요.
            attempted=True
            result=adapter.execute_measurement_step(deepcopy(step),deepcopy(p[step["profile"]]),context,
                                                     max(0,w["runtime_timeout_s"]-(context.monotonic()-started)))
            if not isinstance(result,StepResult) or not result.ok:
                raise MeasurementError(getattr(result,"error_code","INTERNAL_ERROR"),getattr(result,"message","백엔드 반환 오류"),getattr(result,"outcome","UNKNOWN"))
            check()
            if result.observed_state.get("stop_confirmed") is not True:
                raise MeasurementError("STOP_UNCONFIRMED","동작 완료 후 실제 정지 미확인","UNKNOWN")
            stopped_state=state()
            if step["kind"]=="MOVE" and (math.dist(stopped_state["tip_pose"][:3],step["target_pose"][:3])>w["pose_tolerance_m"] or rotation_distance(stopped_state["tip_pose"],step["target_pose"])>w["angle_tolerance_rad"]):
                raise MeasurementError("MOTION_INCOMPLETE","정지는 확인됐지만 목표 위치/자세에 도달하지 않음")
            if step["kind"]=="PROBE":
                hit=deepcopy(result.observed_state["contact"])
                contact_pose=pose(hit["tip_pose"])
                if hit.get("detected") is not True or hit.get("frame_id")!=w["frame_id"]:
                    raise MeasurementError("CONTACT_UNCONFIRMED","접촉값/좌표계 미확인")
                sample_t=number(hit["measured_at_monotonic_s"],"contact time")
                if not 0 <= context.monotonic()-sample_t <= w["max_state_age_s"]:
                    raise MeasurementError("STALE_DATA","접촉 측정값 시간 만료")
                force=number(hit["normal_force_n"],"normal_force_n")
                profile=p[step["profile"]]
                if not profile["contact_force_n"] <= force < profile["max_force_delta_n"]:
                    raise MeasurementError("CONTACT_UNCONFIRMED","접촉 힘 판정 범위 불일치")
                # 후보 위치가 검사한 선분 안에 있는지 다시 확인.
                d=[contact_pose[k]-step["start_pose"][k] for k in range(3)]
                travel=sum(d[k]*step["direction"][k] for k in range(3))
                lateral=math.sqrt(sum((d[k]-travel*step["direction"][k])**2 for k in range(3)))
                if not 0 <= travel <= step["max_m"] or lateral>w["pose_tolerance_m"]:
                    raise MeasurementError("CONTACT_OUT_OF_RANGE","접촉 위치가 검사한 탐색 범위 밖")
                if (rotation_distance(contact_pose,step["start_pose"])>w["angle_tolerance_rad"] or
                    math.dist(stopped_state["tip_pose"][:3],contact_pose[:3])>w["pose_tolerance_m"]):
                    raise MeasurementError("CONTACT_OUT_OF_RANGE","접촉 자세/접촉 후 정지 이동량 초과")
                hit.update(point_index=step["point_index"],received_at=context.utc_now(),source="SIMULATED" if context.source_mode=="SIMULATION" else "FORCE_CONTACT_ESTIMATE")
                if not step["point_index"]:
                    tcp=apply_tool_offset(contact_pose,w["tool_offset_m"],-1)
                    data["top"]=hit;data["top_tcp_contact_z_m"]=tcp[2]
                    top_offset=w["top"]["contact_offset_tool_m"]
                    if top_offset is not None:
                        data["top_z_m"]=apply_tool_offset(tcp,top_offset)[2]
                    event("TOP_TOUCH","SUCCEEDED","윗면 접촉 측정 완료",values=dict(
                        top_z_m=data["top_z_m"],top_tcp_contact_z_m=tcp[2],
                        absolute_top_valid=data["top_z_m"] is not None))
                else:
                    data["points"].append(hit)
                    event("SIDE_TOUCH","SUCCEEDED",f"{step['point_index']}/8번째 점 측정 완료",step["point_index"],dict(tip_xyz_m=contact_pose[:3]))

    try:
        w=deepcopy(workcell); p=deepcopy(profiles)
        _validate(w,p,context)
        if getattr(adapter,"measurement_contract_version",None)!=1 or getattr(adapter,"source_mode",None)!=context.source_mode:
            raise MeasurementError("UNSUPPORTED_ADAPTER","측정 계약 v1 백엔드 필요. 기존 DoosanRobotAdapter를 그대로 사용할 수 없음")
        acquired=context.motion_lock.acquire(blocking=False)
        if not acquired:
            raise MeasurementError("BUSY","다른 로봇 작업이 실행 중")
        check()
        event("START","RUNNING","측정을 시작합니다")
        event("TOP_APPROACH","RUNNING","양초 윗면을 측정하겠습니다")
        run(build_top_plan(w,state()["tip_pose"]))
        event("SIDE_START","RUNNING","양초 중심·반지름을 측정하겠습니다")
        reference_z=data["top_z_m"] if data["top_z_m"] is not None else data["top_tcp_contact_z_m"]
        data["measurement_scope"]=w.get("measurement_scope","ABSOLUTE_GEOMETRY")
        run(build_side_plan(w,reference_z))
        check()
        event("FIT","RUNNING","양초 좌표 계산 중")
        points=[h["tip_pose"][:3] for h in data["points"]]
        if len(points)!=8:
            raise MeasurementError("INVALID_MEASUREMENT","8점 미완료")
        fit=fit_circle(points)
        if (fit["residual_rms_m"]>w["max_fit_rms_m"] or fit["residual_max_m"]>w["max_fit_residual_m"] or
            math.dist(fit["axis_xy_m"],w["seed_axis_xy_m"])>w["max_center_shift_m"] or
            abs(fit["radius_m"]-w["seed_radius_m"])>w["max_radius_error_m"] or
            max(x[2] for x in points)-min(x[2] for x in points)>w["max_point_z_spread_m"]):
            observed["rejected_fit"]=fit
            raise MeasurementError("INVALID_MEASUREMENT","형상/잔차/이동 범위 조건 미충족")
        state()
        data.update(fit)
        data.update(height_m=w["height_m"],height_source=w["height_source"],
                    bottom_z_m=data["top_z_m"]-w["height_m"] if data["top_z_m"] is not None else None,
                    work_z_range_m=[data["top_z_m"]-w["height_m"]+w["bottom_margin_m"],data["top_z_m"]-w["top_margin_m"]] if data["top_z_m"] is not None else None,
                    work_v_range_m=[w["top_margin_m"],w["height_m"]-w["bottom_margin_m"]],
                    vertical_axis_assumed=True,tilt_measured=False,tool_offset_m=w["tool_offset_m"],
                    measured_at=context.utc_now(),validity="SIMULATED" if context.source_mode=="SIMULATION" else "FORCE_CONTACT_ESTIMATE",
                    geometry_ready=data["top_z_m"] is not None,independent_accuracy_verified=False)
        if data["top_z_m"] is None:data["validity"]="REFERENCE_ONLY"
        observed.update(partial=False,stop_confirmed=True)
        event("COMPLETE","SUCCEEDED","좌표 계산·후퇴 완료: 양초 측정 완료",values=deepcopy(data))
        return StepResult("SUCCEEDED",completed_step="workpiece_calibration",observed_state=observed)
    except Exception as exc:
        fallback = ("COMMUNICATION_LOST" if isinstance(exc,ConnectionError) else
                    "TIMEOUT" if isinstance(exc,TimeoutError) else
                    "INVALID_INPUT" if isinstance(exc,(ValueError,KeyError,TypeError)) else "INTERNAL_ERROR")
        code=getattr(exc,"code",fallback)
        outcome=getattr(exc,"outcome","FAILED")
        if outcome not in ("FAILED","STOPPED","UNKNOWN"):
            outcome="UNKNOWN"
        if attempted:
            try:
                stopped=adapter.stop_measurement(deepcopy(p["stop"]))
                confirmed=isinstance(stopped,StepResult) and stopped.ok and stopped.observed_state.get("stop_confirmed") is True
            except Exception:
                confirmed=False
            observed["stop_confirmed"]=confirmed
            # 정지가 확인되면 실패/취소로 확정. 미확인 상태에서는 후속 단계 금지.
            outcome=("STOPPED" if context.cancel.is_set() else "FAILED") if confirmed else "UNKNOWN"
        data.update(validity="INCOMPLETE",geometry_ready=False)
        observed["partial"]=True
        try:
            event("TERMINAL",outcome,str(exc))
        except Exception:
            pass
        return StepResult(outcome,code,str(exc),"workpiece_calibration",observed)
    finally:
        observed["elapsed_s"]=context.monotonic()-started
        if acquired:
            context.motion_lock.release()
