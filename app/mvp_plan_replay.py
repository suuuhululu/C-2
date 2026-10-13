"""승인 설계 로그와 현재 D 설정으로 A만 재계산한다. 장치/외부 API 호출 없음."""
import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from app.mvp_calculation import whole_input
from planning_trial.assembly_adapter import handle_whole_plan


def approved_input(path):
    current = None
    job_id = None
    for line in Path(path).read_text().splitlines():
        row = json.loads(line)
        if row.get('event') == 'JOB_STARTED':
            current = None
            job_id = row['job_id']
        result = row.get('result') or {}
        response = result.get('response') or {}
        if (row.get('event') == 'CHECK_RESULT' and result.get('disposition') == 'ACCEPTED'
                and response.get('status') == 'OK'):
            current = deepcopy(response['current'])
        if (row.get('event') == 'MODULE_RESULT' and result.get('port') == 'c.review'
                and response.get('status') == 'OK' and response.get('hri_result') == 'APPROVE'):
            if current is None:
                raise ValueError('승인 전 채택 Current가 없습니다')
            return deepcopy(response['design']), current, job_id or row['job_id']
    raise ValueError('C APPROVE 설계가 로그에 없습니다')


def replay(log, robot_root, output):
    # REAL 실행 앱을 만들지 않는다. 기존 프로필 파일과 교시값만 읽는다.
    from app.cad_trial import measured_inputs
    from app.mvp_real_trial import real_settings
    design, current, job_id = approved_input(log)
    settings = real_settings(measured_inputs(robot_root))
    request = whole_input(design, current, settings, job_id, 1, 'OFFLINE_PLAN_REPLAY')
    audit = {}
    result = handle_whole_plan(request, audit=audit)
    report = dict(source_log=str(Path(log).resolve()),
        input_basis='LOG_APPROVED_DESIGN_AND_CURRENT_WITH_CURRENT_D_SETTINGS',
        original_request_recorded=False, robot_executed=False, external_api_called=False,
        request=request, raw_result=audit.get('raw_result'), result=result)
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in [('design', design), ('current', current), ('replay', report)]:
        (directory/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    actions = result['action_proposals']
    kinds = sorted({a['mode']+'/'+a['assistance_kind'] for a in actions})
    print('A 계산:', result['calculation_status'])
    print('선택된 방식:', ', '.join(kinds) or '계획 없음')
    print('실패 이유:', json.dumps(result['stage_errors'], ensure_ascii=False))
    optimization = (audit.get('raw_result') or {}).get('optimization') or {}
    print('탐색 상태 수:', optimization.get('expanded_states', '반환 없음'))
    for item in optimization.get('blocked_candidates', []):
        block = item['block']
        print(f"막힌 블록: {block['color']} {block['brick_type']} "
              f"({block['x']},{block['y']}) {block['layer']}층 · "
              + item['assessment']['reason'])
    print('자료:', directory.resolve())
    print('로봇/Camera/음성/외부 LLM/DB 호출 없음 · 실제 실행 승인 아님')
    planning = result.get('planning_result') or {}
    return 0 if planning.get('status') in ('READY', 'DONE') else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', required=True, type=Path)
    parser.add_argument('--robot-root', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('logs/plan-replay')/datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    args = parser.parse_args()
    return replay(args.log, args.robot_root, args.output)


if __name__ == '__main__':
    raise SystemExit(main())
