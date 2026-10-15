"""Build/validate a saved-evidence supply catalog. No ROS, camera or motion API."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path

from scipy.spatial.transform import Rotation, Slerp

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT/'robot_control_integration'
GROUPS = [('yellow','2x2x1'),('yellow','2x3x1'),('blue','2x2x1'),('blue','2x3x1'),('red','1x2x1')]
RGBD = {'yellow_2x2x1_04', 'blue_2x3x1_03'}
TAUGHT = {'yellow_2x2x1_02', 'red_1x2x1_01'}
HISTORIC = {'yellow_2x2x1_01', 'yellow_2x2x1_03', 'yellow_2x3x1_03'}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def finite_pose(pose):
    return (isinstance(pose, list) and len(pose)==6
            and all(type(x) in (int,float) and math.isfinite(x) for x in pose))


def interpolated_pose(records, color, kind, slot):
    """Same 1/3/6 XYZ interpolation and ZYZ Slerp as app.robot_teaching."""
    left, right = (slot,slot) if slot in (1,3,6) else ((1,3) if slot<3 else (3,6))
    anchors=[]
    for number in sorted({left,right}):
        key=f'supply/{color}/{kind}/{number}'; row=records[key]
        if (row.get('source')!='READ_ONLY_DEVICE_QUERY' or row.get('operator_confirmed') is not True
                or row.get('receipt',{}).get('physical_commands')!=0
                or (row.get('color'),row.get('brick_type'),row.get('slot_index'))!=(color,kind,number)
                or not finite_pose(row.get('tcp_pose_mm_zyz_deg'))):
            raise ValueError('INVALID_MEASURED_ANCHOR:'+key)
        anchors.append(dict(key=key,pose=row['tcp_pose_mm_zyz_deg']))
    if left==right:return anchors[0]['pose'].copy(),[dict(key=anchors[0]['key'],weight=1.)]
    fraction=(slot-left)/(right-left);a,b=[x['pose'] for x in anchors]
    xyz=[x+fraction*(y-x) for x,y in zip(a[:3],b[:3])]
    abc=Slerp([0.,1.],Rotation.from_euler('ZYZ',[a[3:],b[3:]],degrees=True))([fraction]).as_euler('ZYZ',degrees=True)[0].tolist()
    return xyz+abc,[dict(key=anchors[0]['key'],weight=1-fraction),dict(key=anchors[1]['key'],weight=fraction)]


def build(directory):
    import numpy as np
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    sources = {}
    def evidence(path):
        path = Path(str(path).split('#')[0]).resolve()
        sources[str(path)] = sha256(path.read_bytes()).hexdigest()
        return path
    audit_dir = ROOT/'logs/supply-slot-model/post-red-reconcile-20261015T111258'
    reconciliation = read(evidence(audit_dir/'reference-reconciliation.json'))
    audit = read(evidence(audit_dir/'audit/report.json'))
    layout = read(evidence(audit_dir/'audit/layout.candidate.json'))
    original = read(evidence(NATIVE/'fixtures/teaching_sources/operator_supply.json'))
    write(directory/'layout.json', layout)
    paired = {}
    for sid, folder, run in [
        ('yellow_2x2x1_04','slot4-execution-20261015','supply-rgbd-slot4-trial/1792031150121333215'),
        ('blue_2x3x1_03','T2-slot3-execution-20261015','supply-rgbd-T2-slot3-trial/1792033310942237285')]:
        cfg = read(evidence(NATIVE/'settings/round3_supply_rgbd_20261015'/folder/'config.json'))
        summary = evidence(ROOT/'logs'/run/'trial-summary.json')
        if read(summary).get('operator_exact_grasp_confirmed') is not True or read(summary).get('cleanup_confirmed') is not True:
            raise ValueError('SUCCESSFUL_CLEANED_UP_TRIAL_REQUIRED:'+sid)
        for source, digest in cfg['source_sha256'].items():
            if sha256(evidence(source).read_bytes()).hexdigest() != digest: raise ValueError('SOURCE_CHANGED:'+source)
        paired[sid] = (cfg, read(cfg['vision']['depth_center_profile']), str(summary))
    base = deepcopy(paired['blue_2x3x1_03'][0])
    rows=[]; (directory/'depth').mkdir(); (directory/'single-slot').mkdir()
    for source in reconciliation['slots']:
        sid=source['slot_id']; color, kind, number=sid.split('_'); slot=int(number)
        teaching=deepcopy(source['teaching'])
        modeled, anchors=interpolated_pose(original['records'],color,kind,slot)
        pose=deepcopy(teaching['pose'] if teaching else modeled)
        if teaching: evidence(teaching['source'])
        mode='TEACHING_ONLY' if sid in TAUGHT|HISTORIC else 'RGBD_XY'
        surface=source['observed_surface_center_base_candidate_mm']
        basis='OBSERVED_MODEL_BASELINE_NOT_PAIRED_GROUND_TRUTH'
        trial=None; depth_profile=None
        if sid in paired:
            cfg, profile, trial=paired[sid]; pose=cfg['blocks'][0]['pickup_pose'].copy()
            teaching=dict(pose=pose, source=cfg['blocks'][0]['pose_source'], kind='PAIRED_MEASURED')
            evidence(teaching['source'])
            surface=profile['references'][0]['surface_center_base_mm']
            basis='PAIRED_MEASURED_AND_SINGLE_GRASP_TESTED'
        elif mode=='RGBD_XY':
            samples=next(r for r in audit['slots'] if r['slot_id']==sid)['samples']
            valid=[s for s in samples if s.get('surface_available')]
            if len(valid)!=19: raise ValueError('MODEL_REQUIRES_19_CONSISTENT_OBSERVATIONS:'+sid)
            patch=np.asarray([s['patch_mm'] for s in valid]); points=np.asarray([s['surface_center_base_candidate_mm'] for s in valid])
            profile=deepcopy(paired['blue_2x3x1_03'][1])
            # These are educational operating caps, not measured accuracy certification.
            profile.update(max_shift_mm=1., max_height_error_mm=float(max(2.,np.max(np.abs(points[:,2]-surface[2]))+1.)),
                max_depth_spread_mm=float(np.max(np.ptp(patch.reshape(len(valid),-1),axis=1))+1.),
                depth_range_mm=[float(patch.min()-2.),float(patch.max()+2.)], max_packet_age_ms=310.)
            profile['limit_basis']='MODEL_EDUCATIONAL_CAP_XY_1MM; PATCH_RANGE_PLUS_2MM; SPREAD_PLUS_1MM; HEIGHT_BASELINE_MAX_RESIDUAL_PLUS_1MM_MIN_2MM; NOT_ACCURACY_CERTIFICATION'
        else:
            basis='EXPLICIT_ORIGINAL_OR_UPDATED_TEACHING_NO_DEPTH_CORRECTION'
            if sid=='yellow_2x2x1_02': trial=str(evidence(ROOT/'logs/supply-slot2-reapproach/1792028718726814565/operator-review.json'))
            if sid=='red_1x2x1_01': trial=str(evidence(ROOT/'logs/supply-red-slot1-trial/1792030144985357132/operator-review.json'))
            if sid in HISTORIC:
                evidence(audit_dir/'yellow-2x3-slot3-history-review.json' if sid=='yellow_2x3x1_03' else ROOT.parent/'reports/round3_robot_pc_20261015/remaining-slots-teaching-grasp-review.json')
        if mode=='RGBD_XY':
            profile.update(independently_verified=False, reference_accepted=True,
                layout_sha256=sha256((directory/'layout.json').read_bytes()).hexdigest(),
                references=[dict(slot_id=sid,pickup_pose=pose,surface_center_base_mm=surface)],
                educational_acceptance=dict(scope='APPROVED_EDUCATIONAL_SUPPLY_REGISTRY',operator_accepted=True,
                    evidence_ref=str(directory/'profile.json'), reference_basis=basis), verification_scope=basis)
            depth_profile='depth/'+sid+'.json'; write(directory/depth_profile,profile)
        entry=dict(slot_id=sid,execution_mode=mode,execution_approved=True,
            approval_scope='EDUCATIONAL_CONDITIONAL_SUPPLY_ONLY',reference_basis=basis,
            pickup_pose=pose, pickup_pose_is_measured=teaching is not None,
            teaching_source=teaching, interpolation_anchors=anchors if teaching is None else None,
            baseline_surface_center_base_mm=surface if mode=='RGBD_XY' else None,
            depth_profile=depth_profile,automatic_depth_failure_fallback_enabled=False,
            current_single_grasp_evidence=trial,independently_verified=False,
            all_placements_or_repeatability_verified=False,
            config='single-slot/'+sid+'.json',observation_counts={k:source[k] for k in ('audit_frames','recognized_frames','valid_depth_frames')})
        rows.append(entry)
        cfg=deepcopy(base);cfg.pop('source_sha256',None);cfg.pop('trial_step',None)
        cfg.update(schema_version='educational-supply-single-trial/1',scope='EDUCATIONAL_APPROACH_CLOSE_HOLD_ONLY',
            operator_accepted_t2_educational_profile=False,
            blocks=[dict(color=color,brick_type=kind,slot=slot,span=1 if color=='red' else 2,
                close_mm=20. if color=='red' else 35.,pickup_pose=pose,pose_source=str(directory/'profile.json'),
                pose_basis='MEASURED' if teaching else 'EXISTING_1_3_6_INTERPOLATION_NOT_MEASURED',axis_basis='ORIGINAL_TAUGHT_AXIS')])
        cfg['vision']={k:v for k,v in cfg['vision'].items() if not k.startswith('allow_educational') and k!='depth_center_profile'}
        write(directory/entry['config'],cfg)
    # Freeze data dependencies, not mutable application source files.
    registry=dict(schema_version='educational-supply-execution/1',
        operator_conditional_execution_approved=True,approval_basis='USER_REQUESTED_MODEL_BASED_EDUCATIONAL_EXPANSION_AND_FINAL_EXECUTION_PROFILE_20261015',
        connection={k:base['connection'][k] for k in ('robot_id','tcp','tool')},
        observation_pose=base['observation_pose'],camera_binding=layout['model_binding']['camera'],
        assembly_xy_correction_enabled=False,all_slots_physically_verified=False,
        hardware_revalidation_required_after_team_handoff=True,automatic_device_start=False,
        assembly_completion=False,B_actual_assembly_confirmed=False,final_DB_saved=False,
        slots=rows,source_sha256=sources,
        artifacts_sha256={str(p.relative_to(directory)):sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*.json')})
    write(directory/'profile.json',registry)
    return validate(directory)


def validate(directory):
    import sys
    sys.path.insert(0,str(NATIVE))
    from app.supply_stud.execution_profile import load, bind
    from app.supply_stud.depth_center import load_profile
    from scripts.supply_pick_release_trial import validate_rows, validate_teaching_location
    directory=Path(directory).resolve();registry=load(directory/'profile.json')
    for row in registry['slots']:
        cfg=bind(read(directory/row['config']),directory/'profile.json')
        validate_rows(cfg,cfg['blocks'],require_ready=True)
        validate_teaching_location(cfg,cfg['blocks'][0]['pickup_pose'])
        if row['execution_mode']=='RGBD_XY': load_profile(cfg['vision']['depth_center_profile'],cfg['vision']['layout'],cfg)
        elif cfg['vision'].get('depth_center_profile'): raise ValueError('TEACHING_EXCEPTION_MUST_NOT_USE_DEPTH')
    result=dict(status='OFFLINE_EXECUTION_BINDINGS_VALIDATED',slots=25,RGBD_conditionally_approved=20,
        teaching_only_approved=5,current_RGBD_single_grasp_verified=2,current_teaching_single_grasp_verified=2,
        model_RGBD_without_individual_grasp_verification=18,physical_commands=0,device_connections=0,
        all_slots_physically_verified=False,B_actual_assembly_confirmed=False,final_DB_saved=False)
    write(directory/'validation.json',result)
    return result



def export_portable(source, directory):
    """Copy hash-bound JSON evidence; leave source bytes and raw captures intact."""
    import os
    import shutil
    import sys
    sys.path.insert(0, str(NATIVE))
    from app.supply_stud.execution_profile import load
    source = Path(source).resolve(); directory = Path(directory).resolve()
    registry = load(source/'profile.json')
    directory.mkdir(parents=True, exist_ok=False)
    (directory/'evidence').mkdir()
    mapping = {}; provenance = []
    for index, (name, digest) in enumerate(registry['source_sha256'].items(), 1):
        path = Path(name)
        path = path if path.is_absolute() else source/path
        path = path.resolve()
        relative = f'evidence/{index:02d}-{path.name}'
        shutil.copyfile(path, directory/relative)
        if sha256((directory/relative).read_bytes()).hexdigest() != digest:
            raise ValueError('EXPORTED_EVIDENCE_HASH_MISMATCH:'+name)
        mapping[str(path)] = directory/relative
        origin = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else 'external-reports/'+path.name
        provenance.append(dict(file=relative, original_source=origin, sha256=digest,
            interpretation='BYTE_IDENTICAL_ARCHIVE; NESTED_PATHS_ARE_HISTORICAL_NOT_RUNTIME_DEPENDENCIES'))
    archival_references = []
    def rewrite(value, parent, field=None):
        if isinstance(value, dict): return {k:rewrite(v,parent,k) for k,v in value.items()}
        if isinstance(value, list): return [rewrite(v,parent,field) for v in value]
        if isinstance(value,str) and value.startswith('/') and not value.startswith('/camera/'):
            name, separator, fragment = value.partition('#')
            path = Path(name)
            if str(path) in mapping: target = mapping[str(path)]
            elif path.is_relative_to(source): target = directory/path.relative_to(source)
            else:
                # Capture directories and old ROI draft locators are provenance,
                # not files consumed by the execution loader. Keep that explicit.
                if field not in ('opencv_roi_source','capture_source','capture','quality_audit','candidate_layout'):
                    raise ValueError('UNPACKAGED_ACTIVE_ABSOLUTE_PATH:'+value)
                historical = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else 'external/'+path.name
                archival_references.append(dict(original_source=historical, included=False))
                return 'ARCHIVE_NOT_PACKAGED:'+historical+(separator+fragment if separator else '')
            return os.path.relpath(target,parent)+(separator+fragment if separator else '')
        return value
    for relative in registry['artifacts_sha256']:
        target = directory/relative; target.parent.mkdir(parents=True,exist_ok=True)
        write(target,rewrite(read(source/relative),target.parent))
    layout_digest = sha256((directory/'layout.json').read_bytes()).hexdigest()
    for entry in registry['slots']:
        if entry['depth_profile']:
            profile_path = directory/entry['depth_profile']
            profile = read(profile_path); profile['layout_sha256'] = layout_digest
            write(profile_path,profile)
    value = rewrite({k:v for k,v in registry.items() if k not in ('source_sha256','artifacts_sha256')},directory)
    value['source_path_basis']='BUNDLE_RELATIVE'
    value['source_sha256']={row['file']:row['sha256'] for row in provenance}
    value['packaging_scope']='RELOCATABLE_RUNTIME_WITH_IMMUTABLE_JSON_EVIDENCE_NOT_RAW_REPLAY_DATASET'
    write(directory/'evidence-index.json',dict(byte_identical_sources=provenance,
        archival_references_not_required_at_runtime=archival_references))
    # Native scenario paths are interpreted relative to the checkout, not cwd.
    scenario_source = (source/'scenario.json' if (source/'scenario.json').exists() else
                       NATIVE/'settings/round3_educational_t1_20261015/scenario.json')
    scenario = read(scenario_source)
    (directory/'teaching').mkdir()
    teaching = (source/'teaching/T1-preclose.json' if (source/'teaching/T1-preclose.json').exists() else
                NATIVE/'settings/round3_educational_t1_20261015/slot4-preclose.json')
    shutil.copyfile(teaching,directory/'teaching/T1-preclose.json')
    for case in scenario['steps']:
        if case.get('operator_pickup_file'):
            case['operator_pickup_file']=str((directory/'teaching/T1-preclose.json').relative_to(ROOT))
        if case.get('supply_layout_file'):
            case['supply_layout_file']=str((directory/'layout.json').relative_to(ROOT))
    write(directory/'scenario.json',scenario)
    value['artifacts_sha256']={str(p.relative_to(directory)):sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*.json') if 'evidence' not in p.relative_to(directory).parts}
    write(directory/'profile.json',value)
    return validate(directory)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('build','validate','export'))
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args(argv)
    if args.command == 'export' and args.source is None: parser.error('export requires --source')
    result = (build(args.directory) if args.command=='build' else
              export_portable(args.source,args.directory) if args.command=='export' else validate(args.directory))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
