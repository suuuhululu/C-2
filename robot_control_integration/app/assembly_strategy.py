"""Dispatch D operations without changing the source A assembly mode."""
import hashlib
import json


def is_release_press(plan):
    """Accept the legacy D mode and A's ROBOT_GRIP release/press strategy."""
    return (plan.get('mode') == 'ROBOT_RELEASE_PRESS' or
            has_source_release_press(plan))


def has_source_release_press(plan):
    return (plan.get('mode') == 'ROBOT_GRIP' and
            plan.get('assembly_strategy') == 'RELEASE_PRESS')


def validate_d_profile_motion(motion,request,profile,key):
    """Bind D's profile proposal; it carries no A motion or physical approval."""
    proposal=motion.get('motion_proposal') or {}
    digest=hashlib.sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if (motion.get('message_type')!='DReleasePressMotionResult' or
            motion.get('schema_version')!='d-release-press-motion/1' or
            motion.get('producer')!='D_RELEASE_PRESS_PROFILE' or
            motion.get('status')!='CANDIDATE' or motion.get('execution_allowed') is not False or
            motion.get('errors') or motion.get('context')!=request['context'] or
            motion.get('assessment_id')!=request['assessment_id'] or
            proposal.get('motion_scope')!='D_PICK_TRANSPORT_RELEASE_PRESS' or
            not proposal.get('motion_plan_id') or proposal.get('profile_id')!=profile['profile_id'] or
            proposal.get('profile_digest')!=digest or proposal.get('d_profile_key')!=key):
        raise ValueError('D_PROFILE_MOTION_BINDING_MISMATCH')
    return motion
