"""D taught coordinates + explicit nominal bodies for stage-3 SIM preparation.

No robot process, simulator, IK/path planner or device command is started here.
D's existing pure input/geometry functions remain the coordinate authority.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from app.cad_trial import measured_inputs, step_geometry
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment, handle_step_motion
from planning_trial.assembly_api_fixtures import reassess_request, motion_request
from planning_trial.planner import block_key
from prepare_cpu_model import read_model_bundle
from prepare_gpu_scene import tcp_fk
from prepare_sim_scene import SEED_SCHEMA
from plan_only import checked_pose, digest, vector
from sim_utils import error, pose_matrix
from taught_moveit import pose_mm_zyz, read_teaching, supply_slots

ROOT = Path(__file__).resolve().parents[1]


def source_file(path):
    path = Path(path).resolve(strict=True)
    return dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())


def check_sources(sources):
    if not sources or any(source_file(row['path']) != row for row in sources.values()):
        raise ValueError('Taught/nominal source changed after preparation')


def verify_taught_capture_pose(actual_tcp, motion):
    drift=error(actual_tcp,checked_pose(motion['motion_proposal']['pickup_tcp_pose']))
    if drift[0]>.0008 or drift[1]>.005:
        raise ValueError('Observed capture did not return to the taught pickup pose')
    return drift


def prepare_taught_inputs(whole, robot_root, slot_index=1):
    """Run shared A with the same D per-step taught supply and target profiles."""
    if type(slot_index) is not int or not 1 <= slot_index <= 5:
        raise ValueError('D full-real supply reservation must use slots 1..5')
    root = Path(robot_root).resolve(strict=True)
    supply = ROOT/'config/taught_coordinates_20261012/supply.json'
    board = ROOT/'config/taught_coordinates_20261012/assembly_board_by_studs.json'
    inputs = measured_inputs(root, supply_teaching_path=supply, assembly_board_teaching_path=board)
    teaching, _ = read_teaching(supply)
    feedback = [s for row in teaching['records'].values()
                for s in [row['robot_sample'], *row['receipt']['samples']]]
    if any(s.get('gripper_fingertip_offset_mm') != 0. for s in feedback):
        raise ValueError('This D teaching baseline requires fingertip offset 0mm')
    w = deepcopy(whole)
    w['frame_profile'] = deepcopy(inputs['frame'])
    w['context'].update(frame_profile_id=inputs['frame']['profile_id'],
                        frame_profile_version=inputs['frame']['profile_version'])
    wr = handle_whole_plan(w)
    if not wr.get('planning_result') or wr['planning_result']['status'] != 'READY':
        raise ValueError('Shared A whole plan blocked: '+str(wr.get('stage_errors')))
    if not wr['planning_result']['plan']['steps']:
        raise ValueError('No remaining step to prepare')
    step = wr['planning_result']['plan']['steps'][0]
    rrq = reassess_request(w, wr)
    frame, profile, slot, _ = step_geometry(inputs, step, rrq['selected_action'], slot_index)
    # The exact D per-step profile must be assessed before constructing motion.
    # Updating only the motion profile would invalidate the assessment digest.
    rrq['frame_profile'] = deepcopy(frame)
    rr = handle_step_reassessment(rrq)
    if rr['status'] != 'CANDIDATE':
        raise ValueError('Shared A reassessment blocked: '+str(rr['errors']))
    if any(rr['action_proposal'][k]!=rrq['selected_action'][k] for k in ('mode','assistance_kind','grip_axis')):
        raise ValueError('Reassessment changed the D scoped grasp; prepare a new profile')
    mr = motion_request(rrq, rr, profile=frame)
    mr['reserved_supply_slot'].update(slot, bound_workflow_generation=mr['context']['workflow_generation'])
    mr['reserved_supply_slot']['reservation_id'] = 'sim-taught-'+w['context']['request_id']+'-'+str(slot_index)
    motion = handle_step_motion(mr)
    if motion['status'] != 'CANDIDATE' or motion['execution_allowed'] is not False:
        raise ValueError('Shared A taught motion blocked: '+str(motion['errors']))
    settings = profile['steps']['cad/'+step['step_id']]
    pickup = pose_mm_zyz(settings['pickup_pose'])
    orientation = settings.get('assembly_tcp_zyz_deg')
    if orientation is None:
        orientation = settings['pickup_pose'][3:].copy()
        orientation[0] = (orientation[0]+settings['turn_base_z_deg']+180.) % 360.-180.
    target = settings['reference_pose'][:3]+list(orientation)
    target[2] += profile['approach_offset_mm']
    waiting = pose_mm_zyz(target)
    final = [p for s in motion['motion_proposal']['segments'] for p in s['waypoints']][-1]
    for actual, expected in ((motion['motion_proposal']['pickup_tcp_pose'], pickup),
                             (final['tcp_pose'], waiting)):
        drift = error(checked_pose(actual), pose_matrix(expected))
        if drift[0] > 1e-10 or drift[1] > 1e-8:
            raise ValueError('Shared A and D taught endpoint differ')
    sources = dict(supply=source_file(supply), board=source_file(board),
        assembly=source_file(inputs['assembly_teaching_ref']),
        layers=source_file(root/'calibration/layer_records.json'),
        affine=source_file(root/'calibration/assembly_board_16mm_20261007.json'),
        profile=source_file(root/'settings/integration_native35/profile.reference.json'),
        d_waiting_code=source_file(root/'app/assembly_step_runner.py'),
        d_board_code=source_file(ROOT.parent/'app/assembly_board_calibration.py'),
        d_geometry_code=source_file(ROOT.parent/'app/cad_trial.py'),
        d_teaching_code=source_file(ROOT.parent/'app/robot_teaching.py'))
    active = {k:v for k,v in supply_slots(teaching).items() if v['slot_index'] <= 5}
    return dict(whole_request=w, whole_result=wr, reassessment_request=rrq, reassessment_result=rr,
        motion_request=mr, motion_result=motion, d_profile=profile, taught_supply_slots=active,
        pickup_tcp_pose=pickup, pre_contact_tcp_pose=waiting,
        coordinate_provenance=dict(scope='D_TAUGHT_TCP_NOT_PHYSICAL_BODY_CALIBRATION',
            sources=sources, source_kind='OPERATOR_TAUGHT_READ_ONLY', execution_allowed=False),
        d_gripper_reference=dict(fingertip_offset_mm=0., pickup_width_mm=settings['pickup_width_mm'],
            pickup_open_width_mm=settings['pickup_open_width_mm'], force_n=profile['gripper_force_n'],
            pad_bottom_above_block_bottom_mm=frame['calculation_profiles']['supply']['desired_grip_height_above_bottom_mm'],
            sim_width_joint_mapping_verified=False, real_execution_owner='D'))


def align_nominal_model(model, prepared, geometry):
    """Body/board poses must be supplied separately, never taken from TCP alone."""
    if (geometry['scope'] != 'EXPLICIT_SIM_NOMINAL_GEOMETRY_NOT_PHYSICAL_CALIBRATION' or
            geometry['execution_allowed'] is not False or not geometry['evidence_ref']):
        raise ValueError('Explicit nominal geometry evidence required')
    slots = prepared['taught_supply_slots']
    if set(geometry['supply_bodies']) != set(slots) or len(slots) != 25:
        raise ValueError('All 25 active nominal supply bodies required')
    if Counter(block_key(b['block']) for b in geometry['current_models']) != Counter(
            map(block_key, prepared['motion_request']['latest_current']['blocks'])):
        raise ValueError('Nominal geometry must preserve every Current block')
    if {b['role'] for b in geometry['board_models']} != {'SUPPLY_BOARD','ASSEMBLY_BOARD'}:
        raise ValueError('Both nominal board bodies required')
    m = deepcopy(model)
    m['current'] = deepcopy(prepared['motion_request']['latest_current'])
    m['current_models'] = deepcopy(geometry['current_models'])
    m['board_models'] = deepcopy(geometry['board_models'])
    selected = prepared['motion_request']['reserved_supply_slot']['slot_id']
    m['omitted_legacy_slots'] = [s['slot_id'] for s in m['supply']['slots'] if s['slot_id'] not in slots]
    m['supply']['slots'] = []
    for key, row in slots.items():
        body = deepcopy(geometry['supply_bodies'][key])
        nx, ny, _ = map(int,row['brick_type'].split('x'))
        if not np.allclose(body['size_m'],[nx*.016,ny*.016,.019],atol=1e-9,rtol=0):
            raise ValueError('Preserve adopted full nominal block dimensions')
        vector(body['centre_m'],3); vector([body['yaw_rad']],1)
        body.update(slot_id=key, slot_index=row['slot_index'], color=row['color'], brick_type=row['brick_type'],
            pickup_tcp_pose=deepcopy(row['pickup_tcp_pose']), selected=key==selected,
            geometry_evidence_ref=geometry['evidence_ref'])
        m['supply']['slots'].append(body)
    m['coordinate_provenance'] = deepcopy(prepared['coordinate_provenance'])
    m['d_gripper_reference'] = deepcopy(prepared['d_gripper_reference'])
    m['nominal_geometry_evidence'] = dict(scope=geometry['scope'], evidence_ref=geometry['evidence_ref'])
    m['context'] = deepcopy(prepared['motion_result']['context'])
    m['plan'] = deepcopy(prepared['whole_result']['planning_result']['plan'])
    m['source_profile'] = deepcopy(prepared['motion_request']['frame_profile'])
    m['pickup_tcp_pose'] = deepcopy(prepared['pickup_tcp_pose'])
    m['segments'] = deepcopy(prepared['motion_result']['motion_proposal']['segments'])
    m['precontact'] = dict(tcp_pose=deepcopy(prepared['pre_contact_tcp_pose']),physical_bottom_clearance_verified=False)
    for key in ('target_model','final_models','held_model'):
        m.pop(key,None)  # Legacy target bodies are not updated Current obstacles.
    return m


def prepare_taught_capture_setup(seed, mr, model_bundle, path):
    """Validate newly calculated setup postures before native SIM initialization."""
    candidate = json.loads(Path(path).read_text())
    motion = handle_step_motion(deepcopy(mr))
    if (candidate['scope'] != 'NEW_SIM_IK_SETUP_NOT_REAL_ROBOT_JOINTS' or
            candidate['execution_allowed'] is not False or seed['schema_version']!=SEED_SCHEMA or
            seed['execution_allowed'] is not False or seed['production_B_confirmed'] is not False or
            candidate['seed_digest'] != digest(seed) or
            seed['motion_input_digest'] != digest(mr) or candidate['motion_input_digest'] != digest(mr) or
            motion['status'] != 'CANDIDATE' or seed['a_context'] != motion['context'] or
            seed['reservation_binding'] != motion['reservation_binding'] or seed['current'] != mr['latest_current']):
        raise ValueError('Taught capture setup belongs to another seed/A/Current/reservation')
    check_sources(seed['coordinate_provenance']['sources'])
    if candidate['d_gripper_reference'] != seed['d_gripper_reference']:
        raise ValueError('D gripper reference changed')
    bundle = read_model_bundle(model_bundle)
    if candidate['model_manifest_sha256'] != bundle['manifest_sha256']:
        raise ValueError('Capture posture model changed')
    pickup = checked_pose(motion['motion_proposal']['pickup_tcp_pose'])
    a = tcp_fk(bundle, candidate['initial_q_rad'], candidate['sim_gripper']['open_q_rad'])
    b = tcp_fk(bundle, candidate['lift_q_rad'], candidate['sim_gripper']['close_q_rad'])
    drift = error(a,pickup)
    delta = b[:3,3]-a[:3,3]
    if (drift[0]>.0008 or drift[1]>.005 or not .02<=delta[2]<=.04 or
            np.linalg.norm(delta[:2])>.002 or error(a,b)[1]>.005):
        raise ValueError('New setup does not match taught pickup or short grasp-proof lift')
    if candidate['return_to_pickup_before_capture'] is not True:
        raise ValueError('Taught capture must return to pickup after the holding proof')
    if candidate['sim_gripper']['mapping_scope'] != 'EXISTING_SIM_PRESET_NOT_REAL_WIDTH_FORCE_CALIBRATION':
        raise ValueError('SIM preset must not claim real gripper calibration')
    dt=vector([candidate.get('physics_dt_s',1/60)],1)[0]
    if not 1/240 <= dt <= 1/60:
        raise ValueError('Capture physics resolution must be explicitly within 60..240Hz')
    iterations=candidate.get('solver_iterations',dict(position=64,velocity=4))
    if (set(iterations)!={'position','velocity'} or
            any(type(value) is not int or not 1<=value<=255 for value in iterations.values())):
        raise ValueError('Explicit articulation solver counts must be integers in 1..255')
    return dict(candidate, source_slot_id=seed['reservation_binding']['slot_id'],
                source_files=dict(setup=source_file(path)), old_observation_reused_as_current=False,
                old_trajectory_executed=False, fk_pickup_error_m_rad=drift,physics_dt_s=dt,solver_iterations=iterations)


if __name__ == '__main__':
    import argparse
    from sim_utils import save
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('whole-request','robot-root','model','nominal-geometry','output-dir'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--slot-index',type=int,default=1)
    args=parser.parse_args()
    if args.output_dir.exists():
        raise ValueError('Prepared input directory must be new')
    prepared=prepare_taught_inputs(json.loads(args.whole_request.read_text()),args.robot_root,args.slot_index)
    prepared['coordinate_provenance']['sources']['nominal_geometry']=source_file(args.nominal_geometry)
    geometry=json.loads(args.nominal_geometry.read_text())
    model=align_nominal_model(json.loads(args.model.read_text()),prepared,geometry)
    args.output_dir.mkdir(parents=True)
    for name in ('whole_request','whole_result','reassessment_request','reassessment_result','motion_request','motion_result'):
        save(args.output_dir/(name.replace('_','.')+'.json'),prepared[name])
    save(args.output_dir/'model.json',model)
    save(args.output_dir/'coordinate_alignment.json',{k:v for k,v in prepared.items() if k not in (
        'whole_request','whole_result','reassessment_request','reassessment_result','motion_request','motion_result')})
    print('D_TAUGHT_SIM_INPUT_READY_NO_PLAYBACK:',args.output_dir)
