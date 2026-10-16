"""Saved scope retains its original restriction; source auditing is separate."""
from initial_moveit_source import verify_initial_moveit_source


def verify_saved_initial_moveit_anchor(request_ref,result_ref,*,scope):
    if scope!='SAVED_ACTUAL_SIM_CPU_PREPARATION':
        raise ValueError('SAVED_ONLY_INITIAL_MOVEIT_ANCHOR_REVIEW_REQUIRED')
    return verify_initial_moveit_source(request_ref,result_ref)['initial_request']
