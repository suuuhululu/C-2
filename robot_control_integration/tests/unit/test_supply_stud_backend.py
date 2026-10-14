from copy import deepcopy
import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from app.supply_stud.backend import observe
from scripts.supply_pick_release_trial import center_target,DEFAULT,load_config


def setup():
    config=load_config(DEFAULT)
    layout=json.loads(Path(config['vision']['layout']).read_text())
    return config,layout


def test_missing_block_uses_exact_taught_pose():
    config,layout=setup()
    for row in config['blocks']:
        decision=observe(np.zeros((480,640,3),np.uint8),layout,row,1)
        assert not decision['recognized'] and decision['center_uv'] is None
        assert center_target(row,decision)==row['pickup_pose']
        assert not decision['center_assist_applied']


def test_old_box_mapping_not_used_for_stud_center():
    config,_=setup();row=deepcopy(config['blocks'][0])
    row['center_mapping']=dict(independently_verified=True,base_xy_mm_per_pixel=[[1,0],[0,1]],reference_center_uv=[0,0],max_shift_mm=5)
    decision=dict(slot_id='yellow_2x2x1_01',recognized=True,center_available=True,center_uv=[1,2],center_basis='STUD_ARRAY')
    assert center_target(row,decision)==row['pickup_pose']
    assert decision['fallback_reason']=='STUD_CENTER_MAPPING_NOT_VERIFIED'
    row['center_mapping']['center_basis']='STUD_ARRAY'
    assert center_target(row,decision)[:2]==[row['pickup_pose'][0]+1,row['pickup_pose'][1]+2]


def test_invalid_layout_stops_instead_of_silent_coordinate_fallback():
    config,layout=setup();layout['slots']=[]
    with pytest.raises(ValueError,match='EXACT_TARGET_SLOT_REQUIRED'):
        observe(np.zeros((480,640,3),np.uint8),layout,config['blocks'][0],1)


def test_adopted_live_roi_preserves_right_to_left_physical_slot_identity():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    c=load_config(root/'settings/supply_sequence_20261014/config.json')
    layout=json.loads(Path(c['vision']['layout']).read_text())
    yellow=[s for s in layout['slots'] if s['color']=='yellow' and s['brick_type']=='2x2x1']
    assert next(s for s in yellow if s['slot']==1)['roi_xyxy']==[452,37,514,99]
    assert next(s for s in yellow if s['slot']==5)['roi_xyxy']==[161,37,217,99]
    assert 'OTHER_CHAT' in layout['opencv_roi_basis']


def test_slot_threshold_settings_are_not_overwritten(monkeypatch):
    from app.supply_stud import backend
    config,layout=setup();row=config['blocks'][0]
    entry=next(s for s in layout['slots'] if (s['color'],s['brick_type'],s['slot'])==(row['color'],row['brick_type'],row['slot']))
    entry.update(min_area_px=250,short_side_px=[25,60],long_side_px=[28,63],aspect_range=[1,1.6])
    seen=[]
    def detect(frame,settings):
        seen.append(settings['slots'][0])
        return [dict(success=False,reason='TEST_NO_OUTLINE')],None
    monkeypatch.setattr(backend,'detect',detect)
    observe(np.zeros((480,640,3),np.uint8),layout,row,1)
    assert seen[0]['min_area_px']==250 and seen[0]['aspect_range']==[1,1.6]
