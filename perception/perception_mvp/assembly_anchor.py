"""Fixed first-placement frame; Observed always remains in board coordinates."""
from copy import deepcopy
from dataclasses import dataclass

from .contracts import validate_block


@dataclass(frozen=True)
class AssemblyAnchor:
    reference_x: int
    reference_y: int
    board_x: int
    board_y: int

    @classmethod
    def from_first_block(cls, design_blocks, reference_index, observed_first):
        """Caller explicitly selects the matching design block, once per job.

        Validate the entire translated final design before adopting the anchor.
        No automatic rotation, clipping or later re-anchoring is performed.
        """
        if not design_blocks or type(reference_index) is not int or not 0 <= reference_index < len(design_blocks):
            raise ValueError("explicit final design and reference index required")
        for block in design_blocks:
            validate_block(block)
        validate_block(observed_first)
        reference = design_blocks[reference_index]
        if any(reference[k] != observed_first[k] for k in
               ("brick_type", "color", "layer", "orientation_deg")):
            raise ValueError("first block does not match the selected design reference")
        anchor = cls(reference["x"], reference["y"], observed_first["x"], observed_first["y"])
        anchor.translate_design(design_blocks)
        return anchor

    def translate_design(self, blocks):
        """Translate ORIGINAL design coordinates, never already-shifted Expected."""
        for value in (self.reference_x, self.reference_y, self.board_x, self.board_y):
            if type(value) is not int or not 0 <= value < 24:
                raise ValueError("anchor requires integer board coordinates")
        result = deepcopy(blocks)
        for block in result:
            validate_block(block)
            block["x"] += self.board_x - self.reference_x
            block["y"] += self.board_y - self.reference_y
            validate_block(block)
        return result

    def relative_observation(self, board_blocks):
        """Internal relative representation; NOT an Observed payload.

        Negative relative coordinates are valid. Actual observations are neither
        shifted nor snapped to the target; Backend receives the original blocks.
        """
        result = deepcopy(board_blocks)
        for block in result:
            validate_block(block)
            block["x"] -= self.board_x
            block["y"] -= self.board_y
        return result
