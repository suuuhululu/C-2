"""Operator exceptions for the standalone five-layer test, never B success."""
from copy import deepcopy
import json
from uuid import uuid4

from app.round3_initial_inspection import open_motion

HMI_PREFIX = 'C2_STACK_HMI '


class HmiProtocol:
    """Child waits for an explicit parent reply; EOF/STOP never approves."""
    def __init__(self, source, sink):
        self.source, self.sink = source, sink

    def publish(self, event, data):
        self.sink.write(HMI_PREFIX+json.dumps(dict(event=event,data=data),ensure_ascii=False,allow_nan=False)+'\n')
        self.sink.flush()

    def request(self, kind, data):
        identity=str(uuid4())
        self.publish('REQUEST',dict(request_id=identity,kind=kind,**data))
        line=self.source.readline()
        if not line:return False
        reply=json.loads(line)
        if set(reply)!={'request_id','approved'} or reply['request_id']!=identity or type(reply['approved']) is not bool:
            raise ValueError('HMI_REVIEW_REPLY_MISMATCH')
        return reply['approved']

    def review(self, kind, failure, target):
        return self.request('B_FAILURE',dict(check_kind=kind,failure=failure,target=target))

    def step_ready(self, case, index, total):
        return self.request('STEP_READY',dict(case=case,index=index,total=total))


def review_checkbox(kind, failure, target=None):
    from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                                QLabel, QPlainTextEdit, QVBoxLayout)
    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    dialog.setWindowTitle('5층 시험 · B 실패 후 작업자 확인')
    layout = QVBoxLayout(dialog)
    text = ('INITIAL 실패: 조립판이 실제로 비어 있는지 확인하세요.\n'
            '확인 후 검토된 HOME 경로로 복귀하고 시험을 시작합니다.' if kind == 'INITIAL' else
            f"{target['layer']}층 B 실패: 실제 블록의 종류·색상·좌표·결착을 확인하세요.\n"
            f"목표: {target['color']} {target['brick_type']} / ({target['x']},{target['y']}) / {target['orientation_deg']}°")
    title = QLabel(text)
    title.setWordWrap(True)
    layout.addWidget(title)
    details = QPlainTextEdit(json.dumps(failure, ensure_ascii=False, indent=2))
    details.setReadOnly(True)
    layout.addWidget(details)
    checkbox = QCheckBox('실물을 확인했고, 이번 시험의 B 실패를 기록한 채 계속합니다.')
    checkbox.setObjectName('operator_b_failure_review')
    layout.addWidget(checkbox)
    layout.addWidget(QLabel('B 판정·Current는 성공으로 바꾸지 않습니다. 창 닫기/취소는 보류입니다.'))
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    proceed = buttons.button(QDialogButtonBox.Ok)
    proceed.setText('확인 기록 후 계속')
    proceed.setObjectName('continue_after_b_failure')
    proceed.setEnabled(False)
    proceed.setAutoDefault(False)
    checkbox.toggled.connect(proceed.setEnabled)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(750, 480)
    return dialog.exec_() == QDialog.Accepted and checkbox.isChecked()


def recover_initial_home(settings, review, cancelled, record):
    """Run only after checkbox approval, using the existing reviewed HOME route."""
    with open_motion(settings, cancelled) as motion:
        state = motion.confirm(review, 'HOME', dict(settings, route_reviewed=True), review)
        record('OPERATOR_INITIAL_HOME_RETURN', state)
        if state.get('stopped_verified') is not True:
            raise RuntimeError('OPERATOR_INITIAL_HOME_NOT_VERIFIED')
    return dict(home_return_verified=True, actual_stop_verified=True,
                writer_released=True, home_sample=deepcopy(state))
