"""실제 HMI·경로·공정 노드 + 가상 장치만 localhost/domain 20에서 실행."""
import argparse
import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8020)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'backend/monitor_data/virtual_cell')
    parser.add_argument('--scenario',choices=['normal','ik_failure','motion_failure'],default='normal')
    parser.add_argument('--move-time',type=float,default=.06)
    args=parser.parse_args()
    if not 1024<=args.port<=65535 or not 0<=args.move_time<=10:parser.error('port/move-time 범위 오류')
    domain_lock=open(f'/tmp/c2-virtual-domain-20-{os.getuid()}.lock','a')
    try:fcntl.flock(domain_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:parser.error('가상 domain 20 실행기가 이미 실행 중입니다. 먼저 종료하세요.')
    data=args.data_dir.resolve();data.mkdir(parents=True,exist_ok=True)
    if not (ROOT/'frontend/dist/index.html').exists():parser.error('frontend에서 npm run build를 먼저 실행하세요.')
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:sock.bind(('127.0.0.1',args.port))
        except OSError:parser.error('선택한 HTTP 포트가 사용 중입니다.')
    # 임의 환경의 REAL 설정을 상속하지 않고, 모션 API/외부 드라이버를 시작하지 않는다.
    env=os.environ.copy()
    for name in ('C2_PREPARATION_CONFIG','C2_EXECUTION_PROFILE','CYCLONEDDS_URI',
                 'FASTRTPS_DEFAULT_PROFILES_FILE','FASTDDS_DEFAULT_PROFILES_FILE','ROS_DISCOVERY_SERVER'):
        env.pop(name,None)
    env.update(C2_VIRTUAL_CELL='1',C2_VIRTUAL_ORIGIN=f'http://127.0.0.1:{args.port}',C2_MONITOR_MODE='SIMULATION',C2_MONITOR_TRANSPORT='ros',
               C2_ROS_EXECUTION_SIM='1',C2_ROS_PREPARATION_SIM='1',C2_IMAGE_WORKFLOW='1',
               C2_MONITOR_DATA=str(data),ROS_DOMAIN_ID='20',ROS_LOCALHOST_ONLY='1',
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',ROS_STATIC_PEERS='',RMW_IMPLEMENTATION='rmw_fastrtps_cpp',
               ROS_LOG_DIR=str(data/'ros_logs'),PYTHONUNBUFFERED='1')
    env['PYTHONPATH']=os.pathsep.join([str(ROOT/'backend'),str(ROOT/'ws_cobot1/src/c2_path'),
        str(ROOT/'ws_cobot1/src/c2_process'),env.get('PYTHONPATH','')])
    subprocess.run([sys.executable,'-c','import rclpy, uvicorn; from c2_interfaces.action import PrepareWorkpiece, GeneratePath, ExecuteProcess; from c2_process.virtual_cell import simulation_settings; from c2_path.pipeline import GeneratePipeline'],env=env,check=True)
    commands={
        'hmi':[sys.executable,'-m','uvicorn','app.monitor:app','--host','127.0.0.1','--port',str(args.port)],
        'path':[sys.executable,'-m','c2_path.node','--ros-args','-p',f'managed_data_dir:={data}'],
        'process':[sys.executable,'-m','c2_process.virtual_cell','--backend-url',f'http://127.0.0.1:{args.port}',
            '--data-dir',str(data/'device'),'--scenario',args.scenario,'--move-time',str(args.move_time)]}
    children=[];files=[];stopping=False
    def shutdown(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,shutdown);signal.signal(signal.SIGTERM,shutdown)
    print(f'가상 장치 / 실제 로봇 미연결 / ROS domain 20\nHMI http://127.0.0.1:{args.port}/operator\n로그 {data}\n종료 Ctrl+C',flush=True)
    try:
        for name,command in commands.items():
            f=(data/f'{name}.log').open('a');files.append(f)
            children.append((name,subprocess.Popen(command,env=env,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)))
        while not stopping:
            for name,child in children:
                if child.poll() is not None:
                    raise RuntimeError(f'{name} 종료 코드 {child.returncode}. {data/name}.log 확인')
            time.sleep(.2)
    finally:
        for _,child in reversed(children):
            if child.poll() is None:os.killpg(child.pid,signal.SIGINT)
        for _,child in children:
            try:child.wait(timeout=8)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        for f in files:f.close()

if __name__=='__main__':main()
