"""PrepareWorkpiece의 파일/함수 경계. ROS 타입과 장치 명령을 생성하지 않는다.

홈/재검사를 포함하는 runner는 제어 노드가 명시적으로 주입한다. 없으면 NOT_READY.
원장은 재시작 후 중복 모션을 막으며 준비 실행 권한은 재시작 시 복원하지 않는다.
"""
import copy
import hashlib
import json
import math
from datetime import datetime
import sqlite3
import threading
import time
from pathlib import Path
from urllib.request import build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
from uuid import UUID

from .robot_adapter import StepResult

GOAL_FIELDS = ('schema_version','operation','request_id','preparation_id','measurement_id','source_mode',
               'input_profile_snapshot_id','input_profile_sha256','measurement_record_id',
               'measurement_record_sha256','profile_snapshot_id','profile_sha256')
IDS = ('request_id','preparation_id','measurement_id','input_profile_snapshot_id')
GEOMETRY = ('height_m','axis_xy_m','radius_m','top_z_m','bottom_z_m','work_v_range_m',
            'work_z_range_m','residual_rms_m','residual_max_m')

class ContractError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def uuid4_string(value):
    try:
        u = UUID(value)
        return u.version == 4 and str(u) == value
    except (ValueError, TypeError, AttributeError):
        return False


def sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def validate_goal(g):
    if set(g) != set(GOAL_FIELDS):
        raise ContractError('INVALID_INPUT', '준비 Goal 필드 불일치')
    if type(g['schema_version']) is not int or g['schema_version'] != 2:
        raise ContractError('UNSUPPORTED_SCHEMA', 'PrepareWorkpiece v2 필요')
    if g['operation'] not in ('MEASURE','BIND_SNAPSHOT') or g['source_mode'] not in ('SIMULATION','REAL'):
        raise ContractError('INVALID_INPUT', 'operation/source_mode 오류')
    if not all(uuid4_string(g[k]) for k in IDS) or not sha(g['input_profile_sha256']):
        raise ContractError('INVALID_INPUT', 'UUID v4/원본 해시 오류')
    for stem in ('measurement_record','profile'):
        id_key = stem+'_id' if stem == 'measurement_record' else 'profile_snapshot_id'
        hash_key = stem+'_sha256'
        if g['operation'] == 'MEASURE':
            if g[id_key] != '' or g[hash_key] != '':
                raise ContractError('INVALID_INPUT', 'MEASURE 최종 참조는 비어 있어야 함')
        elif not uuid4_string(g[id_key]) or not sha(g[hash_key]):
            raise ContractError('INVALID_INPUT', 'BIND 최종 참조 오류')


def utc(value):
    if value is None:
        return {'sec':0, 'nanosec':0}
    if isinstance(value,str):
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None: raise ContractError('INVALID_MEASUREMENT','UTC timezone 필요')
        value=parsed.timestamp()
    if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
        raise ContractError('INVALID_MEASUREMENT','UTC 시각 오류')
    sec = math.floor(value)
    ns = round((value-sec)*1e9)
    return {'sec':sec+ns//1000000000,'nanosec':ns%1000000000}


def result_base(g):
    result = {k:g.get(k,'') for k in GOAL_FIELDS if k != 'schema_version'}
    result.update(outcome='UNKNOWN',error_code='UNKNOWN',message='',stop_confirmed=False,
                  partial=True,geometry_ready=False,snapshot_bound=False,log_id='',frame_id='',
                  validity='INCOMPLETE',started_at=utc(None),measured_at=utc(None),height_source='',
                  height_m=0.,axis_xy_m=[0.,0.],radius_m=0.,top_z_m=0.,bottom_z_m=0.,
                  work_v_range_m=[0.,0.],work_z_range_m=[0.,0.],residual_rms_m=0.,residual_max_m=0.,
                  vertical_axis_assumed=False,tilt_measured=False,independent_accuracy_verified=False,
                  contact_indices=[],contact_tip_poses=[],contact_normal_force_n=[],
                  contact_received_at=[],contact_monotonic_s=[],contact_sources=[])
    return result


def result_from_step(g, step):
    out = result_base(g)
    out.update(outcome=step.outcome,error_code=step.error_code,message=step.message)
    obs = step.observed_state
    out.update(stop_confirmed=obs.get('stop_confirmed') is True, partial=obs.get('partial') is not False)
    data = obs.get('measurement') or {}
    try:
        for key in ('frame_id','validity','height_source','vertical_axis_assumed','tilt_measured','independent_accuracy_verified'):
            if key in data: out[key] = data[key]
        out['started_at'],out['measured_at'] = utc(data.get('started_at')),utc(data.get('measured_at'))
        # 부분 실패의 기하 default=0은 실측값이 아니다. 접촉은 원본에서 검증된 것만 보존.
        for hit in ([data['top']] if data.get('top') else []) + data.get('points',[]):
            pose = hit['tip_pose']
            if (len(pose) != 7 or any(type(v) not in (int,float) or not math.isfinite(v) for v in pose)
                    or abs(sum(v*v for v in pose[3:])-1.) > 1e-6 or hit.get('detected') is not True
                    or hit.get('frame_id') != 'c2_base'):
                raise ContractError('INVALID_MEASUREMENT','접촉 자세/확인 오류')
            index = hit['point_index']
            if type(index) is not int or not 0 <= index <= 8 or index in out['contact_indices']:
                raise ContractError('INVALID_MEASUREMENT','접촉 인덱스 오류')
            force,mono = hit['normal_force_n'],hit['measured_at_monotonic_s']
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (force,mono)):
                raise ContractError('INVALID_MEASUREMENT','접촉 힘/시각 오류')
            out['contact_indices'].append(index)
            out['contact_tip_poses'].append({'position':dict(zip(('x','y','z'),pose[:3])),
                                           'orientation':dict(zip(('x','y','z','w'),pose[3:]))})
            out['contact_normal_force_n'].append(float(force))
            out['contact_received_at'].append(utc(hit.get('received_at')))
            out['contact_monotonic_s'].append(float(mono))
            out['contact_sources'].append(hit['source'])
        if step.ok:
            expected = ('SIMULATED',) if g['source_mode']=='SIMULATION' else ('FORCE_CONTACT_ESTIMATE','ESTIMATED')
            if (data.get('geometry_ready') is not True or out['partial'] or not out['stop_confirmed']
                    or out['validity'] not in expected or out['frame_id'] != 'c2_base'
                    or out['contact_indices'] != list(range(9))
                    or not out['started_at']['sec'] or not out['measured_at']['sec']):
                raise ContractError('NOT_READY','절대 형상/9접촉/후퇴·정지 완료 미확인')
            for key in GEOMETRY:
                value = data[key]
                values = value if isinstance(value,list) else [value]
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
                    raise ContractError('INVALID_MEASUREMENT','기하 유한값 필요')
                out[key] = copy.deepcopy(value)
            h,top = out['height_m'],out['top_z_m']
            lo,hi = out['work_v_range_m']
            if (h<=0 or out['radius_m']<=0 or len(out['axis_xy_m'])!=2 or not 0<=lo<hi<=h
                    or abs(out['bottom_z_m']-(top-h))>1e-9
                    or any(abs(a-b)>1e-9 for a,b in zip(out['work_z_range_m'],[top-hi,top-lo]))
                    or len(out['work_z_range_m'])!=2):
                raise ContractError('INVALID_MEASUREMENT','기하 범위/높이 불일치')
            out['geometry_ready'] = True
            if out['validity']=='ESTIMATED':
                if data.get('absolute_top_verified') is not False:
                    raise ContractError('INVALID_MEASUREMENT','추정 윗면 확인 상태 불일치')
                out['message'] += ' [ESTIMATED: 접촉 TCP 기반 임시 윗면, 절대 높이 미검증]'
    except (KeyError,ValueError,TypeError) as exc:
        out.update(outcome='FAILED',error_code=getattr(exc,'code','INVALID_MEASUREMENT'),
                   message=str(exc),geometry_ready=False,partial=True)
    return out


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ContractError('NOT_READY','자산 조회 리다이렉트 금지')


class AssetResolver:
    """배포 주소만 사용. 원본 바이트 해시 검증 후 JSON 해석. 호출당 5초/2회."""
    def __init__(self, base_url=None, fetch=None):
        if base_url and (urlsplit(base_url).scheme not in ('http','https') or urlsplit(base_url).username
                         or urlsplit(base_url).query or urlsplit(base_url).fragment):
            raise ValueError('배포 백엔드 URL 오류')
        self.base_url,self.fetch = base_url,fetch

    def read(self, asset_id, digest, cancel):
        if not uuid4_string(asset_id) or not sha(digest):
            raise ContractError('INVALID_INPUT','자산 ID/해시 오류')
        if not self.fetch and not self.base_url:
            raise ContractError('NOT_READY','자산 resolver 배포 설정 없음')
        raw = None
        for _ in range(2):
            if cancel.is_set(): raise ContractError('CANCELLED','조회 취소')
            try:
                if self.fetch:
                    raw = self.fetch(asset_id,5.)
                else:
                    with build_opener(_NoRedirect).open(self.base_url.rstrip('/')+'/api/operator/assets/'+asset_id+'/content',timeout=5.) as f:
                        raw = f.read(8*1024*1024+1)
                break
            except (OSError,TimeoutError):
                continue
        if cancel.is_set(): raise ContractError('CANCELLED','조회 취소')
        if not isinstance(raw,bytes) or len(raw)>8*1024*1024:
            raise ContractError('NOT_READY','자산 조회 실패/크기 초과')
        if hashlib.sha256(raw).hexdigest()!=digest:
            raise ContractError('HASH_MISMATCH','자산 원본 바이트 해시 불일치')
        try:
            value=json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            if not isinstance(value,dict): raise ValueError('object 필요')
            return value
        except (ValueError,UnicodeError) as exc:
            raise ContractError('INVALID_INPUT',str(exc)) from exc


class PreparationActionHandler:
    """동기 Action 처리기. runner(g, config, cancel, feedback) -> StepResult.

    runner는 동일 coordinator의 prepare/measure 함수를 사용하여 준비 기록과
    motion_lock을 공유해야 한다. 홈 검사/재검사는 runner 담당. 기본 REAL 연결 없음.
    """
    def __init__(self, coordinator, resolver, journal_path=None, runner=None):
        self.coordinator,self.resolver,self.runner = coordinator,resolver,runner
        self.lock=threading.RLock()
        self.active=None
        self.pending_cancel={}
        self.latest=None
        self.success=None
        self.db=None
        if journal_path:
            Path(journal_path).parent.mkdir(parents=True,exist_ok=True)
            self.db=sqlite3.connect(journal_path,check_same_thread=False)
            self.db.execute('CREATE TABLE IF NOT EXISTS prepare_requests(id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)')
            self.db.execute('CREATE TABLE IF NOT EXISTS prepare_used(preparation TEXT UNIQUE, measurement TEXT UNIQUE)')
            self.db.commit()
        coordinator.preparation_required=True
        self.invalidate()

    def invalidate(self):
        with self.lock, self.coordinator._lock:
            self.success=None; self.latest=None
            self.coordinator._preparations.clear()
            self.coordinator._preparation_bindings.clear()

    def cancel(self,g):
        with self.lock:
            rid=g.get('request_id','')
            fingerprint=hashlib.sha256(encoded(g)).hexdigest()
            if self.active and self.active['id']==rid:
                if self.active['fingerprint']!=fingerprint: return False
                if self.active.get('bound'): return False
                self.active['cancel'].set()
                self.invalidate()
                return True
            if self.db and self.db.execute('SELECT 1 FROM prepare_requests WHERE id=?',(rid,)).fetchone():
                return False
            self.pending_cancel[rid]=fingerprint
            return True

    def execute(self,g,feedback=None):
        g=copy.deepcopy(g)
        try: validate_goal(g)
        except ContractError as exc: return self._failure(g,exc)
        fingerprint=hashlib.sha256(encoded(g)).hexdigest()
        waiter=None
        with self.lock:
            if self.db is None: return self._failure(g,ContractError('NOT_READY','영속 준비 원장 필요'))
            old=self.db.execute('SELECT fingerprint,result FROM prepare_requests WHERE id=?',(g['request_id'],)).fetchone()
            if old:
                if old[0]!=fingerprint: return self._failure(g,ContractError('REQUEST_CONFLICT','같은 요청 ID에 다른 Goal'))
                if old[1]:
                    if g['operation']=='BIND_SNAPSHOT' and (not self.latest or g['preparation_id']!=self.latest['preparation_id']):
                        return self._failure(g,ContractError('NOT_READY','이전 준비 등록은 현재 유효하지 않음'))
                    return json.loads(old[1])
                if self.active and self.active['id']==g['request_id']: waiter=self.active['done']
                else: return self._failure(g,ContractError('NOT_READY','재시작 전 미완료 요청; 새 측정 필요'))
            elif self.active:
                return self._failure(g,ContractError('BUSY','다른 준비 요청 실행 중'))
            if waiter is None:
                with self.coordinator._lock:
                    if self.coordinator._active or self.coordinator._motion_uncertain:
                        return self._failure(g,ContractError('BUSY','조각 실행 중/정지 미확인'))
                    self.coordinator._preparation_action_busy=True
                if g['operation']=='MEASURE':
                    try:
                        self.db.execute('INSERT INTO prepare_used VALUES (?,?)',(g['preparation_id'],g['measurement_id']))
                    except sqlite3.IntegrityError:
                        self.coordinator._preparation_action_busy=False
                        return self._failure(g,ContractError('REQUEST_CONFLICT','이미 사용한 준비/측정 ID'))
                    self.invalidate()
                cancel=threading.Event()
                if self.pending_cancel.pop(g['request_id'],None)==fingerprint: cancel.set()
                self.active=dict(id=g['request_id'],fingerprint=fingerprint,cancel=cancel,done=threading.Event())
                self.db.execute('INSERT INTO prepare_requests VALUES (?,?,NULL)',(g['request_id'],fingerprint));self.db.commit()
        if waiter is not None:
            waiter.wait()
            return self.execute(g,feedback)
        started=time.monotonic(); timed_out=threading.Event(); timer=None; runner_started=False
        last_stage=None; last_emit=-1.; completed=set()
        def emit(event):
            nonlocal last_stage,last_emit
            stage=event.get('stage','UNKNOWN')
            if stage in ('MEASUREMENT_PRECHECK','MEASURE_WORKPIECE','CONFIRM_MEASUREMENT'): return
            if stage=='COMPLETE' and 'values' in event: return
            if stage=='TERMINAL': stage=last_stage or 'UNKNOWN'
            aliases={'ROBOT_STATUS':'ROBOT_CHECK','MEASUREMENT_PRECHECK':'VALIDATING','MEASURE_WORKPIECE':'TOP_TOUCH',
                     'CONFIRM_MEASUREMENT':'FIT','START':'VALIDATING','TOP_APPROACH':'TOP_TOUCH','SIDE_START':'SIDE_TOUCH',
                     'HOME_READY':'HOME_RECHECK','HOME_RETURN':'RETRACT'}
            stage=aliases.get(stage,stage)
            idx=event.get('point_index',0)
            boundary=event.get('status') in ('SUCCEEDED','FAILED','STOPPED','UNKNOWN')
            if stage=='SIDE_TOUCH' and event.get('status')=='SUCCEEDED' and type(idx) is int and 1<=idx<=8: completed.add(idx)
            now=time.monotonic()
            if feedback and (stage!=last_stage or boundary or now-last_emit>=.2):
                feedback(dict(request_id=g['request_id'],preparation_id=g['preparation_id'],measurement_id=g['measurement_id'],
                              operation=g['operation'],stage=stage,progress=len(completed)/8.,completed_side_points=len(completed),
                              total_side_points=8,elapsed_s=now-started,message=event.get('message','')))
                last_emit=now;last_stage=stage
        try:
            if cancel.is_set(): raise ContractError('CANCELLED','시작 전 취소')
            if g['source_mode']=='REAL' and not getattr(self.runner,'real_preparation_ready',False):
                raise ContractError('NOT_READY','REAL 준비 runner/하드웨어 관측 미연결')
            if g['source_mode']!=self.coordinator.runtime_mode: raise ContractError('INVALID_INPUT','실행 모드 불일치')
            if g['operation']=='MEASURE':
                emit({'stage':'VALIDATING'})
                config=self.resolver.read(g['input_profile_snapshot_id'],g['input_profile_sha256'],cancel)
                self._validate_config(config,g)
                timeout=config['workcell']['runtime_timeout_s']-(time.monotonic()-started)
            else: timeout=30.-(time.monotonic()-started)
            if timeout<=0: raise ContractError('TIMEOUT','준비 처리 기한 초과')
            def expired():
                with self.lock:
                    if self.active and self.active.get('bound'): return
                    timed_out.set();cancel.set();self.invalidate()
            timer=threading.Timer(timeout,expired);timer.daemon=True;timer.start()
            if g['operation']=='MEASURE':
                if self.runner is None: raise ContractError('NOT_READY','홈·재검사 포함 측정 runner 미연결')
                runner_started=True
                step=self.runner(g,config,cancel,emit)
                if not isinstance(step,StepResult): raise ContractError('INTERNAL_ERROR','측정 반환 형식 오류')
                out=result_from_step(g,step)
                if timed_out.is_set():
                    out.update(outcome='FAILED' if out['stop_confirmed'] else 'UNKNOWN',error_code='TIMEOUT',geometry_ready=False)
                elif cancel.is_set() and out['outcome']=='SUCCEEDED':
                    out.update(outcome='UNKNOWN',error_code='STOP_UNCONFIRMED',geometry_ready=False)
                with self.lock:
                    if out['outcome']=='SUCCEEDED' and not cancel.is_set():
                        self.latest=copy.deepcopy(g); self.success=copy.deepcopy(out); self.config=copy.deepcopy(config)
                    else: self.invalidate()
            else:
                emit({'stage':'BINDING'})
                out=self._bind(g,cancel)
            emit({'stage':'COMPLETE','status':out['outcome'],'message':out['message']})
        except Exception as exc:
            out=self._failure(g,exc)
            if runner_started:
                out.update(outcome='UNKNOWN',error_code='STOP_UNCONFIRMED',stop_confirmed=False)
                with self.coordinator._lock: self.coordinator._motion_uncertain=True
            if timed_out.is_set(): out['error_code']='TIMEOUT'
            if g['operation']=='MEASURE': self.invalidate()
        finally:
            if timer: timer.cancel()
        with self.lock:
            # BIND 등록 후 늦은 cancel은 cancel()에서 DONE을 보고 거절하도록 동일 잠금에서 확정.
            if cancel.is_set() and out['outcome']=='SUCCEEDED':
                out.update(outcome='UNKNOWN',error_code='STOP_UNCONFIRMED',snapshot_bound=False,geometry_ready=False)
                self.invalidate()
            self.db.execute('UPDATE prepare_requests SET result=? WHERE id=?',(encoded(out).decode(),g['request_id']));self.db.commit()
            self.active['done'].set();self.active=None
            self.coordinator._preparation_action_busy=False
        return out

    def _failure(self,g,exc):
        out=result_base(g);code=getattr(exc,'code','INTERNAL_ERROR')
        out.update(outcome='STOPPED' if code=='CANCELLED' else 'FAILED',error_code=code,message=str(exc))
        return out

    def _validate_config(self,c,g):
        if c.get('contract')!='prepare-workpiece-config/1' or c.get('source_mode')!=g['source_mode']:
            raise ContractError('INVALID_INPUT','측정 설정 contract/mode 불일치')
        if c.get('tool_id')!='engraving_drill' or c.get('tcp_id')!='GripperDA_v1' or not c.get('load_id'):
            raise ContractError('PROFILE_MISMATCH','도구/TCP/하중 설정 오류')
        w,p=c.get('workcell'),c.get('profiles')
        if not isinstance(w,dict) or not isinstance(p,dict): raise ContractError('INVALID_INPUT','측정 설정 없음')
        for key in ('height_m','runtime_timeout_s'):
            if type(w.get(key)) not in (float,int) or not math.isfinite(w[key]) or w[key]<=0:
                raise ContractError('INVALID_INPUT',key+' 필요')
        if w.get('height_source')!='OPERATOR_RULER': raise ContractError('INVALID_INPUT','높이 출처 오류')
        encoded(c)  # 비유한 값은 저장·실행 조건으로 허용하지 않음

    def _bind(self,g,cancel):
        with self.lock:
            if not self.latest or not self.success: raise ContractError('NOT_READY','현재 프로세스 성공 측정 없음')
            original=copy.deepcopy(self.success)
            if original['validity']=='ESTIMATED':
                raise ContractError('NOT_READY','추정값의 경로용 스냅샷 승인은 별도 계약 필요; 측정 결과만 반환')
            for key in ('preparation_id','measurement_id','source_mode','input_profile_snapshot_id','input_profile_sha256'):
                if g[key]!=self.latest[key]: raise ContractError('PROFILE_MISMATCH','다른 측정/설정 참조')
        record=self.resolver.read(g['measurement_record_id'],g['measurement_record_sha256'],cancel)
        profile=self.resolver.read(g['profile_snapshot_id'],g['profile_sha256'],cancel)
        if record.get('contract')!='prepare-workpiece-result/1' or encoded(record.get('result'))!=encoded(original):
            raise ContractError('PROFILE_MISMATCH','저장 측정 원본이 제어 Result와 다름')
        for key in ('preparation_id','measurement_id','source_mode','input_profile_snapshot_id','input_profile_sha256',
                    'measurement_record_id','measurement_record_sha256'):
            if profile.get(key)!=g[key]: raise ContractError('PROFILE_MISMATCH','스냅샷 출처 불일치: '+key)
        for key in ('tool_id','tcp_id','load_id','tool_version','tcp_version','load_version','tools_config_id','tools_config_version'):
            if key in self.config and profile.get(key)!=self.config[key]:
                raise ContractError('PROFILE_MISMATCH','스냅샷 도구/설정 불일치: '+key)
        h=original['height_m'];lo,hi=original['work_v_range_m']
        expected=dict(radius_mm=original['radius_m']*1000,height_mm=h*1000,
                      axis_origin_m=[*original['axis_xy_m'],original['bottom_z_m']],axis_direction=[0,0,1],
                      height_reference='bottom',v_direction='up',valid_v_range_mm=[(h-hi)*1000,(h-lo)*1000])
        surf=profile.get('surface',{})
        for key,value in expected.items():
            actual=surf.get(key)
            if isinstance(value,str): good=actual==value
            else:
                a=actual if isinstance(actual,list) else [actual];b=value if isinstance(value,list) else [value]
                tol=1e-6 if key.endswith('_mm') else 1e-9
                good=len(a)==len(b) and all(type(x) in (float,int) and math.isfinite(x) and abs(x-y)<=tol for x,y in zip(a,b))
            if not good: raise ContractError('PROFILE_MISMATCH','스냅샷 기하 불일치: '+key)
        with self.lock, self.coordinator._lock:
            if cancel.is_set(): raise ContractError('CANCELLED','BIND 취소')
            if self.success!=original or g['preparation_id'] not in self.coordinator._preparations or self.coordinator._motion_uncertain:
                raise ContractError('NOT_READY','준비 기록 무효화/정지 미확인')
            identity=(g['profile_snapshot_id'],g['profile_sha256'])
            old=self.coordinator._preparation_bindings.get(g['preparation_id'])
            if old is not None and old!=identity: raise ContractError('REQUEST_CONFLICT','기존 등록 변경 금지')
            self.coordinator._preparation_bindings[g['preparation_id']]=identity
            self.active['bound']=True
        out=result_base(g)
        out.update(outcome='SUCCEEDED',error_code='NONE',message='측정 원본·최종 스냅샷 대조 완료',
                   snapshot_bound=True,geometry_ready=True,partial=False,stop_confirmed=True)
        return out


def make_measurement_runner(coordinator, *, status_adapter, measurement_adapter_factory,
                            evidence_factory, home_fn=None, measurement_owns_home=False):
    """기존 함수 연결. home_fn은 시율의 검사/홈/정지 확인 함수이며 lock을 직접 소유.

    미연결 홈 동작을 임의 성공으로 채우지 않는다. 제어는 홈 명령을 만들지 않는다.
    홈 함수(ctx,workcell,profiles,progress)->StepResult, 성공 stop_confirmed=True 필수.
    """
    def run(goal, config, cancel, feedback):
        from .node import check_preparation_status
        from .workpiece_calibration import MeasurementContext
        if home_fn is None and not measurement_owns_home:
            return StepResult('FAILED','NOT_READY','검사된 홈/도착 확인 함수 미연결','home_check')
        ctx=MeasurementContext(goal['measurement_id'],goal['preparation_id'],goal['source_mode'],
            cancel=cancel,motion_lock=coordinator.motion_lock,
            profile_snapshot_id=goal['input_profile_snapshot_id'],profile_sha256=goal['input_profile_sha256'])
        evidence=evidence_factory(goal,config)
        settings={'tcp_profile_id':config['tcp_id'],'load_profile_id':config['load_id']}
        def before(context, progress):
            feedback({'stage':'HOME_CHECK'})
            ready=home_fn(context,config['workcell'],config['profiles'],feedback)
            if not isinstance(ready,StepResult) or not ready.ok: return ready
            if ready.observed_state.get('stop_confirmed') is not True:
                return StepResult('UNKNOWN','STOP_UNCONFIRMED','홈 도착/정지 미확인','home_check')
            feedback({'stage':'HOME_RECHECK'})
            return check_preparation_status(status_adapter,evidence_factory(goal,config),settings,cancel=cancel)
        return coordinator.prepare_workpiece(ctx,status_adapter,measurement_adapter_factory(config),
            config['workcell'],config['profiles'],evidence,settings,on_progress=feedback,
            on_phase=lambda stage: feedback({'stage':stage}),before_measure=None if measurement_owns_home else before)
    return run


def make_simulation_runner_factory():
    """배포 SIM 노드용 준비 runner 팩터리.

    요청별 불변 설정으로 상태/측정 어댑터를 만들며, 시율 measure_workpiece가 관측값으로
    홈 계획·검사·이동·재관측을 수행한다. 제어에서 중복 홈 이동하지 않는다. 모션 없는 임의 성공 콜백이나 REAL 대체값은 쓰지 않는다.
    """
    def factory(coordinator):
        # ProcessCoordinator가 검사하는 것과 동일한 클래스 객체를 사용한다.
        # 동적 계약 시험이 preconditions 모듈을 다시 적재해도 타입이 갈리지 않는다.
        from .node import PreconditionEvidence
        from .robot_adapter import MockRobotAdapter
        from .workpiece_simulation import SimulatedWorkpieceAdapter

        status = MockRobotAdapter()

        def run(goal, config, cancel, feedback):
            workcell = config['workcell']
            selected = (config['tcp_id'], config['load_id'])
            status._read_tool_tcp = lambda: selected
            measurement = SimulatedWorkpieceAdapter(workcell, clock=time.monotonic)

            def evidence_factory(_goal, current):
                return PreconditionEvidence(
                    runtime_mode='SIMULATION', robot_state=None,
                    control_authority_confirmed=True, stop_latched=False,
                    max_robot_state_age_s=current['workcell']['max_state_age_s'])

            runner = make_measurement_runner(
                coordinator, status_adapter=status,
                measurement_adapter_factory=lambda _config: measurement,
                evidence_factory=evidence_factory, measurement_owns_home=True)
            return runner(goal, config, cancel, feedback)
        return run
    return factory


def make_real_measurement_runner(coordinator, node, *, evidence_provider,
                                 evidence_max_age_s, stop_latched_provider,
                                 scene_check=None, controller_prefix=None,
                                 stop_latch_recorder=None):
    """실물 장치 연결은 주입한다. 생성은 모션을 보내지 않으며 측정 중만 사용한다.

    authority 관측·정지 래치 공급이 없으면 생성 자체를 거절한다.
    HMI Action 타입은 바꾸지 않는다. ESTIMATED의 세부 새 필드는 아직 전달 계약 밖이다.
    """
    from .workpiece_process_adapter import create_process_measurement_adapter, check_process_scene
    from .workpiece_calibration import MeasurementContext
    from .node import PreconditionEvidence
    if scene_check is None:
        scene_check = check_process_scene
    if (coordinator.runtime_mode!='REAL' or not callable(evidence_provider)
            or not callable(scene_check) or not callable(stop_latched_provider)):
        raise ValueError('REAL 관측·현장 검사·정지 래치 공급 함수 필요')
    def run(goal, config, cancel, feedback):
        if (controller_prefix is not None
                and config.get('controller_prefix') != controller_prefix):
            return StepResult('FAILED','PROFILE_MISMATCH',
                '기동 controller_prefix와 준비 설정 불일치','robot_status')
        ctx=MeasurementContext(goal['measurement_id'],goal['preparation_id'],'REAL',
            cancel=cancel,motion_lock=coordinator.motion_lock,
            profile_snapshot_id=goal['input_profile_snapshot_id'],profile_sha256=goal['input_profile_sha256'])
        adapter=create_process_measurement_adapter(node,config,ctx,
            motion_lock=coordinator.motion_lock,cancel=cancel,evidence_provider=evidence_provider,
            evidence_max_age_s=evidence_max_age_s,scene_check=scene_check)
        try:
            # readiness도 같은 원본을 동작 전에 다시 검사한다. 장착/OFF는 수동 절차다.
            raw=evidence_provider(ctx)
            item=raw.get('control_authority',{}) if isinstance(raw,dict) else {}
            stamp=item.get('observed_at_monotonic_s')
            age=evidence_max_age_s['control_authority']
            valid=(isinstance(raw,dict) and raw.get('measurement_id')==ctx.measurement_id
                   and item.get('value') is True and item.get('valid') is True
                   and item.get('source')=='CONTROLLER_ACCESS_CONTROL'
                   and type(stamp) in (int,float) and math.isfinite(stamp)
                   and type(age) in (int,float) and math.isfinite(age) and age>0
                   and 0<=time.monotonic()-stamp<=age)
            evidence=PreconditionEvidence(runtime_mode='REAL',robot_state=None,
                control_authority_confirmed=valid,stop_latched=stop_latched_provider(ctx),
                max_robot_state_age_s=config['workcell']['max_state_age_s'])
            result = coordinator.prepare_workpiece(ctx,coordinator.real_adapter,adapter,
                config['workcell'],config['profiles'],evidence,
                {'tcp_profile_id':config['tcp_id'],'load_profile_id':config['load_id']},
                on_progress=feedback,on_phase=lambda stage:feedback({'stage':stage}))
            if callable(stop_latch_recorder):
                stop_latch_recorder(result, cancel)
            return result
        finally:
            adapter.close()  # 공유 Lock/Event/노드 수명은 종료하지 않음
    run.real_preparation_ready=True
    return run
