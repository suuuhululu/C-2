"""Isolated MOCK-only A-message/D-driver bridge for the integration review."""
from copy import deepcopy
import json
import math
import sys

from scipy.spatial.transform import Rotation

from app.assembly_step_bridge import build_plan, step_from_messages
from app.assembly_step_runner import StepReplayDriver
from app.control_driver import execute_step
from app.control_session import ControlSession
from scripts.robot_control_trial import test_session


def verify_route(document, plan, profile):
    """Do not silently replace an A route with a different D profile route."""
    proposal = document['motion']['motion_proposal']
    settings = plan['settings']
    pick, reference = settings['pickup_pose'], settings['reference_pose']
    height = max(profile['clearance_z_mm'], reference[2]+profile['approach_offset_mm'])
    abc = pick[3:]
    route = [('LIFT_HOLDING', pick[:2]+[height]+abc)]
    route += [(label, xy+[height]+abc) for label, xy in (
        ('SUPPLY_20_0', profile['supply_transit_xy_mm']),
        ('BODY_BYPASS', profile['body_bypass_xy_mm']), ('PLACE_BOARD', profile['place_pose'][:2]))]
    route += [('TARGET_HIGH', reference[:2]+[height]+abc),
              ('PRE_CONTACT_HOLDING', reference[:2]+[reference[2]+profile['approach_offset_mm']]+abc)]
    actual = proposal['segments'][2]['waypoints']
    if [w['label'] for w in actual] != [label for label, _ in route]:
        raise ValueError('A_D_ROUTE_LABELS_DIFFER')
    checked = [('PICK_TCP', pick, proposal['pickup_tcp_pose'])]
    checked += [(label, native, wire['tcp_pose']) for (label, native), wire in zip(route, actual)]
    for label, native, wire in checked:
        quat = Rotation.from_euler('ZYZ', native[3:], degrees=True).as_quat()
        if (wire['frame_id'] != 'base_link' or math.dist(native[:3], [v*1000 for v in wire['xyz_m']]) > 1e-6
                or abs(1-abs(sum(a*b for a,b in zip(quat, wire['quaternion_xyzw'])))) > 1e-10):
            raise ValueError('A_D_POSE_DIFFERS:'+label)


def run(document):
    step = step_from_messages(document['assessment'], document['request'], document['motion'], case_id='virtual')
    profile = deepcopy(document['d_profile'])
    if not profile['profile_id'].startswith('MOCK_VIRTUAL_'):
        raise ValueError('VIRTUAL_PROFILE_REQUIRED')
    plan = build_plan(step, profile)
    verify_route(document, plan, profile)
    ticks, events = [0.], []
    def clock(): return ticks[0]
    def sleep(seconds): ticks[0] += seconds
    def record(event, data): events.append(dict(event=event, data=deepcopy(data)))
    value = test_session(plan)
    value['execution_id'] = document['execution_id']
    value['automatic_stage_checks'] = dict(enabled=True, review_ref='VIRTUAL_TEST_ONLY',
        block=deepcopy(plan['block']), release_after_contact_stop=True)
    session = ControlSession(value, plan, record, clock=clock)
    raw = StepReplayDriver(plan['settings']['reference_pose'])
    if document.get('failure') == 'force_ack':
        def lost_ack(*args, **kwargs): raise TimeoutError('FAKE_ACK_LOST')
        raw.set_downward_force = lost_ack
    elif document.get('failure') == 'cleanup':
        def cleanup_failed(*args): raise RuntimeError('FAKE_CLEANUP_FAILED')
        raw.release_compliance = cleanup_failed
    elif document.get('failure') == 'no_load':
        raw.set_downward_force = lambda *args, **kwargs: None
    result, error = None, None
    try:
        result = execute_step(raw, session, dict(tcp='GripperDA_v4', tool='ToolWeight0'),
            plan, profile, lambda *args: False, record, phase='full', clock=clock, sleep=sleep)
    except (RuntimeError, ValueError) as exc:
        error = str(exc)
    return dict(result=result, error=error, events=events,
        mock_grips=raw.grips, mock_moves=raw.moves, mock_stops=raw.stops,
        native_force_requests=getattr(raw, 'native_force_requests', []),
        device_connections=0, physical_simulation=False)


def deny_hardware(event, args):
    if event == 'socket.connect' or (event == 'import' and args[0].split('.')[0] in
            ('rclpy', 'dsr_msgs2', 'pymodbus', 'pyrealsense2', 'sounddevice')):
        raise RuntimeError('Hardware access blocked in virtual worker')


if __name__ == '__main__':
    sys.addaudithook(deny_hardware)
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
