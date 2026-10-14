"""Five-slot pick/release trial. Preview by default; no assembly or vision claims."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import time
import sys
from copy import deepcopy
from uuid import uuid4

NATIVE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NATIVE_ROOT))
sys.path.insert(1, str(NATIVE_ROOT.parent/"perception"))

from app.assembly_motion import motion_still, pose_error, vector
from app.assembly_motion_ros import AssemblyMotionRos
from scripts.assembly_position_trial import guard, run, trial_motion_still

ORDER = [('yellow', '2x2x1', 1, 2), ('yellow', '2x3x1', 2, 3),
         ('blue', '2x2x1', 3, 2), ('blue', '2x3x1', 4, 3), ('red', '1x2x1', 5, 1)]
ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT/'settings/supply_sequence_20261014/config.json'


def load_config(path):
    """Runtime paths may be relative to the checkout; historical sources stay intact."""
    value=json.loads(Path(path).read_text())
    fields=[('vision','layout'),('vision','weights'),('vision','model_deps'),
        ('virtual_grid','board_calibration'),('virtual_grid','static_tf'),('virtual_grid','block_geometry'),
        ('virtual_grid','layer_records'),('assembly_target_source',)]
    for keys in fields:
        parent=value
        for key in keys[:-1]:parent=parent.get(key,{})
        name=keys[-1]
        if parent.get(name) and not Path(parent[name]).is_absolute():
            parent[name]=str((ROOT.parent/parent[name]).resolve())
    return value


def validate(config, require_ready=False):
    vector(config['observation_pose'], 6, 'observation_pose')
    if len(config['blocks']) != 5:
        raise ValueError('EXACT_FIVE_BLOCKS_REQUIRED')
    for row, identity in zip(config['blocks'], ORDER):
        if tuple(row[k] for k in ('color', 'brick_type', 'slot', 'span')) != identity:
            raise ValueError('FIXED_BLOCK_ORDER_REQUIRED')
    return validate_rows(config, config['blocks'], require_ready)


def validate_rows(config, rows, require_ready=False):
    """Retain the trial's device/pose limits for explicitly selected rows."""
    vector(config['observation_pose'], 6, 'observation_pose')
    for row in rows:
        identity = tuple(row[k] for k in ('color', 'brick_type', 'slot', 'span'))
        if row['pickup_pose'] is not None:
            target = vector(row['pickup_pose'], 6, 'pickup_pose')
            if not config.get('target_only_motion',False) and target[2] >= config['observation_pose'][2]:
                raise ValueError('OBSERVATION_MUST_BE_ABOVE_PICKUP')
        if require_ready and (row['pickup_pose'] is None or not row['pose_source']):
            raise ValueError('EXACT_SLOT_AXIS_TEACHING_REQUIRED:'+str(identity))
        if not 0 <= row['close_mm'] < config['open_mm'] <= 110:
            raise ValueError('OPEN_MUST_CLEAR_EVERY_GRASP')
    for key in ('force_stop_n', 'gripper_force_n', 'velocity', 'acceleration', 'angular_velocity', 'angular_acceleration', 'rise_velocity', 'transit_velocity', 'rise_acceleration', 'transit_acceleration'):
        if type(config[key]) not in (int, float) or not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError('INVALID_'+key)
    if config['force_stop_n'] > 45 or config['gripper_force_n'] > 40:
        raise ValueError('EXISTING_FORCE_LIMIT_EXCEEDED')
    return config


def validate_teaching_location(config, target):
    # Plausibility envelope from original supply teaching, not collision clearance.
    bounds = config['teaching_xy_bounds_mm']
    if any(not low <= value <= high for value, (low, high) in zip(target[:2], bounds)):
        raise ValueError('현재 위치는 공급판 교시 범위 밖입니다. 지정 블록 중앙에 수동 정렬한 뒤 teach를 실행하세요.')


def selected_blocks(config, slot=None):
    validate(config)
    rows = [row for row in config['blocks'] if slot is None or row['slot'] == slot]
    if not rows or any(row['pickup_pose'] is None or not row['pose_source'] for row in rows):
        raise ValueError('선택한 블록의 실제 파지 교시가 필요합니다.')
    return rows


def motion_force_limit(config):
    """Separate ordinary motion from contact cutoff; omitted fields stay legacy."""
    return config.get('motion_force_stop_n', config['force_stop_n'])


def segment_rates(config, current, target):
    if target[2] < current[2]-.05:
        return config['velocity'], config['acceleration']
    if math.dist(current[:2], target[:2]) > .05:
        return config['transit_velocity'], config['transit_acceleration']
    if target[2] > current[2]+.05:
        return config['rise_velocity'], config['rise_acceleration']
    return config['transit_velocity'], config['transit_acceleration']


def startup_targets(config, current, zone):
    view = config['observation_pose']
    if zone not in ('assembly', 'supply', 'home'):
        raise ValueError('EXPLICIT_START_ZONE_REQUIRED')
    if max(pose_error(current, view)) <= .5:
        return []
    height = max(current[2], view[2])
    high = list(current); high[2] = height
    targets = [('START_VERTICAL_LIFT', high)]
    route = config['startup_route']
    if zone in ('assembly','home'):
        for label, xy in [('START_PLACE_HIGH', route['place_xy']),
                          ('START_BODY_BYPASS', route['body_bypass_xy']),
                          ('START_SUPPLY_TRANSIT', route['supply_transit_xy'])]:
            if config.get('integrated_cycle') and label=='START_PLACE_HIGH':
                if zone=='home':continue
                label='START_ASSEMBLY_OBSERVATION_HIGH'
            targets.append((label, [*xy, height, *current[3:]]))
    targets.append(('START_OBSERVATION_HIGH', [*view[:2], height, *view[3:]]))
    if height > view[2]:
        targets.append(('START_OBSERVATION_LOWER', list(view)))
    return targets


def execute(driver, config, record, observe, *, slot=None, trial_row=None, start_zone="assembly", display=None, hold_at_pickup=False, sleep=time.sleep, clock=time.monotonic):
    if trial_row is None:
        rows = selected_blocks(config, slot)
    else:
        rows = [deepcopy(trial_row)]
        validate_rows(config, rows, require_ready=True)
    if hold_at_pickup and len(rows)!=1:
        raise ValueError('HOLD_TRIAL_REQUIRES_ONE_BLOCK')
    connection = config['connection']
    limit = motion_force_limit(config)
    target_only=config.get('target_only_motion',False)
    stopped=trial_motion_still if target_only else motion_still
    view = config['observation_pose']
    low_view = list(view); low_view[2] = config['pickup_clearance_z_mm']
    if not target_only and not max(row['pickup_pose'][2] for row in rows) < low_view[2] < view[2]:
        raise ValueError('PICKUP_CLEARANCE_BETWEEN_PICK_AND_VIEW_REQUIRED')
    initial = driver.sample()
    if start_zone=='home':
        deadline=clock()+5.
        while not stopped(initial):
            guard(initial,connection,limit,automatic=False,force_norm_limit=limit,required_gripper_status=initial['gripper_status'])
            if clock()>=deadline:raise RuntimeError('HOME_STOP_WAIT_TIMEOUT')
            sleep(.05);initial=driver.sample()
        if not target_only and (len(initial.get('posj',[]))!=6 or max(abs(a-b) for a,b in zip(initial['posj'],[0.,0.,90.,0.,90.,0.]))>.5):
            raise RuntimeError('CURRENT_HOME_0_0_90_0_90_0_REQUIRED')
        if config.get('integrated_cycle') and initial['gripper_width_mm']<=12.:
            guard(initial,connection,limit,automatic=False,force_norm_limit=limit,required_gripper_status=initial['gripper_status'])
            record('PREPARE_EMPTY_PAD_OPEN_AT_HOME',dict(sample=initial,open_mm=config['open_mm']))
            driver.command_gripper(config['open_mm'],config['gripper_force_n'])
            deadline=clock()+10.
            while True:
                sleep(.05);initial=driver.sample()
                guard(dict(initial,gripper_status=0),connection,limit,automatic=False,force_norm_limit=limit,required_gripper_status=0)
                if initial['gripper_status']==0 and initial['gripper_width_mm']>=config['open_mm']-1:break
                if initial['gripper_status'] not in (0,1,2):raise RuntimeError('GRIPPER_FAULT')
                if clock()>=deadline:raise TimeoutError('HOME_OPEN_TIMEOUT')
    guard(initial, connection, limit, automatic=False, force_norm_limit=limit, required_gripper_status=0)
    if initial['gripper_width_mm'] < config['open_mm']-1:
        raise RuntimeError('START_WITH_OPEN_60MM_GRIPPER_REQUIRED')
    deadline=clock()+5.
    while not stopped(initial):
        if clock()>=deadline:raise RuntimeError('STOPPED_START_WAIT_TIMEOUT')
        sleep(.05);initial=driver.sample()
        guard(initial,connection,limit,automatic=False,force_norm_limit=limit,required_gripper_status=0)
    startup = startup_targets(config, initial['posx'], start_zone)
    for _, target in ([] if target_only else startup):
        if max(pose_error(driver.check_pose(target), target)) > .05:
            raise RuntimeError('START_ROUTE_ENDPOINT_IK_FK_MISMATCH')
    # Coordinate preflight remains available for the legacy path.
    for row in ([] if target_only else rows):
        high = row['pickup_pose'].copy(); high[2] = low_view[2]
        for target in (low_view, high, row['pickup_pose'], view):
            if max(pose_error(driver.check_pose(target), target)) > .05:
                raise RuntimeError('ENDPOINT_IK_FK_MISMATCH')
    record('TRIAL_START', dict(sample=initial, assembly_completion=False))

    def move(label, target):
        current = driver.sample()['posx']
        rate, acceleration = segment_rates(config, current, target)
        record(label, dict(target=target, velocity_mm_s=rate, acceleration_mm_s2=acceleration))
        run(driver, connection, target, limit, record,
            clearance_z=target[2] if target[2]>current[2]+.05 else None,
            transfer_only=target[2]>=current[2]-.05, required_gripper_status=0,
            force_norm_stop_n=limit, transfer_rate=rate, descent_rate=rate,
            transfer_acceleration=acceleration, descent_acceleration=acceleration,
            angular_velocity=config['angular_velocity'], angular_acceleration=config['angular_acceleration'],
            target_only_motion=target_only, sleep=sleep, clock=clock)

    def grip(width, expected):
        before = driver.sample()
        guard(before, connection, limit, automatic=True, force_norm_limit=limit,
              required_gripper_status=0)
        if not stopped(before):
            raise RuntimeError('GRIP_REQUIRES_STOPPED_ROBOT')
        driver.command_gripper(width, config['gripper_force_n'])
        deadline = clock()+10
        stable = 0
        while clock() < deadline:
            sample = driver.sample()
            # Busy status is expected during jaw travel; still check all other guards.
            guard(dict(sample, gripper_status=0), connection, limit, automatic=True,
                  force_norm_limit=limit, required_gripper_status=0)
            if sample['gripper_status'] not in (0, 1, 2):
                raise RuntimeError('GRIPPER_FAULT')
            okay = sample['gripper_status'] == expected and stopped(sample)
            if expected == 0:
                okay = okay and sample['gripper_width_mm'] >= width-1
            stable = stable+1 if okay else 0
            if stable >= 3:
                record('GRIP_FEEDBACK', dict(command_mm=width, expected_status=expected, sample=sample))
                return
            sleep(.1)
        raise TimeoutError('GRIPPER_FEEDBACK_TIMEOUT')

    try:
        fresh = driver.sample()
        if not stopped(fresh) or (not target_only and max(pose_error(fresh['posx'], initial['posx'])) > .05):
            raise RuntimeError('START_CHANGED_AFTER_PREFLIGHT')
        for label, target in startup:
            move(label, target)
        record('START_OBSERVATION_REACHED', driver.sample())
        for row in rows:
            record('BLOCK_BEGIN', row)
            decision = observe(deepcopy(row))
            target = center_target(row, decision)
            record('VISION_DECISION', dict(**decision, commanded_pickup_pose=target))
            if display is not None:
                display(row, decision)
            # Inference is stationary; recheck actual view before any movement.
            fresh = driver.sample()
            guard(fresh, connection, limit, automatic=False, force_norm_limit=limit, required_gripper_status=0)
            if not stopped(fresh) or (not target_only and max(pose_error(fresh['posx'], view)) > .5):
                raise RuntimeError('OBSERVATION_POSE_CHANGED')
            high = target.copy(); high[2] = low_view[2]
            move('OBSERVATION_TO_TRANSIT_HEIGHT', low_view)
            move('BLOCK_HIGH', high)
            move('BLOCK_DESCEND', target)
            grip(row['close_mm'], 2)
            if hold_at_pickup:
                record('PICKUP_COMPLETE_HOLDING', dict(slot=row['slot'], sample=driver.sample(), assembly_completion=False))
                return
            # No loaded lift: return this block to the same supply position.
            sleep(.5)
            # Opening begins held, unlike the empty close command.
            # Validate held state before opening; use the normal feedback loop below.
            sample = driver.sample()
            guard(sample, connection, limit, automatic=True, force_norm_limit=limit, required_gripper_status=2)
            if not stopped(sample):
                raise RuntimeError('RELEASE_REQUIRES_STOPPED_ROBOT')
            driver.command_gripper(config['open_mm'], config['gripper_force_n'])
            deadline = clock()+10
            stable = 0
            while clock() < deadline:
                sample = driver.sample()
                guard(dict(sample, gripper_status=0), connection, limit, automatic=True,
                      force_norm_limit=limit, required_gripper_status=0)
                if sample['gripper_status'] not in (0, 1, 2):
                    raise RuntimeError('GRIPPER_FAULT')
                okay = (sample['gripper_status'] == 0 and stopped(sample)
                        and sample['gripper_width_mm'] >= config['open_mm']-1)
                stable = stable+1 if okay else 0
                if stable >= 3:
                    record('RELEASE_FEEDBACK', sample)
                    break
                sleep(.1)
            else:
                raise TimeoutError('RELEASE_FEEDBACK_TIMEOUT')
            move('EMPTY_RISE', high)
            move('EMPTY_RETURN_AT_TRANSIT_HEIGHT', low_view)
            move('SUPPLY_OBSERVATION', view)
            record('BLOCK_COMPLETE', dict(slot=row['slot'], assembly_completion=False))
        record('TRIAL_COMPLETE', dict(blocks=len(rows), assembly_completion=False, physical_grasp_verified=False))
    except BaseException:
        driver.stop()
        raise


def center_target(row, decision):
    target = row['pickup_pose'].copy()
    decision['center_assist_applied'] = False
    decision['fallback_reason'] = decision.get('reason') or 'METRIC_MAPPING_NOT_VERIFIED'
    if decision.get('slot_id') != f"{row['color']}_{row['brick_type']}_{row['slot']:02d}":
        raise ValueError('VISION_SLOT_BINDING_MISMATCH')
    if decision.get('recognized') is not True or decision.get('center_available', True) is not True:
        return target
    mapping = row.get('center_mapping')
    if not mapping or mapping.get('independently_verified') is not True:
        decision['fallback_reason']='METRIC_MAPPING_NOT_VERIFIED'
        return target
    if decision.get('center_basis') == 'STUD_ARRAY' and mapping.get('center_basis') != 'STUD_ARRAY':
        decision['fallback_reason'] = 'STUD_CENTER_MAPPING_NOT_VERIFIED'
        return target
    import numpy as np
    matrix = np.asarray(mapping['base_xy_mm_per_pixel'], dtype=float)
    center = np.asarray(decision['center_uv'], dtype=float)
    reference = np.asarray(mapping['reference_center_uv'], dtype=float)
    limit = mapping['max_shift_mm']
    if (matrix.shape != (2, 2) or center.shape != (2,) or reference.shape != (2,)
            or not np.isfinite(matrix).all() or not np.isfinite(center).all()
            or not np.isfinite(reference).all() or abs(np.linalg.det(matrix)) < 1e-9
            or type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0):
        raise ValueError('INVALID_REGISTERED_CENTER_MAPPING')
    delta = matrix@(center-reference)
    if np.linalg.norm(delta) > limit:
        decision['fallback_reason'] = 'CENTER_OUT_OF_BOUND'
        return target
    target[:2] = (np.asarray(target[:2])+delta).tolist()
    decision.update(center_assist_applied=True, fallback_reason=None, delta_xy_mm=delta.tolist())
    return target


def box_observation(frame, model, layout, request, stamp):
    from supply_vision.seg_backend import infer_color_candidates, assign_slots, block_class, slot_id
    config = deepcopy(layout)
    config['slots'] = [entry for entry in config['slots'] if slot_id(entry)==request['slot_id']]
    if len(config['slots']) != 1:
        raise ValueError('EXACT_TARGET_SLOT_REQUIRED')
    all_detections = infer_color_candidates(model, frame, config)
    expected = block_class(request['color'], request['brick_type'])
    selected = [d for d in all_detections if d['class_name']==expected]
    state = assign_slots(config, selected, config['confidence'])[0]
    center = None
    if state['status']=='DETECTED':
        x1,y1,x2,y2=state['box']
        center=[(x1+x2)/2,(y1+y2)/2]
        state['status']='BOX_CENTER_CANDIDATE'
    if not selected and all_detections:
        state['reason']='NO_EXPECTED_CLASS_OTHER_CLASS_DETECTED'
    return dict(scope='LOCAL_REQUEST_CONDITIONED_DIAGNOSTIC', slots=[state],
        raw_detections=all_detections, expected_class=expected, center_uv=center,
        frame_stamp_ns=stamp, competing_class_count=len(all_detections)-len(selected),
        class_selection_basis='USER_REQUESTED_BLOCK_CLASS', execution_allowed=False)


class GreenGrayModel:
    def __init__(self, model):
        self.model, self.names = model, model.names

    def predict(self, frame, **kwargs):
        import cv2
        import numpy as np
        hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,np.array([35,40,30],np.uint8),np.array([90,255,255],np.uint8))
        gray=cv2.cvtColor(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        adjusted=frame.copy(); adjusted[mask>0]=gray[mask>0]
        return self.model.predict(adjusted,**kwargs)


class LiveVision:
    def __init__(self, driver, config, evidence_dir):
        from sensor_msgs.msg import Image
        from rclpy.qos import qos_profile_sensor_data
        self.ros = driver.ros
        self.node = self.ros.create_node('supply_sequence_vision_'+uuid4().hex[:8])
        self.config, self.directory = config, evidence_dir
        self.message = None
        self.frame = None
        self.window = 'Supply vision - ESC to stop'
        import cv2
        if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
            raise RuntimeError('비전 팝업은 데스크톱 터미널에서 실행해야 합니다. DISPLAY가 없습니다.')
        cv2.namedWindow(self.window, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window, 960, 720)
        self.subscription = self.node.create_subscription(Image, config['vision']['rgb_topic'],
            self.receive, qos_profile_sensor_data)
        self.layout = json.loads(Path(config['vision']['layout']).read_text())
        if config['vision'].get('backend') == 'opencv_studs':
            return
        deps = config['vision'].get('model_deps')
        if deps:
            sys.path.insert(0, deps)
        from supply_vision.seg_backend import load_model
        # A missing/broken model is a setup failure, not unrecognized imagery.
        self.model = load_model(config['vision']['weights'])
        if config['vision'].get('green_gray', False):
            self.model = GreenGrayModel(self.model)
        self.layout = json.loads(Path(config['vision']['layout']).read_text())
        self.layout['confidence']=config['vision']['confidence']
        self.layout['candidate_confidence']=config['vision']['confidence']

    def receive(self, message):
        self.message = message

    def observe(self, row):
        import cv2
        import numpy as np
        identity = f"{row['color']}_{row['brick_type']}_{row['slot']:02d}"
        result = dict(slot_id=identity, vision_attempted=True, recognized=False,
                      inference_completed=False, center_available=False, reason=None, center_uv=None)
        self.message = None
        self.frame = None
        self.display(row, dict(recognized=False, reason='WAITING_FRESH_RGB'))
        start = self.node.get_clock().now().nanoseconds
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            self.ros.spin_once(self.node, timeout_sec=.1)
            self.pump_sleep(0)
            msg = self.message
            if msg is not None:
                stamp = msg.header.stamp.sec*10**9+msg.header.stamp.nanosec
                now = self.node.get_clock().now().nanoseconds
                if start < stamp <= now and now-stamp < 300_000_000:
                    break
        else:
            result['reason'] = 'NO_FRESH_RGB'
            return result
        if msg.encoding not in ('rgb8', 'bgr8') or msg.step < msg.width*3:
            raise ValueError('UNSUPPORTED_RGB_ENCODING')
        rgb = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)[:, :msg.width*3].reshape(msg.height, msg.width, 3).copy()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) if msg.encoding == 'rgb8' else rgb
        self.frame = frame.copy()
        self.display(row, dict(recognized=False, reason='RUNNING_INFERENCE'))
        path = self.directory/('vision-slot'+str(row['slot'])+'-'+str(time.time_ns())+'.png')
        if not cv2.imwrite(str(path), frame):
            raise OSError('VISION_EVIDENCE_SAVE_FAILED')
        if self.config['vision'].get('backend') == 'opencv_studs':
            from app.supply_stud.backend import observe
            result = observe(frame, self.layout, row, stamp)
            result['rgb_evidence'] = str(path.resolve())
            return result
        from supply_vision.seg_backend import validate_config
        request = dict(request_id=uuid4().hex, step_id='SUPPLY_UNIT_'+str(row['slot']),
            slot_id=identity, color=row['color'], brick_type=row['brick_type'],
            view_id='SUPPLY_VIEW', config_id=self.layout['config_id'], stopped=True,
            not_before_ns=start, expires_at_ns=now+30_000_000_000)
        layout = deepcopy(self.layout)
        for entry in layout['slots']:
            if (entry['color'], entry['brick_type'], entry['slot']) == (row['color'], row['brick_type'], row['slot']):
                entry['grasp_edge_pair'] = 1 if row['span'] == 3 else 0
        validate_config(layout, request)
        response = box_observation(frame, self.model, layout, request, stamp)
        state = response['slots'][0]
        result.update(inference_completed=True, recognized='box' in state,
            center_available=state['status']=='BOX_CENTER_CANDIDATE',
            reason=state['reason'], center_uv=response['center_uv'], center_basis='BOUNDING_BOX_CENTER',
            model_confidence_threshold=layout['confidence'], green_gray=self.config['vision'].get('green_gray',False),
            frame_stamp_ns=stamp, frame_id=msg.header.frame_id, image=str(path.resolve()),
            response=response, layout_status=layout.get('layout_status'),
            detection_status=state['status'])
        return result

    def display(self, row, decision):
        import cv2
        import numpy as np
        canvas = self.frame.copy() if self.frame is not None else np.zeros((480,640,3), dtype=np.uint8)
        for entry in self.layout['slots'] if hasattr(self, 'layout') else []:
            if (entry['color'],entry['brick_type'],entry['slot']) == (row['color'],row['brick_type'],row['slot']):
                x1,y1,x2,y2 = entry['roi_xyxy']
                cv2.rectangle(canvas,(x1,y1),(x2,y2),(255,200,0),2)
        for state in decision.get('response',{}).get('slots',[]):
            if state.get('box'):
                x1,y1,x2,y2 = map(int,state['box'])
                cv2.rectangle(canvas,(x1,y1),(x2,y2),(0,255,0),2)
            geometry = state.get('geometry')
            if geometry and geometry.get('corners_uv'):
                corners=np.asarray(geometry['corners_uv'],dtype=np.int32).reshape(-1,1,2)
                cv2.polylines(canvas,[corners],True,(0,255,255),2)
        if decision.get('contour_uv'):
            cv2.polylines(canvas,[np.asarray(decision['contour_uv'],np.int32)],True,(0,255,0),1)
        for uv in decision.get('stud_centers_uv',[]):
            cv2.circle(canvas,tuple(int(round(v)) for v in uv),3,(255,255,0),-1)
        for line in decision.get('center_lines_uv',[]):
            a,b=np.rint(np.asarray(line)).astype(int)
            cv2.line(canvas,tuple(a),tuple(b),(255,255,255),2)
        if decision.get('center_uv') is not None:
            center=tuple(int(round(v)) for v in decision['center_uv'])
            cv2.drawMarker(canvas,center,(0,0,255),cv2.MARKER_CROSS,20,2)
        lines=[f"Slot {row['slot']} | {row['color']} {row['brick_type']} | span {row['span']}",
               ('OpenCV CLAHE -> baseline | SNAPSHOT' if self.config['vision'].get('backend')=='opencv_studs' else 'YOLO | SNAPSHOT'),
               'Recognized: '+str(bool(decision.get('recognized'))),
               'XY assist: '+str(bool(decision.get('center_assist_applied'))),
               'Reason: '+str(decision.get('fallback_reason') or decision.get('reason') or 'OK')]
        # Text panel above the image keeps the target ROI unobscured.
        panel=np.zeros((140,canvas.shape[1],3),dtype=np.uint8)
        for index,line in enumerate(lines):
            cv2.putText(panel,line,(8,23+index*25),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
        cv2.imshow(self.window,np.vstack((panel,canvas)))
        self.pump_sleep(0)

    def pump_sleep(self, duration):
        import cv2
        deadline=time.monotonic()+duration
        while True:
            if cv2.waitKey(1)&255 == 27:
                raise KeyboardInterrupt('VISION_WINDOW_STOP')
            if cv2.getWindowProperty(self.window,cv2.WND_PROP_VISIBLE)<1:
                raise KeyboardInterrupt('VISION_WINDOW_CLOSED_STOP')
            remaining=deadline-time.monotonic()
            if remaining<=0:
                return
            time.sleep(min(.02,remaining))

    def close(self):
        import cv2
        cv2.destroyWindow(self.window)
        self.node.destroy_node()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preview', 'teach', 'check', 'run'), nargs='?', default='preview')
    parser.add_argument('--config', type=Path, default=DEFAULT)
    parser.add_argument('--slot', type=int, choices=range(1, 6))
    parser.add_argument('--start-zone', choices=('assembly', 'supply'), default='assembly')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-hand-clear', action='store_true')
    parser.add_argument('--green-gray', action='store_true', help='Experimental green-to-gray model input')
    args = parser.parse_args(argv)
    config = validate(load_config(args.config))
    target_only=config.get('target_only_motion',False)
    stopped=trial_motion_still if target_only else motion_still
    if args.green_gray:
        config['vision']['green_gray']=True
    if args.command == 'preview' or (args.command == 'run' and not args.execute):
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION', config=config,
            pending_slots=[r['slot'] for r in config['blocks'] if r['pickup_pose'] is None], physical_commands=0), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'run':
        selected_blocks(config, args.slot)
        if not args.confirm_hand_clear:
            parser.error('run requires --confirm-hand-clear')
    elif args.command == 'teach' and args.slot is None:
        parser.error('teach requires --slot; manually align exact block/axis before capture')
    if args.command == 'teach':
        row = config['blocks'][args.slot-1]
        input(f"공급판 {row['slot']}번 {row['color']} {row['brick_type']}의 {row['span']}축 파지 위치에 직접 수동 정렬하고 정지한 뒤 Enter. 자동 이동은 없습니다: " )
    if os.environ.get('ROS_DOMAIN_ID') != str(config['connection']['ros_domain_id']):
        raise ValueError('EXPLICIT_ROS_DOMAIN_REQUIRED')
    with Path('/tmp/c2-assembly-'+config['connection']['robot_id']+'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        driver = AssemblyMotionRos(dict(mode='REAL', connection=config['connection'], timing=dict(service_timeout_s=3.)))
        old = {}
        try:
            if driver.robot_system() != 0:
                raise RuntimeError('PHYSICAL_ROBOT_REQUIRED')
            if args.command == 'check':
                samples = [driver.sample() for _ in range(3)]
                pending = [row['slot'] for row in config['blocks'] if row['pickup_pose'] is None]
                last = samples[-1]
                error = pose_error(last['posx'], config['observation_pose'])
                print(json.dumps(dict(status='READ_ONLY_PRECHECK', pending_slots=pending,
                    observation_position_error_mm=error[0], observation_angle_error_deg=error[1],
                    observation_ready=all(stopped(s) and (target_only or max(pose_error(s['posx'], config['observation_pose'])) <= .5) for s in samples),
                    gripper_status=last['gripper_status'], gripper_width_mm=last['gripper_width_mm'],
                    open_ready=all(s['gripper_status']==0 and s['gripper_width_mm']>=config['open_mm']-1 for s in samples),
                    physical_commands=0), ensure_ascii=False, indent=2))
                return 0
            if args.command == 'teach':
                samples = [driver.sample() for _ in range(3)]
                if any(not stopped(s) or s['tcp'] != config['connection']['tcp'] or s['tool'] != config['connection']['tool'] for s in samples):
                    raise RuntimeError('STOPPED_CORRECT_TCP_TOOL_REQUIRED')
                if any(max(pose_error(samples[0]['posx'], s['posx'])) > .05 for s in samples):
                    raise RuntimeError('TEACHING_NOT_STABLE')
                validate_teaching_location(config, samples[-1]['posx'])
                evidence = args.config.parent/('slot'+str(args.slot)+'-teaching-'+str(time.time_ns())+'.json')
                evidence.write_text(json.dumps(dict(samples=samples, physical_commands=0), indent=2))
                row = config['blocks'][args.slot-1]
                row.update(pickup_pose=samples[-1]['posx'], pose_source=str(evidence.resolve()))
                validate(config)
                args.config.write_text(json.dumps(config, ensure_ascii=False, indent=2))
                print('기록 완료:', evidence)
                return 0
            def interrupt(*_):
                raise KeyboardInterrupt('OPERATOR_STOP')
            for sig in (signal.SIGINT, signal.SIGTERM):
                old[sig] = signal.signal(sig, interrupt)
            log = args.config.parent/('trial-'+str(time.time_ns())+'.jsonl')
            with log.open('x') as journal:
                def record(event, data):
                    journal.write(json.dumps(dict(event=event, data=data, unix_s=time.time()), ensure_ascii=False, allow_nan=False)+'\n')
                    journal.flush()
                    if event == 'VISION_DECISION':
                        print('비전:', json.dumps({k:data.get(k) for k in ('slot_id','vision_attempted','inference_completed','recognized','center_available','center_assist_applied','fallback_reason')}, ensure_ascii=False), flush=True)
                    if event in ('START_OBSERVATION_REACHED', 'BLOCK_BEGIN', 'BLOCK_COMPLETE', 'TRIAL_COMPLETE'):
                        print(event, data, flush=True)
                vision = LiveVision(driver, config, log.parent)
                try:
                    vision.display(selected_blocks(config, args.slot)[0], dict(reason='MOVING_TO_OBSERVATION'))
                    execute(driver, config, record, vision.observe, slot=args.slot, start_zone=args.start_zone, display=vision.display, sleep=vision.pump_sleep)
                except BaseException as error:
                    record('TRIAL_ABORTED', dict(reason=str(error), assembly_completion=False))
                    raise
                finally:
                    vision.close()
            print('시험 기록:', log)
        finally:
            for sig, handler in old.items():
                signal.signal(sig, handler)
            driver.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, TimeoutError) as error:
        print('시험 중단:', error, file=sys.stderr)
        raise SystemExit(2)
