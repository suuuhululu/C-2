import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.workpiece_calibration import build_top_plan,build_side_plan,MeasurementError
from c2_process.robot_adapter import posx_to_pose
from c2_process.workpiece_real_trial import check_trial_scene


def test_recorded_start_and_reference_plans_pass_model():
    c=json.loads((Path(__file__).resolve().parents[1]/'config/workpiece_real_trial_0921.json').read_text());w=c['workcell']
    current=dict(posx=[427.127258,155.9008,214.7045,10.39775,-179.99992,10.397785])
    top=build_top_plan(w,posx_to_pose(current['posx'],w['tool_offset_m']))
    assert check_trial_scene(top,w,current)['path_checked']
    assert check_trial_scene(build_side_plan(w,.23470465),w,current)['probe_envelopes_checked']


def test_low_cross_candle_move_is_rejected():
    c=json.loads((Path(__file__).resolve().parents[1]/'config/workpiece_real_trial_0921.json').read_text());w=c['workcell']
    current=dict(posx=[427.127258,155.9008,214.7045,0,-180,0])
    plan=build_side_plan(w,.23470465)
    plan[0]['target_pose']=posx_to_pose([426.24,-155.,214.7,0,-180,0],w['tool_offset_m'])
    with pytest.raises(MeasurementError):check_trial_scene(plan,w,current)
