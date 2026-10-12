"""Test/analysis helper: does a Design follow the canonical facing (front = +X, backrest = low x)?

NOT a validator and NOT production code (app/ never imports this). The Design JSON and the validator are untouched;
this only reads block footprints to classify a finished Design for tests and smoke reports.

Verdicts:
    PASS            backrest mass sits at lower x than the seat (viewer at +X sees the open front)
    FAIL            backrest mass sits at higher x than the seat, or is offset along y (turned 90°)
    UNDEFINED       no backrest-like mass above the seat (stool, bench, ottoman) or mass centred (crown/arms only)
    FOLLOWS_CURRENT Revised case: the Current blocks already fix a non-canonical facing and the Design keeps it
                    (Current preservation outranks facing; see the Wave 2 design)

Seat heuristic (2026-10-12 facing runs, 5/5 agreement with visual check): per-layer stud sets; the seat layer is the
HIGHEST layer whose stud count is at least SEAT_RATIO of the largest layer, so a wide plinth below the seat does not
win and a thin crown above it does not either. Everything above the seat layer is "backrest mass".
"""

from app.c_design import validator

SEAT_RATIO = 0.6
CENTRE_TOLERANCE = 0.75  # studs; |dx| and |dy| both below this = no readable direction

PASS, FAIL, UNDEFINED, FOLLOWS_CURRENT = "PASS", "FAIL", "UNDEFINED", "FOLLOWS_CURRENT"


def _layers(blocks):
    per = {}
    for block in blocks:
        per.setdefault(block["layer"], set()).update(validator.footprint(block))
    return per


def _centre(studs):
    return sum(s[0] for s in studs) / len(studs), sum(s[1] for s in studs) / len(studs)


def _direction(blocks):
    """(axis_verdict, info). axis_verdict is PASS / FAIL / UNDEFINED for the blocks alone."""
    per = _layers(blocks)
    if not per:
        return UNDEFINED, {"why": "no blocks"}
    largest = max(len(studs) for studs in per.values())
    seat_layer = max(layer for layer, studs in per.items() if len(studs) >= SEAT_RATIO * largest)
    above = [stud for layer, studs in per.items() if layer > seat_layer for stud in studs]
    info = {"seat_layer": seat_layer, "seat_studs": len(per[seat_layer]), "above_studs": len(above)}
    if not above:
        return UNDEFINED, dict(info, why="no blocks above the seat layer")
    sx, sy = _centre(per[seat_layer])
    bx, by = _centre(above)
    dx, dy = bx - sx, by - sy
    info.update(dx=round(dx, 2), dy=round(dy, 2))
    if abs(dx) < CENTRE_TOLERANCE and abs(dy) < CENTRE_TOLERANCE:
        return UNDEFINED, dict(info, why="above-seat mass centred (crown or arms only)")
    if abs(dx) >= abs(dy):
        if dx < 0:
            return PASS, dict(info, why="backrest mass at low x (opposite the +X viewer)")
        return FAIL, dict(info, why="backrest mass at high x (toward the viewer)")
    return FAIL, dict(info, why="backrest mass offset along y (turned 90°)")


def classify_facing(design, current=None):
    """Return (verdict, info) for a Design dict ({design_version, blocks}) or a plain blocks list.

    current: optional list of Current blocks (Revised case). When the Current alone already reads as a direction and
    that direction is not canonical, a Design that keeps the same direction is FOLLOWS_CURRENT instead of FAIL.
    """
    blocks = design["blocks"] if isinstance(design, dict) else design
    verdict, info = _direction(blocks)
    if current:
        current_verdict, current_info = _direction(current)
        info["current"] = dict(current_info, verdict=current_verdict)
        if verdict == FAIL and current_verdict == FAIL and _same_sign(current_info, info):
            return FOLLOWS_CURRENT, dict(info, why="Current fixes a non-canonical facing and the Design keeps it")
    return verdict, info


def _same_sign(a, b):
    """Same dominant axis and the same direction along it (the minor axis may drift with crowns or arms)."""
    def dominant(info):
        dx, dy = info.get("dx", 0), info.get("dy", 0)
        axis, value = ("x", dx) if abs(dx) >= abs(dy) else ("y", dy)
        return axis, (value > 0) - (value < 0)
    return dominant(a) == dominant(b)
