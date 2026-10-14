"""Explicit operator Base-Z offset trial. Never mislabeled as measured raised geometry."""
from copy import deepcopy
import math


def apply_held_offset_trial(config,offset_mm=10.):
    if type(offset_mm) not in (int,float) or not math.isfinite(offset_mm) or offset_mm!=10.:
        raise ValueError('OPERATOR_RAISED_TRIAL_PLUS10MM_REQUIRED')
    value=deepcopy(config)
    for row in value['blocks']:
        if row['pickup_pose'] is None:continue
        row['baseline_pickup_pose']=row['pickup_pose'].copy()
        row['pickup_pose'][2]+=offset_mm
        row.pop('center_mapping',None)
    value['alignment_target']['baseline_placement_tcp_reference']=value['alignment_target']['placement_tcp_reference'].copy()
    value['alignment_target']['placement_tcp_reference'][2]+=offset_mm
    value['alignment_approach_z_mm']+=offset_mm
    # Empty tool contact depends on the seated block top, NOT the held grasp height.
    value['operator_raised_z_trial']=dict(base_z_offset_mm=offset_mm,nominal_pad_bottom_height_mm=15.,
        source='USER_EXPLICIT_BASE_Z_OFFSET_TRIAL',measured_15mm_relation_verified=False,
        starts_with_changed_supply_pickup=True,assembly_completion=False)
    return value


def apply_step_offset_trial(plan,profile,offset_mm=10.):
    if type(offset_mm) not in (int,float) or offset_mm!=10.:
        raise ValueError('OPERATOR_RAISED_TRIAL_PLUS10MM_REQUIRED')
    out=deepcopy(plan);p=deepcopy(profile);s=out['settings']
    source=dict(pickup_pose=s['pickup_pose'].copy(),reference_pose=s['reference_pose'].copy())
    s['pickup_pose'][2]+=offset_mm;s['reference_pose'][2]+=offset_mm
    if 'release_pose' in s:s['release_pose'][2]+=offset_mm
    s.pop('center_mapping',None)
    out['operator_raised_z_trial']=dict(source='USER_EXPLICIT_BASE_Z_OFFSET_TRIAL',base_z_offset_mm=10.,
        baseline=source,measured_15mm_relation_verified=False,starts_with_changed_supply_pickup=True)
    p['steps'][out['key']]=deepcopy(s)
    return out,p
