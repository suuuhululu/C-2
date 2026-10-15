"""C/A/D 실물 시험과 명시적으로 선택하는 실제 B 관측 연결."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time
from uuid import uuid4
from queue import Queue

from app.cad_trial import measured_inputs, step_geometry
from app.cad_real_trial import REAL_STILLNESS_TOLERANCES, live_robot_state, save
from app.mvp_integration import MvpIntegration, main
from app.mvp_fake import execution_document

FULL_REAL_SUPPLY_SLOT_COUNT = 5


def require_available_supply_slot(slot_index):
    if type(slot_index) is not int or not 1 <= slot_index <= FULL_REAL_SUPPLY_SLOT_COUNT:
        raise ValueError('SUPPLY_SLOT_UNAVAILABLE: full-real uses replenished slots 1..5; slot 6 is empty')


def real_settings(inputs):
    context = deepcopy(inputs['context'])
    context['supported_modes'] = ['ROBOT_GRIP', 'HUMAN_ASSEMBLY']
    frame = deepcopy(inputs['frame'])
    frame['profile_id'] = 'D_FULL_FEATURE_FRAME_20261012'
    p = inputs['profile']
    frame['calculation_profiles']['tray'] = dict(profile_id='D_TAUGHT_PLACE_BOARD',
        tcp_pose_mm_zyz_deg=deepcopy(p['place_pose']), travel_tcp_z_mm=p['clearance_z_mm'],
        d_loaded_transit=[dict(label=label,xy_mm=deepcopy(xy)) for label,xy in (
            ('SUPPLY_20_0',p['supply_transit_xy_mm']),('BODY_BYPASS',p['body_bypass_xy_mm']),
            ('PLACE_BOARD',p['place_pose'][:2]))])
    if p.get('empty_return_skip_place'):frame['calculation_profiles']['tray']['empty_return_skip_place']=True
    return dict(assembly_context=context, frame_profile=frame,
                observation_kind='SYNTHETIC',
                geometry_reference='SYNTHETIC_B_USING_D_19_4.5_16_GEOMETRY')


def prepare_measured(workflow, inputs, payload, slot_index, receipt, receipt_ref, review_ref):
    if not review_ref:
        raise ValueError('OPERATOR_PREPARATION_REQUIRED')
    require_available_supply_slot(slot_index)
    action = workflow.whole_result['action_proposals'][len(workflow.completed)]
    frame, profile, slot, correction = step_geometry(inputs,payload['step'],action,slot_index)
    frame.update(profile_id=workflow.settings['frame_profile']['profile_id'],
                 profile_version=workflow.settings['frame_profile']['profile_version'])
    # Whole/assessment/motion share the same real tray; no fake handover coordinates.
    frame['calculation_profiles']['tray'] = deepcopy(workflow.settings['frame_profile']['calculation_profiles']['tray'])
    if profile.get('empty_return_skip_place') and action['mode']!='HUMAN_ASSEMBLY':
        frame['calculation_profiles']['assembly']['d_onsite_step']['empty_return_skip_place']=True
    if action['mode'] == 'HUMAN_ASSEMBLY':
        frame['calculation_profiles']['assembly'].pop('d_onsite_step',None)
    robot = live_robot_state(receipt,frame)
    robot.update(source_epoch=workflow.epoch,state_sequence=len(workflow.completed)+1,
        stop_observation_ref=receipt_ref,freshness_policy_ref='D_LIVE_QUERY_0.5_SECONDS')
    slot.update(bound_workflow_generation=workflow.generation,valid_until_ref=receipt_ref)
    profile.update(profile_id='D_FULL_FEATURE_STEP_'+str(uuid4()),physical_route_reviewed=True,
        human_collaboration_commissioning_ref=review_ref,operator_review_ref=review_ref)
    profile['steps']={'mvp/'+payload['step']['step_id']:next(iter(profile['steps'].values()))}
    s=next(iter(profile['steps'].values()))
    s.update(physical_reference_reviewed=True,operator_review_ref=review_ref)
    # Human pressure is performed by the operator; never add robot force pressing.
    if action['mode']!='ROBOT_GRIP' or action['assistance_kind'] not in ('NONE','HOLD'):
        profile.pop('native_press',None)
    return dict(deepcopy(payload),frame_profile=frame,slot=slot,robot_state=robot,d_profile=profile,
        state_receipt_ref=receipt_ref,operator_review_ref=review_ref,correction_base_xy_mm=correction)


def measured_document(bundle, identity, epoch):
    require_available_supply_slot(bundle['request']['reserved_supply_slot']['slot_index'])
    doc=execution_document(bundle,identity)
    request=bundle['request'];p=doc['d_profile'];s=doc['session'];prepared=bundle['prepared']
    review=prepared['operator_review_ref'];receipt=prepared['state_receipt_ref']
    from scipy.spatial.transform import Rotation
    state=request['robot_state']
    s.update(backend='REAL',provenance='LIVE_D_RUNTIME',source_epoch=epoch,
        frame_profile_id=request['frame_profile']['profile_id'],profile_id=p['profile_id'],
        exclusive_control_reviewed=True,device_feedback_reviewed=True,stillness_parameters_reviewed=True,
        hand_clear_reviewed=True,operator_review_ref=review,transport_blend_review_ref=review,
        b_observation_kind='SYNTHETIC',trial_alignment_pending=False,alignment_evidence_ref=None,
        planned_start_pose=[v*1000 for v in state['tcp_pose']['xyz_m']]+
            Rotation.from_quat(state['tcp_pose']['quaternion_xyzw']).as_euler('ZYZ',degrees=True).tolist())
    s['stillness'].update(REAL_STILLNESS_TOLERANCES)
    s['d_runtime']=dict(sample_kind='LIVE_D_RUNTIME',source_epoch=epoch,execution_id=identity,
        plan_id=doc['step']['plan_id'],step_id=doc['step']['step_id'],current_revision=doc['step']['current_revision'],
        profile_id=p['profile_id'],valid_until_unix_s=s['expires_unix_s'],
        reassessment_ref=bundle['assessment']['context']['request_id'],reassessed_block=doc['step']['block'],
        reassessed_mode=doc['step']['action']['mode'],reassessed_assistance_kind=doc['step']['action']['assistance_kind'],
        current_ref='SYNTHETIC_B_CURRENT:'+str(doc['step']['current_revision']),reservation_ref=request['reserved_supply_slot']['reservation_id'],
        start_pose_ref=receipt,reservation_confirmed=True,slot_id=request['reserved_supply_slot']['slot_id'])
    doc.update(fixture_kind='REAL_D_SYNTHETIC_B_OPERATOR_TRIAL',start_zone='assembly',
               state_basis='SYNTHETIC_B_NOT_CAMERA_CONFIRMED',physical_assembly_verified=False)
    return doc


class FullFeatureRealTrial(MvpIntegration):
    supply_slot_count = FULL_REAL_SUPPLY_SLOT_COUNT

    def __init__(self,robot_root,directory,*,contact_alignment_trial=False,round3_fixed_step=False,
                 fixed_trial_scenario=None,supply_depth_profile=None,educational_depth_demo=False,execution_profile=None,
                 gestures=True,**kwargs):
        self.fixed_step = round3_fixed_step
        self.fixed_trial = None
        self.fixed_result = None
        self.fixed_robot_root = Path(robot_root)
        self.fixed_native_options=dict(scenario=fixed_trial_scenario,supply_depth_profile=supply_depth_profile,
                                       educational_depth_demo=educational_depth_demo,execution_profile=execution_profile)
        self.inputs=measured_inputs(robot_root)
        if self.inputs['taught_supply'] is None:
            raise ValueError('SUPPLY_TEACHING_REQUIRED_FOR_FULL_REAL_TRIAL')
        self.contact_alignment_trial=contact_alignment_trial
        p=self.inputs['profile']
        p.update(empty_return_skip_place=True,palm_handover_before_contact=True,noncontact_force_guard=False,
            supply_approach_blending=False,force_stop_n=40.,operator_cue_timeout_holds=True,operator_cue_buttons=True,
            ik_fk_position_tolerance_mm=.5,ik_fk_orientation_tolerance_deg=.5,
            transfer_velocity=276.48,transfer_acceleration=96.,
            descent_acceleration=12.,pickup_descent_acceleration=12.,
            supply_slot_count=self.supply_slot_count,supply_unavailable_slots=[6],
            supply_slots_always_replenished=True)
        p['native_press'].update(force_n=40.,alignment_trial=True,
            review_ref='USER_40N_REACTION_STOP_20261013')
        p.pop('pre_contact_slow_distance_mm',None)
        if contact_alignment_trial:
            p['native_press']['alignment_trial']=True
            p['continuous_transport']=True
            p.update(reaction_descent_velocity=6.,reaction_descent_acceleration=6.)
            p.update(motion_position_tolerance_mm=1.,motion_orientation_tolerance_deg=1.)
            p['transport_blending'].update(relaxed_constraints=True,
                transit_position_tolerance_mm=10.,transit_orientation_tolerance_deg=5.,
                corridor_margin_mm=40.,timeout_floor_s=45.,finish_endpoint=True)
        self.review_ref=None
        self.pending_read=None
        self.next_fake_check='MATCH'
        super().__init__(robot_root,directory,**kwargs,robot_mode='REAL',
            runtime_settings=real_settings(self.inputs),gestures=gestures)
        self.directory=Path(directory)

    def confirm_operator(self,request_id):
        request=self.ready_signal
        if (not request or request['request_id']!=request_id or request.get('_operator_sent')
                or self.workflow.status in ('STOPPED','HOLD')
                or not request.get('operator_button_allowed')):return False
        request['_operator_sent']=True
        self.robot.send('OPERATOR_CONFIRM',request_id=request_id,ready=True)
        return True

    def observe(self,context,active):
        value,diagnostic=super().observe(context,active)
        if context['check_kind']=='STEP':
            fault=self.next_fake_check;self.next_fake_check='MATCH'
            if fault=='ERROR':raise RuntimeError('EXPLICIT_SYNTHETIC_B_ERROR')
            if fault=='UNOBSERVABLE':value.update(visible_blocks=[],verified_regions=[],reason='SYNTHETIC_B_OCCLUSION')
            if fault=='MISMATCH':
                target=self.workflow.step()['after']
                value['visible_blocks']=[b for b in value['visible_blocks'] if b!=target]
                self.scene=deepcopy(value['visible_blocks'])
        return value,dict(diagnostic,observation_kind='SYNTHETIC_NOT_CAMERA')

    def review_preparation(self,checked):
        # An operator response, not a calibration/commissioning result generated by A.
        if self.workflow.status not in ('IDLE','COMPLETE'):
            return
        self.review_ref='OPERATOR_FULL_FEATURE_'+str(uuid4()) if checked else None

    def command(self,name):
        if self.fixed_step:
            return self.fixed_command(name)
        if name=='START' and not self.review_ref:return False
        if name=='STOP':
            idle=self.workflow.execution_id is None
            self.pending_read=None
            accepted=super().command(name)
            if accepted and idle:
                self.pending_read=dict(kind='stop',opened=time.monotonic())
                self.robot.send('READ_STATE')
            return accepted
        return super().command(name)

    def fixed_command(self, name):
        if (name == 'STOP' and self.fixed_trial is not None and self.fixed_trial.process is not None
                and self.fixed_trial.process.poll() is None):
            self.fixed_trial.stop()
            self.workflow.robot_status = 'STOP_PENDING'
            self.workflow.status, self.workflow.reason = 'HOLD', '정지 요청 전송 · 실제 정지 확인 필요'
            return True
        if (name != 'START' or self.workflow.status != 'IDLE' or not self.review_ref
                or self.login_pending or self.owner_state == 'PENDING'):
            return False
        if self.history_dsn is not None and self.creator is None:
            self.creator_reason = '시작 전에 제작자 로그인이 필요합니다.'
            return False
        from app.round3_fixed_trial import FixedStepProcess
        self.workflow.job_id = str(uuid4())
        self.job_creator = deepcopy(self.creator)
        self.workflow.status = 'DELIVERING'
        self.workflow.robot_status = 'BUSY'
        self.workflow.reason = 'T1 고정 시험 · 공급 인식 → yaw 정렬 → 조립·윗면 누르기 · 기존 팝업 조작 필요'
        if not self.workflow.event('ROUND3_FIXED_TRIAL_STARTED', dict(step_id='T1',
                source='round2_three_step_trial', assembly_completion=False, current_update=False)):
            return False
        if self.job_creator is not None:
            self.link_creator()
        self.fixed_trial = FixedStepProcess(self.fixed_robot_root,
            self.directory / self.workflow.job_id / 'fixed-trial', **self.fixed_native_options)
        try:
            self.fixed_trial.start()
        except (OSError, ValueError, RuntimeError) as error:
            self.workflow.status, self.workflow.reason = 'HOLD', str(error)
            self.workflow.robot_status = 'ERROR'
            return False
        return True

    def emit(self,port,payload):
        if port=='d.prepare_step':
            self.pending_read=dict(kind='prepare',payload=deepcopy(payload),opened=time.monotonic())
            self.robot.send('READ_STATE')
        elif port=='robot.EXECUTE':
            bundle=dict(payload['bundle'],prepared=self.workflow.step_inputs)
            self.last_document=measured_document(bundle,payload['execution_id'],self.workflow.epoch)
            save(self.directory/self.workflow.job_id/(payload['execution_id']+'.execution.json'),self.last_document)
            self.robot.send('EXECUTE',document=deepcopy(self.last_document))
        elif port=='robot.RESUME':
            if self.last_document is None:raise ValueError('No stopped Step')
            document=deepcopy(self.last_document)
            require_available_supply_slot(document['request']['reserved_supply_slot']['slot_index'])
            s=document['session'];s.update(execution_id=payload['execution_id'],
                resume_current_revision=payload['current']['current_revision'],expires_unix_s=time.time()+600,
                trial_alignment_pending=False,alignment_evidence_ref=None)
            s['d_runtime'].update(execution_id=payload['execution_id'],valid_until_unix_s=s['expires_unix_s'])
            self.last_document=document
            self.robot.send('RESUME',document=document)
        else:
            super().emit(port,payload)

    def state_snapshot(self,value):
        pending=self.pending_read;self.pending_read=None
        if pending is None:return
        try:
            path=self.directory/self.workflow.job_id/(str(uuid4())+'.state.json')
            save(path,value)
            live_robot_state(value,self.workflow.settings['frame_profile'])
            if pending['kind']=='stop':
                if self.workflow.reason=='STOP_PENDING':
                    self.workflow.robot_event(dict(event='STOP_VERIFIED',data=dict(actual_stop_verified=True,
                        sample=value['samples'][-1],evidence_ref=str(path),previous_state='IDLE',
                        execution_id=self.workflow.last_execution_id)))
                return
            payload=pending['payload']
            if (payload['generation']!=self.workflow.generation or payload['current']!=self.workflow.current
                    or self.workflow.status!='REPLANNING' or self.workflow.reason=='STOP_PENDING'):return
            block=payload['step']['after'];column=block['brick_type'],block['color']
            self.workflow.prepared_step(prepare_measured(self.workflow,self.inputs,payload,
                self.slot_indices.get(column,1),value,str(path),self.review_ref))
        except (ValueError,KeyError) as error:
            self.workflow.status,self.workflow.reason='HOLD',str(error)
            self.workflow.event('LIVE_PREPARATION_FAILED',dict(reason=str(error),robot_motion_sent=False))

    def poll(self):
        super().poll()
        if self.fixed_step:
            if self.fixed_trial is not None and self.fixed_result is None:
                result = self.fixed_trial.poll()
                if result is not None:
                    self.fixed_result = result
                    self.workflow.status = 'HOLD'
                    self.workflow.robot_status = None  # Process exit is not measured physical stillness.
                    self.workflow.reason = ('T1 동작 시험 종료 · 실제 조립·정지 확인 필요 · B 판정·최종 저장 미연결'
                        if result['status'] == 'FIXED_STEP_EXECUTED' else
                        'T1 시험 중단/실패 · 실제 정지 확인 후 console.log와 events.jsonl 확인')
                    self.workflow.event('ROUND3_FIXED_TRIAL_RESULT', result)
            return
        if self.pending_read and time.monotonic()-self.pending_read['opened']>20:
            self.pending_read=None
            self.workflow.status,self.workflow.reason='HOLD','LIVE_STATE_QUERY_TIMEOUT'
        if self.workflow.release_instruction:
            self.workflow.release_instruction='B는 가짜입니다. 실물 구조의 안정을 직접 확인한 뒤 도움을 해제해주세요.'
        if self.workflow.help and self.workflow.help['kind']=='HUMAN_ASSEMBLY':
            self.workflow.help['instruction']='목표 위치에 조립한 뒤 엄지척을 보여주세요. 10초 안에 확인하지 못하면 관측을 보류하고 다시 검사합니다. B는 가짜입니다.'

    def close(self):
        if self.fixed_trial is not None:
            self.fixed_trial.close()
        super().close()

    def answer_voice(self):
        if self.c_mode!='live' or self.c_pending is None:return False
        port,payload=self.c_pending;self.c_pending=None
        self.workflow.dialogue.update(phase='LISTENING')
        def call(token):
            from app.c_design import main as c
            def progress(value):
                self.inbox.put(('voice_progress',(payload['request_id'],deepcopy(value))))
            if port=='c.initial':return c.create_initial_design(should_stop=token.is_set,on_progress=progress)
            if port=='c.review':return c.review_design_candidate(payload['candidate'],kind=payload['kind'],
                previous_design=payload['previous_design'],current=payload['current']['blocks'],
                should_stop=token.is_set,on_progress=progress,change_reason=payload.get('change_reason'),
                design_metadata=payload.get('design_metadata'),planning_failure=payload.get('planning_failure'))
            context={k:deepcopy(payload.get(k)) for k in ('expected','difference','observation','reason')}
            from app.c_text_connection import differences_for_c
            diff=payload.get('difference')
            pairs=differences_for_c(dict(diff,unobservable=[])) if diff and (diff['missing'] or diff['unexpected']) else []
            if pairs:return c.run_intervention(payload['design'],payload['current']['blocks'],pairs,
                should_stop=token.is_set,on_progress=progress,inspection_context=context)
            return c.run_design_change(payload['design'],payload['current']['blocks'],reason=payload['reason'],
                should_stop=token.is_set,on_progress=progress,inspection_context=context,
                planning_failure=payload.get('planning_failure'))
        self.background(port,payload,call)
        return True


class ApprovedStepRealTrial(FullFeatureRealTrial):
    """One native A step using a real B archive or an explicitly labeled trial baseline."""
    approved_step_mode = True

    def __init__(self, robot_root, directory, *, initial_observation, fixed_trial_scenario,
                 execution_profile, live_inspection=False, inspection_config=None,
                 camera_free_trial=False, three_step_trial=False, live_three_step=False, **kwargs):
        from app.round3_approved_step import load_initial_capture
        self.scenario_path = Path(fixed_trial_scenario).resolve()
        self.registry_path = Path(execution_profile).resolve()
        self.camera_free_trial = camera_free_trial
        self.three_step_trial = three_step_trial
        self.live_three_step = live_three_step
        if live_three_step and (not live_inspection or camera_free_trial or three_step_trial):
            raise ValueError('REAL_B_THREE_STEP_REQUIRES_REAL_INITIAL_AND_LIVE_INSPECTION')
        if three_step_trial and not camera_free_trial:
            raise ValueError('THREE_STEP_TRIAL_REQUIRES_CAMERA_FREE_TRIAL')
        self.trial_archive_status, self.trial_archive_reason = 'NOT_STARTED', None
        self.trial_db_recorded = False
        self.trial_archive_inbox = Queue()
        self.scenario = json.loads(self.scenario_path.read_text())
        if camera_free_trial:
            if initial_observation is not None or live_inspection or inspection_config is not None:
                raise ValueError('CAMERA_FREE_TRIAL_CANNOT_USE_REAL_B_OBSERVATION')
            from app.round3_approved_step import file_digest
            self.initial_observation = dict(status='OK',
                visible_blocks=[deepcopy(row['block']) for row in self.scenario['preplaced']],
                verified_regions=[dict(x=0,y=0,width=24,height=24,layer=i) for i in range(1,6)], reason=None)
            self.initial_packet = dict(source_kind='SYNTHETIC_SCENARIO_NOT_B_OBSERVATION',
                generated_unix_s=time.time(), geometry_reference='SYNTHETIC_ROUND3_SCENARIO',
                source_sha256={str(path):file_digest(path) for path in (self.scenario_path,self.registry_path)})
        else:
            self.initial_observation, self.initial_packet = load_initial_capture(initial_observation)
        packet = self.initial_packet
        self.live_inspection_mode = live_inspection
        self.live_observer = None
        self.live_check_running = Event()
        self.inspection_stop_worker = None
        if live_inspection:
            from app.round3_initial_inspection import DEFAULT, load_settings
            self.inspection_settings = load_settings(inspection_config or DEFAULT)
            if self.inspection_settings['calibration_id'] != packet['geometry_reference']:
                raise ValueError('APPROVED_STEP_LIVE_INSPECTION_GEOMETRY_MISMATCH')
        # The native preview resolves the same teaching, layout and authenticated registry as run.
        preview = subprocess.run([sys.executable, '-m', 'scripts.round2_three_step_trial', 'preview',
            '--scenario', str(self.scenario_path),
            '--execution-profile', str(self.registry_path)], cwd=robot_root,
            text=True, capture_output=True, timeout=30)
        if preview.returncode:
            raise ValueError('APPROVED_STEP_NATIVE_PREVIEW_FAILED: ' + preview.stderr)
        self.native_configs = [item['config'] for item in json.loads(preview.stdout)['steps']]
        self.native_config = None
        self.initial_consumed = False
        self.service_binding = None
        super().__init__(robot_root, directory, fixed_trial_scenario=self.scenario_path,
                         execution_profile=self.registry_path, gestures=not (camera_free_trial or live_three_step), **kwargs)
        self.workflow.settings['observation_kind'] = ('SYNTHETIC_SCENARIO_NOT_B_OBSERVATION' if camera_free_trial
            else 'REAL_CAMERA_STEP_FINAL' if live_inspection else 'SAVED_REAL_INITIAL_ONLY')
        self.workflow.settings['geometry_reference'] = packet['geometry_reference']

    def observe(self, context, active):
        if context['check_kind'] != 'INITIAL' and self.live_inspection_mode:
            if not self.robot_retired or self.fixed_result is None or self.live_observer is None:
                raise ValueError('APPROVED_NATIVE_WRITER_MUST_FINISH_BEFORE_INSPECTION')
            execution_id = self.workflow.execution_id or self.workflow.last_execution_id
            self.live_check_running.set()
            try:
                return self.live_observer(context, active)
            finally:
                self.live_check_running.clear()
                outcome = self.live_observer.outcomes.get(context['check_id'], {})
                if self.cancelled.is_set() and outcome.get('actual_stop_verified') is True:
                    self.robot.events.put(dict(event='STOP_VERIFIED', data=dict(
                        actual_stop_verified=True, execution_id=execution_id, previous_state='IDLE',
                        sample=outcome.get('stop_sample') or outcome.get('home_sample', {}).get('sample'),
                        check_id=context['check_id'],
                        evidence_ref=str(self.live_observer.output / context['check_id'] / 'd-result.json'))))
        from app.round3_approved_step import file_digest
        packet = self.initial_packet
        if (not active() or self.initial_consumed or context['check_kind'] != 'INITIAL'
                or not 0 <= time.time() - packet['generated_unix_s' if self.camera_free_trial else 'captured_unix_s'] <= 300
                or any(file_digest(path) != digest for path, digest in packet['source_sha256'].items())):
            raise ValueError('APPROVED_STEP_FRESH_INITIAL_OBSERVATION_REQUIRED')
        self.initial_consumed = True
        return dict(deepcopy(self.initial_observation), check_id=context['check_id'],
                    observation_seq=context['observation_seq']), dict(
                        observation_kind=self.workflow.settings['observation_kind'])

    def command(self, name):
        if self.live_inspection_mode and self.fixed_result is not None and name == 'STOP':
            self.cancelled.set()
            self.c_pending = None
            return self.workflow.stop()
        if (self.live_inspection_mode and self.fixed_result is not None
                and name in ('REINSPECT', 'REQUEST_DESIGN_CHANGE')):
            return MvpIntegration.command(self, name)
        if name in ('RESUME', 'REINSPECT', 'CONTINUE_AFTER_CORRECTION'):
            return False
        if self.fixed_trial is not None and name != 'STOP':
            return False
        accepted = super().command(name)
        if accepted and name == 'START':
            return self.workflow.event('ROUND3_CAMERA_FREE_TRIAL_STARTED' if self.camera_free_trial
                else 'ROUND3_INITIAL_CAPTURE_SOURCE', self.initial_packet)
        return accepted

    def state_snapshot(self, value):
        from app.round3_approved_step import same_blocks
        pending = self.pending_read
        if pending is not None and pending['kind'] != 'prepare':
            return super().state_snapshot(value)
        self.pending_read = None
        if pending is None or pending['kind'] != 'prepare':
            return
        payload = pending['payload']
        if (payload['generation'] != self.workflow.generation or payload['current'] != self.workflow.current
                or self.workflow.status != 'REPLANNING' or self.workflow.reason == 'STOP_PENDING'):
            return
        try:
            baseline = [row['block'] for row in self.scenario['preplaced']]
            targets = [row['target'] for row in self.scenario['steps']]
            prefix = (self.workflow.bundle['expected_steps'][len(self.workflow.completed)]['before_blocks']
                      if self.live_three_step else baseline)
            if (not same_blocks(self.workflow.current['blocks'], prefix)
                    or not same_blocks(self.workflow.approved['blocks'], baseline + targets)):
                raise ValueError('APPROVED_STEP_SCENARIO_MISMATCH')
            matches = [cfg for cfg in self.native_configs if cfg['trial_step']['target'] == payload['step']['after']]
            if len(matches) != 1:
                raise ValueError('APPROVED_STEP_EXACT_NATIVE_TEACHING_REQUIRED')
            self.native_config = cfg = matches[0]
            target = payload['step']['after']
            path = self.directory / self.workflow.job_id / (str(uuid4()) + '.state.json')
            save(path, value)
            prepared = prepare_measured(self.workflow, self.inputs, payload,
                cfg['trial_step']['supply_slot'], value, str(path), self.review_ref)
            pick = deepcopy(cfg['blocks'][0]['pickup_pose'])
            reference = deepcopy(cfg['alignment_target']['placement_tcp_reference'])
            native_settings = {key:deepcopy(cfg[key]) for key in
                ('release_width_mm','release_feedback_range_mm','seating_force_stop_n','press_force_stop_n',
                 'free_motion_speed_scale','assembly_board_offset',
                 'velocity','rise_velocity','transit_velocity','descent_velocity',
                 'seating_velocity','press_velocity') if key in cfg}
            for key in ('seating_force_stop_n','press_force_stop_n'):
                if key in cfg:prepared['d_profile'][key] = cfg[key]
            frame = prepared['frame_profile']['calculation_profiles']
            frame['supply']['d_taught_slot'] = dict(identity=dict(brick_type=target['brick_type'],
                color=target['color'], slot_index=cfg['trial_step']['supply_slot']), tcp_mm_zyz_deg=pick,
                source_sha256=cfg['educational_supply_binding']['registry_sha256'])
            frame['assembly']['d_onsite_step'].update(pickup_pose=pick, reference_pose=reference,
                assembly_tcp_zyz_deg=reference[3:], **deepcopy(native_settings))
            next(iter(prepared['d_profile']['steps'].values())).update(pickup_pose=pick,
                reference_pose=reference, assembly_tcp_zyz_deg=reference[3:], **deepcopy(native_settings))
            self.workflow.prepared_step(prepared)
        except (ValueError, KeyError, OSError) as error:
            self.workflow.status, self.workflow.reason = 'HOLD', str(error)
            self.workflow.event('APPROVED_STEP_PREPARATION_FAILED', dict(reason=str(error), robot_motion_sent=False))

    def emit(self, port, payload):
        if port == 'd.prepare_step' and self.live_three_step and self.fixed_result is not None:
            outcome = self.live_observer.outcomes.get(self.workflow.completed[-1]['check_id'], {}) if self.workflow.completed else {}
            if not all(outcome.get(key) is True for key in ('home_return_verified','writer_released','actual_stop_verified')):
                self.workflow.status, self.workflow.reason = 'HOLD', 'REAL_B_HOME_WRITER_HANDOFF_REQUIRED'
                return
            # B has accepted this prefix and released the observation writer. Query a
            # fresh start state through the existing D process before reassessment.
            from app.mvp_integration import RobotProcess
            self.fixed_trial.close()
            self.fixed_trial = self.fixed_result = None
            self.robot = RobotProcess(self.fixed_robot_root, mode='REAL',
                config=self.fixed_robot_root / 'interfaces/assembly_contact_trial.json', gestures=False)
            self.robot_retired = False
            super().emit(port, payload)
        elif port == 'd.prepare_step' and self.live_inspection_mode and self.fixed_result is not None:
            # Preserve B Current and C/A results. A later native binding must cover the
            # changed Current/prefix/support before another physical step can start.
            self.workflow.status, self.workflow.reason = 'HOLD', 'REMAINING_NATIVE_STEP_BINDING_REQUIRED'
            self.workflow.event('ROUND3_REMAINING_NATIVE_STEP_PENDING', deepcopy(payload))
        elif port == 'robot.EXECUTE':
            from app.round3_approved_step import digest, file_digest, validate_binding
            from app.round3_fixed_trial import FixedStepProcess
            document = dict(schema_version='round3-approved-step/1', approved=deepcopy(self.workflow.approved),
                planning_bundle=deepcopy(self.workflow.bundle), prepared=deepcopy(payload['bundle']),
                execution_id=payload['execution_id'], operator_review_ref=self.review_ref,
                expires_unix_s=time.time() + 120, native_config_sha256=digest(self.native_config),
                scenario_sha256=digest(self.scenario), execution_profile_sha256=file_digest(self.registry_path))
            if self.live_three_step:
                from app.round3_initial_inspection import DEFAULT
                initial = [r for r in self.workflow.accepted_checks.values() if r['check_kind']=='INITIAL']
                if len(initial) != 1:
                    raise ValueError('REAL_B_SEQUENCE_ONE_INITIAL_REQUIRED')
                document.update(execution_scope='ROUND3_REAL_B_THREE_STEP',
                    b_initial_response=deepcopy(initial[0]),
                    b_confirmed_steps=[deepcopy(self.workflow.accepted_checks[r['check_id']]) for r in self.workflow.completed],
                    manual_step_confirmation=True, home_after_each_step=True, home_settings_sha256=file_digest(DEFAULT))
            if self.camera_free_trial:
                document.update(trial_scope='SIXPART_REAL_D_THREE_STEP_TRIAL' if self.three_step_trial else 'SIXPART_REAL_D_SINGLE_STEP',
                    state_basis='SYNTHETIC_SCENARIO_NOT_B_OBSERVATION',
                    physical_assembly_verified=False, baseline_source_sha256=self.initial_packet['source_sha256'])
            if self.three_step_trial:
                from app.round3_initial_inspection import DEFAULT
                from app.round3_approved_step import trial_sequence_entries, validate_trial_sequence
                prepared = [dict(case=cfg['trial_step'],config=cfg) for cfg in self.native_configs]
                document.update(native_sequence=trial_sequence_entries(self.workflow.bundle, prepared),
                    manual_step_confirmation=True, home_after_each_step=True, home_settings_sha256=file_digest(DEFAULT))
                _, self.service_binding = validate_trial_sequence(document, prepared, self.scenario, self.registry_path)
            else:
                self.service_binding = validate_binding(document, self.native_config, self.scenario, self.registry_path)
            path = self.directory / self.workflow.job_id / (payload['execution_id'] + '.approved-step.json'
                if self.live_three_step else 'approved-step.json')
            try:
                if self.live_inspection_mode:
                    from app.round3_live_inspection import LiveInspectionObserver
                    self.live_observer = LiveInspectionObserver(self.fixed_robot_root.resolve().parent,
                        self.inspection_settings, self.directory / self.workflow.job_id / 'live-inspection',
                        self.review_ref)
                save(path, document)
            except (OSError, ValueError) as error:
                self.workflow.status, self.workflow.reason = 'HOLD', str(error)
                self.workflow.event('APPROVED_STEP_SAVE_FAILED', dict(reason=str(error), robot_motion_sent=False))
                return
            if not self.workflow.event('ROUND3_APPROVED_STEP_BOUND', self.service_binding):
                return
            # READ_STATE owns the old ROS writer lock. Close and join before native takes it.
            try:
                self.robot.close()
                self.robot_retired = True
                self.fixed_trial = FixedStepProcess(self.fixed_robot_root,
                    self.directory / self.workflow.job_id / ('native-' + payload['execution_id']
                        if self.live_three_step else 'approved-native'), scenario=self.scenario_path,
                    execution_profile=self.registry_path, approved_step_document=path,
                    native_step=self.native_config['trial_step']['step_id'], three_step_trial=self.three_step_trial,
                    return_home_after_step=self.live_three_step)
                self.fixed_trial.start()
            except (OSError, ValueError, RuntimeError) as error:
                self.workflow.status, self.workflow.reason = 'HOLD', str(error)
                self.workflow.event('APPROVED_STEP_START_FAILED', dict(reason=str(error), assembly_completion=False))
        elif port == 'robot.STOP' and self.robot_retired:
            if (self.live_inspection_mode and self.fixed_result is not None
                    and not self.live_check_running.is_set()):
                self.stop_retired_inspection()
            elif self.fixed_trial is not None:
                self.fixed_trial.stop()
        else:
            super().emit(port, payload)

    def poll(self):
        super().poll()
        if self.fixed_trial is not None and self.fixed_result is None:
            result = self.fixed_trial.poll()
            if result is not None:
                self.fixed_result = result
                matched = (result['status'] == ('THREE_STEP_TRIAL_EXECUTED' if self.three_step_trial else 'FIXED_STEP_EXECUTED')
                    and result['native_result'].get('service_binding') == self.service_binding
                    and self.workflow.reason != 'STOP_PENDING' and not self.fixed_trial.stopping)
                self.workflow.status, self.workflow.robot_status = 'HOLD', None
                self.workflow.robot_resume_allowed = False
                self.workflow.reason = (('THREE_STEP_TRIAL_EXECUTED_B_CONFIRMATION_REQUIRED' if self.three_step_trial
                    else 'APPROVED_STEP_EXECUTED_B_CONFIRMATION_REQUIRED') if matched
                    else 'APPROVED_STEP_INTERRUPTED_OR_FAILED_VERIFY_PHYSICAL_STATE')
                self.workflow.event('ROUND3_APPROVED_STEP_RESULT', dict(result, binding_matched=matched))
                if matched and self.live_inspection_mode and not self.workflow.log_failed:
                    self.workflow.execution_closed = True
                    self.workflow.status = 'WAIT_ASSEMBLY'
                    self.workflow.request_check('STEP')
                if self.camera_free_trial:
                    self.archive_trial()
        while not self.trial_archive_inbox.empty():
            job, status, reason = self.trial_archive_inbox.get_nowait()
            if job == self.workflow.job_id:
                if status == 'DB_RECORDED':
                    self.trial_db_recorded = True
                self.trial_archive_status, self.trial_archive_reason = status, reason

    def archive_trial(self):
        """Persist an unverified trial, preserving the normal FINAL-gated save path."""
        if (not self.camera_free_trial or self.fixed_result is None or self.history_dsn is None
                or not self.creator or not self.job_creator or self.login_pending
                or self.creator['user_id'] != self.job_creator['user_id']
                or self.trial_archive_status in ('PENDING','DB_RECORDED')):
            return False
        job, creator = self.workflow.job_id, deepcopy(self.job_creator)
        credentials, web_only = self._credentials, self.trial_db_recorded
        if not credentials or credentials[0] != creator['username']:
            return False
        self.trial_archive_status, self.trial_archive_reason = 'PENDING', None
        if not self.workflow.event('ROUND3_TRIAL_ARCHIVE_REQUESTED', dict(
                trial_scope='SIXPART_REAL_D_THREE_STEP_TRIAL' if self.three_step_trial else 'SIXPART_REAL_D_SINGLE_STEP',
                web_only=web_only, assembly_completion=False)):
            self.trial_archive_status = 'FAILED'
            return False
        def run():
            try:
                from history import store
                from history.mvp_save import link_current_job, verify_web_job
                if not web_only:
                    with store.connect(self.history_dsn) as connection:
                        link_current_job(connection,self.workflow.log_directory,job,creator)
                    self.trial_archive_inbox.put((job,'DB_RECORDED',None))
                verify_web_job(self.web_url,job,*credentials,None)
                self.trial_archive_inbox.put((job,'SUCCEEDED',None))
            except Exception as error:
                self.trial_archive_inbox.put((job,'FAILED',
                    str(error) if isinstance(error,ValueError) else type(error).__name__))
        worker = Thread(target=run,daemon=True)
        self.workers.append(worker)
        worker.start()
        return True

    def trial_display(self):
        order = ['T2','T1','T3']
        progress = self.fixed_trial.progress() if self.fixed_trial is not None else None
        data = progress.get('data',{}) if progress else {}
        event = progress.get('event') if progress else None
        identity = data.get('step',{}).get('step_id') or data.get('step_id') or order[0]
        identity = identity if identity in order else order[0]
        index = order.index(identity)
        completed = index + (1 if event=='TRIAL_HOME_RETURNED' else 0)
        if self.fixed_result is not None and self.fixed_result['status']=='THREE_STEP_TRIAL_EXECUTED':
            completed = 3
        cases = {case['step_id']:case for case in self.scenario['steps']}
        return dict(step_id=identity,index=index,completed=completed,event=event,target=cases[identity]['target'],
            trial_expected=[deepcopy(row['block']) for row in self.scenario['preplaced']]
                +[deepcopy(cases[step]['target']) for step in order[:completed]])

    def stop_retired_inspection(self):
        from app.round3_initial_inspection import open_motion
        identity = self.workflow.execution_id or self.workflow.last_execution_id
        def run():
            try:
                with open_motion(self.inspection_settings, Event()) as motion:
                    sample = motion.stop()
                row = dict(event='STOP_VERIFIED', data=dict(actual_stop_verified=True,
                    execution_id=identity, previous_state='IDLE', sample=sample))
            except Exception as error:
                row = dict(event='STOP_UNVERIFIED', data=dict(execution_id=identity, reason=str(error)))
            self.robot.events.put(row)
        self.inspection_stop_worker = Thread(target=run, daemon=True)
        self.inspection_stop_worker.start()

    def close(self):
        super().close()
        if self.live_inspection_mode:
            self.b._worker.join()
            if self.inspection_stop_worker is not None:
                self.inspection_stop_worker.join()


if __name__=='__main__':main(FullFeatureRealTrial,real_trial=True)
