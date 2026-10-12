import json
import os
from pathlib import Path
import time

import pytest
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication

from app.mvp_integration import MvpIntegration
from app.qt_hmi import HmiWindow, fields
from history.records import read_source
from history.final_mvp import CONTRACT
from app.mvp_fake import execution_document
from jsonschema import Draft202012Validator, RefResolver

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / 'interfaces/schemas'
HMI_SCHEMA = json.loads((SCHEMA_ROOT / 'hmi.schema.json').read_text())
COMMON_SCHEMA = json.loads((SCHEMA_ROOT / 'day4.schema.json').read_text())
HMI_VALIDATOR = Draft202012Validator(HMI_SCHEMA, resolver=RefResolver.from_schema(HMI_SCHEMA,
    store={COMMON_SCHEMA['$id']: COMMON_SCHEMA, 'https://c-2.invalid/schemas/day4.schema.json': COMMON_SCHEMA}))

ROOT=Path(os.environ.get('C2_ROBOT_ROOT',''))
pytestmark=pytest.mark.skipif(not (ROOT/'scripts/robot_integration_runtime.py').is_file(),reason='C2_ROBOT_ROOT required')


def test_five_layers_a_b_c_robot_process_hmi_jsonl(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    app=QApplication.instance() or QApplication([])
    window=HmiWindow(screen_size=QSize(1920,1080))
    blocks=[dict(brick_type='2x2x1',color='blue',x=6,y=6,layer=i,orientation_deg=0) for i in range(1,6)]
    runtime=MvpIntegration(ROOT,tmp_path,fixture_design=dict(design_version=1,blocks=blocks))
    try:
        assert runtime.command('START')
        end=time.monotonic()+45
        while time.monotonic()<end:
            runtime.poll();snapshot=runtime.workflow.snapshot();HMI_VALIDATOR.validate(snapshot)
            window.render_snapshot(snapshot);app.processEvents()
            if runtime.workflow.candidate:runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
            if runtime.c_pending:runtime.answer('좋아 이걸로 하자')
            assert runtime.workflow.status!='HOLD',runtime.workflow.reason
            if runtime.workflow.status=='COMPLETE':break
            time.sleep(.03)
        assert runtime.workflow.status=='COMPLETE',runtime.workflow.reason
        assert runtime.workflow.current==runtime.b.inspection.current
        assert runtime.workflow.current['current_revision']==5
        assert runtime.workflow.bundle['plan']['base_current_revision']==0
        assert runtime.workflow.storage=='NOT_STARTED'
        assert window.completion_view.save_button.isVisibleTo(window)
        log=tmp_path/(runtime.workflow.job_id+'.jsonl')
        rows,pending=read_source(log,'fixture',contract=CONTRACT)
        assert pending is None
        assert sum(r['document']['event']=='CHECK_RESULT' for r in rows)==7
        assert sum(r['document']['event']=='ASSEMBLY_COMPLETED' for r in rows)==1
        assert fields(dict(blocks[0],brick_type='1x2x1',color='red'))[:2]==['2점 (1×2)','빨강']
        artifact=Path('logs/mvp-integration-verification');artifact.mkdir(parents=True,exist_ok=True)
        window.grab().save(str(artifact/'five-layer-final.png'))
        (artifact/'five-layer.jsonl').write_bytes(log.read_bytes())
        (artifact/'final-snapshot.json').write_text(json.dumps(runtime.workflow.snapshot(),ensure_ascii=False,indent=2))
    finally:runtime.close();window.close()


@pytest.mark.parametrize('kind,color,angle,manual', [('1x2x1','red',0,False),
    ('1x2x1','red',90,False), ('2x3x1','yellow',90,True)])
def test_rotated_red_or_human_tray_uses_a_candidate_and_real_b_functions(tmp_path,monkeypatch,kind,color,angle,manual):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    block=dict(brick_type=kind,color=color,x=6,y=6,layer=1,orientation_deg=angle)
    runtime=MvpIntegration(ROOT,tmp_path,fixture_design=dict(design_version=1,blocks=[block]))
    if manual:runtime.workflow.settings['assembly_context']['supported_modes']=['HUMAN_ASSEMBLY']
    try:
        assert runtime.command('START')
        end=time.monotonic()+25
        while time.monotonic()<end:
            runtime.poll();HMI_VALIDATOR.validate(runtime.workflow.snapshot())
            if runtime.workflow.candidate:runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
            if runtime.c_pending:runtime.answer('좋아 이걸로 하자')
            assert runtime.workflow.status!='HOLD',runtime.workflow.reason
            if runtime.workflow.status=='COMPLETE':break
            time.sleep(.02)
        assert runtime.workflow.status=='COMPLETE',runtime.workflow.reason
        assert runtime.workflow.current['blocks']==[block]
        lines=[json.loads(line) for line in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
        contact=any(row['event']=='ROBOT_CONTACT_SUCCEEDED' for row in lines)
        assert contact is (not manual)
        if manual:assert any(row['event']=='ROBOT_MOVE_SUCCEEDED' and row['result']['label']=='TRAY_LOWER' for row in lines)
    finally:runtime.close()


def test_empty_approach_mismatch_rejected_before_robot_execution(tmp_path,monkeypatch):
    monkeypatch.setenv('C_DESIGN_USE_LLM','0')
    block=dict(brick_type='2x2x1',color='blue',x=6,y=6,layer=1,orientation_deg=0)
    runtime=MvpIntegration(ROOT,tmp_path,fixture_design=dict(design_version=1,blocks=[block]))
    original=runtime.workflow.emit
    def mutate(port,payload):
        if port=='robot.EXECUTE':
            document=execution_document(payload['bundle'],payload['execution_id'])
            document['motion']['motion_proposal']['segments'][0]['waypoints'][2]['tcp_pose']['xyz_m'][0]+=.01
            runtime.robot.send('EXECUTE',document=document)
        else:original(port,payload)
    runtime.workflow.emit=mutate
    try:
        runtime.command('START');end=time.monotonic()+8
        while time.monotonic()<end:
            runtime.poll()
            if runtime.workflow.candidate:runtime.workflow.preview_ready(runtime.workflow.candidate['request_id'])
            if runtime.c_pending:runtime.answer('좋아 이걸로 하자')
            if runtime.workflow.status=='HOLD':break
            time.sleep(.02)
        assert runtime.workflow.status=='HOLD' and 'A_D_POSE_DIFFERS' in runtime.workflow.reason
        lines=[json.loads(line) for line in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
        assert not any(r['event']=='ROBOT_EXECUTION_STARTED' for r in lines)
        assert runtime.workflow.current['blocks']==[]
    finally:runtime.close()
