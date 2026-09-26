# robot_adapter.py — 두산 드라이버(ws_dsr 브링업) 호출·결과 확인·단위 변환. 공정 제어의 로봇 연결 모듈.
# 집기·반납(tool_sequence)·조각(engraving)·청소(cleaning)가 함께 부른다. 별도 ROS Topic/Service 를 만들지 않는다.
# 담당: 이시율 (초안 2026-09-18, 로컬). 실기 검증본 clay_carving/clay_common.py 의 Robot 클래스를 새 계약에 맞춰 옮겼다.
# PR #73 후보: 법선 힘 유지(hold_normal_force_begin/end)·이동 중 힘 감시·서비스 클라이언트 재사용·이동 시작 재판정(_verify_start).
#
# 계약(INTERFACE_RECOMMENDATION v1 §2·§9):
#   - 입력 자세는 m + quaternion(x,y,z,w) + frame_id. 두산 API 의 mm·ZYZ(A,B,C deg) 변환은 이 파일에서만 한다.
#   - 함수는 부르면 완료·실패·정지 중 하나로 돌아온다(호출자 입장 동기). 안에서는 비동기 이동 서비스를 보내고
#     완료를 감시하므로, 이동 대기 중에도 cancel 이벤트를 보면 QSTOP 을 보내고 실제 정지 확인 후 STOPPED 로 돌아온다 (미확인 시 UNKNOWN).
#   - deadline_s 초과·취소·오류를 상위로 전달하고, 정지 접수와 실제 정지 확인을 구분한다.
#   - 실기(REAL) 값(속도·힘·TCP)은 프로파일(tools.yaml 스냅샷)에서만 온다. 여기에 현장 수치를 넣지 않는다.
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------- 공통 결과 형식 ----
OUTCOMES = ("SUCCEEDED", "FAILED", "STOPPED", "UNKNOWN")


@dataclass
class RobotState:
    """observe() 결과. 측정 시각은 monotonic 초. quality: VALID / STALE / UNKNOWN / UNSUPPORTED."""
    joints_rad: Optional[List[float]] = None
    tcp_pose: Optional[List[float]] = None           # [x, y, z (m), qx, qy, qz, qw]
    frame_id: str = ""
    robot_state: Optional[int] = None                 # 두산 robot_state 코드 (1 = STANDBY, 2 = MOVING, 3 = SAFE_OFF ...)
    force_n: Optional[List[float]] = None             # base 기준 툴 힘 [Fx, Fy, Fz] N
    measured_at: float = 0.0
    quality: str = "UNKNOWN"


@dataclass
class StepResult:
    outcome: str                                      # OUTCOMES 중 하나
    error_code: str = "NONE"
    message: str = ""
    completed_step: str = ""
    observed_state: Dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome == "SUCCEEDED"


class CancelledError(Exception):
    pass


# ---------------------------------------------------------------- 단위·회전 변환 ----
def quat_to_matrix(q):
    """quaternion (x,y,z,w) → 3x3 회전행렬 (열 = 도구 x, y, z 축을 base 로 표현)."""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0:
        raise ValueError("zero quaternion")
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def matrix_to_zyz_deg(M):
    """3x3 회전행렬 → 두산 posx 의 (A, B, C) ZYZ 오일러 [deg]. (clay_common.matrix_to_zyz 와 동일)"""
    B = math.degrees(math.acos(max(-1.0, min(1.0, M[2][2]))))
    if abs(M[2][2]) < 1.0 - 1e-9:
        A = math.degrees(math.atan2(M[1][2], M[0][2]))
        C = math.degrees(math.atan2(M[2][1], -M[2][0]))
    elif M[2][2] > 0:                                  # B ≈ 0: R = Rz(A+C) → A = 0, C = A+C
        A = 0.0
        C = math.degrees(math.atan2(M[1][0], M[0][0]))
    else:                                              # B ≈ 180: R = Ry(180)·Rz(C−A) = [[-cos, sin, 0],[sin, cos, 0],[0,0,-1]] → A = 0, C = C−A
        # 9/19 실기 버그: 여기서 A = atan2(M10, M00), C = 0 을 쓰면 툴 Y 가 180° 뒤집힌 자세가 나온다 (그리퍼 수직일 때 드릴이 반대로 향함)
        A = 0.0
        C = math.degrees(math.atan2(M[1][0], M[1][1]))
    return A, B, C


def zyz_deg_to_matrix(A, B, C):
    a, b, c = (math.radians(v) for v in (A, B, C))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [
        [ca * cb * cc - sa * sc, -ca * cb * sc - sa * cc, ca * sb],
        [sa * cb * cc + ca * sc, -sa * cb * sc + ca * cc, sa * sb],
        [-sb * cc, sb * sc, cb],
    ]


def matrix_to_quat(M):
    """3x3 회전행렬 → quaternion (x,y,z,w), 정규화."""
    t = M[0][0] + M[1][1] + M[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w, x, y, z = 0.25 * s, (M[2][1] - M[1][2]) / s, (M[0][2] - M[2][0]) / s, (M[1][0] - M[0][1]) / s
    elif M[0][0] > M[1][1] and M[0][0] > M[2][2]:
        s = math.sqrt(1.0 + M[0][0] - M[1][1] - M[2][2]) * 2
        w, x, y, z = (M[2][1] - M[1][2]) / s, 0.25 * s, (M[0][1] + M[1][0]) / s, (M[0][2] + M[2][0]) / s
    elif M[1][1] > M[2][2]:
        s = math.sqrt(1.0 + M[1][1] - M[0][0] - M[2][2]) * 2
        w, x, y, z = (M[0][2] - M[2][0]) / s, (M[0][1] + M[1][0]) / s, 0.25 * s, (M[1][2] + M[2][1]) / s
    else:
        s = math.sqrt(1.0 + M[2][2] - M[0][0] - M[1][1]) * 2
        w, x, y, z = (M[1][0] - M[0][1]) / s, (M[0][2] + M[2][0]) / s, (M[1][2] + M[2][1]) / s, 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w)
    return [x / n, y / n, z / n, w / n]


def apply_tool_offset(pose, offset_tool_m, sign=+1):
    """도구 좌표계 오프셋(m, [ox,oy,oz])을 자세에 더한다(sign=+1) / 뺀다(sign=-1). 회전은 그대로.
    경로는 '송곳 끝' 위치를 주고, 제어기 TCP 는 패드 기본값(GripperDA_v1)이므로, 송곳 끝 목표 → 패드 TCP 목표는
    끝 위치에서 오프셋을 뺀 자리다: 패드 = 끝 − R·offset."""
    if not offset_tool_m or not any(offset_tool_m):
        return list(pose)
    M = quat_to_matrix(pose[3:7])
    p = list(pose)
    for i in range(3):
        p[i] += sign * sum(M[i][k] * offset_tool_m[k] for k in range(3))
    return p


def pose_to_posx(pose, tool_offset_m=None):
    """[x,y,z (m), qx,qy,qz,qw] (송곳 끝 목표) → 두산 posx [X,Y,Z (mm), A,B,C (deg)] (제어기 TCP 목표).
    tool_offset_m 이 있으면 끝 → 패드 TCP 로 환산한다."""
    p = apply_tool_offset(pose, tool_offset_m, -1) if tool_offset_m else pose
    A, B, C = matrix_to_zyz_deg(quat_to_matrix(p[3:7]))
    return [p[0] * 1000.0, p[1] * 1000.0, p[2] * 1000.0, A, B, C]


def posx_to_pose(px, tool_offset_m=None):
    """두산 posx [X,Y,Z (mm), A,B,C (deg)] (제어기 TCP) → [x,y,z (m), qx,qy,qz,qw] (송곳 끝, 오프셋 있으면 환산)"""
    pose = [px[0] / 1000.0, px[1] / 1000.0, px[2] / 1000.0] + matrix_to_quat(zyz_deg_to_matrix(px[3], px[4], px[5]))
    return apply_tool_offset(pose, tool_offset_m, +1) if tool_offset_m else pose


def tool_axis_in_base(pose, axis="+z"):
    """자세의 도구 축(+x/-x/+y/-y/+z/-z)을 base 단위벡터로. engraving 이 '송곳 방향' 을 얻을 때 쓴다."""
    M = quat_to_matrix(pose[3:7])
    idx = {"x": 0, "y": 1, "z": 2}[axis[-1]]
    sgn = -1.0 if axis.startswith("-") else 1.0
    return [sgn * M[0][idx], sgn * M[1][idx], sgn * M[2][idx]]


# ---------------------------------------------------------------- 어댑터 인터페이스 ----
class RobotAdapter:
    """공정 모듈이 부르는 함수 집합. 실기 구현은 DoosanRobotAdapter, 모의는 MockRobotAdapter."""

    def move(self, pose, frame_id, profile, deadline_s, cancel) -> StepResult:
        raise NotImplementedError

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel) -> StepResult:
        raise NotImplementedError

    def probe_touch(self, direction, max_m, profile, deadline_s, cancel) -> StepResult:
        raise NotImplementedError

    def stop(self, stop_profile, deadline_s) -> StepResult:
        raise NotImplementedError

    def select_tool_profile(self, tcp_id, load_id, profile_version=None, deadline_s=10.0) -> StepResult:
        """도구 장착 뒤 TCP·하중 프로파일 선택. 실제 선택 결과를 제어기에서 다시 읽어 대조하고 observed_state 에
        {tcp, tool, profile_version, applied(bool)} 을 넣는다. deadline_s 초과면 TIMEOUT."""
        raise NotImplementedError

    def observe(self) -> RobotState:
        raise NotImplementedError

    def inverse_kinematics(self, pose, tool_offset_m, ref_joints_deg):
        """도구 끝 pose(m·quat) → 관절 [deg] 6개. 해가 없으면 None. ref_joints_deg 로 해 공간을 고른다 (연속성). 로봇을 움직이지 않는다."""
        raise NotImplementedError

    def reset_ik_metrics(self):
        """선택 계측 API. 구현하지 않는 어댑터는 고수준 검사 계측만 사용한다."""

    def ik_metrics_snapshot(self):
        return None

    def set_tool_offset(self, offset_tool_m):
        """제어기 TCP(패드 기본값) 에서 송곳 끝까지의 도구 좌표계 오프셋 [ox,oy,oz] (m). 집기 뒤 측정한 송곳 길이로
        tool_sequence/상태 기계가 설정한다. 이후 move/move_spline/observe 는 모두 '송곳 끝' 기준으로 동작한다."""
        raise NotImplementedError

    def read_force_bias(self, samples=8):
        """정지·무접촉 상태의 힘 [Fx,Fy,Fz] (base, N) 평균. CUT 감시의 편향 제거용. 로봇을 움직이지 않는다."""
        raise NotImplementedError

    def hold_normal_force_begin(self, tool_axis, profile, deadline_s, cancel) -> StepResult:
        """9/22: 획 CUT 동안 도구 축(tool_axis, 예 '-y' = 표면 안쪽) 방향만 힘 제어, 나머지 축은 순응(강성)으로 두는
        제어기 모드를 켠다. 경로 진행(MoveSX)은 그대로 위치 명령이고, 법선 방향 위치는 제어기가 목표 힘에 맞춰 덮어쓴다.
        profile: cut_force_n(목표 접촉력), cut_stiffness(6개 강성), ramp_s(전환 시간). 값이 없으면 켜지 않고 실패."""
        raise NotImplementedError

    def hold_normal_force_end(self, deadline_s) -> StepResult:
        """힘 제어·순응 해제. observed_state.force_released 가 True 일 때만 다음 공중 이동을 허용한다."""
        raise NotImplementedError


def _cancelled(cancel) -> bool:
    return cancel is not None and cancel.is_set()


def _axis_index(tool_axis):
    """'-y' → (1, -1.0). 도구 축 문자열을 두산 fd/dir 배열 인덱스와 부호로."""
    idx = {"x": 0, "y": 1, "z": 2}[tool_axis[-1]]
    return idx, (-1.0 if tool_axis.startswith("-") else 1.0)


def evaluate_contact_sample(monitor, tip_pose, force_vec):
    """이동 중 힘·위치 샘플 하나를 감시 기준에 대조한다 (실기 _wait_motion 과 모의 어댑터가 같이 쓴다).
    monitor: kind ("CUT" | "AIR"), bias [Fx,Fy,Fz], force_limit_n(절대 상한),
             CUT 추가: surface(원본 표면 waypoint 목록), normals(각 점의 안쪽 법선), offset_range [lo, hi] (m, + 안쪽).
    반환 dict(force_n=편향 제거 후 크기, normal_force_n=법선 접촉력(안쪽으로 누르는 힘 +), normal_dev_m=표면 대비 법선 이탈,
             nearest=가장 가까운 표면점 index, fail=(code, message) | None)."""
    bias = monitor.get("bias") or [0.0, 0.0, 0.0]
    f = [force_vec[k] - bias[k] for k in range(3)]
    mag = math.sqrt(sum(v * v for v in f))
    out = dict(force_n=mag, normal_force_n=None, normal_dev_m=None, nearest=None, fail=None)
    limit = monitor.get("force_limit_n")
    if limit is not None and mag > float(limit):
        out["fail"] = ("FORCE_LIMIT", f"{monitor.get('kind', '?')} 중 힘 {mag:.1f} N > 상한 {float(limit):.1f} N")
        return out
    if monitor.get("kind") == "CUT" and monitor.get("surface"):
        surface, normals = monitor["surface"], monitor["normals"]
        i = min(range(len(surface)), key=lambda k: math.dist(tip_pose[:3], surface[k][:3]))
        n = normals[i]
        out["nearest"] = i
        out["normal_force_n"] = -sum(f[k] * n[k] for k in range(3))        # 표면이 도구를 바깥으로 미는 반력 → 안쪽 누름 +
        out["normal_dev_m"] = sum((tip_pose[k] - surface[i][k]) * n[k] for k in range(3))
        rng = monitor.get("offset_range")
        if rng is not None and not (float(rng[0]) <= out["normal_dev_m"] <= float(rng[1])):
            out["fail"] = ("VALIDATION_FAILED",
                           f"CUT 중 법선 이탈 {out['normal_dev_m'] * 1000:+.2f} mm 가 허용 범위 [{rng[0] * 1000:+.1f}, {rng[1] * 1000:+.1f}] mm 밖 → 재검사 필요")
    return out


# ---------------------------------------------------------------- 실기: 두산 드라이버 ----
class DoosanRobotAdapter(RobotAdapter):
    """ws_dsr 브링업의 명시적인 dsr_controller2 절대 prefix로 ROS 서비스를 호출한다.
    공정 노드 namespace에 의존하지 않으며 executor 안에서 중첩 spin을 하지 않는다.
    실행 중에는 별도 작업 스레드에서 호출한다.
    툴/TCP 선택·상태 검사는 상태 기계의 preconditions 와 select_tool_profile() 이 담당."""

    ROBOT_ID, ROBOT_MODEL = "dsr01", "m0609"
    STATE_STANDBY, STATE_MOVING = 1, 2

    def __init__(self, node, frame_id="c2_base", logger=None, *,
                 controller_prefix="/dsr01/dsr_controller2",
                 initialization_timeout_s=5.0):
        from dsr_msgs2.srv import (MoveStop, GetCurrentTcp, GetCurrentTool, SetCurrentTcp, SetCurrentTool, SetRobotMode,
                                   GetRobotState, GetCurrentPosj, GetCurrentPosx, GetToolForce,
                                   MoveLine, MoveSplineTask, CheckMotion, Ikin, GetSolutionSpace,
                                   SetSingularityHandling,
                                   TaskComplianceCtrl, SetDesiredForce, ReleaseForce, ReleaseComplianceCtrl)
        if (not isinstance(controller_prefix, str)
                or not controller_prefix.startswith("/")
                or controller_prefix.rstrip("/") == ""):
            raise ValueError("controller_prefix must be an absolute ROS prefix")
        self.node, self.frame_id = node, frame_id
        self.controller_prefix = controller_prefix.rstrip("/")
        self.tool_offset_m = None
        self.log = logger or node.get_logger()
        self._srv = dict(MoveStop=MoveStop, GetCurrentTcp=GetCurrentTcp, GetCurrentTool=GetCurrentTool,
                         SetCurrentTcp=SetCurrentTcp, SetCurrentTool=SetCurrentTool, SetRobotMode=SetRobotMode,
                         GetRobotState=GetRobotState, GetCurrentPosj=GetCurrentPosj,
                         GetCurrentPosx=GetCurrentPosx, GetToolForce=GetToolForce,
                         MoveLine=MoveLine, MoveSplineTask=MoveSplineTask, CheckMotion=CheckMotion,
                         Ikin=Ikin, GetSolutionSpace=GetSolutionSpace,
                         SetSingularityHandling=SetSingularityHandling,
                         TaskComplianceCtrl=TaskComplianceCtrl, SetDesiredForce=SetDesiredForce,
                         ReleaseForce=ReleaseForce, ReleaseComplianceCtrl=ReleaseComplianceCtrl)
        self._hold_active = False                  # 법선 힘 유지(순응+힘 제어) 켜짐 여부. 켜진 채 공중 이동 금지
        self._ik_metrics_lock = threading.Lock()
        self.reset_ik_metrics()
        if (isinstance(initialization_timeout_s, bool)
                or not isinstance(initialization_timeout_s, (int, float))
                or not math.isfinite(initialization_timeout_s)
                or initialization_timeout_s <= 0):
            raise ValueError("initialization_timeout_s must be positive")
        self._initialization_timeout_s = float(initialization_timeout_s)
        self._controller_initialized = False

    def initialize_controller(self) -> StepResult:
        """제어권·정지·TCP/load 확인 후에만 DR_AVOID(0)을 설정한다.

        adapter 생성은 읽기/클라이언트 구성만 하며, 이 메서드 전에는
        제어기 설정을 변경하지 않는다.
        """
        if self._controller_initialized:
            return StepResult("SUCCEEDED", "NONE", "제어기 초기화 유지", "controller_initialization",
                              {"singularity_mode": 0, "already_initialized": True})
        try:
            self._read("motion/set_singularity_handling", "SetSingularityHandling",
                       timeout=self._initialization_timeout_s, mode=0)
        except Exception as exc:
            return StepResult("UNKNOWN", "COMMUNICATION_LOST", f"제어기 초기화 실패: {exc}",
                              "controller_initialization")
        self._controller_initialized = True
        return StepResult("SUCCEEDED", "NONE", "DR_AVOID 초기화 확인", "controller_initialization",
                          {"singularity_mode": 0, "already_initialized": False})

    # ---- 서비스 도우미 ----
    def _call(self, name, srv, req, timeout=5.0):
        """공정 작업 스레드에서 조회한다. 실행 중인 노드를 다른 executor로 옮기지 않는다."""
        import rclpy
        from rclpy.callback_groups import ReentrantCallbackGroup

        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("service timeout must be positive")
        executor = self.node.executor
        if executor is not None and not executor.is_spinning:
            raise RuntimeError("attached executor is not spinning")
        started = time.monotonic()
        clients = self.__dict__.setdefault("_clients", {})
        cli = clients.get(name)
        if cli is None:
            cli = clients[name] = self.node.create_client(
                srv, self.controller_prefix + "/" + name,
                callback_group=ReentrantCallbackGroup())
        fut = None
        try:
            if not cli.wait_for_service(timeout_sec=timeout):
                raise RuntimeError(f"service {name} not available")
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError(f"service {name} timed out")
            fut = cli.call_async(req)
            if executor is None:
                # 노드가 executor에 아직 등록되지 않은 단독 호출만 임시 spin 허용.
                rclpy.spin_until_future_complete(self.node, fut, timeout_sec=remaining)
            else:
                # 응답 처리는 기존 executor의 다른 worker가 담당한다.
                completed = threading.Event()
                fut.add_done_callback(lambda _future: completed.set())
                completed.wait(remaining)
            if (not fut.done() or fut.cancelled()
                    or time.monotonic() - started > timeout):
                raise TimeoutError(f"service {name} timed out")
            result = fut.result()
            if result is None:
                raise RuntimeError(f"service {name} returned no response")
            return result
        finally:
            if fut is not None and not fut.done():
                fut.cancel()

    def _read(self, endpoint, typename, *, timeout=5.0, **fields):
        kind = self._srv[typename]
        result = self._call(endpoint, kind, kind.Request(**fields), timeout=timeout)
        if result.success is not True:
            raise RuntimeError(f"service {endpoint} rejected")
        return result

    def _frame_ok(self, frame_id):
        return frame_id == self.frame_id

    def inverse_kinematics(self, pose, tool_offset_m, ref_joints_deg):
        """제어기 ikin(posx, sol_space) 로 관절해 [deg]. sol_space 는 처음 8개 중 ref 에 가장 가까운 것을 고르고 이후 유지한다."""
        if not hasattr(self, "_ik_metrics_lock"):
            self.reset_ik_metrics()
        with self._ik_metrics_lock:
            self._ik_inverse_calls += 1
        px = pose_to_posx(pose, tool_offset_m)
        best = None
        if getattr(self, "_ik_space", None) is None:
            try:                                                                # 현재(기준) 관절의 해 공간을 제어기에 물어 그것부터
                self._ik_space = int(self._read("aux_control/get_solution_space", "GetSolutionSpace",
                                                pos=[float(v) for v in ref_joints_deg]).sol_space)
            except Exception:
                self._ik_space = None
        spaces = ([self._ik_space] if self._ik_space is not None else []) + [k for k in range(8) if k != self._ik_space]
        for sp in spaces:
            service_started = time.monotonic()
            try:
                q = self._read("motion/ikin", "Ikin", pos=[float(v) for v in px], sol_space=sp, ref=0).conv_posj
            except Exception:
                q = None
            finally:
                elapsed = max(0.0, time.monotonic() - service_started)
                with self._ik_metrics_lock:
                    self._ik_service_calls += 1
                    self._ik_service_elapsed_s += elapsed
                    self._ik_service_max_s = max(self._ik_service_max_s, elapsed)
            if isinstance(q, tuple) and len(q) and hasattr(q[0], "__len__"):   # (posj, status) 형태 대비
                q = q[0]
            if q is None or len(q) < 6:                                          # numpy 배열이라 `not q` 는 쓰지 않는다 (9/19 실기)
                continue
            q = [float(v) for v in list(q)[:6]]
            d = max(abs(q[k] - ref_joints_deg[k]) for k in range(6))
            if best is None or d < best[0]:
                best = (d, sp, q)
            if d < 5.0:                                                         # 기준 관절과 사실상 같은 해 → 더 볼 필요 없음
                break
        if best is None:
            return None
        self._ik_space = best[1]
        return best[2]

    def reset_ik_metrics(self):
        if not hasattr(self, "_ik_metrics_lock"):
            self._ik_metrics_lock = threading.Lock()
        with self._ik_metrics_lock:
            self._ik_inverse_calls = 0
            self._ik_service_calls = 0
            self._ik_service_elapsed_s = 0.0
            self._ik_service_max_s = 0.0

    def ik_metrics_snapshot(self):
        if not hasattr(self, "_ik_metrics_lock"):
            self.reset_ik_metrics()
        with self._ik_metrics_lock:
            service_calls = self._ik_service_calls
            return {
                "inverse_kinematics_calls": self._ik_inverse_calls,
                "motion_ikin_calls": service_calls,
                "solution_space_queries_per_ik": (
                    service_calls / self._ik_inverse_calls
                    if self._ik_inverse_calls else 0.0),
                "motion_ikin_elapsed_s": self._ik_service_elapsed_s,
                "motion_ikin_mean_response_s": (
                    self._ik_service_elapsed_s / service_calls if service_calls else 0.0),
                "motion_ikin_max_response_s": self._ik_service_max_s,
            }

    def set_tool_offset(self, offset_tool_m):
        self._last_completed_target = None
        self.tool_offset_m = list(offset_tool_m) if offset_tool_m else None
        self.log.info(f"tool offset (tool frame, m) = {self.tool_offset_m}")

    def _posx_now(self, timeout=5.0):
        result = self._read("aux_control/get_current_posx", "GetCurrentPosx", timeout=timeout, ref=0)
        values = list(result.task_pos_info[0].data[:6])
        if len(values) != 6 or not all(math.isfinite(v) for v in values):
            raise ValueError("invalid TCP observation")
        return values

    def _tip_pose_now(self):
        return posx_to_pose(self._posx_now(), self.tool_offset_m)

    def _force_vec(self, timeout=5.0):
        values = list(self._read("aux_control/get_tool_force", "GetToolForce", timeout=timeout, ref=0).tool_force[:3])
        if len(values) != 3 or not all(math.isfinite(v) for v in values):
            raise ValueError("invalid force observation")
        return values

    def read_force_bias(self, samples=8):
        n = max(1, int(samples))
        acc = [0.0, 0.0, 0.0]
        for _ in range(n):
            f = self._force_vec()
            for k in range(3):
                acc[k] += f[k] / n
        return acc

    # ---- 법선 힘 유지 (9/22: CUT 중 연속 표면 추종) ----
    def hold_normal_force_begin(self, tool_axis, profile, deadline_s, cancel) -> StepResult:
        step = "hold_normal_force_begin"
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨 (힘 유지 시작 전)", step)
        try:
            idx, sgn = _axis_index(str(tool_axis))
            force = float(profile["cut_force_n"])
            stx = [float(v) for v in profile["cut_stiffness"]]
            ramp = float(profile["ramp_s"])
            if (not math.isfinite(force) or force <= 0 or len(stx) != 6
                    or any(not math.isfinite(v) or v < 0 for v in stx)
                    or not math.isfinite(ramp) or not 0.0 <= ramp <= 1.0
                    or not math.isfinite(deadline_s) or deadline_s <= 0):
                raise ValueError("cut_force_n(>0)·cut_stiffness(6개, ≥0)·ramp_s(0~1 s) 범위 오류")
        except (KeyError, ValueError, TypeError) as exc:
            return StepResult("FAILED", "NOT_READY", f"힘 유지 프로파일 없음/오류: {exc}", step)
        end = time.monotonic() + deadline_s
        try:
            _, state, motion = self._motion_sample(min(2.0, deadline_s))
            if state != self.STATE_STANDBY or motion != 0:
                return StepResult("FAILED", "NOT_READY", "힘 유지 시작 전 정지 상태 아님", step)
        except Exception as exc:
            return StepResult("UNKNOWN", "COMMUNICATION_LOST", str(exc), step)
        fd = [0.0] * 6; direction = [0] * 6
        fd[idx] = sgn * force                      # 툴 좌표계(ref=1): '-y' 면 fd[1] = −F → 표면 안쪽으로 F 만큼 누른다
        direction[idx] = 1                         # 이 축만 힘 제어, 나머지 축은 순응(강성)
        S = self._srv
        self._hold_active = True                   # 활성 응답이 유실돼도 해제 대상으로 본다
        try:
            r1 = self._call("force/task_compliance_ctrl", S["TaskComplianceCtrl"],
                            S["TaskComplianceCtrl"].Request(stx=stx, ref=1, time=ramp), timeout=min(2.0, max(0.1, end - time.monotonic())))
            if r1 is None or r1.success is not True:
                raise RuntimeError("task_compliance_ctrl 거부")
            r2 = self._call("force/set_desired_force", S["SetDesiredForce"],
                            S["SetDesiredForce"].Request(fd=fd, dir=direction, ref=1, time=ramp, mod=0),
                            timeout=min(2.0, max(0.1, end - time.monotonic())))
            if r2 is None or r2.success is not True:
                raise RuntimeError("set_desired_force 거부")
        except Exception as exc:
            released = self.hold_normal_force_end(min(2.0, deadline_s))
            return StepResult("FAILED", "NOT_READY", f"힘 유지 시작 실패: {exc}", step,
                              dict(force_released=released.observed_state.get("force_released") is True))
        self.log.info(f"법선 힘 유지 시작: 툴 {tool_axis} {force:.1f} N, 강성 {stx}, 전환 {ramp:.2f} s")
        return StepResult("SUCCEEDED", "NONE", "", step, dict(hold_active=True, fd=fd, stiffness=stx, ramp_s=ramp))

    def hold_normal_force_end(self, deadline_s) -> StepResult:
        step = "hold_normal_force_end"
        if not self._hold_active:
            return StepResult("SUCCEEDED", "NONE", "힘 유지 비활성", step, dict(force_released=True, was_active=False))
        S = self._srv
        failures = []
        end = time.monotonic() + max(0.2, float(deadline_s))
        for endpoint, name, req in (("force/release_force", "ReleaseForce", S["ReleaseForce"].Request(time=0.0)),
                                    ("force/release_compliance_ctrl", "ReleaseComplianceCtrl", S["ReleaseComplianceCtrl"].Request())):
            try:
                r = self._call(endpoint, S[name], req, timeout=min(2.0, max(0.1, end - time.monotonic())))
                if r is None or r.success is not True:
                    failures.append(endpoint + " 거부")
            except Exception as exc:
                failures.append(f"{endpoint}: {exc}")
        if failures:
            self.log.error(f"힘 유지 해제 실패: {failures} (다음 이동 금지)")
            return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "힘/순응 해제 미확인: " + "; ".join(failures), step,
                              dict(force_released=False, was_active=True, release_errors=failures))
        self._hold_active = False
        self.log.info("법선 힘 유지 해제")
        return StepResult("SUCCEEDED", "NONE", "", step, dict(force_released=True, was_active=True))

    # ---- 관측 ----
    def observe(self) -> RobotState:
        st = RobotState(measured_at=time.monotonic(), frame_id=self.frame_id)
        try:
            joints = list(self._read("aux_control/get_current_posj", "GetCurrentPosj").pos)
            if len(joints) != 6 or not all(math.isfinite(v) for v in joints):
                raise ValueError("invalid joint observation")
            st.joints_rad = [math.radians(v) for v in joints]
            st.tcp_pose = self._tip_pose_now()
            st.force_n = self._force_vec()
            st.robot_state = self._read("system/get_robot_state", "GetRobotState").robot_state
            st.quality = "VALID"
        except Exception as e:
            self.log.warn(f"observe: {e}")
            st.quality = "UNKNOWN"
        return st

    # ---- 툴·TCP ----
    def _read_tool_tcp(self):
        S = self._srv
        tcp = self._call("tcp/get_current_tcp", S["GetCurrentTcp"], S["GetCurrentTcp"].Request()).info
        tool = self._call("tool/get_current_tool", S["GetCurrentTool"], S["GetCurrentTool"].Request()).info
        return tcp, tool

    def select_tool_profile(self, tcp_id, load_id, profile_version=None, deadline_s=10.0) -> StepResult:
        S = self._srv
        t0 = time.monotonic()
        obs = dict(tcp=None, tool=None, profile_version=profile_version, applied=False)
        try:
            tcp, tool = self._read_tool_tcp()
            obs.update(tcp=tcp, tool=tool)
            if tcp != tcp_id or tool != load_id:
                # 자율 모드에선 선택이 거부되므로 수동 모드로 바꿔 선택 후 자율 모드로 복귀 (9/17 검증)
                ok = self._call("system/set_robot_mode", S["SetRobotMode"], S["SetRobotMode"].Request(robot_mode=0)).success
                ok &= self._call("tcp/set_current_tcp", S["SetCurrentTcp"], S["SetCurrentTcp"].Request(name=tcp_id)).success
                ok &= self._call("tool/set_current_tool", S["SetCurrentTool"], S["SetCurrentTool"].Request(name=load_id)).success
                ok &= self._call("system/set_robot_mode", S["SetRobotMode"], S["SetRobotMode"].Request(robot_mode=1)).success
                tcp, tool = self._read_tool_tcp()
                obs.update(tcp=tcp, tool=tool)
                if time.monotonic() - t0 > deadline_s:
                    return StepResult("UNKNOWN", "TIMEOUT", "툴/TCP 선택 응답이 제한 시간을 넘김", "select_tool_profile", obs)
                if not ok or tcp != tcp_id or tool != load_id:
                    return StepResult("FAILED", "PROFILE_MISMATCH",
                                      f"툴/TCP 선택 실패 (지금 {tool}/{tcp}, 기대 {load_id}/{tcp_id})", "select_tool_profile", obs)
            obs["applied"] = True
            return StepResult("SUCCEEDED", "NONE", f"툴/TCP {tool}/{tcp} 적용 확인", "select_tool_profile", obs)
        except Exception as e:
            code = "TIMEOUT" if "timed out" in str(e) else "COMMUNICATION_LOST"
            return StepResult("UNKNOWN" if code == "TIMEOUT" else "FAILED", code, str(e), "select_tool_profile", obs)

    # ---- 이동: 기존 executor가 응답을 처리하고 호출 스레드는 완료를 기다린다 ----
    @staticmethod
    def _angle_error(a, b):
        qa, qb = posx_to_pose(a)[3:], posx_to_pose(b)[3:]
        dot = min(1.0, abs(sum(x * y for x, y in zip(qa, qb))))
        return math.degrees(2 * math.acos(dot))

    def _motion_sample(self, timeout_s):
        end = time.monotonic() + timeout_s
        def read(endpoint, name, **fields):
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('모션 관측 제한 시간 초과')
            kind = self._srv[name]
            result = self._call(endpoint, kind, kind.Request(**fields), timeout=remaining)
            if result is None or result.success is not True:
                raise RuntimeError('모션 관측 실패: ' + endpoint)
            return result
        state = read('system/get_robot_state', 'GetRobotState').robot_state
        motion = read('motion/check_motion', 'CheckMotion').status
        px = list(read('aux_control/get_current_posx', 'GetCurrentPosx', ref=0).task_pos_info[0].data[:6])
        if len(px) != 6 or not all(math.isfinite(v) for v in px):
            raise ValueError('유효하지 않은 모션 TCP')
        if time.monotonic() > end:
            raise TimeoutError('모션 관측 제한 시간 초과')
        return px, state, motion

    def _send_line(self, target, vel, acc, timeout_s):
        kind = self._srv['MoveLine']
        return self._call('motion/move_line', kind, kind.Request(
            pos=[float(v) for v in target], vel=[vel, vel], acc=[acc, acc],
            time=0.0, radius=0.0, ref=0, mode=0, blend_type=0, sync_type=1), timeout=timeout_s)

    def _motion_failure(self, outcome, code, message, step):
        stopped = self.stop({'mode': 1}, 2.0)
        confirmed = stopped.ok and stopped.observed_state.get('stop_confirmed') is True
        return StepResult(outcome if confirmed else 'UNKNOWN', code, message, step,
                          dict(stop_confirmed=confirmed, stop_result=stopped.outcome,
                               stop_error_code=stopped.error_code))

    def _verify_start(self, start, target, tol_mm, angle_tol_deg, cancel, *, window_s=2.5, stable_s=2.0, allow_completed=True):
        """'이동 시작 미확인' 뒤 상태를 다시 읽어 구분한다. 관측 실패는 연속 3회까지 허용.
        반환 (verdict, last_posx): started(움직였거나 MOVING) / completed(목표에 정지) / not_accepted(stable_s 동안 시작 위치·STANDBY·motion 0) / unknown."""
        t0 = time.monotonic(); last = None; failures = 0; stable_since = None
        while time.monotonic() - t0 < window_s:
            if _cancelled(cancel):
                return 'unknown', last
            try:
                cur, state, motion = self._motion_sample(2.0)
                failures = 0
            except Exception:
                failures += 1
                if failures > 3:
                    return 'unknown', last
                time.sleep(0.1)
                continue
            last = cur
            if state == self.STATE_MOVING or motion != 0 or math.dist(cur[:3], start[:3]) > 0.03 or self._angle_error(cur, start) > 0.03:
                return 'started', cur
            if (allow_completed and state == self.STATE_STANDBY and motion == 0 and math.dist(cur[:3], target[:3]) <= tol_mm
                    and self._angle_error(cur, target) <= angle_tol_deg):
                return 'completed', cur                      # 폐곡선(시작 = 끝)에서는 쓰지 않는다: 목표에 있다는 것이 완료 근거가 아니다
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= stable_s:
                return 'not_accepted', cur
            time.sleep(0.1)
        return 'unknown', last

    def _wait_motion(self, target, deadline_s, cancel, step, tol_mm, *, start,
                     angle_tol_deg=0.15, closed_excursion_mm=0.0,
                     closed_excursion_deg=0.0, require_start=True, require_controller_start=False,
                     monitor=None):
        """접수만으로 완료하지 않는다. 시작 관측 → 목표 위치/자세 → 정착을 확인.

        폐곡선은 출발점에서 실제로 떨어진 관측까지 필요하다. 관측을 놓쳤으면
        성공을 추정하거나 명령을 재전송하지 않고 제한 시간 뒤 정지·UNKNOWN 반환.
        """
        t0 = time.monotonic()
        moved = not require_start
        controller_started = False
        excursion = angular_excursion = 0.0
        stable_since = None
        anchor = None
        while True:
            if _cancelled(cancel):
                return self._motion_failure('STOPPED', 'NONE', '이동 중 취소', step)
            remaining = deadline_s - (time.monotonic() - t0)
            if remaining <= 0:
                return self._motion_failure('UNKNOWN', 'TIMEOUT', '이동 완료 제한 시간 초과', step)
            try:
                cur, state, motion = self._motion_sample(min(remaining, 2.0))
            except Exception as exc:
                return self._motion_failure('UNKNOWN', 'COMMUNICATION_LOST', str(exc), step)
            now = time.monotonic()
            if _cancelled(cancel):
                return self._motion_failure('STOPPED', 'NONE', '이동 중 취소', step)
            if now - t0 >= deadline_s:
                return self._motion_failure('UNKNOWN', 'TIMEOUT', '이동 완료 제한 시간 초과', step)
            if state not in (self.STATE_STANDBY, self.STATE_MOVING) or motion not in (0, 1, 2):
                return self._motion_failure('FAILED', 'NOT_READY', '이동 중 비정상 로봇/모션 상태', step)
            if monitor is not None:
                # 9/22: 이동 중 힘 감시. CUT = 편향 제거 후 법선 접촉력·표면 대비 법선 이탈·절대 상한, AIR = 절대 상한만.
                # 힘 서비스가 이동 중 잠깐 응답을 못 하는 일이 있어(9/22 return_x: 2 s timeout) 연속 실패 허용 횟수까지는 계속 감시한다.
                try:
                    f = self._force_vec(timeout=min(remaining, 2.0))
                    monitor['read_failures'] = 0
                except Exception as exc:
                    monitor['read_failures'] = monitor.get('read_failures', 0) + 1
                    self.log.warn(f"{step} 힘 관측 실패 {monitor['read_failures']}회: {exc}")
                    if monitor['read_failures'] > int(monitor.get('max_read_failures', 2)):
                        return self._motion_failure('UNKNOWN', 'COMMUNICATION_LOST', f'힘 관측 연속 실패: {exc}', step)
                    f = None
                sample = evaluate_contact_sample(monitor, posx_to_pose(cur, self.tool_offset_m), f) if f is not None else None
                if sample is None:
                    time.sleep(0.05)
                    continue
                monitor.setdefault('samples', []).append(sample)
                if sample['fail']:
                    code, message = sample['fail']
                    return self._motion_failure('FAILED', code, message + ' → 정지', step)
            excursion = max(excursion, math.dist(cur[:3], start[:3]))
            angular_excursion = max(angular_excursion, self._angle_error(cur, start))
            controller_started |= state == self.STATE_MOVING or motion != 0
            moved |= (state == self.STATE_MOVING or motion != 0 or excursion > 0.03
                      or self._angle_error(cur, start) > 0.03)
            if not moved and now - t0 >= min(3.0, deadline_s):
                # 9/22: 바로 정지·UNKNOWN 으로 끝내지 않고, 통신 흔들림인지 실제 미수락인지 상태를 다시 읽어 구분한다 (재전송 없음).
                verdict, cur = self._verify_start(start, target, tol_mm, angle_tol_deg, cancel,
                                                  window_s=min(2.5, max(0.0, deadline_s - (time.monotonic() - t0))),
                                                  allow_completed=(closed_excursion_mm <= 0 and closed_excursion_deg <= 0
                                                                   and not require_controller_start))
                if verdict == 'started':
                    moved = True; controller_started = True
                    continue
                if verdict == 'completed':
                    return StepResult('SUCCEEDED', 'NONE', '이동 시작은 못 봤지만 목표에 정지 확인', step,
                                      dict(tcp_pose=posx_to_pose(cur, self.tool_offset_m), error_mm=math.dist(cur[:3], target[:3]),
                                           motion_started=None, motion_status=0, stop_confirmed=True))
                if verdict == 'not_accepted':
                    return StepResult('FAILED', 'NOT_ACCEPTED', '명령 미수락 확정: 2 s 동안 시작 위치에 정지 상태로 관측', step,
                                      dict(tcp_pose=posx_to_pose(cur, self.tool_offset_m), accepted=False, at_start=True,
                                           motion_status=0, stop_confirmed=True))
                return self._motion_failure('UNKNOWN', 'TIMEOUT', '명령 후 이동 시작 미확인 (상태 재확인도 불충분)', step)
            err = math.dist(cur[:3], target[:3])
            if monitor is not None and monitor.get('ignore_normal') and monitor.get('normals'):
                # 힘 유지 중에는 법선 방향 위치를 제어기가 힘에 맞춰 덮어쓰므로, 완료 판정은 접선·높이 성분만 본다
                surface = monitor['surface']; tgt_m = [v / 1000.0 for v in target[:3]]
                n = monitor['normals'][min(range(len(surface)), key=lambda k: math.dist(tgt_m, surface[k][:3]))]
                e = [cur[k] - target[k] for k in range(3)]
                along = sum(e[k] * n[k] for k in range(3))
                err = math.sqrt(max(0.0, sum(v * v for v in e) - along * along))
            settled = (moved and (controller_started or not require_controller_start)
                       and excursion >= closed_excursion_mm
                       and angular_excursion >= closed_excursion_deg and state == self.STATE_STANDBY
                       and motion == 0 and err <= tol_mm
                       and self._angle_error(cur, target) <= angle_tol_deg)
            if settled:
                if (anchor is None or math.dist(cur[:3], anchor[:3]) > 0.05
                        or self._angle_error(cur, anchor) > 0.05):
                    anchor, stable_since = cur, now
                elif now - stable_since >= 0.2:
                    return StepResult('SUCCEEDED', 'NONE', '', step,
                                      dict(tcp_pose=posx_to_pose(cur, self.tool_offset_m), error_mm=err,
                                           motion_started=require_start, motion_status=0, stop_confirmed=True))
            else:
                anchor = stable_since = None
            time.sleep(min(0.05, max(0.0, deadline_s - (time.monotonic() - t0))))

    def _execute_motion(self, poses, frame_id, profile, deadline_s, cancel, spline):
        step = 'move_spline' if spline else 'move'
        previous_target = getattr(self, '_last_completed_target', None)
        self._last_completed_target = None
        if _cancelled(cancel):
            return StepResult('STOPPED', 'NONE', '취소됨 (이동 전)', step)
        if not self._frame_ok(frame_id):
            return StepResult('FAILED', 'INVALID_INPUT', 'frame_id 불일치', step)
        try:
            if spline and not 2 <= len(poses) <= 80:
                raise ValueError('movesx 점 수는 2~80')
            vel = float(profile['vel_mm_s']); acc = float(profile.get('acc_mm_s2', vel * 2))
            tol = float(profile.get('pos_tol_mm', 3.0 if spline else 2.0))
            angle_tol = float(profile.get('angle_tol_deg', 0.15))
            if any(not math.isfinite(v) or v <= 0 for v in (vel, acc, tol, angle_tol, deadline_s)):
                raise ValueError('속도·가속도·허용오차·제한 시간은 양의 유한 값이어야 함')
            if any(len(p) != 7 or any(not math.isfinite(v) for v in p) for p in poses):
                raise ValueError('유효한 pose7 필요')
            points = [pose_to_posx(p, self.tool_offset_m) for p in poses]
        except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
            return StepResult('FAILED', 'INVALID_INPUT', str(exc), step)
        end = time.monotonic() + deadline_s
        try:
            start, state, motion = self._motion_sample(min(2.0, deadline_s))
            if _cancelled(cancel):
                return StepResult('STOPPED', 'NONE', '취소됨 (전송 전)', step)
            if state != self.STATE_STANDBY or motion != 0:
                return StepResult('FAILED', 'NOT_READY', '새 명령 전 정지 상태 아님', step)
            remaining = end - time.monotonic()
            if remaining <= 0:
                return StepResult('UNKNOWN', 'TIMEOUT', '전송 전 제한 시간 초과', step)
        except Exception as exc:
            return StepResult('UNKNOWN', 'COMMUNICATION_LOST', str(exc), step)
        # 시작점과 같은 단일 목표는 정착만 확인한다. 폐곡선 spline에는 적용하지 않는다.
        exact_target = (math.dist(start[:3], points[-1][:3]) < 1e-6
                        and self._angle_error(start, points[-1]) < 1e-6)
        # 직전 완료 명령과 동일한 목표만 관측 잡음 허용 범위에서 재전송을 생략한다.
        # 새 깊이 목표는 허용오차 안이어도 전송하며 폐곡선에는 적용하지 않는다.
        repeated_target = (previous_target is not None
                           and math.dist(previous_target[:3], points[-1][:3]) < 1e-6
                           and self._angle_error(previous_target, points[-1]) < 1e-6
                           and math.dist(start[:3], points[-1][:3]) <= tol
                           and self._angle_error(start, points[-1]) <= angle_tol)
        if not spline and (exact_target or repeated_target):
            result = self._wait_motion(points[-1], remaining, cancel, step, tol, start=start,
                                       angle_tol_deg=angle_tol, require_start=False)
            if result.ok:
                self._last_completed_target = list(points[-1])
            return result
        extent = max(math.dist(start[:3], p[:3]) for p in points)
        angle_extent = max(self._angle_error(start, p) for p in points)
        if spline and extent < 1e-6 and angle_extent < 1e-6:
            return StepResult('FAILED', 'INVALID_INPUT', '이동 구간 없는 spline', step)
        sent = False
        try:
            sent = True  # 응답 실패도 접수 불명: 정지 확인하며 재전송하지 않는다.
            if spline:
                from std_msgs.msg import Float64MultiArray
                kind = self._srv['MoveSplineTask']
                req = kind.Request(pos=[Float64MultiArray(data=[float(v) for v in p]) for p in points],
                                   pos_cnt=len(points), vel=[vel, vel], acc=[acc, acc], time=0.0,
                                   ref=0, mode=0, opt=0, sync_type=1)
                result = self._call('motion/move_spline_task', kind, req, timeout=min(2.0, remaining))
            else:
                result = self._send_line(points[0], vel, acc, min(2.0, remaining))
            if result is None or result.success is not True:
                return self._motion_failure('FAILED', 'NOT_READY', '이동 명령 거부/응답 없음', step)
            closed_excursion = closed_angle = 0.0
            if spline and math.dist(start[:3], points[-1][:3]) <= tol:
                closed_excursion = min(0.03, extent / 2.0)
                if self._angle_error(start, points[-1]) <= angle_tol:
                    closed_angle = min(0.03, angle_extent / 2.0)
            monitor = profile.get('contact_monitor') or profile.get('air_monitor')
            result = self._wait_motion(points[-1], max(0.0, end-time.monotonic()), cancel, step, tol,
                                     start=start, angle_tol_deg=angle_tol,
                                     closed_excursion_mm=closed_excursion, closed_excursion_deg=closed_angle,
                                     require_controller_start=spline and math.dist(start[:3], points[-1][:3]) <= tol,
                                     monitor=monitor)
            if result.ok:
                self._last_completed_target = list(points[-1])
            return result
        except Exception as exc:
            if sent:
                return self._motion_failure('UNKNOWN', 'COMMUNICATION_LOST', str(exc), step)
            return StepResult('UNKNOWN', 'COMMUNICATION_LOST', str(exc), step)

    def move(self, pose, frame_id, profile, deadline_s, cancel) -> StepResult:
        return self._execute_motion([pose], frame_id, profile, deadline_s, cancel, False)

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel) -> StepResult:
        return self._execute_motion(poses, frame_id, profile, deadline_s, cancel, True)

    # ---- 힘 감시 접촉 찾기 ----
    def probe_touch(self, direction, max_m, profile, deadline_s, cancel) -> StepResult:
        """base 단위벡터 direction 으로 저속 직선 이동(비동기)하며 이동 방향 반력 급증/완만 상승을 접촉으로 판정.
        위치 제어 + 힘 감시 (순응 제어 없음: 툴 무게 과보상으로 순응 모드가 위로 밀림, 9/17).
        profile: touch_force_n(완만 상승 문턱), touch_step_n(급증 문턱, 기본 1.5), touch_speed_mm_s, hard_limit_n(기본 4.5),
                 settle_s(기본 1.5), settle_mm(기본 4). 반환 observed_state: contact(bool), tcp_pose(m), onset_pose(m), force_n"""
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨 (접촉 찾기 전)", "probe_touch")
        try:
            if (len(direction) != 3 or not all(math.isfinite(v) for v in direction)
                    or not math.isfinite(max_m) or max_m <= 0
                    or not math.isfinite(deadline_s) or deadline_s <= 0):
                raise ValueError("접촉 방향/거리/제한 시간 오류")
            n = math.sqrt(sum(v * v for v in direction))
            if n <= 0:
                raise ValueError("접촉 방향은 영벡터일 수 없음")
            d = [v / n for v in direction]
            speed = float(profile["touch_speed_mm_s"]); soft_n = float(profile["touch_force_n"])
            step_n = float(profile.get("touch_step_n", 1.5)); hard_n = float(profile.get("hard_limit_n", 4.5))
            settle_s = float(profile.get("settle_s", 1.5)); settle_mm = float(profile.get("settle_mm", 4.0))
            soft_samples = int(profile.get("soft_samples", 2))
            dual = profile.get("entry_confirmation") == "force_and_position"
            target = profile.get("entry_target_tip_pose")
            if dual and (not isinstance(target, (list, tuple)) or len(target) != 7
                         or not all(math.isfinite(v) for v in target)):
                raise ValueError("복합 진입 판정에는 도구 끝 목표 자세 필요")
            if (any(not math.isfinite(v) or v <= 0 for v in (speed, soft_n, step_n, hard_n))
                    or any(not math.isfinite(v) or v < 0 for v in (settle_s, settle_mm))
                    or soft_samples < 1):
                raise ValueError("접촉 프로파일 범위 오류")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return StepResult("FAILED", "INVALID_INPUT", str(exc), "probe_touch")
        end = time.monotonic() + deadline_s
        max_mm = max_m * 1000.0

        def remaining():
            if _cancelled(cancel):
                raise CancelledError("접촉 찾기 취소")
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError("접촉 찾기 제한 시간 초과")
            # 서비스 응답 기한과 동작 전체 기한 중 짧은 것을 사용한다.
            return min(2.0, left)

        def along(mm):
            return [start[k] + d[k] * mm for k in range(3)] + start[3:6]

        def travelled(cur):
            return sum((cur[k] - start[k]) * d[k] for k in range(3))

        def f_of(vec):
            return -sum(vec[k] * d[k] for k in range(3))

        try:
            start = self._posx_now(timeout=remaining())
            if dual:
                start_tip = posx_to_pose(start, self.tool_offset_m)
                target_travel = sum((target[k] - start_tip[k]) * d[k] for k in range(3))
                lateral = math.sqrt(sum((target[k]-start_tip[k]-target_travel*d[k])**2 for k in range(3)))
                if not 0 <= target_travel < max_m or lateral > .0003:
                    raise ValueError("진입 목표가 탐색 선분/거리 범위 밖")
            base = [f_of(self._force_vec(timeout=remaining())) for _ in range(8)]
            if not all(math.isfinite(v) for v in base):
                raise ValueError("유효하지 않은 힘 기준값")
            f0 = sum(base) / len(base)
            _, state, motion = self._motion_sample(remaining())
            remaining()
            if state != self.STATE_STANDBY or motion != 0:
                return StepResult("FAILED", "NOT_READY", "접촉 전 정지 상태 아님", "probe_touch")
        except CancelledError:
            return self._motion_failure("STOPPED", "NONE", "접촉 전 취소", "probe_touch")
        except Exception as exc:
            return StepResult("UNKNOWN", "TIMEOUT" if isinstance(exc, TimeoutError) else "COMMUNICATION_LOST",
                              str(exc), "probe_touch", dict(contact=False))
        try:
            accepted = self._send_line(along(max_mm), speed, max(1.0, speed), remaining())
            if accepted is None or accepted.success is not True:
                return self._motion_failure("FAILED", "NOT_READY", "접촉 이동 명령 거부", "probe_touch")
        except CancelledError:
            return self._motion_failure("STOPPED", "NONE", "접촉 전송 전 취소", "probe_touch")
        except Exception as exc:
            return self._motion_failure("UNKNOWN", "TIMEOUT" if isinstance(exc, TimeoutError) else "COMMUNICATION_LOST",
                                        str(exc), "probe_touch")
        t0 = time.monotonic(); hist = []; f_move = None; step_run = 0; soft_run = 0
        result = StepResult("FAILED", "TIMEOUT", "접촉 없이 끝남", "probe_touch", dict(contact=False))
        try:
            while True:
                now = time.monotonic()
                if now >= end:
                    # finally에서 실제 정지까지 확인한다.
                    result = StepResult("UNKNOWN", "TIMEOUT", "접촉 찾기 제한 시간 초과", "probe_touch", dict(contact=False))
                    break
                if _cancelled(cancel):
                    # finally에서 실제 정지까지 확인한다.
                    result = StepResult("STOPPED", "NONE", "취소됨 (접촉 찾기 중)", "probe_touch", dict(contact=False))
                    break
                cur = self._posx_now(timeout=remaining())
                tr = travelled(cur)
                f = f_of(self._force_vec(timeout=remaining()))
                remaining()  # 늦게 받은 값 또는 취소 후 응답을 접촉 성공으로 쓰지 않는다.
                now = time.monotonic()
                if not math.isfinite(f):
                    raise ValueError("유효하지 않은 힘 관측")
                if dual:
                    tip_now = posx_to_pose(cur, self.tool_offset_m)
                    position_ok = sum((tip_now[k]-target[k])*d[k] for k in range(3)) >= 0
                    delta = f-f0
                    soft_run = soft_run+1 if delta >= soft_n else 0
                    force_ok = soft_run >= soft_samples
                    values = dict(contact=force_ok, force_ok=force_ok, position_ok=position_ok,
                                  entry_confirmed=force_ok and position_ok, tcp_pose=tip_now,
                                  force_delta_n=delta, travelled_m=tr/1000.)
                    # 과부하는 접촉 성공으로 바꾸지 않는다. 과거 힘 신호도 성공으로 고정하지 않는다.
                    if abs(delta) >= hard_n:
                        values["entry_confirmed"] = False
                        result = StepResult("FAILED", "VALIDATION_FAILED", "진입 힘 상한 초과", "probe_touch", values)
                        break
                    if position_ok and force_ok:
                        result = StepResult("SUCCEEDED", "NONE", "좌표·힘 복합 진입 확인", "probe_touch", values)
                        break
                    if tr >= max_mm - .05:
                        result = StepResult("FAILED", "VALIDATION_FAILED", "추가 진입 한도에서 두 조건 미충족", "probe_touch", values)
                        break
                    time.sleep(.05)
                    continue
                hist.append((now, tr, f)); hist = [h for h in hist if now - h[0] <= 2.0]
                avg = [h[2] for h in hist if 0.3 <= now - h[0] <= 1.8 and h[0] - t0 >= 1.0]
                step = f - sum(avg) / len(avg) if len(avg) >= 3 else 0.0
                settled = now - t0 >= settle_s and tr >= settle_mm
                if settled and f_move is None:
                    recent = [h[2] for h in hist if now - h[0] <= 0.5]
                    f_move = sum(recent) / len(recent)
                dm = (f - f_move) if f_move is not None else 0.0
                step_run = step_run + 1 if (settled and step >= step_n) else 0
                hard = (settled and abs(dm) >= hard_n) or (tr >= 1.0 and abs(f - f0) >= 2 * hard_n)
                soft_run = soft_run + 1 if (settled and dm >= soft_n) else 0
                soft = soft_run >= soft_samples
                if step_run >= 2 or hard or soft:
                    # finally에서 실제 정지까지 확인한다.
                    # 힘이 오르기 시작한 지점: 최근 3 s 창 안에서만 찾고, 기준은 그 직전(3~1.5 s 전) 평균으로 잡는다.
                    # (9/18 bag 1836: 250 mm 긴 하강에서 출발 기준 대비 서서히 밀린 값 때문에 onset 이 190 mm 위로 잡혔다)
                    win = [h for h in hist if now - h[0] <= 3.0]
                    before = [h[2] for h in win if 1.5 <= now - h[0] <= 3.0]
                    ref = sum(before) / len(before) if before else (f_move if f_move is not None else f0)
                    on_tr = tr
                    for (th, ttr, tf) in reversed(win):
                        if tf - ref >= 0.6:
                            on_tr = ttr
                        else:
                            break
                    on_tr = max(0.0, min(on_tr, tr))
                    on = along(on_tr)
                    result = StepResult("SUCCEEDED", "NONE",
                                        "접촉 " + ("급증" if step_run >= 2 else "강한" if hard else "완만"),
                                        "probe_touch",
                                        dict(contact=True, tcp_pose=posx_to_pose(cur, self.tool_offset_m),
                                             onset_pose=posx_to_pose([on[0], on[1], on[2], start[3], start[4], start[5]], self.tool_offset_m),
                                             force_n=abs(f - f0), travelled_m=tr / 1000.0))
                    break
                if tr >= max_mm - 0.3:
                    result = StepResult("FAILED", "VALIDATION_FAILED", f"{max_mm:.0f} mm 안에 접촉 없음", "probe_touch",
                                        dict(contact=False, tcp_pose=posx_to_pose(cur, self.tool_offset_m)))
                    break
                time.sleep(0.05)
        except CancelledError:
            result = StepResult("STOPPED", "NONE", "접촉 찾기 취소", "probe_touch", dict(contact=False))
        except Exception as exc:
            result = StepResult("UNKNOWN", "TIMEOUT" if isinstance(exc, TimeoutError) else "COMMUNICATION_LOST",
                                str(exc), "probe_touch", dict(contact=False))
        finally:
            stopped = self.stop({"mode": 1}, 2.0)
            if not stopped.ok or stopped.observed_state.get("stop_confirmed") is not True:
                return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "접촉 종료 후 정지 미확인", "probe_touch",
                                  dict(contact=False, stop_confirmed=False))
        result.observed_state["stop_confirmed"] = True
        if dual and result.ok:
            stopped_tip = stopped.observed_state.get("tcp_pose")
            if not stopped_tip or not all(math.isfinite(v) for v in stopped_tip):
                return StepResult("UNKNOWN", "NOT_READY", "진입 후 실제 정지 위치 미확인", "probe_touch",
                                  dict(stop_confirmed=True, entry_confirmed=False))
            stopped_travel = sum((stopped_tip[k]-start_tip[k])*d[k] for k in range(3))
            position_ok = sum((stopped_tip[k]-target[k])*d[k] for k in range(3)) >= 0
            if not position_ok or stopped_travel > max_m:
                return StepResult("FAILED", "VALIDATION_FAILED", "정지 위치가 진입 검사 범위 밖", "probe_touch",
                                  dict(stop_confirmed=True, position_ok=position_ok, entry_confirmed=False,
                                       tcp_pose=stopped_tip))
            result.observed_state["detection_tip_pose"] = result.observed_state["tcp_pose"]
            result.observed_state["tcp_pose"] = stopped_tip
        return result

    # ---- 정지 ----
    def stop(self, stop_profile, deadline_s) -> StepResult:
        """정지 접수와 실제 정지를 구별한다. 위치·자세·motion=0 정착까지 확인."""
        self._last_completed_target = None
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            return StepResult('FAILED', 'INVALID_INPUT', '정지 제한 시간 오류', 'stop',
                              dict(stop_confirmed=False))
        end = time.monotonic() + deadline_s
        try:
            kind = self._srv['MoveStop']
            result = self._call('motion/move_stop', kind,
                                kind.Request(stop_mode=int(stop_profile.get('mode', 2))),
                                timeout=min(2.0, deadline_s))
            if result is None or result.success is not True:
                return StepResult('UNKNOWN', 'STOP_UNCONFIRMED', '정지 접수 확인 불가', 'stop',
                                  dict(stop_confirmed=False))
            anchor = None
            stable = None
            while time.monotonic() < end:
                px, state, motion = self._motion_sample(min(2.0, end-time.monotonic()))
                now = time.monotonic()
                if now >= end:
                    break
                if state == self.STATE_STANDBY and motion == 0:
                    if (anchor is None or math.dist(px[:3], anchor[:3]) > 0.05
                            or self._angle_error(px, anchor) > 0.05):
                        anchor, stable = px, now
                    elif now - stable >= 0.2:
                        return StepResult('SUCCEEDED', 'NONE', '실제 정지 확인', 'stop',
                                          dict(robot_state=state, motion_status=motion,
                                               stop_confirmed=True, tcp_pose=posx_to_pose(px, self.tool_offset_m)))
                else:
                    anchor = stable = None
                time.sleep(min(0.05, max(0.0, end-time.monotonic())))
        except Exception as exc:
            return StepResult('UNKNOWN', 'STOP_UNCONFIRMED', str(exc), 'stop',
                              dict(stop_confirmed=False))
        return StepResult('UNKNOWN', 'STOP_UNCONFIRMED', '정지 관측 제한 시간 초과', 'stop',
                          dict(stop_confirmed=False))


# ---------------------------------------------------------------- 모의 어댑터 ----
class MockRobotAdapter(RobotAdapter):
    """로봇 없이 흐름을 검증한다. 호출 기록(calls)을 남기고, probe_touch 는 surface_fn(start_pose, direction) 이 주는
    거리(m)에서 접촉한 것으로 답한다. fail_at / stop_at 으로 실패·취소 사례를 흉내 낸다."""

    def __init__(self, frame_id="c2_base", surface_fn: Optional[Callable] = None, fail_at: Optional[str] = None,
                 delay_s: float = 0.0, move_time_s: float = 0.0):
        self.frame_id, self.surface_fn, self.fail_at, self.delay_s = frame_id, surface_fn, fail_at, delay_s
        self.move_time_s = move_time_s                  # > 0 이면 이동이 이 시간 동안 진행되며 도중 취소를 받는다
        self.pose = [0.384, 0.0076, 0.1054, 0.0, 1.0, 0.0, 0.0]    # 홈 근처 임의 시작
        self.tool_offset_m = None
        self.calls: List[Dict] = []
        self.stopped = False
        self.hold_active = False                       # 법선 힘 유지 모의 상태
        self.force_fn: Optional[Callable] = None        # force_fn(tip_pose) → base 힘 [Fx,Fy,Fz] (CUT 감시 모의)
        self.deviation_fn: Optional[Callable] = None    # deviation_fn(tip_pose) → 표면 대비 법선 이탈 m (순응이 밀어낸 양의 모의)
        self.hold_fail_at: Optional[str] = None         # "begin" | "end" 실패 모의

    def read_force_bias(self, samples=8):
        self.calls.append(dict(fn="read_force_bias"))
        return [0.0, 0.0, 0.0]

    def hold_normal_force_begin(self, tool_axis, profile, deadline_s, cancel):
        self.calls.append(dict(fn="hold_begin", axis=tool_axis, force=profile.get("cut_force_n")))
        for key in ("cut_force_n", "cut_stiffness", "ramp_s"):
            if profile.get(key) is None:
                return StepResult("FAILED", "NOT_READY", f"힘 유지 프로파일 없음: {key}", "hold_normal_force_begin")
        if self.hold_fail_at == "begin":
            return StepResult("FAILED", "NOT_READY", "모의 힘 유지 시작 실패", "hold_normal_force_begin", dict(force_released=True))
        self.hold_active = True
        return StepResult("SUCCEEDED", "NONE", "", "hold_normal_force_begin", dict(hold_active=True))

    def hold_normal_force_end(self, deadline_s):
        self.calls.append(dict(fn="hold_end"))
        if self.hold_fail_at == "end" and self.hold_active:
            return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "모의 해제 실패", "hold_normal_force_end", dict(force_released=False))
        was = self.hold_active
        self.hold_active = False
        return StepResult("SUCCEEDED", "NONE", "", "hold_normal_force_end", dict(force_released=True, was_active=was))

    def _monitor(self, profile, poses, step):
        """이동 중 힘 감시 모의: 각 목표점에서 force_fn/deviation_fn 으로 샘플을 만들어 실기와 같은 판정을 한다."""
        monitor = profile.get("contact_monitor") or profile.get("air_monitor")
        if monitor is None:
            return None
        for p in poses:
            f = self.force_fn(p) if self.force_fn else [0.0, 0.0, 0.0]
            tip = list(p)
            if monitor.get("kind") == "CUT" and self.deviation_fn and monitor.get("surface"):
                i = min(range(len(monitor["surface"])), key=lambda k: math.dist(p[:3], monitor["surface"][k][:3]))
                n = monitor["normals"][i]; d = self.deviation_fn(p)
                tip = [monitor["surface"][i][k] + n[k] * d for k in range(3)] + list(p[3:])
            sample = evaluate_contact_sample(monitor, tip, f)
            monitor.setdefault("samples", []).append(sample)
            if sample["fail"]:
                self.calls.append(dict(fn="stop")); self.stopped = True
                code, message = sample["fail"]
                return StepResult("FAILED", code, message + " → 정지", step, dict(tcp_pose=list(self.pose), stop_confirmed=True))
        return None

    def _rec(self, name, **kw):
        self.calls.append(dict(fn=name, **kw))
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail_at == name:
            return StepResult("FAILED", "NOT_READY", f"모의 실패 {name}", name)
        return None

    def inverse_kinematics(self, pose, tool_offset_m, ref_joints_deg):
        """모의 IK: J6 = 툴 Y 의 base 방위각(deg) + ik_j6_offset, 나머지는 ref 그대로. ik_fail_at_call 번째 호출부터 None."""
        self.calls.append(dict(fn="ik"))
        if getattr(self, "ik_fail_at_call", None) is not None and self.calls.count(dict(fn="ik")) >= self.ik_fail_at_call:
            return None
        ty = tool_axis_in_base(pose, "+y")
        j6 = math.degrees(math.atan2(ty[1], ty[0])) + getattr(self, "ik_j6_offset", 0.0)
        q = list(ref_joints_deg); q[5] = j6
        return q

    def set_tool_offset(self, offset_tool_m):
        self.tool_offset_m = list(offset_tool_m) if offset_tool_m else None
        self.calls.append(dict(fn="set_tool_offset", offset=self.tool_offset_m))

    def observe(self):
        return RobotState(joints_rad=[0.0] * 6, tcp_pose=list(self.pose), frame_id=self.frame_id, robot_state=1,
                          force_n=[0.0, 0.0, 0.0], measured_at=time.monotonic(), quality="VALID")

    def select_tool_profile(self, tcp_id, load_id, profile_version=None, deadline_s=10.0):
        r = self._rec("select_tool_profile", tcp=tcp_id, load=load_id, version=profile_version)
        return r or StepResult("SUCCEEDED", "NONE", "", "select_tool_profile",
                               dict(tcp=tcp_id, tool=load_id, profile_version=profile_version, applied=True))

    def _simulate_motion(self, target, step, cancel):
        """이동을 move_time_s 동안 잘게 나눠 진행하며 cancel 을 감시한다 (실기 _wait_motion 과 같은 의미)."""
        n = max(1, int(self.move_time_s / 0.01))
        start = list(self.pose)
        for i in range(1, n + 1):
            if _cancelled(cancel):
                self.stopped = True
                self.calls.append(dict(fn="stop"))
                return StepResult("STOPPED", "NONE", f"취소됨 ({step} 대기 중)", step, dict(tcp_pose=list(self.pose)))
            if self.move_time_s:
                time.sleep(0.01)
            self.pose = [start[k] + (target[k] - start[k]) * i / n for k in range(3)] + list(target[3:])
        return StepResult("SUCCEEDED", "NONE", "", step, dict(tcp_pose=list(self.pose)))

    def move(self, pose, frame_id, profile, deadline_s, cancel):
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨", "move")
        r = self._rec("move", pose=list(pose), profile=profile.get("id"), hold=self.hold_active)
        if r:
            return r
        r = self._monitor(profile, [pose], "move")
        if r:
            return r
        return self._simulate_motion(list(pose), "move", cancel)

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel):
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨", "move_spline")
        if not 2 <= len(poses) <= 80:
            return StepResult("FAILED", "INVALID_INPUT", f"movesx 점 수 {len(poses)}", "move_spline")
        r = self._rec("move_spline", n=len(poses), profile=profile.get("id"), hold=self.hold_active)
        if r:
            return r
        r = self._monitor(profile, poses, "move_spline")
        if r:
            return r
        return self._simulate_motion(list(poses[-1]), "move_spline", cancel)

    def probe_touch(self, direction, max_m, profile, deadline_s, cancel):
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨", "probe_touch")
        r = self._rec("probe_touch", direction=list(direction), max_m=max_m)
        if r:
            return r
        dist = self.surface_fn(self.pose, direction) if self.surface_fn else max_m * 0.5
        if dist is None or dist > max_m:
            return StepResult("FAILED", "VALIDATION_FAILED", f"{max_m * 1000:.0f} mm 안에 접촉 없음", "probe_touch", dict(contact=False))
        p = list(self.pose)
        for k in range(3):
            p[k] += direction[k] * dist
        self.pose = p
        return StepResult("SUCCEEDED", "NONE", "접촉 모의", "probe_touch",
                          dict(contact=True, tcp_pose=list(p), onset_pose=list(p), force_n=float(profile.get("touch_force_n", 0.8)),
                               travelled_m=dist))

    def stop(self, stop_profile, deadline_s):
        self.calls.append(dict(fn="stop"))
        self.stopped = True
        return StepResult("SUCCEEDED", "NONE", "정지 확인(모의)", "stop")
