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
    for key in ('control_authority','mount_fixed','drill_off_confirmed'):
        evidence[key]=dict(value=True,valid=True,observed_at_monotonic_s=10.,source='CONTROLLER_ACCESS_CONTROL' if key=='control_authority' else 'OPERATOR_CONFIRMATION')
    r=ProcessMeasurementReadiness(IO(),dict(tcp_id='tcp',load_id='load'),ctx,lock,cancel,lambda _:evidence,
        {k:1. for k in ('control_authority','mount_fixed','drill_off_confirmed')},clock=lambda:10.)
    return r,ctx,lock,evidence


def test_shared_lock_and_evidence_required():
    r,ctx,lock,e=setup_readiness()
    with pytest.raises(MeasurementError):r(ctx)
    with lock:
        assert r(ctx)['ownership_confirmed']
        e['control_authority']['source']='AUTO'
        with pytest.raises(MeasurementError):r(ctx)


def test_expired_operator_confirmation_and_closed_adapter_rejected():
    r,ctx,lock,e=setup_readiness()
    with lock:
        e['drill_off_confirmed']['observed_at_monotonic_s']=8.
        with pytest.raises(MeasurementError):r(ctx)
        e['drill_off_confirmed']['observed_at_monotonic_s']=10.
        r.close()
        with pytest.raises(MeasurementError):r(ctx)
    assert not ctx.cancel.is_set()
