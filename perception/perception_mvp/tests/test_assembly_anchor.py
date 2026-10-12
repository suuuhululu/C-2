from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from perception_mvp.assembly_anchor import AssemblyAnchor
from perception_mvp.visualization import freeze_overlay_states


def block(x, y, *, layer=1, color="yellow", kind="2x2x1", angle=0):
    return dict(brick_type=kind, color=color, x=x, y=y,
                layer=layer, orientation_deg=angle)


def test_first_placement_translates_whole_design_preserves_spacing_and_inputs():
    design = [block(10, 10), block(12, 10, layer=2)]
    original = deepcopy(design)
    anchor = AssemblyAnchor.from_first_block(design, 0, block(3, 5))
    assert anchor.translate_design(design) == [block(3, 5), block(5, 5, layer=2)]
    assert design == original
    with pytest.raises(FrozenInstanceError):
        anchor.board_x = 9


def test_actual_previous_and_new_blocks_share_fixed_relative_frame():
    anchor = AssemblyAnchor.from_first_block([block(10, 10)], 0, block(3, 5))
    observed = [block(3, 5), block(1, 4), block(15, 15)]
    original = deepcopy(observed)
    assert anchor.relative_observation(observed) == [block(0, 0), block(-2, -1), block(12, 10)]
    assert observed == original


@pytest.mark.parametrize("observed", [block(22, 10), block(0, 10)])
def test_valid_first_block_but_final_design_outside_board_rejected(observed):
    with pytest.raises(ValueError, match="whole footprint"):
        AssemblyAnchor.from_first_block([block(10, 10), block(12, 10), block(8, 10)], 0, observed)


def test_rotated_2x3_full_footprint_and_boundary():
    design = [block(10, 10, kind="2x3x1", angle=90)]
    anchor = AssemblyAnchor.from_first_block(design, 0, block(21, 22, kind="2x3x1", angle=90))
    assert anchor.translate_design(design)[0]["x"] == 21
    with pytest.raises(ValueError):
        AssemblyAnchor.from_first_block(design, 0, block(22, 22, kind="2x3x1", angle=90))


@pytest.mark.parametrize("first", [block(3, 5, color="blue"), block(3, 5, layer=2)])
def test_no_guessing_reference_identity(first):
    with pytest.raises(ValueError, match="does not match"):
        AssemblyAnchor.from_first_block([block(10, 10)], 0, first)


def test_overlay_translates_only_original_target_keeps_actual_current():
    design = [block(10, 10), block(12, 10, layer=2)]
    anchor = AssemblyAnchor.from_first_block(design, 0, block(3, 5))
    current = [block(3, 5)]
    snapshot = freeze_overlay_states(current, design, {"check_id": "test"}, assembly_anchor=anchor)
    assert snapshot["current"] == current
    assert snapshot["expected"] == [block(3, 5), block(5, 5, layer=2)]
    current[0]["x"] = 7
    assert snapshot["current"][0]["x"] == 3


def test_existing_backend_board_coordinate_overlay_unchanged():
    current, expected = [block(3, 5)], [block(3, 5), block(5, 5, layer=2)]
    snapshot = freeze_overlay_states(current, expected, {}, assembly_anchor=None)
    assert snapshot["current"] == current and snapshot["expected"] == expected
