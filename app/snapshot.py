"""Backend 상태에서 화면 계약 전체를 생성한다. Qt는 이 결과만 표시한다."""

from app.hmi_contracts import validate_hmi_snapshot


def make_snapshot(state: dict) -> dict:
    real_trial = state["mode"] == "REAL"
    context, workflow = state["context"], state["workflow_status"]
    robot = state.get("robot_state")
    completed = len(context["confirmed_steps"]) if context else 0
    total = len(context["plan"]["steps"]) if context else 0
    step = context["plan"]["steps"][completed] if completed < total else None
    observed = state["step_observation"] if step else None
    observation = state["last_observation"]
    robot_status = ("ERROR" if state["fault"] else "STOP_PENDING" if state["stop_request"] else
                    "STOPPED" if workflow == "STOPPED" else "BUSY" if state["execution_id"] else
                    "IDLE" if state["controller_ready"] and state["at_observe_point"] else None)
    request = state.get("correction_request") or state["question_request"]
    request_id = request["request_id"] if request else None
    choice = workflow == "WAIT_INTENT" and state.get("choice_required", False)
    correction = workflow == "WAIT_CORRECTION" and request_id is not None
    reason = {"WAIT_PLACE_EMPTY":"새 관측으로 전달판 비움을 확인하고 있습니다.",
              "WAIT_PLACE_OCCUPIED":"전달판의 블록을 가져가고 손을 빼주세요.",
              "WAIT_INTENT":"목표와 실제 배치가 달라 다음 전달을 보류했습니다.",
              "STOP_PENDING":"정지를 요청했습니다. 실제 정지와 블록 상태 확인을 기다립니다.",
              "STOP_UNCONFIRMED":"정지·이전 실행 종료·블록 상태 중 확인되지 않은 항목이 있습니다.",
              "STOP_CONFIRMED":"정지 확인을 받았습니다. 같은 작업을 재개할 수 있습니다.",
              "NEEDS_REFILL":"해당 공급열을 채우고 보충 완료를 눌러주세요. 새 전달판 관측 뒤 진행합니다.",
              "INITIAL_LAYOUT_CONFIRM_START":"장치 정리 확인을 받았습니다. 조립판·전달판 비움과 공급판 채움을 확인한 뒤 시작하세요.",
              "CURRENT_RECHECK_REQUIRED":"재계획 결과를 받았지만 실제 배치를 다시 확인하기 전에는 채택하지 않습니다.",
              "TARGET_UNVERIFIED":"이번 목표를 확인할 관측 근거가 부족합니다."}.get(state["reason"],state["reason"])
    if workflow == "COMPLETE":
        reason = (f"현재 Plan 관측 확인 {completed}/{total} · 채택 기준 Current {len(context['base_current']['blocks'])}개 · "
                  f"전체 목표 {len(context['design']['blocks'])}개와 "
                  f"누적 실제 배치 {len(state['current']['blocks'])}개 일치 · "
                  f"Current revision {state['current']['current_revision']}")
    required_action = ("목표 유지 또는 목표 수정 중 선택해주세요." if choice else
                       "문제 블록을 정리한 뒤 정리 완료를 눌러 재관측하세요." if correction else
                       "정지 확인 후 재개할 수 있습니다." if workflow == "STOPPED" else
                       f"{'파랑' if step['after']['color']=='blue' else '노랑'} "
                       f"{'4점' if step['after']['brick_type']=='2x2x1' else '6점'}을 "
                       f"({step['after']['x']}, {step['after']['y']}) · {step['after']['layer']}층에 조립해주세요. "
                       "관측으로 확인하며 다음 전달을 진행합니다." if workflow == "WAIT_ASSEMBLY" else
                       "시작 버튼으로 새 작업을 요청하세요." if workflow == "IDLE" else None)
    if correction:
        placements = "; ".join(f"{block.get('brick_type', '?')} {block.get('color', '?')} "
            f"({block.get('x', '?')}, {block.get('y', '?')}) {block.get('layer', '?')}층 {block.get('orientation_deg', '?')}°"
            for block in state["correction_conflicts"])
        required_action += f"\n문제 배치: {placements}" if placements else ""
    if state.get("planner_errors") and workflow in ("HOLD", "WAIT_CORRECTION", "STOPPED"):
        details = "\n".join(error["reason"] + (f" · 배치: {error['block']}" if error["block"] is not None else "")
                            for error in state["planner_errors"])
        required_action = (required_action + "\n" if required_action else "") + details
    if state["fault"] and workflow != "IDLE":
        required_action = "정지 확인 뒤 장치를 정리하고 준비/빈 그리퍼 확인을 받아야 새로 시작할 수 있습니다. 자동 복구는 하지 않습니다."
    if real_trial:
        reason = ("실제 한 블록 전달·복귀 완료. 조립 완료는 확인하지 않았습니다."
                  if state["reason"] == "REAL_TRANSFER_DONE_ASSEMBLY_UNVERIFIED" else
                  "실제 한 블록 전달 시험입니다." if state["reason"] == "REAL_SINGLE_TRANSFER" else state["reason"])
        required_action = "실제 STOP/재개는 미검증으로 비활성화했습니다. 현장 비상정지에 대응할 사람이 있어야 합니다. 자동 다음 전달은 없습니다."
        if robot and robot.get("trial_notice"):
            required_action = robot["trial_notice"] + "\n" + required_action
    button = lambda enabled: dict(visible=True, enabled=enabled)
    snapshot = dict(
        workflow_status=workflow,
        design=context["design"] if context else None,
        step=dict(plan_id=context["plan"]["plan_id"] if context else None,
                  step_id=step["step_id"] if step else None, target=step["after"] if step else None,
                  observed=observed, comparison=state["comparison"] if observed else "WAITING"),
        progress=dict(completed=completed, total=total),
        monitor=dict(robot=dict(mode=state["mode"], status=robot_status),
                     observation={key: observation[key] if observation else None
                                  for key in ("status", "check_id", "observation_seq", "reason")},
                     place_status=state["place_status"],
                     supply=robot["supply"] if robot else
                            [dict(brick_type=brick, color=color, next_slot=None, needs_refill=None)
                             for brick in ("2x2x1", "2x3x1") for color in ("yellow", "blue")]),
        notice=dict(question=state["question"], reason=reason, required_action=required_action,
                    request_id=request_id),
        actions=dict(job_id=state["job_id"], start=button(workflow in ("IDLE", "COMPLETE") and
                     (not real_trial or state["job_id"] is None and state["controller_ready"] and state["at_observe_point"])),
                     stop=button(not real_trial and workflow not in ("IDLE", "COMPLETE", "STOPPED")),
                     resume=button(not real_trial and workflow == "STOPPED"),
                     intent_choice=dict(visible=choice, enabled=choice, request_id=request_id if choice else None),
                     correction_continue=dict(visible=correction, enabled=correction,
                                              request_id=request_id if correction else None),
                     supply_refill=[dict(brick_type=row["brick_type"], color=row["color"],
                                         visible=True, enabled=robot["ready_at_observe"]
                                         and state["fault"] is None and state["stop_request"] is None)
                                    for row in robot["supply"] if row["needs_refill"] and state["job_id"]]
                                    if robot and not real_trial else []))
    if real_trial and robot is not None:
        snapshot["transfer_target"] = robot["transfer_target"]
    return validate_hmi_snapshot(snapshot)
