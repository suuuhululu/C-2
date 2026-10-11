"""C 대화와 초안의 표시. 승인·Current 갱신·명령 발행은 하지 않는다."""

from PyQt5.QtWidgets import QGroupBox, QLabel, QTextBrowser, QVBoxLayout, QWidget

from app.hmi_board import BoardView


DIALOGUE_LABELS = dict(LISTENING="말씀을 듣고 있습니다", GENERATING="설계를 만들고 있습니다",
    SPEAKING="설계를 설명하고 있습니다", REVIEW="설계를 확인해주세요",
    WAIT_APPROVAL="대화에서 승인을 기다립니다", FAILED="대화를 진행하지 못했습니다")


class DesignDialogueView(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        self.phase = QLabel("설계 대화 정보 없음")
        self.phase.setWordWrap(True)
        root.addWidget(self.phase)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        self.preview_panel = QGroupBox("대화 중 초안 · 미승인", self)
        preview_layout = QVBoxLayout(self.preview_panel)
        self.preview_board = BoardView(isometric=True)
        self.preview_board.zoom_caption = "미승인 초안 확대"
        self.preview_board.setAccessibleName("대화 중 미승인 설계 초안")
        preview_layout.addWidget(self.preview_board)
        self.preview_caption = QLabel()
        self.preview_caption.setWordWrap(True)
        preview_layout.addWidget(self.preview_caption)
        self.approved_panel = QGroupBox("승인된 조립 목표 · 없음", self)
        approved_layout = QVBoxLayout(self.approved_panel)
        self.approved_board = BoardView(isometric=True)
        self.approved_board.zoom_caption = "승인 목표 확대"
        self.approved_board.setAccessibleName("승인된 조립 목표")
        approved_layout.addWidget(self.approved_board)
        self.approved_caption = QLabel()
        self.approved_caption.setWordWrap(True)
        approved_layout.addWidget(self.approved_caption)
        self.conversation = QTextBrowser()
        self.conversation.setOpenExternalLinks(False)
        self.conversation.setMinimumHeight(35)
        root.addWidget(self.conversation, 2)
        self.reason = QTextBrowser()
        self.reason.setOpenExternalLinks(False)
        self.reason.setFixedHeight(35)
        root.addWidget(self.reason)

    def render_snapshot(self, snapshot):
        preview = snapshot.get("design_preview")
        dialogue = snapshot.get("dialogue")
        approved = snapshot["design"]
        self.phase.setText(DIALOGUE_LABELS[dialogue["phase"]] if dialogue else "설계 대화 정보 없음")
        self.preview_board.set_blocks(preview["design"]["blocks"] if preview else [])
        # 전체 snapshot에서 생략된 초안은 이전 요청의 그림을 남기지 않는다.
        self.preview_board.setVisible(bool(preview and preview["design"]["blocks"]))
        self.preview_caption.setText(("미승인 · 실행 목표와 별개" if preview["design"]["blocks"] else
                                      "미승인 초안 · 블록 없음") if preview else "받은 설계 초안이 없습니다.")
        self.approved_board.set_blocks(approved["blocks"] if approved else [])
        self.approved_board.setVisible(bool(approved and approved["blocks"]))
        self.approved_panel.setTitle(f"승인된 조립 목표 · v{approved['design_version']}" if approved else "승인된 조립 목표 · 없음")
        self.approved_caption.setText(("현재 조립의 승인 설계" if approved["blocks"] else
                                       "승인된 설계 · 블록 없음") if approved else "아직 승인된 조립 목표가 없습니다.")
        self.conversation.setPlainText("\n\n".join((
            "사용자: " + (dialogue["user_text"] or "발화 정보 없음"),
            "C: " + (dialogue["assistant_text"] or "응답 정보 없음"))) if dialogue else "받은 대화 내용이 없습니다.")
        self.reason.setPlainText("진행 사유: " + dialogue["reason"] if dialogue and dialogue["reason"] else "")
        self.reason.setVisible(bool(dialogue and dialogue["reason"]))
