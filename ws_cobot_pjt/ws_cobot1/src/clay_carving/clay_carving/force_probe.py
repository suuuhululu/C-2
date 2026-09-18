# [3번 노드] 송곳을 쥔 상태에서 1번 노드가 찾은 지점토 중심을 천천히 눌러, 살짝 눌리는 순간의 힘과 높이를 저장.
# stage "grip_done" → 홈 → 이동 높이 → 중심 위 → 하강(송곳 끝이 표면 근처까지 보통 속도) → 저속 프로빙(1.5 N)
# → /clay/data 에 awl 항목 추가 → 10 mm 상승(홈 안 감) → stage "probe_done"
# 실행: ros2 run clay_carving force_probe   (터미널 5)   단독 테스트: ros2 run clay_carving force_probe 398.4 -14.3 55.9
import sys

import rclpy
from clay_carving.clay_common import Robot, Bus, MotionFailed, AWL_LEN, TCP_Y_OFF

TOUCH_N = 1.5                    # "살짝 눌림" 판정: 1.5 s 이동평균 대비 급증 [N]
SOFT_N = 1.0                     # 송곳 끝은 뾰족해 힘이 완만히 오른다 → 이동 중 기준 대비 이만큼(연속 2회) 오르면 접촉
                                 # (9/17 bag 1912: 0.5 N 한 번은 노이즈 ±0.4 에 걸려 공중에서 멈춤 → 롤백)
PROBE_SPEED = 4.0                # 하강 [mm/s]. 어디서 닿을지 모르므로(길이 1~10 cm) 빠른 구간 없이 전 구간 같은 속도
# 2번 노드에서 송곳을 쥘 때마다 튀어나온 길이가 달라진다 (1~10 cm, 9/17 사용자). 그래서 출발 높이는 '송곳이 AWL_MAX 까지
# 나와 있어도 끝이 지점토 위 CLEAR 만큼 뜨는 높이' 로 잡고, 거기서부터 닿을 때까지 일정 속도로 내려간다.
AWL_MAX = 110.0                  # 이보다 길게 물리면 중심 위로 갈 때 끝이 지점토에 닿을 수 있다
CLEAR = 15.0
# 하강 한도: 1번 노드가 손끝으로 잰 윗면 TCP 높이(z_top) + FLOOR_ABOVE 까지. 송곳이 조금이라도 나와 있으면 그 전에 닿는다.
# (9/17 bag 1700: 고정 70 mm 로는 TCP 76 에서 끝나 송곳 끝이 윗면까지 못 미침 → TCP 기준점이 손끝이 아님)
FLOOR_ABOVE = 2.0
HOVER = 10.0                     # 접촉 뒤 올라가는 높이 [mm]. 홈으로 가지 않고 여기서 4번 노드로 넘긴다


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("force_probe", namespace="dsr01")
    log = node.get_logger()
    bus = Bus(node)
    # 단독 실행: ros2 run clay_carving force_probe <cx> <cy> <z_top>  (1번 노드 결과를 직접 넣으면 grip_done 을 기다리지 않는다)
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(argv) >= 3:
        clay = dict(cx=float(argv[0]), cy=float(argv[1]), z_top=float(argv[2]))
        log.info(f"Standalone: clay center/top from arguments {clay}")
    else:
        data = bus.wait_stage("grip_done")
        clay = data.get("clay")
        if not clay:
            log.error("No clay data on /clay/data; run clay_scan first"); return
    rb = Robot(node, "force_probe")
    posx = rb.posx
    no_home = "--no-home" in sys.argv       # 물체가 홈 손끝보다 높을 때: 홈 관절로 가지 않고 지금 자세에서 위로 올라가 중심 위로 (9/18 양초)
    try:
        if no_home:
            from clay_carving.clay_common import HOME_TCP_XY
            home = rb.posx_now()
            A, B, C = 90.3, 88.6, 90.9        # 홈 자세의 방향 (툴 -Y = 아래)
            log.info(f"--no-home: 지금 자세 {[round(v, 1) for v in home[:3]]} 에서 시작, 홈 방향 (A,B,C)=({A},{B},{C})")
            _ = HOME_TCP_XY
        else:
            rb.go_home()
            home = rb.posx_now()
            A, B, C = home[3], home[4], home[5]
        cx, cy, z_top = clay["cx"], clay["cy"], clay["z_top"]
        # z_top = 1번 노드가 잰 실제 윗면 높이(패드 접촉점). 홈 자세에서 TCP 는 패드보다 60 mm 아래이고 송곳 끝은 패드에서
        # L 아래이므로, 송곳 끝이 표면에 닿을 때 TCP = z_top - 60 + L. L 은 모르니 AWL_MAX 기준으로 출발 높이를 잡는다.
        travel_z = z_top - TCP_Y_OFF + AWL_MAX + CLEAR
        log.info(f"Clay center ({cx:.1f},{cy:.1f}), surface z={z_top:.1f}; awl length unknown (≤{AWL_MAX:.0f}) → "
                 f"start z={travel_z:.1f} (home z={home[2]:.1f})")
        if travel_z > home[2]:
            rb.lift_straight_up(travel_z - home[2])
        rb.movel(posx(cx, cy, travel_z, A, B, C), vel=[15.0, 10.0], acc=[20.0, 10.0])
        # 앞 FAST_MM 은 빠르게(접촉 예상 높이보다 START_ABOVE-FAST_MM 위까지), 그 뒤 저속
        z_floor = z_top - TCP_Y_OFF + FLOOR_ABOVE       # 패드가 윗면 FLOOR_ABOVE 위에 올 때의 TCP 높이 (송곳 없어도 안 닿게)
        probe_travel = travel_z - z_floor
        log.info(f"Probe down up to {probe_travel:.0f} mm (until TCP z={z_floor:.1f}, pads {FLOOR_ABOVE:.0f} mm above surface)")
        r = rb.probe_down(TOUCH_N, probe_travel, speed_mm_s=PROBE_SPEED, label="awl-center",
                          settle_mm=4.0, settle_s=1.5, hard_limit_n=4.5, soft_n=SOFT_N)
        if not r["contact"]:
            raise MotionFailed("Awl did not touch the clay within travel; check clay position/height")
        # 표면 높이 = 힘이 오르기 시작한 지점 (판정 시점엔 이미 조금 파고든 뒤)
        z_touch = r["onset_pos"][2] if r.get("onset_pos") else r["z"]
        awl_len_measured = z_touch - z_top + TCP_Y_OFF   # 실제로 쥔 송곳이 패드 아래로 나온 길이
        awl = dict(z_touch_tcp=z_touch, z_stop_tcp=r["z"], force_n=abs(r["delta"]), cx=cx, cy=cy, awl_len=awl_len_measured)
        log.info(f"AWL: force onset at TCP z={z_touch:.2f} (stopped {r['z']:.2f}) → measured awl length {awl_len_measured:.1f} mm "
                 f"(nominal {AWL_LEN:.0f}), force {abs(r['delta']):.2f} N")
        bus.update_data(awl=awl)
        # 9/17 사용자: 홈으로 가지 말고 콕 찍은 자리에서 HOVER 만 올라가 4번 노드에 넘긴다 (4번은 여기서 바로 시작)
        rb.movel(posx(cx, cy, r["z"] + HOVER, A, B, C), vel=[6.0, 6.0], acc=[10.0, 10.0])
        bus.publish_stage("probe_done")
        log.info("\n".join(["", "==================== 3번 노드 결과 (송곳 접촉) ====================",
                            f" 찍은 위치      : ({cx:.1f}, {cy:.1f})  (1번 노드 중심)",
                            f" 접촉 시 TCP 높이: z = {z_touch:.1f} mm   (멈춘 높이 {r['z']:.1f})",
                            f" 접촉 힘        : {abs(r['delta']):.2f} N",
                            f" 송곳 길이      : {awl_len_measured:.1f} mm  (패드 아래로 나온 길이, 명목 {AWL_LEN:.0f})",
                            "==================================================================", ""]))
        log.info("force_probe finished")
    except MotionFailed as e:
        log.error(str(e))
    except KeyboardInterrupt:
        log.info("Program Stopped")
        try:
            rb.stop(); rb.R.release_force(time=0.0); rb.R.release_compliance_ctrl()
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
