"""누적 Current 표시 계약과 장치 없는 Qt 조립 안내 회귀 검사."""

from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urljoin

from jsonschema import Draft202012Validator, RefResolver
import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.hmi_contracts import validate_hmi_snapshot
from app.qt_hmi import HmiWindow
from app.snapshot import make_snapshot
from test_backend import A, B, C, RA, RB, RC, FakePorts, delivering, observation, robot_success


ROOT = Path(__file__).resolve().parents[2]
HMI = json.loads((ROOT / 'interfaces/fixtures/hmi.json').read_text())


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    window = HmiWindow(screen_size=QSize(1920, 1080))
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def scene(name):
    snapshot = deepcopy(HMI['snapshots']['waiting'])
    if name in HMI['snapshots']:
        return deepcopy(HMI['snapshots'][name])
    if name == 'first':
        snapshot['current'] = dict(current_revision=0, blocks=[])
        snapshot['step'].update(step_id='S01', target=deepcopy(A))
        snapshot['progress']['completed'] = 0
    elif name == 'multiple_layers':
        snapshot['current'] = dict(current_revision=4, blocks=[A, B, C, {**A, 'x':19, 'y':19}])
        snapshot['step']['target'] = {**A, 'color':'blue', 'layer':3}
    elif name == 'replanned':
        snapshot['current'] = dict(current_revision=5, blocks=[{**A, 'x':9}])
        snapshot['design'] = dict(design_version=2, blocks=[{**A, 'x':9}, {**C, 'x':9}])
        snapshot['step'].update(plan_id='new-plan', step_id='new-step', target={**C, 'x':9})
        snapshot['progress'] = dict(completed=0, total=1)
    else:
        raise ValueError(name)
    target = snapshot['step']['target']
    snapshot['notice']['required_action'] = (f"합성 시험 목표: ({target['x']}, {target['y']}) · "
                                           f"{target['layer']}층 · 종류/색상/방향은 표에서 확인하세요.")
    return snapshot


@pytest.mark.parametrize('name,count', [('first',1), ('waiting',3), ('multiple_layers',5),
                                       ('match',3), ('mismatch',4), ('unobservable',3),
                                       ('partial',3), ('stopped',3), ('complete',3)])
def test_assembly_uses_adopted_current_and_target_without_mutation(window, qapp, name, count):
    snapshot = scene(name)
    before = deepcopy(snapshot)
    window.render_snapshot(snapshot)
    qapp.processEvents()
    assert not window.grab().isNull()
    assert window.target_board.current == snapshot['current']
    assert window.target_board.target == snapshot['step']['target']
    assert len(window.target_board.blocks) == count
    assert window.target_board.isometric
    assert snapshot == before
    window.target_board.current['blocks'].clear()
    assert snapshot == before and window._snapshot == before
    if name == 'complete':
        assert window.target_board.target is None
        assert '다음 목표 없음' in window.target_caption.text()
    elif name == 'match':
        assert 'Current에 반영됨' in window.target_caption.text()


@pytest.mark.parametrize('field,value', [('brick_type','2x2x1'), ('color','yellow'), ('x',9),
                                        ('y',9), ('layer',3), ('orientation_deg',0)])
def test_target_deduplication_requires_all_six_placement_fields(window, field, value):
    snapshot = scene('match')
    if field == 'brick_type':
        # 4점 대표각은 0°만 허용한다. 두 0° 배치의 종류 필드만 비교한다.
        snapshot['current']['blocks'][2]['orientation_deg'] = 0
        snapshot['step']['target']['orientation_deg'] = 0
    original_current = deepcopy(snapshot['current'])
    snapshot['step']['target'][field] = value
    window.render_snapshot(snapshot)
    assert len(window.target_board.blocks) == 4
    assert window.target_board.current == original_current
    assert window.target_board.target[field] == value


@pytest.mark.parametrize('field,value', [('current_revision',True), ('current_revision',-1),
                                        ('blocks',[A,A]), ('blocks',[{**A,'block_id':'invented'}]),
                                        ('blocks',[{**A,'layer':6}])])
def test_snapshot_reuses_current_rejection_rules(field, value):
    snapshot = scene('waiting')
    snapshot['current'][field] = value
    before = deepcopy(snapshot)
    with pytest.raises(ValueError):
        validate_hmi_snapshot(snapshot)
    assert snapshot == before


def test_current_schema_and_all_hmi_fixtures_agree():
    common = json.loads((ROOT/'interfaces/schemas/day4.schema.json').read_text())
    schema = json.loads((ROOT/'interfaces/schemas/hmi.schema.json').read_text())
    store = {common['$id']:common, urljoin(schema['$id'],'day4.schema.json'):common}
    Draft202012Validator.check_schema(common)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store=store))
    for snapshot in HMI['snapshots'].values():
        validator.validate(snapshot)
        assert validate_hmi_snapshot(snapshot) == snapshot
    for snapshot in HMI['invalid_snapshots'].values():
        assert list(validator.iter_errors(snapshot))
    for current in (None, {'blocks':[]}, dict(current_revision=True,blocks=[]),
                    dict(current_revision=0,blocks=[A,A])):
        snapshot = scene('waiting')
        snapshot['current'] = current
        assert list(validator.iter_errors(snapshot))
    missing = scene('waiting')
    del missing['current']
    assert list(validator.iter_errors(missing))
    with pytest.raises(ValueError, match='current'):
        validate_hmi_snapshot(missing)


def test_latest_snapshot_updates_replanned_current_and_target_together(window, qapp):
    window.snapshot_received.emit(scene('waiting'))
    latest = scene('replanned')
    window.snapshot_received.emit(latest)
    qapp.processEvents()
    assert window.target_board.current == dict(current_revision=5, blocks=[{**A,'x':9}])
    assert window.target_board.target == {**C,'x':9}
    assert window.design_board.blocks == latest['design']['blocks']
    assert window._snapshot['step']['plan_id'] == 'new-plan'
    assert window.table.item(2,1).text() == '(9, 5)'


def test_backend_cumulative_current_survives_lower_occlusion_and_target_unobservable(window, qapp):
    backend, ports = delivering()
    for blocks, regions in [([A],[RA]), ([A,B],[RA,RB])]:
        robot_success(backend)
        payload = observation(backend, blocks, regions)
        backend.on_place(payload['check_id'],0,'EMPTY')
        assert backend.on_observation(payload)
    robot_success(backend)
    before = deepcopy(backend.state['current'])
    invisible = observation(backend, [], [], seq=0)
    invisible.update(status='UNOBSERVABLE', reason='synthetic hand occlusion')
    assert backend.on_observation(invisible)
    snapshot = make_snapshot(backend.state)
    assert snapshot['current'] == before == dict(current_revision=2, blocks=[A,B])
    assert snapshot['step']['comparison'] == 'UNOBSERVABLE'
    window.render_snapshot(snapshot)
    assert window.target_board.blocks == [A,B,C]
    # 이번 목표만 보이는 실제 합성 관측: 확인한 아래층은 snapshot에서도 유지한다.
    assert backend.on_observation(observation(backend,[C],[RC],seq=1))
    snapshot = make_snapshot(backend.state)
    window.render_snapshot(snapshot)
    qapp.processEvents()
    assert snapshot['current'] == dict(current_revision=3,blocks=[A,B,C])
    assert window.target_board.blocks == [A,B,C] and window.target_board.target is None
    assert len(ports.calls('robot.deliver')) == 3
    snapshot['current']['blocks'].clear()
    assert backend.state['current']['blocks'] == [A,B,C]


def test_matched_target_is_drawn_once_per_view_and_layers_remain_in_frame(window, qapp, monkeypatch):
    drawn=[]
    board = window.target_board
    original = board._brick

    def draw(painter, block, project, scale):
        from app.hmi_board import dimensions, STUD_HEIGHT
        w,d = dimensions(block)
        points=[project(x,y,z) for x in (block['x'],block['x']+w)
                for y in (block['y'],block['y']+d)
                for z in (block['layer']-1,block['layer']+STUD_HEIGHT/board.brick_height_per_stud)]
        drawn.append((deepcopy(block),points))
        original(painter,block,project,scale)

    window.render_snapshot(scene('match'))
    qapp.processEvents()
    monkeypatch.setattr(board,'_brick',draw)
    assert not board.grab().isNull()
    assert len(drawn) == 6
    assert sum(block == C for block,_ in drawn) == 2
    for _,points in drawn:
        assert all(0 < point.x() < board.width() and 22 < point.y() < board.height()-10 for point in points)


def test_real_single_transfer_has_no_fabricated_assembly_current(window, qapp):
    backend = Backend(FakePorts(), mode='REAL', single_trial=True)
    backend.controller_ready(ready=True,at_observe_point=True)
    snapshot = make_snapshot(backend.state)
    snapshot['transfer_target'] = dict(brick_type='2x2x1',color='blue',slot=5)
    window.render_snapshot(snapshot)
    qapp.processEvents()
    assert window.target_board.current == dict(current_revision=0,blocks=[])
    assert window.target_board.blocks == [] and window.target_board.target is None
    assert window.design_board.blocks == []
    assert '조립 위치·층·방향 미채택' in window.target_caption.text()
    assert not window.buttons['STOP'].isEnabled() and not window.buttons['RESUME'].isEnabled()


@pytest.mark.parametrize('change', [dict(x=9),dict(color='yellow'),dict(layer=3)])
def test_mismatch_keeps_actual_placement_and_separate_goal(window, change):
    snapshot = scene('mismatch')
    actual = {**C, **change}
    snapshot['current'] = dict(current_revision=3,blocks=[A,B,actual])
    snapshot['step']['observed']['visible_blocks'] = [actual]
    window.render_snapshot(snapshot)
    assert window.target_board.current['blocks'] == [A,B,actual]
    assert window.target_board.target == C
    assert window.target_board.blocks == [A,B,actual,C]
    assert window._snapshot['step']['comparison'] == 'MISMATCH'
    assert window.table.item(2,2).text() == f"({actual['x']}, {actual['y']})"
    assert window.table.item(3,2).text() == f"{actual['layer']}층"


@pytest.mark.parametrize('x,y', [(0,0),(21,0),(0,21),(21,21)])
def test_four_layer_assembly_at_board_edges_fits_both_views(window, qapp, monkeypatch, x, y):
    from app.hmi_board import dimensions, STUD_HEIGHT
    snapshot = scene('waiting')
    blocks=[dict(brick_type='2x3x1',color='yellow',x=x,y=y,layer=layer,orientation_deg=90)
            for layer in range(1,4)]
    snapshot['current'] = dict(current_revision=3,blocks=blocks)
    snapshot['step']['target'] = {**blocks[0],'color':'blue','layer':4}
    window.render_snapshot(snapshot)
    qapp.processEvents()
    points=[]
    board=window.target_board
    original=board._brick

    def draw(painter, block, project, scale):
        w,d=dimensions(block)
        points.extend(project(px,py,z) for px in (block['x'],block['x']+w)
                      for py in (block['y'],block['y']+d)
                      for z in (block['layer']-1,block['layer']+STUD_HEIGHT/board.brick_height_per_stud))
        original(painter,block,project,scale)

    monkeypatch.setattr(board,'_brick',draw)
    assert not board.grab().isNull()
    assert len(points) == 64
    assert all(0 < point.x() < board.width() and 22 < point.y() < board.height()-10 for point in points)
    assert window.frameGeometry().size() == QSize(1200,900)


def test_nearby_wrong_position_and_goal_are_both_drawn_in_zoom(window, qapp, monkeypatch):
    snapshot=scene('mismatch')
    actual={**C,'x':9}
    snapshot['current']=dict(current_revision=3,blocks=[A,B,actual])
    snapshot['step']['observed']['visible_blocks']=[actual]
    window.render_snapshot(snapshot)
    qapp.processEvents()
    drawn=[]
    original=window.target_board._brick

    def draw(painter, block, project, scale):
        drawn.append(deepcopy(block))
        original(painter,block,project,scale)

    monkeypatch.setattr(window.target_board,'_brick',draw)
    assert not window.target_board.grab().isNull()
    assert drawn.count(actual)==2 and drawn.count(C)==2


def test_real_manual_mismatch_displays_adopted_input_without_camera_claim(window, qapp):
    snapshot=scene('mismatch')
    snapshot.update(manual_trial=True,workflow_status='HOLD',
                    reported_placement={**C,'color':'yellow'})
    snapshot['monitor']['robot']['mode']='REAL'
    snapshot['actions']['stop']['enabled']=True
    window.render_snapshot(snapshot)
    qapp.processEvents()
    assert window.target_board.current == snapshot['current']
    assert window.target_board.blocks == [A,B,{**C,'color':'yellow'},C]
    assert window.table.horizontalHeaderItem(2).text()=='현장 입력'
    assert 'Camera 확인 아님' in window.target_caption.text()
    assert window.buttons['STOP'].isEnabled() and not window.buttons['RESUME'].isEnabled()
