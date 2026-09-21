"""현재 main 제어 handler/실제 SIM 측정 함수와 HMI 저장·BIND 경계. ROS/로봇 비구동."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import threading

import pytest

ROOT = Path(__file__).resolve().parents[2] / 'ws_cobot1/src'
for package in ('c2_path', 'c2_process'):
    sys.path.insert(0, str(ROOT / package))

from app.monitor_contract import uid
from app.preparation import PreparationService, input_config
from app.ros_preparation import display_result
from app.storage import Storage
from c2_path.pipeline import matching_test_profile, validate_profile
from c2_process.node import ProcessCoordinator
from c2_process.preparation_action import AssetResolver, PreparationActionHandler, make_simulation_runner_factory


@pytest.mark.parametrize('bind_failure', [False, True])
@pytest.mark.parametrize('transport', ['direct', 'ros'])
def test_hmi_measure_store_bind_with_main_handler(tmp_path, bind_failure, transport):
    if transport == 'ros':
        if os.environ.get('C2_RUN_HMI_PREPARE_ROS') != '1':
            pytest.skip('격리 ROS 왕복은 C2_RUN_HMI_PREPARE_ROS=1로 실행')
        assert os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST'
    async def scenario():
        store = Storage(tmp_path / 'hmi')
        base = store.profile(matching_test_profile())
        coordinator = ProcessCoordinator()
        handler = PreparationActionHandler(coordinator,
            AssetResolver(fetch=lambda aid, timeout: store.read_asset(aid)), tmp_path / 'process.db',
            make_simulation_runner_factory()(coordinator))
        calls = []
        callbacks = []
        class Peer:
            async def prepare_raw(self, goal, feedback):
                callbacks.append(feedback)
                calls.append(deepcopy(goal))
                events = []
                result = await asyncio.to_thread(handler.execute, goal, events.append)
                for event in events:
                    await feedback(event)
                if goal['operation'] == 'BIND_SNAPSHOT' and bind_failure:
                    result.update(outcome='FAILED', error_code='NOT_READY', snapshot_bound=False)
                return result
        peer = Peer()
        server = executor = thread = None
        if transport == 'ros':
            import rclpy
            from rclpy.executors import MultiThreadedExecutor
            from c2_process.node import create_ros_node
            from app.ros_bridge import RosBridge
            rclpy.init(args=[])
            server = create_ros_node(preparation_runner_factory=make_simulation_runner_factory(),
                preparation_resolver=handler.resolver, preparation_journal_path=tmp_path/'ros.db')
            executor = MultiThreadedExecutor(num_threads=4)
            executor.add_node(server)
            thread = threading.Thread(target=executor.spin, daemon=True)
            thread.start()
            async def emit(kind, value):
                pass
            bridge = RosBridge(emit)
            await bridge.start()
            assert await asyncio.to_thread(bridge.preparation_client.wait_for_server, timeout_sec=10.)
            async def send(goal, feedback):
                calls.append(deepcopy(goal))
                result = await bridge.prepare_raw(goal, feedback)
                if goal['operation'] == 'BIND_SNAPSHOT' and bind_failure:
                    result.update(outcome='FAILED', error_code='NOT_READY', snapshot_bound=False)
                return result
            peer = SimpleNamespace(prepare_raw=send, cancel_preparation=bridge.cancel_preparation)
        owner = SimpleNamespace(store=store, transport='ros', peer=peer, profile=base, fresh=lambda: True)
        service = PreparationService(owner)
        service.config = input_config(store, base['payload'])
        goal = dict(request_id=uid(), preparation_id=uid(), measurement_id=uid(), source_mode='SIMULATION',
                    input_profile_snapshot_id=service.config['id'], input_profile_sha256=service.config['sha256'],
                    height_m=.15)
        service.current = dict(request_id=goal['request_id'], goal=goal, state='ACCEPTED', feedback=[])
        try:
            await service.run_ros(goal, asyncio.Event())
            if server:
                handler.success = deepcopy(server.preparation.success)
                coordinator = server.coordinator
        finally:
            if server:
                await bridge.close()
                executor.shutdown(timeout_sec=3)
                thread.join(3)
                server.destroy_node()
                rclpy.shutdown()
        record = service.current
        assert [g['operation'] for g in calls] == ['MEASURE', 'BIND_SNAPSHOT'], record
        assert calls[0]['request_id'] != calls[1]['request_id']
        raw = json.loads(store.read_asset(record['measurement_record']['id']))
        assert raw['contract'] == 'prepare-workpiece-result/1'
        assert raw['result'] == handler.success
        assert raw['result']['contact_indices'] == list(range(9))
        if bind_failure:
            assert record['state'] == 'FAILED' and not service.ready()
            assert owner.profile == base
        else:
            assert record['state'] == 'SUCCEEDED' and service.ready(), record
            validate_profile(owner.profile['payload'])
            assert owner.profile['payload']['contract'].endswith('/2')
            assert coordinator._preparation_bindings[goal['preparation_id']] == (
                owner.profile['id'], owner.profile['sha256'])
            store.recover_preparation()
            assert store.preparation(goal['request_id'])['binding_status'] == 'REPREPARATION_REQUIRED'
        handler.db.close()
        if callbacks:
            service.current = dict(request_id=uid(), state='ACCEPTED', feedback=[])
            await callbacks[0](dict(stage='COMPLETE'))
            assert service.current['feedback'] == []  # 이전 Goal의 늦은 Feedback은 새 준비를 덮지 않음
    asyncio.run(scenario())


@pytest.mark.parametrize('defect', ['points', 'quaternion', 'time', 'validity'])
def test_bad_success_cannot_become_path_profile(defect):
    sample = json.loads((ROOT / 'c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())
    raw = sample['result']
    if defect == 'points': raw['contact_indices'] = [0, 1]
    if defect == 'quaternion': raw['contact_tip_poses'][0]['orientation']['w'] = 4.
    if defect == 'time': raw['measured_at'] = dict(sec=0, nanosec=0)
    if defect == 'validity': raw['validity'] = 'ESTIMATED'
    with pytest.raises(ValueError):
        display_result(raw, sample['goal'])


@pytest.mark.parametrize('when', ['before_send', 'late_success', 'timeout'])
def test_cancel_or_timeout_never_binds_late_success(tmp_path, when):
    async def scenario():
        store = Storage(tmp_path)
        base = store.profile(matching_test_profile())
        sample = json.loads((ROOT / 'c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())
        cancel = asyncio.Event()
        release = asyncio.Event()
        calls, canceled = [], []
        class Peer:
            async def prepare_raw(self, goal, feedback):
                calls.append(goal['operation'])
                if when == 'late_success': cancel.set()
                if when == 'timeout': await release.wait()
                return deepcopy(sample['result'])
            async def cancel_preparation(self, rid):
                canceled.append(rid)
                release.set()
        owner = SimpleNamespace(store=store, transport='ros', peer=Peer(), profile=base, fresh=lambda: True)
        service = PreparationService(owner)
        service.config = input_config(store, base['payload'])
        service.timeout_s = .01
        goal = dict(sample['goal'], height_m=.15)
        service.current = dict(request_id=goal['request_id'], goal=goal, state='ACCEPTED', feedback=[])
        if when == 'before_send': cancel.set()
        await service.run_ros(goal, cancel)
        assert service.current['state'] == 'UNKNOWN'
        assert not service.ready() and owner.profile == base
        assert 'BIND_SNAPSHOT' not in calls
        if when == 'before_send': assert calls == []
        if when == 'timeout': assert canceled == [goal['request_id']]
    asyncio.run(scenario())
