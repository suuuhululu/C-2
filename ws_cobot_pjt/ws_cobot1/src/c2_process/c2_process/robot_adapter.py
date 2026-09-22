# robot_adapter.py — 두산 드라이버(ws_dsr 브링업) 호출·결과 확인·단위 변환. 공정 제어의 로봇 연결 모듈.
# 집기·반납(tool_sequence)·조각(engraving)·청소(cleaning)가 함께 부른다. 별도 ROS Topic/Service 를 만들지 않는다.
# 담당: 이시율 (초안 2026-09-18, 로컬). 실기 검증본 clay_carving/clay_common.py 의 Robot 클래스를 새 계약에 맞춰 옮겼다.
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

    def set_tool_offset(self, offset_tool_m):
        """제어기 TCP(패드 기본값) 에서 송곳 끝까지의 도구 좌표계 오프셋 [ox,oy,oz] (m). 집기 뒤 측정한 송곳 길이로
        tool_sequence/상태 기계가 설정한다. 이후 move/move_spline/observe 는 모두 '송곳 끝' 기준으로 동작한다."""
        raise NotImplementedError


def _cancelled(cancel) -> bool:
    return cancel is not None and cancel.is_set()


# ---------------------------------------------------------------- 실기: 두산 드라이버 ----
class DoosanRobotAdapter(RobotAdapter):
    """ws_dsr 브링업(dsr_controller2, namespace dsr01)의 기존 ROS 서비스를 호출한다. 공정 executor 안에서는 중첩 spin을 하지 않는다.
    node: rclpy 노드 (namespace 'dsr01'). 실행 중에는 별도 작업 스레드에서 호출한다.
    툴/TCP 선택·상태 검사는 상태 기계의 preconditions 와 select_tool_profile() 이 담당."""

    ROBOT_ID, ROBOT_MODEL = "dsr01", "m0609"
    STATE_STANDBY, STATE_MOVING = 1, 2

    def __init__(self, node, frame_id="c2_base", logger=None, *, initialization_timeout_s=5.0):
        from dsr_msgs2.srv import (MoveStop, GetCurrentTcp, GetCurrentTool, SetCurrentTcp, SetCurrentTool, SetRobotMode,
                                   GetRobotState, GetCurrentPosj, GetCurrentPosx, GetToolForce,
                                   MoveLine, MoveSplineTask, CheckMotion, Ikin, GetSolutionSpace,
                                   SetSingularityHandling)
        self.node, self.frame_id = node, frame_id
        self.tool_offset_m = None
        self.log = logger or node.get_logger()
        self._srv = dict(MoveStop=MoveStop, GetCurrentTcp=GetCurrentTcp, GetCurrentTool=GetCurrentTool,
                         SetCurrentTcp=SetCurrentTcp, SetCurrentTool=SetCurrentTool, SetRobotMode=SetRobotMode,
                         GetRobotState=GetRobotState, GetCurrentPosj=GetCurrentPosj,
                         GetCurrentPosx=GetCurrentPosx, GetToolForce=GetToolForce,
                         MoveLine=MoveLine, MoveSplineTask=MoveSplineTask, CheckMotion=CheckMotion,
                         Ikin=Ikin, GetSolutionSpace=GetSolutionSpace,
                         SetSingularityHandling=SetSingularityHandling)
        # 기존 DR_AVOID(0) 설정만 기한 내 전달한다. DSR_ROBOT2 전역 초기화/무제한 대기 없음.
        # 모든 이동/조회 요청에 base ref=0을 명시하므로 전역 set_ref_coord는 불필요하다.
        self._read("motion/set_singularity_handling", "SetSingularityHandling",
                   timeout=initialization_timeout_s, mode=0)

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
        group = ReentrantCallbackGroup()
        cli = self.node.create_client(srv, "dsr_controller2/" + name, callback_group=group)
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
            self.node.destroy_client(cli)

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
            try:
                q = self._read("motion/ikin", "Ikin", pos=[float(v) for v in px], sol_space=sp, ref=0).conv_posj
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

    def _wait_motion(self, target, deadline_s, cancel, step, tol_mm, *, start,
                     angle_tol_deg=0.15, closed_excursion_mm=0.0,
                     closed_excursion_deg=0.0, require_start=True, require_controller_start=False):
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
            excursion = max(excursion, math.dist(cur[:3], start[:3]))
            angular_excursion = max(angular_excursion, self._angle_error(cur, start))
            controller_started |= state == self.STATE_MOVING or motion != 0
            moved |= (state == self.STATE_MOVING or motion != 0 or excursion > 0.03
                      or self._angle_error(cur, start) > 0.03)
            if not moved and now - t0 >= min(3.0, deadline_s):
                return self._motion_failure('UNKNOWN', 'TIMEOUT', '명령 후 이동 시작 미확인', step)
            err = math.dist(cur[:3], target[:3])
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
        if not spline and exact_target:
            return self._wait_motion(points[-1], remaining, cancel, step, tol, start=start,
                                     angle_tol_deg=angle_tol, require_start=False)
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
                                   ref=0, mode=0, opt=1, sync_type=1)
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
            return self._wait_motion(points[-1], max(0.0, end-time.monotonic()), cancel, step, tol,
                                     start=start, angle_tol_deg=angle_tol,
                                     closed_excursion_mm=closed_excursion, closed_excursion_deg=closed_angle,
                                     require_controller_start=spline and math.dist(start[:3], points[-1][:3]) <= tol)
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
            base = [f_of(self._force_vec(timeout=remaining())) for _ in range(8)]
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
        return result

    # ---- 정지 ----
    def stop(self, stop_profile, deadline_s) -> StepResult:
        """정지 접수와 실제 정지를 구별한다. 위치·자세·motion=0 정착까지 확인."""
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
