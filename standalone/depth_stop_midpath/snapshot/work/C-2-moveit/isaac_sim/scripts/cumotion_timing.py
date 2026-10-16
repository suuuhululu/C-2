"""Explicit spline retiming. Collision-unaware; final quintic/FCL is required."""
import time
import numpy as np


ENGINE = "CUMOTION_SDK_SPLINE_FCL_CALCULATION_ONLY"
TIMING_ENGINE = "CUMOTION_SDK_CSPACE_SPLINE_RETIMED_NO_TOTG"


def final_quintic_jerk(trajectory):
    """Analytic jerk extrema of every delivered Hermite quintic interval."""
    from plan_only import validate_trajectory
    trajectory = validate_trajectory(trajectory)
    points = trajectory['points']
    t = np.array([p['time_from_start_s'] for p in points])
    q, v, a = [np.array([p[key] for p in points]) for key in
               ('positions_rad', 'velocities_rad_s', 'accelerations_rad_s2')]
    h = np.diff(t)[:, None]
    c1, c2 = v[:-1]*h, a[:-1]*h*h/2
    rhs = np.stack([q[1:]-q[:-1]-c1-c2,
                    v[1:]*h-c1-2*c2, a[1:]*h*h-2*c2], axis=-1)
    tail = rhs @ np.linalg.inv([[1., 1., 1.], [3., 4., 5.], [6., 12., 20.]]).T
    j0, j1, j2 = (tail * [6., 24., 60.]).transpose(2, 0, 1)/h**3
    u = np.divide(-j1, 2*j2, out=np.zeros_like(j1), where=abs(j2)>1e-12)
    peak = np.maximum(abs(j0), abs(j0+j1+j2))
    peak = np.maximum(peak, np.where((u>0) & (u<1), abs(j0+j1*u+j2*u*u), 0.))
    if not np.isfinite(peak).all() or np.max(peak)>5.00001:
        raise ValueError('FINAL_QUINTIC_JERK_LIMIT_EXCEEDED')
    return dict(max_jerk_rad_s3=float(np.max(peak)), intervals=len(h),
                nominal_limit_rad_s3=5., numerical_tolerance_rad_s3=.00001)


def linear_breakpoints(times, positions):
    """Recover line intersections without assuming SDK knot/padding counts."""
    times, positions = np.asarray(times, float), np.asarray(positions, float)
    if (times.ndim != 1 or positions.ndim != 2 or len(times) != len(positions)
            or len(times) < 5 or not np.isfinite(times).all()
            or not np.isfinite(positions).all() or np.any(np.diff(times) <= 0)):
        raise ValueError("Finite ordered sampled position path required")
    slopes = np.diff(positions, axis=0) / np.diff(times)[:, None]
    changes = np.flatnonzero(np.max(np.abs(np.diff(slopes, axis=0)), axis=1) > 1e-8)
    groups = np.split(changes, np.flatnonzero(np.diff(changes) > 1) + 1) if len(changes) else []
    knots, points = [times[0]], [positions[0].copy()]
    for group in groups:
        left, right = int(group[0]) - 1, int(group[-1]) + 2
        if left < 0 or right >= len(slopes) or len(group) > 2:
            raise ValueError("Native position path is not resolved piecewise linear")
        difference = slopes[left] - slopes[right]
        rhs = (positions[right] - positions[left] + slopes[left] * times[left]
               - slopes[right] * times[right])
        t = float(np.dot(difference, rhs) / np.dot(difference, difference))
        if not times[left] < t < times[right + 1] or t <= knots[-1]:
            raise ValueError("Unresolved native position breakpoint")
        knots.append(t)
        points.append(positions[left] + slopes[left] * (t - times[left]))
    knots.append(times[-1]); points.append(positions[-1].copy())
    points, knots = np.asarray(points), np.asarray(knots)
    rebuilt = np.column_stack([np.interp(times, knots, points[:, j]) for j in range(points.shape[1])])
    error = float(np.max(np.abs(rebuilt - positions)))
    if error > 1e-9:
        raise ValueError("Recovered native position path does not match all samples")
    return knots, points, error


def position_breakpoints(times, positions):
    knots, points, error = linear_breakpoints(times, positions)
    # Endpoint holds are removed only for this explicitly retimed path.
    keep = np.r_[True, np.max(np.abs(np.diff(points, axis=0)), axis=1) > 1e-9]
    if np.count_nonzero(keep) < 2:
        raise ValueError("Nonstationary path required for spline retiming")
    return points[keep], dict(sampled_position_fit_error_rad=error,
        recovered_position_node_count=len(points), spline_input_node_count=int(np.count_nonzero(keep)),
        endpoint_hold_times_preserved=False)


def export_spline_points(trajectory):
    """Include acceleration slope changes so quintic never bridges two cubics.

    SDK cubic splines have continuous, piecewise-linear acceleration. Their
    jerk can jump at segment boundaries; a quintic spanning a jump may exceed
    even the exact spline's derivative limits. Segment-aware export preserves
    the curve up to the final nanosecond timestamp representation.
    """
    domain = trajectory.domain()
    probes = np.linspace(domain.lower, domain.upper, 16385)
    acceleration = np.array([np.array(trajectory.eval(float(t), 2), copy=True) for t in probes])
    knots, _, error = linear_breakpoints(probes, acceleration)
    times = [domain.lower]
    for start, stop in zip(knots[:-1], knots[1:]):
        times.extend(np.linspace(start, stop, int(np.ceil((stop-start)/.01))+1)[1:])
    nanoseconds = np.rint((np.array(times)-domain.lower)*1e9).astype(np.int64)
    if np.any(np.diff(nanoseconds) <= 0):
        raise ValueError("Spline segments unresolved at nanosecond timestamp precision")
    points = []
    for ns in nanoseconds:
        t = float(ns)*1e-9
        p,v,a,_ = trajectory.eval_all(float(np.clip(domain.lower+t,domain.lower,domain.upper)))
        points.append(dict(positions_rad=p.tolist(), velocities_rad_s=v.tolist(),
            accelerations_rad_s2=a.tolist(), time_from_start_s=t))
    return points, dict(segment_boundary_count=len(knots),
        acceleration_boundary_probe_count=len(probes), sampled_acceleration_fit_error_rad_s2=error,
        spline_segment_boundaries_included=True, timestamps_quantized_to_nanoseconds=True,
        max_export_interval_s=float(np.max(np.diff(nanoseconds)))*1e-9)


def retime_sdk_position_path(native, lower, upper, jerk_limits, cumotion, *, velocity_limit=.35, acceleration_limit=.7):
    """Rebuild q/v/a from one SDK spline; no planner/derivative fallback."""
    begin = time.perf_counter()
    domain = native.domain()
    times = np.linspace(domain.lower, domain.upper, 4097)
    positions = np.array([np.array(native.eval(float(t)), copy=True) for t in times])
    points, metadata = position_breakpoints(times, positions)
    n = positions.shape[1]
    lower, upper, jerk_limits = map(lambda x: np.asarray(x, float), (lower, upper, jerk_limits))
    if (any(x.shape != (n,) or not np.isfinite(x).all() for x in (lower, upper, jerk_limits))
            or np.any(lower >= upper) or np.any(jerk_limits <= 0)
            or np.any(points < lower) or np.any(points > upper)):
        raise ValueError("Invalid original position/temporary jerk limits")
    if not (np.isfinite([velocity_limit,acceleration_limit]).all() and
            0<velocity_limit<=.35 and 0<acceleration_limit<=.7 and np.all(jerk_limits<=5.)):
        raise ValueError('Retiming cannot exceed original v/a/temporary jerk ceilings')
    generator = cumotion.create_cspace_trajectory_generator(n)
    generator.set_position_limits(lower, upper)
    generator.set_velocity_limits(np.full(n, velocity_limit))
    generator.set_acceleration_limits(np.full(n, acceleration_limit))
    generator.set_jerk_limits(jerk_limits)
    trajectory = generator.generate_trajectory([p.copy() for p in points])
    if trajectory is None:
        raise ValueError("SDK spline generation failed; no fallback")
    out = trajectory.domain()
    if (np.max(np.abs(trajectory.eval(out.lower) - positions[0])) > 1e-9
            or np.max(np.abs(trajectory.eval(out.upper) - positions[-1])) > 1e-9):
        raise ValueError("SDK spline retiming changed an endpoint")
    metadata.update(engine="CUMOTION_SDK_CSPACE_SPLINE_RETIMED_NO_TOTG", native_timing_changed=True,
        native_duration_s=domain.span(), final_duration_s=out.span(),
        native_position_sampling_count=len(times), native_derivatives_used=False,
        collision_aware=False, final_quintic_fcl_required=True,
        used_velocity_limit_rad_s=velocity_limit,used_acceleration_limit_rad_s2=acceleration_limit,
        used_jerk_limits_rad_s3=jerk_limits.tolist(),
        retiming_wall_s=time.perf_counter() - begin)
    return trajectory, metadata
