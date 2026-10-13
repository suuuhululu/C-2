import json
import pytest

from app.mvp_plan_replay import approved_input, replay


def write_log(tmp_path, rows):
    path = tmp_path/'job.jsonl'
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    return path


def test_replay_uses_approved_design_and_last_accepted_current(tmp_path):
    current = dict(current_revision=4, blocks=[])
    design = dict(design_version=2, blocks=[])
    rows = [dict(event='JOB_STARTED', job_id='J01'),
        dict(event='CHECK_RESULT', result=dict(disposition='ACCEPTED',
            response=dict(status='OK', current=current))),
        dict(event='CHECK_RESULT', result=dict(disposition='STALE',
            response=dict(status='OK', current=dict(current_revision=100, blocks=[])))),
        dict(event='MODULE_RESULT', job_id='J01', result=dict(port='c.initial',
            response=dict(status='OK', design=dict(design_version=1, blocks=[])))),
        dict(event='MODULE_RESULT', job_id='J01', result=dict(port='c.review',
            response=dict(status='OK', hri_result='APPROVE', design=design)))]
    assert approved_input(write_log(tmp_path, rows)) == (design, current, 'J01')


@pytest.mark.parametrize('decision', ['MODIFY', 'UNCLEAR', 'CANCEL'])
def test_unapproved_design_is_not_replayed(tmp_path, decision):
    rows = [dict(event='MODULE_RESULT', job_id='J01', result=dict(port='c.review',
        response=dict(status='OK', hri_result=decision, design=dict(design_version=1, blocks=[]))))]
    with pytest.raises(ValueError, match='APPROVE'):
        approved_input(write_log(tmp_path, rows))


def test_missing_current_never_fabricates_empty_assembly_board(tmp_path):
    rows = [dict(event='MODULE_RESULT', job_id='J01', result=dict(port='c.review',
        response=dict(status='OK', hri_result='APPROVE', design=dict(design_version=1, blocks=[]))))]
    with pytest.raises(ValueError, match='Current'):
        approved_input(write_log(tmp_path, rows))


def test_replay_saves_actual_a_request_and_raw_result_without_running_robot(tmp_path, monkeypatch):
    from app.mvp_fake import settings
    monkeypatch.setattr('app.cad_trial.measured_inputs', lambda root: {})
    monkeypatch.setattr('app.mvp_real_trial.real_settings', lambda inputs: settings())
    def no_robot(*args, **kwargs):
        raise AssertionError('offline replay must not create RobotProcess')
    monkeypatch.setattr('app.mvp_integration.RobotProcess', no_robot)
    design = dict(design_version=1, blocks=[dict(brick_type='2x2x1', color='yellow',
        x=6, y=6, layer=1, orientation_deg=0)])
    current = dict(current_revision=0, blocks=[])
    rows = [dict(event='CHECK_RESULT', result=dict(disposition='ACCEPTED',
        response=dict(status='OK', current=current))),
        dict(event='MODULE_RESULT', job_id='J01', result=dict(port='c.review',
            response=dict(status='OK', hri_result='APPROVE', design=design)))]
    output = tmp_path/'output'
    assert replay(write_log(tmp_path, rows), tmp_path, output) == 0
    report = json.loads((output/'replay.json').read_text())
    assert report['request']['design'] == design and report['request']['current'] == current
    assert report['raw_result']['planning_result']['status'] == 'READY'
    assert report['result']['execution_allowed'] is False
    assert report['original_request_recorded'] is False
    assert report['robot_executed'] is False and report['external_api_called'] is False
