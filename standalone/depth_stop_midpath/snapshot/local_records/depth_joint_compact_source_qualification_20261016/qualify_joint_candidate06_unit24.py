"""MI orchestration only: original Depth qualifier, actual native_joint, allocated unit20.

Original algorithm, scope thresholds and wrapper files remain unchanged.
"""
from pathlib import Path
import importlib.util, json, sys

ROOT = Path(__file__).resolve().parents[1].parent
sys.path[:0]=[str(ROOT/'work/C-2-moveit'),str(ROOT/'work/C-2-moveit/isaac_sim/scripts')]
from isaac_sim.depth_obstacles.helper_provenance import freeze
# The original qualifier imports Depth at module top level. Prove selected
# Python bytes before that first import, separately from native runtime pins.
QUALIFIER_FIRST_IMPORT = freeze(
    tuple('isaac_sim.depth_obstacles.novel_depth.'+n for n in
          ('interval_kernel','raster_kernel','geometry','qualification','expected_depth','difference','point_bounds','replay_saved'))+
    ('isaac_sim.depth_obstacles.projection',),
    Path(__file__).with_name('qualifier_candidate06_unit24_first_import_source_pins'),
    class_methods={
        'isaac_sim.depth_obstacles.novel_depth.interval_kernel':
            ('IntervalKernel.__init__','IntervalKernel._inputs','IntervalKernel.finish','IntervalKernel.slab_intersection'),
        'isaac_sim.depth_obstacles.novel_depth.raster_kernel':('RasterKernel.__init__','RasterKernel.raster')})
for module_name in ('interval_kernel','raster_kernel','qualification','expected_depth'):
    proof=QUALIFIER_FIRST_IMPORT['isaac_sim.depth_obstacles.novel_depth.'+module_name]
    if proof['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH':
        raise ValueError('QUALIFIER_FIRST_IMPORT_SOURCE_PROOF_REQUIRED:'+module_name)
source = ROOT/'local_records/depth_native11_latency_stage03_20261015/unit01/qualify_native12_v2.py'
spec = importlib.util.spec_from_file_location('original_joint_scope_qualifier', source)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
q.HANDOFF = ROOT/'local_records/moveit_joint_compact_trial_candidate06_20261016/producer_handoff.json'
q.OUT = ROOT/'local_records/depth_joint_compact_source_qualification_20261016/unit24'
q.REPORT = Path(__file__).with_name('unit24_pending_publication.json')

def configure_numerical_kernel(run):
    from isaac_sim.depth_obstacles.novel_depth import expected_depth
    record_path=run/'loaded_runtime_source_pins.json'
    record=q.read(record_path);binding=record['numerical_kernel_binding']
    if binding.get('engine')!='CPP_BBOX_F64':raise ValueError('QUALIFIER_EXPLICIT_CPP_KERNEL_REQUIRED')
    q._pin(binding['manifest']);manifest=q.read(binding['manifest']['path'])
    process=q.read(run/'native_process.json');allocation_ref=dict(path=process['allocation_path'],sha256=process['allocation_sha256']);q._pin(allocation_ref)
    allocation=q.read(allocation_ref['path'])
    if allocation.get('numerical_kernel_manifest')!=binding['manifest'] or manifest['scope']!='EXPLICIT_ISOLATED_SIM_NUMERICAL_TRIAL':raise ValueError('QUALIFIER_ALLOCATION_KERNEL_MISMATCH')
    canonical=ROOT/'work/C-2-moveit/isaac_sim/depth_obstacles/novel_depth'
    if {Path(p['path']).name for p in manifest['files']}!={'expected_depth.py','raster_kernel.py','raster_bbox_f64.cpp','raster_bbox_f64.so'} or len(manifest['files'])!=4:raise ValueError('QUALIFIER_EXACT_KERNEL_FILES_REQUIRED')
    for pin in manifest['files']+[manifest['compile_command'],binding['manifest']]:
        q._pin(pin)
        if record['source_files'].get(pin['path'])!=pin['sha256']:raise ValueError('QUALIFIER_RUNTIME_KERNEL_SOURCE_MISMATCH')
    if any(Path(p['path']).resolve()!=canonical/Path(p['path']).name for p in manifest['files']):raise ValueError('QUALIFIER_CANONICAL_KERNEL_REQUIRED')
    for pin in manifest['files']:
        if Path(pin['path']).suffix=='.py':
            proof=QUALIFIER_FIRST_IMPORT['isaac_sim.depth_obstacles.novel_depth.'+Path(pin['path']).stem]
            if not proof.get('source_pin') or proof['source_pin']['sha256']!=pin['sha256']:
                raise ValueError('QUALIFIER_IMPORTED_SOURCE_SHA_MISMATCH:'+Path(pin['path']).name)
    lib=next(p for p in manifest['files'] if Path(p['path']).suffix=='.so')
    loaded=expected_depth.configure_cpp_raster(lib['path'],lib['sha256'],sim_scope=manifest['scope'])
    actual=dict(engine='CPP_BBOX_F64',load=loaded,manifest=binding['manifest'],source_files=manifest['files'],compile_command=manifest['compile_command'])
    if actual!=binding:raise ValueError('QUALIFIER_RUNTIME_KERNEL_BINDING_MISMATCH')
    return dict(scope='SEPARATE_CPU_QUALIFIER_SAME_CANONICAL_KERNEL',runtime_source_pins=q.ref(record_path),numerical_kernel_binding=actual,configured_before_first_baseline_evaluation=True,SDK_execution=False)

def configure_interval_kernel(run):
    from isaac_sim.depth_obstacles.novel_depth import qualification
    record_path=run/'loaded_runtime_source_pins.json';record=q.read(record_path);binding=record['numerical_interval_kernel_binding']
    if binding.get('engine')!='CPP_INTERVAL_TAIL_F64':raise ValueError('QUALIFIER_EXPLICIT_INTERVAL_KERNEL_REQUIRED')
    q._pin(binding['manifest']);manifest=q.read(binding['manifest']['path'])
    process=q.read(run/'native_process.json');allocation_ref=dict(path=process['allocation_path'],sha256=process['allocation_sha256']);q._pin(allocation_ref)
    allocation=q.read(allocation_ref['path'])
    if allocation.get('interval_kernel_manifest')!=binding['manifest'] or manifest['scope']!='EXPLICIT_ISOLATED_SIM_NUMERICAL_TRIAL':raise ValueError('QUALIFIER_INTERVAL_ALLOCATION_MISMATCH')
    canonical=ROOT/'work/C-2-moveit/isaac_sim/depth_obstacles/novel_depth'
    if len(manifest['files'])!=4 or {Path(p['path']).name for p in manifest['files']}!={'qualification.py','interval_kernel.py','interval_f64.cpp','interval_f64.so'}:raise ValueError('QUALIFIER_INTERVAL_EXACT_FILES_REQUIRED')
    for pin in manifest['files']+[manifest['compile_command'],binding['manifest']]:
        q._pin(pin)
        if record['source_files'].get(pin['path'])!=pin['sha256']:raise ValueError('QUALIFIER_INTERVAL_RUNTIME_SOURCE_MISMATCH')
    if any(Path(p['path']).resolve()!=canonical/Path(p['path']).name for p in manifest['files']):raise ValueError('QUALIFIER_INTERVAL_CANONICAL_SOURCE_REQUIRED')
    for pin in manifest['files']:
        if Path(pin['path']).suffix=='.py':
            proof=QUALIFIER_FIRST_IMPORT['isaac_sim.depth_obstacles.novel_depth.'+Path(pin['path']).stem]
            if not proof.get('source_pin') or proof['source_pin']['sha256']!=pin['sha256']:
                raise ValueError('QUALIFIER_IMPORTED_SOURCE_SHA_MISMATCH:'+Path(pin['path']).name)
    lib=next(p for p in manifest['files'] if Path(p['path']).suffix=='.so')
    loaded=qualification.configure_cpp_intervals(lib['path'],lib['sha256'],sim_scope=manifest['scope'])
    actual=dict(engine='CPP_INTERVAL_TAIL_F64',load=loaded,manifest=binding['manifest'],source_files=manifest['files'],compile_command=manifest['compile_command'])
    if actual!=binding:raise ValueError('QUALIFIER_INTERVAL_KERNEL_BINDING_MISMATCH')
    return dict(scope='SEPARATE_CPU_QUALIFIER_SAME_CANONICAL_INTERVAL_AND_RASTER',runtime_source_pins=q.ref(record_path),numerical_interval_kernel_binding=actual,configured_before_first_baseline_evaluation=True,SDK_execution=False)

def main():
    if not q.HANDOFF.is_file():
        print('WAIT_ACTUAL_NATIVE_JOINT06_SOURCE')
        return False
    h = json.loads(q.HANDOFF.read_bytes())
    if 'actual_native_producer' in h and 'known_map' not in h:
        q._pin(h['actual_native_producer'])
        h = q.read(h['actual_native_producer']['path'])
    previous_units = [ROOT/('local_records/depth_native12_source_qualification_20261015/'+u+'/qualification.json')
                      for u in ('unit01', 'unit02')]
    previous_units.append(ROOT/'local_records/depth_native13_source_qualification_20261015/unit03/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native14_source_qualification_20261015/unit04/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native15_source_qualification_20261015/unit05/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native18_source_qualification_20261015/unit06/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native19_source_qualification_20261015/unit07/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native21_source_qualification_20261015/unit08/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native22_source_qualification_20261015/unit09/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native23_source_qualification_20261015/unit10/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native24_source_qualification_20261015/unit11/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native25_source_qualification_20261015/unit12/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native26_source_qualification_20261015/unit13/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native27_source_qualification_20261015/unit14/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native28_source_qualification_20261015/unit15/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native29_source_qualification_20261015/unit16/qualification.json')
    previous_units.append(ROOT/'local_records/depth_native30_source_qualification_20261016/unit17/qualification.json')
    # Native31 never published a baseline/qualification; no unit18 file exists.
    previous_units.append(ROOT/'local_records/depth_native32_source_qualification_20261016/unit19/qualification.json')
    previous_units.append(ROOT/'local_records/depth_joint_compact_source_qualification_20261016/unit20/qualification.json')
    previous_units.append(ROOT/'local_records/depth_joint_compact_source_qualification_20261016/unit21/qualification.json')
    previous_units.append(ROOT/'local_records/depth_joint_compact_source_qualification_20261016/unit22/qualification.json')
    previous_units.append(ROOT/'local_records/depth_joint_compact_source_qualification_20261016/unit23/qualification.json')
    for previous_path in previous_units:
        if h.get('session_id') in q.read(previous_path)['capture_sessions']:
            print('REJECT_OLD_NATIVE12_13_14_SESSION_SCOPE')
            return False
    run = Path(h.get('run', ''))
    if run.name != 'native_joint06' or not run.resolve().is_relative_to(q.HANDOFF.parent.resolve()):
        print('WAIT_EXPLICIT_ACTUAL_NATIVE_JOINT06_RUN')
        return False
    allocation_path=ROOT/'management/allocations/MI_COORDINATED_JOINT_COMPACT_CANDIDATE06.json'
    allocation=q.read(allocation_path)
    process=q.read(run/'native_process.json')
    if (allocation['run']!=str(run.resolve()) or allocation['qualification_output']!=str(q.OUT.resolve())
            or allocation['new_qualification_required'] is not True or allocation['static_fixture_adapter_adopted'] is not False
            or process['allocation_path']!=str(allocation_path) or process['allocation_sha256']!=q.ref(allocation_path)['sha256']):
        raise ValueError('EXACT_ALLOCATED_NEW_SESSION_QUALIFICATION_REQUIRED')
    if q.np.__version__!='2.5.4':raise ValueError('EXACT_NATIVE_NUMPY_2_5_4_REQUIRED')
    kernel_receipt=configure_numerical_kernel(run)
    q.save(q.HANDOFF.parent/'qualification_kernel_load.json',kernel_receipt)
    interval_receipt=configure_interval_kernel(run)
    q.save(q.HANDOFF.parent/'qualification_interval_kernel_load.json',interval_receipt)
    ready=q.main()
    if ready:
        publication=q.read(q.REPORT)
        if (publication['session_id']!=h['session_id'] or publication['clock_epoch']!=h['clock_epoch']
                or publication['run']!=str(run) or Path(publication['qualification_ref']['path']).parent!=q.OUT):
            raise ValueError('UNIT24_PUBLICATION_BINDING_CHANGED')
        for item in (publication['qualification_ref'],publication['error_model_ref'],publication['scope_review_ref'],publication['pre_baseline_checks_ref']):q._pin(item)
        target=ROOT/'management/reports/depth_native12_source_qualification.json'
        temporary=target.with_name(target.name+'.unit24.tmp')
        with temporary.open('xb') as stream:stream.write(q.REPORT.read_bytes())
        temporary.replace(target)
        print('UNIT24_PUBLIC_POINTER_ATOMICALLY_UPDATED',publication['session_id'])
    return ready

if __name__ == '__main__':
    main()
