"""B-owned inspection core with 10/8 INITIAL/STEP/FINAL and legacy diagnostic API.

Uses existing PLACE Plan inputs. No step advancement, robot control or Expected
correction from actual deviations. A new approved Plan explicitly replaces models.
"""
from copy import deepcopy
from threading import RLock

from .contracts import footprint, placement_key, region_cells, validate_block


def _blocks(blocks):
    occupied = set()
    for block in blocks:
        validate_block(block)
        cells = footprint(block)
        if cells & occupied:
            raise ValueError("duplicate or overlapping same-layer placement")
        occupied.update(cells)
    return deepcopy(blocks)


def _current(value):
    if set(value) != {"current_revision", "blocks"}:
        raise ValueError("current requires revision and blocks")
    if type(value["current_revision"]) is not int or value["current_revision"] < 0:
        raise ValueError("nonnegative integer revision required")
    return dict(current_revision=value["current_revision"], blocks=_blocks(value["blocks"]))


def _keys(blocks):
    return {placement_key(b) for b in blocks}


def build_step_models(design, plan, base_current):
    """Compile existing PLACE-only Plan in array order, never layer order."""
    # Reuse team contract validation without importing Backend state ownership.
    from app.contracts import validate_design, validate_plan
    design, plan, base = validate_design(design), validate_plan(plan), _current(base_current)
    final = _blocks(design["blocks"])
    if len(final) > 40:
        raise ValueError('approved Design exceeds round1 maximum 40 placements')
    if design["design_version"] != plan["design_version"]:
        raise ValueError("Design/Plan version mismatch")
    if base["current_revision"] != plan["base_current_revision"]:
        raise ValueError("Plan/baseline revision mismatch")
    blocks, models = base["blocks"], {}
    for step in plan["steps"]:
        blocks = _blocks(blocks + [step["after"]])
        models[step["step_id"]] = deepcopy(blocks)
    if _keys(blocks) != _keys(final):
        raise ValueError("Plan effects do not produce approved final Design")
    return deepcopy(design), deepcopy(plan), models


def _unverified_regions(verified):
    """Row-run diagnostic coverage; camera ROI is never evidence."""
    regions = []
    for layer in range(1, 6):
        for y in range(24):
            start = None
            for x in range(25):
                missing = x < 24 and (x, y, layer) not in verified
                if missing and start is None:
                    start = x
                elif not missing and start is not None:
                    regions.append(dict(x=start, y=y, width=x-start, height=1, layer=layer))
                    start = None
    return regions


class VisionInspection:
    """One job's Current/models and one D-selected active check.

    Caller serializes plan/start/cancel/finish calls. Current is in board coordinates;
    translated Design/Plan must already use the SAME fixed first-placement frame.
    """
    def __init__(self, current):
        self._initialized = current is not None
        self._current = _current(current) if self._initialized else dict(current_revision=0, blocks=[])
        self._lock = RLock()
        self._confirmed_steps = set()
        self._plan = None
        self._active = None
        self._used_checks = set()

    @property
    def current(self):
        if not self._initialized:
            raise ValueError("INITIAL observation required; Current is not known")
        return deepcopy(self._current)

    @property
    def final_model(self):
        if self._plan is None:
            raise ValueError("approved final model unavailable")
        return deepcopy(self._design["blocks"])

    def load_plan(self, design, plan, base_current, *, geometry_reference):
        with self._lock:
            if self._active is not None:
                raise ValueError("cancel active check before sharing a new Plan")
            return self._load_plan(design, plan, base_current, geometry_reference=geometry_reference)

    def _load_plan(self, design, plan, base_current, *, geometry_reference):
        if not self._initialized:
            raise ValueError("INITIAL observation required before Plan")
        if not isinstance(geometry_reference, str) or not geometry_reference:
            raise ValueError("explicit coordinate/geometry profile reference required")
        base = _current(base_current)
        if base["current_revision"] != self._current["current_revision"] or _keys(base["blocks"]) != _keys(self._current["blocks"]):
            raise ValueError("new Plan baseline differs from B Current")
        design, plan, models = build_step_models(design, plan, base)
        if self._plan is not None and plan["plan_id"] == self._plan["plan_id"]:
            raise ValueError("new Plan must have a new identifier")
        self._design, self._plan, self._models = design, plan, models
        self._geometry_reference = geometry_reference
        self._confirmed_steps = set()

    def start(self, check_id, plan_id, step_id, *, geometry_reference):
        with self._lock:
            return self._start(check_id, plan_id, step_id, geometry_reference=geometry_reference)

    def _start(self, check_id, plan_id, step_id, *, geometry_reference):
        if self._active is not None:
            raise ValueError("cancel the active check before starting another")
        if not isinstance(check_id, str) or not check_id or check_id in self._used_checks:
            raise ValueError("new nonempty check identifier required")
        if self._plan is None or self._plan["plan_id"] != plan_id or step_id not in self._models:
            raise ValueError("requested Plan/Step model unavailable")
        if geometry_reference != self._geometry_reference:
            raise ValueError("coordinate/geometry profile mismatch")
        self._active = dict(check_id=check_id, plan_id=plan_id, step_id=step_id)
        self._used_checks.add(check_id)
        target = next(s["after"] for s in self._plan["steps"] if s["step_id"] == step_id)
        return dict(**deepcopy(self._active), expected=deepcopy(self._models[step_id]),
                    current=self.current, target_after=deepcopy(target))

    def cancel(self, check_id):
        with self._lock:
            if self._active is not None and self._active["check_id"] == check_id:
                self._active = None

    def is_active(self, check_id, plan_id, step_id):
        with self._lock:
            return self._active == dict(check_id=check_id, plan_id=plan_id, step_id=step_id)

    def finish(self, observed, *, plan_id, step_id, geometry_reference, issues=()):
        with self._lock:
            return self._finish(observed, plan_id=plan_id, step_id=step_id,
                                geometry_reference=geometry_reference, issues=issues)

    def _finish(self, observed, *, plan_id, step_id, geometry_reference, issues=(), final=False):
        from app.contracts import validate_observed
        observed = validate_observed(observed)
        context = dict(check_id=observed["check_id"], plan_id=plan_id, step_id=step_id)
        if context != self._active or geometry_reference != self._geometry_reference:
            raise ValueError("cancelled, stale or mismatched inspection")
        visible = _blocks(observed["visible_blocks"])
        verified = region_cells(observed["verified_regions"])
        if any(not footprint(b) & verified for b in visible):
            raise ValueError("visible placement requires actual same-layer evidence")
        if final and not verified:
            # Historical Current cannot replace evidence from this FINAL check.
            # No regions also implies no admissible visible placement above.
            issues = [*issues, 'FINAL_OBSERVATION_EVIDENCE_MISSING']
        old = self._current["blocks"]
        seen = _keys(visible)
        # Positive conflicting placement disproves the old exact placement; no
        # physical identity is claimed. Missing coverage alone cannot delete it.
        retained = [b for b in old if placement_key(b) in seen or not (
            footprint(b) <= verified or any(footprint(b) & footprint(n) & verified for n in visible))]
        merged = _blocks(retained + [b for b in visible if placement_key(b) not in _keys(retained)])
        changed = _keys(merged) != _keys(old)
        next_current = dict(current_revision=self._current["current_revision"] + int(changed), blocks=merged)
        expected = self.final_model if final else self._models[step_id]
        missing, unknown = [], []
        for block in expected:
            if placement_key(block) not in _keys(merged):
                confirmed = footprint(block) <= verified or any(footprint(block) & footprint(n) & verified for n in visible)
                (missing if confirmed else unknown).append(deepcopy(block))
        unexpected = [deepcopy(b) for b in merged if placement_key(b) not in _keys(expected)]
        if not final:
            target = next(s["after"] for s in self._plan["steps"] if s["step_id"] == step_id)
            target_known = placement_key(target) in seen or footprint(target) <= verified or any(
                footprint(target) & footprint(n) & verified for n in visible)
            if not target_known and placement_key(target) not in _keys(unknown):
                unknown.append(deepcopy(target))
        comparison = "MISMATCH" if missing or unexpected else (
            "UNOBSERVABLE" if unknown or issues or observed["status"] == "UNOBSERVABLE" else "MATCH")
        if final and not verified:
            comparison = 'UNOBSERVABLE'
        historical = [deepcopy(b) for b in merged if placement_key(b) not in seen]
        result = dict(**context, comparison=comparison, current=deepcopy(next_current),
            expected=deepcopy(expected), difference=dict(missing=missing, unexpected=unexpected,
                unobservable=unknown), observed_blocks=deepcopy(visible), retained_history=historical,
            verified_regions=deepcopy(observed["verified_regions"]),
            unverified_regions=_unverified_regions(verified), reason=observed["reason"],
            observation_seq=observed["observation_seq"], geometry_reference=geometry_reference,
            issues=deepcopy(list(issues)),
            actual_changes=dict(
                added=[deepcopy(b) for b in merged if placement_key(b) not in _keys(old)],
                removed=[deepcopy(b) for b in old if placement_key(b) not in _keys(merged)],
                identity="NOT_INFERRED"),
            format_status="internal_inspection_not_wire_schema")
        self._current, self._active = next_current, None
        if comparison == "MATCH" and not final:
            self._confirmed_steps.add(step_id)
        return result

    def start_check(self, request, *, geometry_reference):
        """10/8 contract: D selects INITIAL/STEP/FINAL, never B step advancement."""
        with self._lock:
            kind = request['check_kind']
            if kind == 'STEP':
                if self._plan is None or request['plan_id'] != self._plan['plan_id']:
                    raise LookupError('PLAN_NOT_FOUND')
                return self._start(request['check_id'], request['plan_id'], request['step_id'],
                                   geometry_reference=geometry_reference)
            if self._active is not None or request['check_id'] in self._used_checks:
                raise ValueError('active or reused check; cancel before replacement')
            if kind == 'INITIAL':
                if request['plan_id'] is not None or request['step_id'] is not None:
                    raise ValueError('INITIAL requires null Plan/Step')
                expected = None
            elif kind == 'FINAL':
                if self._plan is None or request['plan_id'] != self._plan['plan_id']:
                    raise LookupError('PLAN_NOT_FOUND')
                if request['step_id'] is not None or self._confirmed_steps != set(self._models):
                    raise ValueError('FINAL requires all Step MATCH results and null Step')
                if geometry_reference != self._geometry_reference:
                    raise ValueError('geometry profile mismatch')
                expected = self.final_model
            else:
                raise ValueError('unsupported check kind')
            self._active = {k: request[k] for k in ('check_id', 'plan_id', 'step_id')}
            self._used_checks.add(request['check_id'])
            return dict(**deepcopy(self._active), expected=expected,
                        current=self.current if self._initialized else None)

    def finish_check(self, request, observed, *, geometry_reference, issues=()):
        """Serialize cancel and commit. Capture occurs outside this critical section."""
        with self._lock:
            kind = request['check_kind']
            if kind == 'STEP':
                return self._finish(observed, plan_id=request['plan_id'], step_id=request['step_id'],
                                    geometry_reference=geometry_reference, issues=issues)
            from app.contracts import validate_observed
            observed = validate_observed(observed)
            context = {k: request[k] for k in ('check_id', 'plan_id', 'step_id')}
            if self._active != context or observed['check_id'] != context['check_id']:
                raise ValueError('cancelled, stale or mismatched inspection')
            if kind == 'INITIAL':
                if observed['status'] != 'OK' or issues:
                    self._active = None
                    return dict(comparison=None, current=self.current if self._initialized else None,
                                expected=None, difference=dict(missing=[], unexpected=[], unobservable=[]))
                visible = _blocks(observed['visible_blocks'])
                verified = region_cells(observed['verified_regions'])
                if not self._initialized and _unverified_regions(verified):
                    self._active = None
                    raise ValueError('INITIAL_STATE_UNAVAILABLE: initial board coverage incomplete')
                if not verified or any(not footprint(b) <= verified for b in visible):
                    raise ValueError('INITIAL requires actual coverage for initial state')
                old = self._current['blocks']
                retained = [b for b in old if not footprint(b) <= verified and not any(
                    footprint(b) & footprint(n) & verified for n in visible)]
                blocks = _blocks(retained + [b for b in visible if placement_key(b) not in _keys(retained)])
                self._current = dict(current_revision=self._current['current_revision'] +
                                     int(_keys(blocks) != _keys(old)), blocks=blocks)
                self._initialized, self._active = True, None
                return dict(comparison=None, current=self.current, expected=None,
                            difference=dict(missing=[], unexpected=[], unobservable=[]))
            if kind != 'FINAL' or geometry_reference != self._geometry_reference:
                raise ValueError('invalid FINAL context')
            return self._finish(observed, plan_id=context['plan_id'], step_id=None,
                                geometry_reference=geometry_reference, issues=issues, final=True)
