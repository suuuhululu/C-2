"""Preview coupled TCP rotation/translation for one yellow 4-stud block; no devices."""
import argparse,json,sys
from pathlib import Path
NATIVE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(NATIVE))
from app.edge_first_seating import preview


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=NATIVE/'fixtures/yellow4_edge_first_preview.json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    result=preview(json.loads(args.config.read_text()))
    text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(text,end='');return 0


if __name__=='__main__':raise SystemExit(main())
