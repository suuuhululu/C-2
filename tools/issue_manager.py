"""Manage team issues through GitHub REST; never execute issue or comment text."""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
AREAS = {"mini", "main", "common"}
ROLES = {"general", "ros", "robot", "gripper", "hmi", "validation"}
KINDS = {"implementation", "bug", "docs", "hardware-validation"}
STATUSES = {"todo", "doing", "review", "blocked", "done"}
STATE_PATTERN = re.compile(r"<!-- c2-state:(\{[^\n]*\}) -->")
BOT = "github-actions[bot]"
LABELS = {
    **{f"area:{x}": "1d76db" for x in AREAS},
    **{f"role:{x}": "5319e7" for x in ROLES},
    **{f"type:{x}": "0075ca" for x in KINDS},
    **{f"status:{x}": "c5def5" for x in STATUSES},
    "automation:managed": "0e8a16",
    "automation:paused": "eeeeee",
    "assignment:needed": "fbca04",
    "schedule:missing": "fbca04",
    "schedule:due-soon": "fbca04",
    "schedule:overdue": "d93f0b",
    "schedule:change-requested": "d4c5f9",
    "schedule:milestone-conflict": "b60205",
}


def validate_config(config):
    if config.get("repository") != "suuuhululu/C-2":
        raise ValueError("대상 저장소가 C-2와 다릅니다.")
    if type(config.get("enabled")) is not bool or config.get("timezone") != "Asia/Seoul":
        raise ValueError("enabled는 bool, timezone은 Asia/Seoul이어야 합니다.")
    logins = set()
    for member in config["members"]:
        login = member["login"]
        if login is not None:
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login):
                raise ValueError("login에는 이메일이나 @ 없이 GitHub 아이디를 입력합니다.")
            if login.lower() in logins:
                raise ValueError("중복 GitHub 아이디입니다.")
            logins.add(login.lower())
        if type(member["active"]) is not bool or type(member["leader"]) is not bool:
            raise ValueError("active와 leader는 bool이어야 합니다.")
        if member["active"] and not login:
            raise ValueError("활성 팀원에게 GitHub 아이디가 필요합니다.")
        if not member["roles"] or not set(member["roles"]) <= ROLES:
            raise ValueError("지원하지 않는 담당 분야입니다.")
        if type(member["max_open_issues"]) is not int or member["max_open_issues"] < 1:
            raise ValueError("max_open_issues는 양의 정수여야 합니다.")
    return config


def parse_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
    return date.fromisoformat(value)


def form_fields(body):
    parts = re.split(r"^### (.+?)\s*$", body or "", flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def initial_state(body):
    fields = form_fields(body)
    area, role, kind = (fields.get(x) for x in ("프로젝트", "담당 분야", "작업 종류"))
    if area not in AREAS or role not in ROLES or kind not in KINDS:
        return None
    due = fields.get("최초 마감일", "")
    try:
        parse_date(due)
    except ValueError:
        due = None
    return {"version": 1, "area": area, "role": role, "kind": kind, "due": due,
            "status": "todo", "cursor": 0, "pending": None, "last_change": "최초 등록"}


def bot_comment(comment):
    return comment["user"]["login"] == BOT and comment["user"].get("type") == "Bot"


def saved_state(comments):
    for comment in comments:
        if bot_comment(comment):
            match = STATE_PATTERN.search(comment.get("body") or "")
            if match:
                state = json.loads(match[1])
                if state["version"] != 1 or state["status"] not in STATUSES:
                    raise ValueError("운영 현황 댓글의 형식 확인이 필요합니다.")
                return comment, state
    return None, None


def milestone_date(issue, timezone):
    value = (issue.get("milestone") or {}).get("due_on")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone).date() if value else None


def schedule_labels(state, today, milestone=None):
    labels = set()
    if not state["due"]:
        labels.add("schedule:missing")
    else:
        due = parse_date(state["due"])
        if due < today:
            labels.add("schedule:overdue")
        elif (due - today).days <= 1:
            labels.add("schedule:due-soon")
        if milestone and due > milestone:
            labels.add("schedule:milestone-conflict")
    if state["pending"]:
        labels.add("schedule:change-requested")
    return labels


def select_assignee(members, role, loads):
    candidates = [m for m in members if m["active"] and m["login"]
                  and (role == "general" or role in m["roles"])
                  and loads[m["login"].lower()] < m["max_open_issues"]]
    return min(candidates, key=lambda m: (loads[m["login"].lower()], m["login"].lower()))["login"] if candidates else None


def clean_text(value):
    # Escape user-provided prose and neutralize mentions in the bot's copy.
    return html.escape(value).replace("@", "＠").replace("|", "&#124;").replace("\n", " ")


def process_command(state, comment, *, leader, owner, today, milestone=None, busy=False):
    """Return a new state and audit text. No external writes or issue closure."""
    new = deepcopy(state)
    raw = (comment.get("body") or "").strip()
    actor = comment["user"]["login"]
    if not raw.startswith("/team "):
        return new, None
    if not (leader or owner):
        return new, "거절: 현재 담당자 또는 팀장·저장소 관리자만 명령을 사용할 수 있습니다."
    parts = raw.split(maxsplit=3)
    command = parts[1]
    if command in {"start", "review", "todo", "block"}:
        if command != "block" and len(parts) != 2:
            return new, "거절: 상태 명령은 `/team start`, `/team review`, `/team todo`입니다."
        if command == "start" and busy:
            return new, "거절: 같은 담당자의 진행 중 Issue가 있습니다. 완료·검토·대기 상태를 먼저 정리하세요."
        if command == "block" and len(parts) < 3:
            return new, "거절: `/team block 막힌 이유와 필요한 도움`으로 작성하세요."
        new["status"] = {"start": "doing", "review": "review", "todo": "todo", "block": "blocked"}[command]
        return new, f"상태: {state['status']} → {new['status']} / {clean_text(raw)}"
    if command == "request-date":
        if len(parts) != 4 or len(parts[3]) < 3 or len(parts[3]) > 500 or "\n" in raw:
            return new, "거절: `/team request-date YYYY-MM-DD 변경 이유`를 한 줄로 작성하세요."
        try:
            requested = parse_date(parts[2])
        except ValueError:
            return new, "거절: 유효한 YYYY-MM-DD 날짜가 필요합니다."
        if requested < today or (milestone and requested > milestone):
            return new, "거절: 과거 날짜나 연결된 마일스톤 마감 이후로 변경할 수 없습니다."
        new["pending"] = {"id": comment["id"], "due": parts[2], "reason": parts[3], "by": actor}
        return new, f"변경 요청 접수: {parts[2]}. 팀장은 `/team approve-date {comment['id']}` 또는 `/team reject-date {comment['id']} 이유`로 처리하세요. 이전 미승인 요청은 대체됩니다."
    if command in {"approve-date", "reject-date"}:
        if not leader:
            return new, "거절: 일정 승인·반려는 팀장·저장소 관리자만 가능합니다."
        if len(parts) < 3 or not parts[2].isdigit():
            return new, "거절: 봇이 안내한 요청 번호를 입력하세요."
        pending = state["pending"]
        if not pending or pending["id"] != int(parts[2]):
            return new, "거절: 현재 대기 중인 요청 번호와 다릅니다."
        if command == "reject-date":
            if len(parts) != 4 or len(parts[3]) < 3:
                return new, "거절: 반려 이유를 함께 작성하세요."
            new["pending"] = None
            return new, f"일정 요청 {pending['id']} 반려: {clean_text(parts[3])}"
        if len(parts) != 3:
            return new, "거절: `/team approve-date 요청번호`로 작성하세요."
        requested = parse_date(pending["due"])
        if requested < today or (milestone and requested > milestone):
            return new, "거절: 요청 후 날짜 또는 마일스톤이 변경되었습니다. 새 일정을 요청하세요."
        new["due"] = pending["due"]
        new["pending"] = None
        new["last_change"] = f"{state['due'] or '미정'} → {new['due']} / 승인자 {actor} / 요청 {pending['id']}"
        return new, f"일정 승인: {new['last_change']} / 이유: {clean_text(pending['reason'])}"
    return new, "거절: 지원 명령은 start, review, todo, block, request-date, approve-date, reject-date입니다."


class API:
    def __init__(self, repository, token):
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token

    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10", "Content-Type": "application/json",
            "User-Agent": "C-2-issue-management"})
        # Mutating requests are not blindly retried after an uncertain response.
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def pages(self, path, **query):
        page = 1
        results = []
        while True:
            batch = self.call("GET", path + "?" + urlencode({**query, "per_page": 100, "page": page}))
            results.extend(batch)
            if len(batch) < 100:
                return results
            page += 1


class Manager:
    def __init__(self, api, config, today=None):
        self.api, self.config = api, validate_config(config)
        self.tz = ZoneInfo(config["timezone"])
        self.today = today or datetime.now(self.tz).date()
        self.permissions = {}
        self.members = {m["login"].lower(): m for m in config["members"] if m["login"]}

    def permission(self, login):
        if login.lower() not in self.permissions:
            try:
                result = self.api.call("GET", f"/collaborators/{quote(login, safe='')}/permission")
                self.permissions[login.lower()] = result["permission"]
            except HTTPError as error:
                if error.code != 404:
                    raise
                self.permissions[login.lower()] = "none"
        return self.permissions[login.lower()]

    def leader(self, login):
        permission = self.permission(login)
        member = self.members.get(login.lower(), {})
        return permission == "admin" or (permission == "write" and member.get("active") and member.get("leader"))

    def post_once(self, issue, comments, key, message):
        marker = f"<!-- c2-notice:{key} -->"
        if not any(bot_comment(c) and marker in (c.get("body") or "") for c in comments):
            created = self.api.call("POST", f"/issues/{issue['number']}/comments", {"body": f"{marker}\n{message}"})
            comments.append(created)

    def write_state(self, issue, comments, state):
        pending = state["pending"]
        request = f"{pending['due']} / 요청 번호 {pending['id']} / {clean_text(pending['reason'])}" if pending else "없음"
        assignees = ", ".join("@" + a["login"] for a in issue["assignees"]) or "배정 대기"
        # ASCII JSON prevents user text from terminating the hidden HTML comment.
        encoded = json.dumps(state, ensure_ascii=True, separators=(",", ":"))
        for literal, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("@", "\\u0040"), ("--", "\\u002d\\u002d")):
            encoded = encoded.replace(literal, escaped)
        body = (f"<!-- c2-state:{encoded} -->\n"
                "### 팀 작업 운영 현황\n\n"
                f"- 담당자: {assignees}\n- 상태: `{state['status']}`\n"
                f"- 확정 마감: **{state['due'] or '미정'}** (Asia/Seoul, 해당 날짜 종료까지)\n"
                f"- 일정 변경 대기: {request}\n- 최근 일정 변경: {clean_text(state['last_change'])}\n\n"
                "일정의 기준은 이 댓글입니다. 본문의 최초 마감일을 수정해도 확정 일정은 바뀌지 않습니다.\n"
                "시작 `/team start` · 검토 `/team review` · 대기 `/team todo` · 막힘 `/team block 이유`\n"
                "일정 요청 `/team request-date YYYY-MM-DD 이유` · 팀장 승인 `/team approve-date 요청번호`\n"
                "구현 병합과 실기 검증은 별도로 완료 처리합니다.")
        current, _ = saved_state(comments)
        if current and current["body"] != body:
            self.api.call("PATCH", f"/issues/comments/{current['id']}", {"body": body})
            current["body"] = body
        elif not current:
            comments.append(self.api.call("POST", f"/issues/{issue['number']}/comments", {"body": body}))

    def sync_labels(self, issue, desired):
        # Touch only labels owned by this automation, preserving manual labels.
        current = {x["name"] for x in issue["labels"]}
        if desired - current:
            self.api.call("POST", f"/issues/{issue['number']}/labels", {"labels": sorted(desired - current)})
        for label in (current & (LABELS.keys() - {"automation:paused"})) - desired:
            self.api.call("DELETE", f"/issues/{issue['number']}/labels/{quote(label, safe='')}")
        issue["labels"] = [{"name": name} for name in (current - LABELS.keys()) | desired]

    def run(self):
        if not self.config["enabled"]:
            print("Issue 자동화가 설정에서 일시 중지되었습니다.")
            return
        existing = {x["name"] for x in self.api.pages("/labels")}
        for label, color in LABELS.items():
            if label not in existing:
                self.api.call("POST", "/labels", {"name": label, "color": color})
        # Full reconciliation also recovers events replaced in the concurrency queue.
        issues = [i for i in self.api.pages("/issues", state="all", sort="created", direction="asc") if "pull_request" not in i]
        loads = Counter(a["login"].lower() for i in issues if i["state"] == "open" for a in i["assignees"])
        eligible = []
        for member in self.config["members"]:
            if member["active"] and member["login"] and self.permission(member["login"]) in {"write", "admin"}:
                try:
                    self.api.call("GET", f"/assignees/{quote(member['login'], safe='')}")
                    eligible.append(member)
                except HTTPError as error:
                    if error.code != 404:
                        raise
        for snapshot in issues:
            issue = self.api.call("GET", f"/issues/{snapshot['number']}")
            if "automation:paused" in {x["name"] for x in issue["labels"]}:
                continue
            comments = self.api.pages(f"/issues/{issue['number']}/comments")
            _, state = saved_state(comments)
            if not state:
                if issue["state"] != "open" or self.permission(issue["user"]["login"]) not in {"write", "admin"}:
                    continue
                state = initial_state(issue.get("body"))
                if not state:
                    continue
                self.write_state(issue, comments, state)
            if state.get("receipt"):
                receipt = state["receipt"]
                self.post_once(issue, comments, f"command-{receipt['id']}", receipt["message"])
            if issue["state"] == "open":
                fields = initial_state(issue.get("body"))
                if fields:
                    for key in ("area", "role", "kind"):
                        state[key] = fields[key]
                if state["status"] == "done":
                    state["status"] = "todo"
                if not issue["assignees"]:
                    login = select_assignee(eligible, state["role"], loads)
                    if login:
                        result = self.api.call("POST", f"/issues/{issue['number']}/assignees", {"assignees": [login]})
                        issue["assignees"] = result["assignees"]
                        if login.lower() not in {a["login"].lower() for a in issue["assignees"]}:
                            raise RuntimeError("담당자 등록 결과가 일치하지 않습니다. GitHub 권한을 확인하세요.")
                        loads[login.lower()] += 1
                for comment in sorted(list(comments), key=lambda c: c["id"]):
                    if comment["id"] <= state["cursor"] or bot_comment(comment) or not (comment.get("body") or "").startswith("/team "):
                        continue
                    actor = comment["user"]["login"]
                    if self.permission(actor) not in {"write", "admin"}:
                        continue
                    owners = {a["login"].lower() for a in issue["assignees"]}
                    busy = any(i["number"] != issue["number"] and i["state"] == "open"
                               and "status:doing" in {x["name"] for x in i["labels"]}
                               and owners & {a["login"].lower() for a in i["assignees"]} for i in issues)
                    state, message = process_command(state, comment, leader=self.leader(actor),
                                                     owner=actor.lower() in owners, today=self.today,
                                                     milestone=milestone_date(issue, self.tz), busy=busy)
                    state["cursor"] = comment["id"]
                    # Persist state first; the outcome is recoverable if the notice fails.
                    state["receipt"] = {"id": comment["id"], "message": message}
                    self.write_state(issue, comments, state)
                    self.post_once(issue, comments, f"command-{comment['id']}", message)
            else:
                state["status"] = "done"
                # Commands written while closed are not replayed on reopening.
                state["cursor"] = max([state["cursor"]] + [c["id"] for c in comments])
                state["pending"] = None
            if state.get("receipt"):
                receipt = state["receipt"]
                self.post_once(issue, comments, f"command-{receipt['id']}", receipt["message"])
            desired = {"automation:managed", f"area:{state['area']}", f"role:{state['role']}",
                       f"type:{state['kind']}", f"status:{state['status']}"}
            if issue["state"] == "open":
                if not issue["assignees"]:
                    desired.add("assignment:needed")
                timing = schedule_labels(state, self.today, milestone_date(issue, self.tz))
                desired |= timing
                for label in timing - {"schedule:change-requested"}:
                    fingerprint = hashlib.sha256(f"{label}:{state['due']}:{milestone_date(issue, self.tz)}".encode()).hexdigest()[:16]
                    self.post_once(issue, comments, fingerprint,
                                   f"일정 확인: `{label}` · 확정 마감 {state['due'] or '미정'} (한국 날짜). 담당자는 진행 상황을 남기고 필요하면 일정 변경을 요청하세요. 마감은 자동 연장되지 않습니다.")
            self.write_state(issue, comments, state)
            self.sync_labels(issue, desired)
            snapshot.update(issue)
        print(f"Issue {len(issues)}개 확인. 로봇 실행·코드 변경·PR 병합은 수행하지 않습니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="GitHub에서 Issue 변경 실행")
    args = parser.parse_args()
    config = validate_config(json.loads((ROOT / ".github/team.json").read_text()))
    if not args.apply:
        ready = sum(bool(m["login"] and m["active"]) for m in config["members"])
        print(f"설정 형식 정상. 활성 계정 {ready}/{len(config['members'])}. 네트워크·변경 없음.")
        return
    if os.environ.get("GITHUB_REPOSITORY") != config["repository"]:
        raise ValueError("GITHUB_REPOSITORY와 설정 저장소가 일치해야 합니다.")
    Manager(API(config["repository"], os.environ["GITHUB_TOKEN"]), config).run()


if __name__ == "__main__":
    main()
