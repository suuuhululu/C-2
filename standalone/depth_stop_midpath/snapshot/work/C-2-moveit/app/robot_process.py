"""별도 D Robot 프로세스 호출. 기존 Backend/HMI에는 자동 연결하지 않는다."""
import json
import queue
from pathlib import Path
import subprocess
import sys
import threading


class RobotProcess:
    def __init__(self, robot_root, *, mode='MOCK', config=None, python=sys.executable, gestures=False):
        if mode not in ('MOCK', 'REAL'):
            raise ValueError('explicit MOCK/REAL required')
        root = Path(robot_root).resolve()
        if not (root/'scripts/robot_integration_runtime.py').is_file():
            raise ValueError('integrated robot entrypoint missing')
        command = [python, '-m', 'scripts.robot_integration_runtime', '--mode', mode]
        if config is not None: command += ['--config', str(Path(config).resolve())]
        if gestures: command.append('--gestures')
        # stderr remains visible; it cannot block or corrupt JSON replies.
        self.process = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, bufsize=1)
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.events.put(json.loads(line))
        except Exception as error:
            self.events.put(dict(event='CHANNEL_ERROR', data=dict(reason=str(error))))
        finally:
            self.events.put(dict(event='PROCESS_EXITED', data={}))

    def send(self, command, **payload):
        text = json.dumps(dict(command=command, **payload), ensure_ascii=False, allow_nan=False)+'\n'
        with self.lock:
            if self.process.poll() is not None: raise RuntimeError('robot process exited')
            self.process.stdin.write(text)
            self.process.stdin.flush()

    def receive(self, timeout=5):
        return self.events.get(timeout=timeout)

    def close(self):
        if self.process.poll() is None:
            self.send('CLOSE')
            try: self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                # A process timeout is not proof of a stopped robot; don't kill a force cleanup.
                raise RuntimeError('robot shutdown pending; verify STOP') from None
        self.reader.join(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
