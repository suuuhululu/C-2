from copy import deepcopy

import pytest

from app.snapshot import make_snapshot
from test_backend import FIXTURES, A, RA, B, RB, C, RC, delivering, observation, robot_success, stop_confirmed


def mismatch():
    backend,ports = delivering()
    robot_success(backend)
    backend.on_observation(observation(backend,[{**A,"color":"blue"}],[RA]))
    return backend,ports


def intent(backend,decision,**fields):
    return backend.on_intent(dict(request_id=backend.state["question_request"]["request_id"],
                                 decision=decision,**fields))


def revised(backend):
    design=deepcopy(backend.state["context"]["design"])
    design["design_version"]+=1
    design["blocks"][0]["color"]="blue"
    return design


def remaining(backend,blocks=None):
    request=backend.state["planning_request"]
    plan=deepcopy(FIXTURES["remaining_plan"])
    plan.update(plan_id="new-plan",design_version=request["design_version"],
                base_current_revision=request["base_current_revision"])
    if blocks is not None:
        plan["steps"]=[]
    return dict(status="READY",plan=plan,errors=[])


def current_observation(backend,blocks,regions,seq=0):
    return dict(check_id=backend.state["current_check"]["check_id"],observation_seq=seq,status="OK",
                visible_blocks=blocks,verified_regions=regions,reason=None)


def test_keep_requests_original_goal_latest_actual_and_needs_correction_without_retry():
    backend,ports=mismatch()
    actual=backend.state["current"]
    assert intent(backend,"KEEP")
    request=ports.calls("planner")[-1]
    assert request["design"]==FIXTURES["design"] and request["current"]==actual
    assert request["base_current_revision"]==1 and len(ports.calls("planner"))==2
    assert request["supported_scope"]==dict(operations=["PLACE"],brick_types=["1x2x1","2x2x1","2x3x1"],
        colors=["red","yellow","blue"],max_blocks=40,board_width=24,board_height=24,max_layer=5)
    assert ports.calls("hri")[-1]["supported_scope"]==request["supported_scope"]
    assert backend.on_plan_result(request["request_id"],dict(status="NEEDS_CORRECTION",plan=None,errors=[dict(reason="정리 필요",block=block) for block in actual["blocks"]]))
    snapshot=make_snapshot(backend.state)
    assert snapshot["workflow_status"]=="WAIT_CORRECTION"
    assert snapshot["actions"]["correction_continue"]["enabled"]
    assert backend.state["current"]==actual and len(ports.calls("robot.deliver"))==1
    assert not backend.on_plan_result(request["request_id"],dict(status="READY",plan=FIXTURES["completed_plan"],errors=[]))
    assert len(ports.calls("planner"))==2


def test_correction_command_only_reobserves_then_requests_latest_baseline():
    backend,ports=mismatch();intent(backend,"KEEP")
    request=backend.state["planning_request"]["request_id"]
    backend.on_plan_result(request,dict(status="NEEDS_CORRECTION",plan=None,errors=[dict(reason="정리 필요",block=block) for block in backend.state["current"]["blocks"]]))
    actual=backend.state["current"]
    command=dict(command="CONTINUE_AFTER_CORRECTION",job_id=backend.state["job_id"],
                 request_id=backend.state["correction_request"]["request_id"])
    assert backend.command(command)["accepted"]
    assert backend.state["current"]==actual and len(ports.calls("planner"))==2
    assert not backend.command(command)["accepted"]
    assert backend.on_observation(current_observation(backend,[],[RA]))
    assert backend.state["current"]==dict(current_revision=2,blocks=[])
    assert len(ports.calls("planner"))==3
    assert ports.calls("planner")[-1]["base_current_revision"]==2


@pytest.mark.parametrize("status",["UNCHANGED","UNOBSERVABLE"])
def test_failed_or_unobservable_cleanup_does_not_reissue_same_plan(status):
    backend,ports=mismatch();intent(backend,"KEEP")
    backend.on_plan_result(backend.state["planning_request"]["request_id"],dict(status="NEEDS_CORRECTION",plan=None,errors=[dict(reason="정리 필요",block=block) for block in backend.state["current"]["blocks"]]))
    backend.command(dict(command="CONTINUE_AFTER_CORRECTION",job_id=backend.state["job_id"],
                         request_id=backend.state["correction_request"]["request_id"]))
    value=current_observation(backend,backend.state["current"]["blocks"],[RA])
    if status=="UNOBSERVABLE":
        value.update(status=status,visible_blocks=[],verified_regions=[],reason="hand")
    backend.on_observation(value)
    assert len(ports.calls("planner"))==2 and len(ports.calls("robot.deliver"))==1
    assert backend.state["workflow_status"]==("HOLD" if status=="UNOBSERVABLE" else "WAIT_CORRECTION")
    assert backend.state["current"]["current_revision"]==1


def test_revise_candidate_preview_waits_for_plan_and_is_adopted_atomically():
    backend,ports=mismatch();design=revised(backend)
    intent(backend,"REVISE",design=design)
    assert make_snapshot(backend.state)["design"]==FIXTURES["design"]
    assert backend.state["workflow_status"]=="REPLANNING"
    request=backend.state["planning_request"]["request_id"]
    assert backend.on_plan_result(request,remaining(backend))
    assert make_snapshot(backend.state)["design"]==design
    assert backend.state["context"]["base_current"]["blocks"]==[{**A,"color":"blue"}]
    assert backend.state["workflow_status"]=="HOLD"
    assert len(ports.calls("robot.deliver"))==1
    assert backend.on_place(backend.state["place_check"]["check_id"],0,"EMPTY")
    assert len(ports.calls("robot.deliver"))==2


def test_current_changes_during_replan_cancel_old_result_and_refresh_once():
    backend,ports=mismatch();intent(backend,"REVISE",design=revised(backend))
    old=backend.state["planning_request"]["request_id"]
    old_result=remaining(backend)
    payload=current_observation(backend,[{**A,"color":"blue"},B],[RA,RB])
    assert backend.on_observation(payload)
    assert backend.state["current"]["current_revision"]==2
    assert backend.state["planning_request"]["request_id"]!=old
    assert len(ports.calls("planner"))==3
    assert not backend.on_plan_result(old,old_result)
    assert not backend.on_observation(payload)
    assert len(ports.calls("planner"))==3
    assert make_snapshot(backend.state)["design"]["design_version"]==1


def test_current_change_during_question_cancels_answer_and_updates_difference_context():
    backend,ports=mismatch()
    old=backend.state["question_request"]["request_id"]
    backend.on_observation(current_observation(backend,[{**A,"color":"blue"},B],[RA,RB]))
    assert len(ports.calls("hri"))==2
    assert not backend.on_intent(dict(request_id=old,decision="KEEP"))
    assert ports.calls("hri")[-1]["current_revision"]==2
    assert B in ports.calls("hri")[-1]["difference"]["unexpected"]


def test_unclear_waits_for_explicit_choice_without_automatic_calls_or_keep():
    backend,ports=mismatch()
    request=backend.state["question_request"]["request_id"]
    choose=dict(command="CHOOSE_INTENT",job_id=backend.state["job_id"],request_id=request,choice="KEEP")
    assert not backend.command(choose)["accepted"]
    intent(backend,"UNCLEAR",question="유지하려면 정리해야 합니다. 어느 쪽인가요?")
    assert not make_snapshot(backend.state)["actions"]["intent_choice"]["visible"]
    intent(backend,"UNCLEAR",question="목표 유지 또는 수정 중 선택하세요.")
    assert make_snapshot(backend.state)["actions"]["intent_choice"]["visible"]
    assert len(ports.calls("hri"))==1 and len(ports.calls("planner"))==1
    assert not backend.command(choose)["accepted"]
    choose["request_id"]=backend.state["question_request"]["request_id"]
    assert backend.command(choose)["accepted"]
    assert backend.state["workflow_status"]=="REPLANNING"
    assert not backend.command(choose)["accepted"] and len(ports.calls("planner"))==2


def test_explicit_revise_selection_requests_full_design_from_c_with_fresh_id():
    backend,ports=mismatch()
    for _ in range(2):intent(backend,"UNCLEAR",question="어느 쪽인가요?")
    old=backend.state["question_request"]["request_id"]
    assert backend.command(dict(command="CHOOSE_INTENT",job_id=backend.state["job_id"],
                                request_id=old,choice="REVISE"))["accepted"]
    assert ports.calls("hri")[-1]["choice"]=="REVISE"
    assert backend.state["question_request"]["request_id"]!=old
    assert not backend.on_intent(dict(request_id=old,decision="KEEP"))
    assert make_snapshot(backend.state)["design"]["design_version"]==1


@pytest.mark.parametrize("change",["version","partial","unsupported","bad_decision"])
def test_invalid_hri_is_failure_not_unclear_or_goal_adoption(change):
    backend,ports=mismatch();design=revised(backend)
    value=dict(request_id=backend.state["question_request"]["request_id"],decision="REVISE",design=design)
    if change=="version":design["design_version"]=1
    elif change=="partial":design.pop("blocks")
    elif change=="unsupported":design["blocks"][0]["layer"]=6
    else:value["decision"]="ERROR"
    assert backend.on_intent(value)
    assert backend.state["workflow_status"]=="HOLD" and "HRI_INVALID" in backend.state["reason"]
    assert make_snapshot(backend.state)["design"]["design_version"]==1
    assert len(ports.calls("planner"))==1


@pytest.mark.parametrize("status",["INVALID","BROKEN","READY_WITHOUT_PLAN"])
def test_invalid_planner_output_does_not_change_adopted_goal(status):
    backend,ports=mismatch();intent(backend,"REVISE",design=revised(backend))
    value=dict(status="READY",errors=[]) if status=="READY_WITHOUT_PLAN" else dict(
        status=status,plan=None,errors=[dict(reason="unsupported",block=None)])
    assert backend.on_plan_result(backend.state["planning_request"]["request_id"],value)
    assert backend.state["workflow_status"]=="HOLD"
    assert make_snapshot(backend.state)["design"]["design_version"]==1
    assert len(ports.calls("robot.deliver"))==1


def test_empty_remaining_cannot_finish_whole_design_mismatch():
    backend,ports=mismatch();intent(backend,"REVISE",design=revised(backend))
    backend.on_plan_result(backend.state["planning_request"]["request_id"],remaining(backend,blocks=[]))
    assert backend.state["workflow_status"]=="WAIT_INTENT"
    assert backend.state["current"]["blocks"]==[{**A,"color":"blue"}]
    assert len(ports.calls("robot.deliver"))==1


@pytest.mark.parametrize("port",["hri","planner","vision"])
def test_async_call_failure_holds_with_reason_and_no_retry(port):
    backend,ports=mismatch()
    if port=="planner":intent(backend,"KEEP")
    request=backend.state["planning_request" if port=="planner" else "question_request" if port=="hri" else "current_check"]
    request_id=request.get("request_id",request.get("check_id"))
    count=len(ports.requests)
    assert backend.on_failure(port,request_id,"timeout fixture")
    assert backend.state["workflow_status"]=="HOLD"
    assert "timeout fixture" in backend.state["reason"] and len(ports.requests)==count
    assert not backend.on_failure(port,request_id,"late timeout")


def test_stop_closes_replan_and_resume_revalidates_candidate_with_fresh_request():
    backend,ports=mismatch();design=revised(backend);intent(backend,"REVISE",design=design)
    old=backend.state["planning_request"]["request_id"];result=remaining(backend)
    stop_confirmed(backend)
    assert not backend.on_plan_result(old,result)
    backend.command(dict(command="RESUME",job_id=backend.state["job_id"]))
    assert backend.state["planning_request"] is None
    robot_success(backend)
    assert backend.state["planning_request"]["request_id"]!=old
    assert ports.calls("planner")[-1]["design"]==design
    assert len(ports.calls("robot.deliver"))==1


def test_stop_and_resume_correction_wait_does_not_repeat_failed_planner():
    backend,ports=mismatch();intent(backend,"KEEP")
    backend.on_plan_result(backend.state["planning_request"]["request_id"],dict(status="NEEDS_CORRECTION",plan=None,errors=[dict(reason="정리 필요",block=block) for block in backend.state["current"]["blocks"]]))
    old=backend.state["correction_request"]["request_id"]
    stop_confirmed(backend)
    backend.command(dict(command="RESUME",job_id=backend.state["job_id"]))
    robot_success(backend)
    assert backend.state["workflow_status"]=="WAIT_CORRECTION"
    assert backend.state["correction_request"]["request_id"]!=old
    assert len(ports.calls("planner"))==2


def test_same_layout_revise_reordered_blocks_keeps_version():
    backend,ports=mismatch();design=deepcopy(FIXTURES["design"])
    design["blocks"].reverse()
    assert intent(backend,"REVISE",design=design)
    assert backend.state["workflow_status"]=="REPLANNING"
    assert ports.calls("planner")[-1]["design_version"]==1


def test_ready_plan_wrong_version_or_baseline_cannot_adopt_candidate():
    for field in ("design_version","base_current_revision"):
        backend,ports=mismatch();intent(backend,"REVISE",design=revised(backend))
        result=remaining(backend);result["plan"][field]+=1
        assert backend.on_plan_result(backend.state["planning_request"]["request_id"],result)
        assert backend.state["workflow_status"]=="HOLD"
        assert make_snapshot(backend.state)["design"]["design_version"]==1
        assert len(ports.calls("robot.deliver"))==1


def test_same_version_different_goal_cannot_replace_pending_candidate():
    backend,ports=mismatch();intent(backend,"REVISE",design=revised(backend))
    request=backend.state["planning_request"]["request_id"]
    design=revised(backend);design["blocks"][1]["color"]="blue"
    assert backend.on_plan(request,design,remaining(backend)["plan"])
    assert "pending candidate" in backend.state["reason"]
    assert make_snapshot(backend.state)["design"]["design_version"]==1


def test_unobservable_live_current_cannot_confirm_step_or_advance_revision():
    backend,ports=mismatch();intent(backend,"KEEP")
    check=backend.state["current_check"]["check_id"]
    payload={**FIXTURES["observed_unobservable"],"check_id":check}
    assert backend.on_observation(payload)
    snapshot=make_snapshot(backend.state)
    assert snapshot["step"]["comparison"]=="UNOBSERVABLE"
    assert snapshot["monitor"]["observation"]["check_id"]==check
    assert backend.state["current"]["current_revision"]==1
    assert backend.state["context"]["confirmed_steps"]==[]
    assert not backend.on_observation(payload) and len(ports.calls("planner"))==2


@pytest.mark.parametrize("changed",[False,True])
def test_ready_plan_after_unobservable_current_waits_for_verified_state(changed):
    backend,ports=mismatch();intent(backend,"REVISE",design=revised(backend))
    request=backend.state["planning_request"]["request_id"]
    check=backend.state["current_check"]["check_id"]
    backend.on_observation({**FIXTURES["observed_unobservable"],"check_id":check,"observation_seq":1})
    assert backend.on_plan_result(request,remaining(backend))
    assert backend.state["context"]["design"]["design_version"]==1
    assert backend.state["reason"]=="CURRENT_RECHECK_REQUIRED"
    assert backend.state["place_check"] is None and len(ports.calls("robot.deliver"))==1
    assert not backend.on_plan_result(request,remaining(backend))
    assert not backend.on_failure("planner",request,"late failure after READY")
    blocks=[{**A,"color":"blue"}]+([B] if changed else [])
    backend.on_observation(current_observation(backend,blocks,[RA,RB],seq=2))
    if changed:
        assert backend.state["context"]["design"]["design_version"]==1
        assert backend.state["planning_request"]["request_id"]!=request
        assert not backend.on_plan_result(request,remaining(backend))
    else:
        assert backend.state["context"]["design"]["design_version"]==2
        assert backend.state["planning_request"] is None
    assert len(ports.calls("robot.deliver"))==1


def test_duplicate_unclear_from_previous_question_does_not_enable_choice_or_parse_keep():
    backend,ports=mismatch();old=backend.state["question_request"]["request_id"]
    value=dict(request_id=old,decision="UNCLEAR",question="선택 결과를 안내합니다.")
    assert backend.on_intent(value)
    assert backend.state["question_request"]["request_id"]!=old
    assert not backend.on_intent(value)
    assert not backend.on_intent(dict(request_id=old,decision="KEEP"))
    assert backend.state["unclear_count"]==1 and not backend.state["choice_required"]
    assert len(ports.calls("hri"))==1 and len(ports.calls("planner"))==1
    current=backend.state["question_request"]["request_id"]
    value["request_id"]=current
    assert backend.on_intent(value) and backend.state["choice_required"]
    assert not backend.on_intent(value) and backend.state["unclear_count"]==2


def test_human_corrects_final_block_then_empty_remaining_needs_actual_whole_design_match():
    backend,ports=delivering()
    for blocks,regions in (([A],[RA]),([A,B],[RA,RB])):
        robot_success(backend);value=observation(backend,blocks,regions)
        backend.on_place(value["check_id"],0,"EMPTY");backend.on_observation(value)
    robot_success(backend)
    backend.on_observation(observation(backend,[{**C,"color":"yellow"}],[RC]))
    intent(backend,"KEEP")
    backend.on_plan_result(backend.state["planning_request"]["request_id"],dict(status="NEEDS_CORRECTION",plan=None,errors=[dict(reason="정리 필요",block=block) for block in [{**C,"color":"yellow"}]]))
    backend.command(dict(command="CONTINUE_AFTER_CORRECTION",job_id=backend.state["job_id"],
        request_id=backend.state["correction_request"]["request_id"]))
    backend.on_observation(current_observation(backend,[C],[RC]))
    request=backend.state["planning_request"]
    plan={**deepcopy(FIXTURES["completed_plan"]),"base_current_revision":request["base_current_revision"]}
    assert backend.on_plan_result(request["request_id"],dict(status="READY",plan=plan,errors=[]))
    assert backend.state["workflow_status"]=="COMPLETE"
    assert backend.state["current"]==dict(current_revision=4,blocks=[A,B,C])
    assert len(ports.calls("robot.deliver"))==3
