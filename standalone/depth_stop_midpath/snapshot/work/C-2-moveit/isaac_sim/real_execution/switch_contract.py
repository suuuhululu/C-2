"""Record-only future switch audit. No controller or collision checker invocation."""
from copy import deepcopy
import math
import numpy as np
from numpy.polynomial import Polynomial
from .preflight import digest
from stop_curve import quintic_intervals

JOINTS=['joint_'+str(i) for i in range(1,7)]
IDENTITY=('session_id','clock_basis','clock_epoch','goal_id','goal_version','cancel_generation',
          'snapshot_digest','snapshot_version','result_version','fcl_version')


def finite(value):
    if type(value) not in (float,int) or not math.isfinite(value):raise ValueError('FINITE_NUMBER_REQUIRED')
    return value


def at(trajectory,t):
    finite(t)
    if trajectory['joint_names']!=JOINTS:raise ValueError('JOINT_MAPPING_REQUIRED')
    for start,h,c in quintic_intervals(trajectory):
        if start<=t<=start+h:
            u=(t-start)/h
            return [np.array([Polynomial(c[:,j]).deriv(order)(u)/h**order for j in range(6)]) for order in range(3)]
    raise ValueError('SWITCH_OUTSIDE_EXISTING_TRAJECTORY')


def extrema(trajectory,limits):
    peaks=np.zeros(3)
    for _,h,c in quintic_intervals(trajectory):
        for joint in range(6):
            p=Polynomial(c[:,joint])
            for order in range(4):
                d=p.deriv(order);roots=d.deriv().roots()
                u=[0.,1.]+[z.real for z in roots if abs(z.imag)<1e-8 and 0<z.real<1]
                v=d(np.asarray(u))/h**order
                if not np.isfinite(v).all():raise ValueError('NONFINITE_QUINTIC')
                if order==0:
                    if min(v)<limits['lower_rad'][joint] or max(v)>limits['upper_rad'][joint]:raise ValueError('POSITION_LIMIT')
                else:
                    peak=max(abs(v));peaks[order-1]=max(peaks[order-1],peak)
                    if peak>limits['max_vaj'][order-1]+limits['numeric_vaj_tolerance'][order-1]:raise ValueError('QUINTIC_VAJ_LIMIT')
    return peaks.tolist()


class SwitchContract:
    def __init__(self):self.seen=set();self.previous=None
    def review(self,candidate,latest,limits):
        """Fixture boundary/evidence binding only; does not certify real FCL or tracking."""
        c=deepcopy(candidate);before=deepcopy(latest())
        if limits['scope']!='CPU_SWITCH_FIXTURE_LIMITS' or c['source_kind']!='FIXTURE':raise ValueError('FIXTURE_ONLY_NOT_SOURCE_ADMISSION')
        for key in ('lower_rad','upper_rad','qva_tolerance','max_vaj','numeric_vaj_tolerance'):
            values=limits[key];size=6 if key in ('lower_rad','upper_rad') else 3
            if len(values)!=size:raise ValueError('LIMIT_SIZE')
            for value in values:finite(value)
        if any(a>=b for a,b in zip(limits['lower_rad'],limits['upper_rad'])):raise ValueError('POSITION_BOUNDS')
        if any(v<0 for key in ('qva_tolerance','numeric_vaj_tolerance') for v in limits[key]) or min(limits['max_vaj'])<=0:raise ValueError('POSITIVE_LIMITS')
        for key in ('min_lead_s','max_observation_age_s','max_state_age_s','max_tracking_error_rad'): 
            if finite(limits[key])<0:raise ValueError('NEGATIVE_LIMIT')
        switch=finite(c['planned_switch_stamp_s']);deadline=finite(c['apply_deadline_s'])
        if deadline>switch:raise ValueError('DEADLINE_AFTER_SWITCH')
        def check(current):
            for key in IDENTITY:
                if type(c[key]) is not type(current[key]) or c[key]!=current[key]:raise ValueError('CONTEXT_CHANGED:'+key)
            if current['single_writer']!='D' or current['mode']!='EXECUTING':raise ValueError('D_EXECUTING_REQUIRED')
            if any(current[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):raise ValueError('STOP_FAILURE_UNKNOWN')
            for key in ('clock_epoch','goal_version','cancel_generation','snapshot_version','result_version','fcl_version'):
                if type(c[key]) is not int or c[key]<0:raise ValueError('INVALID_VERSION')
            now=finite(current['now_s'])
            if now>=deadline or switch-now<limits['min_lead_s']:raise ValueError('LATE_RESULT')
            if not 0<=now-finite(c['observation_stamp_s'])<=limits['max_observation_age_s']:raise ValueError('OBSERVATION_STALE_OR_FUTURE')
            if switch>finite(c['valid_until_s']):raise ValueError('OBSERVATION_EXPIRES_BEFORE_SWITCH')
            if not 0<=now-finite(current['state_stamp_s'])<=limits['max_state_age_s']:raise ValueError('STATE_STALE_OR_FUTURE')
            q=current['actual_q_rad']
            if len(q)!=6:raise ValueError('STATE_SIZE')
            expected=at(c['old_trajectory'],now-finite(c['old_goal_start_stamp_s']))[0]
            if max(abs(finite(x)-y) for x,y in zip(q,expected))>limits['max_tracking_error_rad']:raise ValueError('TRACKING_ERROR')
        check(before)
        if c['result_version']<=c['goal_version']:raise ValueError('RESULT_NOT_NEWER_THAN_GOAL')
        if self.previous is not None and self.previous['session_id']==c['session_id']:
            if self.previous['clock_epoch']!=c['clock_epoch']:raise ValueError('EPOCH_RESET_REQUIRES_NEW_REVIEW')
            if c['result_version']<=self.previous['result_version'] or c['snapshot_version']<self.previous['snapshot_version']:raise ValueError('OLD_OR_DUPLICATE_RESULT')
        if c['old_trajectory_digest']!=digest(c['old_trajectory']) or c['new_trajectory_digest']!=digest(c['new_trajectory']):raise ValueError('CURVE_CHANGED')
        old=at(c['old_trajectory'],switch-c['old_goal_start_stamp_s']);new=at(c['new_trajectory'],0.)
        for order in range(3):
            if max(abs(old[order]-new[order]))>limits['qva_tolerance'][order]:raise ValueError('SWITCH_QVA_DISCONTINUITY')
        last=c['new_trajectory']['points'][-1]
        if max(abs(finite(x)) for k in ('velocities_rad_s','accelerations_rad_s2') for x in last[k])>1e-10:raise ValueError('FINAL_STOP_REQUIRED')
        peaks=dict(old=extrema(c['old_trajectory'],limits),new=extrema(c['new_trajectory'],limits))
        expected=dict(snapshot_digest=c['snapshot_digest'],snapshot_version=c['snapshot_version'],result_version=c['result_version'],
                      fcl_version=c['fcl_version'],old_trajectory_digest=c['old_trajectory_digest'],new_trajectory_digest=c['new_trajectory_digest'],
                      old_goal_start_stamp_s=c['old_goal_start_stamp_s'],planned_switch_stamp_s=switch,valid_until_s=c['valid_until_s'])
        evidence=c['swept_evidence']
        finite(evidence['checked_from_s']);finite(evidence['checked_until_s'])
        if evidence['source_kind']!='FIXTURE' or evidence['binding']!=expected or evidence['time_varying_bounds_checked'] is not True:
            raise ValueError('SWEEP_BINDING_REQUIRED')
        if evidence['checked_from_s']>before['now_s'] or evidence['checked_until_s']<c['old_goal_start_stamp_s']+c['old_trajectory']['points'][-1]['time_from_start_s'] or evidence['checked_until_s']<switch+c['new_trajectory']['points'][-1]['time_from_start_s']:
            raise ValueError('REMAINING_OLD_AND_NEW_SWEEP_REQUIRED')
        if evidence['checked_until_s']>c['valid_until_s']:raise ValueError('SWEEP_EXCEEDS_OBSERVATION_VALIDITY')
        after=deepcopy(latest());check(after)
        if digest({k:v for k,v in before.items() if k!='now_s'})!=digest({k:v for k,v in after.items() if k!='now_s'}):raise ValueError('AUTHORITY_CHANGED_DURING_REVIEW')
        key=(c['session_id'],c['goal_id'],c['result_version'])
        if key in self.seen:raise ValueError('DUPLICATE_RESULT')
        self.seen.add(key);self.previous=deepcopy(c)
        return dict(status='CPU_SWITCH_FIXTURE_REVIEWED_NATIVE_UNSUPPORTED',dispatch_intent=None,execution_allowed=False,
                    hardware_execution_allowed=False,collision_safety_verified=False,tracking_verified=False,
                    switch_qva=[x.tolist() for x in old],quintic_peak_vaj=peaks,source_kind='FIXTURE',
                    native_blockers=['D send rejects active timed_goal','No explicit future header stamp',
                                     'No verified running-goal replacement/atomic switch or real swept FCL evidence'])
