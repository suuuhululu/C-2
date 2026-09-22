"""격리된 ROS 대역 드라이버로 이동·IK 중 executor 유지 확인. 실물에 연결하지 않는다."""
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.mark.skipif(os.environ.get('C2_RUN_ADAPTER_ROS_TEST') != '1', reason='격리 ROS 환경 필요')
def test_motion_and_ikin_preserve_running_executor(monkeypatch):
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from dsr_msgs2 import srv
    from std_msgs.msg import Float64MultiArray
    from c2_process.robot_adapter import DoosanRobotAdapter, posx_to_pose

    rclpy.init(args=[])
    namespace = '/motion_test_' + uuid4().hex
    owner = Node('process', namespace=namespace)
    driver = Node('fake_driver', namespace=namespace)
    prefix = namespace + '/dsr_controller2/'
    current = [0.] * 6
    target = current[:]
    started = [None]
    closed = [False]
    sent = []
    stops = []
    stop_works = [True]
    force_reads = [0]
    probe_active = [False]
    def update():
        if started[0] is not None:
            elapsed = time.monotonic() - started[0]
            if elapsed >= .7:
                current[:] = target
                started[0] = None
            elif closed[0]:
                current[0] = target[0] + 10.
            else:
                current[:] = target
        return started[0] is not None
    def state(req, res):
        res.robot_state = 2 if update() else 1
        res.success = True
        return res
    def motion(req, res):
        res.status = 2 if update() else 0
        res.success = True
        return res
    def position(req, res):
        update()
        res.task_pos_info = [Float64MultiArray(data=current + [0.])]
        res.success = True
        return res
    def move(req, res):
        closed[0] = hasattr(req, 'pos_cnt')
        target[:] = list(req.pos[-1].data) if closed[0] else list(req.pos)
        started[0] = time.monotonic()
        sent.append('spline' if closed[0] else 'line')
        res.success = True
        return res
    def stop(req, res):
        stops.append(time.monotonic())
        if stop_works[0]:
            started[0] = None
        res.success = True
        return res
    def force(req, res):
        force_reads[0] += 1
        res.tool_force = [-10. if probe_active[0] and force_reads[0] > 8 else 0.] + [0.] * 5
        res.success = True
        return res
    def singularity(req, res):
        assert req.mode == 0
        res.success = True
        return res
    def solution(req, res):
        res.sol_space = 0
        res.success = True
        return res
    def ikin(req, res):
        res.conv_posj = [1.] * 6
        res.success = True
        return res
    definitions = [
        ('motion/set_singularity_handling', 'SetSingularityHandling', singularity),
        ('aux_control/get_tool_force', 'GetToolForce', force),
        ('system/get_robot_state', 'GetRobotState', state),
        ('motion/check_motion', 'CheckMotion', motion),
        ('aux_control/get_current_posx', 'GetCurrentPosx', position),
        ('motion/move_line', 'MoveLine', move),
        ('motion/move_spline_task', 'MoveSplineTask', move),
        ('motion/move_stop', 'MoveStop', stop),
        ('aux_control/get_solution_space', 'GetSolutionSpace', solution),
        ('motion/ikin', 'Ikin', ikin),
    ]
    for path, kind, callback in definitions:
        driver.create_service(getattr(srv, kind), prefix + path, callback)
    ticks = []
    owner.create_timer(.02, lambda: ticks.append(time.monotonic()))
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(owner)
    executor.add_node(driver)
    thread = threading.Thread(target=executor.spin)
    thread.start()
    try:
        deadline = time.monotonic() + 3
        while not executor.is_spinning and time.monotonic() < deadline:
            time.sleep(.01)
        def forbidden(*args, **kwargs):
            pytest.fail('실행 중인 executor에 중첩 spin 발생')
        monkeypatch.setattr(rclpy, 'spin_until_future_complete', forbidden)
        adapter = DoosanRobotAdapter(owner, initialization_timeout_s=1.)
        end = posx_to_pose([20., 0., 0., 0., 0., 0.])
        profile = {'vel_mm_s': 10., 'pos_tol_mm': .1}
        assert adapter.inverse_kinematics(end, None, [0.] * 6) == [1.] * 6
        result = adapter.move(end, 'c2_base', profile, 8., None)
        assert result.ok, result
        before = len(ticks)
        result = adapter.move_spline([end, posx_to_pose([30., 0., 0., 0., 0., 0.]), end],
                                     'c2_base', profile, 8., None)
        assert result.ok, result
        assert len(ticks) > before
        assert sent == ['line', 'spline']
        assert adapter.stop({'mode': 1}, 5.).observed_state['stop_confirmed'] is True
        assert owner.executor is executor and owner in executor.get_nodes()
        assert not list(owner.clients)

        # 실제 접촉 함수의 시작 전/중 조회도 동일 executor에서 처리한다.
        force_reads[0] = 0
        probe_active[0] = True
        result = adapter.probe_touch([1., 0., 0.], .01,
                                      {'touch_speed_mm_s': 1., 'touch_force_n': 1.}, 3., None)
        assert result.ok and result.observed_state['stop_confirmed'], result
        assert force_reads[0] >= 9
        probe_active[0] = False

        # 공정 StopProcess 경로에서 공유 cancel 전달 → 이동 반환 전 실제 QSTOP.
        from types import SimpleNamespace
        from c2_process.node import ProcessCoordinator, _ActiveRun
        coordinator = ProcessCoordinator(runtime_mode='REAL', real_adapter=adapter, measurement_only=True)
        cancel = threading.Event()
        context = SimpleNamespace(stop_profile={'mode': 1, 'confirmation_timeout_s': 1.})
        active = _ActiveRun('req', 'run', cancel, adapter, context)
        coordinator._active = active
        results = []
        before_stops, before_ticks = len(stops), len(ticks)
        worker = threading.Thread(target=lambda: results.append(adapter.move(
            posx_to_pose([60., 0., 0., 0., 0., 0.]), 'c2_base', profile, 5., cancel)))
        worker.start()
        until = time.monotonic() + 2.
        while started[0] is None and worker.is_alive() and time.monotonic() < until:
            time.sleep(.01)
        assert started[0] is not None
        assert coordinator.stop('run').accepted
        worker.join(timeout=3.)
        assert not worker.is_alive() and results[0].outcome == 'STOPPED', results
        assert len(stops) > before_stops and results[0].observed_state['stop_confirmed']
        assert len(ticks) > before_ticks
        assert coordinator._finalize_stop(active, results[0]).outcome == 'STOPPED'
        # stop 접수만 성공하고 로봇이 계속 움직이는 경우에는 STOPPED가 될 수 없다.
        stop_works[0] = False
        started[0] = time.monotonic() + 5.
        unconfirmed = adapter.stop({'mode': 1}, .3)
        assert unconfirmed.outcome == 'UNKNOWN' and not unconfirmed.observed_state['stop_confirmed']
        started[0] = None
        assert owner.executor is executor and not list(owner.clients)
        for service in list(driver.services):
            if service.srv_name.endswith('/motion/set_singularity_handling'):
                driver.destroy_service(service)
        began = time.monotonic()
        # DDS가 삭제된 서비스를 잠시 캐시하면 접수 후 timeout일 수도 있다.
        with pytest.raises((RuntimeError, TimeoutError), match='not available|timed out'):
            DoosanRobotAdapter(owner, initialization_timeout_s=.1)
        assert time.monotonic() - began < 1.5
        assert owner.executor is executor and not list(owner.clients)
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(timeout=3)
        owner.destroy_node()
        driver.destroy_node()
        rclpy.shutdown()
