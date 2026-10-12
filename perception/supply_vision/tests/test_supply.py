import copy

import pytest

from supply_vision.main import assign_slots, load_model, validate_layout

LAYOUT = {'image_size': [640, 480], 'slots': [
    {'brick_type': '2x3x1', 'color': 'blue', 'slot': 1, 'grasp_edge_pair': 1, 'roi_xyxy': [10, 20, 100, 120]},
    {'brick_type': '2x3x1', 'color': 'blue', 'slot': 2, 'grasp_edge_pair': 1, 'roi_xyxy': [150, 20, 240, 120]}]}


def hit(box=(20, 30, 80, 100), score=.9, name='blue_2x3'):
    return {'box': list(box), 'confidence': score, 'class_name': name}


def test_requested_block_and_missing_slot():
    states = assign_slots(LAYOUT, [hit()], .8)
    assert states[0]['status'] == 'DETECTED'
    assert states[0]['brick_type'] == '2x3x1'
    assert states[0]['slot'] == 1
    assert states[1]['status'] == 'UNKNOWN'
    assert states[1]['reason'] == 'no_detection'


@pytest.mark.parametrize('detections,reason', [
    ([hit(score=.6)], 'low_confidence'),
    ([hit(), hit(name='red_2x1')], 'multiple_detections'),
    ([hit(box=(80, 30, 180, 100))], 'detection_crosses_slot'),
])
def test_uncertain_not_selected(detections, reason):
    state = assign_slots(LAYOUT, detections, .8)[0]
    assert state['status'] == 'UNKNOWN'
    assert state['geometry'] is None
    assert state['reason'] == reason


def test_crossing_two_slots_invalidates_both():
    states = assign_slots(LAYOUT, [hit(box=(80, 30, 180, 100))], .8)
    assert all(s['reason'] == 'detection_crosses_slot' for s in states)


@pytest.mark.parametrize('change', ['overlap', 'duplicate', 'outside', 'empty'])
def test_invalid_layout(change):
    layout = copy.deepcopy(LAYOUT)
    if change == 'overlap':
        layout['slots'][1]['roi_xyxy'] = [90, 20, 200, 120]
    elif change == 'duplicate':
        layout['slots'][1]['slot'] = 1
    elif change == 'outside':
        layout['slots'][0]['roi_xyxy'][0] = -1
    else:
        layout['slots'] = []
    with pytest.raises(ValueError):
        validate_layout(layout)


@pytest.mark.parametrize('detection', [hit(score=float('nan')), hit(box=(80,30,20,100)),
                                       hit(name='unknown')])
def test_invalid_detection(detection):
    with pytest.raises(ValueError):
        assign_slots(LAYOUT, [detection], .8)


def test_missing_model_no_download(tmp_path):
    with pytest.raises(ValueError):
        load_model(tmp_path / 'missing.pt')
