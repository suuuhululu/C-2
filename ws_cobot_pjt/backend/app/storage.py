"""새 모니터 전용 SQLite와 관리 파일. 기존 saegim.sqlite3는 열지 않는다."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .monitor_contract import now, uid


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Storage:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.files = self.root / 'assets'
        self.files.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / 'monitor.sqlite3'
        with self.db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError('지원하지 않는 모니터 DB 버전입니다.')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS assets (
              id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, kind TEXT NOT NULL,
              storage_key TEXT NOT NULL UNIQUE, mime TEXT NOT NULL, name TEXT NOT NULL,
              size_bytes INTEGER NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS profile_snapshots (
              id TEXT PRIMARY KEY REFERENCES assets(id), sha256 TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS path_generations (
              request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
              result TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS path_versions (
              path_id TEXT NOT NULL, version INTEGER NOT NULL, sha256 TEXT NOT NULL,
              asset_id TEXT NOT NULL REFERENCES assets(id), generation_id TEXT NOT NULL REFERENCES path_generations(request_id),
              payload TEXT NOT NULL, PRIMARY KEY(path_id, version));
            CREATE TABLE IF NOT EXISTS command_requests (
              request_id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
              response TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE REFERENCES command_requests(request_id),
              path_id TEXT NOT NULL, path_version INTEGER NOT NULL, state TEXT NOT NULL,
              payload TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY(path_id,path_version) REFERENCES path_versions(path_id,version));
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY, run_id TEXT, event_type TEXT NOT NULL,
              occurred_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alarms (
              id TEXT PRIMARY KEY REFERENCES events(event_id), active INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inspections (
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
              verdict TEXT NOT NULL CHECK(verdict IN ('PASS','HOLD','REJECT')),
              reason TEXT NOT NULL, inspector TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_run ON events(run_id,occurred_at);
            CREATE INDEX IF NOT EXISTS runs_time ON runs(created_at);
            PRAGMA user_version=1;
            ''')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=.25)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def put_asset(self, data, kind, mime, name, metadata=None, asset_id=None):
        aid = asset_id or uid()
        key = f'{aid}.bin'
        target = self.files / key
        if target.exists():
            raise ValueError('관리 파일은 덮어쓸 수 없습니다.')
        temp = self.files / f'{aid}.tmp'
        with temp.open('xb') as f:
            f.write(data)
        temp.replace(target)
        record = dict(id=aid, sha256=digest(data), kind=kind, mime=mime, name=name,
                      size_bytes=len(data), metadata=metadata or {}, created_at=now())
        try:
            with self.db() as c:
                c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)',
                          (aid, record['sha256'], kind, key, mime, name, len(data),
                           encoded(record['metadata']).decode(), record['created_at']))
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return record

    def put_json(self, value, kind, name):
        return self.put_asset(encoded(value), kind, 'application/json', name)

    def asset(self, aid):
        with self.db() as c:
            row = c.execute('SELECT * FROM assets WHERE id=?', (aid,)).fetchone()
        if not row:
            raise KeyError(aid)
        result = dict(row)
        result['metadata'] = json.loads(result['metadata'])
        return result

    def read_asset(self, aid, expected=None):
        rec = self.asset(aid)
        path = (self.files / rec['storage_key']).resolve()
        if path.parent != self.files:
            raise ValueError('잘못된 관리 파일 경로')
        data = path.read_bytes()
        if digest(data) != rec['sha256'] or (expected and expected != rec['sha256']):
            raise ValueError('HASH_MISMATCH')
        return data

    def profile(self, value):
        raw = encoded(value)
        with self.db() as c:
            row = c.execute('SELECT * FROM profile_snapshots WHERE sha256=?', (digest(raw),)).fetchone()
        if row:
            return dict(id=row['id'], sha256=row['sha256'], payload=json.loads(row['payload']))
        a = self.put_asset(raw, 'profile', 'application/json', 'simulation-profile.json')
        with self.db() as c:
            c.execute('INSERT INTO profile_snapshots VALUES (?,?,?)', (a['id'], a['sha256'], raw.decode()))
        return dict(id=a['id'], sha256=a['sha256'], payload=value)

    def generation(self, request_id):
        with self.db() as c:
            r = c.execute('SELECT * FROM path_generations WHERE request_id=?', (request_id,)).fetchone()
        return None if not r else {**dict(r), 'payload': json.loads(r['payload']), 'result': json.loads(r['result']) if r['result'] else None}

    def create_generation(self, goal):
        with self.db() as c:
            c.execute('INSERT INTO path_generations VALUES (?,?,?,?,?)',
                      (goal['request_id'], encoded(goal).decode(), 'ACCEPTED', None, now()))

    def finish_generation(self, request_id, state, result, path=None):
        with self.db() as c:
            if path:
                c.execute('INSERT INTO path_versions VALUES (?,?,?,?,?,?)',
                          (path['path_id'], path['path_version'], path['path_sha256'], path['path_asset_id'],
                           request_id, encoded(path).decode()))
            c.execute('UPDATE path_generations SET state=?,result=? WHERE request_id=?',
                      (state, encoded(result).decode(), request_id))

    def path(self, path_id, version):
        with self.db() as c:
            r = c.execute('SELECT payload FROM path_versions WHERE path_id=? AND version=?', (path_id, version)).fetchone()
        if not r:
            raise KeyError(path_id)
        return json.loads(r[0])

    def request(self, request_id):
        with self.db() as c:
            r = c.execute('SELECT * FROM command_requests WHERE request_id=?', (request_id,)).fetchone()
        return None if not r else {**dict(r), 'payload': json.loads(r['payload']), 'response': json.loads(r['response'])}

    def stop_requests(self):
        with self.db() as c:
            return {r['request_id']: {'payload': json.loads(r['payload']), 'response': json.loads(r['response'])}
                    for r in c.execute("SELECT * FROM command_requests WHERE kind='STOP'")}

    def save_stop(self, payload, response):
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO command_requests VALUES (?,?,?,?,?)',
                      (payload['request_id'], 'STOP', encoded(payload).decode(), encoded(response).decode(), now()))

    def reserve_run(self, body, run):
        with self.db() as c:
            c.execute('INSERT INTO command_requests VALUES (?,?,?,?,?)',
                      (body['request_id'], 'START', encoded(body).decode(), encoded(run).decode(), now()))
            c.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',
                      (run['run_id'], body['request_id'], body['path_id'], body['path_version'],
                       run['status'], encoded(run).decode(), now()))

    def save_run(self, run):
        with self.db() as c:
            c.execute('UPDATE runs SET state=?,payload=? WHERE run_id=?',
                      (run['status'], encoded(run).decode(), run['run_id']))

    def run(self, run_id):
        with self.db() as c:
            r = c.execute('SELECT payload FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if not r:
            raise KeyError(run_id)
        return json.loads(r[0])

    def runs(self):
        with self.db() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT payload FROM runs ORDER BY created_at DESC LIMIT 100')]

    def recover(self):
        with self.db() as c:
            c.execute("UPDATE path_generations SET state='FAILED',result=? WHERE state IN ('ACCEPTED','CANCELING','UNKNOWN')",
                      (encoded(dict(success=False,error_code='COMMUNICATION_LOST',message='서버 재시작으로 생성 결과 미확인')).decode(),))
        active = None
        for run in self.runs():
            if run['status'] in ('ACCEPTED','RUNNING','STOPPING','UNKNOWN'):
                run.update(status='UNKNOWN', stop_state='UNKNOWN', error_code='COMMUNICATION_LOST',
                           message='이전 실행 결과 미확인. 자동 재실행하지 않습니다.')
                self.save_run(run)
                active = active or run
        return active

    def event(self, event):
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)',
                      (event['event_id'], event.get('run_id'), event['event_type'], event['occurred_at'], encoded(event).decode()))
            if event['event_type'] == 'ALARM_RAISED':
                c.execute('INSERT OR IGNORE INTO alarms VALUES (?,?,?)', (event['event_id'], 1, encoded(event).decode()))

    def events(self, run_id=None):
        with self.db() as c:
            rows = c.execute('SELECT payload FROM events WHERE (? IS NULL OR run_id=?) ORDER BY occurred_at DESC LIMIT 100',
                             (run_id, run_id))
            return [json.loads(r[0]) for r in rows]

    def alarms(self):
        with self.db() as c:
            return [{**json.loads(r['payload']), 'active': bool(r['active'])} for r in c.execute('SELECT * FROM alarms')]

    def inspect(self, body, inspector):
        rec = dict(id=uid(), **body, inspector=inspector, created_at=now())
        with self.db() as c:
            c.execute('INSERT INTO inspections VALUES (?,?,?,?,?,?)',
                      tuple(rec[k] for k in ('id','run_id','verdict','reason','inspector','created_at')))
        return rec

    def inspections(self, run_id):
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT * FROM inspections WHERE run_id=? ORDER BY created_at DESC', (run_id,))]
