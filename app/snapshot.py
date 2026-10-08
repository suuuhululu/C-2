"""Backend 상태에서 화면 계약 전체를 생성한다. Qt는 이 결과만 표시한다."""

from app.hmi_contracts import validate_hmi_snapshot


def make_snapshot(state: dict) -> dict:
    real_trial = state["mode"] == "REAL"
    manual_trial = state.get("manual_trial", False)
    day4_workflow = state.get("day4_workflow", False)
    context, workflow = state["context"], state["workflow_status"]
    robot = state.get("robot_state")
    robot_fault = state["fault"] or (robot.get("fault") if robot else None)
    robot_stop = robot.get("stop") if robot else None
    completed = len(context["confirmed_steps"]) if context else 0
    total = len(context["plan"]["steps"]) if context else 0
    step = context["plan"]["steps"][completed] if completed < total else None
    observed = state["step_observation"] if step else None
    observation = state["last_observation"]
    robot_status = ("ERROR" if robot_fault else "STOP_PENDING" if state["stop_request"] or robot_stop and not robot_stop["confirmed"] else
                    "STOPPED" if robot_stop and robot_stop["confirmed"] else
                    "STOPPED" if workflow == "STOPPED" else "BUSY" if state["execution_id"] else
                    "BUSY" if robot and robot.get("active_execution") else
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
              "MANUAL_ASSEMBLY_MISMATCH":"현장에서 잘못 놓았다고 신고했습니다. 다음 전달을 보류했습니다. 실제 배치 좌표는 아직 받지 않았습니다.",
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
        if workflow == "IDLE" and not state["controller_ready"]:
            preparing = robot is not None and robot.get("active_execution") is not None
            reason = "실제 HOME→observe 사전 이동 중입니다." if preparing else robot_fault or "Robot 무이동 준비 조회가 아직 성공하지 않았습니다."
            required_action = ("사전 이동 종료와 observe 도착/대기 확인을 기다립니다. 아직 Job/집기는 시작하지 않았습니다." if preparing else
                               "시작은 무이동 조회 성공 또는 사전 이동 도착/대기 확인 후에만 가능합니다. 실패 사유와 장치 상태를 확인하세요.")
        if manual_trial and workflow == "COMPLETE":
            reason = f"현장 수동 확인 {completed}/{total} · 채택 Design과 누적 Current 일치 · Camera 검증 없음"
            required_action = f"{completed}회 전달과 현장 수동 조립 확인을 마쳤습니다. 이 창에서 추가 전달하지 않습니다."
        if manual_trial and workflow == "WAIT_ASSEMBLY":
            following = "입력하면 다음 실제 전달이 시작됩니다." if completed + 1 < total else "입력하면 최종 조립 확인을 기록합니다."
            required_action = "기존 조립 유지·현재 목표 일치·전달판 비움·손을 뺀 상태를 확인하고 터미널 JSON을 입력하세요. " + following
        if manual_trial and workflow == "WAIT_CORRECTION":
            required_action = (required_action or "") + "\n사람이 실제 배치를 정리한 뒤 정리 완료를 누르세요. 터미널의 current JSON에 현장에서 확인한 조립판 전체 배치를 입력하면 실제 A가 다시 계산합니다."
        if manual_trial and state["reason"] == "MANUAL_ASSEMBLY_MISMATCH":
            required_action = "이 신고에는 실제 좌표가 없어 Current를 유지했습니다. 사람이 목표대로 정리한 뒤 정지 확인→재개로 새 조립 확인을 받으세요. 추가 전달은 확인 전까지 보류합니다."
            actual = state.get("manual_reported_placement")
            if actual is not None:
                reason = f"현장 입력 배치가 현재 Step 목표와 다릅니다. 입력 ({actual['x']}, {actual['y']}) · {actual['layer']}층 / 목표 ({step['after']['x']}, {step['after']['y']}) · {step['after']['layer']}층. 종류·색상·방향도 표에서 확인하세요."
                required_action = "표시된 목표는 현재 Step의 참고 위치입니다. 사람이 배치·색상·층·방향을 확인해 정리해야 합니다. 정리 후 재관측/재개와 목표 수정 의도 처리는 아직 미연결이며 추가 전달하지 않습니다."
        if manual_trial and state["fault"]:
            required_action = "오류로 시험을 중단했습니다. 현장 정지·블록 상태를 확인하세요. 이 창에서 자동 복구/재개하지 않습니다."
        if not manual_trial and not day4_workflow and workflow != "IDLE":
            reason = ("실제 한 블록 전달·복귀 완료. 조립 완료는 확인하지 않았습니다."
                  if state["reason"] == "REAL_TRANSFER_DONE_ASSEMBLY_UNVERIFIED" else
                  "실제 한 블록 전달 시험입니다." if state["reason"] == "REAL_SINGLE_TRANSFER" else state["reason"])
        required_action = (("시험용 현장 수동 확인 · Camera 미연결\n" + (required_action or "터미널의 현장 확인 입력을 기다립니다.") + "\n") if manual_trial else ((required_action + "\n") if day4_workflow and required_action else "")) + "정지는 요청 후 실제 정지·이전 실행 종료·블록 상태를 확인합니다. 확인 완료 후 재개로 같은 작업을 이어갑니다. 긴급 정지는 현장 비상정지를 사용하세요."
        if robot and robot.get("trial_notice") and not (manual_trial and (workflow == "COMPLETE" or state["reason"] == "MANUAL_ASSEMBLY_MISMATCH")):
            required_action = robot["trial_notice"] + "\n" + required_action
    if day4_workflow and workflow in ("IDLE", "COMPLETE") and state["controller_ready"] and not robot_fault:
        required_action = "조립판을 비운 뒤 시작하세요. 시작은 빈 조립판 확인이며 새 Job을 만듭니다. 공급열은 자동 초기화하지 않습니다."
    button = lambda enabled: dict(visible=True, enabled=enabled)
    snapshot = dict(
        workflow_status=workflow,
        design=context["design"] if context else None,
        current=state["current"],
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
                     (not real_trial or (day4_workflow or state["job_id"] is None) and state["controller_ready"] and state["at_observe_point"] and robot_status == "IDLE")),
                     stop=button(workflow not in ("IDLE", "COMPLETE", "STOPPED") or real_trial and state["job_id"] is None and robot_status in ("BUSY", "STOP_PENDING")),
                     resume=button(workflow == "STOPPED" or real_trial and state["job_id"] is None and robot_status == "STOPPED"),
                     intent_choice=dict(visible=choice, enabled=choice, request_id=request_id if choice else None),
                     correction_continue=dict(visible=correction, enabled=correction,
                                              request_id=request_id if correction else None),
                     supply_refill=[dict(brick_type=row["brick_type"], color=row["color"],
                                         visible=True, enabled=robot["ready_at_observe"]
                                         and state["fault"] is None and state["stop_request"] is None)
                                    for row in robot["supply"] if row["needs_refill"] and state["job_id"]]
                                    if robot and (not real_trial or day4_workflow) else []))
    if day4_workflow:
        snapshot["day4_workflow"] = True
    elif manual_trial:
        snapshot["manual_trial"] = True
        if (state.get("manual_reported_placement") is not None and state["comparison"] == "MISMATCH"
                and observed is not None and state["manual_reported_placement"] in observed["visible_blocks"]):
            snapshot["reported_placement"] = state["manual_reported_placement"]
    elif real_trial and robot is not None:
        snapshot["transfer_target"] = robot["transfer_target"]
    if real_trial and robot is not None and state["job_id"] is None and "prepare_available" in robot:
        snapshot["actions"]["prepare_observe"] = dict(visible=True, enabled=robot["prepare_available"])
    return validate_hmi_snapshot(snapshot)
