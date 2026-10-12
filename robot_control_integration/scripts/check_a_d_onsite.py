"""Export one D onsite Step as A input and compare pure calculation outputs.

Imports planning calculators only; no ROS, device connection or execution session.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_A = (ROOT.parent/'planning_reference' if (ROOT.parent/'planning_reference/planning_trial').is_dir()
             else Path('/home/rokey/Documents/ChatGPT/협동2'))
DEFAULT_D = ROOT/'settings/onsite_blue_slot1_11_11_l2_20261011/auto-blend-1fec868f-e364-408b-8cea-fd897635b65c.smooth040.assembly.profile.json'


def make_profile(document, source_hash):
    from planning_trial.assembly_api_fixtures import frame_profile
    d = document['d_profile']
    block = document['step']['block']
    if len(d['steps']) != 1 or block['brick_type'] != '2x2x1' or block['color'] != 'blue' or block['orientation_deg'] != 0:
        raise ValueError('Only the scoped blue 2x2 no-turn onsite Step is supported')
    s = next(iter(d['steps'].values()))
    if s.get('turn_base_z_deg') != 0 or document['source_slot']['slot_id'] != 'blue_2x2x1_01':
        raise ValueError('Explicit zero turn and blue first-slot identity required')
    p = frame_profile()
    p.update(profile_id='D_ONSITE_STEP_'+source_hash[:16], profile_version='onsite-input/0.1',
             calibration_version='D_PROFILE_SHA256_'+source_hash)
    p['speed_profile'] = dict(profile_id=d['profile_id'], version='D_ONSITE_REVIEW', verification='UNVERIFIED')
    cp = p['calculation_profiles']
    cp['supply']['d_taught_slot'] = dict(identity=dict(brick_type='2x2x1', color='blue', slot_index=1),
        tcp_mm_zyz_deg=deepcopy(s['pickup_pose']), source_sha256=document['pickup_source']['sha256'])
    cp['assembly']['d_onsite_step'] = dict(block=deepcopy(block), grip_axis='x', turn_base_z_deg=0,
        reference_pose=deepcopy(s['reference_pose']), pickup_pose=deepcopy(s['pickup_pose']),
        approach_offset_mm=d['approach_offset_mm'], clearance_z_mm=d['clearance_z_mm'], source_sha256=source_hash,
        loaded_transit=[dict(label=label, xy_mm=deepcopy(xy)) for label, xy in (
            ('SUPPLY_20_0', d['supply_transit_xy_mm']), ('BODY_BYPASS', d['body_bypass_xy_mm']),
            ('PLACE_BOARD', d['place_pose'][:2]))])
    return p


def calculate(document, source_hash):
    from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment, handle_step_motion
    from planning_trial.assembly_api_fixtures import whole_request, reassess_request, motion_request
    from planning_trial.assembly_wire import pose_mm_zyz
    block = document['step']['block']
    profile = make_profile(document, source_hash)
    # These are review snapshots, never observations adopted by the live Backend.
    support = [dict(block, layer=i) for i in range(1, block['layer'])]
    req = whole_request(dict(design_version=1, blocks=support+[block]),
                        dict(current_revision=len(support), blocks=support), profile=profile)
    whole = handle_whole_plan(req)
    if whole['planning_result']['status'] != 'READY':raise ValueError('A WholePlan not READY')
    reassessment = reassess_request(req, whole)
    assessed = handle_step_reassessment(reassessment)
    if assessed['status'] != 'CANDIDATE' or assessed['action_proposal']['mode'] != 'ROBOT_GRIP':
        raise ValueError('A Step reassessment not ROBOT_GRIP candidate')
    motion_input = motion_request(reassessment, assessed, profile=profile)
    s = next(iter(document['d_profile']['steps'].values()))
    observe = s.get('handover_trial', {}).get('observe_pose', [400.851,8.573,314.981,175.022,-179.595,175.461])
    motion_input['robot_state'].update(tcp_pose=pose_mm_zyz(observe), stop_observation_ref='D_TAUGHT_OBSERVE_REVIEW_NOT_LIVE')
    motion = handle_step_motion(motion_input)
    if motion['status'] != 'CANDIDATE':raise ValueError(str(motion['errors']))
    return dict(frame_profile=profile, whole_request=req, whole_result=whole,
                reassessment_request=reassessment, reassessment_result=assessed,
                motion_request=motion_input, motion_result=motion)


def compare(document, bundle):
    from planning_trial.assembly_wire import pose_mm_zyz
    d = document['d_profile']; s = next(iter(d['steps'].values()))
    proposal = bundle['motion_result']['motion_proposal']
    approach = s['reference_pose'][:3]+s['pickup_pose'][3:]
    approach[2] += d['approach_offset_mm']
    height = max(d['clearance_z_mm'], approach[2])
    expected = [('LIFT_HOLDING', s['pickup_pose'][:2]+[height]+s['pickup_pose'][3:])]
    expected += [(label, xy+[height]+s['pickup_pose'][3:]) for label, xy in (
        ('SUPPLY_20_0',d['supply_transit_xy_mm']), ('BODY_BYPASS',d['body_bypass_xy_mm']),
        ('PLACE_BOARD',d['place_pose'][:2]), ('TARGET_HIGH',s['reference_pose'][:2]))]
    expected.append(('PRE_CONTACT_HOLDING',approach))
    actual = proposal['segments'][2]['waypoints']
    initial = bundle['motion_request']['robot_state']['tcp_pose']
    high = max(initial['xyz_m'][2]*1000, height, s['pickup_pose'][2]+30.0)
    place = d['place_pose'][:2]; abc = s['pickup_pose'][3:]
    empty_expected = [('PLACE_BOARD_EMPTY_HIGH',place+[high]+abc),('PLACE_BOARD_EMPTY',place+[height]+abc),
        ('BODY_BYPASS_EMPTY',d['body_bypass_xy_mm']+[height]+abc),
        ('SUPPLY_20_0_EMPTY',d['supply_transit_xy_mm']+[height]+abc),
        ('ABOVE_PICK',s['pickup_pose'][:2]+[height]+abc),('PICK_TCP',s['pickup_pose'])]
    rows = []
    for label, native in [('PICK_TCP',s['pickup_pose'])]+expected:
        actual_pose = proposal['pickup_tcp_pose'] if label=='PICK_TCP' else next(w['tcp_pose'] for w in actual if w['label']==label)
        wire = pose_mm_zyz(native)
        delta = [(a-b)*1000 for a,b in zip(actual_pose['xyz_m'],wire['xyz_m'])]
        dot = abs(sum(a*b for a,b in zip(actual_pose['quaternion_xyzw'],wire['quaternion_xyzw'])))
        rows.append(dict(label=label, D_xyz_mm=native[:3], A_minus_D_xyz_mm=delta,
                         attitude_matches=abs(1-dot)<1e-10, passed=max(map(abs,delta))<1e-8 and abs(1-dot)<1e-10))
    empty_actual = proposal['segments'][0]['waypoints']
    rise = deepcopy(initial); rise['xyz_m'][2]=high/1000
    for label, wire in [('RISE_FROM_CURRENT',rise)]+[(label,pose_mm_zyz(native)) for label,native in empty_expected]:
        actual_pose = next(w['tcp_pose'] for w in empty_actual if w['label']==label)
        delta = [(a-b)*1000 for a,b in zip(actual_pose['xyz_m'],wire['xyz_m'])]
        dot = abs(sum(a*b for a,b in zip(actual_pose['quaternion_xyzw'],wire['quaternion_xyzw'])))
        rows.append(dict(label='EMPTY/'+label, D_xyz_mm=[v*1000 for v in wire['xyz_m']], A_minus_D_xyz_mm=delta,
                         attitude_matches=abs(1-dot)<1e-10, passed=max(map(abs,delta))<1e-8 and abs(1-dot)<1e-10))
    labels = [w['label'] for w in proposal['segments'][0]['waypoints']]
    path_ok = labels==['RISE_FROM_CURRENT','PLACE_BOARD_EMPTY_HIGH','PLACE_BOARD_EMPTY','BODY_BYPASS_EMPTY','SUPPLY_20_0_EMPTY','ABOVE_PICK','PICK_TCP']
    loaded_ok = [w['label'] for w in actual]==[label for label,_ in expected]
    return dict(status='A_D_ONSITE_OFFLINE_MATCH' if all(r['passed'] for r in rows) and path_ok and loaded_ok else 'MISMATCH',
                positions=rows, empty_route_labels=labels, empty_route_matches=path_ok, loaded_route_matches=loaded_ok,
                future_D_operating_policy=dict(assembly_release_width_mm=48.0, assembly_release_owner='D', pickup_close_width_mm=35.0,
                    source='User onsite instructions; historical source documents remain unchanged'),
                sample_Current_not_live=True, execution_allowed=False, physical_verified=False,
                live_A_D_contract_verified=False, robot_motion_commands=0, robot_gripper_commands=0, device_connections=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--d-profile', type=Path, default=DEFAULT_D,
                        help='Default: reviewed blue first-slot -> (11,11) layer2 future template')
    parser.add_argument('--output', type=Path, default=ROOT/'logs/a-d-onsite'/str(uuid4()))
    parser.add_argument('--a-project', type=Path, default=DEFAULT_A)
    args = parser.parse_args()
    sys.path.insert(0, str(args.a_project.resolve()))
    raw = args.d_profile.read_bytes(); document = json.loads(raw)
    pickup_path = Path(document['pickup_source']['path'])
    if not pickup_path.is_absolute():pickup_path=ROOT/pickup_path
    pickup_raw = pickup_path.read_bytes()
    if sha256(pickup_raw).hexdigest()!=document['pickup_source']['sha256']:
        raise ValueError('D pickup teaching source hash mismatch')
    bundle = calculate(document, sha256(raw).hexdigest())
    report = compare(document, bundle)
    args.output.mkdir(parents=True, exist_ok=False)
    provenance=dict(D_profile_path=str(args.d_profile.resolve()), D_profile_sha256=sha256(raw).hexdigest(),
        A_project_path=str(args.a_project.resolve()), A_code_sha256={name:sha256((args.a_project/'planning_trial'/name).read_bytes()).hexdigest()
            for name in ('supply_pick.py','assembly_target.py','assembly_motion.py','assembly_adapter.py','assembly_contract.py')})
    for name, data in {**bundle,'comparison':report,'D_source':document,'provenance':provenance}.items():
        (args.output/(name+'.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(status=report['status'], checked_poses=len(report['positions']),
                         block=document['step']['block'], robot_motion_commands=0, output=str(args.output.resolve())), ensure_ascii=False))
    return 0 if report['status']=='A_D_ONSITE_OFFLINE_MATCH' else 1


if __name__ == '__main__':
    raise SystemExit(main())
