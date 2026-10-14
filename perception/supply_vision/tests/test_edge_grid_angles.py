import numpy as np
import pytest
from supply_vision.edge_grid_angles import fit_grid_axes,compare_edge_grid,angle_delta


def grid(angle):
    a=np.radians(angle);r=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
    return (np.array([[x*20,y*20] for x in range(5) for y in range(4)])@r.T+100).tolist()


def test_rotated_grid_recovers_two_axes_without_diagonal_all_pair_lines():
    result=fit_grid_axes(grid(23))
    assert result['status']=='PIXEL_GRID_AXES_CANDIDATE'
    assert min(abs(angle_delta(a,23)) for a in result['axes_deg'])<1e-6
    assert min(abs(angle_delta(a,113)) for a in result['axes_deg'])<1e-6
    assert not result['execution_allowed']


def test_duplicate_circular_edges_are_merged():
    points=grid(5);points+=[[x+.2,y+.1] for x,y in points]
    result=fit_grid_axes(points)
    assert len(result['unique_centers_uv'])==20
    assert result['status']=='PIXEL_GRID_AXES_CANDIDATE'


def test_edge_relative_angle_compares_to_grid_not_image_horizontal():
    a=np.radians(30);edge=[[0,0],[40*np.cos(a),40*np.sin(a)]]
    result=compare_edge_grid([edge],grid(23))
    assert result['relative_angle_deg']==pytest.approx(-7.,abs=1e-9)
    assert result['robot_correction'] is None


def test_inadequate_or_one_line_points_do_not_claim_two_axis_alignment():
    assert fit_grid_axes([[0,0],[20,0]])['status']=='UNKNOWN'
    assert fit_grid_axes([[i*20,0] for i in range(8)])['status']=='UNKNOWN'
    assert compare_edge_grid([],grid(0))['status']=='UNKNOWN'
def test_labelled_top_edge_tracks_new_image_and_rejects_lost_corners():
    import cv2
    from supply_vision.edge_grid_angles import track_visible_edge
    frame=np.zeros((160,200),np.uint8)
    cv2.rectangle(frame,(40,45),(110,95),220,-1)
    moved=cv2.warpAffine(frame,np.array([[1.,0.,7.],[0.,1.,4.]],np.float32),(200,160))
    result=track_visible_edge(frame,moved,[[40.,45.],[110.,45.]])
    assert np.asarray(result)==pytest.approx(np.array([[47.,49.],[117.,49.]]),abs=.15)
    assert track_visible_edge(np.zeros_like(frame),np.zeros_like(frame),[[40.,45.],[110.,45.]]) is None
