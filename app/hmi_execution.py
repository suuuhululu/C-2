"""D가 보고한 현재 Step 실행 단계의 표시. 완료·실행권을 계산하지 않는다."""

from PyQt5.QtWidgets import QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget


METHOD_LABELS = dict(ROBOT_GRIP="로봇 직접 조립", HUMAN_ASSEMBLY="전달판을 통한 사람 조립")
PHASE_LABELS = dict(APPROACH_PICK="공급 블록 픽업 접근", PICK_AND_CONFIRM="집기·파지 확인 단계",
    TRANSPORT_HOLDING="블록을 잡은 채 이송", PRE_CONTACT="접촉 전 대기", CONTACT="로봇 결착 단계",
    RELEASE="그리퍼 개방 단계", RETREAT="로봇 후퇴 단계", WAIT_INSPECTION="조립 관측 확인 대기", HOLD="진행 보류")


def execution_is_active(snapshot):
    return (snapshot["workflow_status"] in ("PREPARING", "DELIVERING", "WAIT_ASSEMBLY")
            and snapshot["monitor"]["robot"]["status"] not in ("STOP_PENDING", "STOPPED", "ERROR")
            and snapshot["execution"]["phase"] != "HOLD")


def execution_heading(snapshot):
    execution = snapshot.get("execution")
    if not execution:
        return None
    robot = snapshot["monitor"]["robot"]["status"]
    if robot in ("STOP_PENDING", "STOPPED", "ERROR"):
        return {"STOP_PENDING": "정지 확인 대기", "STOPPED": "정지 확인", "ERROR": "로봇 오류 · 진행 보류"}[robot]
    if snapshot["workflow_status"] not in ("PREPARING", "DELIVERING", "WAIT_ASSEMBLY"):
        return None
    if execution["phase"] == "HOLD":
        return "진행 보류"
    return f"{METHOD_LABELS[execution['method']]} · {PHASE_LABELS[execution['phase']]}"


class ExecutionView(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(3)
        self.method, self.phase = QLabel(), QLabel()
        for item in (self.method, self.phase):
            item.setWordWrap(True)
            root.addWidget(item)
        self.description = QTextBrowser()
        self.description.setOpenExternalLinks(False)
        self.description.setMinimumHeight(25)
        root.addWidget(self.description, 1)
        self.details_button = QPushButton("개발 정보")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._render_description)
        root.addWidget(self.details_button)
        self._snapshot = None
        self.render_snapshot({})

    def render_snapshot(self, snapshot):
        self._snapshot = snapshot
        execution = snapshot.get("execution")
        self.details_button.setEnabled(execution is not None)
        if not execution:
            self.method.setText("실행 방식 정보 없음")
            self.phase.setText("실행 단계 정보 없음")
            self.details_button.setChecked(False)
        else:
            self.method.setText(METHOD_LABELS[execution["method"]])
            phase = PHASE_LABELS[execution["phase"]]
            if execution["method"] == "ROBOT_GRIP" and execution["phase"] == "PRE_CONTACT":
                phase = "결착 전 대기 (pre-contact)"
            active = execution_is_active(snapshot)
            prefix = "보고 단계" if active else "직전 보고 단계 · 공정 상태 우선"
            self.phase.setText(f"{prefix}: {phase}")
        self._render_description()

    def _render_description(self):
        execution = self._snapshot.get("execution") if self._snapshot else None
        if not execution:
            self.description.setPlainText("현재 Step의 실행 정보가 제공되지 않았습니다.")
            return
        human = execution["method"] == "HUMAN_ASSEMBLY"
        actor = ("사람 조립 / 비전 확인 대기" if human else "비전 확인 대기") if execution["phase"] == "WAIT_INSPECTION" else "로봇 (D 제어)"
        if not execution_is_active(self._snapshot):
            actor = "공정 보류 · D 상태 확인"
        flow = ("픽업 접근 → 집기·확인 → 전달판 이송 → 개방·후퇴 → 사람 조립·관측" if human else
                "픽업 접근 → 집기·확인 → 파지 이송 → 결착 전 대기 → 결착 → 개방·후퇴 → 관측")
        text = f"이번 Step 담당: {actor}\n참고 흐름: {flow}\n\n보고 단계는 완료 이력이 아닙니다. 조립 확인은 비전 결과를 기다립니다."
        if self.details_button.isChecked():
            text += (f"\n\nPlan: {execution['plan_id']}\nStep: {execution['step_id']}"
                     f"\n경로: {execution['motion_plan_id'] or '미발급'}"
                     f"\nmethod: {execution['method']}\nphase: {execution['phase']}")
        self.description.setPlainText(text)
