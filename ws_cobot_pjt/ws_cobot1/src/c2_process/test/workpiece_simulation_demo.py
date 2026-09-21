"""python3 test/workpiece_simulation_demo.py — 로봇 연결 없는 Action 내부 함수 예제."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.workpiece_calibration import MeasurementContext, measure_workpiece
from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter


def main():
    config=json.loads((Path(__file__).resolve().parents[1]/"config/workpiece_simulation.json").read_text())
    context=MeasurementContext("sim-workpiece-001","sim-preparation-001","SIMULATION")
    adapter=SimulatedWorkpieceAdapter(config["workcell"],clock=context.monotonic)
    def feedback(e):
        print(json.dumps(e,ensure_ascii=False,allow_nan=False))
    result=measure_workpiece(adapter,config["workcell"],config["profiles"],context,feedback)
    print(json.dumps(dict(outcome=result.outcome,error_code=result.error_code,
                         message=result.message,result=result.observed_state),ensure_ascii=False,allow_nan=False))
    return 0 if result.ok else 1


if __name__=="__main__":
    raise SystemExit(main())
