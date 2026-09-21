"""HMI SIM 파일 교환. ROS 타입·공정 설정을 변경하거나 로봇을 호출하지 않는다."""
import io
import json
import os
import re
import stat
import tempfile
import zipfile
import zlib
from uuid import UUID

from pydantic import ValidationError

from .artifact_loader import ArtifactLoadError, PathArtifactLoader, require
from .monitor_contract import GenerateInput, now, uid
from .storage import Storage, digest, encoded


FORMAT = 'c2-hmi-bundle/1'
MAX_PROFILE = 1024 * 1024
MAX_ZIP = 32 * 1024 * 1024
MAX_UNPACKED = 64 * 1024 * 1024
KINDS = {'image', 'profile', 'path', 'svg', 'preview', 'validation'}
MIMES = {'profile': 'application/json', 'path': 'application/json',
         'svg': 'image/svg+xml', 'preview': 'application/json', 'validation': 'application/json'}


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('중복 JSON 필드')
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('비유한 수치')))
        require(isinstance(value, dict), 'JSON 최상위는 객체여야 합니다.')
        encoded(value)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, ArtifactLoadError):
            raise
        raise ArtifactLoadError('INVALID_INPUT', '중복 필드·비유한 수치가 없는 JSON 객체를 사용하세요.') from exc


def valid_uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def profile_payload(raw):
    require(len(raw) <= MAX_PROFILE, '스냅샷은 1 MiB 이하여야 합니다.')
    value = strict_json(raw)
    require(type(value.get('schema_version')) is int and value['schema_version'] == 2,
            'schema_version=2 스냅샷을 사용하세요.')
    require(value.get('source_mode') == 'SIMULATION', 'SIMULATION 스냅샷만 등록할 수 있습니다.')
    for key in ('allow_real', 'real_execution_allowed'):
        require(key not in value or value[key] is False, '실기 허용 스냅샷은 등록할 수 없습니다.')
    require('test_only' not in value or value['test_only'] is True, 'test_only=false 스냅샷은 지원하지 않습니다.')
    require('profile_snapshot_id' not in value and 'profile_sha256' not in value,
            '자기 자신의 ID·해시는 JSON 본문 대신 등록 정보로 전달하세요.')
    return value


def goal_payload(value):
    try:
        goal = GenerateInput.model_validate(value).model_dump(mode='json')
    except (ValidationError, ValueError) as exc:
        raise ArtifactLoadError('INVALID_INPUT', 'GeneratePath 요청의 필드·자료형·범위를 확인하세요.') from exc
    require(goal['conversion_preset'] == 'raster_centerline_bezier',
            '파일 교환은 실제 이미지 변환 preset인 raster_centerline_bezier를 사용합니다.')
    return goal


def result_payload(value):
    keys = {'success', 'error_code', 'message', 'path_id', 'path_version', 'path_sha256',
            'svg_asset_id', 'preview_asset_id', 'segment_count', 'cut_length_m',
            'validation_passed', 'validation_report_id'}
    require(set(value) == keys, 'result.json에는 GeneratePath Result 전체 필드만 넣으세요.')
    require(value['success'] is True and value['validation_passed'] is True,
            '실패 결과는 미리보기 경로로 가져올 수 없습니다.')
    require(value['error_code'] == 'NONE' and isinstance(value['message'], str), '성공 결과 형식 불일치')
    for key in ('path_id', 'svg_asset_id', 'preview_asset_id', 'validation_report_id'):
        require(valid_uuid(value[key]), f'{key}는 정규 UUID여야 합니다.')
    require(valid_sha(value['path_sha256']), 'path_sha256 형식 불일치')
    return value


class FileIntegration:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS integration_selection (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                profile_id TEXT NOT NULL REFERENCES profile_snapshots(id))''')

    def profiles(self):
        with self.store.db() as db:
            rows = db.execute('''SELECT p.id,p.sha256,p.payload FROM profile_snapshots p
                JOIN assets a ON a.id=p.id ORDER BY a.created_at DESC''').fetchall()
            selected = db.execute('SELECT profile_id FROM integration_selection WHERE singleton=1').fetchone()
        return dict(items=[dict(id=r['id'], sha256=r['sha256'], payload=json.loads(r['payload'])) for r in rows],
                    selected_id=selected[0] if selected else None,
                    contract_validation='PENDING', source_mode='SIMULATION')

    def register_profile(self, raw):
        value = profile_payload(raw)
        registered = self.store.profile(value)
        # 재등록도 실제 저장 파일을 검증한다. DB 해시만 믿지 않는다.
        self.store.read_asset(registered['id'], registered['sha256'])
        self.select_profile(registered['id'])
        return registered

    def select_profile(self, pid):
        require(valid_uuid(pid), '스냅샷 ID 형식 불일치')
        with self.store.db() as db:
            row = db.execute('SELECT sha256 FROM profile_snapshots WHERE id=?', (pid,)).fetchone()
            require(row is not None, '등록된 스냅샷을 선택하세요.', 'ASSET_NOT_FOUND')
            profile_payload(self.store.read_asset(pid, row['sha256']))
            db.execute('INSERT INTO integration_selection VALUES (1,?) '
                       'ON CONFLICT(singleton) DO UPDATE SET profile_id=excluded.profile_id', (pid,))
        return dict(selected_id=pid)

    def _inputs(self, goal):
        records = []
        for aid, expected, kind in ((goal['asset_id'], goal['asset_sha256'], 'image'),
                                    (goal['profile_snapshot_id'], goal['profile_sha256'], 'profile')):
            rec = self.store.asset(aid)
            require(rec['kind'] == kind, f'입력 파일 종류 불일치: {kind}')
            raw = self.store.read_asset(aid, expected)
            if kind == 'profile':
                profile_payload(raw)
            else:
                require(rec['mime'] in ('image/png', 'image/jpeg'), 'PNG/JPEG 입력만 지원합니다.')
            records.append((rec, raw))
        return records

    def prepare_input(self, value):
        goal = goal_payload(value)
        require(self.profiles()['selected_id'] == goal['profile_snapshot_id'],
                '파일 통합 시험에서 선택한 스냅샷과 다릅니다.', 'PROFILE_MISMATCH')
        self._inputs(goal)
        with self.store.db() as db:
            old = db.execute('SELECT payload,state FROM path_generations WHERE request_id=?',
                             (goal['request_id'],)).fetchone()
            if old:
                require(json.loads(old['payload']) == goal and old['state'] in ('EXPORTED', 'SUCCEEDED'),
                        '기존 생성 요청과 충돌합니다.', 'REQUEST_CONFLICT')
            else:
                db.execute('INSERT INTO path_generations VALUES (?,?,?,?,?)',
                           (goal['request_id'], encoded(goal).decode(), 'EXPORTED', None, now()))
        return dict(request_id=goal['request_id'], state='EXPORTED',
                    download_url=f'/api/operator/integration/inputs/{goal["request_id"]}')

    @staticmethod
    def _archive(goal, records, result=None):
        contents = {'goal.json': encoded(goal)}
        manifest = dict(format=FORMAT, source_mode='SIMULATION',
                        purpose='generation-result' if result else 'generation-input',
                        goal=dict(file='goal.json', sha256=digest(contents['goal.json'])), files=[])
        for rec, raw in records:
            kind = rec['kind']
            filename = {'image': 'input.png' if rec['mime'] == 'image/png' else 'input.jpg',
                        'profile': 'snapshot.json', 'path': 'path.json', 'svg': 'diagram.svg',
                        'preview': 'preview.json', 'validation': 'validation.json'}[kind]
            contents[filename] = raw
            manifest['files'].append(dict(asset_id=rec['id'], kind=kind, file=filename,
                                          sha256=digest(raw), mime=rec['mime'], metadata=rec['metadata']))
        if result:
            contents['result.json'] = encoded(result)
            manifest['result'] = dict(file='result.json', sha256=digest(contents['result.json']))
        contents['manifest.json'] = encoded(manifest)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in contents.items():
                archive.writestr(name, raw)
        return buffer.getvalue()

    def export_input(self, rid):
        record = self.store.generation(rid)
        require(record is not None and record['state'] in ('EXPORTED', 'SUCCEEDED'),
                '내보낸 생성 요청을 찾지 못했습니다.', 'ASSET_NOT_FOUND')
        goal = goal_payload(record['payload'])
        return self._archive(goal, self._inputs(goal))

    def paths(self):
        with self.store.db() as db:
            rows = db.execute('''SELECT payload FROM path_versions
                WHERE json_extract(payload,'$.origin')='FILE_BUNDLE' ORDER BY rowid DESC LIMIT 100''').fetchall()
        return [json.loads(r[0]) for r in rows]

    def export_path(self, pid, version):
        metadata = self.store.path(pid, version)
        require(metadata.get('origin') == 'FILE_BUNDLE', '파일로 가져온 경로를 선택하세요.')
        goal = metadata['input']
        generated = self.store.generation(goal['request_id'])
        PathArtifactLoader(self.store).load(goal, generated['result'])
        records = self._inputs(goal)
        for key in ('path_asset_id', 'svg_asset_id', 'preview_asset_id', 'validation_report_id'):
            aid = metadata[key]
            records.append((self.store.asset(aid), self.store.read_asset(aid, metadata['artifact_sha256'][aid])))
        return self._archive(goal, records, generated['result'])

    def import_bundle(self, raw):
        require(len(raw) <= MAX_ZIP, 'ZIP은 32 MiB 이하여야 합니다.')
        try:
            return self._import_archive(raw)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as exc:
            raise ArtifactLoadError('INVALID_INPUT', '읽을 수 있는 암호화되지 않은 ZIP을 사용하세요.') from exc

    def _import_archive(self, raw):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            require(len(names) <= 16 and len(names) == len(set(names)), '중복 파일 또는 파일 개수 초과')
            require(sum(i.file_size for i in infos) <= MAX_UNPACKED, '압축 해제 크기는 64 MiB 이하여야 합니다.')
            for info in infos:
                require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', info.filename) is not None,
                        'ZIP 최상위에 일반 파일만 넣으세요. 폴더·절대 경로는 지원하지 않습니다.')
                require(not stat.S_ISLNK(info.external_attr >> 16) and not info.flag_bits & 1,
                        '링크·암호화된 파일은 지원하지 않습니다.')
            require('manifest.json' in names, 'manifest.json이 없습니다.')
            require(archive.getinfo('manifest.json').file_size <= MAX_PROFILE, '파일 목록 크기 초과')
            manifest = strict_json(archive.read('manifest.json'))
            require(manifest.get('format') == FORMAT and manifest.get('source_mode') == 'SIMULATION'
                    and manifest.get('purpose') == 'generation-result', 'HMI 결과 묶음 계약이 다릅니다.')
            used = {'manifest.json'}

            def read(entry):
                require(isinstance(entry, dict), '파일 목록 항목은 객체여야 합니다.')
                filename = entry.get('file')
                require(isinstance(filename, str) and filename in names and filename not in used,
                        '파일 누락 또는 중복 참조')
                require(valid_sha(entry.get('sha256')), '파일 해시 형식 불일치')
                data = archive.read(filename)
                require(digest(data) == entry['sha256'], f'파일 해시 불일치: {filename}', 'HASH_MISMATCH')
                used.add(filename)
                return data

            goal = goal_payload(strict_json(read(manifest.get('goal'))))
            result = result_payload(strict_json(read(manifest.get('result'))))
            previous = self.store.generation(goal['request_id'])
            require(previous is not None and previous['payload'] == goal
                    and previous['state'] in ('EXPORTED', 'SUCCEEDED'),
                    'HMI에서 내보낸 입력 요청과 일치하지 않습니다.', 'REQUEST_CONFLICT')
            inputs = self._inputs(goal)
            files = manifest.get('files')
            require(isinstance(files, list) and len(files) == 6, '입력 2개와 산출물 4개가 필요합니다.')
            entries, ids, kinds = [], set(), set()
            for entry in files:
                data = read(entry)
                aid, kind = entry.get('asset_id'), entry.get('kind')
                require(valid_uuid(aid) and aid not in ids, '파일 ID 누락·중복·형식 오류')
                require(isinstance(kind, str) and kind in KINDS and kind not in kinds, '파일 종류 누락·중복')
                require(isinstance(entry.get('metadata'), dict), '파일 metadata 객체가 필요합니다.')
                require(entry.get('mime') in ('image/png', 'image/jpeg') if kind == 'image'
                        else entry.get('mime') == MIMES[kind], '파일 MIME 불일치')
                if kind in ('profile', 'path', 'preview', 'validation'):
                    strict_json(data)
                ids.add(aid); kinds.add(kind)
                entries.append((entry, data))
            require(used == set(names), '목록에 없는 파일이 있습니다.')
        for rec, expected in inputs:
            candidates = [(e, data) for e, data in entries if e['kind'] == rec['kind']]
            entry, data = candidates[0]
            require(entry['asset_id'] == rec['id'] and data == expected
                    and entry['metadata'] == rec['metadata'] and entry['mime'] == rec['mime'],
                    'HMI가 등록한 입력 파일과 다릅니다.', 'PROFILE_MISMATCH')
        # 기존 로더로 먼저 격리 검증한다. 실패 묶음은 운영 DB/파일에 쓰지 않는다.
        with tempfile.TemporaryDirectory(prefix='c2-bundle-') as directory:
            stage = Storage(directory)
            for entry, data in entries:
                stage.put_asset(data, entry['kind'], entry['mime'], entry['file'],
                                entry['metadata'], asset_id=entry['asset_id'])
            metadata = PathArtifactLoader(stage).load(goal, result)
        metadata.update(origin='FILE_BUNDLE', bundle_sha256=digest(raw), execution_enabled=False)
        return self._commit(goal, result, metadata, entries)

    def _commit(self, goal, result, metadata, entries):
        created = []
        try:
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT payload,state,result FROM path_generations WHERE request_id=?',
                                 (goal['request_id'],)).fetchone()
                require(old is not None and json.loads(old['payload']) == goal
                        and old['state'] in ('EXPORTED', 'SUCCEEDED'), '생성 요청이 변경됐습니다.', 'REQUEST_CONFLICT')
                if old['state'] == 'SUCCEEDED':
                    path = db.execute('SELECT payload FROM path_versions WHERE generation_id=?',
                                      (goal['request_id'],)).fetchone()
                    require(path is not None and json.loads(old['result']) == result,
                            '같은 요청 ID에 다른 결과가 있습니다.', 'REQUEST_CONFLICT')
                    existing = json.loads(path[0])
                    require(existing.get('origin') == 'FILE_BUNDLE'
                            and existing['artifact_sha256'] == metadata['artifact_sha256'],
                            '등록된 결과와 파일이 다릅니다.', 'REQUEST_CONFLICT')
                else:
                    existing = None
                    require(db.execute('SELECT 1 FROM path_versions WHERE path_id=? AND version=?',
                                       (result['path_id'], result['path_version'])).fetchone() is None,
                            '이미 등록된 경로 ID·버전입니다.', 'REQUEST_CONFLICT')
                for entry, data in entries:
                    aid = entry['asset_id']
                    rec = db.execute('SELECT * FROM assets WHERE id=?', (aid,)).fetchone()
                    if rec:
                        require(rec['sha256'] == entry['sha256'] and rec['kind'] == entry['kind']
                                and rec['mime'] == entry['mime'] and json.loads(rec['metadata']) == entry['metadata'],
                                '기존 파일 ID와 내용·종류·메타데이터가 충돌합니다.', 'ASSET_CONFLICT')
                        require(self.store.read_asset(aid, entry['sha256']) == data, '기존 파일 내용 불일치', 'HASH_MISMATCH')
                        continue
                    require(existing is None, '기존 결과의 파일이 누락됐습니다.', 'ASSET_NOT_FOUND')
                    # path_id/version으로 파일을 찾는 기존 로더의 유일성을 보존한다.
                    if entry['kind'] == 'path':
                        require(db.execute("SELECT 1 FROM assets WHERE kind='path' AND json_extract(metadata,'$.path_id')=? "
                                           "AND json_extract(metadata,'$.path_version')=?",
                                           (result['path_id'], result['path_version'])).fetchone() is None,
                                '경로 ID·버전의 파일이 이미 존재합니다.', 'ASSET_CONFLICT')
                    target = self.store.files / f'{aid}.bin'
                    temporary = self.store.files / f'.{uid()}.tmp'
                    try:
                        temporary.write_bytes(data)
                        os.link(temporary, target)  # 기존 파일은 덮어쓰지 않는다.
                        created.append(target)
                    except FileExistsError as exc:
                        raise ArtifactLoadError('ASSET_CONFLICT', '기존 파일과 저장 위치가 충돌합니다.') from exc
                    finally:
                        temporary.unlink(missing_ok=True)
                    db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?)',
                               (aid, entry['sha256'], entry['kind'], target.name, entry['mime'], entry['file'],
                                len(data), encoded(entry['metadata']).decode(), now()))
                if existing:
                    return existing
                db.execute('INSERT INTO path_versions VALUES (?,?,?,?,?,?)',
                           (result['path_id'], result['path_version'], result['path_sha256'], metadata['path_asset_id'],
                            goal['request_id'], encoded(metadata).decode()))
                db.execute("UPDATE path_generations SET state='SUCCEEDED',result=? WHERE request_id=?",
                           (encoded(result).decode(), goal['request_id']))
            return metadata
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
