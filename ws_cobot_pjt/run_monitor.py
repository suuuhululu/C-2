"""한 PC의 HMI 실행. REAL 공정 연결이며 공정 노드/드라이버는 별도 기동한다."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def path_node_command(python, data, mode):
    command = [str(python), '-m', 'c2_path.node', '--ros-args', '-p', f'managed_data_dir:={data}',
               '-p', f'source_mode:={mode}']
    if mode == 'REAL':
        command += ['-p', 'allow_real_execution:=true']
    return command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport',choices=('mock','ros'),default=os.getenv('C2_MONITOR_TRANSPORT','mock'))
    parser.add_argument('--legacy-mock-image',action='store_true',help='과거 고정 그림 MOCK 호환 시험')
    parser.add_argument('--process-integration',action='store_true',help='ROS SIM 준비→경로→공정 Action 연결')
    parser.add_argument('--mode', choices=('SIMULATION','REAL'), default='SIMULATION')
    parser.add_argument('--preparation-config', help='REAL 준비용 prepare-workpiece-config/1 현장 원본 JSON')
    parser.add_argument('--execution-profile', help='REAL 경로·공정 실행 설정 JSON (배포 설정; 운영자 업로드 아님)')
    parser.add_argument('--external-path-node',action='store_true',help='ROS 모드에서 이미 실행 중인 경로 노드 사용')
    parser.add_argument('--ros-domain-id',type=int,default=173,help='ROS 경로 시험용 도메인 (기본 173)')
    args=parser.parse_args()
    if args.process_integration and (args.transport != 'ros' or args.mode != 'SIMULATION'):
        parser.error('--process-integration은 --transport ros --mode SIMULATION에서 사용합니다.')
    if args.transport not in ('mock','ros'):parser.error('transport는 mock 또는 ros여야 합니다.')
    if not 0 <= args.ros_domain_id <= 232:parser.error('ROS domain은 0~232 범위여야 합니다.')
    if args.mode == 'REAL' and (args.transport != 'ros' or not args.preparation_config):
        parser.error('REAL 준비는 --transport ros --preparation-config 현장설정.json이 필요합니다.')
    if args.preparation_config and not Path(args.preparation_config).expanduser().is_file():
        parser.error('준비 설정 파일을 찾을 수 없습니다.')
    root=Path(__file__).resolve().parent
    python=root/'backend/.venv/bin/python'
    node=shutil.which('node')
    bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    if not node and bundled.is_file():node=str(bundled)
    vite=root/'frontend/node_modules/vite/bin/vite.js'
    if not node or not python.exists() or not vite.exists():
        raise SystemExit('backend/README.md · frontend/README.md의 의존성 설치를 먼저 완료하세요.')
    env=os.environ.copy();env['C2_MONITOR_MODE']=args.mode;env['C2_MONITOR_TRANSPORT']=args.transport
    env['C2_IMAGE_WORKFLOW']='0' if args.legacy_mock_image else '1'
    env['C2_ROS_EXECUTION_SIM']='1' if args.process_integration else '0'
    if args.process_integration: env['C2_ROS_PREPARATION_SIM']='1'
    # ROS 설치 없이도 같은 원본 c2_path 계산 모듈을 사용한다.
    env['PYTHONPATH']=str(root/'ws_cobot1/src/c2_path')+os.pathsep+env.get('PYTHONPATH','')
    if args.preparation_config:
        env['C2_PREPARATION_CONFIG']=str(Path(args.preparation_config).expanduser().resolve())
    if args.execution_profile:
        env['C2_EXECUTION_PROFILE']=str(Path(args.execution_profile).expanduser().resolve())
    default_data=root/'backend/monitor_data'
    if args.transport=='ros':
        default_data/='real_preparation' if args.mode == 'REAL' else 'ros_path'
        env.update(ROS_DOMAIN_ID=str(args.ros_domain_id),ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
                   ROS_STATIC_PEERS='',RMW_IMPLEMENTATION='rmw_fastrtps_cpp')
    data=Path(env.get('C2_MONITOR_DATA',str(default_data))).expanduser().resolve()
    env['C2_MONITOR_DATA']=str(data)
    if args.transport=='ros':
        # 같은 Python·타입·변환 의존성 확인 뒤 경로 노드보다 먼저 저장소 초기화.
        preflight=('import os, rclpy; from c2_interfaces.action import GeneratePath; '
                   'from c2_path.pipeline import matching_test_profile; from app.storage import Storage; '
                   'assert GeneratePath.Goal.SCHEMA_VERSION == 2; Storage(os.environ["C2_MONITOR_DATA"])')
        if args.mode == 'REAL':
            preflight += ('; from c2_interfaces.action import PrepareWorkpiece; '
                          'from app.preparation import real_input_config; '
                          'from app.real_execution_config import validate_real_execution_config; '
                          'validate_real_execution_config(real_input_config(Storage(os.environ["C2_MONITOR_DATA"]), os.environ["C2_PREPARATION_CONFIG"])["payload"])')
        subprocess.run([str(python),'-c',preflight],cwd=root/'backend',env=env,check=True)
    if not args.legacy_mock_image and args.transport == 'mock':
        subprocess.run([str(python),'-c','from c2_path.pipeline import GeneratePipeline'],cwd=root/'backend',env=env,check=True)
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
            children.append(subprocess.Popen(path_node_command(python, data, args.mode),env=env))
        children.append(subprocess.Popen([str(python),'-m','uvicorn','app.monitor:app','--host','127.0.0.1','--port','8010'],cwd=root/'backend',env=env))
        children.append(subprocess.Popen([node,str(vite),'--host','127.0.0.1'],cwd=root/'frontend',env=env))
        print('새김 HMI: http://127.0.0.1:5174/operator',flush=True)
        print(f'{args.mode} / {args.transport.upper()} · DB: {data / "monitor.sqlite3"} · 종료 Ctrl+C',flush=True)
        if args.transport=='ros':
            print(f'ROS domain {args.ros_domain_id} / LOCALHOST · '+('SIM 공정 Action 연결' if args.process_integration else '경로/측정 시험')+' · 공정 노드는 별도 실행',flush=True)
        while all(p.poll() is None for p in children):time.sleep(.3)
        raise SystemExit(next((p.returncode for p in children if p.returncode),1))
    finally:stop()


if __name__=='__main__':main()
