import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.assembly_sensor import normalize_sensor_snapshot
from app.assembly_sensor_readings import project_no_motion_readings
from scripts import assembly_sensor_bridge as bridge
from test_assembly_completion import ACTIVE, DATA


FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "interfaces/fixtures/assembly_sensor_readings.json").read_text())
PREFIX = "/dsr01/dsr_controller2/"


def project(*, live=False, feedback=None, camera=None, **changes):
    window = dict(clock_id="TEST_CLOCK", started_at=101.5, finished_at=101.6,
        request_utc="2026-10-07T05:39:31+00:00", response_utc="2026-10-07T05:39:32+00:00")
    inputs = dict(active=deepcopy(ACTIVE["motion_permitted"]), sequence=0, sample_window=window,
        service_prefix=PREFIX, force_ref=0, live=live)
    inputs.update(changes)
    return project_no_motion_readings(deepcopy(FIXTURE["feedback"]) if feedback is None else feedback,
        deepcopy(FIXTURE["camera"]) if camera is None else camera, **inputs)


def normalize(result):
    return normalize_sensor_snapshot(result["snapshot"], active=ACTIVE["motion_permitted"],
        now=101.6, max_age=2, last_sequence=None, last_stamp=None, clock_id="TEST_CLOCK")


def test_historical_reader_output_cannot_become_fresh_evidence_by_default():
    result = project()
    assert result["raw"] == dict(feedback=FIXTURE["feedback"], camera=FIXTURE["camera"])
    assert result["snapshot"]["metadata"]["valid"] is False
    normalized = normalize(result)
    assert not normalized["accepted"] and normalized["event"]["value"] is None


@pytest.mark.parametrize("ref", [0, 1])
def test_live_projection_selects_one_force_ref_without_combining_samples(ref):
    result = project(live=True, force_ref=ref)
    expected = next(r["response"]["tool_force"] for r in FIXTURE["feedback"]["service_reads"]
        if r["service"].endswith("get_tool_force") and r["request"]["ref"] == ref)
    assert result["snapshot"]["wrench"]["tool_force"] == expected
    assert result["snapshot"]["wrench"]["force_frame"] == "UNKNOWN"
    normalized = normalize(result)
    assert normalized["event"]["value"] is False
    assert normalized["diagnostic"]["gripper_width_mm"] == 62.1
    assert normalized["diagnostic"]["rgbd_metadata_usable"]


@pytest.mark.parametrize("query", ["system/get_robot_state","motion/check_motion","drl/get_drl_state","aux_control/get_current_velj","aux_control/get_tool_force"])
@pytest.mark.parametrize("case", ["missing", "failed", "ack_only"])
def test_missing_failed_or_ack_only_reads_do_not_use_old_payload(query, case):
    feedback = deepcopy(FIXTURE["feedback"])
    selected = [r for r in feedback["service_reads"] if r["service"] == PREFIX + query]
    if case == "missing": feedback["service_reads"] = [r for r in feedback["service_reads"] if r not in selected]
    for record in selected:
        if case == "failed": record.update(status="FAILED", response={**record["response"], "success":False})
        if case == "ack_only": record["response"] = {"success":True}
    result = project(live=True, feedback=feedback)
    group = "wrench" if query.endswith("get_tool_force") else "robot"
    assert not result["snapshot"][group]["success"]
    assert normalize(result)["diagnostic"]["execution_result"] is None


def test_wrong_namespace_and_duplicate_response_are_not_silently_selected():
    result = project(live=True, service_prefix="/other/dsr_controller2/")
    assert not result["snapshot"]["robot"]["success"] and not result["snapshot"]["wrench"]["success"]
    feedback = deepcopy(FIXTURE["feedback"])
    feedback["service_reads"].append(deepcopy(feedback["service_reads"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        project(live=True, feedback=feedback)


@pytest.mark.parametrize("case", ["mapping", "width", "commands", "bool_count"])
def test_unknown_register_mapping_missing_register_and_commands_are_rejected(case):
    feedback = deepcopy(FIXTURE["feedback"])
    if case == "mapping": feedback["gripper"]["registers"]["status"] = 269
    if case == "width": feedback["gripper"].pop("raw_width")
    if case == "commands": feedback["motion_commands_sent"] = 1
    if case == "bool_count": feedback["gripper_commands_sent"] = False
    with pytest.raises(ValueError): project(feedback=feedback)


def test_gripper_read_error_and_camera_unknown_unit_remain_unknown():
    feedback, camera = deepcopy(FIXTURE["feedback"]), deepcopy(FIXTURE["camera"])
    feedback["gripper"]["status"] = "UNREADABLE"
    camera["depth_unit"] = "sensor native units"
    result = project(live=True, feedback=feedback, camera=camera)
    assert normalize(result)["event"]["value"] is None
    assert result["snapshot"]["camera"]["depth_unit"] == "UNKNOWN"
    assert not normalize(result)["diagnostic"]["rgbd_metadata_usable"]


def test_camera_size_mismatch_and_fraction_do_not_create_geometry_or_zero_count():
    camera = deepcopy(FIXTURE["camera"])
    camera["depth_camera_info"]["width"] = 848
    camera["depth_zero_fraction"] = 1.0
    result = project(live=True, camera=camera)
    assert not result["snapshot"]["camera"]["success"]
    assert result["snapshot"]["camera"]["depth_zero_count"] is None
    assert all(value is None for value in result["snapshot"]["human_confirmation"].values())


@pytest.mark.parametrize("record", ["robot", "camera"])
def test_old_file_cannot_be_relabelled_live_when_receipt_is_outside_query_window(record):
    feedback, camera = deepcopy(FIXTURE["feedback"]), deepcopy(FIXTURE["camera"])
    if record == "robot": feedback["service_reads"][0]["request_utc"] = "2026-10-06T05:39:31+00:00"
    else: camera["received_utc"] = "2026-10-06T05:39:31+00:00"
    with pytest.raises(ValueError, match="outside acquisition window"):
        project(live=True,feedback=feedback,camera=camera)


def test_single_query_pipeline_uses_existing_reader_and_logs_backend_without_motion(tmp_path, monkeypatch):
    clock = iter((100, 100.1, 100.3, 100.3))
    monkeypatch.setattr(bridge.time, "monotonic", lambda: next(clock))
    events, calls = [], []
    backend, clock_id = bridge.diagnostic_backend(DATA, 2, record=events.append)
    def save(out, message):
        calls.append("save")
        return deepcopy(FIXTURE["camera"])
    utc = iter(("2026-10-07T05:39:31+00:00", "2026-10-07T05:39:32+00:00"))
    reader = SimpleNamespace(probe=lambda node,config: deepcopy(FIXTURE["feedback"]),
        receive_rgbd=lambda node: calls.append("receive"), save_rgbd=save,
        utc_now=lambda: next(utc),
        write_json=lambda path,value: path.write_text(json.dumps(value)))
    config = tmp_path / "config.json"
    config.write_text(json.dumps(dict(settings=dict(robot_id="dsr01"))))
    result = bridge.collect_once(backend, reader, None, config, tmp_path, clock_id, 0)
    assert result["status"] == "CONNECTED_READ_ONLY" and result["synthetic_geometry"]
    assert result["decision"]["decision"] == "SAFE_STOP" and not result["physical_completion_verified"]
    assert result["motion_commands_sent"] == result["gripper_commands_sent"] == 0
    assert calls == ["receive", "save"] and events[-1]["event"] == "SENSOR_SNAPSHOT_EVALUATED"
    assert (tmp_path / "projection.json").exists() and backend.assembly_state["completion"] is None


def test_camera_timeout_still_delivers_gripper_fault_without_claiming_complete_link(tmp_path, monkeypatch):
    clock = iter((100, 100.1, 100.3, 100.3))
    monkeypatch.setattr(bridge.time, "monotonic", lambda: next(clock))
    backend, clock_id = bridge.diagnostic_backend(DATA, 2)
    def timeout(node): raise TimeoutError("CAMERA_UNAVAILABLE")
    utc = iter(("2026-10-07T05:39:31+00:00", "2026-10-07T05:39:32+00:00"))
    reader = SimpleNamespace(probe=lambda node,config: deepcopy(FIXTURE["feedback"]), receive_rgbd=timeout,
        save_rgbd=lambda out,message: deepcopy(FIXTURE["camera"]),
        utc_now=lambda: next(utc), write_json=lambda path,value: path.write_text(json.dumps(value)))
    config = tmp_path / "config.json"; config.write_text(json.dumps(dict(settings=dict(robot_id="dsr01"))))
    result = bridge.collect_once(backend, reader, None, config, tmp_path, clock_id, 0)
    assert result["status"] == "PARTIAL_READS_OR_INPUT_REJECTED"
    assert result["decision"]["decision"] == "SAFE_STOP" and (tmp_path / "camera_error.json").exists()


def test_changed_reader_source_is_rejected_before_import_and_cli_defaults_to_no_io(tmp_path, capsys):
    reader = tmp_path / "reader.py"
    reader.write_text('raise RuntimeError("MUST_NOT_IMPORT")')
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        bridge.load_reader(reader, "wrong")
    assert bridge.main([]) == 0
    assert "--live-read" in capsys.readouterr().out


def test_bridge_code_has_no_motion_publisher_write_or_driver_binding():
    paths = (Path(bridge.__file__), Path(__file__).resolve().parents[2] / "app/assembly_sensor_readings.py")
    calls = {node.func.attr for path in paths for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
    assert not calls & {"create_publisher","publish","write_register","write_registers","send_goal_async",
        "movej","movel","move","stop","connect_robot"}


def test_wrong_domain_is_rejected_before_source_import_or_output_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", "99")
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as error:
        bridge.main(["--live-read","--reader","missing.py","--reader-sha256","wrong",
            "--config","missing.json","--fixture","missing.json","--out",str(out),
            "--expected-domain","20","--max-age","2"])
    assert error.value.code == 2 and not out.exists()


def test_existing_output_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", "20")
    marker = tmp_path / "original.txt"; marker.write_text("keep")
    with pytest.raises(FileExistsError):
        bridge.main(["--live-read","--reader","missing.py","--reader-sha256","wrong",
            "--config","missing.json","--fixture","missing.json","--out",str(tmp_path),
            "--expected-domain","20","--max-age","2"])
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("max_age", [0,-1,True,float("inf")])
def test_diagnostic_profile_requires_explicit_finite_age(max_age):
    with pytest.raises(ValueError): bridge.diagnostic_backend(DATA, max_age)
