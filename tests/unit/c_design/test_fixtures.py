"""Run the shared C fixtures through validator and dialogue (Contract §3·§5·§8·§9)."""

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
REVISED = load("revised_before_after.json")
# A valid single Difference so current_cases can be checked in isolation.
ONE_DIFFERENCE = [{"expected": INITIAL["bricks"][0], "actual": INITIAL["bricks"][0]}]


def test_initial_design_is_valid_and_centered():
    assert validator.validate_design(INITIAL) == []
    cells = set().union(*(validator.footprint(b) for b in INITIAL["bricks"]))
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    # §3.3: bounding-box min stud follows the formula, not a brick anchor at 24 // 2.
    assert (min(xs), min(ys)) == ((24 - width) // 2, (24 - height) // 2)


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


def test_revised_example_passes_and_keeps_ids():
    assert validator.validate_revised(REVISED["candidate"], REVISED["input_design"], REVISED["current"]) == []
    assert validator.validate_design(REVISED["revised"]) == []
    revised_ids = {b["block_id"] for b in REVISED["revised"]["bricks"]}
    # §8.3: assembled bricks keep id and values.
    for cur in REVISED["current"]:
        assert cur in REVISED["revised"]["bricks"]
    # §8.4: ids written by the LLM are kept; new ids start after the input Design's max number.
    kept = {b["block_id"] for b in REVISED["candidate"]["bricks"] if b["block_id"] is not None}
    new = revised_ids - kept
    input_max = max(int(b["block_id"][1:]) for b in REVISED["input_design"]["bricks"])
    assert new and min(int(i[1:]) for i in new) == input_max + 1
    assert (REVISED["revised"]["design_version"], REVISED["revised"]["parent_version"]) == (2, 1)


@pytest.mark.parametrize("name", ["revised_invalid_cases.json", "llm_output_invalid.json"])
def test_invalid_revised_candidates_rejected(name):
    data = load(name)
    for case in data["cases"]:
        candidate = case.get("candidate", case.get("raw"))
        found = rules(validator.validate_revised(candidate, data["input_design"], data["current"]))
        assert set(case["expected_rules"]) <= found, case["case"]


@pytest.mark.parametrize("row", load("dialogue_responses.json")["intervention"], ids=lambda r: r["case"])
def test_dialogue_responses(row):
    assert dialogue.parse_response(row["text"]) == row["expected"]
    assert dialogue.is_meaningful(row["text"]) is row["meaningful"]


@pytest.mark.parametrize("row", load("dialogue_responses.json")["goal"], ids=lambda r: r["case"])
def test_goal_responses(row):
    assert dialogue.parse_goal(row["text"]) == row["expected"]
