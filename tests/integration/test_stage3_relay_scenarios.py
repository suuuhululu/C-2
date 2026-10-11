"""int B 임시 시나리오 시험(커밋 금지, Opus B 검사용).

#22 D Backend·c_candidate·CTextConnection + #23 C public API(LLM 함수는 fake) + #22 실제 A planner를
한 프로세스에서 연결한다. #22 head 단독에는 C Stage 3 코드가 없으므로 #22 + #23(C 파일) 결합 사본의
tests/integration/에 복사해 실행했다. 실제 OpenAI·마이크·Robot·Camera 호출 없음(tests/conftest.py가 차단).
Wave 3-light: WAIT_INTENT는 B 확정 Current relay(current_revision=12, current_provenance=B_CONFIRMED_D_RELAYED)를
Backend.on_observation으로 넣어 만든다(D는 revision을 재발급하지 않는다). 실제 B 생산자 연결은 아님.
"""

import importlib.util
import json
import threading
from copy import deepcopy
from pathlib import Path

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.c_candidate import on_review, open_candidate, valid_review
from app.c_design import main as c_main
from app.c_text_connection import CTextConnection, differences_for_c
from app.contracts import B_CURRENT_PROVENANCE
from app.fake_robot_driver import FakeRobotDriver
from app.planning_connection import current_blocks_for_c, run_planning_request
from app.robot_controller import RobotController

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("c_lifecycle", ROOT / "tests/integration/test_c_stage3_lifecycle.py")
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)
fake_llm = lc.fake_llm  # C 내부 llm 함수만 fake(C_DESIGN_USE_LLM=1)
APPROVE_TEXT = ["좋아 이걸로 하자"]


def backend(robot=True):
    calls = []
    b = Backend(lambda port, payload: calls.append((port, deepcopy(payload))), mode="FAKE")
    driver = None
    if robot:
        driver = FakeRobotDriver(ready_at_observe=True)
        b.connect_robot(RobotController(json.loads((ROOT / "interfaces/fixtures/robot.json").read_text()),
                                        driver, b.on_robot_result, on_stopped=b.on_stopped))
    else:
        b.controller_ready(ready=True, at_observe_point=True)
    assert b.command(dict(command="START"))["accepted"]
    return b, calls, driver


def plans(calls):
    """A Plan/Replan 요청(Design 포함 planner 호출)만."""
    return [payload for port, payload in calls if port == "planner" and "design" in payload]


def displayed(b):
    # CTextConnection.preview_ready가 하는 상태 전환과 같다(Qt 표시 완료 가정).
    b._state["c_review"]["phase"] = "REVIEW"
    return deepcopy(b.state["c_review"])


def c_review(review, answers):
    """c_text_connection.CTextConnection.start의 review 호출 인자 구성과 같다."""
    context = dict(previous_design=deepcopy(review["previous_design"]), current=current_blocks_for_c(review),
                   differences=differences_for_c(review["difference"])) if review["kind"] == "revised" else {}
    return c_main.review_design_candidate(deepcopy(review["design"]), kind=review["kind"],
                                          design_metadata=deepcopy(review["design_metadata"]),
                                          text_answers=list(answers), **context)


def approved_and_planned(b, calls):
    initial = c_main.create_initial_design(text="의자 만들어줘")
    assert open_candidate(b, "initial", b.state["planning_request"], initial)
    review = displayed(b)
    assert on_review(b, review, c_review(review, APPROVE_TEXT))
    assert run_planning_request(b, plans(calls)[-1])
    assert b.state["context"]["design"] == initial["design"]
    return initial["design"]


B_REVISION = 12


def wait_intent(b, design, revision=B_REVISION):
    """B가 확정한 Current(1층 블록 하나가 1 stud 이동, revision 12)를 relay해 WAIT_INTENT를 만든다."""
    target = b._next_step()["after"]
    assert b.on_place(b.state["place_check"]["check_id"], 0, "EMPTY")
    execution = b.state["execution_id"]
    for operation in ("pick", "place", "observe"):
        assert b._robot._driver.confirm(execution, operation)
    moved = dict(target, y=target["y"] + 1)
    assert b.on_observation(dict(check_id=b.state["active_check"]["check_id"], observation_seq=0, status="OK",
        visible_blocks=[moved], verified_regions=[dict(x=0, y=0, width=24, height=24, layer=layer)
                                                  for layer in range(1, 6)], reason=None,
        current=dict(current_revision=revision, blocks=[moved]), current_provenance=B_CURRENT_PROVENANCE))
    state = b.state
    assert state["workflow_status"] == "WAIT_INTENT" and state["current"]["current_revision"] == revision
    return dict(**state["question_request"], design=state["context"]["design"], current=state["current"],
                difference=state["difference"])


def revise(fake, payload):
    """c_text_connection의 run_intervention 호출 인자 구성과 같다."""
    fake.answers = [{"decision": "REVISE", "style_hint": "", "reason": "…", "reply": ""}]
    return c_main.run_intervention(deepcopy(payload["design"]), current_blocks_for_c(payload),
                                   differences_for_c(payload["difference"]), text_answers=["일부러 그렇게 놨어요"])


# 시나리오 1: Initial APPROVE → A Plan 1회
def test_s1_initial_approve_plans_once(fake_llm):
    b, calls, _ = backend()
    source = b.state["planning_request"]
    initial = c_main.create_initial_design(text="의자 만들어줘")
    assert initial["status"] == "OK" and initial["design"]["design_version"] == 1
    assert open_candidate(b, "initial", source, initial)
    assert plans(calls) == [] and b.state["approved_design"] is None and b.state["context"] is None
    review = displayed(b)
    approve = c_review(review, APPROVE_TEXT)
    assert approve["hri_result"] == "APPROVE"
    assert on_review(b, review, approve)
    assert len(plans(calls)) == 1 and plans(calls)[0]["design"] == initial["design"]
    assert run_planning_request(b, plans(calls)[0])
    assert b.state["context"]["design"] == initial["design"]
    assert not on_review(b, review, approve) and len(plans(calls)) == 1  # 중복 APPROVE


# 시나리오 2 + 항목 3·5·8: Initial MODIFY(2회) → 승인 후 A Plan 1회, 이전 후보 승인 거절
def test_s2_initial_modify_then_approve_plans_once(fake_llm):
    b, calls, _ = backend()
    initial = c_main.create_initial_design(text="의자 만들어줘")
    open_candidate(b, "initial", b.state["planning_request"], initial)
    fake_llm.reviews = [lc.review_reply("MODIFY", "조금 더 넓게", "patch"),
                        lc.review_reply("MODIFY", "등받이를 높게", "patch")]
    first = displayed(b)
    m1 = c_review(first, ["조금 더 넓게"])
    assert (m1["status"], m1["hri_result"]) == ("OK", "MODIFY") and m1["design"] != first["design"]
    assert on_review(b, first, m1)
    second = b.state["c_review"]
    assert second["phase"] == "PREVIEW" and second["request_id"] != first["request_id"]
    assert second["design"] == m1["design"] and second["design"]["design_version"] == 1
    assert second["design_metadata"] == m1["design_metadata"] and second["design_metadata"]["review"]["round"] == 1
    assert plans(calls) == []
    second = displayed(b)
    m2 = c_review(second, ["등받이를 높게"])  # D가 교체한 metadata를 넘겨 round가 이어진다
    assert m2["hri_result"] == "MODIFY" and m2["design_metadata"]["review"]["round"] == 2
    on_review(b, second, m2)
    third = displayed(b)
    assert third["design"]["design_version"] == 1 and len({first["request_id"], second["request_id"],
                                                           third["request_id"]}) == 3
    stale = c_review(first, APPROVE_TEXT)  # 첫 후보(A)에 대한 늦은 승인
    assert stale["hri_result"] == "APPROVE"
    assert not on_review(b, first, stale) and not on_review(b, second, stale)
    assert plans(calls) == [] and b.state["c_review"]["request_id"] == third["request_id"]
    assert on_review(b, third, c_review(third, APPROVE_TEXT))
    assert len(plans(calls)) == 1 and plans(calls)[0]["design"] == m2["design"]


# 시나리오 3: REVISE → Current 보존·v2·A Replan은 APPROVE 후 1회
def test_s3_revise_preview_then_approve_replans_once(fake_llm):
    b, calls, _ = backend()
    approved = approved_and_planned(b, calls)
    payload = wait_intent(b, approved)
    current = deepcopy(b.state["current"])
    response = revise(fake_llm, payload)
    assert (response["status"], response["hri_result"]) == ("OK", "REVISE")
    assert response["design"]["design_version"] == 2
    assert open_candidate(b, "revised", payload, response)
    assert len(plans(calls)) == 1  # Initial Plan만
    assert b.state["context"]["design"] == approved and b.state["current"] == current
    review = displayed(b)
    assert review["kind"] == "revised" and review["previous_design"] == approved
    approve = c_review(review, APPROVE_TEXT)
    assert approve["hri_result"] == "APPROVE" and approve["design"] == response["design"]
    assert on_review(b, review, approve)
    replans = plans(calls)[1:]
    assert len(replans) == 1 and replans[0]["design"] == response["design"]
    assert replans[0]["base_current_revision"] == current["current_revision"] == B_REVISION
    assert b.state["current"] == current
    assert b.state["workflow_status"] == "REPLANNING"
    assert not on_review(b, review, approve) and len(plans(calls)) == 2


# 시나리오 4: Revised MODIFY → v2 유지·round 증가, 승인 후 Replan 1회
def test_s4_revised_modify_keeps_v2_and_round_increases(fake_llm):
    b, calls, _ = backend()
    approved = approved_and_planned(b, calls)
    payload = wait_intent(b, approved)
    response = revise(fake_llm, payload)
    open_candidate(b, "revised", payload, response)
    fake_llm.reviews = [lc.review_reply("MODIFY", "조금 더 넓게", "patch")]
    first = displayed(b)
    modify = c_review(first, ["조금 더 넓게"])
    assert (modify["status"], modify["hri_result"]) == ("OK", "MODIFY") and modify["design"] != first["design"]
    assert on_review(b, first, modify)
    review = b.state["c_review"]
    assert review["design"]["design_version"] == 2 and review["design_metadata"]["review"]["round"] == 1
    assert review["request_id"] != first["request_id"] and len(plans(calls)) == 1
    assert b.state["context"]["design"] == approved and b.state["current"]["current_revision"] == B_REVISION
    second = displayed(b)
    assert not on_review(b, first, c_review(first, APPROVE_TEXT))  # 후보 A 승인 거절
    assert on_review(b, second, c_review(second, APPROVE_TEXT))
    assert len(plans(calls)) == 2 and plans(calls)[1]["design"] == modify["design"]


# 시나리오 6: Current revision 변경 시 이전 결과(생성·검토·REVISE·승인) 채택 금지
def test_s6_current_revision_change_rejects_previous_results(fake_llm):
    b, calls, _ = backend()
    source = b.state["planning_request"]
    initial = c_main.create_initial_design(text="의자 만들어줘")
    b._state["current"]["current_revision"] += 1
    assert not open_candidate(b, "initial", source, initial) and b.state["c_review"] is None
    b, calls, _ = backend()
    open_candidate(b, "initial", b.state["planning_request"], initial)
    review = displayed(b)
    approve = c_review(review, APPROVE_TEXT)
    b._state["current"]["current_revision"] += 1
    assert not valid_review(b, review) and not on_review(b, review, approve) and plans(calls) == []
    b, calls, _ = backend()
    approved = approved_and_planned(b, calls)
    payload = wait_intent(b, approved)
    response = revise(fake_llm, payload)
    b._state["current"]["current_revision"] += 1
    assert not open_candidate(b, "revised", payload, response) and b.state["c_review"] is None
    b._state["current"]["current_revision"] -= 1
    open_candidate(b, "revised", payload, response)
    review = displayed(b)
    approve = c_review(review, APPROVE_TEXT)
    b._state["current"]["current_revision"] += 1
    assert not on_review(b, review, approve) and len(plans(calls)) == 1


# 항목 6: 실제 C 실패 envelope은 Candidate로 채택되지 않는다
def test_c_failure_envelopes_are_not_adopted(fake_llm):
    b, calls, _ = backend()
    failed = c_main.create_initial_design(text="자동차 만들어줘")
    assert failed["status"] == "FAILED" and failed["error"]["code"] == "UNSUPPORTED_OBJECT"
    assert open_candidate(b, "initial", b.state["planning_request"], failed)
    assert b.state["workflow_status"] == "HOLD" and b.state["c_review"] is None and plans(calls) == []
    b, calls, _ = backend()
    approved = approved_and_planned(b, calls)
    payload = wait_intent(b, approved)
    open_candidate(b, "revised", payload, revise(fake_llm, payload))
    review = displayed(b)
    invalid = c_main.review_design_candidate(deepcopy(review["design"]), kind="revised",
                                             design_metadata=review["design_metadata"], text_answers=APPROVE_TEXT)
    assert invalid["status"] == "FAILED" and invalid["error"]["code"] == "INVALID_INPUT"
    assert on_review(b, review, invalid)
    assert b.state["workflow_status"] == "HOLD" and b.state["approved_design"] == approved and len(plans(calls)) == 1
    b, calls, _ = backend()
    open_candidate(b, "initial", b.state["planning_request"], c_main.create_initial_design(text="의자 만들어줘"))
    review = displayed(b)
    cancel = c_review(review, ["취소할게요"])
    assert (cancel["status"], cancel["hri_result"]) == ("CANCELLED", "CANCEL")
    assert on_review(b, review, cancel)
    assert b.state["workflow_status"] == "HOLD" and plans(calls) == []


def _wait(connection):
    for _ in range(500):
        QTest.qWait(2)
        if not connection.active:
            return
    raise AssertionError("C call did not end")


# 시나리오 7: STOP 뒤 늦은 C response(Initial 생성·Review APPROVE)로 Plan/Pick 없음
def test_s7_stop_then_late_c_responses_make_no_plan_or_pick(monkeypatch, fake_llm):
    app = QApplication.instance() or QApplication([])  # 참조를 유지해야 queued signal이 전달된다
    real_initial = c_main.create_initial_design
    for phase in ("initial", "review"):
        b, calls, driver = backend(robot=True)
        gate, seen = threading.Event(), {}
        connection = CTextConnection(b, lambda: connection.sync(), initial_text="의자 만들어줘")
        if phase == "initial":
            def slow_initial(**kwargs):
                gate.wait(5)
                seen["stop"] = kwargs["should_stop"]()
                return real_initial(text="의자 만들어줘")  # 취소를 무시하고 늦게 도착한 정상 response
            monkeypatch.setattr(c_main, "create_initial_design", slow_initial)
            connection.start("initial", b.state["planning_request"])
        else:
            open_candidate(b, "initial", b.state["planning_request"], real_initial(text="의자 만들어줘"))
            review = displayed(b)

            def slow_review(candidate, **kwargs):
                gate.wait(5)
                seen["stop"] = kwargs["should_stop"]()
                return dict(status="OK", hri_result="APPROVE", design=deepcopy(candidate),
                            design_metadata=kwargs["design_metadata"], questions=[], error=None)
            monkeypatch.setattr(c_main, "review_design_candidate", slow_review)
            connection.start("review", review, answers=APPROVE_TEXT)
        assert connection.active
        assert b.command(dict(command="STOP", job_id=b.state["job_id"]))["accepted"]
        connection.sync()  # publish 경계에서 D가 C 취소 Event를 켠다
        gate.set()
        _wait(connection)
        assert seen["stop"] is True
        assert plans(calls) == [] and b.state["approved_design"] is None
        assert not any(operation == "pick" for operation, _ in driver.calls)
        if phase == "initial":
            assert b.state["c_review"] is None
        connection.close()
    assert app is not None
