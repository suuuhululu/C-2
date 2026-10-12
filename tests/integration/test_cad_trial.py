import json
import math
import os
from pathlib import Path

import pytest

from app import cad_trial

ROOT = Path(os.environ.get('C2_ROBOT_ROOT', ''))
pytestmark = pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),
    reason='C2_ROBOT_ROOT required')


def block(kind='2x2x1', color='blue', angle=0, layer=1):
    return dict(brick_type=kind, color=color, x=6, y=6, layer=layer, orientation_deg=angle)


def test_five_layers_without_b_and_without_fabricated_current(tmp_path, monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM', '0')
    design = dict(design_version=1, blocks=[block(layer=i) for i in range(1,6)])
    result = cad_trial.run_mock(design, ROOT)
    assert result['status'] == 'TRIAL_EXECUTION_FINISHED', result['reason']
    assert result['c_review']['hri_result'] == 'APPROVE'
    assert result['a_whole']['planning_result']['plan']['base_current_revision'] == 0
    assert result['assumed_state']['blocks'] == design['blocks']
    assert result['assumed_state']['planned_state_sequence'] == 5
    assert not result['b_called'] and not result['vision_confirmed'] and not result['assembly_completion']
    names = [e['event'] for e in result['events']]
    assert names.count('TRIAL_STEP_EXECUTED') == names.count('CONTACT_SUCCEEDED') == 5
    assert not set(names) & {'B_DECISION', 'INSPECTION_REQUIRED', 'ASSEMBLY_COMPLETED'}
    for index, doc in enumerate(result['documents']):
        assert doc['step']['current_revision'] is None
        assert doc['session']['backend'] == 'TEST'
        assert doc['planned_state_sequence'] == index
        assert doc['state_basis'] == 'ASSUMED_PLAN_PREFIX_NOT_B_CURRENT'
        assert doc['d_profile']['approach_offset_mm'] == 20.1
        setting = next(iter(doc['d_profile']['steps'].values()))
        assert (setting['pickup_open_width_mm'], setting['pickup_width_mm'], setting['release_width_mm']) == (55.,35.,48.)
        assert not setting['physical_reference_reviewed']
    out = Path('logs/cad-trial-20261012')
    out.mkdir(parents=True,exist_ok=True)
    (out/'five-layer.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


@pytest.mark.parametrize('kind,color,angle,allowed', [('2x2x1','yellow',0,True),
    ('2x2x1','blue',0,True), ('2x3x1','yellow',0,True), ('2x3x1','blue',0,True),
    ('1x2x1','red',0,True), ('1x2x1','red',90,True)])
def test_final_mvp_parts_pass_mock_runtime_without_physical_completion(kind,color,angle,allowed,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    result = cad_trial.run_mock(dict(design_version=1,blocks=[block(kind,color,angle)]),ROOT)
    assert len(result['documents']) == 1, result.get('reason')
    assert result['documents'][0]['motion']['status'] == 'CANDIDATE'
    if allowed:
        assert result['status'] == 'TRIAL_EXECUTION_FINISHED', result['reason']
    assert not result['assembly_completion'] and not result['vision_confirmed']
    out = Path('logs/cad-trial-20261012')
    out.mkdir(parents=True,exist_ok=True)
    (out/f'{color}-{kind}-{angle}.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


def test_supply_anchor_is_latest_blue_5mm_and_order_is_preserved():
    inputs = cad_trial.measured_inputs(ROOT)
    from planning_trial.supply_pick import calculate_supply_pick
    source = cad_trial.read(ROOT/'fixtures/teaching_sources/supply_slot1_grasp_summary.json')['current_tcp_posx']
    supply = inputs['frame']['calculation_profiles']['supply']
    first = calculate_supply_pick('2x2x1','blue',1,profile=supply)['pickup_tcp_pose']['xyz_abc']
    assert first == pytest.approx(source)
    assert first[2] == source[2]  # no repeated -3mm shift
    assert [(c['color'],c['brick_type']) for c in supply['columns']] == [
        ('yellow','2x2x1'),('yellow','2x3x1'),('blue','2x2x1'),('blue','2x3x1')]
    red6 = calculate_supply_pick('1x2x1','red',6,profile=supply)
    red7 = calculate_supply_pick('1x2x1','red',7,profile=supply)
    assert (red6['column_index'],red6['slot_within_column']) == (1,6)
    assert (red7['column_index'],red7['slot_within_column']) == (2,1)
    assert red6['grasp']['width_grid_cells'] == red7['grasp']['width_grid_cells'] == 2


def test_rotation_offset_uses_board_y_not_base_y():
    assembly = cad_trial.measured_inputs(ROOT)['frame']['calculation_profiles']['assembly']
    correction = cad_trial.rotation_correction(assembly,[6,6],turn=90)
    assert math.hypot(*correction) == pytest.approx(2.5)
    assert correction[0] < -2.49 and abs(correction[1]) < .02
    assert cad_trial.rotation_correction(assembly,[6,6],turn=-90) == correction
    assert cad_trial.rotation_correction(assembly,[6,6],turn=0) == [0.,0.]


def test_a_d_mismatch_holds_before_commands(monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    original = cad_trial.step_document
    def wrong(*args,**kwargs):
        doc = original(*args,**kwargs)
        doc['motion']['motion_proposal']['segments'][0]['waypoints'][2]['tcp_pose']['xyz_m'][0] += .01
        return doc
    monkeypatch.setattr(cad_trial,'step_document',wrong)
    result = cad_trial.run_mock(dict(design_version=1,blocks=[block()]),ROOT)
    assert result['status'] == 'HOLD' and 'A_D_POSE_DIFFERS' in result['reason']
    assert result['assumed_state']['blocks'] == []
    assert not any(e['event']=='EXECUTION_STARTED' for e in result['events'])


def test_stop_before_approval_has_no_robot_commands(monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    result = cad_trial.run_mock(dict(design_version=1,blocks=[block()]),ROOT,cancel=lambda:True)
    assert result['status']=='HOLD' and not result['completed_steps']
    assert result['events']==[] and result['documents']==[]


def test_mock_entry_rejects_live_llm_environment(monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','1')
    with pytest.raises(ValueError,match='offline test'):
        cad_trial.run_mock(dict(design_version=1,blocks=[block()]),ROOT)


def test_requested_color_stack_executes_five_mock_steps(monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    design=cad_trial.read('interfaces/fixtures/cad_trial_yellow_blue_five_layers.json')
    result=cad_trial.run_mock(design,ROOT)
    assert result['status']=='TRIAL_EXECUTION_FINISHED',result['reason']
    docs=result['documents']
    assert [(d['step']['block']['color'],d['step']['block']['layer']) for d in docs]==[
        ('yellow',1),('blue',2),('yellow',3),('blue',4),('yellow',5)]
    assert [int(d['step']['reservation']['slot_id'].rsplit('_',1)[1]) for d in docs]==[1,1,2,2,3]
    assert result['assumed_state']['blocks']==design['blocks']
    assert not result['b_called'] and not result['assembly_completion']
    moves=[e['data'] for e in result['events'] if e['event']=='MOVE_REQUEST']
    blends=[d for d in moves if d['segment']=='BLENDED_TRANSIT']
    assert len(blends)==10
    assert all(d['radius_mm']==30. and d['velocity']==[192.,192.]
               and d['acceleration']==[48.,48.] for d in blends)
    grips=[e['data']['width_mm'] for e in result['events'] if e['event']=='SINGLE_WRITER_GRIPPER']
    assert grips==[55.,35.,48.]*5
    label=None;pickup=[];approaches=[];precontacts=[]
    for e in result['events']:
        if e['event']=='MOVE_STARTED':label=e['data']['label']
        if e['event']=='MOVE_REQUEST' and label=='PICKUP_LOWER':pickup.append(e['data'])
        if e['event']=='MOVE_REQUEST' and label=='ASSEMBLY_APPROACH' and e['data']['segment']=='DESCENT':approaches.append(e['data'])
        if e['event']=='MOVE_REQUEST' and label=='PRE_CONTACT' and e['data']['segment']=='DESCENT':precontacts.append(e['data'])
    assert len(pickup)==5
    assert all(d['velocity']==[24.,24.] and d['acceleration']==[6.,6.] for d in pickup)
    assert len(approaches)==len(precontacts)==5
    assert all(d['velocity']==[24.,24.] and d['acceleration']==[6.,6.] for d in approaches)
    assert all(d['velocity']==[2.,2.] and d['acceleration']==[1.,1.] for d in precontacts)
    assert all(abs(a['target'][2]-b['target'][2]-10.)<1e-6 for a,b in zip(approaches,precontacts))
    out=Path('logs/cad-five-layer-20261012');out.mkdir(parents=True,exist_ok=True)
    (out/'five-layer.result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


def test_all_requested_supply_groups_follow_design_through_a_and_mock_d(monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    design=dict(design_version=1,blocks=[dict(brick_type=kind,color=color,x=11,y=11,layer=layer,orientation_deg=0)
        for layer,(kind,color) in enumerate([('2x3x1','yellow'),('2x3x1','blue'),
                             ('2x2x1','yellow'),('2x2x1','blue'),('1x2x1','red')],1)])
    result=cad_trial.run_mock(design,ROOT)
    assert result['status']=='TRIAL_EXECUTION_FINISHED',result.get('reason')
    assert len(result['completed_steps'])==5 and result['assumed_state']['blocks']==design['blocks']
    assert [(d['step']['block']['brick_type'],d['step']['block']['color']) for d in result['documents']]==[
        (b['brick_type'],b['color']) for b in design['blocks']]
    assert all(d['step']['reservation']['slot_id'].endswith('_01') for d in result['documents'])
    assert not result['b_called'] and not result['assembly_completion']
    out=Path('logs/cad-open60-20261012/all-types-mock-result.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
