"""Check both scenario inputs, immutable assets, and saved Plan continuation."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from scenario_core import Scenario
from sim_utils import load


@pytest.mark.parametrize('fixture,count', [
    ('whole.complete_first.request.json', 1),
    ('whole.chair.regression.request.json', 12),
])
def test_each_step_reassesses_with_preserved_plan_and_latest_mock_current(tmp_path, fixture, count):
    request = load(ROOT/'config'/fixture)
    before = deepcopy(request)
    scenario = Scenario(tmp_path, whole_request=request)
    assert request == before
    assert len(scenario.plan['steps']) == count
    start = {'frame_id': 'base_link', 'xyz_m': [.3, 0, .2], 'quaternion_xyzw': [0, 1, 0, 0]}
    plan = deepcopy(scenario.plan)
    for i in range(count):
        step, slot, model, result, folder = scenario.prepare(i, start, [])
        assert result['status'] == 'CANDIDATE' and result['execution_allowed'] is False
        assert model['current']['current_revision'] == i
        assert len(model['current_models']) == i
        assert load(folder/'reassessment.request.json')['plan_base_current'] == before['current']
        scenario.mock_complete(step, slot)
        assert scenario.plan == plan
    assert scenario.current['current_revision'] == count
    assert sorted(map(lambda b: json.dumps(b, sort_keys=True), scenario.current['blocks'])) == sorted(map(lambda b: json.dumps(b, sort_keys=True), before['design']['blocks']))


def test_reuse_keeps_saved_chair_input_instead_of_red_default(tmp_path):
    first = Scenario(tmp_path, whole_request=load(ROOT/'config/whole.chair.regression.request.json'))
    continued = Scenario(tmp_path, reuse=True)
    assert continued.whole_request == first.whole_request
    assert continued.plan == first.plan
    assert len(continued.plan['steps']) == 12
    assert len(continued.template_model['supply']['slots']) == 24


def test_all_frozen_source_inputs_and_original_meshes_match():
    for relative, expected in load(ROOT/'fixtures/protected_sources.json').items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == expected, relative


def test_original_and_canonical_mesh_references_resolve_inside_package():
    raw = ROOT/'assets/original_robot'
    for mesh in ET.parse(raw/'m0609_rg2.urdf').findall('.//mesh'):
        assert (raw/mesh.get('filename')).is_file()
    canonical = ROOT/'ros_ws/src/m0609_rg2_sim_model'
    for mesh in ET.parse(canonical/'urdf/m0609_rg2_sim.urdf').findall('.//mesh'):
        relative = mesh.get('filename').removeprefix('package://m0609_rg2_sim_model/')
        assert (canonical/relative).is_file()
