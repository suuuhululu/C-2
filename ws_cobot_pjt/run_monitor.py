"""새 모니터의 로컬 모의 서버·화면 실행. 설치나 로봇 브링업을 수행하지 않는다."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def main():
    root=Path(__file__).resolve().parent
    python=root/'backend/.venv/bin/python'
    node=shutil.which('node')
    bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    if not node and bundled.is_file():node=str(bundled)
    vite=root/'frontend/node_modules/vite/bin/vite.js'
    if not node or not python.exists() or not vite.exists():
        raise SystemExit('backend/README.md · frontend/README.md의 의존성 설치를 먼저 완료하세요.')
    env=os.environ.copy();env['C2_MONITOR_MODE']='SIMULATION';env['C2_MONITOR_TRANSPORT']='mock'
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
        children.append(subprocess.Popen([str(python),'-m','uvicorn','app.monitor:app','--host','127.0.0.1','--port','8010'],cwd=root/'backend',env=env))
        children.append(subprocess.Popen([node,str(vite),'--host','127.0.0.1'],cwd=root/'frontend',env=env))
        print('새김 HMI: http://127.0.0.1:5174/operator',flush=True)
        print('SIMULATION · 새 DB: backend/monitor_data/monitor.sqlite3 · 종료 Ctrl+C',flush=True)
        while all(p.poll() is None for p in children):time.sleep(.3)
    finally:stop()


if __name__=='__main__':main()
