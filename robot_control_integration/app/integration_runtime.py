"""D의 Step 실행. 기존 이동/파지/체결 함수를 호출하며 B의 Current를 쓰지 않는다."""
from copy import deepcopy
import math
import time
import threading
from uuid import uuid4

from app.assembly_motion import pose_error,motion_still
from app.assembly_blend_trial import run_blend
from app.assembly_step_bridge import build_plan, pose, release_feedback_range
from app.assembly_step_runner import assembly_target_pose
from app.control_driver import ControlledDriver
from app.control_session import ControlSession, validate_execution
from scripts.assembly_position_trial import run, guard
from scripts.assembly_press_trial import press


class StepRuntime:
    def __init__(self, raw, connection, record, *, clock=time.monotonic,
                 sleep=time.sleep, wall=time.time):
        self.raw, self.connection, self.record = raw, connection, record
        self.clock, self.sleep, self.wall = clock, sleep, wall
        self.session = self.driver = self.plan = None
        self.cursor = 0
        self.operations = []
        self.pending = None
        self.state = 'IDLE'
        self.signal = None
        self.signal_seq = -1
        self.request = None
        self.signal_lock = threading.Lock()
        self.contact = self.stopped_sample = None
        self.contact_started = False
        self.used_executions = set()
        self.inspection_attempt = 0
        self.blend_command_sent = False
        self.handover_active = False
        self.handover_intent_pending = False
        self.blend_start = None
        self.recovery_reason = None

    def emit(self, event, data):
        # STOP evidence must still be emitted after the execution is cancelled.
        self.record(event, dict(data, execution_id=self.session.value['execution_id'] if self.session else None,
                               plan_id=self.plan['plan_id'] if self.plan else None,
                               step_id=self.plan['step_id'] if self.plan else None,
                               current_revision=self.plan['current_revision'] if self.plan else None))

    def start(self, step, profile, value, *, resume=False, start_zone='assembly'):
        if (resume and self.state != 'STOPPED' and not self.can_resume()) or (not resume and self.state not in ('IDLE', 'WAIT_C')):
            raise RuntimeError('STEP_BUSY_OR_INSPECTION_PENDING')
        plan = build_plan(step, profile)
        if type(profile.get('noncontact_force_guard',True)) is not bool:
            raise ValueError('EXPLICIT_NONCONTACT_FORCE_GUARD_BOOLEAN_REQUIRED')
        motion_force_limit=profile['force_stop_n'] if profile.get('noncontact_force_guard',True) else None
        trial = value.get('no_vision_trial', False)
        if type(trial) is not bool:
            raise ValueError('EXPLICIT_NO_VISION_TRIAL_BOOLEAN_REQUIRED')
        if trial and (plan['mode'] != 'ROBOT_GRIP' or plan['assistance_kind'] != 'NONE'
                      or plan['current_revision'] is not None):
            raise ValueError('NO_VISION_TRIAL_REQUIRES_UNASSISTED_ROBOT_AND_NO_B_REVISION')
        if self.state == 'WAIT_C' and plan['plan_id'] == self.plan['plan_id']:
            raise RuntimeError('WAIT_FOR_C_APPROVED_NEW_PLAN')
        block = plan['block']
        permitted = ((block['color'] in ('yellow', 'blue') and block['brick_type'] in ('2x2x1', '2x3x1'))
                     or (block['color'] == 'red' and block['brick_type'] == '1x2x1'))
        if not permitted or (block['brick_type'] == '2x2x1' and block['orientation_deg'] != 0):
            raise ValueError('UNSUPPORTED_FINAL_MVP_BLOCK')
        if plan['mode'] not in ('ROBOT_GRIP', 'HUMAN_ASSEMBLY') or plan['assistance_kind'] not in ('NONE', 'HOLD', 'PRESS', 'PRESS_AND_HOLD', 'MANUAL_ASSEMBLY', 'MANUAL_ASSEMBLY_AND_HOLD'):
            raise ValueError('UNSUPPORTED_METHOD')
        if start_zone not in ('assembly', 'place', 'supply'):
            raise ValueError('INVALID_START_ZONE')
        for key in ('pickup_pose', 'reference_pose'):
            pose(plan['settings'][key], key)
        pose(profile['place_pose'], 'place_pose')
        for key in ('pickup_width_mm', 'release_width_mm', 'pickup_open_width_mm'):
            if key == 'pickup_open_width_mm' and key not in plan['settings']:
                continue
            width = plan['settings'][key]
            if type(width) not in (int, float) or not math.isfinite(width) or not 0 <= width <= 110:
                raise ValueError('STEP_GRIPPER_WIDTH_REQUIRED:'+key)
        if plan['settings']['pickup_width_mm'] >= plan['settings']['release_width_mm']:
            raise ValueError('OPEN_WIDTH_MUST_EXCEED_CLOSE_WIDTH')
        if ('pickup_open_width_mm' in plan['settings'] and
                plan['settings']['pickup_open_width_mm'] <= plan['settings']['pickup_width_mm']):
            raise ValueError('PICKUP_OPEN_WIDTH_MUST_EXCEED_CLOSE_WIDTH')
        if value.get('automatic_stage_checks') or plan['settings'].get('human_step_gestures'):
            raise ValueError('USE_INTEGRATION_SIGNALS_NOT_LOCAL_TRIAL_POLICY')
        if value['execution_id'] in self.used_executions:
            raise ValueError('EXECUTION_ALREADY_USED')
        if self.raw.mode == 'REAL':
            validate_execution(plan, profile, value, 'full')
            if profile.get('native_press'):
                from scripts.onsite_slot2_force_trial import require_drcf2_runtime
                require_drcf2_runtime()
                self.raw.check_contact_services(native_force=True)
        if self.raw.mode == 'REAL' and (value.get('provenance') != 'LIVE_D_RUNTIME' or value['d_runtime'].get('execution_id') != value['execution_id']):
            raise ValueError('MATCHING_LIVE_D_EXECUTION_REQUIRED')
        session = ControlSession(value, plan, self.emit, clock=self.clock, wall=self.wall)
        driver = ControlledDriver(self.raw, session, self.connection, clock=self.clock, sleep=self.sleep)
        if resume:
            initial_open = self.state == 'RECOVERY_REQUIRED' and self.cursor == 0 and self.operations[0][1][0] == 'PREPARE_OPEN'
            waiting_contact = self.pending == 'contact' and self.can_resume()
            waiting_blend = self.pending == 'blend' and self.can_resume()
            if plan != self.plan or profile != self.profile or (self.pending in ('grip', 'contact', 'blend') and not (initial_open or waiting_contact or waiting_blend)) or self.stopped_sample is None:
                raise RuntimeError('RESUME_REQUIRES_UNCHANGED_STEP_AND_KNOWN_OPERATION')
            sample = driver.stillness()
            mm, deg = pose_error(sample['posx'], self.stopped_sample['posx'])
            if (mm > 1 or deg > 1 or sample['gripper_status'] != self.stopped_sample['gripper_status']
                    or abs(sample['gripper_width_mm']-self.stopped_sample['gripper_width_mm']) > 1):
                raise RuntimeError('RESUME_STATE_CHANGED_REQUIRES_RECOVERY')
            if value.get('resume_current_revision') != plan['current_revision']:
                raise RuntimeError('RESUME_REQUIRES_LATEST_CURRENT_CHECK')
            if self.cursor < len(self.operations) and self.operations[self.cursor][0] == 'tray':
                # STOP으로 닫힌 수신 관측은 재사용하지 않는다. 하강 전 새 관측/준비를 요청한다.
                self.operations.insert(self.cursor, ('receive', None))
        else:
            sample = driver.stillness()
            guard(sample, self.connection, motion_force_limit, automatic=True, required_gripper_status=0)
            if self.raw.mode == 'REAL' and trial:
                expected = pose(value.get('planned_start_pose'), 'planned_start_pose')
                mm, deg = pose_error(sample['posx'], expected)
                if mm > value['stillness']['position_mm'] or deg > value['stillness']['orientation_deg']:
                    raise RuntimeError('START_STATE_CHANGED_RECALCULATION_REQUIRED')
            self.operations = self.make_operations(plan, profile, start_zone)
            self.cursor = 0
            self.contact = None
            self.contact_started = False
            self.inspection_attempt = 0
            self.handover_active = False
            self.handover_intent_pending = False
        session.claim_execution()
        self.used_executions.add(value['execution_id'])
        self.session, self.driver, self.plan, self.profile = session, driver, plan, deepcopy(profile)
        self.motion_force_limit=motion_force_limit
        self.no_vision_trial = trial
        driver.automatic_confirmation = True
        self.signal, self.signal_seq, self.request = None, -1, None
        self.pending, self.state = None, 'RUNNING'
        self.recovery_reason = None
        self.emit('EXECUTION_STARTED', dict(resume=resume, cursor=self.cursor, physical_verified=False,
            noncontact_force_guard=profile.get('noncontact_force_guard',True),
            contact_stop_force_n=profile['force_stop_n']))

    def can_resume(self):
        if self.stopped_sample is None:
            return False
        if self.pending == 'contact' and not self.contact_started and self.stopped_sample['gripper_status'] == 2:
            target = self.contact_start_pose()
            mm,deg = pose_error(self.stopped_sample['posx'],target)
            return self.state in ('STOPPED','RECOVERY_REQUIRED') and mm <= 1 and deg <= 1
        if (self.pending=='blend' and not self.blend_command_sent
                and self.state in ('STOPPED','RECOVERY_REQUIRED')
                and not self.driver.command_outcome_unknown):return True
        if (self.state=='RECOVERY_REQUIRED' and self.pending=='tray'
                and self.recovery_reason=='HAND_PRESENT_BEFORE_LOWER'
                and self.stopped_sample['gripper_status']==2
                and not self.driver.command_outcome_unknown):return True
        if self.state == 'STOPPED':
            return self.pending not in ('grip', 'contact', 'blend')
        # Opening an empty gripper before any arm motion can be reissued explicitly.
        # Pickup close/contact/release must never be replayed when their outcome is unknown.
        return (self.state == 'RECOVERY_REQUIRED' and self.cursor == 0 and self.pending == 'grip'
                and bool(self.operations) and self.operations[0][1][0] == 'PREPARE_OPEN'
                and self.stopped_sample['gripper_status'] == 0)

    def make_operations(self, plan, profile, zone):
        s = plan['settings']; pickup = s['pickup_pose']; reference = s['reference_pose']
        height = max(profile['clearance_z_mm'], reference[2]+profile['approach_offset_mm'],
                     pickup[2]+profile['approach_offset_mm'], profile['place_pose'][2]+profile['approach_offset_mm'])
        if (profile.get('continuous_transport') and plan['mode']=='ROBOT_GRIP'
                and plan['assistance_kind']=='NONE' and profile.get('native_press',{}).get('alignment_trial')):
            return self.continuous_operations(plan,profile,height,zone)
        # Pickup clearance and post-contact release are separate D commands.
        opening = s.get('pickup_open_width_mm', s['release_width_mm'])
        ops = [('grip', ('PREPARE_OPEN', opening, 0)), ('lift', (height, 0))]
        route = []
        skip_place=zone=='assembly' and profile.get('empty_return_skip_place',False)
        if skip_place:
            ops.append(('move',('BODY_EMPTY',[*profile['body_bypass_xy_mm'],height,*pickup[3:]],0,False)))
        if zone == 'assembly' and not skip_place:
            # Establish the pickup orientation/height before horizontal blending.
            ops.append(('move', ('PLACE_EMPTY', [*profile['place_pose'][:2], height, *pickup[3:]], 0, False)))
        if zone != 'supply':
            if not skip_place:route.append(('BODY_EMPTY',profile['body_bypass_xy_mm']))
            route.append(('SUPPLY_EMPTY',profile['supply_transit_xy_mm']))
        route.append(('PICKUP_HIGH', pickup[:2]))
        if profile.get('transport_blending') and len(route) >= 2:
            ops.append(('blend', ([[*xy, height, *pickup[3:]] for _,xy in route], 0)))
        else:
            ops += [('move', (label, [*xy, height, *pickup[3:]], 0, False)) for label, xy in route]
        ops += [('move', ('PICKUP_LOWER', pickup, 0, True)), ('grip', ('PICKUP_CLOSE', s['pickup_width_mm'], 2)),
                ('lift', (height, 2))]
        loaded = [('SUPPLY_LOADED', profile['supply_transit_xy_mm']), ('BODY_LOADED', profile['body_bypass_xy_mm']), ('PLACE_LOADED', profile['place_pose'][:2])]
        merged_target = (plan['mode'] != 'HUMAN_ASSEMBLY' and
            profile.get('empty_return_skip_place',False) and bool(profile.get('transport_blending')) and
            math.dist(profile['place_pose'][:2],reference[:2]) > 2*profile['transport_blending']['radius_mm'])
        if merged_target:
            # Keep the existing bypass corridor, but PLACE is an intermediate
            # blend point. Hold the pickup orientation until above the target.
            loaded.append(('TARGET_HIGH',reference[:2]))
        if profile.get('transport_blending'):
            ops.append(('blend', ([[*xy, height, *pickup[3:]] for _,xy in loaded], 2)))
        else:
            for label, xy in loaded:
                ops.append(('move', (label, [*xy, height, *pickup[3:]], 2, False)))
        if plan['mode'] == 'HUMAN_ASSEMBLY':
            tray = profile['place_pose']; high = [*tray[:2], height, *tray[3:]]
            ops += [('move', ('TRAY_HIGH', high, 2, True))]
            if plan['assistance_kind'] == 'MANUAL_ASSEMBLY_AND_HOLD':
                ops.append(('help', None))
            ops += [('receive', None), ('tray', tray), ('ack', None)]
            if plan['assistance_kind'] == 'MANUAL_ASSEMBLY_AND_HOLD':
                ops.append(('help_release', None))
        else:
            orientation = assembly_target_pose(s)[3:]
            target = [*reference[:3], *orientation]; target[2] += profile['approach_offset_mm']
            if not merged_target or pose_error([0.,0.,0.,*pickup[3:]],[0.,0.,0.,*orientation])[1]>.1:
                ops.append(('move', ('TARGET_HIGH', [*target[:2], height, *orientation], 2, False)))
            if 'pre_contact_slow_distance_mm' in profile:
                distance = profile['pre_contact_slow_distance_mm']
                if type(distance) not in (int, float) or not math.isfinite(distance) or distance <= 0:
                    raise ValueError('POSITIVE_SLOW_APPROACH_DISTANCE_REQUIRED')
                if height > target[2]+distance:
                    ops.append(('move', ('ASSEMBLY_APPROACH', [*target[:2], target[2]+distance, *orientation], 2, False)))
            ops.append(('move', ('PRE_CONTACT', target, 2, True)))
            assisted = plan['assistance_kind'] in ('HOLD', 'PRESS', 'PRESS_AND_HOLD')
            if assisted: ops.append(('help', None))
            if plan['assistance_kind'] in ('PRESS', 'PRESS_AND_HOLD'):
                # 기존 D 계약: 사람이 누를 수 있도록 near-contact에서 놓고 후퇴한다.
                # 이 방식에 Robot force press를 덧붙이지 않는다.
                near = [*reference[:3], *orientation]
                near[2] += profile['near_contact_offset_mm']
                ops += [('move', ('SUPPORTED_NEAR_CONTACT', near, 2, True)),
                        ('grip', ('SUPPORTED_RELEASE', s['release_width_mm'], 0)),
                        ('lift', (height, 0)), ('ack', None)]
            else:
                ops += [('contact', None), ('grip', ('SEATED_RELEASE', s['release_width_mm'], 0)), ('lift', (height, 0))]
            if assisted: ops.append(('help_release', None))
        return ops

    def continuous_operations(self,plan,p,height,zone):
        s=plan['settings'];pickup=s['pickup_pose'];target=assembly_target_pose(s)
        pick_high=[*pickup[:2],height,*pickup[3:]]
        def point(xy,orientation):return [*xy,height,*orientation]
        empty=[]
        if zone!='supply':
            empty=[point(p['body_bypass_xy_mm'],pickup[3:]),point(p['supply_transit_xy_mm'],pickup[3:])]
        empty.append(pick_high)
        # Rise is prepended from measured TCP at dispatch. Its corner blends into transit.
        loaded=[pick_high,point(p['supply_transit_xy_mm'],pickup[3:]),
            point(p['body_bypass_xy_mm'],pickup[3:]),point(p['place_pose'][:2],pickup[3:]),
            point(target[:2],target[3:])]
        # B inspects at assembly clearance. The next admitted Step owns the
        # empty corridor to its actual pickup; never return to this Step's slot.
        return [('grip',('PREPARE_OPEN',s.get('pickup_open_width_mm',s['release_width_mm']),0)),
            ('blend',(empty,0,height)),('move',('PICKUP_LOWER',pickup,0,True)),
            ('grip',('PICKUP_CLOSE',s['pickup_width_mm'],2)),('blend',(loaded,2)),
            ('move',('PRE_CONTACT',self.pre_contact_pose(s,p),2,True)),
            ('contact',None),('grip',('SEATED_RELEASE',s['release_width_mm'],0)),
            ('lift',(height,0))]

    @staticmethod
    def pre_contact_pose(settings,profile):
        target=assembly_target_pose(settings)
        target[2]+=profile['approach_offset_mm']
        return target

    def contact_start_pose(self):
        return self.pre_contact_pose(self.plan['settings'],self.profile)

    def request_handover(self):
        with self.signal_lock:
            # The camera requests an interrupt; only the motion worker can release.
            if (self.state!='RUNNING' or not self.profile.get('palm_handover_before_contact')
                    or self.contact_started or self.handover_active
                    or self.session.cancelled or self.driver.command_outcome_unknown):return False
            close=next(i for i,(kind,arg) in enumerate(self.operations)
                       if kind=='grip' and arg[0]=='PICKUP_CLOSE')
            sample=self.driver.snapshot
            if self.cursor<=close or not sample or sample['gripper_status']!=2:
                if not self.handover_intent_pending:
                    self.handover_intent_pending=True
                    self.emit('PALM_HANDOVER_DEFERRED',dict(until='PICKUP_CONFIRMED',release_authorized=False))
                return True
            if self.session.handover_requested:return True
            self.session.handover_requested=True
            self.emit('PALM_HANDOVER_REQUESTED',dict(original_mode=self.plan['mode'],
                actual_stop_verified=False,assembly_completion=False))
            return True

    def switch_to_handover(self):
        self.driver.stop()  # ACK and a fresh stopped window; no release here.
        stopped=deepcopy(self.driver.snapshot)
        guard(stopped,self.connection,self.motion_force_limit,automatic=True,required_gripper_status=2)
        self.session.handover_requested=False
        self.session.check()
        self.close_signal_request()
        s=self.plan['settings'];p=self.profile
        height=max(p['clearance_z_mm'],stopped['posx'][2],s['pickup_pose'][2]+p['approach_offset_mm'])
        route=[]
        kind,arg=self.operations[self.cursor]
        if kind=='blend' and arg[1]==2 and not self.blend_command_sent:
            route=arg[0]
        elif kind=='blend' and arg[1]==2:
            # Continue through the remaining approved loaded corridor, not a shortcut across the arm.
            points=[self.blend_start,*arg[0]];distances=[]
            for a,b in zip(points,points[1:]):
                delta=[y-x for x,y in zip(a[:3],b[:3])];length=sum(v*v for v in delta)
                t=max(0.,min(1.,sum((x-y)*v for x,y,v in zip(stopped['posx'][:3],a[:3],delta))/length))
                distances.append(math.dist(stopped['posx'][:3],[x+t*v for x,v in zip(a[:3],delta)]))
            index=min(range(len(distances)),key=distances.__getitem__)
            if distances[index]>p['transport_blending']['radius_mm']+p['transport_blending'].get('corridor_margin_mm',.5):
                raise RuntimeError('HANDOVER_STOP_OUTSIDE_LOADED_CORRIDOR')
            route=arg[0][index:]
        else:
            for op,data in self.operations[self.cursor:]:
                if op=='blend' and data[1]==2:route=data[0];break
                if op=='move' and data[0].endswith('_LOADED'):route.append(data[1])
                if op=='move' and data[0] in ('TARGET_HIGH','PRE_CONTACT','TRAY_HIGH'):break
        if (self.plan['mode']!='HUMAN_ASSEMBLY' and route and
                route[-1][:2]==s['reference_pose'][:2]):
            # A palm interrupt goes to the tray, never onward to the assembly target.
            route=route[:-1]
        ops=[('lift',(height,2))]
        for target in route:
            ops.append(('move',('HANDOVER_TRANSIT',target[:2]+[height]+target[3:],2,False)))
        tray=p['place_pose']
        ops.append(('move',('TRAY_HIGH',tray[:2]+[height]+tray[3:],2,False)))
        if self.plan['assistance_kind'] not in ('NONE','MANUAL_ASSEMBLY'):ops.append(('help',None))
        ops += [('handover',None),('lift',(height,0)),('ack',None)]
        if self.plan['assistance_kind'] not in ('NONE','MANUAL_ASSEMBLY'):ops.append(('help_release',None))
        self.operations[self.cursor:]=ops
        self.pending=None;self.handover_active=True
        self.emit('HANDOVER_OVERRIDE',dict(sample=stopped,actual_stop_verified=True,
            original_mode=self.plan['mode'],effective_mode='HUMAN_ASSEMBLY',
            target=self.plan['block'],assembly_completion=False,current_update=False))

    def accept_signal(self, value):
        with self.signal_lock:
            if self.state != 'RUNNING' or self.request is None:
                raise RuntimeError('NO_ACTIVE_SIGNAL_REQUEST')
            if any(value.get(k) != self.request[k] for k in ('request_id', 'execution_id', 'plan_id', 'step_id', 'current_revision')):
                raise ValueError('STALE_SIGNAL')
            seq = value.get('sequence')
            if type(seq) is not int or seq <= self.signal_seq:
                raise ValueError('OLD_SIGNAL_SEQUENCE')
            if value.get('source') not in ('SENSOR', 'HMI', 'FAKE') or (self.raw.mode == 'REAL' and value['source'] == 'FAKE'):
                raise ValueError('INVALID_SIGNAL_SOURCE')
            if self.request['kind'] == 'RECEIVE':
                if value['source'] == 'HMI' or type(value.get('hand_present')) is not bool or type(value.get('receiving_ready')) is not bool:
                    raise ValueError('HAND_PRESENCE_SENSOR_REQUIRED')
                if value['receiving_ready'] and (not value['hand_present'] or value.get('verified') is not True):
                    raise ValueError('RECEIVING_READINESS_NOT_VERIFIED')
            elif type(value.get('ready')) is not bool or (value['ready'] and value.get('verified') is not True):
                raise ValueError('READINESS_NOT_VERIFIED')
            observed = value.get('observed_monotonic_s', self.clock() if self.raw.mode != 'REAL' else None)
            if (type(observed) not in (int, float) or not math.isfinite(observed) or
                    not 0 <= self.clock()-observed <= self.session.value['frame_max_age_s']):
                raise ValueError('STALE_SIGNAL_OBSERVATION')
            self.signal_seq, self.signal = seq, (deepcopy(value), observed)

    def wait_signal(self, kind, timeout=None, *, keep=False):
        self.driver.own('WAIT')
        with self.signal_lock:
            self.request = dict(request_id=str(uuid4()), kind=kind, execution_id=self.session.value['execution_id'],
                                **{k:self.plan[k] for k in ('plan_id', 'step_id', 'current_revision')})
            self.signal = None
        self.emit('SIGNAL_REQUEST', dict(self.request, timeout_s=timeout))
        begin = self.clock()
        retaining = False
        try:
            while True:
                self.session.check()
                self.driver.stillness()
                with self.signal_lock:
                    row = self.signal
                fresh = row is not None and self.clock()-row[1] <= self.session.value['frame_max_age_s']
                # Alignment is a one-time operator answer, accepted while fresh.
                # A subsequent stop window must not age that answer out before
                # it can be consumed. Continuous hand-presence cues stay fresh-only.
                operator_answer = (kind in ('ALIGNMENT_READY', 'HELP_READY', 'ASSEMBLY_ACK') and row is not None and
                    (row[0]['source'] == 'HMI' or
                     row[0].get('confirmation_kind') == 'OPERATOR_GESTURE_NOT_ALIGNMENT_MEASUREMENT'))
                if kind == 'RECEIVE':
                    if fresh and row[0]['hand_present'] and row[0]['receiving_ready']:
                        retaining = keep
                        return True
                    if timeout is not None and self.clock()-begin >= timeout and fresh and not row[0]['hand_present']:
                        retaining = keep
                        return False
                    # Missing or stale observations never prove the lowering zone is clear.
                elif (fresh or operator_answer) and row[0]['ready']:
                    retaining = keep
                    return True
                elif timeout is not None and self.clock()-begin >= timeout:
                    return False
                self.sleep(.05)
        finally:
            if not retaining: self.close_signal_request()

    def close_signal_request(self):
        with self.signal_lock:
            request = self.request
            self.request, self.signal = None, None
        if request: self.emit('SIGNAL_REQUEST_CLOSED', dict(request_id=request['request_id']))

    def check_receive_signal(self, *, ready):
        self.session.check()
        with self.signal_lock:
            row = self.signal
        if row is None or self.clock()-row[1] > self.session.value['frame_max_age_s']:
            raise RuntimeError('RECEIVE_OBSERVATION_STALE')
        if ready and not (row[0]['hand_present'] and row[0]['receiving_ready']):
            raise RuntimeError('HANDOVER_READINESS_LOST')
        if not ready and row[0]['hand_present']:
            raise RuntimeError('HAND_PRESENT_BEFORE_LOWER')

    def move(self, label, target, held, slow=False):
        proof = self.driver.last_verified_sample if (self.plan['mode']=='ROBOT_GRIP' and
            not self.handover_active and self.request is None) else None
        self.driver.own('MOTION',verified_snapshot=proof)
        current = self.driver.sample()['posx']; p = self.profile
        descent = p.get('pickup_descent_velocity', p['descent_velocity']) if label == 'PICKUP_LOWER' else p['descent_velocity']
        descent_acc = p.get('pickup_descent_acceleration', p['descent_acceleration']) if label == 'PICKUP_LOWER' else p['descent_acceleration']
        if label == 'ASSEMBLY_APPROACH':
            descent, descent_acc = p['assembly_approach_velocity'], p['assembly_approach_acceleration']
        self.emit('MOVE_STARTED', dict(label=label, target=target))
        def record(event, data):
            if label == 'TRAY_LOWER' and event == 'MOVE_REQUEST' and data['segment'] == 'DESCENT':
                self.check_receive_signal(ready=False)
            self.emit(event, data)
        run(self.driver, self.connection, target, self.motion_force_limit, record,
            clearance_z=max(current[2], target[2]), transfer_only=target[2]>=current[2]-.05,
            transfer_rate=descent if slow else p['transfer_velocity'],
            descent_rate=descent,
            transfer_acceleration=descent_acc if slow else p['transfer_acceleration'],
            descent_acceleration=descent_acc,
            ik_fk_position_tolerance_mm=p.get('ik_fk_position_tolerance_mm',.05),
            ik_fk_orientation_tolerance_deg=p.get('ik_fk_orientation_tolerance_deg',.05),
            position_tolerance_mm=p.get('motion_position_tolerance_mm',.05),
            orientation_tolerance_deg=p.get('motion_orientation_tolerance_deg',.05),
            set_automatic_mode=False, force_norm_stop_n=self.motion_force_limit, required_gripper_status=held,
            clock=self.clock, sleep=self.sleep)
        sample = self.driver.stillness()
        mm, deg = pose_error(sample['posx'], target)
        if mm > 1 or deg > 1: raise RuntimeError('TARGET_NOT_REACHED')
        self.emit('MOVE_SUCCEEDED', dict(label=label, sample=sample, actual_stop_verified=True))

    def grip(self, label, width, status, *, precondition=None):
        reaction_release=(label=='SEATED_RELEASE' and self.contact is not None and
            self.contact.get('press_control')=='POSITION_DESCENT_REACTION_STOP' and
            self.contact.get('release_after_verified_reaction_stop') is True and
            self.contact.get('stop',{}).get('stillness_verified') is True)
        if label == 'SEATED_RELEASE' and not reaction_release:
            current = self.driver.stillness()
            if not self.contact or max(pose_error(current['posx'], self.contact['final_sample']['posx'])) > 1:
                raise RuntimeError('CONTACT_POSE_CHANGED')
            # The user allows up to 2mm of target XY variation from the grasp/contact.
            if math.dist(current['posx'][:2], self.plan['settings']['reference_pose'][:2]) > 2:
                raise RuntimeError('CONTACT_TARGET_DRIFT')
        self.driver.own('GRIPPER',verified_snapshot=self.driver.last_verified_sample
            if label in ('PREPARE_OPEN','PICKUP_CLOSE') or reaction_release else None)
        self.emit('GRIP_STARTED', dict(label=label))
        self.driver.command_gripper(width, self.profile['gripper_force_n'], precondition=precondition)
        bounds = release_feedback_range(self.plan['settings'], width) if status == 0 else [0, 110]
        if label == 'PREPARE_OPEN' and 'pickup_start_open_range_mm' in self.plan['settings']:
            bounds = self.plan['settings']['pickup_start_open_range_mm']
        deadline = self.clock()+10
        count = 0
        while self.clock() < deadline:
            sample = self.driver.sample()
            if reaction_release:self.emit('GRIP_SAMPLE',dict(label=label,sample=sample))
            if sample['gripper_status'] not in (0, 1, 2, 3):
                raise RuntimeError('GRIPPER_SAFETY_OR_STATUS_FAULT')
            # Busy feedback is allowed while awaiting completion; equipment/force guards still apply.
            # A stopped, verified seating reaction can remain above 35N until opening unloads it.
            # STOP was already verified before opening. Gripper motion/unloading can disturb
            # arm feedback; completion here uses gripper state/width. The next arm owner
            # must establish a new stopped window before sending any return motion.
            guard(dict(sample, gripper_status=status), self.connection,
                  math.inf if reaction_release else self.motion_force_limit,
                  automatic=True, required_gripper_status=status)
            if type(sample['gripper_width_mm']) not in (int, float) or not math.isfinite(sample['gripper_width_mm']):
                raise RuntimeError('INVALID_GRIPPER_WIDTH_FEEDBACK')
            count = count+1 if (sample['gripper_status'] == status and bounds[0] <= sample['gripper_width_mm'] <= bounds[1]
                               and (reaction_release or motion_still(sample,self.session.value['stillness']))) else 0
            if count >= 3:
                self.emit('GRIP_SUCCEEDED', dict(label=label, sample=sample))
                return
            self.sleep(.05)
        raise TimeoutError('GRIP_COMPLETION_NOT_VERIFIED')

    def run(self):
        try:
            while self.cursor < len(self.operations):
                self.session.check()
                self.pending, argument = self.operations[self.cursor]
                kind = self.pending
                if kind == 'move': self.move(*argument)
                elif kind == 'blend':
                    self.blend_command_sent=False
                    self.blend_start=deepcopy(self.driver.snapshot['posx'])
                    self.driver.own('MOTION')
                    targets, held = argument[:2]
                    if len(argument)==3:
                        start=self.driver.snapshot['posx'].copy()
                        start[2]=max(start[2],argument[2])
                        targets=[start,*targets]
                    if self.profile.get('continuous_transport'):
                        # Already at clearance on the next Step: omit exact no-op poses.
                        previous=self.driver.snapshot['posx'];filtered=[]
                        for target in targets:
                            if max(pose_error(previous,target))<=1e-6:continue
                            filtered.append(target);previous=target
                        targets=filtered
                        self.operations[self.cursor]=('blend',(targets,held))
                        if not targets:
                            self.emit('TRANSIT_ALREADY_REACHED',dict(gripper_status=held))
                            self.cursor+=1;self.pending=None
                            continue
                        if len(targets)==1:
                            self.move('TRANSIT_ENDPOINT',targets[0],held)
                            self.cursor+=1;self.pending=None
                            continue
                    self.emit('MOVE_STARTED', dict(label='BLENDED_TRANSIT', targets=targets, gripper_status=held))
                    self.blend_command_sent=False
                    self.blend_start=self.driver.sample()['posx']
                    def blend_record(event,data):
                        if event=='MOVE_REQUEST':self.blend_command_sent=True
                        self.emit(event,data)
                    run_blend(self.driver, self.connection, targets, self.profile, blend_record,
                        held=held, clock=self.clock, sleep=self.sleep)
                elif kind == 'grip': self.grip(*argument)
                elif kind == 'lift':
                    target = self.driver.sample()['posx']; target[2] = max(target[2], argument[0])
                    self.move('LIFT', target, argument[1])
                elif kind == 'receive':
                    direct = self.wait_signal('RECEIVE', 3., keep=True)
                    # Replace the remaining tray operation once, keeping the cursor valid on STOP.
                    if direct:
                        self.close_signal_request()
                        self.operations[self.cursor+1] = ('handover', None)
                elif kind == 'tray':
                    try:
                        self.move('TRAY_LOWER', argument, 2, True)
                    except RuntimeError as error:
                        if str(error)!='HAND_PRESENT_BEFORE_LOWER':raise
                        # DESCENT 명령 전 검사에서 들어온 손은 새 인계 요청으로 처리한다.
                        # 트레이 하강/개방을 실행하거나 기존 수신 신호를 재사용하지 않는다.
                        self.operations.insert(self.cursor,('receive',None))
                        self.pending=None
                        self.emit('HANDOVER_RECEIVE_REOPENED',dict(reason=str(error),
                            descent_command_sent=False,assembly_completion=False))
                        continue
                    finally:
                        self.close_signal_request()
                    # Descent is complete and stopped before opening; separate checkpoint avoids replaying it.
                    self.operations[self.cursor+1:self.cursor+1] = [
                        ('grip', ('TRAY_RELEASE', self.plan['settings']['release_width_mm'], 0)),
                        ('lift', (self.profile['clearance_z_mm'], 0))]
                elif kind == 'handover':
                    self.wait_signal('RECEIVE', keep=True)
                    self.pending = 'grip'
                    try:
                        self.grip('DIRECT_HANDOVER', self.plan['settings']['release_width_mm'], 0,
                                  precondition=lambda:self.check_receive_signal(ready=True))
                    finally:
                        self.close_signal_request()
                elif kind == 'ack':
                    received = self.wait_signal('ASSEMBLY_ACK', 10.)
                    self.emit('ASSEMBLY_CUE_FINISHED', dict(received=received, assembly_completion=False))
                elif kind == 'help':
                    if not self.wait_signal('HELP_READY', self.session.value['request_timeout_s']):
                        raise TimeoutError('HELP_READY_TIMEOUT')
                elif kind == 'help_release':
                    # Robot has released and retreated. Structural confirmation belongs to D/B.
                    self.emit('HELP_MAINTAIN', dict(until='B_CONFIRMED_STRUCTURE', automatic_release=False))
                elif kind == 'contact':
                    if self.raw.mode == 'REAL' and self.session.value.get('b_observation_kind') == 'SYNTHETIC':
                        validate_execution(self.plan, self.profile, self.session.value, 'contact')
                    elif self.raw.mode == 'REAL' and self.no_vision_trial:
                        # 접촉 전 사람의 실제 정렬 확인을 새 요청으로 받는다.
                        # 테스트 신호/계산 TCP가 물리 정렬 근거를 대신하지 않는다.
                        if not self.wait_signal('ALIGNMENT_READY', self.session.value['request_timeout_s']):
                            raise TimeoutError('OPERATOR_ALIGNMENT_TIMEOUT')
                        self.session.value['trial_alignment_pending'] = False
                        self.session.value['alignment_evidence_ref'] = 'THIS_EXECUTION_OPERATOR_ALIGNMENT'
                        validate_execution(self.plan, self.profile, self.session.value, 'contact')
                    proof = self.driver.last_verified_sample
                    target = self.contact_start_pose()
                    if proof is not None and (proof['gripper_status']!=2 or max(pose_error(proof['posx'],target))>1):
                        proof = None
                    self.driver.own('CONTACT',verified_snapshot=proof)
                    if self.raw.mode == 'REAL' and self.session.value.get('b_observation_kind') == 'SYNTHETIC':
                        stopped = self.driver.snapshot
                        target = self.contact_start_pose()
                        mm, deg = pose_error(stopped['posx'], target)
                        if stopped['gripper_status'] != 2:
                            raise RuntimeError('CONTACT_GRASP_NOT_CONFIRMED')
                        if mm > 1 or deg > 1:
                            raise RuntimeError('CONTACT_PRE_CONTACT_NOT_REACHED')
                        self.emit('AUTOMATIC_CONTACT_READY', dict(sample=stopped,
                            actual_stop_verified=True, operator_alignment_measured=False))
                    with self.signal_lock:
                        self.session.check()
                        self.contact_started = True
                    reference = self.plan['settings']['reference_pose']
                    travel = self.driver.sample()['posx'][2]-(reference[2]+self.profile['near_contact_offset_mm']-self.profile['max_press_travel_mm'])
                    if self.profile.get('native_press'):
                        from app.assembly_native_press import native_press
                        self.contact = native_press(self.driver, self.connection, self.plan, self.profile, travel,
                                                    self.emit, clock=self.clock, sleep=self.sleep)
                    else:
                        self.contact = press(self.driver, self.connection, self.emit, max_travel_mm=travel,
                            force_stop_n=self.profile['force_stop_n'], velocity=self.profile['descent_velocity'],
                            acceleration=self.profile['descent_acceleration'], clock=self.clock, sleep=self.sleep)
                    if self.contact['status'] not in ('FORCE_THRESHOLD_REACHED_STOP_VERIFIED', 'NATIVE_FORCE_LIMIT_STOP_VERIFIED', 'NATIVE_FORCE_LOAD_HOLD_VERIFIED'):
                        raise RuntimeError('CONTACT_NOT_VERIFIED')
                    if self.contact.get('press_control')!='POSITION_DESCENT_REACTION_STOP':
                        self.driver.stillness()
                    self.emit('CONTACT_SUCCEEDED', dict(status=self.contact['status'], assembly_completion=False))
                self.cursor += 1
                if kind=='grip' and argument[0]=='PICKUP_CLOSE' and self.handover_intent_pending:
                    self.handover_intent_pending=False
                    self.session.handover_requested=True
                self.pending = None
                self.emit('CHECKPOINT', dict(cursor=self.cursor))
            self.session.check()
            if self.no_vision_trial:
                self.state = 'IDLE'
                self.emit('TRIAL_STEP_EXECUTED', dict(vision_confirmed=False,
                    assembly_completion=False, current_update=False))
                return dict(status=self.state, vision_confirmed=False,
                            assembly_completion=False, current_update=False)
            self.state = 'AWAITING_INSPECTION'
            self.emit('INSPECTION_REQUIRED', dict(purpose='STEP', assembly_completion=False, current_update=False))
            return dict(status=self.state, assembly_completion=False, current_update=False)
        except Exception as error:
            if str(error)=='HANDOVER_REQUESTED' and not self.session.cancelled:
                try:
                    self.switch_to_handover()
                    return self.run()
                except Exception as handover_error:
                    error=handover_error
                    self.session.handover_requested=False
            self.recovery_reason=str(error)
            stopped = self.session.cancelled
            self.session.request_stop('STOP_REQUESTED' if stopped else 'EXECUTION_FAILED')
            try:
                self.driver.stop()
                self.stopped_sample = deepcopy(self.driver.snapshot)
                self.state = 'STOPPED' if stopped else 'RECOVERY_REQUIRED'
                self.emit('STOP_VERIFIED', dict(sample=self.stopped_sample, actual_stop_verified=True))
            except Exception as stop_error:
                self.stopped_sample = None
                self.state = 'RECOVERY_REQUIRED'
                self.emit('STOP_UNVERIFIED', dict(reason=str(stop_error), actual_stop_verified=False))
            self.emit('EXECUTION_HELD', dict(status=self.state, reason=str(error), pending=self.pending,
                                           cursor=self.cursor, resume_allowed=self.can_resume(),
                                           assembly_completion=False, current_update=False))
            return dict(status=self.state, reason=str(error), current_update=False)
        finally:
            self.close_signal_request()
            self.session.owner, self.session.lease = 'NONE', None

    def stop(self):
        if self.session is None: return
        previous = self.state
        self.session.request_stop('STOP_REQUESTED')
        if previous in ('AWAITING_INSPECTION', 'WAIT_REINSPECTION', 'WAIT_C', 'IDLE', 'RECOVERY_REQUIRED'):
            try:
                self.driver.stop()
                self.stopped_sample = deepcopy(self.driver.snapshot)
                # 오류 처리 스레드가 끝난 뒤의 STOP도 새 정지 증거를 응답한다.
                # 복구 보류를 정지 성공만으로 재실행 가능한 상태로 바꾸지 않는다.
                if previous != 'RECOVERY_REQUIRED':
                    self.state, self.pending = 'STOPPED', None
                self.emit('STOP_VERIFIED', dict(sample=self.stopped_sample, actual_stop_verified=True,
                                                previous_state=previous))
            except Exception as error:
                self.state, self.stopped_sample = 'RECOVERY_REQUIRED', None
                self.emit('STOP_UNVERIFIED', dict(reason=str(error), actual_stop_verified=False))
            self.emit('EXECUTION_HELD', dict(status=self.state, cursor=self.cursor,
                                           pending=self.pending, resume_allowed=self.can_resume(),
                                           reason='RECOVERY_REQUIRED' if previous=='RECOVERY_REQUIRED' else None,
                                           assembly_completion=False, current_update=False))

    def inspection(self, result, *, conditions_ready=False):
        if self.state not in ('AWAITING_INSPECTION', 'WAIT_REINSPECTION'):
            raise RuntimeError('NO_INSPECTION_PENDING')
        self.session.check()
        if any(result.get(k) != self.plan[k] for k in ('plan_id', 'step_id')):
            raise ValueError('STALE_INSPECTION')
        if result.get('execution_id') != self.session.value['execution_id']:
            raise ValueError('STALE_INSPECTION')
        decision = result['decision']
        if decision in ('KEEP', 'CALL_C') and not isinstance(result.get('current'), dict):
            raise ValueError('B_CONFIRMED_CURRENT_REQUIRED')
        if decision in ('UNOBSERVABLE', 'ERROR'):
            self.state = 'WAIT_REINSPECTION'
            if decision == 'UNOBSERVABLE' and conditions_ready and self.inspection_attempt == 0:
                self.inspection_attempt += 1
                self.state = 'AWAITING_INSPECTION'
                self.emit('INSPECTION_REQUIRED', dict(purpose='STEP', automatic_reinspection=True, current_update=False))
            else:
                self.emit('REINSPECTION_WAIT', dict(hmi_request_needed=True, current_update=False,
                                                   inspection_status=decision, reason=result.get('reason')))
        elif decision in ('KEEP', 'CALL_C'):
            self.state = 'IDLE' if decision == 'KEEP' else 'WAIT_C'
            if decision == 'KEEP' and self.plan['assistance_kind'] in ('HOLD', 'PRESS', 'PRESS_AND_HOLD', 'MANUAL_ASSEMBLY_AND_HOLD'):
                self.emit('HELP_RELEASE_GUIDANCE', dict(
                    b_confirmed=self.session.value.get('b_observation_kind') != 'SYNTHETIC',
                    observation_kind=self.session.value.get('b_observation_kind','B_RESULT')))
            self.emit('B_DECISION', dict(result=result, next_step_allowed=decision == 'KEEP', current_update=False))
        else:
            raise ValueError('UNKNOWN_B_DECISION')
        return self.state

    def reinspect(self):
        if self.state != 'WAIT_REINSPECTION': raise RuntimeError('NO_REINSPECTION_PENDING')
        self.session.check()
        self.state = 'AWAITING_INSPECTION'
        self.emit('INSPECTION_REQUIRED', dict(purpose='STEP', automatic_reinspection=False, current_update=False))
