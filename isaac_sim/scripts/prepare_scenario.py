import argparse
from pathlib import Path
from scenario_core import Scenario
from sim_utils import save,load
from copy import deepcopy
p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--manual-regression-from',type=Path);p.add_argument('--whole-request',type=Path);a=p.parse_args()
start=0
if a.manual_regression_from:
 previous=load(a.manual_regression_from/'status.json')
 if not previous.get('success') or len(previous['steps'])!=12:raise ValueError('Tail fixture needs validated completed chair source')
 for name in ('whole.request.json','whole.result.json'):save(a.run_dir/name,load(a.manual_regression_from/name))
 s=Scenario(a.run_dir,reuse=True);start=10
 if any(s.actions[v['step_id']]['mode']!='HUMAN_ASSEMBLY' for v in s.plan['steps'][start:]):raise ValueError('Tail test is limited to handover steps')
 s.current=deepcopy(s.baseline);s.current['blocks']=[deepcopy(v['after']) for v in s.plan['steps'][:start]];s.current['current_revision']=start;s.used=[v['slot_id'] for v in previous['steps'][:start]]
 q=load(a.manual_regression_from/'S10/OPEN_RESET.actual.json')['q_rad']
 save(a.run_dir/'fixture_seed.json',{'source_run':str(a.manual_regression_from.resolve()),'kind':'MOCK_CURRENT_PREFIX_SEEDED_NOT_EXECUTED_IN_THIS_RUN','start_index':start,'current':s.current,'used_slots':s.used,'initial_q_rad':q,'base_current_revision':s.baseline['current_revision']})
else:s=Scenario(a.run_dir,whole_request=load(a.whole_request) if a.whole_request else None)
step=s.plan['steps'][start]
slot=next(v for v in s.template_model['supply']['slots'] if v['slot_id'] not in s.used and all(v[k]==step['after'][k] for k in ('color','brick_type')))
save(a.run_dir/'initial.model.json',s.model(step,slot));print('READY',len(s.plan['steps']),'steps',s.plan['plan_id'])
