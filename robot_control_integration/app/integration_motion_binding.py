"""A 반환의 픽업/파지 이송 좌표가 D 실행 프로필과 일치하는지 검사한다."""
import math
from app.assembly_step_runner import assembly_target_pose
from scipy.spatial.transform import Rotation


def verify_motion(proposal, plan, profile, robot_state=None):
    settings = plan['settings']; pick = settings['pickup_pose']; ref = settings['reference_pose']
    height = max(profile['clearance_z_mm'], ref[2]+profile['approach_offset_mm'],
                 pick[2]+profile['approach_offset_mm'], profile['place_pose'][2]+profile['approach_offset_mm'])
    route = [('LIFT_HOLDING', pick[:2]+[height]+pick[3:])]
    route += [(label, xy+[height]+pick[3:]) for label, xy in (
        ('SUPPLY_20_0', profile['supply_transit_xy_mm']), ('BODY_BYPASS', profile['body_bypass_xy_mm']),
        ('PLACE_BOARD', profile['place_pose'][:2]))]
    if plan['mode'] == 'HUMAN_ASSEMBLY':
        # Existing A generic tray route skips D's reviewed bypasses. Request an aligned scoped route.
        route += [('TRANSIT_ABOVE_TRAY', profile['place_pose'][:2]+[height]+profile['place_pose'][3:]),
                  ('HANDOVER_TRAY_HOLDING', profile['place_pose'])]
    else:
        orientation = assembly_target_pose(settings)[3:]
        route += [('TARGET_HIGH', ref[:2]+[height]+orientation),
                  ('PRE_CONTACT_HOLDING', ref[:2]+[ref[2]+profile['approach_offset_mm']]+orientation)]
    actual = proposal['segments'][2]['waypoints']
    if [w['label'] for w in actual] != [label for label, _ in route]:
        raise ValueError('A_D_ROUTE_LABELS_DIFFER')
    checked = [('PICK_TCP', pick, proposal['pickup_tcp_pose'])]
    if robot_state is not None:
        source=robot_state['tcp_pose']
        high=max(height,source['xyz_m'][2]*1000)
        expected_labels=['RISE_FROM_CURRENT','PLACE_BOARD_EMPTY','BODY_BYPASS_EMPTY',
                         'SUPPLY_20_0_EMPTY','ABOVE_PICK','PICK_TCP']
        if profile.get('empty_return_skip_place'):expected_labels.remove('PLACE_BOARD_EMPTY')
        approach=proposal['segments'][0]['waypoints']
        if [w['label'] for w in approach]!=expected_labels:
            raise ValueError('A_D_APPROACH_LABELS_DIFFER')
        first=approach[0]['tcp_pose']
        xyz=[*source['xyz_m'][:2],high/1000]
        if math.dist(first['xyz_m'],xyz)>1e-6 or abs(1-abs(sum(a*b for a,b in zip(first['quaternion_xyzw'],source['quaternion_xyzw']))))>1e-6:
            raise ValueError('A_D_START_POSE_DIFFERS')
        empty=[profile['place_pose'][:2],profile['body_bypass_xy_mm'],profile['supply_transit_xy_mm'],pick[:2]]
        if profile.get('empty_return_skip_place'):empty.pop(0)
        checked += [(label,xy+[height]+pick[3:],wire['tcp_pose']) for label,xy,wire in zip(expected_labels[1:-1],empty,approach[1:-1])]
        checked.append(('APPROACH_PICK_TCP',pick,approach[-1]['tcp_pose']))
    checked += [(label, expected, wire['tcp_pose']) for (label,expected),wire in zip(route,actual)]
    for label, expected, wire in checked:
        q = Rotation.from_euler('ZYZ', expected[3:], degrees=True).as_quat()
        quat = wire['quaternion_xyzw']
        if (wire['frame_id'] != 'base_link' or len(quat) != 4 or
                any(type(v) not in (int,float) or not math.isfinite(v) for v in quat) or
                abs(math.dist(quat,[0,0,0,0])-1) > 1e-6 or
                math.dist(expected[:3], [v*1000 for v in wire['xyz_m']]) > .001 or
                abs(1-abs(sum(a*b for a,b in zip(q,quat)))) > 1e-6):
            raise ValueError('A_D_POSE_DIFFERS:'+label)
