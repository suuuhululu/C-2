"""Local display is separate from hand gate and physical motion permission."""
import numpy as np
import pytest

from perception_mvp.live_view import geometry_display_allowed, geometry_input_reasons
from perception_mvp.integrated_view import draw_integrated


def test_unknown_hand_blocks_normal_display_but_explicit_diagnostic_is_separate():
    event = dict(observation_allowed=False)
    assert not geometry_display_allowed(True, True, True, 'V0', event)
    assert geometry_display_allowed(True, True, True, 'V0', event, diagnostic=True)
    assert event == dict(observation_allowed=False)


@pytest.mark.parametrize('sync,info,stop', [(False, True, True), (True, False, True),
                                          (True, True, False)])
def test_diagnostic_still_requires_synchronized_stopped_input(sync, info, stop):
    assert not geometry_display_allowed(sync, info, stop, 'V0', {}, diagnostic=True)


def test_measured_height_does_not_invent_layer(monkeypatch):
    texts = []
    monkeypatch.setattr('perception_mvp.integrated_view.cv2.putText',
                        lambda canvas, text, *args: texts.append(text))
    mask = np.ones((60, 500), bool)
    record = dict(mask=mask, part_class='yellow_2x2', grid=[3, 5], layer=None,
                  height_mm=47.2, reason='layer_reference_missing')
    draw_integrated(np.zeros((60, 500, 3), np.uint8), [record], show_height=True)
    assert 'L:?' in texts[0] and 'H:47.2mm' in texts[0]
    assert record['layer'] is None


@pytest.mark.parametrize('cal,depth,info,sync,expected', [
    (None, True, True, True, ['calibration_missing']),
    ({}, False, True, False, ['aligned_depth_not_received']),
    ({}, True, False, True, ['aligned_camera_info_not_received']),
    ({}, True, True, False, ['rgb_depth_not_fresh_or_synchronized']),
    ({}, True, True, True, [])])
def test_distinct_geometry_input_reasons(cal, depth, info, sync, expected):
    assert geometry_input_reasons(cal, depth, info, sync, True, 'V0', {},
                                  diagnostic=True) == expected


def test_sync_diagnostic_separates_header_delta_from_arrival_age(monkeypatch):
    from perception_mvp.live_view import sync_diagnostic
    monkeypatch.setattr('perception_mvp.live_view.stamp', lambda message: message)
    queues = dict(rgb=[1_000_000_000], aligned=[1_080_000_000], raw=[])
    result = sync_diagnostic(queues, {'rgb': 9.9, 'aligned': 9.5}, 10., 9.)
    assert result == pytest.approx(dict(delta_ms=80, rgb_age_ms=100,
                                       depth_age_ms=500, packet_age_ms=1000))


def test_sync_diagnostic_no_depth_reports_missing_not_zero():
    from perception_mvp.live_view import sync_diagnostic, sync_diagnostic_text
    result = sync_diagnostic(dict(rgb=[], aligned=[], raw=[]), {}, 10., 0.)
    assert all(value is None for value in result.values())
    assert 'Depth age:missing' in sync_diagnostic_text(result)


def test_receiver_buffer_snapshot_does_not_change_during_inference(monkeypatch):
    from perception_mvp.live_view import LiveFrameBuffer
    monkeypatch.setattr('perception_mvp.live_view.stamp', lambda message: message)
    buffer = LiveFrameBuffer()
    buffer.image('rgb', 100)
    buffer.image('aligned', 100)
    queues, infos, received, arrivals = buffer.snapshot()
    buffer.image('rgb', 200)
    assert queues['rgb'] == [100]
    assert buffer.snapshot()[0]['rgb'] == [100, 200]
    assert ('rgb', 100) in arrivals and received['rgb'] > 0
    buffer.clear()
    assert not buffer.snapshot()[0]['rgb']


def test_receiver_buffer_is_bounded(monkeypatch):
    from perception_mvp.live_view import LiveFrameBuffer
    monkeypatch.setattr('perception_mvp.live_view.stamp', lambda message: message)
    buffer = LiveFrameBuffer()
    for value in range(30):
        buffer.image('rgb', value)
    queues, _, _, arrivals = buffer.snapshot()
    assert queues['rgb'] == list(range(20, 30))
    assert len(arrivals) == 10


@pytest.mark.parametrize('view', ['V0', 'D1', 'D3'])
def test_moving_never_allows_block_analysis(view):
    from perception_mvp.live_view import stopped_analysis_ready
    assert not stopped_analysis_ready(view, False, True, True,
                                      dict(observation_allowed=True), 200, 0)


def test_v0_requires_hand_permission_and_a_new_frame_after_ready():
    from perception_mvp.live_view import stopped_analysis_ready
    assert not stopped_analysis_ready('V0', True, True, True,
                                      dict(observation_allowed=False), 200, 0)
    ready = dict(observation_allowed=True)
    assert not stopped_analysis_ready('V0', True, True, True, ready, 200, 200)
    assert stopped_analysis_ready('V0', True, True, True, ready, 201, 200)


@pytest.mark.parametrize('view', ['D1', 'D3'])
def test_diagonal_views_need_no_hand_detection_and_do_not_repeat(view):
    from perception_mvp.live_view import stopped_analysis_ready
    assert stopped_analysis_ready(view, True, True, True, {}, 200, 0)
    assert not stopped_analysis_ready(view, True, True, True, {}, 201, 0, completed=True)


@pytest.mark.parametrize('sync,info', [(False, True), (True, False)])
def test_one_shot_needs_synchronized_input_and_camera_info(sync, info):
    from perception_mvp.live_view import stopped_analysis_ready
    assert not stopped_analysis_ready('D1', True, sync, info, {}, 200, 0)
