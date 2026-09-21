"""실제 ObservationCache와 모의 ROS client로 관측 공급만 검사한다. 모션 없음."""
from concurrent.futures import Future
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c2_process.node import ObservationCache
from c2_process import process_state_observer as module


class Pending(Future):
    # 취소 직후에도 네트워크 응답이 늦게 도착하는 경우를 재현한다.
    def cancel(self):return False


class Client:
    def __init__(self):self.ready = True; self.calls = []
    def service_is_ready(self):return self.ready
    def call_async(self, request):
        future = Pending()
        self.calls.append((request, future))
        return future


class Node:
    def __init__(self):
        self.observations = ObservationCache()
        self.coordinator = NS(runtime_mode='REAL')
        self.clients = {}; self.timers = []; self.destroyed = []
    def create_client(self, kind, name, **kwargs):
        client = Client(); self.clients[name] = client
        return client
    def create_timer(self, period, callback, **kwargs):
        timer = NS(period=period, callback=callback)
        self.timers.append(timer)
        return timer
    def destroy_timer(self, timer):self.destroyed.append(timer)
    def destroy_client(self, client):self.destroyed.append(client)
    # create_publisher/create_subscription/create_service는 제공하지 않는다.


@pytest.fixture
def setup(monkeypatch):
    clock = NS(now=100.)
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(module.time, 'time_ns', lambda: int((1_800_000_000+clock.now)*1e9))
    types = NS(GetCurrentPosj=NS(Request=NS), GetCurrentPosx=NS(Request=NS),
               GetRobotState=NS(Request=NS))
    monkeypatch.setitem(sys.modules, 'dsr_msgs2.srv', types)
    monkeypatch.setitem(sys.modules, 'rclpy.callback_groups', NS(MutuallyExclusiveCallbackGroup=NS))
    node = Node()
    config = dict(controller_prefix='/dsr01/dsr_controller2', service_timeout_s=.5,
                  guards={'max_state_age_s': .5})
    observer = module.start_process_state_observer(node, config)
    return node, config, observer, clock


def finish(observer, *, x=426., code=1, failed=None):
    replies = {
        'joints': NS(success=True, pos=[0., 90., -90., 45., 30., 180.]),
        'tcp': NS(success=True, task_pos_info=[NS(data=[x, 100., 330., 0., 180., 0.])]),
        'robot': NS(success=True, robot_state=code),
    }
    for key, (client, _) in observer.clients.items():
        reply = replies[key]
        if key == failed:reply.success = False
        client.calls[-1][1].set_result(reply)


def test_query_to_existing_cache_uses_contract_units_and_original_tcp(setup):
    node, config, observer, clock = setup
    assert len(node.timers) == 1 and node.timers[0].period == .2
    assert all(not client.calls for client, _ in observer.clients.values())
    observer._tick()
    assert node.observations.values()['joints_quality'] == 'UNKNOWN'
    clock.now += .05
    finish(observer)
    values = node.observations.values()
    assert values['joints'] == pytest.approx([0., math.pi/2, -math.pi/2, math.pi/4, math.pi/6, math.pi])
    assert values['tcp_pose'][:3] == pytest.approx([.426, .1, .330])
    assert sum(v*v for v in values['tcp_pose'][3:]) == pytest.approx(1.)
    assert values['frame_id'] == 'c2_base' and values['tcp_quality'] == 'VALID'
    assert values['robot_mode'] == 'UNKNOWN' and values['temperature_quality'] == 'UNSUPPORTED'
    stamp = values['tcp_stamp_ns']
    clock.now += .1
    assert node.observations.values()['tcp_stamp_ns'] == stamp
    clock.now += .5
    assert node.observations.values()['tcp_quality'] == 'STALE'
    assert set(node.clients) == {config['controller_prefix']+'/'+name for name in (
        'aux_control/get_current_posj', 'aux_control/get_current_posx', 'system/get_robot_state')}


def test_pending_queries_do_not_overlap_or_block_and_late_reply_is_ignored(setup):
    node, _, observer, clock = setup
    observer._tick()
    first = {k:c.calls[-1][1] for k,(c, _) in observer.clients.items()}
    clock.now += .2; observer._tick()
    assert all(len(c.calls) == 1 for c, _ in observer.clients.values())
    clock.now += .4; observer._tick()
    assert all(len(c.calls) == 2 for c, _ in observer.clients.values())
    finish(observer, x=450.)
    for future in first.values():future.set_exception(ConnectionError('늦은 이전 실패'))
    assert node.observations.values()['tcp_pose'][0] == pytest.approx(.450)


@pytest.mark.parametrize('failure', ['unavailable', 'rejected', 'nan', 'unknown_state', 'timeout', 'exception'])
def test_failure_invalidates_cached_values_and_next_cycle_recovers(setup, failure):
    node, _, observer, clock = setup
    observer._tick(); finish(observer)
    assert node.observations.values()['tcp_quality'] == 'VALID'
    clock.now += .2
    if failure == 'unavailable':observer.clients['tcp'][0].ready = False
    observer._tick()
    if failure == 'rejected':finish(observer, failed='tcp')
    elif failure == 'nan':finish(observer, x=math.nan)
    elif failure == 'unknown_state':finish(observer, code=99)
    elif failure == 'exception':observer.clients['tcp'][0].calls[-1][1].set_exception(ConnectionError())
    elif failure == 'timeout':
        clock.now += .6
        finish(observer)
    assert node.observations.values()['tcp_quality'] == 'UNKNOWN'
    observer.clients['tcp'][0].ready = True
    clock.now += .2; observer._tick(); finish(observer)
    assert node.observations.values()['tcp_quality'] == 'VALID'


def test_node_owns_start_stop_and_measurement_completion_does_not_stop_observer(setup):
    node, config, observer, clock = setup
    assert module.start_process_state_observer(node, config) is observer
    for status in ['IDLE', 'RUNNING', 'SUCCEEDED', 'IDLE']:
        node.status = status
        observer._tick(); finish(observer)
        clock.now += .2
    assert len(node.timers) == 1
    assert all(len(c.calls) == 4 for c, _ in observer.clients.values())
    observer._tick()
    module.stop_process_state_observer(node)
    module.stop_process_state_observer(node)
    finish(observer)
    observer._tick()
    assert len(node.destroyed) == 4
    assert node.observations.values()['joints_quality'] == 'UNKNOWN'
    assert module.start_process_state_observer(node, config) is not observer


def test_mode_and_configuration_mismatch_cannot_start_duplicate_queries(setup):
    node, config, _, _ = setup
    with pytest.raises(ValueError):module.start_process_state_observer(node, dict(config, service_timeout_s=.4))
    module.stop_process_state_observer(node)
    node.coordinator.runtime_mode = 'SIMULATION'
    with pytest.raises(ValueError):module.start_process_state_observer(node, config)
    assert len(node.timers) == 1
