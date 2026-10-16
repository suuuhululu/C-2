"""Record renderer reference time and raw Depth; never admit dynamic input.

Replicator Writer's synchronized payload is used instead of labeling the latest
Depth with the caller's current physics time. This is a diagnostic SIM hook.
"""
from collections import deque
import hashlib
import json
from pathlib import Path

import numpy as np


def install_probe(sensor, output):
    import omni.replicator.core as rep
    output=Path(output);output.mkdir(exist_ok=False)
    source=Path(__file__)
    (output/'executed_source.py').write_bytes(source.read_bytes())
    pending=deque();states=[];rows=[]

    class ReferenceWriter(rep.Writer):
        def __init__(self):
            self.version='0.1.0'
            self.annotators=['distance_to_image_plane','semantic_segmentation','camera_params','ReferenceTime']
            self.last_time=None

        def write(self,data):
            reference=data['reference_time']
            if len(reference)!=2 or reference[1]<=0:
                raise ValueError('Renderer reference rational time unavailable')
            stamp=reference[0]/reference[1]
            if self.last_time is not None and stamp-self.last_time<.1:return
            depth=data['distance_to_image_plane']
            if not isinstance(depth,np.ndarray) or not depth.size:return
            self.last_time=stamp
            pending.append(dict(reference_time=list(reference),source_time_s=stamp,
                data_keys=list(data),camera_params=data['camera_params'],
                reference_annotator=data['ReferenceTime'],
                depth=depth.copy(),semantic=data['semantic_segmentation']))

        def write_metadata(self):
            # Source and numeric evidence are pinned by this producer directly.
            pass

    writer=ReferenceWriter();writer.attach(str(sensor.render_product.GetPath()))
    trace=(output/'source_time.jsonl').open('x')

    def collect(state):
        states.append(state)
        while pending:
            row=pending.popleft();depth=row.pop('depth');semantic=row.pop('semantic')
            row['depth_shape']=list(depth.shape)
            row['depth_sha256']=hashlib.sha256(depth.tobytes()).hexdigest()
            # Raw arrays of the first 16 synchronized payloads are retained.
            # All later records retain time/camera/state diagnostics only.
            if len(rows)<16:
                stem=f'frame_{len(rows):03d}'
                np.save(output/(stem+'.depth.npy'),depth,allow_pickle=False)
                np.save(output/(stem+'.semantic_ids.npy'),semantic['data'],allow_pickle=False)
                (output/(stem+'.semantic_info.json')).write_text(json.dumps(semantic['info'],default=_json)+'\n')
                row['raw_frame_stem']=stem
            row['state_at_readout']=state
            rows.append(row)
            trace.write(json.dumps(row,default=_json)+'\n');trace.flush()

    def close():
        writer.detach();trace.close()
        (output/'states.json').write_text(json.dumps(states,default=_json)+'\n')
        matches=[]
        times=np.array([s['sim_time_s'] for s in states])
        for row in rows:
            if not len(times):continue
            index=int(np.argmin(abs(times-row['source_time_s'])))
            state=states[index]
            matches.append(dict(source_time_s=row['source_time_s'],
                nearest_timeline_time_s=state['timeline_time_s'],
                nearest_sim_time_s=state['sim_time_s'],
                source_state_skew_s=float(abs(times[index]-row['source_time_s'])),
                readout_minus_source_s=row['state_at_readout']['sim_time_s']-row['source_time_s'],
                q_rad=state['q_rad'],T_world_camera=state['T_world_camera'],
                camera_params=row['camera_params']))
        (output/'clock_match.json').write_text(json.dumps(dict(
            scope='RENDER_REFERENCE_TIME_PROBE_NOT_DYNAMIC_ADMISSION',
            execution_allowed=False,hardware_execution_allowed=False,
            capture_source_sha256=hashlib.sha256((output/'executed_source.py').read_bytes()).hexdigest(),
            synchronized_frame_count=len(rows),state_count=len(states),matches=matches),default=_json,indent=2)+'\n')
    return collect,close


def _json(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    raise TypeError('Unsupported raw renderer metadata: '+type(value).__name__)
