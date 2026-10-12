from pathlib import Path
import argparse,json,hashlib,math
import numpy as np,yaml
ROOT=Path(__file__).resolve().parents[1]
def load(p):return yaml.load(p.read_text(),Loader=yaml.CSafeLoader)
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();r=a.run_dir.resolve();s=load(r/'status.json');checks=[]
 def check(name,value,evidence=None):checks.append({'name':name,'pass':bool(value),'evidence':evidence})
 row=s['steps'][0];f=r/'S01';m=load(f/'model.json');motion=load(f/'motion.result.json');initial=load(r/'red_supply_initial.actual.json');stock=m['supply']['slots'];red=[v for v in stock if v['color']=='red'];policy=load(ROOT/'config/red_supply.layout.json')
 check('Dedicated red fixture completed',s['success'] and len(s['steps'])==1 and row['block']['brick_type']=='1x2x1' and row['block']['color']=='red' and row['action_mode']=='ROBOT_GRIP')
 check('36 source bodies displayed',len(stock)==36 and len(initial['world_objects'])==39 and len(red)==12 and len({v['slot_id'] for v in stock})==36)
 check('Two columns of six with confirmed gap rule',policy['gap_from_blue_y']==policy['gap_between_red_columns_y']==2 and [v['column_index'] for v in red]==[1]*6+[2]*6 and [v['slot_within_column'] for v in red]==list(range(1,7))*2)
 check('Red small-end face model and pickup',all(v['size_m']==[.016,.032,.019] and v['grasp_contact']=='SMALL_END_SIDE_MIDPOINT' for v in red) and load(r/'whole.result.json')['action_proposals'][0]['grip_axis']=='x')
 check('Native arm control',load(r/'host_status.json')['control_backend']=='isaacsim.ros2.control' and not load(r/'host_status.json')['direct_arm_trajectory_loop'])
 check('Original A endpoints retained',not motion['execution_allowed'] and load(f/'PICKUP_DOWN.request.yaml')['goal']==motion['motion_proposal']['pickup_tcp_pose'] and load(f/'PRE_CONTACT.request.yaml')['goal']==[w['tcp_pose'] for seg in motion['motion_proposal']['segments'] for w in seg['waypoints']][-1]==row['a_wait_goal'])
 check('Actual contact grasp with measured full transform',not s['virtual_grasp_used'] and np.array(load(f/'measured_attachment.json')).shape==(4,4) and row['actual_grasp_follow_error_m_rad'][0]<.005 and row['actual_grasp_follow_error_m_rad'][1]<.15)
 for phase in ('SUPPLY_APPROACH','PICKUP_DOWN','LIFT','TRANSPORT','PRE_CONTACT','EMPTY_RETREAT'):
  d=load(f/(phase+'.result.yaml'));records=d.get('checked_states',[])
  check(phase+' planned/checked/executed',d['plan_success'] and d['execution_success'] and len(records)==d['post_timing_collision_checks']>0 and d['peak_velocity_rad_s']<=.35001 and d['peak_acceleration_rad_s2']<=.70001 and all(np.isfinite(v['q_rad']).all() and np.array(v['tcp_matrix']).shape==(4,4) for v in records))
 held=load(f/'LIFT.result.yaml');check('Held red included in collision scene',held['attached_ids']==['red_1x2x1_01'] and held['world_object_count']==38 and held['attached_object_count']==1 and 'red_1x2x1_01' not in held['world_object_ids'])
 check('Actual destination and holding tolerances',row['tcp_error_m_rad'][0]<.002 and row['tcp_error_m_rad'][1]<math.radians(1) and row['holding_error_m_rad'][0]<.005 and row['holding_error_m_rad'][1]<.15,row['tcp_error_m_rad'])
 check('Nominal20mm wait gap',abs(row['bottom_to_lower_stud_tip_gap_m']-.020)<.002,row['bottom_to_lower_stud_tip_gap_m'])
 sync=load(f/'SCENE_COMMIT_SYNC.result.yaml');check('Mock Current then scene detach',row['mock_current_revision']==1 and s['base_current_revision']==0 and sync['attached_object_count']==0 and sync['world_object_count']==39 and 'Current_0' in sync['world_object_ids'] and 'red_1x2x1_01' not in sync['world_object_ids'] and not s['physical_insertion_executed'])
 records=[]
 for line in (r/'runtime_collisions.jsonl').read_text().splitlines():
  try:records.append(json.loads(line))
  except json.JSONDecodeError:pass
 check('Actual-pose collision guard clean',bool(records) and all(not v['hits'] and not v.get('context_error') for v in records) and not (r/'runtime_guard_failure.json').exists(),{'samples':len(records)})
 hashes=load(ROOT/'fixtures/protected_sources.json');check('Original A input/calibration preserved',all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==d for n,d in hashes.items()))
 check('Supply/lift/wait/final captures',all((r/(name+'.png')).exists() for name in ('red_supply_initial','S01_lift','S01_wait','chair_completed')))
 report={'all_pass':all(v['pass'] for v in checks),'checks':checks,'run':str(r),'a_fixture':'Single red1x2 orientation90 layer1; original chair design preserved separately','red_slots_calculated':12,'red_slots_physically_simulated':1,'source_total':36,'tcp_error_mm':row['tcp_error_m_rad'][0]*1000,'angle_error_deg':math.degrees(row['tcp_error_m_rad'][1]),'gap_mm':row['bottom_to_lower_stud_tip_gap_m']*1000,'physical_insertion':False,'red_real_calibration_verified':False,'real_robot_execution':False,'scenario_wall_s':s['scenario_wall_s']}
 (ROOT/'runtime_reports').mkdir(exist_ok=True)
 (ROOT/'runtime_reports/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(('PASS' if report['all_pass'] else 'FAIL'),sum(v['pass'] for v in checks),'/',len(checks))
 for v in checks:
  if not v['pass']:print(v['name'],v['evidence'])
 if not report['all_pass']:raise SystemExit(1)
if __name__=='__main__':main()
