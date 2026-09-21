"""제어 서버를 대신하는 HMI 응답 fixture. 로봇/측정 함수 호출·실제 좌표 적합 없음."""
import asyncio
import math
from copy import deepcopy

from .monitor_contract import now


async def prepare_fixture(goal, config, feedback, cancel, tick, scenario):
    w = config['workcell']
    sim = w['simulation']
    started = asyncio.get_running_loop().time()
    m = dict(schema='workpiece-measurement/1', source_mode='SIMULATION', frame_id='c2_base', position_unit='m',
             preparation_id=goal['preparation_id'], measurement_id=goal['measurement_id'],
             profile_snapshot_id=goal['input_profile_snapshot_id'], profile_sha256=goal['input_profile_sha256'],
             validity='INCOMPLETE', geometry_ready=False, points=[], top=None, axis_xy_m=None, radius_m=None,
             top_z_m=None, bottom_z_m=None, measured_at=None,
             origin='HMI_MOCK_FIXTURE', vertical_axis_assumed=True, tilt_measured=False,
             independent_accuracy_verified=False, height_m=w['height_m'], height_source=w['height_source'])
    observed = dict(measurement=m, events=[], plans=[], partial=True, stop_confirmed=None)

    def result(outcome, code, message):
        observed['elapsed_s'] = asyncio.get_running_loop().time() - started
        return dict(outcome=outcome, error_code=code, message=message, observed_state=deepcopy(observed))

    async def emit(stage, status, message, point=0):
        event = dict(preparation_id=goal['preparation_id'], measurement_id=goal['measurement_id'],
                     sequence=len(observed['events'])+1, stage=stage, status=status, message=message,
                     point_index=point, total_points=8, measured_at=now())
        observed['events'].append(event)
        await feedback(deepcopy(event))

    async def step(stage, label, point=0):
        await emit(stage, 'RUNNING', label, point)
        try:
            await asyncio.wait_for(cancel.wait(), tick)
        except asyncio.TimeoutError:
            return True
        return False

    def stopped():
        observed['stop_confirmed'] = scenario != 'stop_unknown'
        return result('STOPPED' if observed['stop_confirmed'] else 'UNKNOWN',
                      'NONE' if observed['stop_confirmed'] else 'STOP_UNCONFIRMED',
                      '모의 준비 취소·정지 확인' if observed['stop_confirmed'] else '모의 준비 정지 미확인')

    if not await step('ROBOT_STATUS', '모의 로봇 상태 확인 중'):
        return stopped()
    if scenario == 'preparation_failure':
        observed['measurement'] = None
        return result('FAILED', 'NOT_READY', '모의 준비 상태 검사 실패 · 측정 미호출')
    await emit('ROBOT_STATUS', 'SUCCEEDED', '모의 로봇 상태 확인 완료')
    for stage, label in (
            ('HOME_CHECK', '모의 홈 확인'),
            ('HOME_MOVE', '모의 비홈 시나리오 · 검사된 홈 이동'),
            ('HOME_RECHECK', '모의 홈 도착·정지 후 상태 재검사')):
        if not await step(stage, label):
            return stopped()
        await emit(stage, 'SUCCEEDED', label + ' 완료')
    if not await step('MEASUREMENT_PRECHECK', '모의 측정 조건 확인 중'):
        return stopped()
    if scenario == 'preparation_timeout':
        await cancel.wait()
        return stopped()
    if not await step('TOP_APPROACH', '모의 윗면 접근 중'):
        return stopped()
    if not await step('TOP_TOUCH', '모의 윗면 접촉 확인 중'):
        return stopped()
    m['top_z_m'] = None if scenario == 'measurement_reference_only' else sim['top_z_m']
    m['top'] = dict(source='HMI_MOCK_FIXTURE', point_index=0, received_at=now())
    await emit('TOP_TOUCH', 'SUCCEEDED', '모의 윗면 측정 완료')
    await emit('SIDE_START', 'RUNNING', '모의 옆면 8점 측정 시작')
    for index in range(1, 9):
        if not await step('SIDE_TOUCH', f'모의 {index}/8번째 점 측정 중', index):
            return stopped()
        angle = math.radians(w['angles_deg'][index-1])
        m['points'].append(dict(point_index=index, source='HMI_MOCK_FIXTURE', received_at=now(),
            tip_pose=[sim['axis_xy_m'][0]+sim['radius_m']*math.cos(angle),
                      sim['axis_xy_m'][1]+sim['radius_m']*math.sin(angle), sim['top_z_m']-w['side_depth_m'], 0, 0, 0, 1]))
        await emit('SIDE_TOUCH', 'SUCCEEDED', f'모의 {index}/8번째 점 측정 완료', index)
    if not await step('RETRACT', '모의 정상 후퇴·정지 확인 중'):
        return stopped()
    if not await step('FIT', '모의 중심·반지름 결과 준비 중'):
        return stopped()
    # 아래 수치는 계산/새 실측 결과가 아니라 공정팀 SIM 설정의 합성 fixture다.
    m.update(axis_xy_m=sim['axis_xy_m'], radius_m=sim['radius_m'], measured_at=now(),
             work_v_range_m=[w['top_margin_m'], w['height_m']-w['bottom_margin_m']])
    if m['top_z_m'] is not None:
        m.update(bottom_z_m=m['top_z_m']-w['height_m'],
                 work_z_range_m=[m['top_z_m']-w['height_m']+w['bottom_margin_m'], m['top_z_m']-w['top_margin_m']],
                 geometry_ready=True, validity='SIMULATED')
    else:
        m.update(work_z_range_m=None, validity='REFERENCE_ONLY')
    observed.update(partial=False, stop_confirmed=True)
    await emit('COMPLETE', 'SUCCEEDED', '모의 측정·후퇴 완료, 최종 준비 결과 확인 중')
    if cancel.is_set():
        m.update(geometry_ready=False, validity='INCOMPLETE')
        return stopped()
    if not m['geometry_ready']:
        return result('FAILED', 'NOT_READY', '절대 윗면 미확인 · 참조 결과만 보존')
    return result('SUCCEEDED', 'NONE', '모의 준비·측정 완료 · 실기 실행 승인 아님')
