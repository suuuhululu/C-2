"""HMI 준비 원장. 측정 신뢰도는 보존하고 BIND와 실행 검사는 공정에 요청한다."""
import asyncio
import json
import math
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .monitor_contract import now, uid
from .storage import digest, encoded

ACTIVE = {'ACCEPTED', 'RUNNING', 'CANCELING', 'UNKNOWN'}


def real_input_config(store, filename):
    """운영자가 명시한 기존 계약의 현장 원본만 등록. SIM/과거 파일 자동 승격 금지."""
    if not filename:
        raise ValueError('REAL 준비는 C2_PREPARATION_CONFIG의 확인된 현장 설정 파일이 필요합니다.')
    raw = Path(filename).expanduser().read_bytes()
    value = json.loads(raw)
    # 명시 선택한 시율 원본에는 Action 봉투만 붙인다. 좌표/힘/속도/시간은 변경하지 않는다.
    if 'contract' not in value and value.get('workcell', {}).get('source_mode') == 'REAL':
        store.put_asset(raw, 'preparation_source', 'application/json', Path(filename).name)
        value.update(contract='prepare-workpiece-config/1', source_mode='REAL', tool_id='engraving_drill',
                     tcp_id=value['workcell'].get('tcp_id'), load_id=value['workcell'].get('load_id'))
        raw = encoded(value)
    if (value.get('contract') != 'prepare-workpiece-config/1' or value.get('source_mode') != 'REAL'
            or value.get('tool_id') != 'engraving_drill' or value.get('tcp_id') != 'GripperDA_v1'
            or not isinstance(value.get('load_id'), str) or not value['load_id'].strip()
            or not isinstance(value.get('controller_prefix'), str) or not value['controller_prefix'].startswith('/')):
        raise ValueError('REAL 설정의 계약·도구·TCP·하중·controller_prefix를 확인하세요.')
    w = value.get('workcell', {})
    if (w.get('source_mode') != 'REAL' or w.get('frame_id') != 'c2_base'
            or w.get('height_source') != 'OPERATOR_RULER' or not isinstance(value.get('profiles'), dict)):
        raise ValueError('REAL workcell/profiles/높이 출처를 확인하세요.')
    for key in ('height_m', 'runtime_timeout_s'):
        n = w.get(key)
        if type(n) not in (int, float) or not math.isfinite(n) or n <= 0:
            raise ValueError(f'REAL 설정의 {key} 오류')
    execution_file = os.getenv('C2_EXECUTION_PROFILE')
    if execution_file:
        execution_raw = Path(execution_file).expanduser().read_bytes()
        execution = json.loads(execution_raw)
        if not isinstance(execution, dict):
            raise ValueError('REAL 실행 설정은 JSON 객체여야 합니다.')
        store.put_asset(execution_raw, 'execution_profile_source', 'application/json', Path(execution_file).name)
        value['execution_profile'] = execution
        raw = encoded(value)
    encoded(value)  # 비유한 JSON 거절. 저장은 재직렬화하지 않고 원본 바이트 사용.
    sha = digest(raw)
    with store.db() as db:
        row = db.execute("SELECT id FROM assets WHERE kind='preparation_config' AND sha256=?", (sha,)).fetchone()
    aid = row['id'] if row else store.put_asset(raw, 'preparation_config', 'application/json', 'real-preparation-config.json')['id']
    store.read_asset(aid, sha)
    return dict(id=aid, sha256=sha, payload=value)


def input_config(store, ros_profile=None):
    source = Path(__file__).resolve().parents[2] / 'ws_cobot1/src/c2_process/config/workpiece_simulation.json'
    value = json.loads(source.read_text())
    value.update(contract='hmi-preparation-sim/1', source_mode='SIMULATION',
                 real_execution_allowed=False, tool_id='engraving_drill', tcp_id='GripperDA_v1',
                 load_id='SIMULATION_ONLY', origin='HMI_MOCK_FIXTURE')
    if ros_profile is not None:
        value.update(contract='prepare-workpiece-config/1', origin='ROS_SIM_FIXTURE')
        for key in ('tool_id', 'tcp_id', 'load_id', 'tool_version', 'tcp_version', 'load_version',
                    'tools_config_id', 'tools_config_version'):
            value[key] = ros_profile[key]
    if os.getenv('C2_VIRTUAL_CELL') == '1':
        from c2_process.virtual_cell import simulation_settings
        value['virtual_device'] = simulation_settings()
    sha = digest(encoded(value))
    with store.db() as db:
        row = db.execute("SELECT id FROM assets WHERE kind='preparation_config' AND sha256=?", (sha,)).fetchone()
    aid = row['id'] if row else store.put_json(value, 'preparation_config', 'preparation-sim-config.json')['id']
    store.read_asset(aid, sha)
    return dict(id=aid, sha256=sha, payload=value)


def measured_profile(base, goal, result):
    """성공한 측정 기하를 바닥 기준 프로파일로 조립. 경로 계산/모션은 하지 않는다."""
    observed = result['observed_state']
    m = observed['measurement']
    if (result['outcome'] != 'SUCCEEDED' or result['error_code'] != 'NONE'
            or observed.get('partial') is not False or observed.get('stop_confirmed') is not True
            or m.get('geometry_ready') is not True or m.get('validity') not in (('SIMULATED',) if goal['source_mode'] == 'SIMULATION' else ('ESTIMATED', 'FORCE_CONTACT_ESTIMATE'))):
        raise ValueError('기하·측정 완료·정상 후퇴 확인이 모두 필요합니다.')
    expected = dict(preparation_id=goal['preparation_id'], measurement_id=goal['measurement_id'],
                    profile_snapshot_id=goal['input_profile_snapshot_id'], profile_sha256=goal['input_profile_sha256'],
                    source_mode=goal['source_mode'], frame_id='c2_base', position_unit='m', height_source='OPERATOR_RULER')
    if any(m.get(k) != v for k, v in expected.items()):
        raise ValueError('측정 ID·설정·모드·단위 연결이 다릅니다.')
    def number(v):
        if type(v) not in (int, float) or not math.isfinite(v):
            raise ValueError('측정값 누락 또는 비유한 수치')
        return v
    h, r, top = (number(m.get(k)) for k in ('height_m', 'radius_m', 'top_z_m'))
    xy = m.get('axis_xy_m')
    vr = m.get('work_v_range_m')
    zr = m.get('work_z_range_m')
    if not isinstance(xy, list) or len(xy) != 2 or not isinstance(vr, list) or len(vr) != 2:
        raise ValueError('중심·작업 범위 형식 불일치')
    xy = [number(v) for v in xy]
    lo, hi = [number(v) for v in vr]
    if not (h > 0 and r > 0 and 0 <= lo < hi <= h and math.isclose(h, goal['height_m'], abs_tol=1e-9)):
        raise ValueError('높이·반지름·작업 범위 불일치')
    bottom = top - h
    if not math.isclose(number(m.get('bottom_z_m')), bottom, abs_tol=1e-9):
        raise ValueError('윗면−높이와 바닥 Z가 다릅니다.')
    if not isinstance(zr, list) or len(zr) != 2 or any(
            not math.isclose(number(v), expected_z, abs_tol=1e-9)
            for v, expected_z in zip(zr, (top-hi, top-lo))):
        raise ValueError('윗면 기준 작업 범위와 base Z 범위가 다릅니다.')
    stamp = datetime.fromisoformat(m['measured_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('측정 완료 시각의 시간대가 없습니다.')
    points = m.get('points')
    if not isinstance(points, list) or len(points) != 8 or {p.get('point_index') for p in points} != set(range(1, 9)):
        raise ValueError('옆면 8점 원본이 없습니다.')
    if m.get('vertical_axis_assumed') is not True or m.get('tilt_measured') is not False:
        raise ValueError('수직 원통 가정·미측정 기울기 표시가 필요합니다.')
    profile = deepcopy(base)
    profile.update(label='양초 준비·측정 모의 결과', measurement_id=m['measurement_id'],
                   preparation_id=m['preparation_id'], measured_at=m['measured_at'],
                   measurement_status=m['validity'],
                   measurement_assumptions={k: m[k] for k in ('vertical_axis_assumed', 'tilt_measured', 'independent_accuracy_verified')},
                   note='HMI MOCK 합성 측정입니다. 제어 Action·실기 측정·관절 검증 완료가 아닙니다.')
    profile['surface'].update(radius_mm=r*1000, height_mm=h*1000,
        axis_origin_m=[*xy, bottom], axis_direction=[0, 0, 1], u_origin_angle_deg=0,
        height_reference='bottom', v_direction='up',
        valid_v_range_mm=[round((h-hi)*1000, 9), round((h-lo)*1000, 9)],
        v_range_mm=[0, h*1000], u_range_mm=[-math.pi*r*1000, math.pi*r*1000])
    return profile


class PreparationService:
    def __init__(self, owner):
        self.owner = owner
        self.current = None
        self.config = None
        self.cancel = None
        self.task = None
        self.save_lock = asyncio.Lock()
        self.timeout_s = 300.0  # 모의 설정과 맞춤. 실기 정지 제한 시간이 아님.
        self.cancel_timeout_s = 5.0

    async def start(self):
        if getattr(self.owner, 'mode', 'SIMULATION') == 'REAL':
            self.config = await asyncio.to_thread(real_input_config, self.owner.store, os.getenv('C2_PREPARATION_CONFIG'))
            self.timeout_s = self.config['payload']['workcell']['runtime_timeout_s']
            self.current = await asyncio.to_thread(self.owner.store.recover_preparation)
        elif self.owner.transport == 'mock' or os.environ.get('C2_ROS_PREPARATION_SIM') == '1' or getattr(self.owner, 'process_integration', False):
            base = self.owner.profile['payload'] if self.owner.transport == 'ros' or getattr(self.owner, 'image_workflow', False) else None
            self.config = await asyncio.to_thread(input_config, self.owner.store, base)
            self.timeout_s = self.config['payload']['workcell']['runtime_timeout_s']
            self.current = await asyncio.to_thread(self.owner.store.recover_preparation)

    def blocks_work(self):
        return bool(self.task and not self.task.done() or self.current and self.current['state'] in ACTIVE)

    def ready(self):
        r = self.current
        return bool(self.owner.fresh() and r and r['state'] == 'SUCCEEDED' and r.get('binding_status') in ('BOUND_MOCK', 'BOUND_ROS')
                    and r.get('profile_snapshot', {}).get('id') == self.owner.profile['id']
                    and r.get('profile_snapshot', {}).get('sha256') == self.owner.profile['sha256'])

    async def invalidate_connection(self):
        """제어 세션 변경/관측 연결 단절 뒤 이전 준비 승인을 복구하지 않는다."""
        if not self.current or self.current['state'] not in ACTIVE | {'SUCCEEDED'}:
            return
        running = self.current['state'] in ACTIVE
        if running and self.cancel:
            self.cancel.set()
        self.current.update(state='UNKNOWN' if running else 'INVALIDATED', binding_status='UNCONFIRMED',
                            error_code='COMMUNICATION_LOST', updated_at=now(),
                            message='공정 상태 연결이 변경되었습니다. 이전 준비를 재사용하지 않고 결과/정지를 확인하세요.')
        if self.owner.transport == 'mock':
            self.owner.peer.bound_preparation = None
        await self.save()

    def start_error(self):
        if getattr(self.owner, 'mode', 'SIMULATION') != 'REAL' or self.config is None:
            return None
        from .real_execution_config import validate_real_execution_config
        try:
            validate_real_execution_config(self.config['payload'])
        except (ValueError, KeyError, TypeError) as exc:
            return str(exc)
        return getattr(self.owner.peer, 'preparation_contract_error', None)

    def snapshot(self):
        supported = self.config is not None and (self.owner.transport == 'mock' or
            getattr(self.owner.peer, 'preparation_client', None) is not None)
        return dict(supported=supported, transport='MOCK' if self.owner.transport == 'mock' else 'ROS2',
                    reason='REAL 준비·실행 요청은 실제 로봇을 움직일 수 있습니다. 측정 후 스냅샷 BIND와 최종 실행 검사를 요청합니다.' if getattr(self.owner, 'mode', 'SIMULATION') == 'REAL'
                    else 'MOCK 모의 준비·측정입니다. 로봇은 움직이지 않습니다.' if self.owner.transport == 'mock'
                    else 'ROS SIM 준비·측정 → 스냅샷 BIND → 이미지 경로 → 공정 요청' if getattr(self.owner, 'process_integration', False)
                    else 'ROS SIM 준비·측정 → 원본 저장 → 스냅샷 등록 시험. REAL/조각 실행은 차단합니다.' if supported
                    else 'ROS 준비 SIM 시험은 C2_ROS_PREPARATION_SIM=1 및 같은 PrepareWorkpiece 설치본이 필요합니다.',
                    start_error=self.start_error(), input_config=self.config, current=deepcopy(self.current), ready=self.ready(),
                    blocks_work=self.blocks_work())

    async def save(self):
        # 진행·취소·최종 결과의 동시 저장이 오래된 상태로 역전되지 않게 직렬화한다.
        async with self.save_lock:
            await asyncio.to_thread(self.owner.store.save_preparation, deepcopy(self.current))

    async def begin(self, body):
        from .monitor_service import DomainError
        o = self.owner
        async with o.lock:
            if not self.snapshot()['supported']:
                raise DomainError('NOT_READY', self.snapshot()['reason'])
            old = await asyncio.to_thread(o.store.preparation, body['request_id'])
            if old:
                if old['payload'] != body:
                    raise DomainError('REQUEST_CONFLICT', '같은 준비 요청 ID에 다른 입력이 있습니다.')
                return old
            error = self.start_error()
            if error:
                raise DomainError('PROFILE_MISMATCH', error)
            if self.blocks_work() or o.busy() or o.generating:
                raise DomainError('BUSY', '준비·측정·생성·조각 또는 미확인 작업이 있습니다.')
            if not o.fresh() or o.storage_error:
                raise DomainError('NOT_READY', '현재 상태와 기록 저장을 확인하세요.')
            if o.transport == 'ros' and not o.peer.preparation_client.server_is_ready():
                raise DomainError('NOT_READY', 'PrepareWorkpiece Action 서버가 준비되지 않았습니다.')
            if any(body[k] != self.config[ref] for k, ref in (
                    ('input_profile_snapshot_id', 'id'), ('input_profile_sha256', 'sha256'))):
                raise DomainError('PROFILE_MISMATCH', '현재 측정 전 설정 참조와 다릅니다.')
            try:
                await asyncio.to_thread(o.store.read_asset, self.config['id'], self.config['sha256'])
            except (ValueError, KeyError, OSError):
                raise DomainError('HASH_MISMATCH', '측정 전 설정 파일을 확인할 수 없습니다.')
            if not math.isclose(body['height_m'], self.config['payload']['workcell']['height_m'], abs_tol=1e-9):
                raise DomainError('PROFILE_MISMATCH', '운영자 높이와 등록 설정 높이가 다릅니다.')
            goal = dict(body, preparation_id=uid(), measurement_id=uid(), source_mode=getattr(o, 'mode', 'SIMULATION'),
                        height_source='OPERATOR_RULER')
            record = dict(request_id=body['request_id'], payload=body, goal=goal, state='ACCEPTED',
                          stage='ROBOT_STATUS', feedback=[], result=None, binding_status='PENDING',
                          created_at=now(), updated_at=now(), source='HMI_MOCK_FIXTURE' if o.transport == 'mock' else 'ROS_'+goal['source_mode'])
            await asyncio.to_thread(o.store.save_preparation, record)
            self.current = record
            self.cancel = asyncio.Event()
            if o.transport == 'mock':
                o.peer.bound_preparation = None
            self.task = o.launch(self.run(goal, self.cancel) if o.transport == 'mock' else self.run_ros(goal, self.cancel))
            return deepcopy(record)

    async def cancel_request(self, rid):
        from .monitor_service import DomainError
        async with self.owner.lock:
            old = await asyncio.to_thread(self.owner.store.preparation, rid)
            if old is None:
                raise KeyError(rid)
            if not self.current or self.current['request_id'] != rid:
                return old
            if self.current['state'] not in ACTIVE:
                return deepcopy(self.current)
            if self.current['state'] == 'UNKNOWN':
                return deepcopy(self.current)
            if self.cancel is None:
                raise DomainError('NOT_READY', '관리 중인 준비 요청이 아닙니다.')
            self.current.update(state='CANCELING', updated_at=now())
            self.cancel.set()  # 저장보다 먼저 모의 상대에 취소 전달. 접수는 종료 확인이 아니다.
            await self.save()
            return deepcopy(self.current)

    async def run(self, goal, cancel):
        o = self.owner
        operation = None
        async def feedback(value):
            if (self.current['request_id'] != goal['request_id']
                    or self.current['state'] not in ('ACCEPTED', 'RUNNING')):
                return
            if any(value.get(k) != goal[k] for k in ('preparation_id', 'measurement_id')):
                return
            previous = self.current['feedback'][-1]['sequence'] if self.current['feedback'] else 0
            if type(value.get('sequence')) is not int or value['sequence'] <= previous:
                return
            self.current['feedback'].append(deepcopy(value))
            self.current.update(state='RUNNING', stage=value['stage'], updated_at=now())
            await self.save()
        try:
            operation = asyncio.create_task(o.peer.prepare_workpiece(goal, self.config['payload'], feedback, cancel))
            waiter = asyncio.create_task(cancel.wait())
            try:
                done, _ = await asyncio.wait((operation, waiter), timeout=self.timeout_s, return_when=asyncio.FIRST_COMPLETED)
                timed_out = not done
                if operation not in done:
                    self.current['state'] = 'CANCELING'
                    cancel.set()
                    await self.save()
                    await asyncio.wait_for(asyncio.shield(operation), self.cancel_timeout_s)
                result = await operation
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            self.current['result'] = deepcopy(result)  # 실패·부분 원본도 저장한다.
            observed = result.get('observed_state', {})
            if result.get('outcome') not in ('SUCCEEDED', 'FAILED', 'STOPPED', 'UNKNOWN'):
                raise ValueError('준비 최종 상태가 올바르지 않습니다.')
            state = result['outcome']
            if (state == 'SUCCEEDED' and cancel.is_set()) or observed.get('stop_confirmed') is False:
                state = 'UNKNOWN'  # 취소 이후 늦은 성공은 다음 단계로 진행하지 않는다.
            if timed_out and state == 'STOPPED':
                state = 'FAILED'
                self.current['error_code'] = 'TIMEOUT'
                self.current['message'] = '준비 대기 시간 초과 후 중단 확인'
            raw = await asyncio.to_thread(o.store.put_json, result, 'measurement_record', 'preparation-result.json')
            self.current['measurement_record'] = dict(id=raw['id'], sha256=raw['sha256'])
            if state == 'SUCCEEDED':
                try:
                    if o.image_workflow:
                        from .ros_preparation import bound_profile
                        value = bound_profile(o.profile['payload'], goal, result, self.config['payload'], raw)
                        value.update(label='이미지 통합용 모의 측정 결과', note='실제 이미지 계산 + 모의 측정/가공. 실측 결과가 아님.')
                    else:
                        value = measured_profile(o.profile['payload'], goal, result)
                except (ValueError, KeyError, TypeError) as exc:
                    state = 'FAILED'
                    self.current.update(error_code='NOT_READY', message=str(exc))
                else:
                    value['measurement_record_id'] = raw['id']
                    value['measurement_record_sha256'] = raw['sha256']
                    profile = await asyncio.to_thread(o.store.profile, value)
                    binding = await o.peer.bind_preparation_snapshot(goal, profile)
                    expected = dict(preparation_id=goal['preparation_id'], measurement_id=goal['measurement_id'],
                                    profile_snapshot_id=profile['id'], profile_sha256=profile['sha256'])
                    if binding != expected or cancel.is_set():
                        raise ValueError('준비 기록과 최종 스냅샷 연결 미확인')
                    self.current.update(profile_snapshot=profile, binding_status='BOUND_MOCK')
                    # 결과 기록이 먼저 확정되어야 생성에 사용할 설정을 공개한다.
                    self.current.update(state=state, updated_at=now())
                    await self.save()
                    o.profile = o.peer.profile = profile
            self.current.update(state=state, updated_at=now())
            await self.save()
        except asyncio.CancelledError:
            cancel.set()
            self.current.update(state='UNKNOWN', binding_status='UNCONFIRMED', error_code='COMMUNICATION_LOST',
                                message='서버 종료로 준비 결과 미확인. 자동 재시작하지 않습니다.')
            await self.save()
            raise
        except Exception as exc:
            cancel.set()
            self.current.update(state='UNKNOWN', binding_status='UNCONFIRMED', error_code='COMMUNICATION_LOST',
                                message=f'준비 종료 또는 결과 저장 미확인 ({type(exc).__name__}). 다음 작업을 차단합니다.')
            try:
                await self.save()
            except Exception:
                o.storage_error = '준비 결과 저장 실패'
        finally:
            if operation and not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def run_ros(self, goal, cancel):
        from .ros_preparation import action_goal, display_result, bound_profile, bind_goal
        o = self.owner
        active_goal = action_goal(goal)
        operation = None
        timed_out = False

        async def feedback(value):
            if (self.current['request_id'] != goal['request_id']
                    or self.current['state'] not in ('ACCEPTED', 'RUNNING')):
                return
            # 그대로 저장: 완료 개수는 개별 점의 접촉 승인이나 최종 성공이 아니다.
            self.current['feedback'].append(deepcopy(value))
            self.current.update(state='RUNNING', stage=value['stage'], updated_at=now())
            await self.save()

        async def invoke(timeout):
            nonlocal operation, timed_out
            if cancel.is_set() or not o.fresh():
                raise ValueError('전송 전에 준비 무효화')
            operation = asyncio.create_task(o.peer.prepare_raw(active_goal, feedback))
            waiter = asyncio.create_task(cancel.wait())
            try:
                done, _ = await asyncio.wait((operation, waiter), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                timed_out = not done
                if operation not in done:
                    cancel.set()
                    self.current.update(state='CANCELING', updated_at=now())
                    await self.save()
                    await o.peer.cancel_preparation(active_goal['request_id'])
                    return await asyncio.wait_for(asyncio.shield(operation), self.cancel_timeout_s)
                return await operation
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)

        try:
            self.current['action_goal'] = deepcopy(active_goal)
            await self.save()  # 발송 전에 실제 Goal과 ID 영속화
            raw = await invoke(self.timeout_s)
            record = await asyncio.to_thread(o.store.put_json,
                dict(contract='prepare-workpiece-result/1', result=raw), 'measurement_record', 'preparation-result.json')
            self.current['measurement_record'] = dict(id=record['id'], sha256=record['sha256'])
            result = display_result(raw, goal)
            self.current['result'] = result
            if (not o.fresh() or raw.get('stop_confirmed') is not True
                    or cancel.is_set() and raw['outcome'] != 'STOPPED'):
                self.current.update(state='UNKNOWN', binding_status='UNCONFIRMED', error_code='STOP_UNCONFIRMED',
                                    message='취소·연결 상실 또는 정지 미확인. 다음 작업을 차단합니다.')
            elif raw['outcome'] != 'SUCCEEDED':
                self.current.update(state='FAILED' if timed_out else raw['outcome'],
                                    error_code='TIMEOUT' if timed_out else raw['error_code'], message=raw['message'])
            else:
                try:
                    value = bound_profile(o.profile['payload'], goal, result, self.config['payload'], record)
                except (ValueError, KeyError, TypeError) as exc:
                    self.current.update(state='FAILED', binding_status='UNCONFIRMED', error_code='PROFILE_MISMATCH',
                                        message=str(exc), updated_at=now())
                    await self.save()
                    return  # 측정은 성공·정지 확인됨. 실행 설정 조립 실패만 확정 실패로 기록.
                profile = await asyncio.to_thread(o.store.profile, value)
                active_goal = bind_goal(active_goal, record, profile)
                self.current.update(bind_goal=deepcopy(active_goal), stage='BINDING', binding_status='PENDING')
                await self.save()
                if cancel.is_set() or not o.fresh():
                    raise ValueError('등록 전에 준비 무효화')
                bound = await invoke(30.)
                self.current['bind_result'] = bound
                if cancel.is_set() or not o.fresh():
                    raise ValueError('등록 후 준비 무효화')
                if bound['outcome'] != 'SUCCEEDED':
                    self.current.update(state='FAILED', binding_status='UNCONFIRMED',
                                        error_code=bound['error_code'], message=bound['message'])
                else:
                    self.current.update(state='SUCCEEDED', stage='COMPLETE', profile_snapshot=profile,
                                        binding_status='BOUND_ROS', message=f"ROS {goal['source_mode']} 측정·스냅샷 등록 완료. 실행 검사는 별도 수행합니다.")
                    await self.save()
                    o.profile = profile  # BIND 성공 원장 저장 후에만 경로 생성에 공개
            self.current['updated_at'] = now()
            await self.save()
        except (Exception, asyncio.CancelledError) as exc:
            cancel.set()
            self.current.update(state='UNKNOWN', binding_status='UNCONFIRMED', error_code='COMMUNICATION_LOST',
                                message=f'준비 결과/등록 미확인 ({type(exc).__name__}). 자동 재요청하지 않습니다.')
            try:
                await self.save()
            except Exception:
                o.storage_error = '준비 결과 저장 실패'
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            if operation and not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    async def reset_mock(self):
        if self.current:
            self.current.update(state='INVALIDATED', binding_status='UNCONFIRMED',
                                message='모의 시험 초기화. 이전 측정 원본 보존, 다시 준비 필요.')
            await self.save()
        self.owner.peer.bound_preparation = None
