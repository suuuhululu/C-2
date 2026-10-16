"""Deterministic uniform retiming of a new MoveIt command suffix, CPU only.

Original request/result/packet and q waypoints remain immutable. A single
integer scale from all analytic P/V/A/J extrema keeps the canonical delivered
nanosecond grid uniformly scaled. No limit changes, retries or spatial plan.
"""
from copy import deepcopy
from math import ceil
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from numpy.polynomial import Polynomial

from plan_only import digest, validate_trajectory, JOINTS
from prepare_cpu_model import file_hash
from sim_utils import save
from stop_curve import quintic_intervals, validate_quintic_limits

LIMITS = dict(velocity_rad_s=.35, acceleration_rad_s2=.7, jerk_rad_s3=5.)


def moveit_command_limits(command_profile='conservative'):
    if command_profile == 'conservative':return dict(LIMITS)
    if command_profile == 'SIM_FAST_J20':
        return dict(velocity_rad_s=.35, acceleration_rad_s2=.7, jerk_rad_s3=20.)
    raise ValueError('UNKNOWN_MOVEIT_COMMAND_PROFILE')


def analytic_extrema(trajectory):
    peaks = np.zeros(3);low = np.full(6, np.inf);high = -low
    for _, h, coefficients in quintic_intervals(trajectory):
        for joint in range(6):
            p = Polynomial(coefficients[:, joint])
            for order in range(4):
                d = p.deriv(order)
                roots = d.deriv().roots()
                u = [0., 1.] + [z.real for z in roots if abs(z.imag)<1e-8 and 0<z.real<1]
                values = d(np.asarray(u))/h**order
                if not np.isfinite(values).all():raise ValueError('NONFINITE_COMMAND_EXTREMA')
                if order == 0:
                    low[joint] = min(low[joint], float(min(values)))
                    high[joint] = max(high[joint], float(max(values)))
                else:peaks[order-1] = max(peaks[order-1], float(max(abs(values))))
    return dict(max_velocity_rad_s=float(peaks[0]), max_acceleration_rad_s2=float(peaks[1]),
                max_jerk_rad_s3=float(peaks[2]), min_q_rad=low.tolist(), max_q_rad=high.tolist())


def retime_moveit_command(folder, request, packet, parents, *, command_profile='conservative'):
    limits=moveit_command_limits(command_profile)
    folder = Path(folder)
    if folder.exists():raise ValueError('NEW_MOVEIT_TIMED_ARTIFACT_FOLDER_REQUIRED')
    for ref in parents.values():
        if file_hash(Path(ref['path'])) != ref['sha256']:raise ValueError('MOVEIT_TIMING_PARENT_CHANGED')
    raw = validate_trajectory(packet['trajectory'])
    if digest(raw) != packet['trajectory_digest']:raise ValueError('RAW_MOVEIT_SUFFIX_CHANGED')
    canonical = deepcopy(raw);source_ns=[]
    for p in canonical['points']:
        ns=round(p['time_from_start_s']*1e9);source_ns.append(ns);p['time_from_start_s']=ns/1e9
    if source_ns[0]!=0 or any(b<=a for a,b in zip(source_ns, source_ns[1:])):
        raise ValueError('CANONICAL_MOVEIT_NANOSECOND_ORDER_REQUIRED')
    before = analytic_extrema(canonical)
    required=max(1.,before['max_velocity_rad_s']/limits['velocity_rad_s'],
                 (before['max_acceleration_rad_s2']/limits['acceleration_rad_s2'])**.5,
                 (before['max_jerk_rad_s3']/limits['jerk_rad_s3'])**(1/3))
    scale=max(1,ceil(required))
    timed=deepcopy(canonical)
    for ns,p in zip(source_ns,timed['points']):
        p['time_from_start_s']=ns*scale/1e9
        p['velocities_rad_s']=[v/scale for v in p['velocities_rad_s']]
        p['accelerations_rad_s2']=[a/(scale*scale) for a in p['accelerations_rad_s2']]
    robot=ET.fromstring(request['model_bundle']['robot_description'])
    bounds=[robot.find("joint[@name='"+n+"']/limit") for n in JOINTS]
    # Original validator and numeric policy, on the final nanosecond wire.
    lower=[float(b.get('lower')) for b in bounds];upper=[float(b.get('upper')) for b in bounds]
    if command_profile=='conservative':checked=validate_quintic_limits(timed,lower,upper)
    else:checked=validate_quintic_limits(timed,lower,upper,command_limits=[limits[k] for k in ('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')])
    after=analytic_extrema(timed)
    if any(a['positions_rad']!=b['positions_rad'] for a,b in zip(raw['points'],timed['points'])):
        raise ValueError('MOVEIT_SPATIAL_WAYPOINT_CHANGED')
    folder.mkdir(parents=True)
    def ref(p):return dict(path=str(p.resolve()),sha256=file_hash(p))
    save(folder/'timed_trajectory.json',timed)
    limits_ref=ref(Path(__file__).with_name('stop_curve.py'))
    receipt=dict(scope='MOVEIT_DERIVED_COMMAND_TIMING_NOT_EXECUTION_APPROVAL',
        parents=deepcopy(parents),original_trajectory_digest=digest(raw),
        canonical_wire_trajectory_digest=digest(canonical),trajectory_digest=digest(timed),
        trajectory_ref=ref(folder/'timed_trajectory.json'),method='SINGLE_INTEGER_UNIFORM_TIME_SCALE_FROM_ANALYTIC_EXTREMA',
        minimum_analytic_scale=required,selected_integer_scale=scale,scale_search_iterations=0,
        time_rule='t_ns_new=integer_scale*round(t_original*1e9)',velocity_rule='v_new=v_original/scale',
        acceleration_rule='a_new=a_original/scale^2',command_profile=command_profile,original_command_limits=limits,
        command_limit_source=limits_ref,command_limit_scope='Explicit selected SIM command profile; conservative default unchanged, not physical observation or official hardware jerk bound',
        original_extrema=before,retimed_extrema=after,final_quintic_checks=checked,
        original_q_waypoints_exact=True,original_goal=deepcopy(request['goal']),
        geometric_curve_rule='Uniform reparameterization of canonical delivered Hermite quintic; no q replan or smoothing.',
        original_timestamp_rounding_max_s=max(abs(p['time_from_start_s']-ns/1e9) for p,ns in zip(raw['points'],source_ns)),
        input_files_modified=False,new_full_geometry_FCL_required=True,initial_connection_not_included=True,
        native_execution_allowed=False,hardware_execution_allowed=False)
    for parent in parents.values():
        if file_hash(Path(parent['path']))!=parent['sha256']:raise ValueError('MOVEIT_TIMING_PARENT_CHANGED_DURING_RETIMING')
    save(folder/'timing_receipt.json',receipt)
    return dict(timed_trajectory_ref=receipt['trajectory_ref'],timing_receipt_ref=ref(folder/'timing_receipt.json'))
