"""B 없는 실물 시험의 한 화면. C 미리보기·승인과 D 실제 정렬 확인을 표시한다."""
from queue import Queue, Empty
from threading import Thread
import json
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QTextOption
from PyQt5.QtWidgets import (QApplication, QCheckBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget)

from app.cad_real_trial import Trial, read, save
from app.c_design.main import create_initial_design, review_design_candidate
from app.c_design import llm
from app.hmi_board import BoardView


def failure_text(error):
    """판정 사유만 표시한다. 원본의 블록 목록은 저장 파일에서 확인한다."""
    if not isinstance(error, dict):
        return str(error)[:400]
    code = error.get('code', 'UNKNOWN')
    messages = {
        'DESIGN_GENERATION_FAILED': '정해진 시도 횟수 안에 설계 조건을 만족하지 못했습니다.',
        'LLM_CALL_FAILED': 'LLM 호출에 실패했습니다.',
        'VOICE_IO_FAILED': '음성 입력 또는 출력에 실패했습니다.',
        'UNSUPPORTED_OBJECT': '현재 C가 지원하는 설계 대상이 아닙니다.',
        'INVALID_INPUT': '입력 또는 설계 형식이 맞지 않습니다.',
        'STOPPED': '정지 요청으로 중단했습니다.',
        'USER_CANCEL': '사용자가 취소했습니다.',
    }
    rules = {
        'support': '아래층 지지 부족', 'connectivity': '블록들이 하나의 구조로 연결되지 않음',
        'overlap': '같은 층의 블록 겹침', 'brick_count': '블록 수가 1~40개 범위를 벗어남',
        'out_of_board': '조립판 범위를 벗어남', 'invalid_combination': '색상·블록 규격 조합 오류',
        'malformed_output': 'LLM 설계 출력 형식 오류', 'unchanged_candidate': '수정 전 설계와 동일함',
        'assembled_not_preserved': '이미 조립된 구조를 보존하지 못함',
    }
    message = str(error.get('message') or '')
    lines = [f"{code}: {messages.get(code, message[:200])}"]
    if code in messages and message:
        lines.append('세부 원인: '+message[:200])
    counts = {}
    for reason in error.get('details') or []:
        if not isinstance(reason, dict):
            continue
        rule = reason.get('rule', 'unknown')
        key = (rule, str(reason.get('message') or '')[:160])
        counts[key] = counts.get(key, 0)+1
    for (rule, detail), count in list(counts.items())[:6]:
        lines.append(f"• {rules.get(rule, rule)} ({count}건): {detail}")
    if len(counts) > 6:
        lines.append('나머지 사유는 시험 기록에서 확인할 수 있습니다.')
    return '\n'.join(lines)


class TrialWindow(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args, self.inbox = args, Queue()
        self.trial = Trial(args.robot_root, args.log_directory,
            lambda event,data:self.inbox.put((event,data)), execute=args.execute, start_zone=args.start_zone,
            gestures=getattr(args,'gestures',False))
        self.worker, self.candidate, self.alignment_request = None, None, None
        self.used = False
        self.setWindowTitle('C→A→D · C 설계 로봇 조립 시험 · B 없음')
        self.resize(1050, 780)
        layout = QVBoxLayout(self)
        self.mode_label = QLabel('실행 모드: REAL · C 승인 후 실제 로봇 실행' if args.execute
                                else '실행 모드: 준비 · 장치 연결/움직임 없음')
        layout.addWidget(self.mode_label)
        self.status = QLabel('REAL 실행 허용 · 아직 장치 미연결' if args.execute else '준비 모드 · 장치 연결/움직임 없음')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setMaximumHeight(80)
        layout.addWidget(self.status)
        boards = QHBoxLayout()
        self.target, self.prefix = BoardView(isometric=True), BoardView(isometric=True)
        for title, board in [('C 설계 후보 · 승인 전 미리보기', self.target),
                             ('실행을 마친 목표의 누적 표시 · 실제 관측 아님', self.prefix)]:
            box = QGroupBox(title)
            box_layout = QVBoxLayout(box); box_layout.addWidget(board)
            boards.addWidget(box)
        layout.addLayout(boards, 1)
        self.reviewed = QCheckBox('시험 준비 확인: 빈 조립판·그리퍼 / 공급판 준비 / 경로·설정 확인 / 손 없는 이동 영역 / 단독 제어')
        layout.addWidget(self.reviewed)
        self.policy = QLabel('집기 전 55mm / 집기 35mm / 결착 후 48mm(실제 44mm 초과 확인) · pad 하단 5mm · pre-contact +20.1mm\n이송 192mm/s · 집기/조립판 접근 24mm/s · 접촉 전 마지막 10mm는 2mm/s · 블렌딩 30mm · B 판정·Current 갱신·DB 저장 없음.')
        self.policy.setWordWrap(True)
        self.policy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if getattr(args,'gestures',False):
            self.policy.setText(self.policy.text()+'\n제스처: 정지된 pre-contact에서 엄지척 2초 → 체결 준비 확인 · 편 손 1초 → 정지 요청')
        layout.addWidget(self.policy)
        self.gesture_label = QLabel('제스처 영상 연결 대기 · 엄지척 2초 / 편 손 1초')
        if getattr(args,'gestures',False):layout.addWidget(self.gesture_label)
        else:self.gesture_label.hide()
        commands = QHBoxLayout()
        self.voice = QPushButton('고정 시험 설계' if args.design is not None else
                                'C 음성 설계 요청' if args.voice else '음성 모드 아님')
        self.voice.setEnabled(args.voice and args.design is None)
        self.voice.clicked.connect(self.initial_voice)
        commands.addWidget(self.voice)
        self.answer = QLineEdit(); self.answer.setPlaceholderText('C에게 승인 또는 수정 의견 입력 (예: 좋아요)')
        commands.addWidget(self.answer, 1)
        self.submit = QPushButton('C 음성 승인 대화' if args.voice else 'C에게 답변')
        self.submit.clicked.connect(self.review)
        commands.addWidget(self.submit)
        layout.addLayout(commands)
        execution = QHBoxLayout()
        self.align = QPushButton('pre-contact 정렬 확인 후 체결 진행')
        self.align.setEnabled(False); self.align.clicked.connect(self.confirm_alignment)
        execution.addWidget(self.align)
        stop = QPushButton('정지'); stop.clicked.connect(self.stop)
        execution.addWidget(stop)
        self.resume_button = QPushButton('재개 · 승인 설계 유지')
        self.resume_button.setEnabled(False); self.resume_button.clicked.connect(self.resume)
        execution.addWidget(self.resume_button)
        layout.addLayout(execution)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.details.setMaximumBlockCount(200)
        self.details.setMaximumHeight(220); layout.addWidget(self.details)
        self.footer = QLabel('시험 기록: '+str(self.trial.directory)); layout.addWidget(self.footer)
        self.footer.setWordWrap(True)
        self.footer.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if getattr(args, 'approved_review', None) is not None:
            self.set_candidate(args.approved_review['design'])
            self.submit.setText('승인 설계로 다시 시작')
            self.answer.setEnabled(False); self.voice.setEnabled(False)
            self.set_status('기존 C 승인 설계 유지 · 시험 준비 확인 후 다시 시작')
        elif args.design is not None:
            self.set_candidate(read(args.design))
        else:
            self.submit.setEnabled(False)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(50)

    def set_candidate(self, value):
        self.candidate = value
        self.target.set_blocks(value['blocks'])
        self.set_status('C 설계 후보가 표시되었습니다. 승인/수정 의견을 C에게 전달하세요.')
        self.submit.setEnabled(True)
        # A의 전체 계산은 승인 후 Trial.run의 작업 스레드에서 한 번 수행한다.
        self.details.setPlainText('설계 미리보기 · 실제 관측 아님\nC 승인 후 A 계획·경로 계산을 진행합니다.\n상세 좌표는 시험 기록에 저장합니다.')

    def set_status(self, text):
        self.status.setText(str(text)[:400])

    def show_failure(self, title, error):
        text = failure_text(error)
        lines = text.splitlines()
        reasons = [line.split(': ',1)[0] for line in lines if line.startswith('• ')]
        self.set_status(title+'\n'+lines[0]+'\n'+' / '.join(reasons[:3]))
        self.details.appendPlainText(title+'\n'+text+'\n원본: 아래 시험 기록 경로')

    def record_ui_event(self, event, data):
        # C 진단은 D 실행 이력과 분리해 기존 승인 재사용 검사에 영향을 주지 않는다.
        with (self.trial.directory/'c-events.jsonl').open('a', encoding='utf-8') as file:
            file.write(json.dumps(dict(event=event,data=data),ensure_ascii=False,allow_nan=False)+'\n')
        self.inbox.put((event,data))

    def background(self, function):
        if self.worker is not None and self.worker.is_alive():
            return
        self.submit.setEnabled(False); self.voice.setEnabled(False)
        def run():
            try:
                function()
            except Exception as error:
                self.record_ui_event('UI_FAILURE', dict(reason=str(error)))
        self.worker = Thread(target=run, daemon=True); self.worker.start()

    def initial_voice(self):
        def call():
            result = create_initial_design(should_stop=self.trial.cancelled.is_set,
                on_question=lambda text:self.record_ui_event('QUESTION',dict(text=text)),
                on_progress=lambda data:self.record_ui_event('C_PROGRESS',data))
            save(self.trial.directory/'c-initial.json', result)
            self.record_ui_event('C_CANDIDATE',result)
        self.background(call)

    def review(self):
        if self.candidate is None or self.used:
            return
        if self.args.execute and not self.reviewed.isChecked():
            self.set_status('실물 시험 전에 위 시험 준비 항목을 확인해주세요.')
            return
        text = self.answer.text().strip()
        approved = getattr(self.args, 'approved_review', None)
        if approved is None and not self.args.voice and not text:
            self.set_status('C에게 보낼 답변을 입력해주세요.')
            return
        reviewed = self.reviewed.isChecked()
        def call():
            if approved is None and getattr(self.args, 'llm_context', False):
                save(self.trial.directory/'llm-input-design.json', self.candidate)
                self.record_ui_event('QUESTION',dict(text='고정 시험 설계 전체를 C LLM에 전달하는 중입니다.'))
                described = llm.describe_initial_design(self.candidate,
                    should_stop=self.trial.cancelled.is_set,
                    concept='사용자가 정한 색상과 층 순서 그대로 쌓는 2×2 로봇 체결 시험 기둥')
                save(self.trial.directory/'llm-design-description.json', described)
                if 'llm_error' in described:
                    raise RuntimeError('LLM 설계 전달 실패: '+str(described['llm_error']))
                self.record_ui_event('C_DESCRIPTION', described)
            if approved is not None:
                result = approved
                save(self.trial.directory/'approval-source.json',
                    dict(directory=str(self.args.retry_start_directory), c_review_repeated=False))
            else:
                result = review_design_candidate(self.candidate, kind='initial', current=[],
                    text_answers=None if self.args.voice else [text], should_stop=self.trial.cancelled.is_set,
                    on_question=lambda question:self.record_ui_event('QUESTION',dict(text=question)),
                    on_progress=lambda data:self.record_ui_event('C_PROGRESS',data))
            save(self.trial.directory/'c-review.json', result)
            self.record_ui_event('C_REVIEW',result)
            if result['status'] == 'OK' and result['hri_result'] == 'APPROVE':
                review_ref = str(self.trial.directory/'operator-preparation.json') if reviewed else None
                if reviewed:
                    save(review_ref, dict(source='ACTUAL_HMI_CHECKBOX', at_unix_s=time.time(),
                        design=result['design'], start_zone=self.args.start_zone,
                        coordinate_source='MEASURED_GEOMETRY_CANDIDATE', physical_verified=False,
                        transport='REVIEWED_HORIZONTAL_BLENDING', b_called=False))
                self.trial.run(result['design'], review_ref)
        self.background(call)

    def confirm_alignment(self):
        request = self.alignment_request
        if request is None:
            return
        self.align.setEnabled(False)
        self.trial.alignment(request)

    def stop(self):
        if self.worker is None or not self.worker.is_alive():
            return
        self.used = True
        self.align.setEnabled(False); self.submit.setEnabled(False); self.voice.setEnabled(False)
        self.trial.stop()
        self.set_status('정지 요청됨 · D의 실제 정지 결과를 확인 중')

    def resume(self):
        if not self.trial.paused:
            return
        self.resume_button.setEnabled(False)
        self.trial.resume()
        self.set_status('승인 설계 유지 · D의 정지 상태/중단 위치를 확인하고 재개 중')

    def poll(self):
        # 장치 이벤트가 이어져도 매 주기 GUI에 제어권을 돌려준다.
        for _ in range(50):
            try:
                event, data = self.inbox.get_nowait()
            except Empty:
                return
            if event == 'C_CANDIDATE' and data['status'] == 'OK':
                self.set_candidate(data['design'])
            elif event == 'C_CANDIDATE':
                self.show_failure('C 설계 생성 실패', data.get('error'))
                self.voice.setEnabled(self.args.voice and not self.used)
            elif event == 'C_REVIEW':
                if data['status'] == 'OK' and data['hri_result'] == 'APPROVE':
                    self.used = True
                    self.set_status('C 승인 완료 · A 계획/경로와 D 연결을 확인 중')
                elif data['status'] == 'OK' and data['hri_result'] == 'MODIFY':
                    self.set_candidate(data['design'])
                else:
                    self.show_failure('C 승인 보류', data.get('error') or data.get('hri_result'))
                    self.submit.setEnabled(not self.used)
            elif event == 'SIGNAL_REQUEST' and data['kind'] == 'ALIGNMENT_READY':
                self.alignment_request = data['request_id']
                self.align.setEnabled(True)
                self.set_status('pre-contact 도달·정지·파지 유지 확인됨. 실제 XY/평행 정렬을 보고 체결 진행 버튼을 누르세요.')
            elif event == 'SIGNAL_REQUEST_CLOSED':
                self.alignment_request = None; self.align.setEnabled(False)
            elif event == 'PREFIX_ASSUMED':
                self.prefix.set_blocks(data['blocks'])
                self.set_status(f"로봇 실행 {data['completed']}/{data['total']} · B 관측 확인 없음")
            elif event == 'STEP_READY':
                self.set_status(data['step']['step_id']+' · 공급 슬롯 '+data['step']['reservation']['slot_id'])
            elif event == 'TRIAL_PAUSED':
                self.resume_button.setEnabled(data.get('resume_allowed') is True)
                if data.get('stage') == 'START_STATE':
                    self.set_status('그리퍼 상태 확인 필요 · 빈 그리퍼로 정리 후 재개 · 설계 승인 유지')
                else:
                    self.set_status(str(data.get('reason'))+' · 승인 설계 유지 · 상태 확인 후 재개 가능')
            elif event == 'TRIAL_RESUMING':
                self.resume_button.setEnabled(False)
                self.set_status(data['step_id']+' · 승인 설계 유지 · 중단 위치에서 재개')
            elif event == 'GESTURE_CAMERA_READY':
                self.set_status('제스처 영상 연결됨 · 엄지척 2초로 준비 응답 / 편 손 1초로 정지 요청')
            elif event == 'GESTURE_STOP_REQUESTED':
                self.set_status('편 손 정지 요청 · D의 실제 정지 확인 중')
            elif event == 'GESTURE_READY_CONFIRMED':
                self.align.setEnabled(False)
                self.set_status('엄지척 준비 응답 수신 · D 체결 진행')
            elif event == 'CAMERA_CANDIDATE':
                hands=data.get('hands',[])
                pose=hands[0].get('pose') if len(hands)==1 else '손 없음/여러 손'
                names={'THUMBS_UP':'엄지척','OPEN_HAND':'편 손','FIST':'주먹','L':'L 모양','UNKNOWN':'인식 불확실'}
                self.gesture_label.setText('제스처: '+names.get(pose,str(pose))+
                    f" · 유지 {data.get('held_ns',0)/1e9:.1f}초 · B 조립 관측 아님")
            elif event in ('QUESTION', 'C_PROGRESS'):
                self.set_status(data.get('text') or data.get('message', 'C 처리 중'))
            elif event == 'C_DESCRIPTION':
                self.set_status(str(data.get('design_summary') or 'C LLM이 고정 설계를 수신했습니다.'))
            elif event in ('UI_FAILURE', 'COMMAND_REJECTED', 'EXECUTION_HELD', 'TRIAL_RESULT',
                           'STOP_CHANNEL_FAILED', 'ALIGNMENT_CHANNEL_FAILED', 'GESTURE_CAMERA_FAILED'):
                self.align.setEnabled(False)
                self.resume_button.setEnabled(False)
                self.set_status(str(data.get('reason') or data.get('status') or event))
                if event == 'UI_FAILURE' and not self.used:
                    self.voice.setEnabled(self.args.voice and self.candidate is None)
                    self.submit.setEnabled(self.candidate is not None)
            if event not in ('CHECKPOINT', 'STILLNESS_WINDOW_VERIFIED', 'ADAPTER_LEASE_APPLIED',
                             'CAMERA_CANDIDATE', 'C_CANDIDATE', 'C_REVIEW'):
                # 큰 상태·좌표·블록 dict는 그리지 않고 원본을 events.jsonl에 남긴다.
                summary = data.get('reason') or data.get('message') or data.get('text') or data.get('status') or ''
                self.details.appendPlainText(event+' · '+str(summary)[:600])

    def closeEvent(self, event):
        if self.worker is not None and self.worker.is_alive():
            self.trial.close()
            self.set_status('정지/연결 종료 중입니다. D 응답 후 창을 닫으세요.')
            event.ignore()
        else:
            event.accept()


def show(args):
    app = QApplication.instance() or QApplication([])
    window = TrialWindow(args); window.show()
    return app.exec_()
