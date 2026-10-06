"""B/C DM 합의의 D 소비 예시. 실제 생산자·완료·Robot 실행 시험은 아니다."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.contracts import validate_design, validate_observed
from app.current import adopt_observation, open_observation_check
from app.hmi_contracts import validate_hmi_snapshot

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / 'interfaces/fixtures/team_handoff.json').read_text()
)


def context(check_id='J01:C07'):
    return open_observation_check(check_id, 'J01', 'P01', 'S03')


@pytest.mark.parametrize('case', FIXTURES['observation_cases'], ids=lambda c: c['name'])
def test_observed_to_current_handoff_keeps_actual_evidence_and_hidden_history(case):
    observation = validate_observed(case['observed'])
    result = adopt_observation(case['current'], context(case['check_id']), observation)
    for field, expected in case['expected'].items():
        assert result[field] == expected
    # Current 채택은 Step 완료나 다음 Robot 발행을 수행하지 않는다.
    assert 'completed' not in result and 'delivery' not in result


def test_multiview_results_arriving_in_reverse_order_cannot_replace_newer_layout():
    match, mismatch = FIXTURES['observation_cases'][:2]
    newer = adopt_observation(match['current'], context(), mismatch['observed'])
    older = adopt_observation(newer['current'], newer['active_check'], match['observed'])
    assert older['disposition'] == 'IGNORED'
    assert older['reason'] == 'STALE_OBSERVATION'
    assert older['current'] == newer['current']
    duplicate = adopt_observation(newer['current'], newer['active_check'], mismatch['observed'])
    assert duplicate['reason'] == 'STALE_OBSERVATION'


@pytest.mark.parametrize('active', [None, context('reopened-check')], ids=['closed', 'reopened'])
def test_cancelled_batch_never_gets_relabelled_to_current_check(active):
    case = FIXTURES['observation_cases'][0]
    result = adopt_observation(case['current'], active, case['observed'])
    assert result['disposition'] == 'IGNORED'
    assert result['current'] == case['current']
    assert result['active_check'] == active


def test_new_batch_check_accepts_session_sequence_without_requiring_a_zero_reset():
    case = FIXTURES['observation_cases'][0]
    payload = {**case['observed'], 'check_id': 'new-check', 'observation_seq': 200}
    result = adopt_observation(case['current'], context('new-check'), payload)
    assert result['current'] == case['expected']['current']
    assert result['active_check']['last_observation_seq'] == 200


@pytest.mark.parametrize('case', FIXTURES['place_display_cases'], ids=lambda c: c['name'])
def test_place_display_never_converts_unknown_or_pending_to_empty(case):
    result = validate_hmi_snapshot(case['snapshot'])
    assert result['monitor']['place_status'] == case['snapshot']['monitor']['place_status']
    assert result['notice']['reason'] == case['snapshot']['notice']['reason']
    # 조립 관측과 전달판 상태는 서로 독립적이며 버튼에 판별 제한을 추가하지 않는다.
    assert result['step'] == case['snapshot']['step']
    assert result['actions'] == case['snapshot']['actions']


@pytest.mark.parametrize('name', FIXTURES['design_cases'])
def test_c_design_candidates_use_full_layout_without_physical_block_identity(name):
    value = validate_design(FIXTURES['design_cases'][name])
    assert len(value['blocks']) == 3
    assert all(set(block) == {'brick_type', 'color', 'x', 'y', 'layer', 'orientation_deg'}
               for block in value['blocks'])


def test_past_tracking_block_cannot_be_added_to_common_observed_payload():
    case = FIXTURES['observation_cases'][0]
    payload = {**deepcopy(case['observed']), 'tracked_blocks': case['current']['blocks']}
    with pytest.raises(ValueError, match='tracked_blocks'):
        validate_observed(payload)
