"""물리 조립 종료와 저장·웹 반영 상태를 분리해 표시한다."""

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget


STORAGE_LABELS = dict(NOT_STARTED="아직 시작 안 함", PENDING="처리 중", SUCCEEDED="완료", FAILED="실패")


def completion_heading(snapshot):
    completion = snapshot.get("completion")
    if not completion or snapshot["workflow_status"] != "COMPLETE":
        return None
    if completion["storage"] == "FAILED":
        return "조립 완료 · 기록 저장 실패"
    if completion["web"] == "FAILED":
        return "조립 완료 · 웹 반영 실패"
    if completion["web"] == "SUCCEEDED":
        return "조립·저장·웹 반영 완료"
    return "조립 완료 · " + ("웹 반영 대기" if completion["storage"] == "SUCCEEDED" else "기록 저장 대기")


class CompletionView(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.hide()  # revision/진행률은 같은 페이지 상단에도 표시된다.
        self.states = {}
        states_row = QHBoxLayout()
        for name in ("blocks_used", "assembly", "storage", "web"):
            item = QLabel()
            item.setWordWrap(True)
            states_row.addWidget(item, 1)
            self.states[name] = item
        root.addLayout(states_row)
        self.reason = QTextBrowser()
        self.reason.setOpenExternalLinks(False)
        self.reason.setFixedHeight(23)
        root.addWidget(self.reason, 1)

    def render_snapshot(self, snapshot):
        completion = snapshot.get("completion")
        self.summary.setText("완료·저장 정보 미수신" if not completion else
                             f"현재 기록 r{snapshot['current']['current_revision']} · 조립 확인 {snapshot['progress']['completed']}/{snapshot['progress']['total']}")
        titles = dict(blocks_used="필요 블록 사용/작업 소진", assembly="최종 조립 확인", storage="기록 저장", web="개인 웹 반영")
        values = dict(blocks_used=("완료" if completion["blocks_used"] else "미완료") if completion else "미수신",
            assembly=dict(PENDING="확인 대기", MATCH="일치 확인", MISMATCH="차이 있음", UNOBSERVABLE="관측 불가").get(completion["assembly"]) if completion else "미수신",
            storage=STORAGE_LABELS[completion["storage"]] if completion else "미수신",
            web=STORAGE_LABELS[completion["web"]] if completion else "미수신")
        for key, item in self.states.items():
            item.setText(titles[key] + ": " + values[key])
        text = "조립 종료·저장·웹 반영은 각각 별도 보고입니다. 저장/웹 실패로 Current를 되돌리거나 로봇을 다시 실행하지 않습니다."
        if completion and completion["reason"]:
            text += "\n\n사유: " + completion["reason"]
        if completion and completion["assembly"] != "MATCH":
            text += "\n\n블록 사용이 끝나도 최종 조립 확인 전에는 전체 완료가 아닙니다."
        self.reason.setPlainText(text)
