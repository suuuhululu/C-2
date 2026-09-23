"""REAL HMI가 저장하는 읽기 전용 제어기 관측 JSON.

이 파일은 속도·힘·모션 설정을 만들지 않고, 두산 제어기에서 실제로
읽은 값만 정규화한다. fixture·그리퍼 고정·드릴 전원·주변 간섭은
자동 관측값이 아니므로 이 JSON에 넣지 않는다.
"""
import math
import numbers

from .monitor_contract import now


CONTRACT = "c2-hardware-observation/1"
FIXED_TCP_ID = "GripperDA_v1"
FIXED_LOAD_ID = "ToolWeight_1"


def _finite_vector(value, size):
    return (isinstance(value, (list, tuple)) and len(value) == size
            and all(isinstance(item, numbers.Real) and not isinstance(item, bool)
                    and math.isfinite(item) for item in value))


def build_hardware_snapshot(config, observed=None, *, error=None):
    """Read-only ROS 응답을 저장 계약으로 변환하고 고정 TCP/load를 검사한다."""
    workcell = config.get("workcell", {}) if isinstance(config, dict) else {}
    prefix = config.get("controller_prefix") if isinstance(config, dict) else None
    expected_tcp = config.get("tcp_id", workcell.get("tcp_id")) if isinstance(config, dict) else None
    expected_load = config.get("load_id", workcell.get("load_id")) if isinstance(config, dict) else None
    if (not isinstance(prefix, str) or not prefix.startswith("/")
            or expected_tcp != FIXED_TCP_ID or expected_load != FIXED_LOAD_ID):
        raise ValueError("REAL 고정 controller_prefix/TCP/load 설정 불일치")

    base = {
        "contract": CONTRACT,
        "observed_at": now(),
        "controller_prefix": prefix.rstrip("/"),
        "state": "UNAVAILABLE",
        "errors": [],
        "observation": None,
    }
    if error is not None:
        base["errors"] = [str(error)]
        return base
    if not isinstance(observed, dict):
        base["errors"] = ["하드웨어 관측 응답 없음"]
        return base

    required_ints = ("robot_state", "robot_mode", "robot_system", "motion_status")
    errors = []
    for key in required_ints:
        if type(observed.get(key)) is not int:
            errors.append(key + " 정수 관측 없음")
    if observed.get("tcp_id") != FIXED_TCP_ID:
        errors.append(f"현재 TCP가 {FIXED_TCP_ID}가 아님")
    if observed.get("load_id") != FIXED_LOAD_ID:
        errors.append(f"현재 load가 {FIXED_LOAD_ID}가 아님")
    if not _finite_vector(observed.get("joints_deg"), 6):
        errors.append("현재 6축 관절 관측 없음")
    if not _finite_vector(observed.get("controller_tcp_posx"), 6):
        errors.append("현재 제어기 TCP 관측 없음")
    if observed.get("robot_system") != 0:
        errors.append("제어기가 REAL system이 아님")
    if observed.get("robot_mode") != 1:
        errors.append("제어기가 AUTO mode가 아님")
    if observed.get("robot_state") != 1 or observed.get("motion_status") != 0:
        errors.append("로봇이 STANDBY/정지 상태가 아님")

    # 자동 읽기 가능한 값만 보존한다. 실행 profile과 수동 확인값은 금지한다.
    base["observation"] = {
        "robot_state": observed.get("robot_state"),
        "robot_mode": observed.get("robot_mode"),
        "robot_system": observed.get("robot_system"),
        "motion_status": observed.get("motion_status"),
        "tcp_id": observed.get("tcp_id"),
        "load_id": observed.get("load_id"),
        "joints_deg": list(observed.get("joints_deg", [])),
        "controller_tcp_posx": list(observed.get("controller_tcp_posx", [])),
    }
    base["errors"] = errors
    base["state"] = "READY" if not errors else "NOT_READY"
    return base
