"""REAL 준비 검사에 사용하는 읽기 전용 드라이버 관측.

제어권은 PR #48의 std_msgs/String JSON v1만 신뢰한다. 이 모듈은 제어권 요청,
정지 해제, 서보·모션·그리퍼·드릴 명령을 보내지 않는다.
"""
import json
import math
import threading
import time
from dataclasses import dataclass
from typing import Optional


SOURCE = "CONTROLLER_ACCESS_CONTROL"
DEFAULT_TOPIC = "/dsr01/dsr_controller2/control_authority"
DEFAULT_MAX_AGE_S = 0.5
SAFE_STOP_STATES = frozenset({3, 5, 6, 9, 10})
STANDBY_STATE = 1
IDLE_MOTION_STATUS = 0
_REQUIRED = {
    "schema_version", "source", "driver_session", "sequence",
    "published_at_unix_ns", "active", "connected", "valid", "has_control",
    "last_access_event", "monitoring_age_ms",
}


@dataclass(frozen=True)
class ControlAuthorityObservation:
    driver_session: str
    sequence: int
    published_at_unix_ns: int
    received_at_monotonic_s: float
    active: bool
    connected: bool
    valid: bool
    has_control: bool
    last_access_event: int
    monitoring_age_ms: int


class ControlAuthorityCache:
    """마지막 JSON v1 관측을 보관하고 오래되거나 순서가 틀리면 폐기한다."""

    def __init__(self, *, max_age_s=DEFAULT_MAX_AGE_S,
                 monotonic=time.monotonic, unix_ns=time.time_ns):
        if (isinstance(max_age_s, bool) or not isinstance(max_age_s, (int, float))
                or not math.isfinite(max_age_s) or not 0 < max_age_s <= DEFAULT_MAX_AGE_S):
            raise ValueError("제어권 최대 경과시간은 0초 초과 0.5초 이하여야 함")
        self.max_age_s = float(max_age_s)
        self.monotonic = monotonic
        self.unix_ns = unix_ns
        self._lock = threading.Lock()
        self._latest: Optional[ControlAuthorityObservation] = None
        self._invalid_reason = "NO_MESSAGE"

    @property
    def invalid_reason(self):
        with self._lock:
            return self._invalid_reason

    def _invalidate(self, reason):
        with self._lock:
            self._latest = None
            self._invalid_reason = reason

    @staticmethod
    def _strict_bool(value, name):
        if type(value) is not bool:
            raise ValueError(name + "은 bool이어야 함")
        return value

    @staticmethod
    def _strict_int(value, name, minimum=0):
        if type(value) is not int or value < minimum:
            raise ValueError(name + " 정수 범위 오류")
        return value

    def ingest_json(self, payload, *, received_at_monotonic_s=None,
                    received_at_unix_ns=None):
        """한 패킷을 검증해 저장한다. 실패 시 이전 GRANT도 즉시 폐기한다."""
        try:
            if not isinstance(payload, str):
                raise ValueError("String.data 문자열 필요")
            value = json.loads(payload, parse_constant=lambda token:
                               (_ for _ in ()).throw(ValueError(token)))
            if not isinstance(value, dict) or set(value) != _REQUIRED:
                raise ValueError("JSON v1 필드 집합 불일치")
            if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
                raise ValueError("schema_version 불일치")
            if value["source"] != SOURCE:
                raise ValueError("source 불일치")
            session = value["driver_session"]
            if not isinstance(session, str) or not session.strip():
                raise ValueError("driver_session 필요")
            sequence = self._strict_int(value["sequence"], "sequence")
            if sequence > 2**64 - 1:
                raise ValueError("sequence uint64 범위 오류")
            published = self._strict_int(
                value["published_at_unix_ns"], "published_at_unix_ns")
            active = self._strict_bool(value["active"], "active")
            connected = self._strict_bool(value["connected"], "connected")
            valid = self._strict_bool(value["valid"], "valid")
            has_control = self._strict_bool(value["has_control"], "has_control")
            event = value["last_access_event"]
            if type(event) is not int or event not in (-1, 0, 1, 2, 3):
                raise ValueError("last_access_event 범위 오류")
            monitoring_age = value["monitoring_age_ms"]
            if type(monitoring_age) is not int or monitoring_age < -1:
                raise ValueError("monitoring_age_ms 범위 오류")

            received_mono = (self.monotonic() if received_at_monotonic_s is None
                             else received_at_monotonic_s)
            received_unix = (self.unix_ns() if received_at_unix_ns is None
                             else received_at_unix_ns)
            if (isinstance(received_mono, bool)
                    or not isinstance(received_mono, (int, float))
                    or not math.isfinite(received_mono)):
                raise ValueError("수신 monotonic 시각 오류")
            if type(received_unix) is not int:
                raise ValueError("수신 Unix 시각 오류")
            transport_age_ns = received_unix - published
            if not 0 <= transport_age_ns <= int(self.max_age_s * 1e9):
                raise ValueError("발행 시각이 미래이거나 전송 지연 만료")
            if monitoring_age < 0 or monitoring_age > int(self.max_age_s * 1000):
                # 미수신(-1)과 드라이버 내부 만료 모두 정상 실행 근거가 아니다.
                raise ValueError("드라이버 monitoring 데이터 만료")
            if valid and not (active and connected):
                raise ValueError("valid와 active/connected 상태 모순")
            if has_control and not valid:
                raise ValueError("무효 상태에서 has_control=true 금지")

            observation = ControlAuthorityObservation(
                session, sequence, published, float(received_mono),
                active, connected, valid, has_control, event, monitoring_age)
            with self._lock:
                previous = self._latest
                if (previous is not None
                        and previous.driver_session == session
                        and sequence <= previous.sequence):
                    self._latest = None
                    self._invalid_reason = "NON_MONOTONIC_SEQUENCE"
                    return False
                # 세션 변경은 이전 값을 덮지 않고 이 패킷 자체를 새 세션 첫 관측으로 사용한다.
                self._latest = observation
                self._invalid_reason = ""
            return True
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._invalidate("INVALID_PACKET: " + str(exc))
            return False

    def fresh(self):
        with self._lock:
            latest = self._latest
        if latest is None:
            return None
        age = self.monotonic() - latest.received_at_monotonic_s
        if not 0 <= age <= self.max_age_s:
            self._invalidate("RECEIVE_TIMEOUT")
            return None
        if not latest.connected:
            self._invalidate("DRIVER_DISCONNECTED")
            return None
        if not latest.valid:
            self._invalidate("DRIVER_STATE_INVALID")
            return None
        return latest

    def _fresh_control_authority(self):
        """준비 제어가 소비하는 fail-closed 최신 관측."""
        return self.fresh()

    def evidence(self, context):
        observation = self._fresh_control_authority()
        ready = bool(observation is not None
                     and observation.active and observation.connected
                     and observation.valid and observation.has_control)
        return {
            "measurement_id": context.measurement_id,
            "control_authority": {
                "value": ready,
                "valid": ready,
                "source": SOURCE,
                "observed_at_monotonic_s": (
                    observation.received_at_monotonic_s
                    if observation is not None else 0.0),
            },
        }


class RealPreparationObservations:
    """제어권 subscriber와 읽기 전용 정지 상태 조회의 수명 소유자."""

    def __init__(self, node, *, topic=DEFAULT_TOPIC,
                 max_age_s=DEFAULT_MAX_AGE_S, cache=None,
                 controller_prefix="/dsr01/dsr_controller2",
                 service_timeout_s=DEFAULT_MAX_AGE_S,
                 service_types=None):
        if not isinstance(topic, str) or not topic.startswith("/"):
            raise ValueError("제어권 토픽은 절대 ROS 이름이어야 함")
        from rclpy.qos import (
            QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy)
        from std_msgs.msg import String
        self.node = node
        self.cache = cache or ControlAuthorityCache(max_age_s=max_age_s)
        if (not isinstance(controller_prefix, str)
                or not controller_prefix.startswith("/")):
            raise ValueError("제어기 prefix는 절대 ROS 이름이어야 함")
        if (isinstance(service_timeout_s, bool)
                or not isinstance(service_timeout_s, (int, float))
                or not math.isfinite(service_timeout_s)
                or not 0 < service_timeout_s <= DEFAULT_MAX_AGE_S):
            raise ValueError("정지 상태 조회 제한시간은 0초 초과 0.5초 이하여야 함")
        if service_types is None:
            from dsr_msgs2.srv import GetRobotState, CheckMotion
            service_types = (GetRobotState, CheckMotion)
        get_state_type, check_motion_type = service_types
        self.service_timeout_s = float(service_timeout_s)
        self._process_stop_latched = False
        self._stop_lock = threading.Lock()
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.subscription = node.create_subscription(
            String, topic, self._on_control_authority, qos)
        prefix = controller_prefix.rstrip("/")
        self.get_robot_state_client = node.create_client(
            get_state_type, prefix + "/system/get_robot_state")
        self.check_motion_client = node.create_client(
            check_motion_type, prefix + "/motion/check_motion")
        self._get_robot_state_type = get_state_type
        self._check_motion_type = check_motion_type
        self._closed = False

    def close(self):
        """노드 종료 때만 ROS 관측 자원을 정리한다. 측정 종료와는 무관하다."""
        if self._closed:
            return
        self._closed = True
        destroy_subscription = getattr(self.node, "destroy_subscription", None)
        if callable(destroy_subscription) and self.subscription is not None:
            destroy_subscription(self.subscription)
        destroy_client = getattr(self.node, "destroy_client", None)
        if callable(destroy_client):
            for client in (self.get_robot_state_client, self.check_motion_client):
                if client is not None:
                    destroy_client(client)
        self.subscription = None
        self.get_robot_state_client = None
        self.check_motion_client = None

    def _on_control_authority(self, message):
        if not self.cache.ingest_json(getattr(message, "data", None)):
            self.node.get_logger().warn(
                "제어권 관측 폐기: " + self.cache.invalid_reason)

    def evidence(self, context):
        return self.cache.evidence(context)

    def mark_process_stop(self):
        """취소·정지 기록을 보존한다. 정상 상태 조회로 자동 해제하지 않는다."""
        with self._stop_lock:
            self._process_stop_latched = True

    def clear_process_stop_after_recovery(self):
        """상위 복구 절차가 끝난 뒤 명시적으로만 호출한다."""
        with self._stop_lock:
            self._process_stop_latched = False

    def record_process_result(self, result, cancel):
        if ((cancel is not None and callable(getattr(cancel, "is_set", None))
             and cancel.is_set())
                or getattr(result, "outcome", None) in {"STOPPED", "UNKNOWN"}):
            self.mark_process_stop()

    def _call_read_only(self, client, service_type, timeout_s):
        """executor의 다른 worker가 완료시키는 service future를 제한시간만 기다린다."""
        started = time.monotonic()
        try:
            if timeout_s <= 0 or not client.wait_for_service(timeout_sec=timeout_s):
                return None
            remaining = timeout_s - (time.monotonic() - started)
            if remaining <= 0:
                return None
            future = client.call_async(service_type.Request())
            done = threading.Event()
            future.add_done_callback(lambda _future: done.set())
            if not done.wait(remaining):
                future.cancel()
                return None
            response = future.result()
            if response is None or getattr(response, "success", False) is not True:
                return None
            if time.monotonic() - started > timeout_s:
                return None
            return response
        except Exception as exc:
            self.node.get_logger().warn("정지 상태 조회 실패: " + str(exc))
            return None

    def stop_latched(self, context):
        if (context is not None
                and callable(getattr(getattr(context, "cancel", None), "is_set", None))
                and context.cancel.is_set()):
            self.mark_process_stop()

        authority = self.cache.fresh()
        if not (authority is not None and authority.active and authority.connected
                and authority.valid and authority.has_control):
            return None

        query_started = time.monotonic()
        state = self._call_read_only(
            self.get_robot_state_client, self._get_robot_state_type,
            self.service_timeout_s)
        remaining = self.service_timeout_s - (time.monotonic() - query_started)
        motion = self._call_read_only(
            self.check_motion_client, self._check_motion_type, remaining)
        if state is None or motion is None:
            return None
        # 조회 중 제어권 관측이 만료되거나 LOSS로 바뀌었으면 두 서비스가 정상이어도 미확인이다.
        authority = self.cache.fresh()
        if not (authority is not None and authority.active and authority.connected
                and authority.valid and authority.has_control):
            return None
        robot_state = getattr(state, "robot_state", None)
        motion_status = getattr(motion, "status", None)
        if type(robot_state) is not int or type(motion_status) is not int:
            return None
        if robot_state in SAFE_STOP_STATES:
            return True
        with self._stop_lock:
            process_latched = self._process_stop_latched
        if (robot_state == STANDBY_STATE
                and motion_status == IDLE_MOTION_STATUS
                and not process_latched):
            return False
        return None
