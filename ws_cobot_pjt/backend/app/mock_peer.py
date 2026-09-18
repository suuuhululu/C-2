"""모의 상대 노드. 이미지 변환·실행 알고리즘이 아닌 UI 시험용 샘플 응답이다.

이 모듈만 샘플 선과 가짜 공정 시간을 만든다. ROS 모드에서는 사용하지 않는다.
"""
import asyncio
import json
import math
from copy import deepcopy

from .monitor_contract import now, uid

PROFILE = {
    'contract': 'mock-profile/1', 'schema_version': 1, 'source_mode': 'SIMULATION',
    'label': '파라핀 양초 · 모의 프로파일', 'workcell_id': 'simulation-cell', 'workcell_version': 1,
    'tool_id': 'engraving_knife', 'tool_version': 1, 'tool_label': '조각칼 01',
    'tcp_id': 'GripperDA_v1', 'tcp_reference': '그리퍼 끝점', 'tcp_version': 1,
    'load_id': 'SIMULATION_ONLY', 'load_version': 1, 'frame_id': 'simulation_base',
    'measurement_status': 'SIMULATION_ONLY',
    'surface': {'kind': 'cylinder', 'radius_mm': 34, 'height_mm': 150,
                'u_range_mm': [-math.pi*34, math.pi*34], 'v_range_mm': [0, 150],
                'valid_v_range_mm': [10, 140], 'angle_range_deg': [-180, 180],
                'zero_angle': '로봇 베이스 정면', 'positive_angle': '축 위에서 반시계',
                'surface_pose_m_xyzw': [0, 0, 0, 0, 0, 0, 1]},
    'note': '실측 전 모의 값. V=10~140 mm는 화면 시험용이며 현장 가공 범위가 아닙니다.',
}
STAGES = ['CONVERTING','EXTRACTING_2D','OPTIMIZING_2D','MAPPING_3D','BUILDING_PATH','VALIDATING']


def sample_strokes():
    """입력 이미지와 무관한, 정해진 식물 모양 중심선 샘플."""
    result = [[(.08*math.sin(t*5), t-.5) for t in [i/70 for i in range(71)]]]
    for j in range(8):
        t = .12 + j*.1
        side = 1 if j % 2 else -1
        root = (.08*math.sin(t*5), t-.5)
        tip = (root[0]+side*(.23+.06*math.sin(j)), root[1]+.15)
        result.append([root, tip])
        leaf = []
        for i in range(41):
            a = i/40*2*math.pi
            f = (1-math.cos(a))/2
            leaf.append((root[0]+(tip[0]-root[0])*f + .045*math.sin(a),
                         root[1]+(tip[1]-root[1])*f - side*.045*math.sin(a)))
        result.append(leaf)
    return result


def sample_svg():
    parts = []
    for points in sample_strokes():
        d = ' '.join(f'{"M" if i == 0 else "L"}{(x+.5)*100:.3f},{(0.5-y)*100:.3f}' for i,(x,y) in enumerate(points))
        parts.append(f'<path d="{d}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<g fill="none" stroke="#294f43" stroke-width="0.7" stroke-linecap="round" stroke-linejoin="round">'
            + ''.join(parts) + '</g></svg>').encode()


def diagnostic(goal, profile, store, strokes, message):
    """진단용 SVG는 path_versions에 등록하지 않으며 실행 참조를 갖지 않는다."""
    half=profile['payload']['surface']['radius_mm']*math.pi
    paths=[]
    issues=[]
    for stroke in strokes:
        pts=stroke['points_uv_mm']
        outside=any(abs(u)>half or not 10<=v<=140 for u,v in pts)
        if outside:issues.append({'reason':'OUT_OF_MOCK_BOUNDS','stroke_id':stroke['stroke_id'],
                                  'segment_id':stroke['segment_id'],'location_uv_mm':next(p for p in pts if abs(p[0])>half or not 10<=p[1]<=140)})
        coords=' '.join(f'{u},{150-v}' for u,v in pts)
        color='#b04533' if outside else '#345e4c'
        paths.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="0.7"/>')
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-270 -140 540 420">'
         f'<rect x="{-half}" y="10" width="{half*2}" height="130" fill="#f2f4ec" stroke="#a0b29f"/>'
         +''.join(paths)+'</svg>').encode()
    a=store.put_asset(svg,'diagnostic_svg','image/svg+xml','non-executable-diagnostic.svg')
    return None,dict(success=False,error_code='VALIDATION_FAILED',message=message,
                     diagnostic_asset_id=a['id'],diagnostic_only=True,issues=issues,
                     diagnostic_contract='mock-diagnostic/1')


def artifacts(goal, profile, store, force_failure=False):
    """모의 GeneratePath 결과. 배치와 곡면은 화면 동작 시험용으로만 계산한다."""
    a = math.radians(goal['rotation_deg']); r = profile['payload']['surface']['radius_mm']
    strokes, segments = [], []
    out = False
    for n, points in enumerate(sample_strokes()):
        uv = []
        for x,y in points:
            x *= goal['width_mm']; y *= goal['height_mm']
            u = x*math.cos(a)-y*math.sin(a)+goal['offset_u_mm']
            v = x*math.sin(a)+y*math.cos(a)+goal['offset_v_mm']
            out |= abs(u) > math.pi*r or not 10 <= v <= 140
            uv.append([round(u,5), round(v,5)])
        xyz = [[r/1000*math.sin(u/r), -r/1000*math.cos(u/r), v/1000, 0,0,0,1] for u,v in uv]
        sid = f'cut-{n+1:03d}'
        strokes.append({'stroke_id':f'stroke-{n+1:03d}', 'segment_id':sid, 'kind':'CUT',
                        'points_uv_mm':uv, 'points_m': [p[:3] for p in xyz], 'connect_to_next':False})
        segments.append({'segment_id':sid,'stroke_id':f'stroke-{n+1:03d}', 'kind':'CUT',
                         'motion_profile_id':'simulation-only','waypoints':xyz})
    if out or force_failure:
        return diagnostic(goal,profile,store,strokes,'도안이 모의 작업 영역을 벗어났습니다. 크기·중심·회전을 조정하세요.' if out else '모의 검증 실패 시나리오. 진단 그림은 실행할 수 없습니다.')
    pid, version = uid(), 1
    path = dict(schema_version=1, path_id=pid, path_version=version, source_mode='SIMULATION',
                asset_id=goal['asset_id'], asset_sha256=goal['asset_sha256'], profile_snapshot_id=profile['id'],
                profile_sha256=profile['sha256'], workcell_id='simulation-cell', workcell_version=1,
                tool_id=goal['tool_id'], tool_version=1, tcp_profile_id='GripperDA_v1', tcp_profile_version=1,
                load_profile_id='SIMULATION_ONLY', load_profile_version=1, frame_id='simulation_base',
                position_unit='m',orientation='quaternion_xyzw', pose_reference='tool_tip',
                simulation_fixture=True, real_execution_allowed=False, segments=segments)
    path_asset = store.put_json(path,'path','simulation-path.json')
    svg = store.put_asset(sample_svg(),'svg','image/svg+xml','simulation-centerline.svg')
    preview = dict(contract='mock-preview/1',schema_version=1,source_mode='SIMULATION',
                   path_id=pid,path_version=version,path_sha256=path_asset['sha256'],
                   path_asset_id=path_asset['id'],asset_id=goal['asset_id'],asset_sha256=goal['asset_sha256'],
                   profile_snapshot_id=profile['id'],profile_sha256=profile['sha256'],
                   frame_id='simulation_base',pose_reference='tool_tip',render_only=True,
                   decimation='none',input=goal,strokes=strokes,
                   note='모의 중심선 샘플입니다. 첨부 이미지를 SVG로 변환한 결과가 아닙니다.')
    pv = store.put_json(preview,'preview','simulation-preview.json')
    report = store.put_json(dict(scope='SIMULATION_ONLY',real_execution_allowed=False,checks=[
        {'code':'MOCK_BOUNDS','status':'PASS','message':'모의 표면 범위'},
        {'code':'REAL_REACHABILITY','status':'UNSUPPORTED','message':'실기 도달·충돌·공구 자세 검증은 수행하지 않음'}]),'validation','simulation-validation.json')
    length = sum(math.dist(w[i][:3],w[i+1][:3]) for s in segments for w in [s['waypoints']] for i in range(len(w)-1))
    result = dict(success=True,error_code='NONE',message='모의 샘플 생성 완료',path_id=pid,path_version=version,
                  path_sha256=path_asset['sha256'],svg_asset_id=svg['id'],preview_asset_id=pv['id'],
                  validation_passed=True,validation_report_id=report['id'],segment_count=len(segments),cut_length_m=length)
    metadata = {**result,'path_asset_id':path_asset['id'],'profile_snapshot_id':profile['id'],
                'profile_sha256':profile['sha256'],'input':goal,'source_mode':'SIMULATION','simulation_fixture':True}
    return metadata, result


class MockPeer:
    transport = 'MOCK'

    def __init__(self, store, profile, emit, tick=.4):
        self.store,self.profile,self.emit,self.tick = store,profile,emit,tick
        self.epoch=uid();self.seq=0;self.event_seq=0;self.scenario='normal';self.stop_event=asyncio.Event()
        self.state=dict(schema_version=1,source_mode='SIMULATION',source_epoch=self.epoch,seq=0,
                        run_id='',path_id='',path_version=0,status='IDLE',phase='',engraving_progress=0,
                        elapsed_s=0,stop_state='NONE',error_code='NONE',message='모의 공정 대기',
                        requested_tool_id='engraving_knife',mounted_tool_id='',tool_confirmation_source='UNKNOWN',
                        grip_state='UNKNOWN',joints=None,tcp=None,temperature=None,quality='UNSUPPORTED')

    async def start(self):
        self.heartbeat_task=asyncio.create_task(self.heartbeat())

    async def close(self):
        self.heartbeat_task.cancel()
        await asyncio.gather(self.heartbeat_task,return_exceptions=True)

    async def heartbeat(self):
        while True:
            if self.scenario != 'communication_loss':
                await self.publish()
            await asyncio.sleep(.2)

    async def publish(self):
        if self.scenario == 'communication_loss':return
        self.seq+=1
        self.state.update(seq=self.seq,published_at=now())
        await self.emit('state',deepcopy(self.state))

    async def event(self,kind,message,code='NONE',severity='INFO'):
        self.event_seq+=1
        await self.emit('event',dict(schema_version=1,source_mode='SIMULATION',event_id=uid(),source_epoch=self.epoch,
             event_seq=self.event_seq,occurred_at=now(),run_id=self.state['run_id'],request_id=self.state.get('request_id',''),
             event_type=kind,phase=self.state['phase'],severity=severity,code=code,message=message,segment_id=''))

    async def generate(self,goal,feedback):
        scenario=self.scenario
        for i,stage in enumerate(STAGES):
            await feedback(dict(request_id=goal['request_id'],stage=stage,progress=(i+1)/len(STAGES)))
            await asyncio.sleep(self.tick)
        return await asyncio.to_thread(artifacts,goal,self.profile,self.store,scenario=='generation_failure')

    def prepare(self,run):
        self.stop_event=asyncio.Event()
        self.state.update(run_id=run['run_id'],request_id=run['request_id'],path_id=run['path_id'],
            path_version=run['path_version'],status='RUNNING',phase='PRECHECK',engraving_progress=0,
            stop_state='NONE',error_code='NONE',message='모의 준비 검사',elapsed_s=0,
            mounted_tool_id='',tool_confirmation_source='UNKNOWN',grip_state='UNKNOWN')

    async def execute(self,goal):
        scenario=self.scenario
        meta=await asyncio.to_thread(self.store.path,goal['path_id'],goal['path_version'])
        preview=json.loads(await asyncio.to_thread(self.store.read_asset,meta['preview_asset_id']))
        observations=[dict(segment_id=s['segment_id'],stroke_id=s['stroke_id'],start_point_index=0,
                           end_point_index=len(s['points_m'])-1,verdict='PENDING',motion_status='NOT_STARTED',
                           reason='',pressure_n=None,observed_at=now(),quality_source='SIMULATION_FIXTURE')
                      for s in preview['strokes']]
        evidence=dict(contract='mock-execution-preview/1',schema_version=1,source_mode='SIMULATION',
                      **{k:goal[k] for k in ('run_id','path_id','path_version','path_sha256')},
                      observations=observations)
        async def observation(index,verdict,reason=''):
            observations[index].update(verdict=verdict,reason=reason,observed_at=now(),
                  motion_status={'IN_PROGRESS':'MOVING','PASSED':'COMPLETED','FAILED':'COMPLETED','UNKNOWN':'UNKNOWN'}[verdict])
            await self.emit('mock_execution_preview',deepcopy(evidence))
        await self.emit('mock_execution_preview',deepcopy(evidence))
        start=asyncio.get_running_loop().time()
        phases=['PRECHECK','PICK_TOOL','APPROACH','ENGRAVE','RETRACT','PLACE_TOOL','FINISH']
        for phase in phases:
            if self.stop_event.is_set():break
            self.state.update(phase=phase)
            await self.event('PHASE_CHANGED',f'모의 {phase} 단계')
            for i in range(len(observations) if phase=='ENGRAVE' else 3):
                if self.stop_event.is_set():break
                if phase=='ENGRAVE':await observation(i,'IN_PROGRESS')
                await asyncio.sleep(self.tick)
                if self.stop_event.is_set():
                    if phase=='ENGRAVE':await observation(i,'UNKNOWN','STOPPED_DURING_SEGMENT')
                    break
                self.state['elapsed_s']=asyncio.get_running_loop().time()-start
                if phase=='ENGRAVE':
                    self.state['engraving_progress']=(i+1)/len(observations)
                    if scenario=='cut_quality_failure' and i==5:
                        await observation(i,'FAILED','SIMULATED_PRESSURE_NOT_CONFIRMED')
                        self.state.update(status='FAILED',error_code='NOT_READY',message='모의 압력 확인 실패. 해당 구간을 표시하고 다음 구간 진행을 중단합니다.')
                        await self.event('ALARM_RAISED',self.state['message'],'NOT_READY','ERROR')
                        break
                    await observation(i,'PASSED')
                await self.publish()
            if self.stop_event.is_set() or self.state['status']=='FAILED':break
            if phase=='PICK_TOOL':
                if scenario=='grip_failure':
                    self.state.update(status='FAILED',grip_state='ERROR',error_code='GRIP_NOT_CONFIRMED',message='모의 도구 확인 실패. 조각으로 진행하지 않습니다.')
                    await self.event('ALARM_RAISED',self.state['message'],'GRIP_NOT_CONFIRMED','ERROR')
                    break
                self.state.update(mounted_tool_id='engraving_knife',tool_confirmation_source='SIMULATION_FIXTURE',grip_state='GRIPPED')
            if phase=='PLACE_TOOL':self.state.update(mounted_tool_id='',grip_state='OPEN',tool_confirmation_source='SIMULATION_FIXTURE')
        if self.stop_event.is_set():
            self.state.update(status='STOPPING',stop_state='STOPPING')
            await self.publish()
            await asyncio.sleep(self.tick)
            unknown=scenario=='stop_unknown'
            self.state.update(status='UNKNOWN' if unknown else 'STOPPED',stop_state='UNKNOWN' if unknown else 'CONFIRMED',
                              error_code='STOP_UNCONFIRMED' if unknown else 'NONE',message='모의 정지 확인 불가' if unknown else '모의 정지 확인')
            if unknown:await self.event('ALARM_RAISED',self.state['message'],'STOP_UNCONFIRMED','ERROR')
        elif self.state['status']!='FAILED':
            self.state.update(status='SUCCEEDED',phase='FINISH',message='모의 공정 완료. 검사 판정은 별도로 기록하세요.')
        await self.publish()
        await self.event('RUN_FINISHED',self.state['message'])
        return dict(run_id=goal['run_id'],outcome=self.state['status'],error_code=self.state['error_code'],
                    message=self.state['message'],last_completed_segment_id='',log_id=uid())

    async def stop(self,body):
        if body['run_id']!=self.state['run_id']:
            return dict(accepted=False,run_id=body['run_id'],stop_state='NONE',error_code='RUN_MISMATCH',message='활성 실행과 다릅니다.')
        self.stop_event.set()
        self.state.update(stop_state='ACCEPTED')
        return dict(accepted=True,run_id=body['run_id'],stop_state='ACCEPTED',error_code='NONE',message='모의 정지 접수')
