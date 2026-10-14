"""Stage6 synthetic contracts only; REAL-labelled fixtures are not field evidence."""
from copy import deepcopy
import json
import subprocess
import sys
import numpy as np
import pytest
from app.yellow4_removal_trial import prepare_removal,removal_route
from app.yellow4_contact_trial import execute
from app.yellow4_seating_trial import prepare_seating
from app.edge_first_seating import pose_matrix,matrix_pose,transform_points
from scripts.yellow4_contact_trial import read_trial_evidence,ContactWindow
from test_yellow4_seating_trial import seating_inputs,SeatingRobot
from test_yellow4_observation import ROOT,bundle
REMOVAL=json.loads((ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/removal_trial.json').read_text())


def removal_inputs(angle=3):
    b,c,s,air,partial=seating_inputs();old=prepare_seating(b,c,s,air,partial)
    old['sources'].update(air_run={'TEST_ONLY':True},partial_run={'TEST_ONLY':True})
    evidence=dict(preview=old,result=dict(backend='REAL',physical_commands=40,
        status='FULL_SEATING_COMMANDS_AND_OPERATOR_REPORT_NOT_INDEPENDENTLY_VERIFIED',operator_reported_seated=True,
        operator_reported_post_release_stable=True),events=[
            dict(event='OPERATOR_OBSERVATION',data=dict(phase='SEATING_RELEASE_INSPECTION',answer='SEATED_READY_TO_RELEASE')),
            dict(event='OPERATOR_OBSERVATION',data=dict(phase='POST_RELEASE_INSPECTION',answer='POST_RELEASE_STABLE'))])
    g=old['ground_geometry']
    m=dict(schema_version='yellow4-removal-measurement/1',source_kind='OPERATOR_FIELD_MEASUREMENT',
        evidence_ref='TEST_ONLY_NOT_FIELD',target=b['target'],tcp=b['connection']['tcp'],tool=b['connection']['tool'],
        grasp_id='INDEPENDENT_REMOVAL_TEST_ONLY',grasp_mode='STANDARD',pad_bottom_from_block_bottom_mm=5,
        coordinate_frame='BASE',frame_pose_in_base_mm_zyz_deg=[0,0,0,0,0,0],board_fixation_confirmed=True,
        regrasp_tcp_pose_mm_zyz_deg=[4,5,40,10,175,20],seated_block_pose_mm_zyz_deg=g['seated_reference_block_mm_zyz_deg'],
        block_geometry=g['block_geometry'],target_studs=dict(frame='BASE',centers_mm=g['target_stud_centers_mm']),
        close_mm=35,width_tolerance_mm=1,removal=dict(tilt_deg=angle,angular_step_deg=.5,
            contact_line=dict(frame='BASE',points_mm=[[-6,0,0],[6,5,0]])))
    config=deepcopy(REMOVAL);config['parameter_source']='TEST_ONLY_INDEPENDENT_REMOVAL_VALUES'
    config['contact']=dict(linear_velocity_mm_s=5,angular_velocity_deg_s=.8,linear_acceleration_mm_s2=10,
        angular_acceleration_deg_s2=1,force_stop_n=42,moment_delta_stop_nm=.7,width_drift_stop_mm=2,axis_registration_tolerance_mm=.5)
    config['field_review']=dict(evidence_ref='TEST_ONLY',current_seated_block_verified=True,board_fixed=True,
        regrasp_relation_checked=True,removal_axis_checked=True,conditions_confirmed=True)
    return bundle(),config,m,evidence


def run_removal(angle=3,empty='OPEN_EMPTY',report='ONE_SIDE_RELEASED_REMAINING_ENGAGED',override=None,driver=None,pad_status=2):
    b,s,m,e=removal_inputs(angle);p=prepare_removal(b,s,m,e);d=driver or SeatingRobot();events=[]
    if empty=='CLOSED_EMPTY_PAD':d.s.update(gripper_status=pad_status,gripper_width_mm=4)
    def operator(phase,allowed,poll):
        poll()
        if override:
            value=override(phase,d,p)
            if value is not None:return value
        if phase=='INITIAL_EMPTY_GRIPPER_CHECK':return empty
        if phase=='PARTIAL_REMOVAL_RESULT':return report
        return allowed[0]
    def forbidden(*_):raise AssertionError('removal must never pick from supply')
    r=execute(d,p,'home',lambda k,v:events.append((k,deepcopy(v))),forbidden,operator,sleep=lambda _:None)
    return d,p,r,events


def test_missing_real_data_does_not_prevent_development_preview_or_copy_assembly_candidates():
    b=bundle();before=deepcopy(b);p=prepare_removal(b,REMOVAL)
    assert not p['execution_ready'] and p['physical_commands']==0 and p['stage']==6 and b==before
    assert p['contact']['force_stop_n'] is None and p['grasp_mode']=='STANDARD' and p['intended_pad_bottom_height_mm']==5
    assert 'stage5_real_seating_run_and_post_release_observation' in p['missing_measurements']
    assert 'assembly_contact_axis' not in p['missing_measurements'] and 'partial_geometry' not in p


@pytest.mark.parametrize('zone',['home','supply','assembly'])
def test_existing_movel_transits_end_above_independent_regrasp(zone):
    b,s,m,e=removal_inputs();p=prepare_removal(b,s,m,e);route=removal_route(p,[100,50,200,0,180,0],zone)
    labels=[label for label,_ in route]
    if zone!='assembly':assert labels[:4]==['START_VERTICAL_LIFT','SUPPLY_TRANSIT','BODY_BYPASS','ASSEMBLY_OBSERVATION']
    assert route[-1][0]=='REGRASP_ABOVE' and route[-1][1][2]==p['regrasp_tcp'][2]+20
    assert route[-1][1][:2]+route[-1][1][3:]==p['regrasp_tcp'][:2]+p['regrasp_tcp'][3:]
    assert p['rates']['transit']==120 and p['rates']['vertical']==12


@pytest.mark.parametrize('angle',[3,-3])
def test_separate_regrasp_relation_axis_and_direction_preserve_contact_line(angle):
    b,s,m,e=removal_inputs(angle);original=deepcopy((b,s,m,e));p=prepare_removal(b,s,m,e);g=p['partial_geometry']
    assert p['execution_ready'] and (b,s,m,e)==original
    assert p['regrasp_tcp']!=e['preview']['pickup_tcp'] and p['grasp_id']!=e['preview']['grasp_id']
    assert g['contact_line_points_mm']!=e['preview']['ground_geometry']['contact_line_points_mm']
    assert [g['waypoints'][0]['tilt_deg'],g['waypoints'][-1]['tilt_deg']]==[0,angle]
    for point in g['waypoints']:
        block=pose_matrix(point['block_mm_zyz_deg'])
        assert pose_matrix(point['tcp_mm_zyz_deg'])@pose_matrix(g['tcp_to_block_pose_mm_zyz_deg'])==pytest.approx(block)
        assert transform_points(block,g['contact_line_points_in_block_mm'])==pytest.approx(np.array(g['contact_line_points_mm']))


def test_named_board_frame_transform_is_applied_to_tcp_studs_and_axis():
    b,s,m,e=removal_inputs();expected=prepare_removal(b,s,m,e)['partial_geometry'];frame=pose_matrix([20,30,4,25,0,0]);inv=np.linalg.inv(frame)
    m['coordinate_frame']='BOARD';m['frame_pose_in_base_mm_zyz_deg']=matrix_pose(frame)
    for key in ('regrasp_tcp_pose_mm_zyz_deg','seated_block_pose_mm_zyz_deg'):m[key]=matrix_pose(inv@pose_matrix(m[key]))
    m['target_studs']=dict(frame='BOARD',centers_mm=transform_points(inv,m['target_studs']['centers_mm']).tolist())
    m['removal']['contact_line']=dict(frame='BOARD',points_mm=transform_points(inv,m['removal']['contact_line']['points_mm']).tolist())
    g=prepare_removal(b,s,m,e)['partial_geometry']
    for a,w in zip(g['waypoints'],expected['waypoints']):assert pose_matrix(a['tcp_mm_zyz_deg'])==pytest.approx(pose_matrix(w['tcp_mm_zyz_deg']))
    m['target_studs']['frame']='CAMERA'
    with pytest.raises(ValueError,match='FRAME'):prepare_removal(b,s,m,e)


@pytest.mark.parametrize('problem',['fake','observations','provenance','tool','height','board','condition','synthetic','width'])
def test_unconfirmed_or_mismatched_field_data_is_not_execution_ready(problem):
    b,s,m,e=removal_inputs()
    if problem=='board':
        m['board_fixation_confirmed']=False;assert not prepare_removal(b,s,m,e)['execution_ready'];return
    if problem=='fake':e['result']['backend']='FAKE'
    elif problem=='observations':e['events']=[]
    elif problem=='provenance':e['preview']['sources'].pop('partial_run')
    elif problem=='tool':m['tool']='wrong'
    elif problem=='height':m['pad_bottom_from_block_bottom_mm']=15
    elif problem=='condition':s['contact']['angular_velocity_deg_s']=float('nan')
    elif problem=='synthetic':m['source_kind']='SYNTHETIC'
    else:m['close_mm']=4
    with pytest.raises(ValueError):prepare_removal(b,s,m,e)


@pytest.mark.parametrize('empty',['OPEN_EMPTY','CLOSED_EMPTY_PAD'])
@pytest.mark.parametrize('report',['ONE_SIDE_RELEASED_REMAINING_ENGAGED','ALL_RELEASED_OBSERVED','NO_RELEASE_OBSERVED'])
def test_partial_trial_distinguishes_empty_pad_and_terminal_observation_without_lift(empty,report):
    d,p,r,events=run_removal(empty=empty,report=report)
    assert d.grips==([(60,40),(35,40)] if empty=='CLOSED_EMPTY_PAD' else [(35,40)])
    assert r['operator_release_observation']==report and not r['removal_completion'] and not r['automatic_lift_or_return']
    assert r['physical_commands']==r['gripper_release_commands']==r['press_commands']==0 and d.stops==0
    moves=[data for event,data in events if event=='MOVE_REQUEST']
    assert moves[-1]['label'].startswith('PARTIAL_REMOVAL_') and d.moves[-1][0]==r['final_sample']['posx']
    assert not any('SUPPLY_BLOCK' in x['label'] or 'RETURN' in x['label'] for x in moves)
    assert all('so3_error_deg' in x for event,x in events if event=='MOTION_SAMPLE')
    assert moves[-1]['velocity']==[p['contact']['linear_velocity_mm_s'],p['contact']['angular_velocity_deg_s']]


@pytest.mark.parametrize('fault',['force','moment','slip','unknown','ack','lift','moved'])
def test_faults_preserve_grasp_and_never_open_retry_or_lift(fault):
    d=SeatingRobot()
    def change(phase,d,p):
        if phase!='PARTIAL_REMOVAL_READY':return None
        if fault=='force':d.s['wrench'][0]=p['contact']['force_stop_n']
        elif fault=='moment':d.s['wrench'][3]=p['contact']['moment_delta_stop_nm']
        elif fault=='slip':d.s['gripper_width_mm']+=p['contact']['width_drift_stop_mm']
        elif fault=='ack':d.fail=True
        else:raise RuntimeError('OPERATOR_'+fault.upper())
        return 'REMOVAL_PIVOT_READY'
    with pytest.raises((RuntimeError,TimeoutError)):run_removal(driver=d,override=change)
    assert d.grips==[(35,40)] and d.stops==1


def test_status2_does_not_skip_empty_context_or_regrasp_and_wrong_context_has_no_writes():
    d=SeatingRobot();d.s.update(gripper_status=2,gripper_width_mm=35)
    with pytest.raises(RuntimeError,match='EMPTY_STATE'):run_removal(driver=d)
    assert not d.moves and not d.grips and d.stops==0


def test_closed_empty_pad_status0_is_supported_and_negative_rotation_executes():
    d,p,r,events=run_removal(angle=-3,empty='CLOSED_EMPTY_PAD',pad_status=0)
    assert d.grips==[(60,40),(35,40)] and r['final_model_tilt_deg']==-3
    assert pose_matrix(r['final_sample']['posx'])==pytest.approx(pose_matrix(p['partial_geometry']['waypoints'][-1]['tcp_mm_zyz_deg']))


def test_changed_regrasp_keeps_block_orbit_and_human15_has_no_supply_z_substitution():
    b,s,m,e=removal_inputs();p=prepare_removal(b,s,m,e);supply=deepcopy(b['baseline_supply_tcp'])
    b.update(grasp_mode='HUMAN_REPLACEMENT',intended_pad_bottom_height_mm=15)
    m.update(grasp_mode='HUMAN_REPLACEMENT',pad_bottom_from_block_bottom_mm=15)
    m['regrasp_tcp_pose_mm_zyz_deg']=[8,7,49,10,175,20]
    new=prepare_removal(b,s,m,e)
    assert pose_matrix(new['regrasp_tcp'])==pytest.approx(pose_matrix(m['regrasp_tcp_pose_mm_zyz_deg']),abs=1e-9)
    assert b['baseline_supply_tcp']==supply
    assert new['regrasp_tcp'][2]!=p['regrasp_tcp'][2]+10
    for a,w in zip(new['partial_geometry']['waypoints'],p['partial_geometry']['waypoints']):
        assert pose_matrix(a['block_mm_zyz_deg'])==pytest.approx(pose_matrix(w['block_mm_zyz_deg']))


def test_cli_accepts_independent_removal_measurements_and_saved_seating_run(tmp_path):
    b,s,m,e=removal_inputs();run=tmp_path/'seating-run';run.mkdir()
    (run/'preview.json').write_text(json.dumps(e['preview']))
    (run/'events.jsonl').write_text('\n'.join(json.dumps(event) for event in [*e['events'],dict(event='RESULT',data=e['result'])])+'\n')
    config=tmp_path/'config.TEST_ONLY.json';config.write_text(json.dumps(s))
    measured=tmp_path/'measurement.TEST_ONLY.json';measured.write_text(json.dumps(m))
    cli=ROOT/'robot_control_integration/scripts/yellow4_contact_trial.py'
    command=[sys.executable,str(cli),'--stage','6','--config',str(config),'--measurements',str(measured),
        '--seating-run',str(run),'--output',str(tmp_path/'preview')]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    p=json.loads((tmp_path/'preview/preview.json').read_text())
    assert p['execution_ready'] and p['physical_commands']==0 and (tmp_path/'preview/removal-path.png').exists()
    assert pose_matrix(p['regrasp_tcp'])==pytest.approx(pose_matrix(m['regrasp_tcp_pose_mm_zyz_deg']),abs=1e-9)
    rejected=subprocess.run([*command,'--execute','--confirm-hand-clear','--confirm-route-clear','--confirm-target-empty'],capture_output=True,text=True)
    assert rejected.returncode==2 and '--confirm-target-seated required' in rejected.stderr


def test_axis_is_not_moved_to_match_regrasp_drift():
    d=SeatingRobot()
    def change(phase,d,p):
        if phase=='PARTIAL_REMOVAL_READY':d.s['posx'][0]+=1
    with pytest.raises(RuntimeError,match='OUTSIDE_REGISTERED_AXIS'):run_removal(driver=d,override=change)
    assert d.grips==[(35,40)] and d.stops==1


def test_cli_no_ros_and_aborted_seating_cannot_be_used(tmp_path):
    cli=ROOT/'robot_control_integration/scripts/yellow4_contact_trial.py'
    result=subprocess.run([sys.executable,str(cli),'--stage','6','--output',str(tmp_path/'preview')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    p=json.loads((tmp_path/'preview/preview.json').read_text());assert p['stage']==6 and not p['execution_ready']
    (tmp_path/'events.jsonl').write_text(json.dumps(dict(event='ABORT',data={}))+'\n')
    with pytest.raises(ValueError,match='ABORTED_SEATING'):read_trial_evidence(tmp_path,'SEATING')


def test_popup_records_removal_categories_and_never_enables_lift():
    w=ContactWindow.__new__(ContactWindow);w.active={};w.answer=None
    w.key(ord('W'));assert w.answer is None
    w.active={'I':'ONE_SIDE_RELEASED_REMAINING_ENGAGED','W':'ALL_RELEASED_OBSERVED','N':'NO_RELEASE_OBSERVED'}
    for key,value in w.active.items():w.key(ord(key));assert w.answer==value
    for key,reason in [('L','BOARD_LIFT'),('S','GRIP_SLIP'),('M','CONTACT_POINT_MOVED'),('U','UNKNOWN')]:
        with pytest.raises(RuntimeError,match=reason):w.key(ord(key))


def test_stage6_popup_projects_independent_removal_path_not_seating(monkeypatch):
    import scripts.yellow4_contact_trial as module
    b,s,m,e=removal_inputs();w=ContactWindow.__new__(ContactWindow);w.bundle=b;w.plan=prepare_removal(b,s,m,e);w.grid=None
    image=np.zeros((40,40,3),np.uint8);points=[]
    monkeypatch.setattr(module,'analyze',lambda frame,*args,**kwargs:(frame.copy(),dict(grid_reference=dict(T_base_from_camera_mm=np.eye(4).tolist()))))
    def project(values,*_):points.append(values);return np.full((len(values),2),10.),np.ones(len(values),bool)
    monkeypatch.setattr(module,'project_base',project)
    _,report=w.analyze_frame(image,{},dict(k=[],d=[]),'assembly',[],None)
    assert points[0]==[p['tcp_mm_zyz_deg'][:3] for p in w.plan['partial_geometry']['waypoints']]
    assert points[1]==w.plan['partial_geometry']['contact_line_points_mm']
    assert report['path_operation']=='removal' and report['planned_partial_tilt_deg']==[0,3]
