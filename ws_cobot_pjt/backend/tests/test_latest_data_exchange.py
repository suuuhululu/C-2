"""실제 생성 ROS Result → HMI → 경로 계약 회귀시험. 모션 호출 없음."""
import pytest
import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ws_cobot1/src/c2_path'),str(ROOT/'ws_cobot1/src/c2_process')]
from c2_path.pipeline import GeneratePipeline
from c2_path.artifacts import ManagedArtifactStore
from app.monitor import create_app
from app.ros_preparation import display_result, real_bound_profile
from app.monitor_contract import uid
from test_path_artifacts import line_png, goal_for


def test_actual_real_result_generates_real_path(tmp_path, monkeypatch):
    monkeypatch.setenv('C2_MONITOR_MODE','SIMULATION')
    monkeypatch.setenv('C2_MONITOR_TRANSPORT','mock')
    with TestClient(create_app(tmp_path)) as client:
        store=client.app.state.store
        config=json.loads((ROOT/'ws_cobot1/src/c2_process/config/workpiece_real_trial_0921.json').read_text())
        from test_real_preparation_hmi import execution_template
        template=execution_template(config)
        config['execution_profile']=template
        cfg=store.put_json(config,'preparation_config','fixture.json')
        goal=dict(preparation_id=uid(),measurement_id=uid(),source_mode='REAL',height_m=.15,
                  input_profile_snapshot_id=cfg['id'],input_profile_sha256=cfg['sha256'])
        raw=json.loads((ROOT/'ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())['result']
        raw.update(source_mode='REAL',validity='ESTIMATED',preparation_id=goal['preparation_id'],measurement_id=goal['measurement_id'])
        # 실제 생성된 ROS Result만 사용한다. Action에 없는 필드를 추가하지 않는다.
        action = pytest.importorskip('c2_interfaces.action')
        from rosidl_runtime_py.set_message import set_message_fields
        from app.ros_bridge import ros_wire_values, preparation_result_error
        message = action.PrepareWorkpiece.Result()
        set_message_fields(message, raw)
        raw = ros_wire_values(message)
        assert preparation_result_error(action.PrepareWorkpiece.Result) is None
        record=store.put_json(dict(contract='prepare-workpiece-result/1',result=raw),'measurement_record','fixture.json')
        value=real_bound_profile(goal,display_result(raw,goal),config,record)
        for key in ('absolute_top_verification_known', 'absolute_top_verified'):
            assert value[key] is raw[key]
            assert value['measurement_assumptions'][key] is raw[key]
        profile=store.profile(value)
        asset=store.put_asset(line_png(),'image','image/png','line.png')
        request=dict(goal_for(asset,profile),source_mode='REAL',offset_v_mm=75.)
        result = GeneratePipeline(ManagedArtifactStore(store.root),allow_real_execution=True).run(request)
        assert result.path_id and result.path_sha256
        # HMI 검사/경로 생성만 통과하고 실제 공정 설정 로더에서 거절되는 회귀를 막는다.
        from c2_process.node import resolve_real_execution_settings
        from c2_process.robot_adapter import MockRobotAdapter
        adapter = MockRobotAdapter()
        settings = resolve_real_execution_settings(value, {'run_id': uid(), 'source_mode': 'REAL'},
                                                   profile['id'], adapter=adapter)
        assert settings['context'].motion_profiles == value['execution_context']['motion_profiles']
        assert not adapter.calls
        assert settings['context'].joint_limits_deg[5] == [-170.0, 170.0]
        assert settings['context'].j6_margin_deg == 0.0
