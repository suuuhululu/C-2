"""Color display checks; no proof of real object identity or physical assembly."""
import numpy as np
import pytest
from perception_mvp.live_view import live_overlay_test_payload
from perception_mvp.visualization import projected_color_test, render_comparison_overlay


def payload():
    k = [[500.,0.,200.],[0.,500.,160.],[0.,0.,1.]]
    c = dict(independently_validated=True,image_size=[400,320],view_id='V0',pitch_mm=16.,
        intrinsics=dict(camera_matrix=k),camera_pose=dict(R_camera_from_board=np.diag([1.,-1.,-1.]).tolist(),
        t_camera_from_board_mm=[-40.,40.,600.],height_normal_sign=1))
    info = dict(width=400,height=320,k=np.array(k).ravel().tolist(),distortion_model='plumb_bob',d=[0.]*5)
    return live_overlay_test_payload(c,info,(320,400,3),
        dict(top_heights_mm=[22.,40.625,59.25,77.875],height_reference_offset_mm=4.),
        [2,2],'OBSERVING',123)


@pytest.mark.parametrize('rgb_color,actual,status', [
    ((255,255,0),'yellow','MATCH'), ((0,0,255),'blue','MISMATCH'),
    ((255,0,0),'red','MISMATCH'), ((120,120,120),None,'UNKNOWN')])
def test_local_probe_matches_rgb_colors_not_synthetic_current(rgb_color,actual,status):
    p=payload()
    rgb=np.full((320,400,3),rgb_color,np.uint8)
    report=projected_color_test(rgb,p['state']['expected'][-1],p['projection'])
    assert report['actual']==actual and report['status']==status and report['trial_only']
    assert p['state']['comparison'] is None


def test_b_color_difference_draws_warning_without_rewriting_current(monkeypatch):
    p=payload()
    target=p['state']['expected'][-1]
    actual=dict(target,color='blue')
    p['state'].update(display_stage='CONFIRMED',comparison='MISMATCH',
        current=dict(current_revision=1,blocks=[actual]),
        difference=dict(missing=[target],unexpected=[actual],unobservable=[]))
    texts=[]
    monkeypatch.setattr('perception_mvp.visualization.cv2.putText',
                        lambda image,text,*args: texts.append(text))
    _,report=render_comparison_overlay(np.zeros((320,400,3),np.uint8),p,view='V0',
        frame_stamp_ns=123,stopped=True,hand_clear=True)
    assert 'expected yellow / actual blue' in report['comparison_warning']
    assert p['state']['current']['blocks'][0]['color']=='blue'
    _,hidden=render_comparison_overlay(np.zeros((320,400,3),np.uint8),p,view='V0',
        frame_stamp_ns=123,stopped=False,hand_clear=True)
    assert not hidden['overlay_visible'] and 'comparison_warning' not in hidden
