"""Action 내부 측정 함수의 데이터/실패/취소 경계. 실제 모션 없음."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import threading
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.robot_adapter import StepResult, tool_axis_in_base
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece, fit_circle, facing_pose
from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter


@pytest.fixture
def setup():
    config=json.loads((Path(__file__).resolve().parents[1]/"config/workpiece_simulation.json").read_text())
    ctx=MeasurementContext("test-measurement","test-preparation","SIMULATION")
    ad=SimulatedWorkpieceAdapter(config["workcell"],clock=ctx.monotonic)
    return config,ctx,ad


def call(setup,feedback=None):
    config,ctx,ad=setup
    return measure_workpiece(ad,config["workcell"],config["profiles"],ctx,feedback)


def test_normal_flow_and_actual_fit(setup):
    config,ctx,ad=setup; before=deepcopy(config); events=[]
    result=call(setup,events.append)
    assert result.ok,result
    m=result.observed_state["measurement"]
    assert math.dist(m["axis_xy_m"],ad.center)<1e-10
    assert abs(m["radius_m"]-ad.radius)<1e-10
    assert abs(m["top_z_m"]-ad.top_z)<1e-10
    assert abs(m["bottom_z_m"]-(ad.top_z-.150))<1e-10
    assert m["work_v_range_m"]==pytest.approx([.010,.140])
    assert m["work_z_range_m"]==pytest.approx([ad.top_z-.140,ad.top_z-.010])
    assert m["source_mode"]=="SIMULATION" and m["validity"]=="SIMULATED"
    assert m["height_source"]=="OPERATOR_RULER"
    assert len(m["points"])==8 and result.observed_state["stop_confirmed"]
    assert [e["point_index"] for e in events if e["stage"]=="SIDE_TOUCH" and e["status"]=="SUCCEEDED"]==list(range(1,9))
    assert events[-1]["stage"]=="COMPLETE"
    assert [e["sequence"] for e in events]==list(range(1,len(events)+1))
    assert config==before
    assert ad.calls[-1][1]["label"]=="point_8_outer"
    assert len(result.observed_state["plans"])==2
    assert not any(c[0]=="stop" for c in ad.calls)
    json.dumps(result.observed_state,allow_nan=False)


def test_force_contact_not_operator_confirmation(setup):
    m=call(setup).observed_state["measurement"]
    assert all(p["operator_confirmed"] is False for p in m["points"])
    assert not m["independent_accuracy_verified"]


def test_circle_matches_recorded_eight_point_trial():
    trial=json.loads((Path(__file__).parent/"fixtures/workpiece_eight_points.json").read_text())
    fit=fit_circle(trial["points_m"])
    assert fit["axis_xy_m"]==pytest.approx(trial["expected_center_m"],abs=1e-9)
    assert fit["radius_m"]==pytest.approx(trial["expected_radius_m"],abs=1e-9)
    assert fit["residual_rms_m"]==pytest.approx(trial["expected_rms_m"],abs=1e-9)


@pytest.mark.parametrize("points", [[],[[0,0,0]]*8,[[i,0,0] for i in range(8)],[[0,0,0],[1,0,0],[0,float("nan"),0]]])
def test_circle_degenerate(points):
    with pytest.raises(ValueError):fit_circle(points)


@pytest.mark.parametrize("angle",range(-270,91,45))
def test_drill_faces_center(angle):
    p=facing_pose([.4,0],.04,.2,angle)
    axis=tool_axis_in_base(p,"-y")
    assert axis==pytest.approx([-math.cos(math.radians(angle)),-math.sin(math.radians(angle)),0.])
    assert tool_axis_in_base(p,"+z")==pytest.approx([0,0,-1])


@pytest.mark.parametrize("key,value",[("height_m",.03),("height_m",True),("seed_radius_m",float("nan")),("orbit_step_deg",45),("frame_id","map"),("source_mode","REAL"),("angles_deg",[0]*8)])
def test_bad_config_never_moves(setup,key,value):
    config,ctx,ad=setup;config["workcell"][key]=value
    r=call(setup)
    assert not r.ok and not ad.calls


def test_missing_bottom_offset_never_moves(setup):
    config,ctx,ad=setup;config["workcell"]["top"]["contact_offset_tool_m"]=None
    assert call(setup).error_code=="INVALID_INPUT"
    assert not ad.calls


def test_unported_adapter_fails_before_calls(setup):
    setup[2].measurement_contract_version=None
    assert call(setup).error_code=="UNSUPPORTED_ADAPTER"
    assert not setup[2].calls


def test_busy_does_not_release_other_owner(setup):
    config,ctx,ad=setup;ctx.motion_lock.acquire()
    try:
        r=call(setup);assert r.error_code=="BUSY" and not ad.calls
        assert ctx.motion_lock.locked()
    finally:ctx.motion_lock.release()


def test_cancel_before_motion(setup):
    setup[1].cancel.set();r=call(setup)
    assert r.outcome=="STOPPED" and not setup[2].calls


def test_cancel_after_point_keeps_partial_and_no_retract(setup):
    config,ctx,ad=setup
    def feedback(e):
        if e["stage"]=="SIDE_TOUCH" and e["status"]=="SUCCEEDED":ctx.cancel.set()
    r=call(setup,feedback)
    assert r.outcome=="STOPPED" and r.observed_state["stop_confirmed"]
    assert len(r.observed_state["measurement"]["points"])==1
    assert not r.observed_state["measurement"]["geometry_ready"]
    assert ad.calls[-1][0]=="stop"
    assert [c[1]["label"] for c in ad.calls if c[0]=="execute"][-1]=="point_1_touch"


@pytest.mark.parametrize("confirmed",[True,False])
def test_communication_loss_stops_without_next_motion(setup,confirmed):
    config,ctx,ad=setup
    def broken(*args):
        ad.calls.append(("sent_unknown",None));raise ConnectionError("link lost")
    ad.execute_measurement_step=broken
    ad.stop_measurement=lambda p:StepResult("SUCCEEDED" if confirmed else "UNKNOWN",observed_state={"stop_confirmed":confirmed})
    r=call(setup)
    assert r.outcome==("FAILED" if confirmed else "UNKNOWN")
    assert [c[0] for c in ad.calls].count("sent_unknown")==1
    assert r.observed_state["measurement"]["geometry_ready"] is False


def test_failed_preflight_no_motion(setup):
    setup[2].preflight_measurement=lambda *args:StepResult("FAILED","IK_FAILED","no IK")
    r=call(setup);assert r.error_code=="IK_FAILED" and not setup[2].calls


def test_unchecked_envelope_no_motion(setup):
    ad=setup[2];original=ad.preflight_measurement
    def wrong(*args):
        r=original(*args);r.observed_state["probe_envelopes_checked"]=False;return r
    ad.preflight_measurement=wrong
    assert call(setup).error_code=="NOT_READY"
    assert all(c[0]!="execute" for c in ad.calls)


def test_state_changed_during_preflight_no_motion(setup):
    ad=setup[2];original=ad.preflight_measurement
    def moved(*args):
        r=original(*args);ad.pose[0]+=.01;return r
    ad.preflight_measurement=moved
    assert call(setup).error_code=="NOT_READY"
    assert all(c[0]!="execute" for c in ad.calls)


def test_stale_state_no_motion(setup):
    ad=setup[2];original=ad.observe_measurement
    def stale():
        o=original();o["measured_at_monotonic_s"]-=10;return o
    ad.observe_measurement=stale
    assert call(setup).error_code=="STALE_DATA" and not ad.calls


def test_force_contact_outside_plan_is_not_green(setup):
    ad=setup[2];original=ad.execute_measurement_step;events=[]
    def wrong(*args):
        r=original(*args)
        if "contact" in r.observed_state:r.observed_state["contact"]["tip_pose"][0]+=.01
        return r
    ad.execute_measurement_step=wrong
    r=call(setup,events.append)
    assert r.error_code=="CONTACT_OUT_OF_RANGE"
    assert not any(e["status"]=="SUCCEEDED" for e in events)


def test_timeout_after_command_stop_required(setup):
    config,ctx,ad=setup;clock=[0.];ctx.monotonic=lambda:clock[0];ad.clock=ctx.monotonic
    original=ad.execute_measurement_step
    def timeout(*args):
        r=original(*args);clock[0]=400.;return r
    ad.execute_measurement_step=timeout
    r=call(setup);assert r.error_code=="TIMEOUT" and r.outcome=="FAILED"
    assert ad.calls[-1][0]=="stop"


def test_callback_failure_stops_and_keeps_events(setup):
    def feedback(e):
        if e["stage"]=="TOP_TOUCH" and e["status"]=="SUCCEEDED":raise RuntimeError("feedback disconnected")
    r=call(setup,feedback)
    assert not r.ok and r.observed_state["stop_confirmed"]
    assert r.observed_state["measurement"]["top"] is not None
    assert setup[2].calls[-1][0]=="stop"


def test_final_retract_failure_is_not_complete(setup):
    ad=setup[2];original=ad.execute_measurement_step;events=[]
    def fail(step,*args):
        if step["label"]=="point_8_outer":return StepResult("FAILED","MOTION_FAILED")
        return original(step,*args)
    ad.execute_measurement_step=fail
    r=call(setup,events.append)
    assert len(r.observed_state["measurement"]["points"])==8
    assert not r.ok and not r.observed_state["measurement"]["geometry_ready"]
    assert not any(e["stage"]=="COMPLETE" for e in events)


def test_surface_not_found_does_not_invent_contact(setup):
    setup[2].top_z=-1.
    r=call(setup)
    assert r.error_code=="CONTACT_NOT_FOUND" and r.observed_state["measurement"]["top"] is None
    assert setup[2].calls[-1][0]=="stop"


def test_contact_reference_does_not_invent_absolute_top(setup):
    c,ctx,ad=setup
    c['workcell']['measurement_scope']='CONTACT_REFERENCE'
    c['workcell']['top']['contact_offset_tool_m']=None
    r=call(setup)
    assert r.ok,r
    m=r.observed_state['measurement']
    assert len(m['points'])==8 and m['top_tcp_contact_z_m'] is not None
    assert m['top_z_m'] is None and m['bottom_z_m'] is None and m['work_z_range_m'] is None
    assert m['geometry_ready'] is False and m['validity']=='REFERENCE_ONLY'
