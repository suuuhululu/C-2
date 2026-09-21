import json
from copy import deepcopy
from pathlib import Path

import pytest
from app.storage import Storage
from app.recover_preparation import validate_rejection, recover


def fixture(tmp_path):
    store = Storage(tmp_path)
    source = Path(__file__).resolve().parents[2]/'ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/success.json'
    sample = json.loads(source.read_text())
    goal = sample['goal']; goal['source_mode'] = 'REAL'
    config = store.put_json({'controller_prefix':'/dsr01/dsr_controller2'}, 'preparation_config', 'config.json')
    goal.update(input_profile_snapshot_id=config['id'], input_profile_sha256=config['sha256'])
    result = sample['result']
    result.update({k:v for k,v in goal.items() if k != 'schema_version'})
    result.update(outcome='FAILED', error_code='NOT_READY', message='정지 래치 또는 로봇 제어권 미확인',
                  contact_indices=[], geometry_ready=False, snapshot_bound=False, stop_confirmed=False)
    raw = store.put_json(dict(contract='prepare-workpiece-result/1', result=result), 'measurement_record', 'result.json')
    record = dict(request_id=goal['request_id'], state='UNKNOWN', action_goal=goal,
                  feedback=[dict(stage='ROBOT_CHECK')], measurement_record=raw, result=deepcopy(result))
    store.save_preparation(record)
    return store, record, result


def test_recovery_keeps_failure_and_writes_audit(tmp_path):
    store, record, raw = fixture(tmp_path)
    checked, config = validate_rejection(store, record['request_id'])
    output = recover(store, checked, {'operator_confirmed_stopped':True, 'test_only':True})
    assert output['state'] == 'INVALIDATED' and output['binding_status'] == 'UNCONFIRMED'
    assert output['result'] == raw and output['result']['stop_confirmed'] is False
    audit = json.loads(store.read_asset(output['recovery_record']['id']))
    assert audit['before']['state'] == 'UNKNOWN'
    assert store.recover_preparation()['state'] == 'INVALIDATED'


@pytest.mark.parametrize('defect', ['motion_stage', 'contacts', 'other_error', 'id', 'bind', 'hash'])
def test_non_precheck_failures_cannot_be_recovered(tmp_path, defect):
    store, record, result = fixture(tmp_path)
    if defect == 'motion_stage': record['feedback'].append(dict(stage='HOME_MOVE'))
    if defect == 'contacts': result['contact_indices'] = [0]
    if defect == 'other_error': result['message'] = '실제 이동 실패'
    if defect == 'id': result['measurement_id'] = 'wrong'
    if defect == 'bind': record['bind_goal'] = {'operation':'BIND_SNAPSHOT'}
    raw = store.put_json(dict(contract='prepare-workpiece-result/1', result=result), 'measurement_record', 'result.json')
    record['measurement_record'] = raw
    if defect == 'hash': record['measurement_record']['sha256'] = '0'*64
    store.save_preparation(record)
    with pytest.raises(ValueError): validate_rejection(store, record['request_id'])
