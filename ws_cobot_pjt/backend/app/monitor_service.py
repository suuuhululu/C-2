"""HTTP와 게이트웨이 사이의 요청·결과·기록 조정. 실제 공정 순서는 상대 노드 소유."""
import asyncio
import contextlib
import time
from collections import deque

from .mock_peer import MockPeer, PROFILE
from .monitor_contract import SCHEMA_VERSION, now, uid


class DomainError(Exception):
    def __init__(self,code,message,status=409):
        self.code,self.message,self.status=code,message,status
        super().__init__(message)


class MonitorService:
    def __init__(self,store,transport='mock',tick=.4):
        self.store=store;self.transport=transport;self.tick=tick
        self.state=None;self.last_state=0.;self.retired_epochs=set()
        self.run=None;self.generating=None;self.generation_status={};self.stops={}
        self.stop_watch=None;self.stop_confirmation_timeout=3.;self.contract_error=None
        self.events=deque(maxlen=60);self.event_ids=set();self.tasks=set()
        self.lock=asyncio.Lock();self.writes=asyncio.Queue();self.storage_error=None;self.closed=False

    async def start(self):
        self.profile=await asyncio.to_thread(self.store.profile,PROFILE)
        self.run=await asyncio.to_thread(self.store.recover)
        self.stops=await asyncio.to_thread(self.store.stop_requests)
        self.events.extend(await asyncio.to_thread(self.store.events))
        self.event_ids.update(e['event_id'] for e in self.events)
        self.writer=asyncio.create_task(self.write_loop())
        if self.transport=='mock':
            self.peer=MockPeer(self.store,self.profile,self.receive,self.tick)
        else:
            from .ros_bridge import RosBridge
            self.peer=RosBridge(self.receive)
        await self.peer.start()

    def launch(self,coro):
        task=asyncio.create_task(coro);self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        return task

    async def close(self):
        self.closed=True
        for task in self.tasks:task.cancel()
        await asyncio.gather(*list(self.tasks),return_exceptions=True)
        await self.peer.close()
        with contextlib.suppress(asyncio.TimeoutError):await asyncio.wait_for(self.writes.join(),2)
        self.writer.cancel();await asyncio.gather(self.writer,return_exceptions=True)

    async def write_loop(self):
        while True:
            method,args=await self.writes.get()
            try:
                for attempt in range(3):
                    try:
                        await asyncio.to_thread(method,*args);break
                    except Exception as exc:
                        if attempt==2:self.storage_error=f'기록 저장 실패: {type(exc).__name__}'
                        else:await asyncio.sleep(.15)
            finally:self.writes.task_done()

    def record(self,method,*args):self.writes.put_nowait((method,args))

    async def notice(self,message,kind='COMMAND',code='NONE',severity='INFO'):
        e=dict(event_id=uid(),source_mode='SIMULATION',schema_version=SCHEMA_VERSION,source_epoch='gateway',event_seq=0,
               run_id=self.run['run_id'] if self.run else '',occurred_at=now(),event_type=kind,
               severity=severity,code=code,message=message,phase='')
        await self.receive('event',e)

    async def receive(self,kind,data):
        if data.get('schema_version')!=SCHEMA_VERSION or data.get('source_mode')!='SIMULATION':
            self.contract_error='통신 계약 또는 모드 불일치. 고정 드릴 v2/SIMULATION 상대를 확인하세요.'
            self.last_state=0
            return
        if kind=='mock_execution_preview':
            # 로컬 모의 확장. 기존 ROS ProcessState/ProcessEvent 필드를 확장하지 않는다.
            if self.transport!='mock' or not self.run:return
            if any(data.get(k)!=self.run.get(k) for k in ('run_id','path_id','path_version','path_sha256')):return
            self.run['execution_preview']=data
            self.record(self.store.save_run,dict(self.run))
            return
        if kind=='state':
            epoch,seq=data.get('source_epoch'),data.get('seq')
            if not epoch or type(seq) is not int or seq<0:return
            if epoch in self.retired_epochs:return
            if self.state:
                if self.state['source_epoch']==epoch and seq<=self.state['seq']:return
                if self.state['source_epoch']!=epoch:
                    self.retired_epochs.add(self.state['source_epoch'])
                    if self.run and self.run['status'] in ('ACCEPTED','RUNNING','STOPPING'):
                        self.run.update(status='UNKNOWN',error_code='COMMUNICATION_LOST',message='공정 노드 재시작. 실행 결과 미확인')
                        self.record(self.store.save_run,dict(self.run))
            self.state=data;self.last_state=time.monotonic();self.contract_error=None
            if self.run and data.get('run_id')==self.run['run_id'] and self.run['status']!='UNKNOWN':
                for key in ['phase','engraving_progress','elapsed_s','stop_state']:
                    self.run[key]=data.get(key)
        elif kind=='event':
            eid=data.get('event_id')
            if not eid or eid in self.event_ids:return
            self.event_ids.add(eid);self.events.appendleft(data)
            self.record(self.store.event,data)

    def fresh(self):return self.last_state>0 and time.monotonic()-self.last_state<2

    def busy(self):return self.run and self.run['status'] in ('ACCEPTED','RUNNING','STOPPING','UNKNOWN')

    def snapshot(self):
        return dict(schema_version=SCHEMA_VERSION,source_mode='SIMULATION',transport=self.peer.transport,server_time=now(),
                    connection='CONNECTED' if self.fresh() else 'STALE',state=self.state,active_run=self.run,
                    profile=self.profile,events=list(self.events),generation=self.generation_status.get(self.generating),
                    storage_error=self.storage_error,scenario=getattr(self.peer,'scenario',None),
                    contract_status=self.contract_error or '고정 드릴 통신 v2 · 미리보기 세부 형식은 모의 계약')

    async def generate(self,goal):
        async with self.lock:
            old=await asyncio.to_thread(self.store.generation,goal['request_id'])
            if old:
                if old['payload']!=goal:raise DomainError('REQUEST_CONFLICT','같은 요청 ID에 다른 입력이 있습니다.')
                return old
            if self.generating or self.busy():raise DomainError('BUSY','현재 생성·실행이 끝난 뒤 다시 요청하세요.')
            try:
                asset=await asyncio.to_thread(self.store.asset,goal['asset_id'])
                if asset['kind']!='image':raise DomainError('UNSUPPORTED_FORMAT','첨부한 원본 이미지 ID를 사용하세요.',415)
                await asyncio.to_thread(self.store.read_asset,goal['asset_id'],goal['asset_sha256'])
                await asyncio.to_thread(self.store.read_asset,goal['profile_snapshot_id'],goal['profile_sha256'])
            except KeyError:raise DomainError('ASSET_NOT_FOUND','입력 파일 또는 설정을 찾을 수 없습니다.',404)
            except ValueError:raise DomainError('HASH_MISMATCH','파일 또는 설정 해시가 일치하지 않습니다.')
            if goal['profile_snapshot_id']!=self.profile['id'] or goal['profile_sha256']!=self.profile['sha256']:
                raise DomainError('PROFILE_MISMATCH','현재 지원하는 모의 프로파일과 다릅니다.')
            self.generating=goal['request_id']
            try:await asyncio.to_thread(self.store.create_generation,goal)
            except Exception:
                self.generating=None;raise
            self.generation_status[goal['request_id']]=dict(request_id=goal['request_id'],state='ACCEPTED',stage='CONVERTING',progress=0,result=None)
            self.launch(self.generate_job(goal))
            return self.generation_status[goal['request_id']]

    async def generate_job(self,goal):
        rid=goal['request_id']
        async def feedback(f):
            if f.get('request_id')!=rid:return
            if self.generation_status[rid]['state'] not in ('SUCCEEDED','FAILED'):
                self.generation_status[rid].update(f,state='RUNNING')
        try:
            metadata,result=await asyncio.wait_for(self.peer.generate(goal,feedback),120)
            status='SUCCEEDED' if result['success'] else 'FAILED'
            await asyncio.to_thread(self.store.finish_generation,rid,status,result,metadata)
            self.generation_status[rid].update(state=status,result=result,progress=1)
            await self.notice(result['message'],code=result['error_code'],severity='INFO' if result['success'] else 'WARNING')
        except Exception as exc:
            result=dict(success=False,error_code='TIMEOUT' if isinstance(exc,asyncio.TimeoutError) else 'NOT_READY' if isinstance(exc,(RuntimeError,ConnectionError)) else 'STORAGE_ERROR',
                        message='생성 결과를 확정하지 못했습니다. 다시 조회하거나 연결 상태를 확인하세요.')
            self.generation_status[rid].update(state='FAILED',result=result)
            try:await asyncio.to_thread(self.store.finish_generation,rid,'FAILED',result)
            except Exception:self.storage_error='생성 실패 기록 저장 불가'
        finally:self.generating=None

    async def start_run(self,body):
        async with self.lock:
            old=await asyncio.to_thread(self.store.request,body['request_id'])
            if old:
                if old['payload']!=body:raise DomainError('REQUEST_CONFLICT','같은 요청 ID에 다른 실행 입력이 있습니다.')
                return await self.get_run(old['response']['run_id'])
            if self.busy() or self.generating:raise DomainError('BUSY','활성 또는 미확인 작업이 있습니다.')
            if not self.fresh() or self.storage_error:raise DomainError('NOT_READY','상태 통신 또는 기록 저장을 확인하세요.')
            path=await asyncio.to_thread(self.store.path,body['path_id'],body['path_version'])
            if path.get('input',{}).get('schema_version')!=SCHEMA_VERSION:
                raise DomainError('UNSUPPORTED_SCHEMA_VERSION','이전 계약의 경로입니다. 고정 드릴 v2로 다시 생성·확인하세요.')
            if self.transport!='mock' and path.get('simulation_fixture'):
                raise DomainError('NOT_READY','모의 경로 파일은 ROS 상대 노드로 전달하지 않습니다. 좌표 노드 산출물 연결이 필요합니다.')
            if path['path_sha256']!=body['path_sha256']:raise DomainError('HASH_MISMATCH','확인한 경로 해시와 다릅니다.')
            if not path['validation_passed'] or path['source_mode']!='SIMULATION':raise DomainError('VALIDATION_FAILED','모의 실행 가능한 경로가 아닙니다.')
            if path['profile_snapshot_id']!=self.profile['id']:raise DomainError('PROFILE_MISMATCH','설정이 변경됐습니다. 경로를 다시 생성하세요.')
            try:
                await asyncio.to_thread(self.store.read_asset,path['path_asset_id'],body['path_sha256'])
                await asyncio.to_thread(self.store.read_asset,path['profile_snapshot_id'],path['profile_sha256'])
                await asyncio.to_thread(self.store.read_asset,path['input']['asset_id'],path['input']['asset_sha256'])
                for key in ('preview_asset_id','svg_asset_id','validation_report_id'):
                    await asyncio.to_thread(self.store.read_asset,path[key])
            except ValueError:raise DomainError('HASH_MISMATCH','실행 의존 파일이 변경됐습니다.')
            run=dict(**body,run_id=uid(),operator_id='local-operator',confirmed_at=now(),status='ACCEPTED',phase='PRECHECK',
                     engraving_progress=0,elapsed_s=0,stop_state='NONE',error_code='NONE',message='실행 요청 접수',created_at=now())
            await asyncio.to_thread(self.store.reserve_run,body,run)
            self.run=run
            self.peer.prepare(run)
            self.launch(self.run_job(dict(run)))
            return dict(run)

    async def run_job(self,run):
        rid=run['run_id']
        try:
            if self.run['stop_state']=='NONE':self.run['status']='RUNNING'
            result=await self.peer.execute({k:run[k] for k in ['schema_version','request_id','run_id','source_mode',
                  'path_id','path_version','path_sha256','operator_confirmed_fixture','operator_id','confirmed_at']})
            if result.get('run_id')!=rid or result.get('outcome') not in ('SUCCEEDED','FAILED','STOPPED','UNKNOWN'):
                raise ValueError('실행 결과의 식별자 또는 상태 불일치')
            # UNKNOWN latch와 정지 이후 늦은 성공은 유지한다.
            if self.run['status']=='UNKNOWN':
                result.update(outcome='UNKNOWN',error_code=self.run['error_code'],message=self.run['message'])
            if self.run['stop_state']!='NONE' and result['outcome']=='SUCCEEDED':
                result.update(outcome='UNKNOWN',error_code='STOP_UNCONFIRMED',message='정지 요청 이후 성공 응답. 실제 정지 미확인')
            self.run.update(result,status=result['outcome'],ended_at=now())
        except Exception:
            self.run.update(status='UNKNOWN',error_code='COMMUNICATION_LOST',message='실행 결과 미확인. 자동 재시작하지 않습니다.')
        finally:
            self.record(self.store.save_run,dict(self.run))

    async def stop(self,rid,body):
        payload={**body,'run_id':rid}
        if body['request_id'] in self.stops:
            old=self.stops[body['request_id']]
            if old['payload']!=payload:raise DomainError('REQUEST_CONFLICT','같은 정지 ID의 내용이 다릅니다.')
            return old['response']
        if not self.run or self.run['run_id']!=rid:raise DomainError('RUN_MISMATCH','대상 실행이 현재 실행과 다릅니다.')
        if not self.busy():raise DomainError('NOT_READY','이미 종료가 확인된 실행입니다.')
        # 미확인 상태는 다른 정지 요청 ID나 늦은 수락 응답으로 해제하지 않는다.
        was_unknown=self.run['status']=='UNKNOWN'
        if not was_unknown:
            self.run['stop_state']='REQUESTED'
            self.run['status']='STOPPING'
        # DB를 읽거나 쓰기 전에 전달한다.
        try:
            response=await asyncio.wait_for(self.peer.stop(payload),1)
            if response.get('run_id')!=rid:raise ValueError('정지 응답 실행 ID 불일치')
        except Exception:
            response=dict(accepted=False,run_id=rid,stop_state='UNKNOWN',error_code='STOP_UNCONFIRMED',message='정지 접수 응답 미확인')
        self.stops[body['request_id']]=dict(payload=payload,response=response)
        if was_unknown or not response['accepted'] or response['stop_state']=='UNKNOWN':
            self.run.update(status='UNKNOWN',stop_state='UNKNOWN')
        if self.run['stop_state']=='REQUESTED':self.run['stop_state']=response['stop_state']
        if self.run['status']=='STOPPING' and (self.stop_watch is None or self.stop_watch.done()):
            self.stop_watch=self.launch(self.watch_stop(rid))
        self.record(self.store.save_stop,payload,response)
        self.record(self.store.save_run,dict(self.run))
        await self.notice(response['message'],code=response['error_code'])
        return response

    async def watch_stop(self,rid):
        deadline=time.monotonic()+self.stop_confirmation_timeout
        while self.run and self.run['run_id']==rid and self.run['status']=='STOPPING':
            if self.run['stop_state']=='CONFIRMED':return
            if time.monotonic()>=deadline:
                self.run.update(status='UNKNOWN',stop_state='UNKNOWN',error_code='STOP_UNCONFIRMED',
                                message='정지 접수 후 확인 시간 초과. 자동 재시작하지 않습니다.')
                self.record(self.store.save_run,dict(self.run))
                await self.notice(self.run['message'],'ALARM_RAISED','STOP_UNCONFIRMED','ERROR')
                return
            await asyncio.sleep(.05)

    async def get_run(self,rid):
        run=dict(self.run) if self.run and self.run['run_id']==rid else await asyncio.to_thread(self.store.run,rid)
        run['inspections']=await asyncio.to_thread(self.store.inspections,rid)
        return run

    async def inspect(self,body):
        run=await self.get_run(body['run_id'])
        if run['status'] not in ('SUCCEEDED','FAILED','STOPPED'):
            raise DomainError('NOT_READY','최종 결과가 확인된 실행에 검사 기록을 추가하세요.')
        return await asyncio.to_thread(self.store.inspect,body,'local-operator')
