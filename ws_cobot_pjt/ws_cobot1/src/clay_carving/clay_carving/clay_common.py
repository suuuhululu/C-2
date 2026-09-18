# 점토 하트 프로젝트 공용 모듈: 로봇 초기화, 이동 래퍼(반환값 검사), 힘 프로빙, 그리퍼, 노드 간 통신.
# 노드: clay_scan(1) → gripper_ui(2) → force_probe(3) → clay_heart(4). 시작 신호는 clay_start.
import json
import math
import time

import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String, Empty
import DR_init
from dsr_msgs2.srv import MoveStop, GetCurrentTcp, GetCurrentTool, SetCurrentTcp, SetCurrentTool, SetRobotMode, GetRobotState

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"

# ---- 홈(시작) 자세: 9/17 사용자 지정. 송곳(툴 -Y)이 수직 아래를 향하고 지점토 중심 위 약 50 mm ----
HOME_J = [-40.4, 41.47, 99.13, 57.0, 115.95, -57.09]
HOME_TCP_Z = 105.4               # 홈에서 읽힌 TCP 높이 (9/17 실측). go_home 의 '홈보다 낮은가' 판단용, 도달 후 갱신
TCP_NAME = "GripperDA_v3"        # DART 에 등록된 TCP (0, -60, 208). 9/17 확인: v1 은 (0, 0, 208) 로 다른 항목
TCP_Y_OFF = 60.0                 # GripperDA_v3 의 Y 오프셋: TCP 는 패드(손끝)에서 툴 -Y 로 60 mm 아래(송곳 끝 자리)다.
                                 # 즉 패드 위치 = TCP + 60·(툴 +Y). 9/17 bag 1700/1705: 이걸 모르고 TCP 를 손끝으로 써서
                                 # 스캔 좌표가 툴 +Y 쪽으로 41 mm, 높이 43 mm 어긋났고 3번 노드 송곳이 지점토를 비껴갔다.
TOOL_NAME = "ToolWeight_1"       # DART 툴 무게 항목 (1.55 kg. 실측 무게로 새 항목을 만들면 이름을 바꾼다)
HOME_TCP_XY = (384.1, 7.6)       # 홈 관절에서 읽혀야 하는 TCP x,y (TCP=GripperDA_v3). 9/17 bag 1644: 브링업 재시작 뒤 TCP 가
HOME_TCP_TOL = 8.0               # 플랜지로 풀려 같은 좌표가 120 mm 옆으로 해석됨 → 홈 도달 후 이 값과 다르면 즉시 중단

# ---- 기하 (mm) ----
AWL_LEN = 50.0                   # 송곳이 그리퍼 TCP 에서 툴 -Y 로 튀어나온 길이. 송곳 끝 z = TCP z - 50 (수직 자세)
CLAY_W, CLAY_H = 92.0, 108.0     # 지점토 가로·세로 (크기는 고정, 위치만 프로빙으로 찾는다)
CLAY_T_NOMINAL = 13.0            # 지점토 두께(대략). 프로빙 결과로 갱신
SAFE_CLEAR = 30.0                # 이동 시 툴 끝(손끝/송곳 끝)이 지점토 윗면 위로 유지할 여유 [mm]. 1번 노드 측정값 기준

# ---- 속도 (9/17 사용자 지시 저속) ----
VELJ, ACCJ = 14.0, 14.0
TRAVEL_VEL, TRAVEL_ACC = [26.0, 14.0], [50.0, 26.0]
PLUNGE_VEL, PLUNGE_ACC = [3.4, 3.4], [10.0, 10.0]
DRAW_VEL, DRAW_ACC = [6.6, 6.6], [15.0, 15.0]

# ---- 힘 프로빙 ----
PUSH_N = 3.0                     # 순응 제어로 누르는 힘
ONSET_N = 0.6                    # 프로빙: 접촉 판정 뒤 '힘이 오르기 시작한 지점' 역산 문턱 [N] (이동 중 노이즈 ±0.5)
STIFFNESS = [3000.0, 3000.0, 1000.0, 200.0, 200.0, 200.0]   # Z 만 부드럽게 (접촉력이 서서히 오르게)

# ---- 통신 ----
STAGE_TOPIC = "/clay/stage"      # std_msgs/String: "scan_done" | "grip_done" | "probe_done" | "draw_done"
DATA_TOPIC = "/clay/data"        # std_msgs/String(JSON): 누적 측정값
START_TOPIC = "/clay/start"
PROMPT_TOPIC = "/clay/prompt"     # 노드 → 대시보드: y/n 질문 (JSON {"id", "text"})
ANSWER_TOPIC = "/clay/answer"     # 대시보드 → 노드: 응답 (JSON {"id", "answer": "y"|"n"})
PREVIEW_TOPIC = "/clay/preview"   # 4번 노드 → 대시보드: 실측에 맞춘 도안 (JSON strokes, mm, 중심 기준)
CONFIRM_TOPIC = "/clay/confirm"   # 대시보드 → 4번 노드: "ok" | "cancel"
JOB_TOPIC = "/clay/job"           # 대시보드 → 상태 파일: 도형·크기 가이드라인 (JSON)      # std_msgs/Empty: 1번 노드 시작 신호

LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                     reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST)


class MotionFailed(Exception):
    pass


class Robot:
    """DSR_ROBOT2 초기화와 이동·프로빙 래퍼. 프로세스당 하나."""

    def __init__(self, node, name):
        self.node = node
        self.log = node.get_logger()
        # 클래스 안에서 DR_init.__dsr__node = ... 라고 쓰면 파이썬 이름 맹글링으로 _Robot__dsr__node 가 되어
        # 두산 라이브러리가 노드를 못 받는다 (9/17 가상 검증에서 g_node None 오류). setattr 로 우회한다.
        setattr(DR_init, "__dsr__id", ROBOT_ID)
        setattr(DR_init, "__dsr__model", ROBOT_MODEL)
        setattr(DR_init, "__dsr__node", node)
        import DSR_ROBOT2 as R
        from DR_common2 import posx, posj
        self.R, self.posx, self.posj = R, posx, posj
        self.log.info("Waiting for controller services...")
        R._ros2_movej.wait_for_service()
        R._ros2_movel.wait_for_service()
        time.sleep(1.0)     # 양방향 디스커버리 여유 (응답 유실 방지)
        self.stop_cli = node.create_client(MoveStop, "dsr_controller2/motion/move_stop")
        self.ensure_tool_tcp()
        self.check_robot_state()
        R.set_singular_handling(R.DR_AVOID)
        R.set_velj(VELJ); R.set_accj(ACCJ)
        R.set_velx(*TRAVEL_VEL); R.set_accx(*TRAVEL_ACC)
        R.set_ref_coord(R.DR_BASE)

    # ---- 툴·TCP 선택 확인/복구 ----
    def _call(self, srv_type, name, req, timeout=5.0):
        cli = self.node.create_client(srv_type, "dsr_controller2/" + name)
        if not cli.wait_for_service(timeout_sec=timeout):
            raise MotionFailed(f"service {name} not available")
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(self.node, fut, timeout_sec=timeout)
        if not fut.done() or fut.result() is None:
            raise MotionFailed(f"service {name} timed out")
        return fut.result()

    ROBOT_STATES = {0: "INITIALIZING", 1: "STANDBY", 2: "MOVING", 3: "SAFE_OFF(서보 오프)", 4: "TEACHING", 5: "SAFE_STOP(안전 정지)",
                    6: "EMERGENCY_STOP(비상 정지)", 7: "HOMING", 8: "RECOVERY", 9: "SAFE_STOP2", 10: "SAFE_OFF2", 11: "RESERVED",
                    15: "NOT_READY"}

    def check_robot_state(self):
        """STANDBY 가 아니면 movej 가 -1 로 거부된다 (9/17 bag 1727: SAFE_OFF). 움직이기 전에 상태를 말로 알려주고 멈춘다."""
        st = self._call(GetRobotState, "system/get_robot_state", GetRobotState.Request()).robot_state
        name = self.ROBOT_STATES.get(st, str(st))
        if st in (1, 2):
            self.log.info(f"Robot state: {name}")
            return
        raise MotionFailed(f"Robot state is {name} (state={st}). TP 에서 서보 온 / 안전정지 해제 후 다시 실행")

    def ensure_tool_tcp(self):
        """브링업을 다시 띄우면 제어기의 툴·TCP 선택이 비워진다 (9/17 16:44). 자율 모드에선 선택이 거부되므로
        수동 모드로 바꿔 선택한 뒤 자율 모드로 되돌린다 (9/17 검증: success=True, 홈 TCP 복구)."""
        tcp = self._call(GetCurrentTcp, "tcp/get_current_tcp", GetCurrentTcp.Request()).info
        tool = self._call(GetCurrentTool, "tool/get_current_tool", GetCurrentTool.Request()).info
        if tcp == TCP_NAME and tool == TOOL_NAME:
            self.log.info(f"Tool/TCP OK: {tool} / {tcp}")
            return
        self.log.warn(f"Tool/TCP is '{tool}' / '{tcp}' (expected {TOOL_NAME} / {TCP_NAME}); re-selecting via manual mode")
        ok = True
        ok &= self._call(SetRobotMode, "system/set_robot_mode", SetRobotMode.Request(robot_mode=0)).success
        ok &= self._call(SetCurrentTcp, "tcp/set_current_tcp", SetCurrentTcp.Request(name=TCP_NAME)).success
        ok &= self._call(SetCurrentTool, "tool/set_current_tool", SetCurrentTool.Request(name=TOOL_NAME)).success
        ok &= self._call(SetRobotMode, "system/set_robot_mode", SetRobotMode.Request(robot_mode=1)).success
        tcp = self._call(GetCurrentTcp, "tcp/get_current_tcp", GetCurrentTcp.Request()).info
        tool = self._call(GetCurrentTool, "tool/get_current_tool", GetCurrentTool.Request()).info
        if not ok or tcp != TCP_NAME or tool != TOOL_NAME:
            raise MotionFailed(f"Could not select tool/TCP (now '{tool}' / '{tcp}'). TP 툴 설정에서 {TCP_NAME} / {TOOL_NAME} 선택")
        self.log.info(f"Tool/TCP re-selected: {tool} / {tcp}")

    # ---- 기본 이동 (반환값 검사) ----
    def mv(self, fn, *a, **kw):
        ret = fn(*a, **kw)
        if ret != 0:
            raise MotionFailed(f"{fn.__name__} returned {ret}: robot stopped or rejected the command. "
                               f"Check TP (protective stop → recover, servo on) and rerun.")
        return ret

    def movej(self, j):
        self.mv(self.R.movej, self.posj(*j), vel=VELJ, acc=ACCJ)

    def movel(self, p, vel=None, acc=None):
        self.mv(self.R.movel, p, vel=vel or TRAVEL_VEL, acc=acc or TRAVEL_ACC, ref=0, mod=self.R.DR_MV_MOD_ABS)

    def movesx(self, pts, vel=None, acc=None):
        self.mv(self.R.movesx, pts, vel=vel or DRAW_VEL, acc=acc or DRAW_ACC, ref=0,
                mod=self.R.DR_MV_MOD_ABS, vel_opt=self.R.DR_MVS_VEL_CONST)

    def posx_now(self):
        p, _ = self.R.get_current_posx()
        return list(p)

    def stop(self):
        req = MoveStop.Request(); req.stop_mode = self.R.DR_QSTOP
        fut = self.stop_cli.call_async(req)
        rclpy.spin_until_future_complete(self.node, fut, timeout_sec=3.0)

    def lift_straight_up(self, mm, vel=None):
        """관절 이동 전 안전 상승: 현재 자세 유지, base +Z 로 직선."""
        p = self.posx_now()
        self.movel(self.posx(p[0], p[1], p[2] + mm, p[3], p[4], p[5]), vel=vel or TRAVEL_VEL)

    def check_probe_axis_down(self, max_tilt_deg=15.0):
        """손끝/송곳(툴 -Y)이 수직 아래를 향하는지. 아니면 프로빙 정확도가 떨어져 경고."""
        p = self.posx_now()
        ty = tool_y_axis(p[3], p[4], p[5])
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, ty[2]))))   # 툴 +Y 와 base +Z 사이 각 (0 이면 -Y 가 정확히 아래)
        msg = f"Tool -Y points {tilt:.1f} deg from straight down"
        if tilt > max_tilt_deg:
            self.log.warn(msg + " → probe/awl tip is tilted; contact point may be off. Consider re-teaching HOME_J")
        else:
            self.log.info(msg + " (ok)")
        return tilt

    def at_home(self, tol_deg=2.0):
        q = self.R.get_current_posj()          # posj 리스트 6개 (get_current_posx 와 달리 튜플이 아님)
        if isinstance(q, (list, tuple)) and len(q) and isinstance(q[0], (list, tuple)):
            q = q[0]
        return all(abs(float(a) - b) <= tol_deg for a, b in zip(list(q)[:6], HOME_J))

    def go_home(self, safe_lift=40.0):
        """이미 홈이면 아무것도 안 한다. 아니면 현재 자세로 40 mm 직선 상승 후 홈 관절 자세로.
        (공작물 위에서 movej 를 바로 하면 툴이 쓸려 충돌한다. 9/17)"""
        global HOME_TCP_Z
        z_now = self.posx_now()[2]
        if self.at_home(tol_deg=3.0):
            # 가까워도 홈 관절값으로 정확히 맞춘다 (2° 차이가 TCP 높이 10 mm 이상 차이를 만든다. 9/17 bag 1438)
            self.log.info("Near home pose: aligning exactly to HOME_J")
            self.movej(HOME_J)
            HOME_TCP_Z = self.posx_now()[2]
            self.check_tcp_at_home()
            return
        # 홈보다 낮은 곳(공작물 근처)에 있을 때만 먼저 위로 뺀다. 홈보다 높으면 바로 관절 이동.
        if z_now < HOME_TCP_Z - 3.0:
            self.log.info(f"Below home height ({z_now:.1f} < {HOME_TCP_Z:.1f}): safety lift +{safe_lift:.0f} mm first")
            self.lift_straight_up(safe_lift)
        else:
            self.log.info(f"At/above home height ({z_now:.1f}): joint move to home directly")
        self.movej(HOME_J)
        HOME_TCP_Z = self.posx_now()[2]
        self.check_tcp_at_home()

    def check_tcp_at_home(self):
        """홈 관절에서 읽힌 TCP 좌표가 등록된 값과 다르면 DART 의 TCP 선택이 풀린 것 → 이후 좌표가 전부 어긋나므로 중단."""
        p = self.posx_now()
        dx, dy, dz = p[0] - HOME_TCP_XY[0], p[1] - HOME_TCP_XY[1], p[2] - 105.4
        self.log.info(f"Home TCP = ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}); expected ({HOME_TCP_XY[0]}, {HOME_TCP_XY[1]}, 105.4)")
        if abs(dx) > HOME_TCP_TOL or abs(dy) > HOME_TCP_TOL or abs(dz) > HOME_TCP_TOL:
            raise MotionFailed(f"TCP mismatch at home: off by ({dx:+.1f}, {dy:+.1f}, {dz:+.1f}) mm. "
                               f"DART 툴 설정에서 TCP 'GripperDA_v3' 이 선택돼 있는지 확인 (브링업/제어기 재시작 후 풀릴 수 있음)")

    # ---- 충돌 감지 민감도 (제어기 자체 기능: 툴이든 손목이든 어디가 닿아도 보호정지) ----
    def set_collision_sensitivity(self, percent):
        try:
            ret = self.R.change_collision_sensitivity(int(percent))
            self.log.info(f"Collision sensitivity → {percent}% (ret={ret})")
        except Exception as e:
            self.log.warn(f"collision sensitivity not set: {e}")

    # ---- 힘 ----
    def force_z(self):
        f = self.R.get_tool_force(self.R.DR_BASE)
        try:
            return float(f[2])
        except Exception:
            return float("nan")

    def force_baseline(self, n=10, dt=0.1):
        v = []
        for _ in range(n):
            f = self.force_z()
            if f == f:
                v.append(f)
            time.sleep(dt)
        return sum(v) / len(v) if v else 0.0

    def force_vec(self):
        f = self.R.get_tool_force(self.R.DR_BASE)
        try:
            return [float(f[0]), float(f[1]), float(f[2])]
        except Exception:
            return [float("nan")] * 3

    def probe_along(self, d, threshold_n, max_travel, speed_mm_s=0.8, hard_limit_n=6.0, label="probe",
                    fast_mm=0.0, fast_speed=3.0, settle_mm=3.0, settle_s=2.0, soft_n=None, soft_samples=2):
        """base 방향 단위벡터 d 로 저속 직선 이동(비동기)하며, 이동 방향의 반력(f = -F·d) 급증을 접촉으로 판정.
        위치 제어만 쓴다 (툴 무게 미보정으로 순응/힘 모드는 위로 밀림, 9/17).
        접촉 판정 (출발 후 settle_s·settle_mm 이후에만): 1.5 s 이동평균 대비 급증 ≥ threshold_n 이 연속 2 샘플,
                   또는 이동 중 기준(정착 시점의 힘) 대비 |Δm| ≥ hard_limit_n.
        9/17 bag 1559: 이동 편향(+2.5~4 N) 때문에 출발 전 기준 대비 Δf 가 hard_limit 4.5 를 넘어 거짓 접촉이 8회
        → 기준을 정착 시점에 다시 잡는다. 정착 전에는 2×hard_limit 만 비상 기준. 반환: dict(contact, pos, z, delta, travelled)"""
        R = self.R
        start = self.posx_now()
        n = math.sqrt(sum(v * v for v in d)); d = [v / n for v in d]
        def along(mm):
            return self.posx(start[0] + d[0] * mm, start[1] + d[1] * mm, start[2] + d[2] * mm, start[3], start[4], start[5])
        def travelled_of(cur):
            return sum((cur[k] - start[k]) * d[k] for k in range(3))
        def f_of(vec):
            return -(vec[0] * d[0] + vec[1] * d[1] + vec[2] * d[2])    # 이동 방향으로 눌리는 반력 (+)
        base = [f_of(self.force_vec()) for _ in range(8)]
        base = [v for v in base if v == v]
        f0 = sum(base) / len(base) if base else 0.0
        result = dict(contact=False, pos=start, z=start[2], delta=0.0, travelled=0.0, onset=None, onset_pos=None)
        trace = []                       # (travelled, Δm) 전체 기록: 접촉 판정 뒤 힘이 오르기 시작한 지점(onset) 역산용
        self.log.info(f"[{label}] probe along ({d[0]:.2f},{d[1]:.2f},{d[2]:.2f}) {max_travel:.0f} mm at {speed_mm_s} mm/s"
                      + (f" (first {fast_mm:.0f} mm at {fast_speed})" if fast_mm > 0 else "")
                      + f"; step ≥ {threshold_n} N or |Δf| ≥ {hard_limit_n} N (baseline {f0:.2f})")
        # 직전 비동기 이동이 자연 종료된 직후 바로 amovel 을 보내면 제어기가 무시하는 경우가 있었다
        # (9/17 bag 1502: +x push 60 s 동안 0 mm). 길이 0 의 동기 이동으로 대기 상태를 확정한 뒤 시작한다.
        try:
            R.mwait()
        except Exception:
            pass
        self.mv(R.movel, along(0.0), vel=[5.0, 5.0], acc=[5.0, 5.0], ref=0, mod=R.DR_MV_MOD_ABS)
        R.set_ref_coord(R.DR_BASE)      # 이동 중 호출하면 제어기가 거부(1903)하므로 정지 확정 후
        target = along(max_travel)
        fast_mm = max(0.0, min(fast_mm, max_travel - 5.0))
        phase = "fast" if fast_mm > 0 else "slow"
        first = along(fast_mm) if fast_mm > 0 else target
        v0 = fast_speed if fast_mm > 0 else speed_mm_s
        def issue():
            ret = R.amovel(first, vel=[v0, v0], acc=[max(1.0, v0), max(1.0, v0)], ref=0, mod=R.DR_MV_MOD_ABS)
            if ret != 0:
                raise MotionFailed(f"[{label}] amovel returned {ret}: cannot start probe move")
        issue()
        t0 = time.time(); t_log = t0
        hist = []; step_run = 0; soft_run = 0; reissued = False; f_move = None
        timeout_s = fast_mm / max(fast_speed, 0.1) + (max_travel - fast_mm) / speed_mm_s + 30.0
        try:
            while time.time() - t0 < timeout_s:
                now = time.time()
                cur = self.posx_now()
                tr = travelled_of(cur)
                f = f_of(self.force_vec())
                if f != f:
                    f = hist[-1][2] if hist else f0
                hist.append((now, tr, f))
                if f_move is not None:
                    trace.append((tr, f - f_move))
                hist = [h for h in hist if now - h[0] <= 2.0]
                delta = f - f0
                # 이동평균에는 출발 편향이 오르는 첫 1 s 의 샘플을 넣지 않는다 (9/17 bag 1608: 6 mm/s 에서 정착 1.2 s
                # 직후 평균이 아직 낮아 step +1.9 거짓 접촉). 유효 샘플 3개 미만이면 step 판정 보류.
                avg = [h[2] for h in hist if 0.3 <= now - h[0] <= 1.8 and h[0] - t0 >= 1.0]
                step = f - (sum(avg) / len(avg)) if len(avg) >= 3 else 0.0
                dm = (f - f_move) if f_move is not None else 0.0
                if now - t_log >= 0.5:
                    self.log.info(f"[{label}]   travelled={tr:.2f} f={f:.2f} Δf={delta:+.2f} Δm={dm:+.2f} step={step:+.2f}")
                    t_log = now
                if tr < -1.0:
                    raise MotionFailed(f"[{label}] moved backwards {-tr:.1f} mm; aborting")
                if now - t0 > 3.0 and tr < 0.3:
                    if not reissued:
                        reissued = True
                        self.log.warn(f"[{label}] no motion after 3 s; re-issuing move command")
                        self.stop(); time.sleep(0.3); issue(); t0 = time.time()
                    else:
                        raise MotionFailed(f"[{label}] robot does not move on probe command (twice); check TP state")
                settled = (now - t0 >= settle_s and tr >= settle_mm)
                if settled and f_move is None:
                    recent = [h[2] for h in hist if now - h[0] <= 0.5]
                    f_move = sum(recent) / len(recent)
                    dm = f - f_move
                step_run = step_run + 1 if (settled and step >= threshold_n) else 0
                hard = (settled and abs(dm) >= hard_limit_n) or (tr >= 1.0 and abs(delta) >= 2.0 * hard_limit_n)
                soft_run = soft_run + 1 if (soft_n is not None and settled and dm >= soft_n) else 0   # 완만한 상승(무른 재료)
                soft = soft_run >= soft_samples          # 연속 샘플 수 (기본 2, 뾰족한 송곳 표면 찾기는 1: 판정 지연 = 깊이)
                if step_run >= 2 or hard or soft:
                    self.stop()
                    result.update(contact=True, pos=cur, z=cur[2], delta=delta, travelled=tr)
                    # 힘이 오르기 시작한 지점: 끝에서 거슬러 Δm ≥ ONSET_N 이 이어지는 구간의 첫 샘플. 무른 지점토는 판정
                    # 전에 몇 mm 파고들므로(9/17 bag 1619: -Y 13 mm) 변의 위치는 이 값으로 잡는다.
                    k = len(trace) - 1
                    while k > 0 and trace[k - 1][1] >= ONSET_N:
                        k -= 1
                    on_tr = trace[k][0] if trace else tr
                    on_tr = max(0.0, min(on_tr, tr))
                    op = along(on_tr)
                    result.update(onset=on_tr, onset_pos=op)
                    self.log.info(f"[{label}] contact by " + ("force STEP" if step_run >= 2 else "hard limit" if hard else "soft rise") +
                                  f" (step {step:+.2f}, Δm {dm:+.2f}, Δf {delta:+.2f}) at ({cur[0]:.1f},{cur[1]:.1f},{cur[2]:.1f})"
                                  f"; force onset at travelled {on_tr:.1f} → ({op[0]:.1f},{op[1]:.1f},{op[2]:.1f})")
                    break
                if phase == "fast" and tr >= fast_mm - 0.3:
                    phase = "slow"
                    ret = R.amovel(target, vel=[speed_mm_s, speed_mm_s], acc=[1.0, 1.0], ref=0, mod=R.DR_MV_MOD_ABS)
                    if ret != 0:
                        raise MotionFailed(f"[{label}] amovel (slow) returned {ret}")
                if tr >= max_travel - 0.3:
                    result.update(pos=cur, z=cur[2], travelled=tr)
                    break
                time.sleep(0.05)
            else:
                self.stop()
                self.log.warn(f"[{label}] timeout")
        finally:
            try:
                R.mwait()
            except Exception:
                pass
        self.log.info(f"[{label}] contact={result['contact']} travelled={result['travelled']:.1f} z={result['z']:.1f} "
                      f"Δf={result['delta']:+.2f} N")
        return result

    def probe_down(self, threshold_n, max_travel, speed_mm_s=0.8, label="probe", fast_mm=0.0, fast_speed=3.0,
                   vertical=False, **kw):
        """내려가며 접촉을 찾는다. vertical=False 면 툴 -Y 방향(손끝/송곳 축), True 면 base -Z (툴을 기울여
        모서리 한 점으로 찍을 때). 반환에 descended 도 넣는다."""
        if vertical:
            d = [0.0, 0.0, -1.0]
        else:
            p = self.posx_now()
            ty = tool_y_axis(p[3], p[4], p[5])
            d = [-ty[0], -ty[1], -ty[2]]
        r = self.probe_along(d, threshold_n, max_travel, speed_mm_s=speed_mm_s, label=label,
                             fast_mm=fast_mm, fast_speed=fast_speed, **kw)
        r["descended"] = r["travelled"]
        return r


# ---- 그리퍼 (RG2, WebLogic 프리셋을 제어기 DO 로 호출) ----
# 9/17 확인: 실물 브링업에서 OnRobot ROS 드라이버 서비스(/onrobot/sendCommand)는 뜨지 않는다. DO 만 쓴다.
# DO1 = 닫기 프리셋, DO2 = 열기 프리셋. 폭 지정(예: 55 mm) 은 WebLogic 에 프리셋을 추가하고 그 DO 번호를
# GRIPPER_HALF_DO 에 적으면 된다 (None 이면 반 열기 요청 시 완전 열기로 대체).
GRIPPER_CLOSE_DO = 1
GRIPPER_OPEN_DO = 2
GRIPPER_HALF_DO = None
GRIPPER_SETTLE_S = 1.5           # 명령 후 그리퍼가 움직일 시간


class Gripper:
    def __init__(self, node, robot):
        self.log = node.get_logger()
        self.robot = robot
        self.log.info(f"Gripper via digital outputs (DO{GRIPPER_CLOSE_DO} close / DO{GRIPPER_OPEN_DO} open"
                      + (f" / DO{GRIPPER_HALF_DO} half" if GRIPPER_HALF_DO else ", no half-open preset") + ")")

    def _pulse(self, on_do):
        """지정 DO 만 켜고 나머지 그리퍼 DO 는 끈다 (프리셋끼리 충돌 방지)."""
        R = self.robot.R
        for d in (GRIPPER_CLOSE_DO, GRIPPER_OPEN_DO, GRIPPER_HALF_DO):
            if d and d != on_do:
                R.set_digital_output(d, 0)
        R.set_digital_output(on_do, 1)
        time.sleep(GRIPPER_SETTLE_S)

    def close(self):
        self.log.info("Gripper close")
        self._pulse(GRIPPER_CLOSE_DO)

    def open(self):
        self.log.info("Gripper open")
        self._pulse(GRIPPER_OPEN_DO)

    def half_open(self):
        if GRIPPER_HALF_DO:
            self.log.info("Gripper half open (preset)")
            self._pulse(GRIPPER_HALF_DO)
        else:
            self.log.info("Gripper half open requested → no preset, opening fully")
            self._pulse(GRIPPER_OPEN_DO)


# ---- 통신 ----
import os
STATE_FILE = os.path.expanduser("~/collaborative/ws_cobot_pjt/ws_dsr/clay_state.json")   # 노드가 종료돼도 남는 상태


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"stage": "", "data": {}}


def _save_state(stage=None, data=None):
    st = _load_state()
    if stage is not None:
        st["stage"] = stage
    if data is not None:
        st["data"] = data
    st["time"] = time.time()
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, ensure_ascii=False)


class Bus:
    """단계·데이터를 latched 토픽으로 주고받되, 발행 노드가 종료되면 토픽이 사라지므로 파일(STATE_FILE)에도 남긴다.
    늦게 켠 노드는 파일에서 마지막 단계·데이터를 읽는다 (9/17: clay_scan 종료 후 /clay/data 소실 확인)."""

    def __init__(self, node):
        self.node = node
        self.stage_pub = node.create_publisher(String, STAGE_TOPIC, LATCHED)
        self.data_pub = node.create_publisher(String, DATA_TOPIC, LATCHED)
        self.data = _load_state().get("data", {})
        self._got_data = bool(self.data)
        node.create_subscription(String, DATA_TOPIC, self._on_data, LATCHED)

    def _on_data(self, msg):
        try:
            self.data = json.loads(msg.data)
            self._got_data = True
        except Exception:
            pass

    def ask_yes_no(self, qid, text, log=None):
        """y/n 질문. 대시보드(/clay/prompt → /clay/answer)와 터미널 입력 중 먼저 오는 답을 쓴다."""
        import select, sys
        got = {}
        def cb(msg):
            try:
                d = json.loads(msg.data)
            except Exception:
                return
            if d.get("id") == qid and d.get("answer") in ("y", "n"):
                got["a"] = d["answer"]
        sub = self.node.create_subscription(String, ANSWER_TOPIC, cb, 10)
        pub = self.node.create_publisher(String, PROMPT_TOPIC, LATCHED)
        pub.publish(String(data=json.dumps({"id": qid, "text": text}, ensure_ascii=False)))
        print(f"{text} (y/n): ", end="", flush=True)
        while "a" not in got:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            r, _, _ = select.select([sys.stdin], [], [], 0.0)
            if r:
                a = sys.stdin.readline().strip().lower()
                if a in ("y", "n"):
                    got["a"] = a
                else:
                    print(f"{text} (y/n): ", end="", flush=True)
        pub.publish(String(data=json.dumps({"id": qid, "text": ""})))     # 질문 닫힘
        self.node.destroy_subscription(sub); self.node.destroy_publisher(pub)
        if log:
            log.info(f"{text} → {got['a']}")
        return got["a"] == "y"

    def publish_stage(self, stage):
        self.stage_pub.publish(String(data=stage))
        _save_state(stage=stage)
        self.node.get_logger().info(f"stage → {stage}")

    def update_data(self, **kw):
        rclpy.spin_once(self.node, timeout_sec=0.2)
        self.data.update(kw)
        self.data_pub.publish(String(data=json.dumps(self.data)))
        _save_state(data=self.data)

    def wait_stage(self, wanted, on_empty_topic=None, also=()):
        """원하는 stage 문자열이 올 때까지 대기. on_empty_topic 이 있으면 그 Empty 토픽도 트리거.
        also: 같이 통과로 볼 stage 들 (예: 4번 노드는 draw_done 상태에서도 다시 그린다)."""
        accept = {wanted, *also}
        got = {"ok": False}
        def cb(msg):
            if msg.data in accept:
                got["ok"] = True
        sub = self.node.create_subscription(String, STAGE_TOPIC, cb, LATCHED)
        sub2 = None
        if on_empty_topic:
            def cb2(_):
                got["ok"] = True
            sub2 = self.node.create_subscription(Empty, on_empty_topic, cb2, 10)
        st = _load_state()
        if st.get("stage") in accept and time.time() - st.get("time", 0) < 3600:
            self.node.get_logger().info(f"Stage '{wanted}' already reached (from state file); proceeding")
            got["ok"] = True
        else:
            self.node.get_logger().info(f"Waiting for stage '{wanted}'" + (f" or {on_empty_topic}" if on_empty_topic else "") + " ...")
        while rclpy.ok() and not got["ok"]:
            rclpy.spin_once(self.node, timeout_sec=0.2)
        self.node.destroy_subscription(sub)
        if sub2:
            self.node.destroy_subscription(sub2)
        # 최신 data 수신 (토픽이 없으면 파일에서)
        for _ in range(5):
            rclpy.spin_once(self.node, timeout_sec=0.1)
        if not self.data:
            self.data = _load_state().get("data", {})
        return self.data


def zyz_to_matrix(A, B, C):
    """DSR posx 자세각(ZYZ 오일러, deg) → 3x3 회전행렬 (열 = 툴 X,Y,Z 축의 base 방향)."""
    a, b, c = (math.radians(v) for v in (A, B, C))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb * cc - sa * sc, -ca * cb * sc - sa * cc, ca * sb],
            [sa * cb * cc + ca * sc, -sa * cb * sc + ca * cc, sa * sb],
            [-sb * cc, sb * sc, cb]]


def matrix_to_zyz(R):
    """3x3 회전행렬 → ZYZ 오일러 (deg)."""
    cb = max(-1.0, min(1.0, R[2][2]))
    b = math.acos(cb)
    if abs(math.sin(b)) < 1e-6:
        a = math.atan2(R[1][0], R[0][0]); c = 0.0
    else:
        a = math.atan2(R[1][2], R[0][2]); c = math.atan2(R[2][1], -R[2][0])
    return math.degrees(a), math.degrees(b), math.degrees(c)


def rotate_about_tool_axis(A, B, C, axis, deg):
    """현재 자세를 툴 자신의 축(axis: 'x'|'y'|'z') 둘레로 deg 만큼 돌린 새 자세각."""
    R = zyz_to_matrix(A, B, C)
    t = math.radians(deg); ct, st = math.cos(t), math.sin(t)
    if axis == "x":
        Rl = [[1, 0, 0], [0, ct, -st], [0, st, ct]]
    elif axis == "y":
        Rl = [[ct, 0, st], [0, 1, 0], [-st, 0, ct]]
    else:
        Rl = [[ct, -st, 0], [st, ct, 0], [0, 0, 1]]
    Rn = [[sum(R[i][k] * Rl[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return matrix_to_zyz(Rn)


def tool_y_axis(A, B, C):
    """ZYZ 오일러(deg) → 툴 +Y 축의 base 방향 벡터."""
    A, B, C = (math.radians(v) for v in (A, B, C))
    cy = (-math.sin(C), math.cos(C), 0.0)
    ry = (cy[0] * math.cos(B), cy[1], -cy[0] * math.sin(B))
    return (ry[0] * math.cos(A) - ry[1] * math.sin(A), ry[0] * math.sin(A) + ry[1] * math.cos(A), ry[2])
