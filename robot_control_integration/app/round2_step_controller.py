"""Opt-in Round2 step routing; source A/B plans and Round1 remain immutable."""
from copy import deepcopy
import math
from app.human_step_raised_press import adapt_human_step
from app.assembly_step_bridge import pose
from app.assembly_step_runner import run_step

SUPPORT={'HOLD','PRESS_AND_HOLD','MANUAL_ASSEMBLY_AND_HOLD'}


def binding(plan):
    return {k:deepcopy(plan.get(k)) for k in ('key','plan_id','step_id','current_revision','block','reservation')}


def prepare_round2_step(plan,profile,measured=None):
    source=deepcopy(plan);candidate=deepcopy(plan);p=deepcopy(profile)
    kind=plan['mode'];assistance=plan['assistance_kind'];reason=None
    if assistance in SUPPORT:
        branch='HUMAN_SUPPORT_PLACE_BOARD'
        candidate.update(mode='HUMAN_ASSEMBLY',assistance_kind='MANUAL_ASSEMBLY_AND_HOLD',
            source_mode=kind,source_assistance_kind=assistance,human_actions=['HOLD','MANUAL_ASSEMBLY'])
        # Place-board delivery, not the old direct target handover policy.
        candidate['settings'].pop('human_step_gestures',None)
        p['steps'][plan['key']]=deepcopy(candidate['settings'])
        reason='BOTTOM_SUPPORT_REQUIRES_PLACE_BOARD_DELIVERY'
    elif kind=='HUMAN_ASSEMBLY':
        branch='HUMAN_FASTENING_ROBOT_COMPLEMENT'
        if measured is None:
            branch='HUMAN_FASTENING_FALLBACK';reason='RAISED15_MEASUREMENTS_MISSING'
        else:
            if measured.get('key')!=plan['key'] or measured.get('block')!=plan['block']:
                raise ValueError('ROUND2_MEASUREMENT_STEP_BINDING_MISMATCH')
            try:
                candidate,p=adapt_human_step(plan,profile,measured)
            except ValueError as error:
                branch='HUMAN_FASTENING_FALLBACK';reason=str(error)
    elif kind=='ROBOT_GRIP' and assistance=='NONE':
        branch='ROBOT_FASTENING'
        if measured is None:reason='CLOSED_PAD_MEASUREMENTS_MISSING'
        else:
            if measured.get('key')!=plan['key'] or measured.get('block')!=plan['block']:
                raise ValueError('ROUND2_MEASUREMENT_STEP_BINDING_MISMATCH')
            checks=('landing_support_verified','release_sweep_verified','press_sweep_verified')
            if any(measured.get(k) is not True for k in checks) or not measured.get('measurement_ref'):
                reason='CLOSED_PAD_SWEEP_OR_CONTACT_PENDING'
            else:
                try:pad=pose(measured.get('pad_contact_pose'),'closed_pad_contact')
                except ValueError:reason='CLOSED_PAD_CONTACT_POSE_PENDING'
                else:
                    candidate.update(mode='ROBOT_RELEASE_PRESS',source_mode=kind,round2_vertical_top_press=True)
                    s=candidate['settings'];landing=pose(s['reference_pose'],'landing')
                    width=measured.get('press_width_mm')
                    if type(width) not in (int,float) or not math.isfinite(width) or not 0<=width<=12:
                        raise ValueError('ROUND2_CLOSED_PAD_WIDTH_REQUIRED')
                    s.update(release_pose=landing.copy(),press_width_mm=width,
                        press_start_pose=[*landing[:2],pad[2]+p['near_contact_offset_mm'],*landing[3:]],
                        press_approach_pose=[*landing[:2],pad[2]+p['approach_offset_mm'],*landing[3:]],
                        round2_measurement_ref=measured['measurement_ref'])
                    p.pop('native_press',None);p['force_stop_n']=45.
                    p['steps'][plan['key']]=deepcopy(s)
    else:
        raise ValueError('ROUND2_UNCLASSIFIED_SOURCE_METHOD')
    rates=p.get('round2_motion',dict(transfer_velocity=120.,vertical_velocity=12.))
    for key in ('transfer_velocity','vertical_velocity'):
        if type(rates.get(key)) not in (int,float) or not math.isfinite(rates[key]) or rates[key]<=0:
            raise ValueError('ROUND2_POSITIVE_MOTION_RATES_REQUIRED')
    p.update(round2=True,round2_motion=deepcopy(rates),transfer_velocity=rates['transfer_velocity'],
        descent_velocity=rates['vertical_velocity'],pickup_descent_velocity=rates['vertical_velocity'],assembly_approach_velocity=rates['vertical_velocity'])
    p['force_stop_n']=45.
    p.pop('transport_blending',None)
    robot=candidate['mode']=='ROBOT_RELEASE_PRESS'
    if robot:
        candidate['round2_vertical_top_press']=True
        p.update(press_control='POSITION_DESCENT_REACTION_STOP',force_control_target_n=None)
        # Keep SUPPLY/BODY, replace PLACE only on the outbound robot route.
        p.pop('transport_blending',None)
    return dict(version='round2-step/1',source_plan=source,source_profile=deepcopy(profile),
        execution_candidate=candidate,profile=p,branch=branch,reason=reason,
        robot_complement_selected=robot,physical_execution_ready=False,
        required_inputs=(['OPENCV_PICKUP_PROVIDER','LIVE_ALIGNMENT_PROVIDER','LIVE_EXECUTION_REVIEW'] if robot else ['OPENCV_PICKUP_PROVIDER','LIVE_EXECUTION_REVIEW']),
        source_plan_preserved=True,assembly_completion=False,current_update=False)


def run_round2_step(driver,connection,prepared,confirm,record,*,pickup_center,assembly_alignment=None,
                    phase='full',start_zone='assembly',clock=None,sleep=None):
    if prepared.get('version')!='round2-step/1':raise ValueError('ROUND2_PREPARED_STEP_REQUIRED')
    if pickup_center is None:raise ValueError('ROUND2_OPENCV_PROVIDER_REQUIRED')
    if prepared['branch']=='ROBOT_FASTENING' and not prepared['robot_complement_selected'] and phase not in ('pickup','approach'):
        return dict(status='WAITING_ROUND2_PAD_MEASUREMENTS',reason=prepared['reason'],assembly_completion=False,current_update=False)
    plan=deepcopy(prepared['execution_candidate']);profile=deepcopy(prepared['profile'])
    if prepared['robot_complement_selected'] and assembly_alignment is None and phase in ('full','contact','assemble-held'):
        return dict(status='WAITING_ALIGNMENT_PROVIDER',assembly_completion=False,current_update=False)
    if getattr(driver,'mode',None)=='REAL':
        # Same single-writer/session/physical review as the existing live runner.
        if not hasattr(driver,'session'):raise ValueError('ROUND2_CONTROLLED_LIVE_SESSION_REQUIRED')
        from app.control_session import validate_execution
        validate_execution(plan,profile,driver.session.value,phase)
    record('ROUND2_STEP_BRANCH',dict(branch=prepared['branch'],binding=binding(plan),reason=prepared['reason'],
        source_mode=prepared['source_plan']['mode'],execution_mode=plan['mode'],assembly_completion=False))
    options=dict(phase=phase,start_zone=start_zone,pickup_center=pickup_center,
        assembly_alignment=assembly_alignment if prepared['robot_complement_selected'] else None)
    if clock is not None:options['clock']=clock
    if sleep is not None:options['sleep']=sleep
    result=run_step(driver,connection,plan,profile,confirm,record,**options)
    result.update(round2_branch=prepared['branch'],source_mode=prepared['source_plan']['mode'],assembly_completion=False,current_update=False)
    return result
