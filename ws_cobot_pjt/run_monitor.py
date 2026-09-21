"""한 PC의 HMI 실행. --transport ros는 이미지 경로 노드만 연결하며 로봇은 구동하지 않는다."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport',choices=('mock','ros'),default=os.getenv('C2_MONITOR_TRANSPORT','mock'))
    parser.add_argument('--external-path-node',action='store_true',help='ROS 모드에서 이미 실행 중인 경로 노드 사용')
    parser.add_argument('--ros-domain-id',type=int,default=173,help='ROS 경로 시험용 도메인 (기본 173)')
    args=parser.parse_args()
    if args.transport not in ('mock','ros'):parser.error('transport는 mock 또는 ros여야 합니다.')
    if not 0 <= args.ros_domain_id <= 232:parser.error('ROS domain은 0~232 범위여야 합니다.')
    root=Path(__file__).resolve().parent
    python=root/'backend/.venv/bin/python'
    node=shutil.which('node')
    bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    if not node and bundled.is_file():node=str(bundled)
    vite=root/'frontend/node_modules/vite/bin/vite.js'
    if not node or not python.exists() or not vite.exists():
        raise SystemExit('backend/README.md · frontend/README.md의 의존성 설치를 먼저 완료하세요.')
    env=os.environ.copy();env['C2_MONITOR_MODE']='SIMULATION';env['C2_MONITOR_TRANSPORT']=args.transport
    default_data=root/'backend/monitor_data'
    if args.transport=='ros':
        default_data/='ros_path'
        env.update(ROS_DOMAIN_ID=str(args.ros_domain_id),ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
                   ROS_STATIC_PEERS='',RMW_IMPLEMENTATION='rmw_fastrtps_cpp')
    data=Path(env.get('C2_MONITOR_DATA',str(default_data))).expanduser().resolve()
    env['C2_MONITOR_DATA']=str(data)
    if args.transport=='ros':
        # 같은 Python·타입·변환 의존성 확인 뒤 경로 노드보다 먼저 저장소 초기화.
        preflight=('import os, rclpy; from c2_interfaces.action import GeneratePath; '
                   'from c2_path.pipeline import matching_test_profile; from app.storage import Storage; '
                   'assert GeneratePath.Goal.SCHEMA_VERSION == 2; Storage(os.environ["C2_MONITOR_DATA"])')
        subprocess.run([str(python),'-c',preflight],cwd=root/'backend',env=env,check=True)
    children=[]
    def stop(*args):
        for p in children:
            if p.poll() is None:p.terminate()
        for p in children:
            try:p.wait(timeout=6)
            except subprocess.TimeoutExpired:p.kill();p.wait()
    def interrupt(*args):stop();sys.exit(0)
    signal.signal(signal.SIGINT,interrupt);signal.signal(signal.SIGTERM,interrupt)
    try:
        if args.transport=='ros' and not args.external_path_node:
            children.append(subprocess.Popen([str(python),'-m','c2_path.node','--ros-args','-p',f'managed_data_dir:={data}'],env=env))
        children.append(subprocess.Popen([str(python),'-m','uvicorn','app.monitor:app','--host','127.0.0.1','--port','8010'],cwd=root/'backend',env=env))
        children.append(subprocess.Popen([node,str(vite),'--host','127.0.0.1'],cwd=root/'frontend',env=env))
        print('새김 HMI: http://127.0.0.1:5174/operator',flush=True)
        print(f'SIMULATION / {args.transport.upper()} · DB: {data / "monitor.sqlite3"} · 종료 Ctrl+C',flush=True)
        if args.transport=='ros':
            print(f'ROS domain {args.ros_domain_id} / LOCALHOST · 이미지 경로 시험 전용 · 공정 실행 차단',flush=True)
        while all(p.poll() is None for p in children):time.sleep(.3)
        raise SystemExit(next((p.returncode for p in children if p.returncode),1))
    finally:stop()


if __name__=='__main__':main()
