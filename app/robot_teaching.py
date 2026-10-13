"""Enter로 현재 TCP를 기록하는 수동 교시 도구. 이동/개폐 명령 없음."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from queue import Empty
import time

from app.robot_process import RobotProcess

GROUPS = [('yellow','2x2x1'), ('yellow','2x3x1'), ('blue','2x2x1'),
          ('blue','2x3x1'), ('red','1x2x1')]


def teaching_cases(section='supply'):
    cases = []
    if section in ('supply','all'):
        for color, kind in GROUPS:
            for slot in (1,3,6):
                cases.append(dict(case_id=f'supply/{color}/{kind}/{slot}', section='supply',
                    color=color, brick_type=kind, slot_index=slot,
                    instruction=f'{color} {kind} {slot}번 슬롯: 블록을 공급판에 놓고 양쪽 2점 면 중앙에 수동 정렬. 패드 하단은 블록 밑면+5mm. 그리퍼 개방/파지는 직접 조작합니다.'))
    if section in ('assembly','all'):
        for color, kind in GROUPS:
            for angle in ((0,) if kind=='2x2x1' else (0,90)):
                for layer in range(1,6):
                    cases.append(dict(case_id=f'assembly/{color}/{kind}/{angle}/{layer}',
                        section='assembly', color=color, brick_type=kind, orientation_deg=angle,
                        layer=layer, planner_xy=[11,11],
                        instruction=f'{color} {kind} 방향 {angle}° · {layer}층 · Planner (11,11): 사람이 완전 체결한 블록을 정상 파지 높이로 수동 정렬합니다. 자동 누르기를 수행하지 않습니다.'))
    if section in ('handover','all'):
        for name, instruction in [('tray','전달판에 블록 밑면이 닿는 놓기 TCP를 수동 정렬합니다.'),
            ('receive_wait','블록을 잡은 채 전달판 상공의 인계 대기 TCP에 수동 정렬합니다. 손은 아직 넣지 않습니다.')]:
            cases.append(dict(case_id='handover/'+name,section='handover',instruction=instruction))
    if section in ('route','all'):
        for name in ('supply_transit','body_bypass'):
            cases.append(dict(case_id='route/'+name,section='route',
                instruction=name+' 경유점의 안전한 상공 TCP로 수동 이동한 뒤 정지합니다.'))
    return cases


def board_corner_cases():
    """색상과 무관한 1층 네 모서리. 좌표는 최소 점유 stud다."""
    cases=[]
    for kind,studs in (('2x3x1',6),('1x2x1',2)):
        for angle in (0,90):
            width,depth=map(int,kind.split('x')[:2])
            if angle==90:width,depth=depth,width
            points=((0,0),(24-width,0),(0,24-depth),(24-width,24-depth))
            long_axis='Y' if angle==0 else 'X'
            for x,y in points:
                cases.append(dict(case_id=f'assembly/geometry/{kind}/{angle}/1/xy{x}_{y}',
                    section='assembly',brick_type=kind,orientation_deg=angle,layer=1,
                    planner_xy=[x,y],
                    instruction=f'{studs}점 방향 {angle}° · 긴 변 {long_axis}방향 · 1층 · Planner ({x},{y}): '
                    f'원점에 가장 가까운 점유 돌기를 기준점으로 삼습니다. 점유 끝 ({x+width-1},{y+depth-1}). '
                    '완전히 체결한 블록을 파지하고 패드 하단 밑면+5mm로 수동 정렬합니다. '
                    'TCP GripperDA_v4 / Tool ToolWeight0. 좌표만 조회하며 자동 이동·개폐·누르기를 하지 않습니다.'))
    return cases


def supply_teaching(path):
    """실측점은 보존하고 미측정 슬롯만 인접 교시점 사이에서 보간한다."""
    import math
    from scipy.spatial.transform import Rotation, Slerp
    path = Path(path)
    data = json.loads(path.read_text())
    if data.get('sample_kind') != 'OPERATOR_TAUGHT_READ_ONLY' or data.get('tcp') != 'GripperDA_v4' or data.get('tool') != 'ToolWeight0':
        raise ValueError('ACTUAL_SUPPLY_TEACHING_WITH_MATCHING_TCP_TOOL_REQUIRED')
    poses = {}
    for color, kind in GROUPS:
        anchors = {}
        for slot in (1,3,6):
            key = f'supply/{color}/{kind}/{slot}'
            row = data['records'].get(key)
            if row is None:
                raise ValueError('MISSING_SUPPLY_TEACHING:'+key)
            point = row.get('tcp_pose_mm_zyz_deg', [])
            if (len(point) != 6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point)
                    or row.get('source') != 'READ_ONLY_DEVICE_QUERY' or row.get('operator_confirmed') is not True
                    or row.get('receipt',{}).get('physical_commands') != 0
                    or (row.get('color'),row.get('brick_type'),row.get('slot_index')) != (color,kind,slot)):
                raise ValueError('INVALID_SUPPLY_TEACHING:'+key)
            anchors[slot] = list(point)
        for slot in range(1,7):
            if slot in anchors:
                poses[f'{color}_{kind}_{slot:02d}'] = anchors[slot]
                continue
            left, right = (1,3) if slot < 3 else (3,6)
            fraction = (slot-left)/(right-left)
            start, end = anchors[left], anchors[right]
            xyz = [a+fraction*(b-a) for a,b in zip(start[:3],end[:3])]
            rotations = Rotation.from_euler('ZYZ',[start[3:],end[3:]],degrees=True)
            abc = Slerp([0.,1.],rotations)([fraction]).as_euler('ZYZ',degrees=True)[0].tolist()
            poses[f'{color}_{kind}_{slot:02d}'] = xyz+abc
    return poses


def assembly_teaching(path):
    """완전 체결한 6점의 색상/방향별 1층 TCP를 그대로 읽는다."""
    import math
    data=json.loads(Path(path).read_text())
    if (data.get('sample_kind')!='OPERATOR_TAUGHT_READ_ONLY' or
            data.get('tcp')!='GripperDA_v4' or data.get('tool')!='ToolWeight0'):
        raise ValueError('ACTUAL_ASSEMBLY_TEACHING_WITH_MATCHING_TCP_TOOL_REQUIRED')
    result={}
    for color in ('blue','yellow'):
        for angle in (0,90):
            key=f'assembly/{color}/2x3x1/{angle}/1'
            row=data['records'].get(key)
            if row is None:raise ValueError('MISSING_ASSEMBLY_TEACHING:'+key)
            point=row.get('tcp_pose_mm_zyz_deg',[])
            samples=row.get('receipt',{}).get('samples',[])
            if (len(point)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point)
                    or row.get('source')!='READ_ONLY_DEVICE_QUERY' or row.get('operator_confirmed') is not True
                    or row.get('receipt',{}).get('physical_commands')!=0 or len(samples)<3
                    or point!=samples[-1].get('posx')
                    or (row.get('color'),row.get('brick_type'),row.get('orientation_deg'),row.get('layer'))!=(color,'2x3x1',angle,1)
                    or row.get('planner_xy')!=[11,11]
                    or any(s.get('tcp')!='GripperDA_v4' or s.get('tool')!='ToolWeight0'
                           or s.get('motion_status')!=0 or s.get('gripper_status')!=2
                           or max(map(abs,s.get('velx',[1.])))>.01 for s in samples)):
                raise ValueError('INVALID_ASSEMBLY_TEACHING:'+key)
            result[(color,angle)]=list(point)
    return result


def validate_receipt(receipt):
    samples = receipt.get('samples', [])
    if receipt.get('physical_commands') != 0 or len(samples) < 3:
        raise ValueError('무이동 조회 3개 표본이 필요합니다.')
    if not 0 <= time.time()-receipt.get('captured_unix_s',0) <= 3:
        raise ValueError('오래된 조회 결과입니다. 다시 기록해주세요.')
    for sample in samples:
        if sample.get('tcp') != 'GripperDA_v4' or sample.get('tool') != 'ToolWeight0':
            raise ValueError('TCP GripperDA_v4 / Tool ToolWeight0 선택을 확인해주세요.')
        if sample.get('motion_status') != 0 or max(map(abs,sample.get('velx',[1.]))) > .01:
            raise ValueError('로봇이 정지한 뒤 다시 기록해주세요.')
        import math
        pose = sample.get('posx', [])
        if len(pose) != 6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in pose):
            raise ValueError('TCP 좌표 형식이 잘못되었습니다.')
    if any(sum((a-b)**2 for a,b in zip(samples[0]['posx'][:3],s['posx'][:3])) > .1**2 for s in samples[1:]):
        raise ValueError('조회 중 위치가 변했습니다. 완전히 정지한 뒤 다시 기록해주세요.')
    return samples[-1]


def capture(robot):
    robot.send('READ_STATE')
    deadline = time.monotonic()+20
    while time.monotonic() < deadline:
        try:
            event = robot.receive(timeout=.2)
        except Empty:
            continue
        if event['event']=='STATE_SNAPSHOT':
            validate_receipt(event['data'])
            return event['data']
        if event['event'] in ('COMMAND_REJECTED','CHANNEL_ERROR','PROCESS_EXITED'):
            raise RuntimeError(event['data'].get('reason',event['event']))
    raise TimeoutError('조회 응답이 없습니다. 드라이버/연결 상태를 확인해주세요.')


def record_cases(cases, output, capture_state, *, prompt=input, emit=print, mock=False):
    output = Path(output)
    state = json.loads(output.read_text()) if output.is_file() else dict(
        sample_kind='SYNTHETIC' if mock else 'OPERATOR_TAUGHT_READ_ONLY',
        execution_allowed=False, tcp='GripperDA_v4',tool='ToolWeight0',records={})
    if state['sample_kind'] != ('SYNTHETIC' if mock else 'OPERATOR_TAUGHT_READ_ONLY'):
        raise ValueError('모의 기록과 실물 기록은 서로 다른 파일에 저장해주세요.')
    output.parent.mkdir(parents=True,exist_ok=True)
    for number, case in enumerate(cases,1):
        key=case['case_id']
        if key in state['records']:
            emit(f'[{number}/{len(cases)}] 기록 있음: {key}'); continue
        while True:
            emit(f"\n[{number}/{len(cases)}] {key}\n{case['instruction']}")
            answer=prompt('정렬 후 Enter=기록 / s=이번 항목 건너뛰기 / q=종료: ').strip().lower()
            if answer=='q': return state
            if answer=='s': break
            if answer: continue
            try:
                receipt=capture_state(); sample=validate_receipt(receipt)
            except (RuntimeError,ValueError,TimeoutError) as error:
                emit('미기록: '+str(error)); continue
            record=dict(deepcopy(case), captured_unix_s=receipt['captured_unix_s'],
                tcp_pose_mm_zyz_deg=sample['posx'],robot_sample=sample,receipt=receipt,
                source='SYNTHETIC' if mock else 'READ_ONLY_DEVICE_QUERY',
                operator_confirmed=True,execution_allowed=False)
            with output.with_suffix('.jsonl').open('a') as f:
                f.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
            state['records'][key]=record
            temporary=output.with_suffix('.tmp')
            temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
            temporary.replace(output)
            emit('저장: '+str(record['tcp_pose_mm_zyz_deg'])+'\n파일: '+str(output.resolve()))
            break
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-root',type=Path)
    parser.add_argument('--section',choices=('supply','assembly','handover','route','all'),default='supply')
    parser.add_argument('--output',type=Path,default=Path('logs/teaching-20261012/supply.json'))
    parser.add_argument('--case',action='append',help='이 항목만 교시. 여러 번 지정하면 지정한 순서로 진행')
    parser.add_argument('--planner-xy',type=int,nargs=2,metavar=('X','Y'),
                        help='조립판 최소 점유 stud 좌표. 기본 (11,11), 조립판 교시에만 사용')
    parser.add_argument('--board-corners',action='store_true',
                        help='색상 구분 없이 6점/2점 × 0°/90°의 1층 네 모서리 교시')
    parser.add_argument('--list',action='store_true',help='항목 목록만 출력. 장치 연결 없음')
    parser.add_argument('--mock',action='store_true',help='가짜 조회로 Enter/저장/재시작만 연습')
    args=parser.parse_args();cases=teaching_cases(args.section)
    if args.board_corners:
        if args.section!='assembly' or args.case or args.planner_xy is not None:
            parser.error('--board-corners는 --section assembly에서 --case/--planner-xy 없이 사용합니다.')
        cases=board_corner_cases()
    if args.case:
        by_id={c['case_id']:c for c in cases}
        unknown=[name for name in args.case if name not in by_id]
        if unknown:parser.error('해당 section에 없는 교시 항목: '+', '.join(unknown))
        cases=[by_id[name] for name in args.case]
    if args.planner_xy is not None:
        if any(c['section']!='assembly' for c in cases):
            parser.error('--planner-xy는 조립판 교시에만 사용합니다.')
        x,y=args.planner_xy
        for c in cases:
            width,depth=map(int,c['brick_type'].split('x')[:2])
            if c['orientation_deg']==90:width,depth=depth,width
            if not (0<=x and x+width<=24 and 0<=y and y+depth<=24):
                parser.error('교시 블록의 점유 영역이 24×24 조립판 밖입니다.')
            c['planner_xy']=[x,y]
            c['case_id']+=f'/xy{x}_{y}'
            c['instruction']=c['instruction'].replace('Planner (11,11)',f'Planner ({x},{y})')
    if args.list:
        for c in cases: print(c['case_id']+' · '+c['instruction'])
        print(str(len(cases))+'개 · 장치 연결 없음'); return 0
    if args.mock:
        def fake():
            sample=dict(posx=[1.,2.,3.,0.,180.,0.],posj=[0.]*6,velx=[0.]*6,
                motion_status=0,tcp='GripperDA_v4',tool='ToolWeight0',gripper_status=0,gripper_width_mm=55.)
            return dict(samples=[deepcopy(sample) for _ in range(3)],captured_unix_s=time.time(),physical_commands=0)
        record_cases(cases,args.output,fake,mock=True); return 0
    if args.robot_root is None: parser.error('실물 조회에는 --robot-root가 필요합니다.')
    # Only READ_STATE reaches the D process. It never receives EXECUTE/GRIP/STOP.
    with RobotProcess(args.robot_root,mode='REAL',config=args.robot_root/'interfaces/assembly_contact_trial.json') as robot:
        record_cases(cases,args.output,lambda:capture(robot))
    return 0


if __name__=='__main__': raise SystemExit(main())
