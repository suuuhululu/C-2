"""Generate an existing Backend FAKE workflow without Qt or physical device imports."""

from copy import deepcopy
import argparse
import json
from pathlib import Path

from app.backend import Backend
from app.jsonl_log import JsonlLog


FIXTURE = Path(__file__).resolve().parents[1] / "interfaces/fixtures/day4.json"


def generate(directory: Path, *, revise=False) -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls = []
    backend = Backend(lambda port,payload: calls.append((port,deepcopy(payload))),
                      mode="FAKE", record=JsonlLog(directory))
    backend.controller_ready(ready=True, at_observe_point=True)
    backend.command(dict(command="START"))
    request = backend.state["planning_request"]["request_id"]
    backend.on_plan(request, fixture["design"], fixture["initial_plan"])
    if revise:
        # C/A-shaped fixture responses only; D does not issue Design versions.
        target = deepcopy(fixture["design"]["blocks"][0])
        backend.on_place(backend.state["place_check"]["check_id"],0,"EMPTY")
        backend.on_robot_result(dict(execution_id=backend.state["execution_id"],success=True,reason=None))
        target["color"] = "blue" if target["color"] == "yellow" else "yellow"
        _observe(backend, [target])
        candidate = deepcopy(fixture["design"])
        candidate["design_version"] = 2
        candidate["blocks"][0] = target
        backend.on_intent(dict(request_id=backend.state["question_request"]["request_id"],
                               decision="REVISE",design=candidate))
        plan = deepcopy(fixture["initial_plan"])
        plan.update(plan_id="mock-revised-plan",design_version=2,
                    base_current_revision=backend.state["current"]["current_revision"])
        plan["steps"] = plan["steps"][1:]
        for step in plan["steps"]:
            step["prerequisites"] = [item for item in step["prerequisites"] if item != "S01"]
        backend.on_plan(backend.state["planning_request"]["request_id"],candidate,plan)
    while backend.state["workflow_status"] != "COMPLETE":
        state = backend.state
        if state["place_check"]:
            backend.on_place(state["place_check"]["check_id"],0,"EMPTY")
        execution = backend.state["execution_id"]
        if execution is None:
            raise RuntimeError(f"mock flow blocked: {backend.state['reason']}")
        backend.on_robot_result(dict(execution_id=execution,success=True,reason=None))
        check = backend.state["active_check"]["check_id"]
        backend.on_place(check,0,"EMPTY")
        _observe(backend,backend.state["current"]["blocks"]+[backend._next_step()["after"]])
    return dict(job_id=backend.state["job_id"],status=backend.state["workflow_status"],
                path=str(directory / f"{backend.state['job_id']}.jsonl"))


def _observe(backend, blocks):
    backend.on_observation(dict(check_id=backend.state["active_check"]["check_id"],observation_seq=0,
        status="OK",visible_blocks=deepcopy(blocks),reason=None,
        verified_regions=[dict(x=0,y=0,width=24,height=24,layer=layer) for layer in range(1,6)]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",type=Path,required=True)
    parser.add_argument("--revise",action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate(args.directory,revise=args.revise),ensure_ascii=False))
