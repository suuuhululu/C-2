"""전체 C/A/D 실물 시험. B는 명시적인 가짜 관측이며 Camera 판정이 아니다."""
from copy import deepcopy
from pathlib import Path
import time
from uuid import uuid4

from app.cad_trial import measured_inputs, step_geometry, load_release_press_profile
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
    robot = live_robot_state(receipt,frame,empty_gripper_context=receipt.get('last_step_gripper_context'))
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

    def __init__(self,robot_root,directory,*,contact_alignment_trial=False,release_press_profile=None,**kwargs):
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
        self.inputs['release_press_profile']=load_release_press_profile(release_press_profile)
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
            live_robot_state(value,self.workflow.settings['frame_profile'],
                empty_gripper_context=value.get('last_step_gripper_context'))
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
        if self.pending_read and time.monotonic()-self.pending_read['opened']>20:
            self.pending_read=None
            self.workflow.status,self.workflow.reason='HOLD','LIVE_STATE_QUERY_TIMEOUT'
        if self.workflow.release_instruction:
            self.workflow.release_instruction='B는 가짜입니다. 실물 구조의 안정을 직접 확인한 뒤 도움을 해제해주세요.'
        if self.workflow.help and self.workflow.help['kind']=='HUMAN_ASSEMBLY':
            self.workflow.help['instruction']='목표 위치에 조립한 뒤 엄지척을 보여주세요. 10초 안에 확인하지 못하면 관측을 보류하고 다시 검사합니다. B는 가짜입니다.'

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


if __name__=='__main__':main(FullFeatureRealTrial,real_trial=True)
