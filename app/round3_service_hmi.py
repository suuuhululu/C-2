"""The existing single-page HMI with live C dialogue and an isolated native child."""
import codecs
from copy import deepcopy
import json
import os
from queue import Empty,Queue
import sys
from threading import Thread
from uuid import uuid4

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QApplication,QInputDialog,QLineEdit,QPushButton,QTableWidgetItem)

from app.round3_stack_hmi import StackFiveWindow
from app.qt_hmi import COLOR_LABELS
from app.round3_service import ROOT,sources
from app import round3_stack_five as stack


class ServiceWindow(StackFiveWindow):
    def __init__(self,**options):
        self.creator=None;self.credentials=None;self.messages=Queue();self.busy_account=False
        self.archive_pending=False;self.final_result=None;self.change_requested=False
        self.archive_receipt=None;self.archive_key=None
        self.history_dsn=os.environ.get('HISTORY_DATABASE_DSN')
        self.web_url=os.environ.get('HISTORY_WEB_URL','http://127.0.0.1:8767')
        super().__init__(0,**options)
        self.setWindowTitle('Round3 · 빈 판 C·A·B·D·HMI·DB·웹 통합')
        self.heading.setText('빈 조립판 · 실제 C 설계/승인 → A 계획 → D 실행 → B 검사 · 사용자별 DB/웹')
        self.design_dialogue.parentWidget().show();self.creator_bar.show()
        self.creator_login.clicked.connect(self.login_dialog)
        self.creator_logout.clicked.connect(self.logout)
        self.ready.toggled.disconnect();self.ready.toggled.connect(self.update_ready)
        self.ready.setText('빈 조립판 · 공급 슬롯 · 빈 그리퍼 · 이동 경로·손 이탈 확인')
        self.buttons['START'].setText('빈 판 확인 · 설계 시작')
        self.buttons['RESUME'].setText('새 작업')
        self.change=QPushButton('설계 변경 요청 · 현재 Step 후')
        self.change.clicked.connect(self.request_change)
        self.archive=QPushButton('사용자 기록 DB·웹 저장 / 재시도')
        self.archive.clicked.connect(self.save_history);self.archive.setEnabled(False)
        self.creator_bar.layout().insertWidget(3,self.archive)
        self.layout().insertWidget(4,self.change)
        self.dialogue_send.clicked.disconnect();self.dialogue_input.returnPressed.disconnect()
        self.dialogue_send.clicked.connect(self.answer_text);self.dialogue_input.returnPressed.connect(self.answer_text)
        self.dialogue_input.show();self.dialogue_send.show();self.dialogue_send.setEnabled(False)
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll_accounts);self.timer.start(100)
        self.refresh_creator()
        if os.environ.get('C2_SIXPART_USERNAME') and os.environ.get('C2_SIXPART_PASSWORD'):
            self.login(os.environ['C2_SIXPART_USERNAME'],os.environ['C2_SIXPART_PASSWORD'])

    def new_plan(self):
        if self.active or self.archive_pending:return
        self.job_id=str(uuid4());folder=ROOT/'logs/round3-service'/self.job_id;folder.mkdir(parents=True)
        self.plan_path=folder/'startup.json';self.document=dict(scenario=dict(steps=[]))
        self.used=False;self.pending=None;self.current=None;self.target=None;self.index=None
        self.expected_base_blocks=[]
        self.final_result=None;self.change_requested=False
        self.archive_receipt=None;self.archive_key=str(uuid4())
        self.ready.setChecked(False);self.ready.setEnabled(True);self.review_panel.hide()
        self.buttons['START'].setEnabled(False);self.buttons['STOP'].setEnabled(False)
        self.buttons['RESUME'].setEnabled(True);self.layers.setRowCount(0)
        self.layers.setHorizontalHeaderLabels(['Step','목표','D 실행','B 검사'])
        self.design_board.set_blocks([]);self.inspection_view.current_board.set_blocks([])
        self.inspection_view.expected_board.set_blocks([])
        self.inspection_view.summary.setText('빈 판 INITIAL 대기 · B Current 미확정')
        self.inspection_view.details.clear()
        self.target_board.set_blocks([]);self.design_panel.setTitle('C 설계 · 아직 없음')
        self.design_caption.setText('고정 후보 없음 · C가 생성한 미리보기를 별도로 승인합니다.')
        self.status.setText('빈 판에서 새 작업 · 로그인 후 준비 확인')
        self.progress.setText('C 설계·A 계획 대기 · 로봇 명령 없음')
        self.supply.setText('I 50N · P 60N 반력 정지 · 70N 이상 보류 · 접촉 3mm/s\n조립판 O 47mm (32~55) · 공급/인계 53mm (40~80)\n빨강 1×2 파지 20mm (10~40)')
        self.notice.setPlainText('로그인 → 준비 확인 → 빈 판 B 검사 → C 설계 대화 → 미리보기 승인 순서입니다.')
        self.footer.setText(str(folder))
        if hasattr(self,'archive'):self.archive.setEnabled(False)

    def update_ready(self,*_):
        self.buttons['START'].setEnabled(bool(self.creator) and not self.active and not self.used
            and self.ready.isChecked() and not self.busy_account)

    def refresh_creator(self):
        self.creator_identity.setText(self.creator['display_name'] if self.creator else '로그인 필요')
        self.creator_job.setText('작업 소유자: '+self.creator['username'] if self.creator else '')
        self.creator_notice.setText(self.web_url if self.history_dsn else 'DB 환경 파일 준비 필요')
        self.creator_login.setEnabled(not self.active and not self.busy_account and not self.archive_pending)
        self.creator_logout.setEnabled(not self.active and not self.busy_account and not self.archive_pending)
        self.update_ready()

    def login_dialog(self):
        user,ok=QInputDialog.getText(self,'제작자 로그인','아이디')
        if not ok:return
        password,ok=QInputDialog.getText(self,'제작자 로그인','비밀번호',QLineEdit.Password)
        if ok:self.login(user,password)

    def login(self,user,password):
        if self.active or self.busy_account or self.archive_pending or not self.history_dsn:return False
        self.busy_account=True;self.refresh_creator()
        def work():
            try:
                from history import store,accounts
                with store.connect(self.history_dsn) as connection:identity=accounts.authenticate(connection,user,password)
                if identity is None:raise ValueError('로그인 정보를 확인해주세요.')
                public={key:identity[key] for key in ('user_id','username','display_name')}
                self.messages.put(('login',public,(user,password)))
            except Exception as error:self.messages.put(('error','로그인 실패: '+type(error).__name__))
        Thread(target=work,daemon=True).start();return True

    def logout(self):
        if self.active or self.busy_account or self.archive_pending:return
        self.creator=self.credentials=None;self.refresh_creator()

    def start_run(self):
        if self.active or self.used or not self.ready.isChecked() or not self.creator:return
        if os.environ.get('C_DESIGN_USE_LLM')!='1' or not os.environ.get('OPENAI_LLM_API_KEY'):
            self.notice.setPlainText('실제 C 대화에 필요한 C_DESIGN_USE_LLM=1 / OPENAI_LLM_API_KEY를 환경 파일에 준비해주세요.');return
        config=dict(job_id=self.job_id,creator=deepcopy(self.creator),source_sha256=sources())
        stack.save(self.plan_path,config)
        self.used=True;self.active=True;self.terminal_result=False;self.buffer='';self.stderr=''
        self.decoder=codecs.getincrementaldecoder('utf-8')('replace');self.stop_requested=False
        self.ready.setEnabled(False);self.buttons['START'].setEnabled(False)
        self.buttons['STOP'].setEnabled(True);self.buttons['RESUME'].setEnabled(False)
        self.archive.setEnabled(False);self.refresh_creator()
        self.status.setText('빈 판 INITIAL · V0 → D1 → D3')
        self.process.setWorkingDirectory(str(ROOT))
        self.process.start(sys.executable,['-u','-m','app.round3_service','run','--execute','--config',str(self.plan_path)])

    def handle_event(self,event,data):
        if event=='REQUEST':
            if self.stop_requested or not self.active:return
            if self.pending is not None:raise ValueError('OVERLAPPING_SERVICE_REQUEST')
            self.pending=deepcopy(data);kind=data['kind']
            self.review_check.setChecked(False);self.review_check.setVisible(kind in ('B_FAILURE','REFILL','HANDOVER_READY','HUMAN_ASSEMBLY_DONE'))
            self.continue_button.setEnabled(kind=='STEP_READY')
            self.dialogue_send.setEnabled(kind=='C_TEXT');self.dialogue_input.setEnabled(kind=='C_TEXT')
            self.review_panel.setVisible(kind!='C_TEXT')
            if kind=='C_TEXT':
                self.status.setText('C 설계 대화 · 답변 대기');self.design_dialogue.phase.setText('C에게 답변해주세요')
                self.notice.setPlainText(data['prompt']);self.dialogue_input.setFocus()
            elif kind=='STEP_READY':
                self.index=data['index'];self.render_target(data['case']['target'])
                self.continue_button.setText('이 Step 실행')
                b=data['case']['target']
                self.notice.setPlainText(f"공급: {COLOR_LABELS[b['color']]} {b['brick_type']} 슬롯 {data['case']['supply_slot']}\n"
                    'A 목표·공급 슬롯·경로를 확인하세요. 설계 변경도 요청할 수 있습니다.')
                if self.change_requested:self.respond('CHANGE');self.change_requested=False
            elif kind=='REFILL':
                self.review_check.setText(data['column']+' 공급 슬롯을 보충했고 손을 뺐습니다.')
                self.continue_button.setText('보충 확인 후 계속')
            elif kind=='HANDOVER_READY':
                self.review_check.setText('place board를 비웠고 인계 경로에서 손을 뺐습니다.')
                self.continue_button.setText('전달판으로 인계 시작')
                self.status.setText('A 사람 조립 선택 · place board 인계 준비')
                self.notice.setPlainText('로봇이 이 블록을 전달판에 놓고 HOME으로 복귀합니다. 그 뒤 블록을 받아 조립하세요.')
            elif kind=='HUMAN_ASSEMBLY_DONE':
                b=data['case']['target']
                supports=[h['target_block'] for h in data['human_actions'] if h['action']=='HOLD']
                help_text='\n'.join(f"지지: {COLOR_LABELS[s['color']]} {s['brick_type']} "
                    f"({s['x']},{s['y']}) · {s['layer']}층" for s in supports)
                self.review_check.setText('목표 위치에 조립했고 손을 뺐습니다. B 검사 진행')
                self.continue_button.setText('조립 완료 신호 · 실제 B 검사')
                self.status.setText('사람 조립 대기 · 로봇 HOME 확인됨')
                self.notice.setPlainText(f"전달판의 {COLOR_LABELS[b['color']]} {b['brick_type']}를 "
                    f"({b['x']},{b['y']}) · {b['layer']}층 · {b['orientation_deg']}°에 조립하세요.\n"
                    '이 확인은 B MATCH가 아닙니다.\n'+help_text)
            else:
                self.review_check.setText('실물 확인 · B 실패를 보존한 채 이번 건만 계속')
                self.continue_button.setText('확인 기록 후 계속')
                self.status.setText(data['check_kind']+' B 실패 · 체크박스 확인 대기')
                self.notice.setPlainText(json.dumps(data['failure'],ensure_ascii=False,indent=2))
            return
        if event in ('C_QUESTION','C_PROGRESS'):
            self.design_dialogue.phase.setText(data.get('text') or data.get('message') or 'C 처리 중');return
        if event=='C_PREVIEW':
            self.design_board.set_blocks(data['design']['blocks']);self.design_panel.setTitle('C 미승인 미리보기')
            self.design_caption.setText('C 대화로 승인한 뒤에만 A 계획을 요청합니다.');return
        if event=='SERVICE_C_APPROVED':
            self.design_panel.setTitle('C 승인 설계 v'+str(data['design']['design_version']));return
        if event=='SERVICE_A_PLAN':
            steps=data['plan']['steps'];self.layers.setRowCount(len(steps));self.index=None
            self.expected_base_blocks=deepcopy(data.get('base_current',{}).get('blocks',[]))
            self.document['scenario']['steps']=[dict(target=s['after']) for s in steps]
            for i,s in enumerate(steps):
                b=s['after']
                for j,text in enumerate((s['step_id'],f"{COLOR_LABELS[b['color']]} {b['brick_type']} L{b['layer']}",'대기','대기')):
                    self.layers.setItem(i,j,QTableWidgetItem(text))
            self.render_expected()
            self.design_caption.setText('A 전체 계획 '+str(len(steps))+' Step · '+data['state_basis']);return
        if event=='SERVICE_A_HOLD':self.notice.setPlainText(data['reason']);return
        if event=='SERVICE_HANDOVER_DELIVERED':
            self.layers.item(self.index,2).setText('인계 완료');self.layers.item(self.index,3).setText('사람 조립 대기')
            self.monitor.setText('전달판 개방·HOME·정지 확인 · 사람 조립 뒤 B 검사')
            self.render_service_progress();return
        if event=='SERVICE_PLANNING_REFERENCE':
            self.monitor.setText('계획 진행 기준: '+data['basis']+' · 실제 B Current는 별도 표시');return
        if event=='STACK_FINISHED':
            self.final_result=deepcopy(data);self.terminal_result=True
            self.status.setText('B FINAL 확인 완료' if data['physical_completion'] else
                '실행 종료 · 작업자 확인 포함 / B 완료 미확인' if data['status']=='CABD_EXECUTED_WITH_OPERATOR_REVIEW' else '진행 보류')
            self.notice.setPlainText(str(data.get('reason') or data['status']));self.footer.setText(data['output_directory']);return
        if event=='STACK_FINAL_NOT_CONFIRMED':
            self.status.setText('계획 실행 종료 · B 최종 미확인');self.notice.setPlainText(data['reason']);return
        if event.startswith('STACK_'):
            super().handle_event(event,data)
            if event=='STACK_STEP_BEGIN' and data['case'].get('execution_mode')=='HUMAN_ASSEMBLY':
                self.status.setText('공급 집기 → place board 개방·후퇴 → HOME 인계')
            self.render_service_progress()

    def render_service_progress(self):
        total=self.layers.rowCount()
        done=sum(self.layers.item(i,2).text() in ('완료','인계 완료') for i in range(total))
        matched=sum(self.layers.item(i,3).text()=='MATCH' for i in range(total))
        manual=sum('수동 진행' in self.layers.item(i,3).text() for i in range(total))
        self.progress.setText(f'D 실행·인계 {done} / {total} Step · 실제 B MATCH {matched} / {total} Step · B 실패 확인 {manual}건')

    def respond(self,answer):
        if not self.active or self.pending is None or self.stop_requested:return
        self.process.write((json.dumps(dict(request_id=self.pending['request_id'],answer=answer),ensure_ascii=False)+'\n').encode())
        self.pending=None;self.review_panel.hide();self.dialogue_send.setEnabled(False);self.dialogue_input.setEnabled(False)

    def reply(self,approved):
        if not self.pending:return
        if approved and self.pending['kind'] in ('B_FAILURE','REFILL','HANDOVER_READY','HUMAN_ASSEMBLY_DONE') and not self.review_check.isChecked():return
        self.respond(approved)

    def answer_text(self):
        if self.pending and self.pending['kind']=='C_TEXT' and self.dialogue_input.text().strip():
            text=self.dialogue_input.text();self.dialogue_input.clear();self.respond(text)

    def request_change(self):
        if not self.active:return
        if self.pending and self.pending['kind']=='STEP_READY':self.respond('CHANGE')
        else:self.change_requested=True;self.notice.setPlainText('현재 Step과 B 검사를 마친 뒤 C에게 설계 변경을 요청합니다.')

    def finished(self,*args):
        super().finished(*args);self.refresh_creator()
        self.archive.setEnabled(self.final_result is not None)
        if self.final_result is not None:self.save_history()

    def save_history(self):
        if self.active or self.archive_pending or not self.final_result or not self.creator or not self.credentials:return False
        result=deepcopy(self.final_result);creator=deepcopy(self.creator);credentials=self.credentials
        config=json.loads(self.plan_path.read_text())
        if config['creator']['user_id']!=creator['user_id']:return False
        self.archive_pending=True;self.archive.setEnabled(False)
        self.buttons['RESUME'].setEnabled(False);self.refresh_creator()
        self.creator_notice.setText('DB·개인 웹 기록 저장 중')
        def work():
            receipt=self.archive_receipt
            try:
                from history import store,personal
                from history.mvp_save import link_current_job,verify_web_job
                if receipt is None:
                    with store.connect(self.history_dsn) as connection:
                        link_current_job(connection,result['history_directory'],result['job_id'],creator)
                        # A storage receipt does not certify physical assembly.
                        receipt=personal.save_job(connection,result['job_id'],creator['user_id'],self.archive_key)
                verify_web_job(self.web_url,result['job_id'],*credentials,receipt)
                self.messages.put(('archive',result['job_id'],receipt,'DB·개인 웹 저장 확인 · '+('B 최종 완료' if result['physical_completion'] else '조립 완료 미확인 기록')))
            except Exception as error:
                self.messages.put(('archive_error',result['job_id'],receipt,'DB·웹 저장 실패: '+type(error).__name__+' · 저장만 재시도 가능'))
        Thread(target=work,daemon=True).start();return True

    def poll_accounts(self):
        while True:
            try:row=self.messages.get_nowait()
            except Empty:break
            if row[0]=='login':self.creator,self.credentials=row[1:];self.busy_account=False;self.refresh_creator()
            elif row[0]=='error':self.busy_account=False;self.refresh_creator();self.notice.setPlainText(row[1])
            elif row[1]==self.job_id:
                self.archive_pending=False;self.archive_receipt=row[2];self.archive.setEnabled(True)
                self.buttons['RESUME'].setEnabled(True);self.refresh_creator();self.creator_notice.setText(row[3])


def launch():
    app=QApplication.instance() or QApplication(sys.argv)
    window=ServiceWindow();window.show()
    return app.exec_()
