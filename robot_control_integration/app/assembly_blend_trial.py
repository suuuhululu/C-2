"""One reviewed blend batch; no overlapping motion commands."""
import math
import time
from app.assembly_motion import pose_error, vector
from scripts.assembly_position_trial import guard


def validate_route(start, targets, radius, *, relaxed=False):
    start = vector(start, 6, 'blend start')
    if (type(radius) not in (int, float) or not math.isfinite(radius) or not 0 < radius or (not relaxed and radius > 40) or
            not isinstance(targets, list) or not (1 if relaxed else 2) <= len(targets) <= (50 if relaxed else 4)):
        raise ValueError('REVIEWED_SMALL_BLEND_BATCH_REQUIRED')
    points = [vector(p, 6, 'blend target') for p in targets]
    previous = start
    directions = []
    for point in points:
        if not relaxed and (abs(point[2]-start[2]) > .05 or pose_error([*point[:3], *start[3:]], point)[1] > .1):
            raise ValueError('BLEND_REQUIRES_CONSTANT_HEIGHT_AND_ORIENTATION')
        distance = math.dist(previous[:3], point[:3])
        if distance <= 1e-6:
            if relaxed and len(points)==1 and pose_error(previous,point)[1]<=1.:
                continue  # A reached final endpoint needs no additional command.
            raise ValueError('BLEND_ZERO_LENGTH_SEGMENT')
        if not relaxed and distance <= 2*radius:
            raise ValueError('BLEND_SEGMENT_TOO_SHORT')
        direction = [(b-a)/distance for a,b in zip(previous[:3], point[:3])]
        if not relaxed and directions and abs(sum(a*b for a,b in zip(direction, directions[-1]))) > .9999:
            raise ValueError('BLEND_REQUIRES_DISTINCT_NONREVERSING_SEGMENTS')
        directions.append(direction)
        previous = point
    return points


def segment_radii(start, points, requested):
    # The local Doosan service supports a radius on every line segment.
    # Fit adjacent corners to the available lengths instead of rejecting the batch.
    lengths = [math.dist(a[:3],b[:3]) for a,b in zip([start,*points],points)]
    radii = [min(requested,.49*lengths[i],.49*lengths[i+1])
            for i in range(len(points)-1)]+[0.]
    # The onsite controller rejected 0.013 mm with alarm 1205. Clamping upward
    # would exceed the available short segment; keep required corners and reject.
    for index,radius in enumerate(radii[:-1]):
        if radius<=1.:
            raise ValueError(f'BLEND_RADIUS_BELOW_CONTROLLER_MINIMUM: segment={index} radius_mm={radius:.6f} required_gt_mm=1')
    return radii


def omit_reached_start(start, targets, record, stage):
    if not isinstance(targets,list):
        raise ValueError('REVIEWED_SMALL_BLEND_BATCH_REQUIRED')
    points=[vector(p,6,'blend target') for p in targets]
    omitted=[]
    # Match this trial's existing 1 mm / 1 degree arrival tolerance. Only leading
    # reached points may go: intermediate corners and the final slot stay intact.
    while len(points)>1:
        mm,deg=pose_error(start,points[0])
        if mm>1. or deg>1.:break
        omitted.append(points.pop(0))
    if omitted:
        record('BLEND_START_POINTS_OMITTED',dict(stage=stage,start=start,
            omitted_targets=omitted,position_tolerance_mm=1.,orientation_tolerance_deg=1.))
    return points


def corridor_distance(position, route):
    distances = []
    for a,b in zip(route, route[1:]):
        delta = [y-x for x,y in zip(a[:3], b[:3])]
        length2 = sum(v*v for v in delta)
        t = max(0., min(1., sum((p-x)*v for p,x,v in zip(position[:3], a[:3], delta))/length2))
        distances.append(math.dist(position[:3], [x+t*v for x,v in zip(a[:3], delta)]))
    return min(distances)


def run_blend(driver, connection, targets, profile, record, *, held=2,
              clock=time.monotonic, sleep=time.sleep):
    if type(profile.get('noncontact_force_guard',True)) is not bool:
        raise ValueError('EXPLICIT_NONCONTACT_FORCE_GUARD_BOOLEAN_REQUIRED')
    force_limit=profile['force_stop_n'] if profile.get('noncontact_force_guard',True) else None
    config = profile['transport_blending']
    if config.get('reviewed') is not True:
        raise ValueError('BLEND_ROUTE_REVIEW_REQUIRED')
    radius, rate, acceleration = config['radius_mm'], profile['transfer_velocity'], profile['transfer_acceleration']
    relaxed = config.get('relaxed_constraints',False)
    position_tolerance,orientation_tolerance = (1.,1.) if relaxed else (.05,.05)
    transit_position = config.get('transit_position_tolerance_mm',position_tolerance)
    transit_orientation = config.get('transit_orientation_tolerance_deg',orientation_tolerance)
    corridor_margin = config.get('corridor_margin_mm',.5)
    timeout_floor = config.get('timeout_floor_s',0.)
    finish_endpoint = config.get('finish_endpoint',False)
    if (type(finish_endpoint) is not bool or
            any(type(v) not in (int,float) or not math.isfinite(v) or v<minimum
                for v,minimum in ((transit_position,position_tolerance),
                    (transit_orientation,orientation_tolerance),(corridor_margin,0.),(timeout_floor,0.))) or
            (not finish_endpoint and (transit_position>position_tolerance or transit_orientation>orientation_tolerance))):
        raise ValueError('INVALID_BLEND_TRANSIT_TOLERANCES')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in (rate, acceleration)):
        raise ValueError('POSITIVE_FINITE_BLEND_RATES_REQUIRED')
    policy = getattr(getattr(driver,'session',None),'value',{}).get('stillness',{})
    def still(sample):
        speed=vector(sample['velx'],6,'blend velocity')
        return (sample['motion_status']==0 and
                max(map(abs,speed[:3]))<=policy.get('linear_mm_s',0.) and
                max(map(abs,speed[3:]))<=policy.get('angular_deg_s',0.))
    def checked(sample):
        try:
            guard(sample, connection, force_limit, automatic=True,
                  force_norm_limit=force_limit, required_gripper_status=held)
        except (RuntimeError,ValueError) as error:
            record('MOTION_GUARD_REJECTED',dict(reason=str(error),sample=sample,force_limit_n=force_limit))
            raise
    def settled():
        # Use the same reviewed window as control ownership, including after IK queries.
        if hasattr(driver,'stillness'):
            return driver.stillness(during_stillness=checked)
        sample=driver.sample();checked(sample);return sample
    attempted = False
    try:
        first = driver.sample();checked(first)
        points = omit_reached_start(first['posx'],targets,record,'INITIAL_START') if relaxed else targets
        points = validate_route(first['posx'], points, radius,relaxed=relaxed)
        for target in (targets if relaxed else points):
            fk = driver.check_pose(target)
            mm,deg=pose_error(fk,target)
            record('IK_FK_CHECK',dict(target=target,fk=fk,position_error_mm=mm,orientation_error_deg=deg))
            if mm > profile.get('ik_fk_position_tolerance_mm',.05) or deg > profile.get('ik_fk_orientation_tolerance_deg',.05):
                raise RuntimeError('IK_FK_ROUNDTRIP_MISMATCH')
            if mm > .05 or deg > .05:
                record('IK_FK_NUMERICAL_WARNING',dict(target=target,fk=fk,position_error_mm=mm,orientation_error_deg=deg))
        current = settled()
        mm,deg=pose_error(first['posx'], current['posx'])
        record('BLEND_START_RECHECK',dict(first_sample=first,current_sample=current,
            position_drift_mm=mm,orientation_drift_deg=deg,
            linear_limit_mm_s=policy.get('linear_mm_s',0.),angular_limit_deg_s=policy.get('angular_deg_s',0.)))
        # IK checks validate the destinations. The fresh stopped pose is the start;
        # feedback settling between those reads must not invalidate the command.
        if not still(current):raise RuntimeError('BLEND_START_NOT_STILL')
        # Reconsider the original route: a fresh pose can also require a rise
        # that appeared reached before the IK reads.
        points=omit_reached_start(current['posx'],targets,record,'COMMAND_START') if relaxed else points
        points=validate_route(current['posx'],points,radius,relaxed=relaxed)
        if len(points)==1:
            mm,deg=pose_error(current['posx'],points[-1])
            if mm<=position_tolerance and deg<=orientation_tolerance:
                record('BLEND_COMPLETE',dict(final_sample=current,endpoint_verified=True,
                    position_tolerance_mm=position_tolerance,orientation_tolerance_deg=orientation_tolerance,
                    command_sent=False))
                return current
        route = [current['posx'], *points]
        distance = sum(math.dist(a[:3], b[:3]) for a,b in zip(route, route[1:]))
        deadline = clock()+max(timeout_floor,distance/rate*3+10)
        finishing = False
        radii = segment_radii(current['posx'],points,radius) if relaxed else radius
        record('MOVE_REQUEST', dict(segment='BLENDED_TRANSIT', targets=points, radius_mm=radius,
                                   segment_radii_mm=radii,
                                   velocity=[rate,rate], acceleration=[acceleration,acceleration]))
        attempted = True
        if len(points)==1:
            driver.move_line_async(points[-1],[rate,rate],[acceleration,acceleration])
        else:
            driver.move_blending_async(points, radii, [rate,rate], [acceleration,acceleration])
        while True:
            sample = driver.sample()
            record('MOTION_SAMPLE', dict(segment='BLEND_ENDPOINT_FINISH' if finishing else 'BLENDED_TRANSIT', sample=sample))
            checked(sample)
            if corridor_distance(sample['posx'], route) > radius+corridor_margin:
                raise RuntimeError('BLEND_LEFT_REVIEWED_CORRIDOR')
            mm, deg = pose_error(sample['posx'], points[-1])
            arrival_mm = position_tolerance if finishing or len(points)==1 else transit_position
            arrival_deg = orientation_tolerance if finishing or len(points)==1 else transit_orientation
            if still(sample) and mm <= arrival_mm and deg <= arrival_deg:
                sample=settled();mm,deg=pose_error(sample['posx'],points[-1])
                if not still(sample) or mm>arrival_mm or deg>arrival_deg:
                    if clock()>=deadline:raise TimeoutError('BLEND_MOTION_TIMEOUT')
                    continue
                if not finishing and (mm>position_tolerance or deg>orientation_tolerance):
                    # A stopped blend near the destination is a transit boundary,
                    # not permission to descend. Finish the unchanged endpoint once.
                    record('BLEND_TRANSIT_COMPLETE',dict(final_sample=sample,
                        position_error_mm=mm,orientation_error_deg=deg,
                        position_tolerance_mm=transit_position,orientation_tolerance_deg=transit_orientation))
                    record('MOVE_REQUEST',dict(segment='BLEND_ENDPOINT_FINISH',target=points[-1],
                        velocity=[rate,rate],acceleration=[acceleration,acceleration]))
                    driver.move_line_async(points[-1],[rate,rate],[acceleration,acceleration])
                    finishing=True
                    deadline=clock()+math.dist(sample['posx'][:3],points[-1][:3])/rate*3+10
                    sleep(.05)
                    continue
                record('BLEND_COMPLETE', dict(final_sample=sample, endpoint_verified=True,
                    endpoint_finish_sent=finishing,
                    position_tolerance_mm=position_tolerance,orientation_tolerance_deg=orientation_tolerance))
                return sample
            if clock() >= deadline:
                raise TimeoutError('BLEND_MOTION_TIMEOUT')
            sleep(.05)
    except BaseException as error:
        stop = dict(requested=attempted, acknowledged=False, stillness_verified=False)
        if attempted:
            try:
                driver.stop()
                feedback = driver.motion_feedback()
                stop.update(acknowledged=True, feedback=feedback,
                            stillness_verified=still(feedback))
            except Exception as stop_error:
                stop['error'] = str(stop_error)
        record('ABORT', dict(reason=str(error), stop=stop))
        raise
