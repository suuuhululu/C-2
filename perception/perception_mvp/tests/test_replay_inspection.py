"""Submitted synthetic sample is replayed through the actual B state owner."""
from pathlib import Path
import json
import pytest

from perception_mvp.replay_inspection import replay, make_sample_observer


def test_submitted_sample_reproduces_normal_and_failure_outputs():
    sample = Path(__file__).resolve().parents[2]/'samples/inspection_replay/sample.json'
    result = replay(json.loads(sample.read_text()))
    assert result['checks'] == 7 and result['status'] == 'PASS'
    assert {row['result']['status'] for row in result['results']} == {'OK', 'UNOBSERVABLE', 'ERROR'}


def test_replay_never_mislabels_real_input_as_synthetic():
    with pytest.raises(ValueError, match='synthetic'):
        replay(dict(source='REAL'))


def test_sample_observer_is_explicit_and_retains_request_identity():
    path = Path(__file__).resolve().parents[2]/'samples/inspection_replay/sample.json'
    sample = json.loads(path.read_text())
    observe = make_sample_observer(sample, scenario_name='normal-and-failure')
    result, diagnostics = observe(dict(check_id='initial', observation_seq=3), lambda: True)
    assert result['check_id'] == 'initial' and result['observation_seq'] == 3
    assert diagnostics['source'] == 'SYNTHETIC_NOT_CAMERA'
    result['verified_regions'].clear()
    assert observe(dict(check_id='initial', observation_seq=4), lambda: True)[0]['verified_regions']
    with pytest.raises(ValueError, match='no synthetic observation'):
        observe(dict(check_id='unknown', observation_seq=0), lambda: True)
    with pytest.raises(RuntimeError, match='canceled'):
        observe(dict(check_id='initial', observation_seq=0), lambda: False)
    with pytest.raises(ValueError, match='synthetic'):
        make_sample_observer(dict(source='REAL'), scenario_name='normal-and-failure')
