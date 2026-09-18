# 양초 둘레 360° 물결무늬. 그리퍼 수직, 도구가 항상 축을 향하도록 base Z 둘레로 자세를 돌리며 돈다.
# 1) 지금 자리(-Y 면, 물러난 상태)에서 반경 방향으로 여유 반지름까지 나감  2) 4각(-90,0,90,180°)에서 힘 터치 → 도구 끝 좌표로 원 맞춤
# 3) 그 원 위에서 z 물결(진폭 AMP, 주기 K)을 한 바퀴+겹침 긋기  4) 반경 방향 이탈
import rclpy, math, sys, json
from clay_carving.clay_common import Robot, MotionFailed, DRAW_VEL, DRAW_ACC, tool_y_axis
from clay_carving.clay_scan2 import LIFT_VEL, COLLISION_SENS_SCAN, COLLISION_SENS_DEFAULT
STAGE = sys.argv[1] if len(sys.argv) > 1 else "all"
CX, CY, ZTOP, R = 422.4, -2.6, 204.0, 34.0
OX, OY = -2.5, -63.3                 # 드릴 끝 = 패드 + OX·툴X + OY·툴Y (9/18 -Y 면 3점 측정)
Z_C, AMP, K = 150.0, 10.0, 6      # 물결 중심 z 150 (지금 159 보다 9 아래), 진폭 10 → 높낮이 차 20 mm, 6주기
CLEAR = 25.0                         # 여유 반지름: 도구 끝이 표면에서 이만큼 바깥
TOUCH_N, HARD_N, SOFT_N = 1.5, 4.5, 0.8
TOUCH_ANGLES = (-90.0, 0.0, 90.0, 180.0)
import os
STATE = os.path.expanduser("~/collaborative/ws_cobot_pjt/ws_dsr/orbit_state.json")
J6_LIMIT = 350.0                     # J6 허용 범위(±360) 안쪽 여유. 9/18: J6 -195 에서 A +270 돌려 한계 초과 → 손목 뒤집힘 → 비상정지
FIT_TOL = 1.0                        # 4점 원 맞춤 잔차 허용 [mm]. 넘으면 물결로 안 넘어간다
rclpy.init(); node = rclpy.create_node("clay_orbit_wave", namespace="dsr01"); log = node.get_logger()
rb = Robot(node, "clay_orbit_wave")
p0 = rb.posx_now(); A0, B0, C0 = p0[3], p0[4], p0[5]
assert abs(-math.cos(math.radians(B0)) - 1.0) < 0.02, "그리퍼가 세워져 있지 않음"
ty0 = tool_y_axis(A0, B0, C0)
TH0 = math.degrees(math.atan2(ty0[1], ty0[0]))          # 지금 툴 Y(바깥 법선) 각
log.info(f"start (A,B,C)=({A0:.1f},{B0:.1f},{C0:.1f}) toolY angle {TH0:.1f}° (expect -90)")
def n_of(th): t = math.radians(th); return (math.cos(t), math.sin(t))
def tx_of(th): t = math.radians(th); return (-math.sin(t), math.cos(t))
def A_of(th): return A0 + (th - TH0)
def pose_tip(tip_xy, z, th):
    """도구 끝을 tip_xy 에 두는 posx (툴 Y 가 각 th 를 향함). 패드 = 끝 - OX·툴X - OY·툴Y, TCP = 패드 - 60·툴Y"""
    n, tx = n_of(th), tx_of(th)
    padx = tip_xy[0] - OX * tx[0] - OY * n[0]; pady = tip_xy[1] - OX * tx[1] - OY * n[1]
    return rb.posx(padx - 60.0 * n[0], pady - 60.0 * n[1], z, A_of(th), B0, C0)
def tip_now(th):
    p = rb.posx_now(); n, tx = n_of(th), tx_of(th)
    padx, pady = p[0] + 60.0 * n[0], p[1] + 60.0 * n[1]
    return (padx + OX * tx[0] + OY * n[0], pady + OX * tx[1] + OY * n[1], p[2])
def tip_at(c, th, r, z): n = n_of(th); return ((c[0] + r * n[0], c[1] + r * n[1]), z)
def arc_to(c, th_from, th_to, r, z, step=15.0):
    k = int(abs(th_to - th_from) / step + 0.999)
    for i in range(1, k + 1):
        th = th_from + (th_to - th_from) * i / k
        (xy, zz) = tip_at(c, th, r, z)
        rb.movel(pose_tip(xy, zz, th), vel=[30.0, 30.0], acc=[30.0, 30.0])
st = {}
try:
    try: st = json.load(open(STATE))
    except Exception: pass
    rb.set_collision_sensitivity(COLLISION_SENS_SCAN)
    if STAGE == "unwind":
        # 홈(손끝이 양초 중심 위 30 mm) 에서만 쓸 것: TCP 고정 회전이라 도구 끝이 반지름 ~120 mm 원을 그린다 (윗면보다 위여야 함)
        q = rb.R.get_current_posj(); j6 = q[5]
        p = rb.posx_now()
        assert p[2] >= ZTOP + 25.0, f"unwind 는 윗면 위에서만 (지금 z {p[2]:.0f})"
        rb.movel(rb.posx(p[0], p[1], p[2], p[3] + 10.0, p[4], p[5]), vel=[20.0, 15.0], acc=[20.0, 10.0])
        slope = (rb.R.get_current_posj()[5] - j6) / 10.0
        dA = -j6 / slope                                       # J6 → 0 이 되는 A 변화량
        log.info(f"unwind: J6 {j6:.0f}° → 0 으로 A {dA:+.0f}° 회전 (slope {slope:+.2f})")
        steps = int(abs(dA) / 90.0) + 1
        for k in range(1, steps + 1):
            rb.movel(rb.posx(p[0], p[1], p[2], p[3] + 10.0 + dA * k / steps, p[4], p[5]), vel=[20.0, 20.0], acc=[20.0, 15.0])
        log.info(f"unwind done: J6 now {rb.R.get_current_posj()[5]:.0f}°, (A,B,C)={[round(v,1) for v in rb.posx_now()[3:]]}")
    if STAGE in ("touch", "all"):
        c = (CX, CY)
        # 회전 방향: J6 가 0 쪽으로 가는 방향 (+10° 시험 회전으로 판별)
        q = rb.R.get_current_posj(); j6a = q[5]
        rb.movel(rb.posx(p0[0], p0[1], p0[2], A0 + 10.0, B0, C0), vel=[20.0, 15.0], acc=[20.0, 10.0])
        q = rb.R.get_current_posj(); j6b = q[5]
        rb.movel(rb.posx(p0[0], p0[1], p0[2], A0, B0, C0), vel=[20.0, 15.0], acc=[20.0, 10.0])
        slope = (j6b - j6a) / 10.0                    # A 가 +1° 돌 때 J6 변화 (≈ ±1)
        DIR = 1.0 if (slope * j6a) < 0 else -1.0      # A 를 이 방향으로 돌리면 J6 가 0 쪽으로 간다
        # 전체 회전량: 터치 4각 = 270° 갔다가 되돌아옴(왕복), 물결 = 368° 한 방향. J6 최대 이탈 = 시작 ± 368°
        j6_far = j6a + slope * DIR * (360.0 + 8.0)
        log.info(f"J6 {j6a:.1f} → A+10 → {j6b:.1f} (slope {slope:+.2f}): orbit direction {DIR:+.0f} (A {'증가' if DIR > 0 else '감소'}), "
                 f"J6 during wave {j6a:.0f} → {j6_far:.0f}")
        if abs(j6_far) > J6_LIMIT or abs(j6a - slope * DIR * 270.0) > J6_LIMIT:
            raise MotionFailed(f"J6 범위 초과 예상 (지금 {j6a:.0f}°, 물결 끝 {j6_far:.0f}°, 터치 왕복 {j6a - slope * DIR * 270.0:.0f}°). "
                               f"홈(양초 위)에서 손목을 먼저 풀고 다시 시작 (unwind 단계)")
        # 여유 반지름으로 나가기 (지금 -Y 면 근처)
        (xy, z) = tip_at(c, TH0, R + CLEAR, Z_C)
        rb.movel(pose_tip(xy, z, TH0), vel=LIFT_VEL, acc=[10.0, 10.0])
        tips = []
        th = TH0
        for i in range(len(TOUCH_ANGLES)):
            ang = TH0 + DIR * 90.0 * i                   # TH0 에서 DIR 방향으로 90° 씩 (9/18 버그: 나머지 연산으로 방향이 뒤집혔음)
            target = ang
            if i > 0:
                arc_to(c, th, target, R + CLEAR, Z_C)
            th = target
            n = n_of(th)
            # 접촉 판정: 정착(8 mm/3 s) 후 급증 1.5 N×2 또는 |Δm| ≥ 2.5 N. 완만 상승(soft) 은 끔 — 회전 뒤 이동 방향 반력이
            # 2~3 N 씩 천천히 오르는 드리프트가 있어 표면 4~10 mm 전에 거짓 접촉 (9/18 0°·90° 터치)
            r = rb.probe_along([-n[0], -n[1], 0.0], TOUCH_N, CLEAR + 10.0, speed_mm_s=2.0, label=f"touch@{ang:+.0f}",
                               settle_mm=8.0, settle_s=3.0, hard_limit_n=2.5, soft_n=None)
            if not r["contact"]:
                raise MotionFailed(f"touch@{ang:+.0f}: {CLEAR + 10:.0f} mm 가도 안 닿음")
            op = r.get("onset_pos") or r["pos"]
            padx, pady = op[0] + 60.0 * n[0], op[1] + 60.0 * n[1]
            tx = tx_of(th)
            tip = (padx + OX * tx[0] + OY * n[0], pady + OX * tx[1] + OY * n[1])
            tips.append((th, tip[0], tip[1]))
            log.info(f"TOUCH @{ang:+.0f}° (th {th:.0f}): tip ({tip[0]:.1f}, {tip[1]:.1f}) force {abs(r['delta']):.2f} N, "
                     f"radial from ({CX},{CY}) = {math.hypot(tip[0] - CX, tip[1] - CY):.1f}")
            (xy, z) = tip_at(c, th, R + CLEAR, Z_C)
            rb.movel(pose_tip(xy, z, th), vel=LIFT_VEL, acc=[10.0, 10.0])
        # 원 맞춤 (대수적 최소제곱): 4점 → 중심·반지름
        import numpy as np
        P = np.array([[x, y] for (_, x, y) in tips]); Amat = np.c_[2 * P, np.ones(len(P))]; b = (P ** 2).sum(1)
        sol, *_ = np.linalg.lstsq(Amat, b, rcond=None); cxf, cyf = sol[0], sol[1]; rf = math.sqrt(sol[2] + cxf ** 2 + cyf ** 2)
        res = [math.hypot(x - cxf, y - cyf) - rf for (_, x, y) in tips]
        # 시작각으로 되돌아가기 (같은 길로 역회전 → J6 원위치)
        arc_to(c, th, TH0, R + CLEAR, Z_C); th = TH0
        st = dict(cx=cxf, cy=cyf, r=rf, dir=DIR, th_end=th, tips=tips, res=res, z_c=Z_C, fit_ok=bool(max(abs(v) for v in res) <= FIT_TOL and abs(rf - R) <= 3.0))
        json.dump(st, open(STATE, "w"))
        log.info(f"FIT: axis ({cxf:.1f}, {cyf:.1f}) R_eff {rf:.1f} (기준 ({CX},{CY}) R {R}); residuals {[round(v, 2) for v in res]} mm; fit_ok={st['fit_ok']}")
        if not st["fit_ok"]:
            raise MotionFailed("원 맞춤 잔차가 크거나 반지름이 어긋남 → 거짓 접촉 의심. 물결로 넘어가지 않음")
    if STAGE in ("wave", "all"):
        c, rf, DIR, th = (st["cx"], st["cy"]), st["r"], st["dir"], st["th_end"]
        # 시작각으로 (여유 반지름에서), 물결 시작점 z 로
        th_s = th
        (xy, z) = tip_at(c, th_s, rf + CLEAR, Z_C)
        rb.movel(pose_tip(xy, z, th_s), vel=LIFT_VEL, acc=[10.0, 10.0])
        # 접근: 표면 6 mm 밖까지 이동 후 힘 터치 (1.5 mm/s) → 실제 접촉 반지름
        (xy, z) = tip_at(c, th_s, rf + 6.0, Z_C)
        rb.movel(pose_tip(xy, z, th_s), vel=LIFT_VEL, acc=[10.0, 10.0])
        n = n_of(th_s)
        r = rb.probe_along([-n[0], -n[1], 0.0], TOUCH_N, 12.0, speed_mm_s=1.5, label="wave touch", settle_mm=2.0, settle_s=1.2,
                           hard_limit_n=2.5, soft_n=None)
        if not r["contact"]:
            raise MotionFailed("wave touch: 12 mm 가도 안 닿음")
        t = tip_now(th_s); r_draw = math.hypot(t[0] - c[0], t[1] - c[1])
        log.info(f"wave touch: contact radius {r_draw:.2f} (fit {rf:.2f}), force {abs(r['delta']):.2f} N")
        pts = []
        total = 360.0 + 8.0                                  # 한 바퀴 + 8° 겹침
        step = 3.0
        nseg = int(total / step)
        for i in range(0, nseg + 1):
            d = i * step
            thi = th_s + DIR * d
            zi = Z_C + AMP * math.sin(math.radians(K * d))
            (xy, _) = tip_at(c, thi, r_draw, zi)
            pts.append(pose_tip(xy, zi, thi))
        log.info(f"wave: {len(pts)} pts, {total:.0f}°, z {Z_C:.1f}±{AMP:.0f}, {K} periods, radius {r_draw:.1f}")
        CH = 62
        for k in range(0, len(pts), CH):
            chunk = pts[k:k + CH]
            if k > 0: chunk = [pts[k - 1]] + chunk
            rb.movesx(chunk, vel=DRAW_VEL, acc=DRAW_ACC)
        th_e = th_s + DIR * total
        (xy, z) = tip_at(c, th_e, r_draw + 15.0, pts[-1][2]); rb.movel(pose_tip(xy, z, th_e), vel=LIFT_VEL, acc=[10.0, 10.0])
        (xy, z) = tip_at(c, th_e, rf + CLEAR, Z_C); rb.movel(pose_tip(xy, z, th_e), vel=LIFT_VEL, acc=[10.0, 10.0])
        st["th_end"] = th_e; json.dump(st, open(STATE, "w"))
        log.info("wave done, retracted to clearance radius")
finally:
    rb.set_collision_sensitivity(COLLISION_SENS_DEFAULT)
    node.destroy_node(); rclpy.shutdown()
