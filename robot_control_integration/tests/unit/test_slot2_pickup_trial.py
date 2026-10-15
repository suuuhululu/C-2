from copy import deepcopy
import json

import pytest

from scripts import slot2_pickup_trial as trial


@pytest.fixture
def teaching(tmp_path):
    path = tmp_path/'pickup.json'
    path.write_text(json.dumps(dict(schema_version='supply-preclose-teaching-record/1',
        status='OPERATOR_IDENTIFIED_PRE_CLOSE_PICKUP_POSE', slot_id=trial.SLOT_ID,
        tcp='GripperDA_v4', tool='ToolWeight0', physical_grasp_verified=True,
        operator_preclose_alignment_confirmed=True,
        tcp_pose_mm_zyz_deg=[-390., 195., 49., 167., -177., 167.])))
    return path


def test_prepare_keeps_exact_manual_pose_and_existing_rates_without_assembly(teaching):
    cfg = trial.prepare(teaching)
    original = trial.reference_config('T1')
    assert cfg['blocks'][0]['slot'] == 2 and len(cfg['blocks']) == 1
    assert cfg['blocks'][0]['pickup_pose'] == [-390., 195., 49., 167., -177., 167.]
    for key in ('gripper_force_n', 'velocity', 'acceleration', 'angular_velocity',
                'angular_acceleration', 'transit_velocity', 'force_stop_n'):
        assert cfg[key] == original[key]
    assert cfg['vision'] == {} and not cfg['target_only_motion']
    assert 'alignment_target' not in cfg and 'center_mapping' not in cfg['blocks'][0]


@pytest.mark.parametrize('field,value', [('slot_id', 'yellow_2x2x1_04'),
    ('operator_preclose_alignment_confirmed', None), ('physical_grasp_verified', False),
    ('tcp', 'GripperDA_v1')])
def test_wrong_or_unconfirmed_record_is_rejected_before_device_connection(teaching, field, value):
    data = json.loads(teaching.read_text()); data[field] = value
    teaching.write_text(json.dumps(data))
    with pytest.raises(ValueError): trial.prepare(teaching)


def test_run_without_execute_is_preview_without_any_device_connection(teaching, monkeypatch, capsys):
    def forbidden(*args, **kwargs): raise AssertionError('Device connection in preview')
    monkeypatch.setattr(trial, 'AssemblyMotionRos', forbidden)
    assert trial.main(['run', '--pickup-record', str(teaching)]) == 0
    assert 'PREVIEW_NO_DEVICE_CONNECTION' in capsys.readouterr().out


def test_execute_requires_both_physical_preparation_flags(teaching, monkeypatch):
    monkeypatch.setattr(trial, 'AssemblyMotionRos', lambda *a, **kw: pytest.fail('No device connection expected'))
    with pytest.raises(SystemExit):
        trial.main(['run', '--pickup-record', str(teaching), '--execute', '--confirm-hand-clear'])


class Driver:
    def __init__(self, cfg):
        self.value = dict(posx=cfg['observation_pose'].copy(), velx=[0.]*6,
            motion_status=0, wrench=[0.]*6, query_duration_s=.01, tcp='GripperDA_v4',
            tool='ToolWeight0', gripper_status=0, gripper_width_mm=52., robot_state=1,
            robot_mode=1, drl_state=3)
        self.commands = []; self.stopped = False

    def robot_system(self): return 0
    def sample(self): return deepcopy(self.value)
    def check_pose(self, pose): return pose.copy()
    def command_gripper(self, width, force):
        self.commands.append((width, force))
        self.value.update(gripper_status=2, gripper_width_mm=40.6)
    def stop(self): self.stopped = True


def test_readonly_preflight_checks_open_observer_and_ik_without_commands(teaching):
    cfg = trial.prepare(teaching); driver = Driver(cfg)
    check = trial.preflight(driver, cfg)
    assert check['physical_commands'] == 0 and len(check['endpoints']) == 4
    assert driver.commands == []
    driver.value['posx'][0] += 2.
    with pytest.raises(RuntimeError, match='STOPPED_OBSERVATION'):
        trial.preflight(driver, cfg)


def test_single_approach_closes_once_and_holds_without_lift_release_or_vision(teaching, monkeypatch):
    cfg = trial.prepare(teaching); driver = Driver(cfg); moves = []; events = []
    def move(d, connection, target, limit, record, **kw):
        assert d.value['gripper_status'] == 0
        moves.append(target.copy()); d.value['posx'] = target.copy()
    monkeypatch.setattr(trial.supply, 'run', move)
    trial.supply.execute(driver, cfg, lambda e, d: events.append(e), trial.taught_observation,
        trial_row=cfg['blocks'][0], start_zone='supply', hold_at_pickup=True, sleep=lambda _: None)
    assert len(moves) == 3
    assert moves[-1] == cfg['blocks'][0]['pickup_pose']
    assert driver.commands == [(35., 40.)]
    assert driver.value['gripper_status'] == 2
    assert 'PICKUP_COMPLETE_HOLDING' in events and 'RELEASE_FEEDBACK' not in events
    assert not trial.taught_observation(cfg['blocks'][0])['vision_attempted']


@pytest.fixture
def red_teaching(tmp_path):
    source = trial.NATIVE/'fixtures/teaching_sources/operator_supply.json'
    path = tmp_path/'operator_supply.json'
    path.write_bytes(source.read_bytes())
    return path


def test_red_uses_exact_slot1_source_without_slot5_rotation_or_xy(red_teaching):
    cfg = trial.prepare(red_teaching, trial.RED_SLOT_ID)
    source = json.loads(red_teaching.read_text())['records']['supply/red/1x2x1/1']
    row = cfg['blocks'][0]
    assert row['pickup_pose'] == source['tcp_pose_mm_zyz_deg']
    assert (row['slot'], row['close_mm'], row['span']) == (1, 20., 1)
    assert not cfg['prior_physical_grasp_verified']
    assert not cfg['supply_rgbd_correction_enabled']
    assert not cfg['assembly_xy_correction_enabled']
    assert source['execution_allowed'] is False
    assert trial.taught_observation(row)['slot_id'] == trial.RED_SLOT_ID
    assert trial.waypoints(cfg)[-1][0] == 'slot1_pickup'
    driver = Driver(cfg)
    assert trial.preflight(driver, cfg)['physical_commands'] == 0
    assert driver.commands == []


@pytest.mark.parametrize('field,value', [('slot_index', 5), ('operator_confirmed', False),
    ('source', 'MODEL_CANDIDATE'), ('tcp_pose_mm_zyz_deg', [0.]*6)])
def test_red_rejects_wrong_slot_unconfirmed_model_or_wrong_location(red_teaching, field, value):
    source = json.loads(red_teaching.read_text())
    source['records']['supply/red/1x2x1/1'][field] = value
    red_teaching.write_text(json.dumps(source))
    with pytest.raises(ValueError): trial.prepare(red_teaching, trial.RED_SLOT_ID)


def test_red_preview_and_wrong_yellow_ready_flag_do_not_connect(red_teaching, monkeypatch, capsys):
    monkeypatch.setattr(trial, 'AssemblyMotionRos', lambda *a, **kw: pytest.fail('No connection'))
    args = ['run', '--slot-id', trial.RED_SLOT_ID, '--pickup-record', str(red_teaching)]
    assert trial.main(args) == 0
    assert 'PREVIEW_NO_DEVICE_CONNECTION' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        trial.main(args+['--execute', '--confirm-slot2-ready', '--confirm-hand-clear'])


def test_red_approaches_exact_pose_closes_once_without_lift_or_open(red_teaching, monkeypatch):
    cfg = trial.prepare(red_teaching, trial.RED_SLOT_ID)
    driver = Driver(cfg); moves = []; events = []
    def move(d, connection, target, limit, record, **kw):
        assert d.value['gripper_status'] == 0
        moves.append(target.copy()); d.value['posx'] = target.copy()
    monkeypatch.setattr(trial.supply, 'run', move)
    trial.supply.execute(driver, cfg, lambda e, d: events.append(e), trial.taught_observation,
        trial_row=cfg['blocks'][0], start_zone='supply', hold_at_pickup=True, sleep=lambda _: None)
    assert moves == [pose for _, pose in trial.waypoints(cfg)[1:]]
    assert driver.commands == [(20., 40.)]
    assert 'PICKUP_COMPLETE_HOLDING' in events and 'RELEASE_FEEDBACK' not in events


@pytest.fixture
def new_red_teaching(tmp_path):
    from hashlib import sha256
    path = tmp_path/'pickup.json'
    path.write_text(json.dumps(dict(schema_version='supply-preclose-teaching-record/1',
        status='OPERATOR_IDENTIFIED_PRE_CLOSE_PICKUP_POSE', slot_id=trial.RED_SLOT_ID,
        tcp='GripperDA_v4', tool='ToolWeight0', physical_grasp_verified=False,
        tcp_pose_mm_zyz_deg=[-329., -54., 49., 167., -178., 167.])))
    evidence = tmp_path/'lift.json'; evidence.write_text('{"status":"POST_LIFT_HOLDING_SIGNAL_CONFIRMED"}')
    review = dict(pickup_record_sha256=sha256(path.read_bytes()).hexdigest(),
        operator_preclose_alignment_confirmed=True, operator_exact_grasp_confirmed=True,
        operator_manual_lift_confirmed=True, post_lift_holding_signal_verified=True,
        grasp_basis='TWO_STUD_SIDE_AXIS', evidence=[dict(file=evidence.name,
            sha256=sha256(evidence.read_bytes()).hexdigest())])
    (tmp_path/'manual-grasp-review.json').write_text(json.dumps(review))
    return path


def test_new_red_teaching_uses_exact_new_pose_and_preserves_raw_record(new_red_teaching):
    before = new_red_teaching.read_bytes()
    cfg = trial.prepare(new_red_teaching, trial.RED_SLOT_ID)
    assert cfg['blocks'][0]['pickup_pose'] == [-329., -54., 49., 167., -178., 167.]
    assert cfg['blocks'][0]['close_mm'] == 20.
    assert cfg['prior_physical_grasp_verified']
    assert new_red_teaching.read_bytes() == before
    assert not json.loads(before)['physical_grasp_verified']
    assert cfg['source_grasp_review_sha256']


@pytest.mark.parametrize('change', ['pickup', 'evidence', 'confirmation', 'axis'])
def test_new_red_rejects_changed_or_unconfirmed_review(new_red_teaching, change):
    review_path = new_red_teaching.parent/'manual-grasp-review.json'
    review = json.loads(review_path.read_text())
    if change == 'pickup':
        new_red_teaching.write_text(new_red_teaching.read_text()+' ')
    elif change == 'evidence':
        (new_red_teaching.parent/'lift.json').write_text('changed')
    elif change == 'confirmation':
        review['operator_exact_grasp_confirmed'] = False
    else:
        review['grasp_basis'] = 'OTHER_AXIS'
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError): trial.prepare(new_red_teaching, trial.RED_SLOT_ID)
