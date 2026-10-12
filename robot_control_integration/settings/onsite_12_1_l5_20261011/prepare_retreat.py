"""This local recovery only lifts the already open tool; --run and START_RETREAT yes required."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app.assembly_step_bridge import build_plan, validate_physical
from app.control_session import validate_execution


def prepare_candidate():
    journals = list((ROOT/'logs/release-recovery-doctor-20261011').glob('trial-*.jsonl'))
    if not journals:
        raise ValueError('RECOVERY_DOCTOR_LOG_REQUIRED')
    evidence = max(journals, key=lambda p: p.stat().st_mtime)
    rows = [json.loads(line) for line in evidence.read_text().splitlines() if line.strip()]
    samples = [row['data'] for row in rows if row['event'] == 'READ_ONLY_DOCTOR']
    if not samples:
        raise ValueError('RECOVERY_DOCTOR_SAMPLE_REQUIRED')
    sample = samples[-1]
    value = json.loads((DIRECTORY/'held-release.reviewed-v2.json').read_text())
    profile = value['d_profile']
    key = value['step']['case_id']+'/'+value['step']['step_id']
    settings = profile['steps'][key]
    lo, hi = settings['release_feedback_range_mm']
    if (sample['gripper_status'] != 0 or not lo <= sample['gripper_width_mm'] <= hi or
            sample['motion_status'] != 0 or any(sample['velx']) or sample['query_duration_s'] > .5 or
            sample['tcp'] != 'GripperDA_v4' or sample['tool'] != 'ToolWeight0' or
            sample['robot_state'] not in (1, 2) or sample['robot_mode'] != 1 or sample['drl_state'] != 3):
        raise ValueError('OPEN_STOPPED_RECOVERY_FEEDBACK_REQUIRED')
    profile['profile_id'] = 'D_LOCAL_OPEN_RETREAT_ONLY_12_1_L5_20261011'
    profile['clearance_z_mm'] = settings['reference_pose'][2]+profile['approach_offset_mm']
    profile['descent_velocity'], profile['descent_acceleration'] = 2., 1.
    settings['recovery_start_pose'] = sample['posx'].copy()
    value.update(status='UNARMED_OPEN_VERTICAL_RETREAT_ONLY', recovery_evidence_ref=str(evidence.resolve()),
                 recovery_target_z_mm=profile['clearance_z_mm'], robot_gripper_commands=0,
                 physical_verified=False, assembly_completion=False, current_update=False)
    value['operator_confirmations']['held_yellow_2x2'] = False
    value['operator_confirmations']['released_block_remains_seated'] = True
    value['operator_review_scope'] = 'Already open tool; vertical retreat to prior approach height only'
    validate_physical(build_plan(value['step'], profile), profile, 'retreat')
    return value


def make_session(value):
    session = deepcopy(json.loads((DIRECTORY/'session.release.live.json').read_text()))
    session.update(execution_id=str(uuid4()), source_epoch='ONSITE_RETREAT_20261011_'+uuid4().hex,
                   expires_unix_s=time.time()+600., allowed_trial_phase='retreat',
                   profile_id=value['d_profile']['profile_id'],
                   recovery_evidence_ref=value['recovery_evidence_ref'],
                   parent_failed_release_execution_id='f64459f0-9ea2-4a3e-aa57-61f9ce988015')
    validate_execution(build_plan(value['step'], value['d_profile']), value['d_profile'], session, 'retreat')
    return session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    value = prepare_candidate()
    key = value['step']['case_id']+'/'+value['step']['step_id']
    start = value['d_profile']['steps'][key]['recovery_start_pose']
    print(f"수직 상승 복구: Z={start[2]:.3f} → {value['recovery_target_z_mm']:.3f}mm, 2mm/s, 가속도1mm/s²", flush=True)
    print('현재 X/Y/자세 유지, 그리퍼 명령 0회. 시작 위치/개방 폭/정지 상태를 다시 확인합니다.', flush=True)
    if not args.run:
        print('미리보기 완료: 장치 연결·이동 없음. --run 실행 시 START_RETREAT 현장 확인을 받습니다.')
        return 0
    session = make_session(value)
    prefix = 'retreat-'+session['execution_id']
    profile_path, session_path = DIRECTORY/(prefix+'.profile.json'), DIRECTORY/(prefix+'.session.json')
    for path, data in ((profile_path, value), (session_path, session)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    print('상승 경로에 손/장애물이 없음을 확인한 뒤 START_RETREAT 요청에 yes를 입력하세요.', flush=True)
    return subprocess.run([str(ROOT/'robot-control-test.sh'), 'run', '--held-profile', str(profile_path),
        '--session', str(session_path), '--phase', 'retreat', '--output',
        str(ROOT/'logs/onsite_12_1_l5_20261011'/prefix), '--execute'], check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
