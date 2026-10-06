"""실제 A + 합성 관측 + D/Qt 화면 시험. C Mock/저장 응답, Robot FAKE, 장치 연결 없음."""

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from threading import Thread

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication

from app.backend import Backend
from app.contracts import _integer, _object, validate_block
from app.fake_robot_driver import FakeRobotDriver
from app.jsonl_log import JsonlLog
from app.planning_connection import on_c_intervention, run_planning_request
from app.qt_hmi import HmiWindow
from app.robot_controller import RobotController, load_robot_config
from app.snapshot import make_snapshot
from app.step_input_hmi import InputBridge


ROOT = Path(__file__).resolve().parents[1]
B_PATH = ROOT / "tests/integration/perception_backend_callback_examples"
SCENARIOS = ("normal", "mismatch", "verified-empty", "occluded", "lower-occluded", "place-unobservable")
CASES = dict(normal="normal_match", mismatch="mismatch", **{
    "verified-empty": "verified_empty", "occluded": "occlusion_or_low_quality",
    "lower-occluded": "lower_layer_only_occluded", "place-unobservable": "delivery_unobservable"})
SCOPE = "A 실제 계산 · B 합성 callback · C Mock · Robot FAKE · 실제 장치 미연결"


class AbdInputDemo:
    def __init__(self, window, log_directory, *, scenario="normal", delay_ms=350,
                 initial_result=None, revised_result=None):
        if scenario not in SCENARIOS:
            raise ValueError("Unsupported synthetic B scenario")
        _integer(delay_ms, 0, None, "synthetic.delay_ms")
        if revised_result is not None and initial_result is None:
            raise ValueError("--revised-result requires --initial-result")
        if initial_result is not None and scenario != "normal":
            raise ValueError("C result files require --scenario normal")
        spec = importlib.util.spec_from_file_location("b_pr10_examples", B_PATH / "callback_examples.py")
        self.b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.b)
        self.window, self.scenario, self.delay_ms = window, scenario, delay_ms
        self.directory = Path(log_directory)
        self.requests, self.sequences = [], {}
        yellow, upper = self.b.block(), self.b.block("blue", 2)
        next_block = {**self.b.block("blue"), "x": 10}
        lower = scenario in ("occluded", "lower-occluded")
        blocks = ([yellow, upper, {**yellow, "layer": 3}] if lower else
                  [yellow, next_block, upper] if scenario == "normal" else [yellow, next_block])
        self.design = dict(design_version=1, blocks=blocks)
        self.seed = dict(current_revision=1, blocks=[yellow]) if lower else None
        self.external_c = initial_result is not None
        self.initial_response = (json.loads(Path(initial_result).read_text()) if self.external_c else
                                 dict(status="OK", hri_result=None, design=deepcopy(self.design)))
        self.revised_response = json.loads(Path(revised_result).read_text()) if revised_result else None
        self.scope = ("A 실제 계산 · C 저장 응답 · 합성 관측 · Robot FAKE · C/Camera 실제 호출 없음"
                      if self.external_c else SCOPE)
        self.backend = Backend(self.emit, mode="FAKE", record=JsonlLog(self.directory))
        self.driver = FakeRobotDriver(ready_at_observe=True, on_request=self.driver_request)
        self.backend.connect_robot(RobotController(load_robot_config(ROOT / "interfaces/fixtures/robot.json"),
            self.driver, self.backend.on_robot_result, on_stopped=self.backend.on_stopped,
            on_event=self.backend.on_robot_event))
        window.command_requested.connect(self.command)
        window.setWindowTitle("협동 조립 · A–B–D 합성 JSON 화면 시험 · FAKE")
        self.publish()

    def emit(self, port, payload):
        self.requests.append((port, deepcopy(payload)))
        print(json.dumps(dict(request=port, payload=payload), ensure_ascii=False), flush=True)
        if port == "planner":
            if "design" in payload:
                run_planning_request(self.backend, payload)
            else:
                if self.seed is not None:
                    # 합성 사례의 이미 채택된 사전 Current. B 추적값을 새 검출로 채택하지 않는다.
                    self.backend._state["current"] = deepcopy(self.seed)
                    self.backend._state["planning_request"]["base_current_revision"] = self.seed["current_revision"]
                    self.backend._event("SYNTHETIC_CURRENT_SEEDED", result=self.seed)
                self.backend.on_initial_design(payload["request_id"],
                    deepcopy(self.initial_response))
        elif port == "hri":
            questions = self.revised_response.get("questions", []) if isinstance(self.revised_response, dict) else []
            self.backend.on_question(payload["request_id"], "\n".join(questions) if questions else
                "합성 관측에서 목표와 차이를 확인했습니다. 실제 C 의도 해석은 미연결입니다.")

    def driver_request(self, operation, payload):
        payload = deepcopy(payload)
        QTimer.singleShot(self.delay_ms, lambda: self.driver_result(operation, payload))

    def driver_result(self, operation, payload):
        if operation == "stop":
            self.driver.confirm_stop(payload["request_id"], stopped=True, execution_ended=True,
                block_state_known=True, block_state=self.driver.block_state)
        else:
            self.driver.confirm(payload["execution_id"], operation)
        self.publish()

    def command(self, value):
        result = self.backend.command(value)
        self.publish()
        print(json.dumps(result, ensure_ascii=False), flush=True)

    def publish(self):
        snapshot = make_snapshot(self.backend.state)
        snapshot["notice"]["required_action"] = (snapshot["notice"]["required_action"] or "") + "\n" + self.scope
        self.window.snapshot_received.emit(snapshot)
        state = self.backend.state
        if state["job_id"]:
            path = self.directory / (state["job_id"] + ".snapshot.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(current=state["current"], snapshot=snapshot), ensure_ascii=False, indent=2))
        if state["active_check"] is not None and state["execution_id"] is None and state["stop_request"] is None:
            print('다음 합성 관측 입력: {"event":"observe"}', flush=True)
        elif state["place_check"] is not None and state["execution_id"] is None and state["stop_request"] is None:
            print('다음 합성 전달판 입력: {"event":"place_empty"}', flush=True)
            if self.scenario == "place-unobservable":
                print('전달판 판단 불가 시험: {"event":"place_unobservable"}', flush=True)
        elif state["workflow_status"] == "COMPLETE":
            print("합성 조립 확인 완료. 실제 장치/Camera 검증 없음.", flush=True)
        elif state["workflow_status"] == "WAIT_INTENT" and self.revised_response is not None:
            print('저장된 C Revised 적용: {"event":"revise"}', flush=True)

    def stored_case(self, name, check_id, seq):
        observed = json.loads((B_PATH / "fixtures" / f"{name}.observed.json").read_text())
        details = json.loads((B_PATH / "fixtures" / f"{name}.diagnostics.json").read_text())["proposed_diagnostics"]
        # 새 합성 묶음 시작에만 ID/seq를 고정한다. 지연된 결과를 수신 시 재식별하지 않는다.
        observed.update(check_id=check_id, observation_seq=seq)
        details.update(check_id=check_id, observation_seq=seq)
        return dict(vision_result=observed, vision_diagnostics=details)

    def assembly_case(self, check_id, seq, *, actual=None):
        state = self.backend.state
        if self.external_c:
            placement = actual if actual is not None else self.backend._next_step()["after"]
            return dict(vision_result=dict(check_id=check_id, observation_seq=seq, status="OK",
                visible_blocks=deepcopy(state["current"]["blocks"] + [placement]),
                verified_regions=[self.b.region(layer=layer) for layer in range(1, 5)], reason=None)), "D 합성 관측 / C 저장 Design"
        index = len(state["context"]["confirmed_steps"])
        if index == 0:
            return self.stored_case(CASES[self.scenario], check_id, seq), "B PR #10 저장 합성 JSON"
        target = self.backend._next_step()["after"]
        if target == self.b.block("blue", 2):
            return self.stored_case("lower_layer_only_occluded", check_id, seq), "B PR #10 저장 합성 JSON"
        # B 예시 밖의 추가 목표는 이 화면 시험의 고정 Design을 위한 D 합성 프레임이다.
        return dict(vision_result=dict(check_id=check_id, observation_seq=seq, status="OK",
            visible_blocks=deepcopy(self.design["blocks"][:index + 1]) if self.seed is None else [deepcopy(target)],
            verified_regions=[self.b.region(layer=target["layer"])], reason=None)), "D 추가 합성 프레임 → B deliver_example"

    def receive(self, value):
        actual_input = isinstance(value, dict) and value.get("event") == "observe" and "actual" in value
        value = _object(value, ("event", "actual") if actual_input else ("event",), "synthetic.input")
        event = value["event"]
        if event == "revise":
            state = self.backend.state
            request = state["question_request"]
            if self.revised_response is None or request is None or state["workflow_status"] != "WAIT_INTENT":
                raise ValueError("저장된 Revised와 활성 의도 확인 요청이 필요합니다.")
            accepted = on_c_intervention(self.backend, request["request_id"], deepcopy(self.revised_response))
            self.publish()
            print(json.dumps(dict(accepted=accepted, workflow=self.backend.state["workflow_status"])), flush=True)
            return
        if event not in ("observe", "place_empty", "place_unobservable"):
            raise ValueError("event must be observe, place_empty, place_unobservable or revise")
        if actual_input and not self.external_c:
            raise ValueError("actual input requires --initial-result")
        actual = validate_block(value["actual"]) if actual_input else None
        state = self.backend.state
        check = state["active_check"] if event == "observe" else state["place_check"]
        if (check is None or state["execution_id"] or state["stop_request"] or state["fault"]
                or not state["at_observe_point"] or state["workflow_status"] == "STOPPED"):
            raise ValueError("현재 확인 단계에서 사용할 수 없는 입력입니다. HMI 상태와 터미널의 다음 입력을 확인하세요.")
        identity = check["check_id"]
        seq = self.sequences.get(identity, -1) + 1
        self.sequences[identity] = seq
        if event == "observe":
            case, source = self.assembly_case(identity, seq, actual=actual)
            details = case.get("vision_diagnostics", {}).get("delivery_board")
            if details is not None:
                # B에 별도 진단 callback은 없다. 시험용 on_place 최소 변환이다.
                self.backend.on_place(identity, seq, details["state"], details.get("reason"))
            self.backend._event("SYNTHETIC_OBSERVATION_INPUT", request_id=identity,
                                result=dict(source=source, observed=case["vision_result"]))
            accepted = self.b.deliver_example(case, self.backend.on_observation)
        else:
            status = "EMPTY" if event == "place_empty" else "UNOBSERVABLE"
            reason = None if status == "EMPTY" else "camera_view_occluded"
            self.backend._event("SYNTHETIC_PLACE_INPUT", request_id=identity,
                result=dict(check_id=identity, observation_seq=seq, status=status, reason=reason))
            accepted = self.backend.on_place(identity, seq, status, reason)
        self.publish()
        print(json.dumps(dict(accepted=accepted, check_id=identity, observation_seq=seq,
                              workflow=self.backend.state["workflow_status"]), ensure_ascii=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-b", action="store_true", required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--delay-ms", type=int, default=350)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "logs/abd_hmi")
    parser.add_argument("--initial-result", type=Path)
    parser.add_argument("--revised-result", type=Path)
    args = parser.parse_args(argv)
    if args.delay_ms < 0:
        parser.error("--delay-ms must be nonnegative")
    if args.revised_result and not args.initial_result or args.initial_result and args.scenario != "normal":
        parser.error("C results require --initial-result and --scenario normal")
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = HmiWindow()
    demo = AbdInputDemo(window, args.log_dir, scenario=args.scenario, delay_ms=args.delay_ms,
                        initial_result=args.initial_result, revised_result=args.revised_result)
    bridge = InputBridge()

    def receive(value):
        try:
            demo.receive(value)
        except (OSError, ValueError, KeyError, TypeError) as error:
            window.footer.setText(f"합성 FAKE · 입력 보류: {error}")
            print(f"입력 보류: {error}", flush=True)

    bridge.received.connect(receive, Qt.QueuedConnection)
    bridge.ended.connect(window.close, Qt.QueuedConnection)
    window.show()
    print(demo.scope + "\nHMI 시작 → 출력된 JSON 한 줄씩 입력. Ctrl+D 또는 창 닫기로 종료.", flush=True)
    print(f"시나리오: {args.scenario} · 로그: {args.log_dir}", flush=True)
    Thread(target=bridge.read, daemon=True).start()
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
