"""Synthetic ROS messages verify file compatibility, not real camera accuracy."""
from types import SimpleNamespace as N

import numpy as np
import pytest

from perception_mvp.rgbd_io import save_capture, load_frame


def packets():
    header = N(frame_id='synthetic_optical', stamp=N(sec=1, nanosec=0))
    messages, infos = {}, {}
    for key in ('rgb', 'raw', 'aligned'):
        rgb = key == 'rgb'
        array = np.zeros((2, 3, 3), np.uint8) if rgb else np.full((2, 3), 1000, np.uint16)
        messages[key] = N(header=header, width=3, height=2, is_bigendian=False,
            encoding='rgb8' if rgb else '16UC1', step=9 if rgb else 6, data=array.tobytes())
        infos[key] = N(header=header, width=3, height=2, distortion_model='plumb_bob',
            d=[0.] * 5, k=[100., 0., 1., 0., 100., 1., 0., 0., 1.], r=[0.] * 9, p=[0.] * 12)
    return messages, infos


def test_packet_selection_uses_buffered_match_when_newest_rgb_has_no_depth():
    from perception_mvp.ros_capture import _select_packet
    def msg(ms):
        return N(header=N(stamp=N(sec=1, nanosec=ms*1_000_000)))
    queues = dict(rgb=[msg(100), msg(200)], raw=[msg(100)], aligned=[msg(100)])
    packet = _select_packet(queues, 1_000_000_000, 1_210_000_000, 50., 250.)
    assert packet['rgb'] is queues['rgb'][0]
    assert set(packet) == {'rgb', 'raw', 'aligned'}


@pytest.mark.parametrize('frame_ms,now_ms,start_ms', [
    (0, 251, 0), (101, 100, 0), (99, 110, 100)])
def test_packet_selection_rejects_old_future_and_pre_request_frames(frame_ms, now_ms, start_ms):
    from perception_mvp.ros_capture import _select_packet
    msg = N(header=N(stamp=N(sec=1, nanosec=frame_ms*1_000_000)))
    assert _select_packet(dict(rgb=[msg], aligned=[msg]),
                          1_000_000_000+start_ms*1_000_000,
                          1_000_000_000+now_ms*1_000_000, 50., 250.) is None


def test_packet_selection_still_requires_all_depths_and_sync():
    from perception_mvp.ros_capture import _select_packet
    def msg(ms):
        return N(header=N(stamp=N(sec=1, nanosec=ms*1_000_000)))
    for raw in ([], [msg(49)]):
        assert _select_packet(dict(rgb=[msg(100)], raw=raw, aligned=[msg(100)]),
                              1_000_000_000, 1_110_000_000, 50., 250.) is None


def test_reception_timeout_reports_missing_stream_and_negative_age(capsys):
    from perception_mvp.ros_capture import _reception_timeout
    msg = N(header=N(stamp=N(sec=2, nanosec=0)))
    error = _reception_timeout(dict(check_id='fixed'), 'D3', 'RGBD_CAPTURE',
        dict(rgb=[msg], raw=[], aligned=[msg]), dict(rgb=4, raw=0, aligned=4),
        1_000_000_000, 1_900_000_000, 15., 50., 250., 'fresh synchronized unavailable',
        infos={'rgb': object(), 'aligned': object()}, topics={'raw': '/raw', 'raw_info': '/raw_info'})
    assert error.view == 'D3'
    assert error.reception['missing_topics'] == ['/raw', '/raw_info']
    assert error.reception['latest_age_ms']['rgb'] == -100.
    assert error.reception['received_counts']['raw'] == 0
    assert 'reception=' in str(error)
    assert 'RGBD_CAPTURE' in capsys.readouterr().out


def context():
    return dict(scene_id='synthetic', robot_pose={'basis': 'synthetic test only'},
                calibration_id='fixture', check_id='fixed', observation_seq=2)


def test_inspection_ros_capture_loads_without_fabricated_coverage(tmp_path):
    messages, infos = packets()
    directory = tmp_path / 'capture'
    save_capture(directory, messages, infos, {}, 'V0', 50., context=context())
    rgb, raw, aligned, meta = load_frame(directory)
    assert rgb.shape == (2, 3, 3) and np.array_equal(raw, aligned)
    assert all(meta[key] == value for key, value in context().items())
    assert meta['camera_info']['aligned']['fx'] == 100.
    assert meta['camera_info']['aligned']['model'] == 'brown_conrady'
    assert 'verified_regions' not in meta
    with pytest.raises(FileExistsError):
        save_capture(directory, messages, infos, {}, 'V0', 50., context=context())


@pytest.mark.parametrize('key,value', [('check_id', ''), ('robot_pose', {}),
                                      ('observation_seq', True), ('calibration_id', None)])
def test_invalid_context_does_not_write(tmp_path, key, value):
    messages, infos = packets()
    value_context = context()
    value_context[key] = value
    with pytest.raises(ValueError):
        save_capture(tmp_path / 'bad', messages, infos, {}, 'V0', 50., context=value_context)
    assert not (tmp_path / 'bad').exists()


def test_unknown_distortion_or_unsynchronized_frames_do_not_write(tmp_path):
    messages, infos = packets()
    infos['aligned'].distortion_model = 'unsupported'
    with pytest.raises(ValueError, match='distortion'):
        save_capture(tmp_path / 'bad', messages, infos, {}, 'V0', 50., context=context())
    infos['aligned'].distortion_model = 'plumb_bob'
    messages['aligned'].header = N(frame_id='synthetic_optical', stamp=N(sec=2, nanosec=0))
    with pytest.raises(ValueError, match='synchronization'):
        save_capture(tmp_path / 'bad', messages, infos, {}, 'V0', 50., context=context())
    assert not (tmp_path / 'bad').exists()


@pytest.fixture
def fake_ros(monkeypatch):
    import sys
    from types import ModuleType
    state = N(closed=False, shutdown=False, frame_ns=1_000_000_000, active=True, subscriptions=[], qoses=[])
    messages, infos = packets()
    class Node:
        def get_clock(self):
            return N(now=lambda: N(nanoseconds=1_000_000_000))
        def create_subscription(self, cls, topic, callback, qos):
            state.subscriptions.append((topic, callback))
            state.qoses.append((topic, qos))
        def destroy_node(self):
            state.closed = True
    def spin(node, **kwargs):
        from threading import get_ident
        state.receiver_thread = get_ident()
        for topic, callback in state.subscriptions:
            key = 'aligned' if 'aligned_depth' in topic else 'raw' if '/depth/' in topic else 'rgb'
            if topic.endswith('camera_info'):
                callback(infos[key])
            else:
                messages[key].header = N(frame_id='synthetic_optical',
                    stamp=N(sec=state.frame_ns // 1_000_000_000, nanosec=state.frame_ns % 1_000_000_000))
                callback(messages[key])
    modules = {name: ModuleType(name) for name in ('rclpy', 'rclpy.context', 'rclpy.executors', 'rclpy.qos', 'sensor_msgs', 'sensor_msgs.msg')}
    modules['rclpy'].init = lambda **kw: None
    modules['rclpy'].create_node = lambda *a, **kw: Node()
    modules['rclpy'].ok = lambda **kw: True
    modules['rclpy'].spin_once = spin
    modules['rclpy'].shutdown = lambda **kw: setattr(state, 'shutdown', True)
    modules['rclpy.context'].Context = lambda: object()
    from threading import Event
    class Executor:
        def __init__(self, **kwargs):
            self.stop = Event()
        def add_node(self, node):
            self.node = node
        def spin(self):
            spin(self.node)
            self.stop.wait()
        def shutdown(self):
            self.stop.set()
    modules['rclpy.executors'].SingleThreadedExecutor = Executor
    modules['rclpy.qos'].QoSProfile = lambda **kw: N(**kw)
    modules['rclpy.qos'].ReliabilityPolicy = N(RELIABLE='reliable')
    modules['rclpy.qos'].qos_profile_sensor_data = 'sensor_data'
    modules['sensor_msgs.msg'].Image = object
    modules['sensor_msgs.msg'].CameraInfo = object
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return state


def receive(tmp_path, state, **kwargs):
    from perception_mvp.ros_capture import capture_inspection_view
    return capture_inspection_view(dict(mode='REAL', check_id='fixed', observation_seq=2),
        'V0', lambda: state.active, output_root=tmp_path, scene_id='synthetic',
        calibration_id='fixture', robot_pose=lambda view: {'basis': 'synthetic only'},
        is_stopped=lambda view: True, **kwargs)


def test_ros_one_shot_closes_before_coverage_and_preserves_context(tmp_path, fake_ros):
    def coverage(directory, manifest, view):
        assert fake_ros.closed and fake_ros.shutdown
        assert manifest['check_id'] == 'fixed' and view == 'V0'
        return dict(verified_regions=[], verification_basis=None)
    record = receive(tmp_path, fake_ros, verify_occupancy=coverage)
    assert record['verified_regions'] == []
    assert load_frame(record['directory'])[-1]['check_id'] == 'fixed'
    assert len(fake_ros.subscriptions) == 6
    rgb_qos = dict(fake_ros.qoses)['/camera/color/image_raw']
    assert rgb_qos.reliability == 'reliable' and rgb_qos.depth == 1
    for topic, qos in fake_ros.qoses:
        if topic.endswith('/camera_info'):
            assert qos == 'sensor_data'
        else:
            assert qos.reliability == 'reliable' and qos.depth == 1


def test_cancel_before_capture_opens_no_subscriptions(tmp_path, fake_ros):
    fake_ros.active = False
    with pytest.raises(RuntimeError, match='cancelled'):
        receive(tmp_path, fake_ros)
    assert fake_ros.subscriptions == [] and not list(tmp_path.iterdir())


def test_stale_ros_packets_timeout_and_close(tmp_path, fake_ros, monkeypatch):
    fake_ros.frame_ns = 500_000_000
    ticks = iter([0., 0., 2.])
    monkeypatch.setattr('perception_mvp.ros_capture.time.monotonic', lambda: next(ticks))
    with pytest.raises(TimeoutError, match='clocks') as caught:
        receive(tmp_path, fake_ros, timeout=1.)
    assert caught.value.view == 'V0'
    assert caught.value.reception['missing_topics'] == []
    assert caught.value.reception['latest_age_ms']['rgb'] == 500.
    assert caught.value.reception['latest_before_request']['rgb'] is True
    assert caught.value.reception['received_counts']['raw_info'] == 1
    assert fake_ros.closed and fake_ros.shutdown and not list(tmp_path.iterdir())


def test_cancel_during_coverage_does_not_return_observation(tmp_path, fake_ros):
    def coverage(*args):
        fake_ros.active = False
        return dict(verified_regions=[], verification_basis=None)
    with pytest.raises(RuntimeError, match='cancelled'):
        receive(tmp_path, fake_ros, verify_occupancy=coverage)
    assert fake_ros.closed and fake_ros.shutdown


def test_cancel_during_reception_closes_without_saving(tmp_path, fake_ros, monkeypatch):
    import rclpy
    original = rclpy.spin_once
    def cancel_spin(*args, **kwargs):
        original(*args, **kwargs)
        fake_ros.active = False
    monkeypatch.setattr(rclpy, 'spin_once', cancel_spin)
    with pytest.raises(RuntimeError, match='cancelled'):
        receive(tmp_path, fake_ros)
    assert fake_ros.closed and fake_ros.shutdown and not list(tmp_path.iterdir())


def test_moving_view_does_not_subscribe(tmp_path, fake_ros):
    from perception_mvp.ros_capture import capture_inspection_view
    with pytest.raises(RuntimeError, match='not stopped'):
        capture_inspection_view(dict(mode='REAL', check_id='fixed', observation_seq=0),
            'D1', lambda: True, output_root=tmp_path, scene_id='synthetic',
            calibration_id='fixture', robot_pose=lambda view: {}, is_stopped=lambda view: False)
    assert fake_ros.subscriptions == []


@pytest.mark.parametrize('view', ['V0', 'D1', 'D3'])
@pytest.mark.parametrize('field,value,code', [
    ('request_active', False, 'INSPECTION_REQUEST_INACTIVE'),
    ('workflow_valid', False, 'WORKFLOW_INVALID'),
    ('bundle_valid', False, 'BUNDLE_INVALID'),
    ('is_stopped', False, 'VIEW_NOT_STOPPED'),
    ('is_stopped', np.bool_(True), 'VIEW_NOT_STOPPED'),
    ('is_stopped', 1, 'VIEW_NOT_STOPPED'),
])
def test_capture_failure_identifies_exact_condition_and_view(
        tmp_path, fake_ros, capsys, view, field, value, code):
    import json
    from perception_mvp.ros_capture import capture_inspection_view
    values = dict(request_active=True, workflow_valid=True, bundle_valid=True, is_stopped=True)
    values[field] = value
    called = []
    def read(key):
        called.append(key)
        return values[key]
    with pytest.raises(RuntimeError, match=code) as caught:
        capture_inspection_view(dict(mode='REAL', check_id='diagnostic', check_kind='INITIAL',
                                     observation_seq=0), view, lambda: read('request_active'),
            output_root=tmp_path, scene_id='synthetic', calibration_id='fixture',
            robot_pose=lambda v: {}, is_stopped=lambda v: read('is_stopped'),
            workflow_valid=lambda: read('workflow_valid'), bundle_valid=lambda: read('bundle_valid'))
    event = json.loads(capsys.readouterr().out.split('관측 조건 실패 ', 1)[1])
    assert event['check_id'] == 'diagnostic' and event['view'] == view
    assert event['failed_condition'] == field and event['failure_code'] == code
    assert event['conditions'][field]['value'] == repr(value)
    assert event['conditions'][field]['type'] == f'{type(value).__module__}.{type(value).__name__}'
    assert caught.value.view == view and f'view={view}' in str(caught.value)
    assert called.count(field) == 1 and called[-1] == field
    assert not fake_ros.subscriptions and not list(tmp_path.iterdir())


def test_hand_failure_logs_request_context_and_workflow_without_opening_ros(fake_ros, capsys):
    from perception_mvp.ros_capture import stream_ros_hand
    with pytest.raises(RuntimeError, match='WORKFLOW_INVALID.*view=V0') as caught:
        next(stream_ros_hand(lambda: True, lambda view: True,
            context=dict(check_id='hand-step', check_kind='STEP'), workflow_valid=lambda: False))
    output = capsys.readouterr().out
    assert 'hand-step' in output and 'HAND_RECEPTION' in output and 'workflow_valid' in output
    assert caught.value.view == 'V0' and not fake_ros.subscriptions


def test_stop_hook_exception_is_reported_without_rechecking(fake_ros, capsys):
    from perception_mvp.ros_capture import _require_observation_state
    calls = []
    def stopped(view):
        calls.append(view)
        raise LookupError('controller state unavailable')
    with pytest.raises(RuntimeError, match='STATE_CHECK_FAILED.*is_stopped.*view=D3') as caught:
        _require_observation_state(dict(check_id='hook-failure'), 'D3', 'RGBD_CAPTURE',
                                   lambda: True, stopped)
    assert calls == ['D3'] and isinstance(caught.value.__cause__, LookupError)
    assert 'controller state unavailable' in capsys.readouterr().out
    assert caught.value.view == 'D3' and not fake_ros.subscriptions


def test_coverage_without_basis_cannot_become_verified(tmp_path, fake_ros):
    with pytest.raises(ValueError, match='actual evidence'):
        receive(tmp_path, fake_ros, verify_occupancy=lambda *args: dict(
            verified_regions=[dict(x=0, y=0, width=1, height=1, layer=1)],
            verification_basis=None))
    assert fake_ros.closed and fake_ros.shutdown


def test_ros_hand_generator_yields_rgb_depth_and_closes(fake_ros):
    from threading import get_ident
    from perception_mvp.ros_capture import stream_ros_hand
    stream = stream_ros_hand(lambda: fake_ros.active, lambda view: view == 'V0')
    try:
        rgb, depth, timestamp = next(stream)
        assert rgb.shape == (2, 3, 3) and depth.shape == (2, 3)
        assert depth.dtype == np.uint16 and timestamp > 0
        assert not fake_ros.closed
        assert fake_ros.receiver_thread != get_ident()
    finally:
        stream.close()
    assert fake_ros.closed and fake_ros.shutdown
    assert len(fake_ros.subscriptions) == 2
    assert dict(fake_ros.qoses)['/camera/color/image_raw'].reliability == 'reliable'
    assert dict(fake_ros.qoses)['/camera/aligned_depth_to_color/image_raw'].reliability == 'reliable'


def test_ros_hand_generator_stop_while_waiting_closes(fake_ros):
    from perception_mvp.ros_capture import stream_ros_hand
    stream = stream_ros_hand(lambda: fake_ros.active, lambda view: True)
    next(stream)
    fake_ros.active = False
    with pytest.raises(RuntimeError, match='cancelled'):
        next(stream)
    assert fake_ros.closed and fake_ros.shutdown


def test_ros_hand_moving_v0_never_subscribes(fake_ros):
    from perception_mvp.ros_capture import stream_ros_hand
    with pytest.raises(RuntimeError, match='not stopped'):
        next(stream_ros_hand(lambda: True, lambda view: False))
    assert fake_ros.subscriptions == []


def test_ros_hand_repeated_frame_cannot_advance_stability(fake_ros):
    from perception_mvp.ros_capture import stream_ros_hand
    stream = stream_ros_hand(lambda: True, lambda view: True, timeout=.01)
    next(stream)
    with pytest.raises(TimeoutError, match='fresh synchronized'):
        next(stream)
    assert fake_ros.closed and fake_ros.shutdown


def test_ros_hand_stale_frame_is_not_hand_absence(fake_ros):
    from perception_mvp.ros_capture import stream_ros_hand
    fake_ros.frame_ns = 500_000_000
    with pytest.raises(TimeoutError, match='fresh synchronized'):
        next(stream_ros_hand(lambda: True, lambda view: True, timeout=.01))
    assert fake_ros.closed and fake_ros.shutdown
