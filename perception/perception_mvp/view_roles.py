"""View roles: V0 owns layers, D1/D3 are auxiliary (kind, colour, position, orientation).

D1/D3 cannot yet select a trusted top plane, so their layer is not evidence. The V0 view
is the only source of visible blocks (and their layer) and of occupied-footprint regions.
An auxiliary View never contributes a block of its own and never borrows V0's layer; its
measured blocks are only cross-checked against V0 blocks of the SAME layer. Its clear-column
(empty) Depth evidence is layer independent and is kept. An UNKNOWN candidate only drops
itself; its cells are never added as verified.
"""
from .contracts import footprint, placement_key

AUTHORITY_VIEW = 'V0'


def build_role_view(identity, result, supplied_regions, to_block):
    """Return (view, notes, gating_issues) for one processed View.

    identity: check_id, observation_seq, calibration_id. result: process_saved output.
    supplied_regions: caller supplied independently verified regions (dropped when any
    candidate of this View is UNKNOWN, because they cannot be cross-checked against it).
    notes carry what is not gating; gating_issues must reach Inspection as issues.
    """
    view_id = result['view_id']
    unknown = [c for c in result['candidates'] if c['status'] == 'UNKNOWN']
    blocks = [to_block(c) for c in result['candidates'] if c['status'] == 'CANDIDATE']
    supplied = [] if unknown else list(supplied_regions)
    occupied = list(result.get('occupied_regions', []))
    empty = list(result.get('empty_regions', []))
    notes = dict(view_id=view_id, role='AUTHORITY' if view_id == AUTHORITY_VIEW else 'AUXILIARY',
                 unknown_reasons=[c.get('reason') for c in unknown], measured_blocks=len(blocks))
    gating = []
    if view_id == AUTHORITY_VIEW:
        regions, visible = supplied + occupied + empty, blocks
        notes['visible_blocks'] = blocks
        if unknown:
            gating.append(f'{view_id}:partial_unknown_candidates')
    else:
        # Occupied footprints carry the Depth-measured layer, which is not trusted here.
        regions, visible = supplied + empty, []
        notes['auxiliary_blocks'] = blocks
        notes['dropped_occupied_regions'] = len(occupied)
    view = dict(identity, view_id=view_id, visible_blocks=visible, verified_regions=regions,
                status='OK', reason=None)
    return view, notes, gating


def finalize(diagnostics, notes_by_view, gating):
    """Attach role notes and the gating issues to diagnostics['issues'] (read by Inspection)."""
    check_gating, report = cross_check(notes_by_view)
    for issue in [*gating, *check_gating]:
        if issue not in diagnostics['issues']:
            diagnostics['issues'].append(issue)
    diagnostics['view_roles'] = [{k: v for k, v in notes.items() if k != 'visible_blocks'}
                                 for notes in notes_by_view.values()]
    diagnostics['cross_check'] = report
    return diagnostics


def cross_check(notes_by_view):
    """Compare auxiliary blocks with V0 blocks of the same layer; return (gating, report)."""
    authority = notes_by_view.get(AUTHORITY_VIEW)
    if authority is None:
        return [], []
    reference = authority.get('visible_blocks', [])
    gating, report = [], []
    for view_id, notes in notes_by_view.items():
        if view_id == AUTHORITY_VIEW:
            continue
        for block in notes.get('auxiliary_blocks', []):
            same_layer = [b for b in reference if footprint(b) & footprint(block)]
            if not same_layer:
                report.append(dict(view_id=view_id, block=block, result='NO_SAME_LAYER_V0_BLOCK'))
            elif any(placement_key(b) == placement_key(block) for b in same_layer):
                report.append(dict(view_id=view_id, block=block, result='AGREES_WITH_V0'))
            else:
                report.append(dict(view_id=view_id, block=block, result='DISAGREES_WITH_V0',
                                   v0_blocks=same_layer))
                gating.append(f'{view_id}:disagrees_with_V0_same_layer')
    return gating, report
