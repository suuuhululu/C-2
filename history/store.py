"""A file import is one transaction, independent of the running process."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from history.records import InputError, adopted_artifacts, read_source


SCHEMA = Path(__file__).with_name("schema.sql")


def connect(dsn: str):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=5)


def initialize(connection) -> None:
    with connection.transaction():
        connection.execute(SCHEMA.read_text(encoding="utf-8"))


def _save_artifact(connection, item: dict, event_id: int) -> None:
    identity = (item["job_id"], item["kind"], item["key"])
    row = connection.execute("""
        INSERT INTO c2_history.artifacts
        (job_id, kind, artifact_key, adoption_event_id, design_version,
         plan_id, base_current_revision, document)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (job_id,kind,artifact_key) DO NOTHING RETURNING artifact_key
        """, (*identity, event_id, item["design_version"], item["plan_id"],
              item["base_current_revision"], Jsonb(item["document"]))).fetchone()
    if row is None:
        old = connection.execute("""SELECT document FROM c2_history.artifacts
            WHERE job_id=%s AND kind=%s AND artifact_key=%s""", identity).fetchone()
        if old["document"] != item["document"]:
            raise ValueError(f"immutable {item['kind']} conflict: {item['key']}")


def _save_event(connection, record: dict) -> bool:
    doc = record["document"]
    existing = connection.execute("""SELECT line_sha256, raw_line FROM c2_history.events
        WHERE source_key=%s AND line_number=%s""", (record["source"], record["line"])).fetchone()
    if existing is not None:
        if existing["line_sha256"] != record["digest"] or existing["raw_line"] != record["raw"]:
            raise ValueError("previously imported line changed; use a new source for a distinct log")
        return False
    connection.execute("INSERT INTO c2_history.jobs VALUES (%s) ON CONFLICT DO NOTHING", (doc["job_id"],))
    event = connection.execute("""INSERT INTO c2_history.events
        (source_key,line_number,line_sha256,raw_line,occurred_at,job_id,plan_id,step_id,
         request_id,event,outcome,reason,design_version,base_current_revision,observation_seq,document)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (record["source"], record["line"], record["digest"], record["raw"], record["timestamp"],
         doc["job_id"], doc["plan_id"], doc["step_id"], doc["request_id"], doc["event"],
         record["outcome"], doc["reason"], record["design_version"], record["base_current_revision"],
         record["observation_seq"], Jsonb(doc))).fetchone()
    for item in adopted_artifacts(record):
        _save_artifact(connection, item, event["id"])
    return True


def ingest(connection, path: Path, source: str) -> dict:
    inserted = 0
    with connection.transaction():
        # Serialize imports of the same source, including concurrent app invocations.
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (source,))
        records, pending = read_source(path, source)
        connection.execute("INSERT INTO c2_history.sources VALUES (%s,0) ON CONFLICT DO NOTHING", (source,))
        previous = connection.execute("SELECT last_line FROM c2_history.sources WHERE source_key=%s",
                                      (source,)).fetchone()["last_line"]
        if len(records) < previous:
            raise InputError(f"{source}:{len(records)+1}: previously imported source truncated")
        for record in records:
            try:
                inserted += _save_event(connection, record)
            except (ValueError, psycopg.Error) as error:
                # Driver diagnostics never include connection strings or raw input values.
                detail = str(error) if isinstance(error, ValueError) else f"DB write failed ({error.sqlstate})"
                raise InputError(f"{source}:{record['line']}: {detail}") from error
        connection.execute("UPDATE c2_history.sources SET last_line=%s WHERE source_key=%s", (len(records), source))
    return dict(source=source, inserted=inserted, skipped=len(records)-inserted, pending_line=pending)


def timeline(connection, job_id: str | None = None) -> list[dict]:
    clause, params = ("", ()) if job_id is None else ("WHERE job_id=%s", (job_id,))
    return connection.execute(f"""SELECT source_key, line_number, occurred_at,
        job_id::text, plan_id, step_id, request_id, event, outcome, reason,
        design_version, base_current_revision, observation_seq, document, raw_line
        FROM c2_history.events {clause}
        ORDER BY occurred_at, source_key, line_number""", params).fetchall()


def artifacts(connection, job_id: str) -> list[dict]:
    return connection.execute("""SELECT a.job_id::text, a.kind, a.artifact_key, a.design_version,
        a.plan_id, a.base_current_revision, a.document, e.occurred_at,
        e.source_key, e.line_number FROM c2_history.artifacts a
        JOIN c2_history.events e ON e.id=a.adoption_event_id WHERE a.job_id=%s
        ORDER BY e.occurred_at,e.source_key,e.line_number,a.kind""", (job_id,)).fetchall()
