"""Loopback-only history UI; authenticated identity always comes from the session."""

import argparse
from datetime import date, datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
from threading import Lock
import time
from urllib.parse import urlsplit
from uuid import UUID

import psycopg

from history import accounts, gallery, personal, store


ASSETS = Path(__file__).with_name("web_assets")
COOKIE = "c2_history_session"
SESSION_SECONDS = 1800


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON type: {type(value).__name__}")


class HistoryServer(ThreadingHTTPServer):
    def __init__(self, address, dsn, *, session_seconds=SESSION_SECONDS):
        if address[0] != "127.0.0.1":
            raise ValueError("history web must bind to 127.0.0.1")
        super().__init__(address, HistoryHandler)
        self.dsn = dsn
        self.session_seconds = session_seconds
        self.sessions = {}
        self.session_lock = Lock()
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def identity(self, token):
        with self.session_lock:
            now = time.monotonic()
            for key, (_, expires) in list(self.sessions.items()):
                if expires <= now:
                    del self.sessions[key]
            entry = self.sessions.get(token)
            return entry[0] if entry else None


class HistoryHandler(BaseHTTPRequestHandler):
    # Requests can contain private Job IDs; avoid default URL/body logging.
    def log_message(self, format, *args):
        pass

    def _token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except (CookieError, ValueError):
            return None
        return cookie[COOKIE].value if COOKIE in cookie else None

    def _reply(self, status, body, content_type="application/json; charset=utf-8", *, cookie=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, default=json_value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie is not None:
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age={self.server.session_seconds if cookie else 0}")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._dispatch(False)

    def do_POST(self):
        self._dispatch(True)

    def _dispatch(self, mutation):
        try:
            # Also blocks DNS rebinding to this local service.
            if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
                self._reply(403, {"error": "This host is not allowed."})
                return
            path = urlsplit(self.path).path
            if mutation:
                if self.headers.get("Origin") != self.server.origin:
                    self._reply(403, {"error": "Requests from other sites are not allowed."})
                    return
                data = self._body()
                self._post(path, data)
            else:
                self._get(path)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._reply(400, {"error": "Check the input format or snapshot request."})
        except psycopg.Error:
            self._reply(503, {"error": "DB unavailable. Check the connection settings and database status."})
        except Exception as error:
            # Do not expose credentials, SQL diagnostics or archived documents.
            print(f"history web internal error: {type(error).__name__}", file=sys.stderr)
            self._reply(500, {"error": "Could not process the history request. Check the server log."})

    def _body(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("JSON required")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 8192:
            raise ValueError("body size")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("object required")
        return data

    def _user(self):
        user = self.server.identity(self._token())
        if user is None:
            self._reply(401, {"error": "Please log in. Your session may have expired."}, cookie="")
        return user

    def _get(self, path):
        assets = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"),
                  "/app.js": ("app.js", "text/javascript")}
        if path in assets:
            name, kind = assets[path]
            self._reply(200, (ASSETS / name).read_bytes(), kind + "; charset=utf-8")
            return
        if path == "/api/gallery":
            with store.connect(self.server.dsn) as connection:
                self._reply(200, dict(designs=gallery.public_designs(connection),jobs=[],
                                     queried_at=datetime.now().astimezone()))
            return
        if not (path in ("/api/me", "/api/library") or path.startswith("/api/jobs/")):
            self._reply(404, {"error": "Page not found."})
            return
        user = self._user()
        if user is None:
            return
        if path == "/api/me":
            self._reply(200, user)
            return
        with store.connect(self.server.dsn) as connection:
            if path == "/api/library":
                with connection.transaction():
                    self._reply(200, dict(**gallery.creator_library(connection,user),
                                         queried_at=datetime.now().astimezone()))
            else:
                job_path = path.removeprefix("/api/jobs/")
                summary = job_path.endswith("/summary")
                job_id = str(UUID(job_path.removesuffix("/summary") if summary else job_path))
                try:
                    result = personal.bundle(connection, job_id, user["user_id"],
                                             timeline_limit=100 if summary else None)
                except ValueError as error:
                    if str(error) != "Job unavailable to this user":
                        raise
                    self._reply(404, {"error": "This job is unavailable."})
                    return
                self._reply(200, result)

    def _post(self, path, data):
        if path == "/api/login":
            if set(data) != {"username", "password"}:
                raise ValueError("login fields")
            with store.connect(self.server.dsn) as connection:
                user = accounts.authenticate(connection, data["username"], data["password"])
            if user is None:
                self._reply(401, {"error": "Check your username or password."})
                return
            self.server.identity(None)  # Remove expired entries before issuing a session.
            token = secrets.token_urlsafe(32)
            with self.server.session_lock:
                self.server.sessions.pop(self._token(), None)
                self.server.sessions[token] = (user, time.monotonic() + self.server.session_seconds)
            self._reply(200, user, cookie=token)
        elif path == "/api/logout":
            with self.server.session_lock:
                self.server.sessions.pop(self._token(), None)
            self._reply(200, {"ok": True}, cookie="")
        elif path.startswith("/api/designs/") and path.endswith("/publication"):
            user = self._user()
            if user is None:
                return
            if set(data) != {"published"}:
                raise ValueError("publication fields")
            _, _, _, job, version, _ = path.split("/")
            job_id = str(UUID(job))
            with store.connect(self.server.dsn) as connection:
                try:
                    result = gallery.set_publication(connection,job_id,int(version),user["user_id"],data["published"])
                except ValueError as error:
                    if str(error) not in ("Job unavailable to this user", "Design unavailable to this user"):
                        raise
                    self._reply(404, {"error": "This design is unavailable."})
                    return
            self._reply(200, result)
        elif path.startswith("/api/jobs/") and path.endswith("/save"):
            user = self._user()
            if user is None:
                return
            if set(data) != {"save_key"}:
                raise ValueError("save fields")
            job_id = str(UUID(path[len("/api/jobs/"):-len("/save")]))
            with store.connect(self.server.dsn) as connection:
                try:
                    receipt = personal.save_job(connection, job_id, user["user_id"], data["save_key"])
                except ValueError as error:
                    if str(error) != "Job unavailable to this user":
                        raise
                    self._reply(404, {"error": "This job is unavailable."})
                    return
            self._reply(200, receipt)
        else:
            self._reply(404, {"error": "Unsupported request."})


def main():
    parser = argparse.ArgumentParser(description="C-2 local personal history web")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not os.environ.get("HISTORY_DATABASE_DSN") and not os.environ.get("PGHOST"):
        parser.error("set HISTORY_DATABASE_DSN or PGHOST/PGDATABASE/PGUSER/PGPASSWORD")
    dsn = os.environ.get("HISTORY_DATABASE_DSN", "")
    try:
        with store.connect(dsn) as connection:
            connection.execute("SELECT user_id FROM c2_history.users LIMIT 0")
            connection.execute("SELECT design_version FROM c2_history.design_publications LIMIT 0")
        with HistoryServer(("127.0.0.1", args.port), dsn) as server:
            print(f"C-2 history web: {server.origin}", flush=True)
            server.serve_forever()
    except (psycopg.Error, OSError):
        parser.exit(1, "history web startup failed: check DB/schema and local port\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
