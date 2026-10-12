"""Trial flow, math and cleanup tests. No robot/physical safety validation."""
from copy import deepcopy
import json
import time

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.assembly_contact_alignment import correction_pose,prepare_contact,run_contact
from app.assembly_contact_fake import ContactFake,fake_config
from scripts.assembly_contact_trial import TEMPLATE,main,save


def config():return fake_config(json.loads(TEMPLATE.read_text()))


class Clock:
    def __init__(self):self.t=0.
    def now(self):return self.t
    def sleep(self,s):self.t+=s


def run(c=None,driver=None,record=None,cancelled=lambda:False,finish=False,contact=False):
    c=c or config();driver=driver or ContactFake(c,allow_force_moves=contact);events=[];clock=Clock()
    result=run_contact(driver,prepare_contact(c),record or (lambda e,p:events.append((e,p))),
        cancelled=cancelled,finish_contact=finish,in_contact=contact,now=clock.now,sleep=clock.sleep)
    return result,driver,events


def test_normal_probes_use_same_runner_and_release_before_any_correction():
    r,d,events=run()
    assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED' and r['probe_count']==12
    assert r['correction'][0]<0 and not d.force and not d.compliance
    assert r['assembled'] is False and r['gripper_commands']==0
    assert d.pos[2]==d.config['reference']['posx'][2]
    assert all(e['sample']['posx'][2]>=d.config['floor_z_mm'] for e in r['observations'])
    assert any(e=='CONTACT_CORRECTION_SELECTED' for e,p in events)


def test_so3_pose_math_stays_correct_at_zyz_poles_and_preserves_tcp_translation():
    for ref in [[1.,2.,10.,80.,180.,81.],[1.,2.,10.,20.,0.,40.]]:
        q=[.2,-.1,.3,-.2,.1];pose=correction_pose(ref,q)
        delta=Rotation.from_euler('ZYZ',pose[3:],degrees=True)*Rotation.from_euler('ZYZ',ref[3:],degrees=True).inv()
        np.testing.assert_allclose(delta.as_rotvec(),np.deg2rad(q[2:]),atol=1e-12)
        assert pose[:3]==[1.2,1.9,10.]


@pytest.mark.parametrize('change',[{'mode':None},{'schema_version':True},{'raw_force_stop_n':36},
    {'probe_force_n':float('nan')},{'velocity':[True,1]},{'rotation_limit_deg':7},
    {'rounds':0},{'floor_z_mm':True},{'stiffness':[1]*5},{'transition_s':-.1}])
def test_invalid_profiles_never_arm(change):
    c=config();c.update(change)
    with pytest.raises(ValueError):prepare_contact(c)


def test_absolute_floor_and_expired_reference_are_not_ignored():
    c=config();c['reference']['captured_at_unix_s']=time.time()-1000
    assert 'reference.expired' in prepare_contact(c)['missing']
    c=config();c['floor_z_mm']=25
    with pytest.raises(ValueError,match='FLOOR_PLUS_FORCE_WINDOW'):prepare_contact(c)


def test_zero_transition_and_invalid_robot_id_follow_api_contract():
    c=config();c['transition_s']=0
    assert prepare_contact(c)['status']=='CONTACT_PLAN_READY'
    c['connection']['robot_id']=None
    with pytest.raises(ValueError,match='INVALID_ROBOT_ID'):prepare_contact(c)


@pytest.mark.parametrize('free_delta',[.38,2.5])
def test_seek_wrench_change_does_not_abort_below_raw_limit_and_force_is_referenced_after_stop(free_delta):
    c=config();d=ContactFake(c)
    def modify(s):
        if s['posx'][2]<c['reference']['posx'][2]:
            s['wrench'][2]+=free_delta
    d.modify=modify
    r,d,e=run(c,d)
    assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED' and r['probe_count']==12
    references=[payload for event,payload in e if event=='CONTACT_FORCE_REFERENCE']
    assert references and references[0]['seek_wrench'][2]==4.+free_delta
    assert references[0]['approach_wrench'][2]==4.


@pytest.mark.parametrize('mutation,reason',[
    ({'wrench':[0,0,35,0,0,0]},'RAW_FORCE_STOP'),
    ({'wrench':[0,0,10,2,0,0]},'RAW_MOMENT_STOP'),
    ({'gripper_status':0},'GRASP_NOT_CONFIRMED'),
    ({'query_duration_s':1},'FEEDBACK_QUERY_TOO_SLOW'),
    ({'robot_mode':0},'AUTOMATIC_MODE_REQUIRED'),
    ({'posx':[300,0,15.999,0,180,0]},'ABSOLUTE_Z_ENVELOPE_EXCEEDED')])
def test_active_faults_stop_and_release_without_retreat(mutation,reason):
    c=config();c['raw_moment_stop_nm']=2.;d=ContactFake(c)
    d.modify=lambda s:s.update(mutation) if d.force else None
    r,d,e=run(c,d)
    assert r['status']=='CONTACT_TRIAL_ABORTED' and reason in r['reason']
    assert [a[0] for a in d.calls[-3:]]==['stop','release_force','release_compliance']
    assert not d.force and not d.compliance


def test_failed_force_ack_is_uncertain_even_when_cleanup_feedback_is_idle():
    c=config();d=ContactFake(c);original=d.set_downward_force
    def lose_ack(*args):original(*args);raise TimeoutError('ACK_TIMEOUT')
    d.set_downward_force=lose_ack
    r,d,e=run(c,d)
    assert r['state_uncertain'] and r['stopped'] is None and r['probe_count']==1
    assert not d.force and not d.compliance


def test_cleanup_release_failure_does_not_skip_other_actions():
    c=config();d=ContactFake(c)
    d.modify=lambda s:s.update(wrench=[0,0,35,0,0,0]) if d.force else None
    d.release_force=lambda *a:(_ for _ in ()).throw(RuntimeError('RELEASE_FAILED'))
    r,d,e=run(c,d)
    assert r['cleanup_errors'][0]['action']=='release_force'
    assert d.calls[-1][0]=='release_compliance' and r['stopped'] is None


def test_logging_failure_after_force_activation_still_cleans_up():
    c=config();d=ContactFake(c)
    def broken(e,p):
        if d.force:raise OSError('LOG_DISK_FULL')
    r,d,e=run(c,d,record=broken)
    assert 'LOG_DISK_FULL' in r['reason'] and not d.force and not d.compliance


def test_unsettled_probe_retracts_and_explores_but_cancel_stops_controller():
    c=config();d=ContactFake(c)
    d.modify=lambda s:s.update(wrench=[0,0,3,0,0,0]) if d.force else None
    r,d,e=run(c,d)
    assert r['status']=='NO_MATCHED_LOAD_HOLD' and r['probe_count']==12
    assert all(not o['matched_load'] for o in r['observations'])
    assert not d.force and not d.compliance and d.pos[2]==c['reference']['posx'][2]
    assert any(o['q'][0] != 0 for o in r['observations'])
    assert any(o['q'][2] != 0 for o in r['observations'])
    c=config();d=ContactFake(c)
    r,d,e=run(c,d,cancelled=lambda:d.force)
    assert 'OPERATOR_CANCELLED' in r['reason'] and not d.force


@pytest.mark.parametrize('permanent_unload',[False,True])
def test_initial_contact_unloading_is_observed_instead_of_immediate_sign_error(permanent_unload):
    c=config();d=ContactFake(c);seen=0
    def modify(s):
        nonlocal seen
        if d.force:
            seen+=1
            if permanent_unload or seen<=2:s['wrench'][2]=4.-1.47
    d.modify=modify
    r,d,e=run(c,d)
    if permanent_unload:
        assert r['status']=='NO_MATCHED_LOAD_HOLD' and r['probe_count']==12
        assert not d.force and not d.compliance
        assert d.pos[2]==c['reference']['posx'][2]
    else:
        assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED' and r['probe_count']==12


def test_unloaded_centre_can_find_and_repeat_a_loaded_xy_candidate():
    c=config();d=ContactFake(c)
    def modify(s):
        if d.force and abs(d.pos[0]-c['reference']['posx'][0])<.01:
            s['wrench'][2]=3.
    d.modify=modify
    r,d,e=run(c,d)
    assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED' and r['probe_count']==13
    assert r['correction'][0]==-.25
    assert not r['observations'][0]['matched_load']
    assert r['observations'][-1]['matched_load']
    assert r['observations'][-1]['q']==r['correction']
    assert not d.force and not d.compliance and d.pos[2]==c['reference']['posx'][2]
    # Every force attempt is released and followed by a vertical retreat before
    # any change to candidate XY or orientation, including an unloaded centre.
    force_indices=[i for i,call in enumerate(d.calls) if call[0]=='force']
    for i in force_indices:
        before=d.calls[:i]
        seek=next(call[1] for call in reversed(before) if call[0]=='move')
        after=d.calls[i+1:]
        first_move=next(j for j,call in enumerate(after) if call[0]=='move')
        assert [call[0] for call in after[:first_move]]==['release_force','stop','release_compliance']
        retreat=after[first_move][1]
        np.testing.assert_allclose(retreat[:2],seek[:2])
        np.testing.assert_allclose(retreat[3:],seek[3:])
        assert retreat[2]==c['reference']['posx'][2]


def test_raw_force_during_next_candidate_still_aborts_after_unmatched_response():
    c=config();d=ContactFake(c)
    def modify(s):
        if d.force:
            s['wrench'][2]=3. if d.pos[0]==c['reference']['posx'][0] else 35.
    d.modify=modify
    r,d,e=run(c,d)
    assert r['reason']=='RAW_FORCE_STOP' and r['probe_count']==2
    assert not r['observations'][0]['matched_load']
    assert not d.force and not d.compliance


def test_release_transient_velocity_does_not_override_controller_stopped_state():
    c=config();d=ContactFake(c);remaining=0;original=d.release_compliance
    def release():
        nonlocal remaining
        original();remaining=2
    def modify(s):
        nonlocal remaining
        if remaining:
            remaining-=1;s['velx'][2]=.08
    d.release_compliance=release;d.modify=modify
    r,d,e=run(c,d)
    assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED' and r['probe_count']==12
    assert any(event=='CONTACT_SAMPLE' and payload['phase']=='BEFORE_MOVE' and payload['sample']['velx'][2]==.08 for event,payload in e)
    assert not d.force and not d.compliance


def test_stationary_feedback_velocity_jitter_does_not_block_baseline():
    c=config();d=ContactFake(c)
    d.modify=lambda s:s.update(velx=[0,.036,0,0,0,0])
    r,d,e=run(c,d)
    assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED' and r['probe_count']==12
    assert not d.force and not d.compliance


def test_feedback_deviation_limits_removed_but_absolute_descent_floor_retained():
    from app.assembly_contact_alignment import validate_sample
    c=config();s=ContactFake(c).sample()
    s.update(posx=[301.2,1.2,26.063,2,180,0],gripper_width_mm=41.,wrench=[0,0,5,0,2.04,0])
    assert c['raw_moment_stop_nm'] is None
    assert validate_sample(s,c,reference=c['reference']) is s
    s['posx'][2]=15.999
    with pytest.raises(RuntimeError,match='ABSOLUTE_Z_ENVELOPE_EXCEEDED'):
        validate_sample(s,c,reference=c['reference'])


def test_in_contact_search_keeps_force_enabled_across_xy_and_rotation_candidates():
    c=config();r,d,e=run(c,contact=True)
    assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED' and r['probe_count']==12
    assert r['in_contact_search'] and r['correction'][0]==-.25
    names=[call[0] for call in d.calls]
    assert names.count('force')==names.count('compliance')==names.count('release_force')==1
    active=d.calls[names.index('force')+1:names.index('release_force')]
    assert all(call[0]=='move' for call in active)
    assert all(call[1][2]<c['reference']['posx'][2] for call in active)
    assert any(o['q'][0] for o in r['observations']) and any(o['q'][2] for o in r['observations'])
    assert d.pos[2]<c['reference']['posx'][2] and not d.force and not d.compliance
    assert not r['assembled']


def test_in_contact_unmatched_load_still_explores_without_extraction_or_reactivation():
    c=config();d=ContactFake(c,allow_force_moves=True)
    d.modify=lambda s:s.update(wrench=[0,0,3,0,0,0]) if d.force else None
    r,d,e=run(c,d,contact=True)
    assert r['status']=='NO_MATCHED_LOAD_HOLD' and r['probe_count']==12
    assert sum(call[0]=='force' for call in d.calls)==1
    assert all(not o['matched_load'] for o in r['observations'])
    assert d.pos[2]<c['reference']['posx'][2] and not d.force and not d.compliance


def test_in_contact_entry_below_approach_does_not_raise_or_claim_a_free_baseline():
    c=config();d=ContactFake(c,allow_force_moves=True);d.pos[2]=20.
    r,d,e=run(c,d,contact=True)
    assert r['probe_count']==12 and r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED'
    assert all(call[1][2]<=20. for call in d.calls if call[0]=='move')
    assert not any(event=='CONTACT_SAMPLE' and payload['phase']=='FREE_BASELINE' for event,payload in e)
    reference=next(payload for event,payload in e if event=='CONTACT_FORCE_REFERENCE')
    assert reference['approach_wrench'] is None


@pytest.mark.parametrize('cancel',[False,True])
def test_in_contact_search_fault_or_cancel_releases_and_does_not_continue(cancel):
    c=config();d=ContactFake(c,allow_force_moves=True)
    corrected=lambda:sum(call[0]=='move' for call in d.calls)>=3
    if not cancel:
        d.modify=lambda s:s.update(wrench=[0,0,35,0,0,0]) if corrected() else None
    r,d,e=run(c,d,contact=True,cancelled=lambda:cancel and corrected())
    assert r['reason']==('OPERATOR_CANCELLED' if cancel else 'RAW_FORCE_STOP')
    assert not d.force and not d.compliance and r['probe_count']<=2
    assert [call[0] for call in d.calls[-3:]]==['stop','release_force','release_compliance']


def test_unchanged_contact_repeat_and_finish_do_not_commit_assembly():
    c=config();d=ContactFake(c,error=[0]*5)
    r,d,e=run(c,d)
    assert r['status']=='NO_CLEAR_IMPROVEMENT_HOLD'
    r,d,e=run(finish=True)
    assert r['status']=='CONTACT_CANDIDATE_REVIEW_REQUIRED' and not r['assembled']
    assert d.pos[2]<d.config['reference']['posx'][2] and not d.force and not d.compliance


def test_changed_contact_repeat_holds_without_final_insertion():
    c=config();d=ContactFake(c);original=d.set_downward_force;count=0
    def changed(*args):
        nonlocal count
        count+=1;original(*args)
        if count==12:d.pos[2]+=.6
    d.set_downward_force=changed
    r,d,e=run(c,d,finish=True)
    assert r['status']=='CONTACT_RESPONSE_CHANGED_HOLD' and r['probe_count']==12
    assert d.pos[2]==c['reference']['posx'][2]


def test_default_cli_preview_never_constructs_real_driver(tmp_path):
    p=tmp_path/'pending.json';save(p,json.loads(TEMPLATE.read_text()))
    assert main(['run','--profile',str(p)],driver_factory=lambda c:pytest.fail('REAL created'))==0
    assert main(['smoke','--log-dir',str(tmp_path/'smoke')],driver_factory=lambda c:pytest.fail('REAL created'))==0


def test_domain_mismatch_and_stop_file_block_execution_before_driver(tmp_path,monkeypatch):
    c=config();c['mode']='REAL';p=tmp_path/'ready.json';save(p,c)
    monkeypatch.setenv('ROS_DOMAIN_ID','19')
    assert main(['run','--profile',str(p),'--execute'],driver_factory=lambda c:pytest.fail('REAL created'))==1
    monkeypatch.setenv('ROS_DOMAIN_ID','20');stop=tmp_path/'STOP';stop.touch()
    assert main(['run','--profile',str(p),'--execute','--stop-file',str(stop)],driver_factory=lambda c:pytest.fail('REAL created'))==1


def test_free_wrench_drift_after_vertical_retract_does_not_block_corrections():
    c=config();d=ContactFake(c);released=False
    original=d.release_force
    def release(*a):
        nonlocal released
        original(*a);released=True
    d.release_force=release
    d.modify=lambda s:s.update(wrench=[3,0,4,0,0,0]) if released and not d.force else None
    r,d,e=run(c,d)
    assert r['status']=='LOCAL_TRIAL_LIMIT_REVIEW_REQUIRED'
    moves=[a for a in d.calls if a[0]=='move']
    assert moves[-1][1][2]==c['reference']['posx'][2]
    assert r['probe_count']==12


def test_readonly_capture_arm_check_and_explicit_real_run_paths_with_fake_transport(tmp_path,monkeypatch):
    monkeypatch.setenv('ROS_DOMAIN_ID','20')
    c=config();c['mode']='REAL';template=tmp_path/'template.json';save(template,c)
    devices=[]
    def factory(profile):
        d=ContactFake(profile);d.mode='REAL';d.robot_system=lambda:0
        devices.append(d);return d
    seat=tmp_path/'seat.json';profile=tmp_path/'onsite.json';logs=tmp_path/'logs'
    assert main(['teach-seat','--profile',str(template),'--confirm-seated','--out',str(seat),'--log-dir',str(logs)],driver_factory=factory)==0
    seated=json.loads(seat.read_text());assert seated['floor_z_mm']==26.
    # Teach a seat independently, then simulate an unchanged grasp raised 10mm.
    c['reference']['posx'][2]=36.;save(template,c)
    assert main(['arm','--profile',str(template),'--seated-reference',str(seat),'--confirm-noncontact','--confirm-envelope','--out',str(profile),'--log-dir',str(logs)],driver_factory=factory)==0
    assert all(not d.calls for d in devices)
    assert main(['check','--profile',str(profile),'--stop-file',str(tmp_path/'STOP'),'--log-dir',str(logs)],driver_factory=factory)==0
    assert not devices[-1].calls
    assert main(['run','--profile',str(profile),'--execute','--stop-file',str(tmp_path/'STOP'),'--log-dir',str(logs)],driver_factory=factory)==0
    assert devices[-1].closed and devices[-1].calls and not devices[-1].force
    assert all(e[0]!='gripper' for e in devices[-1].calls)


def test_budget_and_session_timeouts_do_not_restart_a_trial():
    c=config();c['max_probes']=1
    r,d,e=run(c)
    assert 'PROBE_BUDGET_EXHAUSTED' in r['reason'] and r['probe_count']==1
    c=config();c['timing']['session_timeout_s']=.04
    r,d,e=run(c)
    assert 'SESSION_TIMEOUT' in r['reason'] and not d.force and not d.compliance


def test_rearming_preserves_operator_edited_default_profile(tmp_path,monkeypatch):
    import scripts.assembly_contact_trial as cli
    monkeypatch.setenv('ROS_DOMAIN_ID','20')
    profile=tmp_path/'onsite.json';monkeypatch.setattr(cli,'DEFAULT_PROFILE',profile)
    c=config();c['mode']='REAL';c['probe_force_n']=5.;save(profile,c)
    def factory(p):
        d=ContactFake(p);d.mode='REAL';d.robot_system=lambda:0
        return d
    assert main(['arm','--floor-z-mm','16','--confirm-noncontact','--confirm-envelope',
                 '--log-dir',str(tmp_path/'logs')],driver_factory=factory)==0
    assert json.loads(profile.read_text())['probe_force_n']==5.
