from copy import deepcopy

import cv2
import numpy as np
import pytest

from perception_mvp.rgbd_io import save_frame
from perception_mvp.main import main
from perception_mvp.visualization import color_masks, save_color_review
from perception_mvp.visualization import freeze_overlay_states, render_state_overlay, _block_surfaces


def overlay_inputs():
    transform = np.eye(4)
    camera_from_board = np.eye(4)
    camera_from_board[:3,:3] = np.diag([1.,-1.,-1.])
    camera_from_board[:3,3] = [-.04,.04,.6]
    transform = np.linalg.inv(camera_from_board)
    projection = dict(camera_to_board=transform,
        rgb_intrinsics=dict(model='none',fx=500.,fy=500.,cx=200.,cy=160.),
        grid_origin_m=[0.,0.],stud_pitch_m=.017,
        top_heights_m=[.022,.0425,.0615,.081])
    current = [dict(brick_type='2x2x1',color='yellow',x=2,y=2,layer=1,orientation_deg=0)]
    target = current + [dict(current[0],layer=2)]
    return np.zeros((320,400,3),np.uint8), freeze_overlay_states(current,target,{}), projection


def test_overlay_default_opacity_eight_percent_and_thin_edges(monkeypatch):
    rgb,snapshot,projection = overlay_inputs()
    blends, widths = [], []
    blend = cv2.addWeighted
    lines = cv2.polylines
    def capture_blend(first,alpha,second,beta,gamma,*args,**kwargs):
        blends.append((alpha,beta))
        return blend(first,alpha,second,beta,gamma,*args,**kwargs)
    def capture_lines(image,points,closed,color,thickness,*args,**kwargs):
        widths.append(thickness)
        return lines(image,points,closed,color,thickness,*args,**kwargs)
    monkeypatch.setattr('perception_mvp.visualization.cv2.addWeighted',capture_blend)
    monkeypatch.setattr('perception_mvp.visualization.cv2.polylines',capture_lines)
    _,report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert report['overlay_visible'] and blends and widths
    assert all(alpha == .08 and beta == .92 for alpha,beta in blends)
    assert set(widths) == {1}


@pytest.mark.parametrize('color,kind,rgb_color',[
    ('yellow','2x2x1',(255,220,0)), ('blue','2x2x1',(30,100,255)),
    ('red','1x2x1',(255,45,45))])
def test_overlay_faces_follow_block_color(monkeypatch,color,kind,rgb_color):
    rgb,snapshot,projection = overlay_inputs()
    fills = []
    original = cv2.fillConvexPoly
    def capture(image, polygon, fill, *args, **kwargs):
        fills.append(tuple(fill))
        return original(image, polygon, fill, *args, **kwargs)
    monkeypatch.setattr('perception_mvp.visualization.cv2.fillConvexPoly',capture)
    snapshot['current'] = []
    snapshot['expected'] = [dict(snapshot['expected'][0],color=color,brick_type=kind)]
    _,report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert report['overlay_visible'] and fills == [rgb_color]


def test_actual_wrong_color_is_not_replaced_by_design_color(monkeypatch):
    rgb,snapshot,projection = overlay_inputs()
    snapshot['current'][0]['color'] = 'blue'
    snapshot['expected'] = [dict(snapshot['current'][0],color='yellow')]
    fills = []
    original = cv2.fillConvexPoly
    def capture(image,polygon,fill,*args,**kwargs):
        fills.append(tuple(fill))
        return original(image,polygon,fill,*args,**kwargs)
    monkeypatch.setattr('perception_mvp.visualization.cv2.fillConvexPoly',capture)
    _,report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert report['overlay_visible']
    assert (30,100,255) in fills and (255,220,0) in fills
    assert snapshot['current'][0]['color'] == 'blue'


@pytest.mark.parametrize('stage,comparison,legend', [
    ('OBSERVING', None, 'Current (confirmed)'),
    ('CONFIRMED', 'MATCH', 'Previous confirmed Current'),
    ('CONFIRMED', 'MISMATCH', 'Previous confirmed Current'),
    ('UNOBSERVABLE', 'UNOBSERVABLE', 'Current (confirmed)')])
def test_automatic_overlay_mode_tracks_actual_comparison_stage(monkeypatch, stage, comparison, legend):
    from perception_mvp.visualization import render_comparison_overlay
    rgb, snapshot, projection = overlay_inputs()
    state = dict(check_id='auto', display_stage=stage, comparison=comparison,
        previous_current=dict(blocks=snapshot['current']),
        current=dict(blocks=snapshot['expected']), expected=snapshot['expected'])
    payload = dict(state=state, projection=projection, projection_valid=True,
        height_reference='board_flat_surface', phase='COMPARISON', view_id='V0', frame_stamp_ns=123)
    texts = []
    monkeypatch.setattr('perception_mvp.visualization.cv2.putText',
                        lambda image,text,*args: texts.append(text))
    _, report = render_comparison_overlay(rgb, payload, view='V0', frame_stamp_ns=123,
                                         stopped=True, hand_clear=True)
    assert report['overlay_visible'] and texts[0] == legend


@pytest.mark.parametrize('mode', ['changes', 'target'])
def test_comparison_overlay_modes_use_confirmed_states(mode):
    from perception_mvp.visualization import render_comparison_overlay
    rgb, snapshot, projection = overlay_inputs()
    state = dict(check_id='c1', previous_current=dict(current_revision=0, blocks=snapshot['current']),
        current=dict(current_revision=1, blocks=snapshot['expected']), expected=snapshot['expected'])
    payload = dict(state=state, projection=projection, projection_valid=True,
                   height_reference='board_flat_surface', phase='COMPARISON', view_id='V0', frame_stamp_ns=123)
    result, report = render_comparison_overlay(rgb, payload, view='V0', frame_stamp_ns=123,
        stopped=True, hand_clear=True, mode=mode)
    assert report['overlay_visible'] and report['render_mode'] == '3d_volume'
    assert np.any(result != rgb)


@pytest.mark.parametrize('field,value,reason', [
    ('phase', 'CANCELED', 'not_comparison_phase'),
    ('view_id', 'D1', 'comparison_frame_mismatch'),
    ('frame_stamp_ns', 456, 'comparison_frame_mismatch'),
    ('height_reference', 'stud_top', 'board_flat_height_reference_unconfirmed')])
def test_comparison_overlay_hides_invalid_context(field, value, reason):
    from perception_mvp.visualization import render_comparison_overlay
    rgb, snapshot, projection = overlay_inputs()
    payload = dict(state=dict(check_id='c1',current=dict(blocks=snapshot['current']),
        expected=snapshot['expected']), projection=projection, projection_valid=True,
        height_reference='board_flat_surface', phase='COMPARISON', view_id='V0', frame_stamp_ns=123)
    payload[field] = value
    _, report = render_comparison_overlay(rgb, payload, view='V0', frame_stamp_ns=123,
                                         stopped=True, hand_clear=True)
    assert not report['overlay_visible'] and report['reason'] == reason


def test_overlay_projects_top_and_sides_and_preserves_inputs():
    rgb,snapshot,projection = overlay_inputs()
    before = deepcopy(snapshot)
    result, report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert report['overlay_visible'] and report['render_mode'] == '3d_volume'
    assert report['rendered_faces'] == 2  # Overhead view sees tops, not back-facing sides.
    assert np.count_nonzero(result[80:280]) > 0
    assert not rgb.any() and snapshot == before
    corners = [(0.,0.),(.034,0.),(.034,.034),(0.,.034)]
    faces = _block_surfaces(corners,.022,.0425,{(0,0,2)},np.zeros(2),.017,0.)
    assert len(faces) == 5
    assert np.all(faces[0][0][:,2] == .0425)
    for face,_ in faces[1:]:
        assert set(face[:,2]) == {.022,.0425}


def test_overlay_studs_use_explicit_height():
    rgb,snapshot,projection = overlay_inputs()
    projection['stud_height_m'] = .004
    _,report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert report['rendered_faces'] >= 10
    projection['stud_height_m'] = .03
    _,report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert not report['overlay_visible'] and 'stud height' in report['reason']


def test_fifth_layer_requires_explicit_height():
    rgb, snapshot, projection = overlay_inputs()
    snapshot['expected'] = [dict(snapshot['current'][0], layer=5)]
    _, report = render_state_overlay(rgb, snapshot, projection, stopped=True, projection_valid=True)
    assert not report['overlay_visible'] and 'missing measured height' in report['reason']
    # Synthetic geometry is a unit-test input, not a fifth-layer field measurement.
    projection['top_heights_m'].append(.101)
    _, report = render_state_overlay(rgb, snapshot, projection, stopped=True, projection_valid=True)
    assert report['overlay_visible'] and report['rendered_faces'] > 0


def test_oblique_camera_renders_side_faces():
    rgb,snapshot,projection = overlay_inputs()
    centre = np.array([.04,-.15,.4])
    forward = np.array([.04,.04,.02])-centre
    forward /= np.linalg.norm(forward)
    right = np.cross(forward,[0.,0.,1.])
    right /= np.linalg.norm(right)
    rotation = np.array([right,np.cross(forward,right),forward])
    camera_from_board = np.eye(4)
    camera_from_board[:3,:3] = rotation
    camera_from_board[:3,3] = -rotation @ centre
    projection['camera_to_board'] = np.linalg.inv(camera_from_board)
    _,report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert report['rendered_faces'] > 2 and not report['skipped']


@pytest.mark.parametrize('stopped,valid,snapshot_missing,reason',[
    (False,True,False,'camera_moving'),(True,False,False,'projection_unverified'),
    (True,True,True,'backend_state_missing')])
def test_3d_overlay_still_hides_on_invalid_context(stopped,valid,snapshot_missing,reason):
    rgb,snapshot,projection = overlay_inputs()
    _,report = render_state_overlay(rgb,None if snapshot_missing else snapshot,projection,
                                  stopped=stopped,projection_valid=valid)
    assert not report['overlay_visible'] and report['reason'] == reason


def test_overlay_skips_volume_crossing_camera_plane():
    rgb,snapshot,projection = overlay_inputs()
    projection['camera_to_board'][2,3] = .015
    _,report = render_state_overlay(rgb,snapshot,projection,stopped=True,projection_valid=True)
    assert len(report['skipped']) == 2 and report['rendered_faces'] == 0


@pytest.fixture
def settings():
    # Synthetic pure colors only; these limits are not real-light calibration.
    return {"threshold_status": "temporary_test", "hsv_ranges": {
        "yellow": {"lower": [20, 100, 100], "upper": [40, 255, 255]},
        "blue": {"lower": [100, 100, 100], "upper": [130, 255, 255]}}}


def test_rgb_order_and_original_preserved(settings):
    rgb = np.array([[[255, 255, 0], [0, 0, 255], [255, 0, 0]]], np.uint8)
    original = rgb.copy()
    masks = color_masks(rgb, settings)
    assert masks["yellow"].tolist() == [[255, 0, 0]]
    assert masks["blue"].tolist() == [[0, 255, 0]]
    np.testing.assert_array_equal(rgb, original)


@pytest.mark.parametrize("failure", ["hue", "reverse", "missing", "float", "status"])
def test_invalid_limits(settings, failure):
    settings = deepcopy(settings)
    if failure == "hue":
        settings["hsv_ranges"]["yellow"]["upper"][0] = 180
    elif failure == "reverse":
        settings["hsv_ranges"]["yellow"]["lower"][0] = 50
    elif failure == "missing":
        del settings["hsv_ranges"]["blue"]
    elif failure == "float":
        settings["hsv_ranges"]["blue"]["lower"][0] = 100.5
    else:
        settings["threshold_status"] = "unknown"
    with pytest.raises(ValueError):
        color_masks(np.zeros((2, 2, 3), np.uint8), settings)


def test_same_color_contact_is_not_instance_split(settings):
    rgb = np.full((4, 4, 3), (255, 255, 0), np.uint8)
    assert np.count_nonzero(color_masks(rgb, settings)["yellow"]) == 16


def test_background_is_not_empty_board_evidence(settings):
    masks = color_masks(np.zeros((4, 4, 3), np.uint8), settings)
    assert all(np.count_nonzero(mask) == 0 for mask in masks.values())


def test_overlapping_ranges_are_preserved_not_arbitrarily_selected(settings):
    settings["hsv_ranges"]["blue"] = deepcopy(settings["hsv_ranges"]["yellow"])
    rgb = np.full((4, 4, 3), (255, 255, 0), np.uint8)
    masks = color_masks(rgb, settings)
    assert np.all(masks["yellow"] == 255) and np.all(masks["blue"] == 255)


def test_saved_review_cli_and_no_overwrite(tmp_path, settings):
    import json
    rgb = np.full((32, 40, 3), (0, 0, 255), np.uint8)
    depth = np.ones((32, 40), np.uint16)
    meta = {"mode": "TEST", "scene_id": "synthetic", "view_id": "V0",
            "captured_at": "test", "camera_info": {"basis": "fixture"},
            "depth_scale_m": .001, "robot_pose": None}
    recording = tmp_path / "frame"
    save_frame(recording, rgb, depth, depth, meta)
    config = tmp_path / "hsv.json"
    config.write_text(json.dumps(settings))
    output = tmp_path / "review"
    main(["color-check", str(recording), "--settings", str(config), "--output", str(output)])
    actual = cv2.cvtColor(cv2.imread(str(output / "original.png")), cv2.COLOR_BGR2RGB)
    np.testing.assert_array_equal(actual, rgb)
    assert cv2.imread(str(output / "comparison.png")).shape == (32, 160, 3)
    report = json.loads((output / "color_review.json").read_text())
    assert report["purpose"] == "color_review_only"
    assert report["mode"] == "TEST"
    assert "visible_blocks" not in report and "verified_regions" not in report
    with pytest.raises(FileExistsError):
        save_color_review(recording, settings, output)
