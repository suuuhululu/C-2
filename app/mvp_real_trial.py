"""전체 C/A/D 실물 시험. B는 명시적인 가짜 관측이며 Camera 판정이 아니다."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

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
                 fixed_trial_scenario=None,supply_depth_profile=None,educational_depth_demo=False,execution_profile=None,**kwargs):
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
            runtime_settings=real_settings(self.inputs),gestures=True)
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
    """One approved A step through its native case; B owns the saved initial Current."""
    approved_step_mode = True

    def __init__(self, robot_root, directory, *, initial_observation, fixed_trial_scenario,
                 execution_profile, **kwargs):
        from app.round3_approved_step import load_initial_capture
        self.scenario_path = Path(fixed_trial_scenario).resolve()
        self.registry_path = Path(execution_profile).resolve()
        self.initial_observation, self.initial_packet = load_initial_capture(initial_observation)
        packet = self.initial_packet
        self.scenario = json.loads(self.scenario_path.read_text())
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
                         execution_profile=self.registry_path, **kwargs)
        self.workflow.settings['observation_kind'] = 'SAVED_REAL_INITIAL_ONLY'
        self.workflow.settings['geometry_reference'] = packet['geometry_reference']

    def observe(self, context, active):
        from app.round3_approved_step import file_digest
        packet = self.initial_packet
        if (not active() or self.initial_consumed or context['check_kind'] != 'INITIAL'
                or not 0 <= time.time() - packet['captured_unix_s'] <= 300
                or any(file_digest(path) != digest for path, digest in packet['source_sha256'].items())):
            raise ValueError('APPROVED_STEP_FRESH_INITIAL_OBSERVATION_REQUIRED')
        self.initial_consumed = True
        return dict(deepcopy(self.initial_observation), check_id=context['check_id'],
                    observation_seq=context['observation_seq']), dict(observation_kind='SAVED_REAL_INITIAL_ONLY')

    def command(self, name):
        if name in ('RESUME', 'REINSPECT', 'CONTINUE_AFTER_CORRECTION'):
            return False
        if self.fixed_trial is not None and name != 'STOP':
            return False
        accepted = super().command(name)
        if accepted and name == 'START':
            return self.workflow.event('ROUND3_INITIAL_CAPTURE_SOURCE', self.initial_packet)
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
            if (not same_blocks(self.workflow.current['blocks'], baseline)
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
            frame = prepared['frame_profile']['calculation_profiles']
            frame['supply']['d_taught_slot'] = dict(identity=dict(brick_type=target['brick_type'],
                color=target['color'], slot_index=cfg['trial_step']['supply_slot']), tcp_mm_zyz_deg=pick,
                source_sha256=cfg['educational_supply_binding']['registry_sha256'])
            frame['assembly']['d_onsite_step'].update(pickup_pose=pick, reference_pose=reference,
                assembly_tcp_zyz_deg=reference[3:])
            next(iter(prepared['d_profile']['steps'].values())).update(pickup_pose=pick,
                reference_pose=reference, assembly_tcp_zyz_deg=reference[3:])
            self.workflow.prepared_step(prepared)
        except (ValueError, KeyError, OSError) as error:
            self.workflow.status, self.workflow.reason = 'HOLD', str(error)
            self.workflow.event('APPROVED_STEP_PREPARATION_FAILED', dict(reason=str(error), robot_motion_sent=False))

    def emit(self, port, payload):
        if port == 'robot.EXECUTE':
            from app.round3_approved_step import digest, file_digest, validate_binding
            from app.round3_fixed_trial import FixedStepProcess
            document = dict(schema_version='round3-approved-step/1', approved=deepcopy(self.workflow.approved),
                planning_bundle=deepcopy(self.workflow.bundle), prepared=deepcopy(payload['bundle']),
                execution_id=payload['execution_id'], operator_review_ref=self.review_ref,
                expires_unix_s=time.time() + 120, native_config_sha256=digest(self.native_config),
                scenario_sha256=digest(self.scenario), execution_profile_sha256=file_digest(self.registry_path))
            self.service_binding = validate_binding(document, self.native_config, self.scenario, self.registry_path)
            path = self.directory / self.workflow.job_id / 'approved-step.json'
            try:
                save(path, document)
            except OSError as error:
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
                    self.directory / self.workflow.job_id / 'approved-native', scenario=self.scenario_path,
                    execution_profile=self.registry_path, approved_step_document=path,
                    native_step=self.native_config['trial_step']['step_id'])
                self.fixed_trial.start()
            except (OSError, ValueError, RuntimeError) as error:
                self.workflow.status, self.workflow.reason = 'HOLD', str(error)
                self.workflow.event('APPROVED_STEP_START_FAILED', dict(reason=str(error), assembly_completion=False))
        elif port == 'robot.STOP' and self.robot_retired:
            if self.fixed_trial is not None:
                self.fixed_trial.stop()
        else:
            super().emit(port, payload)

    def poll(self):
        super().poll()
        if self.fixed_trial is not None and self.fixed_result is None:
            result = self.fixed_trial.poll()
            if result is not None:
                self.fixed_result = result
                matched = (result['status'] == 'FIXED_STEP_EXECUTED'
                    and result['native_result'].get('service_binding') == self.service_binding
                    and self.workflow.reason != 'STOP_PENDING' and not self.fixed_trial.stopping)
                self.workflow.status, self.workflow.robot_status = 'HOLD', None
                self.workflow.robot_resume_allowed = False
                self.workflow.reason = ('APPROVED_STEP_EXECUTED_B_CONFIRMATION_REQUIRED' if matched
                    else 'APPROVED_STEP_INTERRUPTED_OR_FAILED_VERIFY_PHYSICAL_STATE')
                self.workflow.event('ROUND3_APPROVED_STEP_RESULT', dict(result, binding_matched=matched))


if __name__=='__main__':main(FullFeatureRealTrial,real_trial=True)
