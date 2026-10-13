from copy import deepcopy
import json
from pathlib import Path
from queue import Queue
import time
import subprocess
import sys
import pytest
from app.robot_teaching import capture, record_cases, teaching_cases, validate_receipt


def receipt():
    s=dict(posx=[1.,2.,3.,0.,180.,0.],posj=[0.]*6,velx=[0.]*6,motion_status=0,
           tcp='GripperDA_v4',tool='ToolWeight0',gripper_status=2,gripper_width_mm=35.)
    return dict(captured_unix_s=time.time(),physical_commands=0,samples=[deepcopy(s) for _ in range(3)])


def test_all_slot_types_and_optional_geometry_cases():
    cases=teaching_cases()
    assert len(cases)==15 and len({c['case_id'] for c in cases})==15
    assert [(c['color'],c['brick_type']) for c in cases[::3]]==[
        ('yellow','2x2x1'),('yellow','2x3x1'),('blue','2x2x1'),('blue','2x3x1'),('red','1x2x1')]
    for start in range(0,15,3):
        assert [c['slot_index'] for c in cases[start:start+3]]==[1,3,6]
    assert len(teaching_cases('assembly'))==40
    assert len(teaching_cases('all'))==59


def test_enter_records_and_restart_skips_saved_cases_preserving_raw_receipt(tmp_path):
    cases=teaching_cases()[:2];output=tmp_path/'teaching.json';calls=[]
    def read():calls.append(True);return receipt()
    replies=iter(['','q'])
    state=record_cases(cases,output,read,prompt=lambda _:next(replies),emit=lambda _:None)
    assert len(state['records'])==1 and len(calls)==1
    before=output.with_suffix('.jsonl').read_text()
    state=record_cases(cases,output,read,prompt=lambda _:'',emit=lambda _:None)
    assert len(state['records'])==2 and len(calls)==2
    assert output.with_suffix('.jsonl').read_text().startswith(before)
    assert not state['execution_allowed']
    assert next(iter(state['records'].values()))['receipt']['physical_commands']==0
    with pytest.raises(ValueError,match='모의'):
        record_cases(cases,output,read,mock=True)


def test_skip_and_quit_never_query_robot(tmp_path):
    responses=iter(['s','q'])
    record_cases(teaching_cases(),tmp_path/'x.json',lambda:pytest.fail('device queried'),
                 prompt=lambda _:next(responses),emit=lambda _:None)
    assert not (tmp_path/'x.json').exists()


@pytest.mark.parametrize('kind',['tcp','tool','moving','stale','command','nan'])
def test_wrong_or_moving_receipt_never_becomes_teaching(kind):
    r=receipt()
    if kind=='tcp':r['samples'][0]['tcp']='old'
    if kind=='tool':r['samples'][0]['tool']='old'
    if kind=='moving':r['samples'][0]['velx'][0]=1.
    if kind=='stale':r['captured_unix_s']-=10
    if kind=='command':r['physical_commands']=1
    if kind=='nan':r['samples'][0]['posx'][0]=float('nan')
    with pytest.raises(ValueError):validate_receipt(r)


def test_capture_sends_only_read_state():
    class Robot:
        def __init__(self):self.commands=[];self.q=Queue();self.q.put(dict(event='STATE_SNAPSHOT',data=receipt()))
        def send(self,command):self.commands.append(command)
        def receive(self,timeout):return self.q.get(timeout=timeout)
    r=Robot();capture(r)
    assert r.commands==['READ_STATE']


def test_colour_independent_board_corners_cover_both_sizes_and_angles(tmp_path):
    from app.robot_teaching import board_corner_cases
    cases=board_corner_cases()
    expected={('2x3x1',0):[(0,0),(22,0),(0,21),(22,21)],
              ('2x3x1',90):[(0,0),(21,0),(0,22),(21,22)],
              ('1x2x1',0):[(0,0),(23,0),(0,22),(23,22)],
              ('1x2x1',90):[(0,0),(22,0),(0,23),(22,23)]}
    assert len(cases)==len({c['case_id'] for c in cases})==16
    for key,points in expected.items():
        rows=[c for c in cases if (c['brick_type'],c['orientation_deg'])==key]
        assert [tuple(c['planner_xy']) for c in rows]==points
        for c in rows:
            assert 'color' not in c and c['layer']==1
            w,d=map(int,c['brick_type'].split('x')[:2])
            if c['orientation_deg']==90:w,d=d,w
            x,y=c['planner_xy']
            assert x+w<=24 and y+d<=24
        assert f'점유 끝 (23,23)' in rows[-1]['instruction']
    path=tmp_path/'corners.json';calls=[]
    def read():calls.append(True);return receipt()
    state=record_cases(cases,path,read,prompt=lambda _:'',emit=lambda _:None)
    assert len(state['records'])==16 and len(calls)==16
    before=path.read_bytes()
    record_cases(cases,path,lambda:pytest.fail('repeat query'),prompt=lambda _:pytest.fail('repeat prompt'),emit=lambda _:None)
    assert path.read_bytes()==before
    assert all('color' not in r and r['receipt']['physical_commands']==0 for r in state['records'].values())


def test_board_corner_cli_lists_all_cases_without_device():
    command=[sys.executable,'-m','app.robot_teaching','--section','assembly','--board-corners','--list']
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.splitlines()[-1]=='16개 · 장치 연결 없음'
    assert 'assembly/geometry/2x3x1/0/1/xy22_21' in result.stdout
    assert 'assembly/geometry/1x2x1/90/1/xy22_23' in result.stdout


@pytest.mark.parametrize('extra',[['--section','supply'],['--case','assembly/blue/2x3x1/0/1'],['--planner-xy','0','0']])
def test_board_corner_cli_rejects_conflicting_selection_before_device(extra):
    result=subprocess.run([sys.executable,'-m','app.robot_teaching','--section','assembly',
                           '--board-corners',*extra,'--list'],text=True,capture_output=True)
    assert result.returncode==2 and '--board-corners는' in result.stderr


def test_selected_first_layer_six_stud_cases_keep_order_without_device():
    cases=['assembly/blue/2x3x1/90/1','assembly/blue/2x3x1/0/1',
           'assembly/yellow/2x3x1/90/1','assembly/yellow/2x3x1/0/1']
    command=[sys.executable,'-m','app.robot_teaching','--section','assembly','--list']
    for name in cases:command+=['--case',name]
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert [line.split(' · ')[0] for line in result.stdout.splitlines()[:-1]]==cases
    assert result.stdout.splitlines()[-1]=='4개 · 장치 연결 없음'
    result=subprocess.run(command+['--case','assembly/blue/2x3x1/90/6'],text=True,capture_output=True)
    assert result.returncode==2 and '해당 section에 없는 교시 항목' in result.stderr


def test_off_centre_assembly_point_is_displayed_and_saved_separately(tmp_path):
    command=[sys.executable,'-m','app.robot_teaching','--section','assembly',
             '--case','assembly/blue/2x3x1/90/1','--planner-xy','12','11']
    result=subprocess.run(command+['--list'],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.startswith('assembly/blue/2x3x1/90/1/xy12_11 · ')
    assert 'Planner (12,11)' in result.stdout and '1개 · 장치 연결 없음' in result.stdout
    path=tmp_path/'axis.json'
    result=subprocess.run(command+['--mock','--output',str(path)],input='\n',text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    saved=json.loads(path.read_text())
    row=saved['records']['assembly/blue/2x3x1/90/1/xy12_11']
    assert row['planner_xy']==[12,11] and row['orientation_deg']==90 and row['layer']==1
    assert row['receipt']['physical_commands']==0 and row['source']=='SYNTHETIC'


@pytest.mark.parametrize('section,xy',[('supply',[12,11]),('assembly',[-1,11]),
                                      ('assembly',[22,11]),('assembly',[12,23])])
def test_invalid_assembly_point_rejected_before_device(section,xy):
    command=[sys.executable,'-m','app.robot_teaching','--section',section,
             '--planner-xy',*map(str,xy),'--list']
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==2
    assert '--planner-xy는 조립판 교시' in result.stderr or '점유 영역' in result.stderr


def test_assembly_teaching_keeps_historical_six_dof_poses_and_rejects_missing_or_unheld(tmp_path):
    from app.robot_teaching import assembly_teaching
    data=dict(sample_kind='OPERATOR_TAUGHT_READ_ONLY',tcp='GripperDA_v4',tool='ToolWeight0',records={})
    for color in ('blue','yellow'):
        for angle in (0,90):
            case=next(c for c in teaching_cases('assembly') if c['case_id']==f'assembly/{color}/2x3x1/{angle}/1')
            r=receipt();r['captured_unix_s']-=86400
            point=[471.,84.,15. if angle==90 else 14.,136.,-179.,-132.]
            for sample in r['samples']:sample['posx']=list(point)
            data['records'][case['case_id']]=dict(case,source='READ_ONLY_DEVICE_QUERY',
                operator_confirmed=True,receipt=r,tcp_pose_mm_zyz_deg=point)
    path=tmp_path/'assembly.json';path.write_text(json.dumps(data));before=path.read_bytes()
    loaded=assembly_teaching(path)
    assert loaded[('blue',90)]==[471.,84.,15.,136.,-179.,-132.]
    assert path.read_bytes()==before
    data['records']['assembly/blue/2x3x1/90/1']['receipt']['samples'][0]['gripper_status']=0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='INVALID_ASSEMBLY_TEACHING'):assembly_teaching(path)
    data['records'].pop('assembly/blue/2x3x1/90/1');path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='MISSING_ASSEMBLY_TEACHING'):assembly_teaching(path)


def test_teaching_interpolates_all_slots_preserves_measured_poses_and_rotations(tmp_path):
    from app.robot_teaching import GROUPS,supply_teaching
    from scipy.spatial.transform import Rotation
    samples=[]
    for c in teaching_cases('supply'):
        i=c['slot_index'];r=receipt()
        pose=[i*10.,i*2.,50.+i,179. if i==1 else -179.,-178.,120.]
        for sample in r['samples']:sample['posx']=list(pose)
        samples.append(r)
    iterator=iter(samples);path=tmp_path/'supply.json'
    saved=record_cases(teaching_cases('supply'),path,lambda:next(iterator),prompt=lambda _:'',emit=lambda _:None)
    poses=supply_teaching(path)
    assert len(poses)==30
    for color,kind in GROUPS:
        for slot in (1,3,6):
            assert poses[f'{color}_{kind}_{slot:02d}']==saved['records'][f'supply/{color}/{kind}/{slot}']['tcp_pose_mm_zyz_deg']
        for slot in (2,4,5):
            assert poses[f'{color}_{kind}_{slot:02d}'][:3]==[slot*10.,slot*2.,50.+slot]
        first=Rotation.from_euler('ZYZ',poses[f'{color}_{kind}_01'][3:],degrees=True)
        middle=Rotation.from_euler('ZYZ',poses[f'{color}_{kind}_02'][3:],degrees=True)
        assert (first.inv()*middle).magnitude()<.02
    saved['records'].pop('supply/red/1x2x1/6')
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError,match='MISSING_SUPPLY_TEACHING'):
        supply_teaching(path)
