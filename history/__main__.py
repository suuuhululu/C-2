"""Container/local commands for importing and querying offline history."""

import argparse
from getpass import getpass
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg

from history import report, store
from history.records import InputError


def _job(value):
    try:
        return str(UUID(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected Job UUID") from error


def _json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot encode {type(value).__name__}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create history schema, no state restoration")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("paths", nargs="+", type=Path)
    ingest.add_argument("--source-root", required=True, type=Path,
                        help="stable root; relative paths identify logs across host/container")
    commands.add_parser("jobs")
    commands.add_parser("users", help="DB-local account identities, no password hashes")
    create = commands.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("display_name")
    create.add_argument("--password-stdin", action="store_true")
    check = commands.add_parser("check-user", help="check credentials, no session created")
    check.add_argument("username")
    check.add_argument("--password-stdin", action="store_true")
    timeline = commands.add_parser("timeline")
    timeline.add_argument("job_id", type=_job)
    reasons = commands.add_parser("reasons")
    reasons.add_argument("--job-id", type=_job)
    artifacts = commands.add_parser("artifacts")
    artifacts.add_argument("job_id", type=_job)
    for name in ("designs", "currents", "plans", "hri"):
        query = commands.add_parser(name, help="recorded history only, no live state query")
        query.add_argument("job_id", type=_job)
    export = commands.add_parser("report")
    export.add_argument("job_id", type=_job)
    export.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if not os.environ.get("HISTORY_DATABASE_DSN") and not os.environ.get("PGHOST"):
            raise ValueError("set HISTORY_DATABASE_DSN or PGHOST/PGDATABASE/PGUSER/PGPASSWORD")
        with store.connect(os.environ.get("HISTORY_DATABASE_DSN", "")) as connection:
            if args.command == "init":
                store.initialize(connection)
                result = dict(schema="c2_history", initialized=True)
            elif args.command in ("users", "create-user", "check-user"):
                from history import accounts
                if args.command == "users":
                    result = accounts.list_users(connection)
                else:
                    if args.password_stdin:
                        line = sys.stdin.readline()
                        password = line[:-1] if line.endswith("\n") else line
                    else:
                        if not sys.stdin.isatty():
                            raise ValueError("interactive password input requires a terminal; use --password-stdin")
                        password = getpass("Password: ")
                        if args.command == "create-user" and password != getpass("Confirm password: "):
                            raise ValueError("password confirmation differs")
                    if args.command == "create-user":
                        result = accounts.create_user(connection,args.username,args.display_name,password)
                    else:
                        result = accounts.authenticate(connection,args.username,password)
                        if result is None:
                            raise ValueError("invalid username or password")
            elif args.command == "ingest":
                root = args.source_root.resolve(strict=True)
                result = []
                for path in args.paths:
                    resolved = path.resolve(strict=True)
                    try:
                        source = resolved.relative_to(root).as_posix()
                    except ValueError as error:
                        raise ValueError(f"{path}: outside source root") from error
                    imported = store.ingest(connection, resolved, source)
                    result.append(imported)
                    # Previous files are committed even if a later file fails.
                    print(json.dumps(imported, ensure_ascii=False), flush=True)
                return 0
            elif args.command == "artifacts":
                result = store.artifacts(connection, args.job_id)
            else:
                rows = store.timeline(connection, getattr(args, "job_id", None))
                if args.command == "jobs":
                    result = report.jobs(rows)
                elif args.command == "timeline":
                    result = rows
                elif args.command == "reasons":
                    result = report.reason_counts(rows)
                elif args.command in ("designs", "currents", "plans", "hri"):
                    result = getattr(report, args.command)(rows)
                else:
                    result = dict(jobs=report.jobs(rows), timeline=rows,
                                  reasons=report.reason_counts(rows), episodes=report.episodes(rows),
                                  durations=report.durations(rows), artifacts=store.artifacts(connection,args.job_id))
                    result.update(designs=report.designs(rows), currents=report.currents(rows),
                                  plans=report.plans(rows), hri=report.hri(rows))
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json)+"\n",
                                           encoding="utf-8")
                    print(json.dumps(dict(report=str(args.output)), ensure_ascii=False))
                    return 0
            print(json.dumps(result, ensure_ascii=False, indent=2, default=_json))
        return 0
    except (InputError, OSError, ValueError) as error:
        print(f"history: {error}", file=sys.stderr)
        return 1
    except psycopg.Error as error:
        print(f"history: DB connection/query failed ({type(error).__name__}, SQLSTATE={error.sqlstate}); "
              "check database service, credentials and schema; original logs retained", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
