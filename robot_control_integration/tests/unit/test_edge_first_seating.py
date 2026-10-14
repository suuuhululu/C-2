from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from app.edge_first_seating import preview,rotate_about_contact_line
from app.assembly_motion import pose_error


def config():
    return json.loads((Path(__file__).resolve().parents[2]/'fixtures/yellow4_edge_first_preview.json').read_text())


def matrix(p):
    t=np.eye(4);t[:3,:3]=Rotation.from_euler('ZYZ',p[3:],degrees=True).as_matrix();t[:3,3]=p[:3]
    return t


@pytest.mark.parametrize('tilt',[5.,-5.,20.,-20.])
def test_contact_line_remains_fixed_and_tcp_follows_arc(tilt):
    c=config();c['initial_tilt_deg']=tilt;source=deepcopy(c);result=preview(c)
    line=np.column_stack((np.asarray(c['contact_line_points_mm']),np.ones(2)))
    local=(np.linalg.inv(matrix(c['seated_reference_tcp_mm_zyz_deg']))@line.T).T
    for point in result['waypoints']:
        assert (matrix(point['tcp_mm_zyz_deg'])@local.T).T==pytest.approx(line,abs=1e-9)
    assert result['max_tcp_translation_from_seated_mm']>0
    assert result['waypoints'][-1]['tcp_mm_zyz_deg']==c['seated_reference_tcp_mm_zyz_deg']
    assert c==source and result['physical_commands']==0


def test_positive_tilt_lifts_opposite_row_while_first_row_stays_fixed():
    c=config();goal=c['seated_reference_tcp_mm_zyz_deg']
    tool_point=np.linalg.inv(matrix(goal))@np.array([0.,8.,0.,1.])
    tilted=rotate_about_contact_line(goal,c['contact_line_points_mm'],10.)
    assert (matrix(tilted)@tool_point)[2]>0


def test_axes_are_supplied_in_frame_not_fixed_robot_x_or_y():
    c=config();c['contact_line_points_mm']=[[10.,-3.,2.],[12.,6.,4.]]
    t=rotate_about_contact_line(c['seated_reference_tcp_mm_zyz_deg'],c['contact_line_points_mm'],7.)
    assert pose_error(t,c['seated_reference_tcp_mm_zyz_deg'])[1]==pytest.approx(7.)


@pytest.mark.parametrize('color,kind',[('blue','2x2x1'),('yellow','2x3x1'),('red','1x2x1')])
def test_no_general_step_or_other_block_adoption(color,kind):
    c=config();c['block'].update(color=color,brick_type=kind)
    with pytest.raises(ValueError,match='SINGLE_YELLOW'):preview(c)


def test_live_mode_and_zero_length_pivot_are_rejected():
    c=config();c['mode']='REAL'
    with pytest.raises(ValueError,match='PREVIEW_ONLY'):preview(c)
    with pytest.raises(ValueError,match='MUST_HAVE_LENGTH'):
        rotate_about_contact_line([0.,0.,30.,0.,180.,0.],[[0.,0.,0.],[0.,0.,0.]],5.)
