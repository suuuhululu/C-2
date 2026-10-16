"""Device-free receipt audit. Never authorizes execution or imports D runtime/ROS/SDK."""
from pathlib import Path
import math
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from plan_only import BINDING, digest, validate_trajectory

CONTEXT=('session_id','replan_sequence','obstacle_snapshot_digest','clock_basis')


def numeric(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Finite numeric PVT/time required')
    return float(value)


def preflight(packet, latest_binding, packet_context, latest_context, observed_start, *,
              start_tolerance_rad, max_snapshot_age_s):
    """Extra audit context is local metadata, not a replacement D execution schema."""
    if packet['execution_allowed'] is not False or packet['hardware_execution_allowed'] is not False:
        raise ValueError('Non-executable candidate required')
    if packet['units']!='rad, seconds':raise ValueError('Existing ROS rad/seconds units required; SDK deg is separate')
    if set(packet['binding'])!=set(BINDING) or set(latest_binding)!=set(BINDING):
        raise ValueError('Full existing planning binding required')
    for key in BINDING:
        if type(packet['binding'][key]) is not type(latest_binding[key]) or packet['binding'][key]!=latest_binding[key]:
            raise ValueError('Stale planning/request/reservation binding: '+key)
    if set(packet_context)!=set(CONTEXT) or set(latest_context)!=set(CONTEXT):raise ValueError('Explicit audit session/replan/obstacle/clock required')
    for key in CONTEXT:
        if type(packet_context[key]) is not type(latest_context[key]) or packet_context[key]!=latest_context[key]:
            raise ValueError('Stale audit context: '+key)
    if type(latest_context['replan_sequence']) is not int or latest_context['replan_sequence']<0:
        raise ValueError('Nonnegative replan sequence required')
    if any(not isinstance(latest_context[k],str) or not latest_context[k] for k in CONTEXT if k!='replan_sequence'):
        raise ValueError('Nonempty audit identity required')
    if observed_start['session_id']!=latest_context['session_id'] or observed_start['clock_basis']!=latest_context['clock_basis']:
        raise ValueError('Start snapshot session/clock mismatch')
    if observed_start['source_kind'] not in ('SIM_SAVED_SNAPSHOT','FIXTURE','REAL_DEVICE_SNAPSHOT'):
        raise ValueError('Explicit start snapshot source required')
    tolerance=numeric(start_tolerance_rad);max_age=numeric(max_snapshot_age_s);age=numeric(observed_start['age_s'])
    if tolerance<=0 or max_age<=0 or not 0<=age<=max_age:raise ValueError('Invalid threshold or stale snapshot')
    trajectory=packet['trajectory']
    for point in trajectory['points']:
        numeric(point['time_from_start_s'])
        for key in ('positions_rad','velocities_rad_s','accelerations_rad_s2'):
            for value in point[key]:numeric(value)
    validate_trajectory(trajectory)  # Existing ordered six joints, finite vectors and calculation limits.
    if packet['trajectory_interpolation']!='QUINTIC' or packet['terminal_gripper_policy']!='HOLD_NO_AUTOMATIC_OPEN':
        raise ValueError('Existing quintic and retained-grasp policy required')
    if any(abs(v)>1e-6 for v in trajectory['points'][-1]['velocities_rad_s']):
        raise ValueError('Existing terminal zero velocity required')
    stamps=[round(p['time_from_start_s']*1e9) for p in trajectory['points']]
    if len(stamps)!=len(set(stamps)):raise ValueError('Native nanosecond timestamp collision')
    if packet['trajectory_digest']!=digest(trajectory):raise ValueError('Trajectory digest changed')
    q=observed_start['q_rad']
    if len(q)!=6:raise ValueError('Six start positions in rad required')
    drift=max(abs(numeric(v)-p) for v,p in zip(q,trajectory['points'][0]['positions_rad']))
    if drift>tolerance:raise ValueError('Start mismatch; new state and planning required')
    for field in ('start_tcp_pose','pre_contact_tcp_pose'):
        pose=packet[field]
        if pose['frame_id']!='base_link' or len(pose['xyz_m'])!=3 or len(pose['quaternion_xyzw'])!=4:
            raise ValueError('Explicit base_link/m/xyzw TCP pose required')
        for v in pose['xyz_m']+pose['quaternion_xyzw']:numeric(v)
        if abs(sum(v*v for v in pose['quaternion_xyzw'])-1)>1e-6:raise ValueError('Unit TCP quaternion required')
    return dict(status='OFFLINE_RECEIPT_PREFLIGHT_PASSED_NOT_REAL_READY',execution_allowed=False,
        hardware_execution_allowed=False,execution_issued=False,trajectory_digest=packet['trajectory_digest'],
        point_count=len(stamps),binding_digest=digest(latest_binding),audit_context=dict(latest_context),
        start_drift_rad=drift,start_snapshot_source=observed_start['source_kind'],
        thresholds=dict(start_tolerance_rad=tolerance,max_snapshot_age_s=max_age,scope='CALLER_SUPPLIED_AUDIT_NOT_COMMISSIONING'),
        SIM_provenance_preserved=packet.get('simulation_provenance'),physical_commands=0,
        unresolved_REAL_checks=['Field test request and current device/grasp/workspace state',
            'Live D session, model/TCP and scene/held-block calibration',
            'Controller commissioning, exclusive writer and current inactive state',
            'Live start/PVT boundaries, collision scene/obstacle freshness',
            'Cancellation, verified physical stop, controller deactivation and unknown outcome recovery'])
