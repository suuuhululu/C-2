from copy import deepcopy
import json
import math
import time

import pytest
from scipy.spatial.transform import Rotation

from app.assembly_board_calibration import load_board_calibration, board_target_pose
from app.robot_teaching import board_corner_cases,record_cases


def source(tmp_path):
    poses=[]
    for c in board_corner_cases():
        x,y=c['planner_xy'];angle=c['orientation_deg']
        pose=[100+16*x+.05*y,50-.04*x+16*y,15+.01*x-.02*y,179.9,180.,179.9-angle]
        sample=dict(posx=pose,velx=[0.]*6,motion_status=0,tcp='GripperDA_v4',tool='ToolWeight0',gripper_status=2)
        poses.append(dict(captured_unix_s=time.time(),physical_commands=0,samples=[deepcopy(sample) for _ in range(3)]))
    iterator=iter(poses);path=tmp_path/'board.json'
    record_cases(board_corner_cases(),path,lambda:next(iterator),prompt=lambda _:'',emit=lambda _:None)
    return path


def test_affine_recovers_independent_xyz_and_rotation_without_changing_source(tmp_path):
    path=source(tmp_path);before=path.read_bytes();cal=load_board_calibration(path)
    assert path.read_bytes()==before and cal['execution_allowed'] is False
    assert len(cal['fits'])==4
    layers={1:dict(sample=dict(posx=[0,0,15])),5:dict(sample=dict(posx=[0,0,89.676]))}
    for kind in ('2x3x1','1x2x1'):
        for angle in (0,90):
            fit=cal['fits'][f'{kind}/{angle}']
            assert fit['max_fit_residual_mm']<1e-9
            b=dict(brick_type=kind,orientation_deg=angle,x=7,y=9,layer=5)
            p=board_target_pose(cal,b,layers)
            assert p[:3]==pytest.approx([100+16*7+.05*9,50-.04*7+16*9,15+.01*7-.02*9+74.676])
            expected=Rotation.from_euler('ZYZ',[179.9,180,179.9-angle],degrees=True)
            assert (expected.inv()*Rotation.from_euler('ZYZ',p[3:],degrees=True)).magnitude()<1e-9
    with pytest.raises(ValueError,match='OUT_OF_RANGE'):
        board_target_pose(cal,dict(brick_type='2x3x1',orientation_deg=0,x=23,y=21,layer=1),layers)


def test_four_corner_residual_and_source_pose_preservation(tmp_path):
    # 개인 교시 로그 없이도 비평면 측정 오차의 잔차와 원자료 보존을 검사한다.
    path=source(tmp_path);raw=json.loads(path.read_text())
    for i,row in enumerate(raw['records'].values()):
        row['tcp_pose_mm_zyz_deg'][0]+=(.3,-.3,-.3,.3)[i%4]
        for sample in row['receipt']['samples']:
            sample['posx']=deepcopy(row['tcp_pose_mm_zyz_deg'])
    path.write_text(json.dumps(raw));before=path.read_bytes();cal=load_board_calibration(path)
    assert len(raw['records'])==16 and path.read_bytes()==before
    for fit in cal['fits'].values():
        assert fit['max_fit_residual_mm']==pytest.approx(.3)
        assert fit['max_orientation_deviation_deg']<1e-9
        for key in fit['source_case_ids']:
            r=raw['records'][key];x,y=r['planner_xy']
            predicted=[fit['origin_xyz_mm'][j]+x*fit['x_step_xyz_mm'][j]+y*fit['y_step_xyz_mm'][j] for j in range(3)]
            assert math.dist(predicted,r['tcp_pose_mm_zyz_deg'][:3])<=fit['max_fit_residual_mm']+1e-9


@pytest.mark.parametrize('failure',('missing','label','grip','moving','command','synthetic'))
def test_incomplete_or_invalid_measurement_never_becomes_calibration(tmp_path,failure):
    path=source(tmp_path);d=json.loads(path.read_text());key=next(iter(d['records']));r=d['records'][key]
    if failure=='missing':d['records'].pop(key)
    if failure=='label':r['orientation_deg']=90
    if failure=='grip':r['receipt']['samples'][0]['gripper_status']=0
    if failure=='moving':r['receipt']['samples'][0]['velx'][0]=1
    if failure=='command':r['receipt']['physical_commands']=1
    if failure=='synthetic':d['sample_kind']='SYNTHETIC'
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError):load_board_calibration(path)
