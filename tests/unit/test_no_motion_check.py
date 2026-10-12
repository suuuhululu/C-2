"""실물 없이 기록 경계·Depth 원본 보존·정답 누락을 검사한다."""

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.no_motion_check import READ_SERVICES, image_array, require_idle, save_rgbd, validate_truth


def test_truth_requires_human_stop_and_execution_evidence():
    value = dict(scene="reference_only", operator="현장 확인자", ground_truth="기준 블록 1개",
                 stop_method="실물 정지 확인", execution_end_method="실행 앱 종료 확인",
                 robot_physically_stopped=True, execution_ended=True, scene_ready=True)
    assert validate_truth(value, "reference_only") == value
    for key in ("operator", "ground_truth", "stop_method", "execution_end_method"):
        with pytest.raises(ValueError):
            validate_truth(dict(value, **{key: ""}), "reference_only")
    for key in ("robot_physically_stopped", "execution_ended", "scene_ready"):
        with pytest.raises(ValueError):
            validate_truth(dict(value, **{key: False}), "reference_only")
    with pytest.raises(ValueError):
        validate_truth(value, "fully_seated")


@pytest.mark.parametrize("bigendian", [0, 1])
def test_depth_preserves_zero_and_uint16_with_row_padding(bigendian):
    depth = np.array([[0, 1200], [65535, 400]], dtype=">u2" if bigendian else "<u2")
    data = b"".join(row.tobytes() + b"\x99\x99" for row in depth)
    message = SimpleNamespace(encoding="16UC1", width=2, height=2, step=6,
                              is_bigendian=bigendian, data=data)
    assert image_array(message).tolist() == [[0, 1200], [65535, 400]]
    with pytest.raises(ValueError):
        image_array(SimpleNamespace(**{**message.__dict__, "data": data[:-1]}))


def test_mismatched_frame_stamps_fail_before_writing_images(tmp_path, monkeypatch):
    def frame(encoding, data, sec):
        return SimpleNamespace(encoding=encoding, data=data, width=1, height=1,
                               step=len(data), is_bigendian=0,
                               header=SimpleNamespace(stamp=SimpleNamespace(sec=sec, nanosec=0)))
    message = SimpleNamespace(rgb=frame("rgb8", b"\x00\x01\x02", 1),
                              depth=frame("16UC1", b"\x00\x00", 2))
    with pytest.raises(ValueError, match="STAMP_MISMATCH"):
        save_rgbd(tmp_path, message)
    assert not list(tmp_path.iterdir())


def test_readonly_tool_has_no_motion_publishers_or_modbus_writes():
    assert {name for _, name, _ in READ_SERVICES} == {
        "GetRobotState", "CheckMotion", "GetDrlState", "GetCurrentVelj",
        "GetToolForce", "GetCurrentTcp", "GetCurrentTool"}
    tree = ast.parse(Path("scripts/no_motion_check.py").read_text())
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)}
    assert not calls & {"create_publisher", "publish", "write_register", "write_registers",
                        "send_goal_async", "movej", "movel", "move", "stop"}
    assert "read_holding_registers" in calls


def test_failed_reads_and_active_motion_cannot_confirm_idle():
    feedback = {"service_reads": [
        {"service": "/dsr01/dsr_controller2/system/get_robot_state", "status": "READ",
         "response": {"robot_state": 1}},
        {"service": "/dsr01/dsr_controller2/motion/check_motion", "status": "READ",
         "response": {"status": 0}}]}
    require_idle(feedback)
    feedback["service_reads"][1]["response"]["status"] = 2
    with pytest.raises(RuntimeError):
        require_idle(feedback)
    feedback["service_reads"][1]["response"]["status"] = 0
    feedback["service_reads"][1]["status"] = "UNREADABLE"
    with pytest.raises(RuntimeError):
        require_idle(feedback)
    feedback["service_reads"][1]["status"] = "READ"
    feedback["service_reads"].append({"service": "/dsr01/dsr_controller2/drl/get_drl_state",
                                     "status": "READ", "response": {"drl_state": 3}})
    require_idle(feedback)  # LAST는 기계적 종료 증거가 아니며 별도 사람 확인이 필요하다.
    for state in (0, 2):
        feedback["service_reads"][-1]["response"]["drl_state"] = state
        with pytest.raises(RuntimeError, match="PLAY_OR_HOLD"):
            require_idle(feedback)
