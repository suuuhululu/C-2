"""SIM-only orchestration around immutable user A 0.5 calculation functions."""
from pathlib import Path
from copy import deepcopy
import sys, json
HOME=Path(__file__).resolve().parents[1]
FIXTURES=HOME/'fixtures'
sys.path.insert(0,str(HOME.parent))
from planning_trial.assembly_adapter import handle_whole_plan,handle_step_reassessment,handle_step_motion
from planning_trial.assembly_target import calculate_step_tcp
from sim_utils import load,save,pose_matrix
import numpy as np
from scipy.spatial.transform import Rotation

class Scenario:
 def __init__(self,out,whole_request=None,reuse=False):
  self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
  self.cfg=load(HOME/'config/contact.sim.json')
  self.template_model=load(FIXTURES/'initial.model.json')
  from planning_trial.supply_pick import calculate_supply_pick
  whole=deepcopy(whole_request) if whole_request is not None else load(self.out/'whole.request.json' if reuse else HOME/'config/whole.complete_first.request.json')
  self.design_file=HOME/'config/design.json'
  whole['context'].update(job_id='chair-moveit-mock-sim',request_id='whole-chair-mock',source_epoch='chair-sim-20261010')
  whole['frame_profile']['calculation_profiles']['tray']=load(HOME/'config/tray.sim.json')
  whole['frame_profile']['profile_version']='fixture-red-1x2-v1'
  whole['context']['frame_profile_version']=whole['frame_profile']['profile_version']
  self.whole_request=whole;self.baseline=deepcopy(whole['current']);self.current=deepcopy(self.baseline);self.used=[]
  source_yaw=self.template_model['supply']['slots'][0]['yaw_rad']
  has_red='red_extension' in whole['frame_profile']['calculation_profiles']['supply']
  for i in (range(1,13) if has_red else []):
   pick=calculate_supply_pick('1x2x1','red',i,profile=whole['frame_profile']['calculation_profiles']['supply'])
   position=np.array(pick['pickup_tcp_pose']['xyz_abc'][:3])/1000
   position[2]=.03773+.0095
   self.template_model['supply']['slots'].append({'slot_id':f'red_1x2x1_{i:02}','slot_index':i,'brick_type':'1x2x1','color':'red','centre_m':position.tolist(),'pickup_tcp_pose':{'xyz_m':[v/1000 for v in pick['pickup_tcp_pose']['xyz_abc'][:3]],'quaternion_xyzw':self.template_model['supply']['slots'][0]['pickup_tcp_pose']['quaternion_xyzw']},'size_m':[.016,.032,.019],'yaw_rad':source_yaw+np.pi/2,'selected':False,'column_index':pick['column_index'],'slot_within_column':pick['slot_within_column'],'grasp_contact':'SMALL_END_SIDE_MIDPOINT','coordinate_status':'DERIVED_FROM_EXISTING_GRID_NOT_RED_TEACH_CALIBRATED'})
  if has_red:
   self.template_model['red_supply_status']={'count':12,'total_count':36,'layout':whole['frame_profile']['calculation_profiles']['supply']['red_extension'],'physical_grasp_verified':False}
  audit={}
  wr=load(self.out/'whole.result.json') if reuse else handle_whole_plan(whole,audit=audit)
  if not reuse:save(self.out/'whole.audit.json',audit)
  save(self.out/'whole.request.json',whole);save(self.out/'whole.result.json',wr)
  if not wr.get('planning_result') or wr['planning_result']['status']!='READY':raise ValueError('A whole Plan blocked: '+str(wr['stage_errors']))
  self.whole_result=wr;self.plan=wr['planning_result']['plan'];self.actions={a['step_id']:a for a in wr['action_proposals']}
  if any(a['mode'] not in ('ROBOT_GRIP','HUMAN_ASSEMBLY') for a in self.actions.values()):raise ValueError('Unsupported motion mode; no replacement')
  if max(b['layer'] for b in whole['design']['blocks'])>4:raise ValueError('Mock Design must be <=4 layers')
  save(self.out/'scenario_manifest.json',{'design_source':str(self.design_file),'a_source':str(HOME.parent/'planning_trial'),'plan_id':self.plan['plan_id'],'baseline_revision':self.baseline['current_revision'],'steps':self.plan['steps'],'completion_mode':'SIM_MOCK_AT_PRECONTACT_NO_PHYSICAL_INSERTION_NO_B_OBSERVATION','real_execution_allowed':False})
 def block_model(self,b):
  s={'step_id':'MODEL','operation':'PLACE','before':None,'after':deepcopy(b),'prerequisites':[],'requires_delivery':True}
  t=calculate_step_tcp(s,profile=self.whole_request['frame_profile']['calculation_profiles']['assembly'])
  xyz=np.array(t['nominal_seated_tcp']['position_m']);xyz[2]+=-.01231+.0095
  from planning_trial.planner import BRICK_SIZES
  size=[v*.016 for v in BRICK_SIZES[b['brick_type']]]+[.019]
  return {'block':deepcopy(b),'centre_m':xyz.tolist(),'size_m':size,'yaw_rad':self.template_model['target_model']['yaw_rad']+np.deg2rad(b['orientation_deg']),'nominal_geometry_only':True}
 def fixture_models(self):
  from planning_trial.assembly_target import trial_nominal_tcp
  prof=self.whole_request['frame_profile']['calculation_profiles']['assembly'];mapping=np.array(prof['grid_mapping']['planner_to_trial_xy']);offset=np.array(prof['grid_mapping']['offset_trial_xy']);out=[]
  for i,box in enumerate(self.whole_request['assembly_context']['obstacles']):
   centre=(np.array(box[:3])+np.array(box[3:]))/2;trial=mapping@(centre[:2]/16)+offset-.5
   xyz=np.array(trial_nominal_tcp(*[float(v) for v in trial],profile=prof))/1000;xyz[2]+=-.01231+centre[2]/1000
   out.append({'id':'MockFixture'+str(i),'centre_m':xyz.tolist(),'size_m':((np.array(box[3:])-np.array(box[:3]))/1000).tolist(),'yaw_rad':self.template_model['target_model']['yaw_rad'],'source_board_mm':box,'sim_only_fixture':True})
  return out
 def model(self,step,slot):
  m=deepcopy(self.template_model);m['obstacle_models']=self.fixture_models();m['tray_model']={'centre_m':[.417561,-.184622,-.002],'size_m':[.18,.14,.004],'yaw_rad':0,'surface_z_m':0,'height_status':'SIM_ONLY_UNMEASURED_SURFACE_TCP_FROM_EXISTING_REFERENCE'};m['current']=deepcopy(self.current);m['plan']=deepcopy(self.plan)
  m['current_models']=[self.block_model(b) for b in self.current['blocks']]
  m['final_models']=[self.block_model(b) for b in self.whole_request['design']['blocks']]
  m['target_model']=self.block_model(step['after']);m['supply']['slots']=[s for s in m['supply']['slots'] if s['slot_id'] not in self.used]
  for s in m['supply']['slots']:s['selected']=s['slot_id']==slot['slot_id']
  ct=calculate_step_tcp(step,profile=self.whole_request['frame_profile']['calculation_profiles']['assembly'],grip_axis=self.actions[step['step_id']]['grip_axis'])
  m['precontact']={'lower_stud_tip_z_m':ct['pre_contact_tcp']['position_m'][2]-.01231-.020,'tcp_above_bottom_m':.01231,'bottom_to_lower_stud_tip_m':.020}
  return m
 def prepare(self,index,start,q):
  step=self.plan['steps'][index];sid=step['step_id'];out=self.out/sid;out.mkdir(exist_ok=True)
  available=[s for s in self.template_model['supply']['slots'] if s['slot_id'] not in self.used and all(s[k]==step['after'][k] for k in ('color','brick_type'))]
  if not available:raise ValueError('No unconsumed matching supply slot')
  slot=deepcopy(available[0]);ctx=deepcopy(self.whole_request['context']);ctx.update(plan_id=self.plan['plan_id'],step_id=sid,input_current_revision=self.current['current_revision'],world_state_revision=11+index,request_id='mock-reassessment-'+sid)
  ra=load(FIXTURES/'source/01_initial/reassessment.request.json');ra.update(context=ctx,design=deepcopy(self.whole_request['design']),plan=deepcopy(self.plan),plan_base_current=deepcopy(self.baseline),expected_current_before_step=deepcopy(self.current),latest_current=deepcopy(self.current),selected_action=deepcopy(self.actions[sid]),policy=deepcopy(self.whole_request['policy']),assembly_context=deepcopy(self.whole_request['assembly_context']),frame_profile=deepcopy(self.whole_request['frame_profile']))
  rr=handle_step_reassessment(ra);save(out/'reassessment.request.json',ra);save(out/'reassessment.result.json',rr)
  if rr['status']!='CANDIDATE':raise ValueError('A reassessment blocked '+str(rr['errors']))
  mr=load(FIXTURES/'source/01_initial/motion.request.json');mctx=deepcopy(ctx);mctx['request_id']='mock-motion-'+sid
  mr.update(context=mctx,plan=deepcopy(self.plan),selected_step=deepcopy(step),latest_current=deepcopy(self.current),assessment_id=rr['assessment_id'],assessment_input_digest=rr['assessment_input_digest'],assessment_context=deepcopy(rr['context']),assessment_current_revision=self.current['current_revision'],action_proposal=deepcopy(rr['action_proposal']),assessed_action=deepcopy(rr['action_proposal']),assembly_context=deepcopy(self.whole_request['assembly_context']),frame_profile=deepcopy(self.whole_request['frame_profile']))
  mr['robot_state'].update(source_epoch=ctx['source_epoch'],state_sequence=index+1,tcp_pose=deepcopy(start),stop_observation_ref='ISAAC_ACTUAL_SIM_STATE_'+sid)
  mr['reserved_supply_slot'].update(**{k:slot[k] for k in ('slot_id','slot_index','brick_type','color')},reservation_id='mock-reservation-'+sid,reservation_generation=index+1,valid_until_ref='SIM_STEP_ONLY_'+sid)
  audit={};r=handle_step_motion(mr,audit=audit);save(out/'motion.request.json',mr);save(out/'motion.raw.json',audit);save(out/'motion.result.json',r)
  if r['status']!='CANDIDATE':raise ValueError('A motion blocked '+str(r['errors']))
  if r['execution_allowed'] is not False:raise ValueError('A cannot authorize real execution')
  model=self.model(step,slot);save(out/'model.json',model)
  return step,slot,model,r,out
 def mock_complete(self,step,slot):
  self.current['blocks'].append(deepcopy(step['after']));self.current['current_revision']+=1;self.used.append(slot['slot_id']) if slot['slot_id'] not in self.used else None
  save(self.out/step['step_id']/'mock_current_after.json',{'event':'MOCK_ASSEMBLY_COMPLETED_AT_PRECONTACT','current':self.current,'plan_base_current':self.baseline,'plan_id':self.plan['plan_id'],'real_B_observation':False,'physical_insertion':False,'consumed_supply_slots':self.used})
