"""Synthetic contracts only; no robot/field measurement files are generated."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from app.yellow4_contact_trial import prepare_contact,execute
from app.yellow4_air_trial import prepare_air
from app.yellow4_observation import prepare
from app.edge_first_seating import pose_matrix,rotate_about_contact_line
from scripts.yellow4_contact_trial import ContactWindow,read_air_evidence
from test_yellow4_observation import ROOT,SETTINGS,bundle,measurement
from test_yellow4_air_trial import AIR,Fake
CONTACT=json.loads((ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/contact_trial.json').read_text())


def inputs(angle=10):
    b=bundle();m=measurement(b);m['operations']['removal']=None;m['operations']['assembly']['tilt_deg']=angle
    b=prepare(ROOT,SETTINGS,m);s=deepcopy(CONTACT)
    s['air_trial_review']=dict(evidence_ref='TEST_ONLY_NOT_FIELD',arc_observed=True,grip_maintained=True)
    air=dict(result=dict(status='AIR_ROUTE_COMMANDS_COMPLETED_NOT_INDEPENDENTLY_VERIFIED',backend='REAL',physical_commands=20),
        context=dict(empty_gripper_trial=False),preview=prepare_air(b,AIR))
    return b,s,air


class Robot(Fake):
    def __init__(self):
        super().__init__();self.s.update(gripper_status=0,gripper_width_mm=60.);self.grips=[]
    def command_gripper(self,width,force):
        self.grips.append((width,force));self.s.update(gripper_status=2,gripper_width_mm=35.)


def trial(d=None,operator_override=None,angle=10,vision_shift=(0,0)):
    b,s,air=inputs(angle);p=prepare_contact(b,s,air);d=d or Robot();events=[]
    def observe(poll):
        poll()
        target=b['selected_pickup_tcp_candidate'].copy();target[:2]=(np.array(target[:2])+vision_shift).tolist()
        return dict(pickup_tcp_candidate=target,supply_decision=dict(vision_attempted=True,recognized=bool(any(vision_shift)),
            center_assist_applied=bool(any(vision_shift)),reason=None if any(vision_shift) else 'NO_STUD_CENTER_FALLBACK'))
    def operator(phase,allowed,poll):
        sample=poll()
        if operator_override:
            answer=operator_override(phase,sample,d,p)
            if answer is not None:return answer
        if phase=='STUD_ENGAGEMENT_CHECK':
            z=p['partial_geometry']['waypoints'][0]['tcp_mm_zyz_deg'][2]
            return 'STUD_ENGAGED' if sample['posx'][2]<=z+.01 else 'NO_ENGAGEMENT_NEXT'
        return allowed[0]
    result=execute(d,p,'home',lambda e,x:events.append((e,deepcopy(x))),observe,operator,sleep=lambda _:None)
    return d,p,result,events


def test_current_preview_keeps_unknown_fields_and_does_not_require_removal():
    b=bundle();original=deepcopy(b);p=prepare_contact(b,CONTACT)
    assert not p['execution_ready'] and p['physical_commands']==0 and b==original
    assert 'removal_contact_axis' not in p['missing_measurements']
    assert 'stage3_real_air_run' in p['missing_measurements']
    assert p['pickup_tcp']==b['baseline_supply_tcp'] and p['intended_pad_bottom_height_mm']==5
    assert p['contact']['linear_velocity_mm_s']==6 and p['contact']['angular_velocity_deg_s']==1
    assert p['engagement_classifier']=='OPERATOR_OBSERVATION_NOT_FORCE_THRESHOLD'


@pytest.mark.parametrize('angle',[10,-10])
def test_partial_geometry_keeps_axis_and_rigid_relation_both_directions(angle):
    b,s,air=inputs(angle);old=deepcopy(b);p=prepare_contact(b,s,air);g=p['partial_geometry']
    assert p['execution_ready'] and b==old
    assert abs(g['waypoints'][-1]['tilt_deg'])==8 and g['waypoints'][0]['tilt_deg']==angle
    grasp=pose_matrix(g['tcp_to_block_pose_mm_zyz_deg'])
    line=np.array(g['contact_line_points_mm']);local=np.c_[g['contact_line_points_in_block_mm'],np.ones(2)].T
    for point in g['waypoints']:
        assert pose_matrix(point['tcp_mm_zyz_deg'])@grasp==pytest.approx(pose_matrix(point['block_mm_zyz_deg']),abs=1e-8)
        assert (pose_matrix(point['block_mm_zyz_deg'])@local)[:3].T==pytest.approx(line,abs=1e-8)
    assert not p['automatic_leveling_during_intentional_tilt'] and not p['assembly_completion']


@pytest.mark.parametrize('field,value',[('partial_rotation_deg',10),('linear_velocity_mm_s',0),('force_stop_n',float('nan')),('entry_clearance_mm',21)])
def test_invalid_conditions_and_full_seating_rejected(field,value):
    b,s,air=inputs();s['contact'][field]=value
    with pytest.raises(ValueError):prepare_contact(b,s,air)


def test_air_completion_scope_and_operator_review_are_not_fabricated():
    b,s,air=inputs();s['air_trial_review']=None
    assert not prepare_contact(b,s,air)['execution_ready']
    for mutate in (lambda a:a['context'].update(empty_gripper_trial=True),lambda a:a['result'].update(backend='FAKE'),
        lambda a:a['preview']['ground_geometry']['contact_line_points_mm'][0].__setitem__(0,9)):
        a=deepcopy(air);mutate(a)
        with pytest.raises(ValueError):prepare_contact(b,CONTACT,a)


def test_board_fixation_missing_holds_real_execution():
    b,s,air=inputs();m=measurement(bundle());m['board_fixation_confirmed']=False
    b=prepare(ROOT,SETTINGS,m)
    assert 'board_fixation' in prepare_contact(b,s,air)['missing_measurements']


def test_fake_supply_opencv_fallback_partial_only_and_grasp_kept():
    d,p,r,events=trial()
    assert d.grips==[(35,40)] and d.stops==0
    assert r['physical_commands']==0 and r['gripper_release_commands']==r['press_commands']==0
    assert not r['assembly_completion'] and r['remaining_tilt_deg']==8
    vision=next(x for e,x in events if e=='VISION_DECISION')
    assert next(x for e,x in events if e=='VISION_OBSERVATION_BEGIN')['vision_attempted'] is False
    assert vision['vision_attempted'] and not vision['recognized']
    assert vision['commanded_pickup_pose']==p['pickup_tcp']
    labels=[x['label'] for e,x in events if e=='MOVE_REQUEST']
    assert 'START_OBSERVATION_HIGH' in labels and 'BODY_BYPASS' in labels and 'ASSEMBLY_OBSERVATION' in labels
    assert not any('RELEASE' in label or 'PRESS' in label or 'RETURN_REFERENCE' in label for label in labels)
    requests=[x for e,x in events if e=='MOVE_REQUEST' and ('CONTACT' in x['label'] or 'PIVOT' in x['label'])]
    assert all(x['velocity']==[6,1] for x in requests)
    assert any('moment_delta_norm_nm' in x for e,x in events if e=='MOTION_SAMPLE')


def test_vision_assistance_changes_xy_without_raising_standard_grasp():
    d,p,r,events=trial(vision_shift=(1,-1))
    v=next(x for e,x in events if e=='VISION_DECISION')
    assert v['center_assist_applied'] and v['commanded_pickup_pose'][:2]==pytest.approx(np.array(p['pickup_tcp'][:2])+[1,-1])
    assert v['commanded_pickup_pose'][2:]==p['pickup_tcp'][2:]


def test_negative_rotation_and_registered_actual_contact_pose_used():
    _,p,r,events=trial(angle=-10)
    engagement=next(x['sample']['posx'] for e,x in events if e=='ENGAGEMENT_AXIS_CHECK')
    expected=rotate_about_contact_line(engagement,p['ground_geometry']['contact_line_points_mm'],2)
    from app.assembly_motion import pose_error
    assert max(pose_error(r['final_sample']['posx'],expected))<1e-6
    assert r['remaining_tilt_deg']==-8


def test_unknown_move_ack_stops_once_without_grip_or_resend():
    d=Robot();d.fail=True
    with pytest.raises(TimeoutError,match='ACK_UNKNOWN'):trial(d)
    assert len(d.moves)==1 and d.stops==1 and not d.grips


def test_contact_journal_failure_cannot_prevent_stop():
    b,s,a=inputs();d=Robot()
    def record(event,data):
        if event in ('MOTION_SAMPLE','ABORT'):raise OSError('JOURNAL_WRITE_FAILED')
    with pytest.raises(OSError,match='JOURNAL_WRITE_FAILED') as error:
        execute(d,prepare_contact(b,s,a),'home',record,lambda *_:None,lambda *_:None,sleep=lambda _:None)
    assert len(d.moves)==1 and d.stops==1 and not d.grips
    assert any('ABORT_LOGGING_FAILED' in note for note in error.value.__notes__)


def test_human15_requires_explicit_measured_supply_pose_not_plus10_fallback():
    obs=deepcopy(SETTINGS);obs['grasp_mode']='HUMAN_REPLACEMENT'
    b=prepare(ROOT,obs);m=measurement(b)
    m.update(grasp_mode='HUMAN_REPLACEMENT',pad_bottom_from_block_bottom_mm=15)
    b=prepare(ROOT,obs,m);s=deepcopy(CONTACT)
    s['air_trial_review']=dict(evidence_ref='TEST_ONLY',arc_observed=True,grip_maintained=True)
    air=dict(result=dict(status='AIR_ROUTE_COMMANDS_COMPLETED_NOT_INDEPENDENTLY_VERIFIED',backend='REAL',physical_commands=20),
        context=dict(empty_gripper_trial=False),preview=prepare_air(b,AIR))
    p=prepare_contact(b,s,air)
    assert not p['execution_ready'] and 'measured_human15_supply_pickup' in p['missing_measurements']
    pose=b['selected_pickup_tcp_candidate'].copy();pose[2]+=1  # Distinct test-only measurement, not +10 fallback.
    s['measured_supply_pickup']={k:m[k] for k in ('grasp_id','grasp_mode','pad_bottom_from_block_bottom_mm')}
    s['measured_supply_pickup'].update(evidence_ref='TEST_ONLY',tcp_pose_mm_zyz_deg=pose)
    assert prepare_contact(b,s,air)['pickup_tcp']==pose


@pytest.mark.parametrize('fault',['force','moment','slip','unknown','contact_moved','board_lift'])
def test_contact_fault_preserves_grasp_without_pivot_or_retry(fault):
    d=Robot()
    def operator(phase,sample,d,p):
        if phase=='STUD_ENGAGEMENT_CHECK':
            if fault=='force':d.s['wrench'][0]=45
            elif fault=='moment':d.s['wrench'][3]=1
            elif fault=='slip':d.s['gripper_width_mm']=38
            else:raise RuntimeError('OPERATOR_REPORT:'+fault)
            return 'STUD_ENGAGED'
    with pytest.raises(RuntimeError):trial(d,operator)
    assert d.stops==1 and d.grips==[(35,40)]


def test_no_engagement_exhausts_search_without_full_seating():
    d=Robot()
    with pytest.raises(RuntimeError,match='SEARCH_EXHAUSTED'):
        trial(d,lambda phase,*args:'NO_ENGAGEMENT_NEXT' if phase=='STUD_ENGAGEMENT_CHECK' else None)
    assert d.stops==1 and len(d.grips)==1


def test_early_report_does_not_silently_translate_measured_axis():
    d=Robot()
    with pytest.raises(RuntimeError,match='OUTSIDE_REGISTERED_AXIS'):
        trial(d,lambda phase,*args:'STUD_ENGAGED' if phase=='STUD_ENGAGEMENT_CHECK' else None)
    assert d.stops==1 and len(d.grips)==1


def test_contact_node_free_cli_and_bad_air_run(tmp_path):
    cli=ROOT/'robot_control_integration/scripts/yellow4_contact_trial.py'
    c=subprocess.run([sys.executable,str(cli),'--output',str(tmp_path/'preview')],capture_output=True,text=True)
    assert c.returncode==0,c.stderr
    assert not json.loads(c.stdout)['execution_ready']
    (tmp_path/'events.jsonl').write_text(json.dumps(dict(event='ABORT',data={}))+'\n')
    with pytest.raises(ValueError,match='ABORTED'):read_air_evidence(tmp_path)


def test_air_evidence_reads_snapshot_bound_to_run_not_mutable_parent(tmp_path):
    b,s,air=inputs();run=tmp_path/'run-test';run.mkdir()
    (run/'events.jsonl').write_text('\n'.join(json.dumps(dict(event=e,data=air[k]))
        for e,k in [('TRIAL_CONTEXT','context'),('RESULT','result')])+'\n')
    (run/'preview.json').write_text(json.dumps(air['preview']))
    (tmp_path/'preview.json').write_text('{}')
    evidence=read_air_evidence(run)
    assert prepare_contact(b,s,evidence)['execution_ready']
    assert evidence['sources']['preview']['path']==str(run/'preview.json')


def test_popup_rejects_early_keys_and_distinguishes_operator_reports():
    w=ContactWindow.__new__(ContactWindow);w.active={};w.answer=None
    w.key(ord('E'));assert w.answer is None
    w.active={'E':'STUD_ENGAGED'};w.key(ord('E'));assert w.answer=='STUD_ENGAGED'
    for key,reason in [('L','BOARD_LIFT'),('S','GRIP_SLIP'),('M','CONTACT_POINT_MOVED'),('U','UNKNOWN')]:
        with pytest.raises(RuntimeError,match=reason):w.key(ord(key))


def test_popup_roi_and_top_edge_clicks_are_nonblocking_pixel_inputs():
    from types import SimpleNamespace
    import cv2
    w=ContactWindow.__new__(ContactWindow);w.active={};w.answer=None;w.selection=None;w.clicks=[];w.edge=[];w.roi=None
    w.instructions=['a','b','c'];w.observer=SimpleNamespace(frame=np.zeros((480,640,3),np.uint8))
    header=244+27*len(w.instructions)
    w.key(ord('T'));w.click(cv2.EVENT_LBUTTONDOWN,10,header+20,0,None);w.click(cv2.EVENT_LBUTTONDOWN,40,header+22,0,None)
    assert w.edge==[[10,20],[40,22]] and w.selection is None
    w.key(ord('B'));w.click(cv2.EVENT_LBUTTONDOWN,60,header+80,0,None);w.click(cv2.EVENT_LBUTTONDOWN,20,header+40,0,None)
    assert w.roi==[20,40,60,80] and w.answer is None


def test_popup_does_not_project_full_seating_as_partial_trial():
    b,s,a=inputs();w=ContactWindow.__new__(ContactWindow);w.bundle=b;w.plan=prepare_contact(b,s,a);w.grid=None
    sample=dict(posx=[472,85,194,102,-176,104],tcp=b['connection']['tcp'],tool=b['connection']['tool'])
    info=dict(width=640,height=480,frame_id='camera_color_optical_frame',distortion_model='plumb_bob',k=[600,0,320,0,600,240,0,0,1],d=[0.]*5)
    canvas,report=w.analyze_frame(np.zeros((480,640,3),np.uint8),sample,info,'assembly',[],None)
    assert report['planned_partial_tilt_deg']==[10,8] and canvas.shape==(480,640,3)
    assert not report['roll_pitch_observed'] and not report['grid_reference']['projection_independently_verified']
