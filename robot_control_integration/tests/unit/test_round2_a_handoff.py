"""Preserve the A source candidate and demonstrate the existing route mismatch."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.assembly_step_bridge import build_plan
from app.integration_motion_binding import verify_motion


def handoff_example():
    return json.loads((Path(__file__).resolve().parents[2]/
                       'interfaces/round2_a_handoff.proposed.json').read_text())


def test_handoff_preserves_a_candidate_and_explicitly_has_no_execution_authority():
    example = handoff_example()
    document = example['existing_a_d_document']
    profile = document['d_profile']
    plan = build_plan(document['step'], profile)
    verify_motion(document['motion']['motion_proposal'], plan, profile,
                  document['request']['robot_state'])
    assert example['status'] == 'A_D_REVIEW_PENDING'
    assert example['provenance'] == 'SYNTHETIC_CONTRACT_EXAMPLE'
    assert example['execution_allowed'] is False
    assert document['motion']['execution_allowed'] is False
    assert example['physical_commands'] == 0


def test_requested_observation_route_is_not_authorized_by_original_a_waypoints():
    example = handoff_example()
    document = example['existing_a_d_document']
    proposal = deepcopy(document['motion']['motion_proposal'])
    waypoint = proposal['segments'][2]['waypoints'][3]
    assert waypoint['label'] == 'PLACE_BOARD'
    waypoint['label'] = example['requested_changes']['robot_loaded_transit'][-1]['label']
    plan = build_plan(document['step'], document['d_profile'])
    with pytest.raises(ValueError, match='A_D_ROUTE_LABELS_DIFFER'):
        verify_motion(proposal, plan, document['d_profile'], document['request']['robot_state'])
