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
    def __init__(self, robot_root, directory, *, fixture_design=None, c_mode='offline',
                 history_dsn=None, web_url='http://127.0.0.1:8765'):
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
        self.slot_indices = {}
        self.robot_sample=None
        self.robot_sequence=0
        self.closed = False
        self.history_dsn, self.web_url = history_dsn, web_url
        self.creator = self.job_creator = None
        self._credentials = None  # Memory only; never part of snapshots or JSONL.
        self.login_pending = False
        self.creator_reason = None
        self.owner_state = 'NOT_STARTED'
        self.workflow = MvpWorkflow(self.emit, settings(), directory)
        self.b = connect_inspection(lambda value:self.inbox.put(('b',value)),
            observe=self.observe, geometry_reference=self.workflow.settings['geometry_reference'])
        self.workflow.b = self.b
        self.robot = RobotProcess(robot_root, mode='MOCK')

    def observe(self, context, active):
        if not active():
            raise ValueError('inspection canceled')
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
                    change_reason=payload.get('change_reason'))
            if pairs:
                return c_main.run_intervention(payload['design'],payload['current']['blocks'],pairs,
                    text_answers=[text],should_stop=token.is_set,inspection_context=context)
            return c_main.run_design_change(payload['design'],payload['current']['blocks'],
                reason=payload['reason'],text_answers=[text],should_stop=token.is_set,inspection_context=context)
        self.background(port,payload,call)
        return True

    def command(self, name):
        if name == 'START':
            if self.workflow.status not in ('IDLE','COMPLETE') or self.workflow.storage=='PENDING':return False
            if self.login_pending or self.owner_state=='PENDING':return False
            if self.history_dsn is not None and self.creator is None:
                self.creator_reason='시작 전에 제작자 로그인이 필요합니다.'
                return False
            self.scene, self.slot_indices = [],{}
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
            else:
                port,identity,reason=data
                active=self.workflow.active
                if active and active['request']['request_id']==identity:
                    self.workflow.active=None
                    self.workflow.status,self.workflow.reason='HOLD',reason
        while True:
            try: row=self.robot.events.get_nowait()
            except Empty: break
            if row['data'].get('sample'):
                self.robot_sequence+=1
                self.robot_sample=dict(deepcopy(row['data']['sample']),state_sequence=self.robot_sequence)
            if row['event']=='SIGNAL_REQUEST':
                self.ready_signal=deepcopy(row['data'])
            elif row['event']=='SIGNAL_REQUEST_CLOSED':self.ready_signal=None
            elif row['event']=='INSPECTION_REQUIRED' and not row['data'].get('automatic_reinspection'):
                # 실제 관측 대신 모의 장면을 변경한다. Current는 B 결과가 올 때만 바뀐다.
                target=self.workflow.step()['after']
                if target not in self.scene:self.scene.append(deepcopy(target))
                column=target['brick_type'],target['color']
                self.slot_indices[column]=next_supply_slot(self.slot_indices.get(column,1))
                for supply in self.workflow.supply:
                    if (supply['brick_type'],supply['color'])==column:
                        index=self.slot_indices[column]
                        supply.update(next_slot=index,needs_refill=False)
            elif row['event']=='PROCESS_EXITED' and not self.closed:
                self.workflow.status,self.workflow.reason='HOLD','ROBOT_PROCESS_EXITED'
            self.workflow.robot_event(row)
        if self.ready_signal and self.workflow.status not in ('STOPPED','HOLD'):
            if self.ready_signal.get('_sent') and self.ready_signal['kind']!='RECEIVE':return
            signal=dict(self.ready_signal,source='FAKE',sequence=time.monotonic_ns(),verified=True)
            signal.pop('_sent',None)
            if signal['kind']=='RECEIVE':signal.update(hand_present=False,receiving_ready=False)
            else:signal['ready']=True  # 모의 엄지척. 실제 gesture producer를 호출하지 않는다.
            self.robot.send('SIGNAL',signal=signal)
            self.ready_signal['_sent']=True

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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-root',required=True,type=Path)
    parser.add_argument('--log-directory',type=Path,default=Path('logs/mvp-integration'))
    parser.add_argument('--design',type=Path,help='명시적인 FAKE C 후보 파일; 생략하면 C 생성 함수 사용')
    parser.add_argument('--c-mode',choices=('offline','live'),default='offline')
    args=parser.parse_args()
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox
    from app.qt_hmi import HmiWindow
    app=QApplication([])
    window=HmiWindow()
    design=json.loads(args.design.read_text()) if args.design else None
    runtime=MvpIntegration(args.robot_root,args.log_directory,fixture_design=design,c_mode=args.c_mode,
        history_dsn=os.environ.get('HISTORY_DATABASE_DSN'),
        web_url=os.environ.get('HISTORY_WEB_URL','http://127.0.0.1:8765'))
    window.creator_bar.setVisible(runtime.history_dsn is not None)
    def publish():
        runtime.poll()
        snapshot=runtime.workflow.snapshot()
        window.render_snapshot(snapshot)
        render_creator(window,runtime)
        window.heading.setText('협동 조립 · 최종 MVP · FAKE Robot/Camera/제스처 · A/B 실제 계산')
        window.dialogue_input.setVisible(runtime.c_pending is not None)
        window.dialogue_send.setVisible(runtime.c_pending is not None)
        window.reinspection_button.setVisible(runtime.workflow.status=='HOLD' and runtime.workflow.inspection is not None)
        if runtime.c_pending:window.notice.setPlainText(runtime.question)
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
