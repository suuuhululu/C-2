"""명시적인 가상 기하/프로필. 실기·IK·충돌·체결력 검증값으로 사용하지 않는다."""
from copy import deepcopy
from uuid import uuid4
from app.assembly_step_bridge import build_plan
from scripts.robot_control_trial import test_session


def document(brick_type='2x2x1', color='blue', layer=1, angle=0, mode='ROBOT_GRIP', assistance='NONE'):
    block = dict(brick_type=brick_type, color=color, x=6, y=8, layer=layer, orientation_deg=angle)
    # MOCK tool: TCP is 45mm above pad bottom. Block-bottom+5mm gives pickup TCP=50mm.
    # Seated bottom=(layer-1)*19mm; the lower stud tip is 4.5mm higher.
    seated_z = (layer-1)*19.+50.
    action = dict(plan_id='FAKE_PLAN', step_id='S01', block=block, mode=mode, assistance_kind=assistance)
    step = dict(case_id='fake', plan_id=action['plan_id'], step_id='S01', block=block,
                action=action, current_revision=layer-1,
                reservation=dict(slot_id=color+'_'+brick_type+'_01', reservation_id='FAKE_SLOT',
                                 reservation_generation=1, bound_workflow_generation=7), source_execution_allowed=False)
    nx, ny = {'1x2x1':(1,2), '2x2x1':(2,2), '2x3x1':(2,3)}[brick_type]
    if angle == 90: nx, ny = ny, nx
    reference = [300.+(block['y']+(ny-1)/2)*16., (block['x']+(nx-1)/2)*16., seated_z, 0.,180.,0.]
    settings = dict(reference_pose=reference, pickup_pose=[-300., 50., 50., 0.,180.,0.],
                    pickup_width_mm=40., release_width_mm=62., turn_base_z_deg=angle,
                    physical_reference_reviewed=False, xy_grasp_rotation_compensation_measured=False,
                    pickup_start_open_range_mm=[61.,110.], release_feedback_range_mm=[61.,110.])
    profile = dict(profile_id='MOCK_INTEGRATION_ONLY', physical_route_reviewed=False,
                   human_collaboration_commissioning_ref=None, clearance_z_mm=200.,
                   supply_transit_xy_mm=[-350.,-170.], body_bypass_xy_mm=[0.,-410.],
                   place_pose=[400.,-180.,50.,0.,180.,0.], approach_offset_mm=24.5,
                   near_contact_offset_mm=1., force_stop_n=35., max_press_travel_mm=5.,
                   transfer_velocity=32., transfer_acceleration=16., descent_velocity=2.,
                   descent_acceleration=1., gripper_force_n=40., steps={'fake/S01':settings})
    session = test_session(build_plan(step,profile))
    session['execution_id'] = str(uuid4())
    return dict(step=step, d_profile=profile, session=session, start_zone='assembly',
                fixture_kind='FAKE_NO_DEVICE_NO_PHYSICAL_VALIDATION')


def real_template():
    value = document()
    value.pop('fixture_kind')
    value['d_profile']['profile_id'] = 'FILL_D_PROFILE_ID'
    for key in ('clearance_z_mm','supply_transit_xy_mm','body_bypass_xy_mm','place_pose','approach_offset_mm',
                'near_contact_offset_mm','force_stop_n','max_press_travel_mm','transfer_velocity',
                'transfer_acceleration','descent_velocity','descent_acceleration','gripper_force_n'):
        value['d_profile'][key] = None
    settings = value['d_profile']['steps']['fake/S01']
    for key in ('reference_pose','pickup_pose','pickup_width_mm','release_width_mm',
                'pickup_start_open_range_mm','release_feedback_range_mm','turn_base_z_deg'):
        settings[key] = None
    value['session'].update(backend='REAL', provenance='LIVE_D_RUNTIME', execution_id='',
        source_epoch='', frame_profile_id='', profile_id='', expires_unix_s=0,
        exclusive_control_reviewed=False, device_feedback_reviewed=False,
        stillness_parameters_reviewed=False, hand_clear_reviewed=False,
        alignment_evidence_ref=None, d_runtime={})
    value['session']['stillness'] = {k:None for k in value['session']['stillness']}
    value['step']['case_id']='FILL_CASE_ID'
    value['d_profile']['steps']={'FILL_CASE_ID/S01':settings}
    return deepcopy(value)


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=('fake','real-template'))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    value=document() if args.kind=='fake' else real_template()
    text=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    else: print(text,end='')
