"""Model linkage example only; no UI, acquisition, commands or source edits."""
import json
from pathlib import Path
from isaac_sim.depth_obstacles.novel_depth.geometry import _pin
from isaac_sim.depth_obstacles.novel_depth.replay_saved import evaluate_depth_frame


def compute_with_native12_scope(actual_depth, known, captured_frame, limits, *, publication, original_now_source_s):
    if publication['status']!='SCOPED_PRE_OBSTACLE_QUALIFICATION_READY':
        raise ValueError('WAIT_NEW_NATIVE12_SCOPE')
    if (captured_frame['session_id']!=publication['session_id'] or
            captured_frame['clock_epoch']!=publication['clock_epoch']):
        raise ValueError('NATIVE12_CAPTURE_SCOPE_IDENTITY_MISMATCH')
    for ref in (publication['qualified_ref'],publication['error_ref']):_pin(ref)
    model=json.loads(Path(publication['error_ref']['path']).read_text())
    if model['qualification_ref']!=publication['qualified_ref']:
        raise ValueError('NATIVE12_MODEL_QUALIFICATION_PARENT_MISMATCH')
    # Preserve captured camera/frame/pixel/source clocks. No old-session model,
    # nearest RGB join or retiming fallback. item.detection masks are available
    # before materialize_projection; use the separate immutable display example.
    return evaluate_depth_frame(actual_depth,known,captured_frame,model,limits,now_source_s=original_now_source_s)
