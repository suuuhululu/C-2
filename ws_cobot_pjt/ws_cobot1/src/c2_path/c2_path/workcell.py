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
    그 사이는 미실측. 우선 허용 범위를 |θ|≤135° (즉 금지는 135°<|θ|≤180°)로 반영(잠정치) —
    5° 간격 정밀 실측(하트 높이 대역 20~65mm) 후 갱신 예정 (시율님 9/20 2차 회신에서 이 로직 확인).
  - 세은님 2026-09-19 확정: tool_id = engraving_drill
  - 팀장님 확정: frame_id = c2_base
  - 시율님 2026-09-21: 작업 가능 높이를 "윗면 아래 20~65mm"(폭 45mm)에서 "윗면 10mm·바닥 10mm 제외,
    나머지 전부"(윗면 아래 10~140mm, 폭 130mm)로 대체. 상하 10mm는 조각 금지 구간이고, 그 사이 130mm는
    전부 CUT 허용 범위다. 이 범위 전체가 실기로 도달 가능하다고 확인된 것은 아니며(관절 검사 별도 필요),
    윗면 Z(`TOP_Z_BASE_M`)가 확정 전이라 상대 높이·SIM 입력 기준으로만 반영한다.
    (c2_path 에서는 이 범위가 경로 생성 조건이 아니라 실행 사전 점검 기준이다 — 아래 WORKABLE_HEIGHT_RANGE_M 주석.)
"""
import contextlib
import contextvars
import math
from dataclasses import dataclass

# --- 원기둥(양초) ----------------------------------------------------------
RADIUS_M = 0.03425                    # 9/20 캘리퍼스 실측 지름 68.5mm(±0.3)의 절반 — 자로 잰 34mm 대체
HEIGHT_TOTAL_M = 0.150                # 시율님 확정
AXIS_ORIGIN_XY_M = (0.4218, 0.0001)   # 0919 실측 (+Y·−Y 면 3점 두 벌 평균). 0918 값 (0.4224, −0.0026) 대체
TOP_Z_BASE_M = 0.2334                 # 0919 손끝 수직 터치 실측 (추정 0.2344 보다 −1.0mm)
AXIS_ORIGIN_Z_M = TOP_Z_BASE_M - HEIGHT_TOTAL_M   # 0.0834 = 양초 바닥 (yaml bottom_z_base_m 과 동일 계산)
AXIS_DIRECTION = (0.0, 0.0, 1.0)

# 도안을 놓을 수 있는 옆면 높이 구간 = 원기둥 옆면 전체(바닥 0 ~ 총 높이). 이음매 각도로 둘레 360° 전체를 쓴다.
# 경로 생성·3D 매핑·미리보기는 이 구간만 확인한다 (옆면 밖으로 나가면 표면이 없으므로 생성할 수 없다).
SURFACE_HEIGHT_RANGE_M = (0.0, HEIGHT_TOTAL_M)

# 높이의 기준은 하나다: **바닥(양초 밑면, 축 원점 z = AXIS_ORIGIN_Z_M) = 0, 위로 갈수록 커진다.** 경로 생성·매핑·검증·
# 사전 점검·스냅샷 `surface.valid_v_range_mm`·`offset_v_mm` 모두 이 기준이다. 윗면 기준(윗면에서 아래로 잰 깊이)은
# 쓰지 않는다 — 아래 여백도 윗면 아래 깊이가 아니라 바닥·윗면 각각에서 잰 여백으로 적는다.
#
# 로봇 작업 가능 높이 구간(실행 사전 점검용): 시율님 9/21 지시(잠정) "윗면 10mm·바닥 10mm 제외, 나머지 전부".
# 양초 높이 150mm 에서 바닥 쪽 여백 10mm, 윗면 쪽 여백 10mm 를 뺀 바닥 기준 10~140mm 다. 이전 값은 "윗면 아래
# 20~65mm"(바닥 기준 85~130mm)였다. 여백으로 적은 것은 시율님 표현("상하 10mm 제외") 그대로이고, 팀장님도 높이와
# 관계없이 `[10, H−10]`(상하 각 10mm 제외)으로 확인했다(9/21 회신). 그래서 양초 높이 H 가 150mm 가 아니어도 같은 규칙이다.
# 스냅샷 contract `/1` 은 `surface.valid_v_range_mm` 이 이 값과 정확히 같아야 한다(`validate_profile`).
# `/2` 는 요청별 값을 스냅샷에서 받는다(이 상수는 /1 기준값이자 기본값).
WORKABLE_MARGIN_BOTTOM_M = 0.010
WORKABLE_MARGIN_TOP_M = 0.010
# 주의(9/21): 이 값은 경로를 만들 수 있는지의 조건이 아니다. 만들어진 경로가 이 구간을 벗어나면 생성은 성공하고
# 실행 사전 점검(execution_readiness)이 OUT_OF_LIMITS 로 표시한다. 실행 가능 판정은 실행 전 검사가 한다.
WORKABLE_HEIGHT_RANGE_M = (round(WORKABLE_MARGIN_BOTTOM_M, 9), round(HEIGHT_TOTAL_M - WORKABLE_MARGIN_TOP_M, 9))  # (0.010, 0.140), 바닥 기준

# --- 각도/이음매 -----------------------------------------------------------
# 각도 θ: 0° = base +X(로봇 반대편), 축 +Z 기준 반시계 양수 (시율님 9/20).
# 도안 배치 원점(u=0)과 이음매는 서로 다른 개념이라 상수를 나눈다.
#   - U_ORIGIN_ANGLE_DEG: offset_u=0 인 도안 중심이 놓이는 각도 (권장안 69줄: u 원점은 표면 설정에 정의)
#   - SEAM_ANGLE_DEG   : 획이 넘으면 안 되는 선. 전개면 u = −πR ~ +πR 의 양 끝이 이음매가 된다.
U_ORIGIN_ANGLE_DEG = 0.0              # u=0 = +X 면 (로봇 반대편)
SEAM_ANGLE_DEG = 180.0                # 이음매 = ±180° = −X 면 (로봇 쪽, J5 위험 구역) — 시율님 9/20
# 로봇이 CUT 할 수 있는 θ 범위(실행 사전 점검용). 시율님 9/20 J5 실측(θ=180°에서 J5=175°, ±135° 초과) 기준 잠정치.
# 오늘 5° 간격 실측으로 정확한 한계각이 나오면 갱신한다.
# 주의(9/21): 경로 생성·미리보기의 실패 조건이 아니다. 범위 밖 구간은 execution_readiness 가 표시한다.
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


# --- 요청별 원통 형상 --------------------------------------------------------
# 위 상수는 `/1` 스냅샷의 기준값이자 기본 형상이다. `/2` 스냅샷은 실측한 반지름·높이·축 원점을 요청마다 준다(9/21 팀장님).
# 그래서 기하 계산은 상수를 직접 읽지 않고 "지금 쓰는 형상"(current_surface)을 읽는다. 파이프라인이 요청을 시작할 때
# 스냅샷에서 만든 형상을 정하고(set_active_surface), 요청이 끝나면 되돌린다. ContextVar 라서 스레드·요청끼리 섞이지 않는다.
# 기본값(DEFAULT_SURFACE)은 위 상수와 같은 값이라 `/1`·기존 호출 코드의 결과는 바뀌지 않는다.
@dataclass(frozen=True)
class Surface:
    radius_m: float
    height_m: float                      # 총 높이(바닥 0 ~ 윗면). 옆면이 있는 구간이다.
    axis_origin_m: tuple                 # (x, y, 바닥 z)
    axis_direction: tuple = AXIS_DIRECTION
    u_origin_angle_deg: float = U_ORIGIN_ANGLE_DEG
    seam_angle_deg: float = SEAM_ANGLE_DEG

    @property
    def axis_origin_xy_m(self):
        return (self.axis_origin_m[0], self.axis_origin_m[1])

    @property
    def axis_origin_z_m(self):
        return self.axis_origin_m[2]

    @property
    def height_range_m(self):
        """도안을 놓을 수 있는 옆면 높이 구간(바닥 기준). 로봇 작업 범위와 다르다."""
        return (0.0, self.height_m)


DEFAULT_SURFACE = Surface(radius_m=RADIUS_M, height_m=HEIGHT_TOTAL_M,
                          axis_origin_m=(AXIS_ORIGIN_XY_M[0], AXIS_ORIGIN_XY_M[1], AXIS_ORIGIN_Z_M))
_ACTIVE_SURFACE = contextvars.ContextVar("c2_path_active_surface", default=DEFAULT_SURFACE)


def current_surface() -> Surface:
    """지금 요청이 쓰는 원통 형상. 정한 것이 없으면 DEFAULT_SURFACE(위 상수)."""
    return _ACTIVE_SURFACE.get()


def set_active_surface(surface: Surface):
    """현재 요청의 원통 형상을 정한다. 반환된 토큰으로 reset_active_surface 를 불러 되돌린다."""
    return _ACTIVE_SURFACE.set(surface)


def reset_active_surface(token) -> None:
    _ACTIVE_SURFACE.reset(token)


@contextlib.contextmanager
def using_surface(surface: Surface):
    """with 블록 안에서만 surface 를 쓴다 (시험·오프라인 도구용)."""
    token = _ACTIVE_SURFACE.set(surface)
    try:
        yield surface
    finally:
        _ACTIVE_SURFACE.reset(token)


def surface_from_snapshot(surface) -> Surface:
    """`/2` 스냅샷의 `surface`(mm 단위 반지름·높이, m 단위 축 원점) -> Surface(m 단위).

    구조·값의 타당성은 snapshot.surface_geometry_errors 가 먼저 검사한다. 축 방향·u 원점·이음매는 아직 상수와
    같은 값만 받는다(pipeline 이 검사) — 이 함수는 스냅샷 값을 그대로 옮긴다."""
    x, y, z = surface["axis_origin_m"]
    return Surface(
        radius_m=float(surface["radius_mm"]) / 1000.0,
        height_m=float(surface["height_mm"]) / 1000.0,
        axis_origin_m=(float(x), float(y), float(z)),
        axis_direction=tuple(float(c) for c in surface["axis_direction"]),
        u_origin_angle_deg=float(surface["u_origin_angle_deg"]),
        seam_angle_deg=float(surface["seam_angle_deg"]),
    )


# --- 기하 ------------------------------------------------------------------
def radial_direction(theta_deg):
    """theta=0 이 base +X 인 바깥쪽 반경 단위벡터 (축 +Z 기준 반시계가 양)."""
    t = math.radians(theta_deg)
    return (math.cos(t), math.sin(t), 0.0)


def surface_point(theta_deg, height_m):
    r = radial_direction(theta_deg)
    cs = current_surface()
    return (cs.axis_origin_m[0] + cs.radius_m * r[0],
            cs.axis_origin_m[1] + cs.radius_m * r[1],
            cs.axis_origin_m[2] + height_m)


def offset_point(theta_deg, height_m, clearance_m):
    """표면에서 바깥쪽 법선으로 clearance 만큼 떨어진 점 (반지름 R+clearance 원통 위)."""
    r = radial_direction(theta_deg)
    cs = current_surface()
    return (cs.axis_origin_m[0] + (cs.radius_m + clearance_m) * r[0],
            cs.axis_origin_m[1] + (cs.radius_m + clearance_m) * r[1],
            cs.axis_origin_m[2] + height_m)


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
    cs = current_surface()
    return cs.u_origin_angle_deg + math.degrees((u_mm / 1000.0) / cs.radius_m)


def u_mm_from_theta_deg(theta_deg):
    cs = current_surface()
    return math.radians(theta_deg - cs.u_origin_angle_deg) * cs.radius_m * 1000.0


def seam_index(theta_deg):
    """θ 가 몇 번째 이음매 구간에 있는지. 구간 k = (seam + 360(k−1), seam + 360k]."""
    return math.ceil((theta_deg - current_surface().seam_angle_deg) / 360.0)


def seams_strictly_between(theta_a, theta_b):
    """두 각도 사이(끝점 제외)에 있는 이음매 각도 목록 (seam + 360k 전부)."""
    seam = current_surface().seam_angle_deg
    lo, hi = min(theta_a, theta_b), max(theta_a, theta_b)
    k0 = math.floor((lo - seam) / 360.0) + 1
    out = []
    k = k0
    while seam + 360.0 * k < hi:
        t = seam + 360.0 * k
        if t > lo:
            out.append(t)
        k += 1
    return out


def arc_length_m(theta_a_deg, theta_b_deg, radius_m):
    """오프셋 원통 위 호 길이 (직선 현이 아니라)."""
    d = abs(theta_b_deg - theta_a_deg)
    return math.radians(d) * radius_m
