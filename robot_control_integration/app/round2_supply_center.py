"""Current OpenCV stud-array detector into the native runner's pickup-center seam."""
from copy import deepcopy
from scripts.supply_pick_release_trial import center_target
from app.supply_stud.backend import observe


def reserved_slot(plan):
    reservation=plan.get('reservation') or {}
    number=reservation.get('slot',reservation.get('slot_index'))
    if number is None:
        try:number=int(reservation['slot_id'].rsplit('_',1)[-1])
        except (KeyError,ValueError):raise ValueError('ROUND2_EXACT_RESERVED_SLOT_REQUIRED')
    if type(number) is not int or not 1<=number<=5:raise ValueError('ROUND2_RESERVED_SLOT_1_TO5_REQUIRED')
    return number


def opencv_pickup_provider(capture,layout):
    """capture(plan,sample) obtains a FRESH RGB at reviewed supply observer pose."""
    def pickup(plan,sample):
        row=dict(color=plan['block']['color'],brick_type=plan['block']['brick_type'],slot=reserved_slot(plan),
            pickup_pose=deepcopy(plan['settings']['pickup_pose']))
        if plan['settings'].get('center_mapping') is not None:row['center_mapping']=deepcopy(plan['settings']['center_mapping'])
        packet=capture(deepcopy(plan),deepcopy(sample))
        if packet.get('fresh') is not True:raise ValueError('ROUND2_FRESH_SUPPLY_FRAME_REQUIRED')
        observation=observe(packet['frame_bgr'],layout,row,packet['stamp_ns'])
        target=center_target(row,observation)
        return dict(status='VISION_GRASP_PLAN_FOR_REVIEW',policy='COORDINATE_FIRST_WITH_OPTIONAL_CENTER',
            candidate_tcp_mm_zyz_deg=target,center_assist_applied=observation['center_assist_applied'],
            vision_attempted=True,recognized=observation['recognized'],fallback_reason=observation.get('fallback_reason'),
            observation=observation,source_ref=packet.get('source_ref'),physical_commands=0)
    return pickup
