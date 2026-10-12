"""One reviewed horizontal blend batch; no overlapping motion commands."""
import math
import time
from app.assembly_motion import pose_error, vector
from scripts.assembly_position_trial import guard


def validate_route(start, targets, radius):
    start = vector(start, 6, 'blend start')
    if (type(radius) not in (int, float) or not math.isfinite(radius) or not 0 < radius <= 30 or
            not isinstance(targets, list) or not 2 <= len(targets) <= 4):
        raise ValueError('REVIEWED_SMALL_BLEND_BATCH_REQUIRED')
    points = [vector(p, 6, 'blend target') for p in targets]
    previous = start
    directions = []
    for point in points:
        if abs(point[2]-start[2]) > .05 or pose_error([*point[:3], *start[3:]], point)[1] > .1:
            raise ValueError('BLEND_REQUIRES_CONSTANT_HEIGHT_AND_ORIENTATION')
        distance = math.dist(previous[:3], point[:3])
        if distance <= 2*radius:
            raise ValueError('BLEND_SEGMENT_TOO_SHORT')
        direction = [(b-a)/distance for a,b in zip(previous[:3], point[:3])]
        if directions and abs(sum(a*b for a,b in zip(direction, directions[-1]))) > .9999:
            raise ValueError('BLEND_REQUIRES_DISTINCT_NONREVERSING_SEGMENTS')
        directions.append(direction)
        previous = point
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
    config = profile['transport_blending']
    if config.get('reviewed') is not True:
        raise ValueError('BLEND_ROUTE_REVIEW_REQUIRED')
    radius, rate, acceleration = config['radius_mm'], profile['transfer_velocity'], profile['transfer_acceleration']
    if any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in (rate, acceleration)):
        raise ValueError('POSITIVE_FINITE_BLEND_RATES_REQUIRED')
    policy = getattr(getattr(driver,'session',None),'value',{}).get('stillness',{})
    def still(sample):
        speed=vector(sample['velx'],6,'blend velocity')
        return (sample['motion_status']==0 and
                max(map(abs,speed[:3]))<=policy.get('linear_mm_s',0.) and
                max(map(abs,speed[3:]))<=policy.get('angular_deg_s',0.))
    def checked(sample):
        guard(sample, connection, profile['force_stop_n'], automatic=True,
              force_norm_limit=profile['force_stop_n'], required_gripper_status=held)
    def settled():
        # Use the same reviewed window as control ownership, including after IK queries.
        if hasattr(driver,'stillness'):
            return driver.stillness(during_stillness=checked)
        sample=driver.sample();checked(sample);return sample
    attempted = False
    try:
        first = driver.sample();checked(first)
        points = validate_route(first['posx'], targets, radius)
        for target in points:
            fk = driver.check_pose(target)
            if max(pose_error(fk, target)) > .05:
                raise RuntimeError('IK_FK_ROUNDTRIP_MISMATCH')
            record('IK_FK_CHECK', dict(target=target, fk=fk))
        current = settled()
        mm,deg=pose_error(first['posx'], current['posx'])
        record('BLEND_START_RECHECK',dict(first_sample=first,current_sample=current,
            position_drift_mm=mm,orientation_drift_deg=deg,
            linear_limit_mm_s=policy.get('linear_mm_s',0.),angular_limit_deg_s=policy.get('angular_deg_s',0.)))
        # IK checks validate the destinations. The fresh stopped pose is the start;
        # feedback settling between those reads must not invalidate the command.
        if not still(current):raise RuntimeError('BLEND_START_NOT_STILL')
        points=validate_route(current['posx'],targets,radius)
        route = [current['posx'], *points]
        distance = sum(math.dist(a[:3], b[:3]) for a,b in zip(route, route[1:]))
        deadline = clock()+distance/rate*3+10
        record('MOVE_REQUEST', dict(segment='BLENDED_TRANSIT', targets=points, radius_mm=radius,
                                   velocity=[rate,rate], acceleration=[acceleration,acceleration]))
        attempted = True
        driver.move_blending_async(points, radius, [rate,rate], [acceleration,acceleration])
        while True:
            sample = driver.sample()
            guard(sample, connection, profile['force_stop_n'], automatic=True,
                  force_norm_limit=profile['force_stop_n'], required_gripper_status=held)
            if corridor_distance(sample['posx'], route) > radius+.5:
                raise RuntimeError('BLEND_LEFT_REVIEWED_CORRIDOR')
            record('MOTION_SAMPLE', dict(segment='BLENDED_TRANSIT', sample=sample))
            mm, deg = pose_error(sample['posx'], points[-1])
            if still(sample) and mm <= .05 and deg <= .05:
                sample=settled();mm,deg=pose_error(sample['posx'],points[-1])
                if not still(sample) or mm>.05 or deg>.05:
                    if clock()>=deadline:raise TimeoutError('BLEND_MOTION_TIMEOUT')
                    continue
                record('BLEND_COMPLETE', dict(final_sample=sample, endpoint_verified=True))
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
