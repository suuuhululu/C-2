"""C 설계→A 계획→D 실물 시험 준비. 기본은 장치에 연결하지 않는다."""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
from queue import Empty
from threading import Event
import time
from uuid import uuid4

from app.supply_slots import next_supply_slot

from app.cad_trial import measured_inputs, read, step_document
from app.robot_process import RobotProcess
from planning_trial.assembly_optimizer import assess_step
from planning_trial.assembly_wire import normalize_action, pose_mm_zyz
from planning_trial.planner import plan_assembly_from_current


# Share the reviewed tolerances with execution: a completed move still reports
# small residual velocities, including when preparing the next supply slot.
REAL_STILLNESS_TOLERANCES = dict(linear_mm_s=5.,angular_deg_s=5.,position_mm=1.,orientation_deg=1.)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def start_retry_approval(directory):
    """이동 전 시작 검사에서 종료된 시험만 기존 C 승인을 재사용한다."""
    directory = Path(directory)
    result, approval = read(directory/'result.json'), read(directory/'c-review.json')
    events = [json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
    if (result.get('status') != 'HOLD' or result.get('reason') != 'OPEN_EMPTY_GRIPPER_REQUIRED'
            or result.get('completed_steps') != [] or approval.get('status') != 'OK'
            or approval.get('hri_result') != 'APPROVE' or not events
            or any(e['event'] not in ('PROCESS_READY','STATE_SNAPSHOT','TRIAL_RESULT') for e in events)
            or any(e['data'].get('physical_commands') != 0 for e in events if e['event']=='STATE_SNAPSHOT')):
        raise ValueError('ONLY_PRE_EXECUTION_GRIPPER_HOLD_CAN_REUSE_APPROVAL')
    return approval


def prepare(design, root):
    """전 Step 지원 여부를 먼저 확인하고 원본 실측 자료는 보존한다."""
    if not design.get('blocks') or any(not (
            b['color'] in ('yellow','blue') and b['brick_type'] in ('2x2x1','2x3x1')
            or b['color']=='red' and b['brick_type']=='1x2x1')
            or b['orientation_deg'] not in ((0,) if b['brick_type']=='2x2x1' else (0,90))
            for b in design['blocks']):
        raise ValueError('이번 실물 시험은 노랑/파랑 2×2·2×3, 빨강 1×2를 지원합니다. 2×2는 0°, 나머지는 0°/90°입니다.')
    inputs = measured_inputs(root)
    baseline = dict(current_revision=0, blocks=[])
    whole = plan_assembly_from_current(design, baseline, inputs['context'])
    if whole['status'] != 'CANDIDATE':
        raise ValueError('A 전체 계획 보류: '+str(whole.get('errors', whole['status'])))
    plan = whole['planning_result']['plan']
    assumed, slots, preview = deepcopy(baseline), {}, []
    axis = inputs['frame']['calculation_profiles']['assembly']['reference']['grip_axis_planner']
    for step in plan['steps']:
        evaluation = assess_step(design, plan, step['step_id'], assumed, inputs['context'])
        options = [o for o in evaluation.get('options', []) if o['mode'] == 'ROBOT_GRIP'
                   and o['assistance_kind'] == 'NONE']
        options.sort(key=lambda o:o['grip_axis'] != axis)
        if evaluation['status'] != 'CANDIDATE' or not options:
            raise ValueError(step['step_id']+': 사람 도움 없는 로봇 체결 방법이 없습니다.')
        action = normalize_action(options[0], plan, step, inputs['context'])
        column = step['after']['brick_type'], step['after']['color']
        slot = slots.get(column, 1)
        preview.append(dict(step=step, action=action, assessment=evaluation, slot=slot,
                            assumed=deepcopy(assumed)))
        assumed['blocks'].append(deepcopy(step['after']))
        assumed['current_revision'] += 1
        slots[column] = next_supply_slot(slot)
    return dict(design=deepcopy(design), inputs=inputs, plan=plan, whole=whole, preview=preview)


def live_robot_state(receipt, frame, *, now=None,empty_gripper_context=None):
    """실제 조회를 A 입력으로 변환한다. 가짜 정지/파지 응답을 만들지 않는다."""
    now = time.time() if now is None else now
    age = now-receipt.get('captured_unix_s', 0)
    samples = receipt.get('samples', [])
    if not 0 <= age <= .5 or len(samples) < 3 or receipt.get('physical_commands') != 0:
        raise ValueError('FRESH_READ_ONLY_STATE_REQUIRED')
    first = samples[0]
    from scipy.spatial.transform import Rotation
    for sample in samples:
        if sample['tcp'] != frame['tcp_setting_name'] or sample['tool'] != 'ToolWeight0':
            raise ValueError('TCP_TOOL_MISMATCH')
        values = sample['posx']+sample['velx']+[sample['query_duration_s'], sample['gripper_width_mm']]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('INVALID_DEVICE_SAMPLE')
        if not 0 <= sample['query_duration_s'] <= .5:
            raise ValueError('STALE_STOP_SAMPLE')
        if (sample['robot_state'] not in (1, 2) or sample['robot_mode'] != 1 or
                sample['drl_state'] != 3 or sample['motion_status'] != 0 or
                max(map(abs, sample['velx'][:3])) > REAL_STILLNESS_TOLERANCES['linear_mm_s'] or
                max(map(abs, sample['velx'][3:])) > REAL_STILLNESS_TOLERANCES['angular_deg_s']):
            raise ValueError('ROBOT_NOT_STOPPED_AND_READY')
        if not 0 <= sample['gripper_width_mm'] <= 110:
            raise ValueError('INVALID_GRIPPER_WIDTH_FEEDBACK')
        a = Rotation.from_euler('ZYZ', first['posx'][3:], degrees=True)
        b = Rotation.from_euler('ZYZ', sample['posx'][3:], degrees=True)
        if (math.dist(first['posx'][:3], sample['posx'][:3]) > REAL_STILLNESS_TOLERANCES['position_mm'] or
                (a.inv()*b).magnitude()*180/math.pi > REAL_STILLNESS_TOLERANCES['orientation_deg']):
            raise ValueError('START_POSE_NOT_STILL')
    # PREPARE_OPEN opens the empty gripper before any arm movement. Its >44mm
    # completion check belongs to D after that command, not to this start snapshot.
    closed_pad=(isinstance(empty_gripper_context,dict) and
        empty_gripper_context.get('state')=='EMPTY_PAD_CLOSED' and empty_gripper_context.get('gripper_status')==2)
    if any(sample['gripper_status'] != 0 and not (closed_pad and sample['gripper_status']==2) for sample in samples):
        raise ValueError('OPEN_EMPTY_GRIPPER_REQUIRED')
    sample = samples[-1]
    return dict(tcp_setting_name=frame['tcp_setting_name'], tcp_frame_id=frame['tcp_frame_id'],
        tcp_pose=pose_mm_zyz(sample['posx']), stopped_verified=True, holding_confirmed=False,
        active_command_count=0, pending_command_count=0)


def execution_document(prepared, row, state, *, review_ref, receipt_ref, start_zone):
    if not isinstance(review_ref, str) or not review_ref.strip() or not receipt_ref:
        raise ValueError('ACTUAL_OPERATOR_AND_STATE_REFS_REQUIRED')
    doc = step_document(prepared['inputs'], prepared['plan'], row['step'], row['action'],
                        row['assumed'], row['slot'], state)
    profile = doc['d_profile']
    profile.update(profile_id='D_CAD_OPERATOR_'+str(uuid4()), physical_route_reviewed=True,
                   operator_review_ref=review_ref, transport_policy='REVIEWED_HORIZONTAL_BLENDING')
    if profile.get('native_press'):
        profile['native_press']['review_ref'] = review_ref
    for settings in profile['steps'].values():
        settings['physical_reference_reviewed'] = True
        settings['operator_review_ref'] = review_ref
    session = doc['session']
    session['stillness'].update(REAL_STILLNESS_TOLERANCES)
    epoch = 'LIVE_CAD_'+str(uuid4())
    session.update(backend='REAL', provenance='LIVE_D_RUNTIME', source_epoch=epoch,
        profile_id=profile['profile_id'], exclusive_control_reviewed=True,
        device_feedback_reviewed=True, stillness_parameters_reviewed=True, hand_clear_reviewed=True,
        operator_review_ref=review_ref, trial_alignment_pending=True, alignment_evidence_ref=None)
    if profile.get('transport_blending'):
        session['transport_blend_review_ref'] = review_ref
    from scipy.spatial.transform import Rotation
    session['planned_start_pose'] = [v*1000 for v in state['tcp_pose']['xyz_m']]+list(
        Rotation.from_quat(state['tcp_pose']['quaternion_xyzw']).as_euler('ZYZ', degrees=True))
    step = doc['step']
    session['d_runtime'] = dict(sample_kind='LIVE_D_RUNTIME', source_epoch=epoch,
        execution_id=session['execution_id'], plan_id=step['plan_id'], step_id=step['step_id'],
        current_revision=None, profile_id=profile['profile_id'], valid_until_unix_s=session['expires_unix_s'],
        reassessment_ref=review_ref+'#'+step['step_id']+'/A-assessment', reassessed_block=step['block'],
        reassessed_mode=step['action']['mode'], reassessed_assistance_kind=step['action']['assistance_kind'],
        current_ref='ASSUMED_PLAN_PREFIX_NOT_B_CURRENT:'+str(doc['planned_state_sequence']),
        reservation_ref=review_ref+'#'+step['reservation']['reservation_id'],
        reservation_confirmed=True, slot_id=step['reservation']['slot_id'], start_pose_ref=receipt_ref)
    doc.update(fixture_kind='LIVE_OPERATOR_CAD_EXPERIMENT', start_zone=start_zone)
    doc['assessment_raw'] = row['assessment']
    return doc


def preview_routes(prepared):
    """표시용 가상 시작 상태. REAL 조회/실행 승인으로 재사용하지 않는다."""
    inputs = prepared['inputs']
    state = dict(tcp_setting_name=inputs['frame']['tcp_setting_name'],
        tcp_frame_id=inputs['frame']['tcp_frame_id'],
        tcp_pose=pose_mm_zyz(inputs['profile']['place_pose'][:2]
            +[inputs['profile']['clearance_z_mm']]+inputs['profile']['place_pose'][3:]),
        stopped_verified=True, holding_confirmed=False, active_command_count=0, pending_command_count=0)
    return [step_document(inputs, prepared['plan'], r['step'], r['action'], r['assumed'], r['slot'], state)
            for r in prepared['preview']]


class Trial:
    def __init__(self, root, directory, notify, *, execute=False, start_zone='assembly', gestures=False):
        self.root, self.directory = Path(root), Path(directory)/str(uuid4())
        self.notify, self.execute, self.start_zone = notify, execute, start_zone
        self.gestures = gestures
        self.cancelled, self.robot, self.prepared = Event(), None, None
        self.resume_requested, self.closing = Event(), Event()
        self.paused = False
        self.directory.mkdir(parents=True, exist_ok=True)
        self.result = dict(mode='REAL' if execute else 'PREPARE', status='PREPARING',
            completed_steps=[], b_called=False, vision_confirmed=False, assembly_completion=False)

    def record(self, event, data):
        if event in ('STOP_VERIFIED', 'STOP_UNVERIFIED'):
            self.result['actual_stop_verified'] = data['actual_stop_verified']
        with (self.directory/'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(event=event, data=data), ensure_ascii=False, allow_nan=False)+'\n')
        self.notify(event, data)

    def stop(self):
        self.cancelled.set()
        if self.robot is not None:
            try:
                self.robot.send('STOP')
            except RuntimeError as error:
                self.record('STOP_CHANNEL_FAILED', dict(reason=str(error), actual_stop_verified=False))

    def alignment(self, request_id):
        if self.robot is not None and not self.cancelled.is_set():
            try:
                self.robot.send('ALIGNMENT_CONFIRM', request_id=request_id, ready=True)
            except RuntimeError as error:
                self.record('ALIGNMENT_CHANNEL_FAILED', dict(reason=str(error)))

    def resume(self):
        if self.paused and not self.closing.is_set():
            self.resume_requested.set()

    def close(self):
        self.closing.set()
        self.stop()
        self.resume_requested.set()

    def run(self, design, review_ref):
        try:
            if self.cancelled.is_set():
                raise RuntimeError('STOP_REQUESTED')
            self.prepared = prepare(design, self.root)
            save(self.directory/'planning.json', {k:v for k,v in self.prepared.items() if k != 'inputs'})
            save(self.directory/'candidate-routes.json', preview_routes(self.prepared))
            if not self.execute:
                self.result['status'] = 'PREPARED_NO_DEVICE_CONNECTION'
                return
            if not review_ref:
                raise ValueError('ACTUAL_OPERATOR_PREPARATION_REVIEW_REQUIRED')
            config = self.root/'interfaces/assembly_contact_trial.json'
            with RobotProcess(self.root, mode='REAL', config=config, gestures=self.gestures) as robot:
                self.robot = robot
                for row in self.prepared['preview']:
                    if self.cancelled.is_set():
                        raise RuntimeError('STOP_REQUESTED')
                    receipt, state = self.wait_start_state(row['step']['step_id'])
                    state_ref = self.directory/(row['step']['step_id']+'.state.json')
                    save(state_ref, receipt)
                    doc = execution_document(self.prepared, row, state, review_ref=review_ref,
                        receipt_ref=str(state_ref), start_zone=self.start_zone if not self.result['completed_steps'] else 'assembly')
                    save(self.directory/(row['step']['step_id']+'.execution.json'), doc)
                    self.record('STEP_READY', dict(step=doc['step'], profile=doc['d_profile']))
                    robot.send('EXECUTE', document=doc)
                    self.wait_step(doc)
                    self.result['completed_steps'].append(row['step']['step_id'])
                    self.record('PREFIX_ASSUMED', dict(blocks=row['assumed']['blocks']+[row['step']['after']],
                        completed=len(self.result['completed_steps']), total=len(self.prepared['preview']),
                        basis='ASSUMED_PLAN_PREFIX_NOT_B_CURRENT'))
                self.result['status'] = 'TRIAL_EXECUTION_FINISHED'
        except Exception as error:
            self.result.update(status='HOLD', reason=str(error))
            if self.robot is not None and self.robot.process.poll() is None:
                self.robot.send('STOP')
        finally:
            self.robot = None
            save(self.directory/'result.json', self.result)
            self.record('TRIAL_RESULT', dict(self.result, directory=str(self.directory)))

    def next_event(self, deadline, *, allow_hold=False):
        while time.monotonic() < deadline:
            try:
                event = self.robot.receive(timeout=.1)
            except Empty:
                continue
            self.record(event['event'], event['data'])
            failures = ('COMMAND_REJECTED', 'CHANNEL_ERROR', 'PROCESS_EXITED') if allow_hold else (
                'COMMAND_REJECTED', 'EXECUTION_HELD', 'CHANNEL_ERROR', 'PROCESS_EXITED')
            if event['event'] in failures:
                raise RuntimeError(event['data'].get('reason', event['event']))
            return event
        raise TimeoutError('D_RESPONSE_TIMEOUT')

    def wait_state(self):
        deadline = time.monotonic()+15
        while True:
            if self.cancelled.is_set():
                raise RuntimeError('STOP_REQUESTED')
            event = self.next_event(deadline)
            if event['event'] == 'STATE_SNAPSHOT':
                return event['data']

    def wait_start_state(self, step_id):
        while True:
            self.robot.send('READ_STATE')
            receipt = self.wait_state()
            save(self.directory/(step_id+'.start-check.json'), receipt)
            try:
                state = live_robot_state(receipt, self.prepared['inputs']['frame'])
                return receipt, state
            except ValueError as error:
                if str(error) != 'OPEN_EMPTY_GRIPPER_REQUIRED':
                    raise
                # No EXECUTE has been sent. Keep the approved plan/process while
                # the operator clears a held/busy gripper, then read fresh state.
                self.paused = True
                self.resume_requested.clear()
                self.result.update(status='PAUSED', reason=str(error))
                save(self.directory/'result.json', self.result)
                self.record('TRIAL_PAUSED', dict(reason=str(error), step_id=step_id,
                    completed_steps=list(self.result['completed_steps']), resume_allowed=True,
                    stage='START_STATE', physical_commands_sent=False))
                try:
                    while not self.resume_requested.wait(.1):
                        if self.robot.process.poll() is not None:
                            raise RuntimeError('ROBOT_PROCESS_EXITED_WHILE_PAUSED')
                    if self.closing.is_set():
                        raise RuntimeError('TRIAL_CLOSED')
                    self.cancelled.clear()
                    self.result.update(status='RUNNING')
                    self.result.pop('reason', None)
                    self.record('TRIAL_RESUMING', dict(step_id=step_id, stage='START_STATE',
                        completed_steps=list(self.result['completed_steps']), c_review_repeated=False))
                finally:
                    self.paused = False

    def wait_step(self, doc):
        deadline = time.monotonic()+600
        while True:
            event = self.next_event(deadline, allow_hold=True)
            if event['event'] == 'EXECUTION_HELD':
                if event['data'].get('execution_id') != doc['session']['execution_id']:
                    raise RuntimeError('STALE_EXECUTION_HELD')
                if not event['data'].get('resume_allowed') or self.result.get('actual_stop_verified') is not True:
                    raise RuntimeError(event['data'].get('reason', 'D_RESUME_UNAVAILABLE'))
                self.paused = True
                self.resume_requested.clear()
                self.result.update(status='PAUSED', reason=event['data'].get('reason'))
                save(self.directory/'result.json', self.result)
                self.record('TRIAL_PAUSED', dict(reason=self.result['reason'], step_id=doc['step']['step_id'],
                    completed_steps=list(self.result['completed_steps']), resume_allowed=True))
                try:
                    while not self.resume_requested.wait(.1):
                        if self.robot.process.poll() is not None:
                            raise RuntimeError('ROBOT_PROCESS_EXITED_WHILE_PAUSED')
                    if self.closing.is_set():
                        raise RuntimeError('TRIAL_CLOSED')
                    self.cancelled.clear()
                    self.robot.send('READ_STATE')
                    receipt = self.wait_state()
                    identity = str(uuid4())
                    save(self.directory/(doc['step']['step_id']+'.resume.'+identity+'.state.json'), receipt)
                    doc = deepcopy(doc)
                    session = doc['session']
                    session.update(execution_id=identity, expires_unix_s=time.time()+600,
                        resume_current_revision=doc['step']['current_revision'],
                        trial_alignment_pending=True, alignment_evidence_ref=None)
                    session['d_runtime'].update(execution_id=identity, valid_until_unix_s=session['expires_unix_s'])
                    save(self.directory/(doc['step']['step_id']+'.resume.'+identity+'.json'), doc)
                    self.robot.send('RESUME', document=doc)
                    self.result.update(status='RUNNING')
                    self.result.pop('reason', None)
                    self.record('TRIAL_RESUMING', dict(step_id=doc['step']['step_id'], execution_id=identity,
                        completed_steps=list(self.result['completed_steps']), c_review_repeated=False))
                    deadline = time.monotonic()+600
                finally:
                    self.paused = False
                continue
            if event['event'] == 'TRIAL_STEP_EXECUTED':
                if self.cancelled.is_set() or event['data']['execution_id'] != doc['session']['execution_id']:
                    raise RuntimeError('STOP_OR_STALE_TRIAL_RESULT')
                return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-root', type=Path, required=True)
    parser.add_argument('--design', type=Path)
    parser.add_argument('--voice', action='store_true')
    parser.add_argument('--llm-context', action='store_true', help='고정 설계 본문을 C LLM 설명 함수에 전달한 뒤 승인받음')
    parser.add_argument('--execute', action='store_true', help='실제 장치 연결 및 실행을 명시적으로 허용')
    parser.add_argument('--gestures', action='store_true', help='엄지척 2초로 정렬 준비 응답, 편 손 1초로 정지 요청')
    parser.add_argument('--start-zone', choices=('assembly', 'place', 'supply'), default='assembly')
    parser.add_argument('--retry-start-directory', type=Path,
        help='이동 전 그리퍼 검사로 종료된 시험의 C 승인을 유지해 새 상태로 시작')
    parser.add_argument('--log-directory', type=Path, default=Path('logs/cad-real-trial'))
    args = parser.parse_args()
    args.approved_review = start_retry_approval(args.retry_start_directory) if args.retry_start_directory else None
    if args.voice and os.environ.get('C_DESIGN_USE_LLM') != '1':
        parser.error('--voice requires C_DESIGN_USE_LLM=1')
    if args.llm_context and (args.design is None or os.environ.get('C_DESIGN_USE_LLM') != '1'):
        parser.error('--llm-context requires --design and C_DESIGN_USE_LLM=1')
    if not args.voice and args.design is None:
        parser.error('--design or --voice required')
    from app.cad_trial_hmi import show
    return show(args)


if __name__ == '__main__':
    raise SystemExit(main())
