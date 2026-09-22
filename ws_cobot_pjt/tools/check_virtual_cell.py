"""가상 환경의 HTTP→실제 ROS Action 왕복 확인. REAL 서버에는 요청하지 않는다."""
import argparse
import io
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8020')
    parser.add_argument('--image',type=Path)
    parser.add_argument('--expect',choices=['SUCCEEDED','FAILED','STOPPED'],default='SUCCEEDED')
    parser.add_argument('--stop-after',type=float)
    args=parser.parse_args();base=args.url.rstrip('/')
    def call(path,body=None,content_type='application/json'):
        raw=json.dumps(body).encode() if isinstance(body,dict) else body
        req=Request(base+'/api/operator/'+path,data=raw,headers={'x-c2-monitor':'1','Content-Type':content_type,'Origin':base})
        with urlopen(req,timeout=10) as response:return json.load(response)
    def wait(path,ready,timeout=100):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=call(path)
            if ready(value):return value
            time.sleep(.2)
        raise RuntimeError('시간 초과: '+path)
    snapshot=wait('snapshot',lambda s:s['connection']=='CONNECTED' and s['path_generation']['ready'])
    if (snapshot['source_mode']!='SIMULATION' or snapshot['transport']!='ROS2'
            or '가상 장치' not in snapshot['contract_status']):
        raise SystemExit('이 검사는 가상 장치 실행기에만 요청합니다.')
    cfg=snapshot['preparation']['input_config']
    rid=str(uuid4())
    call('preparations',dict(request_id=rid,input_profile_snapshot_id=cfg['id'],input_profile_sha256=cfg['sha256'],height_m=cfg['payload']['workcell']['height_m']))
    prep=wait('preparations/'+rid,lambda p:p['state'] not in ('ACCEPTED','RUNNING','CANCELING'))
    print('준비:',prep['state'],prep.get('binding_status'),prep.get('message',''),flush=True)
    if prep['state']!='SUCCEEDED':raise SystemExit(json.dumps(prep,ensure_ascii=False))
    snapshot=wait('snapshot',lambda s:s['preparation']['ready'] and not s['preparation']['blocks_work'])
    if args.image:raw=args.image.read_bytes();filename=args.image.name
    else:
        from PIL import Image,ImageDraw
        image=Image.new('RGB',(100,100),'white');ImageDraw.Draw(image).line((20,50,80,50),fill='black',width=3)
        output=io.BytesIO();image.save(output,format='PNG');raw=output.getvalue();filename='virtual-line.png'
    boundary='c2'+uuid4().hex
    mime='image/jpeg' if filename.lower().endswith(('.jpg','.jpeg')) else 'image/png'
    payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="input.png"\r\nContent-Type: {mime}\r\n\r\n'.encode()+raw+f'\r\n--{boundary}--\r\n'.encode())
    asset=call('assets',payload,'multipart/form-data; boundary='+boundary)
    profile=snapshot['profile'];rid=str(uuid4())
    call('path-generations',dict(schema_version=2,request_id=rid,source_mode='SIMULATION',asset_id=asset['asset_id'],asset_sha256=asset['asset_sha256'],
         profile_snapshot_id=profile['id'],profile_sha256=profile['sha256'],tool_id='engraving_drill',conversion_preset='raster_centerline_bezier',
         **snapshot['path_generation']['default_placement']))
    generation=wait('path-generations/'+rid,lambda g:g['state'] in ('SUCCEEDED','FAILED','UNKNOWN'))
    print('경로:',generation['state'],generation['result'].get('message',''),flush=True)
    if generation['state']!='SUCCEEDED':raise SystemExit(json.dumps(generation,ensure_ascii=False))
    result=generation['result']
    path=call(f"paths/{result['path_id']}/versions/{result['path_version']}")
    assert path['profile_sha256']==profile['sha256']
    response=call('runs',dict(schema_version=2,request_id=str(uuid4()),source_mode='SIMULATION',path_id=result['path_id'],path_version=result['path_version'],path_sha256=result['path_sha256'],operator_confirmed_fixture=True))
    run_id=response['run_id']
    if args.stop_after is not None:
        time.sleep(args.stop_after)
        call('runs/'+run_id+'/stop',dict(schema_version=2,request_id=str(uuid4()),reason='가상 장치 정지 시험'))
    run=wait('runs/'+run_id,lambda r:r['status'] in ('SUCCEEDED','FAILED','STOPPED','UNKNOWN'),timeout=180)
    print(json.dumps(dict(source='VIRTUAL_DEVICE',outcome=run['status'],error_code=run['error_code'],message=run['message'],
        path_id=result['path_id'],path_sha256=result['path_sha256'],preparation_id=prep['goal']['preparation_id']),ensure_ascii=False,indent=2))
    if run['status']!=args.expect:raise SystemExit(1)

if __name__=='__main__':main()
