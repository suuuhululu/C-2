# 실기 확인(로봇 이동 없음): 어댑터 inverse_kinematics(제어기 ikin) 와 joint_check.check_path_joints.
#  1) 지금 도구 끝 자세를 IK 로 풀어 실제 관절과 비교  2) 양초 둘레 궤도(툴 Y 가 축을 향하며 −90°→+180°) 경로를 검사
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rclpy  # noqa: E402
from c2_process.robot_adapter import DoosanRobotAdapter, matrix_to_quat  # noqa: E402
from c2_process.joint_check import check_path_joints  # noqa: E402

CX, CY, R, ZC = 0.4218, 0.0001, 0.034, 0.188
OFFSET = [0.00085, -0.0998, 0.0]


def upright(yaw_deg):
    t = math.radians(yaw_deg)
    x = [-math.cos(t), -math.sin(t), 0.0]; y = [-math.sin(t), math.cos(t), 0.0]; z = [0.0, 0.0, -1.0]
    return matrix_to_quat([[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]])


def orbit_path(th_from, th_to, n, clear=0.025):
    wps = []
    for i in range(n):
        th = th_from + (th_to - th_from) * i / (n - 1)
        t = math.radians(th)
        tip = [CX + (R + clear) * math.cos(t), CY + (R + clear) * math.sin(t), ZC]
        wps.append(tip + upright(th))
    return dict(schema_version=2, segments=[dict(segment_id="orbit", stroke_id="st1", kind="CUT", waypoints=wps, motion_profile_id="cut")])


def main():
    rclpy.init(); node = rclpy.create_node("joint_check_real", namespace="dsr01"); log = node.get_logger()
    ad = DoosanRobotAdapter(node)
    st = ad.observe()
    q_now = [math.degrees(v) for v in st.joints_rad]
    log.info(f"state {st.robot_state}, joints now {[round(v, 1) for v in q_now]}, tcp {[round(v, 4) for v in st.tcp_pose[:3]]}")
    # 1) 지금 자세 IK (오프셋 없음: 관측 tcp_pose 는 손끝 기준)
    t0 = time.time(); q = ad.inverse_kinematics(st.tcp_pose, None, q_now); dt = time.time() - t0
    if q is None:
        log.error("IK 실패 (지금 자세)"); return
    err = max(abs(q[k] - q_now[k]) for k in range(6))
    log.info(f"IK(now) = {[round(v, 1) for v in q]}  최대 오차 {err:.2f}°  ({dt * 1000:.0f} ms, sol_space {ad._ik_space})")
    # 2) 궤도 경로 검사 (도구 끝 좌표 + 실측 오프셋)
    for name, path in (("orbit -90→180 (270°)", orbit_path(-90, 180, 55)), ("orbit -90→-270 (반대 180°)", orbit_path(-90, -270, 37))):
        t0 = time.time()
        r = check_path_joints(path, ad, OFFSET, st.joints_rad, j6_margin_deg=10.0)
        o = r.observed_state
        log.info(f"{name}: {r.outcome}/{r.error_code} {r.message} ({time.time() - t0:.1f}s) "
                 f"J6 {o.get('j6_start_deg')}→{o.get('j6_end_deg')} 누적 {o.get('j6_total_rotation_deg')} 검사점 {o.get('checked_waypoints')} worst {o.get('worst')}")
    node.destroy_node(); rclpy.shutdown()


if __name__ == "__main__":
    main()
