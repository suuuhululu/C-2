"""준비 클라이언트 경계 시험. 장치·ROS 서버를 기동하지 않는다."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ros_bridge import RosBridge, ros_wire_values


def goal(operation='MEASURE'):
    return dict(schema_version=2, operation=operation, request_id=str(uuid4()), preparation_id=str(uuid4()),
                measurement_id=str(uuid4()), source_mode='SIMULATION', input_profile_snapshot_id=str(uuid4()),
                input_profile_sha256='a'*64, measurement_record_id='', measurement_record_sha256='',
                profile_snapshot_id='', profile_sha256='')


class Packet:
    def __init__(self, **values): self.__dict__.update(values)
    def get_fields_and_field_types(self): return dict.fromkeys(self.__dict__, 'test')


def test_raw_measurement_keeps_time_nanoseconds_and_nested_pose_arrays():
    packet=Packet(measured_at=Packet(sec=1, nanosec=123456789),
                  contact_received_at=[Packet(sec=0, nanosec=0)],
                  contact_tip_poses=[Packet(position=Packet(x=.1,y=.2,z=.3))])
    raw=ros_wire_values(packet)
    assert raw['measured_at']==dict(sec=1,nanosec=123456789)
    assert raw['contact_received_at']==[dict(sec=0,nanosec=0)]
    assert raw['contact_tip_poses'][0]['position']==dict(x=.1,y=.2,z=.3)
    with pytest.raises(ValueError): ros_wire_values(Packet(value=float('nan')))


def bridge_for(g, result):
    bridge=RosBridge(None)
    bridge.preparation_client=object()
    bridge.preparation_type=SimpleNamespace(Goal=lambda:Packet(**g))
    async def action(client, kind, values, feedback, **options):
        assert options==dict(wire_result=True)
        if feedback:
            await feedback(dict(g,stage='HOME_RECHECK'))
            await feedback(dict(g,measurement_id='wrong',stage='COMPLETE'))
        return deepcopy(result)
    bridge.action=action
    return bridge


def test_prepare_result_matches_identity_and_feedback_is_scoped():
    g=goal(); result={k:v for k,v in g.items() if k!='schema_version'}
    result.update(outcome='FAILED',error_code='NOT_READY')
    bridge=bridge_for(g,result); seen=[]
    async def feedback(value):seen.append(value)
    assert asyncio.run(bridge.prepare_raw(g,feedback))==result
    assert len(seen)==1 and seen[0]['stage']=='HOME_RECHECK'
    for key in ('request_id','input_profile_sha256','measurement_id'):
        bad={**result,key:'wrong'}
        with pytest.raises(ValueError): asyncio.run(bridge_for(g,bad).prepare_raw(g))


@pytest.mark.parametrize('field,value', [('snapshot_bound',False),('geometry_ready',False),
    ('stop_confirmed',False),('partial',True),('error_code','NOT_READY')])
def test_bind_ack_requires_all_completion_evidence(field,value):
    g=goal('BIND_SNAPSHOT')
    result={k:v for k,v in g.items() if k!='schema_version'}
    result.update(outcome='SUCCEEDED',error_code='NONE',snapshot_bound=True,geometry_ready=True,
                  stop_confirmed=True,partial=False)
    assert asyncio.run(bridge_for(g,result).prepare_raw(g))==result
    result[field]=value
    with pytest.raises(ValueError): asyncio.run(bridge_for(g,result).prepare_raw(g))


def test_preparation_cancellation_uses_action_not_stop_service():
    bridge=RosBridge(None)
    asyncio.run(bridge.cancel_preparation('pending-goal'))
    assert 'pending-goal' in bridge.generation_cancels


def test_prepare_client_missing_or_unagreed_fields_fail_closed():
    bridge=RosBridge(None);bridge.preparation_client=bridge.preparation_type=None
    with pytest.raises(ConnectionError): asyncio.run(bridge.prepare_raw(goal()))
    g=goal();bridge=bridge_for(g,{})
    with pytest.raises(ValueError): asyncio.run(bridge.prepare_raw({**g,'drill_on':True}))
