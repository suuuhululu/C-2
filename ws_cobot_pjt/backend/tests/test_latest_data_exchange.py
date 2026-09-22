"""최신 경로→HMI 자산→공정 로더 데이터 시험. 모션 호출 없음."""
import json
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ws_cobot1/src/c2_path'),str(ROOT/'ws_cobot1/src/c2_process')]
from c2_path.pipeline import GeneratePipeline, matching_test_profile_v4, validate_profile
from c2_path.artifacts import ManagedArtifactStore
from c2_process.node import make_asset_bundle_loader, make_hmi_asset_resolver, resolve_real_execution_settings
from c2_process.robot_adapter import MockRobotAdapter
from app.monitor import create_app
from app.ros_preparation import display_result, real_bound_profile
from app.monitor_contract import uid
from app.artifact_loader import PathArtifactLoader
from test_path_artifacts import line_png, goal_for


def test_latest_real_data_hmi_to_path_to_process(tmp_path, monkeypatch):
    monkeypatch.setenv('C2_MONITOR_MODE','SIMULATION')
    monkeypatch.setenv('C2_MONITOR_TRANSPORT','mock')
    with TestClient(create_app(tmp_path)) as client:
        store=client.app.state.store
        config=json.loads((ROOT/'ws_cobot1/src/c2_process/config/workpiece_real_trial_0921.json').read_text())
        template=matching_test_profile_v4()
        template['tip_calibration']['offset_tool_m']=config['workcell']['tool_offset_m']
        template['execution_context']['stop_profile']['confirmation_timeout_s']=2.
        config['execution_profile']=template
        cfg=store.put_json(config,'preparation_config','fixture.json')
        goal=dict(preparation_id=uid(),measurement_id=uid(),source_mode='REAL',height_m=.15,
                  input_profile_snapshot_id=cfg['id'],input_profile_sha256=cfg['sha256'])
        raw=json.loads((ROOT/'ws_cobot1/src/c2_process/test/fixtures/prepare_workpiece_action_samples/success.json').read_text())['result']
        raw.update(source_mode='REAL',validity='ESTIMATED',preparation_id=goal['preparation_id'],measurement_id=goal['measurement_id'])
        raw['absolute_top_verified']=False
        record=store.put_json(dict(contract='prepare-workpiece-result/1',result=raw),'measurement_record','fixture.json')
        value=real_bound_profile(goal,display_result(raw,goal),config,record)
        validate_profile(value)
        profile=store.profile(value)
        asset=store.put_asset(line_png(),'image','image/png','line.png')
        request=dict(goal_for(asset,profile),source_mode='REAL',offset_v_mm=75.)
        generated=GeneratePipeline(ManagedArtifactStore(store.root),allow_real_execution=True).run(request)
        result=dict(asdict(generated),success=True,validation_passed=True,error_code='NONE',message='데이터 시험')
        metadata=PathArtifactLoader(store).load(request,result)
        store.create_generation(request)
        store.finish_generation(request['request_id'],'SUCCEEDED',result,metadata)
        execution=dict(schema_version=2,request_id=uid(),run_id=uid(),source_mode='REAL',path_id=result['path_id'],path_version=result['path_version'],path_sha256=result['path_sha256'])
        adapter=MockRobotAdapter()
        def fetch(url):
            response=client.get(urlsplit(url).path)
            assert response.status_code==200,response.text
            return response.content
        loader=make_asset_bundle_loader(make_hmi_asset_resolver('http://testserver',fetch_bytes=fetch),lambda snapshot,g,pid:resolve_real_execution_settings(snapshot,g,pid,adapter=adapter))
        loaded=loader(execution)
        assert loaded.path['path_id']==result['path_id']
        assert loaded.path['config']['profile_sha256']==profile['sha256']
        assert not adapter.calls
