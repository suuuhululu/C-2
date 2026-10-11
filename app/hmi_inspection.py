"""B가 확정한 현재/예상/차이를 표시한다. 공간 비교나 Current 채택은 하지 않는다."""

from PyQt5.QtWidgets import QGroupBox, QLabel, QTextBrowser, QVBoxLayout, QWidget

from app.hmi_board import BoardView


class InspectionView(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.board_panels = []
        self.current_board, self.expected_board = BoardView(isometric=True), BoardView(isometric=True)
        self.current_board.zoom_caption = "현재 기록 확대"
        self.expected_board.zoom_caption = "이번 단계 예상 확대"
        for title, board in (("확인된 현재 구조", self.current_board), ("이번 단계 예상 구조", self.expected_board)):
            panel = QGroupBox(title, self)
            layout = QVBoxLayout(panel)
            layout.addWidget(board)
            self.board_panels.append(panel)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        root.addWidget(self.details, 1)

    def render_snapshot(self, snapshot):
        current, result = snapshot["current"], snapshot.get("inspection")
        self.current_board.set_blocks(current["blocks"])
        expected = result["expected"] if result else None
        self.expected_board.set_blocks(expected["blocks"] if expected else [])
        self.expected_board.setVisible(bool(expected and expected["blocks"]))
        self.board_panels[1].setTitle("이번 단계 예상 구조" if expected else "이번 단계 예상 · 미수신/해당 없음")
        prefix = f"Current r{current['current_revision']} · 기록 {len(current['blocks'])}개"
        if not result:
            self.summary.setText(prefix + " · 새 B 검사 결과 미수신")
            self.details.setPlainText("예상 구조와 차이를 제공받지 않았습니다. 현재 기록만으로 보드 비움이나 목표 일치를 판단하지 않습니다.")
            return
        names = dict(MATCH="일치", MISMATCH="차이 있음", UNOBSERVABLE="관측 불가", ERROR="검사 오류", CANCELED="검사 취소", OK="초기 상태 확인")
        self.summary.setText(prefix + " · 비전 판정: " + names[result["comparison"] or result["status"]])
        parts = ["왼쪽은 확인된 실제 구조, 오른쪽은 이번 단계에 있어야 할 구조입니다. 아래에서 차이와 관측 한계를 확인하세요."]
        if expected is None:
            parts.append("이번 검사에는 비교 기준이 없습니다. 빈 예상 구조로 해석하지 않습니다.")
        elif not expected["blocks"]:
            parts.append("제공된 예상 구조: 블록 없음")
        if result["difference"] is not None:
            for key, title in (("missing", "확인된 목표 누락"), ("unexpected", "확인된 예상 밖 배치"), ("unobservable", "확인할 수 없는 대상")):
                blocks = result["difference"][key]
                parts.append(f"{title}: {len(blocks)}개")
                for block in blocks:
                    color = "노랑" if block["color"] == "yellow" else "파랑"
                    kind = "4점" if block["brick_type"] == "2x2x1" else "6점"
                    parts.append(f"  {color} {kind} · ({block['x']}, {block['y']}) · {block['layer']}층 · {block['orientation_deg']}°")
        if result["reason"]:
            parts.append("사유: " + result["reason"])
        observed = snapshot["step"]["observed"]
        if observed:
            parts.append(f"이번 영상: 읽은 블록 {len(observed['visible_blocks'])}개 / 확인 영역 {len(observed['verified_regions'])}개. 가려진 확인 이력은 Current와 별개로 지우지 않습니다.")
        self.details.setPlainText("\n".join(parts))
