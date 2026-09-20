"""HMI 관리 파일 저장소와 c2_path 사이의 최소 파일 어댑터.

브라우저가 보낸 경로를 열지 않고 UUID로 등록된 파일만 읽는다. 생성 산출물은
임시 파일 작성 → 원자적 rename → SQLite 등록 순으로 한 묶음으로 확정한다.
이 모듈은 HMI 서비스 로직이나 로봇 실행을 import하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID, uuid4


class ArtifactError(RuntimeError):
    """관리 파일을 안전하게 해석하거나 저장하지 못했을 때 발생한다."""

    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message if message is not None else code)


def json_bytes(value) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_id() -> str:
    return str(uuid4())


def _uuid(value: str, field: str) -> str:
    try:
        parsed = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ArtifactError("INVALID_INPUT", f"{field}는 UUID여야 합니다.") from exc
    if parsed != str(value).lower():
        raise ArtifactError("INVALID_INPUT", f"{field}는 정규화된 UUID 문자열이어야 합니다.")
    return parsed


def _sha256(value: str, field: str) -> str:
    value = str(value)
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ArtifactError("INVALID_INPUT", f"{field}는 소문자 SHA-256이어야 합니다.")
    return value


@dataclass(frozen=True)
class Artifact:
    id: str
    sha256: str
    kind: str
    mime: str
    name: str
    size_bytes: int
    path: Path
    data: bytes


@dataclass(frozen=True)
class ArtifactWrite:
    data: bytes
    kind: str
    mime: str
    name: str
    metadata: dict
    asset_id: str


class ManagedArtifactStore:
    """backend/app/storage.py가 만든 monitor_data를 엄격히 공유한다.

    DB 스키마를 새로 만들거나 변경하지 않는다. 서버가 먼저 초기화한
    ``monitor.sqlite3``와 ``assets`` 디렉터리가 없으면 요청을 거절한다.
    """

    def __init__(self, root, max_input_bytes=10 * 1024 * 1024):
        if not root:
            raise ArtifactError("NOT_READY", "managed_data_dir ROS 파라미터가 필요합니다.")
        self.root = Path(root).expanduser().resolve()
        self.files = (self.root / "assets").resolve()
        self.db_path = (self.root / "monitor.sqlite3").resolve()
        self.max_input_bytes = int(max_input_bytes)
        if not self.db_path.is_file() or not self.files.is_dir():
            raise ArtifactError("NOT_READY", "HMI 관리 저장소가 초기화되지 않았습니다.")

    def _connect(self):
        try:
            connection = sqlite3.connect(self.db_path, timeout=2.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        except sqlite3.Error as exc:
            raise ArtifactError("STORAGE_ERROR", "관리 DB에 연결할 수 없습니다.") from exc

    def read(self, asset_id: str, expected_sha256: str, allowed_kinds: Iterable[str]) -> Artifact:
        asset_id = _uuid(asset_id, "asset_id")
        expected_sha256 = _sha256(expected_sha256, "asset_sha256")
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        except sqlite3.Error as exc:
            raise ArtifactError("STORAGE_ERROR", "관리 DB에서 파일 정보를 읽지 못했습니다.") from exc
        if row is None:
            raise ArtifactError("ASSET_NOT_FOUND", "관리 파일 ID를 찾을 수 없습니다.")
        if row["kind"] not in set(allowed_kinds):
            raise ArtifactError("UNSUPPORTED_FORMAT", f"허용하지 않는 관리 파일 종류입니다: {row['kind']}")
        key = str(row["storage_key"])
        if Path(key).name != key:
            raise ArtifactError("STORAGE_ERROR", "관리 파일 storage_key가 안전하지 않습니다.")
        path = (self.files / key).resolve()
        if path.parent != self.files or not path.is_file():
            raise ArtifactError("ASSET_NOT_FOUND", "관리 파일 경로가 저장소 밖이거나 존재하지 않습니다.")
        size = path.stat().st_size
        if size <= 0 or size > self.max_input_bytes:
            raise ArtifactError("UNSUPPORTED_FORMAT", "관리 파일 크기가 허용 범위를 벗어났습니다.")
        data = path.read_bytes()
        observed = sha256_bytes(data)
        if observed != row["sha256"] or observed != expected_sha256:
            raise ArtifactError("HASH_MISMATCH")
        return Artifact(
            id=asset_id,
            sha256=observed,
            kind=str(row["kind"]),
            mime=str(row["mime"]),
            name=str(row["name"]),
            size_bytes=size,
            path=path,
            data=data,
        )

    def read_json(self, asset_id: str, expected_sha256: str, allowed_kinds=("profile",)):
        artifact = self.read(asset_id, expected_sha256, allowed_kinds)
        try:
            value = json.loads(artifact.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactError("PROFILE_MISMATCH", "설정 스냅샷이 유효한 UTF-8 JSON이 아닙니다.") from exc
        if not isinstance(value, dict):
            raise ArtifactError("PROFILE_MISMATCH", "설정 스냅샷의 최상위는 객체여야 합니다.")
        return value, artifact

    def put_bundle(self, writes: Iterable[ArtifactWrite]) -> dict[str, Artifact]:
        writes = list(writes)
        if not writes:
            return {}
        ids = [_uuid(item.asset_id, "output asset_id") for item in writes]
        if len(ids) != len(set(ids)):
            raise ArtifactError("STORAGE_ERROR", "산출물 UUID가 중복됐습니다.")

        targets = []
        temps = []
        records = {}
        try:
            for item, asset_id in zip(writes, ids):
                if not item.data:
                    raise ArtifactError("STORAGE_ERROR", f"빈 산출물은 저장할 수 없습니다: {item.name}")
                target = self.files / f"{asset_id}.bin"
                temp = self.files / f".{asset_id}.{os.getpid()}.tmp"
                if target.exists() or temp.exists():
                    raise ArtifactError("STORAGE_ERROR", "산출물 UUID가 이미 존재합니다.")
                temps.append(temp)
                with temp.open("xb") as stream:
                    stream.write(item.data)
                    stream.flush()
                    os.fsync(stream.fileno())
                temp.replace(target)
                targets.append(target)
                records[asset_id] = Artifact(
                    id=asset_id,
                    sha256=sha256_bytes(item.data),
                    kind=item.kind,
                    mime=item.mime,
                    name=item.name,
                    size_bytes=len(item.data),
                    path=target,
                    data=item.data,
                )

            with self._connect() as connection:
                for item, asset_id in zip(writes, ids):
                    record = records[asset_id]
                    connection.execute(
                        """INSERT INTO assets
                        (id,sha256,kind,storage_key,mime,name,size_bytes,metadata,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            record.id,
                            record.sha256,
                            record.kind,
                            record.path.name,
                            record.mime,
                            record.name,
                            record.size_bytes,
                            json.dumps(item.metadata, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"), allow_nan=False),
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
            return records
        except Exception as exc:
            for temp in temps:
                temp.unlink(missing_ok=True)
            for target in targets:
                target.unlink(missing_ok=True)
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError("STORAGE_ERROR", "산출물 묶음을 관리 저장소에 확정하지 못했습니다.") from exc
