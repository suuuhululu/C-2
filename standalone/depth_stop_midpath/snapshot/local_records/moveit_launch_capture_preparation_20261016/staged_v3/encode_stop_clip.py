"""Offline encode of selected own viewport PNGs; never run in the SIM loop."""
from pathlib import Path
import argparse,hashlib,json,subprocess


def encode(folder,output):
    from PIL import Image
    folder=Path(folder).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('NEW_VIDEO_OUTPUT_REQUIRED')
    manifest=folder/'manifest.json';data=json.loads(manifest.read_text());trigger=data['trigger']
    if not trigger:raise ValueError('NO_CANCEL_EVENT_CLIP_AVAILABLE')
    frames=[];excluded=[]
    for row in data['frames']:
        p=Path(row['path']).resolve()
        if not p.is_relative_to(folder) or p.suffix!='.png':raise ValueError('OWN_VIEWPORT_PNG_ONLY')
        if not trigger['wall_s']-8<=row['request_wall_s']<=trigger['wall_s']+32:
            excluded.append(dict(path=str(p),reason='OUTSIDE_WALL_REQUEST_CLIP_WINDOW'));continue
        try:
            with Image.open(p) as image:image.verify()
        except (OSError,ValueError):excluded.append(dict(path=str(p),reason='IMAGE_NOT_COMPLETE'));continue
        frames.append(row)
    if len(frames)<2:raise ValueError('TWO_COMPLETED_VIEWPORT_FRAMES_REQUIRED')
    frames.sort(key=lambda x:x['request_wall_s']);intervals=[b['request_wall_s']-a['request_wall_s'] for a,b in zip(frames,frames[1:])]
    if any(t<=0 for t in intervals):raise ValueError('VIEWPORT_WALL_REQUEST_ORDER_REQUIRED')
    concat=folder/'encode.concat';lines=['ffconcat version 1.0']
    for row,duration in zip(frames,intervals+[data['limits']['interval_wall_s']]):
        path=str(Path(row['path']).resolve())
        if '\n' in path or '\r' in path:raise ValueError('LOCAL_FRAME_PATH_REQUIRED')
        lines.extend(["file '"+path.replace("'","'\\''")+"'",'duration '+str(duration)])
    lines.append("file '"+str(Path(frames[-1]['path']).resolve()).replace("'","'\\''")+"'")
    with concat.open('x') as f:f.write('\n'.join(lines)+'\n')
    command=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-n','-threads','2','-filter_threads','1','-f','concat','-safe','0','-protocol_whitelist','file,pipe','-i',str(concat),'-vf','scale=640:400:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=640:400:(ow-iw)/2:(oh-ih)/2,fps=10,format=yuv420p','-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','28','-movflags','+faststart',str(output)]
    subprocess.run(command,check=True,capture_output=True,text=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_name,width,height','-of','json',str(output)],text=True))
    result=dict(scope='OWN_VIEWPORT_VISUAL_CLIP_NOT_SENSOR_OR_STOP_TIMING_PROOF',manifest=dict(path=str(manifest),sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()),video=dict(path=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest()),frame_count=len(frames),excluded=excluded,probe=probe,playback='Viewport request wall-time intervals, sampled and asynchronous; not certified exposure or 1x SIM playback',trigger=trigger,control_success_claimed=False,SDK_executed_by_encoder=False)
    with output.with_suffix('.json').open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--clip-folder',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(encode(a.clip_folder,a.output),indent=2))
