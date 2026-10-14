"""Coordinate XY correction and bounded insertion trial; not vision XY registration."""
import math
import time
from app.assembly_motion import motion_still,pose_error
from scripts.assembly_position_trial import guard,run


def xy_target(sample,config,max_correction_mm=2.):
    target=sample['posx'].copy()
    shift=math.dist(target[:2],config['assembly_target_xy'])
    if shift>max_correction_mm:raise ValueError('XY_CORRECTION_OUTSIDE_2MM_TRIAL_BOUND')
    minimum=config['alignment_approach_z_mm']
    if target[2]<minimum-.05:raise ValueError('XY_CORRECTION_BELOW_ALIGNMENT_CLEARANCE')
    target[:2]=config['assembly_target_xy']
    return target


def seating_targets(sample,config,step_mm=1.):
    if type(step_mm) not in (int,float) or not math.isfinite(step_mm) or not 0<step_mm<=1.:
        raise ValueError('POSITIVE_SEATING_STEP_MAX1MM_REQUIRED')
    reference=config['alignment_target']['placement_tcp_reference']
    current=sample['posx']
    if math.dist(current[:2],config['assembly_target_xy'])>.05:
        raise ValueError('SEATING_REQUIRES_TARGET_XY')
    goal=reference[2]
    if current[2]<=goal:raise ValueError('SEATING_START_ABOVE_TARGET_REQUIRED')
    targets=[];z=current[2]
    while z>goal+1e-8:
        z=max(goal,z-step_mm)
        targets.append([*current[:2],z,*current[3:]])
    return targets


def insert(driver,config,record, *, sleep=time.sleep,clock=time.monotonic):
    first=driver.sample()
    raw_stop=config['force_stop_n'];velocity=config.get('seating_velocity',6.)
    guard(first,config['connection'],raw_stop,automatic=True,force_norm_limit=raw_stop,required_gripper_status=2)
    deadline=clock()+5.
    while not motion_still(first):
        if clock()>=deadline:raise RuntimeError('SEATING_STOP_WAIT_TIMEOUT')
        sleep(.05);first=driver.sample()
        guard(first,config['connection'],raw_stop,automatic=True,force_norm_limit=raw_stop,required_gripper_status=2)
    targets=seating_targets(first,config)[-1:]
    for target in targets:
        if max(pose_error(driver.check_pose(target),target))>.05:
            raise RuntimeError('SEATING_ENDPOINT_IK_FK_MISMATCH')
    record('SEATING_TRIAL_START',dict(sample=first,goal=targets[-1],motion_mode='CONTINUOUS_DESCENT',
        velocity_mm_s=velocity,raw_force_stop_n=raw_stop,metric_vision_xy_used=False))
    capture=record
    status=None
    try:
        if max(pose_error(driver.sample()['posx'],first['posx']))>.05:
            raise RuntimeError('SEATING_START_CHANGED_AFTER_PREFLIGHT')
        for target in targets:
            run(driver,config['connection'],target,raw_stop,capture,
                clearance_z=None,force_norm_stop_n=raw_stop,required_gripper_status=2,
                transfer_rate=velocity,descent_rate=velocity,transfer_acceleration=1.,descent_acceleration=1.,
                angular_velocity=6.,angular_acceleration=3.,sleep=sleep,clock=clock)
        status='SEATING_TARGET_REACHED_HOLDING_NOT_VERIFIED'
    except RuntimeError as error:
        if str(error) not in ('FORCE_NORM_STOP_LIMIT_REACHED','FZ_STOP_LIMIT_REACHED'):raise
        driver.stop();status='FORCE_STOPPED_BEFORE_VERIFIED_SEATING'
    deadline=clock()+5
    final=driver.sample()
    while not motion_still(final):
        if clock()>=deadline:raise RuntimeError('SEATING_STOP_NOT_VERIFIED')
        sleep(.05);final=driver.sample()
    guard(final,config['connection'],config['force_stop_n'],automatic=True,force_norm_limit=config['force_stop_n'],required_gripper_status=2)
    result=dict(status=status,final_sample=final,assembly_completion=False,gripper_released=False,
                actual_seating_verified=False,coordinate_reference_only=True)
    record('SEATING_TRIAL_RESULT',result)
    return result


def release(driver,config,record, *, operator_seated=False,sleep=time.sleep,clock=time.monotonic):
    first=driver.sample()
    guard(first,config['connection'],config['force_stop_n'],automatic=True,force_norm_limit=config['force_stop_n'],required_gripper_status=2)
    goal=config['alignment_target']['placement_tcp_reference'][2]
    if not motion_still(first) or (not operator_seated and abs(first['posx'][2]-goal)>.1):
        raise RuntimeError('RELEASE_REQUIRES_STOPPED_AT_SEATING_TARGET')
    record('RELEASE_HEIGHT_DIAGNOSTIC',dict(z_error_mm=first['posx'][2]-goal,operator_seated=operator_seated,assembly_completion=False))
    driver.command_gripper(config['open_mm'],config['gripper_force_n'])
    deadline=clock()+10;stable=0
    while clock()<deadline:
        sample=driver.sample()
        guard(dict(sample,gripper_status=0),config['connection'],config['force_stop_n'],automatic=True,force_norm_limit=config['force_stop_n'],required_gripper_status=0)
        if sample['gripper_status'] not in (0,1,2):raise RuntimeError('GRIPPER_FAULT')
        okay=sample['gripper_status']==0 and motion_still(sample) and sample['gripper_width_mm']>=config['open_mm']-1
        stable=stable+1 if okay else 0
        if stable>=3:
            record('SEATED_RELEASE_OPERATOR_CONFIRMED',dict(sample=sample,assembly_completion=False));return
        sleep(.1)
    driver.stop();raise TimeoutError('SEATED_RELEASE_TIMEOUT')


def press_from_top_touch(driver,config,reference,record,required_gripper_status, *, sleep=time.sleep):
    from scripts.assembly_press_trial import press
    first=driver.sample()
    expected=[*reference[:2],reference[2]+10.,*reference[3:]]
    if max(pose_error(first['posx'],expected))>.1:
        raise RuntimeError('PAD_PRESS_REQUIRES_CAPTURED_TOP_PLUS10MM')
    velocity=config.get('press_velocity',6.)
    record('EMPTY_PAD_PRESS_SESSION',dict(top_touch_pose=reference,velocity_mm_s=velocity,
        force_stop_n=config['force_stop_n'],force_control_target_n=None,
        control='POSITION_DESCENT_REACTION_STOP',automatic_tilt_alignment=False))
    return press(driver,config['connection'],record,max_travel_mm=12.,force_stop_n=config['force_stop_n'],
        velocity=velocity,acceleration=1.,required_gripper_status=required_gripper_status,sleep=sleep)


def same_xy_press_plan(release_pose,config):
    """Experimental pad Z offset; release XY/attitude stay fixed, never old pad XY."""
    placement=config['alignment_target']['placement_tcp_reference']
    offset=config['integrated_pad_contact_pose'][2]-placement[2]
    contact=release_pose.copy();contact[2]+=offset
    above=contact.copy();above[2]+=10.
    risen=release_pose.copy();risen[2]=max(release_pose[2]+40.,above[2])
    return dict(release_pose=release_pose.copy(),estimated_contact_pose=contact,
        above_pose=above,rise_pose=risen,pad_z_offset_mm=offset,
        center_assumption='TAUGHT_NEAR_CENTER_GRASP',contact_height_physically_verified=False,
        no_xy_or_attitude_reposition=True)


def same_xy_press_cycle(driver,config,plan,status,record,move):
    from scripts.assembly_press_trial import press
    first=driver.sample()
    if math.dist(first['posx'][:2],plan['release_pose'][:2])>.5 or pose_error(first['posx'],[*first['posx'][:3],*plan['release_pose'][3:]])[1]>.1:
        raise RuntimeError('SAME_XY_PRESS_RELEASE_DATUM_CHANGED')
    record('SAME_XY_PRESS_START',plan)
    move(driver,config,plan['above_pose'],record,required_gripper_status=status)
    result=press(driver,config['connection'],record,max_travel_mm=12.,force_stop_n=config['force_stop_n'],
        velocity=config.get('press_velocity',12.),acceleration=1.,required_gripper_status=status)
    move(driver,config,plan['rise_pose'],record,required_gripper_status=status)
    record('SAME_XY_PRESS_RESULT',dict(press=result,assembly_completion=False,center_physically_verified=False,
        tilt_control='RELEASE_ATTITUDE_PRESERVED',contact_height_physically_verified=False))
    return result
