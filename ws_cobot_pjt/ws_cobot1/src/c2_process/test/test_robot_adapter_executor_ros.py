"""공정 executor에서 상태 조회 후 측정 I/O가 유지되는지 검사. 모션 서비스 없음."""
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest.mark.skipif(os.environ.get('C2_RUN_ADAPTER_ROS_TEST') != '1', reason='격리 ROS 환경 필요')
def test_status_then_measurement_preserves_executor_on_success_and_timeout(monkeypatch):
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from dsr_msgs2 import srv
    from std_msgs.msg import Float64MultiArray
    from c2_process.robot_adapter import DoosanRobotAdapter
    from c2_process.measurement_robot_adapter import RosMeasurementIO

    rclpy.init(args=[])
    namespace = '/executor_test_'+uuid4().hex
    owner = Node('process', namespace=namespace)
    driver = Node('fake_driver', namespace=namespace)
    prefix = namespace+'/dsr_controller2'
    failed = [False]
    delay = [0.]
    endpoints = [
        ('aux_control/get_current_posj', 'GetCurrentPosj', 'pos', [0., 90., 0., 0., 0., 0.]),
        ('aux_control/get_current_posx', 'GetCurrentPosx', 'task_pos_info',
         [Float64MultiArray(data=[426., 0., 330., 0., 180., 0., 0.])]),
        ('aux_control/get_tool_force', 'GetToolForce', 'tool_force', [0.]*6),
        ('system/get_robot_state', 'GetRobotState', 'robot_state', 1),
        ('motion/check_motion', 'CheckMotion', 'status', 0),
        ('aux_control/get_desired_posx', 'GetDesiredPosx', 'pos', [426., 0., 330., 0., 180., 0.]),
        ('tcp/get_current_tcp', 'GetCurrentTcp', 'info', 'GripperDA_v1'),
        ('tool/get_current_tool', 'GetCurrentTool', 'info', 'ToolWeight_1'),
    ]
    for path, kind, field, value in endpoints:
        def respond(request, response, field=field, value=value):
            if field == 'robot_state' and delay[0]:time.sleep(delay[0])
            response.success = not failed[0]
            setattr(response, field, value)
            return response
        driver.create_service(getattr(srv,kind), prefix+'/'+path, respond)
    adapter = object.__new__(DoosanRobotAdapter)
    adapter.node, adapter.log = owner, owner.get_logger()
    adapter.frame_id, adapter.tool_offset_m = 'c2_base', None
    adapter._srv = {kind:getattr(srv,kind) for _,kind,_,_ in endpoints}
    # 예전 DSR_ROBOT2 래퍼를 다시 사용하면 즉시 실패한다.
    adapter.R = SimpleNamespace()
    io = RosMeasurementIO(owner, prefix, .5)
    ticks = []
    owner.create_timer(.02, lambda:ticks.append(time.monotonic()))
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(owner)
    executor.add_node(driver)
    thread = threading.Thread(target=executor.spin)
    thread.start()
    try:
        deadline = time.monotonic()+3
        while not executor.is_spinning and time.monotonic()<deadline:time.sleep(.01)
        monkeypatch.setattr(rclpy, 'spin_until_future_complete',
            lambda *args,**kwargs:pytest.fail('실행 중인 공정에서 중첩 spin 호출'))
        state = adapter.observe()
        assert state.quality == 'VALID'
        assert state.joints_rad[1] == pytest.approx(1.57079632679)
        assert state.tcp_pose[0] == pytest.approx(.426)
        assert adapter._read_tool_tcp() == ('GripperDA_v1','ToolWeight_1')
        assert owner.executor is executor and owner in executor.get_nodes()
        assert io.read()['motion_status'] == 0  # 보고된 실제 실패 지점
        assert len(list(owner.clients)) == 6  # 측정 I/O만 남고 단발 상태 client는 정리
        measurement_clients = dict(io.clients)
        assert io.read()['robot_state'] == 1
        assert io.clients == measurement_clients  # 매 조회마다 연결을 새로 만들지 않음
        assert len(list(owner.clients)) == 6
        failed[0] = True
        assert adapter.observe().quality == 'UNKNOWN'
        assert owner.executor is executor
        failed[0] = False
        delay[0] = .2
        before = len(ticks)
        with pytest.raises(TimeoutError):
            adapter._call('system/get_robot_state',srv.GetRobotState,srv.GetRobotState.Request(),timeout=.05)
        time.sleep(.25)  # 늦은 응답 뒤에도 executor·타이머와 다음 요청 유지
        delay[0] = 0.
        assert len(ticks)>before
        assert owner.executor is executor
        assert io.read()['robot_state'] == 1
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(timeout=3)
        owner.destroy_node()
        driver.destroy_node()
        rclpy.shutdown()
