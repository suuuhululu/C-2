"""Stage5 synthetic contract tests; never field evidence or device commands."""
from copy import deepcopy
import json
import subprocess
import sys
import pytest
from app.yellow4_seating_trial import prepare_seating,press_targets
from app.yellow4_contact_trial import prepare_contact,execute
from app.assembly_motion import pose_error
from app.edge_first_seating import pose_matrix
from scripts.yellow4_contact_trial import ContactWindow,read_partial_evidence
from test_yellow4_observation import ROOT,bundle
from test_yellow4_contact_trial import inputs,Robot,CONTACT
SEATING=json.loads((ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/seating_trial.json').read_text())


def seating_inputs(angle=10,with_press=False):
    b,c,air=inputs(angle);partial=prepare_contact(b,c,air);s=deepcopy(SEATING)
    s['partial_trial_review']=dict(evidence_ref='TEST_ONLY_NOT_FIELD',contact_axis_observed=True,
        rotation_direction_confirmed=True,grip_maintained=True,board_fixed=True,conditions_confirmed=True)
    evidence=dict(preview=partial,result=dict(status='PARTIAL_PIVOT_COMMANDS_COMPLETED_OPERATOR_REPORT_NOT_SEATING',
        backend='REAL',physical_commands=30,gripper_release_commands=0,press_commands=0),events=[
            dict(event='OPERATOR_OBSERVATION',data=dict(phase='STUD_ENGAGEMENT_CHECK',answer='STUD_ENGAGED')),
            dict(event='OPERATOR_OBSERVATION',data=dict(phase='PARTIAL_RESULT_INSPECTION',answer='PARTIAL_OBSERVED'))])
    if with_press:
        pose=partial['ground_geometry']['seated_reference_tcp_mm_zyz_deg'].copy();pose[2]+=10
        s['press']=dict(enabled=True,profile=dict(evidence_ref='TEST_ONLY_NOT_FIELD',parameter_ref='TEST_ONLY',
            pad_contact_verified=True,frame='BASE',target=b['target'],grasp_id=b['measurement']['grasp_id'],
            tcp=b['connection']['tcp'],tool=b['connection']['tool'],contact_tcp_pose_mm_zyz_deg=pose,
            near_contact_offset_mm=3,max_travel_mm=5,velocity_mm_s=6,acceleration_mm_s2=12,
            empty_width_mm=4,empty_width_tolerance_mm=1,force_stop_n=45))
    return b,c,s,air,evidence


class SeatingRobot(Robot):
    def __init__(self,pressure='none'):
        super().__init__();self.pressure=pressure;self.pad_start=None;self.press_seen=False
    def command_gripper(self,width,force):
        self.grips.append((width,force));self.s.update(gripper_status=0 if width==60 else 2,gripper_width_mm=width)
    def move_line_async(self,p,v,a):
        if self.pad_start is not None and p[2]<self.pad_start-.1:
            self.press_seen=True
            if self.pressure=='force':self.s['wrench'][0]=46
            if self.pressure=='moment':self.s['wrench'][3]=2
        super().move_line_async(p,v,a)


def run_trial(with_press=False,pressure='none',angle=10,override=None,driver=None):
    b,c,s,a,e=seating_inputs(angle,with_press);p=prepare_seating(b,c,s,a,e);d=driver or SeatingRobot(pressure);events=[]
    def observe(poll):
        poll();return dict(pickup_tcp_candidate=b['selected_pickup_tcp_candidate'],
            supply_decision=dict(vision_attempted=True,recognized=False,center_assist_applied=False,reason='TEST_COORDINATE_FALLBACK'))
    def operator(phase,allowed,poll):
        sample=poll()
        if override:
            answer=override(phase,d,p)
            if answer is not None:return answer
        if phase=='STUD_ENGAGEMENT_CHECK':
            return 'STUD_ENGAGED' if sample['posx'][2]<=p['partial_geometry']['waypoints'][0]['tcp_mm_zyz_deg'][2]+.01 else 'NO_ENGAGEMENT_NEXT'
        return allowed[0]
    def record(event,data):
        events.append((event,deepcopy(data)))
        if event=='CENTERED_VERTICAL_PRESS':d.pad_start=data['targets']['start'][2]
    r=execute(d,p,'home',record,observe,operator,sleep=lambda _:None)
    return d,p,r,events


def test_current_prepare_keeps_stage2_3_4_unknown_and_press_optional():
    b=bundle();old=deepcopy(b);p=prepare_seating(b,CONTACT,SEATING)
    assert p['stage']==5 and not p['execution_ready'] and p['physical_commands']==0 and b==old
    assert 'stage4_real_partial_run' in p['missing_measurements']
    assert 'removal_contact_axis' not in p['missing_measurements'] and 'measured_closed_pad_press_profile' not in p['missing_measurements']
    assert p['pickup_tcp']==b['baseline_supply_tcp'] and p['intended_pad_bottom_height_mm']==5


def test_actual_partial_run_and_conditions_review_required_without_promotion():
    b,c,s,a,e=seating_inputs();p=prepare_seating(b,c,s,a,e)
    assert p['execution_ready'] and not p['parameter_field_verified'] and not p['contact_conditions_material_limit_verified']
    assert p['seating_geometry']['waypoints'][-1]['tilt_deg']==0 and not p['press']['enabled']
    s['partial_trial_review']['conditions_confirmed']=False
    assert not prepare_seating(b,c,s,a,e)['execution_ready']


@pytest.mark.parametrize('change',['fake','opened','missing_observation','conditions','axis','sampling'])
def test_unmatched_or_unobserved_partial_evidence_rejected(change):
    b,c,s,a,e=seating_inputs()
    if change=='fake':e['result']['backend']='FAKE'
    elif change=='opened':e['result']['gripper_release_commands']=1
    elif change=='missing_observation':e['events']=[]
    elif change=='conditions':e['preview']['contact']['linear_velocity_mm_s']=120
    elif change=='axis':e['preview']['ground_geometry']['contact_line_points_mm'][0][0]+=1
    else:e['preview']['geometry_config']['operations']['assembly']['angular_step_deg']+=1
    with pytest.raises(ValueError):prepare_seating(b,c,s,a,e)


@pytest.mark.parametrize('angle',[10,-10])
def test_full_rotation_release_vertical_retreat_and_operator_inspection(angle):
    d,p,r,events=run_trial(angle=angle)
    assert d.grips==[(35,40),(60,40)] and d.stops==0
    assert r['remaining_tilt_deg']==0 and r['gripper_release_commands']==1 and r['press_commands']==0
    assert r['operator_reported_seated'] and r['block_rpy_deg'] is None and not r['assembly_completion']
    order=[x['phase'] for event,x in events if event=='OPERATOR_OBSERVATION']
    assert order.index('FULL_PIVOT_READY')<order.index('SEATING_RELEASE_INSPECTION')<order.index('POST_RELEASE_INSPECTION')
    release=next(x['released_pose'] for event,x in events if event=='ACTUAL_RELEASE_POSE')
    assert pose_error(release,p['ground_geometry']['seated_reference_tcp_mm_zyz_deg'])[1]<1e-6
    rise=next(x['target'] for event,x in events if event=='MOVE_REQUEST' and x['label']=='POST_RELEASE_VERTICAL_RISE')
    assert rise[:2]+rise[3:]==release[:2]+release[3:]


@pytest.mark.parametrize('failure',['force','moment','slip','unknown','ack'])
def test_full_sweep_fault_never_opens_or_retries(failure):
    d=SeatingRobot()
    def operator(phase,d,p):
        if phase=='FULL_PIVOT_READY':
            if failure=='force':d.s['wrench'][0]=45
            elif failure=='moment':d.s['wrench'][3]=1
            elif failure=='slip':d.s['gripper_width_mm']=38
            elif failure=='ack':d.fail=True
            else:raise RuntimeError('OPERATOR_UNKNOWN')
            return 'FULL_PIVOT_READY'
    with pytest.raises((RuntimeError,TimeoutError)):run_trial(override=operator,driver=d)
    assert d.grips==[(35,40)] and d.stops==1


def test_optional_press_requires_measured_profile_and_same_binding():
    b,c,s,a,e=seating_inputs();s['press']['enabled']=True
    p=prepare_seating(b,c,s,a,e)
    assert not p['execution_ready'] and 'measured_closed_pad_press_profile' in p['missing_measurements']
    b,c,s,a,e=seating_inputs(with_press=True);s['press']['profile']['tool']='wrong'
    with pytest.raises(ValueError,match='BINDING'):prepare_seating(b,c,s,a,e)


def test_press_height_uses_registered_plane_and_preserves_actual_xy_attitude():
    b,c,s,a,e=seating_inputs(with_press=True);p=prepare_seating(b,c,s,a,e)
    # Test-only sloping plane: no field profile is saved or relabelled.
    p['ground_geometry']['seated_reference_block_mm_zyz_deg']=[0,0,0,0,10,0]
    actual=p['ground_geometry']['seated_reference_tcp_mm_zyz_deg'].copy();actual[:2]=[1,2]
    t=press_targets(p,actual,s['press']['profile'],20)
    n=pose_matrix(p['ground_geometry']['seated_reference_block_mm_zyz_deg'])[:3,2]
    assert t['measured_touch_z_at_actual_xy_mm']==pytest.approx(s['press']['profile']['contact_tcp_pose_mm_zyz_deg'][2]-n[0]/n[2])
    assert t['high'][:2]+t['high'][3:]==actual[:2]+actual[3:]
    assert t['start'][:2]+t['start'][3:]==actual[:2]+actual[3:]


@pytest.mark.parametrize('pressure',['none','force'])
@pytest.mark.parametrize('pad_status',[0,2])
def test_closed_empty_pad_press_end_is_not_seating_and_no_auto_retreat(pressure,pad_status):
    d=SeatingRobot(pressure);grip=d.command_gripper
    def command(width,force):
        grip(width,force)
        if width==4:d.s['gripper_status']=pad_status
    d.command_gripper=command
    d,p,r,events=run_trial(with_press=True,driver=d)
    assert d.grips==[(35,40),(60,40),(4,40)]
    assert r['physical_commands']==0 and not r['constant_force_control'] and not r['assembly_completion']
    status=r['press_result']['status']
    assert status==('FORCE_THRESHOLD_REACHED_STOP_VERIFIED' if pressure=='force' else 'MAX_TRAVEL_REACHED_WITHOUT_FORCE_THRESHOLD')
    assert d.stops==(1 if pressure=='force' else 0)
    center=next(x for event,x in events if event=='CENTERED_VERTICAL_PRESS')
    assert center['empty_pad_status']==pad_status
    release=center['released_pose'];press_moves=[x for event,x in events if event=='PAD_MOVE_REQUEST']
    assert all(x['target'][:2]+x['target'][3:]==release[:2]+release[3:] for x in press_moves)
    assert d.moves[-1][0]==r['final_sample']['posx']  # Passive inspection, no post-stop motion.
    assert all('so3_error_deg' in x for event,x in events if event=='PAD_MOTION_SAMPLE')


def test_after_open_actual_xy_is_used_without_nominal_xy_reset():
    d=SeatingRobot();grip=d.command_gripper
    def command(width,force):
        grip(width,force)
        if width==60:d.s['posx'][0]+=.1
    d.command_gripper=command
    _,p,r,events=run_trial(with_press=True,driver=d)
    release=next(x['released_pose'] for event,x in events if event=='ACTUAL_RELEASE_POSE')
    center=next(x for event,x in events if event=='CENTERED_VERTICAL_PRESS')
    assert release[0]==pytest.approx(.1) and center['released_pose']==release
    for event,x in events:
        if event=='MOVE_REQUEST' and x['label'] in ('POST_RELEASE_VERTICAL_RISE','CLOSED_PAD_VERTICAL_LOWER'):
            assert x['target'][:2]+x['target'][3:]==release[:2]+release[3:]


def test_busy_and_grip_bit_combination_during_open_is_transient_not_completion():
    d=SeatingRobot();original=d.sample;grip=d.command_gripper;busy=[0]
    def command(width,force):
        grip(width,force)
        if width==60:busy[0]=1
    def sample():
        s=original()
        if busy[0]:s['gripper_status']=3;busy[0]-=1
        return s
    d.command_gripper=command;d.sample=sample
    _,_,r,events=run_trial(driver=d)
    assert r['gripper_release_commands']==1
    assert any(x['sample']['gripper_status']==3 for event,x in events if event=='GRIP_FEEDBACK')


def test_pressure_moment_fault_preserves_empty_pad_without_stop_resend():
    d=SeatingRobot('moment')
    with pytest.raises(RuntimeError,match='PAD_MOMENT'):run_trial(with_press=True,driver=d)
    assert d.stops==1 and d.grips==[(35,40),(60,40),(4,40)]


def test_stage5_cli_is_node_free_and_aborted_partial_is_rejected(tmp_path):
    cli=ROOT/'robot_control_integration/scripts/yellow4_contact_trial.py'
    c=subprocess.run([sys.executable,str(cli),'--stage','5','--output',str(tmp_path/'preview')],capture_output=True,text=True)
    assert c.returncode==0,c.stderr
    result=json.loads((tmp_path/'preview/preview.json').read_text())
    assert result['stage']==5 and not result['execution_ready'] and result['physical_commands']==0
    (tmp_path/'events.jsonl').write_text(json.dumps(dict(event='ABORT',data={}))+'\n')
    with pytest.raises(ValueError,match='ABORTED'):read_partial_evidence(tmp_path)


def test_cli_reuses_recorded_contact_inputs_without_requiring_duplicate_files(tmp_path):
    b,c,s,a,e=seating_inputs()
    # Temporary synthetic contract records only. The CLI remains preview-only.
    measured=tmp_path/'paired-input.TEST_ONLY.json';measured.write_text(json.dumps(b['measurement']))
    air_run=tmp_path/'air-run';air_run.mkdir()
    (air_run/'preview.json').write_text(json.dumps(a['preview']))
    (air_run/'events.jsonl').write_text('\n'.join(json.dumps(dict(event=event,data=a[key]))
        for event,key in [('TRIAL_CONTEXT','context'),('RESULT','result')])+'\n')
    partial=tmp_path/'partial-run';partial.mkdir()
    e['preview']['sources'].update(field_measurements=dict(path=str(measured)),air_run=dict(events=dict(path=str(air_run/'events.jsonl'))))
    (partial/'preview.json').write_text(json.dumps(e['preview']))
    (partial/'events.jsonl').write_text('\n'.join(json.dumps(event) for event in [*e['events'],dict(event='RESULT',data=e['result'])])+'\n')
    config=tmp_path/'review.TEST_ONLY.json';config.write_text(json.dumps(s))
    cli=ROOT/'robot_control_integration/scripts/yellow4_contact_trial.py'
    result=subprocess.run([sys.executable,str(cli),'--stage','5','--config',str(config),'--partial-run',str(partial),
        '--output',str(tmp_path/'output')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    p=json.loads((tmp_path/'output/preview.json').read_text())
    assert p['execution_ready'] and p['physical_commands']==0
    assert p['contact']==e['preview']['contact'] and p['parameter_field_verified'] is False
