"""D callback boundary checks; no synthetic producer is shipped as runtime."""
from threading import Event

import pytest

from perception_mvp.team_connection import connect


class Bridge:
    def __init__(self):
        self.results = []
    def bind(self, handler):
        self.handler = handler
    def submit_observation(self, value):
        self.results.append(("observation", value))
    def submit_place(self, value):
        self.results.append(("place", value))
    def submit_failure(self, check, reason):
        self.results.append(("failure", check, reason))


def outputs(request):
    check = request["check_id"]
    values = {}
    if request["purpose"] != "PLACE":
        values["observation"] = dict(check_id=check, observation_seq=0,
            status="UNOBSERVABLE", visible_blocks=[], verified_regions=[], reason="depth_missing")
    if request["purpose"] != "CURRENT":
        values["place"] = dict(check_id=check, observation_seq=0, status="EMPTY", reason=None)
    return values


@pytest.mark.parametrize("purpose,channels", [("PLACE", ["place"]),
    ("CURRENT", ["observation"]), ("ASSEMBLY", ["observation", "place"])])
def test_purpose_routing_and_duplicate(purpose, channels):
    bridge, calls = Bridge(), []
    def process(request, active):
        assert active()
        calls.append(request)
        return outputs(request)
    connection = connect(bridge, process_request=process)
    request = dict(check_id="check", purpose=purpose, after=None)
    if purpose == "ASSEMBLY":
        request["after"] = dict(brick_type="2x2x1",color="yellow",x=0,y=0,layer=1,orientation_deg=0)
    try:
        bridge.handler(request)
        bridge.handler(request)
        connection._queue.join()
        assert len(calls) == 1
        assert [v[0] for v in bridge.results] == channels
    finally:
        connection.close()


def test_failure_never_returns_empty_and_wrong_check_rejected():
    for process in (lambda r, a: (_ for _ in ()).throw(RuntimeError("camera failed")),
                    lambda r, a: {"place": dict(check_id="wrong",observation_seq=0,status="EMPTY",reason=None)}):
        bridge = Bridge()
        connection = connect(bridge, process_request=process)
        try:
            bridge.handler(dict(check_id="check",after=None,purpose="PLACE"))
            connection._queue.join()
            assert len(bridge.results) == 1 and bridge.results[0][0] == "failure"
        finally:
            connection.close()


def test_old_worker_result_ignored_after_new_request():
    bridge, started, release = Bridge(), Event(), Event()
    def process(request, active):
        if request["check_id"] == "old":
            started.set()
            assert release.wait(2.)
            assert not active()
        return outputs(request)
    connection = connect(bridge, process_request=process)
    try:
        bridge.handler(dict(check_id="old",after=None,purpose="PLACE"))
        assert started.wait(2.)
        bridge.handler(dict(check_id="new",after=None,purpose="CURRENT"))
        release.set()
        connection._queue.join()
        assert len(bridge.results) == 1 and bridge.results[0][1]["check_id"] == "new"
    finally:
        release.set()
        connection.close()


def test_cancel_and_close_block_callbacks():
    bridge, started, release = Bridge(), Event(), Event()
    def process(request, active):
        started.set()
        assert release.wait(2.)
        return outputs(request)
    connection = connect(bridge, process_request=process)
    try:
        bridge.handler(dict(check_id="check",after=None,purpose="PLACE"))
        assert started.wait(2.)
        connection.cancel("check")
        release.set()
        connection._queue.join()
        assert not bridge.results
    finally:
        release.set()
        connection.close()


def test_missing_runtime_does_not_bind(monkeypatch):
    monkeypatch.delenv("B_PERCEPTION_RUNTIME_MODULE", raising=False)
    bridge = Bridge()
    with pytest.raises(ValueError, match="actual capture/Controller"):
        connect(bridge)
    assert not hasattr(bridge, "handler")


def test_one_argument_connect_loads_runtime_and_queues_contract_callbacks(monkeypatch):
    import sys
    from types import ModuleType
    from PyQt5.QtCore import QCoreApplication, QObject, QThread, Qt, pyqtSignal
    app = QCoreApplication.instance() or QCoreApplication([])
    runtime = ModuleType("test_b_runtime")
    runtime.process_request = lambda request, active: outputs(request)
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
    monkeypatch.setenv("B_PERCEPTION_RUNTIME_MODULE", runtime.__name__)
    # Latest integration does not ship the old app.vision_connection. B checks
    # its explicit bridge contract here; this is not a D production wiring test.
    class QueuedBridge(QObject, Bridge):
        received = pyqtSignal(object)
        def __init__(self):
            QObject.__init__(self)
            Bridge.__init__(self)
            self.callback_threads = []
            self.received.connect(self._receive, Qt.QueuedConnection)
        def submit_observation(self, value):
            self.received.emit(("observation", value))
        def _receive(self, result):
            self.results.append(result)
            self.callback_threads.append(QThread.currentThread())
    bridge = QueuedBridge()
    connection = connect(bridge)
    try:
        assert callable(bridge.handler)
        bridge.handler(dict(check_id="current-check", after=None, purpose="CURRENT"))
        connection._queue.join()
        assert not bridge.results  # Worker must enqueue, not mutate D state.
        app.processEvents()
        assert len(bridge.results) == 1
        assert bridge.results[0][0] == "observation"
        assert bridge.results[0][1]["check_id"] == "current-check"
        assert bridge.callback_threads == [bridge.thread()]
    finally:
        connection.close()
