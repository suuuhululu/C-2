"""Registered supply pickup and the existing fixed place-board delivery route."""
from copy import deepcopy
from pathlib import Path

from app import round3_stack_five as stack
from app.round3_initial_inspection import open_motion


def prepare(item, profile, assessment, request, motion):
    stack.native()
    from app.assembly_step_bridge import step_from_messages,build_plan
    from planning_trial.assembly_wire import pose_mm_zyz
    if assessment['action_proposal']['mode']!='HUMAN_ASSEMBLY':
        raise ValueError('A_MANUAL_ASSEMBLY_REQUIRED_FOR_HANDOVER')
    proposal=motion['motion_proposal']
    if proposal['motion_scope']!='PICK_TRANSPORT_TO_HANDOVER_TRAY':
        raise ValueError('A_PLACE_BOARD_MOTION_REQUIRED')
    transport=next(s['waypoints'] for s in proposal['segments'] if s['stage']=='TRANSPORT_HOLDING')
    cfg=item['config'];p=deepcopy(profile)
    if transport[-1]['tcp_pose']!=pose_mm_zyz(p['place_pose']):
        raise ValueError('A_D_PLACE_BOARD_POSE_MISMATCH')
    for label,xy in [('SUPPLY_20_0',p['supply_transit_xy_mm']),
            ('BODY_BYPASS',p['body_bypass_xy_mm']),('PLACE_BOARD',p['place_pose'][:2])]:
        waypoint=next(w for w in transport if w['label']==label)
        if any(abs(a*1000-b)>1e-8 for a,b in zip(waypoint['tcp_pose']['xyz_m'][:2],xy)):
            raise ValueError('A_D_HANDOVER_ROUTE_MISMATCH: '+label)
    p.update(profile_id='D_ROUND3_PLACE_BOARD_HANDOVER',
        clearance_z_mm=max(w['tcp_pose']['xyz_m'][2]*1000 for w in transport),
        descent_velocity=3.,descent_acceleration=1.,gripper_force_n=cfg['gripper_force_n'],
        target_only_motion=cfg.get('target_only_motion',False))
    from app.cad_real_trial import REAL_STILLNESS_TOLERANCES
    p['handover_stillness']=deepcopy(REAL_STILLNESS_TOLERANCES)
    p.pop('native_press',None);p.pop('transport_blending',None)
    step=step_from_messages(assessment,request,motion,case_id='round3-handover')
    p['steps']={step['case_id']+'/'+step['step_id']:dict(reference_pose=deepcopy(p['place_pose']),
        pickup_pose=deepcopy(cfg['blocks'][0]['pickup_pose']),pickup_width_mm=cfg['blocks'][0]['close_mm'],
        release_width_mm=53.,release_feedback_range_mm=[40.,80.],physical_reference_reviewed=False)}
    return dict(profile=p,step=step,plan=build_plan(step,p))


def execute(item,directory,record,settings,review,cancelled):
    trial=stack.native()
    from app.assembly_step_bridge import build_plan,validate_physical
    from app.assembly_step_runner import run_step
    cfg=item['config'];handover=deepcopy(item['handover']);profile=handover['profile']
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    stack.save(directory/'binding.json',handover)
    profile.update(physical_route_reviewed=True,operator_review_ref=review)
    for s in profile['steps'].values():s.update(physical_reference_reviewed=True,operator_review_ref=review)
    plan=build_plan(handover['step'],profile)
    validate_physical(plan,profile,'handover-held')
    with open_motion(settings,cancelled) as motion:
        raw=motion.raw
        raw.config['timing'].update(service_timeout_s=3.,stopped_sample_retry_window_s=5.)
        raw.feedback_record=record
        try:
            motion.confirm('HANDOVER_START','HOME',dict(settings,route_reviewed=True),review,allow_move=False)
            (directory/'supply').mkdir()
            vision=trial.supply.LiveVision(raw,cfg,directory/'supply')
            try:
                trial.supply.execute(raw,cfg,record,vision.observe,trial_row=cfg['blocks'][0],start_zone='home',
                    display=vision.display,hold_at_pickup=True,sleep=vision.pump_sleep,
                    **(dict(finalize_observation=vision.finalize_depth)
                        if cfg['vision'].get('defer_depth_pose_validation') else {}))
            finally:vision.close()
            # A prior HMI checkbox authorizes releasing onto the clear tray.
            # Human completion is deliberately left unanswered until HOME.
            outcome=run_step(raw,cfg['connection'],plan,profile,
                lambda kind,*_:kind in ('START_HANDOVER-HELD','TRAY_RELEASE') and not cancelled.is_set(),record,
                phase='handover-held',start_zone='supply')
            if outcome['status']!='PAUSED_HUMAN_ASSEMBLY_ACK':
                raise ValueError('PLACE_BOARD_DELIVERY_INCOMPLETE: '+outcome['status'])
            sample=raw.sample();limit=trial.supply.motion_force_limit(cfg)
            trial.guard(sample,cfg['connection'],limit,automatic=True,force_norm_limit=limit,required_gripper_status=0)
            bounds=plan['settings']['release_feedback_range_mm']
            if not trial.held.motion_completed(sample,cfg) or not trial.supply.width_in_range(sample,bounds):
                record('HANDOVER_RELEASE_REJECTED',dict(sample=sample,feedback_range_mm=bounds))
                raise ValueError('HANDOVER_RELEASE_NOT_VERIFIED')
            record('HANDOVER_RELEASE_VERIFIED',dict(sample=sample,place_pose=profile['place_pose'],feedback_range_mm=bounds))
            home=motion.confirm('HANDOVER_HOME','HOME',dict(settings,route_reviewed=True),review)
            if home.get('stopped_verified') is not True:raise ValueError('HANDOVER_HOME_NOT_VERIFIED')
        except BaseException as error:
            try:raw.stop()
            except Exception as stop_error:record('STOP_FAILED',dict(original_reason=str(error),
                stop_reason=str(stop_error),actual_stop_verified=False))
            raise
    result=dict(status='PLACE_BOARD_DELIVERED_HOME_RETURNED',completed_steps=[item['case']['step_id']],
        home_returns=[home],released=True,home_return_verified=True,actual_stop_verified=True,writer_released=True,
        human_assembly_confirmed=False,assembly_completion=False,current_update=False,automatic_retry=False)
    stack.save(directory/'result.json',result)
    return result
