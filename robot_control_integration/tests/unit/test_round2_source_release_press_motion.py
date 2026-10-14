"""SYNTHETIC/MOCK workflow checks; imposed contact is not validated physics."""
from copy import deepcopy
import time

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app import assembly_step_runner as runner
from app.assembly_step_bridge import build_plan, step_from_messages
from app.round2_step_controller import binding, prepare_round2_step, run_round2_step
from tests.unit.test_assembly_strategy import source_case, strategy_messages
from tests.unit.test_control_session import Clock
from tests.unit.test_round2_step_controller import no_center


class PadReplay(runner.StepReplayDriver):
    """The contact surface and persistent stopped load are explicitly imposed."""
    def __init__(self, *, jitter=False,residual_n=60.):
        super().__init__([400.,80.,-100.,0.,180.,0.],reaction_force_n=48.)
        self.press_references=[];self.after_pressure_stop=False;self.residual_n=residual_n
        if jitter:self.value['velx']=[.02,0.,0.,.01,0.,0.]

    def command_gripper(self,width,force):
        super().command_gripper(width,force)
        if width==4.:self.value.update(gripper_status=2,gripper_width_mm=9.3)

    def use_press_tool_reference(self,reference):
        self.reference=reference.copy();self.press_references.append(reference.copy())

    def stop(self):
        super().stop();self.after_pressure_stop=True;self.value['wrench'][2]=self.residual_n

    def move_line_async(self,target,velocity,acceleration):
        super().move_line_async(target,velocity,acceleration)
        if self.after_pressure_stop:self.value['wrench'][2]=self.residual_n


def alignment_provider(landing):
    """Fake registered camera packets through the actual alignment loop."""
    def observe(stage,plan,sample):
        now=time.monotonic_ns()
        common=dict(binding=binding(plan),reference_kind='REGISTERED_BLOCK_AND_STUD_PLANES',
            frame_stamp_ns=now,capture_timing=dict(clock_domain='TEST_MONOTONIC',
                pose_clock_domain='TEST_MONOTONIC',clock_now_ns=now,pose_stamp_ns=now,
                pose_posx=sample['posx'].copy(),exposure_monotonic_ns=now,
                exposure_mapping_error_ns=0,clock_mapping_ref='SYNTHETIC_TEST_CLOCK'))
        if stage=='BEFORE':
            return dict(common,status='SURFACE_ALIGNMENT_CANDIDATE',registration_reviewed=True,
                approach_pose=[*landing[:2],sample['posx'][2],*landing[3:]],
                landing_pose=landing.copy(),pad_contact_z_mm=999.)
        return dict(common,status='SURFACE_ALIGNMENT_OBSERVATION',plane_error_deg=0.,
            center_error_mm=0.,roll_error_deg=0.,pitch_error_deg=0.,yaw_error_deg=0.)
    return observe


def case(force=45., *, motion_policy='null'):
    step,profile=source_case('NONE');profile['force_stop_n']=force
    profile.update(target_only_motion=True,
        round2_alignment_limits=dict(max_translation_mm=20.,max_rotation_deg=90.,
            max_plane_error_deg=.5,max_center_error_mm=.5),
        round2_capture_limits=dict(max_frame_age_ns=1_000_000_000,max_pose_skew_ns=20_000_000,
            max_clock_mapping_error_ns=1_000_000))
    if motion_policy=='null':profile['motion_force_stop_n']=None
    if motion_policy=='disabled':profile['noncontact_force_guard']=False
    plan=build_plan(step,profile)
    pad=[402.4,78.3,60.5,13.,176.,11.]
    return prepare_round2_step(plan,profile,dict(pad_contact_pose=pad,press_width_mm=4.)),pad


@pytest.mark.parametrize('force',[40.,45.])
@pytest.mark.parametrize('motion_policy',['null','disabled'])
def test_source_air_release_compensation_keeps_absolute_pad_then_actual_press_and_rise(force,motion_policy):
    prepared,pad=case(force,motion_policy=motion_policy);before=deepcopy(prepared)
    driver=PadReplay(jitter=True);clock=Clock();events=[]
    landing=[406.,77.,41.2,30.,170.,10.]
    def record(event,data):events.append((event,deepcopy(data)))
    result=run_round2_step(driver,dict(tcp='GripperDA_v4',tool='ToolWeight0'),prepared,
        lambda *_:True,record,pickup_center=no_center,assembly_alignment=alignment_provider(landing),
        phase='full',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert result['status']=='AWAITING_BACKEND_OBSERVATION' and result['robot_press_executed']
    assert not result['assembly_completion'] and not result['current_update'] and prepared==before
    moves=[data for event,data in events if event=='STEP_MOVE']
    release=next(data['target'] for data in moves if data['label']=='RELEASE_POSITION')
    old=prepared['execution_candidate']['settings'];reference=old['reference_pose']
    assert release[:3]==pytest.approx([old['release_pose'][i]+landing[i]-reference[i] for i in range(3)])
    assert release[2]-landing[2]==pytest.approx(4.5)
    relation=Rotation.from_euler('ZYZ',reference[3:],degrees=True).inv()*Rotation.from_euler('ZYZ',old['release_pose'][3:],degrees=True)
    actual_relation=Rotation.from_euler('ZYZ',landing[3:],degrees=True).inv()*Rotation.from_euler('ZYZ',release[3:],degrees=True)
    assert np.allclose(relation.as_matrix(),actual_relation.as_matrix())
    retreat=next(data['target'] for data in moves if data['label']=='RAISED_EMPTY_VERTICAL_RETREAT')
    approach=next(data['target'] for data in moves if data['label']=='PRESS_TOOL_APPROACH')
    lower=next(data['target'] for data in moves if data['label']=='PRESS_TOOL_LOWER')
    assert retreat[:2]==release[:2] and retreat[3:]==release[3:]
    assert approach[:2]==pad[:2] and approach[3:]==pad[3:] and approach[2]==retreat[2]
    assert lower==old['press_start_pose'] and lower[:2]!=release[:2]
    assert driver.press_references==[pad]
    labels=[data['label'] for data in moves]
    assert labels.index('RELEASE_POSITION')<labels.index('RAISED_EMPTY_VERTICAL_RETREAT')<labels.index('PRESS_TOOL_APPROACH')<labels.index('PRESS_TOOL_LOWER')
    pressure=next(data for event,data in events if event=='PRESS_SESSION')
    assert pressure['initial_sample']['posx']==lower and pressure['force_stop_n']==force
    assert pressure['travel_endpoint_posx'][:2]==pad[:2] and pressure['travel_endpoint_posx'][3:]==pad[3:]
    outcome=next(data for event,data in events if event=='PRESS_RESULT')
    assert outcome['status']=='FORCE_THRESHOLD_REACHED_STOP_VERIFIED' and outcome['threshold_force_norm_n']==48.
    assert outcome['final_sample']['wrench'][2]==60.
    assert moves[-1]['label']=='LIFT' and moves[-1]['target'][:2]==pad[:2]
    assert moves[-1]['target'][3:]==pad[3:] and driver.value['wrench'][2]==60.


def test_source_without_explicit_noncontact_policy_keeps_previous_motion_force_guard():
    prepared,_=case(40.,motion_policy='default');driver=PadReplay();clock=Clock();events=[]
    with pytest.raises(RuntimeError,match='FORCE_NORM_STOP_LIMIT_REACHED'):
        run_round2_step(driver,dict(tcp='GripperDA_v4',tool='ToolWeight0'),prepared,
            lambda *_:True,lambda event,data:events.append((event,deepcopy(data))),
            pickup_center=no_center,assembly_alignment=alignment_provider([406.,77.,41.2,30.,170.,10.]),
            phase='full',start_zone='supply',clock=clock,sleep=clock.sleep)
    assert any(event=='PRESS_RESULT' for event,_ in events)
    assert next(data for event,data in events if event=='PRESS_SESSION')['force_stop_n']==40.


def test_d_profile_messages_keep_explicit_air_release_through_native_execution():
    assessment,request,motion,profile=strategy_messages()
    # A StepMotion cannot supply this method; D's bound profile owns these poses.
    a_blocked=dict(deepcopy(motion),message_type='StepMotionResult',producer=None,
        status='BLOCKED',motion_proposal=None,errors=[dict(code='UNSUPPORTED_METHOD')])
    with pytest.raises(ValueError,match='MOTION_NOT_CANDIDATE'):
        step_from_messages(assessment,request,a_blocked,case_id='square')
    plan=build_plan(step_from_messages(assessment,request,motion,case_id='square'),profile)
    prepared=prepare_round2_step(plan,profile)
    driver=PadReplay(residual_n=25.);clock=Clock();events=[]
    result=runner.run_step(driver,dict(tcp='GripperDA_v4',tool='ToolWeight0'),
        prepared['execution_candidate'],prepared['profile'],lambda *_:True,
        lambda event,data:events.append((event,deepcopy(data))),phase='full',start_zone='supply',
        clock=clock,sleep=clock.sleep)
    release=next(data['target'] for event,data in events if event=='STEP_MOVE' and data['label']=='RELEASE_POSITION')
    assert release==profile['steps'][plan['key']]['release_pose']
    assert release[2]>profile['steps'][plan['key']]['reference_pose'][2]
    assert result['status']=='AWAITING_BACKEND_OBSERVATION' and result['robot_press_executed']
