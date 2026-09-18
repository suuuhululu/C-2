# [4번 노드] 1번(지점토 위치·크기)·3번(송곳 접촉 높이·힘) 결과로 하트를 긋는다.
# stage "probe_done" → 홈 → 이동 높이 → 시작점 위 → 하강·진입 → 3구간 긋기, 구간 사이에 지점토 옆면에서 송곳 닦기
# → 홈 → stage "draw_done"
# 실행: ros2 run clay_carving clay_heart   (터미널 6)
import math
import os
import sys

import rclpy
from clay_carving.svg_design import load_svg, fit_to_box, stroke_length
import json
import time

from std_msgs.msg import String
from clay_carving.clay_common import (Robot, Bus, MotionFailed, AWL_LEN, LATCHED,
                               PLUNGE_VEL, PLUNGE_ACC, DRAW_VEL, DRAW_ACC, PREVIEW_TOPIC, CONFIRM_TOPIC)

# ---- 도안 ----
# 실행: ros2 run clay_carving clay_draw <파일.svg>   (인자가 없으면 DESIGN_SVG, 그것도 None 이면 내장 하트)
# SVG 의 path/circle/line/polyline 하나 = 송곳 한 획. 1번 노드가 잰 지점토 크기에서 가장자리 MARGIN 을 뺀 상자 안에
# 가로세로 같은 배율(찌그러짐 없음)로 최대한 크게 맞추고, 0°/90° 중 더 크게 들어가는 방향을 고른다.
DESIGN_SVG = "flower.svg"
DESIGN_FILL = 0.85               # 들어갈 수 있는 최대 크기 대비 비율 (1.0 = 여백 MARGIN 까지 꽉 채움)
DESIGN_MARGIN = 8.0              # 지점토 가장자리에서 띄우는 여백 [mm]
DESIGN_STEP = 2.0                # 곡선을 점으로 찍는 간격 [mm] (movesx 점 간격)
MOVESX_CHUNK = 80                # movesx 한 번에 보내는 최대 점 수 (제어기 한도 100)
DESIGN_ROT_DEG = None            # None: 0/90 자동. 0: 도안 '위' 가 base +X (로봇 앞), '오른쪽' 이 base -Y (로봇 뒤에서 볼 때 오른쪽)
DESIGN_MIRROR = False            # True 면 좌우 반전
WIPE_EVERY = 5                   # 몇 획마다 옆면에서 송곳을 닦을지 (0 = 안 함). 9/17 사용자: 살살, 너무 자주는 말 것
HEART_FILL = 0.6                 # (내장 하트) 지점토 짧은 변 대비 하트 폭 비율
HEART_POINTS = 80
HEART_ROT_DEG = 0.0              # 0: 하트 윗부분이 base +X. 지점토 긴 변 방향으로 맞추려면 90
# 9/17 사용자: 조각이 아니라 '표면 스치기', 높이는 오직 힘 판정으로. 시작·재개 때마다 3번 노드와 같은 방식으로 내려가
# 닿는 순간 멈추고, 올리거나 내리지 않고 딱 그 높이에서 긋는다. 3번 노드가 멈춘 높이는 예상값(접근 높이 계산)으로만 쓴다.
EXTRA_BELOW = 8.0                # 3번 노드 높이보다 이만큼 더 내려가도 안 닿으면 오류 (송곳이 밀려 올라갔거나 지점토 없음)
# 9/17 사용자: 3번 노드가 콕 찍고 10 mm 만 올라온 자리에서 바로 시작. 이동 높이 = 표면 10 mm 위, 거기서 힘을 보며 서서히
# 내려가 닿기 시작하면 그 높이에서 movesx 로 긋는다. 홈으로 가는 건 마지막 한 번뿐.
HOVER = 10.0                     # 이동 높이 = 3번 노드가 멈춘 높이 + 이 값 (3번 노드의 HOVER 와 같게)
NEAR = HOVER
APPROACH_VEL = [8.0, 8.0]        # 닦기에서 옆면 바깥으로 내려갈 때 속도
# 접촉 판정은 3번 노드(force_probe)와 같게. 9/17 bag 1820: 4 mm/s + 1 N 두 번 연속은 판정에 1 s 가 걸려 4 mm 를 더
# 들어갔다 → 2 mm/s, 1 N 한 번이면 즉시 정지 (판정 지연 약 0.5~1 mm)
# 9/17 사용자: 끝이 닿은 뒤에도 2~3 mm 더 들어간다 → 뾰족한 끝은 1 N 까지 오르는 데 2 mm 가 든다. 문턱 0.5 N (노이즈 ±0.3),
# 1.5 mm/s. 노이즈로 공중에서 멈추면 선이 안 그어지므로 그때 0.7 로 올린다.
TOUCH_N = 1.5
TOUCH_SOFT_N = 0.8               # 9/17 확정: 0.8 한 번, 1.5 mm/s. 0.5 는 노이즈(±0.4)에 걸려 닿기 전에 서서 공중에 그림 (bag 1954)
TOUCH_SPEED = 1.5
N_SEGMENTS = 3
WIPE_SIDE = "+x"                 # 닦을 옆면: "+x" "-x" "+y" "-y" (1번 노드가 찾은 가장자리 기준)
WIPE_OUT = 15.0                  # 옆면 바깥에서 접근을 시작하는 거리 [mm]. 8 이면 실제 변이 2 mm 앞이라 정착 구간(판정 꺼짐)
                                 # 안에서 이미 닿아 7~8 N 으로 밀었다 (bag 1939) → 정착이 공중에서 끝나도록 멀리서
WIPE_DOWN = 6.0                  # 지점토 윗면 아래로 내려가 닦는 깊이 [mm] (두께 13 의 중간)
WIPE_TOUCH_N = 0.7               # 옆면에 닿았다고 볼 힘 (이동 중 기준 대비 완만한 상승) [N]
WIPE_SPEED = 1.5                 # 옆면으로 다가가는 속도 [mm/s] (9/17 사용자: 살살)
# 9/17 사용자: 3번 비비면 지점토가 밀린다 → 옆면에 살짝 닿을 때까지만 다가간 뒤 그대로 위로 슥 빼는 것 1회


def heart_uv(i, n):
    t = 2.0 * math.pi * i / (n - 1)
    return 16.0 * math.sin(t) ** 3, 13.0 * math.cos(t) - 5.0 * math.cos(2 * t) - 2.0 * math.cos(3 * t) - math.cos(4 * t)


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("clay_heart", namespace="dsr01")
    log = node.get_logger()
    bus = Bus(node)
    data = bus.wait_stage("probe_done", also=("draw_done",))     # 한 번 그린 뒤에도 다시 실행하면 바로 그린다
    clay, awl = data.get("clay"), data.get("awl")
    if not clay or not awl:
        log.error("Missing clay/awl data on /clay/data; run clay_scan and force_probe first"); return
    rb = Robot(node, "clay_heart")
    posx = rb.posx
    awl_len = float(awl.get("awl_len", AWL_LEN))     # 3번 노드가 실측한 송곳 길이

    try:
        rb.go_home()
        home = rb.posx_now()
        A, B, C = home[3], home[4], home[5]
        cx, cy = clay["cx"], clay["cy"]
        z_touch = awl["z_touch_tcp"]                 # 힘이 오르기 시작한 TCP 높이 (3번 노드)
        z_draw = float(awl.get("z_stop_tcp", z_touch))   # 3번 노드가 '닿았다' 로 멈춘 TCP 높이 = 긋는 높이
        travel_z = z_draw + HOVER                    # 이동 시 송곳 끝이 지점토 위 HOVER 만큼 뜬 높이
        z_cut = z_draw
        short = min(clay["size_x"], clay["size_y"])
        # ---- 획 목록 만들기: (u, v) = (도안 오른쪽 → base -Y, 도안 위 → base +X) [mm], 중심 (0,0)
        job = data.get("job") or {}
        if job.get("face") == "side":
            raise MotionFailed("옆면 그리기(face=side)는 아직 구현 전입니다. 대시보드에서 '그릴 면' 을 윗면으로 바꾸거나 옆면 모드 구현을 기다려 주세요")
        argv = [a for a in sys.argv[1:] if not a.startswith("-")]
        design = argv[0] if argv else DESIGN_SVG
        if design:
            svg_path = design if os.path.isabs(design) or os.path.exists(design) else \
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "designs", design)
            if not os.path.exists(svg_path):
                raise MotionFailed(f"SVG not found: {design}")
            raw, _ = load_svg(svg_path)
            if not raw:
                raise MotionFailed(f"SVG has no drawable path/line/circle: {design}")
            # 지점토에서 여백을 뺀 상자. 도안 '위' 는 base +X 로 가므로 상자 (base Y 폭, base X 폭) = (size_y, size_x) 순서.
            box_y, box_x = clay["size_y"] - 2 * DESIGN_MARGIN, clay["size_x"] - 2 * DESIGN_MARGIN
            cands = []
            for rdeg in ([DESIGN_ROT_DEG] if DESIGN_ROT_DEG is not None else [0.0, 90.0]):
                # rot 0: 도안 가로 → base Y, 도안 세로 → base X. rot 90: 반대
                bw, bh = (box_y, box_x) if abs(rdeg) % 180 < 45 else (box_x, box_y)
                fitted, (dw, dh), k = fit_to_box(raw, bw, bh, DESIGN_FILL, DESIGN_STEP)
                cands.append((k, rdeg, fitted, dw, dh))
            k, rdeg, fitted, dw, dh = max(cands, key=lambda c: c[0])
            sx = 1.0 if DESIGN_MIRROR else -1.0                          # x(오른쪽) → u=-x 이면 base -Y (로봇 뒤에서 볼 때 오른쪽)
            strokes = [[(sx * x, y) for x, y in st] for st in fitted]
            rot = math.radians(rdeg)
            name = os.path.basename(svg_path)
            width = max(dw, dh)
            log.info(f"Design {name}: {len(strokes)} strokes, scaled x{k:.3f} → {dw:.1f}x{dh:.1f} mm (aspect kept), rot {rdeg:.0f}°, "
                     f"total {sum(stroke_length(s) for s in fitted):.0f} mm; clay {clay['size_x']:.0f}x{clay['size_y']:.0f}, margin {DESIGN_MARGIN:.0f}; "
                     f"draw z(TCP)={z_cut:.1f} (node-3 stop; force {awl['force_n']:.2f} N)")
        else:
            width = HEART_FILL * short
            scale = width / 32.0
            pts = [(u * scale, v * scale) for u, v in (heart_uv(i, HEART_POINTS) for i in range(HEART_POINTS))]
            n = len(pts)
            bounds = [round(k * (n - 1) / N_SEGMENTS) for k in range(N_SEGMENTS + 1)]
            strokes = [pts[bounds[k]:bounds[k + 1] + 1] for k in range(N_SEGMENTS)]
            rot = math.radians(HEART_ROT_DEG)
            name = "heart"
            log.info(f"Heart width {width:.0f} mm on clay {clay['size_x']:.0f}x{clay['size_y']:.0f}, draw z(TCP)={z_cut:.1f} "
                     f"(node-3 stop height; force was {awl['force_n']:.2f} N)")

        def surf(u, v, z):
            xx = v * math.cos(rot) - u * math.sin(rot)
            yy = v * math.sin(rot) + u * math.cos(rot)
            return posx(cx + xx, cy + yy, z, A, B, C)

        half_x, half_y = clay["size_x"] / 2.0 - DESIGN_MARGIN, clay["size_y"] / 2.0 - DESIGN_MARGIN
        for st in strokes:
            for u, v in st:
                xx = v * math.cos(rot) - u * math.sin(rot); yy = v * math.sin(rot) + u * math.cos(rot)
                if abs(xx) > half_x or abs(yy) > half_y:
                    raise MotionFailed(f"Design {name} exceeds clay area (8 mm margin); reduce DESIGN_FILL/HEART_FILL")

        def travel(u, v):
            rb.movel(surf(u, v, travel_z), vel=[12.0, 12.0], acc=[15.0, 15.0])   # 표면 10 mm 위 수평 이동

        touches = []

        def descend(u, v, label):
            """이동 높이(표면 10 mm 위)에서 힘을 보며 서서히 내려가 닿기 시작하는 높이를 찾는다 (9/17 사용자: 매번 닿는
            뉴턴으로 확인 — 송곳이 그리퍼 안에서 밀려 올라갔을 수 있다). 닿은 높이에서 바로 긋는다."""
            r = rb.probe_down(TOUCH_N, NEAR + EXTRA_BELOW, speed_mm_s=TOUCH_SPEED, label=label, vertical=True,
                              settle_mm=2.0, settle_s=1.2, hard_limit_n=4.5, soft_n=TOUCH_SOFT_N, soft_samples=1)
            z_c = r["z"]
            f = abs(r["delta"])
            touches.append((label, z_c, f, r["contact"]))
            if not r["contact"]:
                raise MotionFailed(f"{label}: awl did not touch the clay down to {z_draw - EXTRA_BELOW:.1f} (node-3 height {z_draw:.1f}). "
                                   f"송곳이 밀려 올라갔거나 지점토 위치가 다름 → 3번 노드부터 다시")
            log.info(f"{label}: touched at TCP z={z_c:.2f} ({z_c - z_draw:+.2f} vs node-3 height {z_draw:.2f}), force {f:.2f} N → draw here")
            return z_c

        def ascend(u, v):
            rb.movel(surf(u, v, travel_z), vel=PLUNGE_VEL, acc=PLUNGE_ACC)

        def wipe():
            """지점토 옆면(WIPE_SIDE) 바깥에서 윗면 아래 WIPE_DOWN 높이까지 내려간 뒤, 옆면에 살짝 닿을 때까지만
            다가가고(힘 감시), 그 자리에서 그대로 위로 올려 송곳에 묻은 점토를 옆면 모서리에 훑어 낸다. 1회."""
            log.info(f"Wipe awl on clay side {WIPE_SIDE} (touch once, slide up)")
            if WIPE_SIDE == "+x": ex, ey, nx, ny = clay["x_max"], cy, 1, 0
            elif WIPE_SIDE == "-x": ex, ey, nx, ny = clay["x_min"], cy, -1, 0
            elif WIPE_SIDE == "+y": ex, ey, nx, ny = cx, clay["y_max"], 0, 1
            else: ex, ey, nx, ny = cx, clay["y_min"], 0, -1
            z_w = z_draw - WIPE_DOWN
            def P(off_n, z):
                return posx(ex + nx * off_n, ey + ny * off_n, z, A, B, C)
            rb.movel(P(WIPE_OUT, travel_z), vel=[12.0, 12.0], acc=[15.0, 15.0])
            rb.movel(P(WIPE_OUT, z_w), vel=APPROACH_VEL, acc=[10.0, 10.0])
            r = rb.probe_along([-nx, -ny, 0.0], 1.5, WIPE_OUT + 12.0, speed_mm_s=WIPE_SPEED, label="wipe touch",
                               settle_mm=2.0, settle_s=1.0, hard_limit_n=3.0, soft_n=WIPE_TOUCH_N, soft_samples=1)
            if not r["contact"]:        # 9/17 bag 1752: 12 mm 로는 못 찾음 (변 위치 오차) → 한 번 더 10 mm
                log.warn("wipe: side not found within first approach; trying 10 mm further")
                r = rb.probe_along([-nx, -ny, 0.0], 1.5, 10.0, speed_mm_s=WIPE_SPEED, label="wipe touch 2",
                                   settle_mm=2.0, settle_s=1.0, hard_limit_n=3.0, soft_n=WIPE_TOUCH_N, soft_samples=1)
            if not r["contact"]:
                raise MotionFailed(f"wipe: clay side {WIPE_SIDE} not found within {WIPE_OUT + 22:.0f} mm; check clay position")
            log.info(f"wipe: side touched at ({r['pos'][0]:.1f},{r['pos'][1]:.1f}) with {abs(r['delta']):.2f} N → sliding up")
            cur = rb.posx_now()
            rb.movel(posx(cur[0], cur[1], travel_z, A, B, C), vel=PLUNGE_VEL, acc=PLUNGE_ACC)   # 닿은 채 위로 슥

        # ---- 대시보드 미리보기·확인: 실측 지점토에 맞춘 도안을 보내고, 대시보드가 듣고 있으면 확인/취소를 기다린다 ----
        preview = dict(name=name, clay=clay, awl=awl,
                       strokes=[[[round(surf(u, v, 0)[0], 2), round(surf(u, v, 0)[1], 2)] for u, v in st] for st in strokes])
        pv_pub = node.create_publisher(String, PREVIEW_TOPIC, LATCHED)
        pv_pub.publish(String(data=json.dumps(preview)))
        if pv_pub.get_subscription_count() > 0:
            log.info("Preview sent to dashboard; waiting for confirm/cancel ...")
            got = {}
            sub = node.create_subscription(String, CONFIRM_TOPIC, lambda m: got.__setitem__("a", m.data), 10)
            while "a" not in got:
                rclpy.spin_once(node, timeout_sec=0.1)
            node.destroy_subscription(sub)
            if got["a"] != "ok":
                log.warn("Drawing cancelled from dashboard")
                bus.publish_stage("draw_cancelled")
                return
            log.info("Confirmed from dashboard → drawing")
        else:
            time.sleep(0.2)

        if home[2] < travel_z - 1.0:                 # 이동 높이보다 낮게 서 있으면 먼저 그 높이로
            rb.lift_straight_up(travel_z - home[2])
        log.info(f"travel z={travel_z:.1f} (awl tip {HOVER:.0f} mm above clay), start from ({home[0]:.1f},{home[1]:.1f},{home[2]:.1f}), "
                 f"awl len {awl_len:.1f}")
        total = len(strokes)
        for k, st in enumerate(strokes):
            u0, v0 = st[0]
            travel(u0, v0)                           # 표면 10 mm 위로 이 획의 첫 점까지
            z_c = descend(u0, v0, f"stroke {k + 1}")  # 힘을 보며 내려가 닿은 높이
            log.info(f"Draw stroke {k + 1}/{total} ({len(st)} pts, {stroke_length(st):.0f} mm) at z={z_c:.2f}")
            pts = [surf(u, v, z_c) for u, v in st[1:]]   # 이미 첫 점 위에 있으므로 첫 점은 뺀다 (길이 0 구간 경고 방지)
            if len(pts) >= 2:
                # movesx 는 한 번에 최대 100 점 (pos_cnt int8) → 긴 획은 MOVESX_CHUNK 점씩 이어서 보낸다 (들지 않음)
                for i in range(0, len(pts), MOVESX_CHUNK):
                    chunk = pts[i:i + MOVESX_CHUNK]
                    if len(chunk) >= 2:
                        rb.movesx(chunk)
                    else:
                        rb.movel(chunk[-1], vel=DRAW_VEL, acc=DRAW_ACC)
            else:
                rb.movel(pts[-1], vel=DRAW_VEL, acc=DRAW_ACC)
            lu, lv = st[-1]
            ascend(lu, lv)
            if WIPE_EVERY > 0 and k < total - 1 and (k + 1) % WIPE_EVERY == 0:
                wipe()
        travel(0.0, 0.0)
        rb.go_home()
        bus.publish_stage("draw_done")
        log.info("\n".join(["", "==================== 4번 노드 결과 (도안) ===================="] +
                           [f" {lab:<16}: {'닿음' if c else '안 닿음'}  TCP z = {z:6.2f}  힘 {f:5.2f} N  (3번 노드 높이 {z_draw:.2f}, Δ{z - z_draw:+.2f})"
                            for lab, z, f, c in touches] +
                           [f" 도안 {name}: {len(strokes)} 획, 긴 쪽 {width:.0f} mm, 중심 ({cx:.1f}, {cy:.1f}), 긋는 높이 = 각 접촉에서 힘 판정으로 멈춘 높이",
                            "=============================================================", ""]))
        log.info("clay_heart finished")

    except MotionFailed as e:
        log.error(str(e))
    except KeyboardInterrupt:
        log.info("Program Stopped")
    except Exception as e:
        log.error(f"Robot Error: {e}")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
