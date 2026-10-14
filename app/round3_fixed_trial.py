"""One existing native trial, isolated from C/A jobs and B completion claims."""
import json
from pathlib import Path
import signal
import subprocess
import sys


class FixedStepProcess:
    def __init__(self, robot_root, directory):
        self.root = Path(robot_root).resolve()
        self.directory = Path(directory).resolve()
        self.process = None
        self.stopping = False
        self.result = None
        self.output = None

    def start(self):
        if self.process is not None:
            raise RuntimeError('FIXED_TRIAL_ALREADY_STARTED')
        self.directory.mkdir(parents=True, exist_ok=False)
        self.output = (self.directory / 'console.log').open('x')
        command = [sys.executable, '-m', 'scripts.round2_three_step_trial', 'run',
                   '--only-step', 'T1', '--execute', '--confirm-hand-clear',
                   '--start-zone', 'home', '--output', str(self.directory)]
        try:
            self.process = subprocess.Popen(command, cwd=self.root,
                stdout=self.output, stderr=subprocess.STDOUT)
        except Exception:
            self.output.close()
            raise

    def stop(self):
        self.stopping = True
        if self.process is not None and self.process.poll() is None:
            # The existing trial handles SIGINT on its main thread, calls
            # driver.stop(), and unwinds its camera/ROS resources. Never kill it.
            self.process.send_signal(signal.SIGINT)

    def poll(self):
        if self.result is not None or self.process is None:
            return self.result
        code = self.process.poll()
        if code is None:
            return None
        self.output.close()
        documents = list(self.directory.glob('*/result.json'))
        native = None
        try:
            if len(documents) == 1:
                native = json.loads(documents[0].read_text())
        except (OSError, ValueError) as error:
            native = dict(status='INVALID_RESULT', reason=str(error))
        succeeded = (not self.stopping and code == 0 and native is not None
            and native.get('status') == 'FIXED_STEP_EXECUTED'
            and native.get('completed_steps') == ['T1']
            and native.get('backend') == 'REAL'
            and native.get('provenance') == 'LIVE_D_RUNTIME'
            and native.get('assembly_completion') is False
            and native.get('current_update') is False)
        self.result = dict(status='FIXED_STEP_EXECUTED' if succeeded else 'FIXED_STEP_INTERRUPTED_OR_FAILED',
            returncode=code, native_result=native, output_directory=str(self.directory),
            stop_requested=self.stopping, actual_stop_verified=False,
            assembly_completion=False, current_update=False)
        return self.result

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.stop()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                raise RuntimeError('FIXED_TRIAL_SHUTDOWN_PENDING_VERIFY_PHYSICAL_STOP') from None
        self.poll()
