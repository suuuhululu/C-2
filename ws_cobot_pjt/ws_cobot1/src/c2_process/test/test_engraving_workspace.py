import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from c2_process.engraving_workspace import check_path_workspace, check_waypoints
from c2_process.entry_planner import _geometry_check


def pose(z):
    return [0.4, 0.15, z, 0., 0., 0., 1.]


@pytest.mark.parametrize('z,accepted', [(0.05, True), (0.049999, False), (0.19, True), (2., True)])
def test_boundary(z, accepted):
    assert check_waypoints([pose(z)]).ok is accepted


@pytest.mark.parametrize('kind', ['APPROACH', 'CUT', 'TRAVEL', 'RETRACT'])
def test_all_body_segments_checked(kind):
    path = {'frame_id': 'c2_base', 'segments': [{'segment_id': 'bad', 'kind': kind,
                                              'waypoints': [pose(.2), pose(.049)]}]}
    result = check_path_workspace(path)
    assert not result.ok and result.observed_state['segment_id'] == 'bad'


def test_entry_ignores_measurement_box_and_checks_tip_not_controller_tcp():
    workcell = {'axis_xy_m': [0., 0.], 'radius_m': .03, 'top_z_m': .2,
                'trial_scene': {'tcp_min_m': [0., 0., .19], 'tcp_max_m': [.01, .01, .335]}}
    candidate = {'policy': {'min_radial_gap_m': .005}, 'validation_waypoints': [pose(.05)]}
    # TCP Z=0.01でもwaypoint Z=0.05は許可。測定用XY/Z箱は適用しない。
    assert _geometry_check(candidate, workcell, [0., 0., .04]).ok
    candidate['validation_waypoints'] = [pose(.2), pose(.049), pose(.1)]
    # 最初・最後が範囲内でも途中のサンプルを拒否する。
    assert not _geometry_check(candidate, workcell, [0., 0., -.1]).ok


def test_candle_gap_still_rejected():
    workcell = {'axis_xy_m': [.4, .15], 'radius_m': .03, 'top_z_m': .2}
    candidate = {'policy': {'min_radial_gap_m': .005}, 'validation_waypoints': [pose(.1)]}
    assert not _geometry_check(candidate, workcell, [0., 0., 0.]).ok
