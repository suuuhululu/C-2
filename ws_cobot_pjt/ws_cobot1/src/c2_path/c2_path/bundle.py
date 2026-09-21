"""파일 묶음(bundle) 방식의 GeneratePath 입·출력 — 1차 통합 시험(PC 한 대)용.

HMI가 등록한 스냅샷·입력 이미지·요청 정보를 폴더(입력 묶음)로 받아 경로를 만들고,
결과를 ``manifest.json`` 이 붙은 폴더(출력 묶음)로 내보낸다. ROS 액션(node.py)과
같은 ``GeneratePipeline`` 을 그대로 쓰므로 계산·검증 로직은 하나뿐이다.

  python -m c2_path.bundle run    --input <입력 묶음> --output <출력 묶음>
  python -m c2_path.bundle verify <묶음>

이 방식은 **파일 기반 시험** 경로다. 기존 ROS 연동(node.py)을 대체하지 않으며, 시험 기록에는
"파일 묶음 시험"과 "ROS 통신 시험"을 구분해 적는다.

규칙
  - 파일 바이트를 다시 직렬화하지 않는다. 해시는 전달받은/저장한 파일 바이트 그대로 계산한다.
  - 묶음 안에서는 상대 파일명(폴더 없음)만 쓴다. 각자 PC의 절대 경로를 넣지 않는다.
  - ``manifest.json`` 은 자기 자신의 해시를 담지 않는다(목록에서 제외). 나머지 모든 파일이 목록에 있어야 한다.
  - ID·해시는 스냅샷 본문에 넣지 않고 manifest·result·요청에 기록한다.
  - 로봇·그리퍼·두산 API를 호출하지 않는다. SIMULATION 전용.

manifest 규격은 HMI 가져오기를 위한 **전달 규격 제안**이며 아직 공통 규격으로 확정되지 않았다
(BUNDLE_SPEC.md 참고).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Mapping
from uuid import UUID

from .artifacts import Artifact, ArtifactError, json_bytes, sha256_bytes

MANIFEST_CONTRACT = "c2-path-bundle/1"
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
REQUEST_NAME = "request.json"
RESULT_NAME = "result.json"
RESERVED_NAMES = (MANIFEST_NAME, REQUEST_NAME, RESULT_NAME)

ROLE_INPUT = "input"
ROLE_OUTPUT = "output"
INPUT_KINDS = ("image", "profile")
OUTPUT_KINDS = ("path", "svg", "preview", "validation")

JSON_MIME = "application/json"
KIND_MIMES = {
    "image": ("image/png", "image/jpeg"),
    "profile": (JSON_MIME,),
    "path": (JSON_MIME,),
    "svg": ("image/svg+xml",),
    "preview": (JSON_MIME,),
    "validation": (JSON_MIME,),
}

# c2_interfaces/action/GeneratePath.action 의 Goal/Result 필드 (test_bundle 이 action 파일과 대조한다).
GOAL_FIELDS = (
    "schema_version", "request_id", "source_mode", "asset_id", "asset_sha256",
    "width_mm", "height_mm", "offset_u_mm", "offset_v_mm", "rotation_deg",
    "conversion_preset", "tool_id", "profile_snapshot_id", "profile_sha256",
)
RESULT_FIELDS = (
    "success", "error_code", "message", "path_id", "path_version", "path_sha256",
    "svg_asset_id", "preview_asset_id", "segment_count", "cut_length_m",
    "validation_passed", "validation_report_id",
)


class BundleError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


# --------------------------------------------------------------------------- 공통 도우미
def _is_uuid(value) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _is_sha(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _is_safe_name(value) -> bool:
    return (isinstance(value, str) and value not in ("", ".", "..") and value == Path(value).name
            and "\\" not in value and "\x00" not in value and not value.startswith("."))


def _reject_constant(name):
    raise ValueError(f"허용하지 않는 JSON 값: {name}")


def loads_json(data: bytes):
    return json.loads(data.decode("utf-8"), parse_constant=_reject_constant)


def _type_ok(value, expected) -> bool:
    if expected is bool:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _atomic_write(target: Path, data: bytes) -> None:
    temp = target.with_name(f".{target.name}.tmp")
    with temp.open("xb") as stream:
        stream.write(data)
        stream.flush()
    temp.replace(target)


def _document(kind: str, name: str, data: bytes) -> dict:
    return {"kind": kind, "file": name, "mime": JSON_MIME, "sha256": sha256_bytes(data), "size_bytes": len(data)}


def _file_entry(record: Artifact, metadata: Mapping) -> dict:
    entry = {
        "asset_id": record.id,
        "kind": record.kind,
        "file": record.name,
        "name": record.name,
        "mime": record.mime,
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "path_id": metadata.get("path_id"),
        "path_version": metadata.get("path_version"),
    }
    if "executable" in metadata:
        entry["executable"] = bool(metadata["executable"])
    return entry


# --------------------------------------------------------------------------- 저장소
class BundleStore:
    """``ManagedArtifactStore`` 와 같은 read/read_json/put_bundle 를 폴더로 구현한다.

    입력은 입력 묶음 폴더의 manifest 로 조회하고(경로 문자열이 아니라 asset_id 로만 연다),
    산출물은 출력 폴더에 쓴다. SQLite·HMI 저장소를 건드리지 않는다.
    """

    def __init__(self, input_dir, output_dir, max_input_bytes=10 * 1024 * 1024):
        self.input_dir = Path(input_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.max_input_bytes = int(max_input_bytes)
        manifest = load_manifest(self.input_dir, ROLE_INPUT)
        self._inputs = {entry["asset_id"]: entry for entry in manifest["files"]}
        self._written: list[dict] = []
        self._names: set[str] = set()

    # -- 읽기 (ManagedArtifactStore.read 와 같은 오류 코드) --
    def read(self, asset_id, expected_sha256, allowed_kinds) -> Artifact:
        if not _is_uuid(asset_id):
            raise ArtifactError("INVALID_INPUT", "asset_id는 정규화된 UUID여야 합니다.")
        if not _is_sha(expected_sha256):
            raise ArtifactError("INVALID_INPUT", "asset_sha256는 소문자 SHA-256이어야 합니다.")
        entry = self._inputs.get(asset_id)
        if entry is None:
            raise ArtifactError("ASSET_NOT_FOUND", "입력 묶음에서 파일 ID를 찾을 수 없습니다.")
        if entry["kind"] not in set(allowed_kinds):
            raise ArtifactError("UNSUPPORTED_FORMAT", f"허용하지 않는 관리 파일 종류입니다: {entry['kind']}")
        if not _is_safe_name(entry["file"]):
            raise ArtifactError("STORAGE_ERROR", "입력 묶음 파일명이 안전하지 않습니다.")
        path = (self.input_dir / entry["file"]).resolve()
        if path.parent != self.input_dir or not path.is_file():
            raise ArtifactError("ASSET_NOT_FOUND", "입력 묶음 파일이 없거나 묶음 밖입니다.")
        size = path.stat().st_size
        if size <= 0 or size > self.max_input_bytes:
            raise ArtifactError("UNSUPPORTED_FORMAT", "관리 파일 크기가 허용 범위를 벗어났습니다.")
        data = path.read_bytes()
        observed = sha256_bytes(data)
        if observed != entry["sha256"] or observed != expected_sha256:
            raise ArtifactError("HASH_MISMATCH")
        return Artifact(id=asset_id, sha256=observed, kind=entry["kind"], mime=entry["mime"],
                        name=entry["name"], size_bytes=size, path=path, data=data)

    def read_json(self, asset_id, expected_sha256, allowed_kinds=("profile",)):
        artifact = self.read(asset_id, expected_sha256, allowed_kinds)
        try:
            value = loads_json(artifact.data)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ArtifactError("PROFILE_MISMATCH", "설정 스냅샷이 유효한 UTF-8 JSON이 아닙니다.") from exc
        if not isinstance(value, dict):
            raise ArtifactError("PROFILE_MISMATCH", "설정 스냅샷의 최상위는 객체여야 합니다.")
        return value, artifact

    # -- 쓰기 (한 묶음을 전부 쓰거나 전부 지운다) --
    def put_bundle(self, writes) -> dict[str, Artifact]:
        writes = list(writes)
        if not writes:
            return {}
        ids = [item.asset_id for item in writes]
        if not all(_is_uuid(i) for i in ids):
            raise ArtifactError("INVALID_INPUT", "output asset_id는 정규화된 UUID여야 합니다.")
        if len(ids) != len(set(ids)):
            raise ArtifactError("STORAGE_ERROR", "산출물 UUID가 중복됐습니다.")
        names = [item.name for item in writes]
        for name in names:
            if not _is_safe_name(name) or name in RESERVED_NAMES:
                raise ArtifactError("STORAGE_ERROR", f"산출물 파일명을 쓸 수 없습니다: {name!r}")
        if len(names) != len(set(names)) or self._names & set(names):
            raise ArtifactError("STORAGE_ERROR", "산출물 파일명이 중복됐습니다.")

        targets: list[Path] = []
        records: dict[str, Artifact] = {}
        entries: list[dict] = []
        try:
            for item in writes:
                if not item.data:
                    raise ArtifactError("STORAGE_ERROR", f"빈 산출물은 저장할 수 없습니다: {item.name}")
                if item.mime not in KIND_MIMES.get(item.kind, ()):
                    raise ArtifactError("STORAGE_ERROR", f"{item.kind} 산출물의 MIME이 올바르지 않습니다: {item.mime}")
                target = self.output_dir / item.name
                if target.exists():
                    raise ArtifactError("STORAGE_ERROR", f"산출물 파일이 이미 있습니다: {item.name}")
                _atomic_write(target, item.data)
                targets.append(target)
                record = Artifact(id=item.asset_id, sha256=sha256_bytes(item.data), kind=item.kind,
                                  mime=item.mime, name=item.name, size_bytes=len(item.data),
                                  path=target, data=item.data)
                records[item.asset_id] = record
                entries.append(_file_entry(record, item.metadata))
        except Exception as exc:
            for target in targets:
                target.unlink(missing_ok=True)
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError("STORAGE_ERROR", "산출물 묶음을 확정하지 못했습니다.") from exc
        self._written.extend(entries)
        self._names.update(names)
        return records

    def finalize(self, goal: Mapping, request_bytes: bytes, result: Mapping) -> dict:
        """request.json · result.json · manifest.json 을 쓴다. manifest 가 마지막이라 있으면 묶음이 완결이다."""
        result_bytes = json_bytes(dict(result))
        _atomic_write(self.output_dir / REQUEST_NAME, request_bytes)
        _atomic_write(self.output_dir / RESULT_NAME, result_bytes)
        path_entry = None
        if result.get("success"):
            match = [e for e in self._written if e["kind"] == "path" and e["path_id"] == result["path_id"]]
            path_entry = {
                "path_id": result["path_id"],
                "path_version": result["path_version"],
                "path_sha256": result["path_sha256"],
                "asset_id": match[0]["asset_id"] if len(match) == 1 else None,
            }
        manifest = {
            "contract": MANIFEST_CONTRACT,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "bundle_role": ROLE_OUTPUT,
            "source_mode": goal.get("source_mode"),
            "request_id": goal.get("request_id"),
            "inputs": {k: goal.get(k) for k in ("asset_id", "asset_sha256", "profile_snapshot_id", "profile_sha256")},
            "path": path_entry,
            "files": self._written,
            "documents": [_document("request", REQUEST_NAME, request_bytes),
                          _document("result", RESULT_NAME, result_bytes)],
        }
        _atomic_write(self.output_dir / MANIFEST_NAME, json_bytes(manifest))
        return manifest


# --------------------------------------------------------------------------- 입력 묶음
def load_manifest(directory, role=None) -> dict:
    directory = Path(directory)
    path = directory / MANIFEST_NAME
    if not path.is_file():
        raise BundleError("MANIFEST_MISSING", f"{MANIFEST_NAME}이 없습니다: {directory.name}")
    try:
        manifest = loads_json(path.read_bytes())
    except (UnicodeDecodeError, ValueError) as exc:
        raise BundleError("MANIFEST_INVALID", f"{MANIFEST_NAME}이 유효한 JSON이 아닙니다.") from exc
    if not isinstance(manifest, dict):
        raise BundleError("MANIFEST_INVALID", "manifest 최상위는 객체여야 합니다.")
    if manifest.get("contract") != MANIFEST_CONTRACT or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BundleError("MANIFEST_INVALID", f"지원 계약: {MANIFEST_CONTRACT} schema {MANIFEST_SCHEMA_VERSION}")
    if role and manifest.get("bundle_role") != role:
        raise BundleError("MANIFEST_INVALID", f"bundle_role은 {role}이어야 합니다.")
    if not isinstance(manifest.get("files"), list) or not all(isinstance(e, dict) for e in manifest["files"]):
        raise BundleError("MANIFEST_INVALID", "files는 객체 목록이어야 합니다.")
    for entry in manifest["files"]:
        missing = [k for k in ("asset_id", "kind", "file", "name", "mime", "sha256") if k not in entry]
        if missing:
            raise BundleError("MANIFEST_INVALID", f"files 항목에 필드가 없습니다: {missing}")
    return manifest


def write_input_bundle(directory, *, request: Mapping, image: bytes, image_name: str, image_mime: str,
                       profile_bytes: bytes, profile_name: str, origin: str) -> dict:
    """입력 묶음을 만든다. 실제 운영에서는 HMI가 이 모양으로 내보낸다(여기서는 시험·샘플용).

    request 는 GeneratePath Goal 14개 필드 전부이며 ID·해시는 호출자가 정한 값이다. 파일 바이트의 해시가
    request 와 다르면 거절한다(등록 후 재저장으로 해시가 달라지는 사고를 막는다).
    """
    directory = Path(directory)
    if set(request) != set(GOAL_FIELDS):
        raise BundleError("INVALID_INPUT", f"request 필드는 정확히 {list(GOAL_FIELDS)} 여야 합니다.")
    if sha256_bytes(image) != request["asset_sha256"]:
        raise BundleError("HASH_MISMATCH", "image 바이트의 해시가 request.asset_sha256과 다릅니다.")
    if sha256_bytes(profile_bytes) != request["profile_sha256"]:
        raise BundleError("HASH_MISMATCH", "profile 바이트의 해시가 request.profile_sha256과 다릅니다.")
    for name in (image_name, profile_name):
        if not _is_safe_name(name) or name in RESERVED_NAMES:
            raise BundleError("INVALID_INPUT", f"파일명을 쓸 수 없습니다: {name!r}")
    if image_name == profile_name:
        raise BundleError("INVALID_INPUT", "image와 profile의 파일명이 같습니다.")
    if directory.exists() and any(directory.iterdir()):
        raise BundleError("OUTPUT_EXISTS", f"비어 있지 않은 폴더에는 만들지 않습니다: {directory.name}")
    directory.mkdir(parents=True, exist_ok=True)

    request_bytes = json_bytes(dict(request))
    files = []
    for kind, asset_id, name, mime, data in (
        ("image", request["asset_id"], image_name, image_mime, image),
        ("profile", request["profile_snapshot_id"], profile_name, JSON_MIME, profile_bytes),
    ):
        _atomic_write(directory / name, data)
        files.append({"asset_id": asset_id, "kind": kind, "file": name, "name": name, "mime": mime,
                      "sha256": sha256_bytes(data), "size_bytes": len(data), "path_id": None, "path_version": None})
    _atomic_write(directory / REQUEST_NAME, request_bytes)
    manifest = {
        "contract": MANIFEST_CONTRACT,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "bundle_role": ROLE_INPUT,
        "origin": origin,
        "source_mode": request["source_mode"],
        "request_id": request["request_id"],
        "files": files,
        "documents": [_document("request", REQUEST_NAME, request_bytes)],
    }
    _atomic_write(directory / MANIFEST_NAME, json_bytes(manifest))
    return manifest


# --------------------------------------------------------------------------- 실행
def _failed_result(code, message, svg_asset_id="", validation_report_id="") -> dict:
    return {
        "success": False, "error_code": code, "message": message, "path_id": "", "path_version": 0,
        "path_sha256": "", "svg_asset_id": svg_asset_id, "preview_asset_id": "", "segment_count": 0,
        "cut_length_m": 0.0, "validation_passed": False, "validation_report_id": validation_report_id,
    }


def run_bundle(input_dir, output_dir, *, timeout_s=120.0, max_input_bytes=10 * 1024 * 1024) -> dict:
    """입력 묶음 → 경로 생성 → 출력 묶음. 생성이 실패해도 실패 result 가 담긴 출력 묶음을 남긴다.

    반환: result 사전 (GeneratePath.Result 12개 필드 전체).
    입력 묶음이 깨졌거나 출력 폴더가 비어 있지 않으면 BundleError 로 아무것도 쓰지 않는다.
    """
    from .pipeline import GeneratePipeline, PipelineError, success_message  # cv2 가 필요한 계산은 실행할 때만 불러온다

    input_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    if input_dir == output_dir:
        raise BundleError("INVALID_INPUT", "입력과 출력 폴더가 같습니다.")
    manifest = load_manifest(input_dir, ROLE_INPUT)
    documents = {d.get("kind"): d for d in manifest.get("documents", []) if isinstance(d, dict)}
    document = documents.get("request")
    if not document or document.get("file") != REQUEST_NAME:
        raise BundleError("MANIFEST_INVALID", "manifest에 request 문서가 없습니다.")
    request_path = input_dir / REQUEST_NAME
    if not request_path.is_file():
        raise BundleError("MANIFEST_INVALID", f"{REQUEST_NAME}이 없습니다.")
    request_bytes = request_path.read_bytes()
    if sha256_bytes(request_bytes) != document.get("sha256"):
        raise BundleError("HASH_MISMATCH", f"{REQUEST_NAME}의 해시가 manifest와 다릅니다.")
    try:
        goal = loads_json(request_bytes)
    except (UnicodeDecodeError, ValueError) as exc:
        raise BundleError("INVALID_INPUT", f"{REQUEST_NAME}이 유효한 JSON이 아닙니다.") from exc
    if not isinstance(goal, dict) or set(goal) != set(GOAL_FIELDS):
        raise BundleError("INVALID_INPUT", f"{REQUEST_NAME} 필드는 정확히 {list(GOAL_FIELDS)} 여야 합니다.")
    if goal.get("request_id") != manifest.get("request_id"):
        raise BundleError("INVALID_INPUT", "request_id가 manifest와 다릅니다.")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BundleError("OUTPUT_EXISTS", f"비어 있지 않은 폴더에는 쓰지 않습니다: {output_dir.name}")
    output_dir.mkdir(parents=True, exist_ok=True)

    store = BundleStore(input_dir, output_dir, max_input_bytes)
    try:
        generated = GeneratePipeline(store, timeout_s=timeout_s).run(goal)
        result = {
            "success": True, "error_code": "NONE", "message": success_message(generated),
            "path_id": generated.path_id, "path_version": generated.path_version,
            "path_sha256": generated.path_sha256, "svg_asset_id": generated.svg_asset_id,
            "preview_asset_id": generated.preview_asset_id, "segment_count": generated.segment_count,
            "cut_length_m": generated.cut_length_m, "validation_passed": True,
            "validation_report_id": generated.validation_report_id,
        }
    except PipelineError as exc:
        result = _failed_result(exc.code, exc.message, exc.svg_asset_id, exc.validation_report_id)
    except ArtifactError as exc:
        result = _failed_result("STORAGE_ERROR", f"관리 파일 저장 실패: {exc}")
    except Exception as exc:  # 예외를 성공이나 빈 경로로 바꾸지 않는다 (node.py와 같은 정책).
        print(f"경로 생성 내부 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        result = _failed_result("UNKNOWN", "경로 생성 내부 오류가 발생했습니다.")
    result = {name: result[name] for name in RESULT_FIELDS}
    store.finalize(goal, request_bytes, result)
    return result


# --------------------------------------------------------------------------- 검증
def verify_bundle(directory) -> list[str]:
    """묶음의 파일·해시·참조 관계를 검사하고 오류 문자열 목록을 돌려준다(빈 목록 = 통과).

    HMI 가져오기가 등록 전에 같은 규칙으로 확인하는 것을 전제로 한 c2_path 쪽 자체 점검이다.
    계산 의존성(cv2)이 없어도 동작한다.
    """
    directory = Path(directory)
    errors: list[str] = []

    def err(message):
        errors.append(message)

    try:
        manifest = load_manifest(directory)
    except BundleError as exc:
        return [f"{exc.code}: {exc}"]
    role = manifest.get("bundle_role")
    if role not in (ROLE_INPUT, ROLE_OUTPUT):
        err("bundle_role은 input 또는 output이어야 합니다.")
        return errors
    if manifest.get("source_mode") != "SIMULATION":
        err("source_mode는 SIMULATION이어야 합니다.")
    if not _is_uuid(manifest.get("request_id")):
        err("request_id는 정규화된 UUID여야 합니다.")

    allowed_kinds = INPUT_KINDS if role == ROLE_INPUT else OUTPUT_KINDS
    seen_ids, seen_files, by_id = set(), set(), {}
    for index, entry in enumerate(manifest["files"]):
        label = f"files[{index}]"
        if not _is_uuid(entry.get("asset_id")):
            err(f"{label}.asset_id는 정규화된 UUID여야 합니다.")
        elif entry["asset_id"] in seen_ids:
            err(f"{label}.asset_id가 중복됐습니다.")
        else:
            seen_ids.add(entry["asset_id"])
            by_id[entry["asset_id"]] = entry
        if entry.get("kind") not in allowed_kinds:
            err(f"{label}.kind={entry.get('kind')!r}는 {role} 묶음에서 허용되지 않습니다 {list(allowed_kinds)}.")
        elif entry.get("mime") not in KIND_MIMES[entry["kind"]]:
            err(f"{label}.mime={entry.get('mime')!r}는 {entry['kind']}에 허용되지 않습니다.")
        if not _is_sha(entry.get("sha256")):
            err(f"{label}.sha256는 소문자 SHA-256이어야 합니다.")
        if not _is_safe_name(entry.get("file")) or entry.get("file") in RESERVED_NAMES:
            err(f"{label}.file은 예약되지 않은 상대 파일명이어야 합니다: {entry.get('file')!r}")
            continue
        if entry["file"] in seen_files:
            err(f"{label}.file이 중복됐습니다: {entry['file']}")
        seen_files.add(entry["file"])
        _check_file(directory, entry, label, err)
        for key, kind in (("path_id", str), ("path_version", int)):
            if entry.get(key) is not None and not _type_ok(entry[key], kind):
                err(f"{label}.{key} 자료형이 올바르지 않습니다.")

    documents = manifest.get("documents")
    doc_by_kind = {}
    if not isinstance(documents, list):
        err("documents는 목록이어야 합니다.")
        documents = []
    for index, document in enumerate(documents):
        label = f"documents[{index}]"
        if not isinstance(document, dict) or not _is_safe_name(document.get("file")):
            err(f"{label} 형식이 올바르지 않습니다.")
            continue
        if document.get("mime") != JSON_MIME:
            err(f"{label}.mime은 {JSON_MIME}이어야 합니다.")
        if document["file"] in seen_files:
            err(f"{label}.file이 files와 겹칩니다: {document['file']}")
        seen_files.add(document["file"])
        doc_by_kind[document.get("kind")] = document
        _check_file(directory, document, label, err)
    required_docs = ("request",) if role == ROLE_INPUT else ("request", "result")
    for kind in required_docs:
        document = doc_by_kind.get(kind)
        if document is None or document.get("file") != f"{kind}.json":
            err(f"documents에 {kind}.json이 있어야 합니다.")

    if directory.is_dir():
        for child in sorted(directory.iterdir()):
            if child.name != MANIFEST_NAME and child.name not in seen_files:
                err(f"UNLISTED_FILE: manifest에 없는 파일입니다: {child.name}")

    request = _read_json(directory, doc_by_kind.get("request"), err)
    if isinstance(request, dict):
        if set(request) != set(GOAL_FIELDS):
            err(f"request.json 필드는 정확히 {list(GOAL_FIELDS)} 여야 합니다.")
        elif request.get("request_id") != manifest.get("request_id"):
            err("request.json의 request_id가 manifest와 다릅니다.")

    if role == ROLE_INPUT:
        _verify_input(manifest, request, by_id, err)
    else:
        _verify_output(directory, manifest, request, by_id, doc_by_kind, err)
    return errors


def _check_file(directory, entry, label, err):
    path = directory / entry["file"]
    if not path.is_file():
        err(f"{label}: 파일이 없습니다: {entry['file']}")
        return
    data = path.read_bytes()
    if not data:
        err(f"{label}: 빈 파일입니다: {entry['file']}")
    if sha256_bytes(data) != entry.get("sha256"):
        err(f"HASH_MISMATCH: {label} {entry['file']}")
    if "size_bytes" in entry and entry["size_bytes"] != len(data):
        err(f"{label}: size_bytes가 실제 크기와 다릅니다: {entry['file']}")


def _read_json(directory, document, err):
    if not isinstance(document, dict) or not _is_safe_name(document.get("file")):
        return None
    path = directory / document["file"]
    if not path.is_file():
        return None
    try:
        return loads_json(path.read_bytes())
    except (UnicodeDecodeError, ValueError):
        err(f"유효한 JSON이 아닙니다: {document['file']}")
        return None


def _entry_json(directory, entry, err):
    return _read_json(directory, entry, err) if entry else None


def _verify_input(manifest, request, by_id, err):
    if not isinstance(request, dict) or set(request) != set(GOAL_FIELDS):
        return
    for field, sha_field, kind in (("asset_id", "asset_sha256", "image"),
                                   ("profile_snapshot_id", "profile_sha256", "profile")):
        entry = by_id.get(request.get(field))
        if entry is None or entry.get("kind") != kind:
            err(f"request.{field}에 해당하는 {kind} 파일이 files에 없습니다.")
        elif entry.get("sha256") != request.get(sha_field):
            err(f"HASH_MISMATCH: request.{sha_field}가 {kind} 파일의 해시와 다릅니다.")
    kinds = sorted(e.get("kind") for e in manifest["files"])
    if kinds != ["image", "profile"]:
        err("입력 묶음에는 image와 profile이 각각 정확히 하나 있어야 합니다.")


def _verify_output(directory, manifest, request, by_id, doc_by_kind, err):
    result = _read_json(directory, doc_by_kind.get("result"), err)
    if not isinstance(result, dict):
        err("result.json을 읽을 수 없습니다.")
        return
    if set(result) != set(RESULT_FIELDS):
        err(f"result.json 필드는 GeneratePath Result 전체 {list(RESULT_FIELDS)} 여야 합니다.")
        return
    expected_types = {"success": bool, "error_code": str, "message": str, "path_id": str, "path_version": int,
                      "path_sha256": str, "svg_asset_id": str, "preview_asset_id": str, "segment_count": int,
                      "cut_length_m": (int, float), "validation_passed": bool, "validation_report_id": str}
    for name, kind in expected_types.items():
        if not _type_ok(result[name], kind):
            err(f"result.{name} 자료형이 올바르지 않습니다.")
            return
    if not math.isfinite(result["cut_length_m"]):
        err("result.cut_length_m은 유한한 수여야 합니다.")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {"asset_id", "asset_sha256", "profile_snapshot_id", "profile_sha256"}:
        err("manifest.inputs는 asset_id, asset_sha256, profile_snapshot_id, profile_sha256 이어야 합니다.")
        inputs = {}
    if isinstance(request, dict) and inputs:
        for key, value in inputs.items():
            if request.get(key) != value:
                err(f"manifest.inputs.{key}가 request.json과 다릅니다.")

    files = manifest["files"]

    def only(kind, asset_id, label, need_path_id):
        entry = by_id.get(asset_id)
        if entry is None or entry.get("kind") != kind:
            err(f"result.{label}에 해당하는 {kind} 파일이 files에 없습니다: {asset_id!r}")
            return None
        if need_path_id is not None and entry.get("path_id") != need_path_id:
            err(f"{kind} 파일의 path_id가 result.path_id와 다릅니다.")
        return entry

    if result["success"]:
        if result["error_code"] != "NONE" or result["validation_passed"] is not True:
            err("성공 result는 error_code=NONE, validation_passed=true여야 합니다.")
        if not result["path_id"] or result["path_version"] < 1 or not _is_sha(result["path_sha256"]):
            err("성공 result에는 path_id·path_version(>=1)·path_sha256가 있어야 합니다.")
            return
        if result["segment_count"] < 1 or result["cut_length_m"] <= 0:
            err("성공 result의 segment_count·cut_length_m은 양수여야 합니다.")
        paths = [e for e in files if e.get("kind") == "path" and e.get("path_id") == result["path_id"]
                 and e.get("path_version") == result["path_version"]]
        if len(paths) != 1:
            err("result의 path_id/path_version에 해당하는 path 파일이 정확히 하나가 아닙니다.")
            return
        path_entry = paths[0]
        if path_entry.get("sha256") != result["path_sha256"]:
            err("HASH_MISMATCH: result.path_sha256가 path 파일의 해시와 다릅니다.")
        summary = manifest.get("path")
        if summary != {"path_id": result["path_id"], "path_version": result["path_version"],
                       "path_sha256": result["path_sha256"], "asset_id": path_entry.get("asset_id")}:
            err("manifest.path가 result·path 파일과 다릅니다.")
        svg = only("svg", result["svg_asset_id"], "svg_asset_id", result["path_id"])
        preview = only("preview", result["preview_asset_id"], "preview_asset_id", result["path_id"])
        report_entry = only("validation", result["validation_report_id"], "validation_report_id", result["path_id"])
        if len(files) != 4 or {id(e) for e in (path_entry, svg, preview, report_entry)} != {id(e) for e in files}:
            err("성공 묶음의 files는 path·svg·preview·validation 각 하나여야 합니다.")
        for entry in files:
            if entry.get("executable") is False:
                err("성공 묶음의 파일이 executable=false로 표시돼 있습니다.")
        directory_entries = {"path": path_entry, "preview": preview, "validation": report_entry}
        contents = {k: _entry_json(directory, v, err) for k, v in directory_entries.items()}
        _verify_contents(result, inputs, manifest.get("request_id"), contents, err)
    else:
        if result["error_code"] == "NONE" or result["validation_passed"] is not False:
            err("실패 result는 error_code!=NONE, validation_passed=false여야 합니다.")
        for name, empty in (("path_id", ""), ("path_version", 0), ("path_sha256", ""),
                            ("preview_asset_id", ""), ("segment_count", 0)):
            if result[name] != empty:
                err(f"실패 result의 {name}는 {empty!r}여야 합니다.")
        if result["cut_length_m"] != 0:
            err("실패 result의 cut_length_m은 0이어야 합니다.")
        if manifest.get("path") is not None:
            err("실패 묶음의 manifest.path는 null이어야 합니다.")
        for entry in files:
            if entry.get("kind") not in ("svg", "validation") or entry.get("executable") is not False:
                err("실패 묶음에는 executable=false인 진단 svg/validation만 있어야 합니다.")
        if result["svg_asset_id"]:
            only("svg", result["svg_asset_id"], "svg_asset_id", None)
        if result["validation_report_id"]:
            only("validation", result["validation_report_id"], "validation_report_id", None)


def _verify_contents(result, inputs, request_id, contents, err):
    path, preview, report = contents["path"], contents["preview"], contents["validation"]
    if not all(isinstance(v, dict) for v in (path, preview, report)):
        err("path/preview/validation 파일을 JSON 객체로 읽을 수 없습니다.")
        return
    for label, obj in (("path", path), ("preview", preview)):
        if obj.get("path_id") != result["path_id"] or obj.get("path_version") != result["path_version"]:
            err(f"{label} 파일 안의 path_id/path_version이 result와 다릅니다.")
        if obj.get("source_mode") != "SIMULATION":
            err(f"{label} 파일의 source_mode는 SIMULATION이어야 합니다.")
    if report.get("path_id") != result["path_id"] or report.get("path_version") != result["path_version"]:
        err("validation 파일 안의 path_id/path_version이 result와 다릅니다.")
    if report.get("request_id") != request_id:
        err("validation 파일의 request_id가 manifest와 다릅니다.")
    if path.get("schema_version") != 2:
        err("path 파일의 schema_version은 2여야 합니다.")
    if path.get("input") != {"asset_id": inputs.get("asset_id"), "asset_sha256": inputs.get("asset_sha256")}:
        err("path 파일의 input이 manifest.inputs와 다릅니다.")
    config = path.get("config") if isinstance(path.get("config"), dict) else {}
    for key in ("profile_snapshot_id", "profile_sha256"):
        if config.get(key) != inputs.get(key) or preview.get(key) != inputs.get(key):
            err(f"path/preview 파일의 {key}가 manifest.inputs와 다릅니다.")
    for key in ("asset_id", "asset_sha256"):
        if preview.get(key) != inputs.get(key):
            err(f"preview 파일의 {key}가 manifest.inputs와 다릅니다.")
    if preview.get("path_sha256") != result["path_sha256"]:
        err("HASH_MISMATCH: preview 파일의 path_sha256가 result와 다릅니다.")
    validation = path.get("validation") if isinstance(path.get("validation"), dict) else {}
    if validation.get("report_id") != result["validation_report_id"] or validation.get("passed") is not True:
        err("path 파일의 validation이 result의 validation_report_id/합격 여부와 다릅니다.")
    if report.get("passed") is not True or report.get("errors"):
        err("validation 파일이 합격이 아닌데 성공 묶음으로 표시됐습니다.")
    segments = path.get("segments")
    if not isinstance(segments, list) or len(segments) != result["segment_count"]:
        err("result.segment_count가 path 파일의 segments 수와 다릅니다.")
    build = (report.get("stats") or {}).get("build") or {}
    if build.get("cut_length_m") != result["cut_length_m"]:
        err("result.cut_length_m이 validation 파일 통계와 다릅니다.")
    if isinstance(segments, list) and isinstance(preview.get("segments"), list) and len(preview["segments"]) != len(segments):
        err("preview 구간 수가 path 구간 수와 다릅니다.")


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="c2_path.bundle", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="입력 묶음으로 경로를 만들어 출력 묶음을 쓴다")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--timeout-s", type=float, default=120.0)
    check = sub.add_parser("verify", help="묶음의 파일·해시·참조 관계를 검사한다")
    check.add_argument("directory")
    args = parser.parse_args(argv)

    if args.command == "verify":
        errors = verify_bundle(args.directory)
        for message in errors:
            print(f"오류: {message}", file=sys.stderr)
        print("통과" if not errors else f"실패 ({len(errors)}건)")
        return 0 if not errors else 1
    try:
        result = run_bundle(args.input, args.output, timeout_s=args.timeout_s)
    except BundleError as exc:
        print(f"오류 {exc.code}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    errors = verify_bundle(args.output)
    for message in errors:
        print(f"묶음 검증 오류: {message}", file=sys.stderr)
    if errors:
        return 1
    return 0 if result["success"] else 2


if __name__ == "__main__":
    sys.exit(main())
