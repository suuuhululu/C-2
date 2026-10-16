"""Read-only producer completion gate; no clocks, owners, transport or sender.

Classification and point receipts are independently pinned MI observations.
Fresh classification cannot certify a later full-point product. This gate adds
no risk qualification and leaves existing offline consumer APIs unchanged.
"""
from math import isfinite
from plan_only import digest
from .novel_depth_consumer import _read,snapshot_depth_shadow_inputs

MAX_SOURCE_AGE_S=.12  # Existing SIM test policy, not an official sensor tolerance.


def review_point_product_completion(detection,frame_state,*,source_frame_ref,
                                    classification_completion_ref,point_completion_ref):
    refs=dict(frame=source_frame_ref,classification=classification_completion_ref,point=point_completion_ref)
    result=dict(status='GUARD',guard=True,reasons=[],parent_refs=refs,
        classification_age_s=None,point_age_s=None,classification_fresh=False,point_fresh=False,
        source_stamp_s=frame_state['source_stamp_s'],max_source_age_s=MAX_SOURCE_AGE_S,
        live_intent_eligible=False,risk=None,stop_intent=None,execution_allowed=False)
    reasons=result['reasons']
    if detection['guard']:reasons.append('ORIGINAL_DETECTION_GUARD')
    if detection.get('projected') is None or '_projection_inputs' in detection:reasons.append('POINT_PRODUCT_NOT_MATERIALIZED')
    if source_frame_ref is None:reasons.append('SOURCE_FRAME_REF_MISSING')
    if classification_completion_ref is None:reasons.append('CLASSIFICATION_COMPLETION_REF_MISSING')
    if point_completion_ref is None:reasons.append('POINT_COMPLETION_REF_MISSING')
    if not reasons:
        try:
            if digest(_read(source_frame_ref))!=digest(frame_state):reasons.append('SOURCE_FRAME_CHANGED')
            if classification_completion_ref==point_completion_ref:reasons.append('COMPLETION_REF_REUSED')
            classification=_read(classification_completion_ref);point=_read(point_completion_ref)
            if not isinstance(classification,dict) or not isinstance(point,dict):raise ValueError('COMPLETION_RECORD_OBJECT_REQUIRED')
            clocks=[]
            for role,receipt in [('classification',classification),('point',point)]:
                if receipt.get('frame_input')!=source_frame_ref:reasons.append(role.upper()+'_FRAME_REF_MISMATCH')
                for k in ('session_id','clock_epoch','frame_seq','source_stamp_s'):
                    if type(receipt.get(k)) is not type(frame_state[k]) or receipt.get(k)!=frame_state[k]:
                        reasons.append(role.upper()+'_SOURCE_MISMATCH:'+k)
                summary=receipt['summary'];observation=receipt['completion_observation']
                if not isinstance(summary,dict) or not isinstance(observation,dict):raise ValueError('COMPLETION_SUMMARY_AND_CLOCK_REQUIRED')
                if 'clock_basis' in receipt and receipt['clock_basis']!=frame_state['clock_basis']:
                    reasons.append(role.upper()+'_SOURCE_MISMATCH:clock_basis')
                for k in ('map_digest','error_model_digest','qualification_ref','effective_pixel_convention','counts'):
                    if summary.get(k)!=detection.get(k):reasons.append(role.upper()+'_PRODUCT_MISMATCH:'+k)
                for k in ('session_id','clock_epoch','clock_basis'):
                    if type(observation.get(k)) is not type(frame_state[k]) or observation.get(k)!=frame_state[k]:
                        reasons.append(role.upper()+'_CLOCK_IDENTITY_MISMATCH:'+k)
                t=observation['source_s']
                if type(t) not in (int,float) or not isfinite(t):raise ValueError(role.upper()+'_FINITE_SOURCE_CLOCK_REQUIRED')
                age=t-frame_state['source_stamp_s'];clocks.append(t)
                result[role+'_age_s']=age;result[role+'_fresh']=0<=age<=MAX_SOURCE_AGE_S
                if receipt.get('completion_source_age_s') is not None and receipt['completion_source_age_s']!=age:
                    reasons.append(role.upper()+'_REPORTED_AGE_CHANGED')
                if not result[role+'_fresh']:reasons.append(role.upper()+'_COMPLETION_STALE_OR_FUTURE')
            if classification['summary'].get('projection_ready') is not False:
                reasons.append('CLASSIFICATION_ROLE_NOT_DECLARED')
            # Existing MI point notice declares FULL_POINT_PRODUCT_SHADOW in its
            # summary; clock_basis lives in completion_observation. The explicit
            # scope form is also accepted. Diagnostic-export scopes never alias it.
            scope=point.get('completion_scope')
            point_role=scope=='POINT_PRODUCT_COMPLETE' or (scope is None and point['summary'].get('result_product')=='FULL_POINT_PRODUCT_SHADOW')
            if not point_role or point['summary'].get('projection_ready') is not True:
                reasons.append('POINT_COMPLETION_ROLE_NOT_DECLARED')
            p=detection['projected']
            if point['summary'].get('projected_digest')!=p['digest']:reasons.append('POINT_PROJECTION_DIGEST_MISMATCH')
            if type(point['summary'].get('point_count')) is not int or point['summary']['point_count']!=len(p['pixel_uv']):reasons.append('POINT_COUNT_MISMATCH')
            if not frame_state['source_stamp_s']<=frame_state['received_stamp_s']<=clocks[0]<=clocks[1]:
                reasons.append('COMPLETION_CLOCK_ORDER_REVERSED')
            result.update(classification_observation=classification['completion_observation'],point_observation=point['completion_observation'],
                projected_digest=p['digest'],source_identity={k:frame_state[k] for k in ('session_id','clock_epoch','clock_basis','frame_seq','source_stamp_s')})
        except (ValueError,KeyError,OSError) as exc:
            reasons.append('COMPLETION_INPUT_REJECTED:'+str(exc))
    result['reasons']=list(dict.fromkeys(reasons))
    if not result['reasons']:result.update(status='POINT_COMPLETION_VERIFIED_SHADOW_ONLY',guard=False)
    result['digest']=digest(result)
    return result


def snapshot_completed_depth_shadow(raw,detection,expected,frame_state,*,source_frame_ref,
                                     classification_completion_ref,point_completion_ref,
                                     map_ref,error_model_ref,model_bundle,
                                     point_bounds=None,point_error_input=None):
    """Call with MI's actual stage refs under its existing producer buffer lock.

    Never computes/materializes points, samples a clock or manufactures an owner.
    Original completion files remain pinned through existing snapshot pre/post
    checks. A passing clock gate still has no native intent or world-clear claim.
    """
    review=review_point_product_completion(detection,frame_state,source_frame_ref=source_frame_ref,
        classification_completion_ref=classification_completion_ref,point_completion_ref=point_completion_ref)
    packet=None
    if not review['guard']:
        packet=snapshot_depth_shadow_inputs(raw,detection,expected,frame_state,map_ref=map_ref,
            error_model_ref=error_model_ref,model_bundle=model_bundle,point_bounds=point_bounds,point_error_input=point_error_input,
            origin_refs=[source_frame_ref,classification_completion_ref,point_completion_ref])
    return dict(snapshot=packet,completion_review=review,risk=None,stop_intent=None,live_intent_eligible=False)
