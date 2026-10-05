"""Run the shared C fixtures through validator and dialogue (docs/06_CONTRACT_DRAFT.md §1·§2·§4·§5)."""

import json
from pathlib import Path

import pytest

from app.c_design import dialogue, validator

FIXTURES = Path(__file__).parent / "fixtures"


def _drop_notes(value):
    # Fixture authors document hand checks in "_note" keys; they are not contract data.
    if isinstance(value, dict):
        return {k: _drop_notes(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_drop_notes(v) for v in value]
    return value


def load(name):
    return _drop_notes(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def rules(reasons):
    return {r["rule"] for r in reasons}


def case_params(name):
    return [pytest.param(c, id=c["case"]) for c in load(name)["cases"]]


INITIAL = load("design_initial_valid.json")
# A valid single Difference so current_cases can be checked in isolation.
ONE_DIFFERENCE = [{"expected": INITIAL["blocks"][0], "actual": INITIAL["blocks"][0]}]


def test_initial_design_is_valid_and_centered():
    assert validator.validate_design(INITIAL) == []
    assert set(INITIAL.keys()) == set(validator.TOP_FIELDS)
    cells = set().union(*(validator.footprint(b) for b in INITIAL["blocks"]))
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    # §3.3: bounding-box min stud follows the formula, not a block anchor at 24 // 2.
    assert (min(xs), min(ys)) == ((24 - width) // 2, (24 - height) // 2)


def test_initial_design_blocks_use_lowercase_colors():
    for b in INITIAL["blocks"]:
        assert b["color"] in {"yellow", "blue"}


@pytest.mark.parametrize("case", case_params("design_invalid_cases.json"))
def test_invalid_designs_rejected(case):
    assert set(case["expected_rules"]) <= rules(validator.validate_design(case["design"]))


@pytest.mark.parametrize("case", case_params("current_cases.json"))
def test_current_input_cases(case):
    design = load("current_cases.json")["design"]
    found = rules(validator.check_intervention_input(design, case["current"], ONE_DIFFERENCE))
    if case["expected_input_rules"]:
        assert set(case["expected_input_rules"]) <= found
    else:
        assert found == set()
    assert bool(validator.current_support_violations(case["current"])) is case["support_violation"]


@pytest.mark.parametrize("case", case_params("difference_cases.json"))
def test_difference_input_cases(case):
    found = rules(validator.check_intervention_input(INITIAL, [], case["differences"]))
    if case["expected_input_rules"]:
        assert set(case["expected_input_rules"]) <= found
    else:
        assert found == set()


def test_revised_example_passes_and_preserves_current_by_value():
    data = load("revised_before_after.json")
    assert validator.validate_revised(data["candidate"], data["current"]) == []
    assert validator.validate_design(data["revised"]) == []
    # §4: assembled (current) blocks keep their exact values in the final Revised.
    for cur in data["current"]:
        assert cur in data["revised"]["blocks"]
    assert data["revised"]["design_version"] == data["design"]["design_version"] + 1


@pytest.mark.parametrize("name", ["revised_invalid_cases.json", "llm_output_invalid.json"])
def test_invalid_revised_candidates_rejected(name):
    data = load(name)
    for case in data["cases"]:
        found = rules(validator.validate_revised(case["candidate"], data["current"]))
        assert set(case["expected_rules"]) <= found, case["case"]


@pytest.mark.parametrize("row", load("dialogue_responses.json")["intervention"], ids=lambda r: r["case"])
def test_dialogue_responses(row):
    assert dialogue.parse_response(row["text"]) == row["expected"]
    assert dialogue.is_meaningful(row["text"]) is row["meaningful"]


@pytest.mark.parametrize("row", load("dialogue_responses.json")["goal"], ids=lambda r: r["case"])
def test_goal_responses(row):
    assert dialogue.parse_goal(row["text"]) == row["expected"]
