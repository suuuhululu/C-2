"""Exactly one original baseline2 qualification; pending output only."""
from pathlib import Path
import ast,hashlib,json,os,sys,types

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main(session):
 session=Path(session).resolve();ctx=read(session/'context.json');root=Path(ctx['root']);run=Path(ctx['run'])
 marker=read(session/'qualification_once.json');pre=read(run/'pre_obstacle_handoff.json')
 if marker['nonce']!=ctx['session_nonce'] or marker['session_id']!=pre['session_id'] or len(pre['frames'])!=2:raise ValueError('QUALIFIER_DISPATCH_SESSION_BASELINE2_MISMATCH')
 if sha(session/'qualifier_source_handoff.json')!=marker['pre_handoff']['sha256'] or sha(run/'pre_obstacle_handoff.json')!=marker['pre_handoff']['sha256']:raise ValueError('BASELINE2_CHANGED_AFTER_DISPATCH')
 if not Path('/proc/'+str(ctx['native_pid'])).exists():raise ValueError('NATIVE_PARENT_NOT_ALIVE')
 if Path('/proc/'+str(ctx['native_pid'])+'/stat').read_text().split()[21]!=ctx['native_startticks']:raise ValueError('NATIVE_PARENT_PID_REUSED')
 if ctx['session_nonce']!=os.environ.get('DEPTH_STOP_SESSION_NONCE'):raise ValueError('QUALIFIER_SESSION_NONCE_MISMATCH')
 process=read(run/'native_process.json')
 if process['allocation_path']!=str(session/'context.json') or process['allocation_sha256']!=sha(session/'context.json'):raise ValueError('EXACT_CURRENT_NATIVE_CONTEXT_REQUIRED')
 sys.path[:0]=[str(root/'work/C-2-moveit'),str(root/'work/C-2-moveit/isaac_sim/scripts')]
 from isaac_sim.depth_obstacles.helper_provenance import freeze
 names=tuple('isaac_sim.depth_obstacles.novel_depth.'+n for n in ('interval_kernel','raster_kernel','geometry','qualification','expected_depth','difference','point_bounds','replay_saved'))+('isaac_sim.depth_obstacles.projection',)
 proofs=freeze(names,session/'qualifier_first_import_source_pins',class_methods={'isaac_sim.depth_obstacles.novel_depth.interval_kernel':('IntervalKernel.__init__','IntervalKernel._inputs','IntervalKernel.finish','IntervalKernel.slab_intersection'),'isaac_sim.depth_obstacles.novel_depth.raster_kernel':('RasterKernel.__init__','RasterKernel.raster')})
 if any(p['status']!='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' for p in proofs.values()):raise ValueError('QUALIFIER_FIRST_IMPORT_PROOF_REQUIRED')
 original=root/'local_records/depth_native11_latency_stage03_20261015/unit01/qualify_native12_v2.py'
 raw=original.read_text();assert raw.count("pre['frames'][:3]")==1
 raw=raw.replace("pre['frames'][:3]","pre['frames'][:2]")
 q=types.ModuleType('standalone_original_qualifier');q.__file__=str(original);sys.modules[q.__name__]=q
 q_code=compile(raw,str(original),'exec',dont_inherit=True,optimize=sys.flags.optimize)
 exec(q_code,q.__dict__)
 q.ROOT=root;q.HANDOFF=session/'qualifier_source_handoff.json';q.OUT=session/'qualification';q.REPORT=session/'qualification_pending.json'
 # Reuse the exact historical compiled kernel configuration functions only.
 wrapper=root/'local_records/depth_joint_compact_source_qualification_20261016/qualify_joint_candidate06_unit24.py'
 tree=ast.parse(wrapper.read_text());functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('configure_numerical_kernel','configure_interval_kernel')]
 assert len(functions)==2
 env=dict(ROOT=root,q=q,Path=Path,QUALIFIER_FIRST_IMPORT=proofs)
 config_code=compile(ast.Module(body=functions,type_ignores=[]),str(wrapper),'exec',dont_inherit=True,optimize=sys.flags.optimize)
 exec(config_code,env)
 q_expected={c.co_name:c for c in q_code.co_consts if isinstance(c,types.CodeType)}
 q_functions={name:value for name,value in vars(q).items() if isinstance(value,types.FunctionType) and value.__module__==q.__name__}
 config_expected={c.co_name:c for c in config_code.co_consts if isinstance(c,types.CodeType)}
 q_bound=bool(q_functions) and all(f.__code__ is q_expected.get(name) for name,f in q_functions.items())
 config_bound=all(env[name].__code__ is config_expected.get(name) for name in ('configure_numerical_kernel','configure_interval_kernel'))
 if not q_bound or not config_bound:raise ValueError('QUALIFIER_EXECUTED_CODE_SOURCE_BINDING_REQUIRED')
 def ref(path):return dict(path=str(Path(path).resolve()),sha256=sha(path))
 binding=dict(schema='standalone-qualifier-executed-code-binding/1',status='SELECTED_BYTES_FUNCTION_CODE_IDENTITY_VERIFIED_BEFORE_NUMERICAL_CALL',
     original_q_source=ref(original),original_configurators_source=ref(wrapper),q_source_selected_sha256=hashlib.sha256(raw.encode()).hexdigest(),
     only_q_compile_transform="pre['frames'][:3] -> pre['frames'][:2]",q_defined_functions=sorted(q_functions),
     q_code_identity_verified=q_bound,configurator_code_identity_verified=config_bound,
     native_adapter_first_import=ref(session/'native_adapter_first_import_pins/result.json'),worker_first_import=ref(session/'worker_adapter_first_import_pins/result.json'),dependency_first_import=ref(session/'qualifier_first_import_source_pins/result.json'),
     numerical_calls_before_binding=0,session_id=pre['session_id'],clock_epoch=pre['clock_epoch'])
 with (session/'qualifier_executed_source_binding.json').open('x') as f:json.dump(binding,f,indent=2);f.write('\n')
 if q.np.__version__!='2.5.4':raise ValueError('EXACT_NATIVE_NUMPY_2_5_4_REQUIRED')
 q.save(session/'qualification_kernel_load.json',env['configure_numerical_kernel'](run))
 q.save(session/'qualification_interval_kernel_load.json',env['configure_interval_kernel'](run))
 if sha(original)!=binding['original_q_source']['sha256'] or sha(wrapper)!=binding['original_configurators_source']['sha256']:raise ValueError('QUALIFIER_SOURCE_CHANGED_BEFORE_MAIN')
 if not q.main():raise ValueError('QUALIFICATION_NOT_READY_NO_RETRY')
 print('FRESH_BASELINE2_PENDING_READY',pre['session_id'])
if __name__=='__main__':main(sys.argv[1])
