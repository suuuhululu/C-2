from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import supply_rgbd_single_trial as trial

def synthetic_config(tmp_path, t2=False):
    from hashlib import sha256
    connection = dict(robot_id='dsr01', tcp='GripperDA_v4', tool='ToolWeight0',
                      ros_domain_id=20, gripper_ip='127.0.0.1')
    row = dict(color='blue' if t2 else 'yellow', brick_type='2x3x1' if t2 else '2x2x1',
               slot=3 if t2 else 4, span=2, close_mm=35., pose_source='SYNTHETIC',
               pickup_pose=[-450., 10. if t2 else 190., 50., 0., 180., 0.])
    view = [-443., -38., 374., 0., 180., 0.]
    layout = tmp_path/'layout.json'; layout.write_text('{"image_size":[640,480]}')
    profile = dict(schema_version='supply-depth-center/1', independently_verified=False,
        calibration_ref='SYNTHETIC_ONLY', connection={k:connection[k] for k in ('robot_id','tcp','tool')},
        observation_pose=view, layout_sha256=sha256(layout.read_bytes()).hexdigest(),
        T_tcp_camera_mm=[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]],
        input_size=[1280,720],camera_frame='camera_color_optical_frame',
        max_shift_mm=3.,max_height_error_mm=2.,max_depth_spread_mm=2.,depth_range_mm=[200.,600.],
        references=[dict(slot_id='blue_2x3x1_03' if t2 else 'yellow_2x2x1_04',
                         pickup_pose=row['pickup_pose'],surface_center_base_mm=[-450.,10.,100.])],
        educational_acceptance=dict(scope='T2_BLUE_2X3_SLOT3_SUPPLY_ONLY' if t2 else 'FIXED_T1_YELLOW_2X2_SLOT4_ONLY',
            operator_accepted=not t2,approval_mechanism='EXPLICIT_RUNNER_T2_EDUCATIONAL_FLAG',
            evidence_ref='SYNTHETIC_ONLY',measured_residual_xy_mm=1.7))
    pp = tmp_path/'profile.json'; pp.write_text(json.dumps(profile))
    cfg = dict(schema_version='supply-rgbd-single-trial/1',
        scope='T2_SUPPLY_APPROACH_CLOSE_HOLD_ONLY' if t2 else 'FIXED_T1_SUPPLY_APPROACH_CLOSE_HOLD_ONLY',
        connection=connection, observation_pose=view, blocks=[row], target_only_motion=False,
        automatic_lift=False,assembly_xy_correction_enabled=False,open_mm=60.,
        teaching_xy_bounds_mm=[[-650.,-300.],[-100.,250.]],pickup_clearance_z_mm=194.,
        trial_step=dict(step_id='T2' if t2 else 'T1',target=dict(color='yellow',brick_type='2x2x1',x=9,y=9,layer=2,orientation_deg=0)),
        force_stop_n=45.,gripper_force_n=40.,velocity=12.,acceleration=48.,angular_velocity=6.,angular_acceleration=3.,
        rise_velocity=12.,transit_velocity=120.,rise_acceleration=48.,transit_acceleration=48.,
        vision=dict(layout=str(layout),depth_center_profile=str(pp),allow_educational_depth_profile=not t2,
                    allow_educational_t2_depth_profile=t2),
        source_sha256={str(f):sha256(f.read_bytes()).hexdigest() for f in (pp,layout)})
    path=tmp_path/'config.json';path.write_text(json.dumps(cfg));return path


@pytest.fixture
def config(tmp_path):
    return synthetic_config(tmp_path)



def test_existing_t1_educational_pose_limits_and_motion_scope_are_preserved(config):
    cfg = trial.prepare(config)
    profile = json.loads(Path(cfg['vision']['depth_center_profile']).read_text())
    assert cfg['blocks'][0]['pickup_pose'] == profile['references'][0]['pickup_pose']
    assert cfg['blocks'][0]['close_mm'] == 35.
    assert cfg['gripper_force_n'] == 40.
    assert cfg['vision']['allow_educational_depth_profile']
    assert not cfg['automatic_lift'] and not cfg['assembly_xy_correction_enabled']
    assert len(cfg['blocks']) == 1 and not cfg['target_only_motion']
    assert 'alignment_target' not in cfg and 'integrated_cycle' not in cfg


@pytest.mark.parametrize('change', ['slot', 'assembly', 'lift', 'source', 'educational'])
def test_invalid_scope_and_changed_sources_fail_before_connection(config, change):
    cfg = json.loads(config.read_text())
    if change == 'slot': cfg['blocks'][0]['slot'] = 3
    if change == 'assembly': cfg['assembly_xy_correction_enabled'] = True
    if change == 'lift': cfg['automatic_lift'] = True
    if change == 'source': cfg['source_sha256'][next(iter(cfg['source_sha256']))] = 'wrong'
    if change == 'educational': cfg['vision']['allow_educational_depth_profile'] = False
    config.write_text(json.dumps(cfg))
    with pytest.raises(ValueError): trial.prepare(config)


def test_preview_and_missing_ready_flags_never_connect(config, monkeypatch, capsys):
    monkeypatch.setattr(trial, 'AssemblyMotionRos', lambda *a, **k: pytest.fail('Unexpected connection'))
    assert trial.main(['run', '--config', str(config)]) == 0
    assert 'PREVIEW_NO_DEVICE_CONNECTION' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        trial.main(['run', '--config', str(config), '--execute', '--confirm-hand-clear'])


def test_corrected_check_keeps_z_rotation_and_rejects_fallback(config):
    cfg = trial.prepare(config); row = cfg['blocks'][0]; target = row['pickup_pose'].copy()
    target[0] += 1.
    decision = dict(slot_id=trial.SLOT_ID, depth_center_required=True,
        depth_center=dict(status='READY', target=target, source_pickup_pose=row['pickup_pose'],
                          max_shift_mm=3., delta_xy_mm=[1., 0.]))
    class Driver:
        def check_pose(self, p): return p.copy()
    result = trial.check_corrected_endpoint(Driver(), cfg, decision)
    assert result[-1]['target'] == target
    assert result[-1]['target'][2:] == row['pickup_pose'][2:]
    with pytest.raises(ValueError, match='NO_TEACHING_FALLBACK'):
        trial.check_corrected_endpoint(Driver(), cfg, {})
    decision['depth_center']['target'][2] += 1.
    with pytest.raises(ValueError): trial.check_corrected_endpoint(Driver(), cfg, decision)


def test_check_only_reads_and_never_invokes_execution(config, tmp_path, monkeypatch):
    calls = []
    class Driver:
        def __init__(self, cfg): pass
        def close(self): calls.append('driver_close')
    class Vision:
        def __init__(self, driver, cfg, directory):
            assert cfg['vision']['show_window'] is False
        def observe(self, row): return dict(depth_center=dict(delta_xy_mm=[1., 0.]))
        def close(self): calls.append('vision_close')
    monkeypatch.setenv('ROS_DOMAIN_ID', '20')
    monkeypatch.setattr(trial, 'AssemblyMotionRos', Driver)
    monkeypatch.setattr(trial, 'preflight', lambda *a: dict(physical_commands=0))
    monkeypatch.setattr(trial, 'check_corrected_endpoint', lambda *a: [])
    monkeypatch.setattr(trial.supply, 'LiveVision', Vision)
    monkeypatch.setattr(trial.supply, 'execute', lambda *a, **k: pytest.fail('Movement in check'))
    out = tmp_path/'check'
    assert trial.main(['check', '--config', str(config), '--output', str(out)]) == 0
    assert json.loads((out/'live-check.json').read_text())['physical_commands'] == 0
    assert calls == ['vision_close', 'driver_close']


def test_run_dispatch_is_exactly_one_slot_hold_no_assembly(config, tmp_path, monkeypatch):
    calls = []
    class Driver:
        def __init__(self, cfg): pass
        def sample(self): return dict(gripper_status=2)
        def close(self): pass
    class Vision:
        def __init__(self, driver, cfg, directory): assert cfg['vision']['show_window']
        def observe(self, row): pass
        def display(self, row, decision): pass
        def pump_sleep(self, duration): pass
        def close(self): pass
    def execute(driver, cfg, record, observe, **kwargs):
        assert len(cfg['blocks']) == 1
        assert kwargs['trial_row']['slot'] == 4
        assert kwargs['start_zone'] == 'supply' and kwargs['hold_at_pickup'] is True
        assert cfg['vision']['depth_center_profile']
        calls.append('supply_only')
    monkeypatch.setenv('ROS_DOMAIN_ID', '20')
    monkeypatch.setattr(trial, 'AssemblyMotionRos', Driver)
    monkeypatch.setattr(trial, 'preflight', lambda *a: dict(physical_commands=0))
    monkeypatch.setattr(trial.supply, 'LiveVision', Vision)
    monkeypatch.setattr(trial.supply, 'execute', execute)
    out = tmp_path/'run'
    trial.main(['run', '--config', str(config), '--output', str(out), '--execute',
                '--confirm-slot4-ready', '--confirm-hand-clear'])
    assert calls == ['supply_only']
    result = json.loads((out/'result.json').read_text())
    assert not result['automatic_lift'] and not result['assembly_completion']


@pytest.fixture
def t2_config(tmp_path):
    return synthetic_config(tmp_path, t2=True)


def test_t2_requires_explicit_opt_in_and_preserves_real_two_stud_axis(t2_config, monkeypatch, capsys):
    cfg = trial.prepare(t2_config)
    assert not cfg['operator_accepted_t2_educational_profile']
    assert cfg['blocks'][0]['span'] == 2 and cfg['blocks'][0]['close_mm'] == 35.
    monkeypatch.setattr(trial, 'AssemblyMotionRos', lambda *a, **k: pytest.fail('Unexpected connection'))
    assert trial.main(['preview', '--config', str(t2_config)]) == 0
    with pytest.raises(SystemExit):trial.main(['check', '--config', str(t2_config)])
    accepted = trial.prepare(t2_config, True)
    assert accepted['operator_accepted_t2_educational_profile']
    assert not accepted['automatic_lift'] and not accepted['assembly_xy_correction_enabled']
    assert accepted['blocks'][0]['pickup_pose'] == cfg['blocks'][0]['pickup_pose']


def test_t2_loader_rejects_unaccepted_wrong_slot_and_assembly_scope(t2_config):
    cfg = trial.prepare(t2_config)
    pp = cfg['vision']['depth_center_profile']; layout = cfg['vision']['layout']
    with pytest.raises(ValueError, match='T2_EXPLICIT_SINGLE_SUPPLY_SCOPE'):
        trial.load_profile(pp, layout, cfg)
    cfg['operator_accepted_t2_educational_profile'] = True
    for key, value in [('scope', 'ASSEMBLY'), ('automatic_lift', True),
                       ('assembly_xy_correction_enabled', True)]:
        bad = deepcopy(cfg); bad[key] = value
        with pytest.raises(ValueError): trial.load_profile(pp, layout, bad)
    cfg['blocks'][0]['slot'] = 2
    with pytest.raises(ValueError): trial.load_profile(pp, layout, cfg)
