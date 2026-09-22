import asyncio
import time
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
