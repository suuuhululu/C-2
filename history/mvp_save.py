"""현재 HMI 작업만 인증된 사용자에게 저장한다. Robot/Current 변경 없음."""
from pathlib import Path
from uuid import UUID
from http.client import HTTPConnection
from contextlib import closing
import json
from urllib.parse import urlsplit

from history import accounts, personal, store
from history.final_mvp import CONTRACT, completion


def link_current_job(connection, log_directory, job_id, creator):
    """Local HMI only: bind its new Job to the already authenticated creator."""
    job_id = str(UUID(job_id))
    with connection.transaction():
        user = connection.execute('SELECT user_id::text FROM c2_history.users WHERE username=%s',
                                  (creator['username'],)).fetchone()
        if user is None or user['user_id'] != creator['user_id']:
            raise ValueError('CREATOR_ACCOUNT_UNAVAILABLE')
        store.ingest(connection, Path(log_directory)/(job_id+'.jsonl'), 'mvp/'+job_id, contract=CONTRACT)
        return personal.bind_job(connection, job_id, creator['username'],
                                 'HMI Job start: authenticated creator')


def save_current_job(connection, log_directory, job_id, username, password, save_key, *, expected_user_id=None):
    job_id = str(UUID(job_id))
    user = accounts.authenticate(connection, username, password)
    if user is None:
        raise ValueError('AUTHENTICATION_FAILED')
    if expected_user_id is not None and user['user_id'] != expected_user_id:
        raise ValueError('JOB_CREATOR_DIFFERS')
    # 임의 과거 Job을 웹에서 claim하는 API가 아니다. 로컬 진행부가 가진 현재 작업만 전달한다.
    path = Path(log_directory)/(job_id+'.jsonl')
    with connection.transaction():
        imported = store.ingest(connection, path, 'mvp/'+job_id, contract=CONTRACT)
        if imported['pending_line'] is not None:
            raise ValueError('JOB_LOG_NOT_FLUSHED')
        rows = store.timeline(connection, job_id)
        if completion(rows)['assembly'] != 'RECORDED':
            raise ValueError('FINAL_ASSEMBLY_NOT_CONFIRMED')
        personal.bind_job(connection, job_id, user['username'], 'HMI current Job: authenticated personal save')
        receipt = personal.save_job(connection, job_id, user['user_id'], save_key)
    return dict(receipt=receipt, owner={k:user[k] for k in ('user_id','username','display_name')})


def verify_web_job(url, job_id, username, password, receipt):
    """같은 로컬 웹에 인증 후 현재 저장 영수증이 조회되는지 확인한다."""
    address = urlsplit(url)
    if address.scheme != 'http' or address.hostname != '127.0.0.1' or address.path not in ('', '/'):
        raise ValueError('LOCAL_HISTORY_WEB_URL_REQUIRED')
    with closing(HTTPConnection(address.hostname, address.port or 8765, timeout=5)) as client:
        client.request('POST', '/api/login', json.dumps(dict(username=username,password=password)),
            {'Origin':url.rstrip('/'), 'Content-Type':'application/json'})
        response=client.getresponse()
        response.read()
        cookie=response.getheader('Set-Cookie')
        if response.status != 200 or not cookie:
            raise ValueError('WEB_LOGIN_FAILED')
        client.request('GET','/api/jobs/'+str(UUID(job_id)),headers={'Cookie':cookie.split(';')[0]})
        response=client.getresponse()
        body=json.loads(response.read())
        if response.status != 200:
            raise ValueError('WEB_JOB_UNAVAILABLE')
        stored=body['storage']
        if stored['status'] != 'SAVED' or stored['receipt']['manifest_sha256'] != receipt['manifest_sha256']:
            raise ValueError('WEB_SAVED_MANIFEST_DIFFERS')
        return body
