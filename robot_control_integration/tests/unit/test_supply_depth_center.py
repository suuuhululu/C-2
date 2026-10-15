"""Synthetic RGB-D/robot coordinates only; no ROS or robot connection."""
from collections import deque
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from app.supply_stud.depth_center import load_profile, processing_frame, rgbd_target, source_pixels
from scripts import supply_pick_release_trial as trial


def test_live_subscription_callbacks_have_ros_inspectable_signature(tmp_path, monkeypatch):
    import inspect
    import sys
    import cv2
    from app.supply_stud import depth_center

    callbacks = {}
    def subscribe(kind, topic, callback, qos):
        # rclpy validates callback signatures at subscription construction.
        assert len(inspect.signature(callback).parameters) == 1
        callbacks[topic] = callback
        return topic

    monkeypatch.setitem(sys.modules, 'sensor_msgs.msg', NS(Image=object, CameraInfo=object))
    monkeypatch.setitem(sys.modules, 'rclpy.qos', NS(qos_profile_sensor_data=object()))
    monkeypatch.setenv('DISPLAY', ':synthetic')
    monkeypatch.setattr(cv2, 'namedWindow', lambda *args: None)
    monkeypatch.setattr(cv2, 'resizeWindow', lambda *args: None)
    monkeypatch.setattr(depth_center, 'load_profile', lambda *args: {'synthetic': True})
    layout = tmp_path/'layout.json'; layout.write_text('{}')
    config = dict(vision=dict(depth_center_profile='synthetic', backend='opencv_studs',
                             layout=str(layout), rgb_topic='/camera/color/image_raw'))
    driver = NS(ros=NS(create_node=lambda name: NS(create_subscription=subscribe)))
    camera = trial.LiveVision(driver, config, tmp_path)
    rgb, depth, info = object(), object(), object()
    callbacks['/camera/color/image_raw'](rgb)
    callbacks['/camera/aligned_depth_to_color/image_raw'](depth)
    callbacks['/camera/color/camera_info'](info)
    assert camera.message is rgb
    assert list(camera.depth_messages) == [depth]
    assert list(camera.info_messages) == [info]


def inputs(size=(640, 480)):
    width, height = size
    header = NS(stamp=NS(sec=1, nanosec=100_000_000), frame_id='camera_color_optical_frame')
    image = np.zeros((height, width, 3), np.uint8)
    rgb = NS(header=header, width=width, height=height, encoding='bgr8', step=width*3, data=image.tobytes())
    depth = NS(header=deepcopy(header), width=width, height=height, encoding='16UC1', step=width*2,
               is_bigendian=False, data=np.full((height, width), 400, '<u2').tobytes())
    info = NS(header=deepcopy(header), width=width, height=height, distortion_model='plumb_bob',
              k=[400., 0., width/2, 0., 400., height/2, 0., 0., 1.], d=[0.]*5)
    row = dict(color='blue', brick_type='2x2x1', slot=3, pickup_pose=[-400., 0., 50., 0., 180., 0.])
    center = [320., 240.] if width == 640 else [319.75, 239.75]
    decision = dict(slot_id='blue_2x2x1_03', recognized=True, center_available=True,
                    center_basis='STUD_ARRAY', center_uv=center,
                    contour_uv=[[300., 220.], [340., 220.], [340., 260.], [300., 260.]])
    sample = dict(posx=[-400., 0., 300., 0., 0., 0.], motion_status=0)
    transform = np.eye(4); transform[:3, 3] = [5., -3., 10.]
    profile = dict(schema_version='supply-depth-center/1', independently_verified=True,
        calibration_ref='SYNTHETIC_TEST_ONLY', camera_frame=header.frame_id, input_size=list(size),
        T_tcp_camera_mm=transform.tolist(), max_shift_mm=5., max_height_error_mm=2.,
        max_depth_spread_mm=2., depth_range_mm=[200., 600.],
        references=[dict(slot_id=decision['slot_id'], pickup_pose=row['pickup_pose'].copy(),
                         surface_center_base_mm=[-396., -5., 710.])])
    return row, decision, depth, info, rgb, sample, profile, 1_110_000_000, [[-500., -300.], [-50., 50.]]


@pytest.mark.parametrize('size', [(640, 480), (1280, 720)])
def test_measured_displacement_changes_xy_only(size):
    args = inputs(size)
    before = deepcopy(args[0])
    correction = rgbd_target(*args)
    assert correction['delta_xy_mm'] == pytest.approx([1., 2.])
    decision = args[1]
    decision.update(depth_center_required=True, depth_center=correction)
    target = trial.center_target(args[0], decision)
    assert target[:2] == pytest.approx([-399., 2.])
    assert target[2:] == before['pickup_pose'][2:]
    assert args[0] == before and decision['center_assist_applied'] is True


def test_camera_and_tcp_rotations_are_applied_before_base_displacement():
    args = list(inputs()); args[5]['posx'][-1] = 90.
    # Rotating camera translation (5,-3) by +90 produces (3,5).
    args[6]['references'][0]['surface_center_base_mm'] = [-398., 3., 710.]
    assert rgbd_target(*args)['delta_xy_mm'] == pytest.approx([1., 2.])


@pytest.mark.parametrize('height_delta', [3., 5., -5.])
def test_wider_observation_height_gate_preserves_taught_pickup_height(height_delta):
    args = list(inputs())
    args[6]['max_height_error_mm'] = 5.
    args[6]['max_shift_mm'] = 1.
    args[6]['references'][0]['surface_center_base_mm'] = [-396., -3., 710.-height_delta]
    correction = rgbd_target(*args)
    args[1].update(depth_center_required=True, depth_center=correction)
    target = trial.center_target(args[0], args[1])
    assert correction['delta_xy_mm'] == pytest.approx([1., 0.])
    assert target[:2] == pytest.approx([-399., 0.])
    assert target[2:] == args[0]['pickup_pose'][2:]


@pytest.mark.parametrize('height_limit,dx,dz', [(2., 0., 3.), (5., 0., 5.001),
                                            (5., 0., -5.001), (5., 1.001, 3.)])
def test_displacement_failure_reports_actual_axes_and_keeps_other_gates(height_limit, dx, dz):
    args = list(inputs())
    args[6]['max_height_error_mm'] = height_limit
    args[6]['max_shift_mm'] = 1.
    args[6]['references'][0]['surface_center_base_mm'] = [-395.-dx, -3., 710.-dz]
    with pytest.raises(ValueError, match='SUPPLY_DEPTH_DISPLACEMENT_OUT_OF_BOUND') as error:
        rgbd_target(*args)
    text = str(error.value)
    assert 'finite=True' in text
    assert f'xy_shift_mm={abs(dx):.3f} allowed_xy_mm=1.0' in text
    assert f'height_error_mm={abs(dz):.3f} allowed_height_mm={height_limit}' in text
    assert 'delta_xyz_mm=' in text


def test_repeated_observations_apply_absolute_xy_once_without_accumulating():
    args = list(inputs())
    args[6].update(max_shift_mm=5., max_height_error_mm=5.)
    args[6]['references'][0]['surface_center_base_mm'] = [-395., -3., 710.]
    original_row, original_profile = deepcopy(args[0]), deepcopy(args[6])
    for dx, dy in [(-.1, -4.565), (3., 4.), (-5., 0.), (0., 0.), (-.1, -4.565)]:
        args[1]['center_uv'] = [320.+dx, 240.+dy]
        correction = rgbd_target(*args)
        args[1].update(depth_center_required=True, depth_center=correction)
        expected = [-400.+dx, dy, *original_row['pickup_pose'][2:]]
        assert trial.center_target(args[0], args[1]) == pytest.approx(expected)
        assert trial.center_target(args[0], args[1]) == pytest.approx(expected)
        assert args[0] == original_row and args[6] == original_profile


@pytest.mark.parametrize('dx,dy', [(5.001, 0.), (3.001, 4.), (-5.001, 0.)])
def test_five_mm_xy_gate_rejects_total_distance_over_limit(dx, dy):
    args = list(inputs())
    args[6].update(max_shift_mm=5., max_height_error_mm=5.)
    args[6]['references'][0]['surface_center_base_mm'] = [-395., -3., 710.]
    args[1]['center_uv'] = [320.+dx, 240.+dy]
    with pytest.raises(ValueError, match='DISPLACEMENT_OUT_OF_BOUND.*allowed_xy_mm=5.0'):
        rgbd_target(*args)


def test_surface_failure_reports_missing_depth_without_replacing_it():
    args = list(inputs())
    depth = np.frombuffer(args[2].data, '<u2').copy().reshape(480, 640)
    depth[240, 320] = 0
    args[2].data = depth.tobytes()
    with pytest.raises(ValueError, match='SURFACE_UNAVAILABLE zero_pixels=1/9 min_mm=0.0 max_mm=400.0'):
        rgbd_target(*args)


def test_letterbox_retains_shape_field_and_inverse_coordinates():
    image = np.full((720, 1280, 3), 255, np.uint8)
    frame = processing_frame(image, [1280, 720])
    assert frame.shape == (480, 640, 3)
    assert (frame[:60] == 0).all() and (frame[420:] == 0).all()
    assert (frame[60:420] == 255).all()
    assert source_pixels([319.75, 239.75], [1280, 720]) == pytest.approx([640., 360.])
    with pytest.raises(ValueError, match='INPUT_SIZE_MISMATCH'):
        processing_frame(image, [640, 480])


@pytest.mark.parametrize('fault,reason', [
    ('stale', 'FRESH_SYNCHRONIZED'), ('depth_skew', 'FRESH_SYNCHRONIZED'),
    ('info_skew', 'FRESH_SYNCHRONIZED'), ('future', 'FRESH_SYNCHRONIZED'),
    ('frame', 'REGISTERED_FRAME'), ('size', 'REGISTERED_FRAME'),
    ('encoding', '16UC1'), ('zero', 'SURFACE_UNAVAILABLE'),
    ('spread', 'SURFACE_UNAVAILABLE'), ('range', 'SURFACE_UNAVAILABLE'),
    ('padding', 'CENTER_OUTSIDE_IMAGE'), ('contour', 'PATCH_OUTSIDE_BLOCK'),
    ('slot', 'SLOT_MISMATCH'), ('reference', 'TAUGHT_REFERENCE'),
    ('xy_limit', 'DISPLACEMENT_OUT_OF_BOUND'), ('z_limit', 'DISPLACEMENT_OUT_OF_BOUND'),
    ('bounds', 'TARGET_OUTSIDE_TEACHING_BOUNDS'), ('not_seen', 'STUD_CENTER_REQUIRED'),
])
def test_bad_rgbd_never_produces_a_pick_target(fault, reason):
    a = list(inputs())
    if fault == 'stale': a[7] += 400_000_000
    elif fault == 'depth_skew': a[2].header.stamp.nanosec = 0
    elif fault == 'info_skew': a[3].header.stamp.nanosec = 0
    elif fault == 'future': a[7] = 1_000_000_000
    elif fault == 'frame': a[2].header.frame_id = 'depth_optical_frame'
    elif fault == 'size': a[3].width = 1280
    elif fault == 'encoding': a[2].encoding = '32FC1'
    elif fault in ('zero', 'spread', 'range'):
        pixels = np.full((480, 640), 400, '<u2')
        pixels[240, 320] = dict(zero=0, spread=410, range=700)[fault]
        a[2].data = pixels.tobytes()
    elif fault == 'padding':
        a = list(inputs((1280, 720))); a[1]['center_uv'][1] = 10.
    elif fault == 'contour': a[1]['contour_uv'] = [[0., 0.], [2., 0.], [0., 2.]]
    elif fault == 'slot': a[1]['slot_id'] = 'wrong'
    elif fault == 'reference': a[6]['references'][0]['pickup_pose'][0] -= 1
    elif fault == 'xy_limit': a[6]['max_shift_mm'] = 1.
    elif fault == 'z_limit': a[6]['references'][0]['surface_center_base_mm'][2] += 10.
    elif fault == 'bounds': a[8][0] = [-410., -400.]
    elif fault == 'not_seen': a[1]['recognized'] = False
    with pytest.raises(ValueError, match=reason): rgbd_target(*a)


def test_depth_required_never_uses_legacy_fallback_or_changes_rotation():
    row, decision, *_ = inputs()
    decision['depth_center_required'] = True
    with pytest.raises(ValueError, match='CORRECTION_REQUIRED'): trial.center_target(row, decision)
    correction = rgbd_target(*inputs())
    decision['depth_center'] = correction
    correction['target'][5] = 1.
    with pytest.raises(ValueError, match='XY_ONLY'): trial.center_target(row, decision)


def test_profile_is_bound_to_reviewed_setup_and_layout(tmp_path):
    a = inputs(); profile = a[6]
    layout = tmp_path/'layout.json'; layout.write_text('{"image_size":[640,480]}')
    config = dict(connection=dict(robot_id='test', tcp='tcp', tool='tool'), observation_pose=a[5]['posx'])
    profile.update(connection=config['connection'], observation_pose=config['observation_pose'],
                   layout_sha256=sha256(layout.read_bytes()).hexdigest())
    path = tmp_path/'profile.json'; path.write_text(json.dumps(profile))
    assert load_profile(path, layout, config)['calibration_ref'] == 'SYNTHETIC_TEST_ONLY'
    layout.write_text('{"image_size": [640,480]}')
    with pytest.raises(ValueError, match='SETUP_BINDING'): load_profile(path, layout, config)
    profile['independently_verified'] = False; path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match='NOT_VERIFIED'): load_profile(path, layout, config)


def test_educational_acceptance_requires_explicit_fixed_t1_and_preserves_setup_gate(tmp_path):
    a = inputs(); profile = deepcopy(a[6])
    row = dict(color='yellow', brick_type='2x2x1', slot=4, pickup_pose=a[0]['pickup_pose'])
    layout = tmp_path/'layout.json'; layout.write_text('{"image_size":[640,480]}')
    config = dict(connection=dict(robot_id='test', tcp='tcp', tool='tool'),
        observation_pose=a[5]['posx'], vision={}, blocks=[row],
        trial_step=dict(step_id='T1', target=dict(color='yellow', brick_type='2x2x1',
            x=9, y=9, layer=2, orientation_deg=0)))
    profile.update(independently_verified=False, connection=config['connection'],
        observation_pose=config['observation_pose'], layout_sha256=sha256(layout.read_bytes()).hexdigest(),
        references=[dict(slot_id='yellow_2x2x1_04', pickup_pose=row['pickup_pose'],
                         surface_center_base_mm=profile['references'][0]['surface_center_base_mm'])],
        educational_acceptance=dict(operator_accepted=True,
            scope='FIXED_T1_YELLOW_2X2_SLOT4_ONLY', measured_residual_xy_mm=1.71,
            evidence_ref='SYNTHETIC_TEST_ONLY'))
    path = tmp_path/'profile.json'; path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match='NOT_VERIFIED'): load_profile(path, layout, config)
    config['vision']['allow_educational_depth_profile'] = True
    assert load_profile(path, layout, config)['independently_verified'] is False
    config['trial_step']['step_id'] = 'T2'
    with pytest.raises(ValueError, match='NOT_VERIFIED'): load_profile(path, layout, config)
    config['trial_step']['step_id'] = 'T1'
    config['blocks'][0]['slot'] = 3
    with pytest.raises(ValueError, match='NOT_VERIFIED'): load_profile(path, layout, config)
    config['blocks'][0]['slot'] = 4
    layout.write_text('{"image_size": [640,480]}')
    with pytest.raises(ValueError, match='SETUP_BINDING'): load_profile(path, layout, config)


@pytest.mark.parametrize('fault,reason', [('zero','SURFACE_UNAVAILABLE'),
    ('stale','FRESH_SYNCHRONIZED'), ('frame','REGISTERED_FRAME'), ('shift','DISPLACEMENT')])
def test_educational_profile_does_not_relax_rgbd_rejection(fault, reason):
    a = list(inputs()); a[6]['independently_verified'] = False
    a[6]['educational_acceptance'] = dict(measured_residual_xy_mm=1.71)
    if fault == 'zero': a[2].data = np.zeros((480,640), '<u2').tobytes()
    elif fault == 'stale': a[7] += 400_000_000
    elif fault == 'frame': a[2].header.frame_id = 'wrong_frame'
    else: a[6]['max_shift_mm'] = .1
    with pytest.raises(ValueError, match=reason): rgbd_target(*a)


@pytest.mark.parametrize('deferred', [False, True])
@pytest.mark.parametrize('fault', [None, 'moving', 'changed', 'missing_depth', 'stale_after_inference'])
def test_live_receiver_connects_rgbd_correction_or_blocks_before_target(tmp_path, monkeypatch, fault, deferred):
    from app.supply_stud import backend
    row, decision, depth, info, rgb, sample, profile, now, bounds = inputs((1280, 720))
    camera = trial.LiveVision.__new__(trial.LiveVision)
    camera.depth_profile = profile; camera.depth_messages = deque(); camera.info_messages = deque()
    camera.config = dict(observation_pose=sample['posx'], teaching_xy_bounds_mm=bounds,
                         vision=dict(backend='opencv_studs'))
    camera.layout = {}; camera.directory = tmp_path; camera.message = None
    camera.pending_evidence = []
    camera.config['vision']['defer_depth_evidence'] = deferred
    camera.display = lambda *a: None; camera.pump_sleep = lambda _: None
    calls = []
    def sampling():
        current = deepcopy(sample)
        if fault == 'moving': current['motion_status'] = 1
        if fault == 'changed' and calls: current['posx'][0] += 1.
        calls.append(True)
        return current
    camera.driver = NS(sample=sampling)
    validation_now = 1_410_000_000 if fault == 'stale_after_inference' else now
    clock = iter([1_000_000_000, now] + [validation_now]*20)
    camera.node = NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=next(clock))))
    def spin(*a, **kw):
        camera.message = rgb; camera.info_messages.append(info)
        if fault != 'missing_depth': camera.depth_messages.append(depth)
    camera.ros = NS(spin_once=spin)
    ticks = iter([0., 0., 6.] if fault == 'missing_depth' else [0.]*30)
    monkeypatch.setattr(trial.time, 'monotonic', lambda: next(ticks))
    def infer(frame, *a):
        assert frame.shape == (480, 640, 3)
        return deepcopy(decision)
    monkeypatch.setattr(backend, 'observe', infer)
    if fault:
        expected = ValueError if fault == 'stale_after_inference' else (RuntimeError, TimeoutError)
        with pytest.raises(expected, match='SUPPLY_DEPTH'):
            camera.observe(row)
        if fault != 'stale_after_inference' or deferred:
            assert not list(tmp_path.glob('*.json'))
        if fault == 'stale_after_inference':
            camera.flush_evidence()
            evidence = json.loads(next(tmp_path.glob('*.json')).read_text())
            assert evidence['packet_at_validation']['ages_ms'] == [310.]*3
            assert 'FRESH_SYNCHRONIZED' in evidence['depth_error']
            assert 'depth_center' not in evidence
    else:
        result = camera.observe(row)
        assert trial.center_target(row, result)[:2] == pytest.approx([-399., 2.])
        if deferred:
            assert not list(tmp_path.glob('*.png')) and not list(tmp_path.glob('*.json'))
            assert result['packet_at_validation']['deferred_evidence']
            camera.flush_evidence()
        assert list(tmp_path.glob('*.json'))


@pytest.mark.parametrize('fault', [None, 'missing', 'expired', 'pose'])
def test_execute_uses_corrected_xy_or_stops_before_pickup(monkeypatch, fault):
    from app.assembly_step_runner import StepReplayDriver
    config = trial.load_config(trial.DEFAULT)
    config['vision']['depth_center_profile'] = 'SYNTHETIC_TEST_ONLY'
    row, decision, *_ = inputs()
    row.update(span=2, close_mm=35., pose_source='SYNTHETIC_TEST_ONLY')
    correction = rgbd_target(*inputs())
    correction.update(capture_pose=config['observation_pose'].copy(), expires_monotonic_ns=200)
    decision.update(depth_center_required=True, depth_center=correction)
    if fault == 'missing': decision.pop('depth_center_required')
    elif fault == 'expired': correction['expires_monotonic_ns'] = 50
    elif fault == 'pose': correction['capture_pose'][0] += 1.
    driver = StepReplayDriver(row['pickup_pose'])
    driver.value['posx'] = config['observation_pose'].copy()
    movements = []
    def move(device, connection, target, *a, **kw):
        movements.append(target.copy()); device.value['posx'] = target.copy()
    monkeypatch.setattr(trial, 'run', move)
    monkeypatch.setattr(trial.time, 'monotonic_ns', lambda: 100)
    def execute():
        trial.execute(driver, config, lambda *a: None, lambda _: deepcopy(decision),
            trial_row=row, hold_at_pickup=True, sleep=lambda _: None)
    if fault:
        with pytest.raises(RuntimeError, match='SUPPLY_DEPTH'): execute()
        assert not driver.grips and not movements and driver.stops > 0
    else:
        execute()
        assert movements[-1][:2] == pytest.approx([-399., 2.])
        assert movements[-1][2:] == row['pickup_pose'][2:]
        assert len(driver.grips) == 1


@pytest.mark.parametrize('command', ['preview', 'run'])
def test_native_t1_rejects_unverified_profile_before_device(command, monkeypatch):
    from scripts import round2_three_step_trial as native
    import app.assembly_motion_ros as ros
    def forbidden(*a, **kw): raise AssertionError('DEVICE_ACCESS_FORBIDDEN')
    monkeypatch.setattr(ros, 'AssemblyMotionRos', forbidden)
    template = trial.ROOT/'settings/supply_depth_center.template.json'
    with pytest.raises(ValueError, match='CALIBRATION_NOT_VERIFIED'):
        native.main([command, '--only-step', 'T1', '--supply-depth-profile', str(template)])


def test_readonly_headless_camera_never_uses_window_or_key_functions(tmp_path, monkeypatch):
    import sys
    import cv2
    monkeypatch.setitem(sys.modules, 'sensor_msgs.msg', NS(Image=object, CameraInfo=object))
    monkeypatch.setitem(sys.modules, 'rclpy.qos', NS(qos_profile_sensor_data=object()))
    monkeypatch.delenv('DISPLAY', raising=False); monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    def forbidden(*a, **kw): pytest.fail('Headless check called a window function')
    for name in ('namedWindow', 'resizeWindow', 'imshow', 'waitKey', 'destroyWindow'):
        monkeypatch.setattr(cv2, name, forbidden)
    layout = tmp_path/'layout.json'; layout.write_text('{}')
    node = NS(create_subscription=lambda *a: object(), destroy_node=lambda: None)
    camera = trial.LiveVision(NS(ros=NS(create_node=lambda _: node)),
        dict(vision=dict(show_window=False, layout=str(layout), backend='opencv_studs', rgb_topic='rgb')),tmp_path)
    camera.display({}, {}); camera.pump_sleep(0); camera.close()


@pytest.mark.parametrize('age_ns,accepted', [(301_647_878, True), (309_999_999, True), (311_000_000, False)])
def test_explicit_310ms_profile_accepts_only_inside_requested_limit(age_ns, accepted):
    a = list(inputs()); a[6] = deepcopy(a[6]); a[6]['max_packet_age_ms'] = 310.
    stamp = a[4].header.stamp.sec*10**9+a[4].header.stamp.nanosec
    a[7] = stamp+age_ns
    if accepted: assert rgbd_target(*a)['status'] == 'READY'
    else:
        with pytest.raises(ValueError, match='FRESH_SYNCHRONIZED'):rgbd_target(*a)


def test_310ms_setting_does_not_change_default_or_skew_guard():
    a = list(inputs()); a[7] = 1_401_647_878
    with pytest.raises(ValueError, match='FRESH_SYNCHRONIZED'):rgbd_target(*a)
    a[6] = deepcopy(a[6]); a[6]['max_packet_age_ms'] = 310.
    a[2] = deepcopy(a[2]); a[2].header.stamp.nanosec -= 60_000_000
    with pytest.raises(ValueError, match='FRESH_SYNCHRONIZED'):rgbd_target(*a)


@pytest.mark.parametrize('optimized',[False,True])
@pytest.mark.parametrize('fault',[None,'late','pose','moving','grip','tcp','force','old_feedback','binding','compute_delay','log_delay'])
def test_one_post_frame_query_reduces_latency_without_skipping_existing_guards(tmp_path,monkeypatch,optimized,fault):
    from app.assembly_step_runner import StepReplayDriver
    from app.supply_stud import backend
    import cv2
    row,decision,depth,info,rgb,pose,profile,_,bounds=inputs()
    row.update(span=2,close_mm=35.,pose_source='SYNTHETIC_TEST_ONLY')
    profile['max_packet_age_ms']=310.
    elapsed=[0];inferred=[False];post_queries=[];handoff_queries=[];movements=[];events=[]
    class Driver(StepReplayDriver):
        def sample(self):
            started=elapsed[0];elapsed[0]+=114_000_000
            value=super().sample()
            value.update(query_duration_s=.114,query_started_monotonic_s=started/1e9,
                query_finished_monotonic_s=elapsed[0]/1e9)
            if inferred[0] and not movements:
                post_queries.append(True)
                if fault=='pose':value['posx'][0]+=1.
                if fault=='moving':value['motion_status']=1
                if fault=='grip':value['gripper_status']=2
                if fault=='tcp':value['tcp']='wrong'
                if fault=='force':value['wrench']=[0.,0.,50.,0.,0.,0.]
                if fault=='old_feedback':value['query_duration_s']=.8
                if fault=='late':elapsed[0]+=400_000_000
            return value
    driver=Driver(row['pickup_pose']);driver.value['posx']=pose['posx'].copy()
    config=trial.load_config(trial.DEFAULT)
    config['observation_pose']=pose['posx'].copy();config['teaching_xy_bounds_mm']=bounds
    config['vision'].update(backend='opencv_studs',depth_center_profile='SYNTHETIC_ONLY',
        defer_depth_evidence=optimized,defer_depth_pose_validation=optimized)
    camera=trial.LiveVision.__new__(trial.LiveVision)
    camera.driver=driver;camera.config=config;camera.depth_profile=profile;camera.layout={}
    camera.directory=tmp_path;camera.pending_evidence=[]
    camera.depth_messages=deque();camera.info_messages=deque()
    camera.node=NS(get_clock=lambda:NS(now=lambda:NS(nanoseconds=1_000_000_000+elapsed[0])))
    def spin(*a,**kw):
        elapsed[0]+=100_000_000
        stamp=1_000_000_000+elapsed[0]-59_000_000
        for m in (rgb,depth,info):m.header.stamp.sec,m.header.stamp.nanosec=divmod(stamp,10**9)
        camera.message=rgb;camera.depth_messages.append(depth);camera.info_messages.append(info)
    camera.ros=NS(spin_once=spin);camera.pump_sleep=lambda *a:None
    def display(row,result):
        if result.get('center_assist_applied'):elapsed[0]+=180_000_000
    camera.display=display
    def image_write(*a):elapsed[0]+=20_000_000;return True
    monkeypatch.setattr(cv2,'imwrite',image_write)
    def infer(*a):
        elapsed[0]+=16_000_000;inferred[0]=True
        report=deepcopy(decision);report['frame_stamp_ns']=rgb.header.stamp.sec*10**9+rgb.header.stamp.nanosec
        if fault=='binding':report['frame_stamp_ns']+=1
        return report
    monkeypatch.setattr(backend,'observe',infer)
    monkeypatch.setattr(trial.time,'monotonic_ns',lambda:elapsed[0])
    monkeypatch.setattr(trial.time,'monotonic',lambda:elapsed[0]/1e9)
    if fault=='compute_delay':
        from app.supply_stud import depth_center
        calculate=depth_center.rgbd_target
        def slow(*a,**kw):
            result=calculate(*a,**kw);elapsed[0]+=200_000_000;return result
        monkeypatch.setattr(depth_center,'rgbd_target',slow)
    def move(d,c,target,*a,**kw):
        movements.append(target.copy());d.value['posx']=target.copy()
    monkeypatch.setattr(trial,'run',move)
    def record(event,data):
        if event=='VISION_DECISION' and fault=='log_delay':elapsed[0]+=400_000_000
        if event=='SUPPLY_DEPTH_HANDOFF':handoff_queries.append(len(post_queries))
        events.append((event,deepcopy(data)))
    def execute():
        trial.execute(driver,config,record,camera.observe,
            trial_row=row,hold_at_pickup=True,display=camera.display,sleep=lambda *a:None,
            clock=lambda:elapsed[0]/1e9,finalize_observation=camera.finalize_depth if optimized else None)
    if not optimized or fault:
        with pytest.raises((RuntimeError,ValueError)) as error:execute()
        if fault is None:assert 'SUPPLY_DEPTH_EXPIRED_BEFORE_PICKUP' in str(error.value)
        assert not movements and not driver.grips and driver.stops
    else:
        execute()
        assert handoff_queries==[1] and len(driver.grips)==1
        assert len(post_queries)==2  # First movement's existing state read remains.
        handoff=next(d for e,d in events if e=='SUPPLY_DEPTH_HANDOFF')
        assert handoff['remaining_ms']==pytest.approx(121.)  # 310 - (59 + 16 + 114)
        assert not list(tmp_path.glob('*.json'))
        camera.flush_evidence()
        evidence=json.loads(next(tmp_path.glob('*.json')).read_text())
        assert evidence['packet_at_validation']['ages_ms']==[189.]*3
        assert evidence['pose_query_ms']==pytest.approx(114.)


@pytest.mark.parametrize('dx,dy,dz,accepted', [(6.,8.,8.932,True),(6.,8.,10.,True),
    (10.001,0.,0.,False),(0.,0.,10.001,False)])
def test_ten_mm_limits_accept_reported_height_and_reject_over_limit(dx,dy,dz,accepted):
    args=list(inputs());profile=args[6]
    profile.update(max_shift_mm=10.,max_height_error_mm=10.,max_depth_spread_mm=10.)
    profile['references'][0]['surface_center_base_mm']=[-395.-dx,-3.-dy,710.-dz]
    if not accepted:
        with pytest.raises(ValueError,match='SUPPLY_DEPTH_DISPLACEMENT_OUT_OF_BOUND'):
            rgbd_target(*args)
        return
    before=deepcopy(args[0])
    correction=rgbd_target(*args)
    args[1].update(depth_center_required=True,depth_center=correction)
    target=trial.center_target(args[0],args[1])
    assert correction['delta_xy_mm']==pytest.approx([dx,dy])
    assert target[2:]==before['pickup_pose'][2:] and args[0]==before


@pytest.mark.parametrize('spread,accepted',[(10,True),(11,False)])
def test_ten_mm_depth_spread_keeps_finite_packet_and_range_checks(spread,accepted):
    args=list(inputs());args[6].update(max_shift_mm=10.,max_height_error_mm=10.,max_depth_spread_mm=10.)
    depth=np.frombuffer(args[2].data,dtype='<u2').copy().reshape(480,640)
    depth[239,319]=400+spread;args[2].data=depth.tobytes()
    if accepted:assert rgbd_target(*args)['depth_mm']==400.
    else:
        with pytest.raises(ValueError,match='SUPPLY_DEPTH_'):
            rgbd_target(*args)
