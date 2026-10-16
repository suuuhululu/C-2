"""Call-site example for MI's EXISTING CPU worker, not a new worker/dispatcher.

MI first publishes classification/UI independently, then materializes points.
Only after the main loop has independently observed and pinned BOTH actual
completion receipts can its existing bounded job hand back these exact refs.
Do not wait in this function, manufacture a clock, or republish an old frame.

raw/item/frame must remain owned by that job until capture. The supplied lock
is MI's EXISTING producer-buffer lock, NEVER the D execution/physics/UI lock.
The gate reads pinned files; snapshot copies/seals buffers under that producer
lock. Validation happens after release, on this same existing CPU worker.
No D owner is available here: None shadow validation only, no risk or sender.
"""
import numpy as np
from isaac_sim.real_execution.point_product_handoff import snapshot_completed_depth_shadow
from isaac_sim.real_execution.novel_depth_consumer import adapt_depth_shadow_snapshot


def handoff(raw,item,frame,*,producer_buffer_lock,source_frame_ref,
            classification_ref,point_ref,map_ref,error_ref,model):
    # Source clocks come ONLY from the two original MI completion refs. No wall
    # time is promoted to SIM time. The helper gates before any expensive copy.
    runtime=dict(numpy_version=np.__version__,numpy_file=np.__file__)
    with producer_buffer_lock:
        completed=snapshot_completed_depth_shadow(raw,item['detection'],item['expected'],frame,
            source_frame_ref=source_frame_ref,classification_completion_ref=classification_ref,
            point_completion_ref=point_ref,map_ref=map_ref,error_model_ref=error_ref,model_bundle=model)
    consumed=None
    if completed['snapshot'] is not None:
        consumed=adapt_depth_shadow_snapshot(completed['snapshot'],None,
            max_age_s=.12,max_pose_skew_s=.001)
    return dict(runtime=runtime,completion_review=completed['completion_review'],
        consumption=consumed,risk=None,stop_intent=None,live_intent_eligible=False)

# This receipt gate verifies age AT original product completion. It does not
# prove freshness after queue/validation delay. MI must preserve another ACTUAL
# same-clock observation at final handoff/review and reject if age >.12 SIM s.
# Do not overwrite either completion receipt or call risk from this example.
# Missing main-loop point receipt: defer/skip in the existing bounded job; do
# not block the producer/main loop or substitute classification/export clocks.
