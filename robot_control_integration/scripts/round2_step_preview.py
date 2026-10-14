"""Preview the three Round2 branches from existing step data; never connect devices."""
import argparse
import json
from pathlib import Path
import sys

NATIVE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(NATIVE),str(NATIVE.parent/'perception')]
from app.assembly_step_bridge import build_plan,load_step
from app.round2_step_controller import prepare_round2_step
from scripts.supply_pick_release_trial import load_config,DEFAULT


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--step-dir',type=Path,required=True)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--measured',type=Path)
    parser.add_argument('--supply-config',type=Path,default=DEFAULT)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    profile=json.loads(args.profile.read_text())
    plan=build_plan(load_step(args.step_dir),profile)
    measured=json.loads(args.measured.read_text()) if args.measured else None
    prepared=prepare_round2_step(plan,profile,measured)
    supply=load_config(args.supply_config)
    prepared['profile']['round2_supply_observation_pose']=supply['observation_pose']
    prepared['profile']['round2_supply_config_source']=str(args.supply_config.resolve())
    prepared.update(status='PREVIEW_NO_DEVICE_CONNECTION',physical_commands=0)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(prepared,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(status=prepared['status'],branch=prepared['branch'],reason=prepared['reason'],
        output=str(args.output.resolve()),physical_commands=0),ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
