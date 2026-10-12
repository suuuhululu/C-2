"""Fresh one-shot approach session; hardware execution needs --run and START_APPROACH yes."""
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
from app.assembly_motion import pose_error
from app.control_session import validate_execution


def make_preparation(directory=DIRECTORY, now=None):
    now = time.time() if now is None else now
    value = json.loads((directory/'held-approach.profile.json').read_text())
    ready = json.loads((directory/'retry-readiness.json').read_text())
    if (ready['status'] != 'READ_ONLY_RETRY_READINESS_COMPLETE' or
            not 0 <= now-ready['generated_at_unix_s'] <= 600.):
        raise ValueError('FRESH_READ_ONLY_READINESS_REQUIRED')
    start = json.loads((directory/'ik-check.json').read_text())['start_pose']
    samples = ready['samples']
    if len(samples) < 4 or any(s['gripper_status'] != 2 or s['motion_status'] != 0 or any(s['velx']) or
            s['query_duration_s'] > .5 or s['tcp'] != 'GripperDA_v4' or s['tool'] != 'ToolWeight0' or
            pose_error(s['posx'], start)[0] > .05 or pose_error(s['posx'], start)[1] > .05 for s in samples):
        raise ValueError('HELD_STOPPED_RETRY_READINESS_REQUIRED')
    target = value['desired_target']
    if (target['trial_min_xy'] != [5, 18] or target['layer'] != 4 or
            target['brick_type'] != '2x2x1' or target['orientation_deg'] != 0):
        raise ValueError('THIS_HELPER_IS_ONLY_FOR_TRIAL5_18_LAYER4_NO_TURN')
    plan = build_plan(value['step'], value['d_profile'])
    if plan['trial_footprint']['min_xy'] != [5, 18] or plan['block']['layer'] != 4:
        raise ValueError('APPROACH_TARGET_BINDING_MISMATCH')
    session = deepcopy(json.loads((directory/'session.approach.live.json').read_text()))
    session.update(execution_id=str(uuid4()), source_epoch='ONSITE_APPROACH5_18_L4_20261011_'+uuid4().hex,
                   expires_unix_s=now+600., allowed_trial_phase='approach',
                   profile_id=value['d_profile']['profile_id'],
                   **{key: plan[key] for key in ('plan_id', 'step_id', 'current_revision')})
    validate_execution(plan, value['d_profile'], session, 'approach')
    return value, session


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    value, session = make_preparation()
    print('(5,18) 4층: 현재 파지 자세 유지, 수평6mm/s → 목표 위 Z=91.708mm까지 하강2mm/s.', flush=True)
    if not args.run:
        print('미리보기 완료. 파일 생성/장치 연결/이동 없음.')
        return 0
    prefix = 'approach-'+session['execution_id']
    profile_path, session_path = DIRECTORY/(prefix+'.profile.json'), DIRECTORY/(prefix+'.session.json')
    for path, data in ((profile_path, value), (session_path, session)):
        with path.open('x') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write('\n')
    print('START_APPROACH 현장 확인의 yes 전에는 이동하지 않습니다.', flush=True)
    return subprocess.run([str(ROOT/'robot-control-test.sh'), 'run', '--held-profile', str(profile_path),
        '--session', str(session_path), '--phase', 'approach', '--start-zone', 'assembly',
        '--output', str(ROOT/'logs/onsite_5_18_l4_20261011'/prefix), '--execute'], check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
