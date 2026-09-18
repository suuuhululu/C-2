# [1번 노드] 지점토 위치·크기 측정 — 옆면 밀기(터치 프로빙) 방식. 송곳 없이 닫은 그리퍼 손끝으로.
# 시작 신호(/clay/start) → 홈 정렬 → 그리퍼 닫기 → 중심 하강(윗면 높이·접촉 힘 기록) → 윗면 6 mm 위로
# → 네 방향 각각: 지점토 바깥으로 나가 윗면보다 3 mm 낮게 내려간 뒤(윗면에 닿으면 더 바깥으로), 안쪽으로 2 mm/s
#   로 밀며 반력 급증 → 그 좌표가 변 → 위로 복귀
# → 바깥 한 점에서 받침대 높이 → 네 변으로 모서리·중심·가로·세로 → /clay/data → 홈 → 그리퍼 열기 → "scan_done"
# 실행: ros2 run clay_carving clay_scan (터미널 3) / 시작: ros2 run clay_carving clay_start (터미널 7)
import rclpy
from clay_carving.clay_common import (Robot, Gripper, Bus, MotionFailed, START_TOPIC, CLAY_W, CLAY_H, CLAY_T_NOMINAL,
                               TCP_Y_OFF, tool_y_axis)

TOUCH_N = 1.5                    # 접촉 판정: 1.5 s 이동평균 대비 반력 급증 [N]
CENTER_TRAVEL = 150.0            # 중심 프로빙 최대 하강 [mm]
CENTER_FAST = 35.0               # 중심 프로빙 앞 구간 [mm] (7.5 mm/s), 그 뒤 2.4 mm/s (9/17 접촉 50 mm: 60 이면 빠른 구간에서
                                 #  닿아 15 N 으로 찍힘, bag 1608)
EDGE_DROP = 6.0                  # 접촉 높이가 윗면보다 이 이상 낮으면 '밖', 이 이상 높으면 '장애물'
HOVER = 15.0                     # 윗면 위 수평 이동 높이 [mm] (9/17: 6 이면 +Y 에서 그리퍼 몸체가 걸림)
SIDE_DEPTH = 3.0                 # 옆면을 밀 때 손끝 높이 = 윗면 - 이 값 [mm] (두께 13 안쪽)
OUT_START = 90.0                 # 시작점에서 바깥으로 나가 옆면 밀기를 시작하는 거리 [mm] (반폭 54 + 패드 11.5 + 중심 어긋남
                                 #  17 + 여유; 9/17 bag 1559/1608: 60·75 면 +X/+Y 가 출발 직후 닿아 과도 구간과 겹침)
OUT_STEP = 15.0                  # 그 자리가 아직 지점토 위면 더 나가는 간격 [mm]
BACKOFF = 3.0                    # 옆면 접촉 후 바깥으로 물러난 뒤 올라오는 거리 [mm] (모서리 긁힘 방지)
# 접촉점-TCP 오프셋 [mm] (변 방향으로, 안쪽이 +). 45° 자세는 툴 X(=base X) 둘레 회전이라 X 방향은 좌우 대칭이지만
# Y 방향은 비대칭: 손끝(툴 -Y)이 base -Y 쪽으로 기울어 -Y 변은 손끝 점이 먼저 닿고(오프셋 ~0), +Y 변은 기울어진
# 그리퍼 몸체 경사면이 닿는다(오프셋 큼, 완만한 힘 상승). 9/17 bag 1546/1559/1611 실측: X (115.8/114.9/114.5-92)/2 = 11.5,
# -Y 손끝 첫 접촉 -72 ≈ 변, +Y 경사면 첫 접촉 TCP 43~46 → 변 약 36 → 오프셋 약 9. 다음 실측으로 보정.
# 9/17 bag 1619 힘 상승 시작점 기준: X 457.5/341 → (116.5-92)/2 = 12.2, Y 46.6/-75 → 121.6-108 = 13.6 (-Y 손끝 ≈ 1)
TIP_OFF = {"+x": 12.0, "-x": 12.0, "+y": 13.0, "-y": 1.0}
TIP_HALF_X = None                # (이전 방식) 값을 주면 TIP_OFF 대신 X 양쪽에 같은 오프셋
TIP_HALF_Y = None
OUT_MAX = 120.0
SIDE_SPEED = 6.0                 # 옆면 밀기 속도 [mm/s] (9/17 사용자: 2배)
SIDE_SOFT_N = 1.2                # 옆면 밀기: 이동 중 기준 대비 이만큼 완만히 올라도(연속 2 샘플) 접촉 (9/17 bag 1611 +Y: 급증 없이
                                 #  20 mm 에 걸쳐 9 N 까지 올라 hard limit 로 멈춤 → 지점토를 밀고 들어감)
OUTSIDE_TRAVEL = 40.0            # 바깥 점에서 받침대/책상 높이를 잴 때 최대 하강 [mm]
HOVER_VEL = [40.0, 40.0]
LIFT_VEL = [18.0, 18.0]
COLLISION_SENS_SCAN = 90         # 스캔 중 제어기 충돌 감지 민감도 [%] (손목이 받침대에 닿아도 정지)
COLLISION_SENS_DEFAULT = 75      # 스캔 후 되돌릴 값 (DART Robot Limits 기본값 75 %. TP 에서 확인한 값으로 맞출 것)
SCAN_TILT_DEG = 45.0             # 스캔 자세: 홈 자세에서 툴 X 축(수평) 둘레로 이만큼 돌려 눕혀진 툴을 세운다 (9/17: 12→36→45)
                                 # (J6 회전은 툴 자기 축 회전이라 안 됨, 9/17 bag 1525). 반대로 서면 부호를 바꾼다


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("clay_scan", namespace="dsr01")
    log = node.get_logger()
    bus = Bus(node)
    bus.wait_stage("__never__", on_empty_topic=START_TOPIC)

    rb = Robot(node, "clay_scan")
    # 대시보드 가이드라인(도형·가로·세로·높이·받침대). 없으면 상수 그대로. 좌표는 항상 실측한다.
    from clay_carving.clay_common import _load_state
    job = _load_state().get("data", {}).get("job") or {}
    out_start = OUT_START
    if job.get("w") and job.get("h") and not job.get("auto", True):
        out_start = min(140.0, max(60.0, max(float(job["w"]), float(job["h"])) / 2.0 + 12.0 + 25.0))
        log.info(f"Guideline from dashboard: {job} → side search starts at {out_start:.0f} mm")
    gr = Gripper(node, rb)
    posx = rb.posx

    try:
        rb.go_home()
        rb.set_collision_sensitivity(COLLISION_SENS_SCAN)
        gr.close()
        # 스캔 자세: 툴 X 축 둘레로 살짝 돌려 눕혀진 툴을 세우고 손끝이 면이 아니라 한 점으로 닿게 한다. 하강은 수직.
        from clay_carving.clay_common import rotate_about_tool_axis
        h = rb.posx_now()
        A2, B2, C2 = rotate_about_tool_axis(h[3], h[4], h[5], "x", SCAN_TILT_DEG)
        log.info(f"Scan pose: tilt {SCAN_TILT_DEG:+.0f} deg about tool X: (A,B,C) ({h[3]:.1f},{h[4]:.1f},{h[5]:.1f}) → "
                 f"({A2:.1f},{B2:.1f},{C2:.1f})")
        rb.movel(posx(h[0], h[1], h[2], A2, B2, C2), vel=[10.0, 5.0], acc=[20.0, 10.0])
        rb.check_probe_axis_down(max_tilt_deg=abs(SCAN_TILT_DEG) + 5.0)
        home = rb.posx_now()
        A, B, C = home[3], home[4], home[5]
        x0, y0, z_home = home[0], home[1], home[2]
        # 실제로 닿는 건 패드(손끝)이고 TCP 는 그보다 툴 -Y 로 60 mm 아래다. 이동 명령은 TCP 로 하되, 기록하는 접촉
        # 좌표(변·윗면·받침대)는 패드 위치 = TCP + 60·(툴 +Y) 로 바꿔 저장한다.
        ty = tool_y_axis(A, B, C)
        PAD = [TCP_Y_OFF * ty[0], TCP_Y_OFF * ty[1], TCP_Y_OFF * ty[2]]
        log.info(f"Scan start TCP = ({x0:.1f}, {y0:.1f}, {z_home:.1f}); pad = TCP + ({PAD[0]:.1f}, {PAD[1]:.1f}, {PAD[2]:.1f})")

        def at(x, y, z):
            return posx(x, y, z, A, B, C)

        # ---- 1) 중심 하강 ----
        c = rb.probe_down(TOUCH_N, CENTER_TRAVEL, speed_mm_s=2.4, label="center", fast_mm=CENTER_FAST, fast_speed=7.5, vertical=True)
        if not c["contact"]:
            raise MotionFailed("No contact at start position: is the clay under the gripper?")
        z_top, contact_force, descended_first = c["z"], abs(c["delta"]), c["descended"]
        hover_z = z_top + HOVER
        side_z = z_top - SIDE_DEPTH
        z_top_pad = z_top + PAD[2]                # 실제 윗면 높이 (패드 접촉점)
        log.info(f"Clay top: TCP z = {z_top:.1f} → surface z = {z_top_pad:.1f} after {descended_first:.1f} mm, force {contact_force:.2f} N")
        rb.movel(at(x0, y0, hover_z), vel=LIFT_VEL, acc=[10.0, 10.0])
        taps = [dict(kind="top", x=round(x0, 1), y=round(y0, 1), z=round(z_top, 1), force=round(contact_force, 2))]

        # ---- 2) 네 방향 옆면 밀기 ----
        def find_side(dx, dy, name):
            """(dx,dy) 방향 바깥에서 안쪽으로 밀어 변의 좌표를 찾는다. 반환: 접촉점 [x,y], 바깥 거리"""
            d = out_start
            while d <= OUT_MAX:
                ox, oy = x0 + dx * d, y0 + dy * d
                rb.movel(at(ox, oy, hover_z), vel=HOVER_VEL, acc=[20.0, 20.0])
                # 옆면 높이까지 내려가 본다. 도중에 닿으면 아직 지점토 위 → 더 바깥으로
                r = rb.probe_down(TOUCH_N, HOVER + SIDE_DEPTH, speed_mm_s=6.0, label=f"{name} down@{d:.0f}",
                                  settle_mm=4.0, settle_s=1.5, hard_limit_n=4.5, vertical=True)
                if r["contact"]:
                    dzc = r["z"] - z_top          # 접촉 높이 - 윗면 (+ 면 윗면보다 높음)
                    taps.append(dict(kind="top", x=round(ox, 1), y=round(oy, 1), z=round(r["z"], 1)))
                    rb.movel(at(ox, oy, hover_z), vel=LIFT_VEL, acc=[10.0, 10.0])
                    if dzc > EDGE_DROP:
                        # 윗면보다 훨씬 높은 데서 닿음 = 손끝이 아닌 다른 부분이 무언가에 걸림 (9/17 +Y: 윗면 +14 mm)
                        raise MotionFailed(f"{name}: obstacle at {d:.0f} mm — contact {dzc:+.1f} mm ABOVE clay top "
                                           f"(z={r['z']:.1f}). Some part of the gripper other than the tip is touching; "
                                           f"check what it hits or change SCAN_TILT_DEG")
                    log.info(f"  {name}: still on clay at {d:.0f} mm (contact {dzc:+.1f} mm vs top); moving further out")
                    d += OUT_STEP
                    continue
                # 바깥 확인됨 → 안쪽으로 밀기
                r = rb.probe_along([-dx, -dy, 0.0], TOUCH_N, d + 5.0, speed_mm_s=SIDE_SPEED, label=f"{name} push",
                                   settle_mm=4.0, settle_s=1.5, hard_limit_n=4.5, soft_n=SIDE_SOFT_N)
                # 변의 위치 = 힘이 오르기 시작한 지점(무른 지점토라 판정 시점엔 이미 몇 mm 파고든 뒤)
                op = r.get("onset_pos") or r["pos"]
                tx, ty_ = op[0], op[1]                        # 접촉 시 TCP (이동 목표는 반드시 TCP 좌표로)
                px, py = tx + PAD[0], ty_ + PAD[1]            # 기록용 패드 접촉점
                # 파고든 상태에서 곧장 올리면 손끝이 모서리를 긁는다 → 바깥으로 BACKOFF 만큼 물러난 뒤 상승
                # (9/17 bag 1714: 여기서 패드 좌표를 목표로 써서 -Y 변에서 접촉 후 41 mm 를 더 밀고 들어갔다)
                bx, by = tx + dx * BACKOFF, ty_ + dy * BACKOFF
                rb.movel(at(bx, by, side_z), vel=LIFT_VEL, acc=[10.0, 10.0])
                rb.movel(at(bx, by, hover_z), vel=LIFT_VEL, acc=[10.0, 10.0])
                if not r["contact"]:
                    raise MotionFailed(f"{name}: pushed {d + 5:.0f} mm inward without touching the clay side")
                taps.append(dict(kind="side", x=round(px, 1), y=round(py, 1), z=round(side_z, 1),
                                 force=round(abs(r["delta"]), 2), dir=name))
                side_force[name] = abs(r["delta"])
                log.info(f"Side {name}: contact at ({px:.1f}, {py:.1f}), force {abs(r['delta']):.2f} N")
                return [px, py], d
            raise MotionFailed(f"{name}: clay still present at {OUT_MAX:.0f} mm from start")

        side_force = {}
        sx_p, d_out = find_side(1, 0, "+x")
        sx_n, _ = find_side(-1, 0, "-x")
        sy_p, _ = find_side(0, 1, "+y")
        sy_n, _ = find_side(0, -1, "-y")

        # ---- 3) 바깥 한 점에서 받침대/책상 높이 ----
        ox = x0 + d_out + 5.0
        rb.movel(at(ox, y0, hover_z), vel=HOVER_VEL, acc=[20.0, 20.0])
        r = rb.probe_down(TOUCH_N, OUTSIDE_TRAVEL, speed_mm_s=3.0, label="outside +x", settle_mm=4.0, settle_s=1.5, hard_limit_n=4.5, vertical=True)
        rb.movel(at(ox, y0, hover_z), vel=LIFT_VEL, acc=[10.0, 10.0])
        if not r["contact"]:
            outside, stand_z = "none", None
        elif (z_top - r["z"]) < CLAY_T_NOMINAL + 8.0:
            outside, stand_z = "stand", r["z"] + PAD[2]
        else:
            outside, stand_z = "table", r["z"] + PAD[2]
        thickness = (z_top_pad - stand_z) if stand_z is not None else CLAY_T_NOMINAL

        # ---- 4) 결과 (변이 base 축과 나란하다고 가정) ----
        # 접촉점은 TCP 가 아니라 닫힌 그리퍼의 바깥면이므로 양쪽 간격이 그리퍼 폭만큼 크게 나온다 (9/17: 130 vs 92).
        # 중심은 양쪽이 상쇄되어 정확. 크기는 TIP_HALF 를 주면 그걸로, 없으면 명목 크기로 보정한다.
        raw_x = sx_p[0] - sx_n[0]
        raw_y = sy_p[1] - sy_n[1]
        cx, cy = (sx_p[0] + sx_n[0]) / 2.0, (sy_p[1] + sy_n[1]) / 2.0
        ox_p, ox_n = (TIP_HALF_X, TIP_HALF_X) if TIP_HALF_X is not None else (TIP_OFF["+x"], TIP_OFF["-x"])
        oy_p, oy_n = (TIP_HALF_Y, TIP_HALF_Y) if TIP_HALF_Y is not None else (TIP_OFF["+y"], TIP_OFF["-y"])
        x_max, x_min = sx_p[0] - ox_p, sx_n[0] + ox_n
        y_max, y_min = sy_p[1] - oy_p, sy_n[1] + oy_n
        size_x, size_y = x_max - x_min, y_max - y_min
        cx, cy = (x_max + x_min) / 2.0, (y_max + y_min) / 2.0
        log.info(f"Raw side spacing {raw_x:.1f}x{raw_y:.1f}; tip offsets +x/-x/+y/-y = {ox_p}/{ox_n}/{oy_p}/{oy_n}")
        corners = [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]]
        clay = dict(cx=cx, cy=cy, z_top=z_top_pad, z_top_tcp_tilted=z_top, pad_offset=PAD, size_x=size_x, size_y=size_y,
                    x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max, corners=corners,
                    stand_z=stand_z, thickness=thickness, orientation=[A, B, C], outside={"+x": outside},
                    home_tcp_z=z_home, contact_force_n=contact_force, descended_from_home=descended_first, taps=taps)
        log.info(f"CLAY: center=({cx:.1f},{cy:.1f}) size={size_x:.1f}x{size_y:.1f} (nominal {CLAY_W:.0f}x{CLAY_H:.0f}) "
                 f"top z={z_top_pad:.1f} outside={outside} stand_z={stand_z} thickness={thickness:.1f}")
        log.info("Corners: " + ", ".join(f"({x:.1f},{y:.1f})" for x, y in corners) + f"  ({len(taps)} touches)")
        bus.update_data(clay=clay)

        rb.movel(at(x0, y0, hover_z), vel=HOVER_VEL, acc=[20.0, 20.0])
        rb.go_home()
        rb.set_collision_sensitivity(COLLISION_SENS_DEFAULT)
        gr.half_open()
        bus.publish_stage("scan_done")
        sides = dict(zip(["+x", "-x", "+y", "-y"], [sx_p, sx_n, sy_p, sy_n]))
        lines = ["", "==================== 1번 노드 결과 (지점토 스캔) ====================",
                 f" 윗면 접촉      : 높이 z = {z_top_pad:6.1f} mm   힘 {contact_force:5.2f} N   (홈에서 {descended_first:.1f} mm 하강)"]
        for k, lab in [("+x", "+X 변 (앞)"), ("-x", "-X 변 (뒤)"), ("+y", "+Y 변 (왼)"), ("-y", "-Y 변 (오른)")]:
            lines.append(f" {lab:<10}: ({sides[k][0]:6.1f}, {sides[k][1]:6.1f})   힘 {side_force.get(k, 0.0):5.2f} N")
        lines += [f" 받침대        : {'높이 z = %.1f mm' % stand_z if stand_z is not None else '못 찾음'}   지점토 두께 {thickness:.1f} mm",
                  f" 가로 x 세로   : {size_x:5.1f} x {size_y:5.1f} mm   (자로 잰 값 {CLAY_W:.0f} x {CLAY_H:.0f})",
                  f" 중심          : ({cx:.1f}, {cy:.1f})",
                  " 꼭짓점        : " + "  ".join(f"({x:.1f}, {y:.1f})" for x, y in corners),
                  "======================================================================", ""]
        log.info("\n".join(lines))
        log.info("clay_scan finished")

    except MotionFailed as e:
        log.error(str(e))
    except KeyboardInterrupt:
        log.info("Program Stopped")
        try:
            rb.stop()
        except Exception:
            pass
    except Exception as e:
        log.error(f"Robot Error: {e}")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
