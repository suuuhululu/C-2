# 실기 확인 스크립트 — DoosanRobotAdapter 를 실제 브링업(sodreal)에 붙여 4가지를 본다. 로봇을 움직이니 옆에서 지켜본다.
#   1) select_tool_profile: GripperDA_v1(그리퍼 기본 TCP, 패드) / ToolWeight_1 적용 확인
#      --awl <mm> 를 주면 송곳이 패드 아래로 그만큼 나온 것으로 보고 소프트웨어 오프셋(툴 −Y)을 건다
#   2) move: 현재 자리에서 위로 20 mm, 다시 내려오기 (26 mm/s)
#   3) 이동 중 취소: 위로 60 mm 를 8 mm/s 로 보내고 1.5 s 뒤 cancel → STOPPED 로 돌아오는지, 정지 후 STANDBY 인지
#   4) probe_touch: 현재 자리에서 아래로 최대 max_mm 힘 감시 하강 (지점토가 아래에 있을 때만, --touch 옵션)
# 실행 (ws_dsr·ws_cobot1 source 된 터미널, 브링업 켜진 상태):
#   python3 test/real_adapter_check.py            # 1~3 만
#   python3 test/real_adapter_check.py --touch 40 # 1~4, 아래로 최대 40 mm
#   python3 test/real_adapter_check.py --awl 40 --touch 60   # 송곳 40 mm 돌출 가정 + 접촉
#   python3 test/real_adapter_check.py --awl 40 --pre 150 --touch 80   # 먼저 150 mm 빨리 내려간 뒤 80 mm 힘 감시
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rclpy  # noqa: E402
from c2_process.robot_adapter import DoosanRobotAdapter, pose_to_posx  # noqa: E402

TRAVEL = dict(id="travel", vel_mm_s=26.0, acc_mm_s2=50.0, completion_timeout_s=30.0, pos_tol_mm=2.0)
SLOW = dict(id="slow", vel_mm_s=8.0, acc_mm_s2=16.0, completion_timeout_s=30.0, pos_tol_mm=2.0)
TOUCH = dict(touch_force_n=1.0, touch_speed_mm_s=4.0, hard_limit_n=4.5, settle_s=1.5, settle_mm=4.0)


def up(pose, mm):
    p = list(pose); p[2] += mm / 1000.0
    return p


def main():
    touch_mm = float(sys.argv[sys.argv.index("--touch") + 1]) if "--touch" in sys.argv else None
    rclpy.init()
    node = rclpy.create_node("adapter_check", namespace="dsr01")
    log = node.get_logger()
    ad = DoosanRobotAdapter(node)
    frame = ad.frame_id
    results = []

    def rec(name, r):
        results.append((name, r.outcome, r.error_code, r.message))
        log.info(f"[{name}] {r.outcome} {r.error_code} {r.message} {({k: v for k, v in r.observed_state.items() if k != 'tcp_pose'})}")
        return r

    # 1) 툴·TCP
    r = rec("select_tool_profile", ad.select_tool_profile("GripperDA_v1", "ToolWeight_1", profile_version=1))
    if "--awl" in sys.argv:
        awl_mm = float(sys.argv[sys.argv.index("--awl") + 1])
        ad.set_tool_offset([0.0, -awl_mm / 1000.0, 0.0])      # 송곳은 툴 −Y 로 나온다 (9/17 확인)
    if not r.ok:
        log.error("툴/TCP 실패 → 중단"); return finish(node, results)
    st = ad.observe()
    log.info(f"observe: state={st.robot_state} tcp(mm)={[round(v, 1) for v in pose_to_posx(st.tcp_pose)]} F={st.force_n}")
    if st.robot_state != 1:
        log.error(f"로봇 상태 {st.robot_state} (STANDBY 아님) → 중단"); return finish(node, results)
    home = list(st.tcp_pose)

    # 2) 위로 20 mm, 다시 복귀
    r = rec("move up 20", ad.move(up(home, 20), frame, TRAVEL, 30.0, None))
    if not r.ok:
        return finish(node, results)
    rec("move back", ad.move(home, frame, TRAVEL, 30.0, None))

    # 3) 이동 중 취소
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    t0 = time.monotonic()
    r = rec("move 60 + cancel@1.5s", ad.move(up(home, 60), frame, SLOW, 30.0, cancel))
    dt = time.monotonic() - t0
    st = ad.observe()
    log.info(f"  취소 반환까지 {dt:.2f}s, 정지 후 상태={st.robot_state}, 높이 변화 {(st.tcp_pose[2] - home[2]) * 1000:.1f} mm "
             f"(1.5 s × 8 mm/s ≈ 12 mm 근처면 정상)")
    time.sleep(0.5)
    rec("move back after cancel", ad.move(home, frame, TRAVEL, 30.0, None))

    # 4) 힘 감시 하강 (옵션). --pre <mm> 를 주면 그만큼은 26 mm/s 로 빨리 내려간 뒤 저속 힘 감시를 시작한다
    if touch_mm:
        if "--pre" in sys.argv:
            # 9/18 bag 1829: 빨리 내려가는 구간에 힘 감시가 없어 양초를 1 mm 뚫고 들어갔다 → 이 구간도 힘 감시(10 mm/s, 4.5 N)로.
            pre = float(sys.argv[sys.argv.index("--pre") + 1])
            fast = dict(TOUCH, touch_speed_mm_s=10.0, touch_force_n=3.0, soft_samples=2)   # 빠른 구간: 3 N 연속 2회 또는 급증/4.5 N
            r = rec(f"pre-descend {pre:.0f}mm (guarded)", ad.probe_touch([0.0, 0.0, -1.0], pre / 1000.0, fast, 60.0, None))
            if r.observed_state.get("contact"):
                log.warn("  빠른 하강 구간에서 이미 닿음 → 접촉 시험은 이 지점 결과로 대신함")
                rec("move back after touch", ad.move(home, frame, TRAVEL, 30.0, None))
                return finish(node, results)
            if r.error_code not in ("NONE", "VALIDATION_FAILED"):     # VALIDATION_FAILED = 안 닿고 끝까지 내려감 (정상)
                return finish(node, results)
        r = rec(f"probe_touch down {touch_mm:.0f}mm", ad.probe_touch([0.0, 0.0, -1.0], touch_mm / 1000.0, TOUCH, 60.0, None))
        if r.observed_state.get("contact"):
            c = r.observed_state
            log.info(f"  접촉 TCP z={pose_to_posx(c['tcp_pose'])[2]:.1f} mm, 힘 시작 z={pose_to_posx(c['onset_pose'])[2]:.1f}, "
                     f"힘 {c['force_n']:.2f} N, 내려간 거리 {c['travelled_m'] * 1000:.1f} mm")
        rec("move back after touch", ad.move(home, frame, TRAVEL, 30.0, None))
    return finish(node, results)


def finish(node, results):
    node.get_logger().info("=== 결과 ===\n" + "\n".join(f" {n:<26} {o:<9} {c:<20} {m}" for n, o, c, m in results))
    node.destroy_node(); rclpy.shutdown()


if __name__ == "__main__":
    main()
