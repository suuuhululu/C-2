"""PR #38의 관리 파일 계약을 읽는 HMI 어댑터. 계산·로봇 실행은 하지 않는다."""
import asyncio
import json
import math
from uuid import UUID


class ArtifactLoadError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, message, code='VALIDATION_FAILED'):
    if not condition:
        raise ArtifactLoadError(code, message)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class PathArtifactLoader:
    """공유 assets의 ID·종류·바이트 해시·경로 연결을 검증한 메타데이터 반환.

    path_id는 파일 UUID가 아니다. 논리 경로 ID/버전에 대응하는 유일한 path
    asset을 찾는다. path_versions 등록은 MonitorService의 성공 트랜잭션 책임이다.
    """
    def __init__(self, store):
        self.store = store

    async def __call__(self, goal, result):
        return await asyncio.to_thread(self.load, goal, result)

    def read(self, aid, kind, expected=None):
        try:
            require(str(UUID(aid)) == aid, '산출물 ID가 정규 UUID가 아닙니다.')
            rec = self.store.asset(aid)
            require(rec['kind'] == kind, f'산출물 종류 불일치: {kind}')
            require(rec['storage_key'] == f'{aid}.bin', '산출물 저장 경로 불일치')
            mime = 'image/svg+xml' if kind == 'svg' else 'application/json'
            require(rec['mime'] == mime, f'산출물 MIME 불일치: {kind}')
            raw = self.store.read_asset(aid, expected)
            require(len(raw) == rec['size_bytes'] and len(raw) > 0, '산출물 크기 불일치')
            return raw, rec
        except ArtifactLoadError:
            raise
        except KeyError as exc:
            raise ArtifactLoadError('ASSET_NOT_FOUND', '결과의 관리 파일 ID를 찾지 못했습니다.') from exc
        except (ValueError, OSError, TypeError) as exc:
            code = 'HASH_MISMATCH' if str(exc) == 'HASH_MISMATCH' else 'STORAGE_ERROR'
            raise ArtifactLoadError(code, f'결과 파일 검증 실패: {kind}') from exc

    def json(self, aid, kind, expected=None):
        raw, rec = self.read(aid, kind, expected)
        try:
            value = json.loads(raw)
            # NaN/Infinity와 객체가 아닌 JSON도 거절한다.
            json.dumps(value, allow_nan=False)
            require(isinstance(value, dict), '결과 JSON은 객체여야 합니다.')
            return value, rec
        except (ValueError, UnicodeError) as exc:
            raise ArtifactLoadError('VALIDATION_FAILED', '결과 JSON 형식이 올바르지 않습니다.') from exc

    def load(self, goal, result):
        try:
            return self._load(goal, result)
        except (KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ArtifactLoadError('VALIDATION_FAILED', '결과 파일의 필수 필드·자료형이 올바르지 않습니다.') from exc

    def _load(self, goal, result):
        require(result['success'] is True and result['validation_passed'] is True,
                '성공·검증 합격 결과만 경로로 등록합니다.')
        require(result['error_code'] == 'NONE', '성공 결과에 오류 코드가 있습니다.')
        pid, version = result['path_id'], result['path_version']
        require(type(version) is int and version >= 1, '경로 버전 불일치')
        require(finite(result['cut_length_m']) and result['cut_length_m'] > 0, '절삭 길이가 유효하지 않습니다.')
        with self.store.db() as db:
            rows = db.execute(
                "SELECT id FROM assets WHERE kind='path' AND json_extract(metadata,'$.path_id')=? "
                "AND json_extract(metadata,'$.path_version')=?", (pid, version)).fetchall()
        require(len(rows) == 1, '경로 ID/버전의 관리 파일을 유일하게 찾을 수 없습니다.')
        path, path_rec = self.json(rows[0]['id'], 'path', result['path_sha256'])
        preview, preview_rec = self.json(result['preview_asset_id'], 'preview')
        report, report_rec = self.json(result['validation_report_id'], 'validation')
        _, svg_rec = self.read(result['svg_asset_id'], 'svg')
        profile, _ = self.json(goal['profile_snapshot_id'], 'profile', goal['profile_sha256'])

        mode = goal['source_mode']
        require(mode in ('REAL', 'SIMULATION') and profile.get('source_mode') == mode, '설정/요청 모드 불일치', 'PROFILE_MISMATCH')
        require(type(path.get('test_only')) is bool, '경로 실행 용도 누락')
        allowed = path.get('real_execution_allowed', False)
        if mode == 'REAL':
            # 기존 /3는 config.real_preview에 용도를 기록한다. 원본을 수정하지 않는다.
            legacy = path.get('config', {}).get('real_preview', {})
            shown_legacy = preview.get('real_preview', {})
            if 'real_execution_allowed' not in path:
                require(path['test_only'] is True and legacy.get('real_execution_allowed') is False
                        and shown_legacy.get('real_execution_allowed') is False, 'REAL 실행 용도 누락')
            else:
                require(type(allowed) is bool and preview.get('real_execution_allowed') is allowed,
                        'REAL 경로/미리보기 실행 용도 불일치')
            require(not (path['test_only'] and allowed), '경로 실행 용도 모순')
            if allowed:
                require(profile.get('test_only') is False and profile.get('real_execution_allowed') is True,
                        '스냅샷과 실행 후보 용도 불일치', 'PROFILE_MISMATCH')
                require(not legacy.get('preview_only') and not shown_legacy.get('preview_only'), '미리보기 용도 모순')
        else:
            require(path['test_only'] is True, 'SIM 경로 시험 용도 불일치')
        for obj in (path, preview):
            for key, expected in {'schema_version': 2, 'source_mode': mode,
                                  'path_id': pid, 'path_version': version,
                                  'frame_id': profile['frame_id'], 'test_only': path['test_only']}.items():
                require(obj.get(key) == expected, f'{key} 연결 불일치')
        if mode == 'REAL':
            for key in ('profile_snapshot_id', 'profile_sha256'):
                require(report.get(key) == goal[key], 'REAL 보고서 스냅샷 불일치', 'PROFILE_MISMATCH')
        require(path['input'] == {k: goal[k] for k in ('asset_id', 'asset_sha256')}, '경로의 원본 이미지 불일치')
        config = path['config']
        for key in ('profile_snapshot_id', 'profile_sha256'):
            require(config[key] == goal[key] == preview[key], f'{key} 연결 불일치', 'PROFILE_MISMATCH')
        for key in ('workcell_id', 'workcell_version', 'tool_id', 'tool_version'):
            require(config[key] == profile[key], f'{key} 설정 불일치', 'PROFILE_MISMATCH')
        for name in ('tcp', 'load'):
            for suffix in ('id', 'version'):
                require(config[f'{name}_profile_{suffix}'] == profile[f'{name}_{suffix}'],
                        f'{name} 프로파일 불일치', 'PROFILE_MISMATCH')
        require(path['tool_id'] == goal['tool_id'] == profile['tool_id'], '도구 불일치')
        require(path['position_unit'] == 'm' and path['orientation'] == 'quaternion_xyzw', '경로 단위 불일치')
        require(preview['contract'] == 'c2-path-preview/1' and preview['render_only'] is True
                and preview['pose_reference'] == 'tool_tip', '미리보기 계약 불일치')
        for key in ('asset_id', 'asset_sha256'):
            require(preview[key] == goal[key], f'미리보기 {key} 불일치')
        require(preview['path_sha256'] == result['path_sha256'], '미리보기 경로 해시 불일치', 'HASH_MISMATCH')
        for rec in (preview_rec, report_rec, svg_rec):
            require(rec['metadata'].get('path_id') == pid, '산출물 묶음의 경로 ID 불일치')
        require(report['passed'] is True and not report['errors'] and not report['mapping_failures'],
                '실패·부분 누락 경로는 등록할 수 없습니다.')
        for key, expected in {'request_id': goal['request_id'], 'path_id': pid, 'path_version': version}.items():
            require(report[key] == expected, f'검증 보고서 {key} 불일치')
        require(path['validation'] == {'report_id': result['validation_report_id'], 'passed': True,
                                      'checks': report['checks'], 'not_checked': report['not_checked']},
                '경로와 검증 보고서가 다릅니다.')
        require(report['checks'] and all(c.get('passed') is True for c in report['checks']), '검증 항목 미통과')
        require(isinstance(report['not_checked'], list) and
                all(isinstance(c, str) for c in report['not_checked']), '미검사 항목 형식 불일치')

        segments = path['segments']
        require(type(result['segment_count']) is int and len(segments) == result['segment_count'] > 0,
                '경로 구간 수 불일치')
        require(report['stats']['build']['segment_count'] == len(segments) and
                report['stats']['build']['cut_length_m'] == result['cut_length_m'], '결과 통계 불일치')
        require(len(preview['segments']) == len(segments), '미리보기 구간 누락')
        require(len({s['segment_id'] for s in segments}) == len(segments), '경로 구간 ID 중복')
        require(any(s['kind'] == 'CUT' for s in segments), '절삭 구간이 없습니다.')
        surface = profile['surface']
        origin = surface['axis_origin_m']
        require(all(finite(surface.get(k)) and surface[k] > 0 for k in ('radius_mm', 'height_mm')),
                '표면 반지름·높이는 유한 양수여야 합니다.')
        require(isinstance(origin, list) and len(origin) == 3 and all(finite(v) for v in origin),
                '축 원점은 유한 XYZ 좌표여야 합니다.')
        limits = surface.get('valid_v_range_mm')
        require(isinstance(limits, list) and len(limits) == 2 and all(finite(v) for v in limits)
                and limits[0] < limits[1], '표면 유효 높이 범위가 올바르지 않습니다.')
        require(finite(surface.get('u_origin_angle_deg')), '표면 기준 각도가 올바르지 않습니다.')
        require(surface['axis_direction'] == [0.0, 0.0, 1.0], '현재 미리보기는 +Z 원통 축만 지원합니다.')
        for segment, shown in zip(segments, preview['segments']):
            require(segment['kind'] in ('APPROACH', 'CUT', 'TRAVEL', 'RETRACT'), '미지원 구간 종류')
            points = segment['waypoints']
            require(len(points) >= 2 and all(len(p) == 7 and all(finite(v) for v in p) for p in points),
                    '경로 waypoint 형식 불일치')
            for key in ('segment_id', 'stroke_id', 'kind', 'split_from_stroke_id', 'split_index', 'split_count', 'join_forbidden'):
                require(shown.get(key) == segment.get(key), f'미리보기 {key} 불일치')
            require(shown['connect_to_next'] is False, '분리 구간을 임의로 연결할 수 없습니다.')
            require(shown['points_m'] == [p[:3] for p in points], '미리보기 좌표와 경로가 다릅니다.')
            if segment['kind'] == 'CUT':
                uv = shown['points_uv_mm']
                require(len(uv) == len(points), '전개면 점 개수 불일치')
                for p, q in zip(points, uv):
                    require(len(q) == 2 and all(finite(v) for v in q), '전개면 좌표 형식 불일치')
                    theta = math.atan2(p[1] - origin[1], p[0] - origin[0])
                    expected = [(theta - math.radians(surface['u_origin_angle_deg'])) * surface['radius_mm'],
                                (p[2] - origin[2]) * 1000]
                    require(all(abs(a - b) <= 1e-5 for a, b in zip(q, expected)), '전개면과 3D 경로 좌표 불일치')

        blocked = next((obj.get('execution_readiness', {}).get('execution_blocked') for obj in (report, preview, path) if obj.get('execution_readiness', {}).get('execution_blocked')), None)
        blocked_code = blocked.get('code') if isinstance(blocked, dict) else blocked
        require(blocked is None or isinstance(blocked_code, str) and bool(blocked_code), '실행 제한 형식 오류')
        return {**result, 'path_asset_id': path_rec['id'], 'input': dict(goal),
                'profile_snapshot_id': goal['profile_snapshot_id'], 'profile_sha256': goal['profile_sha256'],
                'profile_snapshot': {'id': goal['profile_snapshot_id'], 'sha256': goal['profile_sha256'], 'payload': profile},
                'source_mode': mode, 'test_only': path['test_only'], 'real_execution_allowed': allowed,
                'validation_not_checked': report['not_checked'],
                'execution_precheck': report.get('execution_readiness', {}).get('precheck'),
                'execution_blocked': blocked_code,
                'execution_block_message': blocked.get('message', '') if isinstance(blocked, dict) else '',
                'artifact_sha256': {r['id']: r['sha256'] for r in (path_rec, preview_rec, report_rec, svg_rec)}}
