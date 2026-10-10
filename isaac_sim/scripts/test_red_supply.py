from copy import deepcopy
import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from planning_trial.supply_pick import calculate_supply_pick,calculate_all_supply_picks,load_supply_profile,relative_centres
from planning_trial.assembly_geometry import grip_options
from planning_trial.assembly_target import calculate_step_tcp
from planning_trial.assembly_adapter import handle_step_motion
from scenario_core import Scenario
REQ=json.loads((ROOT/'config/whole.complete_first.request.json').read_text());P=REQ['frame_profile']['calculation_profiles']['supply']

def test_twelve_red_slots_two_six_row_columns_and_empty_gap():
 picks=[calculate_supply_pick('1x2x1','red',i,profile=P) for i in range(1,13)]
 assert [p['column_index'] for p in picks]==[1]*6+[2]*6
 assert [p['slot_within_column'] for p in picks]==list(range(1,7))*2
 assert [p['relative_block_centre_grid'] for p in picks]==[[-4*r,y] for y in (-15.5,-18.5) for r in range(6)]
 blue=relative_centres(P)[('2x3x1','blue')]['first_centre_relative_grid'][1]
 assert blue-picks[0]['relative_block_centre_grid'][1]-1.5-.5==2
 assert picks[0]['relative_block_centre_grid'][1]-picks[6]['relative_block_centre_grid'][1]-.5-.5==2

def test_existing_twenty_four_pick_candidates_are_identical():
 old=load_supply_profile();new=deepcopy(old);new['red_extension']=P['red_extension']
 for color in ('yellow','blue'):
  for kind in ('2x2x1','2x3x1'):
   for i in range(1,7):assert calculate_supply_pick(kind,color,i,profile=old)==calculate_supply_pick(kind,color,i,profile=new)

def test_red_requires_explicit_profile_and_never_wraps_index():
 with pytest.raises(ValueError):calculate_supply_pick('1x2x1','red',1,profile=load_supply_profile())
 for i in (0,13):
  with pytest.raises(ValueError):calculate_supply_pick('1x2x1','red',i,profile=P)
 with pytest.raises(ValueError):calculate_supply_pick('2x2x1','yellow',7,profile=P)

@pytest.mark.parametrize('orientation,axis',[(0,'y'),(90,'x')])
def test_red_grips_small_faces_along_long_two_stud_axis(orientation,axis):
 brick={**REQ['design']['blocks'][0],'orientation_deg':orientation}
 options=grip_options(brick,[],REQ['assembly_context'])
 assert options and {v['grip_axis'] for v in options}=={axis}
 step={'step_id':'S01','operation':'PLACE','before':None,'after':brick,'prerequisites':[],'requires_delivery':True}
 result=calculate_step_tcp(step,profile=REQ['frame_profile']['calculation_profiles']['assembly'],grip_axis=axis)
 assert result['status']=='COORDINATE_CANDIDATE'
 with pytest.raises(ValueError):calculate_step_tcp(step,profile=REQ['frame_profile']['calculation_profiles']['assembly'],grip_axis='y' if axis=='x' else 'x')

def test_all_slots_model_and_last_red_wire_motion_candidate(tmp_path):
 scenario=Scenario(tmp_path);assert len(scenario.template_model['supply']['slots'])==36
 original=json.loads((ROOT/'fixtures/initial.model.json').read_text())
 assert scenario.template_model['supply']['slots'][:24]==original['supply']['slots']
 start={'frame_id':'base_link','xyz_m':[.3,0,.2],'quaternion_xyzw':[0,1,0,0]}
 step,slot,model,result,folder=scenario.prepare(0,start,[])
 assert result['status']=='CANDIDATE' and not result['execution_allowed']
 req=json.loads((folder/'motion.request.json').read_text());req['reserved_supply_slot'].update(slot_index=12,slot_id='red_1x2x1_12')
 last=handle_step_motion(req);assert last['status']=='CANDIDATE' and not last['execution_allowed']
 expected=calculate_supply_pick('1x2x1','red',12,profile=scenario.whole_request['frame_profile']['calculation_profiles']['supply'])['pickup_tcp_pose']['xyz_abc'][:3]
 assert last['motion_proposal']['pickup_tcp_pose']['xyz_m']==[v/1000 for v in expected]
