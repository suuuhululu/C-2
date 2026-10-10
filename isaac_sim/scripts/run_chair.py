"""Modified A -> measured contact grasp -> MoveIt -> explicit mock D/B boundary."""
from pathlib import Path
from copy import deepcopy
import argparse,time,json,traceback,subprocess,uuid
import yaml,numpy as np
from sim_utils import load,save,pose_matrix,error
from scenario_core import Scenario,HOME as ROOT

def main():
 p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--auto-human',action='store_true');p.add_argument('--resume-failed-lift',action='store_true');args=p.parse_args()
 out=args.run_dir.resolve();scenario=Scenario(out,reuse=True)
 status={'scope':'SIM_CHAIR_MOVEIT_COMPLETE_FIRST_WITH_MOCK_D_B','success':False,'steps':[],
         'physical_insertion_executed':False,'physical_release_verified':False,'real_B_observation':False,
         'real_human_help_verified':False,'virtual_grasp_used':False,'a_source_variant':'REVIEW_COPY_COMPLETE_FIRST_AND_MANUAL_ACCESS',
         'plan_id':scenario.plan['plan_id'],'base_current_revision':scenario.baseline['current_revision'],
         'auto_human':args.auto_human,'design_block_count':len(scenario.whole_request['design']['blocks'])}
 first_index=0
 if (out/'fixture_seed.json').exists():
  seed=load(out/'fixture_seed.json');first_index=seed['start_index'];scenario.current=deepcopy(seed['current']);scenario.used=list(seed['used_slots']);status.update(scope='SIM_HANDOVER_100MM_REGRESSION',fixture_seed=seed,executed_start_index=first_index)
 if args.resume_failed_lift:
  previous=load(out/'status.json');first_index=len(previous['steps']);sid=scenario.plan['steps'][first_index]['step_id'];failed=yaml.load((out/sid/'LIFT.result.yaml').read_text(),Loader=yaml.CSafeLoader);state=load(out/'live_state.json')
  if previous.get('failed_step')!=sid or failed.get('execution_issued') or failed.get('execution_success') or failed.get('phase')!='LIFT' or state['current_revision']!=first_index or not state['observed_stopped'] or (out/'execution.active.json').exists() or any((out/f).exists() for f in ('runtime_guard_failure.json','host_failure.json')):
   raise RuntimeError('Recovery rejected: requires unexecuted lift failure, same Current, actual stopped grasp, no guard failure')
  save(out/'status.failed_before_recovery.json',previous);status=previous;status.pop('error',None);status.pop('failed_step',None);status['resumed_after_unexecuted_lift_failure']=True
  scenario.current=deepcopy(previous['mock_current']);scenario.used=[row['slot_id'] for row in previous['steps']]
 def live():return load(out/'live_state.json')
 def wait(predicate,timeout=90):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   for failure in ('host_failure.json','runtime_guard_failure.json'):
    if (out/failure).exists():raise RuntimeError(failure+': '+(out/failure).read_text())
   if (out/'live_state.json').exists():
    state=live()
    if predicate(state):return state
   time.sleep(.04)
  raise RuntimeError('Actual SIM wait timeout')
 def host_command(kind,**payload):
  command={'command_id':uuid.uuid4().hex,'kind':kind,'expected_revision':live()['current_revision'],**payload}
  save(out/'host_command.json',command)
  wait(lambda s:(out/'host_command.receipt.json').exists() and load(out/'host_command.receipt.json')['command_id']==command['command_id'])
  receipt=load(out/'host_command.receipt.json');save(step_out/(kind+'.receipt.json'),receipt)
  wait(lambda s:s['current_revision']==receipt['current_revision'] and s['selected_slot_id']==receipt['selected_slot_id'])
  if command.get('world_object_id'):
   wait(lambda s:any(v['id']==command['world_object_id'] and np.linalg.norm(np.array(v['pose']['xyz_m'])-command['target']['centre_m'])<1e-5 for v in s['world_objects']))
  return receipt
 def capture(label,view):
  save(out/'capture.request.json',{'label':label,'view':view})
  wait(lambda s:(out/(label+'.png')).exists(),30)
 def hmi(kind,actions):
  req={'request_id':'mock-hmi-'+uuid.uuid4().hex,'kind':kind,'plan_id':scenario.plan['plan_id'],
       'step_id':step['step_id'],'current_revision':scenario.current['current_revision'],'human_actions':actions,
       'message':step['step_id']+' '+kind+': '+json.dumps(actions,ensure_ascii=True)}
  save(out/'hmi.pending.json',req);events.write(json.dumps({'event':'HUMAN_REQUEST_CREATED',**req})+'\n');events.flush()
  if args.auto_human:
   response={**{k:req[k] for k in ('request_id','kind','plan_id','step_id','current_revision')},'source':'AUTO_MOCK_RESPONSE'}
  else:
   wait(lambda s:(out/'hmi.response.json').exists() and all(load(out/'hmi.response.json').get(k)==req[k] for k in ('request_id','kind','plan_id','step_id','current_revision')),3600)
   response=load(out/'hmi.response.json')
  events.write(json.dumps({'event':'MOCK_HUMAN_RESPONSE',**response})+'\n');events.flush();(out/'hmi.pending.json').unlink()
  save(step_out/(kind+'.hmi.json'),{'request':req,'response':response})
 def after_model(step,slot,extra=None):
  m=scenario.model(step,slot)
  for i,v in enumerate(m['supply']['slots']):v['selected']=i==0
  m['extra_models']=extra or []
  return m
 wait(lambda s:s['started'],3600);wait(lambda s:s['observed_stopped']);begin=time.monotonic()
 events=(out/'mock_hmi_events.jsonl').open('a' if args.resume_failed_lift else 'w')
 try:
  capture('red_supply_initial','Supply');save(out/'red_supply_initial.actual.json',live())
  for index in range(first_index,len(scenario.plan['steps'])):
   state=wait(lambda s:s['observed_stopped'])
   recovering=args.resume_failed_lift and index==first_index
   if recovering:
    step=scenario.plan['steps'][index];step_out=out/step['step_id'];model=load(step_out/'model.json');slot=next(v for v in model['supply']['slots'] if v['selected']);a=load(step_out/'motion.result.json')
    if state['selected_slot_id']!=slot['slot_id']:raise RuntimeError('Recovery selected slot mismatch')
   else:step,slot,model,a,step_out=scenario.prepare(index,state['tcp_pose'],state['q_rad'])
   sid=step['step_id'];save(out/'active_step.json',{'step_id':sid})
   if not recovering:host_command('SELECT',model=model)
   if a['execution_allowed']:raise RuntimeError('A candidate cannot grant execution')
   action=scenario.actions[sid];manual=action['mode']=='HUMAN_ASSEMBLY'
   contract={'current_revision':scenario.current['current_revision'],'world_revision':a['context']['world_state_revision'],
             'profile_version':a['context']['frame_profile_version'],'reservation_id':a['reservation_binding']['reservation_id']}
   save(out/'scene_context.json',contract)
   defaults={**contract,'plan_id':scenario.plan['plan_id'],'step_id':sid,'base_current_revision':scenario.baseline['current_revision'],
             'sim_execution_authorized':True,'a_execution_allowed':False,'held':False,'contact_phase':False,'execute':True,'cartesian':False,'kind':'POSE'}
   row={'step_id':sid,'block':step['after'],'slot_id':slot['slot_id'],'action_mode':action['mode'],'assistance_kind':action['assistance_kind'],
        'input_current_revision':scenario.current['current_revision'],'phases':[],'success':False}
   if recovering:row=load(step_out/'step_progress.json')
   status['active_step']=sid;save(out/'status.json',status)
   def stage(phase,**values):
    start=time.monotonic();req={**deepcopy(defaults),'phase':phase,**values};reqfile=step_out/(phase+'.request.yaml');reqfile.write_text(yaml.safe_dump(req,sort_keys=False))
    save(out/'display.json',{'message':sid+f' / {index+1} of {len(scenario.plan["steps"])} / '+action['mode']+' / '+phase})
    save(out/'guard_context.json',{'phase':phase,'held':req['held'],'attachment':req.get('attachment'),'allow_touch_world_id':req.get('allow_touch_world_id'),**contract,'selected_slot_id':live()['selected_slot_id']})
    result_file=step_out/(phase+'.result.yaml');cmd=['ros2','run','m0609_moveit_sim','moveit_step',str(ROOT),str(out),str(reqfile),str(result_file)]
    with (step_out/(phase+'.log')).open('w') as log:process=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=240)
    data=yaml.load(result_file.read_text(),Loader=yaml.CSafeLoader);summary={k:v for k,v in data.items() if k not in ('checked_states','actual_start','actual_final')};summary['wall_s']=time.monotonic()-start;row['phases'].append(summary)
    save(step_out/'step_progress.json',row)
    if process.returncode or (req['execute'] and req['kind']!='SYNC' and not data.get('execution_success')):
     exc=RuntimeError(sid+' '+phase+' failed: '+str(data.get('error')));exc.execution_issued=data.get('execution_issued',False);raise exc
    state=wait(lambda s:s['observed_stopped']);save(step_out/(phase+'.actual.json'),state)
    return data
   pickup=deepcopy(a['motion_proposal']['pickup_tcp_pose']);waypoints=[w for segment in a['motion_proposal']['segments'] for w in segment['waypoints']]
   goal=deepcopy(waypoints[-1]['tcp_pose']);lift=deepcopy(next(w['tcp_pose'] for w in waypoints if w['label']=='LIFT_HOLDING'))
   above=deepcopy(pickup);above['xyz_m'][2]+=.10
   if not recovering:
    stage('SUPPLY_APPROACH',goal=above)
    stage('PICKUP_DOWN',goal=pickup,cartesian=True,contact_phase=True)
    stage('CLOSE_GRIPPER',kind='GRIP',grip_rad=.4793595967442058,contact_phase=True)
    settle=live()['sim_time_s'];state=wait(lambda s:s['sim_time_s']>=settle+3)
   if state['gripper_mimic_max_error_rad']>.02:raise RuntimeError(sid+' RG2 mimic mismatch')
   attachment=np.array(load(step_out/'measured_attachment.json')) if recovering else np.linalg.inv(pose_matrix(state['tcp_pose']))@pose_matrix(state['block_pose'])
   if recovering:
    drift=error(np.linalg.inv(pose_matrix(state['tcp_pose']))@pose_matrix(state['block_pose']),attachment)
    if drift[0]>.005 or drift[1]>.15:raise RuntimeError('Recovery grasp no longer retained')
   else:save(step_out/'measured_attachment.json',attachment.tolist())
   defaults.update(held=True,attachment=attachment.tolist(),holding_orientation=state['tcp_pose'],allow_yaw_reorientation=True)
   def clearance_lift():
    archive=step_out/'LIFT_A_candidate_rejected';archive.mkdir(exist_ok=True)
    for f in step_out.glob('LIFT.*'):f.rename(archive/f.name)
    clearance=deepcopy(pickup);clearance['xyz_m'][2]+=.10
    if clearance['xyz_m'][2]>=lift['xyz_m'][2]:raise RuntimeError('No shorter lift alternative')
    row['lift_intermediate_override']={'original_a_lift':lift,'sim_clearance_lift':clearance,'reason':'Original high lift had no complete validated path; use 100mm source clearance then global MoveIt; pickup/destination unchanged'}
    save(step_out/'lift_intermediate_override.json',row['lift_intermediate_override']);stage('LIFT',goal=clearance,cartesian=True)
   if manual and not recovering:
    clearance=deepcopy(pickup);clearance['xyz_m'][2]+=load(ROOT/'config/transport.sim.json')['manual_source_lift_m']
    row['manual_lift_policy']={'original_a_lift':lift,'sim_lift':clearance,'relative_rise_m':load(ROOT/'config/transport.sim.json')['manual_source_lift_m'],'reason':'USER_SELECTED_100MM_SOURCE_LIFT_THEN_COLLISION_CHECKED_MOVEIT_TRANSPORT'}
    save(step_out/'manual_lift_policy.json',row['manual_lift_policy']);stage('LIFT',goal=clearance,cartesian=True)
   elif recovering:clearance_lift()
   else:
    try:stage('LIFT',goal=lift,cartesian=True)
    except RuntimeError as exc:
     if getattr(exc,'execution_issued',False) or (out/'runtime_guard_failure.json').exists():raise
     clearance_lift()
   state=live();drift=error(np.linalg.inv(pose_matrix(state['tcp_pose']))@pose_matrix(state['block_pose']),attachment)
   if drift[0]>.005 or drift[1]>.15:raise RuntimeError(sid+' contact grasp failed to follow')
   row['actual_grasp_follow_error_m_rad']=drift;capture(sid+'_lift','Supply')
   attempts=[]
   for dz in (.10,.15,.20):
    approach=deepcopy(goal);approach['xyz_m'][2]+=dz
    try:stage('TRANSPORT',goal=approach);attempts.append({'dz_m':dz,'success':True});break
    except RuntimeError as exc:
     attempts.append({'dz_m':dz,'success':False,'error':str(exc)})
     if getattr(exc,'execution_issued',False) or (out/'runtime_guard_failure.json').exists():raise
     archive=step_out/('TRANSPORT_attempt_'+str(len(attempts)));archive.mkdir()
     for f in step_out.glob('TRANSPORT.*'):f.rename(archive/f.name)
   else:raise RuntimeError(sid+' no collision-free staging route; no forced HUMAN fallback')
   stage('PRE_CONTACT',goal=goal,cartesian=True)
   stop=live()['sim_time_s'];state=wait(lambda s:s['sim_time_s']>=stop+2 and s['observed_stopped'])
   pe,re=error(pose_matrix(state['tcp_pose']),pose_matrix(goal));drift=error(np.linalg.inv(pose_matrix(state['tcp_pose']))@pose_matrix(state['block_pose']),attachment)
   if pe>.002 or re>np.deg2rad(1) or drift[0]>.005 or drift[1]>.15:raise RuntimeError(sid+' wait/holding tolerance exceeded')
   row.update(actual_wait_tcp=state['tcp_pose'],a_wait_goal=goal,tcp_error_m_rad=[pe,re],holding_error_m_rad=drift,transport_attempts=attempts,destination='HANDOVER_TRAY' if manual else 'PRE_CONTACT')
   if not manual:
    t=pose_matrix(state['block_pose']);size=slot['size_m'];corners=np.array([[x,y,z] for x in (-size[0]/2,size[0]/2) for y in (-size[1]/2,size[1]/2) for z in (-size[2]/2,size[2]/2)])@t[:3,:3].T+t[:3,3]
    row['bottom_to_lower_stud_tip_gap_m']=float(corners[:,2].min()-model['precontact']['lower_stud_tip_z_m'])
   capture(sid+'_wait','Tray' if manual else 'Assembly');save(step_out/'arrival_status.json',row)
   if not manual and action['human_actions']:hmi('ASSISTANCE_READY',action['human_actions'])
   if manual:
    scenario.used.append(slot['slot_id']);tray={'id':'TrayWaiting_'+sid,'centre_m':[.417561,-.184622,slot['size_m'][2]/2],'size_m':slot['size_m'],'yaw_rad':0,'studs':True}
    m=after_model(step,slot,[tray]);host_command('MOCK_TRAY_PLACE',slot_id=slot['slot_id'],target=tray,world_object_id=tray['id'],model=m,goal=goal,attachment=attachment.tolist())
    row['tray_mock_release']=True
    touch=tray['id']
   else:
    scenario.mock_complete(step,slot);m=after_model(step,slot)
    host_command('MOCK_ASSEMBLE',slot_id=slot['slot_id'],target=model['target_model'],world_object_id='Current_'+str(index),model=m,goal=goal,attachment=attachment.tolist());touch=None
   contract['current_revision']=live()['current_revision'];contract['world_revision']+=1;contract['reservation_id']='MOCK_RESET_'+sid
   save(out/'scene_context.json',contract);defaults.update(contract,held=False,attachment=None)
   # Detach, remove consumed supply, add committed Current/tray before any new arm path.
   sync=stage('SCENE_COMMIT_SYNC',kind='SYNC',execute=False,allow_touch_world_id=touch)
   row['scene_commit']={k:sync.get(k) for k in ('scene_sync_success','attached_object_count','world_object_ids')}
   if manual:
    # User-selected tray policy: open at the reached tray TCP, before any arm retreat.
    # The existing kinematic mock placement remains separate from physical release proof.
    stage('OPEN_RESET',kind='GRIP',grip_rad=-.4,allow_touch_world_id=touch)
    opened=live();pe,re=error(pose_matrix(opened['tcp_pose']),pose_matrix(goal))
    if pe>.002 or re>np.deg2rad(1) or abs(opened['grip_rad']+.4)>.02:
     raise RuntimeError(sid+' tray opening did not retain reached TCP/open gripper')
    row['tray_open_at_wait']={'policy':'OPEN_AT_REACHED_TRAY_TCP_BEFORE_ARM_RETREAT',
                            'goal':goal,'actual_tcp':opened['tcp_pose'],'tcp_error_m_rad':[pe,re],
                            'grip_target_rad':-.4,'actual_grip_rad':opened['grip_rad'],
                            'sim_time_s':opened['sim_time_s'],'physical_drop_verified':False}
    save(step_out/'tray_open_at_wait.json',row['tray_open_at_wait']);capture(sid+'_tray_delivered','Tray')
   retreat=deepcopy(live()['tcp_pose']);retreat['xyz_m'][2]+=.10
   stage('EMPTY_RETREAT',goal=retreat,cartesian=True,allow_touch_world_id=touch)
   if not manual:stage('OPEN_RESET',kind='GRIP',grip_rad=-.4)
   if manual:
    hmi('MANUAL_ASSEMBLY_DONE',action['human_actions']);scenario.mock_complete(step,slot);m=after_model(step,slot)
    host_command('MOCK_HUMAN_ASSEMBLE',slot_id=slot['slot_id'],target=model['target_model'],world_object_id='Current_'+str(index),model=m)
    contract['current_revision']=live()['current_revision'];contract['world_revision']+=1;save(out/'scene_context.json',contract);defaults.update(contract)
    sync=stage('HUMAN_CURRENT_SYNC',kind='SYNC',execute=False);row['human_scene_commit']={k:sync.get(k) for k in ('scene_sync_success','attached_object_count','world_object_ids')}
   row.update(success=True,mock_current_revision=scenario.current['current_revision'],plan_base_current=scenario.baseline,physical_insertion=False,real_B_observation=False)
   status['steps'].append(row);status['mock_current']=deepcopy(scenario.current);save(step_out/'completed.json',row);save(out/'status.json',status)
   capture(sid+'_assembled','Assembly');print('STEP PASS',sid,'Current',scenario.current['current_revision'],flush=True)
  status.update(success=True,all_blocks_mock_completed=True,scenario_wall_s=(time.time()-(out/'S01/SUPPLY_APPROACH.request.yaml').stat().st_mtime) if args.resume_failed_lift else time.monotonic()-begin,elapsed_includes_recovery_pause=args.resume_failed_lift,mock_current=scenario.current)
  message=f'PASS: {len(status["steps"])}/{len(scenario.plan["steps"])} red1x2 smoke fixture. Small-side contact grasp / MoveIt / mock completion. No physical insertion.'
  save(out/'status.json',status);save(out/'display.json',{'message':message});capture('chair_completed','Assembly');print('CHAIR PASS',out,flush=True)
 except Exception:
  status['error']=traceback.format_exc();status['failed_step']=status.get('active_step');save(out/'status.json',status);save(out/'display.json',{'message':'STOPPED: '+next(line for line in reversed(status['error'].splitlines()) if line.strip())});traceback.print_exc();raise
 finally:events.close()
if __name__=='__main__':main()
