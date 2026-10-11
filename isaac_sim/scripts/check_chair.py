"""Audit saved A lineage, native execution, scene commits, and mock boundaries."""
from pathlib import Path
import argparse,json,hashlib,math,xml.etree.ElementTree as ET
import yaml,numpy as np
from ament_index_python.packages import get_package_share_directory
from sim_utils import pose_matrix,error
ROOT=Path(__file__).resolve().parents[1]
def load(p):return yaml.load(p.read_text(),Loader=yaml.CSafeLoader)
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);args=p.parse_args();run=args.run_dir.resolve()
 status=load(run/'status.json');whole=load(run/'whole.request.json');result=load(run/'whole.result.json');checks=[]
 def check(name,ok,evidence=None):checks.append({'name':name,'pass':bool(ok),'evidence':evidence})
 plan=result['planning_result']['plan'];steps=status['steps'];host=load(run/'host_status.json')
 check('All design blocks completed',status.get('success') and len(steps)==len(plan['steps'])==len(whole['design']['blocks'])==12)
 check('Native controller ownership',host['control_backend']=='isaacsim.ros2.control' and not host['direct_arm_trajectory_loop'])
 check('Mock boundary explicitly separated',not status['physical_insertion_executed'] and not status['physical_release_verified'] and not status['real_B_observation'] and not status['real_human_help_verified'] and not status['virtual_grasp_used'])
 check('Original baseline preserved',status['base_current_revision']==whole['current']['current_revision']==0 and status['plan_id']==plan['plan_id'])
 check('Unique supply slots consumed',len({s['slot_id'] for s in steps})==len(steps))
 check('Planned modes retained',sum(s['action_mode']=='ROBOT_GRIP' for s in steps)==10 and sum(s['action_mode']=='HUMAN_ASSEMBLY' for s in steps)==2)
 completed_slots=set()
 for i,row in enumerate(steps):
  sid=row['step_id'];folder=run/sid;motion=load(folder/'motion.result.json');request=load(folder/'motion.request.json');reassess=load(folder/'reassessment.request.json')
  check(sid+' A lineage',row['block']==plan['steps'][i]['after'] and not motion['execution_allowed'] and request['context']['plan_id']==plan['plan_id'] and reassess['plan_base_current']==whole['current'] and request['latest_current']['current_revision']==i)
  check(sid+' actual endpoints retained',load(folder/'PICKUP_DOWN.request.yaml')['goal']==motion['motion_proposal']['pickup_tcp_pose'] and load(folder/'PRE_CONTACT.request.yaml')['goal']==[w for segment in motion['motion_proposal']['segments'] for w in segment['waypoints']][-1]['tcp_pose']==row['a_wait_goal'])
  check(sid+' measured full grasp',np.array(load(folder/'measured_attachment.json')).shape==(4,4) and row['actual_grasp_follow_error_m_rad'][0]<.005 and row['actual_grasp_follow_error_m_rad'][1]<.15)
  check(sid+' measured wait/hold',row['tcp_error_m_rad'][0]<=.002 and row['tcp_error_m_rad'][1]<=math.radians(1) and row['holding_error_m_rad'][0]<=.005 and row['holding_error_m_rad'][1]<=.15,row['tcp_error_m_rad'])
  for phase in ('SUPPLY_APPROACH','PICKUP_DOWN','LIFT','TRANSPORT','PRE_CONTACT','EMPTY_RETREAT'):
   d=load(folder/(phase+'.result.yaml'));records=d.get('checked_states',[])
   check(sid+' '+phase+' checked native execution',d.get('plan_success') and d.get('execution_success') and len(records)==d.get('post_timing_collision_checks',0)>0 and d['peak_velocity_rad_s']<=.35001 and d['peak_acceleration_rad_s2']<=.70001 and all(np.array(r['q_rad']).shape==(6,) and np.array(r['tcp_matrix']).shape==(4,4) and np.isfinite(r['q_rad']).all() for r in records))
  lift=load(folder/'LIFT.result.yaml');world=set(lift['world_object_ids'])
  check(sid+' Current and held block registered',lift['attached_object_count']==1 and lift['attached_ids']==[row['slot_id']] and row['slot_id'] not in world and {'SupplySurface','AssemblySurface','HandoverTray'}|{'Current_'+str(n) for n in range(i)}<=world and sorted(lift['touch_links'])==['rg2_left_inner_finger','rg2_right_inner_finger'])
  completed_slots.add(row['slot_id']);sync=load(folder/('HUMAN_CURRENT_SYNC.result.yaml' if row['action_mode']=='HUMAN_ASSEMBLY' else 'SCENE_COMMIT_SYNC.result.yaml'));world=set(sync['world_object_ids'])
  check(sid+' detach and Current commit',sync['scene_sync_success'] and sync['attached_object_count']==0 and not completed_slots&world and {'Current_'+str(n) for n in range(i+1)}<=world and len(world)==27)
  check(sid+' revision advances once',row['input_current_revision']==i and row['mock_current_revision']==i+1 and row['plan_base_current']==whole['current'] and not row['physical_insertion'] and not row['real_B_observation'])
  actual=load(folder/('HUMAN_CURRENT_SYNC.actual.json' if row['action_mode']=='HUMAN_ASSEMBLY' else 'OPEN_RESET.actual.json'));body=next(v for v in actual['world_objects'] if v['id']=='Current_'+str(i));target=load(folder/'model.json')['target_model']
  check(sid+' committed USD position matches Current model',np.linalg.norm(np.array(body['pose']['xyz_m'])-target['centre_m'])<1e-6)
  check(sid+' empty gripper reset',abs(load(folder/'OPEN_RESET.actual.json')['grip_rad']+.4)<.02)
  if row.get('lift_intermediate_override'):
   rejected=load(folder/'LIFT_A_candidate_rejected/LIFT.result.yaml');override=row['lift_intermediate_override']
   check(sid+' failed high lift not executed and clearance fallback recorded',not rejected.get('execution_issued') and not rejected.get('execution_success') and rejected['cartesian_fraction']<1 and override['sim_clearance_lift']['xyz_m'][2]<override['original_a_lift']['xyz_m'][2] and load(folder/'LIFT.request.yaml')['goal']==override['sim_clearance_lift'])
  if row['action_mode']=='HUMAN_ASSEMBLY':
   opening=load(folder/'OPEN_RESET.actual.json');policy=row.get('tray_open_at_wait',{})
   pe,re=error(pose_matrix(opening['tcp_pose']),pose_matrix(row['a_wait_goal']))
   check(sid+' open at tray wait before arm retreat',policy.get('policy')=='OPEN_AT_REACHED_TRAY_TCP_BEFORE_ARM_RETREAT' and policy.get('physical_drop_verified') is False and pe<=.002 and re<=math.radians(1) and (folder/'tray_open_at_wait.json').exists())
   h=load(folder/'MANUAL_ASSEMBLY_DONE.hmi.json');keys=('request_id','kind','plan_id','step_id','current_revision')
   check(sid+' handover and bound human mock response',row['destination']=='HANDOVER_TRAY' and row['tray_mock_release'] and all(h['request'][k]==h['response'][k] for k in keys) and h['request']['current_revision']==i and h['response']['source'] in ('AUTO_MOCK_RESPONSE','USER_MOCK_CONFIRMATION') and (run/(sid+'_tray_delivered.png')).exists())
  else:
   check(sid+' nominal wait gap',abs(row['bottom_to_lower_stud_tip_gap_m']-.020)<=.002,row['bottom_to_lower_stud_tip_gap_m'])
  check(sid+' captures',(run/(sid+'_wait.png')).exists() and (run/(sid+'_assembled.png')).exists())
 current=status.get('mock_current',{'blocks':[],'current_revision':-1});canon=lambda b:json.dumps(b,sort_keys=True)
 check('Final mock Current equals Design',current['current_revision']==12 and sorted(map(canon,current['blocks']))==sorted(map(canon,whole['design']['blocks'])))
 collisions=[]
 for line in (run/'runtime_collisions.jsonl').read_text().splitlines():
  try:collisions.append(json.loads(line))
  except json.JSONDecodeError:pass
 check('Actual pose collision guard clean',bool(collisions) and all(not r['hits'] and not r.get('context_error') and r['holding_drift_m_rad'][0]<=.005 and r['holding_drift_m_rad'][1]<=.15 for r in collisions) and not (run/'runtime_guard_failure.json').exists(),{'samples':len(collisions)})
 hashes=load(ROOT/'fixtures/protected_sources.json');changed=[name for name,digest in hashes.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
 check('Original A preserved',not changed,changed)
 report={'all_pass':all(c['pass'] for c in checks),'checks':checks,'run':str(run),'isaac_version':host.get('isaac_version','UNAVAILABLE'),'moveit_version':ET.parse(Path(get_package_share_directory('moveit_core'))/'package.xml').getroot().findtext('version'),'physical_fit_verified':False,'real_human_access_verified':False,'continuous_swept_collision_proof':False,'runtime_sampling_sim_s':.1,'post_timing_joint_interval_rad':.001,'completed_count':len(steps),'scenario_wall_s':status.get('scenario_wall_s')}
 (ROOT/'runtime_reports').mkdir(exist_ok=True)
 (ROOT/'runtime_reports/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(('PASS' if report['all_pass'] else 'FAIL'),sum(c['pass'] for c in checks),'/',len(checks))
 for c in checks:
  if not c['pass']:print(c['name'],c['evidence'])
 if not report['all_pass']:raise SystemExit(1)
if __name__=='__main__':main()
