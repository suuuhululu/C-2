"""Behavioral tests using an in-memory GitHub; no network, tokens or commits."""

from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from issue_manager import (BOT, Manager, initial_state, milestone_date, parse_date,
                           process_command, saved_state, schedule_labels,
                           select_assignee, validate_config)


TODAY = date(2026, 9, 15)
BODY = """### 프로젝트

main

### 담당 분야

general

### 작업 종류

implementation

### 최초 마감일

2026-09-21

### 목표와 완료 조건

화면 상태와 확인 결과를 기록한다.
"""


def member(login, **kwargs):
    return {"name": login, "login": login, "leader": False, "active": True,
            "roles": ["general"], "max_open_issues": 2, **kwargs}


def config():
    return {"repository": "suuuhululu/C-2", "timezone": "Asia/Seoul", "enabled": True,
            "members": [member("lead", leader=True), member("alice"), member("bob")]}


def issue(number=1, **kwargs):
    return {"number": number, "state": "open", "body": BODY, "user": {"login": "lead"},
            "assignees": [], "labels": [], "milestone": None, **kwargs}


class FakeAPI:
    def __init__(self, issues=None):
        self.issues = {i["number"]: deepcopy(i) for i in issues or [issue()]}
        self.comments = {n: [] for n in self.issues}
        self.labels = []
        self.next_id = 100
        self.writes = []
        self.permissions = {"lead": "write", "admin": "admin", "alice": "write", "bob": "write"}
        self.assignable = {"lead", "admin", "alice", "bob"}

    def comment(self, number, login, body, bot=False):
        self.next_id += 1
        comment = {"id": self.next_id, "body": body,
                   "user": {"login": login, "type": "Bot" if bot else "User"}}
        self.comments[number].append(comment)
        return deepcopy(comment)

    def pages(self, path, **query):
        if path == "/labels":
            return deepcopy(self.labels)
        if path == "/issues":
            return deepcopy(list(self.issues.values()))
        return deepcopy(self.comments[int(path.split('/')[2])])

    def call(self, method, path, payload=None):
        parts = path.strip("/").split("/")
        if method == "GET":
            if parts[0] == "collaborators":
                return {"permission": self.permissions.get(parts[1].lower(), "none")}
            if parts[0] == "assignees":
                if parts[1] not in self.assignable:
                    raise HTTPError(path, 404, "Not assignable", None, None)
                return None
            return deepcopy(self.issues[int(parts[1])])
        self.writes.append((method, path, deepcopy(payload)))
        if parts[0] == "labels":
            self.labels.append(deepcopy(payload))
        elif parts[1] == "comments":
            for comments in self.comments.values():
                for comment in comments:
                    if comment["id"] == int(parts[2]):
                        comment["body"] = payload["body"]
                        return deepcopy(comment)
            raise AssertionError("Unknown comment")
        elif parts[2] == "comments":
            return self.comment(int(parts[1]), BOT, payload["body"], bot=True)
        else:
            target = self.issues[int(parts[1])]
            if parts[2] == "assignees":
                target["assignees"] = [{"login": login} for login in payload["assignees"]]
            elif method == "POST" and parts[2] == "labels":
                names = {x["name"] for x in target["labels"]} | set(payload["labels"])
                target["labels"] = [{"name": name} for name in names]
            elif method == "DELETE" and parts[2] == "labels":
                target["labels"] = [x for x in target["labels"] if x["name"] != unquote(parts[3])]
            else:
                raise AssertionError((method, path, payload))
            return deepcopy(target)
        return deepcopy(payload)


class PolicyTests(unittest.TestCase):
    def test_config_rejects_email_invalid_duplicate_and_active_missing_login(self):
        for login in ("name@example.test", "rokey_seeun", "@alice", None, "lead"):
            with self.subTest(login=login), self.assertRaises(ValueError):
                value = config()
                value["members"][1]["login"] = login
                validate_config(value)

    def test_pending_accounts_are_valid_but_not_assignable(self):
        value = config()
        for m in value["members"]:
            m.update(login=None, active=False)
        validate_config(value)
        self.assertIsNone(select_assignee(value["members"], "general", Counter()))

    def test_balance_uses_load_and_respects_role_capacity_and_absence(self):
        members = [member("alice"), member("bob", roles=["ros"]), member("absent", active=False)]
        self.assertEqual(select_assignee(members, "general", Counter(alice=1)), "bob")
        self.assertEqual(select_assignee(members, "ros", Counter()), "bob")
        self.assertIsNone(select_assignee(members, "gripper", Counter()))
        self.assertIsNone(select_assignee(members, "general", Counter(alice=2, bob=2)))

    def test_invalid_dates_do_not_pass(self):
        for value in ("2026-02-30", "2026-9-15", "$(date)", "20260915"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_date(value)

    def test_korean_midnight_and_due_boundaries(self):
        tz = ZoneInfo("Asia/Seoul")
        today = datetime.fromisoformat("2026-09-15T15:00:00+00:00").astimezone(tz).date()
        state = initial_state(BODY)
        for due, expected in (("2026-09-15", "schedule:overdue"), ("2026-09-16", "schedule:due-soon"),
                              ("2026-09-17", "schedule:due-soon"), ("2026-09-18", None)):
            state["due"] = due
            self.assertEqual(schedule_labels(state, today), {expected} if expected else set())
        self.assertEqual(milestone_date(issue(milestone={"due_on": "2026-09-20T15:00:00Z"}), tz), date(2026, 9, 21))

    def test_invalid_initial_date_has_missing_label(self):
        state = initial_state(BODY.replace("2026-09-21", "미정"))
        self.assertEqual(schedule_labels(state, TODAY), {"schedule:missing"})

    def test_member_cannot_approve_or_change_someone_elses_status(self):
        state = initial_state(BODY)
        for command in ("/team approve-date 100", "/team start"):
            new, result = process_command(state, {"id": 1, "user": {"login": "alice"}, "body": command},
                                          leader=False, owner=False, today=TODAY)
            self.assertEqual(new, state)
            self.assertIn("거절", result)

    def test_cannot_start_second_issue(self):
        new, result = process_command(initial_state(BODY), {"id": 1, "user": {"login": "alice"}, "body": "/team start"},
                                      leader=False, owner=True, today=TODAY, busy=True)
        self.assertEqual(new["status"], "todo")
        self.assertIn("거절", result)

    def test_milestone_change_rechecked_at_approval(self):
        state = initial_state(BODY)
        request = {"id": 9, "user": {"login": "alice"}, "body": "/team request-date 2026-09-23 통합 점검 필요"}
        state, _ = process_command(state, request, leader=False, owner=True, today=TODAY)
        approve = {"id": 10, "user": {"login": "lead"}, "body": "/team approve-date 9"}
        state, result = process_command(state, approve, leader=True, owner=False, today=TODAY, milestone=date(2026, 9, 22))
        self.assertEqual(state["due"], "2026-09-21")
        self.assertIn("거절", result)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.cfg = config()

    def run_manager(self, today=TODAY):
        with patch("sys.stdout", new_callable=io.StringIO):
            Manager(self.api, self.cfg, today).run()

    def state(self, number=1):
        return saved_state(self.api.comments[number])[1]

    def labels(self, number=1):
        return {x["name"] for x in self.api.issues[number]["labels"]}

    def test_initial_assignment_and_replay_have_no_duplicate_writes(self):
        self.run_manager()
        self.assertEqual(self.api.issues[1]["assignees"], [{"login": "alice"}])
        writes = len(self.api.writes)
        self.run_manager()
        self.assertEqual(len(self.api.writes), writes)

    def test_balances_batch_of_issues_and_leaves_over_capacity_unassigned(self):
        self.api = FakeAPI([issue(n) for n in range(1, 8)])
        self.run_manager()
        counts = Counter(a["login"] for i in self.api.issues.values() for a in i["assignees"])
        self.assertEqual(counts, Counter(alice=2, bob=2, lead=2))
        self.assertIn("assignment:needed", self.labels(7))

    def test_existing_assignee_and_manual_labels_preserved(self):
        self.api.issues[1].update(assignees=[{"login": "bob"}], labels=[{"name": "priority:high"}])
        self.run_manager()
        self.assertEqual(self.api.issues[1]["assignees"], [{"login": "bob"}])
        self.assertIn("priority:high", self.labels())

    def test_non_collaborator_or_non_assignable_member_excluded(self):
        self.api.permissions["alice"] = "read"
        self.api.assignable.remove("bob")
        self.run_manager()
        self.assertEqual(self.api.issues[1]["assignees"], [{"login": "lead"}])

    def test_public_issue_and_forged_state_are_ignored(self):
        self.api.issues[1]["user"] = {"login": "outsider"}
        self.api.comment(1, "outsider", '<!-- c2-state:{"version":1} -->')
        self.run_manager()
        self.assertIsNone(self.state())
        self.assertEqual(self.api.issues[1]["assignees"], [])

    def test_outsider_commands_ignored_even_on_managed_issue(self):
        self.run_manager()
        self.api.comment(1, "outsider", "/team start")
        self.run_manager()
        self.assertEqual(self.state()["status"], "todo")

    def test_request_approval_and_replay(self):
        self.run_manager()
        request = self.api.comment(1, "alice", "/team request-date 2026-09-23 장비 예약 변경")
        self.run_manager()
        self.assertEqual(self.state()["due"], "2026-09-21")
        self.api.comment(1, "alice", f"/team approve-date {request['id']}")
        self.run_manager()
        self.assertEqual(self.state()["due"], "2026-09-21")
        self.api.comment(1, "lead", f"/team approve-date {request['id']}")
        self.run_manager()
        self.assertEqual(self.state()["due"], "2026-09-23")
        self.assertNotIn("schedule:change-requested", self.labels())
        writes = len(self.api.writes)
        self.run_manager()
        self.assertEqual(len(self.api.writes), writes)

    def test_superseded_request_cannot_be_approved_and_new_can_be_rejected(self):
        self.run_manager()
        old = self.api.comment(1, "alice", "/team request-date 2026-09-22 첫 번째 요청")
        new = self.api.comment(1, "alice", "/team request-date 2026-09-23 두 번째 요청")
        self.api.comment(1, "lead", f"/team approve-date {old['id']}")
        self.run_manager()
        self.assertEqual(self.state()["pending"]["id"], new["id"])
        self.api.comment(1, "lead", f"/team reject-date {new['id']} 범위를 먼저 줄이세요")
        self.run_manager()
        self.assertIsNone(self.state()["pending"])
        self.assertEqual(self.state()["due"], "2026-09-21")

    def test_body_edit_does_not_bypass_date_approval(self):
        self.run_manager()
        self.api.issues[1]["body"] = BODY.replace("2026-09-21", "2026-09-30")
        self.run_manager()
        self.assertEqual(self.state()["due"], "2026-09-21")

    def test_due_notifications_once_and_stale_labels_removed_after_approval(self):
        self.run_manager(date(2026, 9, 20))
        self.assertIn("schedule:due-soon", self.labels())
        self.run_manager(date(2026, 9, 22))
        self.assertIn("schedule:overdue", self.labels())
        self.assertNotIn("schedule:due-soon", self.labels())
        count = len(self.api.comments[1])
        self.run_manager(date(2026, 9, 22))
        self.assertEqual(len(self.api.comments[1]), count)
        request = self.api.comment(1, "alice", "/team request-date 2026-09-25 장비 점검 지연")
        self.api.comment(1, "lead", f"/team approve-date {request['id']}")
        self.run_manager(date(2026, 9, 22))
        self.assertNotIn("schedule:overdue", self.labels())

    def test_concurrent_commands_reconciled_and_work_limit_enforced(self):
        self.api = FakeAPI([issue(1, assignees=[{"login": "alice"}]), issue(2, assignees=[{"login": "alice"}])])
        self.api.comment(1, "alice", "/team start")
        self.api.comment(2, "alice", "/team start")
        self.run_manager()
        self.assertEqual(self.state(1)["status"], "doing")
        self.assertEqual(self.state(2)["status"], "todo")

    def test_closed_and_hardware_issues_not_automatically_closed(self):
        self.api.issues[1]["body"] = BODY.replace("implementation", "hardware-validation")
        self.run_manager()
        self.api.comment(1, "alice", "/team review")
        self.run_manager()
        self.assertEqual(self.api.issues[1]["state"], "open")
        self.api.issues[1]["state"] = "closed"
        self.run_manager()
        self.assertEqual(self.state()["status"], "done")
        self.api.comment(1, "alice", "/team start")
        self.run_manager()
        self.api.issues[1]["state"] = "open"
        self.run_manager()
        self.assertEqual(self.state()["status"], "todo")

    def test_paused_issue_untouched(self):
        self.api.issues[1]["labels"] = [{"name": "automation:paused"}]
        self.run_manager()
        self.assertIsNone(self.state())

    def test_global_disable_does_not_call_api(self):
        self.cfg["enabled"] = False
        with patch.object(self.api, "pages", side_effect=AssertionError("API must not be called")):
            self.run_manager()

    def test_comment_text_cannot_inject_commands_or_forge_bot_state(self):
        self.run_manager()
        text = '/team request-date 2026-09-23 $(touch /tmp/not-executed) --> @outsider <script>'
        self.api.comment(1, "alice", text)
        self.run_manager()
        self.assertIn("$(touch", self.state()["pending"]["reason"])
        dashboard, _ = saved_state(self.api.comments[1])
        self.assertNotIn("<script>", dashboard["body"])
        self.assertNotIn("@outsider", dashboard["body"])

    def test_failure_after_state_write_recovers_notice_without_reapplying(self):
        self.run_manager()
        self.api.comment(1, "alice", "/team start")
        original = self.api.call

        def flaky(method, path, payload=None):
            if method == "POST" and path.endswith("/comments") and "c2-notice:command" in payload["body"]:
                raise RuntimeError("simulated network interruption")
            return original(method, path, payload)

        with patch.object(self.api, "call", side_effect=flaky), self.assertRaises(RuntimeError):
            self.run_manager()
        self.assertEqual(self.state()["status"], "doing")
        self.run_manager()
        self.assertIn("status:doing", self.labels())
        self.assertEqual(sum("c2-notice:command" in c["body"] for c in self.api.comments[1]), 1)

    def test_pull_requests_excluded(self):
        self.api.issues[1]["pull_request"] = {"url": "unused"}
        self.run_manager()
        self.assertIsNone(self.state())


class RepositoryConfigTests(unittest.TestCase):
    def test_committed_config_is_valid(self):
        path = Path(__file__).resolve().parents[1] / ".github/team.json"
        validate_config(json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
