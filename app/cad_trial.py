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
from app.robot_teaching import supply_teaching, assembly_teaching
from app.assembly_board_calibration import load_board_calibration, board_target_pose

from app.c_design.main import create_initial_design, review_design_candidate
from app.robot_process import RobotProcess
from planning_trial.assembly_api_fixtures import frame_profile, whole_request
from planning_trial.assembly_motion import plan_step_motion
from planning_trial.assembly_optimizer import assess_step
from planning_trial.assembly_target import calculate_step_tcp
from planning_trial.assembly_wire import normalize_action, pose_mm_zyz
from planning_trial.planner import BRICK_SIZES, plan_assembly_from_current
from planning_trial.supply_pick import fit_grid_xy, relative_centres


def read(path):
    return json.loads(Path(path).read_text())


def measured_inputs(robot_root, *, supply_teaching_path=None, assembly_board_teaching_path=None):
    """실측 원자료는 보존하고 후보 계산용 사본만 만든다."""
    root = Path(robot_root)
    source = root/'settings/integration_native35/profile.reference.json'
    profile = deepcopy(read(source)['d_profile'])
    profile.update(transfer_velocity=230.4, pickup_descent_velocity=24.,
                   pickup_descent_acceleration=6., assembly_approach_velocity=24.,
                   assembly_approach_acceleration=6., descent_velocity=24.,
                   descent_acceleration=6., pre_contact_slow_distance_mm=10.)
    profile['transport_blending']['radius_mm'] = 40.
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
    # 최신 5mm 교시값에는 과거 8→5mm 보정을 다시 적용하지 않는다.
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
    # 새 (11,11)→(12,11) 실측은 공통 +X가 Base +X임을 확인했다.
    # 실행용 사본만 수정한다. 과거 축 교환 프로필/교시 원자료는 보존한다.
    assembly['grid_mapping'].update(planner_to_trial_xy=[[1,0],[0,1]],
        status='USER_TAUGHT_COMMON_X_BASE_X_20261012',
        confirmation_source='assembly_6point_axis.json:11_11_TO_12_11')
    assembly['reference']['grip_axis_planner'] = 'x'
    base = layers[1]
    assembly['coefficient_xyz_mm'] = dict(
        origin=[base['sample']['posx'][j]-base['target']['x']*affine['x_step_xyz_mm'][j]
                -base['target']['y']*affine['y_step_xyz_mm'][j] for j in range(3)],
        x_coefficient=affine['x_step_xyz_mm'], y_coefficient=affine['y_step_xyz_mm'],
        xy_coefficient=[0., 0., 0.])
    assembly['recorded_transfer_height_candidate_mm'] = profile['clearance_z_mm']
    context = whole_request()['assembly_context']
    context['supported_modes'] = ['ROBOT_GRIP']
    teaching_path = (Path(supply_teaching_path) if supply_teaching_path is not None else
                     Path(__file__).resolve().parents[1]/'logs/teaching-20261012/supply.json')
    if supply_teaching_path is None and not teaching_path.is_file():
        teaching_path=root/'fixtures/teaching_sources/operator_supply.json'
    taught_supply = supply_teaching(teaching_path) if teaching_path.is_file() else None
    if supply_teaching_path is not None and taught_supply is None:
        raise ValueError('SUPPLY_TEACHING_FILE_MISSING:'+str(teaching_path))
    assembly_path=Path(__file__).resolve().parents[1]/'logs/teaching-20261012/assembly_6point_layer1.json'
    if not assembly_path.is_file():
        assembly_path=root/'fixtures/teaching_sources/operator_assembly_6point_layer1.json'
    taught_assembly=assembly_teaching(assembly_path) if assembly_path.is_file() else None
    board_path=(Path(assembly_board_teaching_path) if assembly_board_teaching_path is not None else
                Path(__file__).resolve().parents[1]/'logs/teaching-20261012/assembly_board_by_studs.json')
    if assembly_board_teaching_path is None and not board_path.is_file():
        board_path=root/'fixtures/teaching_sources/operator_assembly_board_by_studs.json'
    board_calibration=load_board_calibration(board_path) if board_path.is_file() else None
    if assembly_board_teaching_path is not None and board_calibration is None:
        raise ValueError('ASSEMBLY_BOARD_TEACHING_FILE_MISSING:'+str(board_path))
    if board_calibration is not None:
        frame['calibration_version']='USER_BOARD_CORNERS_'+board_calibration['source_sha256'][:16]
    return dict(frame=frame, profile=profile, context=context, layers=layers,
                board_calibration=board_calibration,
                taught_supply=taught_supply,
                taught_assembly=taught_assembly,
                assembly_teaching_ref=str(assembly_path.resolve()) if taught_assembly else None,
                assembly_teaching_sha256=sha256(assembly_path.read_bytes()).hexdigest() if taught_assembly else None,
                supply_teaching_ref=str(teaching_path.resolve()) if taught_supply else None,
                supply_teaching_sha256=sha256(teaching_path.read_bytes()).hexdigest() if taught_supply else None,
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
    return [-2.*v/norm for v in tangent]


def step_geometry(inputs, step, action, slot_index):
    frame, profile = deepcopy(inputs['frame']), deepcopy(inputs['profile'])
    assembly = frame['calculation_profiles']['assembly']
    width, depth = BRICK_SIZES[step['after']['brick_type']]
    if step['after']['orientation_deg'] == 90:
        width, depth = depth, width
    # 사람 직접 조립에는 A의 grip_axis가 없다. 비정방형은 2점 폭 기준으로
    # 계산하고, 실제 전달판 실행은 공급 파지 자세를 그대로 사용한다.
    grip_axis = action['grip_axis'] or (assembly['reference']['grip_axis_planner']
        if step['after']['brick_type'] == '2x2x1' else ('x' if width == 2 else 'y'))
    layer = inputs['layers'][step['after']['layer']]
    c = assembly['coefficient_xyz_mm']
    turn = 0 if grip_axis == assembly['reference']['grip_axis_planner'] else 90
    taught_target=None
    teaching_ref=inputs.get('assembly_teaching_ref')
    teaching_hash=inputs.get('assembly_teaching_sha256')
    board_calibration=inputs.get('board_calibration')
    if board_calibration is not None and step['after']['brick_type'] in ('2x3x1','1x2x1'):
        reference=board_target_pose(board_calibration,step['after'],inputs['layers'])
        taught_target=reference[:]
        teaching_ref=board_calibration['source_ref'];teaching_hash=board_calibration['source_sha256']
        correction=[0.,0.]
    else:
        nominal = calculate_step_tcp(step, profile=assembly, grip_axis=grip_axis)
        if nominal['status'] != 'COORDINATE_CANDIDATE':
            raise ValueError(str(nominal.get('errors')))
        trial_xy = nominal['trial_grid_reference_2x2_anchor']
        reference = list(layer['sample']['posx'])
        for j in range(2):
            reference[j] += (trial_xy[0]-layer['target']['x'])*c['x_coefficient'][j]
            reference[j] += (trial_xy[1]-layer['target']['y'])*c['y_coefficient'][j]
        correction = rotation_correction(assembly, trial_xy, turn=turn)
        reference[:2] = [reference[j]+correction[j] for j in range(2)]
    if (board_calibration is None and step['after']['brick_type']=='2x3x1'
            and inputs.get('taught_assembly') is not None):
        taught_target=inputs['taught_assembly'][(step['after']['color'],step['after']['orientation_deg'])]
        reference=list(taught_target)
        # 6점 실측 TCP에는 중심/파지 보정이 포함된다. 추가 축 확인점의 Z는 쓰지 않는다.
        for j in range(2):
            reference[j]+=(step['after']['x']-11)*c['x_coefficient'][j]
            reference[j]+=(step['after']['y']-11)*c['y_coefficient'][j]
        reference[2]+=layer['sample']['posx'][2]-inputs['layers'][1]['sample']['posx'][2]
        correction=[0.,0.]
    # 2026-10-13 사용자 실물 보정: 교시 원본 대신 A/D가 공유할 목표 사본에 한 번 적용한다.
    if (step['after']['brick_type']=='2x3x1' and step['after']['color'] in ('yellow','blue')
            and step['after']['orientation_deg']==90):
        reference[0]+=1.5
        correction[0]+=1.5
    # 2026-10-13 사용자 실물 보정: 정방형의 파지 축 회전 때만 Base X를 보정한다.
    if step['after']['brick_type']=='2x2x1' and abs(turn)==90:
        reference[0]-=1.5
        correction[0]-=1.5
    # 2026-10-13 사용자 실물 보정: 조립 grid x>11 구간의 목표 사본에 Base X -1mm 추가.
    if step['after']['x']>11:
        reference[0]-=1.
        correction[0]-=1.
    from planning_trial.supply_pick import calculate_supply_pick
    if inputs.get('taught_supply') is not None:
        slot_key = f"{step['after']['color']}_{step['after']['brick_type']}_{slot_index:02d}"
        pick = list(inputs['taught_supply'][slot_key])
        supply = frame['calculation_profiles']['supply']
        if slot_index in (1,3,6) and step['after']['color'] != 'red':
            supply['d_taught_slot'] = dict(identity=dict(brick_type=step['after']['brick_type'],
                color=step['after']['color'],slot_index=slot_index), tcp_mm_zyz_deg=list(pick),
                source_sha256=inputs['supply_teaching_sha256'])
        else:
            # 이 요청의 보간 후보만 A와 D가 공유한다. 다른 슬롯의 전역 보정으로 쓰지 않는다.
            nominal_pick = calculate_supply_pick(step['after']['brick_type'],step['after']['color'],slot_index,
                                                 profile=supply)['pickup_tcp_pose']['xyz_abc']
            anchor = supply['first_pick_tcp_mm_zyz_deg']
            supply['first_pick_tcp_mm_zyz_deg'] = [anchor[j]+pick[j]-nominal_pick[j] for j in range(3)]+pick[3:]
            calculated_pick = calculate_supply_pick(step['after']['brick_type'],step['after']['color'],slot_index,
                                                     profile=supply)['pickup_tcp_pose']['xyz_abc']
            if any(abs(a-b)>1e-9 for a,b in zip(pick,calculated_pick)):
                raise ValueError('D_TEACHING_AND_A_PICKUP_MAPPING_DIFFER')
            # A의 완전 동일 비교에 맞춰 같은 산술 결과를 사용한다. 원자료는 변경하지 않는다.
            pick = calculated_pick
    else:
        pick = calculate_supply_pick(step['after']['brick_type'], step['after']['color'], slot_index,
            profile=frame['calculation_profiles']['supply'])['pickup_tcp_pose']['xyz_abc']
    transit = [dict(label=label, xy_mm=xy) for label, xy in (
        ('SUPPLY_20_0', profile['supply_transit_xy_mm']), ('BODY_BYPASS', profile['body_bypass_xy_mm']),
        ('PLACE_BOARD', profile['place_pose'][:2]))]
    assembly['d_onsite_step'] = dict(block=deepcopy(step['after']), grip_axis=grip_axis,
        turn_base_z_deg=turn, reference_pose=reference, pickup_pose=pick,
        approach_offset_mm=20.1, clearance_z_mm=profile['clearance_z_mm'],
        source_sha256=inputs['source_sha256'], loaded_transit=transit)
    if taught_target is not None:
        assembly['d_onsite_step'].update(assembly_tcp_zyz_deg=list(taught_target[3:]),
            source_sha256=teaching_hash)
        profile.update(assembly_teaching_ref=teaching_ref,assembly_teaching_sha256=teaching_hash)
        if board_calibration is not None:
            profile['assembly_pose_basis']='FOUR_CORNER_AFFINE_'+step['after']['brick_type']+'/'+str(step['after']['orientation_deg'])
    slot = dict(brick_type=step['after']['brick_type'], color=step['after']['color'], slot_index=slot_index,
        state='RESERVED', part_confirmation='CONFIRMED',
        slot_id=f"{step['after']['color']}_{step['after']['brick_type']}_{slot_index:02d}",
        reservation_id=str(uuid4()), reservation_generation=slot_index, bound_workflow_generation=1)
    profile['physical_route_reviewed'] = False
    if inputs.get('taught_supply') is not None:
        profile['supply_teaching_ref'] = inputs['supply_teaching_ref']
        profile['supply_teaching_sha256'] = inputs['supply_teaching_sha256']
        profile['supply_pose_basis'] = 'MEASURED' if slot_index in (1,3,6) else 'INTERPOLATED'
    profile['approach_offset_mm'] = 20.1
    profile['steps'] = {'cad/'+step['step_id']: dict(reference_pose=reference, pickup_pose=pick,
        pickup_open_width_mm=55., pickup_width_mm=35., release_width_mm=48., turn_base_z_deg=turn,
        # RG2 reports 0.1mm increments: 44.1 is the first value strictly above 44mm.
        pickup_start_open_range_mm=[44.1,110.], release_feedback_range_mm=[44.1,110.],
        physical_reference_reviewed=False, xy_grasp_rotation_compensation_measured=False)}
    if taught_target is not None:
        profile['steps']['cad/'+step['step_id']]['assembly_tcp_zyz_deg']=list(taught_target[3:])
    return frame, profile, slot, correction


def step_document(inputs, plan, step, action, assumed, slot_index, robot_state):
    frame, profile, slot, correction = step_geometry(inputs, step, action, slot_index)
    motion = plan_step_motion(plan=plan, step_id=step['step_id'], latest_current=assumed,
        action=action, supply_slot=slot, robot_state=robot_state, frame_profile=frame,
        assembly_context=inputs['context'])
    if motion['status'] != 'CANDIDATE':
        raise ValueError('A_MOTION_BLOCKED: '+str(motion['errors']))
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
