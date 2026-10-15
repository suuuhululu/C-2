"""Record candidate T1/T2/T3 surface references; never move a robot or certify a profile."""
import argparse
from collections import deque
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

NATIVE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(NATIVE), str(NATIVE.parent / 'perception')]
from app.supply_stud.depth_center import processing_frame, source_pixels
from app.supply_stud.backend import observe
from supply_vision.held_xy_alignment import _camera, _transform
from supply_vision.virtual_board_grid import pose_matrix


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def stamp(msg):
    return msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec


def reference_config(step):
    from scripts.round2_three_step_trial import prepare, read, DEFAULT
    matches = [item['config'] for item in prepare(read(DEFAULT)) if item['case']['step_id'] == step]
    if step not in ('T1', 'T2', 'T3') or len(matches) != 1:
        raise ValueError('UNIQUE_SUPPORTED_REFERENCE_STEP_REQUIRED')
    return matches[0]


def pickup_config(step, slot_id=None):
    cfg = reference_config(step)
    if slot_id is None:
        return cfg
    # Manual records for other slots do not inherit T1's assembly target.
    layout = json.loads((NATIVE/'settings/supply_sequence_20261014/opencv_stud_layout.json').read_text())
    matches = [s for s in layout['slots']
               if f"{s['color']}_{s['brick_type']}_{s['slot']:02d}" == slot_id]
    if len(matches) != 1:
        raise ValueError('EXACT_CURRENT_SUPPLY_SLOT_REQUIRED')
    from app.cad_trial import measured_inputs
    inputs = measured_inputs(NATIVE)
    row = matches[0]
    return dict(connection=cfg['connection'], teaching_xy_bounds_mm=cfg['teaching_xy_bounds_mm'],
        pickup_clearance_z_mm=cfg['pickup_clearance_z_mm'],
        blocks=[dict(color=row['color'], brick_type=row['brick_type'], slot=row['slot'],
                     pickup_pose=list(inputs['taught_supply'][slot_id]))])


def pair_packet(buffers, now_ns, after_ns):
    for rgb in reversed(buffers['rgb']):
        if stamp(rgb) <= after_ns:
            continue
        others = [min(buffers[k], key=lambda m: abs(stamp(m)-stamp(rgb)))
                  for k in ('depth', 'info') if buffers[k]]
        if len(others) != 2:
            continue
        packet = (rgb, *others)
        times = [stamp(m) for m in packet]
        if (all(0 <= now_ns-t <= 300_000_000 for t in times)
                and max(times)-min(times) <= 50_000_000):
            return packet
    return None


def pose_gap(a, b):
    x, y = pose_matrix(a), pose_matrix(b)
    return (float(np.linalg.norm(x[:3, 3]-y[:3, 3])),
            float(Rotation.from_matrix(x[:3, :3].T @ y[:3, :3]).magnitude()*180/np.pi))


def surface_point(depth, info, decision, input_size):
    if not decision.get('recognized') or decision.get('center_basis') != 'STUD_ARRAY':
        raise ValueError('STUD_CENTER_NOT_DETECTED')
    k, distortion, width, height, _ = _camera(info)
    if depth.shape != (height, width):
        raise ValueError('DEPTH_SIZE_MISMATCH')
    center = source_pixels(decision['center_uv'], input_size)
    x, y = np.floor(center+.5).astype(int)
    if not (1 <= x < width-1 and 1 <= y < height-1):
        raise ValueError('CENTER_PATCH_OUTSIDE_IMAGE')
    contour = source_pixels(decision['contour_uv'], input_size).astype(np.float32)
    if any(cv2.pointPolygonTest(contour, (float(u), float(v)), False) < 0
           for v in range(y-1, y+2) for u in range(x-1, x+2)):
        raise ValueError('CENTER_PATCH_OUTSIDE_BLOCK')
    patch = depth[y-1:y+2, x-1:x+2].astype(float)
    if not np.isfinite(patch).all() or (patch <= 0).any():
        raise ValueError('INVALID_DEPTH_PATCH')
    z = float(np.median(patch))
    ray = cv2.undistortPoints(np.asarray(center).reshape(1, 1, 2), k, distortion).reshape(2)
    return dict(center_source_uv=center.tolist(), patch_mm=patch.tolist(),
                patch_spread_mm=float(np.ptp(patch)), depth_mm=z,
                surface_center_camera_mm=[float(ray[0]*z), float(ray[1]*z), z])


def bind_pickup_record(row, connection, record):
    expected = f"{row['color']}_{row['brick_type']}_{row['slot']:02d}"
    if (record.get('schema_version') != 'supply-preclose-teaching-record/1'
            or record.get('status') != 'OPERATOR_IDENTIFIED_PRE_CLOSE_PICKUP_POSE'
            or record.get('slot_id') != expected
            or any(record.get(k) != connection[k] for k in ('tcp', 'tool'))):
        raise ValueError('PICKUP_RECORD_BINDING_MISMATCH')
    pose = record['tcp_pose_mm_zyz_deg']
    pose_matrix(pose)
    return list(pose)


def pickup_record(sample, cfg, source):
    from scripts.supply_pick_release_trial import validate_teaching_location
    if any(sample[k] != cfg['connection'][k] for k in ('tcp', 'tool')):
        raise ValueError('TCP_TOOL_BINDING_MISMATCH')
    validate_teaching_location(cfg, sample['posx'])
    if sample['posx'][2] >= cfg['pickup_clearance_z_mm']:
        raise ValueError('TEACH_PICKUP_REQUIRES_LOW_SUPPLY_POSE_NOT_OBSERVATION')
    row = cfg['blocks'][0]
    return dict(schema_version='supply-preclose-teaching-record/1',
        status='OPERATOR_IDENTIFIED_PRE_CLOSE_PICKUP_POSE',
        slot_id=f"{row['color']}_{row['brick_type']}_{row['slot']:02d}",
        color=row['color'], brick_type=row['brick_type'], slot=row['slot'], tcp=sample['tcp'], tool=sample['tool'],
        tcp_pose_mm_zyz_deg=sample['posx'], pose_source=str(source.resolve()),
        previous_runtime_pickup_pose=cfg['blocks'][0]['pickup_pose'],
        operator_confirmation='User invoked teach-pickup after manual alignment before closing',
        runtime_config_changed=False, gripper_command_sent=False, physical_grasp_verified=False,
        surface_center_base_mm=None, surface_reference_accepted=False, physical_commands=0)


def teach_pickup(args):
    cfg = pickup_config(args.step, getattr(args, 'slot_id', None))
    args.output.mkdir(parents=True, exist_ok=False)
    reader = Reader()
    try:
        sample = reader.pose()
        save(args.output/'pose-samples.json', sample)
        record = pickup_record(sample, cfg, args.output/'pose-samples.json')
        record['pose_source_sha256'] = sha256((args.output/'pose-samples.json').read_bytes()).hexdigest()
        save(args.output/'pickup.json', record)
        print('닫기 직전 파지 교시 기록:', args.output/'pickup.json', '(장치 동작 0, 실행 설정 변경 없음)')
    except BaseException as exc:
        save(args.output/'teaching-error.json', dict(error=str(exc), physical_commands=0))
        raise
    finally:
        reader.close()


class Reader:
    # Only these read services are reachable through this recorder.
    QUERIES = {'motion/check_motion': 'CheckMotion',
               'aux_control/get_current_posx': 'GetCurrentPosx',
               'tcp/get_current_tcp': 'GetCurrentTcp', 'tool/get_current_tool': 'GetCurrentTool'}

    def __init__(self):
        import rclpy
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import Image, CameraInfo
        import dsr_msgs2.srv as services
        self.ros = rclpy
        rclpy.init()
        self.node = rclpy.create_node('supply_reference_readonly_recorder')
        self.clients = {path: self.node.create_client(getattr(services, typ),
                        '/dsr01/dsr_controller2/'+path) for path, typ in self.QUERIES.items()}
        self.buffers = {k: deque(maxlen=12) for k in ('rgb', 'depth', 'info')}
        self.subs = []
        for key, topic, typ in [('rgb', '/camera/color/image_raw', Image),
                ('depth', '/camera/aligned_depth_to_color/image_raw', Image),
                ('info', '/camera/color/camera_info', CameraInfo)]:
            self.subs.append(self.node.create_subscription(typ, topic,
                lambda msg, k=key: self.buffers[k].append(msg), qos_profile_sensor_data))

    def query(self, path, **fields):
        client = self.clients[path]
        if not client.wait_for_service(timeout_sec=3):
            raise RuntimeError('READ_SERVICE_UNAVAILABLE:'+path)
        req = client.srv_type.Request()
        for k, v in fields.items():
            setattr(req, k, v)
        future = client.call_async(req)
        self.ros.spin_until_future_complete(self.node, future, timeout_sec=3)
        if not future.done():
            future.cancel()
            raise RuntimeError('READ_SERVICE_TIMEOUT:'+path)
        result = future.result()
        if result is None or (hasattr(result, 'success') and not result.success):
            raise RuntimeError('READ_SERVICE_FAILED:'+path)
        return result

    def pose(self):
        rows = []
        for _ in range(3):
            if self.query('motion/check_motion').status != 0:
                raise ValueError('ROBOT_NOT_STOPPED')
            values = list(self.query('aux_control/get_current_posx', ref=0).task_pos_info[0].data)
            rows.append(values[:6])
        if any(d > .5 or a > .5 for d, a in (pose_gap(rows[0], x) for x in rows)):
            raise ValueError('TCP_NOT_STABLE')
        return dict(posx=rows[-1], samples=rows,
                    tcp=self.query('tcp/get_current_tcp').info,
                    tool=self.query('tool/get_current_tool').info)

    def packet(self, after_ns):
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            self.ros.spin_once(self.node, timeout_sec=.05)
            result = pair_packet(self.buffers, self.node.get_clock().now().nanoseconds, after_ns)
            if result:
                return result
        raise RuntimeError('NO_FRESH_SYNCHRONIZED_RGBD')

    def close(self):
        self.node.destroy_node()
        self.ros.shutdown()


def capture(args):
    cfg = reference_config(args.step)
    if args.pickup_record:
        teaching = json.loads(args.pickup_record.read_text())
        row = cfg['blocks'][0]
        row['baseline_pickup_pose'] = list(row['pickup_pose'])
        row['pickup_pose'] = bind_pickup_record(row, cfg['connection'], teaching)
        row['pose_source'] = str(args.pickup_record.resolve())
        row['pose_basis'] = 'OPERATOR_PRE_CLOSE_RECORD_FOR_REFERENCE_CAPTURE_ONLY'
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/f'{args.step.lower()}-config.json', cfg)
    reader = Reader()
    try:
        before = reader.pose()
        gap = pose_gap(before['posx'], cfg['observation_pose'])
        save(args.output/'precheck.json', dict(actual=before, expected_observation_pose=cfg['observation_pose'],
             distance_mm=gap[0], angle_deg=gap[1], measurement_pose_gate_mm_deg=[.5, .5]))
        print('현재 Base TCP(mm/ZYZ deg):', before['posx'])
        print('기존 공급판 관측 자세:', cfg['observation_pose'])
        print(f'자세 차이: {gap[0]:.3f}mm / {gap[1]:.3f}deg', flush=True)
        if (before['tcp'] != cfg['connection']['tcp'] or before['tool'] != cfg['connection']['tool']):
            raise ValueError('TCP_TOOL_BINDING_MISMATCH')
        if gap[0] > .5 or gap[1] > .5:
            print('관측 자세와 달라 촬영하지 않았습니다. precheck.json을 확인하세요.\n'
                  '현재 자세를 기준으로 덮어쓰거나 허용범위를 늘리지 않습니다.\n'
                  '작업자가 기존 현장 절차로 관측 자세에 배치한 뒤 새 출력 폴더로 기록하세요.\n'
                  '로봇·그리퍼 동작 명령은 보내지 않았습니다.', flush=True)
            raise ValueError('NOT_AT_EXISTING_SUPPLY_OBSERVATION_POSE_NO_MOTION_SENT')
        after_ns = reader.node.get_clock().now().nanoseconds
        for index in range(args.frames):
            rgb, depth, info = reader.packet(after_ns)
            received_at_ns = reader.node.get_clock().now().nanoseconds
            if ([rgb.width, rgb.height] != [1280, 720] or
                    [depth.width, depth.height] != [1280, 720] or
                    [info.width, info.height] != [1280, 720] or
                    len({rgb.header.frame_id, depth.header.frame_id, info.header.frame_id}) != 1 or
                    rgb.header.frame_id != 'camera_color_optical_frame' or depth.encoding != '16UC1'):
                raise ValueError('REGISTERED_1280_RGBD_REQUIRED')
            if rgb.encoding not in ('rgb8', 'bgr8'):
                raise ValueError('RGB8_BGR8_REQUIRED')
            frame = np.frombuffer(rgb.data, np.uint8).reshape(rgb.height, rgb.step)[:, :rgb.width*3]
            frame = frame.reshape(rgb.height, rgb.width, 3).copy()
            if rgb.encoding == 'rgb8':
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            array = np.frombuffer(depth.data, '>u2' if depth.is_bigendian else '<u2').reshape(
                depth.height, depth.step//2)[:, :depth.width].astype(np.uint16)
            prefix = args.output/f'frame-{index:02d}'
            if not cv2.imwrite(str(prefix)+'.rgb.png', frame):
                raise RuntimeError('RGB_WRITE_FAILED')
            if not cv2.imwrite(str(prefix)+'.depth-mm.png', array):
                raise RuntimeError('DEPTH_WRITE_FAILED')
            cv2.imwrite(str(prefix)+'.processing.png', processing_frame(frame, [1280, 720]))
            save(Path(str(prefix)+'.json'), dict(width=info.width, height=info.height,
                frame_id=info.header.frame_id, k=list(info.k), d=list(info.d),
                distortion_model=info.distortion_model,
                stamps_ns=[stamp(m) for m in (rgb, depth, info)],
                ages_at_capture_ms=[(received_at_ns-stamp(m))/1e6
                                    for m in (rgb, depth, info)], depth_encoding=depth.encoding))
            after_ns = max(stamp(m) for m in (rgb, depth, info))
        after = reader.pose()
        gap = pose_gap(before['posx'], after['posx'])
        if gap[0] > .5 or gap[1] > .5 or (before['tcp'], before['tool']) != (after['tcp'], after['tool']):
            raise ValueError('POSE_OR_TCP_CHANGED_DURING_CAPTURE')
        row = cfg['blocks'][0]
        save(args.output/'capture.json', dict(status='RAW_CAPTURE_ONLY', frames=args.frames,
            slot_id=f"{row['color']}_{row['brick_type']}_{row['slot']:02d}",
            step_id=args.step, before=before, after=after, reference_accepted=False,
            physical_commands=0, taught_block_placement='OPERATOR_CONFIRMATION_REQUIRED'))
        print('원자료 저장 완료:', args.output, '(기준점 채택 전, 장치 동작 0)')
    except BaseException as exc:
        save(args.output/'capture-error.json', dict(error=str(exc), reference_accepted=False, physical_commands=0))
        raise
    finally:
        reader.close()


def analyze(args):
    capture_data = json.loads((args.output/'capture.json').read_text())
    cfg = json.loads((args.output/f'{args.step.lower()}-config.json').read_text())
    layout = json.loads(Path(cfg['vision']['layout']).read_text())
    row = cfg['blocks'][0]
    original_pickup = list(row['pickup_pose'])
    if args.pickup_record:
        teaching = json.loads(args.pickup_record.read_text())
        row['pickup_pose'] = bind_pickup_record(row, cfg['connection'], teaching)
    slot = next(s for s in layout['slots'] if (s['color'], s['brick_type'], s['slot']) ==
                (row['color'], row['brick_type'], row['slot']))
    slot['roi_xyxy'] = args.roi
    samples = []
    for meta in sorted(args.output.glob('frame-*.json')):
        prefix = str(meta)[:-5]
        info = json.loads(meta.read_text())
        frame = cv2.imread(prefix+'.rgb.png')
        depth = cv2.imread(prefix+'.depth-mm.png', cv2.IMREAD_UNCHANGED)
        decision = observe(processing_frame(frame, [1280, 720]), layout, row, info['stamps_ns'][0])
        point = surface_point(depth, info, decision, [1280, 720])
        if args.matrix:
            if args.calibration_tcp != capture_data['before']['tcp']:
                raise ValueError('CALIBRATION_TCP_MUST_MATCH_CAPTURE_TCP')
            matrix = _transform(np.load(args.matrix, allow_pickle=False))
            point['surface_center_base_candidate_mm'] = (pose_matrix(capture_data['before']['posx']) @
                matrix @ np.r_[point['surface_center_camera_mm'], 1.])[:3].tolist()
        samples.append(dict(frame=meta.name, decision=decision, **point))
    report = dict(status='CANDIDATE_NOT_ACCEPTED', reference_accepted=False,
        roi_xyxy_processing=args.roi, samples=samples, physical_commands=0,
        pickup_pose=row['pickup_pose'], slot_id=f"{row['color']}_{row['brick_type']}_{row['slot']:02d}",
        step_id=args.step,
        calibration_tcp=args.calibration_tcp, required_checks=['taught_block_placement',
        'calibration_mount_and_tcp_binding', 'roi_and_size_review', 'measured_acceptance_limits'])
    report['pickup_pose_at_capture_config'] = original_pickup
    if args.pickup_record:
        report['pickup_record_source'] = str(args.pickup_record.resolve())
        report['pickup_record_sha256'] = sha256(args.pickup_record.read_bytes()).hexdigest()
        report['pickup_source_semantics'] = 'OPERATOR_PRE_CLOSE_POSE_NOT_SURFACE_CENTER'
    if args.matrix:
        report['matrix_source'] = str(args.matrix.resolve())
        report['matrix_sha256'] = sha256(args.matrix.read_bytes()).hexdigest()
    save(args.output/'surface-candidate.json', report)
    print('후보 자료:', args.output/'surface-candidate.json', '(프로파일 검증 완료 아님)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('teach-pickup', 'capture', 'analyze'))
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument('--step', choices=('T1', 'T2', 'T3'), default='T1',
                        help='T1 yellow 2x2 slot4, T2 blue 2x3 slot3, T3 yellow 2x3 slot5; no motion')
    identity.add_argument('--slot-id', help='Explicit current supply slot, teach-pickup only; not a trial step')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=5, choices=range(3, 21))
    parser.add_argument('--roi', nargs=4, type=int, metavar=('X0', 'Y0', 'X1', 'Y1'))
    parser.add_argument('--matrix', type=Path)
    parser.add_argument('--calibration-tcp')
    parser.add_argument('--pickup-record', type=Path,
                        help='Operator-confirmed pre-close record; bind analysis without changing runtime config')
    args = parser.parse_args()
    if args.slot_id and args.command != 'teach-pickup':
        parser.error('--slot-id is only supported for teach-pickup')
    if args.command == 'analyze' and args.roi is None:
        parser.error('analyze requires --roi measured on the saved processing image')
    {'teach-pickup': teach_pickup, 'capture': capture, 'analyze': analyze}[args.command](args)


if __name__ == '__main__':
    main()
