"""Canonical facing rule (Wave 2, 2026-10-12): one constant shared by both generation system prompts.

Facing is a prompt-level soft goal: the validator, the Design schema and the designer are not involved, and in Revised
generation the Current outranks it (CONTRACT §8.9). Sol smoke results live in the Wave 2 report, not here.
"""

import json
from pathlib import Path

from app.c_design import llm, validator

FIXTURES = Path(__file__).parents[2] / "fixtures" / "c_design_change"


def test_facing_rule_constant_states_the_canonical_direction():
    assert "faces +X" in llm._FACING_RULE and "low-x edge" in llm._FACING_RULE
    assert "viewed from the +X side" in llm._FACING_RULE
    assert "Never add a backrest only to show direction" in llm._FACING_RULE  # stool / ottoman / bench stay backless


def test_both_generation_prompts_share_the_single_constant():
    assert llm.SYSTEM_PROMPT_INITIAL.count(llm._FACING_RULE) == 1
    assert llm.SYSTEM_PROMPT_REVISED.count(llm._FACING_RULE) == 1
    # Interpretation / judge / describe prompts do not carry a placement rule.
    for prompt in (llm.SYSTEM_PROMPT_INTERVENTION_ANSWER, llm.SYSTEM_PROMPT_DESIGN_CHANGE_ANSWER, llm.SYSTEM_PROMPT_REVIEW,
                   llm.SYSTEM_PROMPT_REQUEST):
        assert llm._FACING_RULE not in prompt


def test_initial_prompt_places_facing_between_build_hints_and_procedure():
    prompt = llm.SYSTEM_PROMPT_INITIAL
    assert prompt.index(llm._BUILD_HINTS) < prompt.index(llm._FACING_RULE) < prompt.index(llm._PROCEDURE)


def test_revised_prompt_places_facing_before_expressive_hints():
    prompt = llm.SYSTEM_PROMPT_REVISED
    assert prompt.index(llm._BUILD_HINTS) < prompt.index(llm._FACING_RULE) < prompt.index(llm._EXPRESSIVE_HINTS)


def test_revised_priorities_put_current_before_rules_before_facing():
    text = llm._REVISED_PRIORITIES
    first, second, facing = text.index("- First, every Current block"), text.index("- Second, the result passes every rule"), \
        text.index("keep the canonical facing")
    assert first < second < facing
    assert "do not move, rotate, recolour or drop a Current block" in text
    assert "follow the Current's facing instead" in text
    # Both Revised guidance variants (Difference / Design Change) inherit the same line exactly once.
    for guidance in (llm._REVISED_GUIDANCE, llm._REVISED_DESIGN_CHANGE_GUIDANCE):
        assert guidance.count("keep the canonical facing") == 1


def test_revised_user_messages_carry_the_priority_line_in_both_modes():
    approved = json.loads((FIXTURES / "approved_design.json").read_text(encoding="utf-8"))
    current = json.loads((FIXTURES / "current_prefix.json").read_text(encoding="utf-8"))
    diff = [{"expected": approved["blocks"][0], "actual": None}]
    difference = llm._revised_user_message(approved, current, diff, [])
    change = llm._revised_user_message(approved, current, [], [], change_request="등받이를 더 높여줘")
    for message in (difference, change):
        assert "keep the canonical facing" in message and message.count("keep the canonical facing") == 1
    assert llm._REVISED_DIFFERENCE_NOTE in difference and llm._REVISED_DESIGN_CHANGE_NOTE in change  # Wave 3 split kept


def test_facing_is_not_a_validator_or_schema_rule():
    source = Path(validator.__file__).read_text(encoding="utf-8")
    assert "facing" not in source.lower()
    assert validator.BLOCK_FIELDS == ("brick_type", "color", "x", "y", "layer", "orientation_deg")
    assert validator.TOP_FIELDS == ("design_version", "blocks")
