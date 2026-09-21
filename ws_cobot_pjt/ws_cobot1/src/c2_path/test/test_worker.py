"""협조하지 않는 긴 계산도 취소/기한에 종료하고 DB 산출물을 남기지 않는다."""
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path

from c2_path.artifacts import ManagedArtifactStore
from c2_path.pipeline import GenerationCanceled, PipelineError
from c2_path.worker import run_generation


def blocked(connection, root, max_bytes, goal, timeout, scratch):
    connection.send(('feedback', ('CONVERTING', .05)))
    time.sleep(30)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        p=Path(self.directory.name)
        (p/'assets').mkdir();(p/'monitor.sqlite3').touch()
        self.store=ManagedArtifactStore(p)

    def tearDown(self):
        self.directory.cleanup()

    def test_cancel_terminates_worker_and_releases_next_request(self):
        for _ in range(2):
            cancel=[False];started=time.monotonic()
            with self.assertRaises(GenerationCanceled):
                run_generation(self.store,{},timeout_s=10,worker_target=blocked,
                    feedback=lambda *args:cancel.__setitem__(0,True),canceled=lambda:cancel[0])
            self.assertLess(time.monotonic()-started,5)
            self.assertEqual(multiprocessing.active_children(),[])
            self.assertEqual(list(self.store.files.iterdir()),[])

    def test_deadline_interrupts_noncooperative_stage(self):
        started=time.monotonic()
        with self.assertRaises(PipelineError) as exc:
            run_generation(self.store,{},timeout_s=.2,worker_target=blocked)
        self.assertEqual(exc.exception.code,'TIMEOUT')
        self.assertLess(time.monotonic()-started,3)
        self.assertEqual(multiprocessing.active_children(),[])


if __name__=='__main__':unittest.main()
