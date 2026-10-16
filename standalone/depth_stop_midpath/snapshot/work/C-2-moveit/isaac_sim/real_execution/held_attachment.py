"""Reported REAL profile and same-snapshot attachment review; no execution or geometry mutation."""
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
from .engine_receipt import sha
from .preflight import digest,BINDING
from .planner_bundle import read_bundle,PlannerBundleConsumer,consume_hold_evidence
from plan_only import rigid

CONTEXT=('source_kind','session_id','clock_basis','clock_epoch','source_stamp_s','state_sequence','replan_sequence','cancel_generation',
         'tcp_frame_id','block_frame_id','base_frame_id','model_digest','geometry_profile_id','geometry_profile_sha256','selected_block_id','attachment_digest','geometry_digest')


def measured_profile(reference_path,reference_sha):
    path=Path(reference_path)
    if sha(path)!=reference_sha:raise ValueError('MEASUREMENT_REFERENCE_CHANGED')
    ref=json.loads(path.read_text());files=ref['files']
    def select(suffix):return next(x for x in files if x['path'].endswith(suffix))
    latest=select('round2_geometry.operator_20261013.json');old=select('block_geometry.user_20261008.rev2.json');grasp=select('supply_slot1_grasp_summary.json')
    measured=latest['content'];d=measured['reported_dimensions'];pitch=old['content']['pitch_mm'];height=d['height_with_studs_mm']-d['body_height_without_studs_mm']
    profiles={}
    for typ,nx,ny in [('1x2x1',1,2),('2x2x1',2,2),('2x3x1',2,3)]:
        span=lambda n:d[f'span_{n}_outer_length_mm']
        centres=[[(i-(nx-1)/2)*pitch/1000,(j-(ny-1)/2)*pitch/1000,(d['body_height_without_studs_mm']/2+height/2)/1000] for i in range(nx) for j in range(ny)]
        profiles[typ]=dict(visual_reference_body_size_m=[span(nx)/1000,span(ny)/1000,d['body_height_without_studs_mm']/1000],
            axis_basis='REPORTED_SPAN_LENGTHS_REUSED_BY_DESIGN_AXIS_NOT_INDEPENDENT_TWO_AXIS_MEASUREMENTS',stud_count=nx*ny,
            stud_layout_basis='DESIGN_GRID_NOT_REMEASURED',stud_centres_body_m=centres,stud_visual_shape='CYLINDER_DIAMETER_REFERENCE',stud_diameter_m=d['stud_diameter_mm']/1000,stud_height_m=height/1000)
    value=dict(schema='real-reported-block-profile/0.1',profile_id='ROKEY_USER_REPORTED_OUTER_20261013',profile_version=1,
        source_kind='REAL_REPORTED_MEASUREMENT_REFERENCE',reported_date=measured['reported_date'],units=dict(source='mm',geometry='m',orientation='rad'),
        block_frame=dict(origin='BODY_GEOMETRIC_CENTRE',axis_basis='DESIGN_XY_UP_Z_REFERENCE_NOT_MEASURED_POSE',matrix_convention='parent_T_child column vectors'),
        measured_dimensions_mm=deepcopy(d),body_height_m=d['body_height_without_studs_mm']/1000,
        studs=dict(visual_shape='CYLINDER_DIAMETER_REFERENCE',diameter_m=d['stud_diameter_mm']/1000,height_m=height/1000,
                   height_basis='DERIVED_TOTAL_MINUS_BODY_NOT_DIRECT_MEASUREMENT',height_formula_mm='24.0 - 19.6',pitch_m=pitch/1000,
                   pitch_basis='20261008_DESIGN_REFERENCE_NOT_20261013_REMEASURED',pitch_remeasurement_m=None),
        brick_variants=profiles,gripper_pad_reference=dict(thickness_m=d['gripping_pad_thickness_mm']/1000,
            face_size_m=[d['gripping_pad_face_height_mm']/1000,d['gripping_pad_face_width_mm']/1000],actual_loaded_contact_area_m2=None),
        uncertainty=deepcopy(measured['uncertainty']),collision_envelope=dict(status='UNKNOWN_NOT_CERTIFIED',approved_margin_m=None,approved_geometry=None,execution_usable=False),
        source_reference=dict(path=str(path.resolve()),sha256=reference_sha,scope='MANAGEMENT_READ_ONLY_SSH_ARCHIVE_EMBEDDED_CONTENT'),
        source_records=[dict(remote_path=x['path'],remote_file_sha256=x['sha256'],embedded_content_digest=digest(x['content']),original_content=deepcopy(x['content'])) for x in (latest,old,grasp)],
        historical_grasp=dict(operator_height_mm=grasp['content']['operator_confirmed_grasp_height_mm'],tcp_posx_mm_deg=grasp['content']['current_tcp_posx'],
                             sdk_posj_deg=grasp['content']['posj'],tcp_to_brick_transform=None,scope='HISTORICAL_REFERENCE_NOT_CURRENT_ATTACHMENT'),
        tcp_to_brick_transform=None,assembly_layer_increment_m=None,hardware_execution_allowed=False,execution_allowed=False,world_clear_allowed=False)
    value['profile_digest']=digest(value)
    return value


def pinned_profile(path,expected_sha):
    if sha(path)!=expected_sha:raise ValueError('PROFILE_FILE_CHANGED')
    p=json.loads(Path(path).read_text())
    if p['profile_digest']!=digest({k:v for k,v in p.items() if k!='profile_digest'}):raise ValueError('PROFILE_DIGEST_CHANGED')
    if p['source_kind']!='REAL_REPORTED_MEASUREMENT_REFERENCE':raise ValueError('REPORTED_REAL_PROFILE_REQUIRED')
    original=measured_profile(p['source_reference']['path'],p['source_reference']['sha256'])
    if p!=original:raise ValueError('PROFILE_NOT_ORIGINAL_REPORTED_REFERENCE')
    return p


def review_attachment(snapshot,cu_context,d_receipt_context,*,profile_path,profile_sha,latest_owner):
    """Both consumers must name one owner-recorded simultaneous 6D observation."""
    profile=pinned_profile(profile_path,profile_sha);s=deepcopy(snapshot);before=deepcopy(latest_owner())
    if s['schema']!='held-block-owner-snapshot/0.1' or s['source_kind'] not in ('FIXTURE','SIM_OWNER_RECORD','REAL_OWNER_RECORD'):raise ValueError('OWNER_SNAPSHOT_REQUIRED')
    if s['snapshot_digest']!=digest({k:v for k,v in s.items() if k!='snapshot_digest'}):raise ValueError('OWNER_ATTACHMENT_SNAPSHOT_CHANGED')
    if s['matrix_convention']!='parent_T_child column vectors' or s['units']!='m, rad':raise ValueError('ATTACHMENT_FRAME_UNITS')
    if len({s[k] for k in ('tcp_frame_id','block_frame_id','base_frame_id')})!=3 or not all(s[k] for k in ('tcp_frame_id','block_frame_id','base_frame_id')):raise ValueError('EXPLICIT_DISTINCT_FRAMES_REQUIRED')
    if s['source_stamp_s']!=s['tcp_stamp_s'] or s['source_stamp_s']!=s['block_stamp_s']:raise ValueError('SIMULTANEOUS_TCP_BLOCK_REQUIRED')
    for k in ('clock_epoch','state_sequence','replan_sequence','cancel_generation'):
        if type(s[k]) is not int or s[k]<0:raise ValueError('INVALID_ATTACHMENT_VERSION')
    if type(s['source_stamp_s']) not in (int,float):raise ValueError('SOURCE_STAMP_REQUIRED')
    if not np.isfinite(s['source_stamp_s']) or s['source_stamp_s']<=0:raise ValueError('SOURCE_STAMP_REQUIRED')
    if s['geometry_profile_id']!=profile['profile_id'] or s['geometry_profile_sha256']!=profile_sha:raise ValueError('PROFILE_MIXING')
    if s['selected_brick_type'] not in profile['brick_variants']:raise ValueError('UNKNOWN_REPORTED_BRICK_VARIANT')
    tcp=rigid(s['T_base_TCP']);block=rigid(s['T_base_block']);attachment=rigid(s['attachment_tcp_to_block'])
    if not np.allclose(np.linalg.inv(tcp)@block,attachment,atol=1e-10,rtol=0):raise ValueError('ATTACHMENT_NOT_SAME_OBSERVATION')
    if s['attachment_digest']!=digest(s['attachment_tcp_to_block']):raise ValueError('ATTACHMENT_DIGEST_MISMATCH')
    if s['geometry_digest']!=digest(s['geometry_definition']) or s['geometry_definition']!=profile['brick_variants'][s['selected_brick_type']]:raise ValueError('GEOMETRY_PROFILE_MISMATCH')
    def authority(current):
        if current['single_writer']!='D' or any(current[k] is not False for k in ('user_stop_latched','failure_latched','outcome_unknown')):raise ValueError('D_OWNER_STOP_FAILURE_UNKNOWN')
        for ctx in (cu_context,d_receipt_context,current):
            for k in CONTEXT:
                if type(ctx[k]) is not type(s[k]) or ctx[k]!=s[k]:raise ValueError('ATTACHMENT_CONTEXT_MISMATCH:'+k)
            if set(ctx['binding'])!=set(BINDING) or ctx['binding']!=s['binding']:raise ValueError('A_CURRENT_RESERVATION_BINDING_MISMATCH')
        if current['attachment_snapshot_digest']!=s['snapshot_digest']:raise ValueError('CURRENT_ATTACHMENT_OBSERVATION_CHANGED')
    authority(before);after=deepcopy(latest_owner());authority(after)
    if after!=before:raise ValueError('OWNER_CHANGED_DURING_ATTACHMENT_REVIEW')
    if sha(profile_path)!=profile_sha:raise ValueError('PROFILE_CHANGED_DURING_REVIEW')
    return dict(status='SAME_ATTACHMENT_CONTEXT_REVIEWED_REAL_PROFILE_REFERENCE_ONLY',original_owner_snapshot=s,profile_sha256=profile_sha,
                attachment_digest=s['attachment_digest'],dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False,
                collision_envelope_approved=False,measured_attachment_calibration_approved=False)


def review_attached_planner(folder,latest,*,planned_epoch,snapshot,cu_context,d_receipt_context,profile_path,profile_sha,latest_owner,
                            result_path=None,result_pins=None):
    attachment=review_attachment(snapshot,cu_context,d_receipt_context,profile_path=profile_path,profile_sha=profile_sha,latest_owner=latest_owner)
    request,inputs,envelope,pins=read_bundle(folder);state=inputs['state']
    if {k:request[k] for k in BINDING}!=snapshot['binding'] or request['model_digest']!=snapshot['model_digest']:raise ValueError('OLD_REQUEST_PROFILE_OR_MODEL')
    if request['planning_snapshot']['selected_slot_id']!=snapshot['selected_block_id']:raise ValueError('SELECTED_BLOCK_MISMATCH')
    for k in ('session_id','clock_basis','source_stamp_s','state_sequence','cancel_generation'):
        if state[k]!=snapshot[k]:raise ValueError('PLANNER_STATE_NOT_OWNER_ATTACHMENT:'+k)
    if digest(request['attachment'])!=snapshot['attachment_digest'] or digest(state['attachment_tcp_to_block'])!=snapshot['attachment_digest']:raise ValueError('PLANNER_ATTACHMENT_NOT_OWNER')
    # An old request without an explicit geometry-profile binding cannot acquire a new profile by a sidecar.
    if request.get('held_geometry_profile_sha256')!=profile_sha:raise ValueError('OLD_REQUEST_HAS_NO_NEW_GEOMETRY_PROFILE_BINDING')
    review=PlannerBundleConsumer().consume(folder,latest,planned_epoch=planned_epoch,result_path=result_path,result_pins=result_pins)
    review_attachment(snapshot,cu_context,d_receipt_context,profile_path=profile_path,profile_sha=profile_sha,latest_owner=latest_owner)
    if any(sha(Path(folder)/k)!=v for k,v in pins.items()):raise ValueError('PLANNER_CHANGED_AFTER_ATTACHMENT_REVIEW')
    return dict(status='ATTACHED_INPUT_RESULT_PENDING' if result_path is None else 'ATTACHED_RESULT_REVIEWED_NATIVE_BLOCKED',attachment_review=attachment,
                planner_review=review,dispatch_intent=None,execution_allowed=False,hardware_execution_allowed=False)


def review_incomplete_attachment_bundle(path,expected_sha):
    review=consume_hold_evidence(path,expected_sha256=expected_sha,authority_ref='ATTACHMENT_CONSUMER_COMPLETED_CU_PUBLICATION')
    return dict(status='HOLD_INPUT_EVIDENCE_INCOMPLETE',planner_review=review,attachment_snapshot=None,dispatch_intent=None,
                execution_allowed=False,hardware_execution_allowed=False,new_sdk_fcl_present=False)
