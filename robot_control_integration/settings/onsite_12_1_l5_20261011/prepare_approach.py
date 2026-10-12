"""Prepare this one local extrapolation trial; motion needs --run and live HMI yes."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app.assembly_step_bridge import build_plan
from app.control_session import validate_execution

# These are trial acceptance settings, not measured device safety limits.
STILLNESS = dict(window_s=.5, max_gap_s=.5, timeout_s=5., min_samples=4,
    sample_max_duration_s=.5, position_mm=.05, orientation_deg=.05,
    linear_mm_s=.01, angular_deg_s=.01)


def prepare_candidate(directory=DIRECTORY):
    def read(name):
        return json.loads((directory/name).read_text())
    setup = deepcopy(read('held-target.candidate.json'))
    ready, ik = read('readiness.json'), read('ik-check.json')
    if ready['status'] != 'READ_ONLY_READINESS_COMPLETE' or ik['status'] != 'READ_ONLY_IK_CHECK_COMPLETE':
        raise ValueError('READ_ONLY_READINESS_AND_IK_REQUIRED')
    if setup['desired_target']['trial_min_xy'] != [12, 1] or setup['desired_target']['layer'] != 5:
        raise ValueError('THIS_HELPER_IS_ONLY_FOR_TRIAL_12_1_LAYER5')
    rows = ready['samples']
    if len(rows) < 4 or any(row['gripper_status'] != 2 or row['tcp'] != 'GripperDA_v4'
            or row['tool'] != 'ToolWeight0' or row['motion_status'] != 0
            or any(row['velx']) for row in rows):
        raise ValueError('HELD_STOPPED_FEEDBACK_REQUIRED')
    profile = setup['d_profile']
    profile['profile_id'] = 'D_LOCAL_EXTRAPOLATION_12_1_L5_APPROACH_20261011'
    profile['clearance_z_mm'] = max(profile['clearance_z_mm'], ik['start_pose'][2])
    profile['transfer_velocity'], profile['transfer_acceleration'] = 6., 3.
    profile['descent_velocity'], profile['descent_acceleration'] = 2., 1.
    settings = profile['steps'][setup['step']['case_id']+'/S01']
    # The existing runner treats zero as a live grasp reference, preserving ABC.
    # Keeping this field absent would restore the old taught absolute ABC.
    settings.update(turn_base_z_deg=0., turn_reference='CURRENT_SESSION_GRASP_BASE_Z',
        turn_stage='ABOVE_TARGET_AT_TRANSPORT_CLEARANCE')
    settings['notes'] = [note for note in settings['notes']
        if note != 'NO_EXTRA_YAW_ROTATION_DOES_NOT_MEAN_RUNNER_PRESERVES_LIVE_ABC']
    settings['notes'].append('ZERO_RELATIVE_TURN_PRESERVES_LIVE_ABC_APPROACH_ONLY')
    settings['reference_pose'][3:] = ik['start_pose'][3:]
    setup['reference_pose'] = settings['reference_pose'].copy()
    setup.update(status='LOCAL_EXTRAPOLATION_APPROACH_ONLY',
        physical_verified=False, current_grasp_transform_verified=False,
        source_execution_allowed=False, extra_yaw_rotation_deg=0.,
        operator_review_scope='Trial use of existing calibration candidate; not validation of this new target')
    setup['operator_confirmations'] = dict(held_yellow_2x2=True,
        teaching_layout_unchanged=True, no_other_writers=True,
        route_and_target_clear=True, four_layer_support_present=True,
        source='Human responses in integration chat on 2026-10-11')
    return setup


def make_session(setup, *, stillness_reviewed, now=None):
    if stillness_reviewed is not True:
        raise ValueError('EXPLICIT_STILLNESS_TRIAL_PARAMETER_REVIEW_REQUIRED')
    now = time.time() if now is None else now
    value = deepcopy(setup)
    profile = value['d_profile']
    profile['physical_route_reviewed'] = True
    key = value['step']['case_id']+'/S01'
    profile['steps'][key]['physical_reference_reviewed'] = True
    value['operator_review_scope'] += '; local trial envelope and stillness settings reviewed'
    plan = build_plan(value['step'], profile)
    session = dict(backend='REAL', provenance='LOCAL_OPERATOR_TRIAL',
        execution_id=str(uuid4()), source_epoch='ONSITE_20261011_'+uuid4().hex,
        frame_profile_id='BASE_EXISTING_BOARD_20261007_EXPERIMENTAL',
        **{k: plan[k] for k in ('plan_id', 'step_id', 'current_revision')},
        expires_unix_s=now+600., request_timeout_s=60., frame_max_age_s=.3,
        frame_max_gap_s=.3, inference_max_latency_s=.3, stillness=deepcopy(STILLNESS),
        profile_id=profile['profile_id'], exclusive_control_reviewed=True,
        device_feedback_reviewed=True, stillness_parameters_reviewed=True,
        hand_clear_reviewed=True, seating_evidence_ref=None, alignment_evidence_ref=None,
        parameter_source='EXPERIMENTAL_STILLNESS_SETTINGS_OPERATOR_REVIEWED_NOT_SAFETY_LIMITS',
        allowed_trial_phase='approach', physical_verified=False)
    validate_execution(plan, profile, session, 'approach')
    return value, session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='after review, start approach with another live HMI confirmation')
    args = parser.parse_args()
    setup = prepare_candidate()
    print('대상: 노랑2x2 / 결착 시험 좌표(12,1) / 5층 / 추가 회전 없음')
    print('목표 후보 TCP XYZ:', [round(x, 3) for x in [*setup['reference_pose'][:2], setup['approach_z_mm']]])
    print('현재 파지 자세 유지, 수평6mm/s, 하강2mm/s; 접근 후 파지 유지. 결착·개방 없음.')
    print('정지 확인 시험값:', json.dumps(STILLNESS, ensure_ascii=False))
    print('위 값은 장비 안전 한계가 아닙니다. 현장에서 시험용 정지 확인 조건으로 검토합니다.')
    if input('위 정지 확인 시험값을 검토했으면 yes, 보류는 Enter: ').strip().lower() != 'yes':
        print('보류: REAL 세션 생성 및 장치 연결 없음.')
        return 1
    reviewed, session = make_session(setup, stillness_reviewed=True)
    prefix = 'approach-'+session['execution_id']
    profile_path, session_path = DIRECTORY/(prefix+'.profile.json'), DIRECTORY/(prefix+'.session.json')
    for path, data in [(profile_path, reviewed), (session_path, session)]:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    command = [str(ROOT/'robot-control-test.sh'), 'run', '--held-profile', str(profile_path),
        '--session', str(session_path), '--phase', 'approach', '--start-zone', 'assembly',
        '--output', str(ROOT/'logs/onsite_12_1_l5_20261011'/prefix), '--execute']
    if args.run:
        print('실제 접근 시험 시작: START_APPROACH 요청의 yes 전에는 이동하지 않습니다.', flush=True)
        return subprocess.run(command, check=False).returncode
    import shlex
    print('준비 완료. 10분 이내 실행 명령:', shlex.join(command))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
