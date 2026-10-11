"""Wave 2 초안: REAL 경로 Preview→Review 연결과 B 확정 Current/revision relay.

장치·네트워크 호출 없음. REAL controller는 측정 원본(/home/ms-02/...) 없이 만들 수 있도록 Qt/Backend 접점만 흉내 낸
stub이다(실제 Robot 증거 아님). C 내부 llm 함수는 tests/integration/test_c_stage3_lifecycle.py의 FakeLLM을 쓴다.
"""

import importlib.util
import json
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from PyQt5.QtCore import QObject, QSize
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.c_candidate import on_review, open_candidate
from app.c_design import main as c_main
from app.c_text_connection import differences_for_c
from app.contracts import B_CURRENT_PROVENANCE
from app.fake_robot_driver import FakeRobotDriver
from app.jsonl_log import JsonlLog
from app.planning_connection import current_blocks_for_c, run_planning_request
from app.qt_hmi import HmiWindow
from app.real_design_controller import RealDesignController
from app.real_workflow_hmi import WorkflowTrial
from app.robot_controller import RobotController

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("c_lifecycle", ROOT / "tests/integration/test_c_stage3_lifecycle.py")
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)
fake_llm = lc.fake_llm
APPROVE = ["좋아 이걸로 하자"]
SUPPLY = [dict(brick_type=b, color=c, next_slot=1, needs_refill=False)
          for b, c in (("2x2x1", "yellow"), ("2x2x1", "blue"), ("2x3x1", "yellow"), ("2x3x1", "blue"), ("1x2x1", "red"))]


class StubRealController(RealDesignController):
    """REAL 접점만 흉내 낸다: 측정 파일·QProcess·ROS 없음. deliver 호출은 기록만 하고 거절한다(pick 0 확인용)."""

    def __init__(self):
        QObject.__init__(self)
        self.on_result = self.on_event = self.on_stopped = None
        self.delivered, self.prepared = [], []

    @property
    def state(self):
        return dict(mode="REAL", config_id="stub", transfer_target=dict(brick_type="2x2x1", color="blue", slot=1),
                    prepare_available=False, ready_at_observe=True, cleanup_ready=False, stop=None, fault=None,
                    active_execution=None, trial_notice="stub", supply=deepcopy(SUPPLY))

    @property
    def configuration(self):
        return dict(stub=True)

    def eventFilter(self, watched, event):
        return False

    def new_job(self, config=None):
        return dict(accepted=True, reason=None)

    def prepare_design_plan(self, plan):
        self.prepared.append(deepcopy(plan))

    def deliver(self, value):
        self.delivered.append(deepcopy(value))
        return dict(accepted=False, reason="STUB_NO_MOTION")

    def stop(self, value):
        return dict(accepted=True, reason=None)


def candidate(version=1, color="blue"):
    blocks = [dict(brick_type="2x2x1", color=color, x=10, y=10, layer=1, orientation_deg=0)]
    return dict(status="OK", hri_result=None, design=dict(design_version=version, blocks=blocks),
                design_metadata=dict(review=dict(round=0)), questions=[], error=None)


def review_reply(response, **changes):
    return dict(status="OK", hri_result="APPROVE", design=deepcopy(response["design"]),
                design_metadata=deepcopy(response["design_metadata"]), questions=["좋아요?"], error=None, **changes)


@pytest.fixture
def real(tmp_path, monkeypatch):
    monkeypatch.setenv("C_DESIGN_USE_LLM", "0")
    app = QApplication.instance() or QApplication([])
    built = []

    def build(reviews, *, initial=None, gate=None):
        """reviews: review 호출마다 돌려줄 응답 함수 목록(candidate, kwargs) -> envelope."""
        window = HmiWindow(screen_size=QSize(1920, 1080))
        controller = StubRealController()
        seen = dict(review=[], preview_at_review=[])
        monkeypatch.setattr(c_main, "create_initial_design", lambda **kwargs: deepcopy(initial or candidate()))

        def review(design, **kwargs):
            # 호출 순간 Qt에 그려진 Preview를 기록한다: Preview 완료 뒤에만 Review가 시작되는지 확인.
            seen["preview_at_review"].append(deepcopy((window._snapshot or {}).get("design_preview")))
            seen["review"].append(dict(design=deepcopy(design), **{k: deepcopy(v) for k, v in kwargs.items()
                                                                   if k in ("kind", "design_metadata")}))
            if gate is not None:
                gate.wait(5)
                seen["should_stop"] = kwargs["should_stop"]()
            return reviews[len(seen["review"]) - 1](design, kwargs)
        monkeypatch.setattr(c_main, "review_design_candidate", review)
        trial = WorkflowTrial(window, controller, None, tmp_path / "backend", c_mode="offline")
        built.append(trial)
        return trial, controller, seen

    yield build
    for trial in built:
        trial.c_connection.close()
        trial.window.close()
    assert app is not None


def settle(trial, until, steps=500):
    for _ in range(steps):
        QTest.qWait(2)
        if until():
            return
    raise AssertionError("Qt flow did not settle")


def start(trial):
    assert trial.command(dict(command="START"))["accepted"]


# 1. REAL Preview 완료 → Review: Preview 전 0회, 그려진 뒤 1회, 재렌더링으로 중복 호출 없음
def test_real_review_starts_only_after_preview_is_drawn(real):
    unclear = lambda design, kwargs: dict(status="OK", hri_result="UNCLEAR", design=deepcopy(design),
                                          design_metadata=kwargs["design_metadata"], questions=["어떤가요?"], error=None)
    trial, controller, seen = real([unclear])
    start(trial)
    settle(trial, lambda: seen["review"] and not trial.c_connection.active)
    assert len(seen["review"]) == 1
    shown = seen["preview_at_review"][0]
    assert shown is not None and shown["design"] == candidate()["design"]
    for _ in range(5):  # 같은 후보의 재렌더링은 phase guard로 무시
        trial.publish()
        QTest.qWait(5)
    assert len(seen["review"]) == 1
    # UNCLEAR는 자동 승인하지 않는다: 질문 대기, Plan/Pick 0
    assert trial.backend.state["c_review"]["phase"] == "WAIT_ANSWER"
    assert controller.prepared == [] and controller.delivered == []


# 2. MODIFY 재호출 → APPROVE만 채택 → A(REAL preflight) 1회
def test_real_modify_previews_again_and_only_approval_reaches_a(real):
    modified = candidate(color="yellow")
    trial, controller, seen = real([
        lambda design, kwargs: dict(review_reply(modified), hri_result="MODIFY",
                                    design_metadata=dict(review=dict(round=1))),
        lambda design, kwargs: review_reply(dict(design=design, design_metadata=kwargs["design_metadata"])),
    ])
    start(trial)
    settle(trial, lambda: len(seen["review"]) == 2 and not trial.c_connection.active)
    assert seen["review"][1]["design"] == modified["design"]
    assert seen["review"][1]["design_metadata"] == dict(review=dict(round=1))
    assert seen["preview_at_review"][1]["design"] == modified["design"]
    assert len(controller.prepared) == 1  # APPROVE 뒤 REAL 전체 Plan preflight 1회
    assert trial.backend.state["context"]["design"] == modified["design"]
    assert controller.delivered == []  # 현장 place_empty 입력 전 이동 없음


# 3. CANCEL / FAILED → Plan/Pick 0
@pytest.mark.parametrize("status,decision,code", [("CANCELLED", "CANCEL", "USER_CANCEL"),
                                                  ("FAILED", None, "LLM_CALL_FAILED")])
def test_real_cancel_or_failed_review_never_plans(real, status, decision, code):
    trial, controller, seen = real([lambda design, kwargs: dict(status=status, hri_result=decision, design=None,
        design_metadata=None, questions=[], error=dict(code=code, message="x", details=[]))])
    start(trial)
    settle(trial, lambda: seen["review"] and not trial.c_connection.active)
    assert trial.backend.state["workflow_status"] == "HOLD"
    assert controller.prepared == [] and controller.delivered == []


# 4. Review 중 STOP → 늦은 APPROVE로 Plan/Pick 0
def test_real_stop_during_review_ignores_late_approval(real):
    gate = threading.Event()
    trial, controller, seen = real([lambda design, kwargs: review_reply(dict(
        design=design, design_metadata=kwargs["design_metadata"]))], gate=gate)
    start(trial)
    settle(trial, lambda: seen["review"])
    assert trial.command(dict(command="STOP", job_id=trial.backend.state["job_id"]))["accepted"]
    gate.set()
    settle(trial, lambda: not trial.c_connection.active)
    assert seen["should_stop"] is True
    assert controller.prepared == [] and controller.delivered == []
    assert trial.backend.state["context"] is None


# 5. B 확정 Current relay: revision 12·provenance 유지, D 재발급 없음, A·C 입력
CONFIG = json.loads((ROOT / "interfaces/fixtures/robot.json").read_text())


def b_frame(check, blocks, revision, *, seq=0, status="OK"):
    return dict(check_id=check, observation_seq=seq, status=status,
                visible_blocks=deepcopy(blocks) if status == "OK" else [],
                verified_regions=[dict(x=0, y=0, width=24, height=24, layer=layer) for layer in range(1, 6)]
                if status == "OK" else [], reason=None if status == "OK" else "hand occlusion",
                current=dict(current_revision=revision, blocks=deepcopy(blocks)),
                current_provenance=B_CURRENT_PROVENANCE)


def fake_job(tmp_path):
    calls = []

    def emit(port, payload):
        calls.append((port, deepcopy(payload)))
        if port == "planner" and "design" in payload:
            run_planning_request(backend, payload)
    backend = Backend(emit, mode="FAKE", record=JsonlLog(tmp_path))
    driver = FakeRobotDriver(ready_at_observe=True)
    backend.connect_robot(RobotController(CONFIG, driver, backend.on_robot_result,
                                          on_stopped=backend.on_stopped, on_event=backend.on_robot_event))
    assert backend.command(dict(command="START"))["accepted"]
    return backend, driver, calls


def approve_initial(backend):
    initial = c_main.create_initial_design(text="의자 만들어줘")
    open_candidate(backend, "initial", backend.state["planning_request"], initial)
    backend._state["c_review"]["phase"] = "REVIEW"
    review = deepcopy(backend.state["c_review"])
    assert on_review(backend, review, c_main.review_design_candidate(
        review["design"], kind="initial", design_metadata=review["design_metadata"], text_answers=APPROVE))
    return initial["design"]


def deliver_one(backend, driver):
    assert backend.on_place(backend.state["place_check"]["check_id"], 0, "EMPTY")
    execution = backend.state["execution_id"]
    for operation in ("pick", "place", "observe"):
        assert driver.confirm(execution, operation)
    return backend.state["active_check"]["check_id"]


def rows(tmp_path, backend):
    return [json.loads(line) for line in (tmp_path / (backend.state["job_id"] + ".jsonl")).read_text().splitlines()]


def test_b_revision_12_is_relayed_to_d_a_and_c_without_reissue(tmp_path, fake_llm):
    backend, driver, calls = fake_job(tmp_path)
    design = approve_initial(backend)
    target = backend._next_step()["after"]
    check = deliver_one(backend, driver)
    moved = dict(target, y=target["y"] + 1)
    assert backend.on_observation(b_frame(check, [moved], 12))
    state = backend.state
    assert state["current"] == dict(current_revision=12, blocks=[moved])  # D +1 아님(0→12 그대로)
    adopted = [row for row in rows(tmp_path, backend) if row["event"] == "CURRENT_ADOPTED"]
    assert adopted[-1]["result"]["current_provenance"] == B_CURRENT_PROVENANCE
    assert state["workflow_status"] == "WAIT_INTENT" and state["question_request"]["current_revision"] == 12
    hri = next(payload for port, payload in reversed(calls) if port == "hri")
    assert hri["current"]["current_revision"] == 12
    assert current_blocks_for_c(hri) == [moved]  # C에는 block list만
    fake_llm.answers = [{"decision": "REVISE", "style_hint": "", "reason": "…", "reply": ""}]
    revise = c_main.run_intervention(design, current_blocks_for_c(hri), differences_for_c(hri["difference"]),
                                     text_answers=["일부러 그렇게 놨어요"])
    payload = dict(**state["question_request"], design=design, current=state["current"], difference=state["difference"])
    assert open_candidate(backend, "revised", payload, revise)
    backend._state["c_review"]["phase"] = "REVIEW"
    review = deepcopy(backend.state["c_review"])
    approve = c_main.review_design_candidate(review["design"], kind="revised", design_metadata=review["design_metadata"],
        previous_design=review["previous_design"], current=current_blocks_for_c(review),
        differences=differences_for_c(review["difference"]), text_answers=APPROVE)
    assert on_review(backend, review, approve)
    replan = [payload for port, payload in calls if port == "planner" and "design" in payload][-1]
    assert replan["base_current_revision"] == 12 and replan["current"]["current_revision"] == 12
    assert backend.state["current"]["current_revision"] == 12
    plans = [row for row in rows(tmp_path, backend) if row["event"] == "PLAN_RESULT"]
    assert plans[-1]["result"]["plan"]["base_current_revision"] == 12  # A가 12를 그대로 복사


def test_b_relay_same_state_keeps_revision_and_rejects_regression(tmp_path, fake_llm):
    backend, driver, calls = fake_job(tmp_path)
    approve_initial(backend)
    target = backend._next_step()["after"]
    check = deliver_one(backend, driver)
    assert backend.on_observation(b_frame(check, [target], 12))  # Step 확인
    assert backend.state["current"]["current_revision"] == 12
    target2 = backend._next_step()["after"]
    check = deliver_one(backend, driver)
    with pytest.raises(ValueError):  # revision 역행
        backend.on_observation(b_frame(check, [target, target2], 11))
    with pytest.raises(ValueError):  # 같은 revision인데 다른 배치
        backend.on_observation(b_frame(check, [target, target2], 12))
    assert backend.state["current"]["current_revision"] == 12
    assert backend.on_observation(b_frame(check, [target], 12, seq=1, status="UNOBSERVABLE"))
    assert backend.state["current"] == dict(current_revision=12, blocks=[target])  # 관측 불가: 유지·재발급 없음
    assert backend.on_observation(b_frame(check, [target, target2], 13, seq=2))
    assert backend.state["current"]["current_revision"] == 13


def test_day4_observation_without_b_current_keeps_existing_d_revision(tmp_path, fake_llm):
    backend, driver, calls = fake_job(tmp_path)
    approve_initial(backend)
    target = backend._next_step()["after"]
    check = deliver_one(backend, driver)
    day4 = {key: value for key, value in b_frame(check, [target], 12).items()
            if key not in ("current", "current_provenance")}
    assert backend.on_observation(day4)
    assert backend.state["current"]["current_revision"] == 1  # 호환 경로: 기존 D 발급 그대로
