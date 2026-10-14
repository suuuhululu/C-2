"""Local execution candidate for human-fastening steps blocked by gripper access.

Original A/B action and completion ownership remain in the source plan.
"""
from copy import deepcopy
import math
from app.raised_grasp_press import pose

KINDS={('yellow','2x2x1'),('yellow','2x3x1'),('blue','2x2x1'),('blue','2x3x1'),('red','1x2x1')}


def adapt_human_step(plan,profile,measured):
    if plan['mode']!='HUMAN_ASSEMBLY':raise ValueError('HUMAN_FASTENING_STEP_REQUIRED')
    block=plan['block']
    if (block['color'],block['brick_type']) not in KINDS or block['orientation_deg'] not in (0,90):
        raise ValueError('SUPPORTED_BLOCK_AND_ORIENTATION_REQUIRED')
    if measured.get('reason') not in ('GRIPPER_COLLISION','GRIPPER_ACCESS'):
        raise ValueError('GRIPPER_ACCESS_REASON_REQUIRED')
    if measured.get('key')!=plan['key'] or measured.get('block')!=block:
        raise ValueError('EXACT_STEP_BLOCK_MEASUREMENT_REQUIRED')
    height=measured.get('pad_bottom_from_block_bottom_mm')
    body=measured.get('body_height_mm')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (height,body)) or not math.isclose(height,15.,abs_tol=1e-6) or not height<body:
        raise ValueError('RAISED_PAD_BOTTOM_15MM_WITH_BODY_CONTACT_REQUIRED')
    for check in ('grasp_stability_verified','insertion_sweep_verified','release_sweep_verified','press_sweep_verified','landing_support_verified'):
        if measured.get(check) is not True:raise ValueError('MEASURED_CLEARANCE_REQUIRED:'+check)
    if not measured.get('measurement_ref'):raise ValueError('MEASUREMENT_REFERENCE_REQUIRED')
    need_support=plan['assistance_kind'] in ('HOLD','PRESS_AND_HOLD','MANUAL_ASSEMBLY_AND_HOLD')
    if measured.get('human_support_required') is not need_support:
        raise ValueError('EXISTING_HUMAN_SUPPORT_MUST_BE_PRESERVED')
    pickup=pose(measured.get('pickup_pose'),'raised_pickup')
    landing=pose(measured.get('landing_pose'),'raised_landing')
    pad=pose(measured.get('pad_contact_pose'),'pad_contact')
    # The held block center and the closed tool share the same vertical line.
    pad[:2]=landing[:2]
    pad[3:]=landing[3:]
    old=pose(plan['settings']['pickup_pose'],'baseline_pickup')
    if pickup[2]<=old[2]:raise ValueError('RAISED_PICKUP_Z_REQUIRED')
    if math.dist(pickup[:2],old[:2])>.05:raise ValueError('SAME_SUPPLY_SLOT_REQUIRED')
    close=measured.get('pickup_width_mm');opened=measured.get('release_width_mm');press=measured.get('press_width_mm')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (close,opened,press)) or not 0<=close<opened<=110 or not 0<=press<=110:
        raise ValueError('MEASURED_GRIP_WIDTHS_REQUIRED')
    if press>12.:raise ValueError('CLOSED_PRESS_TOOL_WIDTH_REQUIRED')
    out=deepcopy(plan);p=deepcopy(profile);s=out['settings']
    p['force_stop_n']=45.
    p.pop('native_press',None)
    p['press_control']='POSITION_DESCENT_REACTION_STOP'
    p['force_control_target_n']=None
    out.update(mode='ROBOT_RELEASE_PRESS',assistance_kind='HOLD' if need_support else 'NONE',
        source_mode=plan['mode'],source_assistance_kind=plan['assistance_kind'],raised_human_step=True,
        source_plan_preserved=True,assembly_completion=False)
    s.update(pickup_pose=pickup,reference_pose=landing,release_pose=landing.copy(),assembly_tcp_zyz_deg=landing[3:],
        pickup_width_mm=close,release_width_mm=opened,press_width_mm=press,press_start_pose=pad.copy(),press_approach_pose=pad.copy(),
        raised_measurement_ref=measured['measurement_ref'])
    s['press_start_pose'][2]+=p['near_contact_offset_mm']
    s['press_approach_pose'][2]+=p['approach_offset_mm']
    s.pop('center_mapping',None)
    if not need_support:s.pop('human_step_gestures',None)
    out['human_actions']=['HOLD'] if need_support else []
    out['operations']=['PICK_RAISED','TRANSFER','HUMAN_READY' if need_support else 'ALIGN',
        'LAND_ON_STUDS','CONFIRM_LANDING','OPEN','VERTICAL_EMPTY_RETREAT','CLOSE_PRESS_TOOL','TOP_PRESS','RETREAT','BACKEND_OBSERVATION_REQUIRED']
    p['steps'][out['key']]=deepcopy(s)
    return out,p


def square_last_block(color,kind,orientation=0):
    """Four nonoverlapping pinwheel bars, three present, fourth is target.

    A grid fixture, not a measured collision clearance claim.
    """
    if (color,kind) not in KINDS or orientation not in (0,90):raise ValueError('SUPPORTED_BLOCK_REQUIRED')
    a,b=map(int,kind.split('x')[:2])
    raw=[(0,0,0),(a,0,90),(b,a,0),(0,b,90)]
    blocks=[dict(color=color,brick_type=kind,x=x+8,y=y+8,layer=1,orientation_deg=r) for x,y,r in raw]
    if orientation==0:
        # Reflect the entire pinwheel across its diagonal using axis exchange.
        blocks=[dict(q,x=q['y'],y=q['x'],orientation_deg=90-q['orientation_deg']) for q in blocks]
    return dict(current=blocks[:3],target=blocks[3],board_size=[24,24],fixture_kind='TEST_GRID_ONLY',square_outer_size_studs=a+b)
