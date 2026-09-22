import asyncio
import time
import pytest
from types import SimpleNamespace
from app.monitor_service import MonitorService

def test_success_is_finished_and_late_state_cannot_regress_it():
    async def scenario():
        service=MonitorService.__new__(MonitorService)
        service.run={k:'x' for k in ['schema_version','request_id','run_id','source_mode','path_id','path_version','path_sha256','operator_confirmed_fixture','operator_id','confirmed_at']}
        service.run.update(status='RUNNING',phase='RETRACT',stop_state='NONE')
        async def execute(goal):
            return dict(run_id='x',outcome='SUCCEEDED',engraving_progress=1.0000000000000002)
        service.peer=SimpleNamespace(execute=execute)
        service.store=SimpleNamespace(save_run=lambda run:None)
        saved=[];service.record=lambda fn,run:saved.append(run)
        await service.run_job(service.run)
        assert saved[-1]['phase']=='FINISH' and saved[-1]['engraving_progress']==1.
        service.mode="SIMULATION";service.retired_epochs=set();service.state={'source_epoch':'epoch','seq':1};service.last_state=time.monotonic()
        await service.receive('state',dict(schema_version=2,source_mode='SIMULATION',source_epoch='epoch',seq=2,run_id='x',phase='RETRACT',engraving_progress=.9))
        assert service.run['phase']=='FINISH' and service.run['engraving_progress']==1.
    asyncio.run(scenario())


def test_pending_action_keeps_busy_and_old_result_cannot_replace_new_run():
    async def scenario():
        service=MonitorService.__new__(MonitorService)
        old={k:'old' for k in ['schema_version','request_id','run_id','source_mode','path_id','path_version','path_sha256','operator_confirmed_fixture','operator_id','confirmed_at']}
        old.update(status='RUNNING',stop_state='NONE')
        service.run=old
        started=asyncio.Event();release=asyncio.Event()
        async def execute(goal):
            started.set();await release.wait()
            return dict(run_id='old',outcome='FAILED',error_code='VALIDATION_FAILED',message='old failure')
        service.peer=SimpleNamespace(execute=execute)
        service.store=SimpleNamespace(save_run=lambda run:None)
        service.record=lambda fn,run:None
        task=asyncio.create_task(service.run_job(old))
        await started.wait()
        old['status']='FAILED'
        assert service.busy()
        replacement=dict(run_id='new',status='ACCEPTED')
        service.run=replacement
        release.set();await task
        assert service.run==replacement and 'message' not in replacement
        assert not service.pending_run_ids
    asyncio.run(scenario())


@pytest.mark.parametrize('status,stop_state,incoming,confirmed,expected', [
    ('UNKNOWN','NONE','SUCCEEDED','NONE','UNKNOWN'),
    ('STOPPING','REQUESTED','SUCCEEDED','NONE','STOPPING'),
    ('STOPPING','REQUESTED','STOPPED','UNCONFIRMED','STOPPING'),
    ('STOPPING','REQUESTED','STOPPED','CONFIRMED','STOPPED'),
])
def test_terminal_topic_preserves_unknown_and_stop_latches(status,stop_state,incoming,confirmed,expected):
    async def scenario():
        service=MonitorService.__new__(MonitorService)
        service.run=dict(run_id='x',status=status,stop_state=stop_state)
        service.mode='REAL';service.retired_epochs=set()
        service.state=dict(source_epoch='epoch',seq=1);service.last_state=time.monotonic()
        service.store=SimpleNamespace(save_run=lambda run:None);service.record=lambda *args:None
        await service.receive('state',dict(schema_version=2,source_mode='REAL',source_epoch='epoch',seq=2,
            run_id='x',status=incoming,stop_state=confirmed))
        assert service.run['status']==expected
        assert service.run['stop_state']==('CONFIRMED' if expected=='STOPPED' else stop_state)
    asyncio.run(scenario())


def test_terminal_process_state_updates_active_run_without_waiting_for_action_result():
    async def scenario():
        service=MonitorService.__new__(MonitorService)
        service.run=dict(run_id='run-1',status='RUNNING',phase='PRECHECK',stop_state='NONE',
                         engraving_progress=0.,elapsed_s=10.,error_code='NONE',message='검사 중')
        service.mode='REAL';service.retired_epochs=set();service.contract_error=None
        service.state={'source_epoch':'epoch','seq':1};service.last_state=time.monotonic()
        service.preparation=SimpleNamespace(invalidate_connection=lambda:None)
        service.store=SimpleNamespace(save_run=lambda run:None)
        saved=[];service.record=lambda fn,run:saved.append(run)
        await service.receive('state',dict(schema_version=2,source_mode='REAL',source_epoch='epoch',seq=2,
            run_id='run-1',status='FAILED',phase='PRECHECK',engraving_progress=0.,elapsed_s=147.,
            stop_state='NONE',error_code='VALIDATION_FAILED',
            message='관절 한계/여유 초과: J6 171° (segment seg-0163)'))
        assert service.run['status']=='FAILED'
        assert service.run['error_code']=='VALIDATION_FAILED'
        assert service.run['message'].endswith('(segment seg-0163)')
        assert saved[-1]['status']=='FAILED'
    asyncio.run(scenario())


def test_process_binding_failure_invalidates_gateway_preparation():
    async def scenario():
        service=MonitorService.__new__(MonitorService)
        service.run={k:'x' for k in ['schema_version','request_id','run_id','source_mode','path_id','path_version','path_sha256','operator_confirmed_fixture','operator_id','confirmed_at']}
        service.run.update(status='RUNNING',phase='PRECHECK',stop_state='NONE',engraving_progress=0.)
        async def execute(goal):
            return dict(run_id='x',outcome='FAILED',error_code='NOT_READY',
                        message='준비 결과 연결 필요',engraving_progress=0.)
        invalidated=[]
        async def invalidate(reason): invalidated.append(reason)
        service.peer=SimpleNamespace(execute=execute)
        service.preparation=SimpleNamespace(invalidate_process_binding=invalidate)
        service.store=SimpleNamespace(save_run=lambda run:None)
        service.record=lambda fn,run:None
        await service.run_job(service.run)
        assert invalidated==['준비 결과 연결 필요']
    asyncio.run(scenario())
