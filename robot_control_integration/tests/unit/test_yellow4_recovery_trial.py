"""Stage7 synthetic contract/Fake tests; fixtures are never field evidence."""
from copy import deepcopy
import json
import subprocess
import sys
import numpy as np
import pytest
from app.yellow4_removal_trial import prepare_removal
from app.yellow4_seating_trial import prepare_seating
from app.yellow4_recovery_trial import prepare_recovery,prepare_cycle,execute_cycle
from app.yellow4_contact_trial import execute
from app.edge_first_seating import pose_matrix,matrix_pose,transform_points,rotate_about_contact_line
from scripts.yellow4_contact_trial import read_trial_evidence,ContactWindow
from test_yellow4_removal_trial import removal_inputs
from test_yellow4_seating_trial import seating_inputs,SeatingRobot
from test_yellow4_observation import ROOT,bundle
CONFIG=json.loads((ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/recovery_cycle.json').read_text())


def recovery_inputs(angle=5):
    b,c,m,e=removal_inputs();old=prepare_removal(b,c,m,e);old['sources']['seating_run']={'TEST_ONLY':True}
    d=SeatingRobot();d.s.update(posx=old['partial_geometry']['waypoints'][-1]['tcp_mm_zyz_deg'],gripper_status=2,gripper_width_mm=35,robot_mode=1)
    partial=dict(preview=old,result=dict(backend='REAL',physical_commands=20,gripper_release_commands=0,automatic_lift_or_return=False,
        status='PARTIAL_REMOVAL_COMMANDS_AND_OPERATOR_REPORT_NOT_INDEPENDENTLY_VERIFIED',
        operator_release_observation='ONE_SIDE_RELEASED_REMAINING_ENGAGED',final_sample=deepcopy(d.s)),events=[
        dict(event='OPERATOR_OBSERVATION',data=dict(phase='REMOVAL_GRASP_RELATION_CHECK',answer='REMOVAL_GRASP_MATCH')),
        dict(event='OPERATOR_OBSERVATION',data=dict(phase='PARTIAL_REMOVAL_RESULT',answer='ONE_SIDE_RELEASED_REMAINING_ENGAGED'))])
    s=deepcopy(CONFIG);r=s['recovery'];r['contact']=dict(c['contact']);r.update(parameter_source='TEST_ONLY',rotation_deg=angle,angular_step_deg=1,
        completion_axis=dict(source_kind='OPERATOR_FIELD_MEASUREMENT',evidence_ref='TEST_ONLY',coordinate_frame='BASE',
            frame_pose_in_base_mm_zyz_deg=[0,0,0,0,0,0],points_mm=[[0,-6,0],[5,6,0]]),clearance_mm=15,
        field_review=dict(evidence_ref='TEST_ONLY',partial_contact_state_checked=True,axis_after_partial_checked=True,
            grasp_maintained=True,board_fixed=True,conditions_confirmed=True),
        release_validation=dict(method='VALIDATED_OPERATOR_OBSERVATION',evidence_ref='TEST_ONLY',validated_on_real_logs=True),
        recovery_route_source='TEST_ONLY',recovery_waypoints=[
            dict(frame='BASE',evidence_ref='TEST_ONLY',tcp_pose_mm_zyz_deg=[-30,-20,200,10,175,20]),
            dict(frame='BASE',evidence_ref='TEST_ONLY',tcp_pose_mm_zyz_deg=[-30,-20,50,10,175,20])])
    s['cycle']['reset_source']='TEST_ONLY'
    s['cycle']['return_zone_source']='TEST_ONLY'
    return b,s,partial,d


def recovery_trial(angle=5,override=None,driver=None):
    b,s,e,d=recovery_inputs(angle);d=driver or d;p=prepare_recovery(b,s,e);events=[]
    def operator(phase,allowed,poll):
        poll()
        if override:
            answer=override(phase,d,p)
            if answer is not None:return answer
        return allowed[0]
    r=execute(d,p,'assembly',lambda k,x:events.append((k,deepcopy(x))),lambda *_:None,operator,sleep=lambda _:None)
    return d,p,r,events


def test_pending_input_has_no_axis_recovery_or_automatic_release_assumptions():
    b=bundle();old=deepcopy(b);p=prepare_recovery(b,CONFIG)
    assert b==old and p['stage']==7 and not p['execution_ready'] and p['physical_commands']==0
    assert 'stage6_real_partial_holding_run' in p['missing_measurements'] and not p['automatic_release_classifier']
    assert p['contact']['force_stop_n'] is None and p['grasp_mode']=='STANDARD' and 'completion_geometry' not in p


@pytest.mark.parametrize('angle',[5,-5])
def test_independent_completion_axis_signed_geometry_keeps_rigid_grasp_and_contact_line(angle):
    b,s,e,d=recovery_inputs(angle);old=deepcopy((b,s,e));p=prepare_recovery(b,s,e);g=p['completion_geometry']
    assert p['execution_ready'] and (b,s,e)==old
    assert g['contact_line_points_mm']!=p['stage6_geometry']['contact_line_points_mm']
    for point in g['waypoints']:
        block=pose_matrix(point['block_mm_zyz_deg'])
        assert pose_matrix(point['tcp_mm_zyz_deg'])@pose_matrix(g['tcp_to_block_pose_mm_zyz_deg'])==pytest.approx(block)
        assert transform_points(block,g['contact_line_points_in_block_mm'])==pytest.approx(np.array(g['contact_line_points_mm']))
    d,p,r,events=recovery_trial(angle)
    labels=[x['label'] for k,x in events if k=='MOVE_REQUEST']
    assert 'RELEASED_VERTICAL_CLEARANCE' in labels and labels[-1]=='RECOVERY_ROUTE_001'
    assert d.grips==[(60,40)] and r['physical_commands']==0 and not r['removal_completion']
    order=[x['phase'] for k,x in events if k=='OPERATOR_OBSERVATION']
    assert order.index('ALL_STUDS_RELEASE_VERIFICATION')<order.index('RECOVERY_RELEASE_INSPECTION')
    assert r['operator_target_empty_and_board_stable'] and not r['all_studs_released_independently_verified']
    rise=next(x['target'] for k,x in events if k=='MOVE_REQUEST' and x['label']=='RELEASED_VERTICAL_CLEARANCE')
    free=next(x['sample']['posx'] for k,x in events if k=='LIFT_PERMISSION')
    assert rise[:2]+rise[3:]==free[:2]+free[3:] and rise[2]==free[2]+15


@pytest.mark.parametrize('problem',['fake','all','none','empty_pad','tool','grasp','observations','provenance','validation'])
def test_invalid_partial_or_unvalidated_release_is_not_ready(problem):
    b,s,e,d=recovery_inputs()
    if problem=='validation':
        s['recovery']['release_validation']['validated_on_real_logs']=False
        assert not prepare_recovery(b,s,e)['execution_ready'];return
    if problem=='fake':e['result']['backend']='FAKE'
    elif problem=='all':e['result']['operator_release_observation']='ALL_RELEASED_OBSERVED'
    elif problem=='none':e['result']['operator_release_observation']='NO_RELEASE_OBSERVED'
    elif problem=='empty_pad':e['result']['final_sample']['gripper_width_mm']=4
    elif problem=='tool':e['preview']['connection']['tool']='wrong'
    elif problem=='grasp':e['preview']['grasp_mode']='HUMAN_REPLACEMENT'
    elif problem=='observations':e['events']=[]
    else:e['preview']['sources'].pop('seating_run')
    with pytest.raises(ValueError):prepare_recovery(b,s,e)


@pytest.mark.parametrize('changed',['xy','rotation','width','status'])
def test_changed_live_state_has_no_mode_move_or_gripper_writes(changed):
    _,_,_,d=recovery_inputs()
    if changed=='xy':d.s['posx'][0]+=.2
    elif changed=='rotation':d.s['posx'][3]+=1
    elif changed=='width':d.s['gripper_width_mm']+=2
    else:d.s['gripper_status']=0
    with pytest.raises(RuntimeError):recovery_trial(driver=d)
    assert not d.moves and not d.grips and not d.calls and d.stops==0


@pytest.mark.parametrize('fault',['unknown_release','force','moment','slip','ack','board_lift','contact_moved'])
def test_completion_fault_does_not_lift_open_retry_or_reverse_axis(fault):
    _,_,_,d=recovery_inputs()
    def operator(phase,d,p):
        if phase=='CURRENT_PARTIAL_STATE_CHECK':
            if fault=='ack':d.fail=True
            return None
        if phase!='ALL_STUDS_RELEASE_VERIFICATION':return None
        if fault=='force':d.s['wrench'][0]=p['contact']['force_stop_n']
        elif fault=='moment':d.s['wrench'][3]=p['contact']['moment_delta_stop_nm']
        elif fault=='slip':d.s['gripper_width_mm']+=3
        else:raise RuntimeError(fault.upper())
    with pytest.raises((RuntimeError,TimeoutError)):recovery_trial(driver=d,override=operator)
    assert not d.grips and d.stops==1
    assert all(v[0][2]<100 for v in d.moves)


def cycle_inputs():
    b,s,e,_=recovery_inputs();recovery=prepare_recovery(b,s,e)
    a,c,t,air,partial=seating_inputs();seating=prepare_seating(a,c,t,air,partial)
    removal=deepcopy(e['preview']);s['cycle']['repeat_count']=2
    return s,prepare_cycle(s,seating,removal,recovery)


def run_cycle(override=None):
    s,p=cycle_inputs();d=SeatingRobot();events=[];phases=[];vision=[]
    def observe(poll):
        poll();vision.append(True);return dict(pickup_tcp_candidate=p['seating_plan']['pickup_tcp'],
            supply_decision=dict(vision_attempted=True,recognized=False,center_assist_applied=False,reason='TEST_FALLBACK'))
    def operator(phase,allowed,poll):
        sample=poll()
        if override:
            answer=override(phase,d,p,events,phases)
            if answer is not None:return answer
        if phase=='STUD_ENGAGEMENT_CHECK':
            z=p['seating_plan']['partial_geometry']['waypoints'][0]['tcp_mm_zyz_deg'][2]
            return 'STUD_ENGAGED' if sample['posx'][2]<=z+.01 else 'NO_ENGAGEMENT_NEXT'
        return allowed[0]
    r=execute_cycle(d,p,'home',lambda k,x:events.append((k,deepcopy(x))),observe,operator,lambda active:phases.append(active['stage']),sleep=lambda _:None)
    return d,p,r,events,phases,vision


def test_two_cycles_use_one_backend_fresh_partial_state_and_vision_each_iteration():
    d,p,r,events,phases,vision=run_cycle()
    assert phases==[5,6,7,5,6,7] and len(vision)==2 and d.stops==0
    assert d.grips==[(35,40),(60,40),(35,40),(60,40)]*2
    assert r['completed_iterations']==2 and r['physical_commands']==0 and not r['removal_completion']
    assert any(k=='OPERATOR_OBSERVATION' and x['phase']=='CYCLE_RESET_INSPECTION' for k,x in events)
    assert [x['preview']['reference_sample']['posx'] for k,x in events if k=='CYCLE_PHASE' and x['phase']=='recovery']==[
        x['final_sample']['posx'] for k,x in events if k=='RESULT' and x.get('cycle_phase')=='removal']


@pytest.mark.parametrize('fault',['reset_unknown','partial_not_qualified','completion_stop'])
def test_cycle_never_retries_next_phase_or_iteration_after_unknown_or_stop(fault):
    saved={}
    def operator(phase,d,p,events,phases):
        saved.update(driver=d,events=events,phases=phases)
        if fault=='reset_unknown' and phase=='CYCLE_RESET_INSPECTION':return 'UNKNOWN'
        if fault=='partial_not_qualified' and phase=='PARTIAL_REMOVAL_RESULT':return 'ALL_RELEASED_OBSERVED'
        if fault=='completion_stop' and phase=='ALL_STUDS_RELEASE_VERIFICATION':raise RuntimeError('OPERATOR_UNKNOWN')
    with pytest.raises(RuntimeError):run_cycle(operator)
    d=saved['driver'];phases=saved['phases']
    assert phases==([5,6] if fault=='partial_not_qualified' else [5,6,7])
    assert d.stops==(1 if fault=='completion_stop' else 0)
    assert len(d.grips)==(4 if fault=='reset_unknown' else 3)
    assert any(k=='CYCLE_ABORT' for k,_ in saved['events'])


def test_completion_axis_frame_and_fresh_origin_do_not_translate_axis():
    b,s,e,d=recovery_inputs();expected=prepare_recovery(b,s,e)
    frame=pose_matrix([20,30,5,25,0,0]);axis=s['recovery']['completion_axis']
    axis.update(coordinate_frame='BOARD',frame_pose_in_base_mm_zyz_deg=matrix_pose(frame),
        points_mm=transform_points(np.linalg.inv(frame),axis['points_mm']).tolist())
    p=prepare_recovery(b,s,e)
    assert p['completion_geometry']['contact_line_points_mm']==pytest.approx(np.array(expected['completion_geometry']['contact_line_points_mm']))
    d.s['posx'][0]+=.02;start=d.s['posx'].copy();events=[]
    execute(d,p,'assembly',lambda k,x:events.append((k,x)),lambda *_:None,lambda phase,allowed,poll:(poll() and allowed[0]),sleep=lambda _:None)
    end=next(x['target'] for k,x in events if k=='MOVE_REQUEST' and x['label']=='COMPLETE_RELEASE_004')
    assert pose_matrix(end)==pytest.approx(pose_matrix(rotate_about_contact_line(start,p['completion_geometry']['contact_line_points_mm'],5)))


def test_popup_evidence_uses_captured_phase_snapshot_not_mutable_next_phase(monkeypatch):
    import scripts.yellow4_contact_trial as module
    b,s,e,d=recovery_inputs();plan=prepare_recovery(b,s,e);w=ContactWindow.__new__(ContactWindow)
    w.bundle=b;w.plan=dict(plan,stage=6);w.grid=None
    monkeypatch.setattr(module,'analyze',lambda frame,*args,**kwargs:(frame.copy(),{}))
    captured={}
    def save(path,frame,canvas,bundle,report,**kwargs):captured.update(report);return path
    monkeypatch.setattr(module,'save_capture',save)
    w.save_evidence('TEST_ONLY',np.zeros((20,20,3),np.uint8),d.s,None,0,0,'assembly','RESULT',[],None,plan)
    assert captured['stage']==7 and captured['planned_angle_basis']=='DELTA_FROM_PARTIAL_REFERENCE'


def test_cycle_rejects_changed_qualification_conditions_and_press_terminal():
    s,p=cycle_inputs();p['removal_plan']['contact']['linear_velocity_mm_s']+=1
    with pytest.raises(ValueError,match='CONDITIONS_CHANGED'):prepare_cycle(s,p['seating_plan'],p['removal_plan'],p['recovery_plan'])
    s,p=cycle_inputs();p['seating_plan']['press']['enabled']=True
    assert not prepare_cycle(s,p['seating_plan'],p['removal_plan'],p['recovery_plan'])['execution_ready']


@pytest.mark.parametrize('count',[0,-1,True,1.5])
def test_invalid_repeat_count_rejected(count):
    s,p=cycle_inputs();s['cycle']['repeat_count']=count
    with pytest.raises(ValueError):prepare_cycle(s,p['seating_plan'],p['removal_plan'],p['recovery_plan'])


def test_stage7_and_cycle_cli_previews_are_node_free_and_cannot_execute_pending_input(tmp_path):
    for script,args in [('yellow4_contact_trial.py',['--stage','7']),('yellow4_cycle_trial.py',[])]:
        command=[sys.executable,str(ROOT/'robot_control_integration/scripts'/script),*args,'--output',str(tmp_path/script)]
        result=subprocess.run(command,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        plan=json.loads((tmp_path/script/'preview.json').read_text())
        assert not plan['execution_ready'] and plan['physical_commands']==0
        rejected=subprocess.run([*command,'--execute'],capture_output=True,text=True)
        assert rejected.returncode==2 and 'Traceback' not in rejected.stderr
    (tmp_path/'events.jsonl').write_text(json.dumps(dict(event='CYCLE_ABORT',data={}))+'\n')
    with pytest.raises(ValueError,match='ABORTED'):read_trial_evidence(tmp_path,'REMOVAL')


def test_complete_synthetic_cycle_files_build_preview_and_paths_without_device(tmp_path):
    # All files are temporary TEST_ONLY contracts, including REAL-labelled test records.
    b,s,e,d=recovery_inputs();a,c,t,air,part=seating_inputs();_,rc,rm,seated=removal_inputs()
    def write(name,value):
        path=tmp_path/(name+'.TEST_ONLY.json');path.write_text(json.dumps(value));return str(path)
    def write_run(name,evidence,context=None):
        path=tmp_path/name;path.mkdir()
        (path/'preview.json').write_text(json.dumps(evidence['preview']))
        events=deepcopy(evidence.get('events',[]))
        if context is not None:events.append(dict(event='TRIAL_CONTEXT',data=context))
        events.append(dict(event='RESULT',data=evidence['result']))
        (path/'events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n');return str(path)
    s['cycle']['inputs'].update(assembly_measurements=write('assembly-measurements',a['measurement']),
        removal_measurements=write('removal-measurements',rm),contact_settings=write('contact-settings',c),
        seating_settings=write('seating-settings',t),removal_settings=write('removal-settings',rc),
        air_run=write_run('air-run',air,air['context']),assembly_partial_run=write_run('assembly-partial',part),
        seating_run=write_run('seating-run',seated),removal_partial_run=write_run('removal-partial',e))
    config=write('cycle-settings',s)
    command=[sys.executable,str(ROOT/'robot_control_integration/scripts/yellow4_cycle_trial.py'),
        '--config',config,'--output',str(tmp_path/'preview'),'--repeat','2']
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    p=json.loads((tmp_path/'preview/preview.json').read_text())
    assert p['execution_ready'] and p['physical_commands']==0 and p['repeat_count']==2
    assert all((tmp_path/'preview'/(key+'-path.png')).exists() for key in ('seating_plan','removal_plan','recovery_plan'))
    assert p['cycle_settings']['repeat_count_source']=='USER_CLI_OVERRIDE'
