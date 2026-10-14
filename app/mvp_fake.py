"""전체 모의 시험용 입력. 이 파일의 값은 REAL 프로필로 사용할 수 없다."""
from copy import deepcopy
import time
from uuid import uuid4

from planning_trial.assembly_api_fixtures import frame_profile, whole_request
from planning_trial.assembly_target import calculate_step_tcp
from planning_trial.assembly_wire import pose_mm_zyz
from planning_trial.supply_pick import calculate_supply_pick


def settings():
    frame = frame_profile()
    frame.update(profile_id='FAKE_MVP_FRAME', profile_version='FAKE_1', sample_kind='REVIEW_ONLY')
    frame['calculation_profiles']['supply']['red_extension'] = dict(user_confirmed_small_faces=True,
        gap_from_blue_y=2, gap_between_red_columns_y=2, columns=2, slots_per_column=6)
    frame['calculation_profiles']['supply']['first_pick_tcp_mm_zyz_deg'] = [-300., 50., 50., 0., 180., 0.]
    frame['calculation_profiles']['supply']['anchor_grip_height_above_bottom_mm'] = 5
    target = frame['calculation_profiles']['assembly']
    target.update(coefficient_xyz_mm=dict(origin=[300., 0., 50.], x_coefficient=[16., 0., 0.],
        y_coefficient=[0., 16., 0.], xy_coefficient=[0.,0.,0.]), recorded_transfer_height_candidate_mm=400.)
    target['reference']['tcp_zyz_deg'] = [0.,180.,0.]
    context = whole_request()['assembly_context']
    context['supported_modes'] = ['ROBOT_GRIP', 'HUMAN_ASSEMBLY']
    return dict(assembly_context=context, frame_profile=frame, geometry_reference='FAKE_19_4.5_16')


def prepare(workflow, payload, *, slot_index=1, robot_sample=None):
    step, block = payload['step'], payload['step']['after']
    action = workflow.whole_result['action_proposals'][len(workflow.completed)]
    frame = deepcopy(workflow.settings['frame_profile'])
    cp = frame['calculation_profiles']
    pick = calculate_supply_pick(block['brick_type'], block['color'], slot_index, profile=cp['supply'])['pickup_tcp_pose']['xyz_abc']
    target = calculate_step_tcp(step, profile=cp['assembly'], grip_axis=action['grip_axis'])['nominal_seated_tcp']['xyz_mm_zyz_deg']
    turn = target[3]-pick[3]
    d = dict(profile_id='MOCK_MVP_STEP', physical_route_reviewed=False,
        human_collaboration_commissioning_ref=None, clearance_z_mm=400.,
        supply_transit_xy_mm=[-350.,-170.], body_bypass_xy_mm=[0.,-410.],
        place_pose=[400.,-180.,50.,0.,180.,0.], approach_offset_mm=24.5,
        near_contact_offset_mm=1., force_stop_n=35., max_press_travel_mm=5.,
        transfer_velocity=32., transfer_acceleration=16., descent_velocity=2.,
        descent_acceleration=1., gripper_force_n=40., steps={})
    d['steps']['mvp/'+step['step_id']] = dict(reference_pose=target, pickup_pose=pick,
        pickup_width_mm=40., release_width_mm=62., turn_base_z_deg=turn,
        physical_reference_reviewed=False, xy_grasp_rotation_compensation_measured=False,
        pickup_start_open_range_mm=[61.,110.], release_feedback_range_mm=[61.,110.])
    if action.get('assembly_strategy') == 'RELEASE_PRESS':
        # Explicit synthetic geometry for the announced strategy, never a REAL datum.
        release = target.copy(); release[2] += 4.5
        pad = target.copy(); pad[2] += 20.
        d['steps']['mvp/'+step['step_id']].update(release_pose=release,
            press_approach_pose=[*pad[:2], pad[2]+10., *pad[3:]],
            press_start_pose=[*pad[:2], pad[2]+1., *pad[3:]], press_width_mm=4.)
        d.update(force_stop_n=45., max_press_travel_mm=12.,
                 round2_motion=dict(transfer_velocity=120., vertical_velocity=12.))
    transit = [dict(label=label, xy_mm=xy) for label,xy in
        [('SUPPLY_20_0',d['supply_transit_xy_mm']), ('BODY_BYPASS',d['body_bypass_xy_mm']), ('PLACE_BOARD',d['place_pose'][:2])]]
    if action['mode'] == 'HUMAN_ASSEMBLY':
        cp['tray'] = dict(profile_id='FAKE_TRAY', tcp_pose_mm_zyz_deg=d['place_pose'],
                           travel_tcp_z_mm=400., d_loaded_transit=transit)
    else:
        cp['assembly']['d_onsite_step'] = dict(block=deepcopy(block), grip_axis=action['grip_axis'],
            turn_base_z_deg=turn, reference_pose=target, pickup_pose=pick, approach_offset_mm=24.5,
            clearance_z_mm=400., source_sha256='0'*64, loaded_transit=transit)
    slot = dict(slot_id=block['color']+'_'+block['brick_type']+f'_{slot_index:02d}', slot_index=slot_index,
        brick_type=block['brick_type'],color=block['color'],reservation_id=str(uuid4()), reservation_generation=slot_index+17,
        bound_workflow_generation=workflow.generation,state='RESERVED',part_confirmation='CONFIRMED',valid_until_ref='FAKE_ONLY')
    robot = dict(source_epoch=workflow.epoch,state_sequence=1,tcp_frame_id=frame['tcp_frame_id'],
        tcp_setting_name=frame['tcp_setting_name'],tcp_pose=pose_mm_zyz([400.,-180.,400.,0.,180.,0.]),
        stopped_verified=True,holding_confirmed=False,active_command_count=0,pending_command_count=0,
        stop_observation_ref='FAKE_ONLY',freshness_policy_ref='FAKE_ONLY')
    if robot_sample is not None:
        robot['tcp_pose']=pose_mm_zyz(robot_sample['posx'])
        robot['state_sequence']=robot_sample['state_sequence']
    return dict(deepcopy(payload), frame_profile=frame, slot=slot, robot_state=robot, d_profile=d)


def execution_document(bundle, execution_id):
    request, action = bundle['request'], bundle['assessment']['action_proposal']
    step = dict(case_id='mvp',plan_id=request['plan']['plan_id'],step_id=request['selected_step']['step_id'],
        block=request['selected_step']['after'],action=action,current_revision=request['latest_current']['current_revision'],
        reservation={k:request['reserved_supply_slot'][k] for k in
            ('slot_id','reservation_id','reservation_generation','bound_workflow_generation')},source_execution_allowed=False)
    session = dict(backend='TEST',provenance='SYNTHETIC',execution_id=execution_id,source_epoch='TEST_MVP',
        frame_profile_id='FAKE_MVP_FRAME',plan_id=step['plan_id'],step_id=step['step_id'],current_revision=step['current_revision'],
        expires_unix_s=time.time()+600,request_timeout_s=30,frame_max_age_s=.3,frame_max_gap_s=.3,inference_max_latency_s=.3,
        stillness=dict(window_s=.1,max_gap_s=.25,timeout_s=3,min_samples=3,sample_max_duration_s=.5,
            position_mm=.05,orientation_deg=.05,linear_mm_s=.01,angular_deg_s=.01))
    return dict(assessment=bundle['assessment'],request=request,motion=bundle['motion'],case_id='mvp',
                motion_source=bundle.get('motion_source', 'A_STEP_MOTION'),
                step=step,d_profile=bundle['d_profile'],session=session,fixture_kind='FAKE_NO_DEVICE')
