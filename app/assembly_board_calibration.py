"""수동 체결 교시의 방향별 affine TCP 변환. 장치 명령은 발행하지 않는다."""
from hashlib import sha256
import json
import math
from pathlib import Path
import warnings

import numpy as np
from scipy.spatial.transform import Rotation


def load_board_calibration(path):
    path=Path(path)
    raw=path.read_bytes();data=json.loads(raw)
    if (data.get('sample_kind')!='OPERATOR_TAUGHT_READ_ONLY' or
            data.get('tcp')!='GripperDA_v4' or data.get('tool')!='ToolWeight0'):
        raise ValueError('ACTUAL_BOARD_TEACHING_WITH_MATCHING_TCP_TOOL_REQUIRED')
    records=data.get('records',{})
    expected_ids=set();fits={}
    for kind in ('2x3x1','1x2x1'):
        for angle in (0,90):
            w,h=map(int,kind.split('x')[:2])
            if angle==90:w,h=h,w
            rows=[]
            for x,y in ((0,0),(24-w,0),(0,24-h),(24-w,24-h)):
                key=f'assembly/geometry/{kind}/{angle}/1/xy{x}_{y}'
                expected_ids.add(key);row=records.get(key)
                if row is None:raise ValueError('MISSING_BOARD_TEACHING:'+key)
                pose=row.get('tcp_pose_mm_zyz_deg',[])
                samples=row.get('receipt',{}).get('samples',[])
                if (row.get('case_id')!=key or row.get('brick_type')!=kind or
                        row.get('orientation_deg')!=angle or row.get('layer')!=1 or
                        row.get('planner_xy')!=[x,y] or row.get('operator_confirmed') is not True or
                        row.get('source')!='READ_ONLY_DEVICE_QUERY' or
                        row.get('receipt',{}).get('physical_commands')!=0 or len(samples)<3 or
                        len(pose)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in pose) or
                        pose!=samples[-1].get('posx') or
                        any(s.get('tcp')!='GripperDA_v4' or s.get('tool')!='ToolWeight0' or
                            s.get('motion_status')!=0 or s.get('gripper_status')!=2 or
                            len(s.get('velx',[]))!=6 or
                            any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>.01
                                for v in s.get('velx',[])) for s in samples)):
                    raise ValueError('INVALID_BOARD_TEACHING:'+key)
                rows.append(row)
            design=np.array([[1.,*r['planner_xy']] for r in rows])
            positions=np.array([r['tcp_pose_mm_zyz_deg'][:3] for r in rows])
            coefficients,_,rank,_=np.linalg.lstsq(design,positions,rcond=None)
            if rank!=3:raise ValueError('DEGENERATE_BOARD_TEACHING')
            # 회전으로 평균하여 ±180°의 Euler 표기 차이를 실제 회전 차이로 취급하지 않는다.
            rotations=Rotation.from_euler('ZYZ',[r['tcp_pose_mm_zyz_deg'][3:] for r in rows],degrees=True)
            mean=rotations.mean()
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                abc=mean.as_euler('ZYZ',degrees=True).tolist()
            fits[f'{kind}/{angle}']=dict(origin_xyz_mm=coefficients[0].tolist(),
                x_step_xyz_mm=coefficients[1].tolist(),y_step_xyz_mm=coefficients[2].tolist(),
                tcp_zyz_deg=abc,source_case_ids=[r['case_id'] for r in rows],
                fit_residual_xyz_mm=(design@coefficients-positions).tolist(),
                max_fit_residual_mm=float(np.linalg.norm(design@coefficients-positions,axis=1).max()),
                max_orientation_deviation_deg=float(np.rad2deg((mean.inv()*rotations).magnitude()).max()))
    if set(records)!=expected_ids:raise ValueError('UNEXPECTED_BOARD_TEACHING_CASES')
    return dict(source_ref=str(path.resolve()),source_sha256=sha256(raw).hexdigest(),
                coordinate_reference='MIN_OCCUPIED_STUD',model='FOUR_CORNER_AFFINE_XYZ_MEAN_ROTATION',
                fits=fits,execution_allowed=False)


def board_target_pose(calibration,block,layers):
    kind=block['brick_type'];angle=block['orientation_deg']
    fit=calibration['fits'][f'{kind}/{angle}']
    w,h=map(int,kind.split('x')[:2])
    if angle==90:w,h=h,w
    x,y,layer=block['x'],block['y'],block['layer']
    if (type(x) is not int or type(y) is not int or type(layer) is not int or
            not 0<=x<=24-w or not 0<=y<=24-h or layer not in layers):
        raise ValueError('BOARD_TARGET_OUT_OF_RANGE')
    xyz=[fit['origin_xyz_mm'][j]+x*fit['x_step_xyz_mm'][j]+y*fit['y_step_xyz_mm'][j]
         for j in range(3)]
    # 1층 TCP의 판 위치 변화를 유지하고, 높은 층은 기존 실측 층간 Z 차이만 더한다.
    xyz[2]+=layers[layer]['sample']['posx'][2]-layers[1]['sample']['posx'][2]
    return xyz+fit['tcp_zyz_deg']
