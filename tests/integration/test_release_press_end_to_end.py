"""Actual A example + explicit TEST teaching → real adapter → MOCK D service.

The REAL document is only inspected. A separately constructed TEST session is
sent to the MOCK child; these synthetic poses are not physical approval.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from uuid import uuid4

from app.mvp_fake import execution_document
from app.hmi_contracts import validate_hmi_snapshot
from app.mvp_integration import MvpIntegration
from app.mvp_real_trial import FullFeatureRealTrial, measured_document, prepare_measured
from app.mvp_workflow import MvpWorkflow
from app.release_press_connection import d_motion, validate_a_message
from perception.perception_mvp.team_connection import InspectionConnection

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'robot_control_integration'


def test_actual_A_file_profile_and_real_preparation_reach_mock_inspection(tmp_path, monkeypatch):
    examples = json.loads((ROOT / 'planning_trial/fixtures/round2_strategy.examples.json').read_text())['examples']
    messages = deepcopy(next(e['messages'] for e in examples if e['case_id'] == 'release_press'))
    original = deepcopy(messages)
    for message in messages.values():
        validate_a_message(message)
    action = messages['reassessment_result']['action_proposal']
    assert action['mode'] == 'ROBOT_GRIP' and action['assembly_strategy'] == 'RELEASE_PRESS'
    assert action['assistance_kind'] == 'NONE'
    assert messages['motion_result']['status'] == 'BLOCKED'
    assert messages['motion_result']['errors'][0]['code'] == 'UNSUPPORTED_METHOD'

    record = dict(block=deepcopy(action['block']),
        supply_slot=dict(color=action['block']['color'], brick_type=action['block']['brick_type'], slot_index=1),
        settings=dict(pickup_pose=[-300., 50., 50., 0., 180., 0.],
            reference_pose=[400., 80., 40., 0., 180., 0.],
            release_pose=[400., 80., 44.5, 0., 180., 0.],
            press_start_pose=[401., 81., 61., 1., 179., 1.],
            press_approach_pose=[401., 81., 80., 1., 179., 1.],
            pickup_width_mm=35., release_width_mm=62., press_width_mm=4.),
        profile_settings=dict(force_stop_n=45., max_press_travel_mm=12., target_only_motion=True,
                              round2_motion=dict(transfer_velocity=80., vertical_velocity=6.)),
        measurement_refs=dict(release_pose='SYNTHETIC_TEST_NOT_REAL', press_start_pose='SYNTHETIC_TEST_NOT_REAL'))
    profile_path = tmp_path / 'synthetic-profile.json'
    profile_path.write_text(json.dumps(dict(profile_id='SYNTHETIC_TEST_NOT_REAL', entries=[record])))

    # Replace only transport construction. Geometry, state conversion, workflow
    # field transfer, document creation and native execution remain actual code.
    def no_devices(self, robot_root, directory, **kwargs):
        self.received_settings = kwargs['runtime_settings']
    monkeypatch.setattr(MvpIntegration, '__init__', no_devices)
    runtime = FullFeatureRealTrial(NATIVE, tmp_path, release_press_profile=profile_path)
    ports = []
    workflow = MvpWorkflow(lambda port, value: ports.append((port, value)), runtime.received_settings, tmp_path)
    request = messages['reassessment_request']
    workflow.job_id = str(uuid4())
    workflow.epoch = request['context']['source_epoch']
    workflow.generation = request['context']['workflow_generation']
    workflow.current = deepcopy(request['latest_current'])
    workflow.approved = deepcopy(request['design'])
    workflow.whole_result = deepcopy(messages['whole_result'])
    workflow.bundle = deepcopy(messages['whole_result']['shared_planning_bundle'])
    # Keep B's request pending: there is no observed scene or camera in this proof.
    workflow.b = InspectionConnection(lambda value: None, lambda *args: None,
        runtime.received_settings['geometry_reference'], workflow.current)
    workflow.b.load_plan(workflow.bundle['design'], workflow.bundle['plan'], workflow.bundle['plan_base_current'],
                         geometry_reference=runtime.received_settings['geometry_reference'])
    sample = dict(tcp='GripperDA_v4', tool='ToolWeight0', posx=[400., -180., 200., 0., 180., 0.],
        velx=[0.]*6, query_duration_s=0., gripper_width_mm=62., gripper_status=0,
        robot_state=1, robot_mode=1, drl_state=3, motion_status=0)
    receipt = dict(samples=[deepcopy(sample) for _ in range(3)], captured_unix_s=time.time(), physical_commands=0)
    payload = dict(step=deepcopy(messages['motion_request']['selected_step']), current=deepcopy(workflow.current),
                   generation=workflow.generation)
    prepared = prepare_measured(workflow, runtime.inputs, payload, 1, receipt,
                                'SYNTHETIC_TEST_STATE', 'SYNTHETIC_TEST_OPERATOR_REVIEW')
    workflow.step_inputs = dict(deepcopy(prepared), assessment_request=deepcopy(request))
    outer = str(uuid4())
    workflow.active = dict(port='a.assess', request=dict(request_id=outer, input=deepcopy(request)),
                           generation=workflow.generation, current_revision=workflow.current['current_revision'])
    assert workflow.receive('a.assess', outer, messages['reassessment_result'])
    port, data = ports[-1]
    assert port == 'd.release_press' and not any(p == 'a.motion' for p, _ in ports)
    candidate = d_motion(data['input'], data['d_profile'])
    assert candidate['status'] == 'CANDIDATE' and candidate['execution_allowed'] is False
    assert workflow.receive(port, data['request_id'], candidate)
    assert ports[-1][0] == 'robot.EXECUTE'
    validate_hmi_snapshot(workflow.snapshot())
    bundle = dict(ports[-1][1]['bundle'], prepared=prepared)

    real = measured_document(bundle, workflow.execution_id, workflow.epoch)
    real_before = deepcopy(real)
    assert real['session']['backend'] == 'REAL' and real['session']['provenance'] == 'LIVE_D_RUNTIME'
    assert real['step']['action'] == action
    assert real['motion_source'] == 'D_PROFILE' and not real['physical_assembly_verified']
    mock = execution_document(bundle, 'MOCK_COMPONENT_' + str(uuid4()))
    mock['fixture_kind'] = 'SYNTHETIC_TEST_NOT_REAL_NO_DEVICE'
    assert mock['session']['backend'] == 'TEST' and mock['session']['provenance'] == 'SYNTHETIC'
    assert mock['session']['execution_id'] != real['session']['execution_id']
    before_current = deepcopy(workflow.current)

    child = subprocess.Popen([sys.executable, '-u', str(NATIVE / 'scripts/robot_integration_runtime.py'), '--mode', 'MOCK'],
        cwd=NATIVE, env=dict(os.environ, PYTHONPATH=str(NATIVE), PYTHONDONTWRITEBYTECODE='1'),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    events = []
    try:
        child.stdin.write(json.dumps(dict(command='EXECUTE', document=mock)) + '\n')
        child.stdin.flush()
        deadline = time.monotonic() + 20.
        buffer = ''
        done = False
        while time.monotonic() < deadline:
            if select.select([child.stdout], [], [], .1)[0]:
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk.decode()
                lines = buffer.split('\n')
                buffer = lines.pop()
                for line in lines:
                    event = json.loads(line)
                    events.append(event)
                    if event['event'] in ('INSPECTION_REQUIRED', 'COMMAND_REJECTED', 'EXECUTION_HELD'):
                        done = True
                if done:
                    break
        inspection = next((v for v in events if v['event'] == 'INSPECTION_REQUIRED'), None)
        assert inspection is not None, events[-5:]
        assert next(v['data'] for v in events if v['event'] == 'PROCESS_READY') == dict(mode='MOCK', device_connections=0)
        assert not any(v['event'] in ('COMMAND_REJECTED', 'EXECUTION_HELD', 'B_DECISION') for v in events)
        assert inspection['data']['robot_press_executed'] is True
        assert inspection['data']['assembly_completion'] is False and inspection['data']['current_update'] is False
        pressure = next(v['data'] for v in events if v['event'] == 'PRESS_SESSION')
        assert pressure['force_stop_n'] == 45. and pressure['max_travel_mm'] == 12.
        assert workflow.robot_event(dict(inspection, data=dict(inspection['data'], execution_id=workflow.execution_id)))
        assert workflow.current == before_current and not workflow.completed
        assert workflow.status == 'WAIT_ASSEMBLY' and workflow.assembly == 'PENDING'
        validate_hmi_snapshot(workflow.snapshot())
        assert real == real_before and messages == original
        (tmp_path / 'proof.json').write_text(json.dumps(dict(device_connections=0, physical_commands=0,
            real_document=real, mock_document=mock, original_a_motion=messages['motion_result'], events=events), indent=2))
        child.stdin.close()
        child.wait(timeout=10.)
        assert child.returncode == 0, child.stderr.read()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.)
