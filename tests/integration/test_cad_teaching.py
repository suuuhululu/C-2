"""실물 교시 자료를 사용한 경로/설정 검사. Robot 프로세스/장치는 생성하지 않는다."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from app.cad_real_trial import prepare,preview_routes
from app.robot_teaching import GROUPS,supply_teaching

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
TEACHING=Path(__file__).resolve().parents[2]/'logs/teaching-20261012/supply.json'
if not TEACHING.is_file():TEACHING=ROOT/'fixtures/teaching_sources/operator_supply.json'
pytestmark=pytest.mark.skipif(not TEACHING.is_file() or not (ROOT/'scripts/robot_integration_runtime.py').is_file(),reason='recorded teaching and C2_ROBOT_ROOT required')


def test_all_taught_and_interpolated_slots_create_matching_a_d_documents(tmp_path):
    poses=supply_teaching(TEACHING)
    records=json.loads(TEACHING.read_text())['records']
    documents=[]
    for color,kind in GROUPS:
        for angle in ((0,) if kind=='2x2x1' else (0,90)):
            design=dict(design_version=1,blocks=[dict(brick_type=kind,color=color,x=11,y=11,layer=1,orientation_deg=angle)])
            prepared=prepare(design,ROOT)
            assert prepared['inputs']['supply_teaching_ref']==str(TEACHING.resolve())
            for slot in range(1,7):
                sample=deepcopy(prepared);sample['preview'][0]['slot']=slot
                d=preview_routes(sample)[0]
                settings=next(iter(d['d_profile']['steps'].values()))
                # A/D끼리의 일치뿐 아니라 실물 시험에서 확인한 공급 파지 기준을 검사한다.
                expected_turn = (0 if kind=='2x2x1' or (kind=='2x3x1' and angle==0)
                                 or (kind=='1x2x1' and angle==90) else 90)
                assert settings['turn_base_z_deg']==expected_turn
                # 노랑/파랑 6점 90°의 사용자 실물 보정만 추가하며 기존 회전 보정은 중복하지 않는다.
                offset_x=1.5 if kind=='2x3x1' and angle==90 else 0.
                assert d['correction_base_xy_mm']==[offset_x,0.]
                assert settings['pickup_pose']==pytest.approx(poses[f'{color}_{kind}_{slot:02d}'],abs=1e-10,rel=0)
                if slot in (1,3,6):
                    assert settings['pickup_pose']==pytest.approx(records[f'supply/{color}/{kind}/{slot}']['tcp_pose_mm_zyz_deg'],abs=1e-10,rel=0)
                assert d['d_profile']['supply_pose_basis']==('MEASURED' if slot in (1,3,6) else 'INTERPOLATED')
                assert not d['motion']['execution_allowed'] and not d['d_profile']['physical_route_reviewed']
                documents.append(d)
    assert len(documents)==48
    code='''
import json,sys
from app.assembly_step_bridge import build_plan
from app.integration_motion_binding import verify_motion
from app.assembly_blend_trial import validate_route
for d in json.load(sys.stdin):
 p=build_plan(d['step'],d['d_profile'])
 verify_motion(d['motion']['motion_proposal'],p,d['d_profile'],d['robot_state'])
 profile=d['d_profile'];s=p['settings'];h=profile['clearance_z_mm'];abc=s['pickup_pose'][3:]
 route=[[*xy,h,*abc] for xy in (profile['place_pose'][:2],profile['body_bypass_xy_mm'],profile['supply_transit_xy_mm'],s['pickup_pose'][:2])]
 validate_route(route[0],route[1:],40.)
 validate_route(route[-1],list(reversed(route[:-1])),40.)
print('48 A/D routes verified; no driver/device constructed')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,input=json.dumps(documents),text=True,capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='48 A/D routes verified; no driver/device constructed'


@pytest.mark.parametrize('color,angle',[(c,a) for c in ('blue','yellow') for a in (0,90)])
@pytest.mark.parametrize('layer',range(1,6))
def test_six_point_teaching_anchors_xy_z_and_actual_a_d_orientation(color,angle,layer):
    from app.cad_trial import measured_inputs,step_geometry
    from planning_trial.assembly_target import calculate_step_tcp
    inputs=measured_inputs(ROOT)
    # 이전 중앙 교시 소비 경로도 네 모서리 프로필이 없는 경우에 보존한다.
    inputs['board_calibration']=None
    source=json.loads(Path(inputs['assembly_teaching_ref']).read_text())
    taught=source['records'][f'assembly/{color}/2x3x1/{angle}/1']['tcp_pose_mm_zyz_deg']
    b=dict(brick_type='2x3x1',color=color,x=11,y=11,layer=layer,orientation_deg=angle)
    step=dict(step_id='S01',operation='PLACE',before=None,after=b,prerequisites=[],requires_delivery=True)
    action=dict(grip_axis='x' if angle==0 else 'y')
    frame,profile,_,correction=step_geometry(inputs,step,action,1)
    settings=next(iter(profile['steps'].values()))
    expected_z=taught[2]+inputs['layers'][layer]['sample']['posx'][2]-inputs['layers'][1]['sample']['posx'][2]
    offset_x=1.5 if angle==90 else 0.
    expected_xy=[taught[0]+offset_x,taught[1]]
    assert settings['reference_pose']==pytest.approx(expected_xy+[expected_z]+taught[3:])
    assert settings['assembly_tcp_zyz_deg']==taught[3:] and correction==[offset_x,0.]
    assert frame['calculation_profiles']['assembly']['grid_mapping']['planner_to_trial_xy']==[[1,0],[0,1]]
    target=calculate_step_tcp(step,profile=frame['calculation_profiles']['assembly'],grip_axis=action['grip_axis'])
    expected=expected_xy+[expected_z+20.1]+taught[3:]
    assert target['pre_contact_tcp']['xyz_mm_zyz_deg']==pytest.approx(expected)
    code='''
import json,sys
from app.integration_runtime import StepRuntime
from app.assembly_step_runner import assembly_target_pose
s,p,expected=json.load(sys.stdin)
rt=StepRuntime(None,None,lambda *a:None)
ops=rt.make_operations(dict(settings=s,mode='ROBOT_GRIP',assistance_kind='NONE'),p,'assembly')
actual=next(v[1] for op,v in ops if op=='move' and v[0]=='PRE_CONTACT')
assert actual==expected
assert rt.raw is None
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,
        input=json.dumps([settings,profile,expected]),text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    # 공통 +X 이동은 Base +X, +Y 이동은 Base +Y이며 가상 2x2 반 stud를 다시 더하지 않는다.
    for x,y,delta in [(12,11,[15.97326086956522,-.06173913043478052]),
                       (11,12,[.045000000000001705,15.949565217391301])]:
        moved=deepcopy(step);moved['after'].update(x=x,y=y)
        _,p,_,c=step_geometry(inputs,moved,action,1)
        actual=next(iter(p['steps'].values()))['reference_pose']
        assert actual[:2]==pytest.approx([expected_xy[j]+delta[j] for j in range(2)])
        assert actual[2:]==pytest.approx([expected_z]+taught[3:]) and c==[offset_x,0.]


@pytest.mark.parametrize('kind,color',[('2x3x1','blue'),('2x3x1','yellow'),('1x2x1','red')])
@pytest.mark.parametrize('angle',(0,90))
@pytest.mark.parametrize('layer',range(1,6))
def test_board_calibration_shared_by_actual_a_and_d(kind,color,angle,layer):
    from app.cad_trial import measured_inputs,step_geometry
    from app.assembly_board_calibration import board_target_pose
    from planning_trial.assembly_target import calculate_step_tcp
    inputs=measured_inputs(ROOT);cal=inputs['board_calibration']
    assert cal is not None
    original_inputs=deepcopy(inputs)
    w,h=map(int,kind.split('x')[:2])
    if angle==90:w,h=h,w
    documents=[]
    for x,y in ((0,0),(24-w,24-h),(11,11)):
        b=dict(brick_type=kind,color=color,x=x,y=y,layer=layer,orientation_deg=angle)
        step=dict(step_id='S01',operation='PLACE',before=None,after=b,prerequisites=[],requires_delivery=True)
        action=dict(grip_axis='x' if w==2 else 'y')
        frame,profile,_,correction=step_geometry(inputs,step,action,1)
        s=next(iter(profile['steps'].values()))
        pose=board_target_pose(cal,b,inputs['layers'])
        offset_x=1.5 if kind=='2x3x1' and angle==90 else 0.
        pose[0]+=offset_x
        assert s['reference_pose']==pytest.approx(pose) and correction==[offset_x,0.]
        repeated=step_geometry(inputs,step,action,1)
        assert repeated[0]==frame and repeated[1]==profile
        assert inputs==original_inputs
        assert profile['assembly_teaching_sha256']==cal['source_sha256']
        assert s['assembly_tcp_zyz_deg']==pose[3:]
        target=calculate_step_tcp(step,profile=frame['calculation_profiles']['assembly'],grip_axis=action['grip_axis'])
        expected=pose[:];expected[2]+=20.1
        assert target['pre_contact_tcp']['xyz_mm_zyz_deg']==pytest.approx(expected)
        documents.append([s,profile,expected])
    code='''
import json,sys
from app.integration_runtime import StepRuntime
from app.assembly_step_runner import assembly_target_pose
for s,p,expected in json.load(sys.stdin):
 rt=StepRuntime(None,None,lambda *a:None)
 ops=rt.make_operations(dict(settings=s,mode='ROBOT_GRIP',assistance_kind='NONE'),p,'assembly')
 assert next(v[1] for op,v in ops if op=='move' and v[0]=='PRE_CONTACT')==expected
 assert assembly_target_pose(s)==s['reference_pose']
 assert rt.raw is None
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,input=json.dumps(documents),
                          text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
