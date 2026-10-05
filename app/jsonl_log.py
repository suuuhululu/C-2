"""Job마다 주요 이벤트 한 줄씩 기록한다. 영상·DB·종료 후 복원은 없다."""

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID


class JsonlLog:
    def __init__(self, directory):
        self.directory = Path(directory)

    def __call__(self, event: dict) -> None:
        job_id = str(UUID(event["job_id"]))
        if job_id != event["job_id"]:
            raise ValueError("log.job_id: expected canonical UUID")
        line = json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(), **event),
                          ensure_ascii=False, allow_nan=False)
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / f"{job_id}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
