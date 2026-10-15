"""One native case, optionally bound to an approved A step; no B completion claim."""
import json
from pathlib import Path
import signal
import subprocess
import sys


class FixedStepProcess:
    def __init__(self, robot_root, directory, *, scenario=None, supply_depth_profile=None,
                 educational_depth_demo=False, execution_profile=None, approved_step_document=None, native_step='T1', three_step_trial=False,
                 return_home_after_step=False):
        if native_step not in ('T1', 'T2', 'T3') or native_step != 'T1' and approved_step_document is None:
            raise ValueError('NONFIXED_STEP_REQUIRES_APPROVED_A_BINDING')
        if execution_profile is not None and (supply_depth_profile is not None or educational_depth_demo):
            raise ValueError('CONFLICTING_SUPPLY_PROFILE_OPTIONS')
        if educational_depth_demo and supply_depth_profile is None:
            raise ValueError('EDUCATIONAL_FIXED_T1_REQUIRES_SUPPLY_DEPTH_PROFILE')
        self.root = Path(robot_root).resolve()
        self.directory = Path(directory).resolve()
        self.process = None
        self.stopping = False
        self.result = None
        self.output = None
        self.scenario = Path(scenario).resolve() if scenario is not None else None
        self.supply_depth_profile = Path(supply_depth_profile).resolve() if supply_depth_profile is not None else None
        self.educational_depth_demo = educational_depth_demo
        self.execution_profile = Path(execution_profile).resolve() if execution_profile is not None else None
        self.approved_step_document = Path(approved_step_document).resolve() if approved_step_document is not None else None
        self.native_step = native_step
        self.three_step_trial = three_step_trial
        self.return_home_after_step = return_home_after_step
        if return_home_after_step and (three_step_trial or approved_step_document is None):
            raise ValueError('REAL_B_HOME_REQUIRES_SINGLE_APPROVED_STEP')
        if three_step_trial and (approved_step_document is None or execution_profile is None or native_step != 'T2'):
            raise ValueError('THREE_STEP_TRIAL_REQUIRES_APPROVED_T2_FIRST')

    def start(self):
        if self.process is not None:
            raise RuntimeError('FIXED_TRIAL_ALREADY_STARTED')
        self.directory.mkdir(parents=True, exist_ok=False)
        self.output = (self.directory / 'console.log').open('x')
        command = [sys.executable, '-m', 'scripts.round2_three_step_trial', 'run',
                   *(['--three-step-trial'] if self.three_step_trial else ['--only-step', self.native_step]), '--execute', '--confirm-hand-clear',
                   '--start-zone', 'home']
        if self.scenario is not None:
            command.extend(['--scenario', str(self.scenario)])
        if self.return_home_after_step:
            command.append('--return-home-after-step')
        if self.supply_depth_profile is not None:
            command.extend(['--supply-depth-profile', str(self.supply_depth_profile)])
        if self.execution_profile is not None:
            command.extend(['--execution-profile', str(self.execution_profile)])
        if self.approved_step_document is not None:
            command.extend(['--approved-step-document', str(self.approved_step_document)])
        if self.educational_depth_demo:
            command.append('--educational-depth-demo')
        command.extend(['--output', str(self.directory)])
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
                if not isinstance(native, dict):
                    raise ValueError('NATIVE_RESULT_OBJECT_REQUIRED')
        except (OSError, ValueError) as error:
            native = dict(status='INVALID_RESULT', reason=str(error))
        succeeded = (not self.stopping and code == 0 and native is not None
            and native.get('status') == ('THREE_CYCLES_COMPLETED' if self.three_step_trial else 'FIXED_STEP_EXECUTED')
            and native.get('completed_steps') == (['T2','T1','T3'] if self.three_step_trial else [self.native_step])
            and native.get('backend') == 'REAL'
            and native.get('provenance') == 'LIVE_D_RUNTIME'
            and native.get('assembly_completion') is False
            and native.get('current_update') is False)
        needs_home = self.three_step_trial or self.return_home_after_step
        returns = native.get('home_returns') if succeeded else None
        home_verified = (succeeded and needs_home and isinstance(returns,list)
            and len(returns)==(3 if self.three_step_trial else 1)
            and all(isinstance(r,dict) and r.get('view')=='HOME' and r.get('stopped_verified') is True for r in returns))
        succeeded = succeeded and (not needs_home or home_verified)
        self.result = dict(status=('THREE_STEP_TRIAL_EXECUTED' if self.three_step_trial else 'FIXED_STEP_EXECUTED')
                if succeeded else 'FIXED_STEP_INTERRUPTED_OR_FAILED',
            returncode=code, native_result=native, output_directory=str(self.directory),
            stop_requested=self.stopping, actual_stop_verified=bool(home_verified), home_return_verified=bool(home_verified),
            assembly_completion=False, current_update=False)
        return self.result

    def progress(self):
        paths = list(self.directory.glob('*/progress.json'))
        if len(paths) != 1:
            return None
        try:
            value = json.loads(paths[0].read_text())
            return value if isinstance(value,dict) else None
        except (OSError,ValueError):
            return None

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.stop()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                raise RuntimeError('FIXED_TRIAL_SHUTDOWN_PENDING_VERIFY_PHYSICAL_STOP') from None
        self.poll()
