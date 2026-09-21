import hashlib
import json
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parent))
from workpiece_test_node import TrialSession
from c2_process.workpiece_simulation import SimulatedWorkpieceAdapter


def config():
    raw=(Path(__file__).resolve().parents[1]/'config/workpiece_simulation.json').read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def test_service_session_calls_actual_measurement_function():
    c,h=config();events=[]
    session=TrialSession(c,'SIMULATION',lambda ctx:SimulatedWorkpieceAdapter(c['workcell'],clock=ctx.monotonic),lambda k,v:events.append((k,v)),h)
    accepted,message=session.start();assert accepted
    session.thread.join(2);assert not session.thread.is_alive()
    assert session.status()['status']=='SUCCEEDED'
    assert len(session.status()['result']['observed_state']['measurement']['points'])==8
    assert events[-1][0]=='result'


def test_duplicate_busy_and_cancel_before_measurement():
    c,h=config();entered=threading.Event();release=threading.Event()
    def factory(ctx):
        entered.set();release.wait(2)
        return SimulatedWorkpieceAdapter(c['workcell'],clock=ctx.monotonic)
    session=TrialSession(c,'SIMULATION',factory,lambda *args:None,h)
    assert session.start()[0];assert entered.wait(1)
    assert session.start()[0] is False
    assert session.cancel()[0]
    release.set();session.thread.join(2)
    assert session.status()['status']=='STOPPED'


def test_factory_failure_latches_unknown_and_blocks_restart():
    c,h=config()
    def broken(ctx):raise ConnectionError('unavailable')
    session=TrialSession(c,'SIMULATION',broken,lambda *args:None,h)
    assert session.start()[0];session.thread.join(2)
    assert session.status()['status']=='UNKNOWN'
    assert session.start()[0] is False
