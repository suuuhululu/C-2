#!/usr/bin/env python3
"""workcell.py — 워크셀·도구 상수와 원통 기하 계산 (test_only).

값 출처
  - ws_cobot_pjt/docs/evidence/workcell_candle_0919.yaml (시율님 9/19 실측, PR #32 병합) — 아래 반지름은
    이 yaml 의 0.034(자로 잰 값)를 9/20 캘리퍼스 재측정값으로 대체한 것이라 yaml 은 아직 구버전이다.
    yaml 자체도 팀이 갱신해야 한다.
  - 시율님 2026-09-20: 캘리퍼스 실측 지름 68.5mm(±0.3) → 반지름 34.25mm 확정.
    (참고: 같은 실측에서 나온 "돌출 99.55mm"는 툴-드릴끝 TCP 길이라 c2_path 워크셀 상수가 아니다 —
    c2_process 쪽 TCP 프로파일에 반영될 값)
  - 시율님 2026-09-20: 각도 기준 0° = base +X(로봇 반대편), 반시계 양수,
    이음매 = ±180°(−X 면, 로봇 쪽 = J5 위험 구역)
  - 시율님 2026-09-20 J5 실측: θ=180°(−X)에서 J5=175°(±135° 한계 초과), θ=0°·±90° 는 정상,
    그 사이는 미실측. 우선 |θ|≤135° 를 금지 조건으로 반영(잠정치) — 오늘 5° 간격 실측 후 갱신 예정.
  - 세은님 2026-09-19 확정: tool_id = engraving_drill
  - 팀장님 확정: frame_id = c2_base
"""
import math

# --- 원기둥(양초) ----------------------------------------------------------
RADIUS_M = 0.03425                    # 9/20 캘리퍼스 실측 지름 68.5mm(±0.3)의 절반 — 자로 잰 34mm 대체
HEIGHT_TOTAL_M = 0.150                # 시율님 확정
AXIS_ORIGIN_XY_M = (0.4218, 0.0001)   # 0919 실측 (+Y·−Y 면 3점 두 벌 평균). 0918 값 (0.4224, −0.0026) 대체
TOP_Z_BASE_M = 0.2334                 # 0919 손끝 수직 터치 실측 (추정 0.2344 보다 −1.0mm)
AXIS_ORIGIN_Z_M = TOP_Z_BASE_M - HEIGHT_TOTAL_M   # 0.0834 = 양초 바닥 (yaml bottom_z_base_m 과 동일 계산)
AXIS_DIRECTION = (0.0, 0.0, 1.0)

# 작업 가능 높이 구간: "윗면 아래 20~65mm"를 축 원점(바닥) 기준 상대값으로 환산.
# 양초가 통째로 올라가도 윗면 기준 상대 구간은 그대로다.
WORKABLE_HEIGHT_RANGE_M = (HEIGHT_TOTAL_M - 0.065, HEIGHT_TOTAL_M - 0.020)  # (0.085, 0.130)

# --- 각도/이음매 -----------------------------------------------------------
# 각도 θ: 0° = base +X(로봇 반대편), 축 +Z 기준 반시계 양수 (시율님 9/20).
# 도안 배치 원점(u=0)과 이음매는 서로 다른 개념이라 상수를 나눈다.
#   - U_ORIGIN_ANGLE_DEG: offset_u=0 인 도안 중심이 놓이는 각도 (권장안 69줄: u 원점은 표면 설정에 정의)
#   - SEAM_ANGLE_DEG   : 획이 넘으면 안 되는 선. 전개면 u = −πR ~ +πR 의 양 끝이 이음매가 된다.
U_ORIGIN_ANGLE_DEG = 0.0              # u=0 = +X 면 (로봇 반대편)
SEAM_ANGLE_DEG = 180.0                # 이음매 = ±180° = −X 면 (로봇 쪽, J5 위험 구역) — 시율님 9/20
# CUT 이 들어가도 되는 θ 범위. 시율님 9/20 J5 실측(θ=180°에서 J5=175°, ±135° 초과) 기준 잠정치.
# 오늘 5° 간격 실측으로 정확한 한계각이 나오면 갱신한다.
REACHABLE_ANGLE_DEG = (-135.0, 135.0)
STROKE_MAX_ARC_DEG = 180.0            # 한 획의 둘레 각도 범위 상한 (J6 감김 방지)

# 이음매 분할 등으로 생기는 퇴화 조각(점 2~3개, 길이 거의 0)은 버린다 — 실제 절삭 의미가 없고
# 제어기가 동일점 movesx 를 거부할 수 있다 (시율님 9/20 heart_seam 실측).
MIN_STROKE_LEN_M = 0.001

# --- 도구/프레임 -----------------------------------------------------------
TOOL_ID = "engraving_drill"           # 세은님 2026-09-19 확정
TOOL_VERSION = 1
TCP_PROFILE_ID = "GripperDA_v1"       # 권장안 4절 "사용 TCP·하중 프로파일 ID·버전"
TCP_PROFILE_VERSION = 1
LOAD_PROFILE_ID = "ToolWeight_1"
LOAD_PROFILE_VERSION = 1
WORKCELL_ID = "candle_test_0919"
WORKCELL_VERSION = 1
TOOLS_CONFIG_ID = "c2_tools"
TOOLS_CONFIG_VERSION = 1
FRAME_ID = "c2_base"                  # 팀장님 확정

# --- 경로 파일 형식 (로봇팀 engraving.py / joint_check.py 와 동일) -----------
# engraving.py SUPPORTED_SCHEMA=(2,), waypoint = [x, y, z, qx, qy, qz, qw] (m, 정규화 quaternion).
# 9/19 세은님 답변에 따라 c2_path 가 로봇팀 형식에 맞춘다 (2026-09-20).
PATH_SCHEMA_VERSION = 2
POSE_LEN = 7

# --- 모션 ------------------------------------------------------------------
CLEARANCE_STROKE_M = 0.010            # 획 사이 이격
CLEARANCE_FIRST_LAST_M = 0.030        # 첫 접근 / 마지막 후퇴
WAYPOINT_SPACING_MAX_M = 0.002        # CUT 내 간격 상한
WAYPOINT_SPACING_MIN_M = 0.0003       # 너무 촘촘한 점은 합친다 (적응형 하한)
CHORD_TOLERANCE_M = 0.00005           # 적응형 샘플링 현 오차 허용 (0.05mm)
SEGMENT_POINTS_MAX = 80               # CUT segment 최대 점 수 (movesx 한도 100에 여유)

MOTION_PROFILE = {
    "approach": "candle_approach",
    "cut": "candle_cut",
    "travel": "candle_travel",
    "retract": "candle_retract",
}


# --- 기하 ------------------------------------------------------------------
def radial_direction(theta_deg):
    """theta=0 이 base +X 인 바깥쪽 반경 단위벡터 (축 +Z 기준 반시계가 양)."""
    t = math.radians(theta_deg)
    return (math.cos(t), math.sin(t), 0.0)


def surface_point(theta_deg, height_m):
    r = radial_direction(theta_deg)
    return (AXIS_ORIGIN_XY_M[0] + RADIUS_M * r[0],
            AXIS_ORIGIN_XY_M[1] + RADIUS_M * r[1],
            AXIS_ORIGIN_Z_M + height_m)


def offset_point(theta_deg, height_m, clearance_m):
    """표면에서 바깥쪽 법선으로 clearance 만큼 떨어진 점 (반지름 R+clearance 원통 위)."""
    r = radial_direction(theta_deg)
    return (AXIS_ORIGIN_XY_M[0] + (RADIUS_M + clearance_m) * r[0],
            AXIS_ORIGIN_XY_M[1] + (RADIUS_M + clearance_m) * r[1],
            AXIS_ORIGIN_Z_M + height_m)


def to_pose7(position, quat_xyzw, ndigits=6):
    """(x,y,z) m + (qx,qy,qz,qw) -> 로봇팀 waypoint [x, y, z, qx, qy, qz, qw]."""
    return [round(float(c), ndigits) for c in tuple(position) + tuple(quat_xyzw)]


def normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def rotation_matrix_to_quat_xyzw(x_axis, y_axis, z_axis):
    m00, m01, m02 = x_axis[0], y_axis[0], z_axis[0]
    m10, m11, m12 = x_axis[1], y_axis[1], z_axis[1]
    m20, m21, m22 = x_axis[2], y_axis[2], z_axis[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    q = (x, y, z, w)
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def tool_orientation(theta_deg):
    """Tool -Y = 표면 안쪽 법선 (세은님), Tool +Z = base -Z (시율님 9/18 실기 자세).

    주의: 이 함수만으로는 인접 자세의 부호 연속성이 보장되지 않는다.
    theta 가 180도를 지날 때 trace 분기가 바뀌며 q 와 -q 가 번갈아 나온다.
    경로를 만들 때는 반드시 make_continuous() 로 부호를 이어 붙인다.
    """
    y_axis = normalize(radial_direction(theta_deg))   # 로컬 +Y = 바깥쪽 법선
    z_axis = (0.0, 0.0, -1.0)                         # 로컬 +Z = 아래
    x_axis = normalize(cross(y_axis, z_axis))
    return rotation_matrix_to_quat_xyzw(x_axis, y_axis, z_axis)


def quat_dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def make_continuous(quats):
    """인접 쿼터니언의 부호를 이어 붙인다. q 와 -q 는 같은 회전이지만
    부호가 튀면 보간 시 손목이 먼 쪽으로 돌 수 있다 (실측: theta=180도 통과 지점)."""
    out = []
    prev = None
    for q in quats:
        if prev is not None and quat_dot(prev, q) < 0.0:
            q = tuple(-c for c in q)
        out.append(q)
        prev = q
    return out


def quat_angle_deg(a, b):
    """두 자세 사이 회전각(도). 부호 무시."""
    d = min(1.0, abs(quat_dot(a, b)))
    return math.degrees(2.0 * math.acos(d))


def theta_deg_from_u_mm(u_mm):
    """u(전개 거리, mm) -> theta(도). theta = u 원점 각도 + u / radius. (이음매와 무관)"""
    return U_ORIGIN_ANGLE_DEG + math.degrees((u_mm / 1000.0) / RADIUS_M)


def u_mm_from_theta_deg(theta_deg):
    return math.radians(theta_deg - U_ORIGIN_ANGLE_DEG) * RADIUS_M * 1000.0


def seam_index(theta_deg):
    """θ 가 몇 번째 이음매 구간에 있는지. 구간 k = (seam + 360(k−1), seam + 360k]."""
    return math.ceil((theta_deg - SEAM_ANGLE_DEG) / 360.0)


def seams_strictly_between(theta_a, theta_b):
    """두 각도 사이(끝점 제외)에 있는 이음매 각도 목록 (seam + 360k 전부)."""
    lo, hi = min(theta_a, theta_b), max(theta_a, theta_b)
    k0 = math.floor((lo - SEAM_ANGLE_DEG) / 360.0) + 1
    out = []
    k = k0
    while SEAM_ANGLE_DEG + 360.0 * k < hi:
        t = SEAM_ANGLE_DEG + 360.0 * k
        if t > lo:
            out.append(t)
        k += 1
    return out


def arc_length_m(theta_a_deg, theta_b_deg, radius_m):
    """오프셋 원통 위 호 길이 (직선 현이 아니라)."""
    d = abs(theta_b_deg - theta_a_deg)
    return math.radians(d) * radius_m
