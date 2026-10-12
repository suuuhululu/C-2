"""C 대화와 초안의 표시. 승인·Current 갱신·명령 발행은 하지 않는다."""

from PyQt5.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from app.hmi_board import BoardView


DIALOGUE_LABELS = dict(LISTENING="말씀을 듣고 있습니다", GENERATING="설계를 만들고 있습니다",
    SPEAKING="설계를 설명하고 있습니다", REVIEW="설계를 확인해주세요",
    WAIT_APPROVAL="대화에서 승인을 기다립니다", FAILED="대화를 진행하지 못했습니다")


class DesignDialogueView(QWidget):
    def __init__(self):
        super().__init__()
        root = QHBoxLayout(self)
        self.phase = QLabel("설계 대화 정보 없음")
        self.phase.setWordWrap(True)
        self.phase.setFixedWidth(245)
        root.addWidget(self.phase)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        self.target_panel = QGroupBox("조립 목표 · 미채택", self)
        target_layout = QVBoxLayout(self.target_panel)
        self.target_board = BoardView(isometric=True)
        target_layout.addWidget(self.target_board, 1)
        self.target_caption = QLabel()
        self.target_caption.setWordWrap(True)
        target_layout.addWidget(self.target_caption)
        self.context = QLabel()
        self.context.setWordWrap(True)
        root.addWidget(self.context, 1)
        self.reason = QTextBrowser()
        self.reason.setOpenExternalLinks(False)
        self.reason.setFixedHeight(38)
        root.addWidget(self.reason, 2)
        self.setFixedHeight(42)

    def render_snapshot(self, snapshot):
        preview = snapshot.get("design_preview")
        dialogue = snapshot.get("dialogue")
        approved = snapshot["design"]
        self.phase.setText(DIALOGUE_LABELS[dialogue["phase"]] if dialogue else "설계 대화 정보 없음")
        # 초안과 승인 목표는 한 그림으로 교체 표시하되 실행 목표/Current를 바꾸지 않는다.
        draft = preview is not None and snapshot["workflow_status"] != "COMPLETE"
        design = preview["design"] if draft else approved
        self.target_board.set_blocks(design["blocks"] if design else [])
        title = (f"조립 목표 · 미승인 미리보기 v{design['design_version']}" if draft else
                 f"조립 목표 · 채택 Design v{design['design_version']}" if design else "조립 목표 · 미채택")
        self.target_panel.setTitle(title)
        self.target_board.setAccessibleName(title)
        self.target_board.zoom_caption = "미승인 미리보기 확대" if draft else "조립 목표 확대"
        context = (f"실행 기준: 채택 Design v{approved['design_version']}" if approved else "실행 목표 미채택")
        self.target_caption.setText(("미승인 · " + context if draft else context) + "\n등받이 뒤쪽 시점 · 24×24점")
        if design is not None and not design["blocks"]:
            self.target_caption.setText(self.target_caption.text() + "\n블록 없음")
        self.context.setText("미리보기 갱신 중 · 설계 승인은 C 대화에서 진행합니다." if draft else
                             "승인된 설계를 표시합니다." if approved else "설계와 승인 결과를 기다립니다.")
        self.reason.setPlainText("진행 사유: " + dialogue["reason"] if dialogue and dialogue["reason"] else "")
        self.reason.setVisible(bool(dialogue and dialogue["reason"]))
