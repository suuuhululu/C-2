"""단일 Qt 화면: Backend snapshot 표시와 명령 신호만 담당한다."""

from PyQt5.QtCore import QSize, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget, QHeaderView,
)

from app.hmi_board import BoardView
from app.hmi_contracts import validate_hmi_command, validate_hmi_snapshot


WORKFLOW_LABELS = dict(IDLE="시작 전", PREPARING="목표·계획 준비", DELIVERING="Robot 전달·복귀 중",
    WAIT_ASSEMBLY="사람 조립 관측 대기", WAIT_INTENT="의도 확인 대기", REPLANNING="재계획 검증 중",
    WAIT_CORRECTION="사람 정리 대기", HOLD="진행 보류", STOPPED="정지 확인", COMPLETE="전체 조립 완료")
STATUS_LABELS = dict(OK="판별 가능", UNOBSERVABLE="판단 불가", EMPTY="비어 있음", OCCUPIED="블록 있음",
    IDLE="관측 위치 준비", BUSY="동작 중", STOP_PENDING="정지 확인 대기", STOPPED="정지 확인",
    ERROR="오류 보류", WAITING="관측 대기", MATCH="일치", MISMATCH="실제 차이")


def label(value):
    return "미확인" if value is None else STATUS_LABELS.get(value, value)


def fields(block):
    return (["4점 (2×2)" if block["brick_type"] == "2x2x1" else "6점 (2×3)",
             "노랑" if block["color"] == "yellow" else "파랑", f"({block['x']}, {block['y']})",
             f"{block['layer']}층", f"{block['orientation_deg']}°"] if block else ["—"]*5)


class HmiWindow(QWidget):
    command_requested = pyqtSignal(dict)
    snapshot_received = pyqtSignal(dict)

    def __init__(self, *, screen_size=None, window_size=None):
        super().__init__()
        self._snapshot = None
        self._screen_size = screen_size or QApplication.primaryScreen().availableGeometry().size()
        preferred = window_size or QSize(1200,900)
        self._frame_size = QSize(min(preferred.width(),self._screen_size.width()),
                                 min(preferred.height(),self._screen_size.height()))
        self.setWindowTitle("협동 조립 · Day4 · FAKE")
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setFont(QFont("Noto Sans CJK KR", 10))
        self.setStyleSheet("QWidget{color:#202730;background:#f0f2f4;}"
            "QGroupBox{background:white;border:1px solid #ccd3dc;border-radius:5px;margin-top:18px;padding:8px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;}"
            "QPushButton{padding:7px 12px;background:#253d57;color:white;border-radius:4px;}"
            "QPushButton:disabled{background:#e2e6eb;color:#6b7785;}"
            "QTableWidget,QTextBrowser{background:white;border:0;}"
            "QLabel{background:transparent;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(12,10,12,10)
        root.setSpacing(9)
        self.heading = QLabel("협동 조립 · Day4                         모의 연결 FAKE · 실제 장치 미연결")
        root.addWidget(self.heading)
        process = QHBoxLayout()
        text = QVBoxLayout()
        self.status, self.progress = QLabel(), QLabel()
        self.status.setFont(QFont("Noto Sans CJK KR",16))
        text.addWidget(self.status)
        text.addWidget(self.progress)
        process.addLayout(text,1)
        controls = QGroupBox("조작")
        control_layout = QGridLayout(controls)
        self.buttons = {}
        for index,(name,caption) in enumerate((("START","시작"),("STOP","정지"),("RESUME","재개"),
            ("KEEP","목표 유지"),("REVISE","목표 수정"),("CONTINUE_AFTER_CORRECTION","정리 완료"),
            ("PREPARE_OBSERVE","사전 이동 · HOME→관측"))):
            button = QPushButton(caption)
            button.setAccessibleName(caption)
            button.clicked.connect(lambda checked=False, name=name: self._request(name))
            control_layout.addWidget(button,index//3,index%3)
            self.buttons[name] = button
            if index >= 3:
                button.hide()
        controls.setFixedWidth(345)
        self.refill_buttons = {}
        for index,(brick,color) in enumerate(( (brick,color) for brick in ("2x2x1","2x3x1")
                                               for color in ("yellow","blue") )):
            button = QPushButton(f"{'노랑' if color=='yellow' else '파랑'} {'4점' if brick=='2x2x1' else '6점'} 보충")
            button.clicked.connect(lambda checked=False, brick=brick,color=color: self._refill(brick,color))
            control_layout.addWidget(button,2+index//2,index%2)
            button.hide()
            self.refill_buttons[brick,color] = button
        process.addWidget(controls)
        root.addLayout(process)
        upper = QHBoxLayout()
        self.design_panel = QGroupBox("전체 완성 목표 · 미채택")
        design_layout = QVBoxLayout(self.design_panel)
        self.design_board = BoardView(isometric=True)
        design_layout.addWidget(self.design_board)
        self.design_caption = QLabel("24×24점 전체판 / 같은 목표의 확대")
        design_layout.addWidget(self.design_caption)
        upper.addWidget(self.design_panel,1)
        monitor_panel = QGroupBox("공정 모니터링 · 공급열별 다음 슬롯")
        monitor_layout = QVBoxLayout(monitor_panel)
        self.monitor = QLabel()
        self.monitor.setWordWrap(True)
        monitor_layout.addWidget(self.monitor)
        self.supply = QLabel()
        self.supply.setWordWrap(True)
        monitor_layout.addWidget(self.supply)
        upper.addWidget(monitor_panel,1)
        root.addLayout(upper,2)
        self.step_panel = QGroupBox("현재 Step · 없음")
        step_layout = QVBoxLayout(self.step_panel)
        self.comparison = QLabel("관측 대기")
        step_layout.addWidget(self.comparison)
        step_body = QHBoxLayout()
        board_layout = QVBoxLayout()
        self.target_board = BoardView(isometric=True)
        board_layout.addWidget(self.target_board,1)
        self.target_caption = QLabel()
        self.target_caption.setFont(QFont("Noto Sans CJK KR",9))
        self.target_caption.setWordWrap(True)
        board_layout.addWidget(self.target_caption)
        step_body.addLayout(board_layout,4)
        self.table = QTableWidget(5,3)
        self.table.setHorizontalHeaderLabels(["항목","현재 목표","실제 관측"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        for row,caption in enumerate(("종류","색상","좌표 (x,y)","층","방향")):
            self.table.setItem(row,0,QTableWidgetItem(caption))
            self.table.setRowHeight(row,32)
        step_body.addWidget(self.table,6)
        step_layout.addLayout(step_body)
        root.addWidget(self.step_panel,4)
        notice_panel = QGroupBox("질문 · 보류 사유 · 해야 할 일")
        notice_layout = QVBoxLayout(notice_panel)
        self.notice = QTextBrowser()
        self.notice.setOpenExternalLinks(False)
        self.notice.setMinimumHeight(92)
        notice_layout.addWidget(self.notice)
        root.addWidget(notice_panel,1)
        self.footer = QLabel("Backend 상태 미수신")
        self.footer.setFont(QFont("Noto Sans CJK KR",8))
        root.addWidget(self.footer)
        self.snapshot_received.connect(self.render_snapshot, Qt.QueuedConnection)
        self.setFixedSize(self._frame_size)
        self.move(0,0)

    def showEvent(self, event):
        super().showEvent(event)
        # 논리 픽셀 기준 지정 크기에 창 장식을 포함한다. 실제 WM/DPI 검증은 별도다.
        margins = self.frameGeometry().size()-self.size()
        self.setFixedSize(self._frame_size-margins)

    def _request(self, name):
        if self._snapshot is None:
            return
        actions = self._snapshot["actions"]
        command = dict(command=name)
        if name in ("STOP", "RESUME") and actions["job_id"] is None:
            command["command"] = "STOP_PREPARATION" if name == "STOP" else "RESUME_PREPARATION"
            self.command_requested.emit(validate_hmi_command(command))
            return
        if name not in ("START", "PREPARE_OBSERVE"):
            command["job_id"] = actions["job_id"]
        if name in ("KEEP","REVISE"):
            command.update(command="CHOOSE_INTENT", choice=name, request_id=actions["intent_choice"]["request_id"])
        elif name == "CONTINUE_AFTER_CORRECTION":
            command["request_id"] = actions["correction_continue"]["request_id"]
        self.command_requested.emit(validate_hmi_command(command))

    def _refill(self, brick, color):
        self.command_requested.emit(validate_hmi_command(dict(command="SUPPLY_REFILLED",
            job_id=self._snapshot["actions"]["job_id"],brick_type=brick,color=color)))

    @pyqtSlot(dict)
    def render_snapshot(self, value):
        snapshot = validate_hmi_snapshot(value)
        self._snapshot = snapshot
        mode = snapshot["monitor"]["robot"]["mode"]
        manual_trial = snapshot.get("manual_trial", False)
        reported = snapshot.get("reported_placement")
        transfer = snapshot.get("transfer_target")
        self.setWindowTitle(f"협동 조립 · Day4 · {mode}")
        self.heading.setText("협동 조립 · Day4                         실제 Robot REAL · 한 블록 시험" if mode == "REAL" else
                             "협동 조립 · Day4                         모의 연결 FAKE · 실제 장치 미연결")
        if manual_trial:
            self.heading.setText("협동 조립 · Day4                         실제 Robot REAL · 현장 수동 확인 시험")
        self.buttons["START"].setText("준비 확인 · 1회 시작" if mode == "REAL" else "시작")
        if manual_trial:
            self.buttons["START"].setText("준비 확인 · Job 시작")
        self.status.setText(WORKFLOW_LABELS[snapshot["workflow_status"]])
        p = snapshot["progress"]
        self.progress.setText("한 블록 전달 시험 · 조립 Plan 미채택" if mode == "REAL" and not manual_trial else
                              f"현재 Plan · 조립 확인 {p['completed']} / {p['total']} Step")
        design = snapshot["design"]
        self.design_panel.setTitle(f"전체 완성 목표 · 채택 Design v{design['design_version']}" if design else "전체 완성 목표 · 미채택")
        self.design_board.set_blocks(design["blocks"] if design else [])
        self.design_caption.setText("조립 Design 미채택 · 지정 블록 1개 전달 시험" if mode == "REAL" and not manual_trial else
                                    "등받이 뒤쪽 시점 · 24×24점 전체판 / 같은 목표의 확대")
        step = snapshot["step"]
        self.step_panel.setTitle(f"현재 Step · {step['step_id'] or '없음'}")
        self.comparison.setText((label(step["comparison"]) if step["target"] else "현재 Step 없음") +
                                " · 등받이 뒤쪽 시점 · X ↙ / Y ↘ · 층 ↑")
        self.target_board.set_assembly(snapshot["current"], step["target"])
        self.target_board.set_transfer_target(transfer)
        self.target_board.set_reported_placement(reported)
        layers = "·".join(str(layer) for layer in sorted({block["layer"] for block in snapshot["current"]["blocks"]}))
        target_legend = ("점선: 이번 목표 (Current에 반영됨)" if step["target"] in snapshot["current"]["blocks"] else
                         "점선: 이번에 놓을 블록" if step["target"] else "다음 목표 없음")
        self.target_caption.setText("블록 종류 표시 · 공급판 → 고정 전달판\n조립 위치·층·방향 미채택\n조립 관측 기록 없음 · 실제 비움 미확인" if transfer else
            f"실선: 확인된 현재 구조\n{target_legend}\n"
            f"Current r{snapshot['current']['current_revision']} · 채택 {len(snapshot['current']['blocks'])}개"
            f"{' · '+layers+'층' if layers else ''}")
        if not snapshot["current"]["blocks"] and not step["target"] and not transfer:
            self.target_caption.setText("채택된 조립 관측 기록 없음 · 실제 보드 비움 여부 미확인")
        if reported:
            self.target_caption.setText(self.target_caption.text()+"\n현장 입력 배치 · Camera 확인 아님")
            self.comparison.setText("현장 입력과 목표 차이 · 사람이 확인/정리 · 다음 전달 보류")
        if transfer:
            self.step_panel.setTitle(f"Robot 전달 대상 · 공급 슬롯 {transfer['slot']}번")
            self.comparison.setText("고정 전달판으로 전달 · 사람 조립 목표 미채택")
        observed = step["observed"]
        actual = [fields(block) for block in observed["visible_blocks"]] if observed else []
        if reported:
            actual = [fields(reported)]
        target = fields(step["target"])
        if transfer:
            target = ["4점 (2×2)" if transfer["brick_type"] == "2x2x1" else "6점 (2×3)",
                      "노랑" if transfer["color"] == "yellow" else "파랑", "미채택", "미채택", "미채택"]
        # 관측 목록의 블록마다 한 열을 사용한다. 목표와 물리 블록의 대응을 추정하지 않는다.
        self.table.setColumnCount(2+max(1,len(actual)))
        self.table.setHorizontalHeaderLabels(["항목","전달할 블록" if transfer else "현재 목표"]+
            (["현장 입력"] if reported else [f"실제 관측 {i+1}" for i in range(len(actual))] if actual else ["실제 관측"]))
        for row in range(5):
            text = "—" if step["target"] is None else (
                "판단 불가" if step["comparison"] == "UNOBSERVABLE" else
                "보이는 블록 없음" if observed else "결과 미수신")
            self.table.setItem(row,1,QTableWidgetItem(target[row]))
            for column,block in enumerate(actual):
                self.table.setItem(row,column+2,QTableWidgetItem(block[row]))
            if not actual:
                self.table.setItem(row,2,QTableWidgetItem(text))
            self.table.setRowHeight(row,32)
        m = snapshot["monitor"]
        self.monitor.setText(f"Robot: {label(m['robot']['status'])}\n관측: {label(m['observation']['status'])}"
                             f"\n전달판: {label(m['place_status'])}")
        self.supply.setText("\n".join(f"{'노랑' if item['color']=='yellow' else '파랑'} "
            f"{'4점' if item['brick_type']=='2x2x1' else '6점'}: "
            f"{'보충 필요' if item['needs_refill'] else str(item['next_slot'])+'번' if item['next_slot'] else '미확인'}"
            for item in m["supply"]))
        self.notice.setPlainText("\n".join(text for text in snapshot["notice"].values() if text and
                                          text != snapshot["notice"]["request_id"]))
        for name in ("START","STOP","RESUME"):
            self.buttons[name].setEnabled(snapshot["actions"][name.lower()]["enabled"])
        prepare = snapshot["actions"].get("prepare_observe")
        self.buttons["PREPARE_OBSERVE"].setVisible(prepare["visible"] if prepare else False)
        self.buttons["PREPARE_OBSERVE"].setEnabled(prepare["enabled"] if prepare else False)
        for name,key in (("KEEP","intent_choice"),("REVISE","intent_choice"),
                         ("CONTINUE_AFTER_CORRECTION","correction_continue")):
            action = snapshot["actions"][key]
            self.buttons[name].setVisible(action["visible"])
            self.buttons[name].setEnabled(action["enabled"])
        for key,button in self.refill_buttons.items():
            action = next((item for item in snapshot["actions"]["supply_refill"]
                           if (item["brick_type"],item["color"])==key),None)
            button.setVisible(action["visible"] if action else False)
            button.setEnabled(action["enabled"] if action else False)
        capture = m["observation"]
        self.footer.setText(f"{mode} · {'단일 전달 시험 · 실제 관측 미연결' if mode == 'REAL' else '장치 미연결'} · 촬영 check {capture['check_id'] or '미수신'} · "
                            f"순번 {capture['observation_seq'] if capture['observation_seq'] is not None else '미수신'}")
        if manual_trial:
            self.footer.setText(f"REAL · 현장 수동 확인 · Camera 미연결 · check {capture['check_id'] or '미수신'}")
