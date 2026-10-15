"""Service-generated history in a dedicated PostgreSQL test DB and local web."""
from contextlib import nullcontext
from threading import Thread
from uuid import uuid4

import pytest

from history import personal,store
from history.mvp_save import link_current_job,verify_web_job
from history.web import HistoryServer
from test_history_personal_db import connection,users
from test_round3_service import setup,run,manual_design


@pytest.mark.parametrize('fault',[None,'MISMATCH'])
@pytest.mark.parametrize('manual',[False,True])
def test_actual_service_history_personal_save_and_web_preserve_b_truth(setup,connection,users,monkeypatch,fault,manual):
    if manual:manual_design(setup)
    folder,config,_=setup
    user,other=users;config['creator']={key:user[key] for key in ('user_id','username','display_name')}
    result,_,launches,_,_=run(setup,fault)
    assert len(launches)==2 and result['physical_completion']==(fault is None)
    link_current_job(connection,result['history_directory'],result['job_id'],config['creator'])
    key=str(uuid4());receipt=personal.save_job(connection,result['job_id'],user['user_id'],key)
    assert personal.save_job(connection,result['job_id'],user['user_id'],key)==receipt
    with pytest.raises(ValueError,match='unavailable'):
        personal.bundle(connection,result['job_id'],other['user_id'])
    monkeypatch.setattr(store,'connect',lambda *a:nullcontext(connection))
    with HistoryServer(('127.0.0.1',0),'') as server:
        worker=Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            viewed=verify_web_job(server.origin,result['job_id'],user['username'],'fixture-password',receipt)
            assert viewed['completion']['assembly']==('RECORDED' if fault is None else 'NOT_RECORDED')
            assert viewed['storage']['status']=='SAVED'
            assert len(launches)==2
        finally:server.shutdown();worker.join(timeout=2)
