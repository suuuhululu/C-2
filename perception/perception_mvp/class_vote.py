"""Auxiliary class consensus on measured associations, never on Expected."""
from collections import Counter
from copy import deepcopy
import math

from .contracts import footprint, placement_key, region_cells


def prepare_class_votes(views, policy):
    """Internal measured_candidates are separate from the six-field Observed.

    Caller must supply adopted metric association tolerances. Ambiguous links
    and hard geometry contradictions retain the conservative legacy conflict.
    """
    for key in ('center_tolerance_m', 'height_tolerance_m'):
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('positive measured vote association tolerance required: '+key)
    if {v['view_id'] for v in views} != {'V0', 'D1', 'D3'}:
        return deepcopy(views), []  # Partial View results remain provisional.
    items, logs = [], []
    for vi, view in enumerate(views):
        seen = set()
        for candidate in view.get('measured_candidates', []):
            if candidate.get('status') != 'CANDIDATE':
                logs.append(dict(view=view['view_id'], decision='ABSTAIN',
                                 reason=candidate.get('reason', 'unverified_candidate')))
                continue
            center, height = candidate['surface_center_m'], candidate['top_height_m']
            if len(center) != 2 or not all(math.isfinite(x) for x in [*center, height]):
                raise ValueError('finite measured vote position required')
            block = candidate['block']
            if block not in view['visible_blocks']:
                raise ValueError('vote placement absent from View evidence')
            key = placement_key(block)
            if key in seen:
                raise ValueError('duplicate vote candidate within View')
            seen.add(key)
            items.append((vi, candidate))
    def linked(a, b):
        return (math.dist(a['surface_center_m'], b['surface_center_m']) <= policy['center_tolerance_m']
                and abs(a['top_height_m']-b['top_height_m']) <= policy['height_tolerance_m'])
    remaining = set(range(len(items)))
    output = deepcopy(views)
    while remaining:
        seed = min(remaining)
        group, pending = {seed}, [seed]
        while pending:
            current = pending.pop()
            neighbors = {j for j in remaining-group if linked(items[current][1], items[j][1])}
            group.update(neighbors)
            pending.extend(neighbors)
        remaining -= group
        members = [items[j] for j in sorted(group)]
        ambiguous = (len({vi for vi, _ in members}) != len(members) or
                     any(not linked(a, b) for _, a in members for _, b in members))
        counts = Counter(c['part_class'] for _, c in members)
        winners = [name for name, count in counts.items() if count == max(counts.values())]
        decision = 'AMBIGUOUS_ASSOCIATION' if ambiguous else 'TIE' if len(winners) != 1 else 'SELECTED'
        if any(c.get('geometry_conflict') for _, c in members):
            decision = 'GEOMETRY_CONFLICT'
        winning = [c for _, c in members if c['part_class'] == winners[0]]
        if decision == 'SELECTED' and len({placement_key(c['block']) for c in winning}) != 1:
            decision = 'GEOMETRY_CONFLICT'
        log = dict(votes=dict(counts), views=[views[vi]['view_id'] for vi, _ in members], decision=decision)
        logs.append(log)
        if decision != 'SELECTED':
            cells = set().union(*(footprint(c['block']) for _, c in members))
            for vi, c in members:
                output[vi]['visible_blocks'].remove(c['block'])
            for view in output:
                view['verified_regions'] = [r for r in view['verified_regions']
                                            if not region_cells([r]) & cells]
            continue
        log['selected_class'] = winners[0]
        log['basis'] = 'single_valid_observation' if len(members) == 1 else 'auxiliary_class_consensus'
        for vi, c in members:
            if c['part_class'] == winners[0]:
                continue
            # Losing class is not converted into a fabricated winning detection.
            output[vi]['visible_blocks'].remove(c['block'])
            cells = footprint(c['block'])
            output[vi]['verified_regions'] = [r for r in output[vi]['verified_regions']
                                               if not region_cells([r]) & cells]
    return output, logs
