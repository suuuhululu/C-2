"""운영자 전용 모의 HMI API. 기존 고객 앱과 DB를 공유하지 않는다."""
import asyncio
import fcntl
import io
import os
import sqlite3
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse, Response, FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from .monitor_contract import GenerateInput, RunInput, StopInput, InspectionInput, ScenarioInput
from .monitor_service import MonitorService, DomainError
from .storage import Storage

ROOT=Path(__file__).resolve().parents[1]
MAX_BYTES=10*1024*1024


def image_data(raw):
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('PNG','JPEG'):raise ValueError('PNG/JPEG만 지원합니다.')
            if im.width*im.height>16_000_000 or max(im.size)>6000:raise ValueError('이미지 제한: 16 MP, 한 변 6000 px')
            mime=Image.MIME[im.format]
            im.load();im=ImageOps.exif_transpose(im).convert('RGB')
            preview=io.BytesIO();im.save(preview,format='PNG')
            return im.size,preview.getvalue(),mime


def create_app(data_dir=None,tick=.4):
    @asynccontextmanager
    async def lifespan(app):
        if os.getenv('C2_MONITOR_MODE','SIMULATION')!='SIMULATION':
            raise RuntimeError('현재 모니터는 SIMULATION 전용입니다.')
        directory=Path(data_dir or os.getenv('C2_MONITOR_DATA',ROOT/'monitor_data'))
        directory.mkdir(parents=True,exist_ok=True)
        lock=(directory/'.server.lock').open('a')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close();raise RuntimeError('같은 모니터 DB를 사용하는 서버가 이미 있습니다.')
        store=Storage(directory);service=MonitorService(store,os.getenv('C2_MONITOR_TRANSPORT','mock'),tick)
        app.state.store=store;app.state.service=service
        try:
            await service.start()
            yield
        finally:
            if hasattr(service,'peer') and hasattr(service.peer,'heartbeat_task') or hasattr(getattr(service,'peer',None),'executor'):
                await service.close()
            lock.close()

    app=FastAPI(title='새김 시스템 모니터',lifespan=lifespan)

    @app.middleware('http')
    async def guard(request,call_next):
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            allowed={'http://127.0.0.1:5174','http://localhost:5174','http://127.0.0.1:8010','http://localhost:8010'}
            if request.headers.get('x-c2-monitor')!='1' or (origin and origin not in allowed):
                return JSONResponse({'error_code':'FORBIDDEN','message':'로컬 모니터에서 요청하세요.'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request,exc):return JSONResponse({'error_code':exc.code,'message':exc.message},status_code=exc.status)

    @app.exception_handler(KeyError)
    async def not_found(request,exc):return JSONResponse({'error_code':'ASSET_NOT_FOUND','message':'요청한 기록·파일이 없습니다.'},status_code=404)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request,exc):return JSONResponse({'error_code':'STORAGE_ERROR','message':'저장소를 사용할 수 없습니다. 작업을 접수하지 못했습니다.'},status_code=503)

    @app.get('/api/operator/snapshot')
    async def snapshot():return app.state.service.snapshot()

    @app.post('/api/operator/assets',status_code=201)
    async def upload(file:UploadFile=File(...)):
        raw=await file.read(MAX_BYTES+1)
        await file.close()
        if len(raw)>MAX_BYTES:raise HTTPException(413,'파일은 10 MiB 이하로 첨부하세요.')
        try:size,thumbnail,mime=await asyncio.to_thread(image_data,raw)
        except (ValueError,UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise DomainError('UNSUPPORTED_FORMAT','정상 PNG/JPEG 이미지를 첨부하세요. 최대 16 MP, 한 변 6000 px입니다.',415)
        thumb=await asyncio.to_thread(app.state.store.put_asset,thumbnail,'thumbnail','image/png','original-preview.png')
        a=await asyncio.to_thread(app.state.store.put_asset,raw,'image',mime,
                                  Path(file.filename or 'image').name,{'width':size[0],'height':size[1],'thumbnail_id':thumb['id']})
        await app.state.service.notice('이미지 첨부 완료 · '+a['name'])
        return {**a,'asset_id':a['id'],'asset_sha256':a['sha256'],'url':f'/api/operator/assets/{thumb["id"]}/content'}

    @app.get('/api/operator/assets/{aid}/content')
    async def content(aid:str):
        a=await asyncio.to_thread(app.state.store.asset,aid)
        try:raw=await asyncio.to_thread(app.state.store.read_asset,aid)
        except ValueError:raise DomainError('HASH_MISMATCH','저장된 파일이 변경됐습니다.')
        return Response(raw,media_type=a['mime'],headers={'Content-Security-Policy':"default-src 'none'; sandbox"})

    @app.post('/api/operator/path-generations',status_code=202)
    async def generate(body:GenerateInput):return await app.state.service.generate(body.model_dump(mode='json'))

    @app.get('/api/operator/path-generations/{rid}')
    async def generation(rid:str):
        if rid in app.state.service.generation_status:return app.state.service.generation_status[rid]
        r=await asyncio.to_thread(app.state.store.generation,rid)
        if r is None:raise KeyError(rid)
        return r

    @app.get('/api/operator/paths/{pid}/versions/{version}')
    async def path(pid:str,version:int):
        meta=await asyncio.to_thread(app.state.store.path,pid,version)
        try:
            # 등록 당시 검증한 해시를 사용한다. DB의 파일 해시만 새 값으로 바뀌어도 거절한다.
            for aid, expected in meta.get('artifact_sha256',{}).items():
                await asyncio.to_thread(app.state.store.read_asset,aid,expected)
            preview=await asyncio.to_thread(app.state.store.read_asset,meta['preview_asset_id'],
                meta.get('artifact_sha256',{}).get(meta['preview_asset_id']))
        except ValueError:raise DomainError('HASH_MISMATCH','미리보기 파일이 변경됐습니다. 실행할 수 없습니다.')
        import json
        return {**meta,'preview':json.loads(preview),'svg_url':f'/api/operator/assets/{meta["svg_asset_id"]}/content',
                'path_url':f'/api/operator/assets/{meta["path_asset_id"]}/content',
                'validation_url':f'/api/operator/assets/{meta["validation_report_id"]}/content'}

    @app.post('/api/operator/runs',status_code=202)
    async def run(body:RunInput):return await app.state.service.start_run(body.model_dump(mode='json'))

    @app.get('/api/operator/runs')
    async def runs():
        items=await asyncio.to_thread(app.state.store.runs)
        current=app.state.service.run
        return [current if current and r['run_id']==current['run_id'] else r for r in items]

    @app.get('/api/operator/runs/{rid}')
    async def run_info(rid:str):return await app.state.service.get_run(rid)

    @app.post('/api/operator/runs/{rid}/stop',status_code=202)
    async def stop(rid:str,body:StopInput):return await app.state.service.stop(rid,body.model_dump(mode='json'))

    @app.get('/api/operator/alarms')
    async def alarms():return await asyncio.to_thread(app.state.store.alarms)

    @app.post('/api/operator/inspections',status_code=201)
    async def inspect(body:InspectionInput):return await app.state.service.inspect(body.model_dump(mode='json'))

    @app.post('/api/operator/simulation/scenario')
    async def scenario(body:ScenarioInput):
        s=app.state.service
        if s.transport!='mock':raise DomainError('NOT_READY','모의 통신에서만 사용할 수 있습니다.')
        if s.busy() or s.generating:raise DomainError('BUSY','진행 중인 작업이 끝난 뒤 시나리오를 변경하세요.')
        s.peer.scenario=body.scenario
        await s.notice('모의 시나리오 변경: '+body.scenario)
        return {'scenario':body.scenario}

    @app.post('/api/operator/simulation/reset')
    async def reset():
        s=app.state.service
        if s.transport!='mock' or s.tasks:raise DomainError('BUSY','모의 작업 종료 후 초기화할 수 있습니다.')
        # 시험 상태만 초기화한다. 실행 이력·파일·DB는 삭제하지 않는다.
        s.run=None;s.peer.scenario='normal'
        s.peer.state.update(run_id='',path_id='',status='IDLE',phase='',stop_state='NONE',error_code='NONE',
                            message='모의 상태 초기화',engraving_progress=0,mounted_tool_id='',grip_state='UNKNOWN')
        await s.peer.publish();await s.notice('모의 상태 초기화 · 이전 실행 이력 보존')
        return s.snapshot()

    @app.websocket('/api/operator/stream')
    async def stream(ws:WebSocket):
        origin=ws.headers.get('origin')
        if origin not in {'http://127.0.0.1:5174','http://localhost:5174','http://127.0.0.1:8010','http://localhost:8010'}:
            await ws.close(code=1008);return
        await ws.accept()
        try:
            while True:
                await ws.send_json({'type':'snapshot','data':app.state.service.snapshot()})
                await asyncio.sleep(.4)
        except (WebSocketDisconnect,RuntimeError):pass

    dist=ROOT.parent/'frontend/dist'
    if dist.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount('/assets',StaticFiles(directory=dist/'assets'),name='ui-assets')
        if (dist/'samples').exists():
            app.mount('/samples',StaticFiles(directory=dist/'samples'),name='ui-samples')
        @app.get('/')
        @app.get('/operator')
        async def ui():return FileResponse(dist/'index.html')
    return app


app=create_app()
