"""Deterministic CPU stopping candidate; no dispatcher, SDK, ROS or device calls.

This deliberately simple construction first neutralizes measured acceleration,
then brakes velocity. It is not time/distance optimal or collision aware.
"""
import math
import numpy as np
from numpy.polynomial import Polynomial
from plan_only import JOINTS, validate_trajectory


def quintic_intervals(trajectory):
    points = validate_trajectory(trajectory)['points']
    for left, right in zip(points[:-1], points[1:]):
        h = right['time_from_start_s'] - left['time_from_start_s']
        q, v, a = [np.asarray(left[k], float) for k in
                   ('positions_rad', 'velocities_rad_s', 'accelerations_rad_s2')]
        dq = np.asarray(right['positions_rad']) - q - v*h - a*h*h/2
        dv = np.asarray(right['velocities_rad_s'])*h - v*h - a*h*h
        da = np.asarray(right['accelerations_rad_s2'])*h*h - a*h*h
        coefficients = np.array([q, v*h, a*h*h/2,
            10*dq-4*dv+da/2, -15*dq+7*dv-da, 6*dq-3*dv+da/2])
        yield left['time_from_start_s'], h, coefficients


def validate_quintic_limits(trajectory, lower, upper, *, command_limits=None):
    """Analytic extrema on the *delivered* quintic, including every interval."""
    lower, upper = np.asarray(lower, float), np.asarray(upper, float)
    if (lower.shape != (6,) or upper.shape != (6,) or
            not np.isfinite([lower, upper]).all() or np.any(lower >= upper)):
        raise ValueError('Six finite original position bounds required')
    limits = [.35, .7, 5.] if command_limits is None else list(command_limits)
    if len(limits)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in limits):
        raise ValueError('Three finite positive command derivative limits required')
    tolerances = [1e-6, 1e-6, 1e-5]
    peaks = np.zeros(3)
    for start, h, coefficients in quintic_intervals(trajectory):
        for joint in range(6):
            p = Polynomial(coefficients[:, joint])
            for order in range(4):
                derivative = p.deriv(order)
                roots = derivative.deriv().roots()
                u = [0., 1.] + [z.real for z in roots if abs(z.imag)<1e-8 and 0<z.real<1]
                values = derivative(np.asarray(u))/h**order
                if not np.isfinite(values).all():
                    raise ValueError('Nonfinite final quintic')
                if order == 0:
                    if min(values)<lower[joint]-1e-10 or max(values)>upper[joint]+1e-10:
                        raise ValueError(f'STOP_POSITION_LIMIT joint={joint+1} interval={start}')
                else:
                    peak = float(max(abs(values))); peaks[order-1] = max(peaks[order-1], peak)
                    if peak > limits[order-1]+tolerances[order-1]:
                        raise ValueError(f'STOP_DERIVATIVE_LIMIT order={order} joint={joint+1} value={peak}')
    return dict(final_quintic_extrema_qva_j_verified=True,
                max_velocity_rad_s=peaks[0], max_acceleration_rad_s2=peaks[1],
                max_jerk_rad_s3=peaks[2], numerical_tolerances_vaj=tolerances)


def validate_stop(trajectory, lower, upper):
    """Stopping candidates additionally promise zero terminal v/a."""
    checks=validate_quintic_limits(trajectory,lower,upper)
    last=trajectory['points'][-1]
    if max(abs(x) for x in last['velocities_rad_s']+last['accelerations_rad_s2'])>1e-10:
        raise ValueError('STOP_NONZERO_TERMINAL_V_A')
    return checks


def stopping_candidate(q, v, a, lower, upper):
    q, v, a = map(lambda x: np.asarray(x, float), (q, v, a))
    if any(x.shape != (6,) or not np.isfinite(x).all() for x in (q, v, a)):
        raise ValueError('Six finite same-time q/v/a values required')
    if np.any(abs(v)>.35) or np.any(abs(a)>.7):
        raise ValueError('INITIAL_STATE_EXCEEDS_ORIGINAL_LIMITS')
    # Every phase boundary lies on the 10ms output grid: quintic interpolation
    # never bridges a jerk change. Recompute jerk after rounding durations up.
    quantum=.01
    ticks=lambda seconds: max(1, math.ceil(seconds/quantum-1e-12))
    axes=[]
    for velocity, acceleration in zip(v, a):
        phases=[]
        if acceleration != 0:
            n=ticks(abs(acceleration)/5.)
            phases.append((n, -acceleration/(n*quantum)))
            velocity += acceleration*n*quantum/2
        if abs(velocity)>0:
            sign=math.copysign(1.,velocity); speed=abs(velocity)
            if speed<=.7**2/5:
                ramp=ticks(math.sqrt(speed/5.)); plateau=0
            else:
                ramp=ticks(.7/5.); plateau=max(0,math.ceil((speed/.7-ramp*quantum)/quantum-1e-12))
            jerk=speed/(ramp*(ramp+plateau)*quantum**2)
            phases.append((ramp,-sign*jerk))
            if plateau: phases.append((plateau,0.))
            phases.append((ramp,sign*jerk))
        axes.append(phases)
    total=max(1,max(sum(n for n,_ in phases) for phases in axes))
    points=[];position=q.copy();velocity=v.copy();acceleration=a.copy()
    for k in range(total+1):
        points.append(dict(positions_rad=position.tolist(),velocities_rad_s=velocity.tolist(),
            accelerations_rad_s2=acceleration.tolist(),time_from_start_s=k/100.))
        if k==total: break
        jerks=[]
        for phases in axes:
            offset=0;value=0.
            for n,j in phases:
                if offset<=k<offset+n: value=j;break
                offset+=n
            jerks.append(value)
        j=np.asarray(jerks)
        position += velocity*quantum+acceleration*quantum**2/2+j*quantum**3/6
        velocity += acceleration*quantum+j*quantum**2/2
        acceleration += j*quantum
    trajectory=dict(joint_names=JOINTS,points=points)
    checks=validate_stop(trajectory,lower,upper)
    return dict(scope='CPU_JERK_LIMITED_STOP_CANDIDATE_NOT_NATIVE_CANCEL',
        execution_allowed=False,hardware_execution_allowed=False,trajectory=trajectory,
        initial_qva=[q.tolist(),v.tolist(),a.tolist()],duration_s=total/100.,
        stopping_displacement_rad=(position-q).tolist(),checks=checks,
        construction='ACCELERATION_NEUTRALIZATION_THEN_JERK_LIMITED_BRAKE',
        optimal=False,collision_checked=False,phase_grid_s=quantum)
