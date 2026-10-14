"""Creator-controlled design publication, separate from private Job history."""

from psycopg.types.json import Jsonb

from history import personal, report, store


def public_designs(connection) -> list[dict]:
    # Explicit projection keeps source paths, dialogue and private Job events out.
    rows = connection.execute("""SELECT p.job_id::text,p.design_version,p.design,p.published_at,
        u.display_name AS creator_name,u.username AS creator_handle FROM c2_history.design_publications p
        JOIN c2_history.jobs j USING(job_id)
        JOIN c2_history.users u ON u.user_id=j.owner_user_id
        WHERE p.is_published ORDER BY p.published_at,p.job_id,p.design_version""").fetchall()
    for row in rows:
        row["creator"] = dict(display_name=row.pop("creator_name"),username=row.pop("creator_handle"))
    return rows


def creator_library(connection, user) -> dict:
    with connection.transaction():
        rows = personal.user_rows(connection,user["user_id"],events=personal.DESIGN_VIEW_EVENTS)
        states = connection.execute("""SELECT p.job_id::text,p.design_version,p.is_published
            FROM c2_history.design_publications p JOIN c2_history.jobs j USING(job_id)
            WHERE j.owner_user_id=%s""", (user["user_id"],)).fetchall()
        published = {(row["job_id"],row["design_version"]):row["is_published"] for row in states}
        designs = [{key:design[key] for key in ("job_id","design_version","design","adopted_at")}
                   for design in report.designs(rows)]
        for design in designs:
            design["creator"] = dict(display_name=user["display_name"],username=user["username"])
            design["published"] = published.get((design["job_id"],design["design_version"]),False)
        jobs = report.jobs(rows)
        for job in jobs:
            job.update(store.job_counts(connection,job["job_id"]))
        return dict(jobs=jobs,designs=designs)


def set_publication(connection, job_id: str, version: int, user_id: str, published: bool) -> dict:
    if type(published) is not bool or type(version) is not int or version < 1:
        raise ValueError("invalid publication fields")
    with connection.transaction():
        personal._owned_job(connection,job_id,user_id,lock="UPDATE")
        design = next((item["design"] for item in report.designs(store.timeline(connection,job_id,events=("PLAN_ADOPTED",)))
                       if item["design_version"] == version),None)
        if design is None:
            raise ValueError("Design unavailable to this user")
        # Publishing captures this version only; later imports never publish new versions.
        row = connection.execute("""INSERT INTO c2_history.design_publications
            (job_id,design_version,design,is_published) VALUES (%s,%s,%s,%s)
            ON CONFLICT(job_id,design_version) DO UPDATE SET
            design=EXCLUDED.design,is_published=EXCLUDED.is_published,
            published_at=CASE WHEN EXCLUDED.is_published AND NOT design_publications.is_published
                THEN CURRENT_TIMESTAMP ELSE design_publications.published_at END
            RETURNING design_version,is_published AS published,published_at""",
            (job_id,version,Jsonb(design),published)).fetchone()
        return row
