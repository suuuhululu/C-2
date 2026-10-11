"""도움 대상·준비·유지·해제 안내. 손 영역/힘이나 실행 조건을 생성하지 않는다."""

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from app.hmi_board import BoardView


KINDS = dict(SUPPORT="구조 지지 도움", HANDOVER="손으로 블록 받기 요청", HUMAN_ASSEMBLY="사람 직접 조립")
PHASES = dict(REQUESTED="도움 요청 · 준비 응답 대기", READY="준비 응답 접수 · 실행 확인 별도",
    MAINTAIN="도움 유지 안내", RELEASED="도움 해제 안내", CANCELED="요청 취소 · 최신 D 안내 확인")


class AssistanceView(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.target_board = BoardView(isometric=True)
        self.target_board.zoom_caption = "도움 대상 확대"
        body = QHBoxLayout()
        self.target_board.setMaximumWidth(105)
        self.target_board.setMinimumHeight(35)
        self.target_board.overview = False
        body.addWidget(self.target_board, 1)
        self.instruction = QTextBrowser()
        self.instruction.setOpenExternalLinks(False)
        body.addWidget(self.instruction, 3)
        root.addLayout(body, 1)

    def render_snapshot(self, snapshot):
        assistance = snapshot.get("assistance")
        if not assistance:
            self.summary.setText("현재 도움 요청 정보 없음")
            self.target_board.set_blocks([])
            self.target_board.hide()
            self.instruction.setPlainText("도움 위치·방향·준비·해제 지시를 제공받지 않았습니다.")
            return
        target = assistance["target"]
        self.target_board.set_blocks([target])
        self.target_board.show()
        paused = (snapshot["workflow_status"] in ("HOLD", "STOPPED", "REPLANNING") or
                  snapshot["monitor"]["robot"]["status"] in ("STOP_PENDING", "STOPPED", "ERROR"))
        self.summary.setText(KINDS[assistance["kind"]] + " · " +
            ("직전 요청 · 유지/해제는 최신 D 안내 확인" if paused else PHASES[assistance["phase"]]))
        text = ("이전 안내 (현재 실행 지시 아님):\n" if paused else "D가 전달한 안내:\n") + assistance["instruction"]
        text += f"\n\n대상: ({target['x']}, {target['y']}) · {target['layer']}층 · {target['orientation_deg']}°. 이번에 놓는 블록과 다를 수 있습니다."
        if assistance["kind"] == "HANDOVER":
            text += "\n손 인계 요청입니다. 전달판 경로만으로 손 인계나 그리퍼 개방을 실행하지 않습니다."
        if assistance["phase"] in ("REQUESTED", "READY"):
            text += "\n준비 응답은 설계/Step 승인이나 파지·조립 완료가 아닙니다. 실제 실행 조건은 D가 확인합니다."
        if assistance["phase"] == "CANCELED" or paused:
            text += "\n취소·정지만으로 손을 놓으라는 뜻은 아닙니다. 구조와 파지를 확인한 D의 안내가 필요합니다."
        self.instruction.setPlainText(text)
