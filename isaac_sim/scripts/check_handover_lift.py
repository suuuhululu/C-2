"""Verify the two handover regressions separately from the full chair run."""
from pathlib import Path
import argparse,json,hashlib,math
import yaml,numpy as np
ROOT=Path(__file__).resolve().parents[1]
def load(p):return yaml.load(p.read_text(),Loader=yaml.CSafeLoader)
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();run=a.run_dir.resolve();s=load(run/'status.json');seed=load(run/'fixture_seed.json');checks=[]
 def check(name,value,evidence=None):checks.append({'name':name,'pass':bool(value),'evidence':evidence})
 check('Only S11/S12 newly executed; prefix explicitly seeded',s.get('success') and len(s['steps'])==2 and [v['step_id'] for v in s['steps']]==['S11','S12'] and seed['start_index']==10 and seed['kind']=='MOCK_CURRENT_PREFIX_SEEDED_NOT_EXECUTED_IN_THIS_RUN')
 check('Baseline and Plan retained',s['base_current_revision']==0 and load(run/'whole.result.json')['planning_result']['plan']['plan_id']==s['plan_id']==load(Path(seed['source_run'])/'status.json')['plan_id'])
 check('100mm selected policy',load(ROOT/'config/transport.sim.json')['manual_source_lift_m']==.1)
 for i,row in enumerate(s['steps'],10):
  sid=row['step_id'];f=run/sid;motion=load(f/'motion.result.json');policy=load(f/'manual_lift_policy.json');lift=load(f/'LIFT.request.yaml')['goal'];pick=motion['motion_proposal']['pickup_tcp_pose'];dest=[w['tcp_pose'] for seg in motion['motion_proposal']['segments'] for w in seg['waypoints']][-1]
  check(sid+' exact relative 100mm lift command',abs(lift['xyz_m'][2]-pick['xyz_m'][2]-.100)<1e-9 and lift['xyz_m'][:2]==pick['xyz_m'][:2] and lift['quaternion_xyzw']==pick['quaternion_xyzw'] and policy['relative_rise_m']==.1 and policy['sim_lift']==lift)
  measured=load(f/'LIFT.actual.json')['tcp_pose']['xyz_m'][2]-load(f/'CLOSE_GRIPPER.actual.json')['tcp_pose']['xyz_m'][2]
  check(sid+' actual rise near 100mm',abs(measured-.1)<.002,{'rise_mm':measured*1000})
  check(sid+' A pickup/handover unchanged',load(f/'PICKUP_DOWN.request.yaml')['goal']==pick and load(f/'PRE_CONTACT.request.yaml')['goal']==dest==row['a_wait_goal'] and row['destination']=='HANDOVER_TRAY' and not motion['execution_allowed'])
  for phase in ('SUPPLY_APPROACH','PICKUP_DOWN','LIFT','TRANSPORT','PRE_CONTACT','EMPTY_RETREAT'):
   d=load(f/(phase+'.result.yaml'));records=d.get('checked_states',[])
   check(sid+' '+phase+' checked execution',d.get('execution_success') and d.get('plan_success') and len(records)==d.get('post_timing_collision_checks',0)>0 and d['peak_velocity_rad_s']<=.35001 and d['peak_acceleration_rad_s2']<=.70001 and all(np.array(v['q_rad']).shape==(6,) and np.isfinite(v['q_rad']).all() for v in records))
  d=load(f/'LIFT.result.yaml');check(sid+' held block and Current represented',d['attached_ids']==[row['slot_id']] and {'Current_'+str(n) for n in range(i)}<=set(d['world_object_ids']) and d['attached_object_count']==1)
  check(sid+' actual contact grasp and stopped destination',row['holding_error_m_rad'][0]<=.005 and row['holding_error_m_rad'][1]<=.15 and row['tcp_error_m_rad'][0]<=.002 and row['tcp_error_m_rad'][1]<=math.radians(1) and load(f/'PRE_CONTACT.actual.json')['observed_stopped'])
  h=load(f/'MANUAL_ASSEMBLY_DONE.hmi.json');sync=load(f/'HUMAN_CURRENT_SYNC.result.yaml');check(sid+' mock human boundary and scene commit',h['request']['current_revision']==i and h['response']['source']=='AUTO_MOCK_RESPONSE' and row['mock_current_revision']==i+1 and sync['attached_object_count']==0 and 'Current_'+str(i) in sync['world_object_ids'] and row['slot_id'] not in sync['world_object_ids'])
  check(sid+' capture evidence',all((run/(sid+'_'+x+'.png')).exists() for x in ('lift','wait','tray_delivered','assembled')))
 collisions=[]
 for line in (run/'runtime_collisions.jsonl').read_text().splitlines():
  try:collisions.append(json.loads(line))
  except json.JSONDecodeError:pass
 check('Actual-pose guard clean',bool(collisions) and all(not v['hits'] and not v.get('context_error') for v in collisions) and not (run/'runtime_guard_failure.json').exists(),{'samples':len(collisions)})
 hashes=load(ROOT/'fixtures/protected_sources.json');check('Original A preserved',all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==d for n,d in hashes.items()))
 check('Final mock Current12; physical assembly not claimed',s['mock_current']['current_revision']==12 and len(s['mock_current']['blocks'])==12 and not s['physical_insertion_executed'] and not s['real_B_observation'] and not s['real_human_help_verified'])
 report={'all_pass':all(c['pass'] for c in checks),'checks':checks,'run':str(run),'newly_executed_steps':['S11','S12'],'seeded_prefix_count':10,'selected_lift_m':.1,'physical_insertion':False,'real_human_completion':False,'wall_s':s.get('scenario_wall_s')}
 (ROOT/'runtime_reports').mkdir(exist_ok=True)
 (ROOT/'runtime_reports/handover_100mm_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(('PASS' if report['all_pass'] else 'FAIL'),sum(c['pass'] for c in checks),'/',len(checks))
 for c in checks:
  if not c['pass']:print(c['name'],c['evidence'])
 if not report['all_pass']:raise SystemExit(1)
if __name__=='__main__':main()
