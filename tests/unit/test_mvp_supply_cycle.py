"""통합의 공급 요청과 실행 완료 이벤트를 검사한다. 장치/LLM 호출 없음."""
from queue import Queue
from types import SimpleNamespace

import pytest

from app import mvp_integration
from app.hmi_contracts import SUPPLY_COLUMNS


@pytest.mark.parametrize('column', sorted(SUPPLY_COLUMNS))
def test_every_block_column_wraps_six_to_one_independently(monkeypatch, column):
    runtime = mvp_integration.MvpIntegration.__new__(mvp_integration.MvpIntegration)
    runtime.inbox = Queue()
    runtime.robot = SimpleNamespace(events=Queue())
    runtime.scene, runtime.slot_indices = [], {}
    runtime.consumed_executions, runtime.scene_executions = set(), set()
    runtime.auto_gestures = False
    runtime.robot_sample, runtime.ready_signal = None, None
    block = dict(brick_type=column[0], color=column[1], x=6, y=6, layer=1, orientation_deg=0)
    prepared, received = [], []
    runtime.workflow = SimpleNamespace(status='RUNNING', reason=None,
        supply=[dict(brick_type=k, color=c, next_slot=1, needs_refill=False) for k,c in SUPPLY_COLUMNS],
        step=lambda:dict(after=block), prepared_step=prepared.append, robot_event=received.append)
    monkeypatch.setattr(mvp_integration, 'prepare', lambda workflow,payload,**kwargs: kwargs['slot_index'])
    for slot in [1,2,3,4,5,6,1,2,3,4,5,6,1]:
        runtime.emit('d.prepare_step', dict(step=dict(after=block)))
        assert prepared[-1] == slot
        runtime.workflow.execution_id = f'execution-{len(prepared)}'
        runtime.workflow.reason = None
        runtime.workflow.step_inputs = dict(slot=dict(brick_type=column[0], color=column[1], slot_index=slot))
        data = dict(execution_id=runtime.workflow.execution_id)
        runtime.robot.events.put(dict(event='GRIP_SUCCEEDED', data=dict(data,label='PICKUP_CLOSE')))
        runtime.robot.events.put(dict(event='INSPECTION_REQUIRED', data=data))
        runtime.poll()
        assert runtime.workflow.status == 'RUNNING'
        row = next(r for r in runtime.workflow.supply if (r['brick_type'],r['color']) == column)
        assert row['next_slot'] == (1 if slot == 6 else slot+1)
        assert row['needs_refill'] is False
        assert all(r['next_slot']==1 for r in runtime.workflow.supply if (r['brick_type'],r['color'])!=column)
    assert len(received)==26
    # 수동/자동 재검사 및 중복 집기 완료는 같은 블록을 다시 소비하지 않는다.
    runtime.robot.events.put(dict(event='INSPECTION_REQUIRED', data=dict(data,automatic_reinspection=False)))
    runtime.robot.events.put(dict(event='INSPECTION_REQUIRED', data=dict(data,automatic_reinspection=True)))
    runtime.robot.events.put(dict(event='GRIP_SUCCEEDED', data=dict(data,label='PICKUP_CLOSE')))
    runtime.poll()
    assert runtime.slot_indices[column] == 2


def test_real_plan_preflight_does_not_limit_plan_to_remaining_supply_slots():
    from app.real_design_controller import RealDesignController
    controller=RealDesignController.__new__(RealDesignController)
    controller._operation=controller._stop=controller._fault=None
    controller._ready=True
    controller.slots={column:6 for column in SUPPLY_COLUMNS}
    controller.plan_columns=[('2x2x1','yellow')]
    controller._attempts=1
    controller._read_config=lambda:None  # 장치 설정과 파일은 이 단위 검사의 외부 경계다.
    columns=list(sorted(SUPPLY_COLUMNS))*8
    controller.prepare_design_plan(dict(steps=[dict(after=dict(brick_type=k,color=c)) for k,c in columns]))
    assert controller.plan_columns==[('2x2x1','yellow')]+columns
    assert controller._limit==41 and controller._attempts==1
    assert all(slot==6 for slot in controller.slots.values())  # 재계획만으로 슬롯을 소비/초기화하지 않는다.


def test_design_count_limit_remains_forty_in_c_and_a():
    from app.c_design import validator
    from planning_trial.planner import validate_design
    # 위층을 한 stud씩 엇갈려 놓되 층마다 양 끝을 한 칸씩 안으로 들여 모든 위층 블록이 아래 두 블록에 2+2=4 stud로
    # 얹히게 한 41개 입력(2026-10-13 C support 규칙 min(4, stud 수); 이전의 끝단 블록은 2 stud뿐이라 새 규칙에서 무효).
    # 피라미드 11+10+9+8+7 = 45개에서 앞 41개를 쓴다. 테스트 목적(40개 통과·41개 거부)은 그대로다.
    blocks=[dict(brick_type='2x2x1',color='yellow',x=2*i+(layer-1),y=0,layer=layer,
        orientation_deg=0) for layer,count in [(1,11),(2,10),(3,9),(4,8),(5,7)] for i in range(count)][:41]
    design=dict(design_version=1,blocks=blocks[:40])
    assert validator.validate_design(design)==[]
    assert len(validate_design(design))==40
    design['blocks']=blocks
    assert any(r['rule']=='brick_count' for r in validator.validate_design(design))
    with pytest.raises(ValueError,match='1..40 placements; got 41'):
        validate_design(design)
