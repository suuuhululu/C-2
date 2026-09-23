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

from .tool_calibration import fixed_tool_reference, projection_from_contact
from .robot_adapter import StepResult, apply_tool_offset, matrix_to_quat, tool_axis_in_base


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


class PointMeasurementError(MeasurementError):
    """동작 결과가 불명확한 오류와 구분하는 내부 재측정 후보. 정지/후퇴 검사는 별도."""


class MoveRecoveryError(MeasurementError):
    """이동 step 의 제한된 자동 복구 후보 (9/23 R1·R2).

    추종/도달 품질 오류만 이 형으로 올린다. 힘·제어권·통신·현장 검사 실패는
    그대로 MeasurementError 다. 복구는 정지 확인 → 현재 위치 재관측 →
    남은 계획 전체 재검사(preflight·scene_check) → 같은 step 재실행 순서이며,
    검사를 건너뛰거나 허용 오차를 넓히지 않는다.
    """
    def __init__(self, code, message, outcome="FAILED", *, evidence=None):
        super().__init__(code, message, outcome)
        self.evidence = dict(evidence or {})


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
    attempts=workcell.get("side_point_max_attempts",1)
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError("side_point_max_attempts: 최초 포함 1~3회 필요")
    move_attempts=workcell.get("move_recovery_max_attempts",1)
    if type(move_attempts) is not int or not 1 <= move_attempts <= 3:
        raise ValueError("move_recovery_max_attempts: 최초 포함 1~3회 필요")
    if attempts>1 and side_contact_window(workcell) is None:
        raise ValueError("점 재측정은 분리된 baseline/접촉 구간 필요")
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
    before_search="side_search_m" in workcell
    if before_search:
        search=number(workcell["side_search_m"],"side_search_m",1e-9)
        lead=number(workcell["side_baseline_lead_in_m"],"side_baseline_lead_in_m",1e-9)
        if (abs(search-workcell["start_gap_m"]-workcell["inside_limit_m"])>1e-9 or
                workcell["start_gap_m"]+lead>=workcell["outer_gap_m"] or side_center_limit(workcell)<=0):
            raise ValueError("탐색 길이/양쪽 여유/비접촉 baseline 위치 범위 오류")
    elif "side_baseline_lead_in_m" in workcell:
        raise ValueError("side_baseline_lead_in_m에는 side_search_m 필요")
    if not before_search and not workcell["slow_retract_gap_m"] < workcell["start_gap_m"] < workcell["outer_gap_m"]:
        raise ValueError("후퇴/접촉 시작/외곽 간격 순서 오류")
    enabled=workcell.get("side_contact_window_enabled",workcell.get("source_mode")=="REAL")
    if type(enabled) is not bool:
        raise ValueError("side_contact_window_enabled는 bool 필요")
    if workcell.get("source_mode")=="REAL" and not enabled:
        raise ValueError("REAL 측정은 초기 위치 오차 접촉 구간 검사 필요")
    if before_search and not enabled:
        raise ValueError("탐색 전 baseline 모드는 탐색 구간 검사 필요")
    if enabled and not before_search:
        low,high=side_contact_window(workcell)
        allowance=workcell["max_center_shift_m"]+workcell["max_radius_error_m"]
        if (low<=0 or high>workcell["start_gap_m"]+workcell["inside_limit_m"]
                or workcell["slow_retract_gap_m"]<=allowance+workcell["pose_tolerance_m"]):
            raise ValueError("초기 위치 오차에 비해 시작/탐색/후퇴 범위 부족")
    if workcell["orbit_step_deg"] > 22.5:
        raise ValueError("현재 원호 분할은 22.5도 이하")
    if not isinstance(workcell["height_source"],str) or not workcell["height_source"]:
        raise ValueError("height_source 출처 필요")
    vector(workcell["seed_axis_xy_m"],2,"seed_axis_xy_m")
    vector(workcell["tool_offset_m"],3,"tool_offset_m")
    # 모르는 값을 0으로 대체하지 않는다. REAL은 출처도 필수.
    scope=workcell.get("measurement_scope","ABSOLUTE_GEOMETRY")
    if scope not in ("ABSOLUTE_GEOMETRY","CONTACT_REFERENCE","INTEGRATION_ESTIMATE"):
        raise ValueError("지원하지 않는 측정 범위")
    if scope=="ABSOLUTE_GEOMETRY":
        vector(workcell["top"]["contact_offset_tool_m"],3,"그리퍼 밑면 접촉 오프셋")
    elif scope=="CONTACT_REFERENCE" and workcell["top"]["contact_offset_tool_m"] is not None:
        raise ValueError("CONTACT_REFERENCE는 미확인 밑면 오프셋을 null로 명시")
    if scope=="INTEGRATION_ESTIMATE":
        top=workcell["top"]
        if top["contact_offset_tool_m"] is not None:
            offset=vector(top["contact_offset_tool_m"],3,"그리퍼 밑면 접촉 오프셋")
            if not isinstance(top.get("offset_record_id"),str) or not top["offset_record_id"].strip():
                raise ValueError("접촉 오프셋 기록 ID 필요")
            # 이전 설정과 함께 전달되면 같은 값인지 확인하고 한 번만 적용한다.
            if "estimated_contact_offset_tool_m" in top and vector(top["estimated_contact_offset_tool_m"],3,"이전 추정 오프셋")!=offset:
                raise ValueError("접촉 오프셋과 이전 추정 오프셋 불일치")
        else:
            vector(top["estimated_contact_offset_tool_m"],3,"통합용 가정 오프셋")
        if not isinstance(workcell["top"].get("estimate_source"),str) or not workcell["top"]["estimate_source"].strip():
            raise ValueError("통합용 윗면 추정의 출처 필요")
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
    if "expected_tcp_z_range_m" in workcell["top"]:
        lo,hi=vector(workcell["top"]["expected_tcp_z_range_m"],2,"expected_tcp_z_range_m")
        start=workcell["top"]["approach_tcp_pose"][2]
        if not start-workcell["top"]["max_probe_m"]<=lo<hi<=start:
            raise ValueError("윗면 접촉 예상 범위가 검사한 수직 탐색 구간 밖")
    home=workcell["home"]
    home_pose=pose(home["tcp_pose"])
    for entry in home.get("entry_tcp_poses",[]):
        candidate=pose(entry)
        if not home["top_corridor_min_z_m"]<candidate[2]<=home["clearance_tcp_z_m"]:
            raise ValueError("알려진 홈 진입 통로 높이 범위 오류")
    for key in ("clearance_tcp_z_m","overhead_z_m","position_tolerance_m","angle_tolerance_rad","corridor_xy_tolerance_m","top_corridor_min_z_m"):
        number(home[key],"home."+key,1e-9)
    if not (home["top_corridor_min_z_m"]<home_pose[2]<=home["clearance_tcp_z_m"] and
            home["top_corridor_min_z_m"]<home["overhead_z_m"]<=home["clearance_tcp_z_m"]):
        raise ValueError("홈/상공/윗면 탐색 높이 순서 오류")
    if tool_axis_in_base(home_pose,"+z")[2]>-math.cos(home["angle_tolerance_rad"]):
        raise ValueError("현재 홈 경유는 그리퍼 수직 자세만 지원")
    if not home.get("source_record"):
        raise ValueError("홈 좌표 출처 필요")
    angles = vector(workcell["angles_deg"],8,"angles_deg")
    for a,b in zip(angles,angles[1:]):
        if abs(abs(b-a)-45)>1e-6:
            raise ValueError("옆면은 연속 45도 간격 8점 필요")
    if len({round(a%360,6) for a in angles}) != 8:
        raise ValueError("중복 측정 각도")
    for name in dict.fromkeys(("travel","approach","retract","top_touch","side_touch",workcell.get("outer_move_profile","approach"))):
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
        if scope=="ABSOLUTE_GEOMETRY":
            top=workcell["top"]
            if not isinstance(top.get("offset_record_id"),str) or not top["offset_record_id"].strip():
                raise ValueError("밑면 오프셋 기록 ID 필요")
            if not isinstance(top.get("estimate_source"),str) or not top["estimate_source"].strip():
                raise ValueError("접촉 오프셋 출처 필요: 기존 estimate_source 필드 사용")


def _point_index_of(label):
    """point_N_* 라벨의 N. 다른 라벨은 0. 기존 이벤트 형식을 벗어나지 않는다."""
    if isinstance(label,str) and label.startswith("point_"):
        head=label[len("point_"):].split("_",1)[0]
        if head.isdigit():
            return int(head)
    return 0


def _recovery_stage(label):
    """이동 복구 이벤트의 stage. WORKPIECE_CALIBRATION.md 의 기존 목록만 사용한다."""
    if not isinstance(label,str):
        return "SIDE_START"
    if label.startswith("home_"):
        return "HOME_MOVE"
    if label.startswith("top_"):
        return "TOP_APPROACH"
    return "SIDE_TOUCH" if _point_index_of(label) else "SIDE_START"


def _move(target, profile, label):
    return dict(kind="MOVE",target_pose=pose(target),profile=profile,label=label)


def _probe(start, direction, distance, profile, label, point_index=0):
    end = list(start)
    for k in range(3):
        end[k] += direction[k]*distance
    return dict(kind="PROBE", start_pose=start, target_pose=end,
                direction=direction, max_m=distance, profile=profile, label=label,
                point_index=point_index)


def home_matches(w, tip_pose):
    current=apply_tool_offset(pose(tip_pose),w["tool_offset_m"],-1)
    h=w["home"]
    return (math.dist(current[:3],h["tcp_pose"][:3])<=h["position_tolerance_m"] and
            rotation_distance(current,h["tcp_pose"])<=h["angle_tolerance_rad"])


def build_home_plan(w, initial_tip_pose, initial_joints_rad=None):
    """검사 가능한 고정 현장 통로로만 홈 경유. 임의 시작점의 복구 플래너가 아님.

    양초 옆은 먼저 바깥으로 이탈, 윗면 통로는 수직 상승. 상공에서만 자세를
    맞춘 뒤 X/Y 분리 이동하고 홈으로 하강한다. 모든 구간은 실행 전 검사한다.
    """
    h=w["home"];offset=w["tool_offset_m"];tip=pose(initial_tip_pose)
    tcp=apply_tool_offset(tip,offset,-1);target=pose(h["tcp_pose"])
    if home_matches(w,tip):
        # 이미 홈이면 이 계획은 검사에만 사용하고 이동 명령은 보내지 않는다.
        return [_move(tip,"travel","home_down")]
    if tool_axis_in_base(tcp,"+z")[2]>-math.cos(h["angle_tolerance_rad"]):
        raise MeasurementError("HOME_PATH_UNAVAILABLE","홈 경유는 확인된 수직 자세에서만 가능")
    steps=[];center=w["seed_axis_xy_m"];radius=w["seed_radius_m"]
    top_corridor=(math.dist(tcp[:2],center)<=h["corridor_xy_tolerance_m"] and tcp[2]>=h["top_corridor_min_z_m"])
    home_corridor=any(math.dist(tcp[:2],p[:2])<=h["corridor_xy_tolerance_m"] and tcp[2]>=p[2]-h["position_tolerance_m"]
                      for p in [target,*h.get("entry_tcp_poses",[])])
    if tcp[2]<h["overhead_z_m"] and not (top_corridor or home_corridor):
        radial=[tip[k]-center[k] for k in range(2)];distance=math.hypot(*radial)
        axis=tool_axis_in_base(tip,"-y")
        if distance<radius or sum(-radial[k]/distance*axis[k] for k in range(2))<math.cos(h["angle_tolerance_rad"]):
            raise MeasurementError("HOME_PATH_UNAVAILABLE","양초 내부/방향 불명 시작점: 홈으로 자동 이동하지 않음")
        outer=radius+w["outer_gap_m"]
        if distance<outer:
            escape_steps=[]
            if distance<radius+w["slow_retract_gap_m"]:
                slow=min(outer,max(distance+w["slow_retract_gap_m"],radius+w["slow_retract_gap_m"]))
                escape_steps.append((slow,"home_escape_slow","retract"))
            escape_steps.append((outer,"home_escape_outer",w.get("outer_move_profile","approach")))
            for r,label,profile in escape_steps:
                tip=[center[0]+radial[0]*r/distance,center[1]+radial[1]*r/distance,*tip[2:]]
                steps.append(_move(tip,profile,label))
            tcp=apply_tool_offset(tip,offset,-1)
    if top_corridor and tcp[2]<w["top"]["approach_tcp_pose"][2]:
        # 윗면 근처에서 새 요청을 받았으면 확인된 접근 높이까지 저속/접촉용 기준으로 이탈한다.
        cleared=tcp[:];cleared[2]=w["top"]["approach_tcp_pose"][2]
        steps.append(_move(apply_tool_offset(cleared,offset),"retract","home_lift"))
        tcp=cleared
    lifted=tcp[:];lifted[2]=h["clearance_tcp_z_m"]
    aligned=lifted[:3]+target[3:]
    along_x=aligned[:];along_x[0]=target[0]
    above=along_x[:];above[1]=target[1]
    steps.append(_move(apply_tool_offset(lifted,offset),"travel","home_lift"))
    if initial_joints_rad is not None:
        joints=vector(initial_joints_rad,6,"initial_joints_rad")
        axis=tool_axis_in_base(tcp,"+y");home_axis=tool_axis_in_base(target,"+y")
        start_angle=math.degrees(math.atan2(axis[1],axis[0]))
        home_angle=math.degrees(math.atan2(home_axis[1],home_axis[0]))
        shortest=(home_angle-start_angle+180.)%360.-180.
        q6=math.degrees(joints[5])
        # 수직 자세에서 J6 여유를 예측해 회전 방향을 고른다. 실제 허용은 전 구간 IK/FK가 판단한다.
        turn=min((shortest-360.,shortest,shortest+360.),key=lambda a:(abs(q6-a),abs(a)))
        if abs(turn-shortest)>1e-6:
            # 같은 최종 자세라도 180도 미만 중간 자세를 명시해 반대 회전으로 축약되지 않게 한다.
            count=math.ceil(abs(turn)/90.)
            for i in range(1,count+1):
                orientation=facing_pose(center,1.,lifted[2],start_angle+turn*i/count)[3:]
                steps.append(_move(apply_tool_offset(lifted[:3]+orientation,offset),"travel","home_align"))
    for native,label in ((aligned,"home_align"),(along_x,"home_x"),(above,"home_y"),(target,"home_down")):
        candidate=apply_tool_offset(native,offset)
        previous=steps[-1]["target_pose"]
        # 분할 회전의 끝과 최종 정렬 등 같은 목표를 다시 명령하지 않는다.
        if math.dist(candidate[:3],previous[:3])<1e-9 and rotation_distance(candidate,previous)<1e-7:
            continue
        steps.append(_move(candidate,"travel",label))
    return steps


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
    steps=[]
    previous=pose(initial_tip_pose) if initial_tip_pose is not None else None
    for i,p in enumerate(entry):
        candidate=apply_tool_offset(p,offset)
        # 이미 윗면 상공 홈이면 다시 상승/정렬/X/Y를 명령하지 않고 바로 접근한다.
        if previous is not None and math.dist(candidate[:3],previous[:3])<=w["pose_tolerance_m"] and rotation_distance(candidate,previous)<=w["angle_tolerance_rad"]:
            continue
        label="home_lift" if i==0 and top.get("auto_entry") and home_matches(w,initial_tip_pose) else "top_entry"
        steps.append(_move(candidate,"travel",label))
        previous=candidate
    start = apply_tool_offset(top["approach_tcp_pose"],offset)
    steps.append(_move(start,"approach","top_approach"))
    steps.append(_probe(start,[0.,0.,-1.],top["max_probe_m"],"top_touch","top_touch"))
    # 실측 후퇴의 시작 위치는 probe 구간 안. 백엔드는 전체 접촉 구간에서 후퇴를 검사한다.
    target = start[:]; target[2] += top["retract_m"]
    steps.append(_move(target,"retract","top_retract"))
    steps.extend(_move(apply_tool_offset(p,offset),"travel","top_exit") for p in top["exit_tcp_poses"])
    return steps


def side_center_limit(w):
    """새 탐색의 양쪽 도달 여유로 계산한 중심 이동 한계. 전체 충돌 승인값은 아님."""
    if "side_search_m" not in w:
        return w["max_center_shift_m"]
    return min(w["start_gap_m"],w["side_search_m"]-w["start_gap_m"])-w["max_radius_error_m"]-w["pose_tolerance_m"]


def side_contact_window(w):
    """탐색 전 baseline 모드는 전체 탐색 구간, 구형 설정은 예상 접촉 창을 반환한다."""
    enabled=w.get("side_contact_window_enabled",w.get("source_mode")=="REAL")
    if type(enabled) is not bool or (w.get("source_mode")=="REAL" and not enabled):
        raise ValueError("REAL 측정은 초기 위치 오차 접촉 구간 검사 필요")
    if not enabled:
        return None
    if "side_search_m" in w:
        lead=number(w["side_baseline_lead_in_m"],"side_baseline_lead_in_m",1e-9)
        return [lead,lead+number(w["side_search_m"],"side_search_m",1e-9)]
    allowance = w["max_center_shift_m"] + w["max_radius_error_m"]
    tolerance = w["pose_tolerance_m"]
    return [w["start_gap_m"]-allowance-tolerance,
            w["start_gap_m"]+allowance+tolerance]


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
        lead=w.get("side_baseline_lead_in_m",0.)
        search_start=facing_pose(center,radius+w["start_gap_m"],z,angle)
        start=facing_pose(center,radius+w["start_gap_m"]+lead,z,angle)
        steps.append(_move(start,"approach",f"point_{index}_approach"))
        a=math.radians(angle); direction=[-math.cos(a),-math.sin(a),0.]
        steps.append(_probe(start,direction,lead+w["start_gap_m"]+w["inside_limit_m"],"side_touch",f"point_{index}_touch",index))
        if side_contact_window(w) is not None:
            steps[-1]["contact_travel_range_m"]=side_contact_window(w)
            steps[-1]["expected_contact_travel_m"]=lead+w["start_gap_m"]
        if lead:
            steps[-1]["search_start_pose"]=search_start
            steps[-1]["baseline_before_search"]=True
        # 이른 접촉에서도 안쪽으로 후퇴하지 않는다. 같은 방사선의 baseline 시작점으로 돌아간다.
        retreat=start if lead else facing_pose(center,radius+w["slow_retract_gap_m"],z,angle)
        steps.append(_move(retreat,"retract",f"point_{index}_retract"))
        steps.append(_move(facing_pose(center,outer,z,angle),w.get("outer_move_profile","approach"),f"point_{index}_outer"))
        previous=angle
    return steps


def measure_workpiece(adapter, workcell, profiles, context, on_progress=None):
    """윗면·8점·원 맞춤 + 정상 홈 복귀. 명시된 점 오류만 제한 재측정.

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
    observed=dict(measurement=data,events=[],plans=[],stop_confirmed=None,partial=True,home_return_confirmed=False)
    acquired=False; attempted=False; started=context.monotonic()
    w={}; p={}; point_attempts={}; move_attempts={}
    observed["point_attempts"]=point_attempts
    # 외부 계약. move_attempts 의 내부 tuple 키를 그대로 내보내지 않는다 (JSON 직렬화 불가).
    observed["move_recoveries"]=[]

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

    def run(steps, *, execute=True):
        nonlocal attempted
        initial=state()
        check()
        # 백엔드는 시작 상태와 모든 구간(보간·접촉 탐색 범위·후퇴) 검사 및 소유권 확인.
        raw=json.dumps(dict(steps=steps,workcell=w,profiles=p),sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        plan_hash=hashlib.sha256(raw).hexdigest()
        report=adapter.preflight_measurement(deepcopy(steps),deepcopy(w),deepcopy(p),context)
        if not isinstance(report,StepResult) or not report.ok:
            raise MeasurementError(getattr(report,"error_code","NOT_READY"),getattr(report,"message","측정 이동 검사 미완료"),getattr(report,"outcome","UNKNOWN"))
        required=("all_segments_checked","probe_envelopes_checked","ownership_confirmed","tcp_load_match")
        if any(report.observed_state.get(k) is not True for k in required):
            raise MeasurementError("NOT_READY","측정 전 검사 필수 항목 미확인")
        current=state()
        if math.dist(current["tip_pose"][:3],initial["tip_pose"][:3])>w["pose_tolerance_m"] or max(abs(a-b) for a,b in zip(current["joints_rad"],initial["joints_rad"]))>w["angle_tolerance_rad"]:
            raise MeasurementError("NOT_READY","검사 도중 시작 위치/관절 변경")
        observed["plans"].append(dict(plan_sha256=plan_hash,checked_at=context.utc_now(),report=deepcopy(report.observed_state)))
        if not execute:
            return
        for position,step in enumerate(steps):
            try:
                execute_one(step)
            except MoveRecoveryError as exc:
                # 추종/도달 품질 오류만 온다. 허용 오차를 넓히지 않고 다시 정렬해서 같은 step 을 재실행한다.
                if w.get("move_recovery_max_attempts",1)==1:
                    raise
                # 내부 조회용 키. 같은 label 의 다른 목표(orbit 등)를 구분한다. 외부로 내보내지 않는다.
                key=(step["label"],tuple(step["target_pose"]))
                move_attempts[key]=move_attempts.get(key,0)+1
                record=next((r for r in observed["move_recoveries"]
                             if r["label"]==step["label"] and r["target_pose_m"]==list(step["target_pose"])),None)
                if record is None:
                    record=dict(label=step["label"],target_pose_m=list(step["target_pose"]),attempts=0,reasons=[])
                    observed["move_recoveries"].append(record)
                record["attempts"]=move_attempts[key];record["reasons"].append(exc.code)
                # 접수 여부가 불명확한 명령이 남아 있을 수 있으므로 먼저 실제 정지를 확인한다.
                confirmed_stop()
                current=state()["tip_pose"]
                index=_point_index_of(step["label"])
                event(_recovery_stage(step["label"]),"RUNNING","이동 오차 복구: 정지 확인·현재 위치에서 재정렬",
                      index,dict(attempt=move_attempts[key],reason=exc.code,label=step["label"],
                                 evidence=deepcopy(exc.evidence)))
                if move_attempts[key]>=w["move_recovery_max_attempts"]:
                    raise MeasurementError("RECOVERY_REQUIRED",
                        f"{step['label']} 이동 {move_attempts[key]}회 복구 실패: {exc}")
                # 현재 위치 기준으로 같은 step 부터 남은 계획을 전부 다시 검사(IK·현장)한 뒤 재실행한다.
                run(steps[position:])
                return
            except PointMeasurementError as exc:
                if (step["kind"]!="PROBE" or not step["point_index"] or
                        exc.outcome!="FAILED" or exc.code not in ("UNSTABLE_BASELINE","CONTACT_NOT_FOUND","CONTACT_OUT_OF_RANGE") or
                        w.get("side_point_max_attempts",1)==1):
                    raise
                index=step["point_index"]
                # 통신/설정/제어권/힘 오류는 이 예외 유형으로 변환하지 않는다.
                confirmed_stop()
                current=state()["tip_pose"]
                delta=[current[k]-step["start_pose"][k] for k in range(3)]
                travel=sum(delta[k]*step["direction"][k] for k in range(3))
                lateral=math.sqrt(sum((delta[k]-travel*step["direction"][k])**2 for k in range(3)))
                if (not -w["pose_tolerance_m"]<=travel<=step["max_m"]+w["pose_tolerance_m"] or
                        lateral>w["pose_tolerance_m"] or
                        rotation_distance(current,step["start_pose"])>w["angle_tolerance_rad"]):
                    raise MeasurementError("RECOVERY_REQUIRED","같은 점의 검사된 방사선 후퇴 범위 밖")
                event("SIDE_TOUCH","RUNNING","같은 점 재측정 전 정지 확인·후퇴",index,
                      dict(attempt=point_attempts[index],reason=exc.code))
                # 시작점보다 바깥의 정지 위치에서는 안쪽으로 후퇴하지 않는다.
                target=current if travel<0 else step["start_pose"]
                run([_move(target,"retract",f"point_{index}_retract")])
                if point_attempts[index]>=w["side_point_max_attempts"]:
                    raise MeasurementError("RECOVERY_REQUIRED",f"{index}번 점 {point_attempts[index]}회 측정 실패: {exc}")
                # baseline은 probe 호출 안에서 새로 확보한다. 남은 구간 캐시도 재검사.
                run([_move(step["start_pose"],"approach",f"point_{index}_approach"),*steps[position:]])
                return

    def confirmed_stop():
        stopped=adapter.stop_measurement(deepcopy(p["stop"]))
        if not isinstance(stopped,StepResult) or not stopped.ok or stopped.observed_state.get("stop_confirmed") is not True:
            raise MeasurementError("STOP_UNCONFIRMED","점 재측정 전 실제 정지 미확인","UNKNOWN")
        observed["stop_confirmed"]=True
        state()

    def execute_one(step):
        nonlocal attempted
        check()
        if step["kind"]=="PROBE":
            index=step["point_index"]
            if index:
                point_attempts[index]=point_attempts.get(index,0)+1
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
            raise MoveRecoveryError("MOTION_INCOMPLETE","정지는 확인됐지만 목표 위치/자세에 도달하지 않음",
                evidence=dict(position_error_m=math.dist(stopped_state["tip_pose"][:3],step["target_pose"][:3]),
                              angle_error_rad=rotation_distance(stopped_state["tip_pose"],step["target_pose"])))
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
            contact_range=step.get("contact_travel_range_m")
            if contact_range is not None and not contact_range[0]<=travel<=contact_range[1]:
                raise PointMeasurementError("CONTACT_OUT_OF_RANGE","허용 접촉 구간 밖의 접촉점")
            if not 0 <= travel <= step["max_m"] or lateral>w["pose_tolerance_m"]:
                raise MeasurementError("CONTACT_OUT_OF_RANGE","접촉 위치가 검사한 탐색 범위 밖")
            if (rotation_distance(contact_pose,step["start_pose"])>w["angle_tolerance_rad"] or
                math.dist(stopped_state["tip_pose"][:3],contact_pose[:3])>w["pose_tolerance_m"]):
                raise MeasurementError("CONTACT_OUT_OF_RANGE","접촉 자세/접촉 후 정지 이동량 초과")
            # 검증에 사용한 기본 Python 수치형을 반환한다. ROS의 numpy.float64를
            # 원본 hit에 남기면 공정 Action의 엄격한 type 검사에서 거절된다.
            hit.update(tip_pose=contact_pose, normal_force_n=force,
                       measured_at_monotonic_s=sample_t,
                       point_index=step["point_index"],received_at=context.utc_now(),
                       source="SIMULATED" if context.source_mode=="SIMULATION" else "FORCE_CONTACT_ESTIMATE")
            if not step["point_index"]:
                tcp=apply_tool_offset(contact_pose,w["tool_offset_m"],-1)
                expected_z=w["top"].get("expected_tcp_z_range_m")
                if expected_z is not None and not expected_z[0]<=tcp[2]<=expected_z[1]:
                    observed["rejected_top_contact"]=dict(contact=hit,tcp_z_m=tcp[2],expected_tcp_z_range_m=expected_z)
                    raise MeasurementError("CONTACT_OUT_OF_RANGE","윗면 접촉 위치가 기존 고정 현장의 확인 범위 밖")
                data["top"]=hit;data["top_tcp_contact_z_m"]=tcp[2]
                top_offset=w["top"]["contact_offset_tool_m"]
                # 상태 문자열은 수용 조건이 아니라 결과의 검증 수준을 설명한다.
                estimated=(w.get("measurement_scope")=="INTEGRATION_ESTIMATE" or
                           (context.source_mode=="REAL" and top_offset is not None and
                            w["top"].get("offset_status")!="VERIFIED"))
                if estimated:
                    if top_offset is None:
                        top_offset=w["top"]["estimated_contact_offset_tool_m"]
                    data["top_z_source"]="CONTACT_BASED_ESTIMATE"
                    data["top_estimate_source"]=w["top"]["estimate_source"]
                    data["assumed_top_contact_offset_tool_m"]=list(top_offset)
                if top_offset is not None:
                    # tool +Z가 아래인 수직 자세에서는 +0.020 m가 base Z -20 mm.
                    data["top_z_m"]=apply_tool_offset(tcp,top_offset)[2]
                data["absolute_top_verified"]=top_offset is not None and not estimated
                event("TOP_TOUCH","SUCCEEDED","윗면 접촉 측정 완료",values=dict(
                    top_z_m=data["top_z_m"],top_tcp_contact_z_m=tcp[2],
                    absolute_top_valid=data["absolute_top_verified"],top_z_source=data.get("top_z_source","CALIBRATED_CONTACT" if top_offset is not None else "TCP_REFERENCE")))
            else:
                old=next((h for h in data["points"] if h["point_index"]==step["point_index"]),None)
                if old is not None:
                    observed.setdefault("superseded_points",[]).append(deepcopy(old))
                    data["points"].remove(old)
                data["points"].append(hit)
                data["points"].sort(key=lambda h:h["point_index"])
                if step["point_index"]==1 and w.get("projection_reference_source"):
                    # 현재 8점에서 다시 맞춘 원을 쓰지 않는다. 접촉 전 스냅샷 기준면을 재사용.
                    angle=math.radians(w["angles_deg"][0]);normal=[math.cos(angle),math.sin(angle),0.]
                    reference=[w["seed_axis_xy_m"][k]+w["seed_radius_m"]*normal[k] for k in range(2)]+[contact_pose[2]]
                    tcp=apply_tool_offset(contact_pose,w["tool_offset_m"],-1)
                    data["tool_projection_check"]=projection_from_contact(tcp,reference,normal,w["tool_offset_m"],
                        reference_source=w["projection_reference_source"],measured_at=hit["received_at"])
                    data["tool_projection_check"]["point_index"]=1
                event("SIDE_TOUCH","SUCCEEDED",f"{step['point_index']}/8번째 점 측정 완료",step["point_index"],dict(tip_xyz_m=contact_pose[:3]))

    try:
        w=deepcopy(workcell); p=deepcopy(profiles)
        _validate(w,p,context)
        if getattr(adapter,"measurement_contract_version",None)!=1 or getattr(adapter,"source_mode",None)!=context.source_mode:
            raise MeasurementError("UNSUPPORTED_ADAPTER","측정 계약 v1 백엔드 필요. 기존 DoosanRobotAdapter를 그대로 사용할 수 없음")
        if w.get("tcp_id") and w.get("load_id"):
            data["tool_reference"]=fixed_tool_reference(w["tool_offset_m"],tool_id=w.get("tool_id","engraving_drill"),
                tcp_id=w["tcp_id"],load_id=w["load_id"],
                source_record=w.get("tool_offset_source") or "CONFIG_SNAPSHOT:"+context.profile_snapshot_id)
        acquired=context.motion_lock.acquire(blocking=False)
        if not acquired:
            raise MeasurementError("BUSY","다른 로봇 작업이 실행 중")
        check()
        event("START","RUNNING","측정을 시작합니다")
        initial=state()
        observed["initial_state"]=deepcopy(initial)
        event("HOME_CHECK","RUNNING","현재 관절·TCP 확인: 홈 경유 경로 검사 중")
        home_plan=build_home_plan(w,initial["tip_pose"],initial["joints_rad"])
        event("HOME_MOVE","RUNNING","홈 위치를 확인하겠습니다" if home_matches(w,initial["tip_pose"]) else "검사 후 외곽·상공을 경유하여 홈으로 이동합니다")
        already_home=home_matches(w,initial["tip_pose"])
        run(home_plan,execute=not already_home)
        observed["home_move_skipped"]=already_home
        home_state=state()
        if not home_matches(w,home_state["tip_pose"]):
            raise MeasurementError("HOME_NOT_REACHED","홈 도착 미확인: 측정 시작 금지")
        observed["home_state"]=deepcopy(home_state)
        event("HOME_READY","SUCCEEDED","홈 도착·정지 확인 완료")
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
        def acceptable(fit, samples):
            return (fit["residual_rms_m"]<=w["max_fit_rms_m"] and fit["residual_max_m"]<=w["max_fit_residual_m"] and
                    math.dist(fit["axis_xy_m"],w["seed_axis_xy_m"])<=side_center_limit(w) and
                    abs(fit["radius_m"]-w["seed_radius_m"])<=w["max_radius_error_m"] and
                    max(x[2] for x in samples)-min(x[2] for x in samples)<=w["max_point_z_spread_m"])

        fit=fit_circle(points); retried_outlier=None; current_angle=w["angles_deg"][-1]
        while not acceptable(fit,points):
            observed["rejected_fit"]=deepcopy(fit)
            if w.get("side_point_max_attempts",1)==1:
                raise MeasurementError("INVALID_MEASUREMENT","형상/잔차/이동 범위 조건 미충족")
            # 7점으로 결과를 승인하지 않는다. 유일하게 설명되는 한 점만 재취득한다.
            candidates=[]
            for k in range(8):
                others=points[:k]+points[k+1:]
                try: candidate=fit_circle(others)
                except ValueError: continue
                residual=abs(math.dist(points[k][:2],candidate["axis_xy_m"])-candidate["radius_m"])
                if acceptable(candidate,others) and residual>w["max_fit_residual_m"]:
                    candidates.append(k+1)
            if len(candidates)!=1 or (retried_outlier is not None and candidates[0]!=retried_outlier):
                raise MeasurementError("INVALID_MEASUREMENT","단일 이상점 식별 불가: 형상/고정 상태 재확인 필요")
            index=candidates[0]; retried_outlier=index
            if point_attempts[index]>=w["side_point_max_attempts"]:
                raise MeasurementError("RECOVERY_REQUIRED",f"{index}번 점 재측정 한도 후에도 원 맞춤 불일치")
            confirmed_stop()
            event("FIT","RUNNING","단일 이상점만 재측정",index,dict(attempt=point_attempts[index]+1))
            # 마지막 측정의 외곽 위치에서 검증된 원주 경유. 내부 직선 횡단 금지.
            angle=w["angles_deg"][index-1];z=reference_z-w["side_depth_m"]
            outer=w["seed_radius_m"]+w["outer_gap_m"]
            expected=facing_pose(w["seed_axis_xy_m"],outer,z,current_angle)
            actual=state()["tip_pose"]
            if math.dist(actual[:3],expected[:3])>w["pose_tolerance_m"] or rotation_distance(actual,expected)>w["angle_tolerance_rad"]:
                raise MeasurementError("RECOVERY_REQUIRED","이상점 재측정 전 외곽 도착 미확인")
            count=max(1,math.ceil(abs(angle-current_angle)/w["orbit_step_deg"]))
            route=[_move(facing_pose(w["seed_axis_xy_m"],outer,z,current_angle+(angle-current_angle)*k/count),"travel","orbit") for k in range(1,count+1)]
            prefix=f"point_{index}_"
            route.extend(step for step in build_side_plan(w,reference_z) if step["label"].startswith(prefix))
            run(route);current_angle=angle
            points=[h["tip_pose"][:3] for h in data["points"]]
            fit=fit_circle(points)
        return_start=state()
        observed["home_return_start"]=deepcopy(return_start)
        event("HOME_RETURN","RUNNING","측정 완료: 검사한 경로로 상공 홈에 복귀합니다")
        return_plan=build_home_plan(w,return_start["tip_pose"],return_start["joints_rad"])
        run(return_plan,execute=not home_matches(w,return_start["tip_pose"]))
        final_state=state()
        if not home_matches(w,final_state["tip_pose"]):
            raise MeasurementError("HOME_NOT_REACHED","측정 후 홈 도착 미확인")
        observed.update(home_return_confirmed=True,final_state=deepcopy(final_state))
        event("HOME_RETURN","SUCCEEDED","상공 홈 도착·정지 확인 완료")
        check()
        data.update(fit)
        data.update(height_m=w["height_m"],height_source=w["height_source"],
                    bottom_z_m=data["top_z_m"]-w["height_m"] if data["top_z_m"] is not None else None,
                    work_z_range_m=[data["top_z_m"]-w["height_m"]+w["bottom_margin_m"],data["top_z_m"]-w["top_margin_m"]] if data["top_z_m"] is not None else None,
                    work_v_range_m=[w["top_margin_m"],w["height_m"]-w["bottom_margin_m"]],
                    vertical_axis_assumed=True,tilt_measured=False,tool_offset_m=w["tool_offset_m"],
                    measured_at=context.utc_now(),validity="SIMULATED" if context.source_mode=="SIMULATION" else "FORCE_CONTACT_ESTIMATE",
                    geometry_ready=data["top_z_m"] is not None,independent_accuracy_verified=False)
        if data["top_z_m"] is None:data["validity"]="REFERENCE_ONLY"
        elif w.get("measurement_scope")=="INTEGRATION_ESTIMATE" or (context.source_mode=="REAL" and not data["absolute_top_verified"]):data["validity"]="ESTIMATED"
        data["work_v_origin"]="TOP";data["work_v_positive_direction"]="DOWN"
        observed.update(partial=False,stop_confirmed=True)
        event("COMPLETE","SUCCEEDED","좌표 계산·홈 복귀 완료: 양초 측정 완료",values=deepcopy(data))
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
