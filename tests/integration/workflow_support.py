"""Saved/manual workflow harness retained only for regression tests."""

from copy import deepcopy
import json
import os
from pathlib import Path


from app.backend import Backend
from app.contracts import _object, validate_block, validate_design
from app.current import _placements
from app.hmi_board import dimensions
from app.jsonl_log import JsonlLog
from app.planning_connection import run_planning_request
from app.real_design_controller import RealDesignController
from app.snapshot import make_snapshot


class WorkflowTrial:
    def __init__(self, window, controller, fixture_path, log_directory, *, c_mode=None, c_voice=False):
        if c_mode not in (None, "offline", "live") or c_voice and c_mode != "live":
            raise ValueError("REAL voice preparation requires --c-mode live")
        if c_mode and (os.environ.get("C_DESIGN_USE_LLM") == "1") != (c_mode == "live"):
            raise ValueError("C_DESIGN_USE_LLM must match --c-mode")
        if c_mode and not isinstance(controller, RealDesignController):
            raise ValueError("REAL C function mode requires four-row controller and whole-Plan preflight")
        self.window, self.controller = window, controller
        self.fixture_path = Path(fixture_path) if fixture_path is not None else None
        self.response = None
        self.c_connection = None
        self.backend = Backend(self.emit, mode="REAL", manual_trial=True, record=JsonlLog(log_directory))
        self.backend.connect_robot(controller)
        controller.on_result, controller.on_event = self.backend.on_robot_result, self.backend.on_robot_event
        controller.on_stopped = self.backend.on_stopped
        controller.changed.connect(self.publish)
        window.command_requested.connect(self.command)
        window.installEventFilter(controller)
        if c_mode:
            from app.c_text_connection import CTextConnection
            self.c_connection = CTextConnection(self.backend, self.publish, initial_text="의자 만들어줘",
                                                voice_mode=c_voice)
            window.destroyed.connect(self.c_connection.close)
        self.publish()

    def publish(self, message=None):
        if self.c_connection:
            self.c_connection.sync()
        if self.backend.state["job_id"] is None:
            ready = self.controller.state["ready_at_observe"]
            self.backend.controller_ready(ready=ready, at_observe_point=ready)
        snapshot = make_snapshot(self.backend.state)
        if message:
            snapshot["notice"]["required_action"] = message
        if self.c_connection:
            snapshot["notice"]["required_action"] = (snapshot["notice"]["required_action"] or "") + \
                ("\nC 설계·의도 연결 · STT/TTS LIVE · AI 생성 음성" if self.c_connection.voice_mode else "\nC 설계·텍스트 의도 연결") + \
                " · Robot REAL · Camera 미연결 · 현장 수동 확인" + \
                ("\n" + self.c_connection.voice_status if self.c_connection.voice_status else "")
        self.window.snapshot_received.emit(snapshot)

    def command(self, command):
        if command["command"] == "RESUME" and self.c_connection and self.c_connection.active:
            self.publish("정지는 유지했습니다. 이전 음성/API 호출 종료 후 재개를 눌러주세요.")
            return dict(accepted=False, reason="C_CALL_STILL_ENDING")
        if command["command"] == "START" and self.backend.state["job_id"] is None and not self.c_connection:
            try:
                response = json.loads(self.fixture_path.read_text(encoding="utf-8"))
                design = validate_design(response["design"])
                if not isinstance(self.controller, RealDesignController) and (len(design["blocks"]) != 3 or any(
                    block[field] != self.controller.target[field]
                    for block in design["blocks"] for field in ("brick_type", "color")
                )):
                    raise ValueError("시험 Design은 지정 공급열과 일치하는 블록 3개여야 합니다.")
                self.response = response
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.publish(f"C Fixture 입력 보류: {error}")
                return dict(accepted=False, reason=str(error))
        reply = self.backend.command(command)
        self.publish()
        print(json.dumps(reply, ensure_ascii=False), flush=True)
        return reply

    def emit(self, port, payload):
        print(json.dumps(dict(request=port, payload=payload), ensure_ascii=False), flush=True)
        if port == "planner":
            if "design" in payload:
                if isinstance(self.controller, RealDesignController):
                    self.check_design_plan(payload)
                else:
                    run_planning_request(self.backend, payload)
            else:
                if self.c_connection:
                    self.c_connection.start("initial", payload)
                else:
                    self.backend.on_initial_design(payload["request_id"], deepcopy(self.response))
        elif port == "hri":
            if self.c_connection:
                forced = payload.get("choice") == "REVISE"
                self.c_connection.start("intervention", payload, answers=["2번"] if forced else (), preview=not forced)
            else:
                self.backend.on_failure(port, payload["request_id"], "MANUAL_TRIAL_HRI_NOT_CONNECTED")
        elif port == "vision":
            if self.backend.state["current_check"] is not None:
                print("조립판 전체를 현장에서 확인한 뒤 아래 blocks를 실제 배치 전체로 고쳐 입력하세요. 확인하지 않은 빈 보드로 제출하지 마세요:", flush=True)
                print(json.dumps(dict(event="current", check_id=payload["check_id"], confirmed=True,
                    blocks=self.backend.state["current"]["blocks"]), ensure_ascii=False), flush=True)
                return
            event = "place_empty" if payload["after"] is None else "assembly"
            instruction = ("전달판이 비었고 손·장애물이 경로에서 벗어났으면" if event == "place_empty" else
                           f"기존 조립을 유지한 채 현재 목표 {payload['after']}대로 조립했고 전달판이 비었으며 손을 뺐으면")
            print(instruction + " 아래 JSON을 같은 터미널에 입력하세요:", flush=True)
            print(json.dumps(dict(event=event, check_id=payload["check_id"], confirmed=True)), flush=True)
            print("단축 확인 입력: " + json.dumps(dict(event=event)) +
                  " · 현재 열린 요청의 현장 확인입니다. 확인 후 한 번만 입력하세요.", flush=True)
            if event == "assembly":
                print("잘못 놓았으면 아래 신고를 입력하세요. 로그/화면에 보류하며 다음 전달은 없습니다:", flush=True)
                print(json.dumps(dict(event=event, check_id=payload["check_id"], confirmed=False)), flush=True)
                print("잘못 놓인 좌표도 표시하려면 신고 JSON에 actual 블록 여섯 필드를 추가하세요. 기존 조립은 유지 확인한 것으로 받습니다.", flush=True)
                print("좌표를 알면 위 신고 대신 아래 actual 양식의 값을 실제 배치로 바꿔 입력하세요. 현재 값은 목표를 복사한 양식입니다:", flush=True)
                print(json.dumps(dict(event=event, check_id=payload["check_id"], confirmed=False, actual=payload["after"])), flush=True)

    def check_design_plan(self, payload):
        request = self.backend.state["planning_request"]
        if (request is None or any(payload[key] != request[key] for key in
                ("request_id", "job_id", "design_version", "base_current_revision")) or
                payload["base_current_revision"] != self.backend.state["current"]["current_revision"]):
            return self.backend._ignored(payload["request_id"])
        from planning_trial.planner import plan_from_current
        result = plan_from_current(deepcopy(payload["design"]), deepcopy(payload["current"]))
        reason = None
        if result["status"] == "READY":
            try:
                self.controller.prepare_design_plan(result["plan"])
            except (OSError, ValueError) as error:
                reason = str(error)
        report = dict(design=payload["design"], current=payload["current"], a_result=result,
                      robot_plan_accepted=reason is None and result["status"] == "READY", reason=reason)
        if not self.backend._event("REAL_PLAN_PREFLIGHT", request_id=payload["request_id"], result=report):
            return False
        print(json.dumps(dict(event="REAL_PLAN_PREFLIGHT", **report), ensure_ascii=False), flush=True)
        if reason:
            return self.backend.on_failure("planner", payload["request_id"], reason)
        return self.backend.on_plan_result(payload["request_id"], result)

    def receive(self, value):
        if isinstance(value, dict) and value.get("event") == "answer" and self.c_connection:
            self.c_connection.answer(_object(value, ("event", "request_id", "text"), "manual.answer"))
            return True
        if isinstance(value, dict) and value.get("event") == "current":
            return self.receive_current(value)
        if (isinstance(value, dict) and "check_id" not in value and "event" in value and
                set(value) <= {"event", "confirmed", "actual"} and value["event"] in ("place_empty", "assembly")):
            state = self.backend.state
            check = state["place_check"] if value["event"] == "place_empty" else state["active_check"]
            if check is None or state["stop_request"] or state["workflow_status"] == "STOPPED":
                raise ValueError("현재 열린 현장 확인 요청이 없습니다. 최신 안내를 확인하세요.")
            value = dict(value, check_id=check["check_id"], confirmed=value.get("confirmed", "actual" not in value))
            print("현재 열린 check에 대한 현장 확인 명령입니다: " + json.dumps(value), flush=True)
        extra = ("actual",) if isinstance(value, dict) and "actual" in value else ()
        value = _object(value, ("event", "check_id", "confirmed") + extra, "manual.input")
        if (value["event"] not in ("place_empty", "assembly") or type(value["confirmed"]) is not bool or
                value["event"] == "place_empty" and not value["confirmed"]):
            raise ValueError("place_empty는 confirmed=true, assembly는 confirmed=true/false여야 합니다.")
        state = self.backend.state
        check = state["place_check"] if value["event"] == "place_empty" else state["active_check"]
        if (check is None or check["check_id"] != value["check_id"] or state["fault"] or
                (value["event"] == "assembly" and state["workflow_status"] != "WAIT_ASSEMBLY") or
                state["execution_id"] is not None or not self.controller.state["ready_at_observe"]):
            raise ValueError("닫힌/오래된 check 또는 Robot 실행/오류 중 확인은 채택하지 않습니다.")
        misplaced = value["event"] == "assembly" and not value["confirmed"]
        if extra and not misplaced:
            raise ValueError("actual 배치는 assembly/confirmed=false 신고에만 입력합니다.")
        target = self.backend._next_step()["after"] if value["event"] == "assembly" else None
        actual = validate_block(value["actual"]) if extra else None
        if actual == target and actual is not None:
            raise ValueError("actual이 현재 목표와 같습니다. 잘못 놓았다는 신고 좌표를 확인하세요.")
        blocks = None
        if value["event"] == "assembly" and (not misplaced or actual is not None):
            blocks = _placements(deepcopy(state["current"]["blocks"]) + [actual or deepcopy(target)],
                                 "manual.blocks", allow_duplicates=False)
        event = "MANUAL_ASSEMBLY_MISMATCH" if misplaced else "MANUAL_FIELD_CONFIRMATION"
        if not self.backend._event(event, request_id=value["check_id"], result=value):
            self.publish()
            return False
        observed = None
        if blocks is not None:
            regions = []
            # 좌표 신고에는 현재 목표 영역도 확인한 빈/다른 영역으로 포함한다.
            for block in blocks + ([target] if misplaced else []):
                width, height = dimensions(block)
                regions.append(dict(x=block["x"], y=block["y"], layer=block["layer"], width=width, height=height))
            # 운영자가 기존 조립 유지와 현재 블록 배치를 확인한 시험 입력이다.
            # 같은 색 아래층/기존 블록의 이동 여부를 Camera 없이 추정하지 않는다.
            observed = dict(check_id=value["check_id"], observation_seq=0, status="OK",
                visible_blocks=blocks, verified_regions=regions, reason=None)
        if misplaced:
            return self._report_misplaced(observed, actual, target)
        accepted = self.backend.on_place(value["check_id"], 0, "EMPTY")
        if observed is not None:
            accepted = self.backend.on_observation(observed) and accepted
        self.publish()
        return accepted

    def receive_current(self, value):
        value = _object(value, ("event", "check_id", "confirmed", "blocks"), "manual.current")
        state = self.backend.state
        check = state["current_check"]
        if (value["confirmed"] is not True or check is None or value["check_id"] != check["check_id"] or
                state["stop_request"] or state["fault"] or state["execution_id"] is not None or
                not self.controller.state["ready_at_observe"]):
            raise ValueError("조립판 전체 현장 확인은 현재 열린 Current check에만 채택합니다.")
        blocks = _placements(value["blocks"], "manual.current.blocks", allow_duplicates=False)
        if not self.backend._event("MANUAL_CURRENT_CONFIRMATION", request_id=value["check_id"], result=value):
            self.publish()
            return False
        # 사람이 조립판 전체·모든 층을 확인하는 시험 입력이다. Camera의 확인 범위를 추정하지 않는다.
        observed = dict(check_id=value["check_id"], observation_seq=check["last_observation_seq"] + 1
            if check["last_observation_seq"] is not None else 0, status="OK", visible_blocks=blocks,
            verified_regions=[dict(x=0, y=0, layer=layer, width=24, height=24) for layer in range(1, 5)], reason=None)
        accepted = self.backend.on_observation(observed)
        self.publish()
        return accepted

    def _report_misplaced(self, observed, actual, target):
        if observed is not None:
            self.backend.on_observation(observed)
            state = self.backend.state
            accepted = not state["fault"] and state["comparison"] == "MISMATCH"
        else:
            # 좌표가 없는 신고는 Observed를 만들거나 Current를 지울 근거가 아니다.
            accepted = True
        if accepted:
            if actual is not None:
                self.backend._state["manual_reported_placement"] = actual
            if observed is None or not self.c_connection:
                self.backend._hold("MANUAL_ASSEMBLY_MISMATCH")
        state = self.backend.state
        self.publish()
        print(json.dumps(dict(accepted=accepted, result="MISPLACED_REPORTED", source="MANUAL_REPORT",
            actual=actual, target=target, current_revision=state["current"]["current_revision"],
            completed_steps=len(state["context"]["confirmed_steps"]), next_delivery=False), ensure_ascii=False), flush=True)
        return accepted

