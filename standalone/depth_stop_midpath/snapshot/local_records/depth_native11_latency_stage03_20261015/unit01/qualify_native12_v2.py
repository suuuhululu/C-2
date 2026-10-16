"""One-shot new-session pre-obstacle review; never clone an old session scope."""
from pathlib import Path
import sys,json,hashlib,ast,time,datetime
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'work/C-2-moveit'),str(ROOT/'work/C-2-moveit/isaac_sim/scripts')]
import numpy as np
from isaac_sim.depth_obstacles.novel_depth.geometry import freeze_known_geometry,_pin,_digest
from isaac_sim.depth_obstacles.novel_depth.expected_depth import _clock_review,_association_status
from isaac_sim.depth_obstacles.novel_depth.qualification import camera_scope
from isaac_sim.depth_obstacles.novel_depth.replay_saved import evaluate_raw_frame
OUT=ROOT/'local_records/depth_native12_source_qualification_20261015/unit01'
HANDOFF=ROOT/'local_records/moveit_native12_no_lift_same_runtime_20261015/producer_handoff.json'
REPORT=ROOT/'management/reports/depth_native12_source_qualification.json'
def read(p):return json.loads(Path(p).read_text())
def ref(p):
    p=Path(p).resolve();return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(p,j):Path(p).write_text(json.dumps(j,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def wait(fields,reason):
    save(REPORT,dict(schema='depth-native12-source-qualification/1.0',status='WAIT_COMPLETED_PRE_OBSTACLE_SOURCE_HANDOFF',
        updated_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),automation_status='PAUSED',
        qualified_ref=None,error_ref=None,session_id=None,clock_epoch=None,missing_fields=fields,reason=reason,
        expected_handoff=str(HANDOFF),previous_session_substituted=False,CPU_staging_work_continues=True))
    print('WAIT',fields);return False
def main():
    if not HANDOFF.is_file():return wait(['producer_handoff.json'],'No native12 handoff file exists; no session/camera/source refs inferred.')
    try:
        handoff_raw=HANDOFF.read_bytes();h=json.loads(handoff_raw)
    except json.JSONDecodeError:return wait(['completed valid JSON producer_handoff.json'],'Producer JSON is incomplete; not consumed.')
    if 'known_map' not in h:
        canonical=h.get('actual_native_producer')
        if not isinstance(canonical,dict) or not {'path','sha256'}<=canonical.keys():
            return wait(['canonical actual_native_producer pin with session/epoch/run/known_map/frames'],'Wrapper has no canonical pinned producer.')
        _pin(canonical);handoff_raw=Path(canonical['path']).read_bytes();h=json.loads(handoff_raw)
    if not all(k in h for k in ('session_id','clock_epoch','run','known_map','frames')):
        return wait(['session_id','clock_epoch','run','known_map','frames'],'Canonical producer fields missing.')
    run=Path(h['run'])
    if not run.resolve().is_relative_to(HANDOFF.parent.resolve()):
        return wait(['native12 actual run directory under native12 producer root'],'Old run path cannot be substituted.')
    prior10=ROOT/'local_records/depth_native10_source_qualification_20261015/unit02/qualification.json'
    if h['session_id'] in read(prior10)['capture_sessions']:
        return wait(['independent native12 session_id'],'Native10 session explicitly rejected.')
    if h['session_id'] in read(ROOT/'local_records/depth_native11_source_qualification_20261015/unit01/qualification.json')['capture_sessions']:
        return wait(['independent native12 session_id'],'Native11 session explicitly rejected.')
    pre_path=run/'pre_obstacle_handoff.json'
    if not pre_path.is_file():return wait(['pre_obstacle_handoff.json'],'Original pre-obstacle handoff not yet published.')
    pre=read(pre_path)
    if (pre.get('new_unknown_actor_created') is not False or pre.get('scope')!='NEW_SESSION_ACTUAL_PRE_OBSTACLE_BASELINE' or
            pre.get('session_id')!=h['session_id'] or pre.get('clock_epoch')!=h['clock_epoch'] or pre.get('known_map')!=h['known_map']):
        return wait(['coherent explicit pre-obstacle session/epoch/map and new_unknown_actor_created=false'],'Pre-obstacle provenance mismatch; no old session substituted.')
    if not pre.get('frames'):return wait(['completed pre-obstacle frames'],'No completed pre-obstacle raw frame available.')
    if OUT.exists():
        if REPORT.is_file():
            published=read(REPORT)
            if (published.get('status')=='SCOPED_PRE_OBSTACLE_QUALIFICATION_READY' and
                    published.get('session_id')==h['session_id'] and published.get('clock_epoch')==h['clock_epoch']):
                for pin in (published['qualified_ref'],published['error_ref']):_pin(pin)
                for pin in read(published['qualified_ref']['path'])['source_refs']:_pin(pin)
                print('Same exact session ready; immutable existing publication retained');return True
        return wait(['new clean qualification output unit after prior incomplete review'],'Existing output retained for audit; not overwritten.')
    k=pre['known_map']
    for name in ('map_snapshot','held_definition','approved_static_ids','source_refs'):_pin(k[name])
    known=freeze_known_geometry(read(k['map_snapshot']['path']),k['model_bundle'],read(k['held_definition']['path']),
        read(k['approved_static_ids']['path'])['approved_static_ids'],read(k['source_refs']['path']))
    if known['metadata']['map_scope']!='PRE_OBSTACLE_APPROVED':return wait(['PRE_OBSTACLE_APPROVED map'],'Wrong map scope.')
    if known['metadata']['session_id']!=h['session_id'] or known['metadata']['clock_epoch']!=h['clock_epoch']:
        return wait(['map session/epoch bound to actual native12'],'Map identity mismatch.')
    prior_run=ROOT/'local_records/moveit_native09_unlabelled_static_shadow_20261015/native09_corrective02'
    previous=read(ROOT/'local_records/depth_native09_static_shadow_20261015/unit01/native09_pre_scope/qualification.json')
    if h['session_id'] in previous['capture_sessions']:return wait(['independent new native12 session_id'],'Old session explicitly rejected.')
    if (set(known['metadata']['approved_static_ids'])!=set(read(prior_run/'known_depth_map/approved_static_ids.json')['approved_static_ids']) or
            read(k['held_definition']['path'])!=read(prior_run/'known_depth_map/held_definition.json')):
        return wait(['reviewed known STATIC roster and held definition'],'Known-map structure changed; independent scope review required.')
    if known['metadata']['model_manifest_sha256']!=previous['model_manifest_sha256']:
        return wait(['reviewed model manifest'],'Model changed; no old geometry qualification applied.')
    profile=read(run/'baseline_camera_profile.json')['profile']
    if profile!=read(prior_run/'baseline_camera_profile.json')['profile']:
        return wait(['unchanged reviewed camera profile'],'Camera profile changed.')
    def calls(path,name):
        return [ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,ast.Call) and ast.unparse(n.func)==name]
    route={}
    for name in ('RtxCamera','CameraSensor','UsdGeom.Camera.Define','camera.AddTransformOp','camera.CreateClippingRangeAttr','self.writer.attach'):
        a,b=[calls(p/'loaded_sources/baseline_camera.py',name) for p in (prior_run,run)]
        if not a or a!=b:return wait(['original camera/render route '+name],'Nonempty original route AST mismatch.')
        route[name]=dict(count=len(a),exact_AST_equal=True)
    selected=[]
    for row in pre['frames'][:3]:
        pin=row.get('frame_input')
        if not pin:return wait(['completed pre frame_input pin'],'No canonical raw-frame pin.')
        _pin(pin);f=read(pin['path']);raw=Path(pin['path']).parent
        if not raw.resolve().is_relative_to(run.resolve()):
            return wait(['original frame under actual native12 run'],'Old raw-frame path explicitly rejected.')
        if (f['session_id']!=h['session_id'] or f['clock_epoch']!=h['clock_epoch'] or camera_scope(f)!=previous['camera_scope']):
            return wait(['coherent actual frame camera/session/epoch scope'],'New original frame scope mismatch.')
        clock=_clock_review(f)
        if _association_status(f,clock_review=clock)!='ACTUAL_SOURCE_TICK':return wait(['independent native actual source proof'],'Source association missing.')
        if np.load(raw/'depth.npy',allow_pickle=False).dtype!=np.float32:return wait(['original float32 optical Z'],'Unsupported depth storage.')
        receipt=read(raw/'receipt.json')
        selected.append(dict(frame_seq=f['frame_seq'],frame_ref=pin,raw_depth_ref=ref(raw/'depth.npy'),raw_folder=str(raw),
            camera_scope=camera_scope(f),camera_path=receipt['camera_path'],source_clock_review=clock))
    if len({s['camera_path'] for s in selected})!=1:return wait(['one original camera_path'],'Selected pre cameras differ.')
    OUT.mkdir(parents=True,exist_ok=False)
    (OUT/'input_producer_handoff_snapshot.json').write_bytes(handoff_raw)
    save(OUT/'input_pre_handoff_snapshot.json',pre)
    review=dict(session_id=h['session_id'],clock_epoch=h['clock_epoch'],map_refs=k,selected=selected,route=route,
        pre_obstacle_handoff_ref=ref(pre_path),original_handoff_ref=ref(OUT/'input_producer_handoff_snapshot.json'),
        original_producer_handoff_path=str(HANDOFF),pre_only=True,
        post_actor_pixels_or_trigger_used=False,old_session_scope_copied=False,
        camera_profile_exact=True,camera_scope_exact=True,known_STATIC_roster_exact=True)
    save(OUT/'scope_review.json',review)
    sources=[ref(OUT/'scope_review.json'),ref(pre_path),ref(run/'baseline_camera_profile.json'),ref(run/'loaded_sources/baseline_camera.py'),ref(run/'loaded_runtime_source_pins.json')]
    sources += [k[n] for n in ('map_snapshot','held_definition','approved_static_ids','source_refs')]
    # Fresh schema built from new native12 inputs. Prior evidence is only a
    # route/model comparison; no previous session allowlist/body is copied.
    q=dict(schema='depth-scoped-qualification/1.0',scope='SIM_TEST_REPORT_ONLY',offset_uv=[.5,.5],
        camera_scope=selected[0]['camera_scope'],camera_path=selected[0]['camera_path'],capture_sessions=[h['session_id']],
        model_manifest_sha256=known['metadata']['model_manifest_sha256'],numerical_model='FLOAT32_AFFINE_DOT_ROUNDING_TRIAL',
        same_face_footprint_px=5,source_refs=sources,applicable_surface='STATIC_AND_HELD_SAME_BOX_FACE_FULL_5X5_GEOMETRY_ONLY',
        unsupported=['SELF mesh bound','edge/occlusion ambiguous pixels','actual sensor/ray/aggregate TF point error'],
        official_observation='REPORT_ONLY',future_guarantee=False,threshold_fitted_to_observed_max=False,
        independent_validation_selection=[s['frame_seq'] for s in selected],validation_scope='NEW_NATIVE12_PRE_OBSTACLE_ONLY')
    save(OUT/'qualification.json',q)
    error=dict(status='SIM_SCOPED_NUMERICAL_MODEL',expected_error_m=None,depth_error_m=None,point_error_m=None,
        point_bound_semantics=None,official_observation_status='OFFICIAL_NOT_DEFINED',official_tolerance_m=None,
        decision='REPORT_ONLY',qualification_ref=ref(OUT/'qualification.json'),source_refs=sources)
    save(OUT/'error_model.json',error)
    limits=read(ROOT/'local_records/depth_native07_qualification_20261015/unit01/limits.json');checks=[]
    for s in selected:
        f=read(s['frame_ref']['path']);t=time.perf_counter()
        item=evaluate_raw_frame(s['raw_folder'],known,error,limits,now_source_s=f['received_stamp_s'])
        if item['guard']:return wait(['passing original-receipt pre-obstacle source guard'],'CPU baseline guard; original raw retained.')
        counts=item['detection']['counts'];checks.append(dict(source_frame_ref=s['frame_ref'],counts=counts,CPU_wall_s=time.perf_counter()-t,
            scope='OFFLINE_ORIGINAL_RECEIPT_REPLAY_NOT_LIVE_COMPLETION'))
        if counts['foreground']!=0 or counts['matched_static']==0:
            save(OUT/'pre_baseline_checks.json',checks)
            return wait(['zero foreground and nonempty known STATIC supported baseline'],'Pre test did not support existing trial; no tuning or threshold change.')
    save(OUT/'pre_baseline_checks.json',checks)
    publication=dict(schema='depth-native12-source-qualification/1.0',status='SCOPED_PRE_OBSTACLE_QUALIFICATION_READY',automation_status='PAUSED',
        session_id=h['session_id'],clock_epoch=h['clock_epoch'],run=str(run),qualified_ref=ref(OUT/'qualification.json'),
        qualification_ref=ref(OUT/'qualification.json'),error_ref=ref(OUT/'error_model.json'),error_model_ref=ref(OUT/'error_model.json'),
        scope_review_ref=ref(OUT/'scope_review.json'),pre_baseline_checks_ref=ref(OUT/'pre_baseline_checks.json'),
        previous_session_substituted=False,old_session_scope_copied=False,staged_patch_active=True,
        point_error_m=None,official_tolerance_m=None,observation='REPORT_ONLY',risk_qualified=False,stop_intent=False,
        source_clock_retimed=False,execution_allowed=False,world_clear_allowed=False,
        consumer_example_ref=ref(ROOT/'local_records/depth_native11_latency_stage03_20261015/unit01/native12_consumer_example.py'),
        display_contract_ref=ref(ROOT/'management/reports/depth_detection_mask_display_handoff.json'))
    save(OUT/'publication.json',publication);save(REPORT,publication);print('READY',publication['qualified_ref']);return True
if __name__=='__main__':main()
