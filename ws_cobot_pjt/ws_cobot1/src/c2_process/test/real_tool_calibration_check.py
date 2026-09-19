# 실기 확인: tool_calibration.measure_tool_tip (3점) → verify_tool_tip (1점). 그리퍼 세운 자세, 드릴 툴 -Y 돌출, TCP GripperDA_v1.
# 사용: python3 test/real_tool_calibration_check.py [--top 0.2334] [--cx 0.4224 --cy -0.0026] [--no-verify]
# 시작 자세: 원통 위 어디든 (같은 높이에서 바깥으로 나간 뒤 내려간다). 그리퍼 열기·닫기 명령 없음.
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rclpy  # noqa: E402
from c2_process.robot_adapter import DoosanRobotAdapter  # noqa: E402
from c2_process.tool_calibration import TipCalibration, measure_tool_tip, verify_tool_tip  # noqa: E402


def opt(name, default):
    return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


class Ctx:
    def __init__(self):
        self.cancel = threading.Event()


def main():
    rclpy.init()
    node = rclpy.create_node("tool_calib_check", namespace="dsr01")
    log = node.get_logger()
    ad = DoosanRobotAdapter(node)
    workcell = dict(axis_xy_m=[opt("--cx", 0.4224), opt("--cy", -0.0026)], radius_m=0.034, top_z_m=opt("--top", 0.2334))
    profiles = dict(travel=dict(id="travel", vel_mm_s=20.0, acc_mm_s2=20.0, pos_tol_mm=2.0, completion_timeout_s=90.0),
                    tip_touch=dict(touch_force_n=0.8, touch_speed_mm_s=2.0, touch_step_n=1.5, hard_limit_n=2.5))
    out = {}
    try:
        r = ad.select_tool_profile("GripperDA_v1", "ToolWeight_1", profile_version=1)
        log.info(f"select_tool_profile: {r.outcome} {r.observed_state}")
        if not r.ok:
            return
        st = ad.observe()
        log.info(f"state {st.robot_state}, tcp_pose {[round(v, 4) for v in st.tcp_pose[:3]]}")
        if st.robot_state != 1:
            log.error("STANDBY 아님 → 중단"); return
        t0 = time.time()
        r = measure_tool_tip(ad, workcell, profiles, Ctx())
        log.info(f"measure_tool_tip → {r.outcome}/{r.error_code} step={r.completed_step} msg={r.message} ({time.time() - t0:.0f}s)")
        out["measure"] = dict(outcome=r.outcome, error_code=r.error_code, message=r.message, observed=r.observed_state)
        if not r.ok:
            return
        calib = TipCalibration(**r.observed_state["calibration"])
        log.info(f"CALIB projection {calib.projection_m * 1000:.1f} mm, lateral_x {calib.lateral_x_m * 1000:+.1f} mm, "
                 f"rms {calib.residual_rms_m * 1000:.2f} mm, side {calib.side}, offset {calib.offset_tool_m}")
        if "--no-verify" not in sys.argv:
            t0 = time.time()
            r2 = verify_tool_tip(ad, workcell, profiles, calib, Ctx(), tol_m=0.001)
            log.info(f"verify_tool_tip → {r2.outcome}/{r2.error_code} {r2.message} ({time.time() - t0:.0f}s) tool_offset now {ad.tool_offset_m}")
            out["verify"] = dict(outcome=r2.outcome, error_code=r2.error_code, message=r2.message, observed=r2.observed_state)
    finally:
        p = os.path.expanduser("~/collaborative/ws_cobot_pjt/ws_dsr/tool_calibration_check_0919.json")
        json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
        node.destroy_node(); rclpy.shutdown()


if __name__ == "__main__":
    main()
