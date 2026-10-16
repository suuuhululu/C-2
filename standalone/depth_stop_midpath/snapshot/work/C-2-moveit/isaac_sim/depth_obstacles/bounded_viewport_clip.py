"""Bounded own-viewport visual ring; not sensor acquisition or control evidence."""
from pathlib import Path
from collections import deque
import json,time,asyncio


def capture_completion_task(handle):
    # Kit services its own asyncio loop. Never drive app/physics updates here.
    return asyncio.ensure_future(handle.wait_for_result())


class BoundedViewportClip:
    def __init__(self,folder,capture,*,wall_time=time.monotonic,completion_task=capture_completion_task):
        self.folder=Path(folder);self.folder.mkdir(exist_ok=False)
        self.capture=capture;self.wall_time=wall_time;self.completion_task=completion_task;self.pre=deque();self.post=[];self.pending=None
        self.trigger=None;self.last=-float('inf');self.counter=0;self.error=None;self.disabled_reason=None
        self.pre_limit=16;self.post_limit=64;self.interval_wall_s=.5;self.max_bytes=64*1024*1024
        self.journal=self.folder/'requests.jsonl';self._record()

    def _record(self):
        value=dict(schema='bounded-viewport-event-clip/1',scope='ASYNCHRONOUS_OWN_VIEWPORT_VISUAL_REQUESTS_NOT_SENSOR_OR_CONTROL_TIMING',trigger=self.trigger,frames=list(self.pre)+self.post,pending=self.pending[0] if self.pending else None,limits=dict(pre_frames=self.pre_limit,post_frames=self.post_limit,interval_wall_s=self.interval_wall_s,max_retained_bytes=self.max_bytes),pending_completion_task_done=bool(self.pending and self.pending[2] and self.pending[2].done()),limit_scope='Completed selected PNGs; at most one in-flight PNG remains separately pending and unaccounted until verified',disabled_reason=self.disabled_reason,error=self.error,source_clock_rewritten=False,actual_STOP_verified_by_video=False)
        try:(self.folder/'manifest.json').write_text(json.dumps(value,indent=2)+'\n')
        except OSError as exc:self.error=type(exc).__name__;self.disabled_reason='VIDEO_RECORD_WRITE_FAILED'

    def _complete(self):
        if self.pending is None:return
        frame,handle,task=self.pending;path=Path(frame['path'])
        if task is None or not task.done():return
        if task.cancelled():
            if self.disabled_reason!='VIDEO_CAPTURE_CANCELLED':
                self.error='Capture completion task cancelled';self.disabled_reason='VIDEO_CAPTURE_CANCELLED';self._record()
            return
        if not task.result():raise ValueError('VIEWPORT_CAPTURE_NO_COMPLETED_AOV')
        if not path.is_file():return
        from PIL import Image
        before=path.stat()
        try:
            with Image.open(path) as image:image.verify()
        except (OSError,SyntaxError,ValueError):return
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):return
        self.pending=None;frame=dict(frame,completion_handle_done=True,PNG_verified=True,file_verified_wall_s=self.wall_time(),bytes=after.st_size)
        target=self.pre if self.trigger is None or frame['request_wall_s']<=self.trigger['wall_s'] else self.post
        target.append(frame)
        while len(self.pre)>self.pre_limit:Path(self.pre.popleft()['path']).unlink()
        if sum(x['bytes'] for x in [*self.pre,*self.post])>self.max_bytes:
            target.pop();path.unlink();self.disabled_reason='VIDEO_BYTE_BUDGET'
        if len(self.post)>=self.post_limit:self.disabled_reason='VIDEO_POST_FRAME_LIMIT'
        self._record()

    def event(self,kind,payload,stamp):
        if kind=='CANCEL_REQUEST' and self.trigger is None:
            self.trigger=dict(kind=kind,source_SIM_s=stamp,wall_s=self.wall_time())
            self._record()

    def sample(self,row):
        try:
            self._complete();now=self.wall_time()
            if self.disabled_reason or self.pending or now-self.last<self.interval_wall_s:return
            if self.trigger is not None and len(self.post)>=self.post_limit:return
            path=self.folder/f'viewport_{self.counter:06d}.png';self.counter+=1
            frame=dict(path=str(path.resolve()),request_wall_s=now,request_source_SIM_s=float(row['time_s']),scope='VIEWPORT_REQUEST_NOT_CAPTURE_TIMESTAMP')
            handle=self.capture(path);self.pending=(frame,handle,None)
            task=self.completion_task(handle);self.pending=(frame,handle,task);self.last=now
            with self.journal.open('a') as stream:stream.write(json.dumps(frame)+'\n')
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc);self.disabled_reason='OPTIONAL_VIDEO_FAILED';self._record()

    def close(self):
        try:self._complete()
        except Exception as exc:self.error=type(exc).__name__+': '+str(exc);self.disabled_reason='OPTIONAL_VIDEO_CLOSE_FAILED'
        self._record()
