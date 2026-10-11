"""DB-local owner binding, authenticated-identity queries and storage-only receipts."""

import hashlib
import json

from history import report, store
from history.final_mvp import checks, completion


def bind_job(connection, job_id: str, username: str, reason: str) -> dict:
    """Privileged local operator action, never an endpoint for self-claiming a Job."""
    if not isinstance(reason, str) or not reason.strip() or "\0" in reason:
        raise ValueError("owner binding reason: nonempty text required")
    with connection.transaction():
        user = connection.execute("SELECT user_id::text FROM c2_history.users WHERE username=%s", (username,)).fetchone()
        if user is None:
            raise ValueError("owner account not found")
        job = connection.execute("SELECT owner_user_id::text FROM c2_history.jobs WHERE job_id=%s FOR UPDATE",
                                 (job_id,)).fetchone()
        if job is None:
            raise ValueError("Job not found")
        if job["owner_user_id"] not in (None, user["user_id"]):
            raise ValueError("Job already has another owner; binding retained")
        if job["owner_user_id"] is None:
            connection.execute("""UPDATE c2_history.jobs SET owner_user_id=%s,
                owner_bound_at=CURRENT_TIMESTAMP, owner_binding_reason=%s WHERE job_id=%s""",
                (user["user_id"], reason, job_id))
        return connection.execute("""SELECT job_id::text, owner_user_id::text,
            owner_bound_at, owner_binding_reason FROM c2_history.jobs WHERE job_id=%s""", (job_id,)).fetchone()


def _owned_job(connection, job_id, user_id, *, lock="SHARE"):
    # user_id comes from successful authentication, never from a submitted ownership field.
    row = connection.execute(f"""SELECT job_id::text, owner_user_id::text FROM c2_history.jobs
        WHERE job_id=%s AND owner_user_id=%s FOR {lock}""", (job_id,user_id)).fetchone()
    if row is None:
        raise ValueError("Job unavailable to this user")
    return row


def user_rows(connection, user_id: str) -> list[dict]:
    return store.timeline(connection, owner_user_id=user_id)


def _manifest(connection, job_id):
    rows = connection.execute("""SELECT e.source_key,e.line_number,e.line_sha256,s.contract
        FROM c2_history.events e JOIN c2_history.sources s USING(source_key)
        WHERE e.job_id=%s ORDER BY e.source_key,e.line_number""", (job_id,)).fetchall()
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return digest, len(rows)


def storage_status(connection, job_id: str) -> dict:
    digest, count = _manifest(connection, job_id)
    receipt = connection.execute("""SELECT save_key,job_id::text,owner_user_id::text,
        manifest_sha256,event_count,saved_at FROM c2_history.save_receipts
        WHERE job_id=%s ORDER BY (manifest_sha256=%s) DESC,saved_at DESC,save_key DESC LIMIT 1""",
        (job_id,digest)).fetchone()
    saved = receipt is not None and receipt["manifest_sha256"] == digest
    return dict(status="SAVED" if saved else "PENDING", imported_event_count=count,
                receipt=receipt, web_reflection="NOT_CONNECTED")


def save_job(connection, job_id: str, user_id: str, save_key: str) -> dict:
    """An immutable receipt for the already imported snapshot, including failed/unfinished Jobs."""
    if not isinstance(save_key, str) or not save_key or save_key != save_key.strip() or "\0" in save_key:
        raise ValueError("save_key: nonempty text without surrounding whitespace required")
    with connection.transaction():
        _owned_job(connection,job_id,user_id,lock="UPDATE")
        digest, count = _manifest(connection,job_id)
        if not count:
            raise ValueError("cannot save an empty Job")
        connection.execute("""INSERT INTO c2_history.save_receipts
            (save_key,job_id,owner_user_id,manifest_sha256,event_count) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(save_key) DO NOTHING""", (save_key,job_id,user_id,digest,count))
        receipt = connection.execute("""SELECT save_key,job_id::text,owner_user_id::text,
            manifest_sha256,event_count,saved_at FROM c2_history.save_receipts WHERE save_key=%s""", (save_key,)).fetchone()
        if (receipt["job_id"],receipt["owner_user_id"],receipt["manifest_sha256"]) != (job_id,user_id,digest):
            raise ValueError("save_key content conflict; existing receipt retained; use a new key for a new snapshot")
        return receipt


def bundle(connection, job_id: str, user_id: str) -> dict:
    with connection.transaction():
        owner = _owned_job(connection,job_id,user_id)
        rows = store.timeline(connection,job_id)
        result = dict(owner=owner, jobs=report.jobs(rows), timeline=rows,
            artifacts=store.artifacts(connection,job_id), checks=checks(rows),
            completion=completion(rows), storage=storage_status(connection,job_id))
        result.update({name:getattr(report,name)(rows) for name in
                       ("designs","plans","currents","hri","reason_counts","durations","episodes")})
        return result
