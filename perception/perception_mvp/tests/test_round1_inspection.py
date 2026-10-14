"""Contract tests only: scripted Observed is not real camera validation."""
from copy import deepcopy
from threading import Event
import importlib.util
import os

import pytest

from perception_mvp.team_connection import connect_inspection
from perception_mvp.contracts import footprint, validate_block


def block(layer=1, color='yellow', brick_type='2x2x1'):
    return dict(brick_type=brick_type, color=color, x=3, y=5, layer=layer, orientation_deg=0)


def request(identity, kind='STEP', step='s0'):
    return dict(check_id=identity, check_kind=kind,
                plan_id=None if kind == 'INITIAL' else 'p', step_id=step if kind == 'STEP' else None)


def materials(blocks):
    return (dict(design_version=1, blocks=blocks), dict(plan_id='p', design_version=1,
        base_current_revision=0, steps=[dict(step_id=f's{i}', operation='PLACE', before=None,
        after=b, prerequisites=[], requires_delivery=True) for i,b in enumerate(blocks)]),
        dict(current_revision=0, blocks=[]))


def observation(context, blocks, *, layers=None, status='OK'):
    return dict(check_id=context['check_id'], observation_seq=context['observation_seq'],
        status=status, visible_blocks=deepcopy(blocks),
        verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in
                          (layers if layers is not None else range(1,6))],
        reason=None if status == 'OK' else 'depth_missing')


@pytest.fixture
def connection():
    responses, observations = [], []
    def observe(context, active):
        assert active()
        return observation(context, **observations.pop(0)), dict(issues=[])
    value = connect_inspection(responses.append, observe=observe,
        geometry_reference='test-profile', initial_current=dict(current_revision=0,blocks=[]))
    yield value, responses, observations
    value.close()


def execute(connection, message, blocks, **kwargs):
    value, responses, observations = connection
    observations.append(dict(blocks=blocks, **kwargs))
    value.request(message)
    value._queue.join()
    return responses[-1]


def test_step_final_five_layers_and_same_state_revision(connection):
    value, responses, _ = connection
    blocks = [block(layer=i) for i in range(1,6)]
    value.load_plan(*materials(blocks), geometry_reference='test-profile')
    for i in range(5):
        result = execute(connection, request(f'c{i}', step=f's{i}'), [blocks[i]], layers=[i+1])
        assert result['comparison'] == 'MATCH' and result['current']['current_revision'] == i+1
        assert result['current']['blocks'] == blocks[:i+1]
        assert result['observation']['visible_blocks'] == [blocks[i]]
    final = execute(connection, request('final', 'FINAL'), [blocks[-1]], layers=[5])
    assert final['check_kind'] == 'FINAL' and final['step_id'] is None
    assert final['comparison'] == 'MATCH' and final['current']['current_revision'] == 5
    assert final['expected']['blocks'] == blocks
    value.request(request('final', 'FINAL'))
    assert len(responses) == 6


@pytest.mark.parametrize('status,blocks,layers,comparison', [
    ('OK',[block(color='blue')],[1],'MISMATCH'),
    ('UNOBSERVABLE',[],[],'UNOBSERVABLE'),
    ('UNOBSERVABLE',[block(color='blue')],[1],'MISMATCH')])
def test_difference_and_unknown_are_not_completion(connection,status,blocks,layers,comparison):
    value, _, _ = connection
    value.load_plan(*materials([block()]), geometry_reference='test-profile')
    result = execute(connection, request('c'), blocks, layers=layers, status=status)
    assert result['comparison'] == comparison
    assert result['current']['blocks'] == blocks
    assert result['expected']['blocks'] == [block()]
    if comparison == 'UNOBSERVABLE':
        assert result['status'] == 'UNOBSERVABLE' and result['current']['current_revision'] == 0


def test_final_before_steps_and_missing_plan_do_not_capture(connection):
    value, responses, observations = connection
    value.request(request('missing'))
    assert responses[-1]['status'] == 'ERROR' and not observations
    value.load_plan(*materials([block()]), geometry_reference='test-profile')
    value.request(request('early','FINAL'))
    assert responses[-1]['status'] == 'ERROR' and responses[-1]['current'] is None


def test_cancel_before_commit_rejects_late_result_and_keeps_current():
    entered, release = Event(), Event()
    responses = []
    def observe(context, active):
        entered.set()
        assert release.wait(2)
        assert not active()
        return observation(context,[block()]), {}
    value = connect_inspection(responses.append, observe=observe, geometry_reference='test-profile',
        initial_current=dict(current_revision=0,blocks=[]))
    try:
        value.load_plan(*materials([block()]), geometry_reference='test-profile')
        value.request(request('c'))
        assert entered.wait(2)
        assert value.cancel('c')
        release.set(); value._queue.join()
        assert [r['status'] for r in responses] == ['CANCELED']
        assert value.inspection.current == dict(current_revision=0,blocks=[])
    finally:
        release.set(); value.close()


def test_cancel_after_commit_preserves_state_and_duplicate_conflict(connection):
    value, responses, _ = connection
    value.load_plan(*materials([block()]), geometry_reference='test-profile')
    execute(connection, request('c'), [block()])
    value.cancel('c')
    assert len(responses) == 1 and value.inspection.current['current_revision'] == 1
    with pytest.raises(ValueError,match='conflicting duplicate'):
        value.request(request('c','FINAL'))


def test_initial_unknown_never_becomes_fake_empty():
    responses = []
    value = connect_inspection(responses.append, geometry_reference='test-profile',
        observe=lambda ctx, active: (observation(ctx,[],layers=[],status='UNOBSERVABLE'),{}))
    try:
        value.request(request('initial','INITIAL')); value._queue.join()
        assert responses[-1]['status'] == 'ERROR' and responses[-1]['current'] is None
        assert 'INITIAL_STATE_UNAVAILABLE' in responses[-1]['reason']
        with pytest.raises(ValueError,match='INITIAL'):
            value.inspection.current
    finally:
        value.close()


def test_initial_actual_empty_enables_plan(connection):
    result = execute(connection,request('initial','INITIAL'),[])
    assert result['comparison'] is None and result['expected'] is None
    assert result['current'] == dict(current_revision=0,blocks=[])


def test_display_sink_emits_observing_then_confirmed_and_cancel():
    events, responses = [], []
    value = connect_inspection(responses.append, geometry_reference='test-profile',
        initial_current=dict(current_revision=0,blocks=[]), display_sink=events.append,
        observe=lambda ctx, active: (observation(ctx,[block()]),{}))
    try:
        value.load_plan(*materials([block()]),geometry_reference='test-profile')
        value.request(request('auto')); value._queue.join()
        stages = [e['display_stage'] for e in events if e is not None]
        assert stages == ['OBSERVING','CONFIRMED']
        assert events[-1]['current']['current_revision'] == 1
        value.cancel('auto')
        assert events[-1] is None
    finally:
        value.close()


def test_display_snapshot_preserves_previous_current_and_cancel_clears(connection):
    value, _, _ = connection
    value.load_plan(*materials([block()]), geometry_reference='test-profile')
    execute(connection, request('display'), [block()])
    snapshot = value.comparison_display_state()
    assert snapshot['previous_current'] == dict(current_revision=0, blocks=[])
    assert snapshot['current'] == dict(current_revision=1, blocks=[block()])
    snapshot['current']['blocks'].clear()
    assert value.comparison_display_state()['current']['blocks'] == [block()]
    value.cancel('display')
    assert value.comparison_display_state() is None


@pytest.mark.parametrize('regions', [
    [dict(x=0, y=0, width=1, height=1, layer=1)],
    [dict(x=0, y=0, width=24, height=24, layer=1)],
    []])
def test_initial_partial_empty_does_not_initialize_or_enable_plan(regions):
    responses = []
    def observe(context, active):
        result = observation(context, [])
        result['verified_regions'] = regions
        return result, {}
    value = connect_inspection(responses.append, observe=observe, geometry_reference='test-profile')
    try:
        value.request(request('partial', 'INITIAL')); value._queue.join()
        assert responses[-1]['status'] == 'ERROR'
        assert responses[-1]['current'] is None
        assert 'INITIAL_STATE_UNAVAILABLE' in responses[-1]['reason']
        with pytest.raises(ValueError, match='INITIAL'):
            value.load_plan(*materials([block()]), geometry_reference='test-profile')
    finally:
        value.close()


def test_initial_full_evidence_initializes_unknown_state():
    responses = []
    value = connect_inspection(responses.append, geometry_reference='test-profile',
        observe=lambda ctx, active: (observation(ctx, []), {}))
    try:
        value.request(request('full', 'INITIAL')); value._queue.join()
        assert responses[-1]['status'] == 'OK'
        assert responses[-1]['current'] == dict(current_revision=0, blocks=[])
        value.load_plan(*materials([block()]), geometry_reference='test-profile')
    finally:
        value.close()


def test_final_without_fresh_evidence_preserves_current(connection):
    value, _, _ = connection
    value.load_plan(*materials([block()]), geometry_reference='test-profile')
    execute(connection, request('step'), [block()])
    before = value.inspection.current
    result = execute(connection, request('empty-final', 'FINAL'), [], layers=[])
    assert result['status'] == 'UNOBSERVABLE'
    assert result['comparison'] == 'UNOBSERVABLE'
    assert result['current'] == before == value.inspection.current


def test_final_fresh_mismatch_remains_mismatch(connection):
    value, _, _ = connection
    value.load_plan(*materials([block()]), geometry_reference='test-profile')
    execute(connection, request('step'), [block()])
    result = execute(connection, request('wrong-final', 'FINAL'), [block(color='blue')])
    assert result['comparison'] == 'MISMATCH'
    assert result['current']['blocks'] == [block(color='blue')]


def test_evidenceless_final_does_not_reuse_historical_mismatch(connection):
    value, _, _ = connection
    value.load_plan(*materials([block()]), geometry_reference='test-profile')
    execute(connection, request('step'), [block()])
    execute(connection, request('changed-step'), [block(color='blue')])
    before = value.inspection.current
    result = execute(connection, request('unknown-final', 'FINAL'), [], layers=[])
    assert result['comparison'] == 'UNOBSERVABLE'
    assert result['current'] == before == value.inspection.current


def test_actual_producer_exception_is_error_without_state_change(connection):
    value,responses,_ = connection
    value.load_plan(*materials([block()]),geometry_reference='test-profile')
    value.observe = lambda *args: (_ for _ in ()).throw(RuntimeError('camera disconnected'))
    value.request(request('c')); value._queue.join()
    assert responses[-1]['status'] == 'ERROR' and 'camera disconnected' in responses[-1]['reason']
    assert value.inspection.current['current_revision'] == 0


def test_result_transport_failure_preserves_commit_and_unsent_response(connection):
    value,_,observations = connection
    value.load_plan(*materials([block()]),geometry_reference='test-profile')
    value.submit_result = lambda response: (_ for _ in ()).throw(RuntimeError('D disconnected'))
    observations.append(dict(blocks=[block()]))
    value.request(request('c')); value._queue.join()
    assert value.inspection.current['current_revision'] == 1
    assert value.last_delivery_error['response']['comparison'] == 'MATCH'
    assert value.last_delivery_error['error'] == 'D disconnected'


def test_red_step_result_uses_latest_inventory(connection):
    value,_,_ = connection
    red = block(color='red',brick_type='1x2x1')
    value.load_plan(*materials([red]),geometry_reference='test-profile')
    result = execute(connection,request('red'),[red])
    assert result['comparison'] == 'MATCH' and result['current']['blocks'] == [red]


def test_plan_over_forty_blocks_is_rejected(connection):
    value,_,_ = connection
    blocks = [dict(block(),x=2*(i%12),y=2*(i//12)) for i in range(41)]
    with pytest.raises(ValueError,match='40'):
        value.load_plan(*materials(blocks),geometry_reference='test-profile')


def test_plan_replacement_requires_cancel(connection):
    value,_,_ = connection
    value.load_plan(*materials([block()]),geometry_reference='test-profile')
    # Use the core's lock so this is not timing-dependent on worker completion.
    value.inspection.start('active','p','s0',geometry_reference='test-profile')
    with pytest.raises(ValueError,match='cancel'):
        value.load_plan(*materials([block()]),geometry_reference='test-profile')
    value.cancel('active')


def test_red_2point_only_and_rotation_footprint():
    red = block(color='red',brick_type='1x2x1',layer=5)
    validate_block(red)
    assert footprint(red) == {(3,5,5),(3,6,5)}
    assert footprint(dict(red,orientation_deg=90)) == {(3,5,5),(4,5,5)}
    with pytest.raises(ValueError):
        validate_block(dict(red,color='yellow'))


def test_actual_pr22_consumer_accepts_generated_b_results(connection):
    path = os.environ.get('B_ROUND1_CONSUMER_PATH')
    if not path:
        pytest.skip('PR22 Consumer source not provided; no claim of actual D contract verification')
    spec = importlib.util.spec_from_file_location('round1_consumer',path)
    consumer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consumer)
    value,responses,_ = connection
    blocks = [block(layer=i) for i in range(1,6)]
    execute(connection,request('initial','INITIAL'),[])
    value.load_plan(*materials(blocks),geometry_reference='test-profile')
    for i in range(5):
        execute(connection,request(f'c{i}',step=f's{i}'),[blocks[i]],layers=[i+1])
    execute(connection,request('final','FINAL'),[blocks[-1]],layers=[5])
    execute(connection,request('unknown',step='s4'),[],layers=[],status='UNOBSERVABLE')
    execute(connection,request('wrong',step='s4'),[block(layer=5,color='blue')],layers=[5])
    value.request(request('error',step='missing'))
    entered,release = Event(),Event()
    def wait_for_cancel(context,active):
        entered.set()
        assert release.wait(2)
        return observation(context,[]),{}
    value.observe = wait_for_cancel
    value.request(request('cancel',step='s4'))
    assert entered.wait(2)
    value.cancel('cancel'); release.set(); value._queue.join()
    for response in responses:
        consumer.validate_response(response)
    assert {r['comparison'] for r in responses} >= {'MATCH','MISMATCH','UNOBSERVABLE',None}
    hmi_path = os.environ.get('B_ROUND1_HMI_CONSUMER_PATH')
    if hmi_path:
        spec = importlib.util.spec_from_file_location('app.round1_hmi_consumer',hmi_path)
        hmi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hmi)
        for response in responses:
            snapshot = dict(inspection={k:response[k] for k in ('check_id','check_kind','plan_id',
                'step_id','status','comparison','expected','difference','reason')},
                monitor=dict(observation=dict(check_id=response['check_id'])),
                step=dict(plan_id=response['plan_id'],step_id=response['step_id'],comparison=response['comparison']))
            hmi._inspection(snapshot)
