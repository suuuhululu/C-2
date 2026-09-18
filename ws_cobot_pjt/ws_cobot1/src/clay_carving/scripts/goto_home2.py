# 새 홈 = 양초 기준점 30 mm 위, 그리퍼 수직. 지금 자세를 읽고 (1) 충분히 높지 않으면 직선 상승 (2) 안전 높이에서 수평 이동+자세 변경 (3) 수직 하강.
import rclpy, time, math, sys
import numpy as np
from rclpy.node import Node
from dsr_msgs2.srv import MoveLine, GetCurrentPosx, GetCurrentTcp, GetCurrentTool, GetRobotState
DRY = "--dry" in sys.argv
HOME_V3 = [421.4, -62.6, 234.4, 3.2, -179.5, 3.9]      # 손끝 (422.2, -2.5, 234.4)
SAFE_Z = 300.0                                          # 수평 이동 중 툴의 가장 낮은 점(플랜지·TCP·손끝)이 이 위여야 함 (양초 윗면 204 + 96)
rclpy.init(); n = Node("goto_home2_tmp")
def call(srv, name, req, t=60.0):
    c = n.create_client(srv, name); assert c.wait_for_service(timeout_sec=5.0), name
    f = c.call_async(req); t0 = time.time()
    while rclpy.ok() and not f.done() and time.time() - t0 < t: rclpy.spin_once(n, timeout_sec=0.1)
    assert f.done(), f"timeout {name}"; return f.result()
def posx(): return list(call(GetCurrentPosx, "/dsr01/dsr_controller2/aux_control/get_current_posx", GetCurrentPosx.Request(ref=0)).task_pos_info[0].data[:6])
def R_of(A, B, C):
    A, B, C = (math.radians(v) for v in (A, B, C))
    Rz = lambda t: np.array([[math.cos(t), -math.sin(t), 0], [math.sin(t), math.cos(t), 0], [0, 0, 1]])
    Ry = lambda t: np.array([[math.cos(t), 0, math.sin(t)], [0, 1, 0], [-math.sin(t), 0, math.cos(t)]])
    return Rz(A) @ Ry(B) @ Rz(C)
def tool_points(p):
    R = R_of(*p[3:6]); v3 = np.array(p[:3])
    flange = v3 - R @ np.array([0, -60, 208]); pad = v3 + 60 * R[:, 1]
    return dict(flange=flange, v3=v3, pad=pad)
def movel(target, vel):
    req = MoveLine.Request(); req.pos = [float(v) for v in target]; req.vel = [float(vel[0]), float(vel[1])]; req.acc = [20.0, 10.0]
    req.time = 0.0; req.radius = 0.0; req.ref = 0; req.mode = 0; req.blend_type = 0; req.sync_type = 0
    if DRY: print("  (dry) movel", [round(v, 1) for v in target]); return True
    return call(MoveLine, "/dsr01/dsr_controller2/motion/move_line", req, t=180.0).success
tcp = call(GetCurrentTcp, "/dsr01/dsr_controller2/tcp/get_current_tcp", GetCurrentTcp.Request()).info
tool = call(GetCurrentTool, "/dsr01/dsr_controller2/tool/get_current_tool", GetCurrentTool.Request()).info
st = call(GetRobotState, "/dsr01/dsr_controller2/system/get_robot_state", GetRobotState.Request()).robot_state
p = posx(); pts = tool_points(p)
print(f"tcp={tcp} tool={tool} state={st}")
print("now v3 =", [round(v, 1) for v in p], " pad =", np.round(pts['pad'], 1), " flange =", np.round(pts['flange'], 1))
assert tcp == "GripperDA_v3" and st == 1, "TCP 나 상태가 다름 → 중단 (TP 에서 GripperDA_v3 / STANDBY 확인)"
low = min(v[2] for v in pts.values())
# 1) 상승: 툴의 가장 낮은 점이 SAFE_Z 위가 되도록 지금 자세 유지한 채 base +Z 로
if low < SAFE_Z:
    dz = SAFE_Z - low
    print(f"1) 직선 상승 {dz:.0f} mm (가장 낮은 점 z {low:.1f} → {SAFE_Z:.0f})")
    assert movel([p[0], p[1], p[2] + dz, p[3], p[4], p[5]], [20, 10]); p = posx()
else:
    print("1) 이미 안전 높이 → 상승 생략")
# 2) 안전 높이에서 목표 xy·자세로 (목표 자세에서 가장 낮은 점은 손끝 = v3 z 이므로 v3 z 를 SAFE_Z 로)
mid = [HOME_V3[0], HOME_V3[1], max(SAFE_Z, p[2]), HOME_V3[3], HOME_V3[4], HOME_V3[5]]
print("2) 수평 이동 + 세우기 →", [round(v, 1) for v in mid]); assert movel(mid, [20, 10]); p = posx()
# 3) 수직 하강
print("3) 수직 하강 →", HOME_V3); assert movel(HOME_V3, [15, 10]); p = posx()
pts = tool_points(p)
print("done v3 =", [round(v, 1) for v in p], " pad =", np.round(pts['pad'], 1))
n.destroy_node(); rclpy.shutdown()
