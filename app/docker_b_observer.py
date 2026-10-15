"""D transport only. The existing B inspection connection still owns Current/Expected."""
from copy import deepcopy
import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Thread


class DockerBObserver:
    def __init__(self, root, controller, *, settings, calibration, weights, output,
                 process_factory=subprocess.Popen, capture_settings=None):
        self.root = Path(root).resolve()
        self.controller = controller
        self.settings, self.calibration, self.weights = settings, calibration, weights
        self.output = Path(output).resolve()
        self.process_factory = process_factory
        self.capture_settings = deepcopy(capture_settings)

    def container_path(self, value):
        return '/workspace/'+str(Path(value).resolve().relative_to(self.root))

    def __call__(self, context, active):
        output = self.output/context['check_id']
        output.mkdir(parents=True, exist_ok=True)
        request = dict(context=deepcopy(context), scene_id=context['check_id'],
            settings=self.container_path(self.settings), calibration=self.container_path(self.calibration),
            weights=self.container_path(self.weights), output=self.container_path(output))
        if self.capture_settings is not None:
            request['capture_settings'] = self.capture_settings
        process = self.process_factory([str(self.root/'scripts/c2_b_docker.sh'), 'python', '-m',
            'perception_mvp.docker_inspection'], cwd=self.root, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, bufsize=1)
        rows = Queue()

        def read():
            try:
                for line in process.stdout:
                    rows.put(json.loads(line))
            except Exception as error:
                rows.put(dict(kind='ERROR', check_id=context['check_id'], reason=str(error)))
            finally:
                rows.put(None)

        reader = Thread(target=read, daemon=True)
        reader.start()
        last_sequence = 0
        try:
            process.stdin.write(json.dumps(request, allow_nan=False)+'\n')
            process.stdin.flush()
            while True:
                if active() is not True:
                    raise RuntimeError('inspection canceled')
                try:
                    row = rows.get(timeout=.05)
                except Empty:
                    continue
                if row is None:
                    raise RuntimeError('B_DOCKER_EXITED_WITHOUT_RESULT')
                if row.get('check_id') != context['check_id']:
                    raise ValueError('B_DOCKER_CHECK_BINDING_MISMATCH')
                if row['kind'] == 'ERROR':
                    raise RuntimeError(row['reason'])
                if row['kind'] == 'PROGRESS':
                    from perception.perception_mvp.runtime_log import progress
                    if (not isinstance(row.get('message'),str) or row.get('view') not in (None,'V0','D1','D3')
                            or not isinstance(row.get('details'),dict)):
                        raise ValueError('B_DOCKER_INVALID_PROGRESS')
                    progress(context,row['message'],view=row['view'],**row['details'])
                    continue
                if row['kind'] == 'RESULT':
                    if active() is not True:
                        raise RuntimeError('inspection canceled')
                    observed = row['observed']
                    if (observed['check_id'], observed['observation_seq']) != (
                            context['check_id'], context['observation_seq']):
                        raise ValueError('B_DOCKER_OBSERVATION_BINDING_MISMATCH')
                    process.wait(timeout=10)
                    if process.returncode != 0:
                        raise RuntimeError('B_DOCKER_RESULT_PROCESS_FAILED')
                    return observed, row['diagnostics']
                sequence = row.get('sequence')
                if row['kind'] != 'HOOK' or type(sequence) is not int or sequence != last_sequence+1:
                    raise ValueError('B_DOCKER_HOOK_SEQUENCE_MISMATCH')
                last_sequence = sequence
                reply = dict(check_id=context['check_id'], sequence=sequence)
                try:
                    name, args = row['name'], row['args']
                    if name == 'valid' and not args:
                        value = active() is True
                    elif name in ('confirm_view', 'is_stopped', 'robot_pose') and len(args) == 1:
                        value = getattr(self.controller, name)(context['check_id'], args[0], active)
                    else:
                        raise ValueError('B_DOCKER_UNKNOWN_HOOK')
                    reply['value'] = value
                except Exception as error:
                    reply['error'] = str(error)
                process.stdin.write(json.dumps(reply, allow_nan=False)+'\n')
                process.stdin.flush()
        finally:
            # This process only receives camera data. Terminating it is not Robot STOP evidence.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
            reader.join(timeout=1)
