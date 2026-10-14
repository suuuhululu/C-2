"""Build a raised-grasp top-press candidate from an existing human step. No devices."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.assembly_step_bridge import load_step,build_plan
from app.human_step_raised_press import adapt_human_step

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--step-dir',type=Path,required=True)
 p.add_argument('--profile',type=Path,required=True)
 p.add_argument('--measured',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 args=p.parse_args();step=load_step(args.step_dir)
 profile=json.loads(args.profile.read_text());source=build_plan(step,profile)
 plan,profile=adapt_human_step(source,profile,json.loads(args.measured.read_text()))
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(json.dumps(dict(source_plan=source,execution_candidate=plan,profile=profile,physical_commands=0),ensure_ascii=False,indent=2)+'\n')
 print('Preview saved:',args.output)
if __name__=='__main__':main()
