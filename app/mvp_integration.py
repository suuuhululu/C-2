"""A/B/C의 실제 함수와 별도 MOCK Robot 프로세스를 연결하는 모의 진입점."""
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
from queue import Queue, Empty
from threading import Event, Thread
import time

from app.supply_slots import next_supply_slot

from app.c_design import main as c_main
from app.c_text_connection import differences_for_c
from app.mvp_fake import settings, prepare, execution_document
from app.mvp_workflow import MvpWorkflow
from app.robot_process import RobotProcess
from app.hmi_contracts import validate_hmi_command
from app.hmi_mvp_contracts import validate_user_request
from perception.perception_mvp.team_connection import connect_inspection
from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment, handle_step_motion


class MvpIntegration:
    """모든 채택은 poll() 호출 스레드에서 수행한다. 작업 thread는 결과만 큐에 넣는다."""
    supply_slot_count = 6

    def __init__(self, robot_root, directory, *, fixture_design=None, c_mode='offline',
                 history_dsn=None, web_url='http://127.0.0.1:8765', robot_mode='MOCK',
                 runtime_settings=None, gestures=False, round3_step_replay=None):
        if round3_step_replay is not None and robot_mode != 'MOCK':
            raise ValueError('ROUND3_STEP_REPLAY_IS_MOCK_ONLY')
        self.round3_step_replay = deepcopy(round3_step_replay)
        self.saved_observation_replay = (round3_step_replay is not None
            and 'saved_observations' in round3_step_replay)
        if self.saved_observation_replay and round3_step_replay.get('provenance') != 'SYNTHETIC':
            raise ValueError('SAVED_OBSERVATION_REPLAY_REQUIRES_SYNTHETIC_INPUT')
        self.design_change_replay = bool(round3_step_replay and round3_step_replay.get('design_change_replay'))
        if self.design_change_replay and (not self.saved_observation_replay or c_mode != 'offline'):
            raise ValueError('DESIGN_CHANGE_REPLAY_REQUIRES_SAVED_OFFLINE_INPUT')
        self.saved_observation_index = 0
        if robot_mode not in ('MOCK', 'REAL'):
            raise ValueError('explicit robot mode required')
        if c_mode not in ('offline', 'live'):
            raise ValueError('explicit C mode required')
        if (os.environ.get('C_DESIGN_USE_LLM') == '1') != (c_mode == 'live'):
            raise ValueError('C_DESIGN_USE_LLM must match c_mode')
        self.inbox, self.scene = Queue(), []
        self.observations = []
        self.fixture_design = deepcopy(fixture_design)
        self.c_mode = c_mode
        self.c_pending, self.question = None, None
        self.cancelled = Event()
        self.workers = []
        self.last_document = None
        self.ready_signal = None
        self.robot_mode = robot_mode
        self.auto_gestures, self.direct_handover = robot_mode == 'MOCK', False
        self.slot_indices = {}
        self.consumed_executions = set()
        self.scene_executions = set()
        self.robot_sample=None
        self.robot_sequence=0
        self.closed = False
        self.robot_retired = False
        self.history_dsn, self.web_url = history_dsn, web_url
        self.creator = self.job_creator = None
        self._credentials = None  # Memory only; never part of snapshots or JSONL.
        self.login_pending = False
        self.creator_reason = None
        self.owner_state = 'NOT_STARTED'
        self.workflow = MvpWorkflow(self.emit, runtime_settings or settings(), directory,
                                    mode='REAL' if robot_mode == 'REAL' else 'FAKE')
        self.workflow.saved_observation_replay = self.saved_observation_replay
        self.workflow.design_change_replay = self.design_change_replay
        self.workflow.replay_change_from_version = (fixture_design['design_version']
            if self.design_change_replay and fixture_design is not None else None)
        self.b = connect_inspection(lambda value:self.inbox.put(('b',value)),
            observe=self.observe, geometry_reference=self.workflow.settings['geometry_reference'])
        self.workflow.b = self.b
        self.robot = RobotProcess(robot_root, mode=robot_mode,
            config=Path(robot_root)/'interfaces/assembly_contact_trial.json' if robot_mode == 'REAL' else None,
            gestures=gestures)

    def state_snapshot(self, value):
        pass  # The measured REAL adapter consumes explicit read-only snapshots.

    def observe(self, context, active):
        if not active():
            raise ValueError('inspection canceled')
        if self.saved_observation_replay:
            records = self.round3_step_replay['saved_observations']
            index = self.saved_observation_index
            if index >= len(records):
                raise ValueError('SAVED_OBSERVATION_MISSING')
            packet = deepcopy(records[index])
            if packet['check_kind'] != context['check_kind']:
                raise ValueError('SAVED_OBSERVATION_KIND_MISMATCH')
            if self.design_change_replay and context['check_kind'] != 'INITIAL':
                if packet.get('design_version') != self.workflow.approved['design_version']:
                    raise ValueError('SAVED_OBSERVATION_DESIGN_VERSION_MISMATCH')
            if context['check_kind'] == 'STEP' and packet.get('target_block') != self.workflow.step()['after']:
                raise ValueError('SAVED_OBSERVATION_STEP_MISMATCH')
            if not active():
                raise ValueError('inspection canceled')
            self.saved_observation_index += 1
            value = packet['observation']
            return dict(value, check_id=context['check_id'], observation_seq=context['observation_seq']), {}
        value = deepcopy(self.observations.pop(0)) if self.observations else dict(status='OK',
            visible_blocks=deepcopy(self.scene),
            verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in range(1,6)],reason=None)
        return dict(value, check_id=context['check_id'],observation_seq=context['observation_seq']), {}

    def background(self, port, request, function):
        token = self.cancelled
        def run():
            try:
                result = function(token)
                self.inbox.put(('module', (port,request['request_id'],result)))
            except Exception as error:
                self.inbox.put(('failure',(port,request['request_id'],type(error).__name__+': '+str(error))))
        worker = Thread(target=run,daemon=True)
        self.workers.append(worker)
        worker.start()

    def emit(self, port, payload):
        if port.startswith('a.'):
            functions = {'a.whole':handle_whole_plan,'a.assess':handle_step_reassessment,'a.motion':handle_step_motion}
            self.background(port,payload,lambda token:functions[port](deepcopy(payload['input'])))
        elif port == 'd.prepare_step':
            block = payload['step']['after']
            column = block['brick_type'],block['color']
            index = self.slot_indices.get(column,1)
            self.workflow.prepared_step(prepare(self.workflow,payload,slot_index=index,robot_sample=self.robot_sample))
        elif port.startswith('c.'):
            self.c_pending = port,deepcopy(payload)
            if port == 'c.initial' and self.fixture_design is not None:
                self.inbox.put(('module',(port,payload['request_id'],
                    dict(status='OK',hri_result=None,design=deepcopy(self.fixture_design),error=None))))
                self.c_pending = None
            else:
                self.question = ('미리보기를 확인하고 C에게 승인 또는 수정 의견을 답해주세요.' if port=='c.review' else
                    '원하는 설계를 C에게 말씀해주세요.' if port=='c.initial' else
                    str(payload.get('reason') or '실제 배치가 달라졌습니다.')+'\n기존 목표를 유지할까요, 설계를 수정할까요?')
                self.workflow.dialogue['assistant_text']=self.question
        elif port == 'robot.EXECUTE':
            self.last_document = execution_document(payload['bundle'],payload['execution_id'])
            if self.round3_step_replay is not None:
                replay = deepcopy(self.round3_step_replay)
                if self.saved_observation_replay:
                    block = self.last_document['step']['block']
                    matches = [m for m in replay.pop('measurements', []) if m['block'] == block]
                    if len(matches) != 1:
                        raise ValueError('SAVED_REPLAY_EXACT_STEP_MEASUREMENT_REQUIRED')
                    replay['measured'] = matches[0]
                    replay.pop('saved_observations')
                    replay.pop('revised_candidates', None)
                    replay['saved_observation_flow'] = True
                self.last_document['round2_replay'] = replay
            self.robot.send('EXECUTE',document=deepcopy(self.last_document))
        elif port == 'robot.RESUME':
            if self.last_document is None:
                raise ValueError('No stopped Step')
            document = deepcopy(self.last_document)
            document['session'].update(execution_id=payload['execution_id'],
                resume_current_revision=payload['current']['current_revision'],expires_unix_s=time.time()+600)
            self.last_document = document
            self.robot.send('RESUME',document=document)
        elif port.startswith('robot.'):
            self.robot.send(port.split('.')[1],**payload)
        else:
            raise ValueError('unknown integration port '+port)

    def answer(self, text):
        if self.c_pending is None or not text.strip():
            return False
        port,payload = self.c_pending
        self.c_pending = None
        self.workflow.dialogue.update(user_text=text,phase='GENERATING')
        def call(token):
            if port == 'c.initial':
                return c_main.create_initial_design(text=text,should_stop=token.is_set)
            context={k:deepcopy(payload.get(k)) for k in ('expected','difference','observation','reason')}
            difference = payload.get('difference')
            confirmed = difference and (difference['missing'] or difference['unexpected'])
            pairs = differences_for_c(dict(difference,unobservable=[])) if confirmed else []
            if port == 'c.review':
                return c_main.review_design_candidate(payload['candidate'],kind=payload['kind'],
                    previous_design=payload['previous_design'],current=payload['current']['blocks'],
                    differences=pairs,text_answers=[text],should_stop=token.is_set,
                    change_reason=payload.get('change_reason'),
                    design_metadata=payload.get('design_metadata'),planning_failure=payload.get('planning_failure'))
            replay_kwargs = {}
            if self.design_change_replay:
                def generate(design, current, differences, reasons):
                    candidates = [v for v in self.round3_step_replay.get('revised_candidates', [])
                        if v['from_design_version'] == design['design_version']
                        and v['current'] == current and v['reason'] == payload['reason']]
                    if len(candidates) != 1:
                        raise ValueError('REPLAY_REVISED_CANDIDATE_BINDING_REQUIRED')
                    return dict(blocks=deepcopy(candidates[0]['blocks']))
                replay_kwargs['revised_generator'] = generate
            if pairs:
                return c_main.run_intervention(payload['design'],payload['current']['blocks'],pairs,
                    text_answers=[text],should_stop=token.is_set,inspection_context=context,**replay_kwargs)
            return c_main.run_design_change(payload['design'],payload['current']['blocks'],
                reason=payload['reason'],text_answers=[text],should_stop=token.is_set,inspection_context=context,
                planning_failure=payload.get('planning_failure'),**replay_kwargs)
        self.background(port,payload,call)
        return True

    def command(self, name):
        if self.saved_observation_replay and (name in ('RESUME', 'REINSPECT', 'CONTINUE_AFTER_CORRECTION')
                or name == 'REQUEST_DESIGN_CHANGE' and not self.design_change_replay):
            return False  # The file describes one fixed capture sequence, not a new scene.
        if name == 'START':
            if self.workflow.status not in ('IDLE','COMPLETE') or self.workflow.storage=='PENDING':return False
            if self.login_pending or self.owner_state=='PENDING':return False
            if self.history_dsn is not None and self.creator is None:
                self.creator_reason='시작 전에 제작자 로그인이 필요합니다.'
                return False
            self.scene, self.slot_indices = [],{}
            self.saved_observation_index = 0
            self.consumed_executions.clear()
            self.scene_executions.clear()
            self.cancelled = Event()
            self.b.close()
            self.b=connect_inspection(lambda value:self.inbox.put(('b',value)),observe=self.observe,
                geometry_reference=self.workflow.settings['geometry_reference'])
            self.workflow.b=self.b
            started = self.workflow.start()
            if started:
                self.job_creator = deepcopy(self.creator)
                self.owner_state = 'NOT_STARTED'
                if self.job_creator is not None:
                    self.link_creator()
            return started
        if name == 'STOP':
            self.cancelled.set()
            self.c_pending = None
            return self.workflow.stop()
        if name == 'RESUME':
            self.cancelled = Event()
            return self.workflow.resume()
        if name == 'REQUEST_DESIGN_CHANGE':return self.workflow.change_design()
        if name == 'REINSPECT':return self.workflow.reinspect()
        if name == 'CONTINUE_AFTER_CORRECTION':return self.workflow.correction_finished()
        return False

    def request(self, value):
        name=value.get('command')
        request=(validate_user_request(value) if name=='REQUEST_DESIGN_CHANGE' else validate_hmi_command(value))
        if name!='START' and request.get('job_id')!=self.workflow.job_id:return False
        if name=='REQUEST_DESIGN_CHANGE' and request['request_id']!=self.workflow.change_request_id:return False
        if name=='CONTINUE_AFTER_CORRECTION' and request['request_id']!=self.workflow.change_request_id:return False
        if name=='SUPPLY_REFILLED':
            column=request['brick_type'],request['color']
            row=next((r for r in self.workflow.supply if (r['brick_type'],r['color'])==column),None)
            if self.workflow.status!='HOLD' or not row or not row['needs_refill']:return False
            self.slot_indices[column]=1
            row.update(next_slot=1,needs_refill=False)
            self.workflow.event('SUPPLY_REFILLED',request)
            self.workflow.calculate_next()
            return True
        return self.command(name)

    def login(self, username, password):
        if (self.history_dsn is None or self.login_pending or self.owner_state=='PENDING' or
                self.workflow.status not in ('IDLE','COMPLETE') or self.workflow.storage=='PENDING'):
            return False
        self.login_pending = True
        self.creator_reason = None
        def run():
            try:
                from history import accounts, store
                with store.connect(self.history_dsn) as connection:
                    user = accounts.authenticate(connection,username,password)
                if user is None:raise ValueError('로그인 ID 또는 비밀번호를 확인해주세요.')
                result = {key:user[key] for key in ('user_id','username','display_name')}
                self.inbox.put(('login',(result,(username,password),None)))
            except Exception as error:
                message = str(error) if isinstance(error,ValueError) else 'DB 로그인 연결 실패: '+type(error).__name__
                self.inbox.put(('login',(None,None,message)))
        worker=Thread(target=run,daemon=True)
        self.workers.append(worker);worker.start()
        return True

    def logout(self):
        if (self.login_pending or self.owner_state=='PENDING' or self.workflow.storage=='PENDING' or
                self.workflow.status not in ('IDLE','COMPLETE')):return False
        self.creator = self._credentials = None
        self.creator_reason = None
        return True

    def link_creator(self):
        job, creator = self.workflow.job_id, deepcopy(self.job_creator)
        self.owner_state = 'PENDING'
        def run():
            try:
                from history import store
                from history.mvp_save import link_current_job
                with store.connect(self.history_dsn) as connection:
                    link_current_job(connection,self.workflow.log_directory,job,creator)
                failure = None
            except Exception as error:
                failure = str(error) if isinstance(error,ValueError) else type(error).__name__
            self.inbox.put(('owner',(job,failure)))
        worker=Thread(target=run,daemon=True)
        self.workers.append(worker);worker.start()

    def save_logged_in(self):
        if not self.creator or not self.job_creator or self.creator['user_id']!=self.job_creator['user_id']:
            self.creator_reason='이 작업을 시작한 제작자로 로그인해주세요.'
            return False
        return self.save(self.history_dsn,*self._credentials,web_url=self.web_url)

    def save(self, dsn, username, password, *, web_url='http://127.0.0.1:8765'):
        if self.workflow.status!='COMPLETE' or self.workflow.storage=='PENDING':return False
        if self.owner_state=='PENDING':return False
        if self.job_creator and username!=self.job_creator['username']:return False
        expected_user_id = self.job_creator['user_id'] if self.job_creator else None
        job=self.workflow.job_id
        self.workflow.storage='PENDING'
        self.workflow.web='NOT_STARTED'
        self.workflow.save_reason=None
        def run():
            try:
                from history import store
                from history.mvp_save import save_current_job, verify_web_job
                from uuid import uuid4
                with store.connect(dsn) as connection:
                    result=save_current_job(connection,self.workflow.log_directory,job,username,password,str(uuid4()),
                                            expected_user_id=expected_user_id)
            except Exception as error:
                self.inbox.put(('save',(job,None,str(error) if isinstance(error,ValueError) else type(error).__name__)))
                return
            self.inbox.put(('save',(job,result,None)))
            try:
                verify_web_job(web_url,job,username,password,result['receipt'])
                self.inbox.put(('web',(job,None)))
            except Exception as error:
                self.inbox.put(('web',(job,str(error) if isinstance(error,ValueError) else type(error).__name__)))
        worker=Thread(target=run,daemon=True)
        self.workers.append(worker);worker.start()
        return True

    def poll(self):
        while True:
            try: kind,data=self.inbox.get_nowait()
            except Empty: break
            if kind in ('b','module'):
                try:
                    if kind=='b':self.workflow.receive_check(data)
                    else:self.workflow.receive(*data)
                except (ValueError,KeyError,TypeError) as error:
                    self.workflow.status,self.workflow.reason='HOLD',str(error)
                    self.workflow.event('INVALID_MODULE_RESULT',reason=str(error))
            elif kind=='login':
                creator,credentials,error=data
                self.login_pending=False
                self.creator_reason=error
                if not error:self.creator,self._credentials=creator,credentials
            elif kind=='owner':
                job,error=data
                if job==self.workflow.job_id:
                    self.owner_state='FAILED' if error else 'SUCCEEDED'
                    self.creator_reason='제작자 DB 연결 실패: '+error if error else None
            elif kind=='save':
                job,result,error=data
                if job==self.workflow.job_id:
                    self.workflow.storage='FAILED' if error else 'SUCCEEDED'
                    self.workflow.web='NOT_STARTED' if error else 'PENDING'
                    self.workflow.save_reason=error
                    if not error and self.job_creator:
                        self.owner_state='SUCCEEDED'
                        self.creator_reason=None
            elif kind=='web':
                job,error=data
                if job==self.workflow.job_id:
                    self.workflow.web='FAILED' if error else 'SUCCEEDED'
                    self.workflow.save_reason=error
            elif kind=='voice_progress':
                identity,value=data
                if self.workflow.active and self.workflow.active['request']['request_id']==identity:
                    self.workflow.dialogue['assistant_text']=str(value.get('message',''))[:1200]
            else:
                port,identity,reason=data
                active=self.workflow.active
                if active and active['request']['request_id']==identity:
                    self.workflow.active=None
                    self.workflow.status,self.workflow.reason='HOLD',reason
        while True:
            try: row=self.robot.events.get_nowait()
            except Empty: break
            if row['event'] == 'STATE_SNAPSHOT':
                self.state_snapshot(row['data'])
                continue
            if (row['event']=='GESTURE_STOP_REQUESTED'
                    and row['data'].get('execution_id') in (self.workflow.execution_id,self.workflow.last_execution_id)):
                # 제스처 정지도 HMI 정지와 같이 C 요청과 계산 세대를 닫는다.
                self.command('STOP')
            if (row['event']=='ASSEMBLY_CUE_FINISHED' and self.robot_mode == 'REAL'
                    and not row['data'].get('received')
                    and self.workflow.settings.get('observation_kind')=='SYNTHETIC'):
                # 가짜 B가 사람 조립 확인 시간 초과를 완료로 대신 승인하지 않는다.
                self.next_fake_check='UNOBSERVABLE'
            if row['data'].get('sample'):
                self.robot_sequence+=1
                self.robot_sample=dict(deepcopy(row['data']['sample']),state_sequence=self.robot_sequence)
            if row['event']=='SIGNAL_REQUEST':
                self.ready_signal=deepcopy(row['data'])
            elif row['event']=='SIGNAL_REQUEST_CLOSED':self.ready_signal=None
            elif (row['event']=='GRIP_SUCCEEDED' and row['data'].get('label')=='PICKUP_CLOSE'
                  and row['data'].get('execution_id')==self.workflow.execution_id
                  and self.workflow.execution_id not in self.consumed_executions):
                slot=self.workflow.step_inputs['slot']
                column=slot['brick_type'],slot['color']
                self.consumed_executions.add(self.workflow.execution_id)
                self.slot_indices[column]=next_supply_slot(slot['slot_index'],self.supply_slot_count)
                for supply in self.workflow.supply:
                    if (supply['brick_type'],supply['color'])==column:
                        index=self.slot_indices[column]
                        supply.update(next_slot=index,needs_refill=False)
            elif (row['event']=='INSPECTION_REQUIRED'
                  and row['data'].get('execution_id')==self.workflow.execution_id
                  and self.workflow.reason!='STOP_PENDING' and self.workflow.status!='STOPPED'
                  and self.workflow.execution_id not in self.scene_executions):
                # 새 실행의 물리 효과만 모의 장면에 적용한다. 재검사는 B만 다시 호출한다.
                target=self.workflow.step()['after']
                self.scene_executions.add(self.workflow.execution_id)
                if target not in self.scene:self.scene.append(deepcopy(target))
            elif row['event']=='PROCESS_EXITED' and self.robot_retired:
                continue  # A reviewed native skill now owns the device writer.
            elif row['event']=='PROCESS_EXITED' and not self.closed:
                self.workflow.status,self.workflow.reason='HOLD','ROBOT_PROCESS_EXITED'
            self.workflow.robot_event(row)
        if self.auto_gestures and self.ready_signal and self.workflow.status not in ('STOPPED', 'HOLD'):
            if self.ready_signal.get('_sent') and self.ready_signal['kind'] != 'RECEIVE':
                return
            pose = ('OPEN_HAND' if self.direct_handover else None) if self.ready_signal['kind'] == 'RECEIVE' else 'THUMBS_UP'
            self.gesture(pose)
            self.ready_signal['_sent'] = True

    def gesture(self, pose):
        """Synthetic camera candidate through D's actual stage dispatcher; no camera/ROS."""
        if self.robot_mode != 'MOCK':
            raise ValueError('SYNTHETIC_GESTURE_CANNOT_CONTROL_REAL_ROBOT')
        if pose not in (None, 'OPEN_HAND', 'THUMBS_UP', 'FIST'):
            raise ValueError('unsupported synthetic hand pose')
        if not self.last_document:
            return False
        session = self.last_document['session']
        request = self.ready_signal
        now = time.monotonic_ns()
        sample = dict(provenance='SYNTHETIC', execution_id=session['execution_id'],
            source_epoch=session['source_epoch'], preview_request_id=request['request_id'] if request else None,
            received_monotonic_ns=now, source_ns=now+1, frame='FAKE_GESTURE_CAMERA',
            hands=[] if pose is None else [dict(pose=pose, center=[100.,100.], palm_size=40.)],
            candidate_event='THUMBS_UP_HELD' if pose == 'THUMBS_UP' else
                'OPEN_HAND_HELD_ORIENTATION_UNKNOWN' if pose == 'OPEN_HAND' else None,
            continuity_estimate=True, pose_verified=False)
        self.robot.send('GESTURE_SAMPLE', sample=sample)
        return True

    def close(self):
        self.closed=True
        self.cancelled.set()
        self.b.close()
        self.robot.close()
        for worker in self.workers:worker.join(timeout=1)
        self.creator = self._credentials = None


def render_creator(window, runtime):
    if runtime.history_dsn is not None:
        creator = runtime.creator
        window.creator_identity.setText('제작자: '+(creator['display_name']+' (@'+creator['username']+')' if creator else '로그인 필요'))
        owner = runtime.job_creator
        states={'NOT_STARTED':'연결 전','PENDING':'연결 중','SUCCEEDED':'DB 연결됨','FAILED':'연결 실패'}
        window.creator_job.setText('현재 작업: @'+owner['username']+' · '+states[runtime.owner_state] if owner else '')
        window.creator_notice.setText(runtime.creator_reason or ('로그인 확인 중' if runtime.login_pending else ''))
        can_change = runtime.workflow.status in ('IDLE','COMPLETE') and runtime.workflow.storage!='PENDING' and runtime.owner_state!='PENDING' and not runtime.login_pending
        window.creator_login.setEnabled(can_change)
        window.creator_logout.setEnabled(can_change and creator is not None)
        window.buttons['START'].setEnabled(window.buttons['START'].isEnabled() and creator is not None and not runtime.login_pending and runtime.owner_state!='PENDING')
        can_save = creator is not None and owner is not None and creator['user_id']==owner['user_id']
        window.completion_view.save_button.setEnabled(window.completion_view.save_button.isEnabled() and can_save and runtime.owner_state!='PENDING')


def main(runtime_class=MvpIntegration, *, real_trial=False):
    parser=argparse.ArgumentParser(description='C/A 전체 함수·REAL Robot/카메라 제스처 시험. B 관측/Current는 가짜입니다.' if real_trial else __doc__)
    parser.add_argument('--robot-root',required=True,type=Path)
    parser.add_argument('--log-directory',type=Path,default=Path('logs/mvp-integration'))
    parser.add_argument('--design',type=Path,help='C 미리보기 후보 파일; 사용자 승인과 구분. 생략하면 C 생성 함수 사용')
    parser.add_argument('--c-mode',choices=('offline','live'),default='offline')
    parser.add_argument('--round3-step-replay', type=Path,
        help='합성 측정 JSON으로 A 한 Step→round2 제어 연결 검사. MOCK 전용')
    if real_trial:
        parser.add_argument('--round3-fixed-step', action='store_true',
            help='T1 고정 현장 시험만 HMI에서 실행. C/A 실행·B 완료·최종 저장과 분리')
        parser.add_argument('--round3-approved-step', action='store_true',
            help='C 승인·실제 A 한 Step을 대응 native 교시·공급 프로파일에 연결하고 B 확인 전 보류')
        parser.add_argument('--initial-observation', type=Path,
            help='실제 B INITIAL 저장 폴더(context.json/observed.json/V0·D1·D3 metadata.json)')
        parser.add_argument('--fixed-trial-scenario', type=Path,
            help='고정 T1 native 시험에 전달할 별도 시나리오')
        parser.add_argument('--execution-profile', type=Path, help='교육용 조건부 공급 실행 프로파일')
        parser.add_argument('--supply-depth-profile', type=Path,
            help='고정 T1 native 시험에 전달할 공급판 RGB-D 보정 프로파일')
        parser.add_argument('--educational-depth-demo', action='store_true',
            help='고정 T1에만 교육용 공급판 보정 수용 옵션 전달')
        parser.add_argument('--contact-alignment-trial',action='store_true',help='연속 결착 하강 · 전체 반력 40N 정지 시험; 실물 미검증')
        parser.add_argument('--execute',action='store_true',required=True,
            help='실제 Robot·카메라 제스처 연결 허용. B 관측은 가짜 시험 입력')
    args=parser.parse_args()
    if real_trial and args.round3_step_replay is not None:
        parser.error('--round3-step-replay는 MOCK HMI 전용입니다.')
    if real_trial and args.round3_approved_step:
        if (args.round3_fixed_step or args.contact_alignment_trial or args.supply_depth_profile
                or args.educational_depth_demo or not args.initial_observation
                or not args.fixed_trial_scenario or not args.execution_profile):
            parser.error('--round3-approved-step에는 --initial-observation/--fixed-trial-scenario/--execution-profile이 필요하며 다른 시험 모드와 혼용할 수 없습니다.')
        from app.mvp_real_trial import ApprovedStepRealTrial
        runtime_class = ApprovedStepRealTrial
    if real_trial and args.initial_observation and not args.round3_approved_step:
        parser.error('--initial-observation은 --round3-approved-step 전용입니다.')
    if real_trial and not (args.round3_fixed_step or args.round3_approved_step) and (args.fixed_trial_scenario is not None
            or args.supply_depth_profile is not None or args.educational_depth_demo or args.execution_profile is not None):
        parser.error('별도 native 시나리오/공급판 보정 옵션은 --round3-fixed-step에서만 사용할 수 있습니다.')
    if real_trial and args.execution_profile is not None and (args.supply_depth_profile is not None or args.educational_depth_demo):
        parser.error('--execution-profile과 이전 공급 보정 옵션은 함께 사용할 수 없습니다.')
    if real_trial and args.educational_depth_demo and args.supply_depth_profile is None:
        parser.error('--educational-depth-demo에는 --supply-depth-profile이 필요합니다.')
    if real_trial and args.round3_fixed_step and args.contact_alignment_trial:
        parser.error('T1 고정 시험은 기존 round2 설정을 사용합니다. --contact-alignment-trial과 함께 사용하지 마세요.')
    if real_trial and args.round3_fixed_step and args.design:
        parser.error('T1 고정 시험에는 --design을 사용할 수 없습니다. 기존 T1 시나리오만 실행합니다.')
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox
    from app.qt_hmi import HmiWindow
    app=QApplication([])
    window=HmiWindow()
    design=json.loads(args.design.read_text()) if args.design else None
    runtime=runtime_class(args.robot_root,args.log_directory,fixture_design=design,c_mode=args.c_mode,
        history_dsn=os.environ.get('HISTORY_DATABASE_DSN'),
        web_url=os.environ.get('HISTORY_WEB_URL','http://127.0.0.1:8765'),
        **(dict(contact_alignment_trial=args.contact_alignment_trial,
                **({'round3_fixed_step':True,'fixed_trial_scenario':args.fixed_trial_scenario,
                    'supply_depth_profile':args.supply_depth_profile,'educational_depth_demo':args.educational_depth_demo,
                    'execution_profile':args.execution_profile}
                   if args.round3_fixed_step else
                   dict(initial_observation=args.initial_observation, fixed_trial_scenario=args.fixed_trial_scenario,
                        execution_profile=args.execution_profile) if args.round3_approved_step else {})) if real_trial else
            ({'round3_step_replay':json.loads(args.round3_step_replay.read_text())}
                if args.round3_step_replay is not None else {})))
    window.creator_bar.setVisible(runtime.history_dsn is not None)
    if real_trial:
        from PyQt5.QtWidgets import QCheckBox, QPushButton, QComboBox
        trial_suffix=' · 결착 반력 40N 정지 시험' if args.contact_alignment_trial else ''
        review=QCheckBox('실물 시험 준비: 빈 조립판·공급 보충·교시 경로·도움/인계 영역 확인 · B는 가짜'+trial_suffix)
        window.layout().insertWidget(1,review)
        review.toggled.connect(runtime.review_preparation)
        voice=QPushButton('C 음성 대화')
        window.layout().insertWidget(2,voice)
        voice.clicked.connect(runtime.answer_voice)
        fake_check=QComboBox()
        fake_check.addItems(['B 가짜: 기본 일치','B 가짜: 다음 Step 불일치',
                            'B 가짜: 다음 Step 관측 불가','B 가짜: 다음 Step ERROR'])
        window.layout().insertWidget(3,fake_check)
        operator_confirm=QPushButton('확인')
        operator_confirm.setVisible(False)
        window.layout().insertWidget(4,operator_confirm)
        operator_confirm.clicked.connect(lambda:runtime.confirm_operator(runtime.ready_signal['request_id'])
            if runtime.ready_signal else None)
        fake_check.currentIndexChanged.connect(lambda index:setattr(runtime,'next_fake_check',
            ('MATCH','MISMATCH','UNOBSERVABLE','ERROR')[index]))
        window.setWindowTitle('전체 기능 실물 시험 · REAL Robot/제스처 · 가짜 B'+trial_suffix)
        if args.round3_fixed_step:
            review.setText('T1 시험 준비 확인: 기존 8블록 사전배치·노랑 2×2 슬롯4·빈 그리퍼 HOME·작업영역 확인')
            voice.hide()
            fake_check.hide()
        if args.round3_approved_step:
            review.setText('승인 Step 시험 준비: 관측 이후 8블록 배치 유지·공급 슬롯 준비·빈 그리퍼 HOME·기존 경로 확인')
            fake_check.hide()
    def publish():
        runtime.poll()
        snapshot=runtime.workflow.snapshot()
        window.render_snapshot(snapshot)
        render_creator(window,runtime)
        window.heading.setText('전체 기능 실물 시험 · C/A 실제 함수 · REAL Robot/제스처 · B 가짜 관측/Current'
            if real_trial else '협동 조립 · 최종 MVP · FAKE Robot/Camera/제스처 · A/B 실제 계산')
        if real_trial:
            window.setWindowTitle('전체 기능 실물 시험 · REAL Robot/제스처 · 가짜 B'+trial_suffix)
            review.setEnabled(runtime.workflow.status in ('IDLE','COMPLETE'))
            fake_check.blockSignals(True)
            fake_check.setCurrentIndex(('MATCH','MISMATCH','UNOBSERVABLE','ERROR').index(runtime.next_fake_check))
            fake_check.blockSignals(False)
            window.buttons['START'].setEnabled(window.buttons['START'].isEnabled() and runtime.review_ref is not None)
            voice.setEnabled(runtime.c_pending is not None and runtime.c_mode == 'live')
            if runtime.workflow.status=='COMPLETE':
                window.status.setText('통합 시험 흐름 완료 · B 가짜 · 실물 완성 판정은 별도')
        window.dialogue_input.setVisible(runtime.c_pending is not None)
        window.dialogue_send.setVisible(runtime.c_pending is not None)
        window.reinspection_button.setVisible(runtime.workflow.status=='HOLD' and runtime.workflow.inspection is not None
            and runtime.workflow.inspection['status'] in ('ERROR','UNOBSERVABLE'))
        if real_trial and runtime.ready_signal and runtime.workflow.status not in ('STOPPED','HOLD'):
            messages=dict(ALIGNMENT_READY='블록과 목표의 실물 정렬을 확인한 뒤 엄지척을 2초 보여주세요. 접촉 전 대기 중입니다.',
                HELP_READY='표시된 도움을 준비한 뒤 엄지척을 2초 보여주세요. 해제 안내 전까지 도움을 유지해주세요.',
                RECEIVE='받을 준비가 됐으면 편 손을 보여주세요. 인계 대기 중 편 손은 정지가 아니라 받기 응답입니다.',
                ASSEMBLY_ACK='다음 스텝으로 넘어갈까요? 사람 조립을 마쳤으면 엄지척을 2초 보여주세요. B 관측은 가짜입니다.')
            window.notice.setPlainText(messages[runtime.ready_signal['kind']])
        if real_trial:
            request=runtime.ready_signal
            available=bool(request and request.get('operator_button_allowed') and
                runtime.workflow.status not in ('STOPPED','HOLD'))
            operator_confirm.setVisible(available)
            operator_confirm.setEnabled(available and not request.get('_operator_sent',False))
            if available:
                operator_confirm.setText(dict(RECEIVE='손으로 받을 준비 완료',HELP_READY='도움 준비 완료',
                    ASSEMBLY_ACK='조립 완료 · 검사 진행',ALIGNMENT_READY='정렬 확인 완료')[request['kind']])
                window.notice.setPlainText(window.notice.toPlainText()+'\n제스처가 인식되지 않으면 확인 버튼을 누르세요.')
        if runtime.c_pending:window.notice.setPlainText(runtime.question)
        if args.round3_step_replay is not None:
            window.heading.setText('ABCD 저장 관측 검사 · 실제 장치 없음' if runtime.saved_observation_replay else
                '통합 2단계 · A 한 Step → round2 제어 · 합성 관측/반력 · 실제 장치 없음')
            window.setWindowTitle('Round3 ABCD 저장 관측 검사 · MOCK 전용' if runtime.saved_observation_replay else
                'Round3 A Step 연결 검사 · MOCK 전용')
            if runtime.design_change_replay:
                window.heading.setText('설계 변경·차이 대응 → 승인 → A 재계획 · 저장 관측 MOCK 전용')
            if runtime.saved_observation_replay:
                window.reinspection_button.hide()
        if real_trial and args.round3_fixed_step:
            window.setWindowTitle('Round3 · T1 고정 로봇 시험 · 최종 조립 판정 아님')
            window.heading.setText('T1: 노랑 2×2 슬롯4 → (9,9,L2) · 기존 8블록 배치 필요')
            window.buttons['START'].setText('T1 고정 시험 시작')
            window.buttons['RESUME'].setEnabled(False)
            running = runtime.fixed_trial is not None and runtime.fixed_trial.process is not None and runtime.fixed_trial.process.poll() is None
            window.buttons['STOP'].setEnabled(running)
            window.dialogue_input.hide()
            window.dialogue_send.hide()
            if runtime.fixed_trial is not None:
                window.notice.setPlainText((runtime.workflow.reason or '')+'\n기록: '+str(runtime.fixed_trial.directory))
        if real_trial and args.round3_approved_step:
            window.setWindowTitle('Round3 · C 승인 → A 한 Step → 실제 D · B 후속 확인 대기')
            window.heading.setText('기존 8블록 + T1/T2/T3 설계 승인 · 첫 A Step만 실제 실행 · 초기 B 저장 관측 사용')
            window.buttons['START'].setText('준비 확인 · 설계 시작')
            progress = snapshot['progress']
            window.progress.setText(f"현재 Plan · B 조립 확인 {progress['completed']} / {progress['total']} Step")
            window.design_caption.setText('C 승인 설계 · D 실행 결과는 B 조립 확인과 구분')
            window.footer.setText('REAL · 초기 B 저장 실관측 · 실행 후 B 확인·연속 실행·최종 저장 미연결')
            window.buttons['RESUME'].setEnabled(False)
            window.reinspection_button.hide()
            if runtime.fixed_trial is not None:
                window.user_request_controls.buttons['change_design'].setEnabled(False)
                window.buttons['STOP'].setEnabled(runtime.fixed_trial.process is not None
                    and runtime.fixed_trial.process.poll() is None)
                window.notice.setPlainText((runtime.workflow.reason or '실제 D 한 Step 실행 중')
                    + '\n기록: ' + str(runtime.fixed_trial.directory))
    def request(value):
        accepted=runtime.request(value)
        if 'request_id' in value:
            window.mvp_reply_received.emit(dict(value,accepted=accepted,reason=None if accepted else '현재 접수할 수 없습니다.'))
    def save():
        if runtime.workflow.status!='COMPLETE':return
        if runtime.history_dsn is not None:
            runtime.save_logged_in()
            return
        username,ok=QInputDialog.getText(window,'개인 이력 저장','로그인 ID')
        if not ok:return
        password,ok=QInputDialog.getText(window,'개인 이력 저장','비밀번호',QLineEdit.Password)
        if not ok:return
        dsn=os.environ.get('HISTORY_DATABASE_DSN')
        if not dsn:
            QMessageBox.information(window,'저장 설정','DB 연결 설정이 필요합니다. 작업 JSONL은 보존되어 있습니다.')
            return
        runtime.save(dsn,username,password,web_url=os.environ.get('HISTORY_WEB_URL','http://127.0.0.1:8765'))
    def login():
        username,ok=QInputDialog.getText(window,'제작자 로그인','로그인 ID')
        if not ok:return
        password,ok=QInputDialog.getText(window,'제작자 로그인','비밀번호',QLineEdit.Password)
        if ok:runtime.login(username,password)
    window.creator_login.clicked.connect(login)
    window.creator_logout.clicked.connect(runtime.logout)
    window.command_requested.connect(request)
    window.mvp_request_requested.connect(request)
    window.preview_ready.connect(runtime.workflow.preview_ready)
    window.dialogue_answered.connect(runtime.answer)
    window.reinspection_requested.connect(lambda:runtime.command('REINSPECT'))
    window.completion_view.save_requested.connect(save)
    timer=QTimer();timer.timeout.connect(publish);timer.start(50)
    publish();window.show()
    try:app.exec_()
    finally:timer.stop();runtime.close()


if __name__=='__main__':main()
