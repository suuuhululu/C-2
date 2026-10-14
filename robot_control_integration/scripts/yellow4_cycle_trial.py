"""Stage7 independent yellow4 seating/removal/recovery cycle; defaults to preview."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'robot_control_integration'),str(ROOT/'perception')]
from app.yellow4_observation import prepare,source
from app.yellow4_seating_trial import prepare_seating
from app.yellow4_removal_trial import prepare_removal
from app.yellow4_recovery_trial import prepare_recovery,prepare_cycle
from scripts.yellow4_contact_trial import read_air_evidence,read_trial_evidence,run_session
from scripts.yellow4_edge_first_preview import save_plot


def prepare_files(root,settings):
    paths={key:None if value is None else (Path(value) if Path(value).is_absolute() else root/value)
        for key,value in settings['cycle']['inputs'].items()}
    def read(key):return None if paths[key] is None else json.loads(paths[key].read_text())
    obs=read('observations');assembly=prepare(root,obs,read('assembly_measurements'));base=prepare(root,obs)
    assembly['camera_info_topic']=base['camera_info_topic']=obs['camera_info_topic']
    air=read_air_evidence(paths['air_run']) if paths['air_run'] else None
    partial=read_trial_evidence(paths['assembly_partial_run'],'PARTIAL') if paths['assembly_partial_run'] else None
    seating=prepare_seating(assembly,read('contact_settings'),read('seating_settings'),air,partial)
    seating_record=read_trial_evidence(paths['seating_run'],'SEATING') if paths['seating_run'] else None
    removal=prepare_removal(base,read('removal_settings'),read('removal_measurements'),seating_record)
    removal_record=read_trial_evidence(paths['removal_partial_run'],'REMOVAL') if paths['removal_partial_run'] else None
    recovery=prepare_recovery(base,settings,removal_record)
    refs={key:source(path) for key,path in paths.items() if path is not None and path.is_file()}
    for key,record in [('air_run',air),('partial_run',partial),('seating_run',seating_record),('removal_run',removal_record)]:
        if record is not None:refs[key]=record['sources']
    for p in (seating,removal,recovery):p['sources'].update(cycle_input_files=deepcopy(refs))
    return assembly,prepare_cycle(settings,seating,removal,recovery)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=ROOT/'robot_control_integration/settings/yellow4_challenge_20261014/recovery_cycle.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--repeat',type=int)
    p.add_argument('--start-zone',choices=('home','supply','assembly'),default='home')
    p.add_argument('--execute',action='store_true');p.add_argument('--confirm-hand-clear',action='store_true')
    p.add_argument('--confirm-route-clear',action='store_true');p.add_argument('--confirm-target-empty',action='store_true')
    args=p.parse_args(argv);settings=json.loads(args.config.read_text())
    if args.repeat is not None:settings['cycle'].update(repeat_count=args.repeat,repeat_count_source='USER_CLI_OVERRIDE')
    bundle,plan=prepare_files(ROOT,settings);plan['sources']=dict(cycle_settings=source(args.config))
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'preview.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    for key,geometry in [('seating_plan','seating_geometry'),('removal_plan','partial_geometry'),('recovery_plan','completion_geometry')]:
        if geometry in plan[key]:save_plot([plan[key][geometry]],args.output/(key+'-path.png'))
    if not args.execute:
        print(json.dumps({key:plan[key] for key in ('status','execution_ready','repeat_count','missing_measurements','physical_commands')},ensure_ascii=False,indent=2));return 0
    if not plan['execution_ready']:p.error('실측·앞 단계 실제 run·검토·해제 관찰 검증·회수 자료가 필요합니다. preview 누락 항목을 확인하세요.')
    if not all((args.confirm_hand_clear,args.confirm_route_clear,args.confirm_target_empty)):
        p.error('--confirm-hand-clear --confirm-route-clear --confirm-target-empty required')
    run_session(bundle,plan,args.output,args.start_zone);return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('시험 종료 / 자동 재시도·개방 없음',flush=True);raise SystemExit(130)
