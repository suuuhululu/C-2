# 양초 옆면(+Y 면)에 송곳으로 하트 긋기. 그리퍼 수직(세운 자세), 송곳은 패드에서 base -Y 로 수평으로 나와 있다고 본다.
# 단계: close(그리퍼 닫기) → measure(옆면 3점 터치로 송곳 끝 기준 원 맞춤) → draw(하트 한 획, 획 시작에서 힘 터치 후 곡률 따라 긋기)
import rclpy, math, sys, json, time
from clay_carving.clay_common import Robot, Gripper, MotionFailed, DRAW_VEL, DRAW_ACC, tool_y_axis
TOUCH_SOFT_N, TOUCH_SPEED = 0.8, 1.5
from clay_carving.clay_scan2 import HOVER_VEL, LIFT_VEL, COLLISION_SENS_SCAN, COLLISION_SENS_DEFAULT
STAGE = sys.argv[1] if len(sys.argv) > 1 else "all"
CX, CY, ZTOP, R = 422.4, -2.6, 204.0, 34.0
def _opt(name, default):
    return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
Z_C = ZTOP - _opt("--depth", 45.0)    # 하트 중심 높이 = 윗면 아래 --depth mm (기본 45; 그리퍼 몸체가 윗면 위에 있게)
HEART_W_OPT = _opt("--width", 24.0)
HEART_W = HEART_W_OPT                # 하트 폭 [mm] (--width)
AWL_MAX, CLEAR = 110.0, 15.0
TOUCH_N, HARD_N = 1.5, 4.5
import os
STATE = os.path.expanduser("~/collaborative/ws_cobot_pjt/ws_dsr/side_heart_state.json")
if "--tag" in sys.argv: STATE = STATE.replace(".json", "_" + sys.argv[sys.argv.index("--tag") + 1] + ".json")
rclpy.init(); node = rclpy.create_node("clay_side_heart", namespace="dsr01"); log = node.get_logger()
rb = Robot(node, "clay_side_heart"); gr = Gripper(node, rb)
def orient():
    """지금 자세 → (A,B,C), 패드 오프셋, SIDE. 패드 = TCP + 60·툴Y. 도구 끝은 툴 -Y 로 나가므로 그리는 면의 바깥 법선 = +툴Y.
    SIDE=+1: 툴Y=+Y → +Y 면에 그림(접근 -Y). SIDE=-1: 180° 돌린 자세 → -Y 면(접근 +Y)."""
    p = rb.posx_now(); A, B, C = p[3], p[4], p[5]
    assert abs(-math.cos(math.radians(B)) - 1.0) < 0.02, "그리퍼가 세워져 있지 않음"
    ty = tool_y_axis(A, B, C)
    assert abs(ty[1]) > 0.98, f"툴 Y 가 base ±Y 가 아님 {ty}"
    return (A, B, C), (60.0 * ty[0], 60.0 * ty[1]), (1.0 if ty[1] > 0 else -1.0)
(A, B, C), PAD, SIDE = orient()
log.info(f"orientation (A,B,C)=({A:.1f},{B:.1f},{C:.1f}) pad offset ({PAD[0]:.1f},{PAD[1]:.1f}) SIDE={SIDE:+.0f} → {'+' if SIDE > 0 else '-'}Y 면")
def at(px, py, z): return rb.posx(px - PAD[0], py - PAD[1], z, A, B, C)
def pad_now():
    p = rb.posx_now(); return (p[0] + PAD[0], p[1] + PAD[1], p[2])
def surf_y(u, cx_fit, yoff):         # 송곳 끝 기준 원: 패드 x=u 일 때 닿는 패드 y (SIDE 쪽 면)
    return yoff + SIDE * math.sqrt(max(0.0, R * R - (u - cx_fit) ** 2))
def touch_minus_y(label, max_travel, speed, first=False):
    # 첫 접근(긴 거리, 4 mm/s): 출발 직후 이동 방향 반력이 ~2 N 올라가 평탄해지는 드리프트가 있어(9/18 -Y 면, 드릴)
    # 완만 상승 판정을 끄고 급증(1.5 N)만 쓰며 정착 구간을 길게 잡는다. 짧은 터치는 종전대로.
    if first:
        r = rb.probe_along([0.0, -SIDE, 0.0], TOUCH_N, max_travel, speed_mm_s=speed, label=label, settle_mm=10.0, settle_s=3.0,
                           hard_limit_n=HARD_N, soft_n=None)
    else:
        r = rb.probe_along([0.0, -SIDE, 0.0], TOUCH_N, max_travel, speed_mm_s=speed, label=label, settle_mm=2.0, settle_s=1.2,
                           hard_limit_n=HARD_N, soft_n=TOUCH_SOFT_N, soft_samples=2)
    return r
st = {}
try:
    if STATE and STAGE != "close":
        try: st = json.load(open(STATE))
        except Exception: st = {}
    rb.set_collision_sensitivity(COLLISION_SENS_SCAN)
    if STAGE == "turn":
        # 제자리에서 수직축 둘레 180° 회전 (TCP 고정, 패드가 60 mm 반지름으로 돔). 90° 두 번.
        p = rb.posx_now()
        for k in (1, 2):
            rb.movel(rb.posx(p[0], p[1], p[2], p[3] + 90.0 * k, p[4], p[5]), vel=[20.0, 15.0], acc=[20.0, 10.0])
        (A, B, C), PAD, SIDE = orient()
        log.info(f"turned: (A,B,C)=({A:.1f},{B:.1f},{C:.1f}) SIDE={SIDE:+.0f}, pad now {tuple(round(v,1) for v in pad_now())}")
    if STAGE == "open":
        gr.open(); time.sleep(1.5); log.info("gripper opened")
    if STAGE in ("close", "all"):
        gr.close(); time.sleep(1.5); log.info("gripper closed (도구 쥠)")
    if STAGE in ("measure", "all"):
        # 홈(중심 위 30 mm)에서 +Y 로 나간 뒤 내려간다 (대각선으로 가면 송곳 끝이 윗모서리에 걸릴 수 있음)
        px, py, pz = pad_now()
        y_far = CY + SIDE * (R + AWL_MAX + CLEAR)
        rb.movel(at(px, y_far, pz), vel=HOVER_VEL, acc=[20.0, 20.0])
        rb.movel(at(CX, y_far, Z_C), vel=HOVER_VEL, acc=[20.0, 20.0])
        pts = []
        for i, u in enumerate((0.0, +15.0, -15.0)):
            if i == 0:
                travel, speed = AWL_MAX + CLEAR + 5.0, 4.0
            else:
                rb.movel(at(CX + u, pts[0][1] + SIDE * (12.0 - 3.5), Z_C), vel=LIFT_VEL, acc=[10.0, 10.0])   # 첫 접촉 y 보다 8.5 mm 바깥 (곡률로 3.5 더 안쪽)
                travel, speed = 25.0, 2.0
            r = touch_minus_y(f"touch u={u:+.0f}", travel, speed, first=(i == 0))
            if not r["contact"]:
                raise MotionFailed(f"touch u={u:+.0f}: {travel:.0f} mm 가도 안 닿음")
            op = r.get("onset_pos") or r["pos"]
            padx, pady = op[0] + PAD[0], op[1] + PAD[1]
            pts.append((padx, pady))
            log.info(f"TOUCH u={u:+.0f}: pad ({padx:.1f}, {pady:.1f}) force {abs(r['delta']):.2f} N")
            rb.movel(at(padx, pady + SIDE * 12.0, Z_C), vel=LIFT_VEL, acc=[10.0, 10.0])
        # 원 맞춤: y_i = yoff + sqrt(R² - (x_i - cx_fit)²), R 고정. cx_fit, yoff 격자 탐색
        best = None
        for dcx in [k * 0.25 for k in range(-100, 101)]:
            cxf = CX + dcx
            ys = [y - SIDE * math.sqrt(max(0.0, R * R - (x - cxf) ** 2)) for (x, y) in pts]
            yoff = sum(ys) / len(ys)
            err = sum((yy - yoff) ** 2 for yy in ys)
            if best is None or err < best[0]: best = (err, cxf, yoff)
        err, cx_fit, yoff = best
        L = SIDE * (pts[0][1] - (CY + SIDE * R))     # 패드 중심 → 도구 끝 거리 (표면 y = CY±R 가정)
        st = dict(cx_fit=cx_fit, yoff=yoff, rms=math.sqrt(err / 3), pts=pts, awl_len_y=L, z_c=Z_C)
        json.dump(st, open(STATE, "w"))
        log.info(f"FIT: 송곳 끝 기준 원 중심 x {cx_fit:.1f} (패드 기준 중심 {CX:.1f} → 끝 x 오프셋 {CX - cx_fit:+.1f}), yoff {yoff:.1f}, rms {st['rms']:.2f} mm, 송곳 돌출 ≈ {L:.1f} mm")
    if STAGE in ("draw", "all"):
        cx_fit, yoff = st["cx_fit"], st["yoff"]
        # 하트 (매개변수식), 폭 HEART_W, 위가 +z. 점 간격 ~1.5 mm
        raw = []
        for k in range(0, 361, 5):
            t = math.radians(k)
            raw.append((16 * math.sin(t) ** 3, 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
        sc = HEART_W / 32.0
        heart = [(x * sc, y * sc) for (x, y) in raw]
        u0, v0 = heart[0]
        # 획 시작점: 표면 밖 6 mm 에서 힘 터치 → 그 y 를 기준으로 곡률만 따라간다 (표면 스치기)
        x_s, z_s = cx_fit + u0, Z_C + v0
        rb.movel(at(x_s, surf_y(x_s, cx_fit, yoff) + SIDE * 6.0, z_s), vel=LIFT_VEL, acc=[10.0, 10.0])
        r = touch_minus_y("stroke touch", 12.0, TOUCH_SPEED)
        if not r["contact"]:
            raise MotionFailed("stroke touch: 12 mm 가도 안 닿음")
        op = r.get("onset_pos") or r["pos"]
        y_touch = op[1] + PAD[1]
        dy = y_touch - surf_y(x_s, cx_fit, yoff)
        log.info(f"stroke touch at pad y {y_touch:.1f} (모델 대비 {dy:+.2f} mm), force {abs(r['delta']):.2f} N")
        pts = [at(cx_fit + u, surf_y(cx_fit + u, cx_fit, yoff) + dy, Z_C + v) for (u, v) in heart]
        log.info(f"drawing heart: {len(pts)} pts, width {HEART_W:.0f} mm, center ({cx_fit:.1f}, z {Z_C:.1f})")
        rb.movesx(pts, vel=DRAW_VEL, acc=DRAW_ACC)
        # 이탈: +Y 로 15 mm
        px, py, pz = pad_now()
        rb.movel(at(px, py + SIDE * 15.0, pz), vel=LIFT_VEL, acc=[10.0, 10.0])
        log.info("heart done, retracted 15 mm")
    if STAGE in ("home", "all"):
        px, py, pz = pad_now()
        y_far = CY + SIDE * (R + AWL_MAX + CLEAR)
        rb.movel(at(px, y_far, pz), vel=HOVER_VEL, acc=[20.0, 20.0])
        rb.movel(at(px, y_far, 234.4), vel=HOVER_VEL, acc=[20.0, 20.0])
        rb.movel(at(422.1, -2.6, 234.4), vel=HOVER_VEL, acc=[20.0, 20.0])
        log.info("returned to new home")
finally:
    rb.set_collision_sensitivity(COLLISION_SENS_DEFAULT)
    node.destroy_node(); rclpy.shutdown()
