from copy import deepcopy

import pytest

from test_assembly_completion import ACTIVE, DATA, PHYSICAL_CONTEXT, TRIAL, begin, metadata, sample, verification
from test_assembly_human import opened, reply, response


RECOVERY = DATA["recovery_trial"]


def binding(context, parameters):
    fields = ("job_id","plan_id","step_id","attempt_id","calibration_id","basis_world_revision")
    return {**{field:context[field] for field in fields}, "parameters":deepcopy(parameters)}


def checkpoint(sequence=0, stamp=101.5, **changes):
    result = deepcopy(RECOVERY["checkpoint"])
    result["physical"] = verification(sequence)["physical"]
    result["physical"]["metadata"]["stamp"] = stamp
    result["physical"]["released"] = result["grasp_state"] != "HOLDING"
    result.update(changes)
    return result


def failed(source="contact_state", value="JAMMED", *, record=None):
    backend, ports = begin(record=record)
    for name in ACTIVE:
        backend.on_assembly_evidence(now=101.5, event=sample(name, value if name == source else None))
    return backend, ports


def propose(backend, action="RE_OBSERVE", *, cp=None, parameters=None, limits=None, now=101.5):
    cp = deepcopy(checkpoint() if cp is None else cp)
    cp["plan_binding"]["parameters"] = deepcopy(RECOVERY["parameters"] if parameters is None else parameters)
    return backend.propose_assembly_recovery(action=action, now=now,
        checkpoint=cp,
        parameters=deepcopy(RECOVERY["parameters"]) if parameters is None else parameters,
        limits=deepcopy(RECOVERY["limits"]) if limits is None else limits)


def resume_inputs(*, stamp=101.75, parameters=None, cp=None):
    world = deepcopy(TRIAL["world"])
    active = {name:{**context, "attempt_id":"A02", "request_id":f"NEW-{name}", "opened_at":stamp}
              for name,context in ACTIVE.items()}
    physical_context = {**PHYSICAL_CONTEXT, "attempt_id":"A02", "opened_at":stamp, "request_id":"NEW-execution_result"}
    observation = dict(metadata=metadata(active["vision_verdict"], stamp=stamp), complete=True, world=world)
    parameters = {**RECOVERY["parameters"], "offset_m":[0.001,0,0]} if parameters is None else parameters
    cp = deepcopy(checkpoint(1,stamp) if cp is None else cp)
    cp["plan_binding"] = binding(active["execution_result"], parameters)
    return dict(active=active, max_age=deepcopy(DATA["attempt_collection"]["max_age"]),
        physical_context=physical_context, physical_max_age=2, world=world,
        target=deepcopy(TRIAL["target"]), observation=observation,
        parameters=parameters, limits=deepcopy(RECOVERY["limits"]), checkpoint=cp, now=stamp)


def test_permitted_recovery_is_only_a_proposal_and_does_not_mark_completion():
    events = []
    backend, ports = failed(record=events.append)
    result = propose(backend, "RETRACT")
    assert result["accepted"] and result["proposal"]["status"] == "PROPOSED"
    state = backend.assembly_state
    assert state["completion"] is None and state["world"] == TRIAL["world"] and ports == []
    assert len(state["recovery"]["reservations"]) == 1
    assert events[-1]["event"] == "RECOVERY_PROPOSAL_EVALUATED"


@pytest.mark.parametrize("action", RECOVERY["invalid_actions"])
def test_regrasp_remove_and_structure_correction_are_never_automatic_actions(action):
    backend, _ = failed()
    before = backend.assembly_state
    with pytest.raises(ValueError, match="action"):
        propose(backend, action)
    assert backend.assembly_state == before


@pytest.mark.parametrize("action,flag", [("RETRACT","retract_permitted"),
    ("MICRO_SEARCH","search_permitted"), ("RE_APPROACH","approach_permitted")])
def test_unknown_or_false_action_permission_is_not_accepted(action, flag):
    backend, _ = failed()
    if action == "RE_APPROACH":
        propose(backend)
    result = propose(backend, action, cp=checkpoint(1, **{flag:None}))
    assert not result["accepted"] and backend.assembly_state["completion"] is None


def test_changed_time_or_sequence_alone_cannot_repeat_same_recovery():
    backend, _ = failed()
    assert propose(backend)["accepted"]
    result = propose(backend, cp=checkpoint(1,101.75), now=101.75)
    assert not result["accepted"] and result["reason"] == "NO_MEANINGFUL_CHANGE"
    assert len(backend.assembly_state["recovery"]["reservations"]) == 1


def test_changed_relevant_parameter_can_reserve_one_more_action_then_budget_stops_it():
    backend, _ = failed()
    assert propose(backend, "MICRO_SEARCH")["accepted"]
    changed = {**RECOVERY["parameters"], "offset_m":[0.001,0,0]}
    assert propose(backend,"MICRO_SEARCH",cp=checkpoint(1),parameters=changed)["accepted"]
    changed["offset_m"] = [0.002,0,0]
    result = propose(backend,"MICRO_SEARCH",cp=checkpoint(2),parameters=changed)
    assert not result["accepted"] and result["reason"] == "RECOVERY_ACTION_BUDGET_EXHAUSTED"


def test_elapsed_budget_and_frozen_profile_cannot_be_bypassed():
    backend, _ = failed()
    limits = {**RECOVERY["limits"], "max_elapsed_s":0.1}
    assert propose(backend, limits=limits)["accepted"]
    result = propose(backend, cp=checkpoint(1,101.75), limits=limits,now=101.75)
    assert result["reason"] == "RECOVERY_TIME_BUDGET_EXHAUSTED"
    result = propose(backend, cp=checkpoint(2,101.75), limits=RECOVERY["limits"],now=101.75)
    assert result["reason"] == "RECOVERY_PROFILE_CHANGED"


@pytest.mark.parametrize("field", ["stopped","execution_ended"])
def test_unconfirmed_stop_or_execution_end_blocks_proposal(field):
    backend, _ = failed()
    cp = checkpoint()
    cp["physical"][field] = False
    assert not propose(backend,cp=cp)["accepted"]


def test_safety_stop_and_lost_grasp_do_not_trigger_automatic_retract():
    backend, _ = failed("motion_permitted",False)
    result = propose(backend,"RETRACT")
    assert not result["accepted"] and result["proposal"]["status"] == "SAFE_STOP"
    backend, _ = failed()
    cp = checkpoint(grasp_state="RELEASED")
    cp["physical"]["released"] = True
    result = propose(backend,"RETRACT",cp=cp)
    assert not result["accepted"] and result["proposal"]["status"] == "HUMAN_ASSISTANCE_REQUIRED"


def test_physical_correction_is_human_assistance_and_cannot_become_an_auto_search():
    backend, _ = opened()
    reply(backend,inspection="PHYSICAL_CORRECTION")
    result = propose(backend,"MICRO_SEARCH",cp=checkpoint(2,101.75),now=101.75)
    assert not result["accepted"] and result["proposal"]["status"] == "HUMAN_ASSISTANCE_REQUIRED"


def test_new_attempt_requires_actual_change_and_drops_old_evidence_and_latches():
    events = []
    backend, ports = failed(record=events.append)
    assert propose(backend)["accepted"]
    old = deepcopy(backend.assembly_state)
    result = backend.resume_assembly_trial(**resume_inputs())
    assert result["accepted"] and not result["committed"]
    state = backend.assembly_state
    assert all(value is None for value in state["collection"]["records"].values())
    assert all(value is None for value in state["collection"]["latched"].values())
    assert state["completion"] is None and state["human_verification"] is None
    assert state["collection"]["active"]["vision_verdict"]["attempt_id"] == "A02"
    assert state["attempt_history"][-1]["collection"]["records"] == old["collection"]["records"]
    assert state["recovery"]["reservations"] == old["recovery"]["reservations"]
    assert events[-1]["event"] == "ASSEMBLY_RESUME_CHECKED" and ports == []
    backend.on_assembly_evidence(now=101.75,event=sample("contact_state","SEATED",9))
    assert state["collection"]["records"]["contact_state"] is None
    assert backend.assembly_state["collection"]["records"]["contact_state"] is None


def test_world_revision_or_new_attempt_identifier_alone_is_not_progress():
    backend, _ = failed()
    propose(backend)
    inputs = resume_inputs(parameters=deepcopy(RECOVERY["parameters"]))
    result = backend.resume_assembly_trial(**inputs)
    assert not result["accepted"] and result["reason"] == "NO_MEANINGFUL_CHANGE"
    inputs["world"]["world_revision"] = 6
    inputs["observation"]["world"]["world_revision"] = 6
    for context in inputs["active"].values():
        context["basis_world_revision"] = 6
    inputs["physical_context"]["basis_world_revision"] = 6
    inputs["observation"]["metadata"]["basis_world_revision"] = 6
    inputs["checkpoint"] = checkpoint(2,101.75)
    inputs["checkpoint"]["plan_binding"] = binding(inputs["active"]["execution_result"], inputs["parameters"])
    result = backend.resume_assembly_trial(**inputs)
    assert not result["accepted"] and result["reason"] == "NO_MEANINGFUL_CHANGE"


@pytest.mark.parametrize("field", ["dependencies_ready","motion_plan_valid","support_ready","approach_permitted"])
def test_resume_requires_each_execution_prerequisite(field):
    backend, _ = failed()
    propose(backend)
    inputs = resume_inputs()
    inputs["checkpoint"][field] = None
    assert not backend.resume_assembly_trial(**inputs)["accepted"]
    assert backend.assembly_state["collection"]["active"]["contact_state"]["attempt_id"] == "A01"


@pytest.mark.parametrize("change", ["old_attempt","old_frame","partial","session_open"])
def test_resume_rejects_old_or_incomplete_reobservation_and_open_session(change):
    backend, _ = failed()
    propose(backend)
    inputs = resume_inputs()
    if change == "old_attempt":
        for context in inputs["active"].values():context["attempt_id"] = "A01"
        inputs["physical_context"]["attempt_id"] = "A01"
    elif change == "old_frame":inputs["observation"]["metadata"]["attempt_id"] = "A01"
    elif change == "partial":inputs["observation"]["complete"] = False
    else:inputs["checkpoint"]["session_closed"] = False
    assert not backend.resume_assembly_trial(**inputs)["accepted"]
    assert backend.assembly_state["completion"] is None


def test_human_completed_target_needs_post_correction_verification_not_immediate_completion():
    backend, _ = failed()
    propose(backend)
    inputs = resume_inputs()
    inputs["observation"]["world"] = deepcopy(TRIAL["observed_world"])
    result = backend.resume_assembly_trial(**inputs)
    assert not result["accepted"] and result["reason"] == "POST_CORRECTION_VERIFICATION_REQUIRED"
    assert backend.assembly_state["completion"] is None


def test_ordinary_fresh_true_safety_is_not_a_hardware_reset():
    backend, _ = failed("motion_permitted",False)
    propose(backend,"RE_OBSERVE")
    backend.on_assembly_evidence(now=101.75,event=sample("motion_permitted",True,1))
    assert not backend.resume_assembly_trial(**resume_inputs())["accepted"]
    assert backend.assembly_state["decision"]["decision"] == "SAFE_STOP"


def test_resume_storage_failure_preserves_old_attempt_and_world():
    def record(event):
        if event["event"] == "ASSEMBLY_RESUME_CHECKED":raise OSError("disk full")
    backend, _ = failed(record=record)
    propose(backend)
    old = backend.assembly_state
    result = backend.resume_assembly_trial(**resume_inputs())
    assert not result["accepted"]
    assert backend.assembly_state["collection"]["active"] == old["collection"]["active"]
    assert backend.assembly_state["world"] == old["world"] and backend.assembly_state["completion"] is None


@pytest.mark.parametrize("parameters", RECOVERY["invalid_parameters"])
def test_bad_parameters_are_rejected_without_partial_mutation(parameters):
    backend, _ = failed()
    before = backend.assembly_state
    with pytest.raises(ValueError):propose(backend,parameters=parameters)
    assert backend.assembly_state == before


@pytest.mark.parametrize("field,value", [("attempt_id","old"), ("calibration_id","old"),
    ("basis_world_revision",6), ("plan_id","old")])
def test_stale_plan_binding_cannot_approve_recovery_or_resume(field, value):
    backend, _ = failed()
    cp = checkpoint()
    cp["plan_binding"][field] = value
    assert propose(backend,cp=cp)["reason"] == "PLAN_CONTEXT_OR_PARAMETERS_MISMATCH"
    inputs = resume_inputs(cp=checkpoint(1,101.75))
    inputs["checkpoint"]["plan_binding"][field] = value
    assert backend.resume_assembly_trial(**inputs)["reason"] == "PLAN_CONTEXT_OR_PARAMETERS_MISMATCH"


def test_motion_approval_cannot_be_reused_for_changed_parameters():
    backend, _ = failed()
    changed = {**RECOVERY["parameters"], "offset_m":[0.001,0,0]}
    result = backend.propose_assembly_recovery(action="MICRO_SEARCH",parameters=changed,
        limits=RECOVERY["limits"],checkpoint=checkpoint(),now=101.5)
    assert not result["accepted"] and result["reason"] == "PLAN_CONTEXT_OR_PARAMETERS_MISMATCH"


def test_reapproach_requires_new_observation_and_meaningful_updated_plan():
    backend, ports = failed()
    assert propose(backend)["accepted"]
    assert propose(backend,"RE_APPROACH",cp=checkpoint(1))["reason"] == "NO_MEANINGFUL_CHANGE"
    changed = {**RECOVERY["parameters"], "offset_m":[0.001,0,0]}
    assert propose(backend,"RE_APPROACH",cp=checkpoint(2),parameters=changed)["accepted"]
    assert backend.assembly_state["completion"] is None and ports == []


def test_latest_invalid_safety_blocks_recovery_despite_valid_motion_flags():
    backend, _ = failed()
    event = sample("motion_permitted",sequence=1)
    event["metadata"]["valid"] = False
    backend.on_assembly_evidence(now=101.5,event=event)
    result = propose(backend,"RETRACT")
    assert not result["accepted"] and result["reason"] == "SAFETY_UNKNOWN"


@pytest.mark.parametrize("source", ["execution_result","vision_verdict"])
def test_closed_execution_and_observation_request_ids_are_not_reused(source):
    backend, _ = failed()
    propose(backend)
    inputs = resume_inputs()
    inputs["active"][source]["request_id"] = ACTIVE[source]["request_id"]
    assert backend.resume_assembly_trial(**inputs)["reason"] == "NEW_EXECUTION_AND_VISION_REQUEST_REQUIRED"


def test_old_human_response_cannot_complete_restarted_attempt():
    backend, _ = opened()
    old_response = response(backend)
    reply(backend,answer="NEGATIVE")
    assert propose(backend,cp=checkpoint(2,101.75),now=101.75)["accepted"]
    inputs = resume_inputs(stamp=101.9,cp=checkpoint(3,101.9))
    assert backend.resume_assembly_trial(**inputs)["accepted"]
    assert not reply(backend,packet=old_response,now=101.9)["committed"]
    assert backend.assembly_state["completion"] is None
    assert backend.assembly_state["collection"]["active"]["vision_verdict"]["attempt_id"] == "A02"


def test_human_regrasp_with_fresh_checks_can_start_new_attempt_without_motion():
    backend, ports = opened()
    reply(backend,inspection="PHYSICAL_CORRECTION")
    cp = checkpoint(2,101.75,grasp_state="RELEASED")
    cp["physical"]["released"] = True
    assert not propose(backend,cp=cp,now=101.75)["accepted"]
    inputs = resume_inputs(stamp=101.9,cp=checkpoint(3,101.9),parameters=deepcopy(RECOVERY["parameters"]))
    assert backend.resume_assembly_trial(**inputs)["accepted"]
    assert backend.assembly_state["completion"] is None and ports == []


def test_restart_does_not_reset_step_recovery_budget():
    backend, _ = failed()
    propose(backend)
    assert backend.resume_assembly_trial(**resume_inputs())["accepted"]
    state = backend.assembly_state
    assert state["recovery"]["restart_count"] == 1
    for name, context in state["collection"]["active"].items():
        event = sample(name,"JAMMED" if name == "contact_state" else None,1)
        event["metadata"] = metadata(context,stamp=101.9,sequence=1)
        backend.on_assembly_evidence(now=101.9,event=event)
    cp = checkpoint(0,101.9)
    cp["physical"]["metadata"] = metadata(state["physical_context"],stamp=101.9)
    cp["plan_binding"] = binding(state["collection"]["active"]["execution_result"],RECOVERY["parameters"])
    assert propose(backend,cp=cp,now=101.9)["reason"] == "RECOVERY_ACTION_BUDGET_EXHAUSTED"


def test_image_captured_before_new_stop_and_grasp_check_cannot_resume():
    backend, _ = failed()
    propose(backend)
    inputs = resume_inputs(stamp=101.9,cp=checkpoint(1,101.9))
    for context in inputs["active"].values():context["opened_at"] = 101.75
    inputs["observation"]["metadata"]["stamp"] = 101.8
    assert backend.resume_assembly_trial(**inputs)["reason"] == "REOBSERVATION_BEFORE_CHECKPOINT"
