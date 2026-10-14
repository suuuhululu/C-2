"""Actual A calculators must match scoped D geometry without device execution."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import pytest

from scripts.check_a_d_onsite import DEFAULT_A, calculate, compare, make_profile

# Native app must keep precedence over the repository Backend app package.
# Add the selected A checkout without changing the native runner's search order.
sys.path.append(str(DEFAULT_A))
pytest.importorskip('planning_trial.assembly_adapter')
from planning_trial.assembly_adapter import handle_step_motion
from planning_trial.assembly_target import calculate_step_tcp, profile_fingerprint
from planning_trial.supply_pick import calculate_supply_pick

ROOT=Path(__file__).resolve().parents[2]
PROFILES=[
    'onsite_blue_slot1_6_6_l2_20261011/approach-0969295c-ebe4-4b17-ac29-14eee0a89028.profile.json',
    'onsite_blue_slot1_6_6_l3_20261011/handover-fallback-44244972-4703-497e-a23d-5acf46f0456e.assembly.profile.json',
    'onsite_blue_slot1_11_11_l2_20261011/auto-blend-1fec868f-e364-408b-8cea-fd897635b65c.smooth040.assembly.profile.json',
]


def document(index=2):
    raw=(ROOT/'settings'/PROFILES[index]).read_bytes()
    return json.loads(raw),sha256(raw).hexdigest()


@pytest.mark.parametrize('index',range(3))
def test_actual_A_matches_all_loaded_empty_points_and_keeps_execution_false(index):
    doc,digest=document(index); before=deepcopy(doc)
    bundle=calculate(doc,digest); report=compare(doc,bundle)
    assert doc==before and report['status']=='A_D_ONSITE_OFFLINE_MATCH'
    assert len(report['positions'])==13 and all(r['passed'] for r in report['positions'])
    assert report['empty_route_matches'] and report['loaded_route_matches']
    for key in ('whole_result','reassessment_result','motion_result'):
        assert not bundle[key]['execution_allowed']
    assert not bundle['motion_result']['motion_proposal']['assembly_completed']
    assert report['robot_motion_commands']==report['robot_gripper_commands']==report['device_connections']==0


@pytest.mark.parametrize('slot,color',[(2,'blue'),(1,'yellow')])
def test_taught_blue_first_slot_does_not_shift_other_slots(slot,color):
    doc,digest=document(); p=make_profile(doc,digest)['calculation_profiles']['supply']
    with pytest.raises(ValueError,match='does not cover'):
        calculate_supply_pick('2x2x1',color,slot,profile=p)
    pick=calculate_supply_pick('2x2x1','blue',1,profile=p)
    assert pick['pickup_tcp_pose']['xyz_abc']==p['d_taught_slot']['tcp_mm_zyz_deg']
    assert pick['grasp']['tcp_z_shift_from_taught_mm']==0 and not pick['grasp']['derived_not_remeasured']


@pytest.mark.parametrize('field,value',[('x',12),('layer',3),('orientation_deg',90),('color','yellow')])
def test_step_scoped_reference_cannot_be_reused_at_another_target(field,value):
    doc,digest=document(); bundle=calculate(doc,digest)
    step=deepcopy(bundle['motion_request']['selected_step']); step['after'][field]=value
    message='orientation_deg must be' if field=='orientation_deg' else 'does not cover'
    with pytest.raises(ValueError,match=message):
        calculate_step_tcp(step,profile=bundle['frame_profile']['calculation_profiles']['assembly'])


def test_profile_change_after_assessment_is_rejected_by_actual_A_digest_binding():
    doc,digest=document(); bundle=calculate(doc,digest); req=deepcopy(bundle['motion_request'])
    req['frame_profile']['calculation_profiles']['assembly']['d_onsite_step']['reference_pose'][0]+=1
    result=handle_step_motion(req)
    assert result['status']=='BLOCKED' and result['motion_proposal'] is None
    assert result['errors']


def test_empty_route_comparison_detects_coordinate_error_not_only_labels():
    doc,digest=document(); bundle=calculate(doc,digest)
    bundle['motion_result']['motion_proposal']['segments'][0]['waypoints'][3]['tcp_pose']['xyz_m'][0]+=.01
    assert compare(doc,bundle)['status']=='MISMATCH'


@pytest.mark.parametrize('field,value',[('clearance_z_mm',float('nan')),('source_sha256','x'*64),('turn_base_z_deg',45)])
def test_malformed_onsite_geometry_produces_no_motion_candidate(field,value):
    doc,digest=document(); p=make_profile(doc,digest)
    p['calculation_profiles']['assembly']['d_onsite_step'][field]=value
    from planning_trial.assembly_api_fixtures import whole_request, reassess_request, motion_request
    from planning_trial.assembly_adapter import handle_whole_plan, handle_step_reassessment
    b=doc['step']['block']; support=dict(b,layer=1)
    req=whole_request(dict(design_version=1,blocks=[support,b]),dict(current_revision=1,blocks=[support]),profile=p)
    # Non-finite values may be rejected at the outer schema boundary first.
    whole=handle_whole_plan(req)
    if whole['planning_result'] is None:
        assert whole['stage_errors']; return
    re_req=reassess_request(req,whole); assessed=handle_step_reassessment(re_req)
    result=handle_step_motion(motion_request(re_req,assessed,profile=p))
    assert result['status']=='BLOCKED' and result['motion_proposal'] is None


def test_onsite_reference_and_route_are_in_the_calibration_fingerprint():
    doc,digest=document(); p=make_profile(doc,digest)['calculation_profiles']['assembly']
    old=profile_fingerprint(p); p['d_onsite_step']['loaded_transit'][1]['xy_mm'][0]+=1
    assert profile_fingerprint(p)!=old


def test_default_A_keeps_calculator_and_fixture_in_the_same_checkout():
    from planning_trial import assembly_adapter, assembly_api_fixtures
    assert Path(assembly_adapter.__file__).resolve().parents[1]==DEFAULT_A.resolve()
    assert Path(assembly_api_fixtures.__file__).resolve().parents[1]==DEFAULT_A.resolve()
    if (ROOT.parent/'planning_trial').is_dir():
        assert DEFAULT_A.resolve()==ROOT.parent.resolve()


def test_invalid_A_whole_result_reports_stage_reason_instead_of_none_subscript(monkeypatch):
    from planning_trial import assembly_adapter
    monkeypatch.setattr(assembly_adapter,'handle_whole_plan',lambda request:dict(
        planning_result=None,calculation_status='INVALID_CONTEXT',
        stage_errors=[dict(code='INVALID_INPUT',reason='Draft schema mismatch: False was expected',block=None)]))
    doc,digest=document()
    with pytest.raises(ValueError,match='A WholePlan not READY:.*Draft schema mismatch: False was expected'):
        calculate(doc,digest)


def test_current_A_supports_quarter_turn_in_scoped_geometry():
    doc,digest=document();p=make_profile(doc,digest)['calculation_profiles']['assembly']
    from planning_trial.assembly_target import onsite_step_geometry
    p['d_onsite_step']['turn_base_z_deg']=90
    scoped=onsite_step_geometry(p,doc['step']['block'],'x')
    assert scoped['turn_base_z_deg']==90
    result=calculate_step_tcp(dict(after=doc['step']['block'],step_id='S01',operation='PLACE',
                                   before=None,prerequisites=[],requires_delivery=True),profile=p,grip_axis='x')
    assert result['status']=='COORDINATE_CANDIDATE'
    expected=p['d_onsite_step']['pickup_pose'][3:].copy();expected[0]+=90
    assert result['nominal_seated_tcp']['xyz_mm_zyz_deg'][3:]==expected


@pytest.mark.parametrize('index',range(3))
def test_current_A_empty_and_loaded_waypoints_match_actual_native_runner(index):
    from types import SimpleNamespace
    from app.assembly_step_bridge import build_plan
    from app.assembly_step_runner import StepReplayDriver,run_step
    from planning_trial.assembly_wire import pose_mm_zyz
    doc,digest=document(index);bundle=calculate(doc,digest)
    profile=deepcopy(doc['d_profile'])
    # The first historical document leaves gripper widths unmeasured. Use the
    # explicit existing future D policy for this MOCK route replay, without
    # changing source geometry or claiming measured gripper/physical behavior.
    policy=compare(doc,bundle)['future_D_operating_policy']
    settings=next(iter(profile['steps'].values()))
    settings.update(pickup_width_mm=policy['pickup_close_width_mm'],
                    release_width_mm=policy['assembly_release_width_mm'],
                    release_feedback_range_mm=[47.,110.])
    plan=build_plan(doc['step'],profile)
    raw=StepReplayDriver(plan['settings']['reference_pose'])
    initial=bundle['motion_request']['robot_state']['tcp_pose']
    observe=plan['settings'].get('handover_trial',{}).get('observe_pose',[400.851,8.573,314.981,175.022,-179.595,175.461])
    raw.value['posx']=observe.copy()
    events=[];timer=SimpleNamespace(now=0.)
    def sleep(duration):timer.now+=duration
    def record(event,data):events.append((event,deepcopy(data)))
    connection=dict(tcp=raw.value['tcp'],tool=raw.value['tool'])
    def targets():
        values=[]
        for event,data in events:
            if event=='STEP_MOVE':values.extend(data.get('targets',[data.get('target')]))
        # Zero-turn endpoints may repeat the same commanded pose.
        result=[]
        for value in values:
            wire=pose_mm_zyz(value)
            if not result or wire!=result[-1]:result.append(wire)
        return result
    def assert_wire_match(native,proposed):
        assert len(native)==len(proposed)
        for pose,waypoint in zip(native,proposed):
            assert pose['xyz_m']==pytest.approx(waypoint['tcp_pose']['xyz_m'],abs=1e-10)
            dot=abs(sum(a*b for a,b in zip(pose['quaternion_xyzw'],waypoint['tcp_pose']['quaternion_xyzw'])))
            assert dot==pytest.approx(1.,abs=1e-10)
    assert initial['xyz_m']==pytest.approx([v/1000 for v in observe[:3]])
    result=run_step(raw,connection,plan,profile,lambda *_:True,record,phase='pickup',start_zone='assembly',clock=lambda:timer.now,sleep=sleep)
    assert result['status']=='PAUSED_PICKUP_COMPLETE_HOLDING'
    assert_wire_match(targets(),bundle['motion_result']['motion_proposal']['segments'][0]['waypoints'])
    events.clear()
    result=run_step(raw,connection,plan,profile,lambda *_:True,record,phase='approach',start_zone='supply',clock=lambda:timer.now,sleep=sleep)
    assert result['status']=='PAUSED_APPROACH_REACHED'
    assert_wire_match(targets(),bundle['motion_result']['motion_proposal']['segments'][2]['waypoints'])
