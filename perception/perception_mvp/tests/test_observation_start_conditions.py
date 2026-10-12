"""Start conditions and offline delay fixtures; no physical safety claims."""
import pytest

from perception_mvp.hand_cycle import HandCycle


def test_initial_final_clear_wait_does_not_require_fictional_hand_entry():
    gate = HandCycle(1., 1.)
    gate.reset_for_reobservation(require_entry=False)
    for timestamp in (0., .5):
        assert not gate.update('ABSENT', True, timestamp)['observation_allowed']
    event = gate.update('ABSENT', True, 1.)
    assert event['observation_allowed']
    assert event['exit_seconds_required_strictly_greater_than'] is None
    assert not gate.entry_seen


@pytest.mark.parametrize('interrupt', ['PRESENT', 'UNKNOWN', 'GAP', 'UNSTABLE'])
def test_clear_mode_interruption_restarts_stability(interrupt):
    gate = HandCycle(1., 1.)
    gate.reset_for_reobservation(require_entry=False)
    gate.update('ABSENT', True, 0.)
    timestamp = 1.1 if interrupt == 'GAP' else .5
    presence = interrupt if interrupt in ('PRESENT', 'UNKNOWN') else 'ABSENT'
    assert not gate.update(presence, interrupt != 'UNSTABLE', timestamp)['observation_allowed']
    assert not gate.update('ABSENT', True, timestamp+.1)['observation_allowed']
    assert not gate.update('ABSENT', True, timestamp+.6)['observation_allowed']
    assert gate.update('ABSENT', True, timestamp+1.2)['observation_allowed']


def test_new_human_request_restores_entry_and_three_second_requirement():
    gate = HandCycle(.2, 1.)
    gate.reset_for_reobservation(require_entry=False)
    gate.update('ABSENT', True, 0.)
    assert gate.update('ABSENT', True, .3)['observation_allowed']
    gate.reset_for_reobservation()
    assert not gate.update('ABSENT', True, 1.)['observation_allowed']
    gate.update('PRESENT', True, 1.5)
    for timestamp in (2., 2.5, 3., 3.5, 4., 4.5, 5.):
        assert not gate.update('ABSENT', True, timestamp)['observation_allowed']
    assert gate.update('ABSENT', True, 5.1)['observation_allowed']


def test_stop_during_clear_wait_blocks_and_closes_stream():
    from perception_mvp.hand_cycle import wait_for_hand_ready
    gate = HandCycle(1., 1.)
    gate.reset_for_reobservation(require_entry=False)
    closed = []
    def stream():
        try:
            yield None, None, 0.
        finally:
            closed.append(True)
    frames = stream()
    class Detector:
        def detect(self, rgb, depth):
            return 'ABSENT', True, {}
    active = iter([True, False])
    with pytest.raises(RuntimeError, match='STOP'):
        wait_for_hand_ready(frames, Detector(), gate, lambda: next(active))
    assert gate.state == 'HOLD' and closed == [True]


def test_human_step_still_requires_entry():
    gate = HandCycle(.2, 1.)
    for timestamp in (0., .5, 1., 1.5, 2., 2.5, 3., 3.5):
        assert not gate.update('ABSENT', True, timestamp)['observation_allowed']
    gate.update('PRESENT', True, 4.)
    for timestamp in (4.5, 5., 5.5, 6., 6.5, 7., 7.5):
        assert not gate.update('ABSENT', True, timestamp)['observation_allowed']
    assert gate.update('ABSENT', True, 7.6)['observation_allowed']


def test_capture_finish_after_1_1_seconds_is_not_live_frame_gap(monkeypatch):
    gate = HandCycle(.2, 1.)
    gate.state, gate.last_time = 'READY', 10.
    monkeypatch.setattr('perception_mvp.hand_cycle.time.monotonic', lambda: 10.)
    gate.begin_observation()
    gate.freeze_capture()
    monkeypatch.setattr('perception_mvp.hand_cycle.time.monotonic', lambda: 11.1)
    gate.finish_observation()
    assert gate.state == 'WAIT_ENTRY'


def test_live_frame_gap_and_positive_reentry_still_interrupt(monkeypatch):
    gate = HandCycle(.2, 1.)
    gate.state, gate.last_time = 'OBSERVING', 10.
    monkeypatch.setattr('perception_mvp.hand_cycle.time.monotonic', lambda: 11.1)
    with pytest.raises(RuntimeError, match='interrupted'):
        gate.finish_observation()
    gate.freeze_capture()
    event = gate.update('PRESENT', True, 11.2)
    assert event['reason'] == 'hand_reentry_observation_invalidated'
    with pytest.raises(RuntimeError, match='interrupted'):
        gate.finish_observation()


@pytest.mark.parametrize('presence,stable', [('UNKNOWN', True), ('ABSENT', False)])
def test_clear_wait_never_accepts_unknown_or_unstable(presence, stable):
    gate = HandCycle(.2, 1.)
    gate.reset_for_reobservation(require_entry=False)
    for timestamp in (0., .5, 1., 1.5, 2., 2.5, 3., 3.5):
        assert not gate.update(presence, stable, timestamp)['observation_allowed']


@pytest.mark.parametrize('kind,explicit,expected', [
    ('INITIAL', None, 'STOPPED_CLEAR'), ('FINAL', None, 'STOPPED_CLEAR'),
    ('STEP', None, 'HUMAN_ASSEMBLY'), ('STEP', 'STOPPED_CLEAR', 'STOPPED_CLEAR'),
    ('FINAL', 'HUMAN_ASSEMBLY', 'HUMAN_ASSEMBLY')])
def test_request_start_policy_is_explicit_and_not_step_guessing(monkeypatch, kind, explicit, expected):
    import perception_mvp.main as runtime
    def cycle(gate, detector, stream, capture, manifest, *args, **kwargs):
        assert manifest['start_condition'] == expected
        return manifest, {}
    monkeypatch.setattr(runtime, 'run_observation_cycle', cycle)
    observer = runtime.make_inspection_observer(None, None, None, None, None, {}, {}, .25,
        confirm_view=lambda v: True, workflow_valid=lambda: True, bundle_valid=lambda: True,
        start_condition=None if explicit is None else lambda ctx: explicit)
    observer(dict(check_kind=kind, check_id='fixed', observation_seq=0, current=None), lambda: True)
