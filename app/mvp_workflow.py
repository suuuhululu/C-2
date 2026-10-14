"""최종 MVP의 D 진행부. 결과는 owning thread에서 채택하고 B의 비교를 중계한다."""
from copy import deepcopy
from uuid import uuid4
from collections import Counter

from app.contracts import validate_design
from app.hmi_contracts import validate_hmi_snapshot
from app.jsonl_log import JsonlLog
from app.mvp_calculation import whole_input, assessment_input, motion_input
from history.final_mvp import validate_response
from app.release_press_connection import (validate_a_message, review_a_result,
                                         release_press, validate_d_motion)
from planning_trial.planning_bundle import validate_planning_bundle


class MvpWorkflow:
    def __init__(self, emit, settings, log_directory, *, mode='FAKE'):
        if mode not in ('FAKE', 'REAL'):
            raise ValueError('explicit mode required')
        self.emit, self.settings, self.mode = emit, deepcopy(settings), mode
        self.record = JsonlLog(log_directory)
        self.log_failed = False
        self.log_directory = log_directory
        self.b = None
        self.job_id = None
        self.epoch = str(uuid4())
        self.generation = 0
        self.status, self.reason = 'IDLE', None
        self.current = dict(current_revision=0, blocks=[])
        self.approved = self.candidate = self.bundle = None
        self.dialogue = None
        self.whole = self.whole_result = self.step_inputs = None
        self.completed = []
        self.active = self.check = self.inspection = None
        self.robot_resume_allowed = True
        self.execution_id = self.execution = self.help = self.signal_request = None
        self.robot_status = 'IDLE'
        self.release_instruction = None
        self.change_pending = False
        self.change_request_id = str(uuid4())
        self.storage = self.web = 'NOT_STARTED'
        self.save_reason = None
        self.assembly = 'PENDING'
        self.retry_count = 0
        self.initial_purpose = 'START'
        self.robot_waiting = False
        self.await_robot_decision = False
        self.execution_closed = False
        self.last_execution_id = None
        self.accepted_checks = {}
        self.check_conflict = None
        self.stopped_call = None
        self.awaiting_revised_design = False
        self.stopped_from = None
        self.supply = [dict(brick_type=brick,color=color,next_slot=1,needs_refill=False)
            for brick,color in [('2x2x1','yellow'),('2x2x1','blue'),('2x3x1','yellow'),('2x3x1','blue'),('1x2x1','red')]]

    def event(self, name, result=None, *, request_id=None, plan_id=None, step_id=None, reason=None):
        if self.job_id is None:
            return True
        try:
            self.record(dict(job_id=self.job_id, plan_id=plan_id, step_id=step_id,
                request_id=request_id, event=name, result=deepcopy(result), reason=reason))
        except (OSError, ValueError) as error:
            self.status, self.reason = 'HOLD', f'LOG_FAILED: {error}'
            if not self.log_failed:
                self.log_failed = True
                self.emit('robot.STOP', {})
            return False
        return True

    def step(self):
        if self.bundle and len(self.completed) < len(self.bundle['plan']['steps']):
            return self.bundle['plan']['steps'][len(self.completed)]
        return None

    def call(self, port, payload):
        request = dict(deepcopy(payload), request_id=str(uuid4()))
        if port.startswith('c.'):
            self.dialogue=dict(request_id=request['request_id'],phase='LISTENING',user_text=None,
                               assistant_text=None,reason=None)
        self.active = dict(port=port, request=request, generation=self.generation,
                           current_revision=self.current['current_revision'])
        self.emit(port, request)
        return request

    def start(self):
        if self.status not in ('IDLE', 'COMPLETE'):
            return False
        if self.storage == 'PENDING':
            return False
        self.job_id = str(uuid4())
        self.log_failed = False
        self.generation += 1
        self.current = dict(current_revision=0, blocks=[])
        self.approved = self.candidate = self.bundle = None
        self.dialogue = None
        self.completed = []
        self.inspection = self.execution = self.help = self.signal_request = None
        self.release_instruction = None
        self.execution_id = None
        self.change_pending = self.robot_waiting = self.await_robot_decision = False
        self.execution_closed = False
        self.last_execution_id = None
        self.accepted_checks = {}
        self.check_conflict = self.stopped_call = None
        self.awaiting_revised_design = False
        self.storage = self.web = 'NOT_STARTED'
        self.save_reason = None
        self.assembly = 'PENDING'
        self.status, self.reason = 'PREPARING', None
        self.initial_purpose = 'START'
        if not self.event('JOB_STARTED'):
            return False
        self.request_check('INITIAL')
        return True

    def request_check(self, kind):
        step = self.step()
        self.check = dict(check_id=str(uuid4()), check_kind=kind,
            plan_id=self.bundle['plan']['plan_id'] if kind != 'INITIAL' else None,
            step_id=step['step_id'] if kind == 'STEP' else None)
        self.reason = f'B_{kind}_CHECK_PENDING'
        self.b.request(deepcopy(self.check))

    def receive_check(self, value):
        validate_response(value)
        result = deepcopy(value)
        previous = self.accepted_checks.get(result['check_id'])
        if previous is not None:
            if result == previous:
                self.event('CHECK_DUPLICATE_IGNORED', dict(response=result), request_id=result['check_id'])
            else:
                self.check_conflict = dict(original=deepcopy(previous), conflicting=result)
                self.event('CHECK_RESULT_CONFLICT', self.check_conflict, request_id=result['check_id'],
                           reason='CONFLICTING_CHECK_RESULT')
                if self.execution_id is not None and self.status != 'STOPPED':
                    self.stop()
                else:
                    self.active = None
                    if self.check:
                        self.b.cancel(self.check['check_id'])
                        self.check = None
                    self.status, self.reason = 'HOLD', 'CONFLICTING_CHECK_RESULT'
            return False
        accepted = bool(self.check and all(result[k] == self.check[k] for k in self.check)
                        and self.status != 'STOPPED' and self.reason != 'STOP_PENDING' and not self.check_conflict)
        logged = self.event('CHECK_RESULT', dict(response=result,
            disposition='ACCEPTED' if accepted else 'REJECTED',
            disposition_reason=None if accepted else 'CLOSED_OR_STALE_CHECK'),
            request_id=result['check_id'], plan_id=result['plan_id'], step_id=result['step_id'])
        if not accepted:
            return False
        self.check = None
        self.accepted_checks[result['check_id']] = deepcopy(result)
        self.inspection = deepcopy(result)
        if result['current'] is not None:
            self.current = deepcopy(result['current'])
        if not logged:
            return False
        if result['status'] in ('ERROR', 'CANCELED'):
            self.status, self.reason = 'HOLD', result['reason']
            if result['status'] == 'ERROR' and self.robot_waiting and result['check_kind'] == 'STEP':
                self.robot_inspection('ERROR')
            return True
        kind = result['check_kind']
        if kind == 'INITIAL':
            if result['status'] != 'OK':
                self.status, self.reason = 'HOLD', result['reason']
            else:
                if self.initial_purpose == 'RESUME' and self.stopped_call:
                    call = self.stopped_call
                    self.stopped_call = None
                    payload = deepcopy(call['request'])
                    payload.pop('request_id', None)
                    payload['current'] = deepcopy(self.current)
                    self.status = 'WAIT_INTENT'
                    self.call(call['port'], payload)
                elif self.initial_purpose == 'RESUME' and self.execution_id is not None:
                    if self.current != self.step_inputs['current']:
                        self.status,self.reason='HOLD','RESUME_CURRENT_CHANGED_REQUIRES_RECOVERY'
                    else:
                        self.execution_id=str(uuid4())
                        self.status='DELIVERING'
                        self.emit('robot.RESUME',dict(execution_id=self.execution_id,current=deepcopy(self.current)))
                elif self.approved is not None:
                    self.plan()
                else:
                    self.call('c.initial', dict(current=self.current))
            return True
        matched = (result['status'] == 'OK' and result['comparison'] == 'MATCH'
                   and not result['difference']['unobservable'])
        if not matched:
            self.status, self.reason = 'HOLD', result['reason'] or result['comparison']
            if kind == 'FINAL':
                self.assembly = result['comparison']
            if result['comparison'] == 'MISMATCH':
                if self.robot_waiting:
                    self.robot_inspection('CALL_C')
                self.open_intent('B_MISMATCH')
            elif self.robot_waiting:
                self.robot_inspection('UNOBSERVABLE')
            return True
        self.retry_count = 0
        if kind == 'STEP':
            self.completed.append(dict(step_id=result['step_id'], check_id=result['check_id'],
                observation_seq=result['observation']['observation_seq']))
            if self.robot_waiting:
                self.await_robot_decision = True
                self.robot_inspection('KEEP')
            else:
                self.after_step()
        else:
            self.assembly, self.status, self.reason = 'MATCH', 'COMPLETE', 'B_FINAL_MATCH'
            self.event('ASSEMBLY_COMPLETED', dict(final_check_id=result['check_id'],
                design_version=self.approved['design_version']), plan_id=result['plan_id'])
        return True

    def robot_inspection(self, decision):
        # Robot의 local KEEP는 B MATCH 수락이다. C KEEP와 별개다.
        self.emit('robot.INSPECTION', dict(result=dict(decision=decision, current=deepcopy(self.current),
            plan_id=self.inspection['plan_id'], step_id=self.inspection['step_id'],
            execution_id=self.execution_id, reason=self.inspection['reason'])))

    def after_step(self):
        self.last_execution_id = self.execution_id
        self.execution_id = None
        self.execution_closed = False
        self.robot_waiting = self.await_robot_decision = False
        self.execution = self.help = self.signal_request = None
        self.robot_status = 'IDLE'
        if self.change_pending:
            self.open_intent('USER_DESIGN_CHANGE')
        elif self.step() is None:
            self.status = 'WAIT_ASSEMBLY'
            self.event('PLAN_WORK_EXHAUSTED', plan_id=self.bundle['plan']['plan_id'])
            self.request_check('FINAL')
        else:
            self.calculate_next()

    def change_design(self):
        if not self.approved or self.status in ('IDLE', 'COMPLETE', 'STOPPED') or self.change_pending:
            return False
        self.change_pending = True
        self.change_request_id = str(uuid4())
        self.event('DESIGN_CHANGE_REQUESTED')
        if self.execution_id is None and self.check is None and self.active is None:
            self.open_intent('USER_DESIGN_CHANGE')
        return True

    def open_intent(self, reason):
        self.change_pending = False
        self.status, self.reason = 'WAIT_INTENT', reason
        self.call('c.intent', dict(design=self.approved, current=self.current,
            expected=self.inspection['expected'] if self.inspection else None,
            difference=self.inspection['difference'] if self.inspection else None,
            observation=self.inspection['observation'] if self.inspection else None, reason=reason))

    def preview_ready(self, identity):
        if not self.candidate or self.candidate['request_id'] != identity or self.reason == 'STOP_PENDING':
            return False
        if self.candidate['phase'] != 'PREVIEW':
            return False
        self.candidate['phase'] = 'REVIEW'
        self.call('c.review', dict(candidate=self.candidate['design'],
            kind=self.candidate['kind'], previous_design=self.approved, current=self.current,
            difference=self.inspection['difference'] if self.inspection else None,
            change_reason=self.candidate.get('change_reason'),
            design_metadata=deepcopy(self.candidate.get('design_metadata')),
            planning_failure=deepcopy(self.candidate.get('planning_failure'))))
        return True

    def receive(self, port, request_id, result):
        active = self.active
        if (not active or port != active['port'] or request_id != active['request']['request_id']
                or active['generation'] != self.generation or self.reason == 'STOP_PENDING'
                or self.status == 'STOPPED' or active['current_revision'] != self.current['current_revision']):
            self.event('LATE_RESULT_IGNORED', request_id=request_id)
            return False
        self.active = None
        if not self.event('MODULE_RESULT', dict(port=port, response=result), request_id=request_id):
            return False
        if port.startswith('c.'):
            accepted = self.receive_c(port, result, request=active['request'])
            # 같은 기존 요청의 완성 후보를 기다린다. STOP은 이 요청을 닫는다.
            if self.awaiting_revised_design:
                self.active = active
            return accepted
        if port == 'd.release_press':
            validate_d_motion(result, self.step_inputs['request'], self.step_inputs['d_profile'])
        else:
            validate_a_message(result)
        if result.get('context') != active['request']['input']['context'] or result.get('execution_allowed') is not False:
            self.status, self.reason = 'HOLD', 'A_RESULT_CONTEXT_OR_PERMISSION_DIFFERS'
            return False
        if port == 'a.whole':
            plan = result.get('planning_result')
            if not plan or plan['status'] != 'READY':
                errors = result.get('stage_errors') or (plan or {}).get('errors') or []
                self.reason = str(errors or result.get('calculation_status'))
                codes = {e.get('code') or e.get('reason') for e in errors}
                if result.get('calculation_status') == 'NO_FEASIBLE_ORDER' or 'NO_FEASIBLE_ORDER' in codes:
                    self.status = 'WAIT_INTENT'
                    self.call('c.plan_failure', dict(design=self.approved, current=self.current,
                        calculation_result=result,reason='현재 설계로 조립 가능한 순서를 찾지 못했습니다.',
                        planning_failure=dict(failure_code='NO_FEASIBLE_ORDER',redesign_required=True,
                            retryable=False,detail=str(errors))))
                elif plan and plan['status'] == 'NEEDS_CORRECTION':
                    self.status = 'WAIT_CORRECTION'
                else:
                    self.status = 'HOLD'
                return True
            self.whole_result = deepcopy(result)
            self.bundle = validate_planning_bundle(result['shared_planning_bundle'])
            if self.bundle['plan_base_current'] != self.current or self.bundle['design'] != self.approved:
                raise ValueError('A bundle does not match requested B Current/Approved Design')
            self.b.load_plan(self.bundle['design'], self.bundle['plan'], self.bundle['plan_base_current'],
                             geometry_reference=self.b.geometry_reference)
            self.completed = []
            self.inspection = self.execution = self.help = None
            self.assembly = 'PENDING'
            self.event('PLAN_ADOPTED', dict(design=self.bundle['design'], plan=self.bundle['plan'],
                base_current=self.bundle['plan_base_current'], confirmed_steps=[]), plan_id=self.bundle['plan']['plan_id'])
            self.event('SHARED_PLANNING_BUNDLE', self.bundle, plan_id=self.bundle['plan']['plan_id'])
            self.execution_id = None
            if self.change_pending:
                self.open_intent('USER_DESIGN_CHANGE')
            elif self.step() is None:
                self.after_step()
            else:
                self.calculate_next()
        elif port == 'a.assess':
            if review_a_result(result, active['request']['input'])['decision']!='STORE_FOR_REVIEW':
                self.status,self.reason='HOLD','A_ASSESSMENT_REFERENCE_DIFFERS'
                return False
            if result['status'] != 'CANDIDATE':
                self.status, self.reason = 'HOLD', str(result['errors'])
                return True
            self.step_inputs['assessment'] = deepcopy(result)
            self.step_inputs['request'] = motion_input(self.step_inputs['assessment_request'], result,
                self.step_inputs['frame_profile'], self.step_inputs['slot'], self.step_inputs['robot_state'])
            action = result['action_proposal']
            port = 'd.release_press' if release_press(action) else 'a.motion'
            payload = dict(input=self.step_inputs['request'])
            if port == 'd.release_press':
                payload['d_profile'] = deepcopy(self.step_inputs['d_profile'])
            self.call(port, payload)
        elif port in ('a.motion', 'd.release_press'):
            request = self.step_inputs['request']
            if ((port == 'a.motion' and review_a_result(result, request)['decision'] != 'STORE_FOR_REVIEW')
                    or result['status'] != 'CANDIDATE'):
                self.status, self.reason = 'HOLD', str(result.get('errors'))
                return True
            self.step_inputs['motion'] = deepcopy(result)
            self.step_inputs['motion_source'] = 'D_PROFILE' if port == 'd.release_press' else 'A_STEP_MOTION'
            if self.change_pending:
                self.open_intent('USER_DESIGN_CHANGE')
                return True
            self.status, self.reason = 'DELIVERING', None
            self.robot_status = 'BUSY'
            self.execution_id = str(uuid4())
            self.emit('robot.EXECUTE', dict(bundle=deepcopy(self.step_inputs), execution_id=self.execution_id))
        return True

    def receive_c(self, port, result, *, request=None):
        if result.get('status') != 'OK':
            self.status, self.reason = 'HOLD', str(result.get('error'))
            if self.dialogue:self.dialogue.update(phase='FAILED',reason=self.reason)
            return True
        decision = result.get('hri_result')
        allowed = {'c.initial':(None,), 'c.review':('APPROVE','MODIFY','UNCLEAR'),
                   'c.intent':('KEEP','REVISE','UNCLEAR'),'c.plan_failure':('KEEP','REVISE','UNCLEAR')}
        if decision not in allowed[port]:
            raise ValueError('C decision does not match active call')
        if self.dialogue:
            self.dialogue['phase']='SPEAKING'
            self.dialogue['assistant_text']=('표시한 설계를 승인했습니다.' if decision=='APPROVE' else
                '\n'.join(result.get('questions') or []) or '새 설계를 미리보기에 표시합니다.')
        if decision == 'REVISE' and result.get('design') is None:
            self.awaiting_revised_design = True
            self.status, self.reason = 'WAIT_INTENT', 'DESIGN_CHANGE_PENDING'
            if self.dialogue:self.dialogue['phase'] = 'GENERATING'
            return True
        self.awaiting_revised_design = False
        if port == 'c.initial' or decision in ('REVISE','MODIFY'):
            design = validate_design(result['design'])
            if self.approved:
                key=lambda b:tuple(sorted(b.items()))
                if design['design_version']!=self.approved['design_version']+1 or Counter(map(key,self.current['blocks']))-Counter(map(key,design['blocks'])):
                    raise ValueError('Revised Design must advance version and preserve B Current')
            self.candidate = dict(request_id=str(uuid4()), phase='PREVIEW', design=design,
                kind='revised' if self.approved else 'initial',
                design_metadata=deepcopy(result.get('design_metadata')),
                planning_failure=deepcopy((request or {}).get('planning_failure')),
                change_reason=self.reason if self.inspection is None or not self.inspection['difference'] or
                not (self.inspection['difference']['missing'] or self.inspection['difference']['unexpected']) else None)
            self.status = 'WAIT_INTENT' if self.bundle else 'PREPARING'
        elif decision == 'APPROVE':
            if self.candidate is None or self.candidate['phase'] != 'REVIEW' or result['design'] != self.candidate['design']:
                raise ValueError('C approval must match displayed candidate')
            self.approved = validate_design(result['design'])
            self.candidate = None
            self.plan()
        elif decision == 'KEEP':
            # 같은 입력으로 실패한 계획을 재요청하면 동일 질문으로 돌아온다.
            self.candidate = None
            if port == 'c.plan_failure':
                self.status = 'HOLD'
                notice = '승인 목표를 유지합니다. 계획 생성이 불가능해 실행을 보류합니다. 설계 변경 요청으로 수정할 수 있습니다.'
                if self.dialogue:
                    self.dialogue.update(phase='FAILED', assistant_text=notice, reason=self.reason)
                self.event('PLAN_FAILURE_KEPT', dict(design_version=self.approved['design_version'],
                    current_revision=self.current['current_revision']), reason=self.reason)
            else:
                # 실제 배치 차이에서의 목표 유지는 새 Current로 재계획한다.
                self.plan()
        elif decision == 'UNCLEAR':
            if port == 'c.plan_failure':
                # C already asked its follow-up question. Starting a fresh C call
                # here resets that limit and embeds the old questions in the next one.
                self.status,self.reason='HOLD','PLAN_FAILURE_RESPONSE_UNCLEAR'
                if self.dialogue:
                    self.dialogue.update(phase='FAILED',reason=self.reason,
                        assistant_text='답변을 명확히 확인하지 못해 보류합니다. 설계 변경 요청에서 다시 진행할 수 있습니다.')
                self.event('PLAN_FAILURE_UNCLEAR',dict(design_version=self.approved['design_version'],
                    current_revision=self.current['current_revision'],questions=result.get('questions',[])))
                return True
            self.status, self.reason = 'WAIT_INTENT', '\n'.join(result.get('questions', []))
            payload=dict(design=self.approved, current=self.current,
                expected=self.inspection['expected'] if self.inspection else None,
                difference=self.inspection['difference'] if self.inspection else None, reason=self.reason)
            if self.candidate:
                payload.update(candidate=self.candidate['design'],kind=self.candidate['kind'],
                    previous_design=self.approved,change_reason=self.candidate.get('change_reason'),
                    design_metadata=deepcopy(self.candidate.get('design_metadata')),
                    planning_failure=deepcopy(self.candidate.get('planning_failure')))
            self.call(port,payload)
        return True

    def plan(self):
        self.generation += 1
        self.assembly = 'PENDING'
        self.status = 'REPLANNING' if self.bundle else 'PREPARING'
        self.whole = whole_input(self.approved, self.current, self.settings,
                                  self.job_id, self.generation, self.epoch)
        self.call('a.whole', dict(input=self.whole))

    def calculate_next(self):
        self.status, self.reason = 'REPLANNING', None
        self.inspection = self.execution = self.help = None
        self.emit('d.prepare_step', dict(step=deepcopy(self.step()), current=deepcopy(self.current),
            generation=self.generation, plan_id=self.bundle['plan']['plan_id']))

    def prepared_step(self, inputs):
        if (self.reason == 'STOP_PENDING' or self.status != 'REPLANNING' or
                inputs['current'] != self.current or inputs['step'] != self.step() or
                inputs['generation'] != self.generation):
            return False
        self.step_inputs = deepcopy(inputs)
        frame = inputs['frame_profile']
        request = assessment_input(self.whole, self.whole_result, self.current, len(self.completed), frame)
        # STOP closes the old generation; the preserved Plan still uses fresh requests/reservations.
        request['context']['workflow_generation'] = self.generation
        self.step_inputs['assessment_request'] = request
        self.call('a.assess', dict(input=request))
        return True

    def robot_event(self, value):
        event, data = value['event'], value['data']
        if event=='COMMAND_REJECTED' and data.get('command') in ('SIGNAL','OPERATOR_CONFIRM') and data.get('reason') in ('NO_ACTIVE_SIGNAL_REQUEST','STALE_SIGNAL'):
            self.event('LATE_GESTURE_IGNORED',data)
            return False
        stopped_idle_execution = (event == 'STOP_VERIFIED' and self.reason == 'STOP_PENDING'
            and self.execution_id is None and data.get('previous_state') == 'IDLE'
            and data.get('execution_id') == self.last_execution_id)
        if data.get('execution_id') and data['execution_id'] != self.execution_id and not stopped_idle_execution:
            return False
        if not self.event('ROBOT_'+event, data, request_id=data.get('execution_id')):
            return False
        if event == 'STOP_ACCEPTED':
            return True  # ACK is not physical stop proof.
        if event == 'STOP_VERIFIED' and data.get('actual_stop_verified'):
            self.status, self.reason, self.robot_status = 'STOPPED', 'STOP_CONFIRMED', 'STOPPED'
            if self.execution_closed or data.get('previous_state') == 'WAIT_C':
                self.last_execution_id = self.execution_id
                self.execution_id = None
                self.execution = None
                self.robot_waiting = False
            if self.check_conflict:
                self.status, self.reason = 'HOLD', 'CONFLICTING_CHECK_RESULT'
        elif event == 'STOP_IDLE' and self.mode == 'FAKE' and self.execution_id is None:
            self.status, self.reason, self.robot_status = 'STOPPED', 'NO_MOCK_MOTION_PENDING', 'STOPPED'
            if self.check_conflict:
                self.status, self.reason = 'HOLD', 'CONFLICTING_CHECK_RESULT'
        elif event == 'EXECUTION_HELD':
            self.robot_resume_allowed=data.get('resume_allowed',True)
            if not self.robot_resume_allowed:self.status='HOLD'
            if data.get('status')=='RECOVERY_REQUIRED' or self.status!='STOPPED':
                self.reason=data.get('reason') or 'EXECUTION_HELD'
                if self.status!='STOPPED':self.status='HOLD'
        elif event in ('STOP_UNVERIFIED', 'COMMAND_REJECTED', 'CHANNEL_ERROR'):
            if self.status != 'STOPPED':
                self.status, self.reason = 'HOLD', data.get('reason') or event
        elif self.reason == 'STOP_PENDING' or self.status == 'STOPPED' or self.check_conflict:
            return False
        elif event == 'HANDOVER_OVERRIDE':
            self.status='DELIVERING'
            if self.execution:
                self.execution.update(method='HUMAN_ASSEMBLY',phase='TRANSPORT_HOLDING')
        elif event == 'SIGNAL_REQUEST':
            self.signal_request = deepcopy(data)
            if data['kind'] == 'HELP_READY':
                self.robot_status = 'IDLE'
                self.release_instruction = None
                action = self.step_inputs['assessment']['action_proposal']
                actions = action.get('human_actions') or []
                detail='\n'.join(f"{a['effect']} · {a['target_block']['layer']}층 ({a['target_block']['x']}, {a['target_block']['y']}) · 접근 {'/'.join(a['approach_sides'])}" for a in actions)
                target=actions[0]['target_block'] if len(actions)==1 else self.step()['after']
                self.help = dict(request_id=data['request_id'], plan_id=data['plan_id'], step_id=data['step_id'],
                    kind='SUPPORT', target=deepcopy(target), phase='REQUESTED',
                    instruction=(detail+'\n' if detail else '')+'준비 후 엄지척을 보여주세요. 확인 안내 전까지 도움을 유지해주세요.')
            elif data['kind']=='RECEIVE' or data['kind']=='ASSEMBLY_ACK' and not (self.help and self.help['kind']=='SUPPORT'):
                self.help=dict(request_id=data['request_id'],plan_id=data['plan_id'],step_id=data['step_id'],
                    kind='HANDOVER' if data['kind']=='RECEIVE' else 'HUMAN_ASSEMBLY',target=deepcopy(self.step()['after']),phase='REQUESTED',
                    instruction=('전달판 상공에서 대기합니다. 받을 준비가 확인되면 손으로 인계하고, 손이 없으면 전달판에 내려놓습니다.'
                        if data['kind']=='RECEIVE' else
                        '목표 위치에 조립하고 엄지척을 보여주세요. 인식되지 않으면 조립 완료 버튼을 누르세요.'
                        if data.get('timeout_holds') else '목표 위치에 조립하고 엄지척을 보여주세요. 10초 뒤에는 B가 실제 배치를 검사합니다.'))
        elif event == 'SIGNAL_REQUEST_CLOSED':
            self.signal_request = None
            if self.help: self.help['phase'] = 'MAINTAIN'
        elif event == 'HELP_RELEASE_GUIDANCE':
            if self.help: self.help['phase'] = 'RELEASED'
            self.release_instruction = f"{data.get('step_id') or '이전 단계'} 확인이 끝났습니다. 해당 도움을 해제해주세요."
        elif event == 'INSPECTION_REQUIRED':
            self.robot_waiting = True
            self.status, self.robot_status = 'WAIT_ASSEMBLY', 'IDLE'
            if self.execution:self.execution['phase']='WAIT_INSPECTION'
            self.request_check('STEP')
        elif event == 'B_DECISION' and self.await_robot_decision:
            self.after_step()
        elif event == 'B_DECISION' and data.get('result', {}).get('decision') == 'CALL_C':
            self.execution_closed = True
            self.robot_waiting = False
        elif event == 'EXECUTION_STARTED':
            self.execution_closed = False
            self.status, self.robot_status = 'DELIVERING', 'BUSY'
            self.execution = dict(plan_id=data['plan_id'], step_id=data['step_id'],
                motion_plan_id=self.step_inputs['motion']['motion_proposal']['motion_plan_id'],
                method=self.step_inputs['assessment']['action_proposal']['mode'], phase='APPROACH_PICK')
        elif event == 'MOVE_STARTED' and self.execution:
            label = data['label']
            self.execution['phase'] = ('PRE_CONTACT' if label == 'PRE_CONTACT' else
                'TRANSPORT_HOLDING' if 'LOADED' in label or label == 'TARGET_HIGH' else
                'CONTACT' if label == 'SUPPORTED_NEAR_CONTACT' else
                'RETREAT' if label=='LIFT' and self.execution['phase']=='RELEASE' else self.execution['phase'])
        elif event=='GRIP_STARTED' and self.execution:
            label=data['label']
            self.execution['phase']=('PICK_AND_CONFIRM' if label=='PICKUP_CLOSE' else
                'APPROACH_PICK' if label=='PREPARE_OPEN' else 'RELEASE')
        elif event=='ADAPTER_LEASE_APPLIED' and data.get('owner')=='CONTACT' and self.execution:
            self.execution['phase']='CONTACT'
        return True

    def stop(self):
        if self.status in ('IDLE', 'COMPLETE', 'STOPPED') or self.reason == 'STOP_PENDING':
            return False
        self.stopped_from = self.status
        self.stopped_call = deepcopy(self.active) if self.active and self.active['port'] in ('c.intent', 'c.plan_failure') else None
        self.generation += 1
        self.active = self.candidate = None
        self.awaiting_revised_design = False
        if self.check:
            self.b.cancel(self.check['check_id'])
            self.check = None
        self.status, self.reason = 'HOLD', 'STOP_PENDING'
        self.robot_status = 'STOP_PENDING'
        self.emit('robot.STOP', {})
        return True

    def reinspect(self, *, conditions_ready=False):
        if self.check or self.status != 'HOLD' or not self.inspection or self.check_conflict or self.reason == 'STOP_PENDING':
            return False
        if conditions_ready:
            if self.retry_count >= 1: return False
            self.retry_count += 1
        kind = self.inspection['check_kind']
        if self.robot_waiting and kind == 'STEP':
            self.status, self.reason = 'WAIT_ASSEMBLY', 'B_STEP_RECHECK_PENDING'
            self.emit('robot.REINSPECT', {})
        else:
            self.request_check(kind)
        return True

    def resume(self):
        if self.status != 'STOPPED' or not self.robot_resume_allowed:
            return False
        self.reason = None
        self.status = 'PREPARING'
        self.initial_purpose = 'RESUME'
        self.request_check('INITIAL')
        return True

    def correction_finished(self):
        if self.status != 'WAIT_CORRECTION':return False
        self.initial_purpose='REPLAN'
        self.status='PREPARING'
        self.request_check('INITIAL')
        return True

    def snapshot(self):
        step = self.step()
        displayed = step
        inspection = self.inspection
        if inspection and inspection['check_kind'] == 'STEP' and self.bundle:
            displayed = next(s for s in self.bundle['plan']['steps'] if s['step_id'] == inspection['step_id'])
        observed = inspection['observation'] if inspection and inspection['status'] in ('OK', 'UNOBSERVABLE') else None
        comparison = inspection['comparison'] if observed and inspection['check_kind'] == 'STEP' else 'WAITING'
        if observed and inspection['check_kind'] == 'STEP':
            observed = dict(deepcopy(observed), status='OK' if inspection['status']=='OK' else 'UNOBSERVABLE', check_id=inspection['check_id'])
            if inspection['status'] != 'OK':
                observed['reason'] = inspection['reason']
        else:
            observed = None
        button = lambda enabled: dict(visible=True, enabled=enabled)
        snapshot = dict(workflow_status=self.status, design=deepcopy(self.approved), current=deepcopy(self.current),
            step=dict(plan_id=self.bundle['plan']['plan_id'] if self.bundle else None,
                step_id=displayed['step_id'] if displayed else None, target=displayed['after'] if displayed else None,
                observed=observed, comparison=comparison or 'WAITING'),
            progress=dict(completed=len(self.completed), total=len(self.bundle['plan']['steps']) if self.bundle else 0),
            monitor=dict(robot=dict(mode=self.mode, status=self.robot_status), observation=dict(
                status=inspection['status'] if inspection and inspection['status'] in ('OK','UNOBSERVABLE') else None, check_id=inspection['check_id'] if inspection else None,
                observation_seq=inspection['observation']['observation_seq'] if inspection and inspection['observation'] else None,
                reason=inspection['reason'] if inspection else None), place_status=None, supply=deepcopy(self.supply)),
            notice=dict(question=self.reason if self.status=='WAIT_INTENT' else None, reason=self.reason,
                required_action=' · '.join(v for v in (self.reason,self.release_instruction) if v) or None,
                request_id=self.help['request_id'] if self.help and self.help['phase'] in ('REQUESTED','MAINTAIN') else None),
            actions=dict(job_id=self.job_id, start=button(self.status in ('IDLE','COMPLETE') and self.storage!='PENDING'),
                stop=button(self.status not in ('IDLE','COMPLETE','STOPPED')), resume=button(self.status=='STOPPED'),
                intent_choice=dict(visible=False,enabled=False,request_id=None),
                correction_continue=dict(visible=self.status=='WAIT_CORRECTION',enabled=self.status=='WAIT_CORRECTION',
                    request_id=self.change_request_id if self.status=='WAIT_CORRECTION' else None),
                supply_refill=[dict(brick_type=r['brick_type'],color=r['color'],visible=True,
                    enabled=self.status=='HOLD' and r['needs_refill']) for r in self.supply if r['needs_refill']]),
            completion=dict(blocks_used=bool(self.bundle and step is None), assembly=self.assembly,
                storage=self.storage, web=self.web, reason=self.save_reason or self.reason),
            user_requests=dict(change_design=dict(visible=bool(self.approved), enabled=bool(self.approved and self.status not in ('IDLE','COMPLETE','STOPPED','WAIT_INTENT') and not self.change_pending), request_id=self.change_request_id),
                home=dict(visible=False,enabled=False,request_id=None),
                assistance_ready=dict(visible=False,enabled=False,request_id=None)))
        if inspection:
            snapshot['inspection'] = {k:deepcopy(inspection[k]) for k in ('check_id','check_kind','plan_id','step_id','status','comparison','expected','difference','reason')}
        if self.dialogue:snapshot['dialogue']=deepcopy(self.dialogue)
        if self.candidate:
            snapshot.update(design_preview=dict(request_id=self.candidate['request_id'],design=self.candidate['design']),
                dialogue=dict(snapshot.get('dialogue') or {},request_id=self.candidate['request_id'],phase='WAIT_APPROVAL'))
        if self.execution and displayed and self.execution['step_id'] == displayed['step_id']:
            snapshot['execution'] = deepcopy(self.execution)
        if self.help and displayed and self.help['step_id'] == displayed['step_id']:
            snapshot['assistance'] = deepcopy(self.help)
        if self.mode=='REAL' and self.settings.get('observation_kind')=='SYNTHETIC':
            snapshot['observation_kind']='SYNTHETIC'
        return validate_hmi_snapshot(snapshot)
