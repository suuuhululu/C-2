"""C 기하 검증 → 실제 A → D/Qt/합성 관측. 모든 장치·LLM은 미연결."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.abd_input_hmi import AbdInputDemo
from app.c_design import validator as c_validator
from app.contracts import validate_block, validate_observed
from app import contracts as d_contracts
from app.hmi_contracts import validate_hmi_snapshot
from app.qt_hmi import HmiWindow
from app.snapshot import make_snapshot
from planning_trial.planner import plan_from_current
from planning_trial import planner as a_planner
from test_a_backend import connected, finish_delivery, start_design
from test_abd_callback import B
from test_abd_input_hmi import records, wait_for

ROOT = Path(__file__).resolve().parents[2]


def test_producer_consumer_and_shared_schema_agree_on_layer_limit():
    schema = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    assert schema["$defs"]["layer"]["minimum"] == 1
    assert c_validator.MAX_LAYER == a_planner.MAX_LAYER == d_contracts.MAX_LAYER == schema["$defs"]["layer"]["maximum"] == 5


def tower(layers):
    return dict(design_version=1, blocks=[dict(brick_type="2x3x1", color="blue",
        x=21, y=22, layer=layer, orientation_deg=90) for layer in range(1, layers + 1)])


def thirty_blocks():
    # 인접층을 한 stud씩 엇갈려 C의 단일 연결 구조·지지 조건을 만족한다.
    return dict(design_version=1, blocks=[dict(brick_type="2x3x1", color="yellow",
        x=8 + col * 2 + (layer % 2), y=8 + row * 3 + (layer % 2),
        layer=layer, orientation_deg=0)
        for layer in range(1, 6) for row in range(2) for col in range(3)])


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("design", [tower(n) for n in range(1, 6)] + [thirty_blocks()])
def test_valid_c_a_d_qt_and_synthetic_observation_to_completion(qapp, tmp_path, design):
    before = deepcopy(design)
    assert not c_validator.validate_design(design)
    path = tmp_path / "initial.json"
    path.write_text(json.dumps(dict(status="OK", hri_result=None, design=design)))
    window = HmiWindow(screen_size=QSize(1920, 1080))
    demo = AbdInputDemo(window, tmp_path, initial_result=path, delay_ms=1)
    try:
        window.show()
        qapp.processEvents()
        window.buttons["START"].click()
        qapp.processEvents()
        count = len(design["blocks"])
        state = demo.backend.state
        assert state["supported_scope"]["max_layer"] == 5
        assert len(state["context"]["plan"]["steps"]) == count
        assert state["context"]["design"] == design and not demo.driver.calls
        assert window.design_board.blocks == design["blocks"]
        for index in range(count):
            demo.receive(dict(event="place_empty"))
            if demo.backend.state["reason"] == "NEEDS_REFILL":
                target = demo.backend._next_step()["after"]
                assert demo.backend.command(dict(command="SUPPLY_REFILLED",
                    job_id=demo.backend.state["job_id"], brick_type=target["brick_type"],
                    color=target["color"]))["accepted"]
                demo.receive(dict(event="place_empty"))
            wait_for(demo, "WAIT_ASSEMBLY")
            assert len(demo.backend.state["context"]["confirmed_steps"]) == index
            demo.receive(dict(event="observe"))
            snapshot = validate_hmi_snapshot(make_snapshot(demo.backend.state))
            assert snapshot["progress"]["completed"] == index + 1
        assert demo.backend.state["workflow_status"] == "COMPLETE"
        assert {frozenset(b.items()) for b in demo.backend.state["current"]["blocks"]} == {
            frozenset(b.items()) for b in design["blocks"]}
        assert demo.backend.state["current"]["current_revision"] == count
        assert sum(row["event"] == "JOB_COMPLETED" for row in records(demo)) == 1
        assert len(demo.driver.calls) == count * 3
        qapp.processEvents()
        assert window.status.text() == "전체 조립 완료"
        assert f"조립 확인 {count} / {count}" in window.progress.text()
        assert window.grab().save(str(tmp_path / f"complete-{count}.png"))
        assert design == before
    finally:
        window.close()


def test_partial_five_layer_replan_keeps_current_and_places_only_remaining(tmp_path):
    design = tower(5)
    current = dict(current_revision=4, blocks=deepcopy(design["blocks"][:4]))
    backend, driver, _ = connected(tmp_path, current=current)
    start_design(backend, dict(status="OK", hri_result=None, design=design))
    context = backend.state["context"]
    assert context["base_current"] == current and backend.state["current"] == current
    assert context["plan"]["base_current_revision"] == 4
    assert [step["after"] for step in context["plan"]["steps"]] == design["blocks"][4:]
    assert not driver.calls
    full = dict(current_revision=5, blocks=design["blocks"])
    assert plan_from_current(design, full)["plan"]["steps"] == []


def test_b_synthetic_callback_fifth_layer_preserves_hidden_layers_and_rejects_sixth(tmp_path):
    design = tower(5)
    current = dict(current_revision=4, blocks=deepcopy(design["blocks"][:4]))
    backend, driver, _ = connected(tmp_path, current=current)
    start_design(backend, dict(status="OK", hri_result=None, design=design))
    check_id = finish_delivery(backend, driver)
    before = backend.state
    observed = dict(check_id=check_id, observation_seq=0, status="OK",
        visible_blocks=deepcopy(design["blocks"][-1:]),
        verified_regions=[dict(x=21, y=22, width=3, height=2, layer=5)], reason=None)
    invalid = deepcopy(observed)
    invalid["visible_blocks"][0]["layer"] = 6
    invalid["verified_regions"][0]["layer"] = 6
    with pytest.raises(ValueError, match="layer"):
        B.deliver_example(dict(vision_result=invalid), backend.on_observation)
    assert backend.state == before
    source = deepcopy(observed)
    B.deliver_example(dict(vision_result=observed), backend.on_observation)
    assert observed == source
    assert backend.state["current"] == dict(current_revision=5, blocks=design["blocks"])
    assert backend.state["workflow_status"] == "COMPLETE"
    completed = backend.state
    B.deliver_example(dict(vision_result=observed), backend.on_observation)
    assert backend.state == completed


def test_six_layers_rejected_by_c_a_d_and_never_adopted(tmp_path):
    design = tower(6)
    assert c_validator.validate_design(design)
    result = plan_from_current(design, dict(current_revision=0, blocks=[]))
    assert result["status"] == "INVALID" and result["plan"] is None
    assert "1 to 5" in result["errors"][0]["reason"]
    with pytest.raises(ValueError, match="layer"):
        validate_block(design["blocks"][-1])
    observed = dict(check_id="invalid-six", observation_seq=0, status="OK", visible_blocks=[],
        verified_regions=[dict(x=0, y=0, width=24, height=24, layer=6)], reason=None)
    with pytest.raises(ValueError, match="layer"):
        validate_observed(observed)
    backend, driver, _ = connected(tmp_path)
    start_design(backend, dict(status="OK", hri_result=None, design=design))
    assert backend.state["workflow_status"] == "HOLD"
    assert backend.state["context"] is None and not driver.calls


def test_five_layer_support_and_footprint_are_still_checked():
    unsupported = tower(5)
    unsupported["blocks"][-1]["x"] = 18
    outside = tower(5)
    outside["blocks"][-1]["x"] = 22
    for design in (unsupported, outside):
        assert c_validator.validate_design(design)
        result = plan_from_current(design, dict(current_revision=0, blocks=[]))
        assert result["status"] == "INVALID" and result["plan"] is None


def test_shared_schema_five_layer_boundary():
    from jsonschema import Draft202012Validator, ValidationError
    from referencing import Registry, Resource
    schema = json.loads((ROOT / "interfaces/schemas/day4.schema.json").read_text())
    hmi = json.loads((ROOT / "interfaces/schemas/hmi.schema.json").read_text())
    registry = Registry().with_resource("https://c-2.invalid/schemas/day4.schema.json", Resource.from_contents(schema))
    consumer = Draft202012Validator(schema)
    design = tower(5)
    consumer.validate(design)
    result = plan_from_current(design, dict(current_revision=0, blocks=[]))
    consumer.validate(result)
    observed = dict(check_id="schema-five", observation_seq=0, status="OK",
        visible_blocks=design["blocks"][-1:],
        verified_regions=[dict(x=0, y=0, width=24, height=24, layer=5)], reason=None)
    consumer.validate(observed)
    validate_observed(observed)
    observed["verified_regions"][0]["layer"] = 6
    with pytest.raises(ValidationError):
        consumer.validate(observed)
    with pytest.raises(ValidationError):
        consumer.validate(tower(6))
    snapshot = json.loads((ROOT / "interfaces/fixtures/hmi.json").read_text())["snapshots"]["waiting"]
    snapshot["design"] = design
    snapshot["step"]["target"] = design["blocks"][-1]
    Draft202012Validator(hmi, registry=registry).validate(snapshot)
    snapshot["step"]["target"] = tower(6)["blocks"][-1]
    with pytest.raises(ValidationError):
        Draft202012Validator(hmi, registry=registry).validate(snapshot)


def test_manual_current_confirmation_covers_five_layers_without_device_calls(monkeypatch):
    from types import SimpleNamespace
    from app.real_workflow_hmi import WorkflowTrial

    received = []
    state = dict(current_check=dict(check_id="manual-five", last_observation_seq=None),
        stop_request=None, fault=None, execution_id=None)
    trial = object.__new__(WorkflowTrial)
    trial.backend = SimpleNamespace(state=state, _event=lambda *args, **kwargs: True,
        on_observation=lambda value: received.append(validate_observed(value)) or True)
    trial.controller = SimpleNamespace(state=dict(ready_at_observe=True))
    monkeypatch.setattr(trial, "publish", lambda: None)
    assert trial.receive_current(dict(event="current", check_id="manual-five", confirmed=True,
        blocks=tower(5)["blocks"]))
    assert [region["layer"] for region in received[0]["verified_regions"]] == [1, 2, 3, 4, 5]
    assert received[0]["visible_blocks"] == tower(5)["blocks"]
    with pytest.raises(ValueError, match="layer"):
        trial.receive_current(dict(event="current", check_id="manual-five", confirmed=True,
            blocks=tower(6)["blocks"]))
    assert len(received) == 1
