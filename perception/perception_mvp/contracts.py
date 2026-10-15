"""Day4 placement/region boundary; calibrated candidate conversion is internal."""
import math

BLOCK_FIELDS = {"brick_type", "color", "x", "y", "layer", "orientation_deg"}
CLASS_NAMES = {0: "yellow_2x2", 1: "yellow_2x3", 2: "blue_2x2", 3: "blue_2x3"}
LIVE_CLASSES = (*CLASS_NAMES.values(), "red_2x1")

# INITIAL tolerance counts board columns, not individual layer cells. A single
# unverified layer makes its whole column unavailable for subsequent placement.
INITIAL_MAX_UNKNOWN_COLUMNS = 60


def unverified_columns(verified):
    return {(x, y) for y in range(24) for x in range(24)
            if any((x, y, layer) not in verified for layer in range(1, 6))}


def footprint(block):
    width, height = {"1x2x1": (1, 2), "2x2x1": (2, 2), "2x3x1": (2, 3)}[block["brick_type"]]
    if block["orientation_deg"] == 90:
        width, height = height, width
    return {(x, y, block["layer"]) for x in range(block["x"], block["x"] + width)
            for y in range(block["y"], block["y"] + height)}


def validate_block(block):
    if set(block) != BLOCK_FIELDS:
        raise ValueError("placement requires exactly the six common fields")
    if (block["brick_type"] not in ("1x2x1", "2x2x1", "2x3x1") or
            block["color"] not in (("red",) if block["brick_type"] == "1x2x1" else ("yellow", "blue"))):
        raise ValueError("unsupported brick type or color")
    if any(type(block[k]) is not int for k in ("x", "y", "layer", "orientation_deg")):
        raise ValueError("placement coordinates must be integers")
    allowed = (0,) if block["brick_type"] == "2x2x1" else (0, 90)
    if block["orientation_deg"] not in allowed or not 1 <= block["layer"] <= 5:
        raise ValueError("unsupported orientation or layer")
    if any(not (0 <= x < 24 and 0 <= y < 24) for x, y, _ in footprint(block)):
        raise ValueError("whole footprint must fit the board")


def region_cells(regions):
    cells = set()
    for region in regions:
        if set(region) != {"x", "y", "width", "height", "layer"}:
            raise ValueError("region requires x/y/width/height/layer")
        if any(type(value) is not int for value in region.values()):
            raise ValueError("region fields must be integers")
        if not (0 <= region["x"] < region["x"] + region["width"] <= 24 and
                0 <= region["y"] < region["y"] + region["height"] <= 24 and
                1 <= region["layer"] <= 5):
            raise ValueError("invalid verified region")
        cells.update((x, y, region["layer"])
                     for x in range(region["x"], region["x"] + region["width"])
                     for y in range(region["y"], region["y"] + region["height"]))
    return cells


def placement_key(block):
    validate_block(block)
    return tuple(block[k] for k in sorted(BLOCK_FIELDS))


def candidate_to_block(candidate, center_to_anchor_offsets):
    """No default anchor offset. Input offsets must follow calibrated grid convention."""
    if candidate["status"] != "CANDIDATE":
        raise ValueError("unverified candidate cannot become visible block")
    name = candidate["part_class"]
    if name not in LIVE_CLASSES:
        raise ValueError("unsupported detector class")
    color, size = name.split("_")
    angle = candidate["axis_angle_deg"]
    if angle not in (0, 90):
        raise ValueError("axis angle must be grid-aligned")
    # Core angle is long-axis from +X; common 2x3 angle 0 has long-axis along +Y.
    orientation = 0 if size == "2x2" else (90 if angle == 0 else 0)
    offsets = center_to_anchor_offsets[name][str(orientation)]
    center = candidate["grid_center_stud"]
    if len(center) != 2 or len(offsets) != 2:
        raise ValueError("two center coordinates and two calibrated offsets required")
    anchor = [float(c) - float(o) for c, o in zip(center, offsets)]
    if any(not math.isfinite(v) or abs(v - round(v)) > 1e-6 for v in anchor):
        raise ValueError("calibrated anchor must land on integer grid")
    index = candidate["measured_layer_index"]
    if type(index) is not int or not 0 <= index <= 4:
        raise ValueError("invalid internal height index")
    block = {"brick_type": ("1x2x1" if name == "red_2x1" else size + "x1"), "color": color, "x": round(anchor[0]),
             "y": round(anchor[1]), "layer": index + 1, "orientation_deg": orientation}
    validate_block(block)
    return block
