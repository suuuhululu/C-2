"""고정 드릴 공정의 단계 순서와 결과 전파. 장치 명령은 주입된 함수가 담당한다.

PRECHECK는 승인된 경로·설정·현재 로봇 상태를 검사한다. TOOL_CHECK는 저장된
드릴 끝 보정값을 1점 확인한다. 시작/복귀 콜백은 경로 외부 연결 이동을, 조각 함수는 경로 내부 구간을 수행한다.
집기·반납·청소와 그리퍼 열기 명령은 이 공정에서 호출하지 않는다.
"""

from typing import Callable, Optional

from .robot_adapter import StepResult


def _cancelled(context) -> bool:
    return context.cancel.is_set()


def _call(step: str, operation: Callable[[], StepResult]) -> StepResult:
    try:
        result = operation()
    except Exception as exc:
        return StepResult("UNKNOWN", "INTERNAL_ERROR", f"{step} 실행 결과 미확인: {exc}", step)
    if (not isinstance(result, StepResult)
            or result.outcome not in {"SUCCEEDED", "FAILED", "STOPPED", "UNKNOWN"}
            or not isinstance(result.observed_state, dict)):
        return StepResult("UNKNOWN", "INVALID_RESULT", f"{step} 결과 형식 오류", step)
    return result


def _with_tool_check(result: StepResult, observed: dict) -> StepResult:
    """1점 확인 근거를 조각의 성공·실패·정지 결과에도 보존한다."""
    state = dict(result.observed_state)
    state["tool_check"] = dict(observed)
    return StepResult(result.outcome, result.error_code, result.message, result.completed_step, state)


def run_process(
    context,
    *,
    precheck: Callable[[], StepResult],
    tool_check: Callable[[], StepResult],
    engrave: Callable[[Optional[Callable]], StepResult],
    on_phase: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
    go_to_start: Optional[Callable[[], StepResult]] = None,
    return_home: Optional[Callable[[], StepResult]] = None,
) -> StepResult:
    """PRECHECK → TOOL_CHECK → 시작 이동 → 조각 → 홈 복귀 → FINISH. 실패·정지 후 자동 재개하지 않는다.

    node.py가 같은 context와 경로·어댑터를 캡처한 콜백을 주입한다. 조각 콜백은
    engraving.execute_path(path, context, on_progress, adapter)를 호출하면 된다.
    """
    if context is None or not callable(getattr(getattr(context, "cancel", None), "is_set", None)):
        return StepResult("FAILED", "INVALID_INPUT", "취소 이벤트가 있는 context 필요", "precheck")
    if (not callable(precheck) or not callable(tool_check) or not callable(engrave)
            or (on_phase is not None and not callable(on_phase))
            or (on_progress is not None and not callable(on_progress))
            or ((go_to_start is None) != (return_home is None))
            or (go_to_start is not None and not callable(go_to_start))
            or (return_home is not None and not callable(return_home))):
        return StepResult("FAILED", "INVALID_INPUT", "공정 콜백 형식 오류", "precheck")

    def phase(name: str) -> Optional[StepResult]:
        if on_phase is None:
            return None
        try:
            on_phase(name)
        except Exception as exc:
            return StepResult("UNKNOWN", "REPORTING_ERROR", f"{name} 상태 발행 실패: {exc}", name.lower())
        return None

    if _cancelled(context):
        return StepResult("STOPPED", "NONE", "실행 전 취소", "precheck")
    error = phase("PRECHECK")
    if error:
        return error
    result = _call("precheck", precheck)
    if not result.ok:
        return result
    if _cancelled(context):
        return StepResult("STOPPED", "NONE", "모션 전 취소", "precheck")

    error = phase("TOOL_CHECK")
    if error:
        return error
    tool_result = _call("tool_check", tool_check)
    if not tool_result.ok:
        return tool_result
    if _cancelled(context):
        return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "도구 확인 중 정지 요청 이후 성공 응답", "tool_check",
                          {"tool_check": dict(tool_result.observed_state)})

    error = phase("APPROACH")
    if error:
        return error
    if _cancelled(context):
        return _with_tool_check(StepResult("STOPPED", "NONE", "시작 이동 전 취소", "go_to_path_start"),
                                tool_result.observed_state)
    if go_to_start is not None:
        start_result = _call("go_to_path_start", go_to_start)
        if not start_result.ok:
            return _with_tool_check(start_result, tool_result.observed_state)
        if _cancelled(context):
            return _with_tool_check(StepResult("UNKNOWN", "STOP_UNCONFIRMED",
                "시작 이동 중 정지 요청 이후 성공 응답", "go_to_path_start"), tool_result.observed_state)
    result = _call("engrave", lambda: engrave(on_progress))
    if not result.ok:
        return _with_tool_check(result, tool_result.observed_state)
    if _cancelled(context):
        unknown = StepResult("UNKNOWN", "STOP_UNCONFIRMED", "조각 중 정지 요청 이후 성공 응답", "engrave",
                             dict(result.observed_state))
        return _with_tool_check(unknown, tool_result.observed_state)
    if return_home is not None:
        error = phase("RETRACT")
        if error:
            return _with_tool_check(error, tool_result.observed_state)
        if _cancelled(context):
            return _with_tool_check(StepResult("STOPPED", "NONE", "홈 복귀 전 취소", "return_home",
                                    dict(result.observed_state)), tool_result.observed_state)
        # 실패/정지 처리 경로에서는 이 복귀 함수를 호출하지 않는다.
        home_result = _call("return_home", return_home)
        if not home_result.ok:
            state = dict(result.observed_state)
            state.update(home_result.observed_state)
            failed = StepResult(home_result.outcome, home_result.error_code, home_result.message,
                                home_result.completed_step, state)
            return _with_tool_check(failed, tool_result.observed_state)
        if _cancelled(context):
            return _with_tool_check(StepResult("UNKNOWN", "STOP_UNCONFIRMED",
                "홈 복귀 중 정지 요청 이후 성공 응답", "return_home", dict(result.observed_state)),
                tool_result.observed_state)
        result.observed_state["return_home"] = dict(home_result.observed_state)
    error = phase("FINISH")
    if error:
        return error
    completed = StepResult("SUCCEEDED", "NONE", "고정 드릴 공정 완료", "finish", dict(result.observed_state))
    return _with_tool_check(completed, tool_result.observed_state)


def run_preparation(context, *, status_check, motion_check, measure, confirm_result,
                    on_phase=None):
    """내부 준비 순서. measure는 측정·계산·후퇴를 포함하고 확인 콜백은 읽기 전용이다.

    측정 원본 형식은 시율 담당 계약에 맞춘 confirm_result가 검사한다.
    새 ROS Action/상태 enum을 정의하지 않는다. 실패 뒤 후퇴를 추가 호출하지 않는다.
    """
    measured = None
    steps = [
        ("ROBOT_STATUS", status_check, False),
        ("MEASUREMENT_PRECHECK", motion_check, False),
        ("MEASURE_WORKPIECE", measure, True),
        ("CONFIRM_MEASUREMENT", lambda: confirm_result(measured), False),
    ]
    for phase, operation, moves in steps:
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "준비 취소", phase.lower())
        if on_phase is not None:
            try:
                on_phase(phase)
            except Exception as exc:
                return StepResult("UNKNOWN", "REPORTING_ERROR", str(exc), phase.lower())
        # 발행 콜백 중 도착한 취소도 다음 동작 전에 확인한다.
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "준비 취소", phase.lower())
        result = _call(phase.lower(), operation)
        if not result.ok:
            if measured is not None:
                result.observed_state = {**measured.observed_state, **result.observed_state}
            return result
        if context.cancel.is_set():
            return StepResult("UNKNOWN" if moves else "STOPPED",
                              "STOP_UNCONFIRMED" if moves else "NONE",
                              "준비 중 취소", phase.lower(), result.observed_state)
        if moves:
            measured = result
    return StepResult("SUCCEEDED", "NONE", "측정·계산·후퇴 확인 완료", "preparation",
                      {**measured.observed_state, "confirmation": result.observed_state})


def run_prepared_process(context, *, precheck, engrave, enter=None, return_home=None,
                         on_phase=None, on_progress=None):
    """준비 성공 기록을 연결한 실행: 최종 검사 → 검사된 entry → 조각 → 검사된 HOME 복귀.

    ``enter``와 ``return_home``은 PRECHECK가 확정한 동일 계획만 실행한다.
    콜백이 없으면 기존 SIM/호환 흐름을 유지하며, REAL 공정에서 필요 여부는
    coordinator가 결정한다.
    """
    if enter is not None and not callable(enter):
        return StepResult("FAILED", "INVALID_INPUT", "entry 콜백 형식 오류", "precheck")
    if return_home is not None and not callable(return_home):
        return StepResult("FAILED", "INVALID_INPUT", "HOME 복귀 콜백 형식 오류", "precheck")
    steps = [("PRECHECK", precheck, False)]
    if enter is not None:
        steps.append(("ENTRY", enter, True))
    steps.append(("ENGRAVE", lambda: engrave(on_progress), True))
    if return_home is not None:
        steps.append(("RETURN_HOME", return_home, True))
    entry_observed = None
    engraving_observed = None
    for phase, operation, moves in steps:
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "실행 취소", phase.lower())
        if on_phase is not None:
            try:
                on_phase(phase)
            except Exception as exc:
                return StepResult("UNKNOWN", "REPORTING_ERROR", str(exc), phase.lower())
        if context.cancel.is_set():
            return StepResult("STOPPED", "NONE", "실행 취소", phase.lower())
        result = _call(phase.lower(), operation)
        if not result.ok:
            if entry_observed is not None:
                result.observed_state = {**result.observed_state,
                                         "entry": dict(entry_observed)}
            if engraving_observed is not None:
                result.observed_state["engrave"] = dict(engraving_observed)
            return result
        if phase == "ENTRY":
            entry_observed = dict(result.observed_state)
        elif phase == "ENGRAVE":
            engraving_observed = dict(result.observed_state)
            if entry_observed is not None:
                result.observed_state["entry"] = dict(entry_observed)
        elif phase == "RETURN_HOME":
            if entry_observed is not None:
                result.observed_state["entry"] = dict(entry_observed)
            if engraving_observed is not None:
                result.observed_state["engrave"] = dict(engraving_observed)
        if context.cancel.is_set():
            return StepResult("UNKNOWN" if moves else "STOPPED",
                              "STOP_UNCONFIRMED" if moves else "NONE",
                              "실행 중 취소", phase.lower(), result.observed_state)
    if on_phase is not None:
        try:
            on_phase("FINISH")
        except Exception as exc:
            return StepResult("UNKNOWN", "REPORTING_ERROR", str(exc), "finish")
    if context.cancel.is_set():
        return StepResult("UNKNOWN", "STOP_UNCONFIRMED", "완료 보고 중 취소", "finish",
                          result.observed_state)
    return result
