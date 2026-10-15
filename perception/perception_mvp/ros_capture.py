"""ROS one-shot inspection capture; no robot commands or occupancy assumptions."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from itertools import product
import json
import time
from threading import Event, Lock, Thread

import numpy as np

from .rgbd_io import image_array, info_dict, save_capture, stamp, ros_main as main
from .runtime_log import progress

__all__ = ["image_array", "info_dict", "save_capture", "stamp", "main", "capture_inspection_view", "stream_ros_hand"]


def _select_packet(queues, start_ns, now_ns, max_delta_ms, max_age_ms, last_stamp=-1):
    """Newest RGB with a valid buffered bundle, not necessarily the newest arrival."""
    valid = {key: [msg for msg in queue if stamp(msg) >= start_ns
                   and 0 <= (now_ns-stamp(msg))/1e6 <= max_age_ms]
             for key, queue in queues.items()}
    others = [key for key in queues if key != 'rgb']
    for rgb in sorted(valid['rgb'], key=stamp, reverse=True):
        if stamp(rgb) <= last_stamp:
            continue
        for depths in product(*(valid[key] for key in others)):
            messages = dict(zip(others, depths), rgb=rgb)
            stamps = [stamp(msg) for msg in messages.values()]
            if (max(stamps)-min(stamps))/1e6 <= max_delta_ms:
                return messages
    return None


def _reception_timeout(context, view, phase, queues, counts, start_ns, now_ns,
                       timeout, max_delta_ms, max_age_ms, message, infos=None, topics=None):
    latest = {key: stamp(queue[-1]) if queue else None for key, queue in queues.items()}
    stamps = [value for value in latest.values() if value is not None]
    missing = [key for key, queue in queues.items() if not queue]
    if infos is not None:
        missing += [key+'_info' for key in queues if key not in infos]
    report = dict(missing_topics=[(topics or {}).get(key, key) for key in missing],
                  received_counts=dict(counts), latest_stamp_ns=latest,
                  latest_age_ms={key: (now_ns-value)/1e6 if value is not None else None
                                 for key, value in latest.items()},
                  latest_span_ms=(max(stamps)-min(stamps))/1e6 if len(stamps) == len(queues) else None,
                  latest_before_request={key: value < start_ns if value is not None else None
                                         for key, value in latest.items()},
                  request_start_ns=start_ns, now_ns=now_ns, timeout_seconds=timeout,
                  max_delta_ms=max_delta_ms, max_age_ms=max_age_ms)
    progress(context or {}, '영상 수신 시간 초과', view=view, phase=phase, reception=report)
    error = TimeoutError(message + '; view=' + view + '; reception=' + json.dumps(report))
    error.view, error.reception = view, report
    return error


def _require_observation_state(context, view, phase, is_active, is_stopped,
                               workflow_valid=None, bundle_valid=None):
    # Preserve strict True and short-circuit order. Do not re-read a failed hook
    # for logging: a later value could hide the actual interruption.
    checks = [('request_active', is_active, 'INSPECTION_REQUEST_INACTIVE', 'inspection cancelled'),
              ('workflow_valid', workflow_valid, 'WORKFLOW_INVALID', 'workflow invalid'),
              ('bundle_valid', bundle_valid, 'BUNDLE_INVALID', 'bundle invalid'),
              ('is_stopped', lambda: is_stopped(view), 'VIEW_NOT_STOPPED', 'View not stopped')]
    states = {name: {'evaluated': False} for name, _, _, _ in checks}
    for name, hook, code, message in checks:
        if hook is None:
            continue
        try:
            value = hook()
        except Exception as cause:
            states[name] = dict(evaluated=True, error=str(cause))
            progress(context or {}, '관측 조건 확인 실패',
                     view=view, phase=phase, failed_condition=name,
                     failure_code='STATE_CHECK_FAILED', conditions=states)
            error = RuntimeError(f'STATE_CHECK_FAILED: {name}; view={view}; phase={phase}: {cause}')
            error.view = view
            raise error from cause
        states[name] = dict(evaluated=True, value=repr(value),
                            type=f'{type(value).__module__}.{type(value).__name__}', passed=value is True)
        if value is not True:
            progress(context or {}, '관측 조건 실패', view=view, phase=phase,
                     failed_condition=name, failure_code=code, conditions=states)
            error = RuntimeError(f'{code}: {message}; view={view}; phase={phase}; '
                                 f'{name}={value!r} ({states[name]["type"]})')
            error.view = view
            raise error


def stream_ros_hand(is_active, is_stopped, *, timeout=15., max_delta_ms=50., max_age_ms=250.,
                    context=None, workflow_valid=None):
    """Stopped V0 RGB/aligned Depth generator for hand_stream; no block inference.

    ROS reception runs separately from the caller's hand inference. Queues are
    bounded; each iteration takes the newest synchronized pair, never a backlog.
    Closing the generator stops only its own receiver, not D or the camera driver.
    """
    if any(not np.isfinite(value) or value <= 0 for value in (timeout, max_delta_ms, max_age_ms)):
        raise ValueError('positive finite hand reception limits required')
    def require_active():
        _require_observation_state(context, 'V0', 'HAND_RECEPTION', is_active,
                                   is_stopped, workflow_valid)
    require_active()
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image
    ros_context = Context()
    rclpy.init(args=[], context=ros_context)
    node, executor, worker = None, None, None
    queues = {'rgb': deque(maxlen=10), 'aligned': deque(maxlen=10)}
    counts = dict.fromkeys(queues, 0)
    lock, changed = Lock(), Event()
    failures = []
    try:
        node = rclpy.create_node('b_v0_hand_receiver', context=ros_context)
        executor = SingleThreadedExecutor(context=ros_context)
        start_ns = node.get_clock().now().nanoseconds
        def receive(message, key):
            with lock:
                queues[key].append(message)
                counts[key] += 1
            changed.set()
        node.create_subscription(Image, '/camera/color/image_raw',
            lambda msg: receive(msg, 'rgb'), QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        node.create_subscription(Image, '/camera/aligned_depth_to_color/image_raw',
            lambda msg: receive(msg, 'aligned'), QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        executor.add_node(node)
        def spin():
            try:
                executor.spin()
            except Exception as error:
                failures.append(error)
                changed.set()
        worker = Thread(target=spin, name='b-v0-hand-receiver', daemon=True)
        worker.start()
        last_stamp = -1
        while rclpy.ok(context=ros_context):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                require_active()
                if failures:
                    raise RuntimeError('V0 ROS reception failed') from failures[0]
                changed.wait(.05)
                changed.clear()
                with lock:
                    packet = _select_packet(queues, start_ns, node.get_clock().now().nanoseconds,
                                            max_delta_ms, max_age_ms, last_stamp)
                if packet is None:
                    continue
                rgb, depth = packet['rgb'], packet['aligned']
                if rgb.encoding not in ('rgb8', 'bgr8') or depth.encoding != '16UC1':
                    raise ValueError('hand stream requires RGB8/BGR8 and aligned 16UC1 Depth')
                rgb_array, depth_array = image_array(rgb), image_array(depth)
                if rgb_array.shape[:2] != depth_array.shape:
                    raise ValueError('hand RGB and aligned Depth dimensions differ')
                require_active()
                last_stamp = stamp(rgb)
                yield rgb_array, depth_array, time.monotonic()
                break
            else:
                with lock:
                    error = _reception_timeout(context, 'V0', 'HAND_RECEPTION', queues, counts,
                        start_ns, node.get_clock().now().nanoseconds, timeout, max_delta_ms, max_age_ms,
                        'fresh synchronized V0 hand RGB/Depth unavailable; check topics/clocks',
                        topics={'rgb': '/camera/color/image_raw',
                                'aligned': '/camera/aligned_depth_to_color/image_raw'})
                raise error
        raise RuntimeError('V0 ROS context stopped')
    finally:
        if executor is not None:
            executor.shutdown()
        if worker is not None:
            worker.join(timeout=1.)
        if node is not None:
            node.destroy_node()
        rclpy.shutdown(context=ros_context)


def capture_inspection_view(manifest, view, is_active, *, output_root, scene_id,
                            calibration_id, robot_pose, is_stopped, timeout=15.,
                            max_delta_ms=50., max_age_ms=250., verify_occupancy=None,
                            workflow_valid=None, bundle_valid=None):
    """capture_view callable for main.make_inspection_observer (bind keyword args).

    Pose/stop hooks belong to Controller. ROS clocks must be synchronized; stale
    messages fail rather than relaxing the thresholds. A private ROS context keeps
    reception off D's executor and never shuts down D's node. No camera restart.
    """
    context = deepcopy(manifest)
    if context.get('mode') != 'REAL' or view not in ('V0', 'D1', 'D3'):
        raise ValueError('explicit REAL assembly View required')
    if any(not np.isfinite(value) or value <= 0 for value in (timeout, max_delta_ms, max_age_ms)):
        raise ValueError('positive finite reception limits required')
    def require_active():
        _require_observation_state(context, view, 'RGBD_CAPTURE', is_active,
                                   is_stopped, workflow_valid, bundle_valid)
    require_active()
    metadata = dict(scene_id=scene_id, calibration_id=calibration_id,
        robot_pose=deepcopy(robot_pose(view)), check_id=context['check_id'],
        observation_seq=context['observation_seq'])
    directory = Path(output_root) / view / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import Image, CameraInfo
    ros_context = Context()
    rclpy.init(args=[], context=ros_context)
    node, executor, worker = None, None, None
    lock, changed = Lock(), Event()
    failures = []
    try:
        executor = SingleThreadedExecutor(context=ros_context)
        node = rclpy.create_node('b_inspection_capture', context=ros_context)
        start_ns = node.get_clock().now().nanoseconds
        queues = {key: deque(maxlen=10) for key in ('rgb', 'raw', 'aligned')}
        counts = dict.fromkeys((*queues, *(key+'_info' for key in queues)), 0)
        infos = {}
        def receive(message, key, info=False):
            with lock:
                counts[key+'_info' if info else key] += 1
                if info:
                    infos[key] = message
                else:
                    queues[key].append(message)
            changed.set()
        topics = {'rgb': '/camera/color/image_raw', 'raw': '/camera/depth/image_rect_raw',
                  'aligned': '/camera/aligned_depth_to_color/image_raw'}
        for key, topic in list(topics.items()):
            qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
            node.create_subscription(Image, topic, lambda msg, k=key: receive(msg, k), qos)
            info_topic = {'rgb': '/camera/color/camera_info', 'raw': '/camera/depth/camera_info',
                          'aligned': '/camera/aligned_depth_to_color/camera_info'}[key]
            topics[key + '_info'] = info_topic
            node.create_subscription(CameraInfo, info_topic,
                lambda msg, k=key: receive(msg, k, info=True), qos_profile_sensor_data)
        executor.add_node(node)
        def spin():
            try:
                executor.spin()
            except Exception as error:
                failures.append(error)
                changed.set()
        worker = Thread(target=spin, name='b-inspection-receiver', daemon=True)
        worker.start()
        deadline = time.monotonic() + timeout
        while rclpy.ok(context=ros_context) and time.monotonic() < deadline:
            # Controller queries may block; image callbacks keep running independently.
            # Pick the packet AFTER the query so its latency does not age a chosen packet.
            changed.wait(.05)
            changed.clear()
            require_active()
            if failures:
                raise RuntimeError('inspection ROS reception failed') from failures[0]
            with lock:
                messages = (_select_packet(queues, start_ns, node.get_clock().now().nanoseconds,
                                           max_delta_ms, max_age_ms) if len(infos) == 3 else None)
                captured_infos = dict(infos)
            if messages is None:
                continue
            save_capture(directory, messages, captured_infos, topics, view, max_delta_ms, context=metadata)
            break
        else:
            with lock:
                error = _reception_timeout(context, view, 'RGBD_CAPTURE', queues, counts,
                    start_ns, node.get_clock().now().nanoseconds, timeout, max_delta_ms, max_age_ms,
                    'fresh synchronized ROS RGB/raw/aligned Depth or CameraInfo unavailable; check topics/clocks',
                    infos=infos, topics=topics)
            raise error
    finally:
        if executor is not None:
            executor.shutdown()
        if worker is not None:
            worker.join(timeout=1.)
        if node is not None:
            node.destroy_node()
        rclpy.shutdown(context=ros_context)
    # Receiver closes before any occupancy computation or model inference.
    require_active()
    evidence = (verify_occupancy(directory, deepcopy(context), view)
                if verify_occupancy is not None else {'verified_regions': [], 'verification_basis': None})
    require_active()
    from .contracts import region_cells
    region_cells(evidence['verified_regions'])
    if evidence['verified_regions'] and not evidence.get('verification_basis'):
        raise ValueError('verified occupancy needs actual evidence, not a board ROI')
    return dict(directory=str(directory), verified_regions=deepcopy(evidence['verified_regions']),
                verification_basis=deepcopy(evidence.get('verification_basis')))

if __name__ == "__main__":
    main()
