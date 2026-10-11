"""Full-plan availability takes precedence over proving help optimality."""
import sys,json
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from planning_trial.assembly_adapter import handle_whole_plan
from planning_trial.planner import validate_plan
REQ=json.loads((ROOT/'config/whole.chair.regression.request.json').read_text())
def call(req):
    audit={};result=handle_whole_plan(req,audit=audit);return result,audit.get('raw_result',{})
def test_complete_plan_retained_when_help_budget_is_exhausted():
    req=deepcopy(REQ);req['assembly_context']['max_states']=12
    old=deepcopy(req);old['assembly_context']['planning_priority']='MIN_HELP_COMPLETE_DESIGN_SEARCH'
    assert call(old)[0]['calculation_status']=='SEARCH_LIMIT'
    result,raw=call(req)
    assert result['calculation_status']=='COMPLETED' and not result['execution_allowed']
    plan=result['planning_result']['plan'];assert len(plan['steps'])==12
    validate_plan(req['design'],[],0,plan,finish_layers=False)
    assert raw['optimization']['complete_plan_found'] and not raw['optimization']['optimal']
    assert raw['optimization']['selection']=='COMPLETE_FEASIBILITY_WITNESS'
def test_budget_limit_without_any_complete_witness_still_blocks():
    req=deepcopy(REQ);req['assembly_context']['max_states']=1
    result,raw=call(req)
    assert result['calculation_status']=='SEARCH_LIMIT'
    assert result['planning_result'] is None and not result['action_proposals']
    assert not raw['optimization']['complete_plan_found']
def test_complete_first_does_not_remove_access_constraints():
    req=deepcopy(REQ);req['assembly_context'].pop('human_assembly_model')
    result,raw=call(req)
    assert result['calculation_status']=='NO_FEASIBLE_ORDER' and not result['planning_result']
def test_second_stage_minimizes_help_among_complete_plans():
    result,raw=call(REQ)
    assert len(result['planning_result']['plan']['steps'])==12
    assert raw['optimization']['optimal'] and raw['optimization']['cost']==[2,2,2]
    assert raw['optimization']['feasibility_expanded_states']==12
    assert [a['mode'] for a in result['action_proposals']].count('HUMAN_ASSEMBLY')==2
    assert result['planning_result']['plan']['base_current_revision']==0

def test_better_complete_incumbent_kept_before_optimality_is_proven(monkeypatch):
    import planning_trial.assembly_optimizer as optimizer
    robot={'mode':'ROBOT_GRIP','release_strategy':'MINIMAL_OPEN','human_actions':[]}
    human={'mode':'HUMAN_ASSEMBLY','release_strategy':None,'human_actions':[{'action':'MANUAL_PLACE'}]}
    blocks=[{'i':i,'layer':1} for i in range(3)]
    def choices(brick,placed,context):
        if brick['i']==0:return [robot,human],{}
        if brick['i']==1:return [robot],{}
        return ([human] if {0,1}<={b['i'] for b in placed} else []),{}
    monkeypatch.setattr(optimizer,'mode_options',choices)
    context={'max_states':3,'finish_layers':False}
    witness=[(0,human),(1,robot),(2,human)]
    best,meta=optimizer._minimize_help_search(blocks,[],context,incumbent_path=witness)
    assert len(best)==3 and meta['cost']==[1,1,1] and not meta['optimal']
    assert meta['best_known_complete_plan_retained']
