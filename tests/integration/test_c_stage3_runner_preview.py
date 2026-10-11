"""Stage 3 C-side Interactive Preview: fake D caller runner의 --show-preview 순서·state PNG (offline, offscreen).

C-side test visualization이며 D Preview integration이 아니다(fake PREVIEW_READY, Not D Production HMI). runner의 FakeDCaller와
Stage 2 Viewer(비차단 QLabel)·c_design_hmi_render(compose_v1/compose_v2)를 실제로 쓰고, LLM·listen·speak만 fake로 바꾼다.
확인: 새 Candidate마다 창 표시가 그 후보의 review 첫 TTS(질문)보다 먼저이고 표시와 질문 사이에 listen이 없음, PNG는 lifecycle
state 4개만(APPROVE는 저장·표시 없음), 마지막 APPROVE 생성 0회, 창을 닫아도 흐름이 계속되고 다음 표시 때 다시 뜸.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # QApplication 생성 전에(창은 화면에 뜨지 않음)

import pytest  # noqa: E402

from app.c_design import designer, dialogue, llm, voice  # noqa: E402
from test_c_stage3_lifecycle import FINAL_ANSWERS, REVIEW_QUESTION, FakeLLM, review_reply  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
import c_stage3_integration_smoke as runner  # noqa: E402

pytest.importorskip("PyQt5")

STATE_PNGS = ["01_initial_candidate.png", "02_initial_modified_candidate_r1.png", "03_revised_candidate.png",
              "04_revised_modified_candidate_r1.png"]


@pytest.fixture
def fake_llm(monkeypatch):
    """test_c_stage3_lifecycle의 FakeLLM을 그대로 쓴다(LLM 모드, 두 번째 생성마다 다른 후보)."""
    monkeypatch.setenv("C_DESIGN_USE_LLM", "1")
    monkeypatch.setattr(designer, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(designer, "RICHNESS_MIN_DELTA", 0)
    fake = FakeLLM()
    for name in ("interpret_initial_request", "interpret_review_answer", "interpret_intervention_answer",
                 "generate_initial_design", "generate_revised_design", "describe_initial_design", "judge_revised_design"):
        monkeypatch.setattr(llm, name, getattr(fake, name))
    monkeypatch.setattr(llm, "choose_initial_family", lambda preference, rng=None: "armchair")
    return fake


def _viewer(events, close_after_first=False):
    from PyQt5.QtWidgets import QApplication
    from c_voice_e2e_c_only import Viewer
    app = QApplication.instance() or QApplication([])
    viewer = Viewer()
    original = viewer.show

    def show(app_, image, title):
        original(app_, image, title)
        events.append(("show", title, viewer.label.isVisible()))
        if close_after_first and sum(1 for e in events if e[0] == "show") == 1:
            viewer.close()  # 사용자가 창을 닫은 경우: runner는 음성 흐름을 계속해야 한다
    viewer.show = show
    return app, viewer


def _install_voice(monkeypatch, events, answers):
    # install_fake_voice가 voice.listen·prewarm을 직접 바꾸므로, 테스트가 끝나면 monkeypatch가 원래 값으로 되돌리게 먼저 등록한다.
    monkeypatch.setattr(voice, "listen", voice.listen)
    monkeypatch.setattr(voice, "prewarm", voice.prewarm)
    monkeypatch.setattr(voice, "speak", lambda sentence: events.append(("speak", sentence)))
    feed = runner.AnswerFeed(answers)
    runner.install_fake_voice(feed)
    fake_listen = voice.listen
    monkeypatch.setattr(voice, "listen", lambda **kwargs: events.append(("listen",)) or fake_listen(**kwargs))
    return feed


def test_preview_is_drawn_before_each_review_question_and_saved_by_state(fake_llm, monkeypatch, tmp_path):
    events = []
    feed = _install_voice(monkeypatch, events, FINAL_ANSWERS)
    fake_llm.reviews = [review_reply("MODIFY", "등받이를 더 높게", "patch", reply="좋아요. 등받이를 높여 볼게요."),
                        review_reply("MODIFY", "더 화려하게", "patch", reply="좋아요. 더 화려하게 바꿔 볼게요.")]
    fake_llm.answers = [{"decision": "REVISE", "style_hint": "조금 더 넓게", "reason": "…", "reply": "알겠습니다."}]
    app, viewer = _viewer(events, close_after_first=True)
    caller = runner.FakeDCaller("fake-voice", feed, None, None, str(tmp_path), viewer=viewer, app=app)

    try:
        runner.run_scenario(caller, "full")
    finally:
        viewer.close()

    # lifecycle 결과(기존 동작 불변)
    assert [row["hri"] for row in caller.rows] == [None, "MODIFY", "APPROVE", "REVISE", "MODIFY", "APPROVE"]
    assert [row["design_version"] for row in caller.rows] == [1, 1, 1, 2, 2, 2]
    assert [row["current_preserved"] for row in caller.rows][3:] == [True, True, True]
    assert feed.remaining() == 0 and not caller.failed

    # PNG: lifecycle state 이름 4개만(APPROVE·UNCLEAR 등 후보가 그대로인 응답은 저장하지 않음)
    assert sorted(os.listdir(tmp_path)) == STATE_PNGS
    assert [preview["state"] for preview in caller.previews] == [
        "initial_candidate", "initial_modified_candidate_r1", "revised_candidate", "revised_modified_candidate_r1"]
    assert all("preview" not in row for row in caller.rows if row["hri"] == "APPROVE")

    # 창 제목과 순서: 새 후보 표시 → (listen 없이) 그 후보의 review 질문 TTS
    shows = [i for i, e in enumerate(events) if e[0] == "show"]
    questions = [i for i, e in enumerate(events) if e[0] == "speak" and e[1] in REVIEW_QUESTION.values()]
    assert all("C-side Test Preview" in events[i][1] and "Not D Production HMI" in events[i][1] for i in shows)
    # review 질문 4번(Initial 후보·수정 후보·Revised 후보·Revised 수정 후보를 각각 검토)마다 직전에 그 후보의 표시가 있다
    assert len(shows) == 4 and len(questions) == 4
    for show_index, question_index in zip(shows, questions):
        assert show_index < question_index
        assert not any(e[0] == "listen" for e in events[show_index:question_index])  # 표시 중에는 마이크를 열지 않음
    assert events[shows[1]][2] is True  # 첫 표시 뒤 창을 닫아도 다음 표시 때 다시 뜬다

    # 마지막 APPROVE는 생성 0회(Revised 생성은 run_intervention 1 + MODIFY 1)
    assert len(fake_llm.calls["revised"]) == 2 and len(fake_llm.calls["judge"]) == 2
    assert dialogue.REVIEW_QUESTIONS["revised"] == events[questions[-1]][1]


def test_show_preview_without_render_saves_nothing(fake_llm, monkeypatch, tmp_path):
    events = []
    feed = _install_voice(monkeypatch, events, FINAL_ANSWERS[:1])
    app, viewer = _viewer(events)
    caller = runner.FakeDCaller("fake-voice", feed, None, None, None, viewer=viewer, app=app)
    try:
        runner.run_scenario(caller, "initial")
    finally:
        viewer.close()
    assert [e[0] for e in events if e[0] == "show"] == ["show"]
    assert caller.previews[0]["state"] == "initial_candidate" and caller.previews[0]["png"] is None
    assert os.listdir(tmp_path) == []
