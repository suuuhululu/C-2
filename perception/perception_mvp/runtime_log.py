"""Immediate, single-line terminal progress; never changes inspection DTOs."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from threading import Event, Lock, Thread, local
import time

_current = local()


def progress(context, message, *, view=None, **details):
    state = getattr(_current, 'state', None)
    if state is not None:
        with state['lock']:
            state.update(message=message, view=view, stage_started=time.monotonic())
    value = dict(check_id=context.get('check_id'), check_kind=context.get('check_kind'),
                 view=view, **details)
    print(f"{datetime.now(timezone.utc).isoformat()} [B] {message} "
          + json.dumps(value, ensure_ascii=False, default=str), flush=True)


@contextmanager
def periodic_progress(context, is_active, *, interval=2.):
    """Heartbeat during the B worker's blocking capture/inference, not more inference."""
    started = time.monotonic()
    state = dict(lock=Lock(), message='관측 시작 대기', view=None, stage_started=started)
    stopped = Event()
    previous = getattr(_current, 'state', None)
    _current.state = state
    def report():
        while not stopped.wait(interval):
            if not is_active():
                return
            with state['lock']:
                stage, view, since = state['message'], state['view'], state['stage_started']
            now = time.monotonic()
            progress(context, '진행 중', view=view, stage=stage,
                     elapsed_seconds=round(now-started, 1), stage_seconds=round(now-since, 1))
    thread = Thread(target=report, name='b-status-log', daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1.)
        _current.state = previous
