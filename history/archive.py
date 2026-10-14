"""Byte-preserving, content-addressed snapshots; never modify the producer log."""

import hashlib
import os
from pathlib import Path
import tempfile

from history.records import InputError


def snapshot(path: Path, root: Path) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with path.open("rb") as source, tempfile.NamedTemporaryFile(dir=root, delete=False) as target:
            temporary = Path(target.name)
            source.seek(0, 2)
            size = source.tell()
            source.seek(0)
            remaining, digest = size, hashlib.sha256()
            while remaining:
                chunk = source.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise InputError("source truncated while preserving original log")
                target.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            target.flush()
            os.fsync(target.fileno())
        checksum = digest.hexdigest()
        preserved = root / (checksum + ".jsonl")
        try:
            # A previous snapshot is immutable, including on concurrent import.
            os.link(temporary, preserved)
        except FileExistsError:
            with preserved.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() != checksum:
                    raise InputError("preserved original log checksum differs")
        return dict(path=str(preserved), sha256=checksum, bytes=size)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prefix_digest(records) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record["raw"].encode("utf-8"))
    return digest.hexdigest()
