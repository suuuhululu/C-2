"""제어권 subscriber와 정지 상태 서비스 판정 시험. 실제 로봇 연결 없음."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from c2_process.real_preparation_observations import (
    ControlAuthorityCache, RealPreparationObservations, SOURCE)


class Clock:
    def __init__(self):
        self.mono = 100.0
        self.unix = 1_800_000_000_000_000_000

    def monotonic(self):
        return self.mono

    def unix_ns(self):
        return self.unix


def packet(clock, **changes):
    value = dict(
        schema_version=1, source=SOURCE, driver_session="driver-a",
        sequence=10, published_at_unix_ns=clock.unix - 20_000_000,
        active=True, connected=True, valid=True, has_control=True,
        last_access_event=2, monitoring_age_ms=25,
    )
    value.update(changes)
    return json.dumps(value, separators=(",", ":"))


def context():
    return NS(measurement_id="measurement-1")


def test_valid_grant_becomes_request_scoped_evidence():
    clock = Clock()
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    assert cache.ingest_json(packet(clock))
    evidence = cache.evidence(context())
    assert evidence["measurement_id"] == "measurement-1"
    assert evidence["control_authority"] == {
        "value": True, "valid": True, "source": SOURCE,
        "observed_at_monotonic_s": 100.0,
    }


@pytest.mark.parametrize("changes", [
    {"schema_version": 2},
    {"source": "AUTO"},
    {"active": 1},
    {"connected": False, "valid": True},
    {"valid": False, "has_control": True},
    {"published_at_unix_ns": 1_800_000_000_100_000_000},
    {"published_at_unix_ns": 1_799_999_999_000_000_000},
    {"monitoring_age_ms": -1},
    {"monitoring_age_ms": 501},
    {"last_access_event": 99},
])
def test_invalid_packet_clears_previous_grant(changes):
    clock = Clock()
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    assert cache.ingest_json(packet(clock))
    assert not cache.ingest_json(packet(clock, sequence=11, **changes))
    assert cache.fresh() is None
    assert cache.evidence(context())["control_authority"]["value"] is False


def test_loss_replaces_grant_and_never_becomes_execution_authority():
    clock = Clock()
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    assert cache.ingest_json(packet(
        clock, has_control=False, last_access_event=3))
    assert cache.fresh() is not None
    evidence = cache.evidence(context())["control_authority"]
    assert evidence["value"] is False and evidence["valid"] is False
    assert evidence["observed_at_monotonic_s"] == 100.0


@pytest.mark.parametrize("changes,reason", [
    ({"connected": False, "valid": False, "has_control": False}, "DRIVER_DISCONNECTED"),
    ({"valid": False, "has_control": False}, "DRIVER_STATE_INVALID"),
])
def test_disconnected_or_invalid_is_immediately_unknown(changes, reason):
    clock = Clock()
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    assert cache.ingest_json(packet(clock, **changes))
    assert cache._fresh_control_authority() is None
    assert cache.invalid_reason == reason


def test_receive_timeout_and_bad_json_clear_grant():
    clock = Clock()
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    assert cache.ingest_json(packet(clock))
    clock.mono += .501
    assert cache.fresh() is None and cache.invalid_reason == "RECEIVE_TIMEOUT"
    clock.mono = 101.
    assert cache.ingest_json(packet(clock, sequence=20),
                             received_at_monotonic_s=101.)
    assert not cache.ingest_json("{bad json")
    assert cache.fresh() is None


def test_session_change_accepts_only_new_session_and_sequence_regression_clears():
    clock = Clock()
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    assert cache.ingest_json(packet(clock, driver_session="a", sequence=20))
    assert cache.ingest_json(packet(clock, driver_session="b", sequence=1))
    assert cache.fresh().driver_session == "b"
    assert not cache.ingest_json(packet(clock, driver_session="b", sequence=1))
    assert cache.fresh() is None
    assert cache.invalid_reason == "NON_MONOTONIC_SEQUENCE"


def test_ros_subscriber_uses_pr48_topic_type_and_qos(monkeypatch):
    clock = Clock()
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    calls = {}
    class Node:
        def create_subscription(self, msg_type, topic, callback, qos):
            calls.update(msg_type=msg_type, topic=topic, callback=callback, qos=qos)
            return object()
        def create_client(self, service_type, name):
            calls.setdefault("clients", []).append((service_type, name))
            return NS()
        def get_logger(self):
            return NS(warn=lambda message: calls.setdefault("warning", message))
    class String:
        def __init__(self, data=""): self.data = data
    class QoS:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    monkeypatch.setitem(sys.modules, "std_msgs.msg", NS(String=String))
    monkeypatch.setitem(sys.modules, "rclpy.qos", NS(
        QoSProfile=QoS, ReliabilityPolicy=NS(RELIABLE="reliable"),
        DurabilityPolicy=NS(VOLATILE="volatile"),
        HistoryPolicy=NS(KEEP_LAST="keep_last")))
    class GetRobotState:
        class Request: pass
    class CheckMotion:
        class Request: pass
    observations = RealPreparationObservations(
        Node(), cache=cache, service_types=(GetRobotState, CheckMotion))
    assert calls["msg_type"] is String
    assert calls["topic"] == "/dsr01/dsr_controller2/control_authority"
    assert calls["qos"].depth == 1
    assert calls["qos"].reliability == "reliable"
    assert calls["qos"].durability == "volatile"
    calls["callback"](String(packet(clock)))
    assert observations.evidence(context())["control_authority"]["value"] is True
    assert calls["clients"] == [
        (GetRobotState, "/dsr01/dsr_controller2/system/get_robot_state"),
        (CheckMotion, "/dsr01/dsr_controller2/motion/check_motion"),
    ]


def test_observation_resources_live_until_node_close_and_close_is_idempotent(monkeypatch):
    destroyed = []
    class Node:
        def create_subscription(self, *args): return "subscription"
        def create_client(self, _service_type, name): return name
        def destroy_subscription(self, value): destroyed.append(("subscription", value))
        def destroy_client(self, value): destroyed.append(("client", value))
        def get_logger(self): return NS(warn=lambda _message: None)
    class String: pass
    class QoS:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class GetRobotState:
        class Request: pass
    class CheckMotion:
        class Request: pass
    monkeypatch.setitem(sys.modules, "std_msgs.msg", NS(String=String))
    monkeypatch.setitem(sys.modules, "rclpy.qos", NS(
        QoSProfile=QoS, ReliabilityPolicy=NS(RELIABLE="reliable"),
        DurabilityPolicy=NS(VOLATILE="volatile"),
        HistoryPolicy=NS(KEEP_LAST="keep_last")))
    observations = RealPreparationObservations(
        Node(), service_types=(GetRobotState, CheckMotion))
    # 측정 함수/어댑터 종료는 이 객체를 닫지 않는다. 노드 종료 지점에서만 close한다.
    assert observations.subscription == "subscription" and destroyed == []
    observations.close()
    observations.close()
    assert destroyed == [
        ("subscription", "subscription"),
        ("client", "/dsr01/dsr_controller2/system/get_robot_state"),
        ("client", "/dsr01/dsr_controller2/motion/check_motion"),
    ]


class ImmediateFuture:
    def __init__(self, value): self.value = value
    def add_done_callback(self, callback): callback(self)
    def result(self): return self.value
    def cancel(self): pass


class ServiceClient:
    def __init__(self, response, available=True):
        self.response, self.available = response, available
    def wait_for_service(self, timeout_sec): return self.available
    def call_async(self, request): return ImmediateFuture(self.response)


def make_observations(clock, monkeypatch, *, robot_state=1, motion_status=0,
                      success=True, available=True):
    cache = ControlAuthorityCache(
        max_age_s=.5, monotonic=clock.monotonic, unix_ns=clock.unix_ns)
    cache.ingest_json(packet(clock))
    clients = [
        ServiceClient(NS(success=success, robot_state=robot_state), available),
        ServiceClient(NS(success=success, status=motion_status), available),
    ]
    class Node:
        def create_subscription(self, *args): return object()
        def create_client(self, *args): return clients.pop(0)
        def get_logger(self): return NS(warn=lambda message: None)
    class String: pass
    class QoS:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class GetRobotState:
        class Request: pass
    class CheckMotion:
        class Request: pass
    monkeypatch.setitem(sys.modules, "std_msgs.msg", NS(String=String))
    monkeypatch.setitem(sys.modules, "rclpy.qos", NS(
        QoSProfile=QoS, ReliabilityPolicy=NS(RELIABLE="reliable"),
        DurabilityPolicy=NS(VOLATILE="volatile"),
        HistoryPolicy=NS(KEEP_LAST="keep_last")))
    return RealPreparationObservations(
        Node(), cache=cache, service_types=(GetRobotState, CheckMotion))


@pytest.mark.parametrize("robot_state", [3, 5, 6, 9, 10])
def test_safe_stop_states_are_latched(monkeypatch, robot_state):
    current = Clock()
    observations = make_observations(current, monkeypatch, robot_state=robot_state)
    assert observations.stop_latched(NS(cancel=NS(is_set=lambda: False))) is True


def test_standby_idle_is_false_until_internal_cancel_latch(monkeypatch):
    observations = make_observations(Clock(), monkeypatch)
    ctx = NS(cancel=NS(is_set=lambda: False))
    assert observations.stop_latched(ctx) is False
    observations.mark_process_stop()
    assert observations.stop_latched(ctx) is None
    observations.clear_process_stop_after_recovery()
    assert observations.stop_latched(ctx) is False


@pytest.mark.parametrize("robot_state,motion_status", [(1, 1), (2, 0), (4, 0), (7, 0)])
def test_unsupported_or_moving_state_is_unknown(monkeypatch, robot_state, motion_status):
    observations = make_observations(
        Clock(), monkeypatch, robot_state=robot_state, motion_status=motion_status)
    assert observations.stop_latched(NS(cancel=NS(is_set=lambda: False))) is None


@pytest.mark.parametrize("success,available", [(False, True), (True, False)])
def test_service_failure_is_unknown(monkeypatch, success, available):
    observations = make_observations(
        Clock(), monkeypatch, success=success, available=available)
    assert observations.stop_latched(NS(cancel=NS(is_set=lambda: False))) is None


def test_cancel_sets_internal_latch_and_normal_response_does_not_clear(monkeypatch):
    observations = make_observations(Clock(), monkeypatch)
    assert observations.stop_latched(NS(cancel=NS(is_set=lambda: True))) is None
    assert observations.stop_latched(NS(cancel=NS(is_set=lambda: False))) is None
