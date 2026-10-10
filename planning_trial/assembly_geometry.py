"""Board-mm envelope checks for candidate assembly, not robot/hand safety proof.

No learned stability, inverse kinematics, arm reachability or contact forces.
Explicit profile data are mandatory; TEST_ONLY dimensions never become defaults.
"""

from itertools import product
from math import isfinite

from planning_trial.planner import BOARD_SIZE, occupied_cells


DIMENSIONS = (
    "pitch_mm", "body_height_mm", "stud_height_mm", "finger_thickness_mm",
    "finger_length_mm", "finger_height_mm", "grip_bottom_offset_mm",
    "jaw_open_margin_mm", "minimal_jaw_open_margin_mm", "tool_body_width_mm", "tool_body_depth_mm",
    "tool_body_height_mm", "press_pad_width_mm", "press_pad_depth_mm",
    "press_tip_height_mm", "release_raise_mm", "hand_width_mm", "hand_depth_mm",
    "hand_height_mm", "hand_reach_mm", "clearance_mm",
)
SIDES = ("-x", "+x", "-y", "+y")
STUD_DIMENSIONS = ("pitch_mm", "body_height_mm", "stud_height_mm", "grip_bottom_offset_mm")


class MissingContext(ValueError):
    """Required geometry/policy is absent, distinct from malformed input."""


def validate_context(context):
    if context is None:
        raise MissingContext("assembly_context is required; no measured dimensions inferred")
    if not isinstance(context, dict):
        raise ValueError("assembly_context must be an explicit object")
    if 'supported_modes' in context:
        modes = context['supported_modes']
        if (not isinstance(modes, list) or not modes or
                any(m not in ('ROBOT_GRIP', 'ROBOT_RELEASE_PRESS', 'HUMAN_ASSEMBLY') for m in modes) or
                len(modes) != len(set(modes))):
            raise ValueError('supported_modes must list distinct recognized methods')
    if context.get("human_assembly_model","PAIRED_SEATED_SIDES") not in ("PAIRED_SEATED_SIDES","APPROACH_AND_TOP_CONTACT_REVIEW"):
        raise ValueError("Unknown human_assembly_model")
    if context.get("planning_priority","COMPLETE_DESIGN_THEN_MIN_HELP") not in ("MIN_HELP_COMPLETE_DESIGN_SEARCH","COMPLETE_DESIGN_THEN_MIN_HELP"):
        raise ValueError("Unknown planning_priority")
    required = {"profile_source", "geometry", "human_sides", "grip_axes",
                "finish_layers", "max_states", "minimal_release_model_confirmed",
                "press_contact_model_confirmed", "obstacles"}
    missing = sorted(name for name in required if context.get(name) is None)
    if missing:
        raise MissingContext("Missing assembly_context fields: " + ", ".join(missing))
    if context["profile_source"] not in ("TEST_ONLY", "MEASURED"):
        raise ValueError("profile_source must be TEST_ONLY or MEASURED")
    if context.get("space_model", "LEGACY_ENVELOPE") not in ("LEGACY_ENVELOPE", "STUD_RULES"):
        raise ValueError("Unknown space_model")
    if context.get("human_press_policy", "NONE") not in ("NONE", "CONTACT_HULL"):
        raise ValueError("Unknown human_press_policy")
    if context.get("space_model") == "STUD_RULES" and context.get("human_press_policy") is None:
        raise MissingContext("STUD_RULES needs an explicit human_press_policy")
    if (context.get("space_model") == "STUD_RULES" and
            type(context.get("hold_gripper_nonintrusion_assumption")) is not bool):
        raise MissingContext("STUD_RULES needs an explicit hold_gripper_nonintrusion_assumption")
    geometry = context["geometry"]
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be an object")
    names = STUD_DIMENSIONS if context.get("space_model") == "STUD_RULES" else DIMENSIONS
    for name in names:
        if geometry.get(name) is None:
            raise MissingContext("Missing geometry." + name)
        value = geometry.get(name)
        if (type(value) not in (int, float) or not isfinite(value) or
                (value < 0 if name in ("clearance_mm", "jaw_open_margin_mm") else
                 name != "grip_bottom_offset_mm" and value <= 0)):
            raise ValueError(f"geometry.{name} must be an explicit finite dimension in mm")
    if (geometry["grip_bottom_offset_mm"] >= geometry["body_height_mm"] or
            (context.get("space_model") != "STUD_RULES" and
             geometry["grip_bottom_offset_mm"] + geometry["finger_height_mm"] <= 0)):
        raise ValueError("Finger contact interval must overlap the held block's side face")
    if context.get("space_model") == "STUD_RULES":
        if not 0 <= geometry["stud_height_mm"] <= geometry["grip_bottom_offset_mm"]:
            raise ValueError("STUD_RULES requires tip at/above the lower stud top; equality is nominal tangency only")
    elif geometry["release_raise_mm"] < geometry["stud_height_mm"]:
        raise ValueError("release_raise_mm must be at least stud_height_mm")
    if (context.get("space_model") != "STUD_RULES" and
            geometry["minimal_jaw_open_margin_mm"] > geometry["jaw_open_margin_mm"]):
        raise ValueError("minimal_jaw_open_margin_mm must not exceed the normal release margin")
    for key, allowed in (("human_sides", SIDES), ("grip_axes", ("x", "y"))):
        values = context[key]
        if (not isinstance(values, list) or not values or
                any(v not in allowed for v in values) or len(values) != len(set(values))):
            raise ValueError(f"{key} must contain distinct values from {allowed}")
    for name in ("finish_layers", "press_contact_model_confirmed", "minimal_release_model_confirmed"):
        if type(context[name]) is not bool:
            raise ValueError(name + " must be a boolean")
    if type(context["max_states"]) is not int or context["max_states"] <= 0:
        raise ValueError("max_states must be a positive integer")
    if not isinstance(context["obstacles"], list):
        raise ValueError("obstacles must be a list of board-mm boxes")
    for box in context["obstacles"]:
        if (not isinstance(box, list) or len(box) != 6 or
                any(type(v) not in (int, float) or not isfinite(v) for v in box) or
                any(box[i] >= box[i + 3] for i in range(3))):
            raise ValueError("obstacle must be [xmin,ymin,zmin,xmax,ymax,zmax] in board mm")
    return context


def footprint(brick):
    return {(x, y) for x, y, _ in occupied_cells(brick)}


def contacts(brick, current):
    cells = footprint(brick)
    lower = [b for b in current if b["layer"] == brick["layer"] - 1]
    supported = cells if brick["layer"] == 1 else cells.intersection(
        set().union(*(footprint(b) for b in lower)))
    unseen, clusters = cells - supported, []
    while unseen:
        stack, component = [min(unseen)], set()
        while stack:
            cell = stack.pop()
            if cell not in unseen:
                continue
            unseen.remove(cell)
            component.add(cell)
            x, y = cell
            stack.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
        clusters.append(sorted(component))
    weak = []
    for b in lower:
        overlap = len(cells.intersection(footprint(b)))
        if 0 < overlap < 4 and b["layer"] > 1:
            count = len(footprint(b).intersection(set().union(*(
                footprint(c) for c in current if c["layer"] == b["layer"] - 1))))
            if count < 4:
                weak.append({"block": b.copy(), "upper_studs": overlap,
                             "lower_studs": count})
    return {"support_studs": len(supported), "total_studs": len(cells),
            "supported_cells": [list(c) for c in sorted(supported)],
            "missing_components": clusters,
            "largest_missing_component": max(map(len, clusters), default=0),
            "weak_supports": weak}


def block_box(brick, context, *, raise_mm=0):
    g, cells = context["geometry"], footprint(brick)
    p = g["pitch_mm"]
    z = (brick["layer"] - 1) * g["body_height_mm"] + raise_mm
    return ((min(x for x, _ in cells) - .5) * p,
            (min(y for _, y in cells) - .5) * p, z,
            (max(x for x, _ in cells) + .5) * p,
            (max(y for _, y in cells) + .5) * p,
            z + g["body_height_mm"] + g["stud_height_mm"])


def intersects(a, b):
    return all(a[i] < b[i + 3] and b[i] < a[i + 3] for i in range(3))


def free_boxes(boxes, current, context, other_boxes=()):
    g = context["geometry"]
    board_min, board_max = -.5 * g["pitch_mm"], (BOARD_SIZE - .5) * g["pitch_mm"]
    obstacles = [block_box(b, context) for b in current] + context["obstacles"] + list(other_boxes)
    for box in boxes:
        margin = g.get("clearance_mm", 0)
        padded = tuple(box[i] - margin for i in range(3)) + tuple(
            box[i + 3] + margin for i in range(3))
        # Treat board studs conservatively as a slab; no mesh-level clearance claim.
        if (padded[2] < g["stud_height_mm"] and padded[3] > board_min and
                padded[0] < board_max and padded[4] > board_min and padded[1] < board_max):
            return False
        if any(intersects(padded, obstacle) for obstacle in obstacles):
            return False
    return True


def grip_options(brick, current, context, *, raise_mm=0):
    if context.get("space_model") == "STUD_RULES":
        return stud_grip_options(brick, current, context, raise_mm=raise_mm)
    g, result = context["geometry"], []
    b = block_box(brick, context, raise_mm=raise_mm)
    cx, cy = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
    z = b[2] + g["grip_bottom_offset_mm"]
    high = max([b[5]] + [block_box(c, context)[5] for c in current] +
               [o[5] for o in context["obstacles"]]) + g["tool_body_height_mm"]
    t, length = g["finger_thickness_mm"], g["finger_length_mm"] / 2
    releases = [("NORMAL_OPEN", g["jaw_open_margin_mm"])]
    if context["minimal_release_model_confirmed"]:
        releases.append(("MINIMAL_OPEN", g["minimal_jaw_open_margin_mm"]))
    for axis, (release, opening) in product(context["grip_axes"], releases):
        if axis == "x":
            fingers = [(b[0] - opening - t, cy - length, z, b[0], cy + length, high),
                       (b[3], cy - length, z, b[3] + opening + t, cy + length, high)]
        else:
            fingers = [(cx - length, b[1] - opening - t, z, cx + length, b[1], high),
                       (cx - length, b[4], z, cx + length, b[4] + opening + t, high)]
        w, d = g["tool_body_width_mm"] / 2, g["tool_body_depth_mm"] / 2
        if axis == "y":
            w, d = d, w
        body = (cx - w, cy - d, z + g["finger_height_mm"], cx + w, cy + d,
                high + g["finger_height_mm"] + g["tool_body_height_mm"])
        boxes = fingers + [body]
        if free_boxes(boxes, current, context):
            result.append({"grip_axis": axis, "tool_boxes": boxes,
                           "release_strategy": release,
                           "release_margin_per_side_mm": opening})
    return result


def press_options(brick, current, context):
    g, b = context["geometry"], block_box(brick, context)
    if not context["press_contact_model_confirmed"]:
        return []
    if context.get("space_model") == "STUD_RULES":
        release = grip_options(brick, current, context, raise_mm=g["stud_height_mm"] + 20)
        high = max([b[5]] + [block_box(c, context)[5] for c in current] +
                   [o[5] for o in context["obstacles"]]) + g["body_height_mm"]
        cx, cy = (b[0]+b[3])/2, (b[1]+b[4])/2
        half = g["pitch_mm"]/2
        tip = (cx-half, cy-half, b[5], cx+half, cy+half, high)
        if free_boxes([tip], current, context):
            return [{**r, "tool_boxes": r["tool_boxes"] + [tip]} for r in release]
        return []
    release = grip_options(brick, current, context, raise_mm=g["release_raise_mm"])
    if not release:
        return []
    cx, cy = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
    high = max([b[5]] + [block_box(c, context)[5] for c in current] +
               [o[5] for o in context["obstacles"]]) + g["tool_body_height_mm"]
    w, d = g["press_pad_width_mm"] / 2, g["press_pad_depth_mm"] / 2
    tip = (cx - w, cy - d, b[5], cx + w, cy + d, high)
    w, d = g["tool_body_width_mm"] / 2, g["tool_body_depth_mm"] / 2
    body = (cx - w, cy - d, b[5] + g["press_tip_height_mm"], cx + w, cy + d,
            high + g["press_tip_height_mm"] + g["tool_body_height_mm"])
    if not free_boxes([tip, body], current, context):
        return []
    return [{**r, "tool_boxes": r["tool_boxes"] + [tip, body]}
            for r in release]


def hand_options(brick, current, context, other_boxes=(), *, assembly=False):
    """Straight side corridor of a hand/fixture envelope; human arm reach is unproved."""
    if context.get("space_model") == "STUD_RULES":
        if assembly and context.get("human_assembly_model","PAIRED_SEATED_SIDES") == "APPROACH_AND_TOP_CONTACT_REVIEW":
            seated=paired_hand_options(brick,current,context,other_boxes,assembly=True)
            return seated or manual_approach_top_options(brick,current,context,other_boxes)
        return paired_hand_options(brick, current, context, other_boxes, assembly=assembly)
    g, b = context["geometry"], block_box(brick, context)
    cx, cy = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
    low = b[2] + g["body_height_mm"] / 2 - g["hand_height_mm"] / 2
    high = low + g["hand_height_mm"]
    half, depth, result = g["hand_width_mm"] / 2, g["hand_depth_mm"], []
    board_lo, board_hi = -.5 * g["pitch_mm"], (BOARD_SIZE - .5) * g["pitch_mm"]
    world = [c for c in current if c != brick]
    for side in context["human_sides"]:
        if side == "-x":
            box, reach = (board_lo - depth, cy - half, low, b[0], cy + half, high), b[0] - board_lo
        elif side == "+x":
            box, reach = (b[3], cy - half, low, board_hi + depth, cy + half, high), board_hi - b[3]
        elif side == "-y":
            box, reach = (cx - half, board_lo - depth, low, cx + half, b[1], high), b[1] - board_lo
        else:
            box, reach = (cx - half, b[4], low, cx + half, board_hi + depth, high), board_hi - b[4]
        if assembly:
            # Include vertical insertion/withdrawal sweep of the manually held target.
            top = max([b[5]] + [block_box(c, context)[5] for c in world] +
                      [o[5] for o in context["obstacles"]]) + g["hand_height_mm"]
            boxes = [box, (min(box[0], b[0]), min(box[1], b[1]), low,
                           max(box[3], b[3]), max(box[4], b[4]), top)]
        else:
            boxes = [box]
        if reach <= g["hand_reach_mm"] and free_boxes(boxes, world, context, other_boxes):
            z0, z1 = max(low, b[2]), min(high, b[2] + g["body_height_mm"])
            if side.endswith("x"):
                x = b[0] if side == "-x" else b[3]
                region = [x, max(cy-half,b[1]), z0, x, min(cy+half,b[4]), z1]
            else:
                y = b[1] if side == "-y" else b[4]
                region = [max(cx-half,b[0]), y, z0, min(cx+half,b[3]), y, z1]
            result.append({"side": side, "boxes": boxes,
                           "contact_region_board_mm": region,
                           "frame_id": "assembly_board_mm", "force_command": None,
                           "effect": ("MANUAL_HOLD_AND_PLACE" if assembly else
                                      "RESTRAIN_TRANSLATION_AND_TILT_NOT_EXTRA_DOWN_PRESS")})
    return result


def support_assignments(weak, brick, current, context, tool_boxes=(), assembly_hand=None,
                        press_hand=None):
    reserved = assembly_hand or press_hand
    max_targets = 1 if reserved is not None else 2
    if len(weak) > max_targets:
        return []
    ignore_tool = (context.get("space_model") == "STUD_RULES" and
                   context["hold_gripper_nonintrusion_assumption"])
    other = ([] if ignore_tool else list(tool_boxes)) + (reserved["boxes"] if reserved else [])
    occupied = current + [brick]
    choices = [hand_options(w["block"], occupied, context, other) for w in weak]
    result = []
    for assignment in product(*choices):
        if any(intersects(a, b) for i, first in enumerate(assignment)
               for second in assignment[i + 1:] for a in first["boxes"] for b in second["boxes"]):
            continue
        result.append([{**w, **hand} for w, hand in zip(weak, assignment)])
    return result


def stud_grip_options(brick, current, context, *, raise_mm=0):
    """User's one-pitch side-space assumption, not a measured whole-gripper mesh."""
    g, result = context["geometry"], []
    b = block_box(brick, context, raise_mm=raise_mm)
    p, z = g["pitch_mm"], b[2]+g["grip_bottom_offset_mm"]
    high = max([b[5]] + [block_box(c, context)[5] for c in current] +
               [o[5] for o in context["obstacles"]]) + g["body_height_mm"]
    cells = footprint(brick)
    widths = (max(x for x,y in cells)-min(x for x,y in cells)+1,
              max(y for x,y in cells)-min(y for x,y in cells)+1)
    for axis in context["grip_axes"]:
        # A 2x3 is pinched across its short dimension, at its long-side centres.
        expected_axis=("x" if widths[0]>widths[1] else "y") if brick['brick_type']=='1x2x1' else ("x" if widths[0]<widths[1] else "y")
        if widths[0] != widths[1] and axis != expected_axis:
            continue
        if axis == "x":
            boxes = [(b[0]-p,b[1],z,b[0],b[4],high),(b[3],b[1],z,b[3]+p,b[4],high)]
        else:
            boxes = [(b[0],b[1]-p,z,b[3],b[1],high),(b[0],b[4],z,b[3],b[4]+p,high)]
        if free_boxes(boxes,current,context):
            result.append({"grip_axis":axis,"tool_boxes":boxes,
                           "release_strategy":"MINIMAL_OPEN", "release_margin_per_side_mm":None,
                           "clearance_pitch_per_side":1,
                           "space_basis":"USER_ONE_PITCH_RULE_NOT_FULL_TOOL_GEOMETRY"})
    return result


def body_box(brick, context):
    b = block_box(brick, context)
    return b[:5]+(b[2]+context["geometry"]["body_height_mm"],)


def hand_boxes_clear(boxes, current, context, other_boxes=()):
    # Local side-body rule; no arm corridor, lower stud detail or reachability claim.
    obstacles = [body_box(b,context) for b in current] + context["obstacles"] + list(other_boxes)
    return not any(intersects(box,obstacle) for box in boxes for obstacle in obstacles)


def paired_hand_options(brick, current, context, other_boxes=(), *, assembly=False, raise_mm=0):
    g, result = context["geometry"], []
    b = body_box(brick,context)
    b = tuple(v+raise_mm if i in (2,5) else v for i,v in enumerate(b))
    p, cx, cy = g["pitch_mm"], (b[0]+b[3])/2, (b[1]+b[4])/2
    world = [c for c in current if c != brick]
    axes = list(dict.fromkeys(side[-1] for side in context["human_sides"]))
    for axis in axes:
        if axis == "x":
            boxes = [(b[0]-p,cy-p/2,b[2],b[0],cy+p/2,b[5]),
                     (b[3],cy-p/2,b[2],b[3]+p,cy+p/2,b[5])]
            regions = [[b[0],cy-p/2,b[2],b[0],cy+p/2,b[5]],
                       [b[3],cy-p/2,b[2],b[3],cy+p/2,b[5]]]
        else:
            boxes = [(cx-p/2,b[1]-p,b[2],cx+p/2,b[1],b[5]),
                     (cx-p/2,b[4],b[2],cx+p/2,b[4]+p,b[5])]
            regions = [[cx-p/2,b[1],b[2],cx+p/2,b[1],b[5]],
                       [cx-p/2,b[4],b[2],cx+p/2,b[4],b[5]]]
        if hand_boxes_clear(boxes,world,context,other_boxes):
            result.append({"side":f"-{axis}/+{axis}","grip_axis":axis,"boxes":boxes,
                           "contact_region_board_mm":None,"contact_regions_board_mm":regions,
                           "frame_id":"assembly_board_mm","force_command":None,"hand_count":1,
                           "effect":"MANUAL_HOLD_AND_PLACE" if assembly else "RESTRAIN_TRANSLATION_AND_TILT_NOT_EXTRA_DOWN_PRESS",
                           "space_basis":"PAIRED_LOCAL_ONE_PITCH_BODY_HEIGHT_RULE"})
    return result


def manual_approach_top_options(brick,current,context,other_boxes=()):
    """Review candidate: side hold above neighbours, then top contact access.

    Keeps HOLD rules unchanged. Checks nominal approach, target-body vertical
    corridor, and top access. Human release/regrasp/final insertion is unverified;
    these independent free regions are not a verified continuous hand motion.
    """
    g=context["geometry"];b=body_box(brick,context)
    clearance=g["stud_height_mm"]+20.0  # same nominal pre-contact gap used by A
    hands=paired_hand_options(brick,current,context,other_boxes,assembly=True,raise_mm=clearance)
    if not hands:return []
    sweep=(b[0],b[1],b[2],b[3],b[4],b[5]+clearance)
    if not hand_boxes_clear([sweep],current,context,other_boxes):return []
    p=g["pitch_mm"];cx=(b[0]+b[3])/2;cy=(b[1]+b[4])/2
    low=b[5]+g["stud_height_mm"]
    high=max([low]+[block_box(c,context)[5] for c in current]+[o[5] for o in context["obstacles"]])+g["body_height_mm"]
    top=(cx-p/2,cy-p/2,low,cx+p/2,cy+p/2,high)
    if not free_boxes([top],current,context,other_boxes):return []
    for hand in hands:
        hand.update(boxes=hand["boxes"]+[sweep,top],
                    effect="MANUAL_HOLD_AND_PLACE",
                    space_basis="REVIEW_APPROACH_TARGET_CORRIDOR_AND_TOP_CONTACT_NOT_CONTINUOUS_HAND_PATH",
                    nominal_precontact_gap_mm=20.0,final_side_hold_required=False,
                    continuous_hand_transition_verified=False,physical_insertion_verified=False,
                    stages={"target_vertical_corridor":sweep,"final_top_contact_access":top})
    return hands


def convex_hull(points):
    points = sorted(set(map(tuple,points)))
    if len(points)<=1:
        return points
    def cross(o,a,b): return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    chains=[]
    for order in (points,points[::-1]):
        chain=[]
        for point in order:
            while len(chain)>=2 and cross(chain[-2],chain[-1],point)<=0:
                chain.pop()
            chain.append(point)
        chains.append(chain[:-1])
    return chains[0]+chains[1]


def point_in_hull(point,hull):
    eps=1e-9
    if not hull: return False
    if len(hull)==1: return all(abs(a-b)<=eps for a,b in zip(point,hull[0]))
    if len(hull)==2:
        a,b=hull
        cross=(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
        return abs(cross)<=eps and all(min(a[i],b[i])-eps<=point[i]<=max(a[i],b[i])+eps for i in (0,1))
    return all((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])>=-eps
               for a,b in zip(hull,hull[1:]+hull[:1]))


def human_press_assessment(brick, support, context):
    cells=footprint(brick)
    centre=((min(x for x,y in cells)+max(x for x,y in cells))/2,
            (min(y for x,y in cells)+max(y for x,y in cells))/2)
    hull=convex_hull(support["supported_cells"])
    active=context.get("human_press_policy","NONE")=="CONTACT_HULL"
    return {"required":active and not point_in_hull(centre,hull),
            "policy":context.get("human_press_policy","NONE"),
            "nominal_robot_point_xy_stud":list(centre),"contact_hull_xy_stud":[list(p) for p in hull],
            "basis":"GEOMETRIC_HEURISTIC_NOT_FORCE_OR_STABILITY_PROOF"}


def human_press_options(brick,current,context,support,tool_boxes):
    """One-pitch patch above an actual contact stud; optional local side entry."""
    g,b=context["geometry"],block_box(brick,context)
    p=g["pitch_mm"]
    result=[]
    for x,y in support["supported_cells"]:
        cx,cy=x*p,y*p
        patch=(cx-p/2,cy-p/2,b[5],cx+p/2,cy+p/2,b[5]+p)
        for side in context["human_sides"]:
            if side=="-x": entry=(b[0]-p,cy-p/2,b[5],cx-p/2,cy+p/2,b[5]+p)
            elif side=="+x": entry=(cx+p/2,cy-p/2,b[5],b[3]+p,cy+p/2,b[5]+p)
            elif side=="-y": entry=(cx-p/2,b[1]-p,b[5],cx+p/2,cy-p/2,b[5]+p)
            else: entry=(cx-p/2,cy+p/2,b[5],cx+p/2,b[4]+p,b[5]+p)
            boxes=[patch,entry]
            if free_boxes(boxes,current,context,tool_boxes):
                result.append({"side":side,"boxes":boxes,"contact_point_board_mm":[cx,cy,b[5]],
                               "contact_region_board_mm":[cx-p/2,cy-p/2,b[5],cx+p/2,cy+p/2,b[5]],
                               "frame_id":"assembly_board_mm","hand_count":1,
                               "requested_force_direction_board":[0,0,-1],"force_command":None,
                               "space_basis":"ONE_PITCH_PATCH_AND_LOCAL_ENTRY_NOT_FULL_HAND_REACH"})
    return result
