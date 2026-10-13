"""The facing helper (tests/unit/c_design/c_facing_helper.py) is test-only: these pin its verdicts on the Wave 1 fixtures.

It is not applied to production generation in Wave 1 (no prompt or validator change); Wave 2 uses it for reports.
"""

import json
from pathlib import Path

import c_facing_helper as facing
from app.c_design import designer, validator

FIXTURES = Path(__file__).parents[2] / "fixtures" / "c_design_change"


def _design():
    return json.loads((FIXTURES / "approved_design.json").read_text(encoding="utf-8"))


def _mirror_x(blocks):
    """Reflect every footprint across the board centre so the backrest lands at high x; stays a valid Design."""
    out = []
    for block in blocks:
        studs = validator.footprint(block)
        width = max(s[0] for s in studs) - min(s[0] for s in studs) + 1
        out.append(dict(block, x=validator.BOARD_RANGE.stop - block["x"] - width))
    return out


def test_fixture_design_is_canonical_pass():
    verdict, info = facing.classify_facing(_design())
    assert verdict == facing.PASS, info
    assert info["seat_layer"] == 2 and info["dx"] < 0


def test_mirrored_design_fails_and_is_still_valid():
    mirrored = {"design_version": 1, "blocks": _mirror_x(_design()["blocks"])}
    assert validator.validate_design(mirrored) == []
    verdict, info = facing.classify_facing(mirrored)
    assert verdict == facing.FAIL and info["dx"] > 0


def test_turned_design_fails_on_y_offset():
    design = _design()
    turned = {"design_version": 1, "blocks": [dict(b, x=b["y"], y=b["x"], orientation_deg=90 - b["orientation_deg"])
                                             for b in design["blocks"]]}
    assert validator.validate_design(turned) == []
    verdict, info = facing.classify_facing(turned)
    assert verdict == facing.FAIL and "y" in info["why"]


def test_mock_chair_without_readable_backrest_is_undefined_or_pass():
    # The deterministic Mock chair is the Day4 baseline; whatever it reads as, it must never be a crash.
    verdict, _ = facing.classify_facing(designer.build_initial_design("CHAIR")["design"])
    assert verdict in (facing.PASS, facing.FAIL, facing.UNDEFINED)


def test_seat_only_is_undefined():
    seat = [b for b in _design()["blocks"] if b["layer"] <= 2]
    assert facing.classify_facing(seat)[0] == facing.UNDEFINED


def test_follows_current_when_current_fixes_the_other_direction():
    mirrored = _mirror_x(_design()["blocks"])
    current = [b for b in mirrored if b["layer"] <= 3]  # seat plus the first backrest row already built at high x
    verdict, info = facing.classify_facing({"design_version": 2, "blocks": mirrored}, current=current)
    assert verdict == facing.FOLLOWS_CURRENT
    assert info["current"]["verdict"] == facing.FAIL


def test_canonical_current_does_not_excuse_a_flipped_design():
    current = [b for b in _design()["blocks"] if b["layer"] <= 3]
    flipped = {"design_version": 2, "blocks": _mirror_x(_design()["blocks"])}
    assert facing.classify_facing(flipped, current=current)[0] == facing.FAIL


def test_helper_is_not_imported_by_production():
    for path in (Path(__file__).parents[3] / "app").rglob("*.py"):
        assert "c_facing_helper" not in path.read_text(encoding="utf-8"), path
