"""B producer contract fixtures, not physical Camera/Controller validation."""
from copy import deepcopy

import pytest

from perception_mvp.backend_adapter import build_observed
from perception_mvp.main import make_inspection_observer, validate_cycle_target


def view(regions):
    return dict(check_id='check', observation_seq=0, calibration_id='cal',
                view_id='V0', visible_blocks=[], verified_regions=regions,
                status='OK', reason=None)


@pytest.mark.parametrize('kind,regions,status', [
    ('INITIAL', [], 'UNOBSERVABLE'),
    ('INITIAL', [dict(x=0, y=0, width=1, height=1, layer=1)], 'UNOBSERVABLE'),
    ('INITIAL', [dict(x=0, y=0, width=24, height=24, layer=i)
                 for i in range(1, 6)], 'OK'),
    ('FINAL', [], 'UNOBSERVABLE'),
    ('FINAL', [dict(x=0, y=0, width=1, height=1, layer=5)], 'OK')])
def test_producer_requires_real_scope_without_invented_step(kind, regions, status):
    observed, _ = build_observed('check', 0, [view(regions)], [], None,
                                 scene_stable=True, check_kind=kind)
    assert observed['status'] == status
    assert observed['visible_blocks'] == []
    assert set(observed) == {'check_id', 'observation_seq', 'status',
                            'visible_blocks', 'verified_regions', 'reason'}
    # FINAL OK here means available evidence, not MATCH or completed assembly.


@pytest.mark.parametrize('kind', ['INITIAL', 'FINAL'])
def test_fake_target_is_rejected(kind):
    with pytest.raises(ValueError, match='target'):
        validate_cycle_target(dict(check_kind=kind, target_after={}))


@pytest.mark.parametrize('kind', ['INITIAL', 'STEP', 'FINAL'])
def test_observer_freezes_capture_context_and_respects_cancellation(monkeypatch, kind):
    import perception_mvp.main as runtime
    target = dict(brick_type='2x2x1', color='blue', x=3, y=5, layer=1, orientation_deg=0)
    context = dict(check_id='original', observation_seq=0, check_kind=kind,
                   current=None if kind == 'INITIAL' else dict(current_revision=2, blocks=[target]))
    if kind == 'STEP':
        context['target_after'] = target
    saved = deepcopy(context)
    active = [True]
    captures = []
    def capture(manifest, view_id, is_active):
        assert manifest['check_id'] == 'original' and is_active()
        captures.append(view_id)
        manifest['check_id'] = 'capture-mutated'
        return {}
    def cycle(gate, detector, stream, capture_view, manifest, *args, **kwargs):
        validate_cycle_target(manifest)
        context['check_id'] = 'outside-mutated'
        assert kwargs['workflow_valid']()
        for view_id in manifest['view_order']:
            capture_view(view_id)
        assert manifest['check_id'] == 'original'
        active[0] = False
        assert not kwargs['workflow_valid']()
        assert manifest['previous_accepted_blocks'] == ([] if kind == 'INITIAL' else [target])
        return dict(check_id='original'), {}
    monkeypatch.setattr(runtime, 'run_observation_cycle', cycle)
    observer = make_inspection_observer(None, None, lambda: iter(()), capture, None, {}, {}, .25,
        confirm_view=lambda v: True, workflow_valid=lambda: True, bundle_valid=lambda: True)
    result, _ = observer(context, lambda: active[0])
    assert result['check_id'] == saved['check_id']
    assert captures == ['V0', 'D1', 'D3']


def test_observer_ros_hand_stream_uses_request_active_and_stop_hooks(monkeypatch):
    import perception_mvp.main as runtime
    import perception_mvp.ros_capture as ros
    active = [True]
    stopped = lambda view: view == 'V0'
    def stream(valid, stop, *, context, workflow_valid):
        assert context['check_kind'] == 'INITIAL' and workflow_valid() is True
        assert valid() and stop is stopped
        active[0] = False
        assert not valid()
        return iter(())
    def cycle(gate, detector, stream_factory, *args, **kwargs):
        list(stream_factory())
        return {}, {}
    monkeypatch.setattr(ros, 'stream_ros_hand', stream)
    monkeypatch.setattr(runtime, 'run_observation_cycle', cycle)
    observer = make_inspection_observer(None, None, None, None, None, {}, {}, .25,
        confirm_view=lambda view: True, workflow_valid=lambda: True, bundle_valid=lambda: True,
        is_stopped=stopped)
    observer(dict(check_kind='INITIAL', current=None), lambda: active[0])


def test_ros_hand_stream_without_stop_hook_is_rejected():
    observer = make_inspection_observer(None, None, None, None, None, {}, {}, .25,
        confirm_view=lambda view: True, workflow_valid=lambda: True, bundle_valid=lambda: True)
    with pytest.raises(ValueError, match='is_stopped'):
        observer(dict(check_kind='INITIAL', current=None), lambda: True)
