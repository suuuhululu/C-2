"""취소 가능한 계산 프로세스. 관리 저장소 확정은 부모 프로세스만 수행한다."""
from __future__ import annotations

import multiprocessing
import time
import tempfile

from .artifacts import ManagedArtifactStore
from .pipeline import GeneratePipeline, GenerationCanceled, PipelineError


class BufferedStore:
    """계산 중에는 원본을 읽고 산출물을 메모리에 보관한다. DB에 쓰지 않는다."""
    def __init__(self, store):
        self.store = store
        self.bundles = []

    def read(self, *args):
        return self.store.read(*args)

    def read_json(self, *args):
        return self.store.read_json(*args)

    def put_bundle(self, items):
        self.bundles.append(list(items))


def calculate(connection, root, max_bytes, goal, timeout_s, scratch,
              allow_real_preview=False, allow_real_execution=False):
    tempfile.tempdir = scratch
    buffered = BufferedStore(ManagedArtifactStore(root, max_bytes))
    try:
        generated = GeneratePipeline(
            buffered, timeout_s=timeout_s, allow_real_preview=allow_real_preview,
            allow_real_execution=allow_real_execution).run(
            goal, feedback=lambda stage, progress: connection.send(('feedback', (stage, progress)))
        )
        connection.send(('success', (generated, buffered.bundles)))
    except PipelineError as exc:
        connection.send(('failure', (exc.code, exc.message, exc.svg_asset_id,
                                     exc.validation_report_id, buffered.bundles)))
    except Exception as exc:
        connection.send(('failure', ('UNKNOWN', f'계산 오류: {type(exc).__name__}', '', '', [])))
    finally:
        connection.close()


def run_generation(store, goal, *, timeout_s=120.0, canceled=lambda: False,
                   feedback=lambda stage, progress: None, worker_target=calculate,
                   allow_real_preview=False, allow_real_execution=False):
    """긴 Python/네이티브 계산도 종료하고 회수한 뒤에만 취소 결과를 반환한다.

    worker_target은 비협조적 계산을 재현하는 시험 주입점이다. ROS 파라미터가 아니다.
    allow_real_preview=True 일 때만 계산 프로세스에 그 값을 넘긴다(끄면 기존 인자 그대로라 시험용 worker_target 이 그대로 동작한다).
    취소와 기한은 최종 저장 직전까지 검사한다. 저장 확정 후에는 성공을 유지한다.
    """
    context = multiprocessing.get_context('spawn')
    incoming, outgoing = context.Pipe(duplex=False)
    scratch = tempfile.TemporaryDirectory(prefix='c2-generation-')
    process = context.Process(target=worker_target, args=(outgoing, str(store.root),
        store.max_input_bytes, dict(goal), timeout_s, scratch.name)
        + ((bool(allow_real_preview), True) if allow_real_execution
           else (True,) if allow_real_preview else ()), daemon=True)
    started = time.monotonic()

    def check():
        if canceled():
            raise GenerationCanceled()
        if time.monotonic() - started >= timeout_s:
            raise PipelineError('TIMEOUT', f'경로 생성 제한 시간 {timeout_s:g}초를 초과했습니다.')

    try:
        check()
        process.start()
        outgoing.close()
        while True:
            check()
            if incoming.poll(.05):
                try:
                    kind, payload = incoming.recv()
                except EOFError as exc:
                    raise PipelineError('UNKNOWN', '경로 계산 프로세스가 결과 없이 종료됐습니다.') from exc
                if kind == 'feedback':
                    feedback(*payload)
                    continue
                # 결과 수신 후 자식 종료를 확인한 다음 저장한다.
                process.join(timeout=1)
                if process.is_alive():
                    raise PipelineError('UNKNOWN', '경로 계산 프로세스 종료를 확인하지 못했습니다.')
                check()
                bundles = payload[-1]
                for bundle in bundles:
                    store.put_bundle(bundle)
                if kind == 'success':
                    return payload[0]
                code, message, svg, report, _ = payload
                raise PipelineError(code, message, svg_asset_id=svg, validation_report_id=report)
            if not process.is_alive():
                raise PipelineError('UNKNOWN', '경로 계산 프로세스가 결과 없이 종료됐습니다.')
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            if process.is_alive():
                raise RuntimeError('계산 프로세스 종료 미확인')
            process.close()
        incoming.close()
        outgoing.close()
        scratch.cleanup()
