"""Measurement regression, physical layout interpretation, and invalid-slot checks."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from planning_trial.supply_pick import (
    calculate_all_supply_picks, calculate_supply_pick, fit_grid_xy,
    load_supply_profile, relative_centres,
)


def test_original_measured_anchor_is_preserved_and_new_depth_changes_only_z():
    profile = load_supply_profile()
    pick = calculate_supply_pick('2x2x1', 'yellow', 1)
    assert profile['first_pick_tcp_mm_zyz_deg'] == [-321.4, 184.61, 53.04, 62.73, -179.99, 63.5]
    assert pick['pickup_tcp_pose']['xyz_abc'] == [-321.4, 184.61, 50.04, 62.73, -179.99, 63.5]
    assert pick['grasp']['pad_bottom_above_block_bottom_mm'] == 5
    assert pick['grasp']['tcp_z_shift_from_taught_mm'] == -3
    assert pick['grasp']['reference_equivalence'] == 'USER_CONFIRMED_SAME_REFERENCE'
    assert pick['execution_allowed'] is False
    assert pick['slot_readiness_checked'] is False


def test_twenty_four_candidates_match_prior_measured_layout_record():
    old = json.loads((Path(__file__).parent / 'measurements/supply_pick_candidates.user_20261007.json').read_text())
    profile = load_supply_profile()
    profile['desired_grip_height_above_bottom_mm'] = 8
    new = calculate_all_supply_picks(profile=profile)
    assert new['count'] == len(old['slots']) == 24
    for expected, actual in zip(old['slots'], new['slots']):
        assert (actual['brick_type'], actual['color'], actual['slot_index']) == (expected['brick_type'], expected['color'], expected['slot'])
        assert actual['pickup_tcp_pose']['xyz_abc'] == pytest.approx(expected['candidate_base_tcp_xyz_abc'])


def test_sixth_slot_is_twenty_cells_down_and_slots_are_not_implicitly_wrapped():
    pick = calculate_supply_pick('2x3x1', 'blue', 6)
    assert pick['relative_block_centre_grid'] == [-20, -11.5]
    # Fourth column, last row: a useful distant check, independently frozen below.
    assert pick['pickup_tcp_pose']['xyz_abc'][:3] == pytest.approx([-642.653695652174, 7.162717391304369, 50.04])
    with pytest.raises(ValueError):
        calculate_supply_pick('2x3x1', 'blue', 7)


def test_twenty_four_hole_centres_have_twenty_three_intervals():
    grid = fit_grid_xy(load_supply_profile())
    assert grid['interval_counts'] == [23, 23]
    assert grid['x_step_xy_mm'] == pytest.approx([15.960434782608697, -0.24326086956521734])
    assert grid['y_step_xy_mm'] == pytest.approx([0.17782608695652188, 15.853260869565217])


def test_neighbour_distances_include_empty_rows_and_half_cell_centres():
    profile = load_supply_profile()
    centres = relative_centres(profile)
    assert [c['first_centre_relative_grid'][1] for c in centres.values()] == [0, -3.5, -8, -11.5]
    assert [c['slot_step_grid_x'] for c in centres.values()] == [-4] * 4
    # Changing only a measured column gap affects that column and all later columns.
    profile['columns'][1]['gap_before_column_y'] = 2
    changed = relative_centres(profile)
    assert [c['first_centre_relative_grid'][1] for c in changed.values()] == [0, -4.5, -9, -12.5]


def test_raw_corner_z_noise_does_not_tilt_the_flat_board_pickups():
    profile = load_supply_profile()
    baseline = calculate_supply_pick('2x3x1', 'blue', 6, profile=profile)
    profile['corners_tcp_mm_zyz_deg']['3'][2] += 15
    assert calculate_supply_pick('2x3x1', 'blue', 6, profile=profile) == baseline
    assert baseline['pickup_tcp_pose']['xyz_abc'][3:] == profile['first_pick_tcp_mm_zyz_deg'][3:]
    assert baseline['pickup_tcp_pose']['xyz_abc'][2] == 50.04


def test_corner_translation_affects_spacing_only_while_taught_anchor_sets_origin():
    profile = load_supply_profile()
    before = calculate_supply_pick('2x2x1', 'blue', 3, profile=profile)
    for pose in profile['corners_tcp_mm_zyz_deg'].values():
        pose[0] += 100
        pose[1] -= 50
    assert calculate_supply_pick('2x2x1', 'blue', 3, profile=profile)['pickup_tcp_pose']['xyz_abc'] == pytest.approx(before['pickup_tcp_pose']['xyz_abc'])
    profile['first_pick_tcp_mm_zyz_deg'][0] += 100
    profile['first_pick_tcp_mm_zyz_deg'][1] -= 50
    after = calculate_supply_pick('2x2x1', 'blue', 3, profile=profile)['pickup_tcp_pose']['xyz_abc']
    assert after[0] == pytest.approx(before['pickup_tcp_pose']['xyz_abc'][0] + 100)
    assert after[1] == pytest.approx(before['pickup_tcp_pose']['xyz_abc'][1] - 50)


def test_no_profile_mutation_or_slot_consumption_and_all_long_faces_align():
    profile = load_supply_profile()
    saved = deepcopy(profile)
    table = calculate_all_supply_picks(profile=profile)
    assert profile == saved
    for pick in table['slots']:
        assert pick['grasp']['closing_axis'] == 'SUPPLY_GRID_X'
        assert pick['grasp']['width_grid_cells'] == 2
        assert pick['grasp']['close_command_source'] == 'D_EXISTING_SETTINGS_NO_A_OVERRIDE'
        if pick['brick_type'] == '2x3x1':
            assert pick['grasp']['contact'] == 'LONG_SIDE_MIDPOINT'


@pytest.mark.parametrize('slot', [0, 7, -1, True, 1.5, '1', None])
def test_reject_ambiguous_or_out_of_range_slot(slot):
    with pytest.raises(ValueError):
        calculate_supply_pick('2x2x1', 'yellow', slot)


@pytest.mark.parametrize('brick,color', [('2x4x1', 'yellow'), ('2x2x1', 'red'), ('2x3x1', 'Blue')])
def test_reject_unsupported_supply_parts(brick, color):
    with pytest.raises(ValueError):
        calculate_supply_pick(brick, color, 1)


@pytest.mark.parametrize('change', [
    lambda p: p.update(same_setup_confirmed=False),
    lambda p: p.update(grid_feature_count=[24, 1]),
    lambda p: p.update(grid_feature_count=[24, True]),
    lambda p: p.update(grid_feature_count=[10, 24]),
    lambda p: p['first_pick_tcp_mm_zyz_deg'].__setitem__(0, float('nan')),
    lambda p: p['corners_tcp_mm_zyz_deg']['4'].__setitem__(0, float('inf')),
    lambda p: p.update(positive_x_corner=p['origin_corner']),
    lambda p: p['columns'][1].update(occupied_grid_x=3, occupied_grid_y=2),
])
def test_reject_mismatched_setup_degenerate_grid_and_nonfinite_measurements(change):
    profile = load_supply_profile()
    change(profile)
    with pytest.raises(ValueError):
        calculate_supply_pick('2x2x1', 'yellow', 1, profile=profile)


def test_degenerate_xy_grid_is_not_a_pose_candidate():
    profile = load_supply_profile()
    for pose in profile['corners_tcp_mm_zyz_deg'].values():
        pose[1] = 0
    with pytest.raises(ValueError):
        fit_grid_xy(profile)


def test_flipped_plate_height_diagnostic_does_not_add_stud_height():
    d = calculate_all_supply_picks()['z_diagnostic']
    assert d['approx_surface_from_closed_tip_mean_mm'] == pytest.approx(36.825)
    assert d['approx_pick_tcp_from_two_offsets_mm'] == pytest.approx(52.135)
    assert d['selected_taught_pick_tcp_z_mm'] == 53.04
    assert d['taught_minus_two_offset_estimate_mm'] == pytest.approx(.905)
    assert d['selected_pick_candidate_tcp_z_mm'] == pytest.approx(50.04)
    assert d['derived_tcp_above_bottom_for_target_mm'] == pytest.approx(12.31)


def test_all_twenty_four_slots_shift_three_mm_down_with_no_xy_or_attitude_change():
    profile = load_supply_profile()
    new = calculate_all_supply_picks(profile=profile)
    profile['desired_grip_height_above_bottom_mm'] = 8
    old = calculate_all_supply_picks(profile=profile)
    for a, b in zip(new['slots'], old['slots']):
        pa, pb = a['pickup_tcp_pose']['xyz_abc'], b['pickup_tcp_pose']['xyz_abc']
        assert pa[:2] == pb[:2] and pa[3:] == pb[3:]
        assert pa[2] - pb[2] == pytest.approx(-3)
        assert a['grasp']['close_command_source'] == b['grasp']['close_command_source']


@pytest.mark.parametrize('height', [-1, 20, float('nan')])
def test_invalid_target_pad_height_is_rejected(height):
    profile = load_supply_profile()
    profile['desired_grip_height_above_bottom_mm'] = height
    with pytest.raises(ValueError):
        calculate_supply_pick('2x2x1', 'yellow', 1, profile=profile)


def test_different_height_reference_is_not_converted_using_three_mm_shortcut():
    profile = load_supply_profile()
    profile['grip_height_reference_equivalence'] = 'DIFFERENT_REFERENCE'
    with pytest.raises(ValueError):
        calculate_supply_pick('2x2x1', 'yellow', 1, profile=profile)
