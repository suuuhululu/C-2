"""Empty-board D/B experiment: frozen random slots, five layers, real B gates.

This is a standalone equipment test, separate from the C-approved fixed 3-Step.
Preview is the default. Only an explicitly reviewed run opens any device.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from queue import Empty, Queue
import random
import signal
from threading import Event
from types import SimpleNamespace
import time
from uuid import uuid4

from app.round3_approved_step import digest, load_initial_capture, same_blocks
from app.round3_initial_inspection import DEFAULT, ROOT, load_settings, open_motion, run_initial
from app.round3_live_inspection import LiveInspectionObserver
from app.round3_stack_review import recover_initial_home, review_checkbox
from perception.perception_mvp.team_connection import connect_inspection

PROFILE = ROOT / 'robot_control_integration/settings/round3_b_three_step_20261015/profile.json'
LAST_PLAN = ROOT / 'logs/stack-five-last-plan.txt'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


def native():
    # Both repositories use `app`; retain root B contracts and append native D.
    import app
    import sys
    path = ROOT / 'robot_control_integration'
    if str(path / 'app') not in app.__path__:
        app.__path__.append(str(path / 'app'))
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    from scripts import round2_three_step_trial
    return round2_three_step_trial


def build(seed, x=13, y=11, profile=PROFILE):
    """Same minimum-stud anchor, not an off-grid common geometric centre."""
    if type(seed) is not int or type(x) is not int or type(y) is not int or not (0 <= x <= 22 and 0 <= y <= 21):
        raise ValueError('INTEGER_SEED_AND_IN_BOARD_STACK_ANCHOR_REQUIRED')
    native()
    from app.supply_stud.execution_profile import load
    registry = load(profile)
    eligible = sorted((r for r in registry['slots'] if r['slot_id'].startswith(('blue_', 'yellow_'))
                       and any('_' + kind + '_' in r['slot_id'] for kind in ('2x2x1', '2x3x1'))),
                      key=lambda r: r['slot_id'])
    if len(eligible) != 20:
        raise ValueError('EXACTLY_20_FOUR_OR_SIX_STUD_SLOTS_REQUIRED')
    rows = random.Random(seed).sample(eligible, 5)
    cases = []
    for i, row in enumerate(rows):
        color, kind, slot = row['slot_id'].split('_')
        target = dict(brick_type=kind, color=color, x=x, y=y, layer=i+1, orientation_deg=0)
        support = i > 0 and kind == '2x3x1' and cases[-1]['target']['brick_type'] == '2x2x1'
        case = dict(step_id=f'STACK{i+1:02d}', target=target, supply_slot=int(slot),
                    human_hold=support, hold_lower=deepcopy(cases[-1]['target']) if support else None)
        # Preserve the newer recorded pickup for the already commissioned slot.
        if row['slot_id'] == 'yellow_2x2x1_04':
            case['operator_pickup_file'] = str(Path(profile).parent/'teaching/T1-preclose.json')
        cases.append(case)
    scenario = dict(preplaced=[], steps=cases, free_motion_speed_scale=2.)
    return scenario, prepare_scenario(scenario, profile)


def prepare_scenario(scenario, profile=PROFILE):
    """Bind explicit A-selected cases to the same registered native settings."""
    scenario=deepcopy(scenario)
    for case in scenario['steps']:
        if (case['target']['color'],case['target']['brick_type'],case['supply_slot'])==('yellow','2x2x1',4):
            case.setdefault('operator_pickup_file',str(Path(profile).parent/'teaching/T1-preclose.json'))
    trial = native()
    from app.supply_stud.execution_profile import load, bind
    from app.supply_stud.depth_center import load_profile
    registry = load(profile)
    by_id = {r["slot_id"]: r for r in registry["slots"]}
    rows = [by_id[f"{c['target']['color']}_{c['target']['brick_type']}_{c['supply_slot']:02d}"]
            for c in scenario['steps']]
    prepared = trial.prepare(scenario)
    for row, item in zip(rows, prepared):
        cfg = item['config']
        if row['execution_mode'] == 'TEACHING_ONLY':
            cfg['blocks'][0]['pickup_pose'] = deepcopy(row['pickup_pose'])
        if row['slot_id'] == 'blue_2x3x1_03':
            # Start with the correctly bound recorded T2, then transfer its grasp
            # relation by the existing measured board/layer model. Never present
            # another target to apply_teaching as the original measured target.
            from app.round2_operator_teaching import retarget_assembly_reference
            from app.cad_trial import measured_inputs, step_geometry
            canonical_scenario = trial.read(trial.DEFAULT)
            canonical_scenario['free_motion_speed_scale'] = 2.
            recorded = next(p['config'] for p in trial.prepare(canonical_scenario)
                            if p['case']['step_id'] == 'T2')
            target = recorded['alignment_target']['target']
            _, nominal, _, _ = step_geometry(measured_inputs(ROOT/'robot_control_integration'),
                dict(after=target,step_id='T2',operation='PLACE',before=None,prerequisites=[],requires_delivery=True),
                dict(grip_axis='x'),3)
            old = nominal['steps']['cad/T2']['reference_pose']
            goal = cfg['alignment_target']['placement_tcp_reference']
            source = recorded['alignment_target']['placement_tcp_reference']
            landing = [source[j]+goal[j]-old[j] for j in range(3)]+source[3:]
            cfg = retarget_assembly_reference(recorded, landing)
            cfg['trial_step'] = deepcopy(item['case'])
            cfg['alignment_target']['target'] = deepcopy(item['case']['target'])
            cfg['operator_teaching']['retargeted_to'] = deepcopy(item['case']['target'])
            cfg['operator_teaching']['retargeted_pose_physically_verified'] = False
            cfg['alignment_use_recorded_attitude'] = True
        cfg = bind(cfg, profile)
        cfg.update(press_control='POSITION_DESCENT_REACTION_STOP',press_force_target_n=None,
                   press_force_stop_n=60.,press_force_abort_n=70.,seating_velocity=3.,press_velocity=3.)
        cfg['seating_force_stop_n'] = 50.
        if cfg['vision'].get('depth_center_profile'):
            cfg['vision'].update(defer_depth_evidence=True,defer_depth_pose_validation=True)
            load_profile(cfg['vision']['depth_center_profile'], cfg['vision']['layout'], cfg)
        item['config'] = cfg
    return prepared


def freeze(seed, x, y, profile, destination):
    scenario, prepared = build(seed, x, y, profile)
    sources = {}
    for path in [Path(profile), DEFAULT, Path(__file__), ROOT/'app/round3_stack_review.py',
                 ROOT/'app/round3_stack_hmi.py', ROOT/'app/cad_trial.py',
                 ROOT/'app/round3_approved_step.py',
                 ROOT/'robot_control_integration/scripts/round2_three_step_trial.py',
                 ROOT/'robot_control_integration/scripts/supply_pick_release_trial.py',
                 ROOT/'robot_control_integration/scripts/held_corner_stud_trial.py',
                 ROOT/'robot_control_integration/scripts/held_xy_seating_trial.py',
                 ROOT/'robot_control_integration/scripts/assembly_press_trial.py',
                 ROOT/'robot_control_integration/scripts/assembly_position_trial.py',
                 ROOT/'robot_control_integration/app/assembly_contact_alignment.py',
                 ROOT/'robot_control_integration/app/assembly_motion_ros.py',
                 ROOT/'robot_control_integration/interfaces/assembly_contact_trial.json',
                 ROOT/'perception/perception_mvp/assembly_roi.py',
                 ROOT/'perception/perception_mvp/backend_adapter.py',
                 ROOT/'perception/perception_mvp/contracts.py',
                 ROOT/'perception/perception_mvp/inspection.py',
                 ROOT/'perception/perception_mvp/depth_grid.py',
                 ROOT/'perception/perception_mvp/main.py',
                 ROOT/'perception/perception_mvp/region_evidence.py',
                 ROOT/'perception/perception_mvp/yolo_pipeline.py',
                 ROOT/'perception/perception_mvp/config.yaml',
                 ROOT/'perception/calibration/assembly_runtime_pitch16_flat0_20261013.json',
                 *[sorted((ROOT/'perception/recordings/assembly_board_roi'/view).glob('*/assembly_roi.json'))[-1]
                   for view in ('V0','D1','D3')]]:
        sources[str(path.resolve())] = sha256(path.read_bytes()).hexdigest()
    document = dict(schema_version='round3-empty-stack-five/1', experiment_id=str(uuid4()),
        seed=seed, anchor=[x,y], anchor_basis='MINIMUM_OCCUPIED_STUD_ZERO_BASED',
        execution_profile=str(Path(profile).resolve()), scenario=scenario,
        configs_sha256=[digest(p['config']) for p in prepared], source_sha256=sources,
        press_control='POSITION_DESCENT_REACTION_STOP',press_force_target_n=None,
        press_force_stop_n=60.,press_force_abort_n=70.,
        seating_force_stop_n=50.,contact_velocity_mm_s=3.,
        b_required=True, C_A_service_approval=False, physical_validation='NOT_RUN')
    save(destination, document)
    return document


def validate(document):
    if document.get('schema_version') != 'round3-empty-stack-five/1' or document.get('b_required') is not True:
        raise ValueError('FROZEN_STACK_FIVE_PLAN_REQUIRED')
    for name, expected in document['source_sha256'].items():
        if sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('STACK_SOURCE_CHANGED: '+name)
    scenario, prepared = build(document['seed'], *document['anchor'], document['execution_profile'])
    if scenario != document['scenario'] or [digest(p['config']) for p in prepared] != document['configs_sha256']:
        raise ValueError('STACK_PLAN_OR_CONFIG_CHANGED')
    return prepared


def execute_step(item, directory, record, settings, review, cancelled):
    trial = native()
    cfg = item['config']
    with open_motion(settings, cancelled) as motion:
        motion.raw.config['timing'].update(service_timeout_s=3., stopped_sample_retry_window_s=5.)
        motion.raw.feedback_record=record
        try:
            motion.confirm(item['case']['step_id'], 'HOME', dict(settings, route_reviewed=True), review,
                           allow_move=False)
            def support(config):
                lower=config['trial_step']['hold_lower']
                return trial.support_dialog('Stack five - support ready',[
                    f"{config['trial_step']['step_id']}: HOLD lower {lower['color']} {lower['brick_type']}",
                    f"Grid ({lower['x']},{lower['y']}) / layer {lower['layer']}",
                    'Keep holding through seating, release, press and rise.',
                    'ENTER: ready / ESC: hold'])
            return trial.run_sequence(motion.raw, [item], directory, record, observe_cycle=trial.held.observe,
                support_ready=support,
                support_finished=lambda:trial.support_dialog('Stack five - support finished',[
                    'Press and vertical rise finished.', 'Release support and clear the HOME route.',
                    'ENTER: continue / ESC: hold']),
                step_ready=None, home_after_step=lambda d,c,r:trial.trial_return_home(d,c,r,review))
        except BaseException as failure:
            try:
                motion.raw.stop()
            except Exception as stop_error:
                record('STOP_FAILED', dict(original_reason=str(failure), stop_reason=str(stop_error),
                                          actual_stop_verified=False))
            raise


def run_stack(document, directory, settings, cancelled, *, initial=run_initial,
              execute=execute_step, observer_factory=LiveInspectionObserver,
              confirm_step=None, timeout_s=900., review_failure=None,
              recover_home=recover_initial_home, on_event=None):
    """Actual B results remain intact; explicit test reviews may advance D only."""
    prepared = validate(document)
    directory = Path(directory).resolve()
    if not directory.is_relative_to(ROOT/'logs'):
        raise ValueError('STACK_LOGS_MUST_STAY_UNDER_CHECKOUT')
    directory.mkdir(parents=True, exist_ok=False)
    review = 'OPERATOR_STACK_FIVE_'+document['experiment_id']
    result = dict(status='HOLD', native_completed=[], b_confirmed=[], current=None,
                  operator_reviews=[], initial_b_confirmed=False, final_b_confirmed=False,
                  reason=None, physical_completion=False, output_directory=str(directory))
    connection = None
    def record(event, data):
        with (directory/'events.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(event=event,data=data,unix_s=time.time()),ensure_ascii=False,allow_nan=False)+'\n')
        if event in ('STACK_STEP_BEGIN','STACK_B_RESULT','STOP_FAILED'):
            print(event,json.dumps(data,ensure_ascii=False),flush=True)
        if on_event is not None and event in ('STACK_INITIAL_BEGIN','STACK_INITIAL_RESULT',
                'STACK_STEP_BEGIN','STACK_NATIVE_FINISHED','STACK_B_BEGIN','STACK_B_RESULT',
                'STACK_OPERATOR_REVIEW','STACK_HOLD','STACK_FINAL_NOT_CONFIRMED','STACK_FINISHED'):
            on_event(event,deepcopy(data))
    try:
        # Exclusive claim before any INITIAL motion. A failed run is never resumed
        # by reissuing the same plan, even if the saved result is incomplete.
        save(Path(document['_plan_path']).with_suffix('.claimed.json'),dict(experiment_id=document['experiment_id']))
        # INITIAL closes its own observer by setting its cancellation token even
        # on success. That cleanup must not cancel this outer five-Step run.
        initial_closed = Event()
        initial_token = SimpleNamespace(is_set=lambda:cancelled.is_set() or initial_closed.is_set(),
                                        set=initial_closed.set)
        record('STACK_INITIAL_BEGIN',dict(experiment_id=document['experiment_id']))
        first = initial(settings, directory/'initial', review_ref=review, cancelled=initial_token)
        save(directory/'initial-attempt.json',first)
        record('STACK_INITIAL_RESULT',first)
        if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
        if (first['status'] != 'INITIAL_CAPTURED_HOME_RETURNED'
                or not all(first.get(k) is True for k in ('home_return_verified','actual_stop_verified','writer_released'))):
            record('STACK_INITIAL_FAILED', first)
            # Only this known B coverage failure is reviewable. Controller/STOP,
            # writer and archive binding failures are never checkbox exceptions.
            eligible = (first.get('current') is None and 'INITIAL_STATE_UNAVAILABLE' in str(first.get('reason'))
                and all(first.get(k) is True for k in ('actual_stop_verified','writer_released'))
                and not first.get('stop_error'))
            if not eligible or review_failure is None or review_failure('INITIAL',deepcopy(first),None) is not True:
                raise ValueError('EMPTY_INITIAL_FAILED: '+str(first.get('reason')))
            if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
            approval=dict(kind='INITIAL',basis='OPERATOR_VISUAL_EMPTY_BOARD_TEST_ONLY',
                approved_unix_s=time.time(),original_failure=deepcopy(first))
            result['operator_reviews'].append(approval)
            save(directory/'operator-initial-review.json',approval)
            record('STACK_OPERATOR_REVIEW',approval)
            home=recover_home(settings,review,cancelled,record)
            save(directory/'operator-initial-home.json',home)
            if not all(home.get(k) is True for k in ('home_return_verified','actual_stop_verified','writer_released')):
                raise ValueError('OPERATOR_INITIAL_HOME_NOT_VERIFIED')
            # Explicit operator test baseline, never an INITIAL B result/Current.
            base=dict(current_revision=0,blocks=[])
            source=dict(captured_unix_s=approval['approved_unix_s'],basis=approval['basis'])
        else:
            if first['current']['blocks']:
                raise ValueError('INITIAL_BOARD_NOT_EMPTY')
            observed, source = load_initial_capture(first['initial_capture_directory'])
            if (observed['status'] != 'OK' or observed['visible_blocks']
                    or not 0 <= time.time()-source['captured_unix_s'] <= 300
                    or source['geometry_reference'] != settings['calibration_id']):
                raise ValueError('FRESH_REAL_EMPTY_INITIAL_REQUIRED')
            result['initial_b_confirmed']=True
            base=deepcopy(first['current'])
            result['current']=deepcopy(base)
        save(directory/'initial-source.json',source)
        progress_blocks=deepcopy(base['blocks'])
        steps = [dict(step_id=c['step_id'], operation='PLACE', before=None, after=deepcopy(c['target']),
                      prerequisites=[] if i==0 else [prepared[i-1]['case']['step_id']], requires_delivery=True)
                 for i,c in enumerate(document['scenario']['steps'])]
        design = dict(design_version=1, blocks=[s['after'] for s in steps])
        plan = dict(plan_id='STACK-'+document['experiment_id'], design_version=1,
                    base_current_revision=base['current_revision'], steps=steps)
        inbox = Queue()
        observer = observer_factory(ROOT, settings, directory/'b-checks', review)
        connection = connect_inspection(inbox.put, initial_current=base,
            geometry_reference=settings['calibration_id'],
            observe=lambda ctx,active:observer(ctx,lambda:active() and not cancelled.is_set()))
        if result['initial_b_confirmed']:
            from app.round3_approved_step import restore_initial_inspection
            restore_initial_inspection(connection,first['initial_capture_directory'],base)
        connection.load_plan(design,plan,base,geometry_reference=settings['calibration_id'])
        save(directory/'test-plan.json',dict(design=design,plan=plan,
            baseline_basis='B_INITIAL' if result['initial_b_confirmed'] else 'OPERATOR_VISUAL_EMPTY_BOARD_TEST_ONLY',
            provenance='EXPLICIT_D_B_EQUIPMENT_TEST_NO_C_A_APPROVAL'))
        def check(kind, step_id):
            request = dict(check_id=str(uuid4()),check_kind=kind,plan_id=plan['plan_id'],step_id=step_id)
            record('STACK_B_BEGIN',request)
            connection.request(request)
            deadline = time.monotonic()+timeout_s
            while not cancelled.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('STACK_B_CHECK_TIMEOUT')
                try: response=inbox.get(timeout=.1);break
                except Empty:continue
            else:raise KeyboardInterrupt('OPERATOR_STOP')
            if any(response[k]!=v for k,v in request.items()):
                raise ValueError('STACK_B_RESPONSE_ID_MISMATCH')
            save(directory/(request['check_id']+'.response.json'),response)
            record('STACK_B_RESULT',response)
            outcome = observer.outcomes.get(request['check_id'],{})
            if response.get('current') is not None:
                result['current']=deepcopy(response['current'])
            if not all(outcome.get(k) is True for k in ('home_return_verified','actual_stop_verified','writer_released')):
                raise ValueError('STACK_B_HOME_WRITER_NOT_VERIFIED')
            if response['status']!='OK' or response['comparison']!='MATCH':
                # Save the actual failure before asking. B Current, comparison
                # and confirmed-Step set are not replaced by the operator target.
                if kind=='STEP' and response['status'] in ('OK','UNOBSERVABLE','ERROR') and review_failure is not None:
                    target=next(s['after'] for s in steps if s['step_id']==step_id)
                    if review_failure(kind,deepcopy(response),deepcopy(target)) is True:
                        if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
                        approval=dict(kind=kind,step_id=step_id,check_id=request['check_id'],
                            basis='OPERATOR_VISUAL_STEP_TEST_ONLY',approved_unix_s=time.time(),
                            reviewed_prefix=[deepcopy(s['after']) for s in steps[:len(result['native_completed'])]],
                            original_failure=deepcopy(response))
                        save(directory/(request['check_id']+'.operator-review.json'),approval)
                        result['operator_reviews'].append(approval)
                        record('STACK_OPERATOR_REVIEW',approval)
                        return False
                raise ValueError('STACK_B_'+str(response['status'])+': '+str(response['comparison'])+' '+str(response.get('reason')))
            return response
        for i,item in enumerate(prepared):
            if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
            validate(document)
            if (confirm_step or native().trial_step_popup)(item['case'],i,5) is not True:
                raise KeyboardInterrupt('STEP_CONFIRMATION_CANCELLED')
            if cancelled.is_set():raise KeyboardInterrupt('OPERATOR_STOP')
            if i==0 and time.time()-source['captured_unix_s'] > 300:
                raise ValueError('INITIAL_EXPIRED_DURING_REVIEW')
            validate(document)
            if not same_blocks(progress_blocks,[s['after'] for s in steps[:i]]):
                raise ValueError('STACK_LATEST_B_PREFIX_MISMATCH')
            record('STACK_STEP_BEGIN',dict(index=i+1,total=5,case=item['case']))
            outcome = execute(item,directory/item['case']['step_id'],record,settings,review,cancelled)
            if (outcome.get('status')!='THREE_CYCLES_COMPLETED'
                    or outcome.get('completed_steps')!=[item['case']['step_id']]
                    or len(outcome.get('home_returns',[]))!=1
                    or outcome['home_returns'][0].get('stopped_verified') is not True):
                raise ValueError('STACK_NATIVE_INCOMPLETE_NO_B_OR_NEXT_PICKUP')
            result['native_completed'].append(item['case']['step_id'])
            record('STACK_NATIVE_FINISHED',dict(step_id=item['case']['step_id'],receipt=outcome))
            response=check('STEP',item['case']['step_id'])
            if response is not False:
                if not same_blocks(result['current']['blocks'],[s['after'] for s in steps[:i+1]]):
                    raise ValueError('STACK_B_MATCH_PREFIX_MISMATCH')
                result['b_confirmed'].append(item['case']['step_id'])
                progress_blocks=deepcopy(result['current']['blocks'])
            else:
                progress_blocks=[deepcopy(s['after']) for s in steps[:i+1]]
        if len(result['b_confirmed'])==5:
            check('FINAL',None)
            result['final_b_confirmed']=True
        else:
            result['reason']='FINAL_REQUIRES_ALL_STEP_MATCH; OPERATOR_REVIEWS_ARE_NOT_B_MATCH'
            record('STACK_FINAL_NOT_CONFIRMED',dict(reason=result['reason']))
        if result['operator_reviews']:
            result.update(status='FIVE_STEPS_EXECUTED_WITH_OPERATOR_REVIEW',physical_completion=False)
        else:
            result.update(status='FIVE_STEPS_AND_FINAL_MATCH',physical_completion=True)
    except (Exception,KeyboardInterrupt) as failure:
        result['reason']=str(failure) or 'OPERATOR_STOP'
        record('STACK_HOLD',dict(reason=result['reason'],automatic_retry=False))
    finally:
        if connection is not None:
            connection.close()
            # Do not exit while the observer may still hold the real D writer.
            connection._worker.join()
        save(directory/'result.json',result)
        record('STACK_FINISHED',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('preview','run','hmi'),nargs='?',default='preview')
    parser.add_argument('--seed',type=int)
    parser.add_argument('--x',type=int,default=13)
    parser.add_argument('--y',type=int,default=11)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--hmi-protocol',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--operator-b-review',action='store_true',
        help='Five-layer test only: offer unchecked operator review after eligible INITIAL/STEP B failures')
    for flag in ('execute','confirm-empty-board','confirm-empty-gripper','confirm-home-route-reviewed','confirm-hand-clear'):
        parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args(argv)
    if args.command=='hmi':
        from app.round3_stack_hmi import launch
        return launch(args)
    if args.command=='preview':
        folder=ROOT/'logs/stack-five'/str(uuid4());folder.mkdir(parents=True)
        path=folder/'plan.json'
        doc=freeze(args.seed if args.seed is not None else random.SystemRandom().randrange(2**32),args.x,args.y,PROFILE,path)
        LAST_PLAN.parent.mkdir(parents=True,exist_ok=True);LAST_PLAN.write_text(str(path)+'\n')
        print(json.dumps(dict(status='PREVIEW_NO_DEVICE_CONNECTION',physical_commands=0,plan=str(path),
            seed=doc['seed'],anchor=doc['anchor'],press_control=doc['press_control'],
            press_force_target_n=doc['press_force_target_n'],press_force_stop_n=doc['press_force_stop_n'],
            press_force_abort_n=doc['press_force_abort_n'],
            steps=doc['scenario']['steps']),ensure_ascii=False,indent=2))
        return 0
    if not all(getattr(args,k) for k in ('execute','confirm_empty_board','confirm_empty_gripper','confirm_home_route_reviewed','confirm_hand_clear')):
        parser.error('run requires --execute and explicit empty-board/gripper/HOME-route/hand-clear confirmations')
    import os
    if os.environ.get('ROS_DOMAIN_ID')!='20':parser.error('ROS_DOMAIN_ID20_REQUIRED')
    path=(args.plan or Path(LAST_PLAN.read_text().strip())).resolve()
    if path.with_suffix('.claimed.json').exists() or (path.parent/'run').exists():
        print(json.dumps(dict(status='HOLD',reason='PLAN_ALREADY_USED_CREATE_NEW_PREVIEW',
            previous_run=str(path.parent/'run'),physical_commands=0),ensure_ascii=False,indent=2))
        return 2
    doc=read(path);validate(doc);doc['_plan_path']=str(path)
    cancelled=Event()
    def interrupt(*_):
        cancelled.set();raise KeyboardInterrupt('OPERATOR_STOP')
    previous={s:signal.signal(s,interrupt) for s in (signal.SIGINT,signal.SIGTERM)}
    try:
        bridge=None
        if args.hmi_protocol:
            import sys
            from app.round3_stack_review import HmiProtocol
            bridge=HmiProtocol(sys.stdin,sys.stdout)
        result=run_stack(doc,path.parent/'run',load_settings(DEFAULT),cancelled,
            review_failure=(bridge.review if bridge else review_checkbox) if args.operator_b_review else None,
            confirm_step=bridge.step_ready if bridge else None,on_event=bridge.publish if bridge else None)
    finally:
        for s,handler in previous.items():signal.signal(s,handler)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status'] in ('FIVE_STEPS_AND_FINAL_MATCH','FIVE_STEPS_EXECUTED_WITH_OPERATOR_REVIEW') else 2


if __name__=='__main__':
    raise SystemExit(main())
