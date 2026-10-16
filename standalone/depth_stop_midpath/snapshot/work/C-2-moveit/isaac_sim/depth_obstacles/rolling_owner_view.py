"""Seal a current rolling window, preserving every original event separately."""
from copy import deepcopy
from isaac_sim.real_execution.owner_records import record_owner_event
from plan_only import digest
from isaac_sim.real_execution.native_boundary import OWNER_KEYS


def seal_view(records,owner):
    samples=owner['stop_record']['samples'];start=samples[0]['stamp_s'];end=samples[-1]['stamp_s']
    lifecycle={'GOAL_ACCEPTED','CANCEL_REQUEST','CANCEL_ACK','GOAL_RESULT'}
    counts=[r for r in records if r['event']=='COMMAND_COUNTS' and r['observed_stamp_s']<=end][-1:]
    original=[deepcopy(r) for r in records if r['event'] in lifecycle or
        (r['event']=='PHYSICS_SAMPLE' and start<=r['original_payload']['stamp_s']<=end) or r in counts]
    view=[]
    for r in original:
        context_keys=tuple(OWNER_KEYS)+('source_kind','state_source_kind','single_writer','mode','user_stop_latched','failure_latched','outcome_unknown','stop_reason','velocity_method','acceleration_method')
        context=deepcopy({k:owner[k] for k in context_keys} if r['event'] in ('PHYSICS_SAMPLE','COMMAND_COUNTS') else r['context'])
        projected=record_owner_event(r['event'],r['record_sequence'],context,r['original_payload'],observed_stamp_s=r['observed_stamp_s'],evidence=r['evidence'])
        projected.update(record_scope='CURRENT_SEALED_WINDOW_CONTEXT_NOT_ORIGINAL_EVENT_CONTEXT',original_record=deepcopy(r),original_record_digest=r['record_digest'])
        projected['record_digest']=digest({k:v for k,v in projected.items() if k!='record_digest'})
        view.append(projected)
    actual=[{k:r['original_payload'][k] for k in ('stamp_s','q_rad','v_rad_s','a_rad_s2')} for r in original if r['event']=='PHYSICS_SAMPLE']
    if actual!=samples:raise ValueError('CURRENT_ROLLING_WINDOW_NOT_EXACT_ORIGINAL_JOURNAL_SAMPLES')
    return original,view
