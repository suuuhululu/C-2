"""B 없는 C/A/D 모의 조립 시험. REAL·Camera·LLM·DB를 호출하지 않는다."""
from copy import deepcopy
from hashlib import sha256
import argparse
import json
import math
import os
from pathlib import Path
from queue import Empty
import time
from uuid import uuid4

from app.supply_slots import next_supply_slot

from app.c_design.main import create_initial_design, review_design_candidate
from app.robot_process import RobotProcess
from planning_trial.assembly_api_fixtures import frame_profile, whole_request
from planning_trial.assembly_motion import plan_step_motion
from planning_trial.assembly_optimizer import assess_step
from planning_trial.assembly_target import calculate_step_tcp
from planning_trial.assembly_wire import normalize_action, pose_mm_zyz
from planning_trial.planner import plan_assembly_from_current
from planning_trial.supply_pick import fit_grid_xy, relative_centres


def read(path):
    return json.loads(Path(path).read_text())


def measured_inputs(robot_root):
    """실측 원자료는 보존하고 후보 계산용 사본만 만든다."""
    root = Path(robot_root)
    source = root/'settings/integration_native35/profile.reference.json'
    profile = deepcopy(read(source)['d_profile'])
    profile.update(transfer_velocity=192., pickup_descent_velocity=24.,
                   pickup_descent_acceleration=6., assembly_approach_velocity=24.,
                   assembly_approach_acceleration=6., pre_contact_slow_distance_mm=10.)
    profile['transport_blending']['radius_mm'] = 30.
    profile['profile_id'] = 'MOCK_CAD_MEASURED_SOURCE_20261012'
    frame = frame_profile()
    frame.update(profile_id='D_CAD_REVIEW_FRAME_20261012', profile_version='1')
    supply = frame['calculation_profiles']['supply']
    taught = read(root/'fixtures/teaching_sources/supply_slot1_grasp_summary.json')['current_tcp_posx']
    grid = fit_grid_xy(supply)
    dx, dy = relative_centres(supply)[('2x2x1', 'blue')]['first_centre_relative_grid']
    supply['first_pick_tcp_mm_zyz_deg'] = [
        taught[j]-dx*grid['x_step_xy_mm'][j]-dy*grid['y_step_xy_mm'][j]
        for j in range(2)] + taught[2:]
    # 最新의 5mm 티칭값에는 과거 8→5mm 보정을 다시 적용하지 않는다.
    supply['anchor_grip_height_above_bottom_mm'] = 5
    supply['desired_grip_height_above_bottom_mm'] = 5
    supply['red_extension'] = dict(user_confirmed_small_faces=True, gap_from_blue_y=2,
        gap_between_red_columns_y=2, columns=2, slots_per_column=6)
    affine = read(root/'calibration/assembly_board_16mm_20261007.json')['affine_comparison']
    layers = {}
    for row in read(root/'calibration/layer_records.json'):
        if row.get('model_excluded') or row.get('adopt_as_layer_z') is False:
            continue
        if row['target']['x'] == 11 and (row['target']['y'] == 11 or row.get('adopt_as_layer_z')):
            layers[row['target']['layer']] = row
    assembly = frame['calculation_profiles']['assembly']
    base = layers[1]
    assembly['coefficient_xyz_mm'] = dict(
        origin=[base['sample']['posx'][j]-base['target']['x']*affine['x_step_xyz_mm'][j]
                -base['target']['y']*affine['y_step_xyz_mm'][j] for j in range(3)],
        x_coefficient=affine['x_step_xyz_mm'], y_coefficient=affine['y_step_xyz_mm'],
        xy_coefficient=[0., 0., 0.])
    assembly['recorded_transfer_height_candidate_mm'] = profile['clearance_z_mm']
    context = whole_request()['assembly_context']
    context['supported_modes'] = ['ROBOT_GRIP']
    return dict(frame=frame, profile=profile, context=context, layers=layers,
                source_sha256=sha256(source.read_bytes()).hexdigest())


def rotation_correction(profile, trial_xy, *, turn):
    """조립판 Y의 수평 방향을 Base XY로 변환한다. 설계 grid/Z는 바꾸지 않는다."""
    if abs(turn) != 90:
        return [0., 0.]
    mapping = profile['grid_mapping']['planner_to_trial_xy']
    c = profile['coefficient_xyz_mm']
    tangent = [mapping[0][1]*(c['x_coefficient'][j]+trial_xy[1]*c['xy_coefficient'][j])
               +mapping[1][1]*(c['y_coefficient'][j]+trial_xy[0]*c['xy_coefficient'][j])
               for j in range(2)]
    norm = math.hypot(*tangent)
    if norm == 0:
        raise ValueError('ASSEMBLY_BOARD_Y_DIRECTION_MISSING')
    return [-2.5*v/norm for v in tangent]


def step_document(inputs, plan, step, action, assumed, slot_index, robot_state):
    frame, profile = deepcopy(inputs['frame']), deepcopy(inputs['profile'])
    assembly = frame['calculation_profiles']['assembly']
    nominal = calculate_step_tcp(step, profile=assembly, grip_axis=action['grip_axis'])
    if nominal['status'] != 'COORDINATE_CANDIDATE':
        raise ValueError(str(nominal.get('errors')))
    trial_xy = nominal['trial_grid_reference_2x2_anchor']
    layer = inputs['layers'][step['after']['layer']]
    c = assembly['coefficient_xyz_mm']
    reference = list(layer['sample']['posx'])
    for j in range(2):
        reference[j] += (trial_xy[0]-layer['target']['x'])*c['x_coefficient'][j]
        reference[j] += (trial_xy[1]-layer['target']['y'])*c['y_coefficient'][j]
    turn = 0 if action['grip_axis'] == assembly['reference']['grip_axis_planner'] else 90
    correction = rotation_correction(assembly, trial_xy, turn=turn)
    reference[:2] = [reference[j]+correction[j] for j in range(2)]
    from planning_trial.supply_pick import calculate_supply_pick
    pick = calculate_supply_pick(step['after']['brick_type'], step['after']['color'], slot_index,
        profile=frame['calculation_profiles']['supply'])['pickup_tcp_pose']['xyz_abc']
    transit = [dict(label=label, xy_mm=xy) for label, xy in (
        ('SUPPLY_20_0', profile['supply_transit_xy_mm']), ('BODY_BYPASS', profile['body_bypass_xy_mm']),
        ('PLACE_BOARD', profile['place_pose'][:2]))]
    assembly['d_onsite_step'] = dict(block=deepcopy(step['after']), grip_axis=action['grip_axis'],
        turn_base_z_deg=turn, reference_pose=reference, pickup_pose=pick,
        approach_offset_mm=20.1, clearance_z_mm=profile['clearance_z_mm'],
        source_sha256=inputs['source_sha256'], loaded_transit=transit)
    slot = dict(brick_type=step['after']['brick_type'], color=step['after']['color'], slot_index=slot_index,
        state='RESERVED', part_confirmation='CONFIRMED',
        slot_id=f"{step['after']['color']}_{step['after']['brick_type']}_{slot_index:02d}",
        reservation_id=str(uuid4()), reservation_generation=slot_index, bound_workflow_generation=1)
    motion = plan_step_motion(plan=plan, step_id=step['step_id'], latest_current=assumed,
        action=action, supply_slot=slot, robot_state=robot_state, frame_profile=frame,
        assembly_context=inputs['context'])
    if motion['status'] != 'CANDIDATE':
        raise ValueError('A_MOTION_BLOCKED: '+str(motion['errors']))
    profile['physical_route_reviewed'] = False
    profile['approach_offset_mm'] = 20.1
    profile['steps'] = {'cad/'+step['step_id']: dict(reference_pose=reference, pickup_pose=pick,
        pickup_open_width_mm=55., pickup_width_mm=35., release_width_mm=48., turn_base_z_deg=turn,
        # RG2 reports 0.1mm increments: 44.1 is the first value strictly above 44mm.
        pickup_start_open_range_mm=[44.1,110.], release_feedback_range_mm=[44.1,110.],
        physical_reference_reviewed=False, xy_grasp_rotation_compensation_measured=False)}
    d_step = dict(case_id='cad', plan_id=plan['plan_id'], step_id=step['step_id'], block=step['after'],
        action=action, current_revision=None, reservation=slot, source_execution_allowed=False)
    session = dict(backend='TEST', provenance='SYNTHETIC', no_vision_trial=True,
        execution_id=str(uuid4()), source_epoch='TEST_CAD', frame_profile_id=frame['profile_id'],
        plan_id=plan['plan_id'], step_id=step['step_id'], current_revision=None,
        expires_unix_s=time.time()+600, request_timeout_s=30, frame_max_age_s=.3,
        frame_max_gap_s=.3, inference_max_latency_s=.3,
        stillness=dict(window_s=.1, max_gap_s=.25, timeout_s=3, min_samples=3,
            sample_max_duration_s=.5, position_mm=.05, orientation_deg=.05,
            linear_mm_s=.01, angular_deg_s=.01))
    return dict(step=d_step, d_profile=profile, session=session, motion=motion,
        robot_state=robot_state, start_zone='assembly', state_basis='ASSUMED_PLAN_PREFIX_NOT_B_CURRENT',
        planned_state_sequence=assumed['current_revision'], correction_base_xy_mm=correction,
        fixture_kind='MOCK_MEASURED_SOURCE_NO_DEVICE')


def run_mock(design, robot_root, *, cancel=None):
    if os.environ.get('C_DESIGN_USE_LLM') != '0':
        raise ValueError('C_DESIGN_USE_LLM=0 required for this offline test')
    events, documents = [], []
    canceled = cancel or (lambda: False)
    review = review_design_candidate(design, kind='initial', current=[],
        text_answers=['좋아 이걸로 하자'], should_stop=canceled)
    report = dict(mode='MOCK', b_called=False, vision_confirmed=False, assembly_completion=False,
        c_review=review, status='HOLD', completed_steps=[], events=events, documents=documents)
    if review['status'] != 'OK' or review['hri_result'] != 'APPROVE':
        report['reason'] = 'C_APPROVAL_NOT_OBTAINED'
        return report
    inputs = measured_inputs(robot_root)
    assumed = dict(current_revision=0, blocks=[])
    raw = plan_assembly_from_current(review['design'], assumed, inputs['context'])
    report['a_whole'] = raw
    if raw['status'] != 'CANDIDATE':
        report['reason'] = raw['status']
        return report
    plan = raw['planning_result']['plan']
    slots = {}
    state = dict(tcp_setting_name=inputs['frame']['tcp_setting_name'],
        tcp_frame_id=inputs['frame']['tcp_frame_id'],
        tcp_pose=pose_mm_zyz(inputs['profile']['place_pose'][:2]
                            +[inputs['profile']['clearance_z_mm']]+inputs['profile']['place_pose'][3:]),
        stopped_verified=True, holding_confirmed=False, active_command_count=0, pending_command_count=0)
    with RobotProcess(robot_root, mode='MOCK') as robot:
        for step in plan['steps']:
            if canceled():
                report['reason'] = 'STOP_REQUESTED'
                break
            assessment = assess_step(review['design'], plan, step['step_id'], assumed, inputs['context'])
            previous = next(a for a in raw['assembly_actions'] if a['step_id'] == step['step_id'])
            options = [o for o in assessment['options'] if o['mode'] == 'ROBOT_GRIP'
                       and o['assistance_kind'] == 'NONE' and o['grip_axis'] == previous['grip_axis']]
            if assessment['status'] != 'CANDIDATE' or not options:
                report['reason'] = 'UNASSISTED_ROBOT_METHOD_UNAVAILABLE'
                break
            action = normalize_action(options[0], plan, step, inputs['context'])
            key = (step['after']['brick_type'], step['after']['color'])
            slot = slots.get(key, 1)
            try:
                document = step_document(inputs, plan, step, action, assumed, slot, deepcopy(state))
            except ValueError as error:
                report['reason'] = str(error)
                break
            documents.append(document)
            robot.send('EXECUTE', document=document)
            end, finished = time.monotonic()+30, False
            while time.monotonic() < end:
                if canceled():
                    robot.send('STOP')
                    report['reason'] = 'STOP_REQUESTED'
                    break
                try:
                    event = robot.receive(timeout=.1)
                except Empty:
                    continue
                events.append(event)
                data = event['data']
                if event['event'] in ('MOVE_SUCCEEDED', 'GRIP_SUCCEEDED'):
                    state['tcp_pose'] = pose_mm_zyz(data['sample']['posx'])
                if event['event'] == 'TRIAL_STEP_EXECUTED':
                    if data['execution_id'] != document['session']['execution_id']:
                        report['reason'] = 'STALE_TRIAL_RESULT'
                        break
                    finished = True
                    break
                if event['event'] in ('COMMAND_REJECTED', 'EXECUTION_HELD', 'PROCESS_EXITED', 'CHANNEL_ERROR'):
                    report['reason'] = data.get('reason', event['event'])
                    break
            if not finished:
                robot.send('STOP')
                report.setdefault('reason', 'STEP_TIMEOUT')
                break
            report['completed_steps'].append(step['step_id'])
            assumed['blocks'].append(deepcopy(step['after']))
            assumed['current_revision'] += 1
            slots[key] = next_supply_slot(slot)
        else:
            report.update(status='TRIAL_EXECUTION_FINISHED', reason=None)
    report['assumed_state'] = dict(planned_state_sequence=assumed['current_revision'],
        blocks=assumed['blocks'], basis='ASSUMED_PLAN_PREFIX_NOT_B_CURRENT')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-root', type=Path, required=True)
    parser.add_argument('--design', type=Path)
    parser.add_argument('--c-text')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.design) == bool(args.c_text):
        parser.error('use exactly one of --design or --c-text')
    if os.environ.get('C_DESIGN_USE_LLM') != '0':
        parser.error('C_DESIGN_USE_LLM=0 required; no LLM/audio/device calls')
    design = read(args.design) if args.design else create_initial_design(text=args.c_text)
    if not args.design:
        if design['status'] != 'OK':
            raise ValueError('C_DESIGN_FAILED: '+str(design['error']))
        design = design['design']
    result = run_mock(design, args.robot_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('status','reason','completed_steps','vision_confirmed')}, ensure_ascii=False))
    return 0 if result['status'] == 'TRIAL_EXECUTION_FINISHED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
