"""Five-layer test in the existing HMI; native robot/CV stays in a child process."""
from copy import deepcopy
import codecs
import json
import os
from pathlib import Path
import random
import signal
import sys
from uuid import uuid4

from PyQt5.QtCore import QProcess, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QCheckBox, QHBoxLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from app.qt_hmi import HmiWindow, fields, COLOR_LABELS
from app.round3_stack_review import HMI_PREFIX


class StackFiveWindow(HmiWindow):
    def __init__(self, seed, x=13, y=11, **window_options):
        super().__init__(**window_options)
        self.seed,self.x,self.y=seed,x,y
        self.process=QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_error)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.process.started.connect(lambda:self.request_stop() if self.stop_requested else None)
        self.buffer='';self.stderr='';self.pending=None;self.active=False;self.terminal_result=False
        self.decoder=codecs.getincrementaldecoder('utf-8')('replace');self.stop_requested=False
        self.current=None;self.target=None;self.index=None
        self.setWindowTitle('Round3 · 랜덤 5층 D·B 시험')
        self.heading.setText('랜덤 5층 실물 시험 · 층별 B 검사 · 작업자 확인은 별도 기록')
        self.design_dialogue.parentWidget().hide()
        self.user_request_controls.hide()
        self.completion_view.hide()
        self.assistance_view.parentWidget().hide()
        self.execution_view.hide()
        self.creator_bar.hide()
        self.buttons['START'].setText('준비 확인 · 5층 시작')
        self.buttons['STOP'].setText('정지 요청')
        self.buttons['RESUME'].setText('새 시험본 · 같은 5개')
        self.buttons['START'].clicked.connect(self.start_run)
        self.buttons['STOP'].clicked.connect(self.request_stop)
        self.buttons['RESUME'].clicked.connect(self.new_plan)
        self.ready=QCheckBox('빈 조립판 · 공급 5슬롯 · 빈 그리퍼 HOME · 경로/손 이탈 확인')
        self.ready.toggled.connect(lambda value:self.buttons['START'].setEnabled(value and not self.active and not self.used))
        self.layout().insertWidget(3,self.ready)
        self.layers=QTableWidget(5,4)
        self.layers.setHorizontalHeaderLabels(['층','공급','D 실행','B 검사'])
        self.layers.verticalHeader().hide()
        self.layers.setEditTriggers(QTableWidget.NoEditTriggers)
        self.layers.setFont(QFont('Noto Sans CJK KR',8))
        self.layers.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.layers.horizontalHeader().setFixedHeight(22)
        self.layers.verticalHeader().setMinimumSectionSize(18)
        self.layers.setMinimumHeight(124)
        for row in range(5):self.layers.setRowHeight(row,20)
        self.execution_view.parentWidget().layout().addWidget(self.layers)
        self.review_panel=QWidget()
        row=QHBoxLayout(self.review_panel);row.setContentsMargins(0,0,0,0)
        self.review_check=QCheckBox('실물 확인 · B 실패를 기록한 채 이번 건만 계속')
        self.review_check.setObjectName('operator_b_failure_review')
        self.continue_button=QPushButton('확인 기록 후 계속')
        self.continue_button.setObjectName('continue_after_b_failure')
        self.cancel_button=QPushButton('보류')
        self.review_check.toggled.connect(self.continue_button.setEnabled)
        self.continue_button.clicked.connect(lambda:self.reply(True))
        self.cancel_button.clicked.connect(lambda:self.reply(False))
        for widget in (self.review_check,self.continue_button,self.cancel_button):row.addWidget(widget)
        self.layout().insertWidget(self.layout().count()-1,self.review_panel)
        self.review_panel.hide()
        self.new_plan()

    def new_plan(self):
        if self.active:return
        from app import round3_stack_five as stack
        folder=stack.ROOT/'logs/stack-five'/str(uuid4());folder.mkdir(parents=True)
        self.plan_path=folder/'plan.json'
        self.document=stack.freeze(self.seed,self.x,self.y,stack.PROFILE,self.plan_path)
        stack.LAST_PLAN.write_text(str(self.plan_path)+'\n')
        self.used=False;self.pending=None;self.current=None;self.target=None;self.index=None
        self.ready.setChecked(False);self.ready.setEnabled(True)
        self.review_panel.hide();self.buttons['START'].setEnabled(False)
        self.buttons['STOP'].setEnabled(False);self.buttons['RESUME'].setEnabled(True)
        self.design_board.set_blocks([c['target'] for c in self.document['scenario']['steps']])
        self.design_panel.setTitle('5층 시험 목표 · 설계 승인과 별개')
        self.design_caption.setText('같은 좌표 · 1→5층 · 실제 B 확인과 작업자 확인을 구분합니다.')
        for i,case in enumerate(self.document['scenario']['steps']):
            color=COLOR_LABELS[case['target']['color']]
            size=case['target']['brick_type'].split('x1')[0].replace('x','×')
            for col,text in enumerate((str(i+1),f"{color} {size} #{case['supply_slot']}",'대기','대기')):
                item=QTableWidgetItem(text);item.setToolTip(text);self.layers.setItem(i,col,item)
        self.status.setText('5층 시험 준비 · 시작 전에는 장치 명령 없음')
        self.progress.setText('D 완료 0 / 5층 · 실제 B MATCH 0 / 5층 · 수동 확인 0건')
        self.monitor.setText('로봇 실제 상태는 실행 시 조회합니다.')
        self.supply.setText('I 50N · P 반력 60N 정지 · 70N 이상 보류 · 접촉 3mm/s\n조립판 O 47mm (32~55) · 공급/인계 53mm (40~80)\n관측창에서 I → O → P → U')
        self.notice.setPlainText('준비 항목을 확인하고 시작하세요. 매 층 실행 전 HMI에서 확인합니다.')
        self.footer.setText(str(self.plan_path))
        self.inspection_view.current_board.set_blocks([]);self.inspection_view.expected_board.set_blocks([])
        self.inspection_view.summary.setText('INITIAL 대기 · B Current 미확정')
        self.inspection_view.details.clear()
        self.inspection_view.board_panels[0].setTitle('실제 B Current · 미확정')
        self.inspection_view.board_panels[1].setTitle('B 예상 · 미수신')
        self.render_target(None)

    def start_run(self):
        if self.active or self.used or not self.ready.isChecked():return
        from app.round3_stack_five import validate
        try:validate(self.document)
        except (ValueError,OSError) as error:
            self.notice.setPlainText(str(error)+'\n새 시험본을 만들어 주세요.');return
        self.used=True;self.active=True;self.terminal_result=False;self.buffer='';self.stderr=''
        self.decoder=codecs.getincrementaldecoder('utf-8')('replace');self.stop_requested=False
        self.ready.setEnabled(False)
        self.buttons['START'].setEnabled(False);self.buttons['STOP'].setEnabled(True);self.buttons['RESUME'].setEnabled(False)
        self.status.setText('INITIAL 시작 · 빈 조립판 검사 중')
        self.process.setWorkingDirectory(str(self.plan_path.parents[3]))
        self.process.start(sys.executable,['-u','-m','app.round3_stack_five','run','--plan',str(self.plan_path),
            '--execute','--confirm-empty-board','--confirm-empty-gripper','--confirm-home-route-reviewed',
            '--confirm-hand-clear','--operator-b-review','--hmi-protocol'])

    def read_output(self):
        self.buffer+=self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if line.startswith(HMI_PREFIX):
                try:
                    row=json.loads(line[len(HMI_PREFIX):]);self.handle_event(row['event'],row['data'])
                except (ValueError,KeyError,TypeError) as error:
                    self.notice.setPlainText('HMI 입력 오류: '+str(error));self.request_stop()

    def read_error(self):
        self.stderr=(self.stderr+bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace'))[-5000:]

    def render_target(self,target):
        self.target=deepcopy(target)
        if self.current is None:self.target_board.set_blocks([target] if target else [])
        else:self.target_board.set_assembly(self.current,target)
        self.step_panel.setTitle(f"현재 목표 · {target['layer']}층" if target else '현재 목표 · 대기')
        self.target_caption.setText('B Current 미확정 · 목표는 관측 결과가 아닙니다.' if self.current is None else
            f"실제 B Current r{self.current['current_revision']} · 기록 {len(self.current['blocks'])}개")
        self.comparison.setText('현재 층 목표 · 실제 B 결과는 아래에 별도 표시')
        for i,value in enumerate(fields(target)):
            self.table.setItem(i,1,QTableWidgetItem(value));self.table.setItem(i,2,QTableWidgetItem('미수신'))
        self.render_expected()

    def render_expected(self):
        # A B result may describe the preceding Step. Preview the fixed plan
        # prefix independently; operator review must never populate B Current.
        blocks=deepcopy(getattr(self,'expected_base_blocks',[]))
        if self.index is not None:
            blocks.extend(deepcopy(case['target']) for case in self.document['scenario']['steps'][:self.index+1])
        self.inspection_view.expected_board.set_blocks(blocks)
        self.inspection_view.expected_board.setVisible(bool(blocks))
        self.inspection_view.board_panels[1].setTitle('이번 단계 예상 구조 · 계획 기준')

    def handle_event(self,event,data):
        if event=='REQUEST':
            if self.stop_requested or not self.active:return
            if self.pending is not None:raise ValueError('OVERLAPPING_HMI_REQUEST')
            self.pending=deepcopy(data)
            review=data['kind']=='B_FAILURE'
            self.review_check.setChecked(False);self.review_check.setVisible(review)
            self.continue_button.setEnabled(not review)
            self.continue_button.setText('확인 기록 후 계속' if review else '이 층 실행')
            self.review_panel.show()
            if review:
                target=data['target']
                self.status.setText('B 실패 · 실물 확인 체크 대기')
                self.notice.setPlainText(('빈 조립판을 확인하세요. 확인 후 HOME 복귀합니다.\n' if target is None else
                    f"{target['layer']}층 종류·색상·좌표·결착을 확인하세요.\n")+str(data['failure'].get('reason')))
            else:
                self.index=data['index'];self.render_target(data['case']['target'])
                self.status.setText(f'{self.index+1}층 실행 확인 대기')
                self.notice.setPlainText('공급 슬롯·조립 목표를 확인하고 이 층 실행을 누르세요.')
        elif event=='STACK_INITIAL_BEGIN':self.status.setText('INITIAL · V0 → D1 → D3 검사 중')
        elif event=='STACK_INITIAL_RESULT':
            self.current=deepcopy(data.get('current'));self.render_target(self.target)
            if self.current is not None:self.inspection_view.current_board.set_blocks(self.current['blocks'])
            self.inspection_view.summary.setText('INITIAL: '+data['status'])
            self.inspection_view.details.setPlainText(str(data.get('reason') or '빈 판 B 확인'))
            self.monitor.setText('INITIAL 실제 정지: '+str(data.get('actual_stop_verified'))+
                ' · HOME: '+str(data.get('home_return_verified')))
        elif event=='STACK_STEP_BEGIN':
            self.index=data['index']-1;self.render_target(data['case']['target'])
            self.layers.item(self.index,2).setText('실행 중')
            self.status.setText(f'{self.index+1}층 · 집기/결착/개방/가압/상승·HOME')
            self.monitor.setText('D 실행 중 · 정지 확인과 장치 제어는 실행 프로그램이 담당합니다.')
        elif event=='STACK_NATIVE_FINISHED':
            self.layers.item(self.index,2).setText('완료')
            self.monitor.setText('D 정상 완료 · HOME 복귀 확인 · B 검사 대기')
        elif event=='STACK_B_BEGIN':
            self.status.setText('FINAL B 검사 중' if data['check_kind']=='FINAL' else f'{self.index+1}층 실제 B 검사 중')
            if data['check_kind']=='STEP':self.layers.item(self.index,3).setText('검사 중')
        elif event=='STACK_B_RESULT':
            if data.get('current') is not None:self.current=deepcopy(data['current'])
            self.render_target(self.target)
            outcome=data.get('comparison') or data['status']
            if data['check_kind']=='STEP':self.layers.item(self.index,3).setText(outcome)
            if self.current is not None:
                self.inspection_view.render_snapshot(dict(current=self.current,inspection=data,step=dict(observed=None)))
            else:
                self.inspection_view.summary.setText('B Current 미확정 · '+outcome)
                self.inspection_view.details.setPlainText(str(data.get('reason')))
            self.inspection_view.board_panels[0].setTitle('실제 B Current' if self.current is not None else '실제 B Current · 미확정')
            visible=(data.get('observation') or {}).get('visible_blocks',[])
            seen=next((b for b in visible if self.target and b['layer']==self.target['layer'] and
                (b['x'],b['y'])==(self.target['x'],self.target['y'])),None)
            if seen:
                for i,value in enumerate(fields(seen)):self.table.setItem(i,2,QTableWidgetItem(value))
            self.notice.setPlainText(str(data.get('reason') or outcome))
        elif event=='STACK_OPERATOR_REVIEW':
            if data['kind']=='STEP':self.layers.item(self.index,3).setText(self.layers.item(self.index,3).text()+' · 수동 진행')
            else:self.inspection_view.summary.setText('INITIAL 실패 유지 · 작업자 빈 판 확인으로 시험 진행')
        elif event in ('STACK_HOLD','STACK_FINAL_NOT_CONFIRMED'):
            self.status.setText('진행 보류' if event=='STACK_HOLD' else '5층 실행 종료 · B 최종 미확인')
            self.notice.setPlainText(str(data['reason']))
            if event=='STACK_HOLD' and self.index is not None and self.layers.item(self.index,2).text()=='실행 중':
                self.layers.item(self.index,2).setText('보류')
        elif event=='STACK_FINISHED':
            self.terminal_result=True
            self.status.setText({'FIVE_STEPS_AND_FINAL_MATCH':'5층·FINAL B 확인 완료',
                'FIVE_STEPS_EXECUTED_WITH_OPERATOR_REVIEW':'5층 실행 종료 · 작업자 확인 포함 / B 전체 완료 아님'}.get(data['status'],'진행 보류'))
            self.notice.setPlainText(str(data.get('reason') or data['status']))
            self.footer.setText(data['output_directory'])
        self.render_expected()
        total=self.layers.rowCount()
        done=sum(self.layers.item(i,2).text()=='완료' for i in range(total))
        matched=sum(self.layers.item(i,3).text()=='MATCH' for i in range(total))
        manual=sum('수동 진행' in self.layers.item(i,3).text() for i in range(total))
        self.progress.setText(f'D 완료 {done} / {total} Step · 실제 B MATCH {matched} / {total} Step · 수동 확인 {manual}건')

    def reply(self,approved):
        if not self.active or self.pending is None:return
        if approved and self.pending['kind']=='B_FAILURE' and not self.review_check.isChecked():return
        reply=dict(request_id=self.pending['request_id'],approved=approved)
        self.process.write((json.dumps(reply)+'\n').encode())
        self.pending=None;self.review_panel.hide()
        self.status.setText('확인 전달 · 실행 중' if approved else '보류 요청 전달 중')

    def request_stop(self):
        if not self.active:return
        self.stop_requested=True
        self.pending=None;self.review_panel.hide()
        self.buttons['STOP'].setEnabled(False)
        self.status.setText('정지 요청 중 · 실제 정지 확인 대기')
        self.monitor.setText('정지 요청 전달 중 · 실제 정지 확인 결과 대기')
        if self.process.processId():
            try:os.kill(int(self.process.processId()),signal.SIGINT)
            except ProcessLookupError:pass

    def process_error(self,error):
        if error==QProcess.FailedToStart:
            self.active=False;self.buttons['RESUME'].setEnabled(True)
            self.buttons['STOP'].setEnabled(False)
            self.status.setText('실행 프로그램 시작 실패');self.notice.setPlainText(self.process.errorString())

    def finished(self,*args):
        self.read_output();self.read_error();self.active=False;self.pending=None;self.review_panel.hide()
        self.buttons['STOP'].setEnabled(False);self.buttons['RESUME'].setEnabled(True)
        if not self.terminal_result:
            self.status.setText('실행 종료 · 정지/완료 미확인')
            self.notice.setPlainText(self.stderr or '결과를 받지 못했습니다. 실행 로그를 확인하세요.')

    def closeEvent(self,event):
        if self.active:
            self.request_stop();event.ignore()
            self.notice.setPlainText('정지 처리 결과를 기다린 뒤 창을 닫아 주세요.')
        else:event.accept()


def launch(args):
    from app.round3_stack_five import LAST_PLAN,read
    path=args.plan or (Path(LAST_PLAN.read_text().strip()) if LAST_PLAN.exists() else None)
    previous=read(path) if path else None
    seed=args.seed if args.seed is not None else previous['seed'] if previous else random.SystemRandom().randrange(2**32)
    app=QApplication.instance() or QApplication([])
    window=StackFiveWindow(seed,args.x,args.y);window.show()
    handlers={s:signal.signal(s,lambda *_:window.request_stop()) for s in (signal.SIGINT,signal.SIGTERM)}
    timer=QTimer();timer.timeout.connect(lambda:None);timer.start(200)
    try:return app.exec_()
    finally:
        for s,handler in handlers.items():signal.signal(s,handler)
