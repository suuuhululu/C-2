"""Exercise the existing A implementation; never starts ROS or a robot process."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time


def block(x, y, layer=1, kind='2x2x1', angle=0, color='blue'):
    return dict(brick_type=kind, color=color, x=x, y=y, layer=layer, orientation_deg=angle)


def cells(b):
    # Independent integer-grid replay, without calling Planner geometry helpers.
    w, d = {'2x2x1': (2, 2), '2x3x1': (2, 3), '1x2x1': (1, 2)}[b['brick_type']]
    if b['orientation_deg'] == 90:
        w, d = d, w
    return {(b['x']+dx, b['y']+dy, b['layer']) for dx in range(w) for dy in range(d)}


def key(b):
    return tuple(b[k] for k in ('brick_type', 'color', 'x', 'y', 'layer', 'orientation_deg'))


def structured(n, height, pattern, seed):
    rng = random.Random(seed)
    pillars = (n+height-1)//height
    specs = []
    for i in range(pillars):
        if pattern == 'square':
            kind, angle, color = '2x2x1', 0, 'blue'
        elif pattern == 'mixed':
            kind, angle, color = rng.choice(['2x2x1', '2x3x1']), rng.choice([0, 90]), rng.choice(['yellow', 'blue'])
        else:
            kind = rng.choice(['1x2x1', '2x2x1', '2x3x1'])
            angle = rng.choice([0, 90])
            color = 'red' if kind == '1x2x1' else rng.choice(['yellow', 'blue'])
        # A's contract uses 0 degrees for the symmetric 2x2 block.
        if kind == '2x2x1':
            angle = 0
        specs.append((kind, angle, color))
    result = []
    for layer in range(1, height+1):
        for i, (kind, angle, color) in enumerate(specs):
            if len(result) == n:
                return result
            result.append(block((i % 8)*3, (i//8)*4, layer, kind, angle, color))
    return result


def make_cases(source):
    os.environ['C_DESIGN_USE_LLM'] = '0'
    from app.c_design.main import create_initial_design
    examples = [('C_chair_15', create_initial_design(text='의자')['design']),
                ('sample_chair_12', json.loads((source/'planning_trial/sample_design.json').read_text())),
                ('modified_chair_12', json.loads((source/'planning_trial/sample_modified_design.json').read_text())),
                ('approved_chair_26', json.loads((source/'planning_trial/fixtures/search_limit_26blocks_20261012.json').read_text())['design']),
                ('stack_5', {'design_version': 1, 'blocks': [block(6, 6, layer) for layer in range(1, 6)]})]
    cases = []

    def add(name, design, progress=0, expected='READY', context_changes=None):
        design = deepcopy(design)
        ordered = sorted(design['blocks'], key=lambda b: (b['layer'], b['y'], b['x']))
        current = {'current_revision': 11 if progress else 0,
                   'blocks': deepcopy(ordered[:progress])}
        random.Random(len(cases)+73012).shuffle(design['blocks'])
        cases.append({'name':name,'design':design,'current':current,'expected':expected,
                      'context_changes':context_changes or {}})

    for name, design in examples:
        for count, tag in [(0, 'empty'), (len(design['blocks'])//2, 'half'), (len(design['blocks']), 'complete')]:
            add(name+'_'+tag, design, count)
    for n in [1, 5, 10, 15, 20, 26, 30, 39, 40]:
        for height in sorted({min(n, h) for h in range(1, 6)}):
            for pattern in ['square', 'mixed', 'red_mixed']:
                design={'design_version':1,'blocks':structured(n,height,pattern,n*97+height)}
                name=f'{pattern}_{n}blocks_{height}layers'
                add(name+'_empty',design)
                if n >= 20 and height == 5:
                    add(name+'_half',design,n//2)
    for pillars in [1, 2, 4, 8]:
        # Offset columns exercise partial support, pressing and lower-block HOLD.
        bricks=[block((i % 4)*4+2*(layer-1),(i//4)*6,layer,'2x3x1',90,
                      'blue' if layer % 2 else 'yellow')
                for layer in range(1,6) for i in range(pillars)]
        design={'design_version':1,'blocks':bricks}
        add(f'offset_{len(bricks)}_empty',design)
        add(f'offset_{len(bricks)}_half',design,len(bricks)//2)
    for n in [20, 40]:
        columns=n//10
        bricks=[block(6+2*x,6+3*y,layer,'2x3x1',0,'blue' if layer % 2 else 'yellow')
                for layer in range(1,6) for y in range(2) for x in range(columns)]
        add(f'dense_six_stud_{n}_five_layers',{'design_version':1,'blocks':bricks})
    for n in [20, 40]:
        bricks=[block(2*(i%10),2*(i//10)) for i in range(n)]
        add(f'dense_square_{n}_one_layer',{'design_version':1,'blocks':bricks})
    add('invalid_one_stud_support',{'design_version':1,'blocks':[block(6,6),block(7,7,2)]},expected='REJECT')
    add('invalid_floating_upper',{'design_version':1,'blocks':[block(6,6,2)]},expected='REJECT')
    add('invalid_overlap',{'design_version':1,'blocks':[block(6,6),block(7,6)]},expected='REJECT')
    add('invalid_board_range',{'design_version':1,'blocks':[block(-1,6)]},expected='REJECT')
    add('invalid_red_size',{'design_version':1,'blocks':[block(6,6,color='red')]},expected='REJECT')
    add('invalid_square_orientation',{'design_version':1,'blocks':[block(6,6,angle=90)]},expected='REJECT')
    add('invalid_41_blocks',{'design_version':1,'blocks':[block(2*(i%12),2*(i//12)) for i in range(41)]},expected='REJECT')
    add('robot_only_order_cycle',{'design_version':1,'blocks':[block(6,6,1,'2x3x1',90),block(6,8,1,'2x3x1',90)]},
        expected='NO_FEASIBLE_ORDER',context_changes={'supported_modes':['ROBOT_GRIP']})
    bases=[block(4,6),block(8,5),block(8,7)]
    lower=[block(5,6,2),block(7,5,2),block(7,7,2)]
    add('three_required_support_hands',{'design_version':1,'blocks':bases+lower+[block(6,6,3,'2x3x1',90)]},
        expected='NO_FEASIBLE_ORDER')
    add('target_static_obstacle',{'design_version':1,'blocks':[block(6,6)]},expected='NO_FEASIBLE_ORDER',
        context_changes={'obstacles':[[80,80,0,150,150,40]]})
    return cases


def run_case(case, default_context):
    from planning_trial.assembly_api_fixtures import whole_request, reassess_request
    from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment
    context=deepcopy(case.get('assembly_context',default_context))
    context.update(case.get('context_changes',{}))
    request=whole_request(case['design'],case['current'],context)
    before=deepcopy(request);audit={};started=time.perf_counter()
    response=handle_whole_plan(request,audit=audit)
    whole_seconds=time.perf_counter()-started
    raw=audit.get('raw_result') or {}
    plan_result=response.get('planning_result')
    ready=response['calculation_status']=='COMPLETED' and plan_result and plan_result['status']=='READY'
    record={'name':case['name'],'input':case,'actual_context':context,'expected':case['expected'],
            'calculation_status':response['calculation_status'],'planning_status':plan_result.get('status') if plan_result else None,
            'whole_seconds':whole_seconds,'optimization':raw.get('optimization'),
            'errors':response.get('stage_errors') or (plan_result or {}).get('errors') or [],
            'plan':plan_result.get('plan') if plan_result else None,'actions':response.get('action_proposals',[]),
            'response':response,'raw_result':raw}
    assert request==before,'A modified the input'
    assert response['execution_allowed'] is False
    if case['expected']!='READY':
        assert not ready and response['action_proposals']==[], 'Invalid/infeasible input received a plan'
        if case['expected']!='REJECT':
            assert response['calculation_status']==case['expected'],response['calculation_status']
        record.update(passed=True,reassessment_checks=0,total_seconds=time.perf_counter()-started)
        return record
    if not ready:
        record.update(passed=False,error='No complete READY plan returned',reassessment_checks=0,
                      total_seconds=time.perf_counter()-started)
        return record
    plan=plan_result['plan'];actions=response['action_proposals']
    remaining=Counter(map(key,case['design']['blocks']))-Counter(map(key,case['current']['blocks']))
    assert Counter(key(s['after']) for s in plan['steps'])==remaining,'Missing/duplicate/extra block'
    assert len(actions)==len(plan['steps'])
    layers=[s['after']['layer'] for s in plan['steps']]
    assert layers==sorted(layers),'Layer order changed'
    placed=deepcopy(case['current']['blocks']);occupied=set().union(*(cells(b) for b in placed));seen=set()
    checks=0
    for index,(step,action) in enumerate(zip(plan['steps'],actions)):
        target=step['after'];target_cells=cells(target)
        assert not target_cells & occupied,'Overlapping placement'
        assert target['layer']==1 or sum((x,y,z-1) in occupied for x,y,z in target_cells)>=2,'Insufficient support'
        assert not any((x,y) in {(a,b) for a,b,_ in target_cells} and z>target['layer'] for x,y,z in occupied),'Upper block prevents insertion'
        assert set(step['prerequisites'])<=seen,'Future/unknown prerequisite'
        assert action['step_id']==step['step_id'] and action['block']==target
        assert action['mode'] in context['supported_modes'] and action['human_hands_used']<=2
        assert all(h['access_assessment']=='HUMAN_ACCESS_NOT_CHECKED' for h in action['human_actions'])
        current={'current_revision':case['current']['current_revision']+index,'blocks':deepcopy(placed)}
        ar=reassess_request(request,response,current,index)
        assessment=handle_step_reassessment(ar)
        assert assessment['status']=='CANDIDATE',assessment
        assert assessment['execution_allowed'] is False
        checks+=1;placed.append(deepcopy(target));occupied.update(target_cells);seen.add(step['step_id'])
    assert Counter(map(key,placed))==Counter(map(key,case['design']['blocks'])),'Final state differs from Design'
    record.update(passed=True,reassessment_checks=checks,total_seconds=time.perf_counter()-started)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--input',type=Path,action='append',help='A Design JSON or {design,current,assembly_context}; repeatable')
    args=parser.parse_args();source=args.source.resolve();sys.path.insert(0,str(source))
    from planning_trial.assembly_api_fixtures import whole_request
    context=whole_request()['assembly_context'];context.update(supported_modes=['ROBOT_GRIP','HUMAN_ASSEMBLY'],finish_layers=True)
    if args.input:
        cases=[]
        for path in args.input:
            d=json.loads(path.read_text());envelope=d if 'design' in d else {'design':d}
            cases.append(dict(name=path.stem,design=envelope['design'],current=envelope.get('current',{'current_revision':0,'blocks':[]}),
                              assembly_context=envelope.get('assembly_context',context),
                              context_changes=envelope.get('context_changes',{}),expected=envelope.get('expected','READY')))
    else:
        cases=make_cases(source)
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'inputs').mkdir(exist_ok=True);(args.output/'results').mkdir(exist_ok=True)
    summary={'scope':'PURE_A_DESIGN_ORDER_AND_SYNTHETIC_CURRENT_REASSESSMENT_NOT_DEVICE_OR_MOVEIT',
             'source':str(source),'context':context,'cases':[],'robot_or_ros_started':False,
             'source_hashes':{str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (source/'planning_trial').glob('*.py') if not p.name.startswith(('test_','check_','run_'))}}
    suite_started=time.perf_counter()
    for i,case in enumerate(cases):
        (args.output/'inputs'/f'{i:03}_{case["name"]}.json').write_text(json.dumps(case,ensure_ascii=False,indent=2)+'\n')
        try:
            record=run_case(case,context)
        except Exception as exc:
            record={'name':case['name'],'passed':False,'expected':case['expected'],'error':str(exc)}
        (args.output/'results'/f'{i:03}_{case["name"]}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        metrics={k:v for k,v in record.items() if k in ('name','passed','expected','error','calculation_status','planning_status','whole_seconds','total_seconds','reassessment_checks')}
        if record.get('optimization'):
            metrics.update(optimal=record['optimization'].get('optimal'),expanded_states=record['optimization'].get('expanded_states'),
                           complete_plan_found=record['optimization'].get('complete_plan_found'),optimization_stop_reason=record['optimization'].get('optimization_stop_reason'))
        summary['cases'].append(metrics)
        if (i+1)%10==0 or not record['passed'] or case['name'].startswith('dense'):
            print(json.dumps({'progress':f'{i+1}/{len(cases)}',**metrics},ensure_ascii=False),flush=True)
        (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    summary.update(elapsed_seconds=time.perf_counter()-suite_started,passed=sum(c['passed'] for c in summary['cases']),
                   failed=sum(not c['passed'] for c in summary['cases']))
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k in ('passed','failed','elapsed_seconds')},ensure_ascii=False),flush=True)
    return 1 if summary['failed'] else 0


if __name__=='__main__':
    raise SystemExit(main())
