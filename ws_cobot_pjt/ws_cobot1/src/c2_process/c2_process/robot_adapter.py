# robot_adapter.py — 두산 드라이버(ws_dsr 브링업) 호출·결과 확인·단위 변환. 공정 제어의 로봇 연결 모듈.
# 집기·반납(tool_sequence)·조각(engraving)·청소(cleaning)가 함께 부른다. 별도 ROS Topic/Service 를 만들지 않는다.
# 담당: 이시율 (초안 2026-09-18, 로컬). 실기 검증본 clay_carving/clay_common.py 의 Robot 클래스를 새 계약에 맞춰 옮겼다.
#
# 계약(INTERFACE_RECOMMENDATION v1 §2·§9):
#   - 입력 자세는 m + quaternion(x,y,z,w) + frame_id. 두산 API 의 mm·ZYZ(A,B,C deg) 변환은 이 파일에서만 한다.
#   - 함수는 부르면 완료·실패·정지 중 하나로 돌아온다(호출자 입장 동기). 안에서는 비동기 명령(amovel/amovesx)을 보내고
#     완료를 감시하므로, 이동 대기 중에도 cancel 이벤트를 보면 즉시 QSTOP 을 보내고 STOPPED 로 돌아온다 (명세 §9).
#   - deadline_s 초과·취소·오류를 상위로 전달하고, 정지 접수와 실제 정지 확인을 구분한다.
#   - 실기(REAL) 값(속도·힘·TCP)은 프로파일(tools.yaml 스냅샷)에서만 온다. 여기에 현장 수치를 넣지 않는다.
import math
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

    def set_tool_offset(self, offset_tool_m):
        """제어기 TCP(패드 기본값) 에서 송곳 끝까지의 도구 좌표계 오프셋 [ox,oy,oz] (m). 집기 뒤 측정한 송곳 길이로
        tool_sequence/상태 기계가 설정한다. 이후 move/move_spline/observe 는 모두 '송곳 끝' 기준으로 동작한다."""
        raise NotImplementedError


def _cancelled(cancel) -> bool:
    return cancel is not None and cancel.is_set()


# ---------------------------------------------------------------- 실기: 두산 드라이버 ----
class DoosanRobotAdapter(RobotAdapter):
    """ws_dsr 브링업(dsr_controller2, namespace dsr01)의 서비스를 DSR_ROBOT2 파이썬 API 로 호출한다.
    node: rclpy 노드 (namespace 'dsr01' 로 만든 것). 생성 시 서비스 대기·툴/TCP 확인·상태 확인은 하지 않는다 →
    상태 기계의 preconditions 와 select_tool_profile() 이 담당."""

    ROBOT_ID, ROBOT_MODEL = "dsr01", "m0609"
    STATE_STANDBY, STATE_MOVING = 1, 2

    def __init__(self, node, frame_id="c2_base", logger=None):
        import DR_init
        setattr(DR_init, "__dsr__id", self.ROBOT_ID)
        setattr(DR_init, "__dsr__model", self.ROBOT_MODEL)
        setattr(DR_init, "__dsr__node", node)          # 클래스 안 'DR_init.__dsr__node=' 는 이름 맹글링 → setattr
        import DSR_ROBOT2 as R
        from DR_common2 import posx
        from dsr_msgs2.srv import (MoveStop, GetCurrentTcp, GetCurrentTool, SetCurrentTcp, SetCurrentTool, SetRobotMode,
                                   GetRobotState)
        self.node, self.R, self.posx, self.frame_id = node, R, posx, frame_id
        self.tool_offset_m = None                      # set_tool_offset() 으로 설정 (없으면 제어기 TCP 그대로)
        self.log = logger or node.get_logger()
        self._srv = dict(MoveStop=MoveStop, GetCurrentTcp=GetCurrentTcp, GetCurrentTool=GetCurrentTool,
                         SetCurrentTcp=SetCurrentTcp, SetCurrentTool=SetCurrentTool, SetRobotMode=SetRobotMode,
                         GetRobotState=GetRobotState)
        R._ros2_movej.wait_for_service()
        R._ros2_movel.wait_for_service()
        time.sleep(1.0)                                # 양방향 디스커버리 여유 (응답 유실 방지, 9/17)
        R.set_singular_handling(R.DR_AVOID)
        R.set_ref_coord(R.DR_BASE)

    # ---- 서비스 도우미 ----
    def _call(self, name, srv, req, timeout=5.0):
        import rclpy
        cli = self.node.create_client(srv, "dsr_controller2/" + name)
        if not cli.wait_for_service(timeout_sec=timeout):
            raise RuntimeError(f"service {name} not available")
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(self.node, fut, timeout_sec=timeout)
        if not fut.done() or fut.result() is None:
            raise RuntimeError(f"service {name} timed out")
        return fut.result()

    def _frame_ok(self, frame_id):
        return frame_id == self.frame_id

    def inverse_kinematics(self, pose, tool_offset_m, ref_joints_deg):
        """제어기 ikin(posx, sol_space) 로 관절해 [deg]. sol_space 는 처음 8개 중 ref 에 가장 가까운 것을 고르고 이후 유지한다."""
        px = pose_to_posx(pose, tool_offset_m)
        best = None
        if getattr(self, "_ik_space", None) is None:
            try:                                                                # 현재(기준) 관절의 해 공간을 제어기에 물어 그것부터
                self._ik_space = int(self.R.get_solution_space(self.R.posj(*[float(v) for v in ref_joints_deg])))
            except Exception:
                self._ik_space = None
        spaces = ([self._ik_space] if self._ik_space is not None else []) + [k for k in range(8) if k != self._ik_space]
        for sp in spaces:
            try:
                q = self.R.ikin(self.posx(*px), sp, self.R.DR_BASE)
            except Exception:
                q = None
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

    def set_tool_offset(self, offset_tool_m):
        self.tool_offset_m = list(offset_tool_m) if offset_tool_m else None
        self.log.info(f"tool offset (tool frame, m) = {self.tool_offset_m}")

    def _posx_now(self):
        p, _ = self.R.get_current_posx()
        return list(p)

    def _tip_pose_now(self):
        return posx_to_pose(self._posx_now(), self.tool_offset_m)

    def _force_vec(self):
        f = self.R.get_tool_force(self.R.DR_BASE)
        return [float(f[0]), float(f[1]), float(f[2])]

    # ---- 관측 ----
    def observe(self) -> RobotState:
        st = RobotState(measured_at=time.monotonic(), frame_id=self.frame_id)
        try:
            j = self.R.get_current_posj()
            st.joints_rad = [math.radians(v) for v in (j if isinstance(j, (list, tuple)) else j[0])]
            st.tcp_pose = self._tip_pose_now()
            st.force_n = self._force_vec()
            st.robot_state = self._call("system/get_robot_state", self._srv["GetRobotState"],
                                        self._srv["GetRobotState"].Request()).robot_state
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

    # ---- 이동 (비동기 명령 + 대기 중 취소·제한 시간 감시) ----
    def _wait_motion(self, target_xyz_mm, deadline_s, cancel, step, tol_mm):
        """amovel/amovesx 를 보낸 뒤 완료를 감시한다. 완료 = TCP 가 목표 tol_mm 안에 들어오고 로봇 상태가 이동 중이 아님.
        (9/18 bag 1819: 명령 직후엔 제어기 상태가 아직 STANDBY 로 읽혀 위치로 판정해야 한다)
        대기 중 cancel 이 서면 즉시 QSTOP → STOPPED. deadline 초과 → QSTOP 후 UNKNOWN(TIMEOUT).
        3 s 동안 위치 변화가 1 mm 미만이고 목표에도 못 갔으면 '안 움직임' FAILED."""
        t0 = time.monotonic()
        last_pos, last_change = None, t0
        while True:
            if _cancelled(cancel):
                self._qstop()
                st = self.observe()
                return StepResult("STOPPED", "NONE", f"취소됨 ({step} 대기 중)", step,
                                  dict(tcp_pose=st.tcp_pose, robot_state=st.robot_state))
            now = time.monotonic()
            if now - t0 > deadline_s:
                self._qstop()
                st = self.observe()
                return StepResult("UNKNOWN", "TIMEOUT", f"{step} 완료가 제한 시간 {deadline_s:.0f}s 를 넘김 (정지 요청함)", step,
                                  dict(tcp_pose=st.tcp_pose, robot_state=st.robot_state))
            cur = self._posx_now()
            err = math.dist(cur[:3], target_xyz_mm)
            if last_pos is None or math.dist(cur[:3], last_pos) >= 1.0:
                last_pos, last_change = cur[:3], now
            if err <= tol_mm:
                st = self.observe()
                if st.robot_state != self.STATE_MOVING:
                    return StepResult("SUCCEEDED", "NONE", "", step, dict(tcp_pose=posx_to_pose(cur, self.tool_offset_m), error_mm=err))
            else:
                st = self.observe()
                if st.robot_state not in (self.STATE_STANDBY, self.STATE_MOVING, None):
                    return StepResult("FAILED", "NOT_READY", f"이동 중 로봇 상태 {st.robot_state} (안전 정지/서보 오프 등)", step,
                                      dict(tcp_pose=posx_to_pose(cur, self.tool_offset_m), robot_state=st.robot_state))
                if now - last_change > 3.0:
                    return StepResult("FAILED", "VALIDATION_FAILED",
                                      f"3 s 동안 움직임 없음, 목표와 {err:.1f} mm 차이 (허용 {tol_mm})", step,
                                      dict(tcp_pose=posx_to_pose(cur, self.tool_offset_m), error_mm=err))
            time.sleep(0.05)

    def move(self, pose, frame_id, profile, deadline_s, cancel) -> StepResult:
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨 (이동 전)", "move")
        if not self._frame_ok(frame_id):
            return StepResult("FAILED", "INVALID_INPUT", f"frame_id {frame_id} != {self.frame_id}", "move")
        vel = float(profile["vel_mm_s"]); acc = float(profile.get("acc_mm_s2", vel * 2))
        target = pose_to_posx(pose, self.tool_offset_m)
        try:
            self.R.mwait()
            ret = self.R.amovel(self.posx(*target), vel=[vel, vel], acc=[acc, acc], ref=0, mod=self.R.DR_MV_MOD_ABS)
        except Exception as e:
            return StepResult("FAILED", "COMMUNICATION_LOST", f"amovel: {e}", "move")
        if ret != 0:
            return StepResult("FAILED", "NOT_READY", f"amovel returned {ret} (제어기 거부/정지 상태)", "move")
        return self._wait_motion(target[:3], deadline_s, cancel, "move", float(profile.get("pos_tol_mm", 2.0)))

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel) -> StepResult:
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨 (곡선 이동 전)", "move_spline")
        if not self._frame_ok(frame_id):
            return StepResult("FAILED", "INVALID_INPUT", f"frame_id {frame_id} != {self.frame_id}", "move_spline")
        if not 2 <= len(poses) <= 80:
            return StepResult("FAILED", "INVALID_INPUT", f"movesx 점 수 {len(poses)} (2~80 만 지원)", "move_spline")
        vel = float(profile["vel_mm_s"]); acc = float(profile.get("acc_mm_s2", vel * 2))
        pts = [self.posx(*pose_to_posx(p, self.tool_offset_m)) for p in poses]
        last = pose_to_posx(poses[-1], self.tool_offset_m)
        try:
            self.R.mwait()
            ret = self.R.amovesx(pts, vel=[vel, vel], acc=[acc, acc], ref=0, mod=self.R.DR_MV_MOD_ABS,
                                 vel_opt=self.R.DR_MVS_VEL_CONST)
        except Exception as e:
            return StepResult("FAILED", "COMMUNICATION_LOST", f"amovesx: {e}", "move_spline")
        if ret != 0:
            return StepResult("FAILED", "NOT_READY", f"amovesx returned {ret}", "move_spline")
        return self._wait_motion(last[:3], deadline_s, cancel, "move_spline", float(profile.get("pos_tol_mm", 3.0)))

    # ---- 힘 감시 접촉 찾기 ----
    def probe_touch(self, direction, max_m, profile, deadline_s, cancel) -> StepResult:
        """base 단위벡터 direction 으로 저속 직선 이동(비동기)하며 이동 방향 반력 급증/완만 상승을 접촉으로 판정.
        위치 제어 + 힘 감시 (순응 제어 없음: 툴 무게 과보상으로 순응 모드가 위로 밀림, 9/17).
        profile: touch_force_n(완만 상승 문턱), touch_step_n(급증 문턱, 기본 1.5), touch_speed_mm_s, hard_limit_n(기본 4.5),
                 settle_s(기본 1.5), settle_mm(기본 4). 반환 observed_state: contact(bool), tcp_pose(m), onset_pose(m), force_n"""
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨 (접촉 찾기 전)", "probe_touch")
        R = self.R
        n = math.sqrt(sum(v * v for v in direction))
        d = [v / n for v in direction]
        speed = float(profile["touch_speed_mm_s"]); soft_n = float(profile["touch_force_n"])
        step_n = float(profile.get("touch_step_n", 1.5)); hard_n = float(profile.get("hard_limit_n", 4.5))
        settle_s = float(profile.get("settle_s", 1.5)); settle_mm = float(profile.get("settle_mm", 4.0))
        soft_samples = int(profile.get("soft_samples", 2))      # 완만 상승은 연속 N 샘플 (9/18 bag 1835: 1 샘플은 10 mm/s 에서 거짓 접촉)
        max_mm = max_m * 1000.0
        start = self._posx_now()

        def along(mm):
            return self.posx(start[0] + d[0] * mm, start[1] + d[1] * mm, start[2] + d[2] * mm, start[3], start[4], start[5])

        def travelled(cur):
            return sum((cur[k] - start[k]) * d[k] for k in range(3))

        def f_of(vec):
            return -(vec[0] * d[0] + vec[1] * d[1] + vec[2] * d[2])

        base = [f_of(self._force_vec()) for _ in range(8)]
        f0 = sum(base) / len(base)
        try:
            R.mwait()
        except Exception:
            pass
        R.movel(along(0.0), vel=[5.0, 5.0], acc=[5.0, 5.0], ref=0, mod=R.DR_MV_MOD_ABS)   # 대기 상태 확정 (9/17 bag 1502)
        R.set_ref_coord(R.DR_BASE)
        ret = R.amovel(along(max_mm), vel=[speed, speed], acc=[max(1.0, speed)] * 2, ref=0, mod=R.DR_MV_MOD_ABS)
        if ret != 0:
            return StepResult("FAILED", "NOT_READY", f"amovel returned {ret}", "probe_touch")
        t0 = time.monotonic(); hist = []; f_move = None; step_run = 0; soft_run = 0
        result = StepResult("FAILED", "TIMEOUT", "접촉 없이 끝남", "probe_touch", dict(contact=False))
        try:
            while True:
                now = time.monotonic()
                if now - t0 > deadline_s:
                    self._qstop()
                    return StepResult("UNKNOWN", "TIMEOUT", "접촉 찾기 제한 시간 초과", "probe_touch", dict(contact=False))
                if _cancelled(cancel):
                    self._qstop()
                    return StepResult("STOPPED", "NONE", "취소됨 (접촉 찾기 중)", "probe_touch", dict(contact=False))
                cur = self._posx_now(); tr = travelled(cur); f = f_of(self._force_vec())
                if f != f:
                    f = hist[-1][2] if hist else f0
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
                    self._qstop()
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
        finally:
            try:
                R.mwait()
            except Exception:
                pass
        return result

    # ---- 정지 ----
    def _qstop(self):
        req = self._srv["MoveStop"].Request(); req.stop_mode = 1      # DR_QSTOP (2는 Soft Stop)
        try:
            self._call("motion/move_stop", self._srv["MoveStop"], req, timeout=3.0)
        except Exception as e:
            self.log.warn(f"move_stop: {e}")

    def stop(self, stop_profile, deadline_s) -> StepResult:
        """QSTOP 접수 후 STANDBY 가 될 때까지 확인. 접수 실패(FAILED)와 정지 미확인(UNKNOWN)을 구분."""
        req = self._srv["MoveStop"].Request(); req.stop_mode = int(stop_profile.get("mode", 2))
        try:
            r = self._call("motion/move_stop", self._srv["MoveStop"], req, timeout=min(3.0, deadline_s))
        except Exception as e:
            return StepResult("FAILED", "COMMUNICATION_LOST", f"정지 접수 실패: {e}", "stop")
        if not r.success:
            return StepResult("FAILED", "NOT_READY", "정지 명령 거부", "stop")
        t0 = time.monotonic()
        while time.monotonic() - t0 < deadline_s:
            st = self.observe()
            if st.robot_state == self.STATE_STANDBY:
                return StepResult("SUCCEEDED", "NONE", "정지 확인", "stop", dict(robot_state=st.robot_state))
            time.sleep(0.1)
        return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "정지 접수됐으나 STANDBY 확인 못 함", "stop")


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
        r = self._rec("move", pose=list(pose), profile=profile.get("id"))
        if r:
            return r
        return self._simulate_motion(list(pose), "move", cancel)

    def move_spline(self, poses, frame_id, profile, deadline_s, cancel):
        if _cancelled(cancel):
            return StepResult("STOPPED", "NONE", "취소됨", "move_spline")
        if not 2 <= len(poses) <= 80:
            return StepResult("FAILED", "INVALID_INPUT", f"movesx 점 수 {len(poses)}", "move_spline")
        r = self._rec("move_spline", n=len(poses), profile=profile.get("id"))
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
