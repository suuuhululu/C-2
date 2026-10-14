"""A message → round2 native runner, SYNTHETIC/MOCK only; no device imports."""
from copy import deepcopy
import time

from app.assembly_step_bridge import build_plan, step_from_messages
from app.assembly_step_runner import StepReplayDriver
from app.control_session import ControlSession
from app.round2_step_controller import binding, prepare_round2_step, run_round2_step


class Round3StepReplay:
    def __init__(self, document, record):
        if document['session']['backend'] != 'TEST' or document['session']['provenance'] != 'SYNTHETIC':
            raise ValueError('ROUND3_REPLAY_REQUIRES_TEST_SESSION')
        self.record = record
        self.request = None
        self.state = 'IDLE'
        self.raw = None
        self.session = None
        self.config = deepcopy(document['round2_replay'])
        if self.config.get('provenance') != 'SYNTHETIC':
            raise ValueError('ROUND3_EXPLICIT_SYNTHETIC_INPUT_REQUIRED')
        step = step_from_messages(document['assessment'], document['request'], document['motion'],
            case_id=document['case_id'])
        self.source = build_plan(step, document['d_profile'])
        from scipy.spatial.transform import Rotation
        robot_pose = document['request']['robot_state']['tcp_pose']
        self.start_pose = [v*1000 for v in robot_pose['xyz_m']] + Rotation.from_quat(
            robot_pose['quaternion_xyzw']).as_euler('ZYZ', degrees=True).tolist()
        self.identity = dict(execution_id=document['session']['execution_id'],
            plan_id=self.source['plan_id'], step_id=self.source['step_id'],
            current_revision=self.source['current_revision'])
        measured = deepcopy(self.config.get('measured'))
        if measured is not None:
            if measured.get('block') != self.source['block']:
                raise ValueError('ROUND3_MEASUREMENT_BLOCK_MISMATCH')
            measured['key'] = self.source['key']
        self.prepared = prepare_round2_step(self.source, document['d_profile'], measured)
        self.plan = self.prepared['execution_candidate']
        self.profile = self.prepared['profile']
        self.session = ControlSession(document['session'], self.plan, self.emit)

    def emit(self, event, data):
        self.record(event, dict(deepcopy(data), **self.identity, provenance='SYNTHETIC', physical_commands=0))

    def can_resume(self):
        return False

    def start(self):
        if self.state != 'IDLE':
            raise RuntimeError('ROUND3_REPLAY_ALREADY_STARTED')
        self.state = 'RUNNING'

    def stop(self):
        self.session.request_stop('ROUND3_REPLAY_STOP')
        if self.raw is not None:
            self.raw.stop()
        if self.state in ('AWAITING_INSPECTION', 'RECOVERY_REQUIRED'):
            self.state = 'STOPPED'
            self.emit('STOP_VERIFIED', dict(actual_stop_verified=True, synthetic_stop=True))

    def held(self, reason):
        self.state = 'STOPPED' if self.session.cancelled else 'RECOVERY_REQUIRED'
        self.emit('EXECUTION_HELD', dict(status=self.state, reason=reason, resume_allowed=False))

    def pickup(self, plan, sample):
        self.session.check()
        return dict(status='VISION_GRASP_PLAN_FOR_REVIEW', policy='COORDINATE_FIRST_WITH_OPTIONAL_CENTER',
            candidate_tcp_mm_zyz_deg=deepcopy(plan['settings']['pickup_pose']),
            center_assist_applied=False, fallback_reason='SYNTHETIC_TAUGHT_PICKUP_NO_CAMERA')

    def alignment(self, stage, plan, sample):
        self.session.check()
        now = time.monotonic_ns()
        common = dict(binding=binding(plan), reference_kind='REGISTERED_BLOCK_AND_STUD_PLANES',
            frame_stamp_ns=now, capture_timing=dict(clock_domain='TEST_MONOTONIC',
                pose_clock_domain='TEST_MONOTONIC', clock_now_ns=now, pose_stamp_ns=now,
                pose_posx=deepcopy(sample['posx']), exposure_monotonic_ns=now,
                exposure_mapping_error_ns=0, clock_mapping_ref='SYNTHETIC_TEST_CLOCK'))
        if stage == 'BEFORE':
            landing = plan['settings']['reference_pose']
            return dict(common, status='SURFACE_ALIGNMENT_CANDIDATE', registration_reviewed=True,
                approach_pose=[*landing[:2], sample['posx'][2], *landing[3:]],
                landing_pose=deepcopy(landing), pad_contact_z_mm=self.config['measured']['pad_contact_pose'][2])
        return dict(common, status='SURFACE_ALIGNMENT_OBSERVATION', plane_error_deg=0.,
            center_error_mm=0., roll_error_deg=0., pitch_error_deg=0., yaw_error_deg=0.)

    def run(self):
        try:
            self.session.check()
            if not self.prepared['robot_complement_selected'] or self.plan['assistance_kind'] != 'NONE':
                self.held(self.prepared.get('reason') or 'ROUND3_REPLAY_UNSUPPORTED_METHOD')
                return
            if self.config.get('providers') != ['pickup', 'alignment']:
                self.held('ROUND3_REPLAY_PROVIDERS_REQUIRED')
                return
            if not self.config.get('measured', {}).get('pad_contact_pose'):
                self.held('ROUND3_REPLAY_PAD_MEASUREMENT_REQUIRED')
                return
            # These are explicit test limits and imposed contact, never physical evidence.
            self.profile.update(round2_alignment_limits=dict(max_translation_mm=20., max_rotation_deg=90.,
                max_plane_error_deg=.5, max_center_error_mm=.5),
                round2_capture_limits=dict(max_frame_age_ns=1_000_000_000, max_pose_skew_ns=20_000_000,
                    max_clock_mapping_error_ns=1_000_000))
            raw = StepReplayDriver([0., 0., -1_000_000., 0., 180., 0.],
                reaction_force_n=self.profile['force_stop_n']+1.,
                grasp_width_mm=self.plan['settings']['pickup_width_mm'])
            self.raw = raw
            raw.value['posx'] = deepcopy(self.start_pose)
            self.emit('EXECUTION_STARTED', dict(resume=False, synthetic_contact=True))

            def record(event, data):
                self.session.check()
                if event == 'PRESS_SESSION':
                    raw.use_press_tool_reference(self.config['measured']['pad_contact_pose'])
                self.emit(event, data)

            def confirm(kind, plan, sample):
                self.session.check()
                if kind == 'GRASP_CONFIRMED':
                    self.emit('GRIP_SUCCEEDED', dict(label='PICKUP_CLOSE', sample=sample))
                return True  # Explicit synthetic operator response, MOCK only.

            result = run_round2_step(raw, dict(tcp='GripperDA_v4', tool='ToolWeight0'),
                self.prepared | {'profile':self.profile}, confirm, record,
                pickup_center=self.pickup, assembly_alignment=self.alignment, session=self.session)
            self.session.check()
            if result['status'] != 'AWAITING_BACKEND_OBSERVATION':
                self.held(result['status'])
                return
            self.state = 'AWAITING_INSPECTION'
            self.emit('ROUND3_STEP_REPLAY_RESULT', dict(result=result, assembly_completion=False,
                current_update=False, inspection_requested=False, sample=raw.sample(),
                saved_observation_flow=self.config.get('saved_observation_flow') is True))
        except Exception as error:
            if self.raw is not None:
                self.raw.stop()
            self.held(str(error))
        finally:
            if self.session.cancelled:
                self.state = 'STOPPED'
                self.emit('STOP_VERIFIED', dict(actual_stop_verified=True, synthetic_stop=True))
