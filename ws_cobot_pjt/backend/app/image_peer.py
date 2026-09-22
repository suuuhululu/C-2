"""실제 이미지 계산 + 기존 모의 준비/공정 peer. 별도 실행 상태 기계를 만들지 않는다."""
import asyncio
from .mock_peer import MockPeer
from .artifact_loader import PathArtifactLoader


class ImageMockPeer(MockPeer):
    async def generate(self, goal, feedback):
        from c2_path.artifacts import ManagedArtifactStore
        from c2_path.pipeline import GeneratePipeline, PipelineError, success_message
        loop = asyncio.get_running_loop()
        def progress(stage, value):
            asyncio.run_coroutine_threadsafe(feedback(dict(request_id=goal['request_id'], stage=stage,
                                                           progress=value)), loop).result()
        def calculate():
            try:
                if self.scenario == 'generation_failure':
                    raise PipelineError('VALIDATION_FAILED', '모의 경로 생성 실패 시나리오')
                generated = GeneratePipeline(ManagedArtifactStore(self.store.root)).run(
                    goal, feedback=progress,
                    canceled=lambda: goal['request_id'] in getattr(self, 'generation_cancels', set()))
                result = {key: getattr(generated, key) for key in (
                    'path_id','path_version','path_sha256','svg_asset_id','preview_asset_id',
                    'validation_report_id','segment_count','cut_length_m')}
                result.update(success=True, error_code='NONE', validation_passed=True, message=success_message(generated))
                metadata = PathArtifactLoader(self.store).load(goal, result)
                metadata['execution_backend'] = 'MOCK_ONLY'
                return metadata, result
            except PipelineError as exc:
                return None, dict(success=False, validation_passed=False, error_code=exc.code, message=exc.message,
                                  path_id='',path_version=0,path_sha256='',svg_asset_id=exc.svg_asset_id,
                                  preview_asset_id='',validation_report_id=exc.validation_report_id,
                                  segment_count=0,cut_length_m=0.)
        try:
            return await asyncio.to_thread(calculate)
        finally:
            getattr(self, 'generation_cancels', set()).discard(goal['request_id'])
