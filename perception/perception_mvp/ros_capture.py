"""ROS one-shot inspection capture; no robot commands or occupancy assumptions."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time
from threading import Event, Lock, Thread

import numpy as np

from .rgbd_io import image_array, info_dict, save_capture, stamp, ros_main as main
from .runtime_log import progress

__all__ = ["image_array", "info_dict", "save_capture", "stamp", "main", "capture_inspection_view", "stream_ros_hand"]


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
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import Image
    ros_context = Context()
    rclpy.init(args=[], context=ros_context)
    node, executor, worker = None, None, None
    queues = {'rgb': deque(maxlen=10), 'aligned': deque(maxlen=10)}
    lock, changed = Lock(), Event()
    failures = []
    try:
        node = rclpy.create_node('b_v0_hand_receiver', context=ros_context)
        executor = SingleThreadedExecutor(context=ros_context)
        start_ns = node.get_clock().now().nanoseconds
        def receive(message, key):
            with lock:
                queues[key].append(message)
            changed.set()
        node.create_subscription(Image, '/camera/color/image_raw',
            lambda msg: receive(msg, 'rgb'), QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
        node.create_subscription(Image, '/camera/aligned_depth_to_color/image_raw',
            lambda msg: receive(msg, 'aligned'), qos_profile_sensor_data)
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
                    rgb = queues['rgb'][-1] if queues['rgb'] else None
                    depth = (min(queues['aligned'], key=lambda msg: abs(stamp(msg) - stamp(rgb)))
                             if rgb is not None and queues['aligned'] else None)
                if rgb is None or depth is None or stamp(rgb) <= last_stamp:
                    continue
                stamps = [stamp(rgb), stamp(depth)]
                now_ns = node.get_clock().now().nanoseconds
                if (min(stamps) < start_ns or (max(stamps) - min(stamps)) / 1e6 > max_delta_ms or
                        any(not 0 <= (now_ns - value) / 1e6 <= max_age_ms for value in stamps)):
                    continue
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
                raise TimeoutError('fresh synchronized V0 hand RGB/Depth unavailable; check topics/clocks')
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
    node = None
    executor = None
    try:
        executor = SingleThreadedExecutor(context=ros_context)
        node = rclpy.create_node('b_inspection_capture', context=ros_context)
        start_ns = node.get_clock().now().nanoseconds
        queues = {key: deque(maxlen=10) for key in ('rgb', 'raw', 'aligned')}
        infos = {}
        topics = {'rgb': '/camera/color/image_raw', 'raw': '/camera/depth/image_rect_raw',
                  'aligned': '/camera/aligned_depth_to_color/image_raw'}
        for key, topic in list(topics.items()):
            qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE) if key == 'rgb' else qos_profile_sensor_data
            node.create_subscription(Image, topic, lambda msg, k=key: queues[k].append(msg), qos)
            info_topic = {'rgb': '/camera/color/camera_info', 'raw': '/camera/depth/camera_info',
                          'aligned': '/camera/aligned_depth_to_color/camera_info'}[key]
            topics[key + '_info'] = info_topic
            node.create_subscription(CameraInfo, info_topic,
                lambda msg, k=key: infos.update({k: msg}), qos_profile_sensor_data)
        deadline = time.monotonic() + timeout
        while rclpy.ok(context=ros_context) and time.monotonic() < deadline:
            require_active()
            rclpy.spin_once(node, executor=executor, timeout_sec=.05)
            if len(infos) != 3 or not all(queues.values()):
                continue
            rgb = queues['rgb'][-1]
            messages = {'rgb': rgb, **{key: min(queues[key], key=lambda msg: abs(stamp(msg) - stamp(rgb)))
                                      for key in ('raw', 'aligned')}}
            stamps = [stamp(msg) for msg in messages.values()]
            now_ns = node.get_clock().now().nanoseconds
            if (min(stamps) < start_ns or (max(stamps) - min(stamps)) / 1e6 > max_delta_ms or
                    any(not 0 <= (now_ns - value) / 1e6 <= max_age_ms for value in stamps)):
                continue
            require_active()
            save_capture(directory, messages, infos, topics, view, max_delta_ms, context=metadata)
            break
        else:
            raise TimeoutError('fresh synchronized ROS RGB/raw/aligned Depth or CameraInfo unavailable; check topics/clocks')
    finally:
        if executor is not None:
            executor.shutdown()
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
