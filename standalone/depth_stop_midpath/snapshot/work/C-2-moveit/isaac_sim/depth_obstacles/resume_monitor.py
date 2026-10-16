"""Fresh encoded monitor inputs. Never reuse the canceled goal's result/request."""
from copy import deepcopy
from current_geometry_fcl import load_calculation,pinned_json,LIVE
from plan_only import BINDING,digest


def prepare_monitor(selection,original_target):
    proof=pinned_json(selection['proof_ref'])
    if proof['scope']!=LIVE or proof['success'] is not True:
        raise ValueError('ACTUAL_LIVE_CURRENT_GEOMETRY_PROOF_REQUIRED')
    request,candidate,wire=load_calculation(selection['files'])
    if request['goal']!=original_target:raise ValueError('RESUME_ORIGINAL_TARGET_CHANGED')
    world=pinned_json(proof['snapshot']['world'])
    attachment=deepcopy(proof['actual_geometry']['attachment'])
    monitor_request=deepcopy(request)
    monitor_request['attachment']=attachment
    monitor_request['planning_snapshot']['grip_rad']=proof['actual_geometry']['grip_rad']
    packet=dict(binding={k:request[k] for k in BINDING},trajectory=deepcopy(wire),trajectory_digest=digest(wire),
                attachment=attachment,pre_contact_tcp_pose=deepcopy(request['goal']),
                source_calculation_request=deepcopy(proof['calculation_files']),
                monitor_scope='CURRENT_ENCODED_PROOF_MONITOR_NOT_REWRITTEN_CALCULATION')
    world_request=deepcopy(monitor_request)
    world_request['planning_snapshot']['world_objects']=deepcopy(world['objects'])
    return dict(original_request=request,request=monitor_request,packet=packet,world_request=world_request,
                proof_ref=deepcopy(selection['proof_ref']),wire_digest=digest(wire))
