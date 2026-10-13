"""Unload-to-native-force composition tests; no physical seating validation."""
import json
import time

import pytest

from app.assembly_contact_fake import ContactFake, fake_config
from scripts.onsite_slot2_force_trial import ROOT, run_trial, trial_config, require_drcf2_runtime


def fixture(*, pressure_stages=None):
    c = fake_config(json.loads((ROOT/'interfaces/assembly_contact_trial.json').read_text()))
    c.update(xy_limit_mm=.25, rotation_limit_deg=.2)
    if pressure_stages:c['probe_force_n']=30.
    d = ContactFake(c); d.pos[2] -= 4.
    start = d.pos.copy(); events = []; elapsed = [0.]
    def sleep(seconds):
        elapsed[0] += seconds
    def run():
        return run_trial(d, c, start, lambda e, p: events.append((e, p)),
                         pressure_stages=pressure_stages,now=lambda: elapsed[0], sleep=sleep, utc=time.time)
    return d, start, events, run


def test_unload_precedes_force_and_final_candidate_holds_without_gripper_writes():
    d, start, events, run = fixture()
    result = run()
    assert d.calls[0] == ('move', [*start[:2], start[2]+4., *start[3:]])
    assert result['status'] == 'CONTACT_CANDIDATE_REVIEW_REQUIRED'
    assert result['probe_count'] == 13
    assert not d.force and not d.compliance
    assert result['assembly_completion'] is False and result['current_update'] is False
    assert result['gripper_commands'] == 0
    assert [payload['relative_force_n'] for event, payload in events
            if event == 'CONTACT_FORCE_REFERENCE'] == [20.]*13
    plan = next(payload for event, payload in events if event == 'FRESH_FORCE_PLAN')
    assert plan['config']['reference']['posx'][2] == start[2]+4.
    assert all(abs(q) <= bound+1e-9 for obs in result['observations']
               for q, bound in zip(obs['q'], [.25, .25, .2, .2, .2]))


def test_remaining_load_after_lift_never_enables_compliance_or_force():
    d, start, _, run = fixture()
    d.modify = lambda s: s.update(wrench=[0, 0, 16, 0, 0, 0]) if s['posx'][2] >= start[2]+4. else None
    with pytest.raises(RuntimeError, match='UNLOADED_REFERENCE_NOT_CONFIRMED'):
        run()
    assert [call[0] for call in d.calls] == ['move', 'stop']
    assert not d.force and not d.compliance


@pytest.mark.parametrize('change', ['grip', 'pose'])
def test_wrong_initial_state_has_no_actuator_calls(change):
    d, _, _, run = fixture()
    if change == 'grip':
        d.modify = lambda s: s.update(gripper_status=0)
    else:
        d.pos[0] += 2.
    with pytest.raises(RuntimeError):
        run()
    assert d.calls == []


@pytest.mark.parametrize('failure', ['force', 'interrupt'])
def test_active_force_failure_releases_both_modes_without_automatic_retreat(failure):
    d, _, _, run = fixture()
    def modify(s):
        if d.force:
            if failure == 'interrupt':
                raise KeyboardInterrupt()
            s['wrench'] = [0, 0, 35, 0, 0, 0]
    d.modify = modify
    result = run()
    assert result['status'] == 'CONTACT_TRIAL_ABORTED'
    assert [call[0] for call in d.calls[-3:]] == ['stop', 'release_force', 'release_compliance']
    assert not d.force and not d.compliance


def test_onsite_config_preserves_floor_and_has_no_invented_free_reference():
    c = trial_config(dict(floor_z_mm=11.51624870300293, seek_z_mm=22.2))
    assert c['reference'] is None
    assert c['floor_z_mm']+c['force_window_mm'] == 22.2
    assert c['probe_force_n'] == 20. and c['raw_force_stop_n'] == 35.


def test_pressure_stages_replace_absolute_force_without_xy_moves_or_extraction():
    d,start,events,run=fixture(pressure_stages=(25.,30.))
    result=run()
    assert result['status']=='PRESS_ONLY_FORCE_RELEASED_REVIEW_REQUIRED'
    assert d.force_requests==[dict(force_n=25.,relative=False),dict(force_n=30.,relative=False)]
    assert [o['measured_fz_n'] for o in result['observations']]==[25.,30.]
    first_force=next(i for i,call in enumerate(d.calls) if call[0]=='force')
    assert all(call[0]!='move' for call in d.calls[first_force:])
    assert all(call[1][:2]==start[:2] and call[1][3:]==start[3:]
               for call in d.calls if call[0]=='move')
    assert result['probe_count']==2 and result['stopped']
    assert not d.force and not d.compliance
    assert not result['assembly_completion'] and result['gripper_commands']==0


@pytest.mark.parametrize('failure',['force','interrupt','floor'])
def test_pressure_fault_never_advances_force_or_extracts(failure):
    d,_,_,run=fixture(pressure_stages=(25.,30.))
    def modify(s):
        if not d.force:return
        if failure=='interrupt':raise KeyboardInterrupt()
        if failure=='floor':s['posx'][2]=d.config['floor_z_mm']-1.
        else:s['wrench']=[0,0,35,0,0,0]
    d.modify=modify
    result=run()
    assert result['status']=='CONTACT_TRIAL_ABORTED'
    assert d.force_requests==[dict(force_n=25.,relative=False)]
    assert [call[0] for call in d.calls[-3:]]==['stop','release_force','release_compliance']
    assert not d.force and not d.compliance


@pytest.mark.parametrize('stages',[(25.,36.),(30.,25.),(True,),(-1.,),()])
def test_invalid_pressure_stages_never_move(stages):
    d,_,_,run=fixture(pressure_stages=stages)
    with pytest.raises(ValueError,match='INVALID_PRESSURE_STAGES'):run()
    assert d.calls==[]


def test_final_35n_stage_stops_at_existing_limit_and_releases_without_retry():
    d,_,_,run=fixture(pressure_stages=(25.,30.,35.))
    result=run()
    assert result['status']=='PRESS_ONLY_FORCE_LIMIT_REACHED_STOP_VERIFIED'
    assert [r['force_n'] for r in d.force_requests]==[25.,30.,35.]
    assert all(not r['relative'] for r in d.force_requests)
    assert result['force_limit_sample']['wrench'][2]==35.
    assert result['stopped'] and result['force_released'] and result['compliance_released']
    assert not result['assembly_completion'] and not d.force and not d.compliance
    assert [call[0] for call in d.calls[-3:]]==['stop','release_force','release_compliance']


def test_direct_35n_has_exactly_one_force_request_and_no_candidate_moves():
    d,_,_,run=fixture(pressure_stages=(35.,))
    result=run()
    assert d.force_requests==[dict(force_n=35.,relative=False)]
    assert result['status']=='PRESS_ONLY_FORCE_LIMIT_REACHED_STOP_VERIFIED'
    assert result['probe_count']==1
    first_force=next(i for i,call in enumerate(d.calls) if call[0]=='force')
    assert all(call[0]!='move' for call in d.calls[first_force:])
    assert not d.force and not d.compliance and not result['assembly_completion']


def test_35n_cleanup_failure_is_not_reported_as_completed_stop():
    d,_,_,run=fixture(pressure_stages=(25.,30.,35.))
    d.release_force=lambda transition:(_ for _ in ()).throw(RuntimeError('release failed'))
    result=run()
    assert result['status']=='CONTACT_TRIAL_ABORTED'
    assert result['stopped'] is None
    assert result['cleanup_errors']
    assert not d.compliance


def test_seated_start_unloads_above_seek_before_pressing():
    d,start,_,run=fixture(pressure_stages=(25.,30.,35.))
    d.pos[2]=18.;start[2]=18.
    d.config['force_window_mm']=8.
    result=run()
    assert d.calls[0][1][2]==24.5
    assert result['status']=='PRESS_ONLY_FORCE_LIMIT_REACHED_STOP_VERIFIED'


def test_runtime_guard_rejects_old_loaded_plugins_until_both_are_restarted(tmp_path, monkeypatch):
    monkeypatch.delenv('C2_DRIVER_ROOT', raising=False)
    process = tmp_path/'123'; process.mkdir()
    (process/'cmdline').write_bytes(b'/opt/ros/jazzy/lib/controller_manager/ros2_control_node\0-r\0__ns:=/dsr01\0')
    paths = [str(ROOT/'runtime/drcf2/install'/package/'lib'/f'lib{package}.so')
             for package in ('dsr_controller2', 'dsr_hardware2')]
    (process/'maps').write_text('/home/rokey/cobot2_ws/install/dsr_controller2/lib/libdsr_controller2.so\n')
    with pytest.raises(RuntimeError, match='DRCF2_DRIVER_RESTART_REQUIRED'):
        require_drcf2_runtime(tmp_path)
    (process/'maps').write_text(paths[0]+'\n')
    with pytest.raises(RuntimeError, match='DRCF2_DRIVER_RESTART_REQUIRED'):
        require_drcf2_runtime(tmp_path)
    (process/'maps').write_text('\n'.join(paths))
    assert require_drcf2_runtime(tmp_path) == 123


@pytest.mark.parametrize('loaded', ['both', 'controller_only', 'old'])
def test_runtime_guard_uses_selected_external_overlay_and_checks_both_plugins(tmp_path, monkeypatch, loaded):
    driver_root = tmp_path/'external driver'
    monkeypatch.setenv('C2_DRIVER_ROOT', str(driver_root))
    proc = tmp_path/'proc'; proc.mkdir()
    process = proc/'123'; process.mkdir()
    (process/'cmdline').write_bytes(b'/opt/ros/jazzy/lib/controller_manager/ros2_control_node\0-r\0__ns:=/dsr01\0')
    paths = [str(driver_root/'install'/package/'lib'/f'lib{package}.so')
             for package in ('dsr_controller2', 'dsr_hardware2')]
    if loaded == 'controller_only':
        paths = paths[:1]
    elif loaded == 'old':
        paths = [str(ROOT/'runtime/drcf2/install'/package/'lib'/f'lib{package}.so')
                 for package in ('dsr_controller2', 'dsr_hardware2')]
    (process/'maps').write_text('\n'.join(paths))
    if loaded == 'both':
        assert require_drcf2_runtime(proc) == 123
    else:
        with pytest.raises(RuntimeError, match='DRCF2_DRIVER_RESTART_REQUIRED'):
            require_drcf2_runtime(proc)
