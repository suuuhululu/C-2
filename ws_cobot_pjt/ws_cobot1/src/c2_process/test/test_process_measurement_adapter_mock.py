"""공유 잠금/실제 근거 연결만 검사. ROS·실물 연결 시험 아님."""
import sys,threading
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from c2_process.workpiece_calibration import MeasurementContext,MeasurementError
from c2_process.workpiece_process_adapter import ProcessMeasurementReadiness


def setup_readiness():
    lock=threading.Lock();cancel=threading.Event();ctx=MeasurementContext('m','p','REAL',motion_lock=lock,cancel=cancel)
    class IO:
        def metadata(self):return dict(robot_mode=1,robot_system=0,tcp_id='tcp',load_id='load')
    evidence={'measurement_id':'m'}
    for key in ('control_authority',):
        evidence[key]=dict(value=True,valid=True,observed_at_monotonic_s=10.,source='CONTROLLER_ACCESS_CONTROL' if key=='control_authority' else 'OPERATOR_CONFIRMATION')
    r=ProcessMeasurementReadiness(IO(),dict(tcp_id='tcp',load_id='load'),ctx,lock,cancel,lambda _:evidence,
        {k:1. for k in ('control_authority',)},clock=lambda:10.)
    return r,ctx,lock,evidence


def test_shared_lock_and_evidence_required():
    r,ctx,lock,e=setup_readiness()
    with pytest.raises(MeasurementError):r(ctx)
    with lock:
        assert r(ctx)['ownership_confirmed']
        e['control_authority']['source']='AUTO'
        with pytest.raises(MeasurementError):r(ctx)


def test_expired_authority_and_closed_adapter_rejected():
    r,ctx,lock,e=setup_readiness()
    with lock:
        e['control_authority']['observed_at_monotonic_s']=8.
        with pytest.raises(MeasurementError):r(ctx)
        e['control_authority']['observed_at_monotonic_s']=10.
        r.close()
        with pytest.raises(MeasurementError):r(ctx)
    assert not ctx.cancel.is_set()


def test_manual_checks_absent_and_never_fabricated():
    r,ctx,lock,e=setup_readiness()
    assert 'mount_fixed' not in e and 'drill_off_confirmed' not in e
    with lock:
        result=r(ctx)
    assert 'mount_fixed' not in result and 'drill_off_confirmed' not in result
    assert result['control_authority']



def _scene_inputs():
    import json
    from copy import deepcopy
    from c2_process.robot_adapter import apply_tool_offset
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'config/workpiece_real_trial_0921.json').read_text())
    workcell = deepcopy(config['workcell'])
    tcp = workcell['top']['approach_tcp_pose']
    tip = apply_tool_offset(tcp, workcell['tool_offset_m'])
    step = dict(kind='MOVE', target_pose=tip, profile='approach', label='top_approach')
    initial = dict(posx=[v * 1000 for v in tcp[:3]] + [0., 180., 0.])
    return [step], workcell, initial


def test_process_scene_check_uses_recorded_corridor_model():
    from c2_process.workpiece_process_adapter import check_process_scene
    steps, workcell, initial = _scene_inputs()
    report = check_process_scene(steps, workcell, initial)
    assert report['path_checked'] and report['probe_envelopes_checked']
    assert report['environment_record_id'] == workcell['trial_scene']['environment_record_id']


@pytest.mark.parametrize('defect', ['frame', 'record', 'nan', 'unit', 'label', 'quaternion'])
def test_process_scene_check_fails_closed_before_motion(defect):
    from c2_process.workpiece_process_adapter import check_process_scene
    steps, workcell, initial = _scene_inputs()
    if defect == 'frame':
        workcell['frame_id'] = 'base'
    elif defect == 'record':
        workcell['trial_scene']['environment_record_id'] = ''
    elif defect == 'nan':
        steps[0]['target_pose'][0] = float('nan')
    elif defect == 'unit':
        steps[0]['target_pose'][0] = 426.0
    elif defect == 'label':
        steps[0]['label'] = 'free_motion'
    else:
        steps[0]['target_pose'][3:] = [0., 0., 0., 0.]
    with pytest.raises(MeasurementError):
        check_process_scene(steps, workcell, initial)
